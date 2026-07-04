#!/usr/bin/env python3
"""Aggregate existing reports into a conservative V1 readiness assessment."""

import argparse
import json
import re
from datetime import UTC, datetime
from pathlib import Path


REPORT_FILES = {
    "data_coverage": "data_coverage_dashboard.json",
    "iec_coverage": "iec_coverage_report.json",
    "inspect": "inspect_db.json",
    "mp_coverage": "mp_coverage_report.json",
    "ingestion_brief": "ingestion_brief.json",
    "mp_source_audit": "mp_member_source_audit.json",
    "people_assembly": "people_assembly_ingestion_summary.json",
    "pmg_ingestion": "pmg_ingestion_summary.json",
    "parliamentary_questions_ingestion": "parliamentary_questions_ingestion_summary.json",
}

SOURCE_TOTALS = {
    "pmg_bills": 1246,
    "pmg_committee_meetings": 34710,
    "parliamentary_questions": 44036,
}

LAUNCH_COVERAGE_TARGET = 80.0


def redact(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)\b(database_url|password|passwd|secret|token|api_key|authorization)\b"
        r"(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@",
        r"\1[REDACTED]:[REDACTED]@",
        text,
    )


def _load_json(path: Path) -> tuple[dict | None, str | None]:
    if not path.exists():
        return None, f"{path.name} is missing."
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None, f"{path.name} could not be read as JSON."
    return payload if isinstance(payload, dict) else None, None


def load_inputs(reports_dir: Path, source_inventory_path: Path | None = None) -> dict:
    inputs = {}
    warnings = []
    for key, filename in REPORT_FILES.items():
        inputs[key], warning = _load_json(reports_dir / filename)
        if warning:
            warnings.append(warning)
    inventory = source_inventory_path or Path("docs/source-inventory.md")
    inputs["source_inventory_exists"] = inventory.exists()
    inputs["input_warnings"] = warnings
    return inputs


def _normalize_status(value: object, default: str = "red") -> str:
    status = str(value or "").lower()
    if status == "yellow":
        return "amber"
    return status if status in {"red", "amber", "green"} else default


def _pa_blocked(inputs: dict) -> bool:
    summary = inputs.get("people_assembly") or {}
    if summary.get("systemic_source_access_failure") is True:
        return True
    brief = inputs.get("ingestion_brief") or {}
    searchable = json.dumps(
        {
            "status": brief.get("status"),
            "reasons": brief.get("reasons"),
            "attention_required": brief.get("attention_required"),
        }
    ).lower()
    return "people's assembly source access failed systemically" in searchable


def build_report(inputs: dict) -> dict:
    mp = inputs.get("mp_coverage") or {}
    dashboard = inputs.get("data_coverage") or {}
    iec = inputs.get("iec_coverage") or {}
    brief = inputs.get("ingestion_brief") or {}

    expected_universe = mp.get("expected_universe_available") is True
    can_claim_all = expected_universe and mp.get("cannot_claim_all_mps") is False
    people_status = _normalize_status(mp.get("readiness")) if mp else "red"
    if not expected_universe:
        people_status = "red"

    public_claim = (dashboard.get("public_claim_readiness") or {}).get(
        "safe_for_public_facing_completeness_claims"
    )
    parliamentary_status = "green" if public_claim is True else ("amber" if dashboard else "red")

    iec_complete = iec.get("full_iec_ingestion_complete") is True
    iec_public = _normalize_status((iec.get("public_readiness") or {}).get("status"), "amber")
    if not iec:
        iec_status = "red"
    elif iec_complete and iec_public == "green":
        iec_status = "green"
    else:
        iec_status = "amber"

    ingestion_status = _normalize_status(brief.get("status")) if brief else "red"
    pa_blocked = _pa_blocked(inputs)
    if pa_blocked:
        pa_status = "amber"
    elif inputs.get("people_assembly"):
        pa_status = "green" if ingestion_status == "green" else "amber"
    else:
        pa_status = "amber"

    inventory_exists = inputs.get("source_inventory_exists") is True
    audit_exists = bool(inputs.get("mp_source_audit"))
    source_inventory_status = (
        "green" if inventory_exists and audit_exists else ("amber" if inventory_exists else "red")
    )

    statuses = [
        people_status,
        parliamentary_status,
        iec_status,
        ingestion_status,
        pa_status,
        source_inventory_status,
    ]
    if not expected_universe or "red" in statuses:
        overall = "red"
    elif all(status == "green" for status in statuses) and iec_complete and can_claim_all:
        overall = "green"
    else:
        overall = "amber"

    blockers = []
    if not expected_universe:
        blockers.append(
            "The formal source-backed expected MP universe is missing; all-MP coverage cannot be measured."
        )
    if mp:
        blockers.extend(redact(item) for item in mp.get("blockers", []) if item)
    else:
        blockers.append("The MP coverage report is missing.")
    if not dashboard:
        blockers.append("The data coverage dashboard is missing.")
    if not iec:
        blockers.append("The IEC coverage report is missing.")
    elif not iec_complete:
        blockers.append("IEC remains foundation-only and issue #24 is not complete.")
    if not brief:
        blockers.append("The ingestion brief is missing.")
    elif ingestion_status == "red":
        blockers.append("The latest ingestion brief is red.")
    if not inventory_exists:
        blockers.append("The maintained source inventory is unavailable.")
    if not audit_exists:
        blockers.append("The MP/member source audit report is missing.")

    completed = []
    for available, label in (
        (bool(dashboard), "Data coverage dashboard"),
        (bool(iec), "IEC coverage quality report"),
        (bool(mp), "MP coverage scoreboard"),
        (bool(brief), "Scheduled ingestion brief"),
        (inventory_exists, "Maintained source inventory"),
        (audit_exists, "MP/member source audit"),
    ):
        if available:
            completed.append(label)
    if pa_blocked:
        completed.append(
            "People's Assembly source-access block is visible but operationally isolated by PMG fallback."
        )

    remaining = []
    if not expected_universe:
        remaining.append("Establish and reconcile an authoritative expected MP universe.")
    if people_status != "green":
        remaining.append("Resolve MP/person evidence and reconciliation blockers.")
    if parliamentary_status != "green":
        remaining.append("Bring parliamentary activity coverage and evidence gates to green.")
    if not iec_complete:
        remaining.append("Complete the reviewed IEC work tracked in issue #24.")
    if ingestion_status != "green":
        remaining.append("Return scheduled ingestion health to green.")
    if pa_status != "green" and not pa_blocked:
        remaining.append("Resolve or operationally isolate the PA source-access blocker in issue #47.")
    if source_inventory_status != "green":
        remaining.append("Refresh source inventory and source-audit evidence.")

    recommendations = []
    if not expected_universe:
        recommendations.append("Next PR: authoritative MP universe storage and reconciliation contract.")
    if pa_status != "green" and not pa_blocked:
        recommendations.append("Next PR: PA-independent official Parliament baseline parser validation.")
    if not iec_complete:
        recommendations.append("Next PR: controlled reviewed IEC file ingestion and reconciliation evidence.")
    if ingestion_status != "green":
        recommendations.append("Next PR: address the current ingestion-health blocker without bypassing quality gates.")

    launch_coverage = _launch_coverage(inputs)
    coverage_blockers = [
        f"{row['label']} coverage is {row['coverage_pct']}% ({row['production_count']}/{row['source_total']})."
        for row in launch_coverage
        if row["launch_status"] == "blocker"
    ]
    blockers.extend(coverage_blockers)
    for row in launch_coverage:
        if row["launch_status"] == "blocker":
            recommendations.append(row["next_recommended_action"])
    if coverage_blockers:
        overall = "red"

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "people_coverage_status": people_status,
        "parliamentary_activity_status": parliamentary_status,
        "IEC_status": iec_status,
        "ingestion_health_status": ingestion_status,
        "PA_source_access_status": pa_status,
        "source_inventory_status": source_inventory_status,
        "blockers": list(dict.fromkeys(blockers)),
        "completed_capabilities": completed,
        "remaining_before_v1": list(dict.fromkeys(remaining)),
        "recommended_next_prs": list(dict.fromkeys(recommendations)),
        "launch_coverage": launch_coverage,
        "expected_universe_available": expected_universe,
        "cannot_claim_all_mps": not can_claim_all,
        "full_coverage_claim_supported": overall == "green",
        "integrity_rules": [
            "Green requires explicit evidence that every required V1 gate passed.",
            "Missing reports and unavailable expected universes are never treated as success.",
            "No MPs, parties, roles, office-holders, winners, or source mappings are inferred.",
            "Unknown or missing coverage remains unknown or missing.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# V1 Readiness Report",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Overall status:** {report['overall_status']}",
        f"- **Expected MP universe available:** {str(report['expected_universe_available']).lower()}",
        f"- **Cannot claim all MPs:** {str(report['cannot_claim_all_mps']).lower()}",
        f"- **Full coverage claim supported:** {str(report['full_coverage_claim_supported']).lower()}",
        "",
        "## Domain gates",
        "",
        "| Gate | Status |",
        "|---|---|",
        f"| People coverage | {report['people_coverage_status']} |",
        f"| Parliamentary activity | {report['parliamentary_activity_status']} |",
        f"| IEC | {report['IEC_status']} |",
        f"| Ingestion health | {report['ingestion_health_status']} |",
        f"| PA source access | {report['PA_source_access_status']} |",
        f"| Source inventory | {report['source_inventory_status']} |",
        "",
        "## Launch coverage",
        "",
        "| Dataset | Production count | Source total | Coverage | Status | Last run evidence | Next action |",
        "|---|---:|---:|---:|---|---|---|",
    ]
    for row in report["launch_coverage"]:
        lines.append(
            f"| {row['label']} | {row['production_count']} | {row['source_total']} | "
            f"{row['coverage_pct']}% | {row['launch_status']} | "
            f"{row['last_ingestion_evidence']} | {row['next_recommended_action']} |"
        )
    for heading, key in (
        ("Blockers", "blockers"),
        ("Completed capabilities", "completed_capabilities"),
        ("Remaining before V1", "remaining_before_v1"),
        ("Recommended next PRs", "recommended_next_prs"),
        ("Integrity rules", "integrity_rules"),
    ):
        lines.extend(["", f"## {heading}", ""])
        lines.extend(f"- {item}" for item in report[key])
        if not report[key]:
            lines.append("- None recorded.")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "v1_readiness_report.json"
    markdown_path = directory / "v1_readiness_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _launch_coverage(inputs: dict) -> list[dict]:
    dashboard = inputs.get("data_coverage") or {}
    summary = dashboard.get("executive_summary") or {}
    inspect_payload = inputs.get("inspect") or {}
    sweep_states = inspect_payload.get("sweep_states") or []
    pmg_summary = inputs.get("pmg_ingestion") or {}
    question_summary = inputs.get("parliamentary_questions_ingestion") or {}

    return [
        _coverage_row(
            "PMG bills",
            int(summary.get("total_bills") or 0),
            _source_total_from_sweep(sweep_states, "pmg_bills", SOURCE_TOTALS["pmg_bills"]),
            _sweep_evidence(sweep_states, "pmg_bills", pmg_summary),
            "Maintain scheduled PMG bill sweeps and monitor for regressions.",
            "Recover PMG bill coverage through the existing sweep before launch.",
        ),
        _coverage_row(
            "PMG committee meetings",
            int(summary.get("total_committee_meetings") or 0),
            _source_total_from_sweep(
                sweep_states,
                "pmg_committee_meetings",
                SOURCE_TOTALS["pmg_committee_meetings"],
            ),
            _sweep_evidence(sweep_states, "pmg_committee_meetings", pmg_summary),
            "Keep monitoring Claude issue #59 until PMG meeting coverage reaches the launch threshold.",
            "Continue Claude issue #59: recover PMG committee meeting coverage to at least 80%.",
        ),
        _coverage_row(
            "Parliament questions",
            int(summary.get("total_parliamentary_questions") or 0),
            SOURCE_TOTALS["parliamentary_questions"],
            _summary_evidence(question_summary),
            "Maintain new-record-first Parliament question ingestion and monitor daily growth.",
            "Run scheduled question ingestion and verify new-record-first backfill increases records.",
        ),
    ]


def _coverage_row(
    label: str,
    production_count: int,
    source_total: int,
    last_evidence: str,
    pass_action: str,
    blocker_action: str,
) -> dict:
    coverage_pct = round(production_count * 100 / source_total, 2) if source_total else None
    launch_status = "pass" if coverage_pct is not None and coverage_pct >= LAUNCH_COVERAGE_TARGET else "blocker"
    return {
        "label": label,
        "production_count": production_count,
        "source_total": source_total,
        "coverage_pct": coverage_pct,
        "launch_status": launch_status,
        "last_ingestion_evidence": last_evidence,
        "next_recommended_action": pass_action if launch_status == "pass" else blocker_action,
    }


def _source_total_from_sweep(sweep_states: list[dict], stream_name: str, fallback: int) -> int:
    for state in sweep_states:
        if state.get("stream_name") == stream_name and state.get("source_total"):
            return int(state["source_total"])
    return fallback


def _sweep_evidence(sweep_states: list[dict], stream_name: str, fallback_summary: dict) -> str:
    for state in sweep_states:
        if state.get("stream_name") != stream_name:
            continue
        return (
            f"{stream_name}: status={state.get('last_status') or 'unknown'}, "
            f"next_page={state.get('next_page')}, seen={state.get('total_seen')}, "
            f"failed={state.get('total_failed')}, completed_at={state.get('last_completed_at')}"
        )
    return _summary_evidence(fallback_summary)


def _summary_evidence(summary: dict) -> str:
    if not summary:
        return "No ingestion summary artifact present."
    return (
        f"status={summary.get('status') or 'unknown'}, "
        f"attempted={summary.get('attempted_count', 0)}, "
        f"processed={summary.get('processed_count', 0)}, "
        f"created={summary.get('created_count', 0)}, "
        f"updated={summary.get('updated_count', 0)}, "
        f"failed={summary.get('failed_count', 0)}"
    )


def main() -> int:
    parser = argparse.ArgumentParser(description="Aggregate V1 readiness reports.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--source-inventory", default="docs/source-inventory.md")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    inputs = load_inputs(Path(args.reports_dir), Path(args.source_inventory))
    report = build_report(inputs)
    json_path, markdown_path = write_report(report, args.reports_dir)
    output = {
        "overall_status": report["overall_status"],
        "json_report": str(json_path),
        "markdown_report": str(markdown_path),
        "cannot_claim_all_mps": report["cannot_claim_all_mps"],
    }
    print(json.dumps(output, sort_keys=True) if args.json_only else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
