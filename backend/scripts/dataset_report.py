import json
from datetime import UTC, datetime
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.models.document_mention import DocumentMention
from app.models.ingestion_error import IngestionError
from app.models.ingestion_run import IngestionRun
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.question_mention import QuestionMention
from app.services.quality_service import quality_issues, quality_summary


def main() -> None:
    report_path = Path("reports/dataset_report.json")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    with SessionLocal() as db:
        summary = quality_summary(db)
        issues = quality_issues(db, limit=500)
        report = {
            "generated_at": datetime.now(UTC).isoformat(),
            "politician_counts": _pick(summary, "total_politicians", "active_politicians", "inactive_politicians", "unknown_status_politicians"),
            "party_counts": _pick(summary, "total_parties", "duplicate_party_short_name_count"),
            "committee_counts": _pick(summary, "total_committees", "committees_without_memberships", "duplicate_committee_slug_count"),
            "membership_counts": _pick(summary, "total_committee_memberships", "duplicate_membership_candidates"),
            "alias_counts": _pick(summary, "total_aliases"),
            "document_counts": _pick(summary, "total_documents", "documents_without_mentions", "documents_without_archive_path"),
            "pmg_counts": _pick(
                summary,
                "total_pmg_documents",
                "pmg_documents_without_mentions",
                "pmg_documents_without_archive_path",
            ),
            "mention_counts": {
                "total_document_mentions": summary["total_document_mentions"],
                "total_question_mentions": summary["total_question_mentions"],
            },
            "question_counts": _pick(
                summary,
                "total_parliamentary_questions",
                "parliamentary_question_pdf_sources",
                "parliamentary_question_parse_failed",
                "parliamentary_question_parse_partial",
            ),
            "unresolved_entity_counts": _pick(
                summary,
                "total_unresolved_entities",
                "unresolved_entities_open",
                "unresolved_entities_resolved",
                "unresolved_entities_ignored",
            ),
            "ingestion_run_counts": _pick(summary, "total_ingestion_runs", "total_ingestion_errors"),
            "archive_file_counts": _archive_counts(),
            "quality_issue_counts": {key: len(value) for key, value in issues.items()},
            "raw_counts": {
                "document_mentions": _model_count(db, DocumentMention),
                "question_mentions": _model_count(db, QuestionMention),
                "parliamentary_questions": _model_count(db, ParliamentaryQuestion),
                "ingestion_runs": _model_count(db, IngestionRun),
                "ingestion_errors": _model_count(db, IngestionError),
            },
        }
    report_path.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(str(report_path))


def _pick(summary: dict, *keys: str) -> dict:
    return {key: summary[key] for key in keys if key in summary}


def _archive_counts() -> dict[str, int]:
    root = Path("data/raw")
    if not root.exists():
        return {}
    return {str(path.relative_to(root)): len(list(path.glob("*"))) for path in root.iterdir() if path.is_dir()}


def _model_count(db, model) -> int:
    from sqlalchemy import func, select

    return db.scalar(select(func.count()).select_from(model)) or 0


if __name__ == "__main__":
    main()
