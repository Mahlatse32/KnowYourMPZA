"""Parse bill listings from parliament.gov.za and pmg.org.za."""
import logging
import re
import time
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PARLIAMENT_BILLS_URL = "https://www.parliament.gov.za/bills"
_PMG_BILLS_URL = "https://pmg.org.za/bills/"
_PMG_API_BILLS_URL = "https://api.pmg.org.za/bill/"
_REQUEST_TIMEOUT_SECONDS = 45
_REQUEST_RETRIES = 3
_REQUEST_BACKOFF_SECONDS = 1.0

BILL_STATUSES = {
    "introduced": "introduced",
    "passed": "passed",
    "assented": "assented",
    "rejected": "rejected",
    "withdrawn": "withdrawn",
    "lapsed": "lapsed",
    "signed": "assented",
    "act": "assented",
}


def _is_retryable_http_error(exc: requests.HTTPError) -> bool:
    response = exc.response
    return response is not None and response.status_code in {429, 500, 502, 503, 504}


def fetch_page(
    url: str,
    timeout: int = _REQUEST_TIMEOUT_SECONDS,
    retries: int = _REQUEST_RETRIES,
    backoff_seconds: float = _REQUEST_BACKOFF_SECONDS,
) -> str:
    """Fetch a page with bounded retry/backoff for transient PMG API failures."""
    attempts = max(1, retries)
    for attempt in range(1, attempts + 1):
        try:
            resp = requests.get(url, timeout=timeout, headers={"User-Agent": "KnowYourMPZA/1.0"})
            resp.raise_for_status()
            return resp.text
        except (requests.Timeout, requests.ConnectionError) as exc:
            retryable = True
            last_exc = exc
        except requests.HTTPError as exc:
            retryable = _is_retryable_http_error(exc)
            last_exc = exc

        if not retryable or attempt == attempts:
            raise last_exc
        delay = backoff_seconds * (2 ** (attempt - 1))
        logger.warning("Retrying %s after %s (%d/%d)", url, last_exc, attempt, attempts)
        time.sleep(delay)

    raise RuntimeError("unreachable fetch retry state")


def _normalize_status(raw: str) -> str:
    if not raw:
        return "unknown"
    key = raw.strip().lower()
    for k, v in BILL_STATUSES.items():
        if k in key:
            return v
    return "unknown"


def _parse_year(text: str) -> int | None:
    m = re.search(r"\b(19|20)\d{2}\b", text)
    return int(m.group()) if m else None


def _parse_bill_number(text: str) -> str | None:
    m = re.search(r"\bB\s*(\d+[A-Z]?)\b", text, re.IGNORECASE)
    return m.group().strip() if m else None


def parse_pmg_bills(html: str, source_url: str = _PMG_BILLS_URL) -> list[dict[str, Any]]:
    """Parse the PMG bills index page into a list of bill dicts."""
    soup = BeautifulSoup(html, "html.parser")
    bills: list[dict[str, Any]] = []

    for row in soup.select("table tr"):
        cells = row.find_all(["td", "th"])
        if len(cells) < 2:
            continue
        link_tag = cells[0].find("a") if cells else None
        if not link_tag:
            continue
        title = link_tag.get_text(strip=True)
        href = link_tag.get("href", "")
        if href and not href.startswith("http"):
            href = "https://pmg.org.za" + href
        status_text = cells[-1].get_text(strip=True) if len(cells) > 1 else ""
        year_text = cells[1].get_text(strip=True) if len(cells) > 1 else ""
        if not title:
            continue
        bills.append(
            {
                "title": title,
                "short_title": None,
                "bill_number": _parse_bill_number(title),
                "year": _parse_year(year_text or title),
                "house": None,
                "status": _normalize_status(status_text),
                "source_url": href or source_url,
                "source_type": "pmg",
                "events": [],
            }
        )
    return bills


def parse_parliament_bills(html: str, source_url: str = _PARLIAMENT_BILLS_URL) -> list[dict[str, Any]]:
    """Parse the parliament.gov.za bills page into a list of bill dicts."""
    soup = BeautifulSoup(html, "html.parser")
    bills: list[dict[str, Any]] = []

    for link_tag in soup.select("a[href*='/bill']"):
        title = link_tag.get_text(strip=True)
        if not title or len(title) < 5:
            continue
        href = link_tag.get("href", "")
        if href and not href.startswith("http"):
            href = "https://www.parliament.gov.za" + href

        parent_text = ""
        parent = link_tag.parent
        if parent:
            parent_text = parent.get_text(" ", strip=True)

        bills.append(
            {
                "title": title,
                "short_title": None,
                "bill_number": _parse_bill_number(title),
                "year": _parse_year(parent_text or title),
                "house": _extract_house(parent_text),
                "status": _normalize_status(parent_text),
                "source_url": href or source_url,
                "source_type": "parliament",
                "events": [],
            }
        )
    return bills


# ---------------------------------------------------------------------------
# PMG JSON API (the HTML pages at pmg.org.za/bills/ are JS-rendered shells,
# so the documented public API at api.pmg.org.za is the reliable source).
# ---------------------------------------------------------------------------

def pmg_api_page_url(page: int) -> str:
    return f"{_PMG_API_BILLS_URL}?page={page}"


def bill_detail_api_url(source_url: str | None) -> str | None:
    """Map a stored human bill URL (https://pmg.org.za/bill/<id>/) to its API detail URL."""
    if not source_url:
        return None
    m = re.search(r"pmg\.org\.za/bill/(\d+)", source_url)
    if not m:
        return None
    return f"https://api.pmg.org.za/bill/{m.group(1)}/"


def _iso_to_date(value) -> Any:
    if not value:
        return None
    from datetime import date as _date

    try:
        return _date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_pmg_api_bill(item: dict) -> dict[str, Any]:
    """Map one PMG API bill object to our bill dict shape."""
    status_obj = item.get("status") or {}
    status_name = status_obj.get("name", "") if isinstance(status_obj, dict) else str(status_obj or "")
    bill_id = item.get("id")
    source_url = f"https://pmg.org.za/bill/{bill_id}/" if bill_id else None
    # Drafts have number=None and share the placeholder code "X-<year>".
    # Using that as bill_number would collapse distinct drafts under the
    # uq_bill_number_year_house constraint, so leave it None instead.
    bill_number = item.get("code") if item.get("number") is not None else None
    return {
        "title": item.get("title") or "Untitled bill",
        "short_title": None,
        "bill_number": bill_number,
        "year": item.get("year"),
        "house": None,
        "status": _normalize_status(status_name),
        "introduced_date": _iso_to_date(item.get("date_of_introduction")),
        "assented_date": _iso_to_date(item.get("date_of_assent")),
        "act_number": item.get("act_name"),
        "source_url": source_url,
        "source_type": "pmg-api",
        "events": parse_pmg_api_bill_events(item, source_url),
    }


def parse_pmg_api_bills(payload: dict) -> list[dict[str, Any]]:
    """Parse one page of the PMG bills API listing."""
    return [parse_pmg_api_bill(item) for item in payload.get("results", [])]


def parse_pmg_api_bill_events(item: dict, source_url: str | None = None) -> list[dict[str, Any]]:
    """Map the events list of a PMG API bill detail object to bill_event dicts."""
    if source_url is None and item.get("id"):
        source_url = f"https://pmg.org.za/bill/{item['id']}/"
    events: list[dict[str, Any]] = []
    for event in item.get("events") or []:
        events.append(
            {
                "event_type": event.get("type") or "unknown",
                "event_date": _iso_to_date(event.get("date")),
                "description": (event.get("title") or "")[:1000] or None,
                "source_url": source_url,
            }
        )
    return events


EVENT_TYPE_KEYWORDS = [
    ("introduced", "introduced"),
    ("first reading", "first_reading"),
    ("second reading", "second_reading"),
    ("third reading", "third_reading"),
    ("committee", "committee_referral"),
    ("ncop", "ncop_concurrence"),
    ("passed", "passed"),
    ("assented", "assented"),
    ("signed", "assented"),
    ("withdrawn", "withdrawn"),
    ("lapsed", "lapsed"),
]


def _classify_event(text: str) -> str:
    low = text.lower()
    for keyword, event_type in EVENT_TYPE_KEYWORDS:
        if keyword in low:
            return event_type
    return "unknown"


def _parse_event_date(text: str):
    from datetime import datetime as _dt

    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if m:
        try:
            return _dt.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
        except ValueError:
            pass
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m2:
        from datetime import date as _date

        try:
            return _date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            pass
    return None


def parse_bill_history(html: str, source_url: str) -> list[dict[str, Any]]:
    """Parse a single bill detail page into a list of lifecycle event dicts.

    Looks for table rows and list items that contain a date plus a description.
    Rows without a recognisable date are kept with event_date=None rather than
    dropped, so the limitation is modelled instead of data being invented.
    """
    soup = BeautifulSoup(html, "html.parser")
    events: list[dict[str, Any]] = []
    seen: set[tuple] = set()

    candidates: list[str] = []
    for row in soup.select("table tr"):
        text = row.get_text(" ", strip=True)
        if text:
            candidates.append(text)
    for li in soup.select("ul li, ol li"):
        text = li.get_text(" ", strip=True)
        if text:
            candidates.append(text)

    for text in candidates:
        event_type = _classify_event(text)
        if event_type == "unknown" and not _parse_event_date(text):
            continue
        event_date = _parse_event_date(text)
        key = (event_type, event_date, text[:100])
        if key in seen:
            continue
        seen.add(key)
        events.append(
            {
                "event_type": event_type,
                "event_date": event_date,
                "description": text[:1000],
                "source_url": source_url,
            }
        )
    return events


def _extract_house(text: str) -> str | None:
    text_lower = text.lower()
    if "national assembly" in text_lower:
        return "National Assembly"
    if "ncop" in text_lower or "national council" in text_lower:
        return "NCOP"
    return None
