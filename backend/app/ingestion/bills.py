"""Parse bill listings from parliament.gov.za and pmg.org.za."""
import logging
import re
from typing import Any

import requests
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

_PARLIAMENT_BILLS_URL = "https://www.parliament.gov.za/bills"
_PMG_BILLS_URL = "https://pmg.org.za/bills/"

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


def fetch_page(url: str, timeout: int = 20) -> str:
    resp = requests.get(url, timeout=timeout, headers={"User-Agent": "KnowYourMPZA/1.0"})
    resp.raise_for_status()
    return resp.text


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


def _extract_house(text: str) -> str | None:
    text_lower = text.lower()
    if "national assembly" in text_lower:
        return "National Assembly"
    if "ncop" in text_lower or "national council" in text_lower:
        return "NCOP"
    return None
