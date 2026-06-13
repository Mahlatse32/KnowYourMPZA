import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.people_assembly import discover_people_assembly_committee_urls, normalize_people_assembly_url
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import ingest_people_assembly_committees
from scripts.ingestion_batch_utils import (
    build_result,
    discovery_failure,
    emit_result,
    run_url_batch,
    should_fail,
    systemic_failure,
)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/committee_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--write-discovered", action="store_true")
    args = parser.parse_args()

    path = Path(args.file)
    existing_urls = _read_urls(path)
    try:
        discovered_urls = discover_people_assembly_committee_urls()
    except Exception as exc:
        result = discovery_failure("committees", exc)
        emit_result(result, "committees_ingestion_summary.json")
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
            run = start_ingestion_run(db, "People's Assembly", "bulk_committees", len(urls))
            total, systemic = run_url_batch(
                urls,
                lambda url: ingest_people_assembly_committees(db, [url]),
                sleep_seconds=args.sleep,
            )
            finish_ingestion_run(db, run, total)
    except Exception as exc:
        result = systemic_failure("committees", "database", exc)
        emit_result(result, "committees_ingestion_summary.json")
        return 1
    result = build_result("committees", len(urls), total, systemic)
    emit_result(result, "committees_ingestion_summary.json")
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
