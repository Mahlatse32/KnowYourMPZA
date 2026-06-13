#!/usr/bin/env python3
"""Ingest IEC election METADATA and SOURCE MANIFESTS only (#24).

This is the first real IEC ingestion step. It stores:
  - iec_elections        official election/event metadata (type/year/name when
                         explicitly labelled by a source — never invented)
  - iec_source_manifests reproducible record of each official IEC source
                         (URL, domain, format, fetch status, parser readiness)

It does NOT ingest, infer, or fabricate:
  - vote totals / results
  - winners
  - councillors or office-bearers
  - party mappings
  - geography (ward/municipality) mappings

Official IEC sources only (reused from discover_iec_sources.KNOWN_IEC_SOURCES).
Bounded, idempotent (keyed on manifest_key / election_key), per-source failure
isolation, credential-safe. Offline-fixture mode for tests; live mode does not
download large bodies (checksum left null and noted).

CLI:
  --limit N            cap sources processed
  --sleep S            polite delay between live requests
  --reports-dir DIR    where reports are written (default: reports)
  --dry-run            build rows + report, NO DB writes
  --offline-fixture P  JSON fixture of responses (no network; for tests)
  --json-only          print JSON report instead of Markdown

Outputs:
  reports/iec_metadata_manifest_report.json
  reports/iec_metadata_manifest_report.md
"""
import argparse
import hashlib
import json
import logging
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discover_iec_sources import KNOWN_IEC_SOURCES, detect_format  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# Concrete electoral types that justify creating an iec_elections row.
# "all"/"unknown" (portal/landing pages) get a manifest only — no election row.
ELECTORAL_TYPES = {"national", "provincial", "municipal", "by-election"}

# Format -> parser readiness (structured formats are candidates for a future
# result-parsing PR; HTML/PDF need a parser design first).
_READINESS = {
    "csv": "structured-candidate",
    "json": "structured-candidate",
    "xlsx": "structured-candidate",
    "html": "needs-parser-design",
    "pdf": "needs-parser-design",
    "unknown": "unknown",
}

_URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")


def redact(value: str | None) -> str | None:
    if not value:
        return value
    return _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)


def normalize_url(url: str) -> str:
    """Stable normalized URL: strip whitespace + fragment, drop trailing slash."""
    parts = urlsplit(url.strip())
    path = parts.path.rstrip("/")
    normalized = f"{parts.scheme.lower()}://{parts.netloc.lower()}{path}"
    if parts.query:
        normalized += f"?{parts.query}"
    return normalized


def election_key_for(election_type: str | None, year: int | None) -> str | None:
    """Deterministic election key, only for concrete electoral types."""
    if not election_type or election_type not in ELECTORAL_TYPES:
        return None
    return f"{election_type}-{year}" if year else election_type


def manifest_key_for(source_url: str, election_key: str | None) -> str:
    """Deterministic, stable manifest key from normalized URL + election key."""
    base = normalize_url(source_url)
    return f"{base}#{election_key}" if election_key else base


def parser_readiness(fmt: str, reachable: bool) -> str:
    if not reachable:
        return "unreachable"
    return _READINESS.get(fmt, "unknown")


def build_rows(
    sources: list[dict],
    fetcher: Callable[[str], dict],
    *,
    limit: int | None = None,
) -> dict:
    """Build election + manifest row dicts from sources. Pure: no DB, no report
    side effects. `fetcher(url)` returns {status, content_type, ok, body?}.
    Per-source exceptions are captured as failures, not raised."""
    now = datetime.now(UTC)
    elections: dict[str, dict] = {}
    manifests: list[dict] = []
    failures: list[dict] = []
    attempted = 0

    for source in sources[: limit or len(sources)]:
        attempted += 1
        url = source["url"]
        etype = source.get("election_type")
        year = source.get("year")
        geo = source.get("geography_level")
        try:
            resp = fetcher(url)
        except Exception as exc:  # never abort the batch on one source
            failures.append({"source_url": redact(url), "error_type": type(exc).__name__, "error": str(exc)[:200]})
            continue

        ok = bool(resp.get("ok"))
        content_type = resp.get("content_type")
        fmt = detect_format(url, content_type)
        ekey = election_key_for(etype, year)

        body = resp.get("body")
        checksum = None
        byte_size = None
        checksum_note = "not_fetched_live"
        if isinstance(body, (bytes, str)):
            raw = body.encode("utf-8") if isinstance(body, str) else body
            checksum = hashlib.sha256(raw).hexdigest()
            byte_size = len(raw)
            checksum_note = "computed_from_fetched_body"

        manifests.append(
            {
                "manifest_key": manifest_key_for(url, ekey),
                "source_url": url,
                "source_domain": urlsplit(url).netloc.lower(),
                "source_type": fmt,
                "election_key": ekey,
                "election_type": etype,
                "election_year": year,
                "geography_level": geo,
                "content_type": content_type,
                "status_code": resp.get("status"),
                "reachable": ok,
                "parser_readiness": parser_readiness(fmt, ok),
                "fetched_at": now,
                "checksum_sha256": checksum,
                "byte_size": byte_size,
                "revision_hint": resp.get("revision_hint"),
                "raw_manifest_json": {
                    "notes": source.get("notes"),
                    "checksum_note": checksum_note,
                    "detected_format": fmt,
                    "vote_totals_ingested": False,
                },
            }
        )

        # Only create an election row when the source explicitly labels a
        # concrete electoral type. Year/name are never invented.
        if ekey is not None:
            elections.setdefault(
                ekey,
                {
                    "election_key": ekey,
                    "election_type": etype,
                    "election_year": year,
                    "name": source.get("name"),  # only if explicitly curated
                    "geography_level": geo,
                    "source_url": url,
                    "source_identifier": source.get("source_identifier"),
                    "source_date": None,  # never invented
                    "first_seen_at": now,
                    "last_seen_at": now,
                    "raw_metadata_json": {"notes": source.get("notes"), "vote_totals_ingested": False},
                },
            )

    return {
        "attempted": attempted,
        "elections": list(elections.values()),
        "manifests": manifests,
        "failures": failures,
    }


# ---------------------------------------------------------------------------
# Idempotent upserts
# ---------------------------------------------------------------------------

def upsert_election(db, data: dict) -> bool:
    """Insert or update by election_key. Returns True if newly created."""
    from sqlalchemy import select

    from app.models.iec_election import IECElection

    row = db.scalar(select(IECElection).where(IECElection.election_key == data["election_key"]))
    if row is None:
        db.add(IECElection(**data))
        return True
    row.last_seen_at = data["last_seen_at"]
    row.election_type = data["election_type"]
    row.election_year = data["election_year"]
    if data.get("name"):
        row.name = data["name"]
    row.geography_level = data["geography_level"]
    row.raw_metadata_json = data["raw_metadata_json"]
    return False


def upsert_manifest(db, data: dict) -> bool:
    """Insert or update by manifest_key. Returns True if newly created.
    source_url and created_at are never changed on update."""
    from sqlalchemy import select

    from app.models.iec_source_manifest import IECSourceManifest

    row = db.scalar(select(IECSourceManifest).where(IECSourceManifest.manifest_key == data["manifest_key"]))
    if row is None:
        db.add(IECSourceManifest(**data))
        return True
    for field in (
        "source_type", "election_key", "election_type", "election_year", "geography_level",
        "content_type", "status_code", "reachable", "parser_readiness", "fetched_at",
        "checksum_sha256", "byte_size", "revision_hint", "raw_manifest_json",
    ):
        setattr(row, field, data[field])
    return False


def run_ingest(db, sources, fetcher, *, dry_run=False, limit=None) -> dict:
    """Build rows then (unless dry_run) upsert them idempotently. Returns a
    summary dict used to build the report. No DB writes when dry_run is True."""
    built = build_rows(sources, fetcher, limit=limit)
    created_elections = updated_elections = 0
    created_manifests = updated_manifests = 0

    if not dry_run:
        for e in built["elections"]:
            if upsert_election(db, e):
                created_elections += 1
            else:
                updated_elections += 1
        for m in built["manifests"]:
            if upsert_manifest(db, m):
                created_manifests += 1
            else:
                updated_manifests += 1
        db.commit()

    return {
        "mode": "dry-run" if dry_run else "real",
        "attempted_sources": built["attempted"],
        "elections_built": len(built["elections"]),
        "manifests_built": len(built["manifests"]),
        "created_elections": created_elections,
        "updated_elections": updated_elections,
        "created_manifests": created_manifests,
        "updated_manifests": updated_manifests,
        "failed_sources": len(built["failures"]),
        "failures": built["failures"],
        "manifests": built["manifests"],
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def build_report(summary: dict) -> dict:
    manifests = summary.get("manifests", [])

    def _count_by(key):
        out: dict[str, int] = {}
        for m in manifests:
            out[str(m.get(key))] = out.get(str(m.get(key)), 0) + 1
        return out

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": summary["mode"],
        "attempted_sources": summary["attempted_sources"],
        "upserted_elections": summary["created_elections"] + summary["updated_elections"],
        "upserted_manifests": summary["created_manifests"] + summary["updated_manifests"],
        "created_elections": summary["created_elections"],
        "updated_elections": summary["updated_elections"],
        "created_manifests": summary["created_manifests"],
        "updated_manifests": summary["updated_manifests"],
        "elections_built": summary["elections_built"],
        "manifests_built": summary["manifests_built"],
        "skipped_sources": summary["attempted_sources"] - summary["manifests_built"] - summary["failed_sources"],
        "failed_sources": summary["failed_sources"],
        "failures": summary["failures"],
        "coverage_by_election_type": _count_by("election_type"),
        "coverage_by_election_year": _count_by("election_year"),
        "coverage_by_geography_level": _count_by("geography_level"),
        "parser_readiness_counts": _count_by("parser_readiness"),
        "reachable_manifests": sum(1 for m in manifests if m.get("reachable")),
        "vote_totals_ingested": False,
        "integrity_rules": [
            "Metadata and source manifests only — no vote totals are ingested.",
            "No winners, councillors, office-bearers, party or geography mappings are created or inferred.",
            "Election dates and names are never invented; only explicit/curated labels are stored.",
            "Every manifest retains its source_url and raw manifest metadata.",
            "Idempotent: rows are keyed on manifest_key / election_key.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# IEC Metadata & Source Manifest Ingestion",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Mode:** {report['mode']}",
        f"- **Attempted sources:** {report['attempted_sources']}",
        f"- **Upserted elections:** {report['upserted_elections']} "
        f"(created {report['created_elections']}, updated {report['updated_elections']})",
        f"- **Upserted manifests:** {report['upserted_manifests']} "
        f"(created {report['created_manifests']}, updated {report['updated_manifests']})",
        f"- **Failed sources:** {report['failed_sources']}",
        f"- **Reachable manifests:** {report['reachable_manifests']}",
        f"- **Vote totals ingested:** {report['vote_totals_ingested']}",
        "",
        "## Coverage by election type",
        "",
    ]
    for k, v in sorted(report["coverage_by_election_type"].items()):
        lines.append(f"- {k}: {v}")
    lines += ["", "## Parser readiness", ""]
    for k, v in sorted(report["parser_readiness_counts"].items()):
        lines.append(f"- {k}: {v}")
    if report["failures"]:
        lines += ["", "## Failures (redacted)", ""]
        for f in report["failures"][:10]:
            lines.append(f"- `{f.get('error_type')}` {f.get('source_url')}: {str(f.get('error'))[:160]}")
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "iec_metadata_manifest_report.json"
    md_path = reports_dir / "iec_metadata_manifest_report.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


# ---------------------------------------------------------------------------
# Fetchers
# ---------------------------------------------------------------------------

def _live_fetcher(sleep: float) -> Callable[[str], dict]:
    import requests

    def fetcher(url: str) -> dict:
        time.sleep(sleep)
        # Bounded: metadata only — do not download bodies in live mode.
        resp = requests.get(url, timeout=20, headers={"User-Agent": "KnowYourMPZA-iec-manifest/1.0"}, stream=True)
        ct = resp.headers.get("Content-Type")
        resp.close()
        return {"status": resp.status_code, "content_type": ct, "ok": 200 <= resp.status_code < 400}

    return fetcher


def _fixture_fetcher(fixture_path: Path) -> tuple[list[dict], Callable[[str], dict]]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    responses = {r["url"]: r for r in data.get("responses", [])}
    sources = data.get("sources") or KNOWN_IEC_SOURCES

    def fetcher(url: str) -> dict:
        r = responses.get(url)
        if r is None:
            raise ConnectionError(f"no fixture response for {url}")
        return {
            "status": r.get("status"),
            "content_type": r.get("content_type"),
            "ok": bool(r.get("ok")),
            "body": r.get("body"),
            "revision_hint": r.get("revision_hint"),
        }

    return sources, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest IEC election metadata + source manifests (no vote totals).")
    parser.add_argument("--limit", type=int, default=len(KNOWN_IEC_SOURCES))
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_IEC_SOURCES, _live_fetcher(args.sleep)

    db = None
    try:
        if not args.dry_run:
            import os

            if not os.environ.get("DATABASE_URL"):
                logger.error("REFUSED: DATABASE_URL is not set — real ingestion needs a database.")
                sys.exit(2)
            from app.db import SessionLocal

            db = SessionLocal()
        summary = run_ingest(db, sources, fetcher, dry_run=args.dry_run, limit=args.limit)
    except SystemExit:
        raise
    except Exception as exc:
        logger.error("FATAL: %s: %s", type(exc).__name__, exc)
        if db is not None:
            db.rollback()
        sys.exit(1)
    finally:
        if db is not None:
            db.close()

    report = build_report(summary)
    write_report(report, Path(args.reports_dir))
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))

    # All sources failed -> non-zero (a real problem with the source set/network).
    if report["attempted_sources"] > 0 and report["failed_sources"] == report["attempted_sources"]:
        logger.error("All %d sources failed.", report["attempted_sources"])
        sys.exit(1)


if __name__ == "__main__":
    main()

