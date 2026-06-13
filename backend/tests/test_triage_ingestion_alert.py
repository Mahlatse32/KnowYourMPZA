"""Tests for the ingestion alert triage script."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from triage_ingestion_alert import (
    CURRENT,
    STALE,
    UNKNOWN,
    redact_text,
    render_markdown,
    triage,
    write_report,
)


def _write(tmp_path: Path, name: str, payload: dict) -> None:
    (tmp_path / name).write_text(json.dumps(payload), encoding="utf-8")


def test_missing_reports_yields_unknown(tmp_path):
    result = triage(tmp_path)
    assert result["verdict"] == UNKNOWN
    assert result["inputs_present"] == {
        "ingestion_brief": False,
        "accountability_sweep_report": False,
        "data_coverage_dashboard": False,
    }


def test_green_brief_is_stale(tmp_path):
    _write(tmp_path, "ingestion_brief.json", {"status": "green", "reasons": ["all good"], "errors": []})
    result = triage(tmp_path)
    assert result["verdict"] == STALE
    assert "green" in result["reasons"][0]


def test_yellow_brief_is_stale(tmp_path):
    _write(tmp_path, "ingestion_brief.json", {"status": "yellow", "reasons": ["dry run"], "errors": []})
    assert triage(tmp_path)["verdict"] == STALE


def test_red_brief_is_current(tmp_path):
    _write(
        tmp_path,
        "ingestion_brief.json",
        {
            "status": "red",
            "reasons": ["2 stage(s) reported failures", "14 errors (threshold 3)"],
            "errors": [{"url": "https://pmg.org.za/bill/1332/", "error": "boom", "type": "DBError"}],
        },
    )
    result = triage(tmp_path)
    assert result["verdict"] == CURRENT
    assert any("failures" in r for r in result["reasons"])
    assert result["error_count"] == 1


def test_sweep_failed_stages_make_current_even_without_brief(tmp_path):
    _write(
        tmp_path,
        "accountability_sweep_report.json",
        {"mode": "real", "exit_code": 1, "stage_summaries": [{"failed": 2, "sweep": {"stream_name": "pmg_bills"}}], "errors": []},
    )
    result = triage(tmp_path)
    assert result["verdict"] == CURRENT
    assert result["failed_stages"]


def test_secret_redaction_in_errors(tmp_path):
    _write(
        tmp_path,
        "ingestion_brief.json",
        {
            "status": "red",
            "reasons": ["x"],
            "errors": [{"url": "x", "type": "E", "error": "connect postgresql://user:hunter2@host/db failed"}],
        },
    )
    result = triage(tmp_path)
    blob = json.dumps(result)
    assert "hunter2" not in blob
    assert "[REDACTED]@" in blob
    assert "hunter2" not in render_markdown(result)


def test_redact_text_handles_database_url():
    assert "hunter2" not in redact_text("DATABASE_URL=postgresql://u:hunter2@h/db")
    assert "[REDACTED]" in redact_text("DATABASE_URL=postgresql://u:hunter2@h/db")


def test_markdown_includes_review_sections(tmp_path):
    _write(tmp_path, "ingestion_brief.json", {"status": "red", "reasons": ["x"], "errors": []})
    md = render_markdown(triage(tmp_path))
    assert "# Ingestion Alert Triage" in md
    assert "Verdict" in md
    assert "Recommended next steps" in md


def test_write_report_produces_valid_json(tmp_path):
    _write(tmp_path, "ingestion_brief.json", {"status": "green", "reasons": ["ok"], "errors": []})
    result = triage(tmp_path)
    json_path, md_path = write_report(result, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["verdict"] == STALE
    assert md_path.read_text(encoding="utf-8").startswith("# Ingestion Alert Triage")


def test_malformed_json_is_handled(tmp_path):
    (tmp_path / "ingestion_brief.json").write_text("{not json", encoding="utf-8")
    # falls through to unknown rather than raising
    assert triage(tmp_path)["verdict"] == UNKNOWN
