#!/usr/bin/env python3
"""Automated ingestion brief: "what changed / what matters / what needs attention".

Reads whatever run artifacts exist under the reports directory —

  accountability_sweep_report.json   (run_scheduled_sweep.py)
  inspect_db.json                    (inspect_db.py --json-output)
  full_coverage_report.json          (report_full_coverage.py)
  search_completeness_report.json    (check_search_completeness.py)
  db_readiness.json                  (check_persistent_db_ready.py)

— and produces a deterministic (no AI) brief as Markdown + JSON:

  reports/ingestion_brief.md
  reports/ingestion_brief.json

Status classification:
  green   real run, exit 0, no failed stages/errors, every stream advanced
          (or legitimately reached end of source)
  yellow  dry-run/validation only, no persistent DB, no new records, or a
          partial advance
  red     failed stages, readiness failure, missing tables, errors at/over
          threshold, or a real run where no stream advanced

Missing inputs are handled gracefully — the brief reports what it knows and
flags what it cannot know. Secrets never appear: upstream reports are already
credential-redacted, and this script adds no environment values.
"""
import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

ERROR_THRESHOLD_RED = 3

INTEGRITY_REMINDERS = [
    "No fabricated attendance: rows come only from PMG's explicit attendance endpoint.",
    "No fabricated votes: individual MP votes are never inferred from party positions.",
    "vote_records may legitimately remain 0 unless sources expose explicit counts or named votes.",
]


def load_inputs(reports_dir: Path) -> dict:
    """Load whichever artifacts exist; absent files become None."""
    names = {
        "sweep_report": "accountability_sweep_report.json",
        "inspect": "inspect_db.json",
        "coverage": "full_coverage_report.json",
        "completeness": "search_completeness_report.json",
        "readiness": "db_readiness.json",
        "people_assembly": "people_assembly_ingestion_summary.json",
    }
    inputs: dict = {}
    for key, filename in names.items():
        path = reports_dir / filename
        if path.exists():
            try:
                inputs[key] = json.loads(path.read_text(encoding="utf-8"))
            except (json.JSONDecodeError, OSError) as exc:
                logger.warning("could not read %s: %s", filename, exc)
                inputs[key] = None
        else:
            inputs[key] = None
    return inputs


def _completeness_summary(inputs: dict) -> dict | None:
    """Normalize check_search_completeness output ({"summary": {"pass": N ...}})
    to upper-case PASS/FAIL/WARN/SKIP keys."""
    completeness = inputs.get("completeness")
    if not completeness:
        return None
    summary = completeness.get("summary") or completeness
    out = {key.upper(): summary[key] for key in ("pass", "fail", "warn", "skip") if key in summary}
    if not out:
        out = {key: summary[key] for key in ("PASS", "FAIL", "WARN", "SKIP") if key in summary}
    return out or None


def _stages(inputs: dict) -> list[dict]:
    report = inputs.get("sweep_report") or {}
    return report.get("stage_summaries") or []


def _errors(inputs: dict) -> list[dict]:
    report = inputs.get("sweep_report") or {}
    return report.get("errors") or []


def _delta(inputs: dict) -> dict | None:
    report = inputs.get("sweep_report") or {}
    return report.get("counts_delta")


def _total_new_records(inputs: dict) -> int | None:
    delta = _delta(inputs)
    if delta is None:
        return None
    return sum(v for v in delta.values() if v > 0)


def _advancement(inputs: dict) -> tuple[int, int]:
    """(advanced_or_completed, total) across stages that carry sweep info."""
    advanced = total = 0
    for stage in _stages(inputs):
        sweep = stage.get("sweep") or {}
        if not sweep:
            continue
        total += 1
        if sweep.get("advanced") or sweep.get("last_status") == "completed_end_of_source":
            advanced += 1
    return advanced, total


def _source_access_failure(inputs: dict) -> dict | None:
    """Return the People's Assembly summary when it is a systemic source-access
    failure (every attempted fetch failed before parsing), else None."""
    summary = inputs.get("people_assembly")
    if isinstance(summary, dict) and summary.get("systemic_source_access_failure"):
        return summary
    return None


def classify_run(inputs: dict) -> tuple[str, list[str]]:
    """Deterministic green / yellow / red with reasons."""
    reasons: list[str] = []
    report = inputs.get("sweep_report")
    readiness = inputs.get("readiness")
    completeness = _completeness_summary(inputs) or {}

    red = False
    yellow = False

    source_access = _source_access_failure(inputs)
    if source_access is not None:
        red = True
        reasons.append(
            "People's Assembly source access failed systemically "
            f"({source_access.get('failed_fetch_count', 0)}/"
            f"{source_access.get('attempted_count', 0)} fetches failed before parsing) — "
            "this is a source-side block/unreachability, not fabricated or missing data"
        )

    if readiness is not None and not readiness.get("ready", False):
        red = True
        failing = [c["name"] for c in readiness.get("checks", []) if c.get("status") == "fail"]
        reasons.append(f"persistent DB readiness failed ({', '.join(failing) or 'unknown check'})")
        if any("table" in name for name in failing):
            reasons.append("database is missing required tables")
        if any("migration" in name for name in failing):
            reasons.append("migrations are not at head")

    if report is None:
        yellow = True
        reasons.append("no sweep report found — sweep did not run or artifacts are missing")
    else:
        mode = report.get("mode", "unknown")
        failed_stages = [s for s in _stages(inputs) if s.get("failed", 0) > 0]
        errors = _errors(inputs)
        if report.get("exit_code", 0) != 0:
            red = True
            reasons.append(f"sweep exited non-zero ({report.get('exit_code')})")
        if failed_stages:
            red = True
            reasons.append(f"{len(failed_stages)} stage(s) reported failures")
        if len(errors) >= ERROR_THRESHOLD_RED:
            red = True
            reasons.append(f"{len(errors)} errors (threshold {ERROR_THRESHOLD_RED})")
        elif errors:
            yellow = True
            reasons.append(f"{len(errors)} error(s) recorded below the red threshold")

        if mode != "real":
            yellow = True
            reasons.append(f"run mode was {mode} — no data was written, sweep state did not advance")
        else:
            advanced, total = _advancement(inputs)
            if total and advanced == 0 and not red:
                red = True
                reasons.append("real run but no sweep stream advanced — investigate before rerunning")
            elif total and advanced < total:
                yellow = True
                reasons.append(f"partial advance: {advanced}/{total} streams moved forward")
            new_records = _total_new_records(inputs)
            if new_records == 0 and advanced > 0:
                yellow = True
                reasons.append("sweep advanced but no new records — possible already-seen pages or source gap")

    if completeness.get("FAIL", 0):
        red = True
        reasons.append(f"search completeness has {completeness['FAIL']} FAIL check(s)")

    if red:
        return "red", reasons
    if yellow:
        return "yellow", reasons
    reasons.append("real run, all streams advanced, no failures or errors")
    return "green", reasons


def build_recommendations(inputs: dict, status: str) -> list[str]:
    """Conservative, deterministic next actions."""
    recs: list[str] = []
    report = inputs.get("sweep_report")
    readiness = inputs.get("readiness")
    mode = (report or {}).get("mode", "unknown")
    coverage_pct = (report or {}).get("estimated_meeting_coverage_percent")
    counts = (report or {}).get("counts_after") or {}
    errors = _errors(inputs)

    source_access = _source_access_failure(inputs)
    if source_access is not None and source_access.get("recommendation"):
        recs.append(source_access["recommendation"])

    readiness_says_no_url = readiness is not None and any(
        c["name"] == "url_present" and c["status"] == "fail" for c in readiness.get("checks", [])
    )
    if readiness_says_no_url or (report is None and readiness is None):
        recs.append(
            "Configure the DATABASE_URL GitHub secret for a persistent PostgreSQL, then "
            "dispatch the 'Persistent DB readiness' workflow to validate it."
        )
    if mode.startswith("dry_run"):
        recs.append(
            "This was validation only. To enable real scheduled sweeps, ensure the "
            "DATABASE_URL secret is set and the readiness workflow passes."
        )
    if errors:
        recs.append(
            "Errors occurred: keep the current page cursor (failed streams did not advance) "
            "and let the next scheduled run retry the same window."
        )
    if status == "green":
        pages = (report or {}).get("pages_per_run") or 3
        if pages < 6:
            recs.append(
                f"Run is green at pages_per_run={pages}. Keep this batch size; after two "
                f"consecutive green runs, increase to pages_per_run={min(pages * 2, 6)}."
            )
        else:
            recs.append(f"pages_per_run={pages} is at the recommended steady state.")
    if coverage_pct is not None and coverage_pct < 50:
        recs.append(
            f"PMG meeting coverage is {coverage_pct}% — keep the daily scheduled sweeps "
            "running; coverage grows automatically."
        )
    if counts.get("vote_events", 0) > 0 and counts.get("vote_records", 0) == 0:
        recs.append(
            "vote_records is 0 while vote_events exist: the minutes scanned so far expose "
            "outcomes but no explicit aggregate counts or named votes. This is correct "
            "behaviour — records are never fabricated. They will appear when sources "
            "include explicit counts."
        )
    if counts.get("committee_meetings", 0) > 0 and counts.get("committee_attendance", 0) == 0:
        recs.append(
            "No attendance rows despite ingested meetings — check whether the PMG "
            "attendance endpoint is reachable (see persistent-db-runbook.md)."
        )
    if not recs:
        recs.append("No action required. Scheduled sweeps continue automatically.")
    return recs


def build_attention_items(inputs: dict, status: str, reasons: list[str]) -> list[str]:
    if status == "green":
        return []
    items = [r for r in reasons if r]
    readiness = inputs.get("readiness")
    if readiness is not None and not readiness.get("ready", False):
        items.append("Real sweeps are blocked until readiness passes — see db_readiness.md artifact.")
    return items


def _top_new_records(inputs: dict, limit: int = 5) -> list[dict]:
    """Sample rows (with source URLs) from tables that grew this run."""
    delta = _delta(inputs) or {}
    inspect = inputs.get("inspect") or {}
    tables = inspect.get("tables") or {}
    top: list[dict] = []
    for table, change in sorted(delta.items(), key=lambda kv: -kv[1]):
        if change <= 0:
            continue
        for sample in (tables.get(table) or {}).get("samples", [])[:2]:
            top.append(
                {
                    "table": table,
                    "title": sample.get("title") or sample.get("full_name") or sample.get("name"),
                    "source_url": sample.get("source_url"),
                }
            )
            if len(top) >= limit:
                return top
    return top


def _redact(value: str) -> str:
    """Defense-in-depth credential redaction for the brief layer.

    Upstream summaries are already credential-redacted; this re-applies the same
    rules so the brief never surfaces a secret even if an upstream stage forgot
    to. Mirrors scripts/ingestion_batch_utils.redact_sensitive."""
    text = str(value)
    text = re.sub(
        r"(?i)\b(database_url|password|passwd|secret|token|api_key|authorization)\b"
        r"(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@",
        r"\1[REDACTED]:[REDACTED]@",
        text,
    )
    text = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
        "[REDACTED]",
        text,
    )
    return text


def _redact_error(error: dict) -> dict:
    if not isinstance(error, dict):
        return error
    return {key: (_redact(value) if isinstance(value, str) else value) for key, value in error.items()}


def _source_access_section(inputs: dict) -> dict | None:
    """Safe, aggregated People's Assembly fetch health for the brief. Returns
    None when no PA summary is present. Carries no response bodies or secrets —
    the underlying summary is already credential-redacted, and the sample errors
    are re-redacted here as defense-in-depth."""
    summary = inputs.get("people_assembly")
    if not isinstance(summary, dict):
        return None
    sample_errors = [_redact_error(error) for error in (summary.get("sample_safe_errors") or [])]
    return {
        "source": summary.get("source", "people_assembly"),
        "status": summary.get("status"),
        "attempted_count": summary.get("attempted_count"),
        "failed_fetch_count": summary.get("failed_fetch_count"),
        "systemic_source_access_failure": bool(summary.get("systemic_source_access_failure")),
        "top_error_types": summary.get("top_error_types") or {},
        "sample_safe_errors": sample_errors,
        "recommendation": summary.get("recommendation") or "",
    }


def build_brief(inputs: dict) -> dict:
    status, reasons = classify_run(inputs)
    report = inputs.get("sweep_report") or {}
    readiness = inputs.get("readiness")
    coverage = inputs.get("coverage") or {}
    sweep_section = coverage.get("accountability_sweep") or {}

    return {
        "timestamp": datetime.now(UTC).isoformat(),
        "status": status,
        "reasons": reasons,
        "mode": report.get("mode"),
        "pages_per_run": report.get("pages_per_run"),
        "db_readiness": (
            {"ready": readiness.get("ready"), "database": readiness.get("database")}
            if readiness is not None
            else None
        ),
        "counts_before": report.get("counts_before"),
        "counts_after": report.get("counts_after"),
        "counts_delta": report.get("counts_delta"),
        "sweep_states": report.get("sweep_states") or [],
        "coverage": {
            "estimated_meeting_coverage_percent": report.get("estimated_meeting_coverage_percent")
            or sweep_section.get("estimated_meeting_coverage_percent"),
            "source_totals": report.get("source_totals") or {},
        },
        "top_new_records": _top_new_records(inputs),
        "source_access": _source_access_section(inputs),
        "errors": _errors(inputs),
        "completeness": _completeness_summary(inputs),
        "attention_required": build_attention_items(inputs, status, reasons),
        "next_actions": build_recommendations(inputs, status),
        "next_recommended_pages_per_run": report.get("next_recommended_batch"),
        "integrity_reminders": INTEGRITY_REMINDERS,
        "inputs_present": {k: v is not None for k, v in inputs.items()},
    }


STATUS_ICON = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


def render_markdown(brief: dict) -> str:
    lines = [
        "# Ingestion Brief",
        "",
        f"## Status: {STATUS_ICON.get(brief['status'], '')} {brief['status'].upper()}",
        "",
        f"- **Timestamp:** {brief['timestamp']}",
        f"- **Mode:** {brief.get('mode') or 'unknown'}",
        f"- **Pages per run:** {brief.get('pages_per_run') or '—'}",
    ]
    if brief.get("db_readiness"):
        ready = brief["db_readiness"]["ready"]
        lines.append(f"- **Persistent DB ready:** {'yes' if ready else 'NO'} ({brief['db_readiness']['database']})")
    lines += ["", "### Why", ""]
    for reason in brief["reasons"]:
        lines.append(f"- {reason}")
    lines.append("")

    if brief.get("counts_after"):
        lines += ["## What changed", "", "| Table | Before | After | Δ |", "|---|---|---|---|"]
        before = brief.get("counts_before") or {}
        delta = brief.get("counts_delta") or {}
        for table, after in brief["counts_after"].items():
            lines.append(f"| {table} | {before.get(table, '—')} | {after} | {delta.get(table, '—')} |")
        lines.append("")

    if brief.get("top_new_records"):
        lines += ["### Top new records", ""]
        for rec in brief["top_new_records"]:
            lines.append(f"- **{rec['table']}**: {rec.get('title') or '(untitled)'} — {rec.get('source_url') or 'no url'}")
        lines.append("")

    if brief.get("sweep_states"):
        lines += ["## Sweep progress", "", "| Stream | Next page | Status | Created | Failed |", "|---|---|---|---|---|"]
        for s in brief["sweep_states"]:
            lines.append(
                f"| {s['stream_name']} | {s['next_page']} | {s['last_status']} | {s['total_created']} | {s['total_failed']} |"
            )
        lines.append("")
    cov = brief.get("coverage") or {}
    if cov.get("estimated_meeting_coverage_percent") is not None:
        lines.append(f"**Estimated PMG meeting coverage:** {cov['estimated_meeting_coverage_percent']}%")
        lines.append("")

    if brief.get("errors"):
        lines += ["## Failures / errors", ""]
        for e in brief["errors"][:10]:
            lines.append(f"- `{e.get('type', '?')}` {e.get('url', '')}: {str(e.get('error', ''))[:160]}")
        lines.append("")

    sa = brief.get("source_access")
    if sa:
        lines += ["## Source access", ""]
        flag = "🔴 SYSTEMIC SOURCE-ACCESS FAILURE" if sa.get("systemic_source_access_failure") else (sa.get("status") or "unknown")
        lines.append(f"- **People's Assembly fetch status:** {flag}")
        lines.append(f"- **Failed fetches:** {sa.get('failed_fetch_count', 0)} / {sa.get('attempted_count', '—')}")
        if sa.get("top_error_types"):
            types = ", ".join(f"{name}×{count}" for name, count in sorted(sa["top_error_types"].items()))
            lines.append(f"- **Error types:** {types}")
        for err in sa.get("sample_safe_errors", [])[:3]:
            lines.append(f"  - `{err.get('type', '?')}` {err.get('url', '')}: {str(err.get('error', ''))[:160]}")
        if sa.get("recommendation"):
            lines.append(f"- **Recommendation:** {sa['recommendation']}")
        lines.append("")
    if brief.get("completeness"):
        c = brief["completeness"]
        lines.append(
            f"**Search completeness:** PASS={c.get('PASS', '—')} FAIL={c.get('FAIL', '—')} "
            f"WARN={c.get('WARN', '—')} SKIP={c.get('SKIP', '—')}"
        )
        lines.append("")

    lines += ["## Attention required", ""]
    if brief["attention_required"]:
        for item in brief["attention_required"]:
            lines.append(f"- ⚠️ {item}")
    else:
        lines.append("Nothing — this run needs no human action.")
    lines.append("")

    lines += ["## Next recommended actions", ""]
    for action in brief["next_actions"]:
        lines.append(f"- {action}")
    lines.append("")
    if brief.get("next_recommended_pages_per_run"):
        lines += [f"**Batch size:** {brief['next_recommended_pages_per_run']}", ""]

    lines += ["## Data integrity", ""]
    for reminder in brief["integrity_reminders"]:
        lines.append(f"- {reminder}")
    lines.append("")
    return "\n".join(lines)


def write_brief_files(brief: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "ingestion_brief.json"
    md_path = out_dir / "ingestion_brief.md"
    json_path.write_text(json.dumps(brief, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(brief), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate the post-sweep ingestion brief.")
    parser.add_argument("--reports-dir", default="reports", help="Directory holding run artifacts (and output).")
    parser.add_argument("--json-output", action="store_true", help="Print the JSON brief to stdout.")
    args = parser.parse_args()

    reports_dir = Path(args.reports_dir)
    inputs = load_inputs(reports_dir)
    brief = build_brief(inputs)
    json_path, md_path = write_brief_files(brief, reports_dir)
    logger.info("brief written: %s, %s (status=%s)", json_path, md_path, brief["status"])

    if args.json_output:
        print(json.dumps(brief, default=str))
    else:
        print(render_markdown(brief))


if __name__ == "__main__":
    main()
