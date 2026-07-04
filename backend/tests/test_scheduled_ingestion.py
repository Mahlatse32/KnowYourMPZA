"""Weekly scheduled ingestion graceful degradation (#47).

The weekly runner must keep running the independent downstream stages after a
systemic People's Assembly source-access failure, generate the reports, and
still mark the run failed (red) — never silently green. No network or database.
"""
import json
import re
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

import run_weekly_ingestion as weekly

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"


def _stages():
    return [
        ("people_assembly", ["python", "scripts/ingest_all_people_assembly.py"]),
        ("committees", ["python", "scripts/ingest_all_committees.py"]),
        ("regenerate_aliases", ["python", "scripts/regenerate_aliases.py"]),
        ("dataset_report", ["python", "scripts/dataset_report.py"]),
    ]


def test_build_stages_order_and_env(monkeypatch):
    monkeypatch.setenv("MAX_WEEKLY_INGESTION_URLS", "7")
    monkeypatch.setenv("SOURCE_RATE_LIMIT_SLEEP", "0.25")
    names = [name for name, _ in weekly.build_stages()]
    assert names == ["people_assembly", "committees", "regenerate_aliases", "dataset_report"]
    pa_command = weekly.build_stages()[0][1]
    assert "--limit" in pa_command and "7" in pa_command
    assert "--sleep" in pa_command and "0.25" in pa_command


def test_independent_stages_run_after_pa_systemic_failure():
    executed = []

    def runner(command):
        executed.append(command)
        # People's Assembly (and the committees page that shares the host) fail;
        # the database-only stages succeed.
        return 1 if "people_assembly" in command[-1] or "committees" in command[-1] else 0

    results = weekly.run_stages(_stages(), runner=runner)
    ran = [r["stage"] for r in results]

    # Every stage ran — the PA failure did not abort the batch.
    assert ran == ["people_assembly", "committees", "regenerate_aliases", "dataset_report"]
    assert len(executed) == 4
    # The independent downstream stages still succeeded.
    by_stage = {r["stage"]: r["exit_code"] for r in results}
    assert by_stage["regenerate_aliases"] == 0
    assert by_stage["dataset_report"] == 0


def _write_source_summary(path: Path, systemic: bool = True) -> None:
    path.write_text(
        json.dumps({"systemic_source_access_failure": systemic}),
        encoding="utf-8",
    )


def test_final_status_is_green_when_only_pa_enrichment_sources_are_systemically_blocked(tmp_path):
    _write_source_summary(tmp_path / "people_assembly_ingestion_summary.json")
    _write_source_summary(tmp_path / "committees_ingestion_summary.json")
    results = [
        {"stage": "people_assembly", "exit_code": 1},
        {"stage": "committees", "exit_code": 1},
        {"stage": "regenerate_aliases", "exit_code": 0},
        {"stage": "dataset_report", "exit_code": 0},
    ]
    ok, summary = weekly.summarize(results, reports_dir=tmp_path)
    assert ok is True
    assert "SOURCE-BLOCKED (non-blocking enrichment)" in summary
    assert "people_assembly" in summary
    assert "PMG-derived identity fallback is the V1 authority" in summary


def test_final_status_is_red_when_failed_source_stage_lacks_systemic_summary(tmp_path):
    results = [
        {"stage": "people_assembly", "exit_code": 1},
        {"stage": "regenerate_aliases", "exit_code": 0},
        {"stage": "dataset_report", "exit_code": 0},
    ]
    ok, summary = weekly.summarize(results, reports_dir=tmp_path)
    assert ok is False
    assert "FAILED" in summary
    assert "people_assembly_ingestion_summary.json" in summary


def test_final_status_is_red_when_non_enrichment_stage_fails(tmp_path):
    _write_source_summary(tmp_path / "people_assembly_ingestion_summary.json")
    results = [
        {"stage": "people_assembly", "exit_code": 1},
        {"stage": "regenerate_aliases", "exit_code": 0},
        {"stage": "dataset_report", "exit_code": 1},
    ]
    ok, summary = weekly.summarize(results, reports_dir=tmp_path)
    assert ok is False
    assert "dataset_report" in summary


def test_final_status_is_green_when_all_stages_pass():
    results = [{"stage": name, "exit_code": 0} for name in
               ("people_assembly", "committees", "regenerate_aliases", "dataset_report")]
    ok, summary = weekly.summarize(results)
    assert ok is True
    assert "FAILED" not in summary


def test_main_exits_nonzero_on_stage_failure(monkeypatch):
    monkeypatch.setattr(weekly, "_ensure_enabled", lambda: None)
    monkeypatch.setattr(weekly, "build_stages", _stages)
    monkeypatch.setattr(weekly, "_run_subprocess", lambda command: 1 if "people_assembly" in command[-1] else 0)
    with pytest.raises(SystemExit) as excinfo:
        weekly.main()
    assert excinfo.value.code == 1


def test_main_succeeds_when_all_stages_pass(monkeypatch):
    monkeypatch.setattr(weekly, "_ensure_enabled", lambda: None)
    monkeypatch.setattr(weekly, "build_stages", _stages)
    monkeypatch.setattr(weekly, "_run_subprocess", lambda command: 0)
    # No SystemExit raised on success.
    weekly.main()


# ---------------------------------------------------------------------------
# Workflow wiring — reports are still produced when the weekly run fails red
# ---------------------------------------------------------------------------

def _weekly_step_blocks() -> list[str]:
    """Return only top-level step blocks from the weekly job."""
    text = WORKFLOW.read_text(encoding="utf-8")
    assert text.count("\n  weekly:") == 1
    weekly_job = text.split("\n  weekly:", 1)[1]
    blocks: list[str] = []
    current: list[str] = []
    for line in weekly_job.splitlines():
        if re.match(r"^      - ", line):
            if current:
                blocks.append("\n".join(current))
            current = [line]
        elif current:
            current.append(line)
    if current:
        blocks.append("\n".join(current))
    return blocks


def _block_with(blocks: list[str], needle: str) -> str:
    matches = [b for b in blocks if needle in b]
    assert len(matches) == 1, (
        f"expected exactly one weekly step block containing {needle!r}, "
        f"found {len(matches)}"
    )
    return matches[0]


def test_scheduled_ingestion_jobs_have_timeouts():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "timeout-minutes: 75" in text
    assert "timeout-minutes: 90" in text


def test_weekly_runner_step_does_not_swallow_unclassified_failures():
    # The runner step must NOT swallow failures — no `|| true`, no
    # `continue-on-error: true` — so a systemic PA failure keeps the job red.
    runner_block = _block_with(_weekly_step_blocks(), "run_weekly_ingestion.py")
    assert "run: python scripts/run_weekly_ingestion.py" in runner_block
    assert "|| true" not in runner_block
    assert "continue-on-error" not in runner_block
    assert "if: always()" not in runner_block


def test_weekly_job_always_generates_brief_after_failure():
    # The brief is generated with if: always() so a red run still reports.
    blocks = _weekly_step_blocks()
    runner_index = blocks.index(_block_with(blocks, "run_weekly_ingestion.py"))
    brief_block = _block_with(blocks, "name: Generate ingestion brief")
    assert "if: always()" in brief_block
    assert "run: python scripts/generate_ingestion_brief.py --reports-dir reports || true" in brief_block
    assert blocks.index(brief_block) > runner_index


def test_weekly_job_uploads_reports_always():
    blocks = _weekly_step_blocks()
    runner_index = blocks.index(_block_with(blocks, "run_weekly_ingestion.py"))
    upload_block = _block_with(blocks, "name: Upload weekly ingestion reports")
    assert "if: always()" in upload_block
    assert "uses: actions/upload-artifact@v4" in upload_block
    assert "backend/reports/" in upload_block
    assert blocks.index(upload_block) > runner_index
