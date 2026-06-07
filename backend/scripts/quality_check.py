from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.quality_service import quality_summary


def main() -> None:
    with SessionLocal() as db:
        report = quality_summary(db)
    for key, value in report.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
