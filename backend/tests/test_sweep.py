"""Tests for the incremental accountability sweep state, service, and script
integration: advancement rules, bounds, end-of-source wraparound, and
orchestration ordering."""
import argparse
import json
import sys
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect as sa_inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import app.db as app_db
from app.db import Base
from app.models.bill import Bill
from app.models.bill_event import BillEvent
from app.models.ingestion_sweep_state import IngestionSweepState
from app.services.accountability_service import upsert_bill
from app.services.sweep_service import (
    complete_sweep_run,
    fail_sweep_run,
    get_or_create_sweep_state,
    list_sweep_states,
    plan_sweep_run,
    reset_sweep_state,
    start_sweep_run,
    sweep_state_as_dict,
)

import run_full_ingestion as rfi
from backfill_legislative_history import run_backfill
from ingest_bills import execute_with_optional_sweep, run_bills_ingest


@pytest.fixture()
def engine():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    yield engine
    Base.metadata.drop_all(engine)


@pytest.fixture()
def db(engine):
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def patched_sessionlocal(engine, monkeypatch):
    """Point app.db.SessionLocal at the test engine for script-level tests."""
    factory = sessionmaker(bind=engine)
    monkeypatch.setattr(app_db, "SessionLocal", factory)
    return factory


# ---------------------------------------------------------------------------
# Model / migration shape
# ---------------------------------------------------------------------------

def test_sweep_state_table_created(engine):
    cols = {c["name"] for c in sa_inspect(engine).get_columns("ingestion_sweep_states")}
    assert {
        "id", "source_name", "stream_name", "cursor_type", "cursor_value",
        "page_number", "batch_size", "max_pages_per_run", "total_seen",
        "total_created", "total_updated", "total_failed", "source_total",
        "sweeps_completed", "last_started_at", "last_completed_at",
        "last_status", "last_error", "created_at", "updated_at",
    } <= cols


# ---------------------------------------------------------------------------
# Sweep service
# ---------------------------------------------------------------------------

def test_get_or_create_is_idempotent(db):
    a = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    b = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    assert a.id == b.id
    assert a.page_number == 0
    assert len(list_sweep_states(db)) == 1


def test_plan_sweep_run_next_window(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    state.page_number = 7
    db.commit()
    plan = plan_sweep_run(state, pages_per_run=3)
    assert plan["start_page"] == 7
    assert plan["pages_per_run"] == 3


def test_plan_sweep_rejects_unbounded(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    with pytest.raises(ValueError):
        plan_sweep_run(state, pages_per_run=0)


def test_successful_run_advances_page(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    start_sweep_run(db, state, 3)
    state = complete_sweep_run(db, state, pages_attempted=3, seen=150, created=100, updated=50)
    assert state.page_number == 3
    assert state.last_status == "completed"
    assert state.total_seen == 150
    assert state.total_created == 100
    assert state.total_updated == 50
    assert state.last_completed_at is not None


def test_failed_run_does_not_advance(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    state.page_number = 5
    db.commit()
    start_sweep_run(db, state, 2)
    state = fail_sweep_run(db, state, "connection refused")
    assert state.page_number == 5
    assert state.last_status == "failed"
    assert state.total_failed == 1
    assert "connection refused" in state.last_error


def test_no_advance_records_run_without_moving_cursor(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    state = complete_sweep_run(db, state, pages_attempted=2, created=10, advance=False)
    assert state.page_number == 0
    assert state.last_status == "completed_no_advance"
    assert state.total_created == 10


def test_end_of_source_wraps_to_page_zero(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    state.page_number = 26
    db.commit()
    state = complete_sweep_run(db, state, pages_attempted=1, end_reached=True, source_total=1349)
    assert state.page_number == 0
    assert state.sweeps_completed == 1
    assert state.last_status == "completed_end_of_source"
    assert state.source_total == 1349


def test_reset_sweep_is_intentional_and_clears_progress(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    complete_sweep_run(db, state, pages_attempted=4, seen=200, created=100, updated=100)
    state = reset_sweep_state(db, state)
    assert state.page_number == 0
    assert state.total_seen == 0
    assert state.total_created == 0
    assert state.last_status == "reset"


def test_structured_errors_persisted(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    errors = [{"url": "https://api.pmg.org.za/bill/?page=9", "error": "HTTP 502", "type": "HTTPError"}]
    state = complete_sweep_run(db, state, pages_attempted=1, failed=1, errors=errors)
    assert "page=9" in state.last_error
    assert "HTTP 502" in state.last_error
    assert state.total_failed == 1


def test_totals_accumulate_across_runs(db):
    state = get_or_create_sweep_state(db, "PMG", "pmg_bills")
    complete_sweep_run(db, state, pages_attempted=2, created=5, updated=1)
    state = complete_sweep_run(db, state, pages_attempted=2, created=3, updated=7)
    assert state.page_number == 4
    assert state.total_created == 8
    assert state.total_updated == 8


# ---------------------------------------------------------------------------
# Bills core: start_page, pagination, end-of-source
# ---------------------------------------------------------------------------

def _bill_item(i):
    return {
        "id": 1000 + i,
        "title": f"Bill {i}",
        "number": i + 1,
        "year": 2025,
        "code": f"B{i + 1}-2025",
        "date_of_introduction": "2025-02-01",
        "status": {"name": "na"},
        "events": [],
    }


def _bills_api(pages: int, fail_pages=()):
    """Fixture API: `pages` pages of 2 bills each; final page has next=None."""

    def fetch(url):
        page = int(url.split("page=")[1])
        if page in fail_pages:
            raise ConnectionError("boom")
        if page >= pages:
            return json.dumps({"count": pages * 2, "next": None, "results": []})
        return json.dumps(
            {
                "count": pages * 2,
                "next": None if page == pages - 1 else f"https://api.pmg.org.za/bill/?page={page + 1}",
                "results": [_bill_item(page * 2), _bill_item(page * 2 + 1)],
            }
        )

    return fetch


def test_bills_core_start_page_and_pagination(db):
    summary = run_bills_ingest(db, limit=100, max_pages=2, start_page=1, sleep=0, fetch=_bills_api(4))
    assert summary["start_page"] == 1
    assert summary["pages_attempted"] == 2
    assert summary["bills_seen"] == 4
    assert summary["end_reached"] is False
    assert summary["source_total"] == 8
    assert summary["created"] == 4


def test_bills_core_end_reached(db):
    summary = run_bills_ingest(db, limit=100, max_pages=5, start_page=2, sleep=0, fetch=_bills_api(3))
    assert summary["pages_attempted"] == 1  # page 2 is the last page
    assert summary["end_reached"] is True


def test_bills_core_failure_recorded(db):
    summary = run_bills_ingest(db, limit=100, max_pages=3, start_page=0, sleep=0, fetch=_bills_api(4, fail_pages=(1,)))
    assert summary["pages_attempted"] == 1
    assert summary["failed"] == 1
    assert summary["errors"][0]["type"] == "ConnectionError"
    # page 0 bills still ingested — partial progress preserved
    assert summary["created"] == 2


def test_bills_core_dry_run_offline(db):
    def forbidden(url):
        raise AssertionError("network")

    summary = run_bills_ingest(None, dry_run=True, discover=False, sleep=0, fetch=forbidden)
    assert summary["pages_attempted"] == 0


# ---------------------------------------------------------------------------
# Backfill core: offset cursor and end-of-table
# ---------------------------------------------------------------------------

def _seed_bills(db, n):
    for i in range(n):
        upsert_bill(
            db,
            {
                "title": f"Seed Bill {i}",
                "bill_number": f"B{i + 50}-2025",
                "year": 2025,
                "house": None,
                "status": "introduced",
                "source_url": f"https://pmg.org.za/bill/{2000 + i}/",
                "source_type": "pmg-api",
                "events": [],
            },
        )
    db.commit()


def test_backfill_offset_walks_table(db):
    _seed_bills(db, 5)
    detail = json.dumps({"id": 1, "events": [{"date": "2025-03-01T00:00:00", "type": "bill-introduced", "title": "Introduced"}]})
    first = run_backfill(db, limit=2, max_pages=10, offset=0, sleep=0, dry_run=False, fetch=lambda u: detail)
    second = run_backfill(db, limit=2, max_pages=10, offset=2, sleep=0, dry_run=False, fetch=lambda u: detail)
    assert first["bills_selected"] == 2
    assert second["bills_selected"] == 2
    assert first["end_reached"] is False


def test_backfill_end_of_table_reached(db):
    _seed_bills(db, 3)
    summary = run_backfill(db, limit=10, max_pages=10, offset=0, sleep=0, dry_run=True, discover=False)
    assert summary["bills_selected"] == 3
    assert summary["end_reached"] is True


# ---------------------------------------------------------------------------
# Script-level sweep execution (execute_with_optional_sweep)
# ---------------------------------------------------------------------------

def _args(**overrides):
    base = dict(
        sweep=True,
        stream_name=None,
        pages_per_run=2,
        no_advance_sweep=False,
        reset_sweep=False,
        show_sweep_state=False,
        dry_run=False,
        discover=False,
        start_page=0,
        max_pages=2,
        limit=20,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def _core(summaries):
    """Fake run_core returning queued summaries and recording calls."""
    calls = []

    def run_core(db, start_page, max_pages):
        calls.append({"start_page": start_page, "max_pages": max_pages})
        return dict(summaries.pop(0))

    run_core.calls = calls
    return run_core


OK_SUMMARY = {
    "pages_attempted": 2, "processed": 4, "created": 4, "updated": 0,
    "failed": 0, "errors": [], "end_reached": False, "source_total": 100,
    "bills_seen": 4, "dry_run": False, "discover": False,
}


def test_sweep_mode_advances_and_resumes(db, patched_sessionlocal):
    args = _args()
    s1 = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="t")
    assert s1["sweep"]["advanced"] is True
    assert s1["sweep"]["next_page"] == 2
    core2 = _core([dict(OK_SUMMARY)])
    s2 = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=core2, run_type="t")
    # second run resumes where the first ended
    assert core2.calls[0]["start_page"] == 2
    assert s2["sweep"]["next_page"] == 4


def test_sweep_dry_run_does_not_advance(db, patched_sessionlocal):
    args = _args(dry_run=True)
    dry = {**OK_SUMMARY, "dry_run": True}
    s = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=_core([dry]), run_type="t")
    assert s["sweep"]["advanced"] is False
    with patched_sessionlocal() as check:
        state = check.scalar(select(IngestionSweepState))
        assert state.page_number == 0
        assert state.last_started_at is None  # dry runs never touch the state


def test_sweep_dry_run_discover_does_not_advance(db, patched_sessionlocal):
    args = _args(dry_run=True, discover=True)
    dry = {**OK_SUMMARY, "dry_run": True, "discover": True}
    execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=_core([dry]), run_type="t")
    with patched_sessionlocal() as check:
        assert check.scalar(select(IngestionSweepState)).page_number == 0


def test_sweep_no_advance_flag(db, patched_sessionlocal):
    args = _args(no_advance_sweep=True)
    s = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="t")
    assert s["sweep"]["advanced"] is False
    with patched_sessionlocal() as check:
        state = check.scalar(select(IngestionSweepState))
        assert state.page_number == 0
        assert state.last_status == "completed_no_advance"
        assert state.total_created == 4  # run recorded


def test_sweep_failed_run_does_not_advance(db, patched_sessionlocal):
    failed = {**OK_SUMMARY, "pages_attempted": 0, "failed": 1, "created": 0,
              "errors": [{"url": "x", "error": "boom", "type": "ConnectionError"}]}
    s = execute_with_optional_sweep(_args(), stream_name="pmg_bills", run_core=_core([failed]), run_type="t")
    assert s["sweep"]["advanced"] is False
    with patched_sessionlocal() as check:
        state = check.scalar(select(IngestionSweepState))
        assert state.page_number == 0
        assert state.last_status == "failed"


def test_failed_sweep_leaves_only_that_stream_cursor_unchanged(db, patched_sessionlocal):
    other = get_or_create_sweep_state(db, "PMG", "pmg_committee_meetings")
    other.page_number = 9
    db.commit()

    def timeout_core(db, start_page, max_pages):
        return {
            **OK_SUMMARY,
            "start_page": start_page,
            "pages_attempted": 0,
            "failed": 1,
            "created": 0,
            "errors": [{"url": "https://api.pmg.org.za/bill/?page=0", "error": "timed out", "type": "Timeout"}],
        }

    s = execute_with_optional_sweep(_args(), stream_name="pmg_bills", run_core=timeout_core, run_type="t")
    assert s["sweep"]["advanced"] is False
    with patched_sessionlocal() as check:
        bills = get_or_create_sweep_state(check, "PMG", "pmg_bills")
        meetings = get_or_create_sweep_state(check, "PMG", "pmg_committee_meetings")
        assert bills.page_number == 0
        assert bills.last_status == "failed"
        assert meetings.page_number == 9


def test_sweep_end_reached_wraps(db, patched_sessionlocal):
    ended = {**OK_SUMMARY, "pages_attempted": 1, "end_reached": True}
    s = execute_with_optional_sweep(_args(), stream_name="pmg_bills", run_core=_core([ended]), run_type="t")
    assert s["sweep"]["next_page"] == 0
    assert s["sweep"]["sweeps_completed"] == 1
    assert s["sweep"]["last_status"] == "completed_end_of_source"


def test_sweep_reset_action(db, patched_sessionlocal):
    execute_with_optional_sweep(_args(), stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="t")
    result = execute_with_optional_sweep(_args(reset_sweep=True), stream_name="pmg_bills", run_core=_core([]), run_type="t")
    assert result["action"] == "reset"
    assert result["sweep"]["next_page"] == 0


def test_sweep_show_state_action(db, patched_sessionlocal, capsys):
    result = execute_with_optional_sweep(_args(show_sweep_state=True), stream_name="pmg_bills", run_core=_core([]), run_type="t")
    assert result["action"] == "show"
    assert result["sweep"]["stream_name"] == "pmg_bills"


def test_sweep_requires_bounded_pages(db, patched_sessionlocal):
    with pytest.raises(SystemExit):
        execute_with_optional_sweep(_args(pages_per_run=0), stream_name="pmg_bills", run_core=_core([]), run_type="t")


def test_sweep_stream_name_override(db, patched_sessionlocal):
    args = _args(stream_name="custom_stream")
    s = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="t")
    assert s["sweep"]["stream_name"] == "custom_stream"


def test_direct_mode_unchanged_no_sweep_state(db, patched_sessionlocal):
    args = _args(sweep=False, dry_run=True)
    s = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="t")
    assert "sweep" not in s
    with patched_sessionlocal() as check:
        assert check.scalar(select(IngestionSweepState)) is None


def test_sweep_json_summary_includes_sweep_info(db, patched_sessionlocal):
    s = execute_with_optional_sweep(_args(), stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="t")
    blob = json.loads(json.dumps(s, default=str))
    assert blob["sweep"]["stream_name"] == "pmg_bills"
    assert "next_page" in blob["sweep"]
    assert "advanced" in blob["sweep"]


def test_sweep_records_ingestion_run(db, patched_sessionlocal):
    from app.models.ingestion_run import IngestionRun

    execute_with_optional_sweep(_args(), stream_name="pmg_bills", run_core=_core([dict(OK_SUMMARY)]), run_type="bills_ingest")
    with patched_sessionlocal() as check:
        run = check.scalar(select(IngestionRun))
        assert run is not None
        assert run.run_type == "bills_ingest"
        assert run.created_count == 4


def test_repeated_sweep_of_same_window_is_idempotent(db, patched_sessionlocal):
    """Re-running the same window (e.g. after --reset-sweep) must not
    duplicate bills — upserts dedupe by source_url."""
    args = _args(pages_per_run=2)
    fetch = _bills_api(2)

    def real_core(session, start_page, max_pages):
        return run_bills_ingest(session, limit=100, max_pages=max_pages, start_page=start_page, sleep=0, fetch=fetch)

    execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=real_core, run_type="t")
    execute_with_optional_sweep(_args(reset_sweep=True), stream_name="pmg_bills", run_core=_core([]), run_type="t")
    s2 = execute_with_optional_sweep(args, stream_name="pmg_bills", run_core=real_core, run_type="t")
    assert s2["created"] == 0
    assert s2["updated"] == 4
    with patched_sessionlocal() as check:
        assert len(list(check.scalars(select(Bill)))) == 4


# ---------------------------------------------------------------------------
# run_full_ingestion orchestration
# ---------------------------------------------------------------------------

def _rfi_args(**overrides):
    base = dict(
        pages_per_run=3,
        sleep=0.5,
        discover=False,
        skip_bill_sweep=False,
        skip_bill_lifecycle_sweep=False,
        skip_committee_meeting_sweep=False,
        skip_vote_sweep=False,
    )
    base.update(overrides)
    return argparse.Namespace(**base)


def test_accountability_sweep_stage_order():
    stages = rfi.build_accountability_sweep_stages(_rfi_args())
    scripts = [s[1] for s in stages]
    assert scripts == [
        "ingest_bills.py",
        "backfill_legislative_history.py",
        "ingest_committee_activity.py",
        "ingest_votes.py",
    ]
    for _, _, extra in stages:
        assert "--sweep" in extra
        assert "--pages-per-run" in extra
        assert extra[extra.index("--pages-per-run") + 1] == "3"
        assert "--json-output" in extra


def test_accountability_sweep_skip_flags():
    stages = rfi.build_accountability_sweep_stages(
        _rfi_args(skip_bill_sweep=True, skip_vote_sweep=True)
    )
    scripts = [s[1] for s in stages]
    assert scripts == ["backfill_legislative_history.py", "ingest_committee_activity.py"]


def test_accountability_sweep_discover_passthrough():
    stages = rfi.build_accountability_sweep_stages(_rfi_args(discover=True))
    assert all("--discover" in extra for _, _, extra in stages)
