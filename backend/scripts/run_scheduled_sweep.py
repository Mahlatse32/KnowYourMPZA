#!/usr/bin/env python3
"""Scheduled accountability sweep runner with safety guards and run reports.

Wraps `run_full_ingestion.py --accountability-sweep` for automated
(GitHub Actions / cron) execution:

  1. Validates configuration BEFORE touching anything:
     - pages_per_run must be set, >= 1, and <= the cap (default 10) unless
       --allow-large-batch is passed
     - real (non-dry) runs require DATABASE_URL to be set
     - real runs require the database to be marked persistent
       (SWEEP_DB_PERSISTENT=true env, set by the workflow when the
       DATABASE_URL secret exists, or --assume-persistent-db for hosts
       that own their database) — otherwise sweep state would be lost
       with each ephemeral database and the sweep would re-ingest page 0
       forever.
  2. Snapshots accountability table counts before and after.
  3. Runs the bounded sweep.
  4. Writes machine-readable JSON + human-readable Markdown reports under
     reports/ (gitignored; uploaded as CI artifacts, never committed).

Secrets are never printed: DATABASE_URL is read but only its presence is
reported.

Examples:
    python scripts/run_scheduled_sweep.py --pages-per-run 3 --dry-run
    SWEEP_DB_PERSISTENT=true python scripts/run_scheduled_sweep.py --pages-per-run 3
"""
import argparse
import json
import logging
import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent
REPORTS_DIR = SCRIPTS_DIR.parent / "reports"
DEFAULT_PAGES_CAP = 10

ACCOUNTABILITY_TABLES = [
    "bills",
    "bill_events",
    "vote_events",
    "vote_records",
    "committee_meetings",
    "committee_attendance",
]

# Sweep stream -> the run_full_ingestion.py flag that skips it. A --streams
# allowlist runs ONLY the named streams by skipping every other one, so all
# streams keep sharing the same cursor rows and sweep guards.
STREAM_SKIP_FLAGS = {
    "pmg_bills": "--skip-bill-sweep",
    "pmg_bill_lifecycle_backfill": "--skip-bill-lifecycle-sweep",
    "pmg_committee_meetings": "--skip-committee-meeting-sweep",
    "pmg_votes_from_meetings": "--skip-vote-sweep",
}


class SweepConfigError(Exception):
    """Raised when a scheduled sweep is misconfigured. The message is safe to
    print (never contains secrets)."""


def parse_streams(raw: str | None) -> list[str] | None:
    """Parse a comma-separated stream allowlist; None/empty means all streams."""
    if not raw:
        return None
    streams = [s.strip() for s in raw.split(",") if s.strip()]
    return streams or None


def stream_selection_args(streams: list[str] | None) -> list[str]:
    """Map a stream allowlist to run_full_ingestion.py --skip-* flags."""
    if not streams:
        return []
    unknown = sorted(set(streams) - set(STREAM_SKIP_FLAGS))
    if unknown:
        raise SweepConfigError(
            f"Unknown sweep stream(s): {', '.join(unknown)}. "
            f"Known streams: {', '.join(STREAM_SKIP_FLAGS)}."
        )
    return [flag for stream, flag in STREAM_SKIP_FLAGS.items() if stream not in streams]


def validate_sweep_config(
    *,
    pages_per_run: int | None,
    dry_run: bool,
    database_url: str | None,
    db_persistent: bool,
    allow_large_batch: bool = False,
    pages_cap: int = DEFAULT_PAGES_CAP,
) -> None:
    """All guards for automated runs. Raises SweepConfigError with a clear,
    secret-free message."""
    if pages_per_run is None:
        raise SweepConfigError(
            "pages_per_run is required — scheduled sweeps must always be bounded. "
            "Pass --pages-per-run N (recommended: 3)."
        )
    if pages_per_run < 1:
        raise SweepConfigError(f"pages_per_run must be >= 1, got {pages_per_run}.")
    if pages_per_run > pages_cap and not allow_large_batch:
        raise SweepConfigError(
            f"pages_per_run={pages_per_run} exceeds the safety cap of {pages_cap}. "
            "Scale gradually (3 -> 6) and pass --allow-large-batch only if you are "
            "sure the source can handle the request volume."
        )
    if dry_run:
        return  # dry runs are offline/bounded and need no database guarantees
    if not database_url:
        raise SweepConfigError(
            "Real sweep refused: DATABASE_URL is not set. Configure the "
            "DATABASE_URL GitHub secret (or environment variable) for a "
            "persistent database, or run with --dry-run for validation."
        )
    if not db_persistent:
        raise SweepConfigError(
            "Real sweep refused: the database is not marked persistent. An "
            "ephemeral database loses sweep state between runs, so the sweep "
            "would re-ingest page 0 forever. Set SWEEP_DB_PERSISTENT=true "
            "(the workflow does this when the DATABASE_URL secret exists) or "
            "pass --assume-persistent-db if this host owns its database."
        )


def snapshot_counts() -> dict | None:
    """Read accountability table counts. Returns None when DB is unreachable."""
    try:
        from sqlalchemy import func, select

        from app import models
        from app.db import SessionLocal

        model_by_table = {m.__tablename__: m for m in [
            models.Bill, models.BillEvent, models.VoteEvent,
            models.VoteRecord, models.CommitteeMeeting, models.CommitteeAttendance,
        ]}
        with SessionLocal() as db:
            return {
                table: db.scalar(select(func.count()).select_from(model)) or 0
                for table, model in model_by_table.items()
            }
    except Exception as exc:
        logger.warning("count snapshot unavailable (%s)", type(exc).__name__)
        return None


def snapshot_sweep_states() -> list[dict]:
    try:
        from app.db import SessionLocal
        from app.services.sweep_service import list_sweep_states, sweep_state_as_dict

        with SessionLocal() as db:
            return [sweep_state_as_dict(s) for s in list_sweep_states(db)]
    except Exception as exc:
        logger.warning("sweep states unavailable (%s)", type(exc).__name__)
        return []


def parse_stage_summaries(stdout: str) -> list[dict]:
    """Each sweep stage prints a one-line JSON summary; collect them."""
    summaries = []
    for line in stdout.splitlines():
        line = line.strip()
        if line.startswith("{") and line.endswith("}"):
            try:
                blob = json.loads(line)
            except json.JSONDecodeError:
                continue
            if "sweep" in blob or "pages_attempted" in blob:
                summaries.append(blob)
    return summaries


def recommend_next_batch(stage_summaries: list[dict], pages_per_run: int) -> str:
    failed = sum(s.get("failed", 0) for s in stage_summaries)
    if failed:
        return f"Stay at pages_per_run={pages_per_run}: last run had {failed} failure(s)."
    if pages_per_run < 6:
        return (
            f"pages_per_run={pages_per_run} is healthy. After two consecutive clean "
            f"runs, scale to pages_per_run={min(pages_per_run * 2, 6)}."
        )
    return f"pages_per_run={pages_per_run} is at the recommended steady state."


def build_report(
    *,
    timestamp: str,
    command: list[str],
    mode: str,
    pages_per_run: int,
    counts_before: dict | None,
    counts_after: dict | None,
    stage_summaries: list[dict],
    sweep_states: list[dict],
    exit_code: int,
) -> dict:
    errors = [e for s in stage_summaries for e in s.get("errors", [])]
    meetings_state = next((s for s in sweep_states if s["stream_name"] == "pmg_committee_meetings"), None)
    coverage = None
    if meetings_state and meetings_state.get("source_total") and counts_after:
        coverage = round(counts_after.get("committee_meetings", 0) / meetings_state["source_total"] * 100, 2)
    return {
        "timestamp": timestamp,
        "command": " ".join(command),
        "mode": mode,
        "pages_per_run": pages_per_run,
        "exit_code": exit_code,
        "counts_before": counts_before,
        "counts_after": counts_after,
        "counts_delta": (
            {k: counts_after[k] - counts_before.get(k, 0) for k in counts_after}
            if counts_before is not None and counts_after is not None
            else None
        ),
        "stage_summaries": stage_summaries,
        "sweep_states": sweep_states,
        "errors": errors,
        "warnings": [],
        "source_totals": {
            s["stream_name"]: s.get("source_total") for s in sweep_states if s.get("source_total")
        },
        "estimated_meeting_coverage_percent": coverage,
        "next_recommended_batch": recommend_next_batch(stage_summaries, pages_per_run),
    }


def write_report_files(report: dict, out_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    """Write JSON + Markdown run reports. Paths are gitignored."""
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "accountability_sweep_report.json"
    md_path = out_dir / "accountability_sweep_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def render_markdown(report: dict) -> str:
    lines = [
        "# Accountability Sweep Report",
        "",
        f"- **Timestamp:** {report['timestamp']}",
        f"- **Mode:** {report['mode']}",
        f"- **Pages per run:** {report['pages_per_run']}",
        f"- **Exit code:** {report['exit_code']}",
        f"- **Command:** `{report['command']}`",
        "",
    ]
    if report.get("counts_after") is not None:
        lines += ["## Accountability counts", "", "| Table | Before | After | Δ |", "|---|---|---|---|"]
        before = report.get("counts_before") or {}
        delta = report.get("counts_delta") or {}
        for table, after in report["counts_after"].items():
            lines.append(f"| {table} | {before.get(table, '—')} | {after} | {delta.get(table, '—')} |")
        lines.append("")
    if report.get("sweep_states"):
        lines += ["## Sweep states", "", "| Stream | Next page | Status | Created | Updated | Failed | Source total |", "|---|---|---|---|---|---|---|"]
        for s in report["sweep_states"]:
            lines.append(
                f"| {s['stream_name']} | {s['next_page']} | {s['last_status']} | "
                f"{s['total_created']} | {s['total_updated']} | {s['total_failed']} | {s.get('source_total') or '—'} |"
            )
        lines.append("")
    if report.get("estimated_meeting_coverage_percent") is not None:
        lines.append(f"**Estimated PMG meeting coverage:** {report['estimated_meeting_coverage_percent']}%")
        lines.append("")
    if report.get("errors"):
        lines += ["## Errors", ""]
        for e in report["errors"][:10]:
            lines.append(f"- `{e.get('type', '?')}` {e.get('url', '')}: {str(e.get('error', ''))[:200]}")
        lines.append("")
    lines += ["## Next batch recommendation", "", report["next_recommended_batch"], ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Guarded scheduled accountability sweep with run reports.")
    parser.add_argument("--pages-per-run", type=int, default=None, help="Bounded page window per stream (required).")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--dry-run", action="store_true", help="Validation mode: offline, no writes, no sweep advancement.")
    parser.add_argument("--discover", action="store_true", help="With --dry-run: bounded live fetches, still no writes.")
    parser.add_argument("--allow-large-batch", action="store_true", help=f"Override the pages_per_run cap of {DEFAULT_PAGES_CAP}.")
    parser.add_argument("--assume-persistent-db", action="store_true",
                        help="Assert that DATABASE_URL points at a persistent database (for hosts that own their DB).")
    parser.add_argument("--streams", default=None,
                        help="Comma-separated allowlist of sweep streams to run "
                             f"(default: all). Known: {', '.join(STREAM_SKIP_FLAGS)}.")
    parser.add_argument("--reports-dir", default=str(REPORTS_DIR))
    args = parser.parse_args()

    database_url = os.environ.get("DATABASE_URL")
    db_persistent = args.assume_persistent_db or os.environ.get("SWEEP_DB_PERSISTENT", "").lower() == "true"

    try:
        validate_sweep_config(
            pages_per_run=args.pages_per_run,
            dry_run=args.dry_run,
            database_url=database_url,
            db_persistent=db_persistent,
            allow_large_batch=args.allow_large_batch,
        )
        streams = parse_streams(args.streams)
        stream_args = stream_selection_args(streams)
    except SweepConfigError as exc:
        logger.error("REFUSED: %s", exc)
        sys.exit(2)

    mode = "dry_run_discover" if (args.dry_run and args.discover) else ("dry_run" if args.dry_run else "real")
    logger.info("mode=%s pages_per_run=%d streams=%s database_url_present=%s db_persistent=%s",
                mode, args.pages_per_run, ",".join(streams) if streams else "all",
                bool(database_url), db_persistent)

    counts_before = snapshot_counts() if not args.dry_run else snapshot_counts()
    command = [
        sys.executable, str(SCRIPTS_DIR / "run_full_ingestion.py"),
        "--accountability-sweep",
        "--pages-per-run", str(args.pages_per_run),
        "--sleep", str(args.sleep),
    ]
    command += stream_args
    if args.dry_run:
        command.append("--dry-run")
    if args.discover:
        command.append("--discover")

    result = subprocess.run(command, capture_output=True, text=True)
    sys.stdout.write(result.stdout)
    sys.stderr.write(result.stderr)

    report = build_report(
        timestamp=datetime.now(UTC).isoformat(),
        command=[Path(c).name if c == command[0] else c for c in command],
        mode=mode,
        pages_per_run=args.pages_per_run,
        counts_before=counts_before,
        counts_after=snapshot_counts(),
        stage_summaries=parse_stage_summaries(result.stdout),
        sweep_states=snapshot_sweep_states(),
        exit_code=result.returncode,
    )
    json_path, md_path = write_report_files(report, Path(args.reports_dir))
    logger.info("report written: %s, %s", json_path, md_path)
    sys.exit(result.returncode)


if __name__ == "__main__":
    main()
