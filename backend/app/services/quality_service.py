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
        "unknown_status_politicians": db.scalar(
            select(func.count()).select_from(Politician).where(
                (Politician.source_status.is_(None)) | (Politician.source_status == "UNKNOWN")
            )
        )
        or 0,
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
        "total_unresolved_entities": _count(db, UnresolvedEntity),
        "unresolved_entities_open": _unresolved_status_count(db, "OPEN"),
        "unresolved_entities_resolved": _unresolved_status_count(db, "RESOLVED"),
        "unresolved_entities_ignored": _unresolved_status_count(db, "IGNORED"),
        "politicians_without_party": db.scalar(select(func.count()).select_from(Politician).where(Politician.party_id.is_(None))) or 0,
        "politicians_without_committees": _politicians_without_child(db, CommitteeMembership),
        "active_politicians_without_committees": _active_politicians_without_committees(db),
        "committees_without_memberships": _committees_without_memberships(db),
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
        "duplicate_politician_slug_count": _duplicate_count(db, Politician.slug),
        "duplicate_committee_slug_count": _duplicate_count(db, Committee.slug),
        "duplicate_party_short_name_count": _duplicate_count(db, Party.short_name),
        "duplicate_membership_candidates": _duplicate_membership_candidates(db),
        "duplicate_source_url_count": _duplicate_count(db, Document.source_url),
    }


def quality_issues(db: Session, limit: int = 100) -> dict[str, list[dict]]:
    return {
        "politicians_without_party": [
            _politician_item(item)
            for item in db.scalars(select(Politician).where(Politician.party_id.is_(None)).order_by(Politician.display_name).limit(limit))
        ],
        "active_politicians_without_committees": [
            _politician_item(item)
            for item in db.scalars(
                select(Politician)
                .where(Politician.is_active.is_(True), Politician.id.not_in(select(CommitteeMembership.politician_id).distinct()))
                .order_by(Politician.display_name)
                .limit(limit)
            )
        ],
        "committees_without_memberships": [
            _committee_item(item)
            for item in db.scalars(
                select(Committee)
                .where(Committee.id.not_in(select(CommitteeMembership.committee_id).distinct()))
                .order_by(Committee.name)
                .limit(limit)
            )
        ],
        "documents_without_mentions": [
            {"id": str(item.id), "title": item.title, "source_url": item.source_url}
            for item in db.scalars(
                select(Document)
                .where(Document.id.not_in(select(DocumentMention.document_id).distinct()))
                .order_by(Document.title)
                .limit(limit)
            )
        ],
        "unresolved_entities_open": [
            {
                "id": str(item.id),
                "raw_value": item.raw_value,
                "entity_type": item.entity_type,
                "source_name": item.source_name,
                "source_url": item.source_url,
            }
            for item in db.scalars(
                select(UnresolvedEntity)
                .where(UnresolvedEntity.status == "OPEN")
                .order_by(UnresolvedEntity.created_at.desc())
                .limit(limit)
            )
        ],
        "duplicate_politician_slugs": _duplicate_values(db, Politician.slug, limit),
        "duplicate_committee_slugs": _duplicate_values(db, Committee.slug, limit),
        "duplicate_party_short_names": _duplicate_values(db, Party.short_name, limit),
    }


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _politicians_without_child(db: Session, child_model) -> int:
    subquery = select(child_model.politician_id).distinct()
    return db.scalar(select(func.count()).select_from(Politician).where(Politician.id.not_in(subquery))) or 0


def _documents_without_mentions(db: Session) -> int:
    subquery = select(DocumentMention.document_id).distinct()
    return db.scalar(select(func.count()).select_from(Document).where(Document.id.not_in(subquery))) or 0


def _committees_without_memberships(db: Session) -> int:
    subquery = select(CommitteeMembership.committee_id).distinct()
    return db.scalar(select(func.count()).select_from(Committee).where(Committee.id.not_in(subquery))) or 0


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


def _unresolved_status_count(db: Session, status: str) -> int:
    return db.scalar(select(func.count()).select_from(UnresolvedEntity).where(UnresolvedEntity.status == status)) or 0


def _duplicate_membership_candidates(db: Session) -> int:
    subquery = (
        select(CommitteeMembership.politician_id, CommitteeMembership.committee_id, CommitteeMembership.role)
        .group_by(CommitteeMembership.politician_id, CommitteeMembership.committee_id, CommitteeMembership.role)
        .having(func.count() > 1)
        .subquery()
    )
    return db.scalar(select(func.count()).select_from(subquery)) or 0


def _duplicate_values(db: Session, column, limit: int) -> list[dict]:
    rows = db.execute(
        select(column, func.count().label("count")).group_by(column).having(func.count() > 1).limit(limit)
    ).all()
    return [{"value": value, "count": count} for value, count in rows]


def _politician_item(item: Politician) -> dict:
    return {
        "id": str(item.id),
        "display_name": item.display_name,
        "slug": item.slug,
        "profile_url": item.profile_url,
        "source_status": item.source_status,
    }


def _committee_item(item: Committee) -> dict:
    return {"id": str(item.id), "name": item.name, "slug": item.slug, "source_url": item.source_url}
