#!/usr/bin/env python3
"""Triage the automated red ingestion alert (issue #18).

Reads the latest locally available run artifacts and decides whether a red
ingestion alert is currently justified, appears stale, or cannot be
determined. This makes the standing "Automated ingestion alert: red brief"
issue actionable: a green/yellow latest brief is evidence the alert may be
stale; a red latest brief lists the exact failed stages/errors so the alert
stays grounded in fresh evidence.

Inputs (all optional — absence yields "unknown", never an error):
  reports/ingestion_brief.json            (generate_ingestion_brief.py)
  reports/accountability_sweep_report.json (run_scheduled_sweep.py)
  reports/data_coverage_dashboard.json     (report_data_coverage_dashboard.py)

Outputs (Markdown printed to stdout; files written only with --write-report):
  reports/ingestion_alert_triage.json
  reports/ingestion_alert_triage.md

Secret safety: this script reads already-redacted report JSON and emits no
environment values. As defence in depth it also redacts any DATABASE_URL or
embedded URL credentials found in error text before printing/writing.
"""
import argparse
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Verdicts
CURRENT = "current"   # latest evidence shows a red run — alert is justified
STALE = "stale"       # latest evidence is green/yellow — alert likely resolved
UNKNOWN = "unknown"   # no usable evidence — cannot decide

_DATABASE_URL_RE = re.compile(r"(?i)\bDATABASE_URL\b\s*[:=]\s*[^\s,;]+")
_URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_SECRET_RE = re.compile(
    r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key|access[_-]?key)\b(\s*[:=]\s*)([^\s,;]+)"
)


def redact_text(value: str) -> str:
    value = _DATABASE_URL_RE.sub("DATABASE_URL=[REDACTED]", value)
    value = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)
    return _SECRET_RE.sub(r"\1\2[REDACTED]", value)


def redact(value: Any) -> Any:
    if isinstance(value, str):
        return redact_text(value)
    if isinstance(value, list):
        return [redact(v) for v in value]
    if isinstance(value, dict):
        return {k: redact(v) for k, v in value.items()}
    return value


def _load(path: Path) -> dict | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as exc:
        logger.warning("could not read %s: %s", path.name, type(exc).__name__)
        return None


def triage(reports_dir: Path) -> dict:
    """Decide current/stale/unknown from whichever artifacts exist."""
    brief = _load(reports_dir / "ingestion_brief.json")
    sweep = _load(reports_dir / "accountability_sweep_report.json")
    dashboard = _load(reports_dir / "data_coverage_dashboard.json")

    evidence: list[str] = []
    failed_stages: list[Any] = []
    errors: list[Any] = []
    status: str | None = None
    timestamp: str | None = None

    if brief is not None:
        status = brief.get("status")
        timestamp = brief.get("timestamp")
        errors = brief.get("errors") or []
        evidence.append(f"ingestion_brief.json status={status!r}")
    if sweep is not None:
        stage_summaries = sweep.get("stage_summaries") or []
        failed_stages = [s for s in stage_summaries if (s.get("failed") or 0) > 0]
        if not errors:
            errors = sweep.get("errors") or []
        evidence.append(
            f"accountability_sweep_report.json mode={sweep.get('mode')!r} "
            f"exit_code={sweep.get('exit_code')} failed_stages={len(failed_stages)}"
        )
    if dashboard is not None:
        evidence.append("data_coverage_dashboard.json present")

    if brief is None and sweep is None:
        verdict = UNKNOWN
        reasons = ["No ingestion brief or sweep report found locally — cannot assess the alert."]
    elif status == "red" or failed_stages or (sweep is not None and sweep.get("exit_code") not in (0, None)):
        verdict = CURRENT
        reasons = []
        if status == "red":
            reasons.extend(brief.get("reasons") or ["latest brief classified the run red"])
        if failed_stages:
            reasons.append(f"{len(failed_stages)} sweep stage(s) reported failures")
        if not reasons:
            reasons = ["latest run reported a non-zero exit or stage failures"]
    elif status in ("green", "yellow"):
        verdict = STALE
        reasons = [
            f"latest ingestion brief is {status}, not red",
            "no failed stages in the latest sweep report" if sweep is not None else
            "no sweep failures observed in available evidence",
        ]
    else:
        verdict = UNKNOWN
        reasons = ["available reports did not contain a usable status signal"]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "verdict": verdict,
        "latest_brief_status": status,
        "latest_brief_timestamp": timestamp,
        "reasons": reasons,
        "failed_stages": redact(failed_stages),
        "errors": redact(errors[:10]),
        "error_count": len(errors),
        "evidence": evidence,
        "inputs_present": {
            "ingestion_brief": brief is not None,
            "accountability_sweep_report": sweep is not None,
            "data_coverage_dashboard": dashboard is not None,
        },
    }


def render_markdown(result: dict) -> str:
    icon = {CURRENT: "🔴", STALE: "🟢", UNKNOWN: "⚪"}.get(result["verdict"], "⚪")
    lines = [
        "# Ingestion Alert Triage",
        "",
        f"## Verdict: {icon} {result['verdict'].upper()}",
        "",
        f"- **Generated:** {result['generated_at']}",
        f"- **Latest brief status:** {result.get('latest_brief_status') or 'n/a'}",
        f"- **Latest brief timestamp:** {result.get('latest_brief_timestamp') or 'n/a'}",
        f"- **Error count (latest):** {result['error_count']}",
        "",
        "### Reasons",
        "",
    ]
    lines += [f"- {r}" for r in result["reasons"]] or ["- (none)"]
    lines.append("")
    if result["verdict"] == CURRENT:
        lines += ["### Failed stages / errors (redacted)", ""]
        if result["failed_stages"]:
            for stage in result["failed_stages"]:
                label = stage.get("sweep", {}).get("stream_name") if isinstance(stage, dict) else None
                lines.append(f"- stage `{label or '?'}`: failed={stage.get('failed') if isinstance(stage, dict) else '?'}")
        for err in result["errors"]:
            if isinstance(err, dict):
                lines.append(f"- `{err.get('type', '?')}` {err.get('url', '')}: {str(err.get('error', ''))[:160]}")
            else:
                lines.append(f"- {str(err)[:160]}")
        lines += ["", "### Recommended next steps", "",
                  "- Keep the failed-stream cursors in place (they do not advance on failure) and let the next scheduled run retry.",
                  "- If errors repeat across runs, treat as systemic and open a targeted fix PR.",
                  ""]
    elif result["verdict"] == STALE:
        lines += ["### Recommendation", "",
                  "The latest evidence is not red. The standing alert issue appears stale; "
                  "a maintainer may close it once a subsequent run is also non-red.", ""]
    else:
        lines += ["### Recommendation", "",
                  "No fresh run evidence is available locally. Re-run the scheduled sweep / brief "
                  "and re-triage; the standing alert should not be closed on missing evidence.", ""]
    lines += ["---", "_Triage reads already-redacted reports and prints no secrets._", ""]
    return "\n".join(lines)


def write_report(result: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "ingestion_alert_triage.json"
    md_path = reports_dir / "ingestion_alert_triage.md"
    json_path.write_text(json.dumps(result, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(result), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Triage the red ingestion alert from local reports.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--write-report", action="store_true", help="Write triage JSON + Markdown into reports/.")
    parser.add_argument("--json-output", action="store_true", help="Print JSON instead of Markdown.")
    args = parser.parse_args()

    result = triage(Path(args.reports_dir))
    if args.write_report:
        json_path, md_path = write_report(result, Path(args.reports_dir))
        logger.info("triage written: %s, %s (verdict=%s)", json_path, md_path, result["verdict"])

    if args.json_output:
        print(json.dumps(result, default=str))
    else:
        print(render_markdown(result))
    # Always exit 0 — triage is informational and must never break a workflow.


if __name__ == "__main__":
    main()
