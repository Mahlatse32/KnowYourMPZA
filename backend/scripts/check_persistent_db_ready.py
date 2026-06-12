#!/usr/bin/env python3
"""Persistent database readiness checker for scheduled accountability sweeps.

Answers one question with evidence: "can real scheduled sweeps run against
this database right now?" — without anyone manually inspecting the DB.

Checks (in order):
  url_present            DATABASE_URL is set
  url_is_postgres        URL scheme is PostgreSQL
  connect                a trivial SELECT 1 succeeds
  alembic_revision       current revision is readable
  migrations_current     revision == head (with --run-migrations, upgrades
                         first and re-checks)
  required_tables        core + accountability + sweep tables exist
  sweep_state_table      ingestion_sweep_states exists
  sweep_dry_run          (--check-sweep) the accountability sweep runs in
                         offline dry-run mode against this configuration
  real_mode_guard        run_scheduled_sweep refuses real runs unless
                         SWEEP_DB_PERSISTENT=true (guard intact)

Secrets: the full DATABASE_URL and password are NEVER printed — output shows
only the scheme, host, port, and database name.

Exit codes:
  0  ready
  2  configuration error (missing/invalid DATABASE_URL)
  3  database not ready (connection/migration/table failures)

Examples:
    python scripts/check_persistent_db_ready.py --json-output
    python scripts/check_persistent_db_ready.py --run-migrations --check-sweep --json-output
"""
import argparse
import json
import logging
import os
import re
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

SCRIPTS_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPTS_DIR.parent
REPORTS_DIR = BACKEND_DIR / "reports"

REQUIRED_TABLES = [
    "politicians",
    "parties",
    "committees",
    "bills",
    "bill_events",
    "vote_events",
    "vote_records",
    "committee_meetings",
    "committee_attendance",
    "ingestion_runs",
    "ingestion_sweep_states",
]

EXIT_READY = 0
EXIT_CONFIG_ERROR = 2
EXIT_NOT_READY = 3


def redact_database_url(url: str | None) -> str:
    """Show only scheme://host:port/dbname — never username or password."""
    if not url:
        return "(not set)"
    m = re.match(r"^(?P<scheme>[\w+]+)://(?:[^@/]*@)?(?P<rest>.*)$", url)
    if not m:
        return "(unparseable url, redacted)"
    rest = m.group("rest")
    # strip any query string that could carry credentials
    rest = rest.split("?")[0]
    return f"{m.group('scheme')}://{rest}"


def is_postgres_url(url: str) -> bool:
    return url.split("://")[0].split("+")[0] in ("postgresql", "postgres")


def default_db_probe(database_url: str) -> dict:
    """Connect and report revision + tables. Raises on connection failure."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory
    from sqlalchemy import create_engine, inspect, text

    engine = create_engine(database_url, pool_pre_ping=True)
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))
        inspector = inspect(engine)
        tables = set(inspector.get_table_names())
        current_rev = None
        if "alembic_version" in tables:
            current_rev = conn.execute(text("SELECT version_num FROM alembic_version")).scalar()
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    head_rev = ScriptDirectory.from_config(cfg).get_current_head()
    engine.dispose()
    return {"connected": True, "tables": tables, "current_revision": current_rev, "head_revision": head_rev}


def run_migrations(database_url: str) -> tuple[bool, str]:
    env = {**os.environ, "DATABASE_URL": database_url}
    result = subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(BACKEND_DIR), env=env, capture_output=True, text=True,
    )
    detail = (result.stdout + result.stderr).strip().splitlines()
    return result.returncode == 0, (detail[-1] if detail else "")[:300]


def sweep_dry_run_probe() -> tuple[bool, str]:
    """Verify the accountability sweep executes in offline dry-run mode."""
    result = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "run_full_ingestion.py"),
         "--accountability-sweep", "--dry-run", "--pages-per-run", "1", "--sleep", "0"],
        cwd=str(BACKEND_DIR), capture_output=True, text=True,
    )
    ok = result.returncode == 0 and "ACCOUNTABILITY SWEEP SUMMARY" in result.stdout
    return ok, "sweep dry-run exited %d" % result.returncode


def real_mode_guard_probe() -> tuple[bool, str]:
    """Verify the persistence guard is intact: a real run with the persistence
    marker absent must be refused."""
    if str(SCRIPTS_DIR) not in sys.path:
        sys.path.insert(0, str(SCRIPTS_DIR))
    from run_scheduled_sweep import SweepConfigError, validate_sweep_config

    try:
        validate_sweep_config(
            pages_per_run=3, dry_run=False,
            database_url="postgresql://example/db", db_persistent=False,
        )
    except SweepConfigError:
        return True, "real sweeps correctly require SWEEP_DB_PERSISTENT=true"
    return False, "GUARD BROKEN: real sweep was allowed without persistence marker"


def run_readiness(
    database_url: str | None,
    *,
    do_migrations: bool = False,
    check_sweep: bool = False,
    db_probe=default_db_probe,
    migrate_fn=run_migrations,
    sweep_probe=sweep_dry_run_probe,
    guard_probe=real_mode_guard_probe,
) -> dict:
    """Run all checks. Pure-ish: dependencies injectable for tests."""
    checks: list[dict] = []

    def record(name: str, ok: bool, detail: str) -> bool:
        checks.append({"name": name, "status": "pass" if ok else "fail", "detail": detail})
        return ok

    report = {
        "timestamp": datetime.now(UTC).isoformat(),
        "database": redact_database_url(database_url),
        "checks": checks,
        "ready": False,
        "exit_code": EXIT_NOT_READY,
    }

    if not record("url_present", bool(database_url), "DATABASE_URL is set" if database_url else "DATABASE_URL is not set — configure the GitHub secret or environment variable."):
        report["exit_code"] = EXIT_CONFIG_ERROR
        return report
    if not record("url_is_postgres", is_postgres_url(database_url), f"scheme ok for {redact_database_url(database_url)}" if is_postgres_url(database_url) else "DATABASE_URL must be a PostgreSQL URL (postgresql+psycopg://...)."):
        report["exit_code"] = EXIT_CONFIG_ERROR
        return report

    try:
        probe = db_probe(database_url)
    except Exception as exc:
        record("connect", False, f"connection failed: {type(exc).__name__}: {str(exc)[:200]}")
        return report
    record("connect", True, "SELECT 1 succeeded")

    current, head = probe.get("current_revision"), probe.get("head_revision")
    record("alembic_revision", current is not None, f"current={current or 'none'} head={head}")

    if current != head and do_migrations:
        ok, detail = migrate_fn(database_url)
        record("migrations_applied", ok, detail)
        if ok:
            try:
                probe = db_probe(database_url)
                current = probe.get("current_revision")
            except Exception as exc:
                record("connect_after_migrate", False, str(exc)[:200])
                return report
    record(
        "migrations_current",
        current == head,
        f"revision {current} == head" if current == head
        else f"revision {current or 'none'} != head {head} — run with --run-migrations or `alembic upgrade head`.",
    )

    tables = probe.get("tables", set())
    missing = [t for t in REQUIRED_TABLES if t not in tables]
    record("required_tables", not missing, "all required tables present" if not missing else f"missing tables: {', '.join(missing)}")
    record("sweep_state_table", "ingestion_sweep_states" in tables,
           "ingestion_sweep_states present" if "ingestion_sweep_states" in tables
           else "ingestion_sweep_states missing — sweep cursors cannot persist.")

    if check_sweep:
        ok, detail = sweep_probe()
        record("sweep_dry_run", ok, detail)
        ok, detail = guard_probe()
        record("real_mode_guard", ok, detail)

    report["ready"] = all(c["status"] == "pass" for c in checks)
    report["exit_code"] = EXIT_READY if report["ready"] else EXIT_NOT_READY
    return report


def render_markdown(report: dict) -> str:
    lines = [
        "# Persistent DB Readiness",
        "",
        f"- **Timestamp:** {report['timestamp']}",
        f"- **Database:** `{report['database']}` (credentials redacted)",
        f"- **Ready for real scheduled sweeps:** {'YES' if report['ready'] else 'NO'}",
        "",
        "| Check | Status | Detail |",
        "|---|---|---|",
    ]
    for c in report["checks"]:
        icon = "✅" if c["status"] == "pass" else "❌"
        lines.append(f"| {c['name']} | {icon} {c['status']} | {c['detail']} |")
    lines.append("")
    if not report["ready"]:
        lines.append("See `backend/docs/persistent-db-runbook.md` for diagnosis and recovery steps.")
        lines.append("")
    return "\n".join(lines)


def write_report_files(report: dict, out_dir: Path = REPORTS_DIR) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    json_path = out_dir / "db_readiness.json"
    md_path = out_dir / "db_readiness.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def main() -> None:
    parser = argparse.ArgumentParser(description="Check whether the persistent DB is ready for real scheduled sweeps.")
    parser.add_argument("--json-output", action="store_true", help="Print the report as JSON.")
    parser.add_argument("--run-migrations", action="store_true", help="Apply alembic upgrade head if behind.")
    parser.add_argument("--check-sweep", action="store_true", help="Also verify sweep dry-run and the real-mode guard.")
    parser.add_argument("--strict", action="store_true", help="(default behavior) non-zero exit when not ready.")
    parser.add_argument("--redact", action="store_true", help="(default behavior) credentials are always redacted.")
    parser.add_argument("--write-report", action="store_true", help="Write JSON+Markdown reports under reports/.")
    args = parser.parse_args()

    report = run_readiness(
        os.environ.get("DATABASE_URL"),
        do_migrations=args.run_migrations,
        check_sweep=args.check_sweep,
    )

    if args.write_report:
        json_path, md_path = write_report_files(report)
        logger.info("readiness report written: %s, %s", json_path, md_path)

    if args.json_output:
        print(json.dumps(report, default=str))
    else:
        print(render_markdown(report))

    sys.exit(report["exit_code"])


if __name__ == "__main__":
    main()
