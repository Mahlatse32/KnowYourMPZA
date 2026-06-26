import hashlib
import re
from datetime import date, datetime
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.people_assembly import create_slug, extract_text
from app.ingestion.pdf_utils import archive_pdf, download_file, extract_pdf_text, is_pdf_url
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.question_mention import QuestionMention
from app.models.source import Source
from app.models.unresolved_entity import UnresolvedEntity
from app.services.entity_resolution import ResolutionResult, resolve_politician_name

SOURCE_NAME = "Parliamentary Questions"


def fetch_page(url: str) -> str:
    try:
        response = requests.get(url, timeout=20, headers={"User-Agent": "KnowYourMPZA/0.1"})
        response.raise_for_status()
        return response.text
    except requests.RequestException:
        return ""


def archive_html(source_name: str, url: str, html: str) -> str:
    base_dir = Path("data/raw/parliament_questions")
    path = _archive_path(url, base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")
    return str(path)


def parse_question_page(url: str, html: str) -> dict:
    soup = BeautifulSoup(html or "", "html.parser")
    text = extract_text(html)
    return _parsed_from_text(
        url=url,
        text=text,
        title=_title(soup, _label_fields(text), url),
        archive_path=archive_html(SOURCE_NAME, url, html),
        source_file_type="HTML",
        parse_notes=None,
    )


def parse_question_pdf(url: str, content: bytes, source_url: str | None = None) -> dict:
    archive_path = archive_pdf(SOURCE_NAME, url, content)
    try:
        text = extract_pdf_text(archive_path)
    except ValueError as exc:
        text = ""
        parse_status = "FAILED"
        parse_notes = str(exc)
    else:
        parse_status = "PARSED" if text else "PARTIAL"
        parse_notes = None if text else "PDF archived but no extractable text was found."
    return _parsed_from_text(
        url=source_url or url,
        text=text,
        title=_title_from_pdf_url(url),
        archive_path=archive_path,
        source_file_type="PDF",
        parse_status=parse_status,
        parse_notes=parse_notes,
    )


def parse_question_source(url: str) -> dict:
    if is_pdf_url(url):
        return parse_question_pdf(url, download_file(url))
    html = fetch_page(url)
    if not html:
        raise ValueError("Fetch failed or returned empty HTML.")
    pdf_url = _first_pdf_link(url, html)
    if pdf_url:
        try:
            parsed = parse_question_pdf(pdf_url, download_file(pdf_url), source_url=url)
            parsed["parse_notes"] = _append_note(parsed.get("parse_notes"), f"PDF linked from {url}")
            return parsed
        except Exception as exc:
            parsed = parse_question_page(url, html)
            parsed["parse_status"] = "PARTIAL"
            parsed["parse_notes"] = f"Linked PDF extraction failed: {exc}"
            return parsed
    return parse_question_page(url, html)


def resolve_question_asker(raw_name: str, db: Session) -> ResolutionResult | None:
    for candidate in _name_candidates(raw_name):
        result = resolve_politician_name(db, candidate)
        if result:
            return result
    return None


def upsert_parliamentary_question(db: Session, parsed: dict) -> tuple[ParliamentaryQuestion, bool]:
    source = _ensure_source(db)
    resolution = resolve_question_asker(parsed.get("asked_by_name") or "", db)
    existing = db.scalars(
        select(ParliamentaryQuestion).where(ParliamentaryQuestion.source_url == parsed["source_url"])
    ).first()
    resolved_politician = resolution.politician if resolution else (existing.politician if existing else None)
    payload = {
        "question_number": parsed.get("question_number"),
        "title": parsed.get("title"),
        "politician": resolved_politician,
        "asked_by_name": parsed.get("asked_by_name"),
        "department": parsed.get("department"),
        "minister": parsed.get("minister"),
        "question_text": parsed.get("question_text"),
        "answer_text": parsed.get("answer_text"),
        "asked_date": parsed.get("asked_date"),
        "answered_date": parsed.get("answered_date"),
        "status": parsed.get("status"),
        "source": source,
        "source_url": parsed["source_url"],
        "archive_path": parsed.get("archive_path"),
        "source_file_type": parsed.get("source_file_type"),
        "extracted_text_available": parsed.get("extracted_text_available", False),
        "parse_status": parsed.get("parse_status"),
        "parse_notes": parsed.get("parse_notes"),
    }
    created = existing is None
    question = existing or ParliamentaryQuestion()
    for key, value in payload.items():
        setattr(question, key, value)
    db.add(question)
    db.flush()

    if resolution:
        _upsert_question_mention(
            db,
            question,
            resolution.politician,
            parsed.get("raw_text") or "",
            resolution.matched_text,
            resolution.confidence_score,
            resolution.match_reason,
        )
    elif parsed.get("asked_by_name"):
        _upsert_unresolved_entity(db, parsed["source_url"], parsed["asked_by_name"])

    for politician, snippet, confidence, reason in _detect_question_mentions(db, parsed.get("raw_text") or ""):
        _upsert_question_mention(db, question, politician, parsed.get("raw_text") or "", politician.display_name, confidence, reason, snippet)
    if question.politician_id is None:
        politician_ids = list(
            db.scalars(
                select(QuestionMention.politician_id)
                .where(QuestionMention.question_id == question.id)
                .distinct()
            )
        )
        if len(politician_ids) == 1:
            question.politician_id = politician_ids[0]
    return question, created


def ingest_parliamentary_question_urls(db: Session, urls: list[str]) -> dict:
    summary = _empty_summary()
    _ensure_source(db)
    db.commit()
    for url in urls:
        try:
            parsed = parse_question_source(url)
            _, created = upsert_parliamentary_question(db, parsed)
            _bump(summary, created)
            summary["processed_count"] += 1
        except Exception as exc:
            db.rollback()
            summary["failed_count"] += 1
            summary["errors"].append({"url": url, "error": str(exc), "type": exc.__class__.__name__})
        else:
            db.commit()
    return summary


def _detect_question_mentions(db: Session, text: str) -> list[tuple[Politician, str, float, str]]:
    results: list[tuple[Politician, str, float, str]] = []
    seen: set[str] = set()
    candidates: list[str] = []
    candidates.extend(alias.alias for alias in db.scalars(select(PoliticianAlias).order_by(PoliticianAlias.alias)))
    for politician in db.scalars(select(Politician).order_by(Politician.display_name)):
        candidates.extend([politician.full_name, politician.display_name])
        surname = politician.display_name.split()[-1] if politician.display_name else ""
        if len(surname) >= 5:
            candidates.append(surname)

    for candidate in sorted(set(c for c in candidates if c), key=len, reverse=True):
        match = re.search(rf"\b{re.escape(candidate)}\b", text, flags=re.IGNORECASE)
        if not match:
            continue
        resolution = resolve_question_asker(candidate, db)
        if not resolution or str(resolution.politician.id) in seen:
            continue
        seen.add(str(resolution.politician.id))
        results.append(
            (
                resolution.politician,
                _snippet(text, match.start(), match.end()),
                resolution.confidence_score,
                resolution.match_reason,
            )
        )
    return results


def _ensure_source(db: Session) -> Source:
    source = db.scalars(select(Source).where(Source.name == SOURCE_NAME)).first()
    if source is None:
        source = Source(
            name=SOURCE_NAME,
            base_url="https://www.parliament.gov.za/",
            source_type="parliamentary_questions",
            reliability_score=0.9,
        )
        db.add(source)
        db.flush()
    return source


def _upsert_question_mention(
    db: Session,
    question: ParliamentaryQuestion,
    politician: Politician,
    raw_text: str,
    matched_text: str,
    confidence: float,
    reason: str,
    snippet: str | None = None,
) -> QuestionMention:
    mention = db.scalars(
        select(QuestionMention).where(
            QuestionMention.question == question,
            QuestionMention.politician == politician,
        )
    ).first()
    if mention is None:
        mention = QuestionMention(question=question, politician=politician)
        db.add(mention)
    mention.snippet = snippet or _snippet_for_match(raw_text, matched_text)
    mention.confidence_score = confidence
    mention.match_reason = reason
    return mention


def _upsert_unresolved_entity(db: Session, source_url: str, raw_value: str) -> UnresolvedEntity:
    entity = db.scalars(
        select(UnresolvedEntity).where(
            UnresolvedEntity.source_name == SOURCE_NAME,
            UnresolvedEntity.source_url == source_url,
            UnresolvedEntity.raw_value == raw_value,
            UnresolvedEntity.entity_type == "POLITICIAN",
        )
    ).first()
    if entity is None:
        entity = UnresolvedEntity(
            source_name=SOURCE_NAME,
            source_url=source_url,
            raw_value=raw_value,
            entity_type="POLITICIAN",
            confidence=None,
        )
        db.add(entity)
    return entity


def _label_fields(text: str) -> dict[str, str]:
    labels = [
        "Question Number",
        "Question No",
        "Number",
        "No",
        "Asked By",
        "Question By",
        "Member",
        "MP",
        "Department",
        "Portfolio",
        "To Department",
        "Minister",
        "Answered By",
        "Reply By",
        "Asked Date",
        "Date Asked",
        "Question Date",
        "Asked On",
        "Answered Date",
        "Date Answered",
        "Reply Date",
        "Answered On",
        "Status",
        "Question",
        "Answer",
        "Reply",
    ]
    pattern = "|".join(re.escape(label) for label in labels)
    matches = list(re.finditer(rf"\b({pattern})\s*[:\-]\s*", text, flags=re.IGNORECASE))
    fields: dict[str, str] = {}
    for index, match in enumerate(matches):
        start = match.end()
        end = matches[index + 1].start() if index + 1 < len(matches) else min(len(text), start + 4000)
        key = match.group(1).lower()
        value = " ".join(text[start:end].split()).strip(" :-")
        if value:
            fields[key] = value
    return fields


def _parsed_from_text(
    url: str,
    text: str,
    title: str | None,
    archive_path: str,
    source_file_type: str,
    parse_status: str | None = None,
    parse_notes: str | None = None,
) -> dict:
    fields = _label_fields(text)
    question_text, answer_text = _split_question_answer(text, fields)
    asked_by_name = _first(fields, "asked_by", "asked by", "member", "mp", "question by")
    inferred_status = _first(fields, "status") or ("ANSWERED" if answer_text else "UNANSWERED")
    return {
        "question_number": _limit_string(_extract_question_number(text, fields), 100),
        "title": _limit_string(title, 500),
        "asked_by_name": _limit_string(_clean_person_value(asked_by_name) if asked_by_name else None, 255),
        "department": _limit_string(_first(fields, "department", "portfolio", "to department"), 255),
        "minister": _limit_string(_clean_person_value(_first(fields, "minister", "answered by", "reply by")), 255),
        "question_text": question_text,
        "answer_text": answer_text,
        "asked_date": _parse_date(_first(fields, "asked date", "date asked", "question date", "asked on")),
        "answered_date": _parse_date(_first(fields, "answered date", "date answered", "reply date", "answered on")),
        "status": _limit_string(inferred_status, 100),
        "source_url": url,
        "archive_path": archive_path,
        "source_file_type": source_file_type,
        "extracted_text_available": bool(text),
        "parse_status": parse_status or ("PARSED" if text else "PARTIAL"),
        "parse_notes": parse_notes,
        "raw_text": text,
    }


def _split_question_answer(text: str, fields: dict[str, str]) -> tuple[str | None, str | None]:
    question = _first(fields, "question")
    answer = _first(fields, "answer", "reply")
    if question or answer:
        return question, answer
    match = re.search(r"\b(question)\b\s*[:\-]\s*(.+?)\b(answer|reply)\b\s*[:\-]\s*(.+)", text, flags=re.IGNORECASE)
    if match:
        return " ".join(match.group(2).split()), " ".join(match.group(4).split())
    return text[:4000] if text else None, None


def _title(soup: BeautifulSoup, fields: dict[str, str], url: str) -> str | None:
    heading = soup.find("h1")
    if heading and heading.get_text(strip=True):
        return heading.get_text(" ", strip=True)
    if soup.title and soup.title.get_text(strip=True):
        return soup.title.get_text(" ", strip=True)
    number = _first(fields, "question number", "question no", "number")
    return f"Parliamentary question {number}" if number else f"Parliamentary question: {url}"


def _title_from_pdf_url(url: str) -> str:
    parsed = urlparse(url)
    name = Path(parsed.path.rstrip("/")).name
    if name:
        return Path(name).stem.replace("-", " ").replace("_", " ").strip() or f"Parliamentary question PDF: {url}"
    return f"Parliamentary question PDF: {url}"


def _first_pdf_link(page_url: str, html: str) -> str | None:
    soup = BeautifulSoup(html or "", "html.parser")
    for link in soup.find_all("a", href=True):
        href = str(link["href"]).strip()
        text = link.get_text(" ", strip=True).lower()
        if is_pdf_url(href) or ".pdf" in href.lower() or "pdf" in text:
            return urljoin(page_url, href)
    return None


def _append_note(existing: str | None, note: str) -> str:
    return f"{existing}; {note}" if existing else note


def _extract_question_number(text: str, fields: dict[str, str]) -> str | None:
    labelled = _first(fields, "question number", "question no", "number", "no")
    if labelled:
        compact = re.search(r"\b([A-Z]{0,4}\s*\d{1,6}(?:/\d{1,6})?)\b", labelled, flags=re.IGNORECASE)
        return " ".join(compact.group(1).split()) if compact else None
    match = re.search(r"\b(?:question|parliamentary question)\s+(?:number|no\.?|num)?\s*[:#]?\s*([A-Z]{0,4}\s*\d+/?\d*)", text, flags=re.IGNORECASE)
    if match:
        return " ".join(match.group(1).split())
    return None


def _limit_string(value: str | None, limit: int) -> str | None:
    if value is None:
        return None
    value = " ".join(str(value).split())
    if not value:
        return None
    return value[:limit]


def _first(fields: dict[str, str], *keys: str) -> str | None:
    for key in keys:
        value = fields.get(key)
        if value:
            return value[:500] if key not in {"question", "answer", "reply"} else value
    return None


def _clean_person_value(value: str | None) -> str | None:
    if not value:
        return None
    value = re.sub(r"\s+", " ", value).strip()
    value = re.sub(r"\s*\([^)]{1,80}\)\s*$", "", value).strip()
    return value or None


def _name_candidates(raw_name: str) -> list[str]:
    raw_name = _clean_person_value(raw_name) or ""
    if not raw_name:
        return []
    candidates = [raw_name]
    candidates.append(re.sub(r"^(hon|mr|ms|mrs|dr|adv|prof)\.?\s+", "", raw_name, flags=re.IGNORECASE).strip())
    comma = re.match(r"^([^,]+),\s*(.+)$", raw_name)
    if comma:
        surname = comma.group(1).strip()
        prefix = comma.group(2).strip()
        candidates.extend([f"{prefix} {surname}", surname])
    parts = raw_name.split()
    if len(parts) > 1:
        candidates.append(parts[-1])
    return list(dict.fromkeys(c for c in candidates if c))


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    value = re.sub(r"(\d+)(st|nd|rd|th)", r"\1", value.strip(), flags=re.IGNORECASE)
    for fmt in ("%Y-%m-%d", "%d %B %Y", "%d %b %Y", "%B %d, %Y"):
        try:
            return datetime.strptime(value[:10] if fmt == "%Y-%m-%d" else value, fmt).date()
        except ValueError:
            continue
    match = re.search(r"\b(\d{1,2} [A-Z][a-z]+ \d{4})\b", value)
    if match:
        return _parse_date(match.group(1))
    return None


def _snippet_for_match(text: str, matched_text: str) -> str | None:
    if not text or not matched_text:
        return None
    match = re.search(rf"\b{re.escape(matched_text)}\b", text, flags=re.IGNORECASE)
    if not match:
        return None
    return _snippet(text, match.start(), match.end())


def _snippet(text: str, start: int, end: int, radius: int = 250) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if left > 0:
        snippet = f"...{snippet}"
    if right < len(text):
        snippet = f"{snippet}..."
    return snippet


def _archive_path(url: str, base_dir: Path) -> Path:
    parsed = urlparse(url)
    slug = create_slug(Path(parsed.path.rstrip("/")).name or parsed.netloc or "question")
    digest = hashlib.sha256(url.encode("utf-8")).hexdigest()[:10]
    return base_dir / f"{slug}-{digest}.html"


def _empty_summary() -> dict:
    return {
        "processed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "failed_count": 0,
        "errors": [],
    }


def _bump(summary: dict, created: bool) -> None:
    if created:
        summary["created_count"] += 1
    else:
        summary["updated_count"] += 1
