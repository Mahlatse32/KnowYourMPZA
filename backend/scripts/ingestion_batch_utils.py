import json
from pathlib import Path
import re
import time
from typing import Callable


SUMMARY_KEYS = (
    "processed_count",
    "created_count",
    "updated_count",
    "skipped_count",
    "failed_count",
)
SYSTEMIC_ERROR_TYPES = {
    "DatabaseError",
    "DataError",
    "IntegrityError",
    "InterfaceError",
    "OperationalError",
    "ProgrammingError",
}
TRANSIENT_ERROR_TYPES = {
    "ConnectionError",
    "ConnectTimeout",
    "HTTPError",
    "ReadTimeout",
    "RequestException",
    "Timeout",
}
# Error types that mean a page could not be fetched *before* parsing — i.e. a
# source-access failure (block, challenge, timeout, unreachable host, empty
# body), as opposed to a parse error or a database failure.
SOURCE_ACCESS_ERROR_TYPES = TRANSIENT_ERROR_TYPES | {"EmptyResponse", "SourceAccessError"}
SOURCE_ACCESS_RECOMMENDATION = (
    "All attempted source fetches failed before parsing (systemic source-access "
    "failure). The source host most likely blocked or challenged this runner, or "
    "is unreachable from it — not a data-quality regression, and no records were "
    "fabricated. Run ingestion from a non-blocked host or network; do not "
    "repeatedly rerun CI while blocked; use a descriptive, contactable "
    "User-Agent only if the source operator approves. Keep the failure visible "
    "until source access is restored."
)
SAMPLE_SAFE_ERROR_LIMIT = 3
TRANSIENT_MESSAGE_PARTS = (
    "429",
    "500",
    "502",
    "503",
    "504",
    "connection",
    "fetch failed",
    "rate limit",
    "temporarily unavailable",
    "timeout",
    "timed out",
)


def empty_summary() -> dict:
    return {**{key: 0 for key in SUMMARY_KEYS}, "errors": []}


def run_url_batch(
    urls: list[str],
    ingest_one: Callable[[str], dict],
    *,
    sleep_seconds: float = 0.5,
    retry_attempts: int = 2,
) -> tuple[dict, bool]:
    total = empty_summary()
    systemic_failure = False

    for index, url in enumerate(urls, start=1):
        print(f"[{index}/{len(urls)}] {url}")
        part = _ingest_with_retry(url, ingest_one, retry_attempts, sleep_seconds)
        merge_summary(total, part, url)
        if any(error.get("type") in SYSTEMIC_ERROR_TYPES for error in part.get("errors", [])):
            systemic_failure = True
            break
        if sleep_seconds > 0 and index < len(urls):
            time.sleep(sleep_seconds)

    return total, systemic_failure


def merge_summary(total: dict, part: dict, url: str) -> None:
    for key in SUMMARY_KEYS:
        total[key] += int(part.get(key, 0) or 0)
    total["errors"].extend(normalize_error(error, url) for error in part.get("errors", []))


def build_result(source: str, attempted_count: int, summary: dict, systemic_failure: bool = False) -> dict:
    result = {
        "source": source,
        "attempted_count": attempted_count,
        **{key: int(summary.get(key, 0) or 0) for key in SUMMARY_KEYS},
        "errors": [normalize_error(error) for error in summary.get("errors", [])],
    }
    result["status"] = _status(result, systemic_failure)
    _annotate_source_access(result)
    return result


def _annotate_source_access(result: dict) -> None:
    """Add observability fields describing *why* a run failed.

    Distinguishes a systemic source-access failure (every attempted item failed
    to fetch before parsing) from parse/database failures, and surfaces safe,
    aggregated diagnostics. All values are derived from already-redacted errors.
    """
    errors = result.get("errors", [])
    error_types = [error.get("type", "IngestionError") for error in errors]

    top_error_types: dict[str, int] = {}
    for error_type in error_types:
        top_error_types[error_type] = top_error_types.get(error_type, 0) + 1

    failed_fetch_count = sum(1 for error_type in error_types if error_type in SOURCE_ACCESS_ERROR_TYPES)

    attempted = int(result.get("attempted_count", 0) or 0)
    processed = int(result.get("processed_count", 0) or 0)
    failed = int(result.get("failed_count", 0) or 0)
    has_database_failure = any(error_type in SYSTEMIC_ERROR_TYPES for error_type in error_types)
    # Systemic source-access failure: something was attempted, nothing was
    # processed, every failure is a fetch/access error, and none is a database
    # failure. Partial success (processed > 0) is never systemic.
    systemic_source_access_failure = bool(
        attempted > 0
        and processed == 0
        and failed >= attempted
        and bool(errors)
        and not has_database_failure
        and all(error_type in SOURCE_ACCESS_ERROR_TYPES for error_type in error_types)
    )

    result["systemic_source_access_failure"] = systemic_source_access_failure
    result["failed_fetch_count"] = failed_fetch_count
    result["top_error_types"] = top_error_types
    result["sample_safe_errors"] = errors[:SAMPLE_SAFE_ERROR_LIMIT]
    result["recommendation"] = SOURCE_ACCESS_RECOMMENDATION if systemic_source_access_failure else ""


def discovery_failure(source: str, exc: Exception) -> dict:
    return systemic_failure(source, "discovery", exc)


def systemic_failure(source: str, location: str, exc: Exception) -> dict:
    error = normalize_error(
        {"url": location, "type": exc.__class__.__name__, "error": str(exc)}
    )
    summary = empty_summary()
    summary["failed_count"] = 1
    summary["errors"].append(error)
    return build_result(source, 0, summary, systemic_failure=True)


def emit_result(result: dict, report_name: str) -> None:
    reports_dir = Path("reports")
    if reports_dir.is_dir():
        (reports_dir / report_name).write_text(
            json.dumps(result, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    print(json.dumps(result, sort_keys=True))


def should_fail(result: dict) -> bool:
    return result.get("status") == "failed"


def normalize_error(error: object, default_url: str = "unknown") -> dict:
    if isinstance(error, dict):
        url = str(error.get("url") or default_url)
        error_type = str(error.get("type") or "IngestionError")
        message = str(error.get("error") or error.get("message") or "Unknown ingestion error")
    else:
        url = default_url
        error_type = error.__class__.__name__
        message = str(error)
    return {
        "url": redact_sensitive(url),
        "type": redact_sensitive(error_type),
        "error": redact_sensitive(message),
    }


def redact_sensitive(value: str) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)\b(database_url|password|passwd|secret|token|api_key|authorization)\b"
        r"(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        text,
    )
    text = re.sub(
        r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@",
        r"\1[REDACTED]:[REDACTED]@",
        text,
    )
    text = re.sub(
        r"\b(?:gh[pousr]_[A-Za-z0-9_]{20,}|github_pat_[A-Za-z0-9_]{20,})\b",
        "[REDACTED]",
        text,
    )
    return text


def _ingest_with_retry(
    url: str,
    ingest_one: Callable[[str], dict],
    retry_attempts: int,
    sleep_seconds: float,
) -> dict:
    attempts = max(1, retry_attempts)
    for attempt in range(1, attempts + 1):
        try:
            part = ingest_one(url)
        except Exception as exc:
            part = empty_summary()
            part["failed_count"] = 1
            part["errors"].append(
                {"url": url, "type": exc.__class__.__name__, "error": str(exc)}
            )
        if attempt >= attempts or not _is_transient_failure(part):
            return part
        time.sleep(max(0.1, sleep_seconds))
    return part


def _is_transient_failure(summary: dict) -> bool:
    errors = summary.get("errors", [])
    if not errors or int(summary.get("failed_count", 0) or 0) == 0:
        return False
    for error in errors:
        normalized = normalize_error(error)
        if normalized["type"] in TRANSIENT_ERROR_TYPES:
            continue
        lowered = normalized["error"].lower()
        if not any(part in lowered for part in TRANSIENT_MESSAGE_PARTS):
            return False
    return True


def _status(result: dict, systemic_failure: bool) -> str:
    attempted = int(result.get("attempted_count", 0) or 0)
    failed = int(result.get("failed_count", 0) or 0)
    processed = int(result.get("processed_count", 0) or 0)
    mostly_failed = attempted >= 5 and failed / attempted >= 0.8
    all_failed = attempted > 0 and processed == 0 and failed >= attempted
    if systemic_failure or mostly_failed or all_failed:
        return "failed"
    if failed:
        return "partial"
    return "ok"
