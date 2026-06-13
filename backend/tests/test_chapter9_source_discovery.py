"""Tests for Chapter 9 report source discovery (no network, no DB)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_chapter9_report_sources import (
    KNOWN_CHAPTER9_SOURCES,
    build_discovery_report,
    is_official_candidate,
    render_markdown,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DOC = REPO_ROOT / "backend" / "docs" / "chapter9-reports-ingestion-design.md"


def _fetcher(ok=True, status=200, content_type="text/html"):
    return lambda url: {"status": status, "content_type": content_type, "ok": ok}


def test_official_institution_sources_only():
    for s in KNOWN_CHAPTER9_SOURCES:
        assert s["official"] is True
        assert is_official_candidate(s["url"])


def test_media_sources_are_rejected():
    assert is_official_candidate("https://www.news24.com/report") is False
    assert is_official_candidate("https://www.dailymaverick.co.za/x") is False
    assert is_official_candidate("https://www.pprotect.org/report") is True


def test_media_source_skipped_in_report():
    sources = KNOWN_CHAPTER9_SOURCES + [
        {"url": "https://www.news24.com/fake-finding", "institution": "Media", "official": False, "notes": "media"}
    ]
    report = build_discovery_report(sources, _fetcher())
    assert "https://www.news24.com/fake-finding" in report["skipped_non_official"]
    assert all("news24" not in s["source_url"] for s in report["sources"])


def test_no_findings_extracted():
    report = build_discovery_report(KNOWN_CHAPTER9_SOURCES, _fetcher())
    assert all(s["findings_extracted"] is False for s in report["sources"])
    assert all(s["ingested"] is False for s in report["sources"])


def test_bounded_limit():
    assert build_discovery_report(KNOWN_CHAPTER9_SOURCES, _fetcher(), limit=1)["total_sources"] == 1


def test_json_and_markdown_outputs(tmp_path):
    report = build_discovery_report(KNOWN_CHAPTER9_SOURCES, _fetcher())
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["source"].startswith("Chapter 9")
    assert "Source Discovery" in md_path.read_text(encoding="utf-8")


def test_offline_fixture_roundtrip(tmp_path):
    from discover_chapter9_report_sources import _fixture_fetcher

    fixture = {
        "sources": [{"url": "https://www.pprotect.org/report.pdf", "institution": "Public Protector",
                     "official": True, "notes": "t"}],
        "responses": [{"url": "https://www.pprotect.org/report.pdf", "status": 200,
                       "content_type": "application/pdf", "ok": True}],
    }
    fpath = tmp_path / "f.json"
    fpath.write_text(json.dumps(fixture), encoding="utf-8")
    sources, fetcher = _fixture_fetcher(fpath)
    report = build_discovery_report(sources, fetcher)
    assert report["sources"][0]["format"] == "pdf"
    assert report["sources"][0]["parse_readiness"] == "needs-parser-design"


def test_design_doc_has_evidence_and_no_fabrication_rules():
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "No fabricated findings" in text
    assert "No allegation-as-finding" in text or "allegation" in text.lower()
    assert "Media is never an official source" in text
    assert "evidence_locator" in text
