import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.parliament_question_discovery import discover_parliamentary_question_records
from app.ingestion.parliament_questions import ingest_parliamentary_question_urls
from app.models.parliamentary_question import ParliamentaryQuestion
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from sqlalchemy import select
from scripts.ingestion_batch_utils import (
    build_result,
    discovery_failure,
    emit_result,
    run_url_batch,
    should_fail,
    systemic_failure,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/parliamentary_question_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument(
        "--discovery-limit",
        type=int,
        default=None,
        help=(
            "Number of candidate URLs to discover before selecting the ingest batch. "
            "Defaults to a larger window than --limit so scheduled runs can skip "
            "already-ingested questions and still create new records."
        ),
    )
    args = parser.parse_args()

    ingest_limit = args.limit
    discovery_limit = args.discovery_limit
    if discovery_limit is None and ingest_limit:
        discovery_limit = max(ingest_limit * 20, 1000)

    try:
        discovered_urls, metadata_by_url = discover_parliamentary_question_records(
            limit=discovery_limit, year=args.year
        )
    except Exception as exc:
        result = discovery_failure("parliamentary_questions", exc)
        emit_result(result, "parliamentary_questions_ingestion_summary.json")
        return 1
    urls = sorted(set(_read_urls(Path(args.file)) + discovered_urls))

    try:
        with SessionLocal() as db:
            existing_urls = set(
                db.scalars(
                    select(ParliamentaryQuestion.source_url).where(
                        ParliamentaryQuestion.source_url.in_(urls)
                    )
                )
            )
            urls = _prioritize_new_urls(urls, existing_urls, ingest_limit)
            print(f"discovered_count: {len(discovered_urls)}")
            print(f"candidate_count: {len(set(_read_urls(Path(args.file)) + discovered_urls))}")
            print(f"existing_candidate_count: {len(existing_urls)}")
            print(f"attempted_count: {len(urls)}")
            if args.dry_run:
                for url in urls:
                    print(url)
                return 0
            run = start_ingestion_run(db, "Parliamentary Questions", "PARLIAMENTARY_QUESTIONS", len(urls))
            total, systemic = run_url_batch(
                urls,
                lambda url: ingest_parliamentary_question_urls(db, [url], metadata_by_url=metadata_by_url),
                sleep_seconds=args.sleep,
            )
            finish_ingestion_run(db, run, total)
    except Exception as exc:
        result = systemic_failure("parliamentary_questions", "database", exc)
        emit_result(result, "parliamentary_questions_ingestion_summary.json")
        return 1
    result = build_result("parliamentary_questions", len(urls), total, systemic)
    emit_result(result, "parliamentary_questions_ingestion_summary.json")
    return 1 if should_fail(result) else 0


def _prioritize_new_urls(urls: list[str], existing_urls: set[str], limit: int | None) -> list[str]:
    unique_urls = sorted(set(urls))
    new_urls = [url for url in unique_urls if url not in existing_urls]
    refresh_urls = [url for url in unique_urls if url in existing_urls]
    selected = new_urls + refresh_urls
    return selected[:limit] if limit else selected


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


if __name__ == "__main__":
    raise SystemExit(main())
