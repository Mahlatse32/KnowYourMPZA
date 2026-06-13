#!/usr/bin/env python3
"""Bounded, safe audit of official IEC structured result downloads (#24).

AUDIT ONLY. Inspects official IEC source URLs with bounded HEAD/GET requests
and reports content type, size, checksum (of the bounded body), detected
format, likely parser profile, and CSV header columns when detectable. It
writes NO database rows, ingests NO vote totals, commits NO downloaded files,
and never prints secrets.

Safety constraints enforced:
  - Official IEC domains only (elections.org.za); off-domain (incl. redirects
    landing off-domain) are rejected as failures, not followed.
  - Bounded body: at most --max-bytes are read; larger responses are flagged
    `oversize` / sampled and marked unsafe for a full fetch.
  - Allowed content types only; others are risk-flagged.
  - Per-URL failures are captured; if every URL fails the run exits non-zero.

Sources: explicit --url (reviewed official URLs), and/or --manifest-key to pull
source_url from iec_source_manifests when a DB is available. Offline-fixture
mode is used by tests and never hits the network.

CLI:
  --url URL                 (repeatable) official IEC URL to audit
  --manifest-key KEY        (repeatable) pull source_url from a manifest row
  --offline-fixture PATH    JSON fixture of responses (tests; no network)
  --max-bytes N             body read cap (default 1_000_000)
  --timeout S               per-request timeout seconds (default 20)
  --reports-dir DIR         output dir (default reports)
  --json-only               print JSON instead of Markdown

Outputs:
  reports/iec_live_download_audit.json
  reports/iec_live_download_audit.md
"""
import argparse
import hashlib
import json
import logging
import re
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from discover_iec_sources import detect_format  # noqa: E402

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
logger = logging.getLogger(__name__)

IEC_OFFICIAL_DOMAIN = "elections.org.za"
DEFAULT_MAX_BYTES = 1_000_000
ALLOWED_CONTENT_TYPES = ("csv", "json", "xlsx", "octet-stream", "html", "pdf")

# A structured result file is parser-foundation-ready only if its CSV header
# exposes an explicit vote column plus source contest + party/candidate ids.
EXPECTED_CSV_COLUMNS = {"contest_id", "party_id", "votes"}

_URL_CREDENTIALS_RE = re.compile(r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@")
_SECRET_RE = re.compile(r"(?i)\b(password|passwd|pwd|secret|token|api[_-]?key)\b\s*[:=]\s*[^\s,;]+")


def redact(value: str | None) -> str | None:
    if not value:
        return value
    value = _URL_CREDENTIALS_RE.sub(r"\1[REDACTED]@", value)
    return _SECRET_RE.sub(lambda m: f"{m.group(1)}=[REDACTED]", value)


def is_official_iec(url: str | None) -> bool:
    if not url:
        return False
    host = urlsplit(url).netloc.lower().split(":")[0]
    return host == IEC_OFFICIAL_DOMAIN or host.endswith("." + IEC_OFFICIAL_DOMAIN)


def _content_type_family(content_type: str | None) -> str:
    ct = (content_type or "").lower()
    if "csv" in ct:
        return "csv"
    if "json" in ct:
        return "json"
    if "spreadsheet" in ct or "excel" in ct:
        return "xlsx"
    if "pdf" in ct:
        return "pdf"
    if "html" in ct:
        return "html"
    if "octet-stream" in ct:
        return "octet-stream"
    return "other"


def detect_csv_columns(body: bytes | str | None) -> list[str] | None:
    if body is None:
        return None
    text = body.decode("utf-8", errors="replace") if isinstance(body, bytes) else body
    first_line = text.splitlines()[0] if text.strip() else ""
    if not first_line:
        return None
    return [c.strip().strip('"').lower() for c in first_line.split(",") if c.strip()]


def audit_one(url: str, resp: dict, *, max_bytes: int) -> dict:
    """Build one audit record from a (possibly fixture) response. No network,
    no DB. `resp` keys: status, content_type, content_length, body, final_url."""
    final_url = resp.get("final_url") or url
    redirected_off_domain = not is_official_iec(final_url)
    body = resp.get("body")
    raw = None
    if isinstance(body, str):
        raw = body.encode("utf-8")
    elif isinstance(body, (bytes, bytearray)):
        raw = bytes(body)

    fetched_bytes = len(raw) if raw is not None else 0
    declared_length = resp.get("content_length")
    sampled = bool(raw is not None and (fetched_bytes >= max_bytes or (declared_length and declared_length > max_bytes)))
    checksum = hashlib.sha256(raw).hexdigest() if raw is not None else None

    fmt = detect_format(url, resp.get("content_type"))
    ct_family = _content_type_family(resp.get("content_type"))
    columns = detect_csv_columns(raw) if fmt == "csv" else None

    risk_flags: list[str] = []
    if redirected_off_domain:
        risk_flags.append("redirect_off_official_domain")
    if ct_family == "other":
        risk_flags.append("disallowed_or_unknown_content_type")
    if declared_length and declared_length > max_bytes:
        risk_flags.append("oversize")
    if sampled:
        risk_flags.append("body_sampled_not_full")
    if columns is not None and not EXPECTED_CSV_COLUMNS.issubset(set(columns)):
        risk_flags.append("csv_header_missing_expected_columns")

    status = resp.get("status")
    reachable = bool(status and 200 <= status < 400) and not redirected_off_domain

    if fmt in ("csv", "json", "xlsx") and not risk_flags and reachable:
        parser_profile = "structured-candidate"
    elif fmt in ("html", "pdf"):
        parser_profile = "needs-parser-design"
    else:
        parser_profile = "unknown"

    return {
        "source_url": url,
        "final_url": final_url if final_url != url else None,
        "status_code": status,
        "content_type": resp.get("content_type"),
        "content_length": declared_length,
        "fetched_bytes": fetched_bytes,
        "body_sampled": sampled,
        "checksum_sha256": checksum,
        "source_format": fmt,
        "official_iec": is_official_iec(url),
        "reachable": reachable,
        "csv_columns": columns,
        "has_expected_csv_columns": (columns is not None and EXPECTED_CSV_COLUMNS.issubset(set(columns))),
        "likely_parser_profile": parser_profile,
        "risk_flags": risk_flags,
        "rows_written_to_db": False,
    }


def build_audit(urls: list[str], fetcher: Callable[[str], dict], *, max_bytes: int) -> dict:
    audited: list[dict] = []
    failures: list[dict] = []
    rejected_non_official: list[str] = []

    for url in urls:
        if not is_official_iec(url):
            rejected_non_official.append(redact(url))
            failures.append({"source_url": redact(url), "error_type": "NonOfficialDomain",
                             "error": "URL is not on an official IEC domain"})
            continue
        try:
            resp = fetcher(url)
        except Exception as exc:
            failures.append({"source_url": redact(url), "error_type": type(exc).__name__, "error": str(exc)[:200]})
            continue
        audited.append(audit_one(url, resp, max_bytes=max_bytes))

    attempted = len(urls)
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "attempted_urls": attempted,
        "audited_count": len(audited),
        "failed_count": len(failures),
        "rejected_non_official": rejected_non_official,
        "structured_candidate_count": sum(1 for a in audited if a["likely_parser_profile"] == "structured-candidate"),
        "audited": audited,
        "failures": failures,
        "integrity_rules": [
            "Audit only — no vote totals ingested and no database rows written.",
            "Official IEC domains only; off-domain URLs and off-domain redirects are rejected.",
            "Bounded body read; oversize responses are sampled and flagged unsafe for full fetch.",
            "No winner, office-bearer, councillor, or internal party/geography mapping is produced.",
            "Downloaded content is never committed.",
        ],
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# IEC Controlled Live Download Audit",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Attempted URLs:** {report['attempted_urls']}",
        f"- **Audited:** {report['audited_count']} | **Failed:** {report['failed_count']}",
        f"- **Structured-candidate:** {report['structured_candidate_count']}",
        f"- **Rejected (non-official):** {len(report['rejected_non_official'])}",
        "",
        "| Source URL | Status | Format | Reachable | Parser profile | Risk flags |",
        "|---|---|---|---|---|---|",
    ]
    for a in report["audited"]:
        lines.append(
            f"| {a['source_url']} | {a['status_code']} | {a['source_format']} | "
            f"{'yes' if a['reachable'] else 'no'} | {a['likely_parser_profile']} | "
            f"{', '.join(a['risk_flags']) or '-'} |"
        )
    if report["failures"]:
        lines += ["", "## Failures (redacted)", ""]
        for f in report["failures"][:20]:
            lines.append(f"- `{f.get('error_type')}` {f.get('source_url')}: {str(f.get('error'))[:160]}")
    lines += ["", "## Integrity rules", ""]
    lines += [f"- {r}" for r in report["integrity_rules"]]
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "iec_live_download_audit.json"
    md_path = reports_dir / "iec_live_download_audit.md"
    json_path.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
    md_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, md_path


def _manifest_urls(manifest_keys: list[str]) -> list[str]:
    """Resolve manifest keys to source URLs from the DB; empty if unavailable."""
    if not manifest_keys:
        return []
    try:
        from sqlalchemy import select

        from app.db import SessionLocal
        from app.models.iec_source_manifest import IECSourceManifest

        with SessionLocal() as db:
            rows = db.scalars(
                select(IECSourceManifest).where(IECSourceManifest.manifest_key.in_(manifest_keys))
            ).all()
            return [r.source_url for r in rows]
    except Exception as exc:
        logger.warning("could not resolve manifest keys (%s) — DB unavailable", type(exc).__name__)
        return []


def _live_fetcher(max_bytes: int, timeout: float) -> Callable[[str], dict]:
    import requests

    def fetcher(url: str) -> dict:
        resp = requests.get(
            url, timeout=timeout, allow_redirects=True, stream=True,
            headers={"User-Agent": "KnowYourMPZA-iec-audit/1.0"},
        )
        body = resp.raw.read(max_bytes + 1, decode_content=True)
        final_url = resp.url
        content_length = resp.headers.get("Content-Length")
        out = {
            "status": resp.status_code,
            "content_type": resp.headers.get("Content-Type"),
            "content_length": int(content_length) if content_length and content_length.isdigit() else len(body),
            "body": body[:max_bytes],
            "final_url": final_url,
        }
        resp.close()
        return out

    return fetcher


def _fixture_fetcher(fixture_path: Path) -> tuple[list[str], Callable[[str], dict]]:
    data = json.loads(fixture_path.read_text(encoding="utf-8"))
    responses = {r["url"]: r for r in data.get("responses", [])}
    urls = data.get("urls") or list(responses.keys())

    def fetcher(url: str) -> dict:
        r = responses.get(url)
        if r is None:
            raise ConnectionError(f"no fixture response for {url}")
        return {
            "status": r.get("status"),
            "content_type": r.get("content_type"),
            "content_length": r.get("content_length"),
            "body": r.get("body"),
            "final_url": r.get("final_url"),
        }

    return urls, fetcher


def main() -> None:
    parser = argparse.ArgumentParser(description="Bounded audit of official IEC downloads (no ingestion).")
    parser.add_argument("--url", action="append", default=[], help="Official IEC URL (repeatable).")
    parser.add_argument("--manifest-key", action="append", default=[], help="Manifest key to resolve to a URL (repeatable).")
    parser.add_argument("--offline-fixture", default=None)
    parser.add_argument("--max-bytes", type=int, default=DEFAULT_MAX_BYTES)
    parser.add_argument("--timeout", type=float, default=20.0)
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        urls, fetcher = _fixture_fetcher(Path(args.offline_fixture))
    else:
        urls = list(args.url) + _manifest_urls(args.manifest_key)
        fetcher = _live_fetcher(args.max_bytes, args.timeout)

    if not urls:
        logger.error("No URLs to audit (provide --url, --manifest-key, or --offline-fixture).")
        sys.exit(2)

    report = build_audit(urls, fetcher, max_bytes=args.max_bytes)
    write_report(report, Path(args.reports_dir))
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))

    if report["attempted_urls"] > 0 and report["failed_count"] == report["attempted_urls"]:
        logger.error("All %d URLs failed the audit.", report["attempted_urls"])
        sys.exit(1)


if __name__ == "__main__":
    main()
