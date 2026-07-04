import re
import unicodedata
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

import requests
from bs4 import BeautifulSoup

BASE_URL = "https://www.pa.org.za/"
DEFAULT_MP_LISTING_URLS = [
    "https://www.pa.org.za/position/member/parliament/",
    "https://www.pa.org.za/person/all/",
]
DEFAULT_COMMITTEE_LISTING_URLS = [
    "https://www.pa.org.za/committees/",
    "https://www.pa.org.za/organisation/national-assembly/",
]
PARTY_NORMALIZATIONS = {
    "african national congress": ("African National Congress", "ANC"),
    "anc": ("African National Congress", "ANC"),
    "democratic alliance": ("Democratic Alliance", "DA"),
    "da": ("Democratic Alliance", "DA"),
    "economic freedom fighters": ("Economic Freedom Fighters", "EFF"),
    "eff": ("Economic Freedom Fighters", "EFF"),
    "umkhonto wesizwe": ("uMkhonto weSizwe", "MK"),
    "mk": ("uMkhonto weSizwe", "MK"),
    "inkatha freedom party": ("Inkatha Freedom Party", "IFP"),
    "ifp": ("Inkatha Freedom Party", "IFP"),
    "freedom front plus": ("Freedom Front Plus", "FF Plus"),
    "ff plus": ("Freedom Front Plus", "FF Plus"),
    "ff+": ("Freedom Front Plus", "FF Plus"),
    "actionsa": ("ActionSA", "ActionSA"),
    "good": ("GOOD", "GOOD"),
    "patriotic alliance": ("Patriotic Alliance", "PA"),
    "pa": ("Patriotic Alliance", "PA"),
    "african christian democratic party": ("African Christian Democratic Party", "ACDP"),
    "acdp": ("African Christian Democratic Party", "ACDP"),
    "united democratic movement": ("United Democratic Movement", "UDM"),
    "udm": ("United Democratic Movement", "UDM"),
    "african transformation movement": ("African Transformation Movement", "ATM"),
    "atm": ("African Transformation Movement", "ATM"),
    "rise mzansi": ("Rise Mzansi", "Rise Mzansi"),
    "build one south africa": ("Build One South Africa", "BOSA"),
    "bosa": ("Build One South Africa", "BOSA"),
    "al jama-ah": ("Al Jama-ah", "Al Jama-ah"),
    "al jamaah": ("Al Jama-ah", "Al Jama-ah"),
}
ROLE_NORMALIZATIONS = {
    "chair": "Chairperson",
    "chairperson": "Chairperson",
    "co-chairperson": "Chairperson",
    "member": "Member",
    "alternate member": "Alternate",
    "alternate": "Alternate",
    "whip": "Whip",
    "minister": "Minister",
    "deputy minister": "Deputy Minister",
}
REQUEST_HEADERS = {
    "User-Agent": "KnowYourMPZA/1.0 (+https://github.com/Mahlatse32/KnowYourMPZA; civic data ingestion)",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-ZA,en;q=0.9",
}


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
    source_status: str = "UNKNOWN"
    is_active: bool = True


@dataclass
class ParsedCommitteePage:
    name: str
    slug: str
    source_url: str
    members: list[ParsedCommitteeMembership]


@dataclass
class FetchOutcome:
    """Safe, structured result of a single source fetch.

    Carries diagnostic metadata for failures without ever exposing the full
    response body, credentials, query strings, or paths. Only the bare host
    (``final_domain``), HTTP status code, response content type, and a coarse
    ``error_kind`` are retained.
    """

    text: str
    ok: bool
    status_code: int | None = None
    error_kind: str | None = None  # http_error | timeout | connection_error | request_error | empty_body
    content_type: str | None = None
    final_domain: str | None = None


# Diagnostics from the most recent fetch_page() call, keyed by URL so callers
# can attribute a failure to the request they just made. Single-threaded
# ingestion scripts only; never holds response bodies or secrets.
_LAST_FETCH_OUTCOME: dict[str, FetchOutcome] = {}

# Map fetch error kinds to the error "type" the resilience layer recognizes as
# a source-access (transient/access) failure rather than a parse/DB failure.
_ERROR_KIND_TO_TYPE = {
    "http_error": "HTTPError",
    "timeout": "Timeout",
    "connection_error": "ConnectionError",
    "request_error": "RequestException",
    "empty_body": "EmptyResponse",
}


def _domain_only(url: str) -> str | None:
    netloc = urlparse(url).netloc.lower()
    # netloc may carry credentials/port (user:pass@host:port); keep host only.
    host = netloc.rsplit("@", 1)[-1].split(":", 1)[0]
    return host or None


def fetch_page_detailed(url: str) -> FetchOutcome:
    """Fetch a page and return a structured outcome with safe diagnostics.

    Never raises and never returns response bodies on failure. On any error it
    records the coarse failure kind, HTTP status (if any), response content
    type, and the bare host, so a systemic source-access block can be told
    apart from a parse error — without bypassing the source or logging HTML.
    """
    domain = _domain_only(url)
    try:
        response = requests.get(url, timeout=30, headers=REQUEST_HEADERS)
    except requests.Timeout:
        return _record(url, FetchOutcome("", False, None, "timeout", None, domain))
    except requests.ConnectionError:
        return _record(url, FetchOutcome("", False, None, "connection_error", None, domain))
    except requests.RequestException:
        return _record(url, FetchOutcome("", False, None, "request_error", None, domain))

    domain = _domain_only(response.url) or domain
    content_type = response.headers.get("Content-Type")
    status_code = response.status_code
    try:
        response.raise_for_status()
    except requests.HTTPError:
        return _record(url, FetchOutcome("", False, status_code, "http_error", content_type, domain))
    if not response.text:
        return _record(url, FetchOutcome("", False, status_code, "empty_body", content_type, domain))
    return _record(url, FetchOutcome(response.text, True, status_code, None, content_type, domain))


def _record(url: str, outcome: FetchOutcome) -> FetchOutcome:
    _LAST_FETCH_OUTCOME[url] = outcome
    return outcome


def last_fetch_outcome(url: str) -> FetchOutcome | None:
    """Return the recorded diagnostics for the most recent fetch of ``url``."""
    return _LAST_FETCH_OUTCOME.get(url)


def describe_fetch_failure(url: str) -> tuple[str, str]:
    """Return ``(error_type, safe_message)`` for a failed fetch of ``url``.

    The message names the failure kind, HTTP status, content type, and bare
    host only — no credentials, query strings, paths, or response body. Falls
    back to a generic message when no diagnostics were recorded (e.g. the
    fetch function was monkeypatched in tests).
    """
    outcome = _LAST_FETCH_OUTCOME.get(url)
    if outcome is None or outcome.ok:
        return "SourceAccessError", "Fetch failed or returned empty HTML."
    error_type = _ERROR_KIND_TO_TYPE.get(outcome.error_kind or "", "SourceAccessError")
    domain = outcome.final_domain or "the source"
    parts: list[str] = []
    if outcome.error_kind == "http_error":
        parts.append(f"HTTP {outcome.status_code}" if outcome.status_code else "HTTP error")
    elif outcome.error_kind == "timeout":
        parts.append("request timed out")
    elif outcome.error_kind == "connection_error":
        parts.append("connection failed")
    elif outcome.error_kind == "empty_body":
        parts.append(f"empty body (HTTP {outcome.status_code})" if outcome.status_code else "empty body")
    else:
        parts.append("request failed")
    if outcome.content_type and outcome.error_kind in {"http_error", "empty_body"}:
        parts.append(f"content-type {outcome.content_type}")
    return error_type, f"Source fetch failed from {domain}: {', '.join(parts)}."


def fetch_page(url: str) -> str:
    """Fetch a page, returning its text or ``""`` on any failure.

    Backwards-compatible string contract. Failure diagnostics are recorded and
    retrievable via :func:`last_fetch_outcome` / :func:`describe_fetch_failure`.
    """
    return fetch_page_detailed(url).text


def normalize_people_assembly_url(url: str) -> str:
    absolute = urljoin(BASE_URL, str(url).strip())
    parsed = urlparse(absolute)
    path = re.sub(r"/+", "/", parsed.path or "/")
    if not path.endswith("/"):
        path = f"{path}/"
    query_pairs = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True) if key.lower() in {"page"}]
    query = urlencode(sorted(query_pairs))
    return urlunparse(("https", parsed.netloc.lower(), path, "", query, ""))


def discover_people_assembly_listing_pages(listing_urls: list[str] | None = None) -> list[str]:
    from app.config import settings

    seeds = listing_urls or settings.people_assembly_listing_urls or DEFAULT_MP_LISTING_URLS
    pages: set[str] = set()
    seen: set[str] = set()
    queue = [normalize_people_assembly_url(url) for url in seeds]
    while queue:
        listing_url = queue.pop(0)
        if listing_url in seen:
            continue
        seen.add(listing_url)
        pages.add(listing_url)
        html = fetch_page(listing_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            text = link.get_text(" ", strip=True).lower()
            href = str(link["href"]).strip()
            candidate = normalize_people_assembly_url(urljoin(listing_url, href))
            if candidate in seen or candidate in queue:
                continue
            parsed = urlparse(candidate)
            is_same_listing = parsed.path == urlparse(listing_url).path and "page=" in parsed.query
            is_next = text in {"next", "next page", "older"} or "next" in link.get("class", [])
            if is_same_listing or is_next:
                queue.append(candidate)
    return sorted(pages)


def discover_people_assembly_mp_urls(listing_urls: list[str] | None = None) -> list[str]:
    discovered: set[str] = set()
    for listing_url in discover_people_assembly_listing_pages(listing_urls):
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
        absolute = normalize_people_assembly_url(urljoin(listing_url, href))
        parsed = urlparse(absolute)
        if not re.fullmatch(r"/person/[a-z0-9-]+/", parsed.path):
            continue
        if parsed.path in {"/person/all/"}:
            continue
        urls.add(absolute)
    return sorted(urls)


def discover_people_assembly_committee_urls(listing_urls: list[str] | None = None) -> list[str]:
    urls: set[str] = set()
    seeds = listing_urls or DEFAULT_COMMITTEE_LISTING_URLS
    for listing_url in seeds:
        html = fetch_page(listing_url)
        if not html:
            continue
        soup = BeautifulSoup(html, "html.parser")
        for link in soup.find_all("a", href=True):
            href = str(link["href"]).strip()
            absolute = normalize_people_assembly_url(urljoin(listing_url, href))
            path = urlparse(absolute).path
            if re.fullmatch(r"/committee/[a-z0-9-]+/", path) or re.fullmatch(r"/organisation/[a-z0-9-]+/", path):
                if not any(skip in path for skip in {"/person/", "/place/", "/messages/", "/party/"}):
                    if path in {"/organisation/all/", "/organisation/is/", "/organisation/national-assembly/", "/organisation/ncop/"}:
                        continue
                    urls.add(absolute)
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
    name = re.sub(r"^(committee|portfolio committee|standing committee|select committee|joint committee)\s+on\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"^(committee|portfolio committee|standing committee|select committee|joint committee)\s+for\s+", "", name, flags=re.IGNORECASE)
    name = re.sub(r"\s+([,.;:])", r"\1", name)
    name = re.sub(r"([,.;:]){2,}", r"\1", name)
    return name.strip(" -,.;:")


def normalize_party_name(value: str) -> tuple[str, str]:
    clean = re.sub(r"\s+", " ", value.replace("\u00a0", " ")).strip(" .,-")
    if not clean:
        return "Unknown", "UNKNOWN"
    match = re.match(r"(.+?)\s*\(([^)]+)\)\s*$", clean)
    if match:
        long_name, short_name = match.group(1).strip(), match.group(2).strip()
    else:
        long_name, short_name = clean, clean
    key = re.sub(r"[^a-z0-9+]+", " ", short_name.lower()).strip()
    normalized = PARTY_NORMALIZATIONS.get(key) or PARTY_NORMALIZATIONS.get(re.sub(r"[^a-z0-9+]+", " ", long_name.lower()).strip())
    if normalized:
        return normalized
    generated_short = short_name if len(short_name) <= 20 and short_name.isupper() else create_slug(short_name).upper()[:20]
    return " ".join(long_name.split()), generated_short


def normalize_role(value: str | None) -> str:
    if not value:
        return "Member"
    clean = " ".join(value.replace(":", " ").split()).strip(" .,-")
    lowered = clean.lower()
    for key, normalized in ROLE_NORMALIZATIONS.items():
        if key in lowered:
            return normalized
    return "Unknown" if not clean else clean[:100]


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
    source_status = profile_source_status(html, url)
    return ParsedPeopleAssemblyProfile(
        full_name=full_name,
        display_name=display_name,
        slug=create_slug(full_name),
        party_name=party_name,
        party_short_name=party_short_name,
        profile_url=url,
        photo_url=photo_url,
        committees=committees,
        source_status=source_status,
        is_active=source_status == "CURRENT",
    )


def parse_committee_page(url: str, html: str) -> ParsedCommitteePage:
    soup = BeautifulSoup(html, "html.parser")
    heading = soup.select_one("h1") or soup.select_one(".committee-name") or soup.find("title")
    raw_name = heading.get_text(" ", strip=True).split("::")[0] if heading else Path(urlparse(url).path.rstrip("/")).name
    name = normalize_committee_name(raw_name)
    members: list[ParsedCommitteeMembership] = []
    seen: set[tuple[str, str]] = set()
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        absolute = normalize_people_assembly_url(urljoin(url, href))
        if not re.fullmatch(r"/person/[a-z0-9-]+/", urlparse(absolute).path):
            continue
        member_name = normalize_name(_strip_honorific(link.get_text(" ", strip=True)))
        if not member_name or member_name.lower() in {"profile", "person"}:
            continue
        role = normalize_role(_nearby_role(link))
        key = (member_name.lower(), role)
        if key in seen:
            continue
        seen.add(key)
        members.append(
            ParsedCommitteeMembership(
                name=member_name,
                slug=create_slug(member_name),
                role=role,
                source_url=url,
            )
        )
    return ParsedCommitteePage(name=name, slug=create_slug(name), source_url=url, members=members)


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
            return normalize_party_name(link.get_text(" ", strip=True))
    raise ValueError("Could not extract political party.")


def _split_party(value: str) -> tuple[str, str]:
    return normalize_party_name(value)


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
        role = normalize_role(_extract_role(text_node, name))
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


def profile_source_status(html: str, url: str | None = None) -> str:
    text = extract_text(html).lower()
    current_signals = ["current positions:", "member of the national assembly", "member of parliament"]
    former_signals = ["former positions:", "former member", "resigned", "deceased", "not a current", "archived"]
    if any(signal in text for signal in current_signals):
        return "CURRENT"
    if any(signal in text for signal in former_signals):
        return "FORMER"
    if url and "/position/member/parliament/" in url:
        return "CURRENT"
    return "UNKNOWN"


def profile_is_current_mp(html: str) -> bool:
    return profile_source_status(html) == "CURRENT"


def _extract_role(text_node, linked_name: str) -> str | None:
    text = text_node.get_text(" ", strip=True)
    role = text.split(" at ", 1)[0].strip()
    role = role.replace(linked_name, "").strip()
    return role or None


def _nearby_role(link) -> str | None:
    container = link.find_parent(["li", "tr", "div", "p"]) or link.parent
    if not container:
        return None
    text = container.get_text(" ", strip=True)
    text = text.replace(link.get_text(" ", strip=True), " ")
    role_match = re.search(r"\b(chairperson|chair|alternate member|alternate|whip|minister|deputy minister|member)\b", text, flags=re.IGNORECASE)
    return role_match.group(1) if role_match else None


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
