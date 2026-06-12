"""Tests for the persistent DB readiness checker, its workflows, and the
no-secrets guarantees."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from check_persistent_db_ready import (
    EXIT_CONFIG_ERROR,
    EXIT_NOT_READY,
    EXIT_READY,
    REQUIRED_TABLES,
    is_postgres_url,
    redact_database_url,
    render_markdown,
    run_readiness,
    write_report_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
READINESS_WF = REPO_ROOT / ".github" / "workflows" / "persistent-db-readiness.yml"
SWEEP_WF = REPO_ROOT / ".github" / "workflows" / "accountability-sweep.yml"

GOOD_URL = "postgresql+psycopg://sweeper:hunter2@db.example.com:5432/knowyourmpza"

ALL_TABLES = set(REQUIRED_TABLES) | {"alembic_version"}


def _probe(tables=ALL_TABLES, current="0010_add_ingestion_sweep_states", head="0010_add_ingestion_sweep_states"):
    def probe(url):
        return {"connected": True, "tables": set(tables), "current_revision": current, "head_revision": head}

    return probe


def _ok_kwargs(**overrides):
    base = dict(
        do_migrations=False,
        check_sweep=False,
        db_probe=_probe(),
        migrate_fn=lambda url: (True, "upgraded"),
        sweep_probe=lambda: (True, "sweep dry-run ok"),
        guard_probe=lambda: (True, "guard intact"),
    )
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Redaction and URL validation
# ---------------------------------------------------------------------------

def test_redaction_strips_credentials():
    redacted = redact_database_url(GOOD_URL)
    assert "hunter2" not in redacted
    assert "sweeper" not in redacted
    assert "db.example.com" in redacted


def test_redaction_strips_query_string():
    redacted = redact_database_url(GOOD_URL + "?password=oops&sslmode=require")
    assert "oops" not in redacted


def test_redaction_handles_missing_url():
    assert redact_database_url(None) == "(not set)"


def test_is_postgres_url():
    assert is_postgres_url(GOOD_URL)
    assert is_postgres_url("postgresql://u@h/db")
    assert not is_postgres_url("mysql://u@h/db")
    assert not is_postgres_url("sqlite:///x.db")


# ---------------------------------------------------------------------------
# Readiness logic
# ---------------------------------------------------------------------------

def test_refuses_missing_database_url():
    report = run_readiness(None, **_ok_kwargs())
    assert report["ready"] is False
    assert report["exit_code"] == EXIT_CONFIG_ERROR
    assert report["checks"][0]["name"] == "url_present"
    assert report["checks"][0]["status"] == "fail"


def test_rejects_non_postgres_url():
    report = run_readiness("mysql://u:p@h/db", **_ok_kwargs())
    assert report["exit_code"] == EXIT_CONFIG_ERROR
    names = {c["name"]: c["status"] for c in report["checks"]}
    assert names["url_is_postgres"] == "fail"


def test_ready_with_fake_db():
    report = run_readiness(GOOD_URL, **_ok_kwargs())
    assert report["ready"] is True
    assert report["exit_code"] == EXIT_READY


def test_connection_failure_reported():
    def broken(url):
        raise ConnectionError("could not translate host name")

    report = run_readiness(GOOD_URL, **_ok_kwargs(db_probe=broken))
    assert report["exit_code"] == EXIT_NOT_READY
    connect = next(c for c in report["checks"] if c["name"] == "connect")
    assert connect["status"] == "fail"
    assert "could not translate" in connect["detail"]


def test_missing_tables_reported():
    tables = ALL_TABLES - {"ingestion_sweep_states", "vote_records"}
    report = run_readiness(GOOD_URL, **_ok_kwargs(db_probe=_probe(tables=tables)))
    assert report["ready"] is False
    required = next(c for c in report["checks"] if c["name"] == "required_tables")
    assert "ingestion_sweep_states" in required["detail"]
    assert "vote_records" in required["detail"]
    sweep_table = next(c for c in report["checks"] if c["name"] == "sweep_state_table")
    assert sweep_table["status"] == "fail"


def test_migration_state_reported_behind():
    report = run_readiness(GOOD_URL, **_ok_kwargs(db_probe=_probe(current="0009_add_accountability_layer")))
    current = next(c for c in report["checks"] if c["name"] == "migrations_current")
    assert current["status"] == "fail"
    assert "0009" in current["detail"]
    assert report["ready"] is False


def test_run_migrations_applies_and_recovers():
    state = {"current": "0009_add_accountability_layer"}

    def probe(url):
        return {"connected": True, "tables": ALL_TABLES,
                "current_revision": state["current"], "head_revision": "0010_add_ingestion_sweep_states"}

    def migrate(url):
        state["current"] = "0010_add_ingestion_sweep_states"
        return True, "upgraded to head"

    report = run_readiness(GOOD_URL, **_ok_kwargs(do_migrations=True, db_probe=probe, migrate_fn=migrate))
    assert report["ready"] is True
    assert any(c["name"] == "migrations_applied" and c["status"] == "pass" for c in report["checks"])


def test_check_sweep_probes_run():
    report = run_readiness(GOOD_URL, **_ok_kwargs(check_sweep=True))
    names = [c["name"] for c in report["checks"]]
    assert "sweep_dry_run" in names
    assert "real_mode_guard" in names


def test_broken_guard_fails_readiness():
    report = run_readiness(
        GOOD_URL, **_ok_kwargs(check_sweep=True, guard_probe=lambda: (False, "GUARD BROKEN"))
    )
    assert report["ready"] is False


def test_report_never_contains_credentials():
    report = run_readiness(GOOD_URL, **_ok_kwargs(check_sweep=True))
    blob = json.dumps(report)
    assert "hunter2" not in blob
    assert "sweeper:" not in blob
    md = render_markdown(report)
    assert "hunter2" not in md


def test_json_output_parseable_and_files_written(tmp_path):
    report = run_readiness(GOOD_URL, **_ok_kwargs())
    json_path, md_path = write_report_files(report, tmp_path)
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["ready"] is True
    assert md_path.read_text(encoding="utf-8").startswith("# Persistent DB Readiness")


def test_markdown_lists_every_check():
    report = run_readiness(GOOD_URL, **_ok_kwargs(check_sweep=True))
    md = render_markdown(report)
    for check in report["checks"]:
        assert check["name"] in md


# ---------------------------------------------------------------------------
# Workflows
# ---------------------------------------------------------------------------

def test_readiness_workflow_exists():
    assert READINESS_WF.exists()


def test_readiness_workflow_manual_dispatch_only():
    text = READINESS_WF.read_text(encoding="utf-8")
    assert "workflow_dispatch" in text
    assert "schedule:" not in text  # on-demand only
    for inp in ("strict", "run_migrations", "check_sweep"):
        assert inp in text


def test_readiness_workflow_never_echoes_database_url():
    """No line may print the secret VALUE ($VAR or ${{ secrets }} expansion).
    Mentioning the variable name in documentation text is fine."""
    for line in READINESS_WF.read_text(encoding="utf-8").splitlines():
        if "echo" not in line:
            continue
        for value_ref in ("$DATABASE_URL", "$PERSISTENT_DATABASE_URL", "${{ secrets.DATABASE_URL }}"):
            if value_ref in line and "GITHUB_ENV" not in line:
                raise AssertionError(f"workflow echoes the secret value: {line.strip()}")


def test_readiness_workflow_uploads_artifacts():
    text = READINESS_WF.read_text(encoding="utf-8")
    assert "actions/upload-artifact" in text
    assert "backend/reports/" in text


def test_readiness_workflow_creates_reports_directory_before_stdout_redirect():
    text = READINESS_WF.read_text(encoding="utf-8")
    mkdir = text.find("mkdir -p reports")
    redirect = text.find("> reports/db_readiness_stdout.json")
    assert mkdir != -1, "readiness workflow must create backend/reports"
    assert redirect != -1, "readiness workflow stdout report redirect is missing"
    assert mkdir < redirect, "reports directory must exist before redirecting readiness stdout"


def test_readiness_workflow_handles_missing_secret():
    text = READINESS_WF.read_text(encoding="utf-8")
    assert "NOT enabled" in text
    assert "GITHUB_STEP_SUMMARY" in text


def test_sweep_workflow_creates_reports_directory_before_report_writes():
    text = SWEEP_WF.read_text(encoding="utf-8")
    mkdir = text.find("mkdir -p reports")
    first_report_write = text.find("> reports/inspect_db.json")
    assert mkdir != -1, "sweep workflow must create backend/reports"
    assert first_report_write != -1, "sweep workflow report redirect is missing"
    assert mkdir < first_report_write, "reports directory must exist before sweep report writes"


def test_sweep_workflow_runs_readiness_preflight_before_real_sweeps():
    text = SWEEP_WF.read_text(encoding="utf-8")
    preflight = text.find("python scripts/check_persistent_db_ready.py")
    sweep = text.find("python scripts/run_scheduled_sweep.py")
    assert preflight != -1, "sweep workflow has no readiness preflight"
    assert sweep != -1
    assert preflight < sweep, "readiness preflight must run before the sweep"
    assert "SWEEP_DB_PERSISTENT == 'true'" in text  # real mode only


# ---------------------------------------------------------------------------
# Docs
# ---------------------------------------------------------------------------

def test_docs_state_secrets_are_never_printed():
    docs_dir = REPO_ROOT / "backend" / "docs"
    combined = "\n".join(
        p.read_text(encoding="utf-8") for p in [docs_dir / "scheduled-sweeps.md", docs_dir / "persistent-db-runbook.md"]
    )
    assert "never prints" in combined or "never prints the URL" in combined or "never contains the URL" in combined
    assert "persistent-db-runbook" in (docs_dir / "scheduled-sweeps.md").read_text(encoding="utf-8")


def test_runbook_covers_common_errors():
    runbook = (REPO_ROOT / "backend" / "docs" / "persistent-db-runbook.md").read_text(encoding="utf-8")
    for phrase in ("hostname", "password authentication", "SSL", "missing", "rotat"):
        assert phrase.lower() in runbook.lower()
