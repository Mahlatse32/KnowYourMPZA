from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.ingestion_service import regenerate_aliases


def main() -> None:
    with SessionLocal() as db:
        created_count = regenerate_aliases(db)
    print(f"created_alias_count: {created_count}")


if __name__ == "__main__":
    main()
