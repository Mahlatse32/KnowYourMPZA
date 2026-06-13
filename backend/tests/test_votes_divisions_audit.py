"""Tests for votes/divisions source audit (no network, no DB)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from audit_votes_divisions_sources import (
    KNOWN_VOTE_SOURCES,
    VALID_GRANULARITIES,
    build_audit_report,
    detect_format,
    render_markdown,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DOC = REPO_ROOT / "backend" / "docs" / "votes-divisions-ingestion-design.md"


def _fetcher(ok=True, status=200, content_type="application/json"):
    return lambda url: {"status": status, "content_type": content_type, "ok": ok}


def test_known_sources_have_valid_granularity():
    for s in KNOWN_VOTE_SOURCES:
        assert s["granularity"] in {"party-level", "MP-level", "house-level", "unknown",
                                     "house-level/party-level"}


def test_pmg_source_is_marked_implemented():
    pmg = [s for s in KNOWN_VOTE_SOURCES if "api.pmg.org.za" in s["url"]]
    assert pmg and pmg[0]["implemented"] is True


def test_audit_report_from_fixture():
    report = build_audit_report(KNOWN_VOTE_SOURCES, _fetcher())
    assert report["total_sources"] == len(KNOWN_VOTE_SOURCES)
    assert report["status"].startswith("audit-only")
    assert report["implemented_count"] >= 1


def test_no_fabricated_votes():
    report = build_audit_report(KNOWN_VOTE_SOURCES, _fetcher())
    assert all(s["creates_vote_records"] is False for s in report["sources"])
    assert any("never inferred from party position" in r for r in report["integrity_rules"])


def test_format_detection():
    assert detect_format("https://api.pmg.org.za/committee-meeting/", "application/json") == "json"
    assert detect_format("https://parliament.gov.za/x.pdf", None) == "pdf"


def test_bounded_limit():
    assert build_audit_report(KNOWN_VOTE_SOURCES, _fetcher(), limit=1)["total_sources"] == 1


def test_json_and_markdown_outputs(tmp_path):
    report = build_audit_report(KNOWN_VOTE_SOURCES, _fetcher())
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["source"].startswith("Parliamentary votes")
    assert "Source Audit" in md_path.read_text(encoding="utf-8")


def test_offline_fixture_roundtrip(tmp_path):
    from audit_votes_divisions_sources import _fixture_fetcher

    fixture = {
        "sources": [{"url": "https://www.parliament.gov.za/minutes-proceedings", "owner": "Parliament",
                     "chamber": "NA", "vote_type": "division", "granularity": "unknown", "implemented": False, "notes": "t"}],
        "responses": [{"url": "https://www.parliament.gov.za/minutes-proceedings", "status": 200,
                       "content_type": "text/html", "ok": True}],
    }
    fpath = tmp_path / "f.json"
    fpath.write_text(json.dumps(fixture), encoding="utf-8")
    sources, fetcher = _fixture_fetcher(fpath)
    report = build_audit_report(sources, fetcher)
    assert report["sources"][0]["parse_readiness"] == "needs-parser-design"


def test_design_doc_has_source_limitation_rules():
    raw = DESIGN_DOC.read_text(encoding="utf-8")
    normalized = " ".join(raw.lower().split())  # collapse line wraps
    assert "Source limitations" in raw
    assert "Party-level vs MP-level" in raw
    assert "never inferred from the party" in normalized
    assert "must remain unknown" in normalized
