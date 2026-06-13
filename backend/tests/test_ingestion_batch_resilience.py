import json

from scripts.ingestion_batch_utils import (
    build_result,
    emit_result,
    empty_summary,
    run_url_batch,
    should_fail,
)


def _success() -> dict:
    summary = empty_summary()
    summary["processed_count"] = 1
    summary["created_count"] = 1
    return summary


def _failure(url: str, error_type: str = "ValueError", message: str = "Could not parse source") -> dict:
    summary = empty_summary()
    summary["failed_count"] = 1
    summary["errors"].append({"url": url, "type": error_type, "error": message})
    return summary


def test_single_source_failure_does_not_abort_batch():
    visited = []

    def ingest(url: str) -> dict:
        visited.append(url)
        return _failure(url) if url.endswith("/bad") else _success()

    urls = ["https://example.test/one", "https://example.test/bad", "https://example.test/two"]
    summary, systemic = run_url_batch(urls, ingest, sleep_seconds=0, retry_attempts=1)
    result = build_result("test", len(urls), summary, systemic)

    assert visited == urls
    assert result["processed_count"] == 2
    assert result["failed_count"] == 1
    assert result["status"] == "partial"
    assert result["errors"] == [
        {
            "url": "https://example.test/bad",
            "type": "ValueError",
            "error": "Could not parse source",
        }
    ]
    assert not should_fail(result)


def test_transient_source_failure_is_retried_once(monkeypatch):
    monkeypatch.setattr("scripts.ingestion_batch_utils.time.sleep", lambda _: None)
    attempts = 0

    def ingest(url: str) -> dict:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            return _failure(url, "ReadTimeout", "Source request timed out")
        return _success()

    summary, systemic = run_url_batch(
        ["https://example.test/retry"],
        ingest,
        sleep_seconds=0,
        retry_attempts=2,
    )
    result = build_result("test", 1, summary, systemic)

    assert attempts == 2
    assert result["status"] == "ok"
    assert result["processed_count"] == 1
    assert result["failed_count"] == 0


def test_systemic_database_failure_stops_and_fails_batch():
    visited = []

    def ingest(url: str) -> dict:
        visited.append(url)
        return _failure(url, "OperationalError", "database is unavailable")

    urls = ["https://example.test/one", "https://example.test/two"]
    summary, systemic = run_url_batch(urls, ingest, sleep_seconds=0, retry_attempts=1)
    result = build_result("test", len(urls), summary, systemic)

    assert visited == [urls[0]]
    assert result["status"] == "failed"
    assert should_fail(result)


def test_all_source_urls_failing_marks_run_failed():
    urls = [f"https://example.test/{index}" for index in range(3)]
    summary, systemic = run_url_batch(
        urls,
        lambda url: _failure(url),
        sleep_seconds=0,
        retry_attempts=1,
    )
    result = build_result("test", len(urls), summary, systemic)

    assert result["failed_count"] == len(urls)
    assert result["status"] == "failed"
    assert should_fail(result)


def test_machine_readable_summary_is_printed_and_written(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    result = build_result("test", 1, _success())

    emit_result(result, "test_ingestion_summary.json")

    stdout_result = json.loads(capsys.readouterr().out.strip().splitlines()[-1])
    file_result = json.loads((reports / "test_ingestion_summary.json").read_text(encoding="utf-8"))
    assert stdout_result == result
    assert file_result == result


def test_summary_redacts_database_urls_and_tokens(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)
    reports = tmp_path / "reports"
    reports.mkdir()
    secret_url = "postgresql://admin:super-secret@example.test/app"
    secret_token = "ghp_abcdefghijklmnopqrstuvwxyz123456"
    summary = _failure(
        "https://example.test/bad",
        message=f"DATABASE_URL={secret_url} token={secret_token}",
    )
    result = build_result("test", 1, summary)

    emit_result(result, "redacted.json")

    output = capsys.readouterr().out
    report = (reports / "redacted.json").read_text(encoding="utf-8")
    for text in (output, report):
        assert "super-secret" not in text
        assert secret_token not in text
        assert "DATABASE_URL=[REDACTED]" in text
