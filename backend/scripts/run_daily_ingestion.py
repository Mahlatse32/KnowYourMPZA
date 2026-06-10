import os
from pathlib import Path
import subprocess
import sys


def main() -> None:
    _ensure_enabled()
    max_urls = os.getenv("MAX_DAILY_INGESTION_URLS", "50")
    sleep = os.getenv("SOURCE_RATE_LIMIT_SLEEP", "0.5")
    _run(["python", "scripts/ingest_all_pmg.py", "--limit", max_urls, "--sleep", sleep])
    _run(["python", "scripts/ingest_all_parliamentary_questions.py", "--limit", max_urls, "--sleep", sleep])
    _run(["python", "scripts/quality_check.py"])
    _run(["python", "scripts/dataset_report.py"])


def _ensure_enabled() -> None:
    if os.getenv("INGESTION_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit("INGESTION_ENABLED is not true; scheduled ingestion is disabled.")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url or "localhost" in database_url or "@db:" in database_url:
        raise SystemExit("DATABASE_URL must point at an explicit non-local production/staging database.")


def _run(command: list[str]) -> None:
    print(" ".join(command), flush=True)
    subprocess.run(command, cwd=Path(__file__).resolve().parents[1], check=True)


if __name__ == "__main__":
    main()
