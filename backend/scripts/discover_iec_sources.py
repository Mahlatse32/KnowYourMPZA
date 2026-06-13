#!/usr/bin/env python3
"""Source discovery for IEC (Electoral Commission of South Africa) results (#24).

FOUNDATION ONLY. This script discovers and annotates official IEC result
sources — it does NOT ingest any election results and writes nothing to the
database. No election records are fabricated. A schema/parser is deliberately
deferred until the source structure is validated and a parser is well tested
(see backend/docs/source-inventory.md).

Only official IEC sources are listed (results.elections.org.za and the IEC
open-data/downloads area). Each entry is annotated with fetch status, detected
format, and parser-readiness so a future ingestion PR can start from evidence.

Outputs:
  reports/iec_source_discovery.json
  reports/iec_source_discovery.md

Modes:
  live (default)        bounded, polite HEAD/GET of each candidate (--limit, --sleep)
  --offline-fixture P   read a JSON fixture of pre-fetched responses; no network
                        (used by tests; never hits the IEC servers)
"""
import argparse
import json
import logging
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Curated official IEC candidate sources. Status is "candidate" — NONE are
# ingested yet. URLs are official IEC properties only.
KNOWN_IEC_SOURCES: list[dict[str, Any]] = [
    {
        "url": "https://results.elections.org.za/home/",
        "election_type": "all",
        "year": None,
        "geography_level": "national/provincial/municipal",
        "notes": "Official IEC results portal landing page (JS-rendered dashboard).",
    },
    {
        "url": "https://www.elections.org.za/pw/Downloads",
        "election_type": "all",
        "year": None,
        "geography_level": "various",
        "notes": "Official IEC downloads area — candidate for CSV/XLSX result exports.",
    },
    {
        "url": "https://results.elections.org.za/dashboards/npe/",
        "election_type": "national",
        "year": None,
        "geography_level": "national",
        "notes": "National & Provincial Elections dashboard (candidate).",
    },
    {
        "url": "https://results.elections.org.za/dashboards/lge/",
        "election_type": "municipal",
        "year": None,
        "geography_level": "municipal/ward",
        "notes": "Local Government Elections dashboard (candidate).",
    },
]

_EXT_FORMAT = {
    ".csv": "csv",
    ".json": "json",
    ".pdf": "pdf",
    ".xlsx": "xlsx",
    ".xls": "xlsx",
    ".html": "html",
    ".htm": "html",
}


def detect_format(url: str, content_type: str | None) -> str:
    lowered = url.split("?")[0].lower()
    for ext, fmt in _EXT_FORMAT.items():
        if lowered.endswith(ext):
            return fmt
    ct = (content_type or "").lower()
    if "csv" in ct:
        return "csv"
    if "json" in ct:
        return "json"
    if "pdf" in ct:
        return "pdf"
    if "spreadsheet" in ct or "excel" in ct:
        return "xlsx"
    if "html" in ct:
        return "html"
    return "unknown"


def _parse_readiness(fmt: str, ok: bool) -> str:
    if not ok:
        return "unreachable"
    if fmt in ("csv", "json", "xlsx"):
        return "structured-candidate"   # parseable once columns are mapped + tested
    if fmt in ("html", "pdf"):
        return "needs-parser-design"     # JS/PDF — design required before ingestion
    return "unknown"


def build_discovery_report(
    sources: list[dict],
    fetcher: Callable[[str], dict],
    *,
    limit: int | None = None,
) -> dict:
    """Annotate candidate sources with fetch status + format. Never touches a DB."""
    discovered: list[dict] = []
    for source in sources[: limit or len(sources)]:
        url = source["url"]
        try:
            resp = fetcher(url)
        except Exception as exc:  # network errors must not abort discovery
            resp = {"status": None, "content_type": None, "ok": False, "error": type(exc).__name__}
        fmt = detect_format(url, resp.get("content_type"))
        ok = bool(resp.get("ok"))
        discovered.append(
            {
                "source_url": url,
                "election_type": source.get("election_type"),
                "year": source.get("year"),
                "geography_level": source.get("geography_level"),
                "format": fmt,
                "fetch_status": resp.get("status"),
                "reachable": ok,
                "parse_readiness": _parse_readiness(fmt, ok),
                "notes": source.get("notes"),
                "ingested": False,  # nothing is ingested in the discovery foundation
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "IEC (Electoral Commission of South Africa)",
        "status": "discovery-only — no election results ingested, no DB writes",
        "total_sources": len(discovered),
        "reachable_count": sum(1 for d in discovered if d["reachable"]),
        "sources": discovered,
        "integrity_rules": [
            "Discovery only: no election records are created or fabricated.",
            "Only official IEC sources are listed.",
            "Schema/parser deferred until source structure is validated and tested.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# IEC Election Results — Source Discovery",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Status:** {report['status']}",
        f"- **Sources listed:** {report['total_sources']} (reachable: {report['reachable_count']})",
        "",
        "| Source URL | Election type | Geography | Format | Reachable | Parser readiness | Notes |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in report["sources"]:
        lines.append(
            f"| {s['source_url']} | {s['election_type']} | {s['geography_level']} | {s['format']} | "
            f"{'yes' if s['reachable'] else 'no'} | {s['parse_readiness']} | {s['notes']} |"
        )
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "iec_source_discovery.json"
    md_path = reports_dir / "iec_source_discovery.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _live_fetcher(sleep: float) -> Callable[[str], dict]:
    import requests

    def fetcher(url: str) -> dict:
        time.sleep(sleep)
        resp = requests.get(url, timeout=20, headers={"User-Agent": "KnowYourMPZA-source-discovery/1.0"}, stream=True)
        ct = resp.headers.get("Content-Type")
        resp.close()
        return {"status": resp.status_code, "content_type": ct, "ok": 200 <= resp.status_code < 400}

    return fetcher


def _fixture_fetcher(fixture_path: Path) -> tuple[list[dict], Callable[[str], dict]]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    responses = {r["url"]: r for r in data.get("responses", [])}
    sources = data.get("sources") or KNOWN_IEC_SOURCES

    def fetcher(url: str) -> dict:
        r = responses.get(url, {})
        return {"status": r.get("status"), "content_type": r.get("content_type"), "ok": bool(r.get("ok"))}

    return sources, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover official IEC result sources (no ingestion).")
    parser.add_argument("--limit", type=int, default=len(KNOWN_IEC_SOURCES))
    parser.add_argument("--sleep", type=float, default=1.0, help="Polite delay between live requests.")
    parser.add_argument("--offline-fixture", default=None, help="JSON fixture of responses (no network).")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_IEC_SOURCES, _live_fetcher(args.sleep)

    report = build_discovery_report(sources, fetcher, limit=args.limit)
    json_path, md_path = write_report(report, Path(args.reports_dir))
    logger.info("IEC source discovery written: %s, %s", json_path, md_path)
    if args.json_only:
        print(json.dumps(report, default=str))
    else:
        print(render_markdown(report))


if __name__ == "__main__":
    main()
