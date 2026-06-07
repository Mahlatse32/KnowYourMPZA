import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pa.org.za/"


@dataclass
class ParsedCommitteeMembership:
    name: str
    slug: str
    role: str | None
    source_url: str
    start_date: date | None = None


@dataclass
class ParsedPeopleAssemblyProfile:
    full_name: str
    display_name: str
    slug: str
    party_name: str
    party_short_name: str
    profile_url: str
    photo_url: str | None
    committees: list[ParsedCommitteeMembership]


def fetch_page(url: str) -> str:
    try:
        response = requests.get(url, timeout=15, headers={"User-Agent": "KnowYourMPZA/0.1"})
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return ""


def discover_people_assembly_mp_urls(listing_urls: list[str] | None = None) -> list[str]:
    from app.config import settings

    urls = listing_urls or settings.people_assembly_listing_urls
    discovered: set[str] = set()
    for listing_url in urls:
        discovered.update(discover_people_assembly_urls_from_listing(listing_url))
    return sorted(discovered)


def discover_people_assembly_urls_from_listing(listing_url: str) -> list[str]:
    html = fetch_page(listing_url)
    if not html:
        return []
    soup = BeautifulSoup(html, "html.parser")
    urls: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = link["href"].strip()
        if not re.fullmatch(r"https?://[^/]+/person/[a-z0-9-]+/|/person/[a-z0-9-]+/", href):
            continue
        absolute = urljoin(listing_url, href)
        parsed = urlparse(absolute)
        if parsed.path in {"/person/all/"}:
            continue
        urls.add(f"{parsed.scheme}://{parsed.netloc}{parsed.path}")
    return sorted(urls)


def extract_text(html: str) -> str:
    if not html:
        return ""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(["script", "style", "noscript"]):
        tag.decompose()
    return " ".join(soup.get_text(" ").split())


def normalize_name(name: str) -> str:
    return " ".join(name.strip().split()).title()


def normalize_committee_name(name: str) -> str:
    name = " ".join(name.strip().split())
    name = re.sub(r"\s+([,.;:])", r"\1", name)
    name = re.sub(r"([,.;:]){2,}", r"\1", name)
    return name


def create_slug(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value).encode("ascii", "ignore").decode("ascii")
    return re.sub(r"[^a-z0-9]+", "-", normalized.lower()).strip("-")


def archive_html(url: str, html: str, base_dir: str | Path = "data/raw/people_assembly") -> str:
    path = _archive_path(url, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)


def parse_profile(url: str, html: str) -> ParsedPeopleAssemblyProfile:
    soup = BeautifulSoup(html, "html.parser")
    full_name = _extract_full_name(soup)
    display_name = _display_name(full_name)
    party_name, party_short_name = _extract_party(soup)
    photo_url = _extract_photo_url(soup)
    committees = _extract_current_committees(soup, url, party_name)
    return ParsedPeopleAssemblyProfile(
        full_name=full_name,
        display_name=display_name,
        slug=create_slug(full_name),
        party_name=party_name,
        party_short_name=party_short_name,
        profile_url=url,
        photo_url=photo_url,
        committees=committees,
    )


def _extract_full_name(soup: BeautifulSoup) -> str:
    first_name = _meta_content(soup, "profile:first_name")
    last_name = _meta_content(soup, "profile:last_name")
    if first_name and last_name:
        return normalize_name(f"{first_name} {last_name}")
    heading = soup.select_one(".mp-name") or soup.find("h1")
    if heading:
        return normalize_name(_strip_honorific(heading.get_text(" ", strip=True)))
    title = soup.find("title")
    if title:
        return normalize_name(title.get_text(" ", strip=True).split("::")[0])
    raise ValueError("Could not extract full name.")


def _display_name(full_name: str) -> str:
    parts = full_name.split()
    if len(parts) <= 2:
        return full_name
    return f"{parts[0]} {parts[-1]}"


def _extract_party(soup: BeautifulSoup) -> tuple[str, str]:
    for title in soup.select(".mp-block__title"):
        if "political party" not in title.get_text(" ", strip=True).lower():
            continue
        block = title.find_parent(class_="mp-block")
        link = block.find("a") if block else None
        if link:
            return _split_party(link.get_text(" ", strip=True))
    raise ValueError("Could not extract political party.")


def _split_party(value: str) -> tuple[str, str]:
    value = " ".join(value.split())
    match = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", value)
    if match:
        return match.group(1).strip(), match.group(2).strip()
    return value, create_slug(value).upper()[:20]


def _extract_photo_url(soup: BeautifulSoup) -> str | None:
    img = soup.select_one("img.mp-image")
    if img and img.get("src"):
        return urljoin(BASE_URL, img["src"])
    og_image = _meta_content(soup, "og:image")
    return og_image or None


def _extract_current_committees(soup: BeautifulSoup, profile_url: str, party_name: str) -> list[ParsedCommitteeMembership]:
    committees: list[ParsedCommitteeMembership] = []
    current = soup.select_one(".current-mp-positions")
    if not current:
        return committees
    for item in current.select(":scope > .text-link"):
        text_node = item.select_one(".text-link__text")
        link = text_node.find("a", href=True) if text_node else None
        if not text_node or not link:
            continue
        name = normalize_committee_name(link.get_text(" ", strip=True))
        if _is_party_or_constituency(name, party_name):
            continue
        role = _extract_role(text_node, name)
        date_text = item.select_one(".text-link__date")
        committees.append(
            ParsedCommitteeMembership(
                name=name,
                slug=create_slug(name),
                role=role,
                source_url=profile_url,
                start_date=_parse_since_date(date_text.get_text(" ", strip=True) if date_text else ""),
            )
        )
    return committees


def profile_is_current_mp(html: str) -> bool:
    text = extract_text(html).lower()
    current_signals = ["current positions:", "member of the national assembly", "member of parliament"]
    former_signals = ["former positions:", "former member", "resigned"]
    if any(signal in text for signal in current_signals):
        return True
    if any(signal in text for signal in former_signals):
        return False
    return True


def _extract_role(text_node, linked_name: str) -> str | None:
    text = text_node.get_text(" ", strip=True)
    role = text.split(" at ", 1)[0].strip()
    role = role.replace(linked_name, "").strip()
    return role or None


def _is_party_or_constituency(name: str, party_name: str) -> bool:
    lowered = name.lower()
    return party_name.lower() in lowered or "constituency office" in lowered or "election list" in lowered


def _parse_since_date(value: str) -> date | None:
    value = re.sub(r"^since\s+", "", value.strip(), flags=re.IGNORECASE)
    value = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", value)
    if not value:
        return None
    try:
        return datetime.strptime(value, "%d %B %Y").date()
    except ValueError:
        return None


def _strip_honorific(value: str) -> str:
    return re.sub(r"^(mr|ms|mrs|miss|dr|adv|prof|hon)\.?\s+", "", value.strip(), flags=re.IGNORECASE)


def _meta_content(soup: BeautifulSoup, key: str) -> str | None:
    meta = soup.find("meta", attrs={"property": key}) or soup.find("meta", attrs={"name": key})
    if meta and meta.get("content"):
        return str(meta["content"]).strip()
    return None


def _archive_path(url: str, base_dir: str | Path) -> Path:
    parsed = urlparse(url)
    slug = create_slug(Path(parsed.path.rstrip("/")).name or parsed.netloc)
    import hashlib

    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return Path(base_dir) / f"{slug}-{digest}.html"
