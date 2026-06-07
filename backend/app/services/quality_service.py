from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.committee import Committee
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.ingestion_error import IngestionError
from app.models.ingestion_run import IngestionRun
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.question_mention import QuestionMention
from app.models.unresolved_entity import UnresolvedEntity


def quality_summary(db: Session) -> dict[str, int]:
    return {
        "total_politicians": _count(db, Politician),
        "active_politicians": db.scalar(select(func.count()).select_from(Politician).where(Politician.is_active.is_(True))) or 0,
        "inactive_politicians": db.scalar(select(func.count()).select_from(Politician).where(Politician.is_active.is_(False))) or 0,
        "total_parties": _count(db, Party),
        "total_committees": _count(db, Committee),
        "total_committee_memberships": _count(db, CommitteeMembership),
        "total_documents": _count(db, Document),
        "total_document_mentions": _count(db, DocumentMention),
        "total_parliamentary_questions": _count(db, ParliamentaryQuestion),
        "total_question_mentions": _count(db, QuestionMention),
        "total_aliases": _count(db, PoliticianAlias),
        "total_ingestion_runs": _count(db, IngestionRun),
        "total_ingestion_errors": _count(db, IngestionError),
        "unresolved_entities_count": _count(db, UnresolvedEntity),
        "politicians_without_party": db.scalar(select(func.count()).select_from(Politician).where(Politician.party_id.is_(None))) or 0,
        "politicians_without_committees": _politicians_without_child(db, CommitteeMembership),
        "active_politicians_without_committees": _active_politicians_without_committees(db),
        "documents_without_mentions": _documents_without_mentions(db),
        "documents_without_archive_path": db.scalar(select(func.count()).select_from(Document).where(Document.archive_path.is_(None))) or 0,
        "parliamentary_questions_without_politician": db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.politician_id.is_(None))
        )
        or 0,
        "parliamentary_questions_without_answer": db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.answer_text.is_(None))
        )
        or 0,
        "parliamentary_questions_without_archive_path": db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.archive_path.is_(None))
        )
        or 0,
        "parliamentary_question_pdf_sources": db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.source_file_type == "PDF")
        )
        or 0,
        "parliamentary_question_parse_failed": db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.parse_status == "FAILED")
        )
        or 0,
        "parliamentary_question_parse_partial": db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.parse_status == "PARTIAL")
        )
        or 0,
        "duplicate_slug_count": _duplicate_count(db, Politician.slug),
        "duplicate_source_url_count": _duplicate_count(db, Document.source_url),
    }


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _politicians_without_child(db: Session, child_model) -> int:
    subquery = select(child_model.politician_id).distinct()
    return db.scalar(select(func.count()).select_from(Politician).where(Politician.id.not_in(subquery))) or 0


def _documents_without_mentions(db: Session) -> int:
    subquery = select(DocumentMention.document_id).distinct()
    return db.scalar(select(func.count()).select_from(Document).where(Document.id.not_in(subquery))) or 0


def _active_politicians_without_committees(db: Session) -> int:
    subquery = select(CommitteeMembership.politician_id).distinct()
    return (
        db.scalar(
            select(func.count())
            .select_from(Politician)
            .where(Politician.is_active.is_(True), Politician.id.not_in(subquery))
        )
        or 0
    )


def _duplicate_count(db: Session, column) -> int:
    subquery = select(column).group_by(column).having(func.count() > 1).subquery()
    return db.scalar(select(func.count()).select_from(subquery)) or 0
