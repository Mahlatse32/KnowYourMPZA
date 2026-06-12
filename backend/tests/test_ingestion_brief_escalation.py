import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from escalate_ingestion_brief import ISSUE_LABELS, ISSUE_TITLE, process_brief

REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "accountability-sweep.yml"


def _write_brief(tmp_path: Path, status: str, **overrides) -> Path:
    brief = {
        "status": status,
        "reasons": ["test reason"],
        "attention_required": ["inspect the failed stage"],
        "next_actions": ["retry the retained cursor"],
        "errors": [],
        "timestamp": "2026-06-12T00:00:00+00:00",
    }
    brief.update(overrides)
    path = tmp_path / "ingestion_brief.json"
    path.write_text(json.dumps(brief), encoding="utf-8")
    return path


class FakeGitHubClient:
    def __init__(self) -> None:
        self.calls = []

    def upsert_issue(self, repo, title, body, labels):
        self.calls.append({"repo": repo, "title": title, "body": body, "labels": labels})
        return {"result": "updated_issue", "issue_url": "https://github.example/issues/1"}


def test_green_brief_does_nothing(tmp_path):
    result, code = process_brief(_write_brief(tmp_path, "green"), "owner/repo", False)
    assert code == 0
    assert result == {"result": "no_escalation", "status": "green"}


def test_yellow_brief_does_nothing(tmp_path):
    result, code = process_brief(_write_brief(tmp_path, "yellow"), "owner/repo", False)
    assert code == 0
    assert result == {"result": "no_escalation", "status": "yellow"}


def test_red_brief_dry_run_reports_planned_issue(tmp_path):
    result, code = process_brief(_write_brief(tmp_path, "red"), "owner/repo", True)
    assert code == 0
    assert result["result"] == "planned_issue"
    assert result["issue"]["title"] == ISSUE_TITLE
    assert result["issue"]["labels"] == ISSUE_LABELS
    assert "retry the retained cursor" in result["issue"]["body"]


def test_red_brief_real_mode_uses_fake_github_client(tmp_path):
    client = FakeGitHubClient()
    result, code = process_brief(_write_brief(tmp_path, "red"), "owner/repo", False, client)
    assert code == 0
    assert result["result"] == "updated_issue"
    assert client.calls == [
        {
            "repo": "owner/repo",
            "title": ISSUE_TITLE,
            "body": client.calls[0]["body"],
            "labels": ISSUE_LABELS,
        }
    ]


def test_missing_brief_handled_cleanly(tmp_path):
    result, code = process_brief(tmp_path / "missing.json", "owner/repo", True)
    assert code == 2
    assert result["result"] == "error"
    assert "brief not found" in result["error"]


def test_malformed_json_handled_cleanly(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("{bad json", encoding="utf-8")
    result, code = process_brief(path, "owner/repo", True)
    assert code == 2
    assert result["result"] == "error"
    assert "could not read brief" in result["error"]


def test_credentials_are_redacted(tmp_path):
    path = _write_brief(
        tmp_path,
        "red",
        reasons=[
            "DATABASE_URL=postgresql://admin:supersecret@db.example/app",
            "token=ghp_abcdefghijklmnopqrstuvwxyz123456",
        ],
        errors=[{"error": "password=hunter2 api_key=private-value"}],
    )
    result, code = process_brief(path, "owner/repo", True)
    blob = json.dumps(result)
    assert code == 0
    for secret in ("supersecret", "hunter2", "private-value", "ghp_"):
        assert secret not in blob
    assert "[REDACTED]" in blob


def test_workflow_contains_issue_write_permission():
    assert "issues: write" in WORKFLOW.read_text(encoding="utf-8")


def test_workflow_calls_escalation_script():
    assert "escalate_ingestion_brief.py" in WORKFLOW.read_text(encoding="utf-8")
