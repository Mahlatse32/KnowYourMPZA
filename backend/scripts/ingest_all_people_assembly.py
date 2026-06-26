import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.people_assembly import discover_people_assembly_mp_urls, normalize_people_assembly_url
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import ingest_people_assembly_profiles
from scripts.ingestion_batch_utils import (
    build_result,
    discovery_failure,
    emit_result,
    run_url_batch,
    should_fail,
    systemic_failure,
)
from scripts.identity_bootstrap_utils import run_pmg_identity_bootstrap


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/people_assembly_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--write-discovered", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    existing_urls = _read_urls(path)
    try:
        discovered_urls = discover_people_assembly_mp_urls()
    except Exception as exc:
        result = discovery_failure("people_assembly", exc)
        emit_result(result, "people_assembly_ingestion_summary.json")
        return 1
    if args.write_discovered:
        _write_merged_urls(path, existing_urls, discovered_urls)
    urls = sorted({normalize_people_assembly_url(url) for url in existing_urls + discovered_urls})
    if args.limit:
        urls = urls[: args.limit]
    print(f"existing_count: {len(existing_urls)}")
    print(f"newly_discovered_count: {len(set(discovered_urls) - set(existing_urls))}")
    print(f"discovered_count: {len(urls)}")
    if args.dry_run or args.discover_only:
        for url in urls:
            print(url)
        return 0

    try:
        with SessionLocal() as db:
            run = start_ingestion_run(db, "People's Assembly", "bulk_people_assembly", len(urls))
            total, systemic = run_url_batch(
                urls,
                lambda url: ingest_people_assembly_profiles(db, [url]),
                sleep_seconds=args.sleep,
            )
            finish_ingestion_run(db, run, total)
    except Exception as exc:
        result = systemic_failure("people_assembly", "database", exc)
        emit_result(result, "people_assembly_ingestion_summary.json")
        return 1
    result = build_result("people_assembly", len(urls), total, systemic)
    if result.get("systemic_source_access_failure"):
        try:
            with SessionLocal() as db:
                result["fallback"] = {
                    "strategy": "pmg_identity_bootstrap",
                    "summary": run_pmg_identity_bootstrap(db),
                }
                result["status"] = "fallback_completed"
        except Exception as exc:
            result["fallback"] = {
                "strategy": "pmg_identity_bootstrap",
                "status": "failed",
                "error_type": exc.__class__.__name__,
                "error": str(exc),
            }
    emit_result(result, "people_assembly_ingestion_summary.json")
    return 1 if should_fail(result) else 0


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [
        normalize_people_assembly_url(line.strip())
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.startswith("#")
    ]


def _write_merged_urls(path: Path, existing: list[str], discovered: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = sorted({normalize_people_assembly_url(url) for url in existing + discovered})
    path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    print(f"wrote_url_count: {len(merged)}")


if __name__ == "__main__":
    raise SystemExit(main())
