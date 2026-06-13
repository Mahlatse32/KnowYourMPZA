#!/usr/bin/env python3
"""Source discovery for Chapter 9 institution reports (#27).

DISCOVERY ONLY. Lists official Chapter 9 institution report repositories and
annotates them with format and parser readiness. It does NOT extract findings
or remedial actions, does NOT ingest reports, and writes nothing to the
database. Media reports are never accepted as official findings; allegations
are never recorded as findings.

Outputs:
  reports/chapter9_source_discovery.json
  reports/chapter9_source_discovery.md

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

# Official Chapter 9 institution sources only. None are ingested.
KNOWN_CHAPTER9_SOURCES: list[dict[str, Any]] = [
    {"url": "https://www.pprotect.org/", "institution": "Public Protector", "official": True,
     "notes": "Official Public Protector site; report indexing/accessibility needs validation."},
    {"url": "https://www.sahrc.org.za/", "institution": "South African Human Rights Commission", "official": True,
     "notes": "Official SAHRC site; report taxonomy and named-entity sensitivity require review."},
    {"url": "https://www.sahrc.org.za/index.php/sahrc-publications/reports", "institution": "SAHRC", "official": True,
     "notes": "SAHRC reports index (candidate path)."},
]

# Explicitly excluded: media/news domains are NOT acceptable as official findings.
EXCLUDED_NON_OFFICIAL_HINTS = ("news24", "iol.co.za", "timeslive", "ewn.co.za", "dailymaverick", "sabc")

_EXT_FORMAT = {".csv": "csv", ".json": "json", ".pdf": "pdf", ".xlsx": "xlsx", ".html": "html", ".htm": "html"}


def is_official_candidate(url: str) -> bool:
    """Reject obvious media domains; only official institution domains qualify."""
    lowered = url.lower()
    return not any(hint in lowered for hint in EXCLUDED_NON_OFFICIAL_HINTS)


def detect_format(url: str, content_type: str | None) -> str:
    lowered = url.split("?")[0].lower()
    for ext, fmt in _EXT_FORMAT.items():
        if lowered.endswith(ext):
            return fmt
    ct = (content_type or "").lower()
    for needle, fmt in (("pdf", "pdf"), ("json", "json"), ("html", "html")):
        if needle in ct:
            return fmt
    return "unknown"


def _parse_readiness(fmt: str, ok: bool) -> str:
    if not ok:
        return "unreachable"
    if fmt == "pdf":
        return "needs-parser-design"   # findings extraction is out of scope until structured + tested
    if fmt == "html":
        return "needs-index-parser"
    return "unknown"


def build_discovery_report(sources: list[dict], fetcher: Callable[[str], dict], *, limit: int | None = None) -> dict:
    discovered: list[dict] = []
    skipped_non_official: list[str] = []
    for source in sources[: limit or len(sources)]:
        url = source["url"]
        if not is_official_candidate(url):
            skipped_non_official.append(url)
            continue
        try:
            resp = fetcher(url)
        except Exception as exc:
            resp = {"status": None, "content_type": None, "ok": False, "error": type(exc).__name__}
        fmt = detect_format(url, resp.get("content_type"))
        ok = bool(resp.get("ok"))
        discovered.append({
            "source_url": url,
            "institution": source.get("institution"),
            "official": bool(source.get("official")),
            "title": source.get("title"),
            "date": source.get("date"),
            "subject_names": source.get("subject_names"),  # only if explicitly present in metadata
            "format": fmt,
            "reachable": ok,
            "fetch_status": resp.get("status"),
            "parse_readiness": _parse_readiness(fmt, ok),
            "limitations": source.get("notes"),
            "findings_extracted": False,  # findings/remedial actions are NOT extracted
            "ingested": False,
        })
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "source": "Chapter 9 institution reports",
        "status": "discovery-only — no reports ingested, no findings extracted, no DB writes",
        "total_sources": len(discovered),
        "reachable_count": sum(1 for d in discovered if d["reachable"]),
        "skipped_non_official": skipped_non_official,
        "sources": discovered,
        "integrity_rules": [
            "Discovery only: no reports ingested and no findings/remedial actions extracted.",
            "Media/news sources are never accepted as official findings.",
            "Allegations are never recorded as findings; only official report metadata is listed.",
            "Named subjects are listed only when explicitly present in official metadata.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Chapter 9 Institution Reports — Source Discovery",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Status:** {report['status']}",
        f"- **Sources listed:** {report['total_sources']} (reachable: {report['reachable_count']})",
        f"- **Skipped non-official:** {len(report['skipped_non_official'])}",
        "",
        "| Source URL | Institution | Official | Format | Reachable | Parser readiness | Limitations |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in report["sources"]:
        lines.append(
            f"| {s['source_url']} | {s['institution']} | {'yes' if s['official'] else 'no'} | {s['format']} | "
            f"{'yes' if s['reachable'] else 'no'} | {s['parse_readiness']} | {s['limitations']} |"
        )
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "chapter9_source_discovery.json"
    md_path = reports_dir / "chapter9_source_discovery.md"
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
    sources = data.get("sources") or KNOWN_CHAPTER9_SOURCES

    def fetcher(url: str) -> dict:
        r = responses.get(url, {})
        return {"status": r.get("status"), "content_type": r.get("content_type"), "ok": bool(r.get("ok"))}

    return sources, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Discover official Chapter 9 report sources (no ingestion).")
    parser.add_argument("--limit", type=int, default=len(KNOWN_CHAPTER9_SOURCES))
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_CHAPTER9_SOURCES, _live_fetcher(args.sleep)

    report = build_discovery_report(sources, fetcher, limit=args.limit)
    json_path, md_path = write_report(report, Path(args.reports_dir))
    logger.info("chapter 9 source discovery written: %s, %s", json_path, md_path)
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))


if __name__ == "__main__":
    main()
