"""Tests asserting the data product roadmap documents the required sections."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPO_ROOT / "backend" / "docs" / "data-product-roadmap.md"


def test_roadmap_exists():
    assert ROADMAP.exists()


def test_roadmap_has_required_sections():
    text = ROADMAP.read_text(encoding="utf-8")
    for heading in (
        "Current capabilities",
        "Currently implemented data sources",
        "Discovery-only areas",
        "Open issues mapped to phases",
        "Not yet",
        "Recommended sequence",
        "Public-readiness checklist",
    ):
        assert heading in text, f"missing roadmap section: {heading}"


def test_roadmap_lists_not_yet_constraints():
    text = ROADMAP.read_text(encoding="utf-8").lower()
    assert "no ai" in text and "rag" in text
    assert "no opensearch" in text
    assert "no frontend" in text


def test_roadmap_maps_all_open_issues():
    text = ROADMAP.read_text(encoding="utf-8")
    for issue in ("#18", "#28", "#24", "#7", "#25", "#26", "#27"):
        assert issue in text, f"roadmap missing issue {issue}"


def test_roadmap_keeps_no_fabrication_rule():
    text = ROADMAP.read_text(encoding="utf-8").lower()
    assert "no fabricated records" in text
    assert "source evidence" in text or "source-backed" in text


def test_roadmap_recommended_sequence_starts_with_alert_then_entity_resolution():
    text = ROADMAP.read_text(encoding="utf-8")
    seq = text.split("Recommended sequence", 1)[1]
    pos_18 = seq.find("#18")
    pos_28 = seq.find("#28")
    pos_24 = seq.find("#24")
    assert -1 < pos_18 < pos_28 < pos_24
