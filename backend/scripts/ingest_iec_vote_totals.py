#!/usr/bin/env python3
"""Ingest one audited IEC CSV vote-total file through an existing manifest."""
import argparse
import json
import os
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.ingestion.iec_vote_totals import parse_vote_totals_csv
from app.models.iec_source_manifest import IECSourceManifest
from app.models.iec_vote_total import IECVoteTotal


_URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_SECRET_RE = re.compile(r"(?i)\b(database_url|password|token|secret)\b\s*[:=]\s*[^\s,;]+")


def redact(value: str) -> str:
    value = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)
    return _SECRET_RE.sub(lambda match: f"{match.group(1)}=[REDACTED]", value)


def load_manifest(db, manifest_key: str) -> IECSourceManifest | None:
    return db.scalar(select(IECSourceManifest).where(IECSourceManifest.manifest_key == manifest_key))


def upsert_vote_total(db, data: dict) -> bool:
    row = db.scalar(select(IECVoteTotal).where(IECVoteTotal.result_key == data["result_key"]))
    if row is None:
        db.add(IECVoteTotal(**data))
        return True
    for field, value in data.items():
        if field != "result_key":
            setattr(row, field, value)
    return False


def run_ingest(db, manifest, input_file: str | Path, *, dry_run: bool = False) -> dict:
    parsed = parse_vote_totals_csv(input_file, manifest)
    created = updated = 0
    failures = list(parsed["failures"])

    if not dry_run:
        for data in parsed["rows"]:
            try:
                with db.begin_nested():
                    if upsert_vote_total(db, data):
                        created += 1
                    else:
                        updated += 1
                    db.flush()
            except Exception as exc:
                failures.append(
                    {
                        "row_number": data["source_row_number"],
                        "error_type": type(exc).__name__,
                        "error": redact(str(exc)[:300]),
                    }
                )
        db.commit()

    party_refs = {
        (row["source_party_id"], row["source_party_name"])
        for row in parsed["rows"]
        if row["source_party_id"] or row["source_party_name"]
    }
    candidate_refs = {
        (row["source_candidate_id"], row["source_candidate_name"])
        for row in parsed["rows"]
        if row["source_candidate_id"] or row["source_candidate_name"]
    }
    valid_count = len(parsed["rows"])
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "dry-run" if dry_run else "real",
        "manifest_key": redact(manifest.manifest_key),
        "manifest_checksum_sha256": manifest.checksum_sha256,
        "source_url": redact(manifest.source_url),
        "source_format": "csv",
        "input_rows": parsed["input_rows"],
        "valid_rows": valid_count,
        "failed_rows": len(failures),
        "created_count": created,
        "updated_count": updated,
        "vote_total_sum": sum(row["vote_total"] for row in parsed["rows"]),
        "unresolved_party_count": len(party_refs),
        "unresolved_candidate_count": len(candidate_refs),
        "failures": failures,
        "exit_code": 1 if valid_count == 0 and failures else 0,
        "winners_ingested": False,
        "office_bearers_ingested": False,
        "internal_party_mapping_applied": False,
        "internal_candidate_mapping_applied": False,
        "geography_mapping_applied": False,
    }


def write_report(report: dict, reports_dir: str | Path) -> tuple[Path, Path]:
    directory = Path(reports_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "iec_vote_totals_report.json"
    markdown_path = directory / "iec_vote_totals_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: dict) -> str:
    lines = [
        "# IEC Vote Totals Ingestion",
        "",
        f"- Mode: {report['mode']}",
        f"- Manifest: `{report['manifest_key']}`",
        f"- Source URL: {report['source_url']}",
        f"- Valid rows: {report['valid_rows']}",
        f"- Failed rows: {report['failed_rows']}",
        f"- Created: {report['created_count']}",
        f"- Updated: {report['updated_count']}",
        f"- Vote total sum: {report['vote_total_sum']}",
        f"- Unresolved source parties: {report['unresolved_party_count']}",
        f"- Unresolved source candidates: {report['unresolved_candidate_count']}",
        "",
        "Safety flags: winners, office-bearers, internal party/candidate mappings, "
        "and geography mappings are all disabled.",
        "",
    ]
    if report["failures"]:
        lines.extend(["## Row failures", ""])
        for failure in report["failures"]:
            lines.append(
                f"- Row {failure.get('row_number')}: {failure.get('error_type')} - "
                f"{redact(str(failure.get('error', '')))}"
            )
        lines.append("")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="Ingest one official IEC party vote-total CSV.")
    parser.add_argument("--manifest-key", required=True)
    parser.add_argument("--input-file", required=True)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if not os.environ.get("DATABASE_URL"):
        print("REFUSED: DATABASE_URL is required to resolve the source manifest.", file=sys.stderr)
        return 2

    from app.db import SessionLocal

    with SessionLocal() as db:
        manifest = load_manifest(db, args.manifest_key)
        if manifest is None:
            print("REFUSED: manifest key was not found.", file=sys.stderr)
            return 2
        report = run_ingest(db, manifest, args.input_file, dry_run=args.dry_run)

    write_report(report, args.reports_dir)
    print(json.dumps(report, sort_keys=True) if args.json_only else render_markdown(report))
    return report["exit_code"]


if __name__ == "__main__":
    raise SystemExit(main())
