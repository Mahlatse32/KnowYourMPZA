from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
INVENTORY = REPO_ROOT / "backend" / "docs" / "source-inventory.md"


def test_source_inventory_separates_implemented_and_candidate_sources():
    text = INVENTORY.read_text(encoding="utf-8")
    assert "## Implemented sources" in text
    assert "## Candidate sources and backlog" in text
    assert "Candidate / not implemented" in text
    assert "Implemented, limited" in text


def test_source_inventory_contains_required_rules():
    text = INVENTORY.read_text(encoding="utf-8")
    assert "### No fabricated records" in text
    assert "### Source evidence required" in text
    assert "## Priority scoring" in text


def test_source_inventory_lists_current_ingestion_scripts():
    text = INVENTORY.read_text(encoding="utf-8")
    for script in (
        "ingest_people_assembly_full.py",
        "ingest_committees_full.py",
        "ingest_pmg_full.py",
        "ingest_questions_full.py",
        "ingest_bills.py",
        "ingest_votes.py",
        "ingest_committee_activity.py",
    ):
        assert script in text


def test_source_inventory_lists_required_candidate_domains():
    text = INVENTORY.read_text(encoding="utf-8")
    for candidate in (
        "IEC election results",
        "Municipal Money",
        "Parliament Hansard",
        "Government Gazette",
        "Municipal councils and office-bearers",
        "Presidency cabinet announcements",
        "Public Protector reports",
    ):
        assert candidate in text
