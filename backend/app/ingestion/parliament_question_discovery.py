import re
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


def discover_parliamentary_question_urls(
    listing_urls: list[str] | None = None,
    limit: int | None = None,
    year: int | None = None,
) -> list[str]:
    discovered: set[str] = set()
    discovered.update(discover_docsjson_urls(limit=limit, year=year))
    if limit and len(discovered) >= limit:
        return sorted(discovered)[:limit]
    for listing_url in listing_urls or DEFAULT_LISTING_URLS:
        html = fetch_page(listing_url)
        if not html:
            continue
        for url in urls_from_listing(listing_url, html, year=year):
            discovered.add(url)
            if limit and len(discovered) >= limit:
                return sorted(discovered)
    return sorted(discovered)


_DOCSJSON_PER_PAGE = 50
# Consecutive batches that add no new URLs before a doc type is abandoned.
# Protects against a source that repeats the same window regardless of offset.
_DOCSJSON_MAX_STALE_BATCHES = 2


def discover_docsjson_urls(limit: int | None = None, year: int | None = None) -> list[str]:
    urls: set[str] = set()
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
                urls.add(url)
                if limit and len(urls) >= limit:
                    return sorted(urls)
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
    return sorted(urls)


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
