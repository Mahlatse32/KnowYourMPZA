"""Generate a comprehensive full coverage report for KnowYourMPZA.

Writes backend/reports/full_coverage_report.json.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.services.coverage_service import generate_full_coverage_report


def main() -> None:
    output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "full_coverage_report.json"

    with SessionLocal() as db:
        report = generate_full_coverage_report(db)

    output_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    print(f"report_path: {output_path}")

    counts = report["database_counts"]
    print(f"politicians: {counts['politicians_total']} ({counts['active_politicians_total']} active)")
    print(f"parties: {counts['parties_total']}")
    print(f"committees: {counts['committees_total']}")
    print(f"memberships: {counts['committee_memberships_total']}")
    print(f"pmg_documents: {counts['pmg_documents_total']}")
    print(f"parliamentary_questions: {counts['parliamentary_questions_total']}")
    print(f"unresolved_open: {counts['unresolved_entities_open']}")
    print("recommendations:")
    for rec in report["recommendations"]:
        print(f"  - {rec}")


if __name__ == "__main__":
    main()
