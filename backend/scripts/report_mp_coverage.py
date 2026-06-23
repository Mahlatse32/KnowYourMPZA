#!/usr/bin/env python3
"""Generate a conservative, source-backed MP/person coverage scoreboard."""

import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.document_mention import DocumentMention
from app.models.expected_representative_universe import ExpectedRepresentativeUniverse
from app.models.politician import Politician
from app.models.unresolved_entity import UnresolvedEntity


def _blank(column):
    return or_(column.is_(None), func.trim(column) == "")


def _count(db, model, where=None) -> int:
    statement = select(func.count()).select_from(model)
    if where is not None:
        statement = statement.where(where)
    value = db.scalar(statement)
    return int(value or 0)


def _distinct_count(db, column, where=None) -> int:
    statement = select(func.count(func.distinct(column)))
    if where is not None:
        statement = statement.where(where)
    value = db.scalar(statement)
    return int(value or 0)


def _unavailable_report(reason: str) -> dict:
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "unavailable",
        "total_people_records": None,
        "people_with_source_url": None,
        "people_without_source_url": None,
        "current_mp_like_records": None,
        "records_with_party": None,
        "records_without_party": None,
        "records_with_pa_profile": None,
        "records_with_pmg_activity": None,
        "records_with_parliament_source": None,
        "possible_duplicate_names": None,
        "unresolved_aliases": None,
        "missing_expected_representatives": None,
        "expected_representative_count": None,
        "expected_representatives_by_chamber": {},
        "expected_representatives_by_party": {},
        "expected_missing_from_people_records": None,
        "people_records_not_in_expected_universe": None,
        "source_coverage_by_source": {},
        "expected_universe_table_available": False,
        "expected_universe_available": False,
        "reconciliation_checks_passed": False,
        "cannot_claim_all_mps": True,
        "readiness": "red",
        "blockers": [
            reason,
            "No formal source-backed expected MP universe is available for reconciliation.",
        ],
        "recommendations": [
            "Restore or migrate the people tables before assessing coverage.",
            "Implement a reviewed expected-representative universe from authoritative sources.",
        ],
        "methodology": [
            "No counts are estimated when required tables are unavailable.",
            "No MPs, parties, roles, or current-office status are inferred.",
        ],
    }


def build_report(db) -> dict:
    inspector = inspect(db.get_bind())
    table_names = set(inspector.get_table_names())
    if Politician.__tablename__ not in table_names:
        return _unavailable_report("The politicians table is unavailable.")

    expected_table_available = ExpectedRepresentativeUniverse.__tablename__ in table_names
    mentions_available = DocumentMention.__tablename__ in table_names
    unresolved_available = UnresolvedEntity.__tablename__ in table_names

    try:
        total = _count(db, Politician)
        without_source = _count(db, Politician, _blank(Politician.profile_url))
        with_source = total - without_source
        active = _count(db, Politician, Politician.is_active.is_(True))
        without_party = _count(db, Politician, Politician.party_id.is_(None))
        with_party = total - without_party
        pa_profiles = _count(
            db,
            Politician,
            func.lower(Politician.profile_url).like("%pa.org.za%"),
        )
        parliament_profiles = _count(
            db,
            Politician,
            func.lower(Politician.profile_url).like("%parliament.gov.za%"),
        )
        pmg_activity = (
            _distinct_count(
                db,
                DocumentMention.politician_id,
                func.lower(DocumentMention.source_url).like("%pmg.org.za%"),
            )
            if mentions_available
            else None
        )
        duplicate_groups = (
            select(func.lower(func.trim(Politician.full_name)).label("normalized_name"))
            .group_by(func.lower(func.trim(Politician.full_name)))
            .having(func.count() > 1)
            .subquery()
        )
        duplicate_names = int(
            db.scalar(select(func.count()).select_from(duplicate_groups)) or 0
        )
        unresolved_aliases = (
            _count(
                db,
                UnresolvedEntity,
                (
                    (func.lower(UnresolvedEntity.status) == "open")
                    & (
                        func.lower(UnresolvedEntity.entity_type).in_(
                            ["person", "politician", "member", "politician_alias", "alias"]
                        )
                    )
                ),
            )
            if unresolved_available
            else None
        )
        expected_count = (
            _count(db, ExpectedRepresentativeUniverse)
            if expected_table_available
            else None
        )
        expected_by_chamber = (
            {
                str(name): int(count)
                for name, count in db.execute(
                    select(ExpectedRepresentativeUniverse.chamber, func.count()).group_by(
                        ExpectedRepresentativeUniverse.chamber
                    )
                ).all()
            }
            if expected_table_available
            else {}
        )
        expected_by_party = (
            {
                str(name) if name else "unknown": int(count)
                for name, count in db.execute(
                    select(ExpectedRepresentativeUniverse.party_name, func.count()).group_by(
                        ExpectedRepresentativeUniverse.party_name
                    )
                ).all()
            }
            if expected_table_available
            else {}
        )
        people_names = select(func.lower(func.trim(Politician.full_name)))
        expected_names = select(
            func.lower(func.trim(ExpectedRepresentativeUniverse.full_name))
        )
        expected_missing = (
            _count(
                db,
                ExpectedRepresentativeUniverse,
                ~func.lower(func.trim(ExpectedRepresentativeUniverse.full_name)).in_(
                    people_names
                ),
            )
            if expected_table_available and expected_count
            else None
        )
        people_not_expected = (
            _count(
                db,
                Politician,
                ~func.lower(func.trim(Politician.full_name)).in_(expected_names),
            )
            if expected_table_available and expected_count
            else None
        )
    except SQLAlchemyError:
        db.rollback()
        return _unavailable_report("MP coverage queries could not be completed safely.")

    expected_universe_available = bool(expected_table_available and expected_count)
    reconciliation_passes = False
    blockers = []
    recommendations = []
    if not expected_table_available:
        blockers.append(
            "No formal source-backed expected MP universe table exists, so missing representatives cannot be calculated."
        )
        recommendations.append(
            "Create a reviewed expected-representative universe from authoritative Parliament sources."
        )
    elif not expected_universe_available:
        blockers.append(
            "The expected representative universe table exists but contains no source-backed rows."
        )
        recommendations.append(
            "Populate it only from a reviewed official-source fixture before reconciliation."
        )
    else:
        blockers.append(
            "Expected-universe reconciliation is not yet implemented as a reviewed report gate."
        )
        recommendations.append(
            "Define and test the expected-universe reconciliation contract before making completeness claims."
        )
    if without_source:
        blockers.append(f"{without_source} people records do not retain a profile/source URL.")
        recommendations.append("Backfill explicit source URLs without guessing source mappings.")
    if duplicate_names:
        recommendations.append("Review duplicate-like names; do not merge records automatically.")
    if unresolved_aliases:
        recommendations.append("Review unresolved entities using source evidence.")

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "available",
        "total_people_records": total,
        "people_with_source_url": with_source,
        "people_without_source_url": without_source,
        "current_mp_like_records": active,
        "records_with_party": with_party,
        "records_without_party": without_party,
        "records_with_pa_profile": pa_profiles,
        "records_with_pmg_activity": pmg_activity,
        "records_with_parliament_source": parliament_profiles,
        "possible_duplicate_names": duplicate_names,
        "unresolved_aliases": unresolved_aliases,
        "missing_expected_representatives": expected_missing,
        "expected_representative_count": expected_count,
        "expected_representatives_by_chamber": expected_by_chamber,
        "expected_representatives_by_party": expected_by_party,
        "expected_missing_from_people_records": expected_missing,
        "people_records_not_in_expected_universe": people_not_expected,
        "source_coverage_by_source": {
            "people_assembly_profile": pa_profiles,
            "parliament_profile": parliament_profiles,
            "other_profile_source": max(with_source - pa_profiles - parliament_profiles, 0),
            "missing_profile_source": without_source,
            "pmg_activity": pmg_activity,
        },
        "expected_universe_table_available": expected_table_available,
        "expected_universe_available": expected_universe_available,
        "reconciliation_checks_passed": reconciliation_passes,
        "cannot_claim_all_mps": not reconciliation_passes,
        "readiness": (
            "red"
            if not expected_universe_available
            else ("green" if reconciliation_passes else "amber")
        ),
        "blockers": blockers,
        "recommendations": recommendations,
        "methodology": [
            "current_mp_like_records counts stored is_active=true rows; it is not an expected MP universe.",
            "Profile-source coverage uses explicit stored URLs only.",
            "PMG activity counts distinct politicians with explicit PMG document mentions.",
            "Duplicate-like names are review candidates only and are not merged automatically.",
            "No MPs, parties, roles, or source mappings are inferred.",
        ],
    }


def render_markdown(report: dict) -> str:
    def display(value) -> str:
        return "unknown/unavailable" if value is None else str(value)

    lines = [
        "# MP Coverage Scoreboard",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Report status:** {report['status']}",
        f"- **Readiness:** {report['readiness']}",
        f"- **Expected universe available:** {str(report['expected_universe_available']).lower()}",
        f"- **Cannot claim all MPs:** {str(report['cannot_claim_all_mps']).lower()}",
        "",
        "## Counts",
        "",
    ]
    for label, key in (
        ("People records", "total_people_records"),
        ("People with source URL", "people_with_source_url"),
        ("People without source URL", "people_without_source_url"),
        ("Current MP-like stored records", "current_mp_like_records"),
        ("Records with party", "records_with_party"),
        ("Records without party", "records_without_party"),
        ("Records with PA profile", "records_with_pa_profile"),
        ("Records with PMG activity", "records_with_pmg_activity"),
        ("Records with Parliament source", "records_with_parliament_source"),
        ("Possible duplicate names", "possible_duplicate_names"),
        ("Unresolved aliases/entities", "unresolved_aliases"),
        ("Missing expected representatives", "missing_expected_representatives"),
        ("Expected representative rows", "expected_representative_count"),
        ("Expected rows missing from people", "expected_missing_from_people_records"),
        ("People rows not in expected universe", "people_records_not_in_expected_universe"),
    ):
        lines.append(f"- {label}: {display(report[key])}")
    lines.extend(["", "## Source coverage", ""])
    coverage = report["source_coverage_by_source"]
    lines.extend(
        [f"- {name}: {display(count)}" for name, count in sorted(coverage.items())]
        or ["- unavailable"]
    )
    for heading, key in (
        ("Blockers", "blockers"),
        ("Recommendations", "recommendations"),
        ("Methodology", "methodology"),
    ):
        lines.extend(["", f"## {heading}", ""])
        lines.extend(f"- {item}" for item in report[key])
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "mp_coverage_report.json"
    markdown_path = directory / "mp_coverage_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    from app.db import SessionLocal

    with SessionLocal() as db:
        report = build_report(db)
    json_path, markdown_path = write_report(report)
    print(
        json.dumps(
            {
                "json_report": str(json_path),
                "markdown_report": str(markdown_path),
                "readiness": report["readiness"],
                "cannot_claim_all_mps": report["cannot_claim_all_mps"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
