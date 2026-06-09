import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote_plus, urljoin, urlparse

from bs4 import BeautifulSoup

from app.ingestion.people_assembly import create_slug, extract_text, fetch_page, normalize_name
from app.services.archive_storage import get_archive_storage


@dataclass
class ParsedPmgDocument:
    title: str
    document_type: str
    source_url: str
    publication_date: date | None
    raw_text: str
    archive_path: str
    committee_name: str | None = None


def archive_html(url: str, html: str, base_dir: str | Path = "data/raw/pmg") -> str:
    path = _archive_path(url, base_dir)
    return get_archive_storage().write_text(str(path), html)


def discover_pmg_document_urls(
    search_terms: list[str] | None = None,
    limit: int = 100,
    year: int | None = None,
    committee: str | None = None,
) -> list[str]:
    terms = search_terms or ["Malema", "Ramaphosa", "Steenhuisen", "Gwarube", "Hlabisa", "Groenewald"]
    urls: set[str] = set()
    listing_urls = _pmg_listing_urls(year=year, committee=committee)
    for listing_url in listing_urls:
        html = fetch_page(listing_url)
        urls.update(_extract_pmg_urls(listing_url, html))
        if len(urls) >= limit:
            return sorted(urls)[:limit]
    for term in terms:
        query = quote_plus(f"{term} {committee or ''} {year or ''}".strip())
        html = fetch_page(f"https://pmg.org.za/search/?q={query}")
        urls.update(_extract_pmg_urls("https://pmg.org.za/search/", html))
        if len(urls) >= limit:
            return sorted(urls)[:limit]
    return sorted(urls)[:limit]


def parse_document(url: str, html: str, archive_path: str) -> ParsedPmgDocument:
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    raw_text = extract_text(html)
    return ParsedPmgDocument(
        title=title,
        document_type=_document_type(url, title, raw_text),
        source_url=url,
        publication_date=_extract_publication_date(soup, raw_text),
        raw_text=raw_text,
        archive_path=archive_path,
        committee_name=_extract_committee_name(soup, raw_text),
    )


def _pmg_listing_urls(year: int | None = None, committee: str | None = None) -> list[str]:
    base = [
        "https://pmg.org.za/committee-meetings/",
        "https://pmg.org.za/tabled-committee-reports/",
        "https://pmg.org.za/briefing/",
        "https://pmg.org.za/committees/",
    ]
    urls: list[str] = []
    for url in base:
        urls.append(url)
        for page in range(2, 6):
            urls.append(f"{url}?page={page}")
    if year:
        urls.extend([f"https://pmg.org.za/committee-meetings/?year={year}", f"https://pmg.org.za/search/?q={year}"])
    if committee:
        urls.append(f"https://pmg.org.za/search/?q={quote_plus(committee)}")
    return urls


def _extract_pmg_urls(base_url: str, html: str) -> set[str]:
    if not html:
        return set()
    soup = BeautifulSoup(html, "html.parser")
    urls: set[str] = set()
    patterns = (
        r"/committee-meeting/\d+/?",
        r"/committee-report/\d+/?",
        r"/tabled-committee-report/\d+/?",
        r"/briefing/\d+/?",
    )
    for link in soup.find_all("a", href=True):
        href = urljoin(base_url, str(link["href"]).strip())
        path = urlparse(href).path
        if any(re.fullmatch(pattern, path) for pattern in patterns):
            urls.add(f"https://pmg.org.za{path if path.endswith('/') else path + '/'}")
    for pattern in patterns:
        for match in re.findall(pattern, html):
            path = match if match.endswith("/") else f"{match}/"
            urls.add(f"https://pmg.org.za{path}")
    return urls


def _extract_title(soup: BeautifulSoup) -> str:
    h1 = soup.find("h1")
    if h1 and h1.get_text(strip=True):
        return h1.get_text(" ", strip=True)
    meta_title = soup.find("meta", attrs={"property": "og:title"}) or soup.find("meta", attrs={"name": "twitter:title"})
    if meta_title and meta_title.get("content"):
        return str(meta_title["content"]).replace("| PMG", "").strip()
    if soup.title:
        return soup.title.get_text(" ", strip=True).replace("| PMG", "").strip()
    raise ValueError("Could not extract PMG title.")


def _extract_publication_date(soup: BeautifulSoup, raw_text: str) -> date | None:
    for meta_name in ("article:published_time", "date", "DC.date"):
        meta = soup.find("meta", attrs={"property": meta_name}) or soup.find("meta", attrs={"name": meta_name})
        if meta and meta.get("content"):
            parsed = _parse_date(str(meta["content"]))
            if parsed:
                return parsed
    for meta in soup.find_all("meta"):
        content = str(meta.get("content", ""))
        if "meeting" in content.lower():
            match = re.search(r"\b(\d{1,2} [A-Z][a-z]+ \d{4})\b", content)
            if match:
                return _parse_date(match.group(1))
    match = re.search(r"\b(\d{1,2} [A-Z][a-z]+ \d{4})\b", raw_text)
    return _parse_date(match.group(1)) if match else None


def _extract_committee_name(soup: BeautifulSoup, raw_text: str) -> str | None:
    for selector in [".committee-name", ".committee", "a[href*='/committee/']", "a[href*='/committees/']"]:
        node = soup.select_one(selector)
        if node and node.get_text(strip=True):
            return " ".join(node.get_text(" ", strip=True).split())[:255]
    match = re.search(r"\b(Portfolio Committee on [A-Za-z ,&-]+|Standing Committee on [A-Za-z ,&-]+)\b", raw_text)
    if not match:
        return None
    return re.sub(r"\s+(meeting|briefing|report)\s*$", "", match.group(1), flags=re.IGNORECASE)[:255]


def _document_type(url: str, title: str, raw_text: str) -> str:
    path = urlparse(url).path.lower()
    if "committee-meeting" in path:
        return "PMG_COMMITTEE_MEETING"
    if "report" in path:
        return "PMG_REPORT"
    if "briefing" in path:
        return "PMG_BRIEFING"
    lowered = f"{url} {title} {raw_text[:500]}".lower()
    if "report" in lowered:
        return "PMG_REPORT"
    if "briefing" in lowered:
        return "PMG_BRIEFING"
    if "committee-meeting" in lowered or "meeting" in lowered:
        return "PMG_COMMITTEE_MEETING"
    return "PMG_DOCUMENT"


def _parse_date(value: str) -> date | None:
    value = value.strip()
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%d %B %Y"):
        try:
            return datetime.strptime(value[: len("2024-01-01")] if fmt == "%Y-%m-%d" else value, fmt).date()
        except ValueError:
            continue
    return None


def _archive_path(url: str, base_dir: str | Path) -> Path:
    parsed = urlparse(url)
    slug = create_slug(Path(parsed.path.rstrip("/")).name or parsed.netloc)
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return Path(base_dir) / f"{slug}-{digest}.html"

__all__ = ["create_slug", "extract_text", "fetch_page", "normalize_name"]
