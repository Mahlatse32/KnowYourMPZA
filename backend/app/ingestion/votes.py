"""Parse vote/division records from PMG."""
import logging
import re
from datetime import date
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PMG_VOTES_URL = "https://pmg.org.za/votes/"

VOTE_TYPE_MAP = {
    "bill": "bill_vote",
    "motion": "motion",
    "amendment": "amendment",
    "committee": "committee_decision",
}

RESULT_MAP = {
    "agreed": "agreed_to",
    "negatived": "negatived",
    "adopted": "adopted",
    "tied": "tied",
    "withdrawn": "withdrawn",
}

VOTE_VALUE_MAP = {
    "yes": "yes",
    "aye": "yes",
    "no": "no",
    "nay": "no",
    "abstain": "abstain",
    "absent": "absent",
    "present": "present",
}


def fetch_page(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "KnowYourMPZA/1.0"})
    resp.raise_for_status()
    return resp.text


# ---------------------------------------------------------------------------
# PMG JSON API vote-signal detection.
#
# PMG exposes no /vote/ or /division/ endpoint (both 404). Vote and division
# signals therefore come from committee-meeting minutes text (the "body"
# field of /committee-meeting/<id>/). Only explicit textual signals create
# VoteEvents, and VoteRecords are created only when explicit counts appear.
# ---------------------------------------------------------------------------

# Ordered: the first matching signal determines the result. More specific
# phrases come first.
VOTE_SIGNALS: list[tuple[str, str, str]] = [
    # (phrase, vote_type, result)
    ("amendment agreed to", "amendment", "agreed_to"),
    ("amendment rejected", "amendment", "negatived"),
    ("amendment negatived", "amendment", "negatived"),
    ("bill was negatived", "bill_vote", "negatived"),
    ("bill was agreed to", "bill_vote", "agreed_to"),
    ("bill was adopted", "bill_vote", "adopted"),
    ("motion was agreed to", "motion", "agreed_to"),
    ("motion was negatived", "motion", "negatived"),
    ("negatived", "unknown", "negatived"),
    ("agreed to", "unknown", "agreed_to"),
    ("adopted", "unknown", "adopted"),
]

# A division/vote must actually be signalled for an event to exist at all.
DIVISION_MARKERS = [
    "division",
    "votes in favour",
    "votes against",
    "abstention",
    "voted in favour",
    "voted against",
    "put to a vote",
    "put to the vote",
]

_COUNT_PATTERNS = [
    (re.compile(r"(\d+)\s+vot(?:es|ed)\s+in\s+favour", re.IGNORECASE), "yes"),
    (re.compile(r"(\d+)\s+vot(?:es|ed)\s+against", re.IGNORECASE), "no"),
    (re.compile(r"(\d+)\s+abstentions?", re.IGNORECASE), "abstain"),
]


def html_to_text(html: str) -> str:
    return BeautifulSoup(html or "", "html.parser").get_text(" ", strip=True)


def detect_vote_signal(text: str) -> dict[str, str] | None:
    """Return {vote_type, result} if the text contains an explicit division/vote
    signal, else None. Outcome words alone ("adopted") do not count without a
    division marker — minutes adopt agendas constantly."""
    low = (text or "").lower()
    if not any(marker in low for marker in DIVISION_MARKERS):
        return None
    for phrase, vote_type, result in VOTE_SIGNALS:
        if phrase in low:
            return {"vote_type": vote_type, "result": result}
    # A division happened but the outcome wording is unrecognised: model the
    # limitation rather than inventing a result.
    return {"vote_type": "unknown", "result": None}


def extract_aggregate_counts(text: str, source_url: str | None = None) -> list[dict[str, Any]]:
    """Extract explicit aggregate vote counts ("X votes in favour, Y against,
    Z abstentions") as aggregate-level vote records. Returns [] when the text
    exposes no explicit counts — records are never inferred."""
    low = text or ""
    records: list[dict[str, Any]] = []
    for pattern, vote_value in _COUNT_PATTERNS:
        m = pattern.search(low)
        if m:
            records.append(
                {
                    "politician_name": None,
                    "party_name": None,
                    "vote_value": vote_value,
                    "record_level": "aggregate",
                    "count": int(m.group(1)),
                    "confidence": "high",
                    "source_url": source_url,
                }
            )
    return records


def build_vote_event_from_meeting(detail: dict) -> dict[str, Any] | None:
    """Build a vote_event dict from a PMG committee-meeting detail payload,
    or None if the minutes expose no explicit vote/division signal."""
    meeting_id = detail.get("id")
    body_text = html_to_text(detail.get("body") or "")
    if not body_text:
        return None
    signal = detect_vote_signal(body_text)
    if not signal:
        return None
    source_url = f"https://pmg.org.za/committee-meeting/{meeting_id}/" if meeting_id else None
    committee = detail.get("committee") or {}
    house = committee.get("house") or {}
    title = detail.get("title") or "Untitled meeting"
    event_date = None
    if detail.get("date"):
        from datetime import date as _date

        try:
            event_date = _date.fromisoformat(str(detail["date"])[:10])
        except ValueError:
            event_date = None
    return {
        "title": f"Committee decision: {title}"[:500],
        "date": event_date,
        "chamber": house.get("name") if isinstance(house, dict) else None,
        "vote_type": "committee_decision" if signal["vote_type"] == "unknown" else signal["vote_type"],
        "result": signal["result"],
        "committee_name": committee.get("name") if isinstance(committee, dict) else None,
        "source_url": source_url,
        "source_type": "pmg-api",
        "vote_records": extract_aggregate_counts(body_text, source_url),
    }


def _normalize_vote_type(text: str) -> str:
    low = text.lower()
    for k, v in VOTE_TYPE_MAP.items():
        if k in low:
            return v
    return "unknown"


def _normalize_result(text: str) -> str:
    low = text.lower()
    for k, v in RESULT_MAP.items():
        if k in low:
            return v
    return None


def _normalize_vote_value(text: str) -> str:
    low = text.strip().lower()
    return VOTE_VALUE_MAP.get(low, "unknown")


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


def parse_pmg_vote_event(html: str, source_url: str) -> dict[str, Any] | None:
    """Parse a single PMG vote/division page into a vote_event dict with vote_records list."""
    soup = BeautifulSoup(html, "html.parser")

    h1 = soup.find("h1")
    if not h1:
        logger.warning("No <h1> found on vote page %s", source_url)
        return None
    title = h1.get_text(strip=True)

    date_tag = soup.find(class_=re.compile(r"date|meta", re.I))
    event_date = _parse_date(date_tag.get_text()) if date_tag else None

    chamber_tag = soup.find(string=re.compile(r"national assembly|ncop|council", re.I))
    chamber = None
    if chamber_tag:
        text = chamber_tag.lower()
        if "national assembly" in text:
            chamber = "National Assembly"
        elif "ncop" in text or "national council" in text:
            chamber = "NCOP"

    result_tag = soup.find(string=re.compile(r"agreed|negatived|adopted|tied|withdrawn", re.I))
    result = _normalize_result(result_tag.strip()) if result_tag else None

    vote_records: list[dict[str, Any]] = []
    for table in soup.find_all("table"):
        headers = [th.get_text(strip=True).lower() for th in table.find_all("th")]
        if not any(h in headers for h in ["party", "yes", "no", "aye", "nay", "vote"]):
            continue
        for row in table.find_all("tr"):
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            if not cells:
                continue
            if len(cells) >= 3:
                party_name = cells[0]
                yes_count = _parse_int(cells[1])
                no_count = _parse_int(cells[2]) if len(cells) > 2 else None
                if party_name:
                    if yes_count is not None:
                        vote_records.append(
                            {
                                "party_name": party_name,
                                "politician_name": None,
                                "vote_value": "yes",
                                "record_level": "party",
                                "count": yes_count,
                                "confidence": "high",
                                "source_url": source_url,
                            }
                        )
                    if no_count is not None:
                        vote_records.append(
                            {
                                "party_name": party_name,
                                "politician_name": None,
                                "vote_value": "no",
                                "record_level": "party",
                                "count": no_count,
                                "confidence": "high",
                                "source_url": source_url,
                            }
                        )
            elif len(cells) == 2:
                name, vote_raw = cells[0], cells[1]
                vote_records.append(
                    {
                        "party_name": None,
                        "politician_name": name,
                        "vote_value": _normalize_vote_value(vote_raw),
                        "record_level": "individual",
                        "count": None,
                        "confidence": "high",
                        "source_url": source_url,
                    }
                )

    return {
        "title": title,
        "date": event_date,
        "chamber": chamber,
        "vote_type": _normalize_vote_type(title),
        "result": result,
        "source_url": source_url,
        "source_type": "pmg",
        "vote_records": vote_records,
    }


def parse_pmg_votes_index(html: str, source_url: str = _PMG_VOTES_URL) -> list[str]:
    """Return a list of individual vote page URLs from the PMG votes index."""
    soup = BeautifulSoup(html, "html.parser")
    urls: list[str] = []
    for a in soup.select("a[href*='/vote'], a[href*='/division']"):
        href = a.get("href", "")
        if not href:
            continue
        if not href.startswith("http"):
            href = "https://pmg.org.za" + href
        if href not in urls:
            urls.append(href)
    return urls


def _parse_int(text: str) -> int | None:
    try:
        return int(text.strip().replace(",", ""))
    except (ValueError, AttributeError):
        return None
