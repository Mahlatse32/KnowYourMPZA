from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
PLAN = REPO_ROOT / "backend" / "docs" / "v1-completion-plan.md"
DEFINITION = REPO_ROOT / "backend" / "docs" / "data-completeness-definition.md"


def _text() -> str:
    return (PLAN.read_text(encoding="utf-8") + "\n" + DEFINITION.read_text(encoding="utf-8")).lower()


def test_v1_completion_documents_exist():
    assert PLAN.exists()
    assert DEFINITION.exists()


def test_docs_require_no_fabrication_and_source_evidence():
    text = _text()
    assert "no fabricated records" in text
    assert "source evidence" in text
    assert "unknown or missing data remains unknown or missing" in text


def test_docs_define_red_amber_green_readiness():
    text = _text()
    for level in ("red", "amber", "green"):
        assert level in text
    assert "complete enough for the defined v1" in text


def test_docs_define_mp_person_coverage_without_overclaiming():
    text = _text()
    assert "mp/person coverage" in text
    assert "expected_universe_available: false" in text
    assert "cannot_claim_all_mps: true" in text
    assert "authoritative expected universe" in text


def test_docs_keep_iec_issue_open_and_pa_blocker_visible():
    text = _text()
    assert "issue #24 remains open" in text
    assert "full iec ingestion is incomplete" in text
    assert "#47" in text
    assert "source-access blocker" in text or "source-access block" in text


def test_docs_list_required_domains_and_out_of_scope_items():
    text = _text()
    for domain in (
        "people and representatives",
        "parties",
        "parliamentary activity",
        "bills, questions, and committees",
        "iec election context",
        "source inventory",
        "data quality and readiness",
        "scheduled ingestion health",
    ):
        assert domain in text
    for excluded in ("ai, rag", "inferred election winners", "inferred office-bearers"):
        assert excluded in text
