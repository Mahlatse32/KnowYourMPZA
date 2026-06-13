#!/usr/bin/env python3
"""Source discovery for Government Gazette / Acts / Bills metadata (#25).

DISCOVERY ONLY. Lists official candidate sources for gazettes, acts, and bill
metadata and annotates each with format and parser readiness. It does NOT
ingest gazettes/acts, does NOT modify bill records, and writes nothing to the
database. No legal records are fabricated and no completeness is claimed.

Outputs:
  reports/gazette_acts_source_discovery.json
  reports/gazette_acts_source_discovery.md

Modes: live bounded fetch (default) or --offline-fixture (tests; no network).
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

# Official / government candidate sources only. None are ingested.
KNOWN_GAZETTE_ACTS_SOURCES: list[dict[str, Any]] = [
    {"url": "https://www.gov.za/documents/acts", "owner": "gov.za", "data_type": "act",
     "identifier_type": "act_number/year", "notes": "Official acts index; reconcile with bill numbers without guessing."},
    {"url": "https://www.gov.za/documents/notices", "owner": "gov.za", "data_type": "notice",
     "identifier_type": "gazette/notice number", "notes": "Gazette notices, proclamations, regulations."},
    {"url": "https://www.gov.za/documents/regulations", "owner": "gov.za", "data_type": "regulation",
     "identifier_type": "gazette/notice number", "notes": "Regulations index (candidate)."},
    {"url": "https://www.parliament.gov.za/acts", "owner": "parliament.gov.za", "data_type": "act",
     "identifier_type": "act_number/year", "notes": "Parliament-hosted act documents; define canonical-source vs duplicate rules."},
    {"url": "https://www.parliament.gov.za/bills", "owner": "parliament.gov.za", "data_type": "bill",
     "identifier_type": "bill_number/year", "notes": "Bill listing; primary machine source remains the PMG bill API."},
    {"url": "https://api.pmg.org.za/bill/", "owner": "pmg.org.za", "data_type": "bill",
     "identifier_type": "pmg bill id / code", "notes": "Already implemented for bills; included for linkage context."},
]

_EXT_FORMAT = {".csv": "csv", ".json": "json", ".pdf": "pdf", ".xlsx": "xlsx", ".xls": "xlsx", ".html": "html", ".htm": "html"}


def detect_format(url: str, content_type: str | None) -> str:
    lowered = url.split("?")[0].lower()
    for ext, fmt in _EXT_FORMAT.items():
        if lowered.endswith(ext):
            return fmt
    ct = (content_type or "").lower()
    for needle, fmt in (("csv", "csv"), ("json", "json"), ("pdf", "pdf"), ("excel", "xlsx"), ("spreadsheet", "xlsx"), ("html", "html")):
        if needle in ct:
            return fmt
    return "unknown"


def _parse_readiness(fmt: str, ok: bool) -> str:
    if not ok:
        return "unreachable"
    if fmt in ("csv", "json", "xlsx"):
        return "structured-candidate"
    if fmt in ("html", "pdf"):
        return "needs-parser-design"
    return "unknown"


def build_discovery_report(sources: list[dict], fetcher: Callable[[str], dict], *, limit: int | None = None) -> dict:
    discovered: list[dict] = []
    for source in sources[: limit or len(sources)]:
        url = source["url"]
        try:
            resp = fetcher(url)
        except Exception as exc:
            resp = {"status": None, "content_type": None, "ok": False, "error": type(exc).__name__}
        fmt = detect_format(url, resp.get("content_type"))
        ok = bool(resp.get("ok"))
        discovered.append({
            "source_url": url,
            "source_owner": source.get("owner"),
            "data_type": source.get("data_type"),
            "identifier_type": source.get("identifier_type"),
            "format": fmt,
            "reachable": ok,
            "fetch_status": resp.get("status"),
            "date_coverage": source.get("date_coverage"),
            "parse_readiness": _parse_readiness(fmt, ok),
            "risks": source.get("notes"),
            "ingested": False,
        })
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "Government Gazette / Acts / Bills metadata",
        "status": "discovery-only — no gazettes/acts ingested, no DB writes",
        "total_sources": len(discovered),
        "reachable_count": sum(1 for d in discovered if d["reachable"]),
        "sources": discovered,
        "integrity_rules": [
            "Discovery only: no gazette/act/bill records are created or fabricated.",
            "Only official government/parliament sources are listed.",
            "Bill-to-act linkage must use explicit identifiers; never inferred.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Government Gazette / Acts / Bills — Source Discovery",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Status:** {report['status']}",
        f"- **Sources listed:** {report['total_sources']} (reachable: {report['reachable_count']})",
        "",
        "| Source URL | Owner | Data type | Identifier | Format | Reachable | Parser readiness | Risks |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in report["sources"]:
        lines.append(
            f"| {s['source_url']} | {s['source_owner']} | {s['data_type']} | {s['identifier_type']} | "
            f"{s['format']} | {'yes' if s['reachable'] else 'no'} | {s['parse_readiness']} | {s['risks']} |"
        )
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "gazette_acts_source_discovery.json"
    md_path = reports_dir / "gazette_acts_source_discovery.md"
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
    sources = data.get("sources") or KNOWN_GAZETTE_ACTS_SOURCES

    def fetcher(url: str) -> dict:
        r = responses.get(url, {})
        return {"status": r.get("status"), "content_type": r.get("content_type"), "ok": bool(r.get("ok"))}

    return sources, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover official Gazette/Acts/Bills metadata sources (no ingestion).")
    parser.add_argument("--limit", type=int, default=len(KNOWN_GAZETTE_ACTS_SOURCES))
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_GAZETTE_ACTS_SOURCES, _live_fetcher(args.sleep)

    report = build_discovery_report(sources, fetcher, limit=args.limit)
    json_path, md_path = write_report(report, Path(args.reports_dir))
    logger.info("gazette/acts source discovery written: %s, %s", json_path, md_path)
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))


if __name__ == "__main__":
    main()
