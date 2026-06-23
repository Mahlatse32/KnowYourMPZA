#!/usr/bin/env python3
"""Profile official Parliament member-list sources without ingesting data."""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable
from urllib.parse import urlparse


CANDIDATE_SOURCES = [
    {
        "source_url": "https://www.parliament.gov.za/members",
        "chamber": "Unknown",
        "source_owner": "Parliament of the Republic of South Africa",
    },
    {
        "source_url": "https://www.parliament.gov.za/national-assembly/members",
        "chamber": "National Assembly",
        "source_owner": "Parliament of the Republic of South Africa",
    },
    {
        "source_url": "https://www.parliament.gov.za/ncop/members",
        "chamber": "NCOP",
        "source_owner": "Parliament of the Republic of South Africa",
    },
]


def redact(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)\b(database_url|password|passwd|secret|token|api_key|authorization)\b"
        r"(\s*[:=]\s*)([^\s,;]+)",
        r"\1\2[REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)\b([a-z][a-z0-9+.-]*://)([^/\s:@]+):([^@\s/]+)@",
        r"\1[REDACTED]:[REDACTED]@",
        text,
    )


def is_official_parliament_url(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host == "parliament.gov.za" or host.endswith(".parliament.gov.za")


def detect_format(url: str, content_type: str | None) -> str:
    clean = url.split("?")[0].lower()
    for suffix, name in (
        (".csv", "csv"),
        (".json", "json"),
        (".xlsx", "xlsx"),
        (".xls", "xlsx"),
        (".pdf", "pdf"),
    ):
        if clean.endswith(suffix):
            return name
    lowered = (content_type or "").lower()
    for marker, name in (
        ("csv", "csv"),
        ("json", "json"),
        ("spreadsheet", "xlsx"),
        ("excel", "xlsx"),
        ("pdf", "pdf"),
        ("html", "html"),
    ):
        if marker in lowered:
            return name
    return "unknown"


def detect_fields(body: str | None) -> list[str]:
    text = re.sub(r"<[^>]+>", " ", body or "")
    normalized = " ".join(text.lower().split())
    fields = []
    signals = {
        "person name": ("member name", "full name", "surname", "members"),
        "party": ("political party", "party"),
        "role": ("position", "role", "whip", "chairperson"),
        "house/chamber": ("national assembly", "ncop", "chamber"),
        "province": ("province", "provincial"),
        "contact/profile URL": ("contact", "profile", "email"),
    }
    for field, markers in signals.items():
        if any(marker in normalized for marker in markers):
            fields.append(field)
    return fields


def _readiness(official: bool, reachable: bool, source_format: str, fields: list[str]) -> str:
    if not official:
        return "rejected-non-official"
    if not reachable:
        return "unreachable"
    if source_format in {"csv", "json", "xlsx"}:
        return "structured-candidate"
    if source_format == "html" and "person name" in fields:
        return "html-parser-candidate"
    if source_format in {"html", "pdf"}:
        return "needs-field-validation"
    return "unknown"


def build_report(
    sources: list[dict],
    fetcher: Callable[[str], dict],
    *,
    limit: int | None = None,
) -> dict:
    profiled = []
    for source in sources[: limit or len(sources)]:
        raw_url = str(source.get("source_url") or "")
        official = is_official_parliament_url(raw_url)
        try:
            response = fetcher(raw_url)
        except Exception as exc:
            response = {
                "ok": False,
                "status_code": None,
                "content_type": None,
                "body": "",
                "error": type(exc).__name__,
            }
        source_format = detect_format(raw_url, response.get("content_type"))
        fields = detect_fields(response.get("body"))
        reachable = bool(response.get("ok"))
        readiness = _readiness(official, reachable, source_format, fields)
        risks = []
        if not official:
            risks.append("Rejected: source is not hosted by Parliament of South Africa.")
        if not reachable:
            risks.append("Source was not reachable during this bounded profile check.")
        if reachable and not fields:
            risks.append("No explicit representative fields were detected in the sampled response.")
        if source_format in {"html", "pdf"}:
            risks.append("Markup or document structure must be reviewed before parser implementation.")
        if response.get("error"):
            risks.append(f"Source check failed: {redact(response['error'])}.")
        ingestion_candidate = bool(
            official
            and reachable
            and readiness in {"structured-candidate", "html-parser-candidate"}
        )
        profiled.append(
            {
                "source_url": redact(raw_url),
                "chamber": source.get("chamber") or "Unknown",
                "source_owner": redact(
                    source.get("source_owner")
                    or "Parliament of the Republic of South Africa"
                ),
                "content_type": response.get("content_type"),
                "status_code": response.get("status_code"),
                "format": source_format,
                "parser_readiness": readiness,
                "detected_fields": fields,
                "risks": risks,
                "recommended_use": (
                    "baseline authority"
                    if ingestion_candidate
                    else "not safe yet"
                ),
                "ingestion_candidate": ingestion_candidate,
                "official_source": official,
            }
        )
    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "profile-only",
        "source_count": len(profiled),
        "ingestion_candidate_count": sum(
            1 for item in profiled if item["ingestion_candidate"]
        ),
        "database_writes": 0,
        "records_ingested": 0,
        "full_mp_coverage_claimed": False,
        "sources": profiled,
        "integrity_rules": [
            "Only official parliament.gov.za sources may be baseline ingestion candidates.",
            "People's Assembly remains enrichment and PMG remains activity support.",
            "Profiling performs no database writes and ingests no representatives.",
            "No MPs, memberships, parties, roles, or office-holders are inferred.",
            "A source profile is not evidence of full MP coverage.",
        ],
    }


def load_fixture(path: Path) -> tuple[list[dict], Callable[[str], dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    responses = {item["url"]: item for item in payload.get("responses", [])}
    sources = payload.get("sources") or CANDIDATE_SOURCES

    def fetcher(url: str) -> dict:
        response = responses.get(url, {})
        return {
            "ok": bool(response.get("ok")),
            "status_code": response.get("status_code"),
            "content_type": response.get("content_type"),
            "body": response.get("body") or "",
            "error": response.get("error"),
        }

    return sources, fetcher


def live_fetcher(sleep_seconds: float) -> Callable[[str], dict]:
    import requests

    def fetch(url: str) -> dict:
        time.sleep(sleep_seconds)
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "KnowYourMPZA-source-profile/1.0"},
        )
        return {
            "ok": 200 <= response.status_code < 400,
            "status_code": response.status_code,
            "content_type": response.headers.get("Content-Type"),
            "body": response.text[:200_000],
        }

    return fetch


def render_markdown(report: dict) -> str:
    lines = [
        "# Parliament Member Source Profile",
        "",
        f"- **Generated:** {report['generated_at']}",
        "- **Mode:** profile only; no database writes or ingestion",
        f"- **Sources profiled:** {report['source_count']}",
        f"- **Ingestion candidates:** {report['ingestion_candidate_count']}",
        "- **Full MP coverage claimed:** no",
        "",
        "| Source | Chamber | Status | Format | Readiness | Fields | Candidate | Risks |",
        "|---|---|---:|---|---|---|---|---|",
    ]
    for source in report["sources"]:
        lines.append(
            f"| {source['source_url']} | {source['chamber']} | "
            f"{source['status_code'] or '-'} | {source['format']} | "
            f"{source['parser_readiness']} | "
            f"{', '.join(source['detected_fields']) or 'none'} | "
            f"{'yes' if source['ingestion_candidate'] else 'no'} | "
            f"{'; '.join(source['risks']) or 'None recorded.'} |"
        )
    lines.extend(["", "## Integrity rules", ""])
    lines.extend(f"- {rule}" for rule in report["integrity_rules"])
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "parliament_member_source_profile.json"
    markdown_path = reports_dir / "parliament_member_source_profile.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Profile official Parliament member sources without ingestion."
    )
    parser.add_argument("--offline-fixture")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = load_fixture(Path(args.offline_fixture))
    else:
        sources, fetcher = CANDIDATE_SOURCES, live_fetcher(args.sleep)
    report = build_report(sources, fetcher, limit=args.limit)
    write_report(report, Path(args.reports_dir))
    print(json.dumps(report, sort_keys=True) if args.json_only else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
