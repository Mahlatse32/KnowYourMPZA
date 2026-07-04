import json

from scripts.report_v1_readiness import build_report, load_inputs, write_report


def _inputs(**overrides):
    base = {
        "mp_coverage": {
            "readiness": "red",
            "expected_universe_available": False,
            "cannot_claim_all_mps": True,
            "blockers": ["No expected MP universe."],
        },
        "data_coverage": {
            "executive_summary": {
                "total_bills": 1171,
                "total_committee_meetings": 3416,
                "total_parliamentary_questions": 139,
            },
            "public_claim_readiness": {
                "safe_for_public_facing_completeness_claims": True
            }
        },
        "inspect": {
            "sweep_states": [
                {
                    "stream_name": "pmg_bills",
                    "source_total": 1246,
                    "last_status": "completed",
                    "next_page": 15,
                    "total_seen": 3242,
                    "total_failed": 1,
                    "last_completed_at": "2026-07-04T06:01:02+00:00",
                },
                {
                    "stream_name": "pmg_committee_meetings",
                    "source_total": 34710,
                    "last_status": "completed",
                    "next_page": 70,
                    "total_seen": 3500,
                    "total_failed": 17,
                    "last_completed_at": "2026-07-04T06:32:57+00:00",
                },
            ]
        },
        "iec_coverage": {
            "public_readiness": {"status": "green"},
            "full_iec_ingestion_complete": False,
        },
        "ingestion_brief": {"status": "green", "reasons": []},
        "people_assembly": {
            "status": "completed",
            "systemic_source_access_failure": False,
        },
        "parliamentary_questions_ingestion": {
            "status": "ok",
            "attempted_count": 50,
            "processed_count": 50,
            "created_count": 0,
            "updated_count": 50,
            "failed_count": 0,
        },
        "mp_source_audit": {"status": "audit-only", "source_count": 4},
        "source_inventory_exists": True,
        "input_warnings": [],
    }
    base.update(overrides)
    return base


def test_red_when_mp_expected_universe_is_missing():
    report = build_report(_inputs())
    assert report["overall_status"] == "red"
    assert report["people_coverage_status"] == "red"
    assert report["expected_universe_available"] is False
    assert report["cannot_claim_all_mps"] is True


def test_red_when_pa_source_access_is_blocked():
    report = build_report(
        _inputs(
            people_assembly={
                "status": "failed",
                "systemic_source_access_failure": True,
                "errors": ["DATABASE_URL=postgresql://user:password@db/test"],
            }
        )
    )
    assert report["PA_source_access_status"] == "red"
    assert any("#47" in blocker for blocker in report["blockers"])
    assert "password" not in json.dumps(report)


def test_iec_foundation_only_is_amber():
    report = build_report(_inputs())
    assert report["IEC_status"] == "amber"
    assert any("#24" in blocker for blocker in report["blockers"])


def test_aggregates_blockers_and_never_claims_full_coverage():
    report = build_report(
        _inputs(
            ingestion_brief={"status": "red", "reasons": ["systemic failure"]},
            data_coverage=None,
        )
    )
    assert "The data coverage dashboard is missing." in report["blockers"]
    assert "The latest ingestion brief is red." in report["blockers"]
    assert report["full_coverage_claim_supported"] is False
    assert any("never treated as success" in rule for rule in report["integrity_rules"])


def test_missing_inputs_are_reported_not_treated_as_green(tmp_path):
    inputs = load_inputs(tmp_path, tmp_path / "missing-source-inventory.md")
    report = build_report(inputs)
    assert report["overall_status"] == "red"
    assert report["source_inventory_status"] == "red"
    assert report["completed_capabilities"] == []


def test_reports_are_generated_and_secret_safe(tmp_path):
    report = build_report(_inputs())
    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["overall_status"] == "red"
    assert "# V1 Readiness Report" in blob
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob


def test_launch_coverage_rows_include_counts_totals_status_and_next_actions():
    report = build_report(_inputs())
    rows = {row["label"]: row for row in report["launch_coverage"]}

    assert rows["PMG bills"]["production_count"] == 1171
    assert rows["PMG bills"]["source_total"] == 1246
    assert rows["PMG bills"]["coverage_pct"] == 93.98
    assert rows["PMG bills"]["launch_status"] == "pass"

    meetings = rows["PMG committee meetings"]
    assert meetings["production_count"] == 3416
    assert meetings["source_total"] == 34710
    assert meetings["coverage_pct"] == 9.84
    assert meetings["launch_status"] == "blocker"
    assert "Claude issue #59" in meetings["next_recommended_action"]
    assert "status=completed" in meetings["last_ingestion_evidence"]

    questions = rows["Parliament questions"]
    assert questions["production_count"] == 139
    assert questions["source_total"] == 44036
    assert questions["coverage_pct"] == 0.32
    assert questions["launch_status"] == "blocker"
    assert "new-record-first" in questions["next_recommended_action"]


def test_readiness_markdown_renders_launch_coverage_table(tmp_path):
    report = build_report(_inputs())
    _, markdown_path = write_report(report, tmp_path)
    text = markdown_path.read_text(encoding="utf-8")

    assert "## Launch coverage" in text
    assert "| PMG committee meetings | 3416 | 34710 | 9.84% | blocker |" in text
    assert "| Parliament questions | 139 | 44036 | 0.32% | blocker |" in text
