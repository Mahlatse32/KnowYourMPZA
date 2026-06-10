"""Full PMG meeting/document ingestion with date range support.

Discovers and ingests PMG committee meeting documents across a date range.
Supports year-by-year pagination to build a broad corpus.

Examples:
    python scripts/ingest_pmg_full.py --dry-run --limit 50
    python scripts/ingest_pmg_full.py --from-date 2024-05-29 --to-date 2026-06-10 --limit 2000 --sleep 0.5
    python scripts/ingest_pmg_full.py --from-date 2023-01-01 --limit 500 --committee Health --sleep 0.5
"""
import argparse
from datetime import date
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.pmg import discover_pmg_document_urls
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import ingest_pmg_documents


def _years_in_range(from_date: date | None, to_date: date | None) -> list[int]:
    start_year = (from_date or date(2024, 1, 1)).year
    end_year = (to_date or date.today()).year
    return list(range(start_year, end_year + 1))


def main() -> None:
    parser = argparse.ArgumentParser(description="Full PMG document ingestion with date range.")
    parser.add_argument("--file", default="data/pmg_urls.txt")
    parser.add_argument("--from-date", default=None, help="Start date (YYYY-MM-DD). Defaults to 2024-01-01.")
    parser.add_argument("--to-date", default=None, help="End date (YYYY-MM-DD). Defaults to today.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--write-discovered", action="store_true")
    parser.add_argument("--committee", default=None, help="Filter by committee name substring.")
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None
    years = _years_in_range(from_date, to_date)

    path = Path(args.file)
    existing_urls = _read_urls(path)

    print(f"discovering PMG URLs for years: {years}")
    discovered_urls: set[str] = set(existing_urls)
    per_year_limit = max(args.limit or 500, 200)
    for year in years:
        year_urls = discover_pmg_document_urls(
            limit=per_year_limit,
            year=year,
            committee=args.committee,
        )
        print(f"  year {year}: {len(year_urls)} URLs discovered")
        discovered_urls.update(year_urls)
        if args.limit and len(discovered_urls) >= args.limit * 2:
            break

    all_urls = sorted(discovered_urls)
    if args.limit:
        all_urls = all_urls[: args.limit]

    if args.write_discovered:
        _write_merged_urls(path, existing_urls, list(discovered_urls))

    print(f"existing_count: {len(existing_urls)}")
    print(f"newly_discovered_count: {len(discovered_urls) - len(set(existing_urls))}")
    print(f"total_to_ingest: {len(all_urls)}")

    if args.dry_run or args.discover_only:
        for url in all_urls:
            print(url)
        return

    total = _summary()
    with SessionLocal() as db:
        run = start_ingestion_run(db, "PMG", "full_pmg", len(all_urls))
        for index, url in enumerate(all_urls, start=1):
            print(f"[{index}/{len(all_urls)}] {url}")
            part = ingest_pmg_documents(db, [url])
            _merge(total, part)
            time.sleep(args.sleep)
        finish_ingestion_run(db, run, total)
    _print(total, len(all_urls))


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


def _write_merged_urls(path: Path, existing: list[str], discovered: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = sorted(set(existing + discovered))
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
