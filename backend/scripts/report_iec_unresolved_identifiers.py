#!/usr/bin/env python3
"""Report unresolved source identifiers from IEC vote totals (#24).

Read-only report. Groups the distinct source-supplied identifiers in
`iec_vote_totals` (party, candidate, geography, contest) so a future
reconciliation phase can build an EXPLICIT source-identifier registry. It
performs NO mapping to internal parties/politicians/geographies, infers NO
winners or office-holders, and writes NO database rows. `mapping_status` is
always `unresolved`.

Outputs:
  reports/iec_unresolved_identifiers.json
  reports/iec_unresolved_identifiers.md

Unavailable-safe: if the table is missing, reports `status: unavailable`.
Credential-safe: source URLs are redacted of any embedded credentials.
"""
import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import func, inspect, or_, select
from sqlalchemy.exc import SQLAlchemyError

from app.models.iec_vote_total import IECVoteTotal

_URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")


def redact(value: str | None) -> str | None:
    if not value:
        return value
    return _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)


def _blank(column):
    return or_(column.is_(None), func.trim(column) == "")


def _grouped(db, *, id_col, name_col, extra_cols=(), require_present=False) -> list[dict]:
    """Group vote totals by the given source identifier columns. Returns one
    record per distinct combination with counts, vote sum, and provenance."""
    vt = IECVoteTotal
    group_cols = [*extra_cols, id_col, name_col]
    stmt = select(
        *group_cols,
        func.count().label("row_count"),
        func.coalesce(func.sum(vt.vote_total), 0).label("vote_total_sum"),
        func.min(vt.manifest_key).label("first_seen_manifest_key"),
        func.min(vt.source_url).label("sample_source_url"),
    ).group_by(*group_cols)
    if require_present:
        # candidate columns are nullable: skip rows where id and name are blank
        stmt = stmt.where(~(_blank(id_col) & _blank(name_col)))
    try:
        rows = db.execute(stmt).all()
    except SQLAlchemyError:
        db.rollback()
        return []
    out = []
    n_extra = len(extra_cols)
    for row in rows:
        extra_vals = list(row[:n_extra])
        ident = row[n_extra]
        name = row[n_extra + 1]
        row_count = row[n_extra + 2]
        vote_sum = row[n_extra + 3]
        manifest_key = row[n_extra + 4]
        sample_url = row[n_extra + 5]
        rec = {
            "source_id": ident,
            "source_name": name,
            "row_count": int(row_count or 0),
            "vote_total_sum": int(vote_sum or 0),
            "first_seen_manifest_key": manifest_key,
            "sample_source_url": redact(sample_url),
            "mapping_status": "unresolved",
        }
        for i, col in enumerate(extra_cols):
            rec[col.key] = extra_vals[i]
        out.append(rec)
    return out


def _counts_by(db, *cols) -> dict:
    vt = IECVoteTotal
    try:
        rows = db.execute(select(*cols, func.count()).group_by(*cols)).all()
    except SQLAlchemyError:
        db.rollback()
        return {}
    out = {}
    for row in rows:
        key = "/".join("unknown" if v is None else str(v) for v in row[:-1])
        out[key] = int(row[-1])
    return out


def build_report(db) -> dict:
    vt = IECVoteTotal
    available = inspect(db.get_bind()).has_table(vt.__tablename__)
    base = {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "available" if available else "unavailable",
        "mapping_status": "unresolved",
        "recommended_next_action": [
            "Create explicit source-identifier registry tables before any reconciliation.",
            "Do not auto-map source identifiers to internal party/politician/geography.",
            "Resolve only via exact official IDs, separately designed and tested.",
        ],
        "integrity_rules": [
            "Report only — no database rows are written and no mappings are created.",
            "No winner or office-holder inference.",
            "All identifiers remain unresolved.",
        ],
    }
    if not available:
        base.update({
            "total_rows": 0, "parties": [], "candidates": [], "geographies": [], "contests": [],
            "counts_by_election_type": {}, "counts_by_election_year": {},
        })
        return base

    total_rows = int(db.scalar(select(func.count()).select_from(vt)) or 0)
    base.update({
        "total_rows": total_rows,
        "parties": _grouped(db, id_col=vt.source_party_id, name_col=vt.source_party_name),
        "candidates": _grouped(db, id_col=vt.source_candidate_id, name_col=vt.source_candidate_name, require_present=True),
        "geographies": _grouped(db, id_col=vt.source_geography_id, name_col=vt.source_geography_name, extra_cols=(vt.geography_level,)),
        "contests": _grouped(db, id_col=vt.source_contest_id, name_col=vt.source_contest_name),
        "counts_by_election_type": _counts_by(db, vt.election_type),
        "counts_by_election_year": _counts_by(db, vt.election_year),
    })
    return base


def render_markdown(report: dict) -> str:
    lines = [
        "# IEC Unresolved Source Identifiers",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Status:** {report['status']}",
        f"- **Mapping status:** {report['mapping_status']} (no internal mapping performed)",
        f"- **Total vote-total rows:** {report.get('total_rows', 0)}",
        "",
    ]
    for section in ("parties", "candidates", "geographies", "contests"):
        recs = report.get(section, [])
        lines += [f"## Unresolved {section} ({len(recs)})", ""]
        if recs:
            lines += ["| Source ID | Source name | Rows | Vote sum | First manifest |", "|---|---|---:|---:|---|"]
            for r in recs[:50]:
                lines.append(
                    f"| {r.get('source_id')} | {r.get('source_name') or ''} | {r['row_count']} | "
                    f"{r['vote_total_sum']} | {r.get('first_seen_manifest_key') or ''} |"
                )
        else:
            lines.append("None.")
        lines.append("")
    lines += ["## Recommended next action", ""]
    lines += [f"- {a}" for a in report["recommended_next_action"]]
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "iec_unresolved_identifiers.json"
    md_path = reports_dir / "iec_unresolved_identifiers.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Report unresolved IEC source identifiers (read-only).")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    from app.db import SessionLocal

    with SessionLocal() as db:
        report = build_report(db)
    write_report(report, Path(args.reports_dir))
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
