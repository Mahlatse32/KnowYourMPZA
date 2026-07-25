from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, joinedload

from app.config import settings
from app.models.ai_answer import AiAnswer
from app.models.bill import Bill
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.models.vote_event import VoteEvent


MAX_SOURCES = 8
MAX_EXCERPT_CHARS = 260
AI_ANSWER_FORMAT_VERSION = 2


@dataclass
class RetrievedEvidence:
    intent: str
    sources: list[dict[str, Any]]
    coverage_notice: str


def normalize_question(question: str) -> str:
    normalized = re.sub(r"\s+", " ", question.strip().lower())
    return normalized[:500]


def answer_question(db: Session, question: str, refresh: bool = False) -> tuple[AiAnswer, bool]:
    normalized = normalize_question(question)
    snapshot = _data_snapshot(db)
    cached = db.scalars(select(AiAnswer).where(AiAnswer.normalized_question == normalized)).first()
    if cached and not refresh and cached.data_snapshot == snapshot:
        return cached, True

    evidence = retrieve_evidence(db, question)
    fallback_answer = _build_deterministic_answer(question, evidence)
    answer_text, model_used = _ask_openai(question, evidence, fallback_answer)
    if not evidence.sources:
        answer_text = fallback_answer

    if cached is None:
        cached = AiAnswer(normalized_question=normalized, question=question)
        db.add(cached)

    cached.question = question
    cached.answer = answer_text
    cached.intent = evidence.intent
    cached.sources = evidence.sources
    cached.data_snapshot = snapshot
    cached.model_used = model_used
    cached.coverage_notice = evidence.coverage_notice
    db.commit()
    db.refresh(cached)
    return cached, False


def retrieve_evidence(db: Session, question: str) -> RetrievedEvidence:
    terms = _search_terms(question)
    intent = _classify_intent(question)
    if intent == "questions":
        sources = _question_sources(db, terms)
    elif intent == "committees":
        sources = _committee_sources(db, terms)
    elif intent == "bills":
        sources = _bill_sources(db, terms)
    elif intent == "votes":
        sources = _vote_sources(db, terms)
    elif intent == "attendance":
        sources = _attendance_sources(db, terms)
    else:
        sources = _politician_sources(db, terms)
        if len(sources) < 3:
            sources.extend(_question_sources(db, terms, limit=MAX_SOURCES - len(sources)))

    sources = sources[:MAX_SOURCES]
    return RetrievedEvidence(
        intent=intent,
        sources=sources,
        coverage_notice=_coverage_notice(intent, bool(sources)),
    )


def _ask_openai(question: str, evidence: RetrievedEvidence, fallback_answer: str) -> tuple[str, str]:
    if not settings.openai_api_key:
        return fallback_answer, "deterministic-source-summary"

    payload = {
        "model": settings.openai_model,
        "input": [
            {
                "role": "system",
                "content": (
                    "You are KnowYourMPZA's civic evidence assistant. Answer only from the supplied records. "
                    "Do not add facts that are not present. If evidence is incomplete, say so plainly. "
                    "Keep the answer concise and mention that sources are attached."
                ),
            },
            {
                "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Intent: {evidence.intent}\n"
                    f"Coverage notice: {evidence.coverage_notice}\n"
                    f"Records: {evidence.sources}"
                ),
            },
        ],
    }
    try:
        with httpx.Client(timeout=30) as client:
            response = client.post(
                f"{settings.openai_base_url.rstrip('/')}/responses",
                headers={
                    "Authorization": f"Bearer {settings.openai_api_key}",
                    "Content-Type": "application/json",
                },
                json=payload,
            )
            response.raise_for_status()
            body = response.json()
    except Exception:
        return fallback_answer, "deterministic-source-summary"

    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip(), settings.openai_model
    for item in body.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip(), settings.openai_model
    return fallback_answer, "deterministic-source-summary"


def _data_snapshot(db: Session) -> dict[str, int]:
    return {
        "ai_answer_format_version": AI_ANSWER_FORMAT_VERSION,
        "politicians": db.scalar(select(func.count()).select_from(Politician)) or 0,
        "committees": db.scalar(select(func.count()).select_from(Committee)) or 0,
        "committee_meetings": db.scalar(select(func.count()).select_from(CommitteeMeeting)) or 0,
        "committee_attendance": db.scalar(select(func.count()).select_from(CommitteeAttendance)) or 0,
        "parliamentary_questions": db.scalar(select(func.count()).select_from(ParliamentaryQuestion)) or 0,
        "bills": db.scalar(select(func.count()).select_from(Bill)) or 0,
        "vote_events": db.scalar(select(func.count()).select_from(VoteEvent)) or 0,
    }


def _classify_intent(question: str) -> str:
    text = question.lower()
    if any(word in text for word in ["question", "asked", "minister", "department"]):
        return "questions"
    if any(word in text for word in ["attendance", "attend", "absent", "apology", "present"]):
        return "attendance"
    if any(word in text for word in ["committee", "committees", "sits on", "serve on"]):
        return "committees"
    if any(word in text for word in ["bill", "act", "legislation"]):
        return "bills"
    if any(word in text for word in ["vote", "division", "voted"]):
        return "votes"
    return "politicians"


def _search_terms(question: str) -> list[str]:
    stop = {
        "about",
        "and",
        "are",
        "did",
        "does",
        "from",
        "have",
        "into",
        "mp",
        "mps",
        "mentioning",
        "question",
        "questions",
        "asked",
        "show",
        "the",
        "their",
        "what",
        "where",
        "which",
        "who",
        "with",
    }
    terms = [term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9+-]{2,}", question.lower()) if term not in stop]
    return terms[:8] or [question.strip()]


def _filters(columns: list[Any], terms: list[str]) -> list[Any]:
    return [column.ilike(f"%{term}%") for term in terms for column in columns]


def _question_sources(db: Session, terms: list[str], limit: int = MAX_SOURCES) -> list[dict[str, Any]]:
    statement = (
        select(ParliamentaryQuestion)
        .options(joinedload(ParliamentaryQuestion.politician).joinedload(Politician.party))
        .order_by(ParliamentaryQuestion.asked_date.desc().nullslast(), ParliamentaryQuestion.created_at.desc())
        .limit(limit)
    )
    filters = _filters(
        [
            ParliamentaryQuestion.title,
            ParliamentaryQuestion.question_text,
            ParliamentaryQuestion.answer_text,
            ParliamentaryQuestion.department,
            ParliamentaryQuestion.asked_by_name,
        ],
        terms,
    )
    if filters:
        statement = statement.where(or_(*filters))
    return [_question_to_source(item) for item in db.scalars(statement).unique()]


def _committee_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    statement = select(Committee).order_by(Committee.name).limit(MAX_SOURCES)
    filters = _filters([Committee.name, Committee.description], terms)
    if filters:
        statement = statement.where(or_(*filters))
    return [
        {
            "title": item.name,
            "source_url": item.source_url,
            "source_type": "committee",
            "record_id": str(item.id),
            "date": None,
            "excerpt": _excerpt(item.description),
        }
        for item in db.scalars(statement)
    ]


def _attendance_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    statement = (
        select(CommitteeAttendance)
        .join(CommitteeAttendance.meeting)
        .options(joinedload(CommitteeAttendance.meeting), joinedload(CommitteeAttendance.politician).joinedload(Politician.party))
        .order_by(CommitteeMeeting.date.desc().nullslast(), CommitteeAttendance.created_at.desc())
        .limit(MAX_SOURCES)
    )
    filters = _filters(
        [CommitteeAttendance.name_raw, CommitteeAttendance.attendance_status, CommitteeMeeting.title, CommitteeMeeting.committee_name],
        terms,
    )
    if filters:
        statement = statement.where(or_(*filters))
    sources = []
    for item in db.scalars(statement).unique():
        name = item.politician.display_name if item.politician else item.name_raw
        meeting = item.meeting
        sources.append(
            {
                "title": f"{name}: {item.attendance_status}",
                "source_url": item.source_url or meeting.source_url,
                "source_type": "committee_attendance",
                "record_id": str(item.id),
                "date": meeting.date.isoformat() if meeting.date else None,
                "excerpt": _excerpt(f"{meeting.title} | {meeting.committee_name or ''}"),
            }
        )
    return sources


def _bill_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    statement = select(Bill).order_by(Bill.year.desc().nullslast(), Bill.updated_at.desc()).limit(MAX_SOURCES)
    filters = _filters([Bill.title, Bill.short_title, Bill.bill_number, Bill.status], terms)
    if filters:
        statement = statement.where(or_(*filters))
    return [
        {
            "title": item.title,
            "source_url": item.source_url,
            "source_type": "bill",
            "record_id": str(item.id),
            "date": str(item.year) if item.year else None,
            "excerpt": _excerpt(" | ".join(part for part in [item.bill_number, item.status, item.house] if part)),
        }
        for item in db.scalars(statement)
    ]


def _vote_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    statement = select(VoteEvent).order_by(VoteEvent.date.desc().nullslast(), VoteEvent.updated_at.desc()).limit(MAX_SOURCES)
    filters = _filters([VoteEvent.title, VoteEvent.chamber, VoteEvent.vote_type, VoteEvent.result], terms)
    if filters:
        statement = statement.where(or_(*filters))
    return [
        {
            "title": item.title,
            "source_url": item.source_url,
            "source_type": "vote_event",
            "record_id": str(item.id),
            "date": item.date.isoformat() if item.date else None,
            "excerpt": _excerpt(" | ".join(part for part in [item.chamber, item.vote_type, item.result] if part)),
        }
        for item in db.scalars(statement)
    ]


def _politician_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    statement = (
        select(Politician)
        .options(joinedload(Politician.party))
        .join(Politician.party)
        .order_by(Politician.display_name)
        .limit(MAX_SOURCES)
    )
    filters = _filters([Politician.full_name, Politician.display_name, Politician.slug, Party.name, Party.short_name], terms)
    if filters:
        statement = statement.where(or_(*filters))
    return [
        {
            "title": item.display_name,
            "source_url": item.profile_url,
            "source_type": "politician",
            "record_id": str(item.id),
            "date": None,
            "excerpt": _excerpt(
                " | ".join(
                    part
                    for part in [
                        item.full_name,
                        item.party.short_name if item.party else None,
                        item.source_status,
                    ]
                    if part
                )
            ),
        }
        for item in db.scalars(statement).unique()
    ]


def _question_to_source(item: ParliamentaryQuestion) -> dict[str, Any]:
    title = item.title or item.question_number or "Parliamentary question"
    asker = item.politician.display_name if item.politician else item.asked_by_name
    if not asker:
        asker = _infer_question_asker(" ".join(part for part in [item.question_text, item.answer_text] if part))
    excerpt = " | ".join(
        part
        for part in [
            f"Asked by {asker}" if asker else None,
            item.department,
            item.question_text,
            item.answer_text,
        ]
        if part
    )
    return {
        "title": title,
        "source_url": item.source_url,
        "source_type": "parliamentary_question",
        "record_id": str(item.id),
        "date": item.asked_date.isoformat() if item.asked_date else None,
        "excerpt": _excerpt(excerpt),
        "asked_by": asker,
        "department": item.department,
        "status": item.status,
    }


def _build_deterministic_answer(question: str, evidence: RetrievedEvidence) -> str:
    if not evidence.sources:
        return (
            "I could not find source-backed KnowYourMPZA records that answer this question yet. "
            f"{evidence.coverage_notice}"
        )
    if evidence.intent == "questions":
        return _build_question_answer(question, evidence)
    lines = [
        f"Based on the source-backed records currently imported, I found {len(evidence.sources)} relevant record"
        f"{'' if len(evidence.sources) == 1 else 's'} for: {question}",
    ]
    for source in evidence.sources[:5]:
        detail = " | ".join(part for part in [source.get("date"), source.get("excerpt")] if part)
        lines.append(f"- {source['title']}{f': {detail}' if detail else ''}")
    lines.append(evidence.coverage_notice)
    lines.append("Open the attached sources to verify each record.")
    return "\n".join(lines)


def _build_question_answer(question: str, evidence: RetrievedEvidence) -> str:
    source_count = len(evidence.sources)
    asker_names = _unique_values(source.get("asked_by") for source in evidence.sources)
    topic = _topic_from_question(question)
    if asker_names:
        named = _join_human(asker_names[:5])
        intro = (
            f"I found {source_count} imported parliamentary question record"
            f"{'' if source_count == 1 else 's'} mentioning {topic}. "
            f"The records include questions from {named}."
        )
    else:
        intro = (
            f"I found {source_count} imported parliamentary question record"
            f"{'' if source_count == 1 else 's'} mentioning {topic}, but the MP names are not linked cleanly yet."
        )

    lines = [intro, "", "Relevant source-backed records:"]
    for source in evidence.sources[:5]:
        asker = source.get("asked_by") or "MP not yet linked"
        detail_parts = [source.get("department"), source.get("status"), source.get("date")]
        detail = ", ".join(str(part) for part in detail_parts if part)
        title = _clean_question_title(source["title"])
        if detail:
            lines.append(f"- {asker}: {title} ({detail})")
        else:
            lines.append(f"- {asker}: {title}")

    if source_count > 5:
        lines.append(f"- Plus {source_count - 5} more matching imported records.")
    lines.extend(["", evidence.coverage_notice, "Use the source links below to verify each record."])
    return "\n".join(lines)


def _infer_question_asker(text: str) -> str | None:
    if not text:
        return None
    patterns = [
        r"\b(?:Mr|Ms|Mrs|Dr|Adv|Prof|Hon)\s+[A-Z][A-Za-z .'-]{2,90}\s+\([^)]+\)\s+to ask",
        r"\b(?:Mr|Ms|Mrs|Dr|Adv|Prof|Hon)\s+[A-Z][A-Za-z .'-]{2,90}\s+to ask",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return re.sub(r"\s+to ask$", "", match.group(0), flags=re.IGNORECASE).strip()
    return None


def _topic_from_question(question: str) -> str:
    terms = _search_terms(question)
    if terms:
        return terms[-1].title()
    return "this topic"


def _clean_question_title(title: str) -> str:
    cleaned = re.sub(r"\s+", " ", title).strip()
    cleaned = cleaned.replace("Written question reply", "Written question")
    cleaned = cleaned.replace("â", "-").replace("—", "-")
    return cleaned


def _unique_values(values: Any) -> list[str]:
    seen: set[str] = set()
    unique: list[str] = []
    for value in values:
        if not value:
            continue
        normalized = re.sub(r"\s+", " ", str(value)).strip()
        key = normalized.lower()
        if key not in seen:
            unique.append(normalized)
            seen.add(key)
    return unique


def _join_human(values: list[str]) -> str:
    if len(values) == 1:
        return values[0]
    if len(values) == 2:
        return f"{values[0]} and {values[1]}"
    return f"{', '.join(values[:-1])}, and {values[-1]}"


def _coverage_notice(intent: str, has_sources: bool) -> str:
    base = {
        "questions": "Parliamentary Questions coverage is still being backfilled, so this answer may not include every historical question.",
        "committees": "Committee records show currently imported and linked committees; historical links may still be improving.",
        "attendance": "Attendance records cover explicit PMG attendance rows linked so far and should not be read as a complete attendance rate yet.",
        "bills": "Bills coverage is PMG-backed and may omit records not yet linked from source backfills.",
        "votes": "Vote data is source-backed where available, but individual vote records remain incomplete.",
        "politicians": "MP identity records are source-backed, while party and committee links continue to improve through scheduled backfills.",
    }.get(intent, "KnowYourMPZA answers only from imported, source-backed records.")
    if has_sources:
        return base
    return f"No matching imported records were found. {base}"


def _excerpt(value: str | None) -> str | None:
    if not value:
        return None
    text = re.sub(r"\s+", " ", value).strip()
    if len(text) <= MAX_EXCERPT_CHARS:
        return text
    return f"{text[:MAX_EXCERPT_CHARS].rstrip()}..."


def response_generated_at(record: AiAnswer) -> datetime:
    return record.updated_at or record.created_at or datetime.now(timezone.utc)
