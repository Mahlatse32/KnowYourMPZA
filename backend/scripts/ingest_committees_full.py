"""Full committee and membership ingestion from People's Assembly.

Discovers and ingests as many committee pages as possible.
Unmatched member names are stored as unresolved entities for review.

Examples:
    python scripts/ingest_committees_full.py --dry-run --limit 100
    python scripts/ingest_committees_full.py --limit 500 --sleep 0.5
    python scripts/ingest_committees_full.py --discover-only
"""
import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.people_assembly import (
    discover_people_assembly_committee_urls,
    normalize_people_assembly_url,
)
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import ingest_people_assembly_committees

EXTENDED_LISTING_URLS = [
    "https://www.pa.org.za/committees/",
    "https://www.pa.org.za/organisation/national-assembly/",
    "https://www.pa.org.za/organisation/ncop/",
    "https://www.pa.org.za/organisation/is/",
]


def main() -> None:
    parser = argparse.ArgumentParser(description="Full committee ingestion from People's Assembly.")
    parser.add_argument("--file", default="data/committee_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--write-discovered", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    existing_urls = _read_urls(path)
    print("discovering committee URLs from People's Assembly...")
    discovered_urls = discover_people_assembly_committee_urls(listing_urls=EXTENDED_LISTING_URLS)

    if args.write_discovered:
        _write_merged_urls(path, existing_urls, discovered_urls)

    urls = sorted({normalize_people_assembly_url(url) for url in existing_urls + discovered_urls})
    if args.limit:
        urls = urls[: args.limit]

    print(f"existing_count: {len(existing_urls)}")
    print(f"newly_discovered_count: {len(set(discovered_urls) - set(existing_urls))}")
    print(f"total_to_ingest: {len(urls)}")

    if args.dry_run or args.discover_only:
        for url in urls:
            print(url)
        return

    total = _summary()
    with SessionLocal() as db:
        run = start_ingestion_run(db, "People's Assembly", "full_committees", len(urls))
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")
            part = ingest_people_assembly_committees(db, [url])
            _merge(total, part)
            time.sleep(args.sleep)
        finish_ingestion_run(db, run, total)
    _print(total, len(urls))


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        normalize_people_assembly_url(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _write_merged_urls(path: Path, existing: list[str], discovered: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = sorted({normalize_people_assembly_url(url) for url in existing + discovered})
    path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    print(f"wrote_url_count: {len(merged)}")


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
    if summary["errors"]:
        print(f"sample_errors: {summary['errors'][:3]}")


if __name__ == "__main__":
    main()
