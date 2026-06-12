"""Parse committee meeting records from PMG."""
import logging
import re
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PMG_MEETINGS_URL = "https://pmg.org.za/committee-meetings/"
_PMG_API_MEETINGS_URL = "https://api.pmg.org.za/committee-meeting/"

# Explicit attendance codes used by the PMG API.
ATTENDANCE_CODE_MAP = {
    "P": "present",
    "A": "absent",
    "AP": "apology",
    "L": "present",    # arrived late — still attended
    "DE": "present",   # departed early — still attended
    "LDE": "present",
}

ATTENDANCE_STATUS_MAP = {
    "present": "present",
    "attended": "present",
    "absent": "absent",
    "apology": "apology",
    "apologies": "apology",
    "leave": "apology",
}


def fetch_page(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "KnowYourMPZA/1.0"})
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# PMG JSON API (the HTML pages at pmg.org.za are JS-rendered shells; the
# public API at api.pmg.org.za is the reliable source).
# ---------------------------------------------------------------------------

def pmg_meetings_api_url(page: int) -> str:
    return f"{_PMG_API_MEETINGS_URL}?page={page}"


def meeting_attendance_api_url(meeting_id: int) -> str:
    return f"{_PMG_API_MEETINGS_URL}{meeting_id}/attendance/"


def meeting_detail_api_url(meeting_id: int) -> str:
    return f"{_PMG_API_MEETINGS_URL}{meeting_id}/"


def _iso_to_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def parse_pmg_api_meetings(payload: dict) -> list[dict[str, Any]]:
    """Map one page of the PMG committee-meeting API listing to meeting dicts."""
    meetings: list[dict[str, Any]] = []
    for item in payload.get("results", []):
        meeting_id = item.get("id")
        if not meeting_id:
            continue
        committee = item.get("committee") or {}
        house = committee.get("house") or {}
        source_url = f"https://pmg.org.za/committee-meeting/{meeting_id}/"
        meetings.append(
            {
                "api_id": meeting_id,
                "title": item.get("title") or "Untitled meeting",
                "date": _iso_to_date(item.get("date")),
                "committee_name": committee.get("name") if isinstance(committee, dict) else None,
                "house": house.get("name") if isinstance(house, dict) else None,
                "summary": None,
                "source_url": source_url,
                "pmg_url": source_url,
                "source_type": "pmg-api",
                "attendance": [],
            }
        )
    return meetings


def parse_pmg_api_attendance(payload: dict, source_url: str | None = None) -> list[dict[str, Any]]:
    """Map the per-meeting attendance API response to attendance dicts.

    Only explicit records are produced: each row carries the member's name
    and the API's attendance code. Unknown codes map to "unknown" rather
    than being guessed.
    """
    rows: list[dict[str, Any]] = []
    for record in payload.get("results", []):
        member = record.get("member") or {}
        name = member.get("name") if isinstance(member, dict) else None
        if not name:
            continue
        party = member.get("party") or {}
        code = (record.get("attendance") or "").strip().upper()
        rows.append(
            {
                "name_raw": name,
                "party_name": party.get("name") if isinstance(party, dict) else None,
                "attendance_status": ATTENDANCE_CODE_MAP.get(code, "unknown"),
                "confidence": 1.0,  # explicit source data, not inferred
                "source_url": source_url,
            }
        )
    return rows


def _normalize_attendance(text: str) -> str:
    low = text.strip().lower()
    for k, v in ATTENDANCE_STATUS_MAP.items():
        if k in low:
            return v
    return "unknown"


def _parse_date(text: str) -> date | None:
    m = re.search(r"(\d{1,2})\s+(\w+)\s+(\d{4})", text)
    if m:
        try:
            from datetime import datetime
            return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%d %B %Y").date()
        except ValueError:
            pass
    m2 = re.search(r"(\d{4})-(\d{2})-(\d{2})", text)
    if m2:
        try:
            return date(int(m2.group(1)), int(m2.group(2)), int(m2.group(3)))
        except ValueError:
            pass
    return None


def parse_pmg_meeting(html: str, source_url: str) -> dict[str, Any] | None:
    """Parse a single PMG committee meeting page."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        logger.warning("No <h1> found on meeting page %s", source_url)
        return None
    title = h1.get_text(strip=True)

    date_tag = soup.find(class_=re.compile(r"date|meta", re.I))
    meeting_date = _parse_date(date_tag.get_text()) if date_tag else None

    summary_tag = soup.find(class_=re.compile(r"summary|content|body", re.I))
    summary = summary_tag.get_text(" ", strip=True)[:2000] if summary_tag else None

    attendance: list[dict[str, Any]] = []
    for section in soup.find_all(string=re.compile(r"attendance|members present|apologies", re.I)):
        parent = section.find_parent()
        if not parent:
            continue
        ul = parent.find_next_sibling("ul") or parent.find_next("ul")
        if ul:
            for li in ul.find_all("li"):
                text = li.get_text(strip=True)
                if not text:
                    continue
                status = _normalize_attendance(section)
                attendance.append(
                    {
                        "name_raw": text,
                        "attendance_status": status,
                        "confidence": 0.9,
                        "source_url": source_url,
                    }
                )
        table = parent.find_next_sibling("table") or parent.find_next("table")
        if table:
            for row in table.find_all("tr"):
                cells = [td.get_text(strip=True) for td in row.find_all("td")]
                if not cells:
                    continue
                name = cells[0]
                status_text = cells[1] if len(cells) > 1 else ""
                if name:
                    attendance.append(
                        {
                            "name_raw": name,
                            "attendance_status": _normalize_attendance(status_text or section),
                            "confidence": 0.85,
                            "source_url": source_url,
                        }
                    )

    return {
        "title": title,
        "date": meeting_date,
        "summary": summary,
        "source_url": source_url,
        "pmg_url": source_url,
        "source_type": "pmg",
        "attendance": attendance,
    }


def parse_pmg_meetings_index(html: str, source_url: str = _PMG_MEETINGS_URL) -> list[str]:
    """Return a list of individual meeting page URLs from the PMG meetings index."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for a in soup.select("a[href*='/committee-meeting/']"):
        href = a.get("href", "")
        if not href:
            continue
        if not href.startswith("http"):
            href = "https://pmg.org.za" + href
        if href not in urls:
            urls.append(href)
    return urls
