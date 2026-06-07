import hashlib
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from app.ingestion.people_assembly import create_slug, extract_text, fetch_page, normalize_name


@dataclass
class ParsedPmgDocument:
    title: str
    document_type: str
    source_url: str
    publication_date: date | None
    raw_text: str
    archive_path: str


def archive_html(url: str, html: str, base_dir: str | Path = "data/raw/pmg") -> str:
    path = _archive_path(url, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)


def discover_pmg_document_urls(search_terms: list[str] | None = None, limit: int = 100) -> list[str]:
    terms = search_terms or ["Malema", "Ramaphosa", "Steenhuisen", "Gwarube", "Hlabisa", "Groenewald"]
    urls: set[str] = set()
    for term in terms:
        html = fetch_page(f"https://pmg.org.za/search/?q={term}")
        if not html:
            continue
        for match in re.findall(r"/committee-meeting/\d+/", html):
            urls.add(f"https://pmg.org.za{match}")
            if len(urls) >= limit:
                return sorted(urls)
    return sorted(urls)


def parse_document(url: str, html: str, archive_path: str) -> ParsedPmgDocument:
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    raw_text = extract_text(html)
    return ParsedPmgDocument(
        title=title,
        document_type="pmg_committee_meeting",
        source_url=url,
        publication_date=_extract_publication_date(soup, raw_text),
        raw_text=raw_text,
        archive_path=archive_path,
    )


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
