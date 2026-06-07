import argparse
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.ingestion.parliament_question_discovery import discover_parliamentary_question_urls


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--file", default="data/parliamentary_question_urls.txt")
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--year", type=int, default=None)
    args = parser.parse_args()

    path = Path(args.file)
    existing = _read_urls(path)
    discovered = discover_parliamentary_question_urls(limit=args.limit, year=args.year)
    urls = sorted(set(existing + discovered))
    print(f"existing_count: {len(existing)}")
    print(f"discovered_count: {len(discovered)}")
    print(f"total_count: {len(urls)}")
    if args.dry_run:
        for url in urls:
            print(url)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("\n".join(urls) + ("\n" if urls else ""), encoding="utf-8")
    print(f"wrote: {path}")


def _read_urls(path: Path) -> list[str]:
    if not path.exists():
        return []
    return [line.strip() for line in path.read_text(encoding="utf-8").splitlines() if line.strip() and not line.startswith("#")]


if __name__ == "__main__":
    main()
