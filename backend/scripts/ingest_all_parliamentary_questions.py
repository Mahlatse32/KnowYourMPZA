import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.parliament_question_discovery import discover_parliamentary_question_urls
from app.ingestion.parliament_questions import ingest_parliamentary_question_urls
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
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
    args = parser.parse_args()

    try:
        discovered_urls = discover_parliamentary_question_urls(limit=args.limit, year=args.year)
    except Exception as exc:
        result = discovery_failure("parliamentary_questions", exc)
        emit_result(result, "parliamentary_questions_ingestion_summary.json")
        return 1
    urls = sorted(set(_read_urls(Path(args.file)) + discovered_urls))
    if args.limit:
        urls = urls[: args.limit]
    print(f"attempted_count: {len(urls)}")
    if args.dry_run:
        for url in urls:
            print(url)
        return 0

    try:
        with SessionLocal() as db:
            run = start_ingestion_run(db, "Parliamentary Questions", "PARLIAMENTARY_QUESTIONS", len(urls))
            total, systemic = run_url_batch(
                urls,
                lambda url: ingest_parliamentary_question_urls(db, [url]),
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


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


if __name__ == "__main__":
    raise SystemExit(main())
