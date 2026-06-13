#!/usr/bin/env python3
"""Audit IEC manifests for safe structured vote-total parser candidates.

Audit only: never downloads result files and never writes database rows.
"""

import argparse
import json
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

STRUCTURED_FORMATS = {"csv", "xlsx", "json"}
VOTE_ALIASES = {"votes", "vote total", "valid votes", "total votes"}
CONTEST_ALIASES = {"contest id", "contest code"}
ACTOR_ALIASES = {"party id", "party code", "candidate id"}


def redact(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)\b(database_url|password|token|secret|api_key)\b\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@",
        r"\1[REDACTED]@",
        text,
    )


def normalize_columns(columns: list[str]) -> set[str]:
    return {
        " ".join(str(column).strip().lower().replace("_", " ").split())
        for column in columns
        if column
    }


def audit_candidate(candidate: dict) -> dict:
    source_format = str(candidate.get("source_type") or candidate.get("format") or "unknown").lower()
    normalized = normalize_columns(candidate.get("columns", []))
    vote_columns = sorted(normalized & VOTE_ALIASES)
    identifiers_detectable = bool(normalized & CONTEST_ALIASES) and bool(normalized & ACTOR_ALIASES)
    structured = source_format in STRUCTURED_FORMATS
    safe = structured and bool(vote_columns) and identifiers_detectable
    priority = {"csv": 1, "json": 2, "xlsx": 3}.get(source_format) if safe else None

    risks = []
    if not structured:
        risks.append("Format is not a supported structured parser candidate.")
    if structured and not normalized:
        risks.append("No header/schema sample is available; vote columns cannot be verified.")
    if structured and not vote_columns:
        risks.append("No explicit vote-total column was detected.")
    if structured and not identifiers_detectable:
        risks.append("Required contest and party/candidate source identifiers were not detected.")
    risks.extend(str(item) for item in candidate.get("risks", []) if item)

    return {
        "manifest_key": redact(candidate["manifest_key"]) if candidate.get("manifest_key") else None,
        "source_url": redact(candidate.get("source_url") or ""),
        "source_type": source_format,
        "election_type": candidate.get("election_type"),
        "election_year": candidate.get("election_year"),
        "geography_level": candidate.get("geography_level"),
        "parser_readiness": "safe-header-candidate" if safe else "not-safe",
        "vote_total_columns_detected": vote_columns,
        "vote_total_columns_detectable": bool(vote_columns),
        "source_identifiers_detectable": identifiers_detectable,
        "recommended_parser_priority": priority,
        "risks_limitations": risks,
        "rows_ingested": 0,
    }


def build_report(candidates: list[dict], *, limit: int | None = None) -> dict:
    audited = [audit_candidate(item) for item in candidates[: limit or len(candidates)]]
    audited.sort(
        key=lambda item: (
            item["recommended_parser_priority"] is None,
            item["recommended_parser_priority"] or 999,
            item["source_url"],
        )
    )
    selected = next((item for item in audited if item["parser_readiness"] == "safe-header-candidate"), None)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "audit-only",
        "candidate_count": len(audited),
        "structured_candidate_count": sum(1 for item in audited if item["source_type"] in STRUCTURED_FORMATS),
        "safe_header_candidate_count": sum(1 for item in audited if item["parser_readiness"] == "safe-header-candidate"),
        "selected_parser_candidate": (
            {
                "manifest_key": selected["manifest_key"],
                "source_url": selected["source_url"],
                "source_type": selected["source_type"],
                "basis": "Explicit vote-total and source identifier columns detected in audited headers.",
            }
            if selected
            else None
        ),
        "candidates": audited,
        "vote_totals_ingested": False,
        "database_writes": 0,
        "integrity_rules": [
            "Audit only: no IEC result rows or vote totals are ingested.",
            "No large source files are downloaded.",
            "A parser candidate is safe only when explicit vote and source identifier columns are detectable.",
            "No winners, office-bearers, councillors, or internal entity mappings are inferred.",
        ],
    }


def load_fixture(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    return payload.get("candidates", payload if isinstance(payload, list) else [])


def load_database_candidates(limit: int | None = None) -> list[dict]:
    from sqlalchemy import select

    from app.db import SessionLocal
    from app.models.iec_source_manifest import IECSourceManifest

    with SessionLocal() as db:
        statement = select(IECSourceManifest).order_by(IECSourceManifest.created_at, IECSourceManifest.manifest_key)
        if limit:
            statement = statement.limit(limit)
        rows = list(db.scalars(statement))
    return [
        {
            "manifest_key": row.manifest_key,
            "source_url": row.source_url,
            "source_type": row.source_type,
            "election_type": row.election_type,
            "election_year": row.election_year,
            "geography_level": row.geography_level,
            "columns": (row.raw_manifest_json or {}).get("columns")
            or (row.raw_manifest_json or {}).get("header_columns")
            or [],
            "risks": (row.raw_manifest_json or {}).get("risks") or [],
        }
        for row in rows
    ]


def render_markdown(report: dict) -> str:
    lines = [
        "# IEC Structured Source Format Audit",
        "",
        f"- **Generated:** {report['generated_at']}",
        "- **Mode:** audit only; no result rows ingested",
        f"- **Candidates audited:** {report['candidate_count']}",
        f"- **Safe header candidates:** {report['safe_header_candidate_count']}",
        "",
        "| Priority | Format | Source | Election | Geography | Vote columns | Parser readiness | Risks / limitations |",
        "|---:|---|---|---|---|---|---|---|",
    ]
    for item in report["candidates"]:
        lines.append(
            f"| {item['recommended_parser_priority'] or '-'} | {item['source_type']} | {item['source_url']} | "
            f"{item['election_type'] or '-'} {item['election_year'] or ''} | {item['geography_level'] or '-'} | "
            f"{', '.join(item['vote_total_columns_detected']) or 'none'} | {item['parser_readiness']} | "
            f"{'; '.join(item['risks_limitations']) or 'None detected in header audit.'} |"
        )
    lines.extend(["", "## Recommended parser candidate", ""])
    selected = report["selected_parser_candidate"]
    if selected:
        lines.append(
            f"Use **{selected['source_type'].upper()}** as the first parser foundation for "
            f"`{selected['source_url']}`. {selected['basis']}"
        )
    else:
        lines.append("No structured source is safe for parser implementation from the audited metadata.")
    lines.extend(["", "## Integrity rules", ""])
    lines.extend(f"- {rule}" for rule in report["integrity_rules"])
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "iec_structured_format_audit.json"
    markdown_path = reports_dir / "iec_structured_format_audit.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit IEC structured formats without ingesting result rows.")
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    candidates = load_fixture(Path(args.offline_fixture)) if args.offline_fixture else load_database_candidates(args.limit)
    report = build_report(candidates, limit=args.limit)
    write_report(report, Path(args.reports_dir))
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
