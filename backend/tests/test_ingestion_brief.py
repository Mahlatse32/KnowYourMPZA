"""Tests for the automated ingestion brief: classification, recommendations,
rendering, graceful degradation, and workflow integration."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from generate_ingestion_brief import (
    build_brief,
    build_recommendations,
    classify_run,
    load_inputs,
    render_markdown,
    write_brief_files,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
SWEEP_WF = REPO_ROOT / ".github" / "workflows" / "accountability-sweep.yml"
READINESS_WF = REPO_ROOT / ".github" / "workflows" / "persistent-db-readiness.yml"


def _stage(advanced=True, failed=0, errors=None, last_status="completed"):
    return {
        "pages_attempted": 2, "processed": 50, "created": 40, "updated": 10,
        "failed": failed, "errors": errors or [], "end_reached": False,
        "sweep": {"stream_name": "pmg_bills", "next_page": 2, "advanced": advanced, "last_status": last_status},
    }


def _sweep_report(mode="real", exit_code=0, stages=None, delta=None, **overrides):
    base = {
        "mode": mode,
        "exit_code": exit_code,
        "pages_per_run": 3,
        "counts_before": {"bills": 90, "vote_events": 9, "vote_records": 0,
                          "committee_meetings": 99, "committee_attendance": 1029, "bill_events": 359},
        "counts_after": {"bills": 140, "vote_events": 12, "vote_records": 0,
                         "committee_meetings": 149, "committee_attendance": 1500, "bill_events": 420},
        "counts_delta": delta if delta is not None else {"bills": 50, "vote_events": 3, "vote_records": 0,
                                                         "committee_meetings": 50, "committee_attendance": 471, "bill_events": 61},
        "stage_summaries": stages if stages is not None else [_stage()],
        "sweep_states": [
            {"source_name": "PMG", "stream_name": "pmg_bills", "next_page": 4, "last_status": "completed",
             "total_created": 120, "total_updated": 30, "total_failed": 0, "total_seen": 150,
             "source_total": 1246, "sweeps_completed": 0, "cursor_type": "page",
             "last_started_at": None, "last_completed_at": None, "last_error": None},
        ],
        "errors": [],
        "estimated_meeting_coverage_percent": 0.43,
        "source_totals": {"pmg_committee_meetings": 34648},
        "next_recommended_batch": "pages_per_run=3 is healthy.",
    }
    base.update(overrides)
    return base


def _pa_summary(systemic=True):
    """A People's Assembly ingestion summary shaped like build_result output."""
    return {
        "source": "people_assembly",
        "attempted_count": 100,
        "processed_count": 0,
        "created_count": 0,
        "updated_count": 0,
        "skipped_count": 0,
        "failed_count": 100,
        "status": "failed" if systemic else "partial",
        "systemic_source_access_failure": systemic,
        "failed_fetch_count": 100 if systemic else 1,
        "top_error_types": {"HTTPError": 100} if systemic else {"HTTPError": 1},
        "sample_safe_errors": [
            {"url": "https://www.pa.org.za/person/1/", "type": "HTTPError",
             "error": "Source fetch failed from www.pa.org.za: HTTP 403."},
        ],
        "recommendation": (
            "All attempted source fetches failed before parsing (systemic "
            "source-access failure). Run ingestion from a non-blocked host or network; "
            "do not repeatedly rerun CI while blocked."
        ) if systemic else "",
        "errors": [],
    }


def _inputs(**overrides):
    base = {
        "sweep_report": _sweep_report(),
        "inspect": {"tables": {"bills": {"count": 140, "samples": [
            {"id": "x", "title": "Gas Bill", "source_url": "https://pmg.org.za/bill/1332/"}]}}, "sweep_states": []},
        "coverage": {"accountability_sweep": {"estimated_meeting_coverage_percent": 0.43}},
        "completeness": {"summary": {"pass": 17, "fail": 0, "warn": 4, "skip": 0}},
        "readiness": {"ready": True, "database": "postgresql+psycopg://db:5432/knowyourmpza",
                      "checks": [{"name": "url_present", "status": "pass", "detail": "ok"}]},
    }
    base.update(overrides)
    return base


# ---------------------------------------------------------------------------
# Classification
# ---------------------------------------------------------------------------

def test_green_classification():
    status, reasons = classify_run(_inputs())
    assert status == "green"
    assert any("advanced" in r for r in reasons)


def test_yellow_for_dry_run():
    status, reasons = classify_run(_inputs(sweep_report=_sweep_report(mode="dry_run")))
    assert status == "yellow"
    assert any("dry_run" in r for r in reasons)


def test_yellow_when_no_sweep_report():
    status, reasons = classify_run(_inputs(sweep_report=None))
    assert status == "yellow"
    assert any("no sweep report" in r for r in reasons)


def test_yellow_when_no_new_records_but_advanced():
    zero_delta = {k: 0 for k in ("bills", "vote_events", "vote_records", "committee_meetings", "committee_attendance", "bill_events")}
    status, reasons = classify_run(_inputs(sweep_report=_sweep_report(delta=zero_delta)))
    assert status == "yellow"
    assert any("no new records" in r for r in reasons)


def test_red_for_failed_stages():
    bad = _sweep_report(stages=[_stage(failed=2)])
    status, reasons = classify_run(_inputs(sweep_report=bad))
    assert status == "red"
    assert any("failures" in r for r in reasons)


def test_red_for_error_threshold():
    errors = [{"url": "x", "error": "boom", "type": "E"}] * 3
    status, _ = classify_run(_inputs(sweep_report=_sweep_report(errors=errors)))
    assert status == "red"


def test_red_for_failed_readiness():
    readiness = {"ready": False, "database": "postgresql+psycopg://db/x",
                 "checks": [{"name": "required_tables", "status": "fail", "detail": "missing"}]}
    status, reasons = classify_run(_inputs(readiness=readiness))
    assert status == "red"
    assert any("missing required tables" in r for r in reasons)


def test_red_for_real_run_with_no_advancement():
    stuck = _sweep_report(stages=[_stage(advanced=False)])
    status, reasons = classify_run(_inputs(sweep_report=stuck))
    assert status == "red"
    assert any("no sweep stream advanced" in r for r in reasons)


def test_red_for_completeness_failures():
    status, _ = classify_run(_inputs(completeness={"summary": {"pass": 15, "fail": 2, "warn": 0, "skip": 0}}))
    assert status == "red"


# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

def test_recommendation_when_database_url_missing():
    readiness = {"ready": False, "database": "(not set)",
                 "checks": [{"name": "url_present", "status": "fail", "detail": "missing"}]}
    recs = build_recommendations(_inputs(readiness=readiness), "red")
    assert any("DATABASE_URL" in r for r in recs)


def test_recommendation_for_green_run():
    recs = build_recommendations(_inputs(), "green")
    assert any("Keep this batch size" in r for r in recs)
    assert any("pages_per_run=6" in r for r in recs)


def test_recommendation_explains_zero_vote_records():
    recs = build_recommendations(_inputs(), "green")
    explanation = next(r for r in recs if "vote_records is 0" in r)
    assert "never fabricated" in explanation


def test_recommendation_for_zero_attendance():
    report = _sweep_report()
    report["counts_after"]["committee_attendance"] = 0
    recs = build_recommendations(_inputs(sweep_report=report), "yellow")
    assert any("attendance endpoint" in r for r in recs)


def test_recommendation_on_errors_keeps_cursor():
    report = _sweep_report(errors=[{"url": "x", "error": "HTTP 502", "type": "HTTPError"}])
    recs = build_recommendations(_inputs(sweep_report=report), "yellow")
    assert any("keep the current page cursor" in r.lower() for r in recs)


def test_recommendation_for_dry_run_mode():
    recs = build_recommendations(_inputs(sweep_report=_sweep_report(mode="dry_run")), "yellow")
    assert any("validation only" in r for r in recs)


def test_recommendation_low_coverage_keeps_sweeping():
    recs = build_recommendations(_inputs(), "green")
    assert any("coverage" in r and "scheduled sweeps" in r for r in recs)


# ---------------------------------------------------------------------------
# Brief building and rendering
# ---------------------------------------------------------------------------

def test_brief_handles_all_inputs_missing(tmp_path):
    inputs = load_inputs(tmp_path)  # empty directory
    brief = build_brief(inputs)
    assert brief["status"] == "yellow"
    assert brief["counts_after"] is None
    assert any("DATABASE_URL" in a for a in brief["next_actions"])
    md = render_markdown(brief)
    assert "# Ingestion Brief" in md


def test_brief_counts_delta_rendering():
    brief = build_brief(_inputs())
    md = render_markdown(brief)
    assert "| bills | 90 | 140 | 50 |" in md
    assert "## What changed" in md


def test_brief_sweep_state_rendering():
    md = render_markdown(build_brief(_inputs()))
    assert "## Sweep progress" in md
    assert "pmg_bills" in md


def test_brief_includes_top_new_records_with_source_urls():
    brief = build_brief(_inputs())
    assert any(r["source_url"] == "https://pmg.org.za/bill/1332/" for r in brief["top_new_records"])
    assert "https://pmg.org.za/bill/1332/" in render_markdown(brief)


def test_brief_markdown_contains_expected_sections():
    md = render_markdown(build_brief(_inputs()))
    for section in ("## Status", "### Why", "## What changed", "## Sweep progress",
                    "## Attention required", "## Next recommended actions", "## Data integrity"):
        assert section in md, f"missing section {section}"


def test_brief_includes_integrity_language():
    brief = build_brief(_inputs())
    blob = json.dumps(brief)
    assert "No fabricated attendance" in blob
    assert "No fabricated votes" in blob
    assert "vote_records may legitimately remain 0" in blob
    md = render_markdown(brief)
    assert "No fabricated votes" in md


def test_brief_green_has_empty_attention():
    brief = build_brief(_inputs())
    assert brief["status"] == "green"
    assert brief["attention_required"] == []
    assert "Nothing — this run needs no human action." in render_markdown(brief)


def test_brief_json_parseable_and_files_written(tmp_path):
    json_path, md_path = write_brief_files(build_brief(_inputs()), tmp_path)
    parsed = json.loads(json_path.read_text(encoding="utf-8"))
    assert parsed["status"] == "green"
    assert md_path.read_text(encoding="utf-8").startswith("# Ingestion Brief")


def test_brief_never_contains_credentials():
    readiness = {"ready": True, "database": "postgresql+psycopg://db:5432/knowyourmpza",
                 "checks": [{"name": "url_present", "status": "pass", "detail": "ok"}]}
    blob = json.dumps(build_brief(_inputs(readiness=readiness)))
    assert "password" not in blob.lower()
    assert "://db:5432" in blob  # redacted host form only


def test_brief_completeness_summary_normalized():
    brief = build_brief(_inputs())
    assert brief["completeness"] == {"PASS": 17, "FAIL": 0, "WARN": 4, "SKIP": 0}


# ---------------------------------------------------------------------------
# Workflow integration
# ---------------------------------------------------------------------------

def test_sweep_workflow_generates_and_uploads_brief():
    text = SWEEP_WF.read_text(encoding="utf-8")
    assert "generate_ingestion_brief.py" in text
    assert "actions/upload-artifact" in text
    assert "backend/reports/" in text  # brief lands in the uploaded dir


def test_sweep_workflow_appends_brief_to_step_summary():
    text = SWEEP_WF.read_text(encoding="utf-8")
    assert "ingestion_brief.md" in text
    assert "GITHUB_STEP_SUMMARY" in text


def test_readiness_workflow_generates_brief():
    assert "generate_ingestion_brief.py" in READINESS_WF.read_text(encoding="utf-8")


def test_brief_path_is_gitignored():
    assert "reports/" in (REPO_ROOT / ".gitignore").read_text(encoding="utf-8")
    assert "reports/" in (REPO_ROOT / "backend" / ".gitignore").read_text(encoding="utf-8")


# ---------------------------------------------------------------------------
# People's Assembly source-access failure (#47)
# ---------------------------------------------------------------------------

def test_brief_red_for_systemic_pa_source_access_failure():
    status, reasons = classify_run(_inputs(people_assembly=_pa_summary()))
    assert status == "red"
    assert any("People's Assembly source access failed systemically" in r for r in reasons)
    # The reason makes clear this is a source-side block, not fabricated/missing data.
    assert any("not fabricated or missing data" in r for r in reasons)


def test_brief_not_red_for_non_systemic_pa_summary():
    # A non-systemic PA summary must not flip an otherwise-green run.
    status, _ = classify_run(_inputs(people_assembly=_pa_summary(systemic=False)))
    assert status == "green"


def test_brief_includes_pa_source_access_recommendation():
    recs = build_recommendations(_inputs(people_assembly=_pa_summary()), "red")
    assert any("non-blocked host" in r for r in recs)
    assert any("do not repeatedly rerun ci" in r.lower() for r in recs)


def test_brief_renders_source_access_section():
    brief = build_brief(_inputs(people_assembly=_pa_summary()))
    assert brief["status"] == "red"
    assert brief["source_access"]["systemic_source_access_failure"] is True
    md = render_markdown(brief)
    assert "## Source access" in md
    assert "SYSTEMIC SOURCE-ACCESS FAILURE" in md
    assert "HTTPError" in md
    assert "www.pa.org.za" in md


def test_brief_redacts_raw_secrets_in_source_access_errors():
    # Feed RAW (unredacted) secrets to prove the brief layer strips them itself —
    # defense-in-depth, not relying on upstream redaction.
    summary = _pa_summary()
    summary["sample_safe_errors"] = [
        {"url": "https://admin:super-secret-pw@www.pa.org.za/x/", "type": "HTTPError",
         "error": "connect failed DATABASE_URL=postgresql://u:hunter2@db/app token=ghp_abcdefghijklmnopqrstuvwxyz123456"},
    ]
    brief = build_brief(_inputs(people_assembly=summary))
    for surface in (json.dumps(brief), render_markdown(brief)):
        assert "super-secret-pw" not in surface
        assert "hunter2" not in surface
        assert "ghp_abcdefghijklmnopqrstuvwxyz123456" not in surface
        assert "[REDACTED]" in surface


def test_brief_without_pa_summary_has_null_source_access():
    brief = build_brief(_inputs())
    assert brief["source_access"] is None
    assert "## Source access" not in render_markdown(brief)