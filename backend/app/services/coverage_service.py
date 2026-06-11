"""Full data coverage report service.

Queries the database for all coverage metrics. Used by both the
/quality/full-coverage API endpoint and the full_coverage_report.py script.
"""
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models.bill import Bill
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
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
from app.models.vote_event import VoteEvent
from app.models.vote_record import VoteRecord


def generate_full_coverage_report(db: Session) -> dict:
    now = datetime.now(UTC).isoformat()

    total_politicians = _count(db, Politician)
    active_politicians = db.scalar(select(func.count()).select_from(Politician).where(Politician.is_active.is_(True))) or 0
    former_politicians = db.scalar(select(func.count()).select_from(Politician).where(Politician.source_status == "FORMER")) or 0

    politicians_with_party = db.scalar(
        select(func.count()).select_from(Politician).where(Politician.party_id.is_not(None))
    ) or 0
    politicians_without_party = total_politicians - politicians_with_party

    politicians_with_source_url = db.scalar(
        select(func.count()).select_from(Politician).where(Politician.profile_url.is_not(None))
    ) or 0
    politicians_without_source_url = total_politicians - politicians_with_source_url

    politicians_with_aliases = db.scalar(
        select(func.count()).select_from(Politician).where(
            Politician.id.in_(select(PoliticianAlias.politician_id).distinct())
        )
    ) or 0
    politicians_without_aliases = total_politicians - politicians_with_aliases

    politicians_with_committees = db.scalar(
        select(func.count()).select_from(Politician).where(
            Politician.id.in_(select(CommitteeMembership.politician_id).distinct())
        )
    ) or 0
    politicians_without_committees = total_politicians - politicians_with_committees

    total_parties = _count(db, Party)
    total_committees = _count(db, Committee)
    total_memberships = _count(db, CommitteeMembership)

    committees_without_memberships = db.scalar(
        select(func.count()).select_from(Committee).where(
            Committee.id.not_in(select(CommitteeMembership.committee_id).distinct())
        )
    ) or 0

    total_documents = _count(db, Document)
    pmg_documents = db.scalar(
        select(func.count()).select_from(Document).where(Document.document_type.like("PMG%"))
    ) or 0

    documents_with_archive = db.scalar(
        select(func.count()).select_from(Document).where(Document.archive_path.is_not(None))
    ) or 0
    documents_without_archive = total_documents - documents_with_archive

    docs_with_mentions = db.scalar(
        select(func.count()).select_from(Document).where(
            Document.id.in_(select(DocumentMention.document_id).distinct())
        )
    ) or 0
    docs_without_mentions = total_documents - docs_with_mentions

    total_mentions = _count(db, DocumentMention)
    low_confidence_mentions = db.scalar(
        select(func.count()).select_from(DocumentMention).where(DocumentMention.confidence_score < 0.8)
    ) or 0

    total_questions = _count(db, ParliamentaryQuestion)
    questions_with_archive = db.scalar(
        select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.archive_path.is_not(None))
    ) or 0
    questions_without_archive = total_questions - questions_with_archive

    questions_with_resolved_asker = db.scalar(
        select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.politician_id.is_not(None))
    ) or 0
    questions_with_unresolved_asker = total_questions - questions_with_resolved_asker

    total_question_mentions = _count(db, QuestionMention)

    pdf_questions = db.scalar(
        select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.source_file_type == "PDF")
    ) or 0
    questions_parse_ok = db.scalar(
        select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.parse_status == "PARSED")
    ) or 0
    questions_parse_failed = db.scalar(
        select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.parse_status == "FAILED")
    ) or 0

    total_unresolved = _count(db, UnresolvedEntity)
    unresolved_open = db.scalar(
        select(func.count()).select_from(UnresolvedEntity).where(UnresolvedEntity.status == "OPEN")
    ) or 0
    unresolved_resolved = db.scalar(
        select(func.count()).select_from(UnresolvedEntity).where(UnresolvedEntity.status == "RESOLVED")
    ) or 0
    unresolved_ignored = db.scalar(
        select(func.count()).select_from(UnresolvedEntity).where(UnresolvedEntity.status == "IGNORED")
    ) or 0

    unresolved_by_source: dict = {}
    for row in db.execute(
        select(UnresolvedEntity.source_name, func.count().label("cnt"))
        .group_by(UnresolvedEntity.source_name)
        .order_by(func.count().desc())
        .limit(20)
    ).all():
        unresolved_by_source[row[0]] = row[1]

    total_bills = _count(db, Bill)
    bills_with_source = db.scalar(select(func.count()).select_from(Bill).where(Bill.source_url.is_not(None))) or 0
    bills_introduced = db.scalar(select(func.count()).select_from(Bill).where(Bill.status == "introduced")) or 0
    bills_passed = db.scalar(select(func.count()).select_from(Bill).where(Bill.status == "passed")) or 0
    bills_assented = db.scalar(select(func.count()).select_from(Bill).where(Bill.status == "assented")) or 0

    total_vote_events = _count(db, VoteEvent)
    vote_events_with_source = db.scalar(select(func.count()).select_from(VoteEvent).where(VoteEvent.source_url.is_not(None))) or 0
    total_vote_records = _count(db, VoteRecord)
    individual_vote_records = db.scalar(select(func.count()).select_from(VoteRecord).where(VoteRecord.record_level == "individual")) or 0
    party_vote_records = db.scalar(select(func.count()).select_from(VoteRecord).where(VoteRecord.record_level == "party")) or 0

    total_committee_meetings = _count(db, CommitteeMeeting)
    meetings_with_source = db.scalar(select(func.count()).select_from(CommitteeMeeting).where(CommitteeMeeting.source_url.is_not(None))) or 0
    total_attendance = _count(db, CommitteeAttendance)
    resolved_attendance = db.scalar(select(func.count()).select_from(CommitteeAttendance).where(CommitteeAttendance.politician_id.is_not(None))) or 0

    total_ingestion_runs = _count(db, IngestionRun)
    failed_runs = db.scalar(
        select(func.count()).select_from(IngestionRun).where(IngestionRun.status == "failed")
    ) or 0

    latest_errors = [
        {
            "run_id": str(row.ingestion_run_id),
            "source_url": row.source_url,
            "error_message": (row.error_message or "")[:200],
        }
        for row in db.scalars(
            select(IngestionError).order_by(IngestionError.created_at.desc()).limit(20)
        )
    ]

    latest_runs = [
        {
            "id": str(r.id),
            "source_name": r.source_name,
            "run_type": r.run_type,
            "status": r.status,
            "started_at": r.started_at.isoformat() if r.started_at else None,
            "processed_count": r.processed_count,
            "created_count": r.created_count,
            "updated_count": r.updated_count,
            "failed_count": r.failed_count,
        }
        for r in db.scalars(
            select(IngestionRun).order_by(IngestionRun.started_at.desc()).limit(10)
        )
    ]

    dup_politician_slugs = _dup_count(db, Politician.slug)
    dup_committee_slugs = _dup_count(db, Committee.slug)
    dup_party_short = _dup_count(db, Party.short_name)
    dup_doc_source_urls = _dup_count(db, Document.source_url)
    dup_question_source_urls = _dup_count(db, ParliamentaryQuestion.source_url)

    active_without_source_url = db.scalar(
        select(func.count()).select_from(Politician).where(
            Politician.is_active.is_(True),
            Politician.profile_url.is_(None),
        )
    ) or 0
    weak_documents = db.scalar(
        select(func.count()).select_from(Document).where(
            Document.archive_path.is_(None),
            Document.raw_text.is_(None),
        )
    ) or 0

    source_coverage = [
        {
            "category": "politicians_total",
            "target_total": None,
            "ingested_total": total_politicians,
            "coverage_percent": None,
            "coverage_note": "Exact Parliament total not automatically verifiable.",
        },
        {
            "category": "active_politicians",
            "target_total": None,
            "ingested_total": active_politicians,
            "coverage_percent": None,
            "coverage_note": "Exact current NA+NCOP total not automatically verifiable.",
        },
        {
            "category": "committees",
            "target_total": None,
            "ingested_total": total_committees,
            "coverage_percent": None,
            "coverage_note": "Includes portfolio, standing, and other committees from People's Assembly.",
        },
        {
            "category": "committee_memberships",
            "target_total": None,
            "ingested_total": total_memberships,
            "coverage_percent": None,
            "coverage_note": "Derived from committee pages on People's Assembly.",
        },
        {
            "category": "pmg_meeting_documents",
            "target_total": None,
            "ingested_total": pmg_documents,
            "coverage_percent": None,
            "coverage_note": "PMG discovery is URL-driven; full PMG corpus is very large.",
        },
        {
            "category": "pmg_document_mentions",
            "target_total": None,
            "ingested_total": total_mentions,
            "coverage_percent": None,
            "coverage_note": "Mentions depend on alias coverage and resolution quality.",
        },
        {
            "category": "parliamentary_questions",
            "target_total": None,
            "ingested_total": total_questions,
            "coverage_percent": None,
            "coverage_note": "Parliament docsjson API used for discovery.",
        },
        {
            "category": "pdf_sources",
            "target_total": None,
            "ingested_total": pdf_questions,
            "coverage_percent": None,
            "coverage_note": "PDF-backed parliamentary question sources.",
        },
        {
            "category": "unresolved_entities_open",
            "target_total": None,
            "ingested_total": unresolved_open,
            "coverage_percent": None,
            "coverage_note": "Names needing manual review to link to politicians.",
        },
    ]

    recommendations = _build_recommendations(
        politicians_without_party=politicians_without_party,
        politicians_without_committees=politicians_without_committees,
        active_politicians=active_politicians,
        politicians_without_aliases=politicians_without_aliases,
        politicians_without_source_url=politicians_without_source_url,
        docs_without_mentions=docs_without_mentions,
        pmg_documents=pmg_documents,
        questions_without_archive=questions_without_archive,
        unresolved_open=unresolved_open,
        questions_parse_failed=questions_parse_failed,
        dup_politician_slugs=dup_politician_slugs,
        dup_doc_source_urls=dup_doc_source_urls,
    )

    return {
        "generated_at": now,
        "database_counts": {
            "politicians_total": total_politicians,
            "active_politicians_total": active_politicians,
            "former_politicians_total": former_politicians,
            "politicians_with_party": politicians_with_party,
            "politicians_without_party": politicians_without_party,
            "politicians_with_source_url": politicians_with_source_url,
            "politicians_without_source_url": politicians_without_source_url,
            "politicians_with_aliases": politicians_with_aliases,
            "politicians_without_aliases": politicians_without_aliases,
            "politicians_with_committees": politicians_with_committees,
            "politicians_without_committees": politicians_without_committees,
            "parties_total": total_parties,
            "committees_total": total_committees,
            "committee_memberships_total": total_memberships,
            "committees_without_memberships": committees_without_memberships,
            "documents_total": total_documents,
            "pmg_documents_total": pmg_documents,
            "documents_with_archive_path": documents_with_archive,
            "documents_without_archive_path": documents_without_archive,
            "documents_with_mentions": docs_with_mentions,
            "documents_without_mentions": docs_without_mentions,
            "document_mentions_total": total_mentions,
            "low_confidence_document_mentions": low_confidence_mentions,
            "parliamentary_questions_total": total_questions,
            "questions_with_archive_path": questions_with_archive,
            "questions_without_archive_path": questions_without_archive,
            "questions_with_resolved_asker": questions_with_resolved_asker,
            "questions_with_unresolved_asker": questions_with_unresolved_asker,
            "question_mentions_total": total_question_mentions,
            "pdf_sources_total": pdf_questions,
            "questions_parse_ok": questions_parse_ok,
            "questions_parse_failed": questions_parse_failed,
            "unresolved_entities_total": total_unresolved,
            "unresolved_entities_open": unresolved_open,
            "unresolved_entities_resolved": unresolved_resolved,
            "unresolved_entities_ignored": unresolved_ignored,
            "bills_total": total_bills,
            "bills_with_source_url": bills_with_source,
            "bills_introduced": bills_introduced,
            "bills_passed": bills_passed,
            "bills_assented": bills_assented,
            "vote_events_total": total_vote_events,
            "vote_events_with_source_url": vote_events_with_source,
            "vote_records_total": total_vote_records,
            "vote_records_individual": individual_vote_records,
            "vote_records_party": party_vote_records,
            "committee_meetings_total": total_committee_meetings,
            "committee_meetings_with_source_url": meetings_with_source,
            "committee_attendance_total": total_attendance,
            "committee_attendance_resolved": resolved_attendance,
            "ingestion_runs_total": total_ingestion_runs,
            "failed_ingestion_runs": failed_runs,
        },
        "source_coverage": source_coverage,
        "politician_coverage": {
            "total": total_politicians,
            "active": active_politicians,
            "former": former_politicians,
            "with_party_pct": _pct(politicians_with_party, total_politicians),
            "with_source_url_pct": _pct(politicians_with_source_url, total_politicians),
            "with_aliases_pct": _pct(politicians_with_aliases, total_politicians),
            "with_committees_pct": _pct(politicians_with_committees, total_politicians),
        },
        "party_coverage": {
            "total": total_parties,
        },
        "committee_coverage": {
            "total": total_committees,
            "memberships_total": total_memberships,
            "committees_without_memberships": committees_without_memberships,
        },
        "pmg_coverage": {
            "pmg_documents_total": pmg_documents,
            "with_archive_path_pct": _pct(documents_with_archive, pmg_documents),
            "with_mentions_pct": _pct(docs_with_mentions, pmg_documents),
            "total_mentions": total_mentions,
            "low_confidence_mentions": low_confidence_mentions,
        },
        "question_coverage": {
            "total": total_questions,
            "with_archive_pct": _pct(questions_with_archive, total_questions),
            "resolved_asker_pct": _pct(questions_with_resolved_asker, total_questions),
            "pdf_sources": pdf_questions,
            "parse_ok": questions_parse_ok,
            "parse_failed": questions_parse_failed,
        },
        "pdf_coverage": {
            "pdf_backed_questions": pdf_questions,
            "parse_ok": questions_parse_ok,
            "parse_failed": questions_parse_failed,
            "extracted_text_pct": _pct(questions_parse_ok, pdf_questions),
        },
        "archive_coverage": {
            "documents_with_archive_pct": _pct(documents_with_archive, total_documents),
            "questions_with_archive_pct": _pct(questions_with_archive, total_questions),
            "documents_without_archive": documents_without_archive,
            "questions_without_archive": questions_without_archive,
        },
        "unresolved_entity_coverage": {
            "total": total_unresolved,
            "open": unresolved_open,
            "resolved": unresolved_resolved,
            "ignored": unresolved_ignored,
            "by_source": unresolved_by_source,
        },
        "duplicate_candidates": {
            "duplicate_politician_slugs": dup_politician_slugs,
            "duplicate_committee_slugs": dup_committee_slugs,
            "duplicate_party_short_names": dup_party_short,
            "duplicate_document_source_urls": dup_doc_source_urls,
            "duplicate_question_source_urls": dup_question_source_urls,
        },
        "weak_records": {
            "active_politicians_without_source_url": active_without_source_url,
            "documents_without_archive_or_text": weak_documents,
        },
        "latest_ingestion_runs": latest_runs,
        "latest_ingestion_errors": latest_errors,
        "accountability_coverage": {
            "bills_total": total_bills,
            "bills_with_source_url_pct": _pct(bills_with_source, total_bills),
            "bills_introduced": bills_introduced,
            "bills_passed": bills_passed,
            "bills_assented": bills_assented,
            "vote_events_total": total_vote_events,
            "vote_records_total": total_vote_records,
            "vote_records_individual": individual_vote_records,
            "vote_records_party": party_vote_records,
            "committee_meetings_total": total_committee_meetings,
            "committee_attendance_total": total_attendance,
            "attendance_resolved_pct": _pct(resolved_attendance, total_attendance),
        },
        "recommendations": recommendations,
    }


def _build_recommendations(**kwargs) -> list[str]:
    recs = []
    if kwargs["politicians_without_party"] > 0:
        recs.append(f"{kwargs['politicians_without_party']} politicians have no party — run ingest_people_assembly_full.py.")
    if kwargs["politicians_without_committees"] > kwargs["active_politicians"] * 0.5 and kwargs["active_politicians"] > 0:
        recs.append("More than 50% of politicians have no committee — run ingest_committees_full.py.")
    if kwargs["politicians_without_aliases"] > 0:
        recs.append(f"{kwargs['politicians_without_aliases']} politicians have no aliases — run regenerate_aliases.py.")
    if kwargs["politicians_without_source_url"] > 0:
        recs.append(f"{kwargs['politicians_without_source_url']} politicians have no source URL — run ingest_people_assembly_full.py.")
    if kwargs["docs_without_mentions"] > kwargs["pmg_documents"] * 0.5 and kwargs["pmg_documents"] > 0:
        recs.append(f"{kwargs['docs_without_mentions']} PMG documents have no mentions — expand MP aliases then re-run PMG ingestion.")
    if kwargs["questions_without_archive"] > 0:
        recs.append(f"{kwargs['questions_without_archive']} questions have no archive path — re-ingest or investigate.")
    if kwargs["unresolved_open"] > 50:
        recs.append(f"{kwargs['unresolved_open']} unresolved entities are OPEN — run suggest_unresolved_matches.py.")
    if kwargs["questions_parse_failed"] > 0:
        recs.append(f"{kwargs['questions_parse_failed']} question PDFs failed to parse — check PDF extraction.")
    if kwargs["dup_politician_slugs"] > 0:
        recs.append(f"{kwargs['dup_politician_slugs']} duplicate politician slugs — investigate and deduplicate.")
    if kwargs["dup_doc_source_urls"] > 0:
        recs.append(f"{kwargs['dup_doc_source_urls']} duplicate document source URLs — investigate.")
    if not recs:
        recs.append("No critical issues. Continue expanding ingestion coverage.")
    return recs


def _count(db: Session, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _dup_count(db: Session, column) -> int:
    subquery = select(column).group_by(column).having(func.count() > 1).subquery()
    return db.scalar(select(func.count()).select_from(subquery)) or 0


def _pct(numerator: int, denominator: int) -> float | None:
    if not denominator:
        return None
    return round(numerator / denominator * 100, 1)
