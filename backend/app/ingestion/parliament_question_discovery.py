import re
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup

from app.ingestion.parliament_questions import fetch_page
from app.ingestion.pdf_utils import is_pdf_url

DEFAULT_LISTING_URLS = [
    "https://www.parliament.gov.za/questions-and-replies",
    "https://www.parliament.gov.za/question-papers",
    "https://www.parliament.gov.za/question-replies-na",
    "https://archive.parliament.gov.za/handle/123456789/14",
]

DOC_TYPES = ["EXE_RQ_NA", "EXE_R_NCOP", "HAN_R_NA", "QUEST_PAP"]

# Human-readable labels for the docsjson document types, used to build titles
# from explicit source metadata. Reply types carry the reply date.
_DOC_TYPE_LABELS = {
    "EXE_RQ_NA": ("Written question reply", "National Assembly", "answered_date"),
    "EXE_R_NCOP": ("Written question reply", "NCOP", "answered_date"),
    "HAN_R_NA": ("Question reply (Hansard)", "National Assembly", "answered_date"),
    "QUEST_PAP": ("Question paper", None, "asked_date"),
}


def discover_parliamentary_question_urls(
    listing_urls: list[str] | None = None,
    limit: int | None = None,
    year: int | None = None,
) -> list[str]:
    urls, _ = discover_parliamentary_question_records(
        listing_urls=listing_urls, limit=limit, year=year
    )
    return urls


def discover_parliamentary_question_records(
    listing_urls: list[str] | None = None,
    limit: int | None = None,
    year: int | None = None,
) -> tuple[list[str], dict[str, dict]]:
    """Discover question document URLs plus per-URL metadata.

    Returns (sorted urls, metadata_by_url). Metadata comes only from explicit
    docsjson record fields (name/date/type); listing-page URLs have no
    metadata and simply map to an absent entry.
    """
    discovered: set[str] = set()
    metadata_by_url: dict[str, dict] = {}
    for url, meta in _docsjson_url_metadata(limit=limit, year=year).items():
        discovered.add(url)
        if meta:
            metadata_by_url[url] = meta
    if limit and len(discovered) >= limit:
        urls = sorted(discovered)[:limit]
        return urls, {url: metadata_by_url[url] for url in urls if url in metadata_by_url}
    for listing_url in listing_urls or DEFAULT_LISTING_URLS:
        html = fetch_page(listing_url)
        if not html:
            continue
        for url in urls_from_listing(listing_url, html, year=year):
            discovered.add(url)
            if limit and len(discovered) >= limit:
                urls = sorted(discovered)
                return urls, metadata_by_url
    return sorted(discovered), metadata_by_url


_DOCSJSON_PER_PAGE = 50
# Consecutive batches that add no new URLs before a doc type is abandoned.
# Protects against a source that repeats the same window regardless of offset.
_DOCSJSON_MAX_STALE_BATCHES = 2


def discover_docsjson_urls(limit: int | None = None, year: int | None = None) -> list[str]:
    return sorted(_docsjson_url_metadata(limit=limit, year=year))


def _docsjson_url_metadata(limit: int | None = None, year: int | None = None) -> dict[str, dict]:
    urls: dict[str, dict] = {}
    for doc_type in DOC_TYPES:
        offset = 0
        stale_batches = 0
        max_requests = 20 if limit is None else (limit // _DOCSJSON_PER_PAGE) * 3 + 10
        for _ in range(max_requests):
            records = _docsjson_records(doc_type, offset=offset, per_page=_DOCSJSON_PER_PAGE)
            if not records:
                break
            before = len(urls)
            for record in records:
                url = _record_file_url(record)
                if not url:
                    continue
                haystack = f"{record.get('name', '')} {record.get('date', '')} {url}"
                if year and str(year) not in haystack:
                    continue
                urls.setdefault(url, question_metadata_from_record(record))
                if limit and len(urls) >= limit:
                    return urls
            # The docsjson endpoint ignores the documented `page` parameter and
            # only advances via `offset`. If a window adds nothing new, the
            # source is repeating itself (or everything normalized to known
            # URLs) — give up on this doc type instead of looping forever.
            if len(urls) == before:
                stale_batches += 1
                if stale_batches >= _DOCSJSON_MAX_STALE_BATCHES:
                    break
            else:
                stale_batches = 0
            if len(records) < _DOCSJSON_PER_PAGE:
                break
            offset += len(records)
    return urls


def question_metadata_from_record(record: dict) -> dict:
    """Extract presentation metadata from explicit docsjson record fields.

    Only source-provided values are used: the original filename (which
    carries the question number and often a date), the record date (which is
    sometimes corrupt and must pass a sanity window), and the document type.
    Anything that cannot be validated is omitted rather than guessed.
    """
    name = str(record.get("name") or "").strip()
    stem = re.sub(r"\.[A-Za-z0-9]{1,5}$", "", name)
    doc_type = str(record.get("type") or "").strip().upper()
    label, house, date_field = _DOC_TYPE_LABELS.get(doc_type, ("Parliamentary question document", None, "asked_date"))

    number = None
    number_match = re.match(r"^R?([A-Z]{1,4}\d{1,6})\b", stem.upper())
    if number_match:
        number = number_match.group(1)

    doc_date = _valid_question_date(str(record.get("date") or "")) or _date_from_name(stem)

    title_parts = [label]
    if number:
        title_parts.append(number)
    if house:
        title_parts.append(f"({house})")
    if doc_date:
        title_parts.append(f"— {doc_date.isoformat()}")
    title = " ".join(title_parts) if (number or doc_date) else (stem or None)

    metadata: dict = {}
    if title:
        metadata["title"] = title
    if number:
        metadata["question_number"] = number
    if doc_date:
        metadata[date_field] = doc_date
    # A reply document type means the question was answered — explicit source
    # semantics, not inference.
    if date_field == "answered_date":
        metadata["status"] = "ANSWERED"
    return metadata


_QUESTION_DATE_MIN_YEAR = 1994


def _valid_question_date(value: str) -> date | None:
    """The docsjson `date` field is sometimes corrupt (question numbers leak
    into it, e.g. "5127-10-10"); accept only ISO dates within a sane window."""
    try:
        parsed = datetime.strptime(value.strip()[:10], "%Y-%m-%d").date()
    except ValueError:
        return None
    if _QUESTION_DATE_MIN_YEAR <= parsed.year <= datetime.now().year + 1:
        return parsed
    return None


def _date_from_name(stem: str) -> date | None:
    match = re.search(r"(\d{4}-\d{2}-\d{2})", stem)
    if not match:
        return None
    return _valid_question_date(match.group(1))


def _docsjson_records(doc_type: str, offset: int, per_page: int) -> list[dict]:
    try:
        response = requests.get(
            f"https://www.parliament.gov.za/docsjson/{doc_type}",
            params={
                "queries[type]": doc_type,
                "offset": offset,
                "perPage": per_page,
                "sorts[date]": -1,
            },
            timeout=20,
            headers={"User-Agent": "KnowYourMPZA/0.1"},
        )
        response.raise_for_status()
        payload = response.json()
    except Exception:
        return []
    records = payload.get("records", [])
    return records if isinstance(records, list) else []


def _record_file_url(record: dict) -> str | None:
    location = str(record.get("file_location") or "").replace("\\/", "/").strip()
    if not location:
        return None
    if location.startswith("http"):
        return _normalize_url(location)
    if "/Docs/" in location:
        return _normalize_url(urljoin("https://www.parliament.gov.za/storage/app/media", location))
    return _normalize_url(urljoin("https://www.parliament.gov.za/storage/app/media/Docs/", location))


def urls_from_listing(listing_url: str, html: str, year: int | None = None) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    urls: set[str] = set()
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        text = link.get_text(" ", strip=True)
        absolute = _safe_urljoin(listing_url, href)
        if not absolute:
            continue
        if not _looks_question_related(absolute, text):
            continue
        if year and str(year) not in absolute and str(year) not in text:
            continue
        urls.add(_normalize_url(absolute))

    for match in re.findall(r"(?:https?://[^\s\"']+|/storage/app/media/[^\s\"']+|/handle/\d+/\d+)", html):
        absolute = _safe_urljoin(listing_url, match)
        if not absolute:
            continue
        if not _looks_question_related(absolute, match):
            continue
        if year and str(year) not in absolute:
            continue
        urls.add(_normalize_url(absolute))
    return sorted(urls)


def _looks_question_related(url: str, text: str) -> bool:
    lowered = f"{url} {text}".lower()
    if is_pdf_url(url) and any(token in lowered for token in ["question", "rq_", "exe_rq", "quest_pap", "rnw", "rno", "qne", "qce"]):
        return True
    return any(
        token in lowered
        for token in [
            "questions-and-replies",
            "question-papers",
            "question-replies",
            "question paper",
            "question reply",
            "parliamentary-question",
            "archive.parliament.gov.za/handle",
            "archive.parliament.gov.za/items",
            "exe_rq_na",
            "quest_pap",
        ]
    )


def _normalize_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}{parsed.path}"


def _safe_urljoin(base_url: str, value: str) -> str | None:
    try:
        return urljoin(base_url, value)
    except ValueError:
        return None
