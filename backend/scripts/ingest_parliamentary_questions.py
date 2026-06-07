import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.parliament_questions import ingest_parliamentary_question_urls
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("file", nargs="?", default="data/parliamentary_question_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    args = parser.parse_args()

    urls = _read_urls(Path(args.file))
    if args.limit:
        urls = urls[: args.limit]
    print(f"attempted_count: {len(urls)}")
    if args.dry_run:
        for url in urls:
            print(url)
        return

    total = _summary()
    with SessionLocal() as db:
        run = start_ingestion_run(db, "Parliamentary Questions", "PARLIAMENTARY_QUESTIONS", len(urls))
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")
            part = ingest_parliamentary_question_urls(db, [url])
            _merge(total, part)
            time.sleep(args.sleep)
        finish_ingestion_run(db, run, total)
    _print(total)


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


def _print(summary: dict) -> None:
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
