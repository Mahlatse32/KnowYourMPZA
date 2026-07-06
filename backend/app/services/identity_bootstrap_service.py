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
from app.services.entity_resolution import alias_values_for_politician

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
        "politicians_party_enriched": 0,
        "aliases_created": 0,
        "meetings_linked": 0,
        "attendance_linked": 0,
        "memberships_created": 0,
        "questions_linked": 0,
        "question_mentions_created": 0,
        "vote_events_linked": 0,
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
    _link_memberships_from_attendance(db, summary)
    _link_questions(db, summary)
    _link_vote_events(db, summary)
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
    candidates: dict[str, tuple[str, str | None]] = {}
    # Distinct explicit party ids seen per person slug across attendance rows.
    # A party is propagated to a politician only when it is unambiguous —
    # exactly one real party across every explicit source record. Conflicting
    # source data is never resolved by guessing.
    parties_seen: dict[str, set] = {}
    parties_by_id = {party.id: party for party in db.scalars(select(Party))}
    politicians_by_slug = {politician.slug: politician for politician in db.scalars(select(Politician))}
    existing_alias_keys = {
        (alias.politician_id, alias.alias)
        for alias in db.scalars(select(PoliticianAlias))
    }

    attendance_rows = db.execute(
        select(CommitteeAttendance.name_raw, CommitteeAttendance.source_url, CommitteeAttendance.party_id)
        .where(CommitteeAttendance.name_raw.is_not(None), CommitteeAttendance.name_raw != "")
        .order_by(CommitteeAttendance.name_raw)
    )
    for raw_name, source_url, party_id in attendance_rows:
        name = normalize_pmg_person_name(raw_name or "")
        if not name:
            continue
        slug = create_slug(name)
        candidates.setdefault(slug, (name, source_url))
        if party_id is not None and party_id in parties_by_id and party_id != unknown_party.id:
            parties_seen.setdefault(slug, set()).add(party_id)

    question_rows = db.execute(
        select(ParliamentaryQuestion.asked_by_name, func.min(ParliamentaryQuestion.source_url))
        .where(ParliamentaryQuestion.asked_by_name.is_not(None), ParliamentaryQuestion.asked_by_name != "")
        .group_by(ParliamentaryQuestion.asked_by_name)
    )
    for raw_name, source_url in question_rows:
        name = normalize_pmg_person_name(raw_name or "")
        if not name:
            continue
        candidates.setdefault(create_slug(name), (name, source_url))

    for slug, (name, source_url) in sorted(candidates.items()):
        seen = parties_seen.get(slug, set())
        explicit_party = parties_by_id[next(iter(seen))] if len(seen) == 1 else None
        party = explicit_party or unknown_party
        politician = politicians_by_slug.get(slug)
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
            politicians_by_slug[slug] = politician
            summary["politicians_created"] += 1
        else:
            if politician.party_id is None:
                politician.party = party
            elif explicit_party is not None and politician.party_id == unknown_party.id:
                # Replace only the Unknown fallback with unambiguous explicit
                # source data; a real party is never overwritten here.
                politician.party = explicit_party
                summary["politicians_party_enriched"] += 1
            if not politician.profile_url and source_url:
                politician.profile_url = source_url
            if not politician.source_status:
                politician.source_status = PMG_DERIVED_STATUS
            politician.source_last_seen_at = datetime.now(UTC)
            summary["politicians_updated"] += 1
        summary["aliases_created"] += _ensure_aliases(db, politician, source_url, existing_alias_keys)


def _link_meetings(db: Session, summary: dict[str, int]) -> None:
    # Strategy 1: meeting has a summary_document_id whose document carries committee_name.
    rows = db.execute(
        select(CommitteeMeeting, Document.committee_name)
        .join(Document, CommitteeMeeting.summary_document_id == Document.id)
        .where(CommitteeMeeting.committee_id.is_(None), Document.committee_name.is_not(None))
    )
    for meeting, raw_committee_name in rows:
        _link_meeting_to_committee(db, meeting, raw_committee_name, summary)

    # Strategy 2: meeting source_url matches a document source_url that carries committee_name.
    rows = db.execute(
        select(CommitteeMeeting, Document.committee_name)
        .join(Document, CommitteeMeeting.source_url == Document.source_url)
        .where(
            CommitteeMeeting.committee_id.is_(None),
            CommitteeMeeting.source_url.is_not(None),
            Document.committee_name.is_not(None),
        )
    )
    for meeting, raw_committee_name in rows:
        _link_meeting_to_committee(db, meeting, raw_committee_name, summary)

    # Strategy 3: meeting has committee_name stored directly (from API ingestion).
    # This column was added by migration 0014; pre-existing rows will have NULL.
    for meeting in db.scalars(
        select(CommitteeMeeting).where(
            CommitteeMeeting.committee_id.is_(None),
            CommitteeMeeting.committee_name.is_not(None),
        )
    ):
        _link_meeting_to_committee(db, meeting, meeting.committee_name, summary)

    # Strategy 4: title-based extraction for remaining unlinked meetings.
    # Handles titles like "Portfolio Committee on Finance: Budget Vote 8" where
    # the committee name precedes the first colon, and substring matches for
    # titles that embed a known committee name.
    unlinked = list(
        db.scalars(
            select(CommitteeMeeting).where(CommitteeMeeting.committee_id.is_(None))
        )
    )
    if not unlinked:
        return
    committees = sorted(
        db.scalars(select(Committee).where(Committee.name.is_not(None))).all(),
        key=lambda c: len(c.name or ""),
        reverse=True,
    )
    if not committees:
        return
    for meeting in unlinked:
        title = (meeting.title or "").strip()
        if not title:
            continue
        # Try the text before the first colon as a committee name candidate.
        if ":" in title:
            candidate = title.split(":", 1)[0].strip()
            if len(candidate) >= 4:
                committee = _resolve_committee(db, candidate)
                if committee is not None:
                    meeting.committee_id = committee.id
                    summary["meetings_linked"] += 1
                    continue
        # Substring match: check if any known committee name appears in the title.
        title_lower = title.lower()
        for committee in committees:
            name = (committee.name or "").lower()
            normalized = normalize_committee_name(committee.name or "").lower()
            candidates = [c for c in {name, normalized} if len(c) >= 6]
            if any(c in title_lower for c in candidates):
                meeting.committee_id = committee.id
                summary["meetings_linked"] += 1
                break


def _link_meeting_to_committee(db: Session, meeting: CommitteeMeeting, raw_committee_name: str | None, summary: dict[str, int]) -> None:
    if meeting.committee_id is not None:
        return
    committee = _resolve_committee(db, raw_committee_name)
    if committee is None:
        return
    meeting.committee_id = committee.id
    summary["meetings_linked"] += 1


def _link_attendance(db: Session, summary: dict[str, int]) -> None:
    politician_index = _politician_index(db)
    membership_keys = {
        (membership.politician_id, membership.committee_id, membership.role)
        for membership in db.scalars(select(CommitteeMembership))
    }
    rows = db.scalars(
        select(CommitteeAttendance)
        .join(CommitteeMeeting, CommitteeAttendance.meeting_id == CommitteeMeeting.id)
        .where(CommitteeAttendance.politician_id.is_(None))
    )
    for record in rows:
        politician = _resolve_from_index(politician_index, normalize_pmg_person_name(record.name_raw) or record.name_raw)
        if politician is None:
            continue
        record.politician_id = politician.id
        record.confidence = max(record.confidence or 0, 0.99)
        summary["attendance_linked"] += 1
        if record.meeting.committee_id:
            if _ensure_membership(db, politician, record.meeting.committee, record.source_url, membership_keys):
                summary["memberships_created"] += 1


def _link_memberships_from_attendance(db: Session, summary: dict[str, int]) -> None:
    membership_keys = {
        (membership.politician_id, membership.committee_id, membership.role)
        for membership in db.scalars(select(CommitteeMembership))
    }
    rows = db.scalars(
        select(CommitteeAttendance)
        .join(CommitteeMeeting, CommitteeAttendance.meeting_id == CommitteeMeeting.id)
        .where(
            CommitteeAttendance.politician_id.is_not(None),
            CommitteeMeeting.committee_id.is_not(None),
        )
    )
    for record in rows:
        if record.politician is None or record.meeting.committee is None:
            continue
        if _ensure_membership(db, record.politician, record.meeting.committee, record.source_url, membership_keys):
            summary["memberships_created"] += 1


def _link_questions(db: Session, summary: dict[str, int]) -> None:
    politician_index = _politician_index(db)
    questions = db.scalars(
        select(ParliamentaryQuestion).where(ParliamentaryQuestion.politician_id.is_(None))
    )
    for question in questions:
        unique_mention = _unique_question_mention_politician(db, question)
        if unique_mention is not None:
            question.politician_id = unique_mention.id
            summary["questions_linked"] += 1
            continue
        if not question.asked_by_name:
            continue
        politician = _resolve_from_index(
            politician_index,
            normalize_pmg_person_name(question.asked_by_name or "") or question.asked_by_name or "",
        )
        if politician is None:
            continue
        question.politician_id = politician.id
        summary["questions_linked"] += 1
        if _ensure_question_mention(db, question, politician, 0.99):
            summary["question_mentions_created"] += 1


def _link_vote_events(db: Session, summary: dict[str, int]) -> None:
    from app.models.vote_event import VoteEvent

    rows = db.execute(
        select(VoteEvent, CommitteeMeeting.committee_id)
        .join(CommitteeMeeting, VoteEvent.source_url == CommitteeMeeting.source_url)
        .where(
            VoteEvent.committee_id.is_(None),
            VoteEvent.source_url.is_not(None),
            CommitteeMeeting.committee_id.is_not(None),
        )
    )
    for event, committee_id in rows:
        event.committee_id = committee_id
        summary["vote_events_linked"] += 1

    committees = sorted(
        list(db.scalars(select(Committee).where(Committee.name.is_not(None)))),
        key=lambda committee: len(committee.name or ""),
        reverse=True,
    )
    if not committees:
        return

    for event in db.scalars(select(VoteEvent).where(VoteEvent.committee_id.is_(None))):
        title = (event.title or "").lower()
        if not title:
            continue
        for committee in committees:
            name = (committee.name or "").lower()
            normalized = normalize_committee_name(committee.name or "").lower()
            candidates = [candidate for candidate in {name, normalized} if len(candidate) >= 4]
            if any(candidate in title for candidate in candidates):
                event.committee_id = committee.id
                summary["vote_events_linked"] += 1
                break


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


def _ensure_membership(
    db: Session,
    politician: Politician,
    committee: Committee,
    source_url: str | None,
    membership_keys: set[tuple],
) -> bool:
    key = (politician.id, committee.id, "Member")
    if key in membership_keys:
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
    membership_keys.add(key)
    return True


def _unique_question_mention_politician(db: Session, question: ParliamentaryQuestion) -> Politician | None:
    politician_ids = list(
        db.scalars(
            select(QuestionMention.politician_id)
            .where(QuestionMention.question_id == question.id)
            .distinct()
        )
    )
    if len(politician_ids) != 1:
        return None
    return db.get(Politician, politician_ids[0])


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


def _ensure_aliases(
    db: Session,
    politician: Politician,
    source_url: str | None,
    existing_alias_keys: set[tuple] | None = None,
) -> int:
    if existing_alias_keys is None:
        existing_alias_keys = {
            (alias.politician_id, alias.alias)
            for alias in db.scalars(select(PoliticianAlias))
        }
    created = 0
    for alias, alias_type in alias_values_for_politician(politician):
        key = (politician.id, alias)
        if key not in existing_alias_keys:
            db.add(
                PoliticianAlias(
                    politician=politician,
                    alias=alias,
                    alias_type=alias_type,
                    source_url=source_url,
                )
            )
            existing_alias_keys.add(key)
            created += 1
    return created


def _politician_index(db: Session) -> dict[str, Politician]:
    index: dict[str, Politician] = {}
    politicians = list(db.scalars(select(Politician)))
    politicians_by_id = {politician.id: politician for politician in politicians}
    for politician in politicians:
        for value in (politician.full_name, politician.display_name, politician.slug):
            if value:
                index.setdefault(value.lower(), politician)
        normalized = normalize_pmg_person_name(politician.full_name)
        if normalized:
            index.setdefault(create_slug(normalized), politician)
    for alias in db.scalars(select(PoliticianAlias)):
        if alias.alias and alias.alias_type != "SURNAME_ONLY":
            politician = politicians_by_id.get(alias.politician_id)
            if politician is not None:
                index.setdefault(alias.alias.lower(), politician)
    return index


def _resolve_from_index(index: dict[str, Politician], raw_name: str) -> Politician | None:
    value = " ".join(raw_name.strip().split())
    if not value:
        return None
    return index.get(value.lower()) or index.get(create_slug(value))


def normalize_pmg_person_name(value: str) -> str | None:
    clean = " ".join(str(value).replace("\xa0", " ").split()).strip(" ,.;:-")
    if not clean:
        return None
    clean = re.sub(r"\([^)]*\)", " ", clean)
    clean = " ".join(clean.split()).strip(" ,.;:-")
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
