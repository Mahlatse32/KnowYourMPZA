import os
import json
from pathlib import Path
import subprocess
from typing import Callable

REPO_ROOT = Path(__file__).resolve().parents[1]
REPORTS_DIR = REPO_ROOT / "reports"
SOURCE_ACCESS_SUMMARIES = {
    "people_assembly": "people_assembly_ingestion_summary.json",
    "committees": "committees_ingestion_summary.json",
}


def main() -> None:
    _ensure_enabled()
    results = run_stages(build_stages())
    ok, summary = summarize(results)
    print(summary, flush=True)
    if not ok:
        # The run failed somewhere, but downstream reports were still produced.
        # Fail the job red for unclassified failures rather than hiding them.
        raise SystemExit(1)


def build_stages() -> list[tuple[str, list[str]]]:
    max_urls = os.getenv("MAX_WEEKLY_INGESTION_URLS", "100")
    sleep = os.getenv("SOURCE_RATE_LIMIT_SLEEP", "0.5")
    return [
        ("people_assembly", ["python", "scripts/ingest_all_people_assembly.py", "--limit", max_urls, "--sleep", sleep]),
        ("committees", ["python", "scripts/ingest_all_committees.py", "--limit", max_urls, "--sleep", sleep]),
        ("regenerate_aliases", ["python", "scripts/regenerate_aliases.py"]),
        ("dataset_report", ["python", "scripts/dataset_report.py"]),
    ]


def run_stages(
    stages: list[tuple[str, list[str]]],
    runner: Callable[[list[str]], int] | None = None,
) -> list[dict]:
    """Run every stage, capturing each exit code without aborting the batch.

    A failed source stage (e.g. a systemic People's Assembly source-access
    block) no longer prevents the independent downstream stages from running,
    so weekly reports are still generated. The failure is not hidden — it is
    aggregated by :func:`summarize` and turned into a red job by :func:`main`.
    """
    runner = runner or _run_subprocess
    results: list[dict] = []
    for name, command in stages:
        print(f"::group::weekly stage {name}", flush=True)
        print(" ".join(command), flush=True)
        exit_code = runner(command)
        print(f"stage {name} exit_code={exit_code}", flush=True)
        print("::endgroup::", flush=True)
        results.append({"stage": name, "exit_code": exit_code})
    return results


def summarize(results: list[dict], reports_dir: Path = REPORTS_DIR) -> tuple[bool, str]:
    """Return ``(ok, human_summary)`` for the weekly maintenance batch."""
    failed = []
    tolerated = []
    for result in results:
        if result["exit_code"] == 0:
            continue
        if _is_tolerated_source_access_failure(result["stage"], reports_dir):
            tolerated.append(result)
        else:
            failed.append(result)
    lines = ["Weekly ingestion stage summary:"]
    for r in results:
        if r in tolerated:
            status = "SOURCE-BLOCKED (non-blocking enrichment)"
        else:
            status = "ok" if r["exit_code"] == 0 else "FAILED"
        lines.append(f"  - {r['stage']}: {status} (exit {r['exit_code']})")
    if tolerated:
        names = ", ".join(r["stage"] for r in tolerated)
        lines.append(
            f"{len(tolerated)} enrichment source stage(s) were blocked systemically: {names}. "
            "The PA block remains visible in reports, but PMG-derived identity fallback is "
            "the V1 authority, so this does not fail the weekly workflow."
        )
    if failed:
        names = ", ".join(r["stage"] for r in failed)
        lines.append(
            f"{len(failed)} stage(s) failed: {names}. Weekly run marked FAILED (red). "
            "Independent downstream stages still ran. See the per-source summaries "
            "under reports/ (e.g. people_assembly_ingestion_summary.json) for the "
            "source-access classification and recommendation."
        )
    return (not failed), "\n".join(lines)


def _is_tolerated_source_access_failure(stage: str, reports_dir: Path) -> bool:
    filename = SOURCE_ACCESS_SUMMARIES.get(stage)
    if not filename:
        return False
    path = reports_dir / filename
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return False
    return payload.get("systemic_source_access_failure") is True


def _ensure_enabled() -> None:
    if os.getenv("INGESTION_ENABLED", "").lower() not in {"1", "true", "yes"}:
        raise SystemExit("INGESTION_ENABLED is not true; scheduled ingestion is disabled.")
    database_url = os.getenv("DATABASE_URL", "")
    if not database_url or "localhost" in database_url or "@db:" in database_url:
        raise SystemExit("DATABASE_URL must point at an explicit non-local production/staging database.")


def _run_subprocess(command: list[str]) -> int:
    return subprocess.run(command, cwd=REPO_ROOT).returncode


if __name__ == "__main__":
    main()
