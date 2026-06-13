#!/usr/bin/env python3
"""Report-only entity-resolution candidate suggestions for unresolved actors (#28).

For each OPEN unresolved political entity this produces ranked candidate
matches using ONLY deterministic, explainable signals (exact normalized name,
display name, slug, known alias, unique surname). It never writes to the
database and never applies a match — ambiguous cases are explicitly left
unresolved for human review.

Confidence buckets:
  high    score >= 0.90  (exact full name / display name / slug / strong alias)
  medium  0.72–0.89      (unique surname or surname-only alias)
  low     < 0.72 OR more than one distinct candidate (ambiguous → do not apply)

Outputs:
  reports/entity_resolution_candidates.json
  reports/entity_resolution_candidates.md

Safety: no DB writes, no auto-apply, no secrets printed (defensive redaction
of any URL credentials in source references).
"""
import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

HIGH_THRESHOLD = 0.90
MEDIUM_THRESHOLD = 0.72

_URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")


def redact(value: str | None) -> str | None:
    if not value:
        return value
    return _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)


def confidence_bucket(score: float, *, ambiguous: bool) -> str:
    if ambiguous:
        return "low"
    if score >= HIGH_THRESHOLD:
        return "high"
    if score >= MEDIUM_THRESHOLD:
        return "medium"
    return "low"


def assess(unresolved: dict, candidates: list[dict]) -> dict:
    """Turn a raw unresolved entity plus its candidate matches into a review
    record. Pure function — `candidates` is produced by an injectable finder.

    Each candidate: {politician_id, politician_name, party, score, signals, reason}.
    """
    ranked = sorted(candidates, key=lambda c: c.get("score", 0.0), reverse=True)
    distinct_ids = {c.get("politician_id") for c in ranked}
    top = ranked[0] if ranked else None
    # Ambiguous when 2+ distinct politicians score within 0.1 of the top.
    ambiguous = False
    if top and len(distinct_ids) > 1:
        near_top = [c for c in ranked if top["score"] - c.get("score", 0.0) <= 0.1]
        ambiguous = len({c.get("politician_id") for c in near_top}) > 1

    bucket = confidence_bucket(top["score"], ambiguous=ambiguous) if top else "low"
    # We never auto-apply; "recommended_for_review" only flags strong, unambiguous matches.
    recommended_for_review = bool(top and bucket == "high" and not ambiguous)
    if not top:
        reason = "No deterministic candidate found — leave unresolved."
    elif ambiguous:
        reason = "Multiple distinct candidates with similar scores — ambiguous, left unresolved."
    elif bucket == "high":
        reason = f"Strong unique deterministic match via {top['signals']}."
    elif bucket == "medium":
        reason = f"Plausible match via {top['signals']} — needs human confirmation."
    else:
        reason = "Only weak signals — left unresolved."

    return {
        "unresolved_entity_id": str(unresolved.get("id")),
        "raw_value": unresolved.get("raw_value"),
        "entity_type": unresolved.get("entity_type"),
        "source_name": unresolved.get("source_name"),
        "source_url": redact(unresolved.get("source_url")),
        "confidence_bucket": bucket,
        "ambiguous": ambiguous,
        "recommended_for_review": recommended_for_review,
        "reason": reason,
        "candidates": [
            {
                "politician_id": str(c.get("politician_id")),
                "politician_name": c.get("politician_name"),
                "party": c.get("party"),
                "score": round(c.get("score", 0.0), 3),
                "signals": c.get("signals"),
                "match_reason": c.get("reason"),
            }
            for c in ranked[:5]
        ],
    }


def build_report(
    unresolved_records: list[dict],
    finder: Callable[[str], list[dict]],
    *,
    min_score: float = 0.0,
    limit: int | None = None,
) -> dict:
    assessments: list[dict] = []
    for record in unresolved_records[: limit or len(unresolved_records)]:
        candidates = [c for c in finder(record.get("raw_value") or "") if c.get("score", 0.0) >= min_score]
        assessments.append(assess(record, candidates))

    buckets = {"high": 0, "medium": 0, "low": 0}
    for a in assessments:
        buckets[a["confidence_bucket"]] = buckets.get(a["confidence_bucket"], 0) + 1

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "total_assessed": len(assessments),
        "bucket_counts": buckets,
        "recommended_for_review_count": sum(1 for a in assessments if a["recommended_for_review"]),
        "min_score": min_score,
        "assessments": assessments,
        "policy": [
            "Report only — no matches are applied to the database.",
            "Ambiguous candidates are always left unresolved.",
            "Only deterministic, explainable signals are used (no fuzzy/AI matching).",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Entity Resolution Candidate Review",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Unresolved entities assessed:** {report['total_assessed']}",
        f"- **Confidence buckets:** high={report['bucket_counts'].get('high', 0)} "
        f"medium={report['bucket_counts'].get('medium', 0)} low={report['bucket_counts'].get('low', 0)}",
        f"- **Flagged for human review (high, unambiguous):** {report['recommended_for_review_count']}",
        "",
        "## How to review",
        "",
        "These are **suggestions only** — nothing has been applied. For each high/medium",
        "candidate, confirm the match manually before linking. Anything ambiguous is left",
        "unresolved on purpose. No fuzzy or AI matching is used; only deterministic signals.",
        "",
        "## Candidates",
        "",
        "| Unresolved | Source | Bucket | Top candidate | Score | Signals | Note |",
        "|---|---|---|---|---|---|---|",
    ]
    for a in report["assessments"]:
        top = a["candidates"][0] if a["candidates"] else None
        lines.append(
            f"| {a['raw_value']} | {a['source_name']} | {a['confidence_bucket']} | "
            f"{(top or {}).get('politician_name') or '—'} | {(top or {}).get('score') if top else '—'} | "
            f"{(top or {}).get('signals') or '—'} | {a['reason']} |"
        )
    lines += ["", "## Policy", ""]
    lines += [f"- {p}" for p in report["policy"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "entity_resolution_candidates.json"
    md_path = reports_dir / "entity_resolution_candidates.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Real (DB-backed) wiring
# ---------------------------------------------------------------------------

def _db_unresolved_records(db, limit: int) -> list[dict]:
    from sqlalchemy import select

    from app.models.unresolved_entity import UnresolvedEntity

    rows = db.scalars(
        select(UnresolvedEntity)
        .where(UnresolvedEntity.status == "OPEN")
        .order_by(UnresolvedEntity.created_at.desc())
        .limit(limit)
    ).all()
    return [
        {
            "id": r.id,
            "raw_value": r.raw_value,
            "entity_type": r.entity_type,
            "source_name": r.source_name,
            "source_url": r.source_url,
        }
        for r in rows
    ]


def _db_candidate_finder(db) -> Callable[[str], list[dict]]:
    """Deterministic candidate finder: exact name/display/slug/alias + unique surname."""
    from sqlalchemy import func, select

    from app.ingestion.people_assembly import create_slug
    from app.models.politician import Politician
    from app.models.politician_alias import PoliticianAlias

    def party_name(p: Politician) -> str | None:
        try:
            return p.party.short_name if p.party else None
        except Exception:
            return None

    def finder(raw_value: str) -> list[dict]:
        value = " ".join((raw_value or "").strip().split())
        if not value:
            return []
        lowered = value.lower()
        slug = create_slug(value)
        found: dict[Any, dict] = {}

        def add(p: Politician, score: float, signal: str):
            prev = found.get(p.id)
            if prev is None or score > prev["score"]:
                found[p.id] = {
                    "politician_id": p.id,
                    "politician_name": p.full_name,
                    "party": party_name(p),
                    "score": score,
                    "signals": signal,
                    "reason": signal,
                }

        for column, candidate, score, signal in [
            (Politician.full_name, lowered, 0.99, "exact_full_name"),
            (Politician.display_name, lowered, 0.95, "display_name"),
            (Politician.slug, slug, 0.93, "slug"),
        ]:
            for p in db.scalars(select(Politician).where(func.lower(column) == candidate)).all():
                add(p, score, signal)

        for alias in db.scalars(
            select(PoliticianAlias).where(func.lower(PoliticianAlias.alias) == lowered)
        ).all():
            score = 0.72 if alias.alias_type == "SURNAME_ONLY" else 0.90
            add(alias.politician, score, f"alias:{alias.alias_type}")

        # Unique-surname fallback only when nothing stronger was found.
        if not found and len(value.split()) == 1 and len(value) >= 5:
            matches = db.scalars(
                select(Politician).where(func.lower(Politician.display_name).like(f"% {lowered}"))
            ).all()
            for p in matches:
                add(p, 0.72, "unique_surname" if len(matches) == 1 else "surname_ambiguous")
        return list(found.values())

    return finder


def main() -> None:
    parser = argparse.ArgumentParser(description="Report deterministic entity-resolution candidates (no auto-apply).")
    parser.add_argument("--limit", type=int, default=100, help="Max unresolved entities to assess.")
    parser.add_argument("--min-score", type=float, default=0.0, help="Drop candidates below this score.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true", help="Print JSON instead of Markdown.")
    args = parser.parse_args()

    try:
        from app.db import SessionLocal

        with SessionLocal() as db:
            records = _db_unresolved_records(db, args.limit)
            finder = _db_candidate_finder(db)
            report = build_report(records, finder, min_score=args.min_score, limit=args.limit)
    except Exception as exc:
        logger.warning("SKIP: database unavailable (%s) — writing empty report.", type(exc).__name__)
        report = build_report([], lambda v: [], min_score=args.min_score)

    json_path, md_path = write_report(report, Path(args.reports_dir))
    logger.info("entity resolution candidates written: %s, %s", json_path, md_path)
    if args.json_only:
        print(json.dumps(report, default=str))
    else:
        print(render_markdown(report))


if __name__ == "__main__":
    main()
