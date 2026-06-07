from dataclasses import dataclass

from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app.ingestion.people_assembly import create_slug
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias


@dataclass
class ResolutionResult:
    politician: Politician
    confidence_score: float
    match_reason: str
    matched_text: str


def resolve_politician_name(db: Session, raw_name: str) -> ResolutionResult | None:
    value = " ".join(raw_name.strip().split())
    if not value:
        return None
    lowered = value.lower()
    slug = create_slug(value)

    checks = [
        (Politician.full_name, lowered, 0.99, "exact_full_name"),
        (Politician.display_name, lowered, 0.95, "display_name"),
        (Politician.slug, slug, 0.93, "slug"),
    ]
    for column, candidate, confidence, reason in checks:
        politician = db.scalars(
            select(Politician)
            .options(joinedload(Politician.party), joinedload(Politician.aliases))
            .where(func.lower(column) == candidate)
        ).unique().first()
        if politician:
            return ResolutionResult(politician, confidence, reason, value)

    alias = db.scalars(
        select(PoliticianAlias)
        .options(joinedload(PoliticianAlias.politician).joinedload(Politician.party))
        .where(func.lower(PoliticianAlias.alias) == lowered)
    ).unique().first()
    if alias:
        if alias.alias_type == "SURNAME_ONLY":
            matches = list(
                db.scalars(
                    select(PoliticianAlias)
                    .options(joinedload(PoliticianAlias.politician))
                    .where(func.lower(PoliticianAlias.alias) == lowered, PoliticianAlias.alias_type == "SURNAME_ONLY")
                ).unique()
            )
            if len({item.politician_id for item in matches}) != 1:
                return None
            return ResolutionResult(alias.politician, 0.72, "unique_surname_alias", value)
        return ResolutionResult(alias.politician, 0.9, f"alias:{alias.alias_type}", value)

    if len(value.split()) == 1 and len(value) >= 5:
        matches = list(
            db.scalars(
                select(Politician)
                .options(joinedload(Politician.party), joinedload(Politician.aliases))
                .where(func.lower(Politician.display_name).like(f"% {lowered}"))
            ).unique()
        )
        if len(matches) == 1:
            return ResolutionResult(matches[0], 0.72, "unique_surname", value)

    return None


def alias_values_for_politician(politician: Politician) -> list[tuple[str, str]]:
    names: list[tuple[str, str]] = [
        (politician.full_name, "FULL_NAME"),
        (politician.display_name, "DISPLAY_NAME"),
    ]
    surname = politician.display_name.split()[-1] if politician.display_name else politician.full_name.split()[-1]
    initials = "".join(part[0].upper() for part in politician.full_name.split()[:-1] if part)
    if initials and surname:
        names.append((f"{initials[0]} {surname}", "INITIAL_SURNAME"))
        names.append((f"{initials} {surname}", "INITIAL_SURNAME"))
        names.append((f"{'. '.join(initials)}. {surname}", "INITIAL_SURNAME"))
    if surname:
        names.extend(
            [
                (f"Hon {surname}", "TITLE_SURNAME"),
                (f"Mr {surname}", "TITLE_SURNAME"),
                (f"Ms {surname}", "TITLE_SURNAME"),
                (f"Dr {surname}", "TITLE_SURNAME"),
                (surname, "SURNAME_ONLY"),
            ]
        )
    deduped: dict[str, str] = {}
    for alias, alias_type in names:
        clean = " ".join(alias.split())
        if clean:
            deduped.setdefault(clean, alias_type)
    return list(deduped.items())
