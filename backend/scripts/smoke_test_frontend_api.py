#!/usr/bin/env python3
"""Frontend production-data smoke test.

Exercises every API endpoint the frontend (frontend/src/main.tsx) calls,
against any --api-base-url, and verifies both reachability and that the
core public datasets are non-empty with the fields the frontend renders.

Two ways to run it:

- Against an already-running API (a deployed backend or local uvicorn):
    python scripts/smoke_test_frontend_api.py --api-base-url https://api.example
- Self-contained against the configured DATABASE_URL (used by the
  scheduled ingestion workflow, where DATABASE_URL is the production
  database): --start-local-server starts uvicorn on a local port, waits
  for /health, runs the checks read-only, and shuts the server down.

Writes reports/frontend_smoke_report.json and .md. Exits 0 when every
check passes (warn allowed), 1 otherwise.
"""

import argparse
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PASS = "pass"
WARN = "warn"
FAIL = "fail"

# List endpoints the frontend renders, with the fields its cards read from
# the first item. Every dataset here is non-zero in production, so an empty
# list is a launch-facing regression, not an acceptable state.
LIST_ENDPOINTS = (
    ("/politicians?limit=100", "politicians list", ("id", "full_name", "display_name", "slug")),
    ("/parties?limit=100", "parties list", ("id", "name", "short_name")),
    ("/committees?limit=100", "committees list", ("id", "name")),
    ("/documents?limit=100", "documents list", ("id", "title", "document_type", "source_url")),
    ("/questions?limit=100", "questions list", ("id", "source_url")),
)


def run_smoke(fetch) -> dict:
    """Run all frontend smoke checks through fetch(path) -> (status, payload).

    fetch returns the HTTP status code and the parsed JSON payload (None
    when the body is not JSON or the request failed at transport level,
    signalled by status 0).
    """
    checks: list[dict] = []

    def add(name: str, status: str, detail: str) -> None:
        checks.append({"name": name, "status": status, "detail": detail})

    status, payload = fetch("/health")
    add(
        "health endpoint",
        PASS if status == 200 else FAIL,
        f"GET /health returned {status or 'transport error'}.",
    )

    first_items: dict[str, dict] = {}
    for path, name, required_keys in LIST_ENDPOINTS:
        status, payload = fetch(path)
        if status != 200 or not isinstance(payload, list):
            add(name, FAIL, f"GET {path} returned {status or 'transport error'}; expected a JSON list.")
            continue
        if not payload:
            add(name, FAIL, f"GET {path} returned an empty list; production data should be non-empty.")
            continue
        first = payload[0]
        missing = [key for key in required_keys if key not in first]
        if missing:
            add(name, FAIL, f"GET {path}: first item is missing frontend-rendered keys: {', '.join(missing)}.")
        else:
            add(name, PASS, f"GET {path}: {len(payload)} records; frontend-rendered keys present.")
            first_items[name] = first

    politician = first_items.get("politicians list")
    if politician:
        politician_id = politician["id"]
        for path, name in (
            (f"/politicians/{politician_id}", "politician detail"),
            (f"/politicians/{politician_id}/committees", "politician committees"),
            (f"/politicians/{politician_id}/documents?limit=20", "politician documents"),
            (f"/politicians/{politician_id}/questions?limit=20", "politician questions"),
        ):
            status, payload = fetch(path)
            add(
                name,
                PASS if status == 200 else FAIL,
                f"GET {path} returned {status or 'transport error'}.",
            )

        name_tokens = str(politician.get("display_name") or politician.get("full_name") or "").split()
        search_term = name_tokens[-1] if name_tokens else "a"
        status, payload = fetch(f"/search?name={search_term}")
        if status != 200 or not isinstance(payload, list):
            add("search", FAIL, f"GET /search?name={search_term} returned {status or 'transport error'}.")
        elif not payload:
            add("search", WARN, f"GET /search?name={search_term} returned 200 but no results for a known MP name.")
        else:
            add("search", PASS, f"GET /search?name={search_term} returned {len(payload)} result(s).")
    else:
        add("politician detail", FAIL, "Skipped: no politician available from the list endpoint.")
        add("search", FAIL, "Skipped: no politician available to search for.")

    for source, path_template, name in (
        ("documents list", "/documents/{id}", "document detail"),
        ("questions list", "/questions/{id}", "question detail"),
    ):
        item = first_items.get(source)
        if not item:
            add(name, FAIL, f"Skipped: no record available from {source}.")
            continue
        path = path_template.format(id=item["id"])
        status, payload = fetch(path)
        add(name, PASS if status == 200 else FAIL, f"GET {path} returned {status or 'transport error'}.")

    for path, name in (("/quality/summary", "quality summary"), ("/quality/issues?limit=20", "quality issues")):
        status, payload = fetch(path)
        add(
            name,
            PASS if status == 200 and isinstance(payload, dict) else FAIL,
            f"GET {path} returned {status or 'transport error'}.",
        )

    statuses = [check["status"] for check in checks]
    overall = FAIL if FAIL in statuses else (WARN if WARN in statuses else PASS)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "overall_status": overall,
        "summary": {
            "checks_total": len(checks),
            "checks_pass": statuses.count(PASS),
            "checks_warn": statuses.count(WARN),
            "checks_fail": statuses.count(FAIL),
        },
        "checks": checks,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Frontend Production-Data Smoke Test",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Overall status:** {report['overall_status']}",
        f"- **Pass / warn / fail:** {report['summary']['checks_pass']} / "
        f"{report['summary']['checks_warn']} / {report['summary']['checks_fail']}",
        "",
        "| Status | Check | Detail |",
        "|---|---|---|",
    ]
    for check in report["checks"]:
        lines.append(f"| {check['status'].upper()} | {check['name']} | {check['detail']} |")
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "frontend_smoke_report.json"
    markdown_path = directory / "frontend_smoke_report.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def make_requests_fetcher(base_url: str, timeout: float = 30.0):
    import requests

    base = base_url.rstrip("/")

    def fetch(path: str) -> tuple[int, object]:
        try:
            response = requests.get(f"{base}{path}", timeout=timeout)
        except requests.RequestException:
            return 0, None
        try:
            return response.status_code, response.json()
        except ValueError:
            return response.status_code, None

    return fetch


def wait_for_health(fetch, attempts: int = 60, sleep_seconds: float = 1.0) -> bool:
    for _ in range(attempts):
        status, _ = fetch("/health")
        if status == 200:
            return True
        time.sleep(sleep_seconds)
    return False


def main() -> int:
    parser = argparse.ArgumentParser(description="Smoke test the API surface the frontend depends on.")
    parser.add_argument("--api-base-url", default="http://127.0.0.1:8000")
    parser.add_argument(
        "--start-local-server",
        action="store_true",
        help="Start uvicorn against the configured DATABASE_URL, run the checks, then stop it.",
    )
    parser.add_argument("--port", type=int, default=8000, help="Port for --start-local-server.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    server = None
    base_url = args.api_base_url
    if args.start_local_server:
        base_url = f"http://127.0.0.1:{args.port}"
        server = subprocess.Popen(
            [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(args.port)],
            cwd=str(Path(__file__).resolve().parents[1]),
        )

    fetch = make_requests_fetcher(base_url)
    try:
        if server is not None and not wait_for_health(fetch):
            report = {
                "generated_at": datetime.now(UTC).isoformat(),
                "overall_status": FAIL,
                "summary": {"checks_total": 1, "checks_pass": 0, "checks_warn": 0, "checks_fail": 1},
                "checks": [
                    {
                        "name": "local server startup",
                        "status": FAIL,
                        "detail": "uvicorn did not become healthy within 60 seconds.",
                    }
                ],
            }
        else:
            report = run_smoke(fetch)
    finally:
        if server is not None:
            server.terminate()
            try:
                server.wait(timeout=15)
            except subprocess.TimeoutExpired:
                server.kill()

    json_path, markdown_path = write_report(report, args.reports_dir)
    if args.json_only:
        print(
            json.dumps(
                {
                    "overall_status": report["overall_status"],
                    "json_report": str(json_path),
                    "markdown_report": str(markdown_path),
                },
                sort_keys=True,
            )
        )
    else:
        print(render_markdown(report))
    return 0 if report["overall_status"] in {PASS, WARN} else 1


if __name__ == "__main__":
    raise SystemExit(main())
