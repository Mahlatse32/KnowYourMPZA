"""Tests for Gazette/Acts/Bills source discovery (no network, no DB)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_gazette_acts_sources import (
    KNOWN_GAZETTE_ACTS_SOURCES,
    build_discovery_report,
    detect_format,
    render_markdown,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DOC = REPO_ROOT / "backend" / "docs" / "gazette-acts-bills-ingestion-design.md"


def _fetcher(ok=True, status=200, content_type="text/html"):
    return lambda url: {"status": status, "content_type": content_type, "ok": ok}


def test_official_sources_only():
    official = ("gov.za", "parliament.gov.za", "pmg.org.za")
    for s in KNOWN_GAZETTE_ACTS_SOURCES:
        assert any(domain in s["url"] for domain in official), s["url"]


def test_discovery_report_generated_from_fixture():
    report = build_discovery_report(KNOWN_GAZETTE_ACTS_SOURCES, _fetcher())
    assert report["total_sources"] == len(KNOWN_GAZETTE_ACTS_SOURCES)
    assert report["status"].startswith("discovery-only")


def test_official_source_metadata_retained():
    report = build_discovery_report(KNOWN_GAZETTE_ACTS_SOURCES, _fetcher())
    acts = [s for s in report["sources"] if s["data_type"] == "act"]
    assert acts and all(a["identifier_type"] for a in acts)
    assert all(s["source_url"] for s in report["sources"])


def test_no_fabricated_records():
    report = build_discovery_report(KNOWN_GAZETTE_ACTS_SOURCES, _fetcher())
    assert all(s["ingested"] is False for s in report["sources"])


def test_format_detection():
    assert detect_format("https://gov.za/x.pdf", None) == "pdf"
    assert detect_format("https://api.pmg.org.za/bill/", "application/json") == "json"


def test_bounded_limit():
    assert build_discovery_report(KNOWN_GAZETTE_ACTS_SOURCES, _fetcher(), limit=2)["total_sources"] == 2


def test_json_and_markdown_outputs(tmp_path):
    report = build_discovery_report(KNOWN_GAZETTE_ACTS_SOURCES, _fetcher())
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["source"].startswith("Government Gazette")
    assert "Source Discovery" in md_path.read_text(encoding="utf-8")


def test_offline_fixture_roundtrip(tmp_path):
    from discover_gazette_acts_sources import _fixture_fetcher

    fixture = {
        "sources": [{"url": "https://www.gov.za/documents/acts/x.pdf", "owner": "gov.za", "data_type": "act",
                     "identifier_type": "act_number/year", "notes": "t"}],
        "responses": [{"url": "https://www.gov.za/documents/acts/x.pdf", "status": 200, "content_type": "application/pdf", "ok": True}],
    }
    fpath = tmp_path / "f.json"
    fpath.write_text(json.dumps(fixture), encoding="utf-8")
    sources, fetcher = _fixture_fetcher(fpath)
    report = build_discovery_report(sources, fetcher)
    assert report["sources"][0]["format"] == "pdf"


def test_design_doc_has_no_fabrication_and_source_rules():
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "No fabricated records" in text
    assert "Source evidence required" in text
    assert "No inferred linkage" in text or "never inferred" in text.lower()
