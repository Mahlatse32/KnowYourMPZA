from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.ingestion_service import ingest_people_assembly_profiles


def main() -> None:
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/ingest_people_assembly.py data/people_assembly_urls.txt")
    urls = _read_urls(Path(sys.argv[1]))
    with SessionLocal() as db:
        print(ingest_people_assembly_profiles(db, urls))


def _read_urls(path: Path) -> list[str]:
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


if __name__ == "__main__":
    main()
