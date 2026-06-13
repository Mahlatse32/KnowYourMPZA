#!/usr/bin/env python3
"""Source discovery for municipal councils and office-bearers (#26).

DISCOVERY ONLY. Lists official/candidate local-government sources and annotates
them with format and parser readiness. It does NOT ingest councils, councillors,
mayors, or party composition, and writes nothing to the database. No
office-bearers are fabricated; election winners are never treated as seated
office-holders without official confirmation.

Outputs:
  reports/municipal_source_discovery.json
  reports/municipal_source_discovery.md

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

# Official/candidate municipal sources. None are ingested or trusted until
# validated. Individual municipal sites are candidates, not trusted sources.
KNOWN_MUNICIPAL_SOURCES: list[dict[str, Any]] = [
    {"url": "https://municipaldata.treasury.gov.za/", "owner": "National Treasury", "province": None,
     "data_type": "budget,performance,audit", "trust": "official",
     "notes": "Municipal Money — finance/audit data; municipality codes + revised releases need care."},
    {"url": "https://municipaldata.treasury.gov.za/api", "owner": "National Treasury", "province": None,
     "data_type": "budget,performance,audit", "trust": "official",
     "notes": "Municipal Money API endpoint (candidate for structured ingestion)."},
    {"url": "https://results.elections.org.za/dashboards/lge/", "owner": "IEC", "province": None,
     "data_type": "ward,party_composition", "trust": "official",
     "notes": "IEC LGE results — ward/party-composition evidence; winners are not seated office-bearers."},
    {"url": "https://www.cogta.gov.za/", "owner": "COGTA", "province": None,
     "data_type": "council,office_bearer", "trust": "official-candidate",
     "notes": "Cooperative Governance dept — candidate for council/office-bearer context; structure unvalidated."},
    {"url": "https://www.salga.org.za/", "owner": "SALGA", "province": None,
     "data_type": "council,office_bearer", "trust": "candidate",
     "notes": "SA Local Government Association — candidate only; not a primary official register."},
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
            "province": source.get("province"),
            "municipality": source.get("municipality"),
            "data_type": source.get("data_type"),
            "trust": source.get("trust"),
            "format": fmt,
            "reachable": ok,
            "fetch_status": resp.get("status"),
            "update_frequency": source.get("update_frequency"),
            "parse_readiness": _parse_readiness(fmt, ok),
            "risk": source.get("notes"),
            "ingested": False,
        })
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "Municipal councils and office-bearers",
        "status": "discovery-only — no councils/office-bearers ingested, no DB writes",
        "total_sources": len(discovered),
        "reachable_count": sum(1 for d in discovered if d["reachable"]),
        "sources": discovered,
        "integrity_rules": [
            "Discovery only: no councils, councillors, or office-bearers are created or fabricated.",
            "Election winners are never recorded as seated office-bearers without official confirmation.",
            "Individual municipal websites are candidates, not trusted until validated.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Municipal Councils & Office-Bearers — Source Discovery",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Status:** {report['status']}",
        f"- **Sources listed:** {report['total_sources']} (reachable: {report['reachable_count']})",
        "",
        "| Source URL | Owner | Data type | Trust | Format | Reachable | Parser readiness | Risk |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for s in report["sources"]:
        lines.append(
            f"| {s['source_url']} | {s['source_owner']} | {s['data_type']} | {s['trust']} | {s['format']} | "
            f"{'yes' if s['reachable'] else 'no'} | {s['parse_readiness']} | {s['risk']} |"
        )
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "municipal_source_discovery.json"
    md_path = reports_dir / "municipal_source_discovery.md"
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
    sources = data.get("sources") or KNOWN_MUNICIPAL_SOURCES

    def fetcher(url: str) -> dict:
        r = responses.get(url, {})
        return {"status": r.get("status"), "content_type": r.get("content_type"), "ok": bool(r.get("ok"))}

    return sources, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover candidate municipal sources (no ingestion).")
    parser.add_argument("--limit", type=int, default=len(KNOWN_MUNICIPAL_SOURCES))
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_MUNICIPAL_SOURCES, _live_fetcher(args.sleep)

    report = build_discovery_report(sources, fetcher, limit=args.limit)
    json_path, md_path = write_report(report, Path(args.reports_dir))
    logger.info("municipal source discovery written: %s, %s", json_path, md_path)
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))


if __name__ == "__main__":
    main()
