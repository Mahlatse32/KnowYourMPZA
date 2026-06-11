"""Official Parliament member ingestion.

Attempts to discover and ingest current member records from official
parliament.gov.za member pages. Merges with existing politicians by
profile URL and name matching. Records failures without crashing.

If official Parliament pages are not accessible, failures are logged and
the script exits cleanly. See docs/data-coverage.md for limitations.

Examples:
    python scripts/ingest_parliament_members_full.py --dry-run --limit 100
    python scripts/ingest_parliament_members_full.py --limit 500 --sleep 0.5
"""
import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, urlparse

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import requests
from bs4 import BeautifulSoup

from app.db import SessionLocal
from app.ingestion.people_assembly import (
    normalize_people_assembly_url,
)
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import ingest_people_assembly_profiles

PARLIAMENT_MEMBER_LISTING_URLS = [
    "https://www.parliament.gov.za/members",
    "https://www.parliament.gov.za/national-assembly/members",
    "https://www.parliament.gov.za/ncop/members",
    "https://www.parliament.gov.za/current-members",
]

PA_BASE = "https://www.pa.org.za"


def discover_parliament_member_pa_urls(listing_urls: list[str], sleep: float = 0.5) -> list[str]:
    """Fetch official Parliament member listing pages and extract People's Assembly profile URLs."""
    pa_urls: set[str] = set()
    for listing_url in listing_urls:
        try:
            response = requests.get(
                listing_url,
                timeout=20,
                headers={"User-Agent": "KnowYourMPZA/1.0"},
                allow_redirects=True,
            )
            if response.status_code != 200:
                print(f"  skip ({response.status_code}): {listing_url}")
                continue
            html = response.text
            soup = BeautifulSoup(html, "html.parser")
            for link in soup.find_all("a", href=True):
                href = str(link["href"]).strip()
                absolute = urljoin(listing_url, href)
                parsed = urlparse(absolute)
                if "pa.org.za" in parsed.netloc and re.fullmatch(r"/person/[a-z0-9-]+/?", parsed.path):
                    pa_urls.add(normalize_people_assembly_url(absolute))
            print(f"  found {len(pa_urls)} PA profile URLs via {listing_url}")
        except Exception as exc:
            print(f"  error fetching {listing_url}: {exc}")
        time.sleep(sleep)
    return sorted(pa_urls)


def main() -> None:
    parser = argparse.ArgumentParser(description="Official Parliament member ingestion via PA cross-reference.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument(
        "--discover",
        action="store_true",
        help="Perform live discovery during --dry-run (off by default so dry runs are fast).",
    )
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    if args.dry_run and not args.discover:
        print("dry-run: skipping live Parliament discovery (pass --discover to enable).")
        return

    print("discovering members from official Parliament listing pages...")
    pa_urls = discover_parliament_member_pa_urls(PARLIAMENT_MEMBER_LISTING_URLS, sleep=args.sleep)

    if not pa_urls:
        print("no People's Assembly URLs found via official Parliament pages.")
        print("limitation: official Parliament member pages may not link to PA profiles.")
        print("see docs/data-coverage.md for details.")
        print("recommendation: run ingest_people_assembly_full.py instead for full coverage.")
        return

    urls = pa_urls
    if args.limit:
        urls = urls[: args.limit]

    print(f"discovered_pa_url_count: {len(urls)}")
    if args.dry_run:
        for url in urls:
            print(url)
        return

    total = _summary()
    with SessionLocal() as db:
        run = start_ingestion_run(db, "Parliament", "full_parliament_members", len(urls))
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")
            part = ingest_people_assembly_profiles(db, [url])
            _merge(total, part)
            time.sleep(args.sleep)
        finish_ingestion_run(db, run, total)
    _print(total, len(urls))


def _summary() -> dict:
    return {"processed_count": 0, "created_count": 0, "updated_count": 0, "skipped_count": 0, "failed_count": 0, "errors": []}


def _merge(total: dict, part: dict) -> None:
    for key in ["processed_count", "created_count", "updated_count", "skipped_count", "failed_count"]:
        total[key] += part.get(key, 0)
    total["errors"].extend(part.get("errors", []))


def _print(summary: dict, attempted: int) -> None:
    print(f"attempted_count: {attempted}")
    for key, value in summary.items():
        if key != "errors":
            print(f"{key}: {value}")


if __name__ == "__main__":
    main()
