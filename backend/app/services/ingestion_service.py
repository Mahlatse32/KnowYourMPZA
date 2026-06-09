import re
from dataclasses import asdict
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.ingestion.people_assembly import fetch_page as fetch_people_assembly_page
from app.ingestion.people_assembly import archive_html as archive_people_assembly_html
from app.ingestion.people_assembly import normalize_committee_name, normalize_party_name, normalize_role
from app.ingestion.people_assembly import parse_committee_page
from app.ingestion.people_assembly import parse_profile
from app.ingestion.pmg import archive_html as archive_pmg_html
from app.ingestion.pmg import fetch_page as fetch_pmg_page
from app.ingestion.pmg import parse_document
from app.ingestion.seed_data import COMMITTEES, PARTIES, POLITICIANS, SOURCES, sample_document_for_politician
from app.models.committee import Committee
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.party import Party
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.source import Source
from app.models.unresolved_entity import UnresolvedEntity
from app.services.entity_resolution import alias_values_for_politician, resolve_politician_name


def _one_by(db: Session, model, field_name: str, value):
    return db.scalars(select(model).where(getattr(model, field_name) == value)).first()


def _upsert_source(db: Session, payload: dict) -> Source:
    source = _one_by(db, Source, "name", payload["name"])
    if source is None:
        source = Source(**payload)
        db.add(source)
    else:
        for key, value in payload.items():
            setattr(source, key, value)
    return source


def _upsert_party(db: Session, payload: dict) -> Party:
    data = dict(payload)
    data["name"], data["short_name"] = normalize_party_name(data.get("short_name") or data["name"])
    if data.get("name") == "Unknown":
        data["name"] = normalize_party_name(data.get("name", ""))[0]
    party = _one_by(db, Party, "short_name", data["short_name"])
    if party is None:
        party = Party(**data)
        db.add(party)
    else:
        for key, value in data.items():
            setattr(party, key, value)
    return party


def _upsert_committee(db: Session, payload: dict) -> Committee:
    payload["name"] = normalize_committee_name(payload["name"])
    payload["slug"] = payload.get("slug") or re.sub(r"[^a-z0-9]+", "-", payload["name"].lower()).strip("-")
    committee = _one_by(db, Committee, "slug", payload["slug"])
    if committee is None:
        committee = Committee(**payload)
        db.add(committee)
    else:
        for key, value in payload.items():
            setattr(committee, key, value)
    return committee


def _upsert_politician(db: Session, payload: dict, party: Party) -> Politician:
    data = {key: value for key, value in payload.items() if key not in {"party", "committee", "role"}}
    politician = _find_politician_for_profile(db, data)
    data["party"] = party
    if politician is None:
        politician = Politician(**data)
        db.add(politician)
    else:
        if data.get("source_status") == "UNKNOWN" and politician.source_status == "CURRENT":
            data["source_status"] = politician.source_status
            data["is_active"] = politician.is_active
        if not data.get("photo_url") and politician.photo_url:
            data["photo_url"] = politician.photo_url
        for key, value in data.items():
            setattr(politician, key, value)
    return politician


def _find_politician_for_profile(db: Session, data: dict) -> Politician | None:
    profile_url = data.get("profile_url")
    profile_match = None
    if profile_url:
        profile_match = db.scalars(select(Politician).where(Politician.profile_url == profile_url)).first()
    slug_match = _one_by(db, Politician, "slug", data["slug"])
    if profile_match and slug_match and profile_match.id != slug_match.id:
        _merge_politicians(db, target=profile_match, duplicate=slug_match)
        db.flush()
        return profile_match
    return profile_match or slug_match


def _merge_politicians(db: Session, target: Politician, duplicate: Politician) -> None:
    for membership in list(duplicate.committee_memberships):
        existing = db.scalars(
            select(CommitteeMembership).where(
                CommitteeMembership.politician == target,
                CommitteeMembership.committee == membership.committee,
                CommitteeMembership.role == membership.role,
            )
        ).first()
        if existing:
            if membership.source_url and not existing.source_url:
                existing.source_url = membership.source_url
            db.delete(membership)
        else:
            membership.politician = target
    for mention in list(duplicate.document_mentions):
        existing = db.scalars(
            select(DocumentMention).where(
                DocumentMention.politician == target,
                DocumentMention.document == mention.document,
            )
        ).first()
        if existing:
            db.delete(mention)
        else:
            mention.politician = target
    db.delete(duplicate)


def _upsert_membership(db: Session, politician: Politician, committee: Committee, role: str | None, source_url: str):
    role = normalize_role(role)
    membership = db.scalars(
        select(CommitteeMembership).where(
            CommitteeMembership.politician == politician,
            CommitteeMembership.committee == committee,
            CommitteeMembership.role == role,
        )
    ).first()
    if membership is None:
        membership = CommitteeMembership(
            politician=politician,
            committee=committee,
            role=role,
            source_url=source_url,
            source_last_seen_at=datetime.now(UTC),
            source_status="CURRENT",
        )
        db.add(membership)
    else:
        membership.source_url = source_url
        membership.source_last_seen_at = datetime.now(UTC)
        membership.source_status = "CURRENT"
    return membership


def _upsert_alias(db: Session, politician: Politician, alias: str, alias_type: str, source_url: str | None = None) -> PoliticianAlias:
    alias = " ".join(alias.strip().split())
    existing = db.scalars(
        select(PoliticianAlias).where(PoliticianAlias.politician == politician, PoliticianAlias.alias == alias)
    ).first()
    if existing is None:
        existing = PoliticianAlias(politician=politician, alias=alias, alias_type=alias_type, source_url=source_url)
        db.add(existing)
    else:
        existing.alias_type = alias_type
        existing.source_url = source_url
    return existing


def _ensure_aliases(db: Session, politician: Politician, source_url: str | None = None) -> int:
    count = 0
    for alias, alias_type in alias_values_for_politician(politician):
        before = db.scalars(
            select(PoliticianAlias).where(PoliticianAlias.politician == politician, PoliticianAlias.alias == alias)
        ).first()
        _upsert_alias(db, politician, alias, alias_type, source_url)
        count += 1 if before is None else 0
    return count


def regenerate_aliases(db: Session) -> int:
    created = 0
    for politician in db.scalars(select(Politician).order_by(Politician.display_name)):
        created += _ensure_aliases(db, politician, politician.profile_url)
    db.commit()
    return created


def _upsert_unresolved_entity(
    db: Session,
    source_name: str,
    raw_value: str,
    entity_type: str,
    source_url: str | None = None,
    confidence: float | None = None,
) -> UnresolvedEntity:
    raw_value = " ".join(raw_value.strip().split())
    existing = db.scalars(
        select(UnresolvedEntity).where(
            UnresolvedEntity.source_name == source_name,
            UnresolvedEntity.source_url == source_url,
            UnresolvedEntity.raw_value == raw_value,
            UnresolvedEntity.entity_type == entity_type,
        )
    ).first()
    if existing is None:
        existing = UnresolvedEntity(
            source_name=source_name,
            source_url=source_url,
            raw_value=raw_value,
            entity_type=entity_type,
            confidence=confidence,
            status="OPEN",
        )
        db.add(existing)
    elif existing.status == "IGNORED":
        existing.confidence = confidence
    return existing


def _upsert_document(db: Session, payload: dict, source: Source) -> Document:
    data = {key: value for key, value in payload.items() if key not in {"source_name", "snippet", "confidence_score"}}
    data["source"] = source
    document = _one_by(db, Document, "source_url", data["source_url"])
    if document is None:
        document = Document(**data)
        db.add(document)
    else:
        for key, value in data.items():
            setattr(document, key, value)
    return document


def _upsert_mention(db: Session, document: Document, politician: Politician, payload: dict) -> DocumentMention:
    mention = db.scalars(
        select(DocumentMention).where(
            DocumentMention.document == document,
            DocumentMention.politician == politician,
        )
    ).first()
    if mention is None:
        mention = DocumentMention(
            document=document,
            politician=politician,
            snippet=payload["snippet"],
            source_url=payload["source_url"],
            confidence_score=payload["confidence_score"],
        )
        db.add(mention)
    else:
        mention.snippet = payload["snippet"]
        mention.source_url = payload["source_url"]
        mention.confidence_score = payload["confidence_score"]
    return mention


def seed_database(db: Session) -> dict[str, int | str]:
    sources = {payload["name"]: _upsert_source(db, payload) for payload in SOURCES}
    parties = {}
    for payload in PARTIES:
        party = _upsert_party(db, payload)
        parties[payload["short_name"]] = party
        parties[party.short_name] = party
    committees = {payload["slug"]: _upsert_committee(db, payload) for payload in COMMITTEES}
    db.flush()

    politicians = []
    for payload in POLITICIANS:
        politician = _upsert_politician(db, payload, parties[payload["party"]])
        politicians.append(politician)
        db.flush()
        _upsert_membership(db, politician, committees[payload["committee"]], payload.get("role"), payload["profile_url"])
        _ensure_aliases(db, politician, payload["profile_url"])

    db.flush()
    document_count = _seed_documents(db, sources, politicians)
    db.commit()
    return {
        "status": "ok",
        "sources": len(sources),
        "parties": len(parties),
        "committees": len(committees),
        "politicians": len(politicians),
        "documents": document_count,
    }


def _seed_documents(db: Session, sources: dict[str, Source], politicians: list[Politician]) -> int:
    documents = 0
    for politician in politicians:
        payload = sample_document_for_politician(
            {
                "slug": politician.slug,
                "display_name": politician.display_name,
            }
        )
        document = _upsert_document(db, payload, sources[payload["source_name"]])
        db.flush()
        _upsert_mention(db, document, politician, payload)
        documents += 1
    return documents


def seed_sample_documents(db: Session) -> dict[str, int | str]:
    politicians = list(db.scalars(select(Politician).order_by(Politician.display_name)))
    if not politicians:
        return seed_database(db)
    sources = {source.name: source for source in db.scalars(select(Source))}
    if "PMG" not in sources:
        sources["PMG"] = _upsert_source(db, next(source for source in SOURCES if source["name"] == "PMG"))
        db.flush()
    count = _seed_documents(db, sources, politicians)
    db.commit()
    return {"status": "ok", "documents": count}


def ingest_people_assembly_profiles(db: Session, urls: list[str]) -> dict:
    summary = _empty_summary()
    source = _upsert_source(db, next(payload for payload in SOURCES if payload["name"] == "People's Assembly"))
    db.commit()
    for url in urls:
        try:
            html = fetch_people_assembly_page(url)
            if not html:
                raise ValueError("Fetch failed or returned empty HTML.")
            archive_path = archive_people_assembly_html(url, html)
            profile = parse_profile(url, html)

            party = _upsert_party(
                db,
                {
                    "name": profile.party_name,
                    "short_name": profile.party_short_name,
                    "logo_url": None,
                    "website_url": None,
                    "source_url": profile.profile_url,
                    "source_last_seen_at": datetime.now(UTC),
                },
            )
            existing_politician = _one_by(db, Politician, "slug", profile.slug)
            politician = _upsert_politician(
                db,
                {
                    "full_name": profile.full_name,
                    "display_name": profile.display_name,
                    "slug": profile.slug,
                    "profile_url": profile.profile_url,
                    "photo_url": profile.photo_url,
                    "is_active": profile.is_active,
                    "source_last_seen_at": datetime.now(UTC),
                    "source_status": profile.source_status,
                },
                party,
            )
            _bump(summary, existing_politician is None)
            db.flush()
            summary["created_count"] += _ensure_aliases(db, politician, profile.profile_url)

            profile_document = _upsert_document(
                db,
                {
                    "title": f"People's Assembly profile: {profile.display_name}",
                    "document_type": "MP_PROFILE",
                    "source_name": source.name,
                    "source_url": profile.profile_url,
                    "archive_path": archive_path,
                    "publication_date": None,
                    "raw_text": profile.full_name,
                },
                source,
            )
            db.flush()
            _upsert_mention(
                db,
                profile_document,
                politician,
                {
                    "snippet": f"{profile.display_name} profile page on People's Assembly.",
                    "source_url": profile.profile_url,
                    "confidence_score": 1.0,
                },
            )

            for membership in profile.committees:
                existing_committee = _one_by(db, Committee, "slug", membership.slug)
                committee = _upsert_committee(
                    db,
                    {
                        "name": membership.name,
                        "slug": membership.slug,
                        "description": f"Committee membership extracted from People's Assembly profile.",
                        "source_url": membership.source_url,
                        "source_last_seen_at": datetime.now(UTC),
                    },
                )
                _bump(summary, existing_committee is None)
                db.flush()
                existing_membership = db.scalars(
                    select(CommitteeMembership).where(
                        CommitteeMembership.politician == politician,
                        CommitteeMembership.committee == committee,
                        CommitteeMembership.role == membership.role,
                    )
                ).first()
                row = _upsert_membership(db, politician, committee, membership.role, membership.source_url)
                row.start_date = membership.start_date
                _bump(summary, existing_membership is None)
            summary["processed_count"] += 1
        except Exception as exc:
            db.rollback()
            summary["failed_count"] += 1
            summary["errors"].append({"url": url, "error": str(exc)})
        else:
            db.commit()
    return summary


def ingest_people_assembly_committees(db: Session, urls: list[str]) -> dict:
    summary = _empty_summary()
    source = _upsert_source(db, next(payload for payload in SOURCES if payload["name"] == "People's Assembly"))
    db.commit()
    for url in urls:
        try:
            html = fetch_people_assembly_page(url)
            if not html:
                raise ValueError("Fetch failed or returned empty HTML.")
            archive_path = archive_people_assembly_html(url, html, "data/raw/people_assembly/committees")
            parsed = parse_committee_page(url, html)
            existing_committee = _one_by(db, Committee, "slug", parsed.slug)
            committee = _upsert_committee(
                db,
                {
                    "name": parsed.name,
                    "slug": parsed.slug,
                    "description": "Committee extracted from People's Assembly committee page.",
                    "source_url": parsed.source_url,
                    "source_last_seen_at": datetime.now(UTC),
                },
            )
            _bump(summary, existing_committee is None)
            db.flush()
            document = _upsert_document(
                db,
                {
                    "title": f"People's Assembly committee: {parsed.name}",
                    "document_type": "COMMITTEE_PAGE",
                    "source_name": source.name,
                    "source_url": parsed.source_url,
                    "archive_path": archive_path,
                    "publication_date": None,
                    "raw_text": parsed.name,
                },
                source,
            )
            db.flush()
            for member in parsed.members:
                resolution = resolve_politician_name(db, member.name)
                if resolution is None:
                    _upsert_unresolved_entity(
                        db,
                        source_name=source.name,
                        raw_value=member.name,
                        entity_type="POLITICIAN",
                        source_url=parsed.source_url,
                        confidence=0.25,
                    )
                    summary["skipped_count"] += 1
                    continue
                existing_membership = db.scalars(
                    select(CommitteeMembership).where(
                        CommitteeMembership.politician == resolution.politician,
                        CommitteeMembership.committee == committee,
                        CommitteeMembership.role == normalize_role(member.role),
                    )
                ).first()
                _upsert_membership(db, resolution.politician, committee, member.role, parsed.source_url)
                _upsert_mention(
                    db,
                    document,
                    resolution.politician,
                    {
                        "snippet": f"{member.name} listed on {parsed.name}.",
                        "source_url": parsed.source_url,
                        "confidence_score": resolution.confidence_score,
                    },
                )
                _bump(summary, existing_membership is None)
            summary["processed_count"] += 1
        except Exception as exc:
            db.rollback()
            summary["failed_count"] += 1
            summary["errors"].append({"url": url, "error": str(exc)})
        else:
            db.commit()
    return summary


def ingest_pmg_documents(db: Session, urls: list[str]) -> dict:
    summary = _empty_summary()
    source = _upsert_source(db, next(payload for payload in SOURCES if payload["name"] == "PMG"))
    db.commit()
    for url in urls:
        try:
            html = fetch_pmg_page(url)
            if not html:
                raise ValueError("Fetch failed or returned empty HTML.")
            archive_path = archive_pmg_html(url, html)
            parsed = parse_document(url, html, archive_path)
            existing_document = _one_by(db, Document, "source_url", parsed.source_url)
            document = _upsert_document(db, {**asdict(parsed), "source_name": source.name}, source)
            _bump(summary, existing_document is None)
            db.flush()

            mentions = _detect_mentions(db, parsed.raw_text)
            if not mentions:
                summary["skipped_count"] += 1
            for politician, snippet, confidence, reason in mentions:
                existing_mention = db.scalars(
                    select(DocumentMention).where(
                        DocumentMention.document == document,
                        DocumentMention.politician == politician,
                    )
                ).first()
                _upsert_mention(
                    db,
                    document,
                    politician,
                    {
                        "snippet": snippet,
                        "source_url": parsed.source_url,
                        "confidence_score": confidence,
                    },
                )
                _bump(summary, existing_mention is None)
            summary["processed_count"] += 1
        except Exception as exc:
            db.rollback()
            summary["failed_count"] += 1
            summary["errors"].append({"url": url, "error": str(exc)})
        else:
            db.commit()
    return summary


def _detect_mentions(db: Session, raw_text: str) -> list[tuple[Politician, str, float, str]]:
    politicians = list(db.scalars(select(Politician).order_by(Politician.display_name)))
    aliases = list(db.scalars(select(PoliticianAlias).order_by(PoliticianAlias.alias)))
    results: list[tuple[Politician, str, float, str]] = []
    seen: set[str] = set()
    candidates: list[str] = []
    for politician in politicians:
        candidates.extend([politician.full_name, politician.display_name, politician.slug])
        surname = politician.display_name.split()[-1] if politician.display_name else ""
        if len(surname) >= 5:
            candidates.append(surname)
    candidates.extend(alias.alias for alias in aliases)

    for candidate in sorted(set(c for c in candidates if c), key=len, reverse=True):
        match = re.search(rf"\b{re.escape(candidate)}\b", raw_text, flags=re.IGNORECASE)
        if not match:
            continue
        resolution = resolve_politician_name(db, candidate)
        if not resolution:
            continue
        key = str(resolution.politician.id)
        if key in seen:
            continue
        seen.add(key)
        results.append(
            (
                resolution.politician,
                _snippet(raw_text, match.start(), match.end()),
                resolution.confidence_score,
                resolution.match_reason,
            )
        )
    return results


def _snippet(text: str, start: int, end: int, radius: int = 250) -> str:
    left = max(0, start - radius)
    right = min(len(text), end + radius)
    snippet = " ".join(text[left:right].split())
    if left > 0:
        snippet = f"...{snippet}"
    if right < len(text):
        snippet = f"{snippet}..."
    return snippet


def _empty_summary() -> dict:
    return {
        "processed_count": 0,
        "failed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "errors": [],
    }


def _bump(summary: dict, created: bool) -> None:
    if created:
        summary["created_count"] += 1
    else:
        summary["updated_count"] += 1
