#!/usr/bin/env python3
"""Audit candidate sources for current MP/member coverage.

Audit only: this script does not ingest representatives or write to the
database. Live checks are bounded; offline fixtures are supported for tests.
"""

import argparse
import json
import re
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Callable


KNOWN_MP_SOURCES = [
    {
        "source_name": "Parliament National Assembly members",
        "source_url": "https://www.parliament.gov.za/national-assembly/members",
        "source_owner": "Parliament of the Republic of South Africa",
        "representative_scope": "National Assembly",
        "officialness": "official",
        "expected_fields": ["person name", "party", "role", "house/chamber", "contact/profile URL"],
        "risks": ["Page structure and field availability require validation before ingestion."],
        "recommended_use": "baseline authority",
    },
    {
        "source_name": "Parliament NCOP members",
        "source_url": "https://www.parliament.gov.za/ncop/members",
        "source_owner": "Parliament of the Republic of South Africa",
        "representative_scope": "NCOP",
        "officialness": "official",
        "expected_fields": [
            "person name",
            "party",
            "role",
            "house/chamber",
            "province",
            "contact/profile URL",
        ],
        "risks": ["Page structure and field availability require validation before ingestion."],
        "recommended_use": "baseline authority",
    },
    {
        "source_name": "People's Assembly members of Parliament",
        "source_url": "https://www.pa.org.za/position/member/parliament/",
        "source_owner": "People's Assembly",
        "representative_scope": "National Assembly",
        "officialness": "civic/enrichment",
        "expected_fields": ["person name", "party", "role", "contact/profile URL"],
        "risks": [
            "Third-party civic source; it must not be the sole authority for the current MP universe.",
            "GitHub Actions source access is currently blocked under issue #47.",
        ],
        "recommended_use": "enrichment",
    },
    {
        "source_name": "PMG committee meeting API",
        "source_url": "https://api.pmg.org.za/committee-meeting/",
        "source_owner": "Parliamentary Monitoring Group",
        "representative_scope": "unknown",
        "officialness": "supporting",
        "expected_fields": ["person name", "role", "contact/profile URL"],
        "risks": ["Activity evidence does not establish the complete current membership universe."],
        "recommended_use": "activity link",
    },
    {
        "source_name": "IEC election context",
        "source_url": "https://results.elections.org.za/",
        "source_owner": "Electoral Commission of South Africa",
        "representative_scope": "unknown",
        "officialness": "official",
        "expected_fields": ["person name", "party", "province"],
        "risks": [
            "Election candidates or results are not evidence that a person currently holds office.",
            "Issue #24 remains open for full IEC ingestion.",
        ],
        "recommended_use": "not safe yet",
    },
]

_EXT_FORMATS = {
    ".csv": "csv",
    ".json": "api",
    ".pdf": "pdf",
    ".html": "html",
    ".htm": "html",
}


def redact(value: object) -> str:
    text = str(value)
    text = re.sub(
        r"(?i)\b(database_url|password|token|secret|api_key)\b\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    return re.sub(
        r"(?i)([a-z][a-z0-9+.-]*://)[^/\s:@]+:[^/\s@]+@",
        r"\1[REDACTED]@",
        text,
    )


def detect_source_type(url: str, content_type: str | None, declared: str | None = None) -> str:
    if declared in {"html", "csv", "pdf", "api", "unknown"}:
        return declared
    clean_url = url.split("?")[0].lower()
    for extension, source_type in _EXT_FORMATS.items():
        if clean_url.endswith(extension):
            return source_type
    if "/api" in clean_url or clean_url.startswith("https://api."):
        return "api"
    lowered = (content_type or "").lower()
    for marker, source_type in (
        ("csv", "csv"),
        ("json", "api"),
        ("pdf", "pdf"),
        ("html", "html"),
    ):
        if marker in lowered:
            return source_type
    return "unknown"


def parser_readiness(source_type: str, reachable: bool) -> str:
    if not reachable:
        return "unreachable"
    if source_type in {"csv", "api"}:
        return "structured-candidate"
    if source_type in {"html", "pdf"}:
        return "needs-parser-validation"
    return "unknown"


def audit_sources(
    sources: list[dict],
    fetcher: Callable[[str], dict],
    *,
    limit: int | None = None,
) -> dict:
    audited = []
    for source in sources[: limit or len(sources)]:
        url = redact(source.get("source_url") or "")
        try:
            response = fetcher(str(source.get("source_url") or ""))
        except Exception as exc:
            response = {
                "ok": False,
                "status": None,
                "content_type": None,
                "error": type(exc).__name__,
            }
        source_type = detect_source_type(
            url,
            response.get("content_type"),
            source.get("source_type"),
        )
        reachable = bool(response.get("ok"))
        risks = [redact(item) for item in source.get("risks", []) if item]
        if response.get("error"):
            risks.append(f"Source check failed: {redact(response['error'])}.")
        audited.append(
            {
                "source_name": redact(source.get("source_name") or ""),
                "source_url": url,
                "source_owner": redact(source.get("source_owner") or ""),
                "representative_scope": source.get("representative_scope") or "unknown",
                "source_type": source_type,
                "officialness": source.get("officialness") or "supporting",
                "parser_readiness": parser_readiness(source_type, reachable),
                "expected_fields": list(source.get("expected_fields") or []),
                "risks": risks,
                "recommended_use": source.get("recommended_use") or "not safe yet",
                "reachable": reachable,
                "fetch_status": response.get("status"),
            }
        )

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "status": "audit-only",
        "source_count": len(audited),
        "baseline_candidate_count": sum(
            1
            for item in audited
            if item["officialness"] == "official"
            and item["recommended_use"] == "baseline authority"
        ),
        "expected_universe_available": False,
        "cannot_claim_all_mps": True,
        "database_writes": 0,
        "records_ingested": 0,
        "sources": audited,
        "integrity_rules": [
            "Audit only: no representatives, roles, parties, or memberships are ingested.",
            "Parliament official member sources are baseline candidates pending parser validation.",
            "People's Assembly is enrichment and must not be the sole current-office authority.",
            "PMG provides activity support, not a complete current-member universe.",
            "IEC election context is not current-office evidence unless an explicit source says so.",
            "No MPs, party memberships, office-holders, or source mappings are inferred.",
        ],
    }


def load_fixture(path: Path) -> tuple[list[dict], Callable[[str], dict]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    responses = {item["url"]: item for item in payload.get("responses", [])}
    sources = payload.get("sources") or KNOWN_MP_SOURCES

    def fetcher(url: str) -> dict:
        item = responses.get(url, {})
        return {
            "ok": bool(item.get("ok")),
            "status": item.get("status"),
            "content_type": item.get("content_type"),
            "error": item.get("error"),
        }

    return sources, fetcher


def live_fetcher(sleep_seconds: float) -> Callable[[str], dict]:
    import requests

    def fetch(url: str) -> dict:
        time.sleep(sleep_seconds)
        response = requests.get(
            url,
            timeout=20,
            headers={"User-Agent": "KnowYourMPZA-source-audit/1.0"},
            stream=True,
        )
        result = {
            "ok": 200 <= response.status_code < 400,
            "status": response.status_code,
            "content_type": response.headers.get("Content-Type"),
        }
        response.close()
        return result

    return fetch


def render_markdown(report: dict) -> str:
    lines = [
        "# MP/Member Source Audit",
        "",
        f"- **Generated:** {report['generated_at']}",
        "- **Mode:** audit only; no database writes or representative ingestion",
        f"- **Sources audited:** {report['source_count']}",
        f"- **Baseline candidates:** {report['baseline_candidate_count']}",
        "- **Expected MP universe available:** no",
        "- **Can claim all MPs:** no",
        "",
        "| Source | Owner | Scope | Type | Officialness | Parser readiness | Recommended use | Risks |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for source in report["sources"]:
        lines.append(
            f"| {source['source_name']} | {source['source_owner']} | "
            f"{source['representative_scope']} | {source['source_type']} | "
            f"{source['officialness']} | {source['parser_readiness']} | "
            f"{source['recommended_use']} | {'; '.join(source['risks']) or 'None recorded.'} |"
        )
    lines.extend(["", "## Integrity rules", ""])
    lines.extend(f"- {rule}" for rule in report["integrity_rules"])
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, reports_dir: Path) -> tuple[Path, Path]:
    reports_dir.mkdir(parents=True, exist_ok=True)
    json_path = reports_dir / "mp_member_source_audit.json"
    markdown_path = reports_dir / "mp_member_source_audit.md"
    json_path.write_text(json.dumps(report, indent=2, default=str) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit MP/member source candidates without ingestion.")
    parser.add_argument("--offline-fixture")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--sleep", type=float, default=1.0)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    if args.offline_fixture:
        sources, fetcher = load_fixture(Path(args.offline_fixture))
    else:
        sources, fetcher = KNOWN_MP_SOURCES, live_fetcher(args.sleep)
    report = audit_sources(sources, fetcher, limit=args.limit)
    write_report(report, Path(args.reports_dir))
    print(json.dumps(report, default=str) if args.json_only else render_markdown(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
