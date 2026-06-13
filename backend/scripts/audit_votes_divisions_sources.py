#!/usr/bin/env python3
"""Audit parliamentary vote / division source availability (#7).

AUDIT ONLY. Inventories known and candidate vote/division sources and their
data granularity (party-level / MP-level / house-level / unknown) and parser
readiness. It does NOT create vote events or vote records and writes nothing
to the database. No votes are fabricated.

Context: vote ingestion today comes only from explicit vote/division language
in PMG committee-meeting minutes (`scripts/ingest_votes.py`), producing vote
events and — only when explicit counts exist — aggregate vote records. There
is no dedicated public vote/division API. This audit records what official
sources could improve granularity (e.g. MP-level division lists) before any
expansion.

Outputs:
  reports/votes_divisions_source_audit.json
  reports/votes_divisions_source_audit.md

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

# Known + candidate vote/division sources. granularity is what the source can
# *at best* provide; "implemented" marks what already has ingestion code.
KNOWN_VOTE_SOURCES: list[dict[str, Any]] = [
    {"url": "https://api.pmg.org.za/committee-meeting/", "owner": "PMG", "chamber": "committees",
     "vote_type": "committee_decision", "granularity": "house-level/party-level",
     "implemented": True,
     "notes": "Current source: explicit vote/division language in minutes; outcome-only events may have no records."},
    {"url": "https://www.parliament.gov.za/minutes-proceedings", "owner": "Parliament", "chamber": "NA/NCOP",
     "vote_type": "division", "granularity": "unknown",
     "implemented": False,
     "notes": "Candidate: formal minutes may record divisions; format/granularity unvalidated."},
    {"url": "https://www.parliament.gov.za/hansard", "owner": "Parliament", "chamber": "NA/NCOP",
     "vote_type": "division", "granularity": "unknown",
     "implemented": False,
     "notes": "Candidate: Hansard may narrate divisions; PDF parsing + attribution risk high."},
    {"url": "https://pmg.org.za/plenary/", "owner": "PMG", "chamber": "NA/NCOP",
     "vote_type": "plenary_vote", "granularity": "unknown",
     "implemented": False,
     "notes": "Candidate: PMG plenary coverage; verify whether MP-level division lists are exposed."},
]

_EXT_FORMAT = {".csv": "csv", ".json": "json", ".pdf": "pdf", ".xlsx": "xlsx", ".html": "html", ".htm": "html"}
VALID_GRANULARITIES = {"party-level", "MP-level", "house-level", "unknown"}


def detect_format(url: str, content_type: str | None) -> str:
    lowered = url.split("?")[0].lower()
    for ext, fmt in _EXT_FORMAT.items():
        if lowered.endswith(ext):
            return fmt
    ct = (content_type or "").lower()
    for needle, fmt in (("json", "json"), ("pdf", "pdf"), ("html", "html")):
        if needle in ct:
            return fmt
    return "unknown"


def _parse_readiness(implemented: bool, fmt: str, ok: bool) -> str:
    if implemented:
        return "implemented-limited"
    if not ok:
        return "unreachable"
    if fmt in ("json", "csv", "xlsx"):
        return "structured-candidate"
    return "needs-parser-design"


def build_audit_report(sources: list[dict], fetcher: Callable[[str], dict], *, limit: int | None = None) -> dict:
    audited: list[dict] = []
    for source in sources[: limit or len(sources)]:
        url = source["url"]
        try:
            resp = fetcher(url)
        except Exception as exc:
            resp = {"status": None, "content_type": None, "ok": False, "error": type(exc).__name__}
        fmt = detect_format(url, resp.get("content_type"))
        ok = bool(resp.get("ok"))
        implemented = bool(source.get("implemented"))
        audited.append({
            "source_url": url,
            "source_owner": source.get("owner"),
            "chamber": source.get("chamber"),
            "vote_type": source.get("vote_type"),
            "data_granularity": source.get("granularity"),
            "format": fmt,
            "reachable": ok,
            "fetch_status": resp.get("status"),
            "implemented": implemented,
            "parse_readiness": _parse_readiness(implemented, fmt, ok),
            "limitations": source.get("notes"),
            "creates_vote_records": False,  # the audit never creates votes
        })
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "Parliamentary votes / divisions",
        "status": "audit-only — no vote events or records created, no DB writes",
        "total_sources": len(audited),
        "implemented_count": sum(1 for a in audited if a["implemented"]),
        "mp_level_available": any(a["data_granularity"] == "MP-level" for a in audited),
        "sources": audited,
        "integrity_rules": [
            "Audit only: no vote events or vote records are created or fabricated.",
            "Vote records require explicit source data; individual MP votes are never inferred from party position.",
            "Outcome-only divisions produce a vote event with no records.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Parliamentary Votes / Divisions — Source Audit",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Status:** {report['status']}",
        f"- **Sources audited:** {report['total_sources']} (implemented: {report['implemented_count']})",
        f"- **MP-level division data available:** {'yes' if report['mp_level_available'] else 'no'}",
        "",
        "| Source URL | Owner | Chamber | Vote type | Granularity | Format | Reachable | Parser readiness | Limitations |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for s in report["sources"]:
        lines.append(
            f"| {s['source_url']} | {s['source_owner']} | {s['chamber']} | {s['vote_type']} | "
            f"{s['data_granularity']} | {s['format']} | {'yes' if s['reachable'] else 'no'} | "
            f"{s['parse_readiness']} | {s['limitations']} |"
        )
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "votes_divisions_source_audit.json"
    md_path = reports_dir / "votes_divisions_source_audit.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _live_fetcher(sleep: float) -> Callable[[str], dict]:
    import requests

    def fetcher(url: str) -> dict:
        time.sleep(sleep)
        resp = requests.get(url, timeout=20, headers={"User-Agent": "KnowYourMPZA-source-audit/1.0"}, stream=True)
        ct = resp.headers.get("Content-Type")
        resp.close()
        return {"status": resp.status_code, "content_type": ct, "ok": 200 <= resp.status_code < 400}

    return fetcher


def _fixture_fetcher(fixture_path: Path) -> tuple[list[dict], Callable[[str], dict]]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    responses = {r["url"]: r for r in data.get("responses", [])}
    sources = data.get("sources") or KNOWN_VOTE_SOURCES

    def fetcher(url: str) -> dict:
        r = responses.get(url, {})
        return {"status": r.get("status"), "content_type": r.get("content_type"), "ok": bool(r.get("ok"))}

    return sources, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Audit vote/division sources (no ingestion).")
    parser.add_argument("--limit", type=int, default=len(KNOWN_VOTE_SOURCES))
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_VOTE_SOURCES, _live_fetcher(args.sleep)

    report = build_audit_report(sources, fetcher, limit=args.limit)
    json_path, md_path = write_report(report, Path(args.reports_dir))
    logger.info("votes/divisions source audit written: %s, %s", json_path, md_path)
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))


if __name__ == "__main__":
    main()
