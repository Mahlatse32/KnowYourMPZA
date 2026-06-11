"""Full Parliamentary Questions ingestion with date range support.

Discovers and ingests parliamentary questions and answer papers across a
date range. Handles HTML pages and PDF sources. Failed PDFs are archived
and logged without stopping the run.

Examples:
    python scripts/ingest_questions_full.py --dry-run --limit 50
    python scripts/ingest_questions_full.py --from-date 2024-05-29 --to-date 2026-06-10 --limit 1000 --sleep 0.5
    python scripts/ingest_questions_full.py --from-date 2023-01-01 --limit 500 --sleep 0.5
"""
import argparse
from datetime import date
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.parliament_question_discovery import discover_parliamentary_question_urls
from app.ingestion.parliament_questions import ingest_parliamentary_question_urls
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run


def main() -> None:
    parser = argparse.ArgumentParser(description="Full parliamentary questions ingestion with date range.")
    parser.add_argument("--file", default="data/parliamentary_question_urls.txt")
    parser.add_argument("--from-date", default=None, help="Start date (YYYY-MM-DD). Filters by year.")
    parser.add_argument("--to-date", default=None, help="End date (YYYY-MM-DD). Filters by year.")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    from_date = date.fromisoformat(args.from_date) if args.from_date else None
    to_date = date.fromisoformat(args.to_date) if args.to_date else None
    years = _years_in_range(from_date, to_date)

    existing_urls = _read_urls(Path(args.file))

    print(f"discovering parliamentary question URLs for years: {years}")
    discovered: set[str] = set(existing_urls)
    per_year_limit = max(args.limit or 500, 200)
    for year in years:
        year_urls = discover_parliamentary_question_urls(limit=per_year_limit, year=year)
        print(f"  year {year}: {len(year_urls)} URLs discovered")
        discovered.update(year_urls)
        if args.limit and len(discovered) >= args.limit * 2:
            break

    urls = sorted(discovered)
    if args.limit:
        urls = urls[: args.limit]

    print(f"existing_count: {len(existing_urls)}")
    print(f"total_to_ingest: {len(urls)}")

    if args.dry_run:
        for url in urls:
            print(url)
        return

    total = _summary()
    with SessionLocal() as db:
        run = start_ingestion_run(db, "Parliamentary Questions", "full_questions", len(urls))
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")
            part = ingest_parliamentary_question_urls(db, [url])
            _merge(total, part)
            time.sleep(args.sleep)
        finish_ingestion_run(db, run, total)
    _print(total, len(urls))


def _years_in_range(from_date: date | None, to_date: date | None) -> list[int]:
    start = (from_date or date(2024, 1, 1)).year
    end = (to_date or date.today()).year
    return list(range(start, end + 1))


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


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
