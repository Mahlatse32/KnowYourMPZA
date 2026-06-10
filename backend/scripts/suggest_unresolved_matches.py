"""Suggest politician matches for open unresolved entities.

Generates conservative match suggestions using the existing entity resolution
service. Does NOT auto-resolve by default. Pass --apply to auto-resolve
suggestions above the confidence threshold (use with caution).

Output: backend/reports/unresolved_match_suggestions.json

Examples:
    python scripts/suggest_unresolved_matches.py
    python scripts/suggest_unresolved_matches.py --apply --threshold 0.9
    python scripts/suggest_unresolved_matches.py --limit 500
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime

from sqlalchemy import select

from app.db import SessionLocal
from app.models.politician_alias import PoliticianAlias
from app.models.unresolved_entity import UnresolvedEntity
from app.services.entity_resolution import resolve_politician_name

DEFAULT_THRESHOLD = 0.9
AUTO_APPLY_MIN_THRESHOLD = 0.9


def suggest_matches(db, limit: int = 1000) -> list[dict]:
    open_entities = list(
        db.scalars(
            select(UnresolvedEntity)
            .where(UnresolvedEntity.status == "OPEN")
            .order_by(UnresolvedEntity.created_at.desc())
            .limit(limit)
        )
    )
    suggestions = []
    for entity in open_entities:
        resolution = resolve_politician_name(db, entity.raw_value)
        if resolution is None:
            suggestions.append(
                {
                    "unresolved_entity_id": str(entity.id),
                    "unresolved_name": entity.raw_value,
                    "source_type": entity.entity_type,
                    "source_name": entity.source_name,
                    "source_url": entity.source_url,
                    "suggested_politician_id": None,
                    "suggested_politician_name": None,
                    "score": None,
                    "reason": "no_match",
                }
            )
        else:
            suggestions.append(
                {
                    "unresolved_entity_id": str(entity.id),
                    "unresolved_name": entity.raw_value,
                    "source_type": entity.entity_type,
                    "source_name": entity.source_name,
                    "source_url": entity.source_url,
                    "suggested_politician_id": str(resolution.politician.id),
                    "suggested_politician_name": resolution.politician.display_name,
                    "score": resolution.confidence_score,
                    "reason": resolution.match_reason,
                }
            )
    return suggestions


def apply_suggestions(db, suggestions: list[dict], threshold: float) -> tuple[int, int]:
    applied = skipped = 0
    for suggestion in suggestions:
        if suggestion["suggested_politician_id"] is None:
            continue
        if (suggestion["score"] or 0) < threshold:
            skipped += 1
            continue
        entity = db.get(UnresolvedEntity, suggestion["unresolved_entity_id"])
        if entity is None or entity.status != "OPEN":
            skipped += 1
            continue
        entity.status = "RESOLVED"
        entity.resolved_politician_id = suggestion["suggested_politician_id"]
        entity.resolved_at = datetime.now(UTC)
        entity.resolution_notes = f"auto-resolved by suggest_unresolved_matches.py (score={suggestion['score']:.2f}, reason={suggestion['reason']})"
        alias_text = " ".join(entity.raw_value.strip().split())
        existing_alias = db.scalars(
            select(PoliticianAlias).where(
                PoliticianAlias.politician_id == suggestion["suggested_politician_id"],
                PoliticianAlias.alias == alias_text,
            )
        ).first()
        if existing_alias is None:
            db.add(
                PoliticianAlias(
                    politician_id=suggestion["suggested_politician_id"],
                    alias=alias_text,
                    alias_type="SOURCE_VARIANT",
                    source_url=entity.source_url,
                )
            )
        applied += 1
    if applied:
        db.commit()
    return applied, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description="Suggest matches for unresolved entities.")
    parser.add_argument("--limit", type=int, default=1000, help="Max unresolved entities to check.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help=(
            f"AUTO-RESOLVE suggestions above --threshold. "
            f"Default threshold is {AUTO_APPLY_MIN_THRESHOLD}. "
            "Review the report before using this flag."
        ),
    )
    parser.add_argument(
        "--threshold",
        type=float,
        default=AUTO_APPLY_MIN_THRESHOLD,
        help=f"Confidence threshold for --apply (default: {AUTO_APPLY_MIN_THRESHOLD}).",
    )
    args = parser.parse_args()

    if args.apply and args.threshold < AUTO_APPLY_MIN_THRESHOLD:
        print(f"WARNING: --threshold {args.threshold} is below the minimum safe threshold {AUTO_APPLY_MIN_THRESHOLD}.")
        print("Aborting. Raise --threshold or review the report manually.")
        sys.exit(1)

    with SessionLocal() as db:
        suggestions = suggest_matches(db, limit=args.limit)

        matched = [s for s in suggestions if s["suggested_politician_id"] is not None]
        unmatched = [s for s in suggestions if s["suggested_politician_id"] is None]
        high_confidence = [s for s in matched if (s["score"] or 0) >= DEFAULT_THRESHOLD]

        print(f"open_entities_checked: {len(suggestions)}")
        print(f"matched: {len(matched)}")
        print(f"high_confidence_matches (>= {DEFAULT_THRESHOLD}): {len(high_confidence)}")
        print(f"unmatched: {len(unmatched)}")

        if args.apply:
            print(f"\nWARNING: --apply mode. Auto-resolving matches with score >= {args.threshold}.")
            applied, skipped = apply_suggestions(db, suggestions, threshold=args.threshold)
            print(f"applied: {applied}")
            print(f"skipped: {skipped}")

    output_dir = Path("reports")
    output_dir.mkdir(parents=True, exist_ok=True)
    output_path = output_dir / "unresolved_match_suggestions.json"
    output_path.write_text(
        json.dumps(
            {
                "generated_at": datetime.now(UTC).isoformat(),
                "total_checked": len(suggestions),
                "matched_count": len(matched),
                "high_confidence_count": len(high_confidence),
                "unmatched_count": len(unmatched),
                "default_threshold": DEFAULT_THRESHOLD,
                "suggestions": suggestions,
            },
            indent=2,
            default=str,
        ),
        encoding="utf-8",
    )
    print(f"\nreport_path: {output_path}")
    if not args.apply and high_confidence:
        print(f"tip: {len(high_confidence)} high-confidence matches found. Review the report, then run with --apply to resolve them.")


if __name__ == "__main__":
    main()
