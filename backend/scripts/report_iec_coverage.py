#!/usr/bin/env python3
"""Report IEC metadata, manifest, and vote-total evidence quality."""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.iec_election import IECElection
from app.models.iec_source_manifest import IECSourceManifest
from app.models.iec_vote_total import IECVoteTotal


def _has_table(db, name: str) -> bool:
    return inspect(db.get_bind()).has_table(name)


def _scalar(db, statement, default=0):
    try:
        value = db.scalar(statement)
        return default if value is None else value
    except SQLAlchemyError:
        db.rollback()
        return default


def _count(db, model, where=None) -> int:
    statement = select(func.count()).select_from(model)
    if where is not None:
        statement = statement.where(where)
    return int(_scalar(db, statement))


def _blank(column):
    return or_(column.is_(None), func.trim(column) == "")


def _group_counts(db, column) -> dict[str, int]:
    rows = db.execute(select(column, func.count()).group_by(column)).all()
    return {str(key) if key is not None else "unknown": int(count) for key, count in rows}


def _distinct_source_refs(db, column) -> int:
    return int(_scalar(db, select(func.count(func.distinct(column))).where(~_blank(column))))


def determine_public_readiness(report: dict) -> dict:
    integrity_failures = sum(
        int(report.get(key) or 0)
        for key in (
            "vote_totals_without_manifest",
            "missing_source_url_count",
            "missing_manifest_key_count",
            "duplicate_result_key_count",
        )
    )
    if integrity_failures:
        return {
            "status": "red",
            "reason": "Source-evidence or identifier integrity failures require correction.",
        }
    if (
        report.get("manifest_count", 0) == 0
        or report.get("vote_total_rows_count") in (None, 0)
        or int(report.get("manifests_without_vote_totals") or 0) > 0
    ):
        return {
            "status": "yellow",
            "reason": "Evidence is internally consistent but vote-total coverage is incomplete or unavailable.",
        }
    return {
        "status": "green",
        "reason": "Every stored manifest has vote totals and no evidence-integrity failures were detected.",
    }


def build_report(db) -> dict:
    elections_available = _has_table(db, IECElection.__tablename__)
    manifests_available = _has_table(db, IECSourceManifest.__tablename__)
    votes_available = _has_table(db, IECVoteTotal.__tablename__)

    election_count = _count(db, IECElection) if elections_available else 0
    manifest_count = _count(db, IECSourceManifest) if manifests_available else 0
    reachable = (
        _count(db, IECSourceManifest, IECSourceManifest.reachable.is_(True))
        if manifests_available else 0
    )
    structured = (
        _count(db, IECSourceManifest, IECSourceManifest.parser_readiness == "structured-candidate")
        if manifests_available else 0
    )
    missing_manifest_urls = (
        _count(db, IECSourceManifest, _blank(IECSourceManifest.source_url))
        if manifests_available else 0
    )

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "available" if manifests_available or elections_available else "unavailable",
        "vote_totals_table_available": votes_available,
        "election_count": election_count,
        "manifest_count": manifest_count,
        "reachable_manifest_count": reachable,
        "structured_manifest_count": structured,
        "vote_total_rows_count": None,
        "vote_total_sum": None,
        "manifests_without_vote_totals": manifest_count,
        "vote_totals_without_manifest": None,
        "missing_source_url_count": missing_manifest_urls,
        "missing_manifest_key_count": None,
        "duplicate_result_key_count": None,
        "parser_readiness_counts": (
            _group_counts(db, IECSourceManifest.parser_readiness) if manifests_available else {}
        ),
        "coverage_by_election_type": (
            _group_counts(db, IECSourceManifest.election_type) if manifests_available else {}
        ),
        "coverage_by_election_year": (
            _group_counts(db, IECSourceManifest.election_year) if manifests_available else {}
        ),
        "coverage_by_geography_level": (
            _group_counts(db, IECSourceManifest.geography_level) if manifests_available else {}
        ),
        "unresolved_source_party_count": None,
        "unresolved_source_candidate_count": None,
        "unresolved_source_geography_count": None,
        "winners_ingested": False,
        "office_bearers_ingested": False,
        "internal_party_mapping_applied": False,
        "internal_candidate_mapping_applied": False,
        "internal_geography_mapping_applied": False,
    }

    if votes_available:
        vote_count = _count(db, IECVoteTotal)
        represented_manifest_keys = select(IECVoteTotal.manifest_key).distinct()
        manifests_without = (
            _count(
                db,
                IECSourceManifest,
                ~IECSourceManifest.manifest_key.in_(represented_manifest_keys),
            )
            if manifests_available else 0
        )
        orphaned = (
            _count(
                db,
                IECVoteTotal,
                ~IECVoteTotal.manifest_key.in_(select(IECSourceManifest.manifest_key)),
            )
            if manifests_available else vote_count
        )
        duplicate_groups = (
            select(IECVoteTotal.result_key)
            .group_by(IECVoteTotal.result_key)
            .having(func.count() > 1)
            .subquery()
        )

        report.update(
            {
                "vote_total_rows_count": vote_count,
                "vote_total_sum": int(
                    _scalar(db, select(func.sum(IECVoteTotal.vote_total)), default=0)
                ),
                "manifests_without_vote_totals": manifests_without,
                "vote_totals_without_manifest": orphaned,
                "missing_source_url_count": missing_manifest_urls
                + _count(db, IECVoteTotal, _blank(IECVoteTotal.source_url)),
                "missing_manifest_key_count": _count(
                    db, IECVoteTotal, _blank(IECVoteTotal.manifest_key)
                ),
                "duplicate_result_key_count": int(
                    _scalar(db, select(func.count()).select_from(duplicate_groups))
                ),
                "unresolved_source_party_count": _distinct_source_refs(
                    db, IECVoteTotal.source_party_id
                ),
                "unresolved_source_candidate_count": _distinct_source_refs(
                    db, IECVoteTotal.source_candidate_id
                ),
                "unresolved_source_geography_count": _distinct_source_refs(
                    db, IECVoteTotal.source_geography_id
                ),
            }
        )

    report["public_readiness"] = determine_public_readiness(report)
    return report


def write_report(report: dict, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "iec_coverage_report.json"
    markdown_path = directory / "iec_coverage_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: dict) -> str:
    readiness = report["public_readiness"]
    lines = [
        "# IEC Coverage Quality Report",
        "",
        f"- Public readiness: **{readiness['status']}**",
        f"- Reason: {readiness['reason']}",
        f"- Elections: {report['election_count']}",
        f"- Manifests: {report['manifest_count']}",
        f"- Reachable manifests: {report['reachable_manifest_count']}",
        f"- Structured manifests: {report['structured_manifest_count']}",
        f"- Vote-total rows: {_display(report['vote_total_rows_count'])}",
        f"- Vote-total sum: {_display(report['vote_total_sum'])}",
        f"- Manifests without vote totals: {report['manifests_without_vote_totals']}",
        f"- Vote totals without manifest: {_display(report['vote_totals_without_manifest'])}",
        f"- Missing source URLs: {report['missing_source_url_count']}",
        f"- Missing manifest keys: {_display(report['missing_manifest_key_count'])}",
        f"- Duplicate result keys: {_display(report['duplicate_result_key_count'])}",
        "",
        "## Unresolved source identifiers",
        "",
        f"- Parties: {_display(report['unresolved_source_party_count'])}",
        f"- Candidates: {_display(report['unresolved_source_candidate_count'])}",
        f"- Geographies: {_display(report['unresolved_source_geography_count'])}",
        "",
        "No winners, office-bearers, or internal entity mappings are ingested or inferred.",
        "",
    ]
    for label, key in (
        ("Parser readiness", "parser_readiness_counts"),
        ("Election type", "coverage_by_election_type"),
        ("Election year", "coverage_by_election_year"),
        ("Geography level", "coverage_by_geography_level"),
    ):
        lines.extend([f"## Coverage by {label.lower()}", ""])
        counts = report[key]
        lines.extend([f"- {name}: {count}" for name, count in sorted(counts.items())] or ["- No data"])
        lines.append("")
    return "\n".join(lines)


def _display(value) -> str:
    return "unavailable" if value is None else str(value)


def main() -> int:
    from app.db import SessionLocal

    with SessionLocal() as db:
        report = build_report(db)
    paths = write_report(report)
    print(json.dumps({"json_report": str(paths[0]), "markdown_report": str(paths[1])}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
