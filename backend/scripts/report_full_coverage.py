"""Full data coverage report — JSON + Markdown output.

Queries the live database and writes two report files:
  backend/reports/full_coverage_report.json
  backend/reports/full_coverage_report.md

The report shows what exists, what is missing, and what cannot yet be
verified against an authoritative external total.

Examples:
    python scripts/report_full_coverage.py
    python scripts/report_full_coverage.py --json-only
    python scripts/report_full_coverage.py --md-only
"""
import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime
from typing import Any

from app.db import SessionLocal
from app.services.coverage_service import generate_full_coverage_report

OUTPUT_DIR = Path("reports")
JSON_PATH = OUTPUT_DIR / "full_coverage_report.json"
MD_PATH = OUTPUT_DIR / "full_coverage_report.md"


def _pct_str(val: float | None) -> str:
    if val is None:
        return "unknown %"
    return f"{val:.1f}%"


def _row(label: str, value: Any, note: str = "") -> str:
    note_str = f" _{note}_" if note else ""
    return f"| {label} | {value} |{note_str}\n"


def build_markdown(report: dict) -> str:
    c = report["database_counts"]
    pc = report["politician_coverage"]
    cc = report["committee_coverage"]
    pmg = report["pmg_coverage"]
    qc = report["question_coverage"]
    pdf = report["pdf_coverage"]
    arc = report["archive_coverage"]
    ue = report["unresolved_entity_coverage"]
    dup = report["duplicate_candidates"]
    weak = report["weak_records"]

    lines: list[str] = []

    lines.append("# KnowYourMPZA — Full Data Coverage Report\n\n")
    lines.append(f"**Generated:** {report['generated_at']}\n\n")
    lines.append(
        "> **Coverage caveat:** percentages are measured against records discovered from known "
        "public sources, not against an independently verified total universe. "
        "Where the denominator is unknown, the percentage is marked _unknown %_.\n\n"
    )

    # Politicians
    lines.append("## Politicians\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("Total politicians", c["politicians_total"]))
    lines.append(_row("Active", c["active_politicians_total"]))
    lines.append(_row("Former / historical", c["former_politicians_total"]))
    lines.append(_row("With party", c["politicians_with_party"], f"{_pct_str(pc['with_party_pct'])} of total"))
    lines.append(_row("Without party", c["politicians_without_party"]))
    lines.append(_row("With source URL", c["politicians_with_source_url"], f"{_pct_str(pc['with_source_url_pct'])} of total"))
    lines.append(_row("Without source URL", c["politicians_without_source_url"]))
    lines.append(_row("With aliases", c["politicians_with_aliases"], f"{_pct_str(pc['with_aliases_pct'])} of total"))
    lines.append(_row("Without aliases", c["politicians_without_aliases"]))
    lines.append(_row("With committee memberships", c["politicians_with_committees"], f"{_pct_str(pc['with_committees_pct'])} of total"))
    lines.append(_row("Without committee memberships", c["politicians_without_committees"]))
    lines.append("\n")

    # Parties
    lines.append("## Parties\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("Total parties", c["parties_total"]))
    lines.append(_row("Duplicate short names", dup["duplicate_party_short_names"]))
    lines.append("\n")

    # Committees
    lines.append("## Committees\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("Total committees", cc["total"]))
    lines.append(_row("Total memberships", cc["memberships_total"]))
    lines.append(_row("Committees without memberships", cc["committees_without_memberships"]))
    lines.append(_row("Duplicate committee slugs", dup["duplicate_committee_slugs"]))
    lines.append("\n")

    # PMG
    lines.append("## PMG Meeting Documents\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("PMG documents total", pmg["pmg_documents_total"]))
    lines.append(_row("With archive path", _pct_str(pmg["with_archive_path_pct"])))
    lines.append(_row("With politician mentions", _pct_str(pmg["with_mentions_pct"])))
    lines.append(_row("Total politician mentions", pmg["total_mentions"]))
    lines.append(_row("Low-confidence mentions (< 0.8)", pmg["low_confidence_mentions"]))
    lines.append(_row("Duplicate document source URLs", dup["duplicate_document_source_urls"]))
    lines.append("\n")

    # Parliamentary Questions
    lines.append("## Parliamentary Questions\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("Total questions", qc["total"]))
    lines.append(_row("With archive path", _pct_str(qc["with_archive_pct"])))
    lines.append(_row("Asker resolved to politician", _pct_str(qc["resolved_asker_pct"])))
    lines.append(_row("PDF-backed sources", qc["pdf_sources"]))
    lines.append(_row("Parsed successfully", qc["parse_ok"]))
    lines.append(_row("Parse failed", qc["parse_failed"]))
    lines.append(_row("Duplicate question source URLs", dup["duplicate_question_source_urls"]))
    lines.append("\n")

    # PDF / Archive
    lines.append("## PDF Extraction & Archives\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("PDF-backed questions", pdf["pdf_backed_questions"]))
    lines.append(_row("Extracted text successfully", pdf["parse_ok"], _pct_str(pdf["extracted_text_pct"])))
    lines.append(_row("Extraction failed", pdf["parse_failed"]))
    lines.append(_row("Documents with archive path", _pct_str(arc["documents_with_archive_pct"])))
    lines.append(_row("Questions with archive path", _pct_str(arc["questions_with_archive_pct"])))
    lines.append(_row("Documents without archive or text", weak["documents_without_archive_or_text"]))
    lines.append("\n")

    # Unresolved entities
    lines.append("## Unresolved Entities\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("Total", ue["total"]))
    lines.append(_row("Open (need review)", ue["open"]))
    lines.append(_row("Resolved", ue["resolved"]))
    lines.append(_row("Ignored", ue["ignored"]))
    lines.append("\n")

    if ue.get("by_source"):
        lines.append("**Open unresolved entities by source (top 10):**\n\n")
        lines.append("| Source | Count |\n|---|---|\n")
        for src, count in list(ue["by_source"].items())[:10]:
            lines.append(f"| {src} | {count} |\n")
        lines.append("\n")

    # Ingestion health
    lines.append("## Ingestion Health\n\n")
    lines.append("| Metric | Value |\n|---|---|\n")
    lines.append(_row("Total ingestion runs", c["ingestion_runs_total"]))
    lines.append(_row("Failed ingestion runs", c["failed_ingestion_runs"]))
    lines.append("\n")

    runs = report.get("latest_ingestion_runs", [])
    if runs:
        lines.append("**Recent ingestion runs (latest 10):**\n\n")
        lines.append("| Source | Type | Status | Started | Created | Updated | Failed |\n|---|---|---|---|---|---|---|\n")
        for r in runs:
            started = (r["started_at"] or "")[:19]
            lines.append(
                f"| {r['source_name']} | {r['run_type']} | {r['status']} "
                f"| {started} | {r['created_count']} | {r['updated_count']} | {r['failed_count']} |\n"
            )
        lines.append("\n")

    errors = report.get("latest_ingestion_errors", [])
    if errors:
        lines.append("**Recent ingestion errors (latest 20):**\n\n")
        lines.append("| Source URL | Error |\n|---|---|\n")
        for e in errors[:20]:
            url = (e.get("source_url") or "")[:80]
            msg = (e.get("error_message") or "")[:100].replace("|", "\\|")
            lines.append(f"| {url} | {msg} |\n")
        lines.append("\n")

    # Recommendations
    lines.append("## Recommendations\n\n")
    for rec in report["recommendations"]:
        lines.append(f"- {rec}\n")
    lines.append("\n")

    # Source coverage table
    lines.append("## Source Coverage\n\n")
    lines.append(
        "> Coverage percentages are not shown where the authoritative total is unknown. "
        "The notes column explains what each figure represents.\n\n"
    )
    lines.append("| Category | Ingested | Note |\n|---|---|---|\n")
    for s in report["source_coverage"]:
        lines.append(f"| {s['category']} | {s['ingested_total']} | {s['coverage_note']} |\n")
    lines.append("\n")

    # Weak records
    lines.append("## Weak Records\n\n")
    lines.append("| Issue | Count |\n|---|---|\n")
    lines.append(_row("Active politicians without source URL", weak["active_politicians_without_source_url"]))
    lines.append(_row("Documents without archive path or extracted text", weak["documents_without_archive_or_text"]))
    lines.append("\n")

    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate full data coverage report (JSON + Markdown).")
    parser.add_argument("--json-only", action="store_true", help="Write only JSON output.")
    parser.add_argument("--md-only", action="store_true", help="Write only Markdown output.")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    with SessionLocal() as db:
        report = generate_full_coverage_report(db)

    if not args.md_only:
        JSON_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"json_report: {JSON_PATH}")

    if not args.json_only:
        md = build_markdown(report)
        MD_PATH.write_text(md, encoding="utf-8")
        print(f"md_report: {MD_PATH}")

    c = report["database_counts"]
    print(f"politicians: {c['politicians_total']} ({c['active_politicians_total']} active)")
    print(f"parties: {c['parties_total']}")
    print(f"committees: {c['committees_total']}")
    print(f"memberships: {c['committee_memberships_total']}")
    print(f"pmg_documents: {c['pmg_documents_total']}")
    print(f"parliamentary_questions: {c['parliamentary_questions_total']}")
    print(f"unresolved_open: {c['unresolved_entities_open']}")
    print("recommendations:")
    for rec in report["recommendations"]:
        print(f"  - {rec}")


if __name__ == "__main__":
    main()
