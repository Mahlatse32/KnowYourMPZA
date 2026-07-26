from __future__ import annotations

import logging
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
from app.models.committee_membership import CommitteeMembership
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.vote_event import VoteEvent


MAX_SOURCES = 8
MAX_EXCERPT_CHARS = 260
AI_ANSWER_FORMAT_VERSION = 15
logger = logging.getLogger(__name__)


@dataclass
class RetrievedEvidence:
    intent: str
    sources: list[dict[str, Any]]
    coverage_notice: str
    subject: str | None = None
    topic: str | None = None
    answer_kind: str = "general"


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
    subject = _question_subject(question)
    asker_terms = _question_asker_terms(question)
    topic_terms = _question_topic_terms(question, terms, asker_terms)
    intent = _classify_intent(question)
    if intent == "questions":
        sources = _question_sources(db, topic_terms or terms, asker_terms=asker_terms)
    elif intent == "committees":
        committee_terms = _committee_topic_terms(question, terms)
        if _is_committee_membership_question(question):
            sources = _committee_membership_sources(db, committee_terms)
        else:
            sources = _committee_sources(db, committee_terms or terms)
    elif intent == "bills":
        sources = _bill_sources(db, terms)
    elif intent == "votes":
        sources = _vote_sources(db, terms)
    elif intent == "attendance":
        sources = _attendance_sources(db, terms)
    elif intent == "hearings":
        sources = _hearing_sources(db, _hearing_topic_terms(question, terms))
    elif intent == "profile":
        subject = _profile_subject(question) or " ".join(terms)
        sources = _profile_sources(db, subject)
    else:
        sources = _politician_sources(db, terms)
        if len(sources) < 3:
            sources.extend(_question_sources(db, terms, limit=MAX_SOURCES - len(sources)))

    sources = sources[:MAX_SOURCES]
    return RetrievedEvidence(
        intent=intent,
        sources=sources,
        coverage_notice=_coverage_notice(intent, bool(sources)),
        subject=subject or (_profile_subject(question) if intent == "profile" else None),
        topic=_topic_from_terms(topic_terms),
        answer_kind="questions_by_person_topic" if asker_terms and topic_terms and intent == "questions" else "general",
    )


def _ask_openai(question: str, evidence: RetrievedEvidence, fallback_answer: str) -> tuple[str, str]:
    api_key = _openai_api_key()
    if not api_key:
        return fallback_answer, "deterministic-source-summary"

    messages = [
        {
            "role": "system",
            "content": (
                "You are KnowYourMPZA's civic evidence assistant. Answer only from the supplied records. "
                "Do not add facts that are not present. If evidence is incomplete, say so plainly. "
                "For committee hearings, do not infer verbatim questions unless the supplied records include them. "
                "Keep the answer concise and mention that sources are attached."
            ),
        },
        {
            "role": "user",
                "content": (
                    f"Question: {question}\n"
                    f"Intent: {evidence.intent}\n"
                    f"Coverage notice: {evidence.coverage_notice}\n"
                    f"Source-backed draft answer to preserve exactly: {fallback_answer}\n"
                    f"Records: {evidence.sources}"
                ),
            },
    ]
    responses_payload = {
        "model": settings.ai_model,
        "input": messages,
    }
    try:
        with httpx.Client(timeout=30) as client:
            if _supports_responses_api():
                response = client.post(
                    f"{settings.ai_base_url.rstrip('/')}/responses",
                    headers=_ai_headers(api_key),
                    json=responses_payload,
                )
                if response.is_success:
                    body = response.json()
                    output = _openai_responses_text(body)
                    if output:
                        return _accepted_ai_answer(output, evidence, fallback_answer)
                    logger.warning("OpenAI Responses API returned no answer text for model %s", settings.ai_model)
                else:
                    _log_openai_failure("Responses API", response)

            chat_response = client.post(
                f"{settings.ai_base_url.rstrip('/')}/chat/completions",
                headers=_ai_headers(api_key),
                json={"model": settings.ai_model, "messages": messages},
            )
            if chat_response.is_success:
                output = _openai_chat_text(chat_response.json())
                if output:
                    return _accepted_ai_answer(output, evidence, fallback_answer)
                logger.warning("OpenAI Chat Completions API returned no answer text for model %s", settings.ai_model)
            else:
                _log_openai_failure("Chat Completions API", chat_response)
    except Exception:
        logger.exception("OpenAI answer generation failed for model %s; using deterministic fallback", settings.ai_model)
        return fallback_answer, "deterministic-source-summary"

    return fallback_answer, "deterministic-source-summary"


def _accepted_ai_answer(output: str, evidence: RetrievedEvidence, fallback_answer: str) -> tuple[str, str]:
    cleaned = _clean_display_text(output)
    if _is_ai_answer_faithful(cleaned, evidence, fallback_answer):
        return cleaned, settings.ai_model
    logger.warning("AI provider answer failed faithfulness checks for intent %s; using deterministic fallback", evidence.intent)
    return fallback_answer, "deterministic-source-summary"


def _is_ai_answer_faithful(answer: str, evidence: RetrievedEvidence, fallback_answer: str) -> bool:
    normalized_answer = _normalize_for_faithfulness(answer)
    required_terms = _required_ai_answer_terms(evidence, fallback_answer)
    return all(_normalize_for_faithfulness(term) in normalized_answer for term in required_terms)


def _required_ai_answer_terms(evidence: RetrievedEvidence, fallback_answer: str) -> list[str]:
    if evidence.intent == "questions":
        terms = [str(len(evidence.sources))]
        askers = [
            asker
            for asker in _unique_values(source.get("asked_by") for source in evidence.sources)
            if asker.lower() != "mp not yet linked"
        ]
        terms.extend(askers[:3])
        if evidence.answer_kind == "questions_by_person_topic" and evidence.subject:
            terms.append(evidence.subject)
        return terms

    if evidence.intent == "committees" and evidence.sources and evidence.sources[0].get("source_type") == "committee_membership_summary":
        members = evidence.sources[0].get("members") or []
        return [_member_label(member).split(" (", 1)[0] for member in members[:MAX_SOURCES]]

    if evidence.intent == "profile" and evidence.sources:
        source = evidence.sources[0]
        name = source.get("full_name") or source.get("display_name") or source.get("title") or fallback_answer.split(" ", 1)[0]
        tokens = _name_tokens(name)
        terms = [tokens[-1] if tokens else str(name)]
        terms.extend(source.get("committees") or [])
        return terms

    if evidence.intent == "hearings":
        return [source.get("title") for source in evidence.sources[:3] if source.get("title")]

    return []


def _normalize_for_faithfulness(value: str) -> str:
    cleaned = _clean_display_text(value).lower()
    return re.sub(r"[^a-z0-9]+", " ", cleaned).strip()


def _openai_responses_text(body: dict[str, Any]) -> str | None:
    output_text = body.get("output_text")
    if isinstance(output_text, str) and output_text.strip():
        return output_text.strip()
    for item in body.get("output", []):
        for content in item.get("content", []):
            text = content.get("text")
            if isinstance(text, str) and text.strip():
                return text.strip()
    return None


def _openai_chat_text(body: dict[str, Any]) -> str | None:
    for choice in body.get("choices", []):
        message = choice.get("message") or {}
        content = message.get("content")
        if isinstance(content, str) and content.strip():
            return content.strip()
    return None


def _log_openai_failure(api_name: str, response: httpx.Response) -> None:
    body_snippet = response.text[:500] if response.text else ""
    logger.warning(
        "OpenAI %s request failed for model %s with status %s: %s",
        api_name,
        settings.ai_model,
        response.status_code,
        body_snippet,
    )


def _data_snapshot(db: Session) -> dict[str, int]:
    return {
        "ai_answer_format_version": AI_ANSWER_FORMAT_VERSION,
        "openai_configured": 1 if _openai_api_key() else 0,
        "openai_model_fingerprint": _stable_text_fingerprint(settings.ai_model),
        "politicians": db.scalar(select(func.count()).select_from(Politician)) or 0,
        "committees": db.scalar(select(func.count()).select_from(Committee)) or 0,
        "committee_meetings": db.scalar(select(func.count()).select_from(CommitteeMeeting)) or 0,
        "committee_attendance": db.scalar(select(func.count()).select_from(CommitteeAttendance)) or 0,
        "parliamentary_questions": db.scalar(select(func.count()).select_from(ParliamentaryQuestion)) or 0,
        "bills": db.scalar(select(func.count()).select_from(Bill)) or 0,
        "vote_events": db.scalar(select(func.count()).select_from(VoteEvent)) or 0,
    }


def _openai_api_key() -> str:
    return settings.ai_api_key.strip().strip('"').strip("'")


def _ai_headers(api_key: str) -> dict[str, str]:
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    if _is_openrouter_base_url():
        app_url = settings.ai_app_url.strip()
        if app_url:
            headers["HTTP-Referer"] = app_url
        headers["X-Title"] = settings.ai_app_title.strip() or settings.app_name
    return headers


def _supports_responses_api() -> bool:
    base_url = settings.ai_base_url.lower()
    return "api.openai.com" in base_url


def _is_openrouter_base_url() -> bool:
    return "openrouter.ai" in settings.ai_base_url.lower()


def _stable_text_fingerprint(value: str) -> int:
    fingerprint = 0
    for char in value:
        fingerprint = (fingerprint * 31 + ord(char)) % 1_000_000_007
    return fingerprint


def _classify_intent(question: str) -> str:
    text = question.lower()
    if re.search(r"\b(who is|who's|tell me about|profile of|what is known about)\b", text):
        return "profile"
    if any(word in text for word in ["hearing", "hearings", "enquiry", "inquiry", "testimony", "testified", "briefing"]):
        return "hearings"
    if any(word in text for word in ["question", "asked", " ask ", "minister", "department"]):
        return "questions"
    if any(word in text for word in ["attendance", "attend", "absent", "apology", "present"]):
        return "attendance"
    if any(word in text for word in ["committee", "committees", "sits on", "sit on", "serve on", "serves on"]):
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
        "ask",
        "about",
        "show",
        "the",
        "their",
        "what",
        "is",
        "known",
        "tell",
        "me",
        "where",
        "which",
        "who",
        "with",
        "sits",
        "sit",
        "serve",
        "serves",
        "served",
        "hearing",
        "hearings",
        "enquiry",
        "inquiry",
        "testimony",
        "testified",
        "briefing",
        "committee",
        "committees",
        "on",
        "mr",
        "mrs",
        "ms",
        "dr",
        "adv",
        "prof",
        "hon",
        "anc",
        "da",
        "eff",
        "mk",
        "ifp",
    }
    terms = [term for term in re.findall(r"[a-zA-Z][a-zA-Z0-9+-]{2,}", question.lower()) if term not in stop]
    return terms[:8] or [question.strip()]


def _profile_subject(question: str) -> str | None:
    cleaned = re.sub(
        r"^\s*(?:who is|who's|tell me about|profile of|what is known about)\s+",
        "",
        question.strip(),
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\?\s*$", "", cleaned).strip()
    return cleaned or None


def _question_subject(question: str) -> str | None:
    pattern = (
        r"\b(?:Mr|Ms|Mrs|Dr|Adv|Prof|Hon)\s+"
        r"[A-Z][A-Za-z .'-]{0,90}?"
        r"(?:\s+\([A-Za-z0-9 +.-]+\))?"
        r"(?=\s+(?:ask|asked|asks|question|questions|about)\b|\?|$)"
    )
    match = re.search(pattern, question)
    if not match:
        return None
    return re.sub(r"\s+", " ", match.group(0)).strip()


def _question_asker_terms(question: str) -> list[str]:
    subject = _question_subject(question)
    if not subject:
        return []
    without_party = re.sub(r"\([^)]+\)", "", subject)
    without_title = re.sub(r"^(?:Mr|Ms|Mrs|Dr|Adv|Prof|Hon)\s+", "", without_party, flags=re.IGNORECASE)
    terms = [term for term in re.findall(r"[A-Za-z][A-Za-z'-]{2,}", without_title)]
    if not terms:
        return []
    surname = terms[-1]
    full_name = " ".join(terms)
    if full_name.lower() == surname.lower():
        return [surname]
    return [full_name, surname]


def _question_topic_terms(question: str, terms: list[str], asker_terms: list[str]) -> list[str]:
    about_match = re.search(r"\babout\s+(.+?)(?:\?|$)", question, flags=re.IGNORECASE)
    if about_match:
        about_text = about_match.group(1)
        about_text = re.sub(r"\([^)]+\)", " ", about_text)
        about_terms = _search_terms(about_text)
        if about_terms:
            return about_terms
    asker_tokens = {token.lower() for term in asker_terms for token in term.split()}
    return [term for term in terms if term.lower() not in asker_tokens]


def _topic_from_terms(terms: list[str]) -> str | None:
    if not terms:
        return None
    return " ".join(terms).title()


def _is_committee_membership_question(question: str) -> bool:
    text = question.lower()
    return "who" in text and any(phrase in text for phrase in ["sits on", "sit on", "serve on", "serves on", "members of"])


def _committee_topic_terms(question: str, terms: list[str]) -> list[str]:
    cleaned = re.sub(
        r"\b(who|which|mps?|members?|sits?|serves?|served|serve|on|the|committee|committees|of)\b",
        " ",
        question,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    topic_terms = _search_terms(cleaned)
    return topic_terms or terms


def _hearing_topic_terms(question: str, terms: list[str]) -> list[str]:
    cleaned = re.sub(
        r"\b(what|did|does|ask|asked|question|questions|in|during|at|the|hearing|hearings|enquiry|inquiry|testimony|testified|briefing|lieutenant|general)\b",
        " ",
        question,
        flags=re.IGNORECASE,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    topic_terms = _search_terms(cleaned)
    return topic_terms or terms


def _filters(columns: list[Any], terms: list[str]) -> list[Any]:
    return [column.ilike(f"%{term}%") for term in terms for column in columns]


def _question_sources(
    db: Session,
    terms: list[str],
    limit: int = MAX_SOURCES,
    asker_terms: list[str] | None = None,
) -> list[dict[str, Any]]:
    statement = (
        select(ParliamentaryQuestion)
        .options(joinedload(ParliamentaryQuestion.politician).joinedload(Politician.party))
        .order_by(ParliamentaryQuestion.asked_date.desc().nullslast(), ParliamentaryQuestion.created_at.desc())
        .limit(limit)
    )
    topic_filters = _filters(
        [
            ParliamentaryQuestion.title,
            ParliamentaryQuestion.question_text,
            ParliamentaryQuestion.answer_text,
            ParliamentaryQuestion.department,
        ],
        terms,
    )
    if topic_filters:
        statement = statement.where(or_(*topic_filters))
    asker_filters = _filters([ParliamentaryQuestion.asked_by_name, ParliamentaryQuestion.question_text], asker_terms or [])
    if asker_filters:
        statement = statement.where(or_(*asker_filters))
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


def _committee_membership_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    committee = _resolve_committee(db, terms)
    if committee is None:
        return []
    memberships = list(
        db.scalars(
            select(CommitteeMembership)
            .options(joinedload(CommitteeMembership.politician).joinedload(Politician.party), joinedload(CommitteeMembership.committee))
            .where(CommitteeMembership.committee_id == committee.id)
            .order_by(CommitteeMembership.role, CommitteeMembership.id)
            .limit(MAX_SOURCES)
        ).unique()
    )
    if not memberships:
        return [
            {
                "title": committee.name,
                "source_url": committee.source_url,
                "source_type": "committee_membership_summary",
                "record_id": str(committee.id),
                "date": None,
                "excerpt": "No linked members are currently imported for this committee.",
                "committee_name": committee.name,
                "members": [],
            }
        ]
    members = []
    for membership in memberships:
        party = membership.politician.party.short_name if membership.politician and membership.politician.party else None
        members.append(
            {
                "name": membership.politician.display_name if membership.politician else "MP not linked",
                "party": None if _is_unknown_label(party) else party,
                "role": membership.role,
                "source_url": membership.source_url,
            }
        )
    return [
        {
            "title": committee.name,
            "source_url": committee.source_url or memberships[0].source_url,
            "source_type": "committee_membership_summary",
            "record_id": str(committee.id),
            "date": None,
            "excerpt": _excerpt(", ".join(_member_label(member) for member in members)),
            "committee_name": committee.name,
            "members": members,
        }
    ]


def _resolve_committee(db: Session, terms: list[str]) -> Committee | None:
    if not terms:
        return None
    candidates = list(
        db.scalars(
            select(Committee)
            .where(or_(*_filters([Committee.name, Committee.description], terms)))
            .limit(50)
        )
    )
    scored = sorted(((committee, _committee_match_score(committee, terms)) for committee in candidates), key=lambda item: item[1], reverse=True)
    if not scored or scored[0][1] < 50:
        return None
    return scored[0][0]


def _committee_match_score(committee: Committee, terms: list[str]) -> int:
    name_tokens = set(_name_tokens(committee.name))
    term_tokens = {term.lower() for term in terms}
    if not name_tokens or not term_tokens:
        return 0
    if term_tokens.issubset(name_tokens):
        return 100
    if term_tokens & name_tokens:
        return 70
    return 0


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


def _hearing_sources(db: Session, terms: list[str]) -> list[dict[str, Any]]:
    statement = select(CommitteeMeeting).order_by(CommitteeMeeting.date.desc().nullslast(), CommitteeMeeting.updated_at.desc()).limit(MAX_SOURCES * 4)
    filters = _filters([CommitteeMeeting.title, CommitteeMeeting.committee_name, CommitteeMeeting.summary], terms)
    if filters:
        statement = statement.where(or_(*filters))
    scored = sorted(
        ((item, _meeting_match_score(item, terms)) for item in db.scalars(statement)),
        key=lambda item: item[1],
        reverse=True,
    )
    strong = [item for item, score in scored if score >= 2]
    if not strong and scored:
        strong = [item for item, score in scored if score > 0]
    return [_meeting_to_source(item) for item in strong[:MAX_SOURCES]]


def _meeting_match_score(meeting: CommitteeMeeting, terms: list[str]) -> int:
    text = " ".join(part for part in [meeting.title, meeting.committee_name, meeting.summary] if part).lower()
    tokens = set(re.findall(r"[a-z][a-z0-9+-]{2,}", text))
    score = 0
    for term in terms:
        normalized = term.lower()
        if normalized in tokens:
            score += 3 if len(normalized) >= 6 else 1
        elif normalized and normalized in text:
            score += 1
    return score


def _profile_sources(db: Session, subject: str) -> list[dict[str, Any]]:
    politician = _resolve_profile_politician(db, subject)
    if politician is None:
        return []
    memberships = list(
        db.scalars(
            select(CommitteeMembership)
            .options(joinedload(CommitteeMembership.committee))
            .where(CommitteeMembership.politician_id == politician.id)
            .order_by(CommitteeMembership.role, CommitteeMembership.id)
            .limit(5)
        ).unique()
    )
    question_count = db.scalar(
        select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.politician_id == politician.id)
    ) or 0
    attendance_count = db.scalar(
        select(func.count()).select_from(CommitteeAttendance).where(CommitteeAttendance.politician_id == politician.id)
    ) or 0
    committee_names = [
        " - ".join(part for part in [membership.committee.name, membership.role] if part)
        for membership in memberships
        if membership.committee
    ]
    party_name = politician.party.short_name or politician.party.name if politician.party else None
    if _is_unknown_label(party_name):
        party_name = None
    source = {
        "title": politician.display_name,
        "source_url": politician.profile_url,
        "source_type": "politician_profile",
        "record_id": str(politician.id),
        "date": None,
        "excerpt": _excerpt(
            " | ".join(
                part
                for part in [
                    politician.full_name,
                    f"Party: {party_name}" if party_name else None,
                    f"Committees: {', '.join(_clean_display_text(name) for name in committee_names)}" if committee_names else None,
                    f"Linked parliamentary questions: {question_count}",
                    f"Linked attendance records: {attendance_count}",
                    politician.source_status,
                ]
                if part
            )
        ),
        "display_name": politician.display_name,
        "full_name": politician.full_name,
        "party": party_name,
        "profile_url": politician.profile_url,
        "committees": committee_names,
        "question_count": question_count,
        "attendance_count": attendance_count,
        "source_status": politician.source_status,
    }
    return [source]


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


def _resolve_profile_politician(db: Session, subject: str) -> Politician | None:
    query_tokens = _name_tokens(subject)
    if not query_tokens:
        return None
    candidates = list(
        db.scalars(
            select(Politician)
            .outerjoin(PoliticianAlias)
            .options(joinedload(Politician.party), joinedload(Politician.aliases))
            .where(
                or_(
                    *[
                        Politician.full_name.ilike(f"%{token}%")
                        for token in query_tokens
                    ],
                    *[
                        Politician.display_name.ilike(f"%{token}%")
                        for token in query_tokens
                    ],
                    *[
                        Politician.slug.ilike(f"%{token}%")
                        for token in query_tokens
                    ],
                    *[
                        PoliticianAlias.alias.ilike(f"%{token}%")
                        for token in query_tokens
                    ],
                )
            )
            .limit(50)
        ).unique()
    )
    scored = sorted(
        ((candidate, _profile_match_score(candidate, query_tokens)) for candidate in candidates),
        key=lambda item: item[1],
        reverse=True,
    )
    if not scored or scored[0][1] < 50:
        return None
    return scored[0][0]


def _profile_match_score(politician: Politician, query_tokens: list[str]) -> int:
    names = [politician.full_name, politician.display_name, politician.slug.replace("-", " ")]
    names.extend(alias.alias for alias in politician.aliases)
    best = 0
    for name in names:
        name_tokens = _name_tokens(name)
        if not name_tokens:
            continue
        score = 0
        if name_tokens == query_tokens:
            score = 100
        elif all(token in name_tokens for token in query_tokens):
            score = 90
        elif query_tokens[-1] in name_tokens and query_tokens[0][0] == name_tokens[0][0]:
            score = 80
        elif query_tokens[-1] in name_tokens:
            score = 65
        elif any(token in name_tokens for token in query_tokens):
            score = 35
        best = max(best, score)
    return best


def _name_tokens(value: str | None) -> list[str]:
    if not value:
        return []
    without_party = re.sub(r"\([^)]+\)", " ", value)
    without_titles = re.sub(r"\b(?:Mr|Ms|Mrs|Dr|Adv|Prof|Hon)\b", " ", without_party, flags=re.IGNORECASE)
    return [token.lower() for token in re.findall(r"[A-Za-z][A-Za-z'-]*", without_titles) if len(token) > 1]


def _question_to_source(item: ParliamentaryQuestion) -> dict[str, Any]:
    title = item.title or item.question_number or "Parliamentary question"
    asker = item.politician.display_name if item.politician else item.asked_by_name
    if not asker:
        asker = _infer_question_asker(" ".join(part for part in [item.question_text, item.answer_text] if part))
    question_text = _clean_parliament_question_text(item.question_text, asker)
    answer_text = _clean_parliament_question_text(item.answer_text, None)
    excerpt = " | ".join(
        part
        for part in [
            f"Asked by {asker}" if asker else None,
            item.department,
            question_text,
            answer_text,
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


def _meeting_to_source(item: CommitteeMeeting) -> dict[str, Any]:
    excerpt = " | ".join(part for part in [item.committee_name, item.summary] if part)
    return {
        "title": item.title,
        "source_url": item.source_url or item.pmg_url,
        "source_type": "committee_meeting",
        "record_id": str(item.id),
        "date": item.date.isoformat() if item.date else None,
        "excerpt": _excerpt(excerpt),
        "committee_name": item.committee_name,
    }


def _build_deterministic_answer(question: str, evidence: RetrievedEvidence) -> str:
    if not evidence.sources:
        return (
            "I could not find source-backed KnowYourMPZA records that answer this question yet. "
            f"{evidence.coverage_notice}"
        )
    if evidence.intent == "profile":
        return _build_profile_answer(evidence)
    if evidence.intent == "committees" and evidence.sources[0].get("source_type") == "committee_membership_summary":
        return _build_committee_membership_answer(evidence)
    if evidence.intent == "questions":
        return _build_question_answer(question, evidence)
    if evidence.intent == "hearings":
        return _build_hearing_answer(evidence)
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


def _build_hearing_answer(evidence: RetrievedEvidence) -> str:
    lines = [
        f"I found {len(evidence.sources)} imported PMG committee meeting record"
        f"{'' if len(evidence.sources) == 1 else 's'} related to this hearing or enquiry.",
        "",
        "Relevant source-backed meeting records:",
    ]
    for source in evidence.sources[:5]:
        detail = " | ".join(part for part in [source.get("date"), source.get("committee_name")] if part)
        excerpt = _clean_answer_excerpt(source.get("excerpt"))
        line = f"- {_clean_display_text(source['title'])}"
        if detail:
            line = f"{line} ({detail})"
        if excerpt:
            line = f"{line}: {excerpt}"
        lines.append(line)
    if len(evidence.sources) > 5:
        lines.append(f"- Plus {len(evidence.sources) - 5} more matching imported meeting records.")
    lines.extend(
        [
            "",
            "PMG meeting records are source-backed, but the imported summary may not contain a verbatim transcript of every question asked in the hearing.",
            evidence.coverage_notice,
            "Use the source links below to verify the meeting records.",
        ]
    )
    return "\n".join(lines)


def _build_committee_membership_answer(evidence: RetrievedEvidence) -> str:
    source = evidence.sources[0]
    committee_name = _clean_display_text(source.get("committee_name") or source["title"])
    members = source.get("members") or []
    if not members:
        return "\n".join(
            [
                f"I found the {committee_name} committee, but no linked member records are imported for it yet.",
                "",
                evidence.coverage_notice,
                "Use the source link below to verify the committee record.",
            ]
        )
    lines = [f"I found {len(members)} linked member record{'' if len(members) == 1 else 's'} for the {committee_name} committee.", "", "Linked members:"]
    for member in members[:MAX_SOURCES]:
        lines.append(f"- {_member_label(member)}")
    lines.extend(["", evidence.coverage_notice, "Use the source links below to verify the membership records."])
    return "\n".join(lines)


def _build_profile_answer(evidence: RetrievedEvidence) -> str:
    source = evidence.sources[0]
    name = _clean_display_text(source.get("display_name") or source["title"])
    full_name = _clean_display_text(source.get("full_name"))
    party = source.get("party") or "party not confirmed yet"
    committees = [_clean_display_text(name) for name in source.get("committees") or []]
    question_count = source.get("question_count") or 0
    attendance_count = source.get("attendance_count") or 0
    lines = [f"{name} is a South African public representative in the KnowYourMPZA records."]
    details = []
    if full_name and full_name != name:
        details.append(f"Full name: {full_name}.")
    details.append(f"Party: {party}.")
    if committees:
        details.append(f"Linked committee work: {_join_human(committees[:4])}.")
    else:
        details.append("No committee memberships are linked in the imported records yet.")
    details.append(
        f"Imported activity currently linked: {question_count} parliamentary question"
        f"{'' if question_count == 1 else 's'} and {attendance_count} attendance record"
        f"{'' if attendance_count == 1 else 's'}."
    )
    lines.extend(["", *details, "", evidence.coverage_notice, "Use the source link below to verify the profile record."])
    return "\n".join(lines)


def _build_question_answer(question: str, evidence: RetrievedEvidence) -> str:
    source_count = len(evidence.sources)
    asker_names = _unique_values(source.get("asked_by") for source in evidence.sources)
    topic = _topic_from_question(question)
    if evidence.answer_kind == "questions_by_person_topic":
        subject = evidence.subject or (asker_names[0] if asker_names else "that MP")
        topic_label = evidence.topic or topic
        intro = (
            f"I found {source_count} imported parliamentary question record"
            f"{'' if source_count == 1 else 's'} where {subject} asked about {topic_label}."
        )
        lines = [intro, "", "What the questions covered:"]
        for source in evidence.sources[:5]:
            title = _clean_question_title(source["title"])
            detail_parts = [source.get("department"), source.get("status"), source.get("date")]
            detail = ", ".join(str(part) for part in detail_parts if part)
            excerpt = _clean_answer_excerpt(source.get("excerpt"))
            line = f"- {title}"
            if detail:
                line = f"{line} ({detail})"
            if excerpt:
                line = f"{line}: {excerpt}"
            lines.append(line)
        if source_count > 5:
            lines.append(f"- Plus {source_count - 5} more matching imported records.")
        lines.extend(["", evidence.coverage_notice, "Use the source links below to verify each record."])
        return "\n".join(lines)

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


def _clean_display_text(value: str | None) -> str:
    if not value:
        return ""
    cleaned = re.sub(r"\s+", " ", value).strip()
    replacements = {
        "â": "'",
        "Ã¢ÂÂ": "'",
        "â€™": "'",
        "’": "'",
        "‘": "'",
        "â¯": " ",
        "\u202f": " ",
        "â": "-",
        "\u2011": "-",
        "â": "-",
        "–": "-",
        "â": "-",
        "Ã¢ÂÂ": "-",
        "â€”": "-",
        "—": "-",
        "â¦": "...",
        "…": "...",
        "ã": "[",
        "ã": "]",
        "ãsourceã": "",
        "【source】": "",
        "[source]": "",
    }
    for bad, good in replacements.items():
        cleaned = cleaned.replace(bad, good)
    cleaned = re.sub(r"\s+", " ", cleaned).strip()
    return cleaned


def _is_unknown_label(value: str | None) -> bool:
    return not value or value.strip().lower() in {"unknown", "unk", "n/a", "none"}


def _member_label(member: dict[str, Any]) -> str:
    label = _clean_display_text(member.get("name")) or "MP not linked"
    details = [member.get("party"), member.get("role")]
    clean_details = [_clean_display_text(str(detail)) for detail in details if detail]
    if clean_details:
        return f"{label} ({', '.join(clean_details)})"
    return label


def _clean_answer_excerpt(excerpt: str | None) -> str | None:
    if not excerpt:
        return None
    cleaned = re.sub(r"^Asked by [^|]+\|\s*", "", excerpt).strip()
    cleaned = re.sub(
        r"^NATIONAL ASSEMBLY(?:\s+\(NA\))?\s+(?:QUESTION|WRITTEN REPLY QUESTION).*?\b\d+\.\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    cleaned = cleaned.replace("â", "-").replace("—", "-")
    if len(cleaned) <= 220:
        return cleaned
    return f"{cleaned[:220].rstrip()}..."


def _clean_parliament_question_text(text: str | None, asker: str | None) -> str | None:
    if not text:
        return None
    cleaned = re.sub(r"\s+", " ", text).strip()
    cleaned = cleaned.replace("â", "-").replace("—", "-")
    cleaned = re.sub(
        r"^NATIONAL ASSEMBLY(?:\s+\(NA\))?\s+(?:QUESTION|WRITTEN REPLY QUESTION).*?\b\d+\.\s*",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).strip()
    if asker:
        cleaned = re.sub(rf"^{re.escape(asker)}\s+to ask\s+the\s+", "asked the ", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(rf"^{re.escape(asker)}\s+to ask\s+", "asked ", cleaned, flags=re.IGNORECASE)
    cleaned = re.sub(r"^(Question|Answer):\s*", "", cleaned, flags=re.IGNORECASE).strip()
    if len(cleaned) <= MAX_EXCERPT_CHARS:
        return cleaned
    return f"{cleaned[:MAX_EXCERPT_CHARS].rstrip()}..."


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
        "profile": "This profile answer uses only source-backed identity and activity records currently linked in production.",
        "hearings": "Committee hearing answers use imported PMG meeting records; verbatim exchanges are available only where the source record includes them.",
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
