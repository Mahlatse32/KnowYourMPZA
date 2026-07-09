import json
from pathlib import Path

from scripts.smoke_test_frontend_api import render_markdown, run_smoke, write_report

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULED_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"
FRONTEND_MAIN = REPO_ROOT / "frontend" / "src" / "main.tsx"

POLITICIAN = {
    "id": "11111111-1111-1111-1111-111111111111",
    "full_name": "Test Person",
    "display_name": "T. Person",
    "slug": "test-person",
}
PARTY = {"id": "p1", "name": "Test Party", "short_name": "TP"}
COMMITTEE = {"id": "c1", "name": "Portfolio Committee on Testing"}
DOCUMENT = {"id": "d1", "title": "Doc", "document_type": "PMG_REPORT", "source_url": "https://pmg.org.za/x/"}
QUESTION = {"id": "q1", "source_url": "https://questions.example/1"}


def _healthy_responses() -> dict:
    politician_id = POLITICIAN["id"]
    return {
        "/health": (200, {"status": "ok"}),
        "/politicians?limit=100": (200, [POLITICIAN]),
        "/parties?limit=100": (200, [PARTY]),
        "/committees?limit=100": (200, [COMMITTEE]),
        "/documents?limit=100": (200, [DOCUMENT]),
        "/questions?limit=100": (200, [QUESTION]),
        f"/politicians/{politician_id}": (200, POLITICIAN),
        f"/politicians/{politician_id}/committees": (200, []),
        f"/politicians/{politician_id}/attendance": (
            200,
            {
                "totals": {"present": 0, "absent": 0, "apology": 0, "unknown": 0},
                "recorded_meetings": 0,
                "by_committee": [],
                "recent": [],
            },
        ),
        f"/politicians/{politician_id}/documents?limit=20": (200, []),
        f"/politicians/{politician_id}/questions?limit=20": (200, []),
        "/search?name=Person": (200, [POLITICIAN]),
        "/documents/d1": (200, DOCUMENT),
        "/questions/q1": (200, QUESTION),
        "/quality/summary": (200, {"total_politicians": 1}),
        "/quality/issues?limit=20": (200, {"politicians_without_party": []}),
    }


def _fetcher(responses: dict):
    def fetch(path: str):
        return responses.get(path, (404, None))

    return fetch


def test_all_checks_pass_against_healthy_api():
    report = run_smoke(_fetcher(_healthy_responses()))

    assert report["overall_status"] == "pass"
    assert report["summary"]["checks_fail"] == 0
    assert report["summary"]["checks_warn"] == 0
    assert report["summary"]["checks_total"] == 16


def test_empty_core_dataset_fails():
    responses = _healthy_responses()
    responses["/committees?limit=100"] = (200, [])
    report = run_smoke(_fetcher(responses))

    check = next(c for c in report["checks"] if c["name"] == "committees list")
    assert check["status"] == "fail"
    assert "empty" in check["detail"]
    assert report["overall_status"] == "fail"


def test_unreachable_api_fails_everything():
    report = run_smoke(lambda path: (0, None))

    assert report["overall_status"] == "fail"
    assert all(check["status"] == "fail" for check in report["checks"])
    assert any("transport error" in check["detail"] for check in report["checks"])


def test_missing_frontend_keys_fail():
    responses = _healthy_responses()
    responses["/politicians?limit=100"] = (200, [{"id": "x"}])
    report = run_smoke(_fetcher(responses))

    check = next(c for c in report["checks"] if c["name"] == "politicians list")
    assert check["status"] == "fail"
    assert "full_name" in check["detail"]
    detail_check = next(c for c in report["checks"] if c["name"] == "politician detail")
    assert detail_check["status"] == "fail"
    assert "Skipped" in detail_check["detail"]


def test_empty_search_results_warn_not_fail():
    responses = _healthy_responses()
    responses["/search?name=Person"] = (200, [])
    report = run_smoke(_fetcher(responses))

    check = next(c for c in report["checks"] if c["name"] == "search")
    assert check["status"] == "warn"
    assert report["overall_status"] == "warn"


def test_http_500_on_detail_fails():
    responses = _healthy_responses()
    responses["/quality/summary"] = (500, None)
    report = run_smoke(_fetcher(responses))

    check = next(c for c in report["checks"] if c["name"] == "quality summary")
    assert check["status"] == "fail"


def test_report_files_are_written_and_secret_safe(tmp_path):
    report = run_smoke(_fetcher(_healthy_responses()))
    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["overall_status"] == "pass"
    assert "# Frontend Production-Data Smoke Test" in blob
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob


def test_markdown_renders_every_check():
    report = run_smoke(_fetcher(_healthy_responses()))
    markdown = render_markdown(report)
    for check in report["checks"]:
        assert check["name"] in markdown


def test_covers_every_endpoint_the_frontend_calls():
    """Every literal API path in frontend/src/main.tsx must be exercised."""
    main_tsx = FRONTEND_MAIN.read_text(encoding="utf-8")
    exercised = set(_healthy_responses())
    frontend_paths = {
        "/politicians?limit=100" if "endpoint=\"/politicians\"" in main_tsx else None,
        "/parties?limit=100" if "endpoint=\"/parties\"" in main_tsx else None,
        "/committees?limit=100" if "endpoint=\"/committees\"" in main_tsx else None,
        "/documents?limit=100" if "endpoint=\"/documents\"" in main_tsx else None,
        "/questions?limit=100" if "endpoint=\"/questions\"" in main_tsx else None,
        "/quality/summary" if "/quality/summary" in main_tsx else None,
        "/quality/issues?limit=20" if "/quality/issues?limit=20" in main_tsx else None,
    } - {None}
    assert frontend_paths, "frontend main.tsx no longer matches the expected endpoint patterns"
    missing = frontend_paths - exercised
    assert not missing, f"smoke test does not cover frontend endpoints: {sorted(missing)}"
    for template in ("/politicians/${id}", "/politicians/${id}/committees", "/politicians/${id}/attendance", "/documents/${id}", "/questions/${id}"):
        assert template in main_tsx, f"frontend no longer calls {template}; update the smoke test"


def test_scheduled_workflow_runs_smoke_test_non_blocking():
    scheduled = SCHEDULED_WORKFLOW.read_text(encoding="utf-8")
    assert "python scripts/smoke_test_frontend_api.py --start-local-server --json-only || true" in scheduled
