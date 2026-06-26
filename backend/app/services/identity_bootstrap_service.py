"""Bootstrap identity rows from already-ingested PMG-derived data.

People's Assembly remains an enrichment source. This service is a production
resilience path for the identity tables when PA access is blocked: it creates
minimal, source-attributed politician and committee records from explicit PMG
fields already present in the database, then links dependent rows where exact
resolution is available.
"""
import re
from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.ingestion.people_assembly import create_slug, normalize_committee_name
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_membership import CommitteeMembership
from app.models.committee_meeting import CommitteeMeeting
from app.models.document import Document
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.question_mention import QuestionMention
from app.models.source import Source
from app.services.entity_resolution import alias_values_for_politician, resolve_politician_name

PMG_SOURCE_NAME = "PMG"
PMG_DERIVED_STATUS = "PMG_DERIVED"
UNKNOWN_PARTY = {
    "name": "Unknown",
    "short_name": "UNKNOWN",
    "source_url": "https://pmg.org.za/",
}

_HONORIFICS = {
    "adv",
    "advocate",
    "dr",
    "hon",
    "honourable",
    "miss",
    "mr",
    "mrs",
    "ms",
    "prof",
    "professor",
}
_NON_PERSON_PARTS = {
    "apology",
    "apologies",
    "chairperson",
    "department",
    "minister",
    "national assembly",
    "none",
    "present",
    "unknown",
}


def bootstrap_identities_from_pmg(db: Session) -> dict[str, int]:
    """Create/link minimal identity records from existing PMG-derived rows.

    The operation is idempotent. It does not fabricate party affiliation; rows
    without an existing party link are assigned to a clearly marked Unknown
    party so the politician table can satisfy its non-null FK.
    """
    summary = {
        "sources_created": 0,
        "parties_created": 0,
        "committees_created": 0,
        "committees_updated": 0,
        "politicians_created": 0,
        "politicians_updated": 0,
        "aliases_created": 0,
        "meetings_linked": 0,
        "attendance_linked": 0,
        "memberships_created": 0,
        "questions_linked": 0,
        "question_mentions_created": 0,
    }

    _, source_created = _ensure_pmg_source(db)
    summary["sources_created"] += int(source_created)
    unknown_party, party_created = _ensure_unknown_party(db)
    summary["parties_created"] += int(party_created)
    db.flush()

    _bootstrap_committees(db, summary)
    _bootstrap_politicians(db, unknown_party, summary)
    db.flush()
    _link_meetings(db, summary)
    _link_attendance(db, summary)
    _link_questions(db, summary)
    db.commit()
    return summary


def estimate_pmg_identity_bootstrap_attempts(db: Session) -> int:
    """Return the number of raw identity hints the bootstrap will inspect."""
    committee_names = db.scalar(
        select(func.count(func.distinct(Document.committee_name))).where(
            Document.committee_name.is_not(None),
            Document.committee_name != "",
        )
    ) or 0
    attendance_names = db.scalar(
        select(func.count(func.distinct(CommitteeAttendance.name_raw))).where(
            CommitteeAttendance.name_raw.is_not(None),
            CommitteeAttendance.name_raw != "",
        )
    ) or 0
    question_names = db.scalar(
        select(func.count(func.distinct(ParliamentaryQuestion.asked_by_name))).where(
            ParliamentaryQuestion.asked_by_name.is_not(None),
            ParliamentaryQuestion.asked_by_name != "",
        )
    ) or 0
    return int(committee_names) + int(attendance_names) + int(question_names)


def _ensure_pmg_source(db: Session) -> tuple[Source, bool]:
    source = db.scalar(select(Source).where(Source.name == PMG_SOURCE_NAME))
    if source is not None:
        return source, False
    source = Source(
        name=PMG_SOURCE_NAME,
        base_url="https://pmg.org.za/",
        source_type="parliamentary_monitoring",
        reliability_score=0.9,
    )
    db.add(source)
    return source, True


def _ensure_unknown_party(db: Session) -> tuple[Party, bool]:
    party = db.scalar(select(Party).where(Party.short_name == UNKNOWN_PARTY["short_name"]))
    if party is not None:
        if not party.source_url:
            party.source_url = UNKNOWN_PARTY["source_url"]
        return party, False
    party = Party(
        name=UNKNOWN_PARTY["name"],
        short_name=UNKNOWN_PARTY["short_name"],
        source_url=UNKNOWN_PARTY["source_url"],
        source_last_seen_at=datetime.now(UTC),
    )
    db.add(party)
    return party, True


def _bootstrap_committees(db: Session, summary: dict[str, int]) -> None:
    rows = db.execute(
        select(Document.committee_name, func.min(Document.source_url))
        .where(Document.committee_name.is_not(None), Document.committee_name != "")
        .group_by(Document.committee_name)
    )
    for raw_name, source_url in rows:
        committee_name = normalize_committee_name(raw_name or "")
        if not committee_name:
            continue
        slug = create_slug(committee_name)
        committee = db.scalar(select(Committee).where(Committee.slug == slug))
        if committee is None:
            db.add(
                Committee(
                    name=committee_name,
                    slug=slug,
                    description="Committee bootstrapped from PMG document metadata.",
                    source_url=source_url,
                    source_last_seen_at=datetime.now(UTC),
                )
            )
            summary["committees_created"] += 1
        else:
            if not committee.source_url and source_url:
                committee.source_url = source_url
            committee.source_last_seen_at = datetime.now(UTC)
            summary["committees_updated"] += 1


def _bootstrap_politicians(db: Session, unknown_party: Party, summary: dict[str, int]) -> None:
    candidates: dict[str, tuple[str, str | None, Party]] = {}

    attendance_rows = db.execute(
        select(CommitteeAttendance.name_raw, CommitteeAttendance.source_url, CommitteeAttendance.party_id)
        .where(CommitteeAttendance.name_raw.is_not(None), CommitteeAttendance.name_raw != "")
        .order_by(CommitteeAttendance.name_raw)
    )
    for raw_name, source_url, party_id in attendance_rows:
        name = normalize_pmg_person_name(raw_name or "")
        if not name:
            continue
        party = db.get(Party, party_id) if party_id else None
        candidates.setdefault(create_slug(name), (name, source_url, party or unknown_party))

    question_rows = db.execute(
        select(ParliamentaryQuestion.asked_by_name, func.min(ParliamentaryQuestion.source_url))
        .where(ParliamentaryQuestion.asked_by_name.is_not(None), ParliamentaryQuestion.asked_by_name != "")
        .group_by(ParliamentaryQuestion.asked_by_name)
    )
    for raw_name, source_url in question_rows:
        name = normalize_pmg_person_name(raw_name or "")
        if not name:
            continue
        candidates.setdefault(create_slug(name), (name, source_url, unknown_party))

    for slug, (name, source_url, party) in sorted(candidates.items()):
        politician = db.scalar(select(Politician).where(Politician.slug == slug))
        if politician is None:
            politician = Politician(
                full_name=name,
                display_name=_display_name(name),
                slug=slug,
                party=party,
                profile_url=source_url,
                is_active=True,
                source_last_seen_at=datetime.now(UTC),
                source_status=PMG_DERIVED_STATUS,
            )
            db.add(politician)
            db.flush()
            summary["politicians_created"] += 1
        else:
            if politician.party_id is None:
                politician.party = party
            if not politician.profile_url and source_url:
                politician.profile_url = source_url
            if not politician.source_status:
                politician.source_status = PMG_DERIVED_STATUS
            politician.source_last_seen_at = datetime.now(UTC)
            summary["politicians_updated"] += 1
        summary["aliases_created"] += _ensure_aliases(db, politician, source_url)


def _link_meetings(db: Session, summary: dict[str, int]) -> None:
    rows = db.execute(
        select(CommitteeMeeting, Document.committee_name)
        .join(Document, CommitteeMeeting.summary_document_id == Document.id)
        .where(CommitteeMeeting.committee_id.is_(None), Document.committee_name.is_not(None))
    )
    for meeting, raw_committee_name in rows:
        committee = _resolve_committee(db, raw_committee_name)
        if committee is None:
            continue
        meeting.committee_id = committee.id
        summary["meetings_linked"] += 1


def _link_attendance(db: Session, summary: dict[str, int]) -> None:
    rows = db.scalars(
        select(CommitteeAttendance)
        .join(CommitteeMeeting, CommitteeAttendance.meeting_id == CommitteeMeeting.id)
        .where(CommitteeAttendance.politician_id.is_(None))
    )
    for record in rows:
        resolution = resolve_politician_name(db, normalize_pmg_person_name(record.name_raw) or record.name_raw)
        if resolution is None:
            continue
        record.politician_id = resolution.politician.id
        record.confidence = max(record.confidence or 0, resolution.confidence_score)
        summary["attendance_linked"] += 1
        if record.meeting.committee_id:
            if _ensure_membership(db, resolution.politician, record.meeting.committee, record.source_url):
                summary["memberships_created"] += 1


def _link_questions(db: Session, summary: dict[str, int]) -> None:
    questions = db.scalars(
        select(ParliamentaryQuestion).where(
            ParliamentaryQuestion.politician_id.is_(None),
            ParliamentaryQuestion.asked_by_name.is_not(None),
            ParliamentaryQuestion.asked_by_name != "",
        )
    )
    for question in questions:
        resolution = resolve_politician_name(db, normalize_pmg_person_name(question.asked_by_name or "") or question.asked_by_name or "")
        if resolution is None:
            continue
        question.politician_id = resolution.politician.id
        summary["questions_linked"] += 1
        if _ensure_question_mention(db, question, resolution.politician, resolution.confidence_score):
            summary["question_mentions_created"] += 1


def _resolve_committee(db: Session, raw_name: str | None) -> Committee | None:
    if not raw_name:
        return None
    normalized = normalize_committee_name(raw_name)
    slug = create_slug(normalized)
    return db.scalar(
        select(Committee).where(
            (Committee.slug == slug)
            | (func.lower(Committee.name) == normalized.lower())
            | (func.lower(Committee.name) == raw_name.lower())
        )
    )


def _ensure_membership(db: Session, politician: Politician, committee: Committee, source_url: str | None) -> bool:
    existing = db.scalar(
        select(CommitteeMembership).where(
            CommitteeMembership.politician_id == politician.id,
            CommitteeMembership.committee_id == committee.id,
            CommitteeMembership.role == "Member",
        )
    )
    if existing is not None:
        if source_url and not existing.source_url:
            existing.source_url = source_url
        existing.source_last_seen_at = datetime.now(UTC)
        return False
    db.add(
        CommitteeMembership(
            politician=politician,
            committee=committee,
            role="Member",
            source_url=source_url or committee.source_url or "https://pmg.org.za/",
            source_last_seen_at=datetime.now(UTC),
            source_status=PMG_DERIVED_STATUS,
        )
    )
    return True


def _ensure_question_mention(
    db: Session,
    question: ParliamentaryQuestion,
    politician: Politician,
    confidence: float,
) -> bool:
    existing = db.scalar(
        select(QuestionMention).where(
            QuestionMention.question_id == question.id,
            QuestionMention.politician_id == politician.id,
        )
    )
    if existing is not None:
        existing.confidence_score = max(existing.confidence_score or 0, confidence)
        return False
    db.add(
        QuestionMention(
            question=question,
            politician=politician,
            snippet=f"{question.asked_by_name} asked this parliamentary question.",
            confidence_score=confidence,
            match_reason=PMG_DERIVED_STATUS,
        )
    )
    return True


def _ensure_aliases(db: Session, politician: Politician, source_url: str | None) -> int:
    created = 0
    for alias, alias_type in alias_values_for_politician(politician):
        existing = db.scalar(
            select(PoliticianAlias).where(
                PoliticianAlias.politician_id == politician.id,
                PoliticianAlias.alias == alias,
            )
        )
        if existing is None:
            db.add(
                PoliticianAlias(
                    politician=politician,
                    alias=alias,
                    alias_type=alias_type,
                    source_url=source_url,
                )
            )
            created += 1
    return created


def normalize_pmg_person_name(value: str) -> str | None:
    clean = " ".join(str(value).replace("\xa0", " ").split()).strip(" ,.;:-")
    if not clean:
        return None
    lowered = clean.lower()
    if lowered in _NON_PERSON_PARTS:
        return None
    if re.search(r"\b(committee|department|parliamentary|secretary|staff|team)\b", lowered):
        return None

    if "," in clean:
        surname, rest = [part.strip() for part in clean.split(",", 1)]
        rest_parts = [_strip_token(part) for part in rest.split()]
        initials = [part for part in rest_parts if part and part.lower() not in _HONORIFICS]
        first = " ".join(initials)
        clean = f"{first} {surname}".strip() if first else surname
    else:
        parts = [_strip_token(part) for part in clean.split()]
        parts = [part for part in parts if part and part.lower() not in _HONORIFICS]
        clean = " ".join(parts)

    clean = re.sub(r"\s+", " ", clean).strip(" ,.;:-")
    if len(clean) < 3 or not re.search(r"[A-Za-z]", clean):
        return None
    return clean.title()


def _display_name(full_name: str) -> str:
    parts = full_name.split()
    if len(parts) <= 2:
        return full_name
    return f"{parts[0]} {parts[-1]}"


def _strip_token(value: str) -> str:
    return value.strip("()[]{}.,;:")
