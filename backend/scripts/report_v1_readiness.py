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
    "mp_coverage": "mp_coverage_report.json",
    "ingestion_brief": "ingestion_brief.json",
    "mp_source_audit": "mp_member_source_audit.json",
    "people_assembly": "people_assembly_ingestion_summary.json",
}


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
        pa_status = "red"
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
    if pa_blocked:
        blockers.append(
            "People's Assembly access is systemically blocked in the latest run; issue #47 remains visible."
        )
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
    if pa_status != "green":
        remaining.append("Resolve or operationally isolate the PA source-access blocker in issue #47.")
    if source_inventory_status != "green":
        remaining.append("Refresh source inventory and source-audit evidence.")

    recommendations = []
    if not expected_universe:
        recommendations.append("Next PR: authoritative MP universe storage and reconciliation contract.")
    if pa_status != "green":
        recommendations.append("Next PR: PA-independent official Parliament baseline parser validation.")
    if not iec_complete:
        recommendations.append("Next PR: controlled reviewed IEC file ingestion and reconciliation evidence.")
    if ingestion_status != "green":
        recommendations.append("Next PR: address the current ingestion-health blocker without bypassing quality gates.")

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
    ]
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
