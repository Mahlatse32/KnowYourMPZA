"""Tests for IEC source discovery foundation (no network, no DB)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_iec_sources import (
    KNOWN_IEC_SOURCES,
    build_discovery_report,
    detect_format,
    render_markdown,
    write_report,
)


def _fetcher(ok=True, status=200, content_type="text/html"):
    def fetch(url):
        return {"status": status, "content_type": content_type, "ok": ok}

    return fetch


def test_detect_format():
    assert detect_format("https://x/results.csv", None) == "csv"
    assert detect_format("https://x/data.json", None) == "json"
    assert detect_format("https://x/report.pdf", None) == "pdf"
    assert detect_format("https://x/sheet.xlsx", None) == "xlsx"
    assert detect_format("https://x/home/", "text/html; charset=utf-8") == "html"
    assert detect_format("https://x/api", "application/json") == "json"
    assert detect_format("https://x/unknown", None) == "unknown"


def test_discovery_uses_official_sources_only():
    for s in KNOWN_IEC_SOURCES:
        assert "elections.org.za" in s["url"]


def test_discovery_report_from_fixture_fetcher():
    report = build_discovery_report(KNOWN_IEC_SOURCES, _fetcher(ok=True))
    assert report["total_sources"] == len(KNOWN_IEC_SOURCES)
    assert report["reachable_count"] == len(KNOWN_IEC_SOURCES)
    assert report["status"].startswith("discovery-only")


def test_source_urls_retained():
    report = build_discovery_report(KNOWN_IEC_SOURCES, _fetcher())
    urls = {s["source_url"] for s in report["sources"]}
    assert "https://results.elections.org.za/home/" in urls


def test_no_fabricated_db_records():
    # Discovery never marks anything ingested and exposes no DB record fields.
    report = build_discovery_report(KNOWN_IEC_SOURCES, _fetcher())
    assert all(s["ingested"] is False for s in report["sources"])


def test_bounded_limit():
    report = build_discovery_report(KNOWN_IEC_SOURCES, _fetcher(), limit=1)
    assert report["total_sources"] == 1


def test_unreachable_marks_parse_readiness():
    report = build_discovery_report(KNOWN_IEC_SOURCES, _fetcher(ok=False, status=503))
    assert all(s["parse_readiness"] == "unreachable" for s in report["sources"])
    assert report["reachable_count"] == 0


def test_fetcher_error_does_not_abort():
    def broken(url):
        raise ConnectionError("boom")

    report = build_discovery_report(KNOWN_IEC_SOURCES, broken)
    assert report["total_sources"] == len(KNOWN_IEC_SOURCES)
    assert report["reachable_count"] == 0


def test_json_and_markdown_outputs(tmp_path):
    report = build_discovery_report(KNOWN_IEC_SOURCES, _fetcher())
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["source"].startswith("IEC")
    md = md_path.read_text(encoding="utf-8")
    assert "IEC Election Results" in md
    assert "Integrity rules" in md


def test_offline_fixture_roundtrip(tmp_path):
    # A real fixture file the test writes, then the module reads — no network.
    from discover_iec_sources import _fixture_fetcher

    fixture = {
        "sources": [{"url": "https://results.elections.org.za/x.csv", "election_type": "national",
                     "year": 2024, "geography_level": "national", "notes": "test"}],
        "responses": [{"url": "https://results.elections.org.za/x.csv", "status": 200,
                       "content_type": "text/csv", "ok": True}],
    }
    fpath = tmp_path / "fixture.json"
    fpath.write_text(json.dumps(fixture), encoding="utf-8")
    sources, fetcher = _fixture_fetcher(fpath)
    report = build_discovery_report(sources, fetcher)
    assert report["sources"][0]["format"] == "csv"
    assert report["sources"][0]["parse_readiness"] == "structured-candidate"
