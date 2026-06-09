import argparse
from pathlib import Path
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.ingestion.pmg import discover_pmg_document_urls
from app.services.ingestion_run_service import finish_ingestion_run, start_ingestion_run
from app.services.ingestion_service import ingest_pmg_documents


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/pmg_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--sleep", type=float, default=0.5)
    parser.add_argument("--discover-only", action="store_true")
    parser.add_argument("--write-discovered", action="store_true")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--committee", default=None)
    args = parser.parse_args()

    path = Path(args.file)
    existing_urls = _read_urls(path)
    discovered_urls = discover_pmg_document_urls(limit=max(args.limit or 100, 100), year=args.year, committee=args.committee)
    if args.write_discovered:
        _write_merged_urls(path, existing_urls, discovered_urls)
    urls = sorted(set(existing_urls + discovered_urls))
    if args.limit:
        urls = urls[: args.limit]
    print(f"existing_count: {len(existing_urls)}")
    print(f"newly_discovered_count: {len(set(discovered_urls) - set(existing_urls))}")
    print(f"discovered_count: {len(urls)}")
    if args.dry_run or args.discover_only:
        for url in urls:
            print(url)
        return

    total = _summary()
    with SessionLocal() as db:
        run = start_ingestion_run(db, "PMG", "bulk_pmg", len(urls))
        for index, url in enumerate(urls, start=1):
            print(f"[{index}/{len(urls)}] {url}")
            part = ingest_pmg_documents(db, [url])
            _merge(total, part)
            time.sleep(args.sleep)
        finish_ingestion_run(db, run, total)
    _print(total, len(urls))


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


def _write_merged_urls(path: Path, existing: list[str], discovered: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    merged = sorted(set(existing + discovered))
    path.write_text("\n".join(merged) + ("\n" if merged else ""), encoding="utf-8")
    print(f"wrote_url_count: {len(merged)}")


def _summary() -> dict:
    return {"processed_count": 0, "created_count": 0, "updated_count": 0, "skipped_count": 0, "failed_count": 0, "errors": []}


def _merge(total: dict, part: dict) -> None:
    for key in ["processed_count", "created_count", "updated_count", "skipped_count", "failed_count"]:
        total[key] += part.get(key, 0)
    total["errors"].extend(part.get("errors", []))


def _print(summary: dict, attempted: int) -> None:
    print(f"attempted_count: {attempted}")
    for key, value in summary.items():
        print(f"{key}: {value}")


if __name__ == "__main__":
    main()
