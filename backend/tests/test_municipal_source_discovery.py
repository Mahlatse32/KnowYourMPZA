"""Tests for municipal source discovery (no network, no DB)."""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from discover_municipal_sources import (
    KNOWN_MUNICIPAL_SOURCES,
    build_discovery_report,
    render_markdown,
    write_report,
)

REPO_ROOT = Path(__file__).resolve().parents[2]
DESIGN_DOC = REPO_ROOT / "backend" / "docs" / "municipal-councils-ingestion-design.md"


def _fetcher(ok=True, status=200, content_type="text/html"):
    return lambda url: {"status": status, "content_type": content_type, "ok": ok}


def test_includes_treasury_and_iec_sources():
    urls = " ".join(s["url"] for s in KNOWN_MUNICIPAL_SOURCES)
    assert "municipaldata.treasury.gov.za" in urls
    assert "results.elections.org.za" in urls


def test_discovery_report_from_fixture():
    report = build_discovery_report(KNOWN_MUNICIPAL_SOURCES, _fetcher())
    assert report["total_sources"] == len(KNOWN_MUNICIPAL_SOURCES)
    assert report["status"].startswith("discovery-only")


def test_no_fabricated_office_bearers():
    report = build_discovery_report(KNOWN_MUNICIPAL_SOURCES, _fetcher())
    assert all(s["ingested"] is False for s in report["sources"])
    # integrity rule about winners must be present
    assert any("seated office-bearers" in r for r in report["integrity_rules"])


def test_trust_levels_present():
    report = build_discovery_report(KNOWN_MUNICIPAL_SOURCES, _fetcher())
    trusts = {s["trust"] for s in report["sources"]}
    assert "official" in trusts
    assert "candidate" in trusts or "official-candidate" in trusts


def test_bounded_limit():
    assert build_discovery_report(KNOWN_MUNICIPAL_SOURCES, _fetcher(), limit=1)["total_sources"] == 1


def test_json_and_markdown_outputs(tmp_path):
    report = build_discovery_report(KNOWN_MUNICIPAL_SOURCES, _fetcher())
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["source"].startswith("Municipal")
    assert "Source Discovery" in md_path.read_text(encoding="utf-8")


def test_offline_fixture_roundtrip(tmp_path):
    from discover_municipal_sources import _fixture_fetcher

    fixture = {
        "sources": [{"url": "https://municipaldata.treasury.gov.za/api/x.json", "owner": "National Treasury",
                     "province": "WC", "data_type": "budget", "trust": "official", "notes": "t"}],
        "responses": [{"url": "https://municipaldata.treasury.gov.za/api/x.json", "status": 200,
                       "content_type": "application/json", "ok": True}],
    }
    fpath = tmp_path / "f.json"
    fpath.write_text(json.dumps(fixture), encoding="utf-8")
    sources, fetcher = _fixture_fetcher(fpath)
    report = build_discovery_report(sources, fetcher)
    assert report["sources"][0]["format"] == "json"
    assert report["sources"][0]["parse_readiness"] == "structured-candidate"


def test_design_doc_has_source_rules():
    text = DESIGN_DOC.read_text(encoding="utf-8")
    assert "No fabricated office-bearers" in text
    assert "Winners are not office-bearers" in text
    assert "municipality_code" in text
    assert "cannot be inferred" in text.lower()
