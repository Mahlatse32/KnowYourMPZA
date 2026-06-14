import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.politician import Politician
from scripts.audit_mp_member_sources import audit_sources, load_fixture, write_report


FIXTURE = Path(__file__).parent / "fixtures" / "mp" / "member_source_audit.json"


def _report() -> dict:
    sources, fetcher = load_fixture(FIXTURE)
    return audit_sources(sources, fetcher)


def test_official_parliament_source_is_baseline_candidate():
    report = _report()
    parliament = next(item for item in report["sources"] if item["source_owner"].startswith("Parliament"))
    assert parliament["officialness"] == "official"
    assert parliament["recommended_use"] == "baseline authority"
    assert parliament["representative_scope"] == "National Assembly"


def test_people_assembly_is_enrichment_not_sole_authority():
    pa = next(item for item in _report()["sources"] if item["source_owner"] == "People's Assembly")
    assert pa["officialness"] == "civic/enrichment"
    assert pa["recommended_use"] == "enrichment"
    assert any("sole" in risk for risk in pa["risks"])


def test_pmg_is_activity_support():
    pmg = next(item for item in _report()["sources"] if item["source_owner"] == "Parliamentary Monitoring Group")
    assert pmg["officialness"] == "supporting"
    assert pmg["recommended_use"] == "activity link"
    assert pmg["source_type"] == "api"


def test_offline_fixture_generates_reports(tmp_path):
    report = _report()
    json_path, markdown_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "audit-only"
    assert "# MP/Member Source Audit" in markdown_path.read_text(encoding="utf-8")


def test_audit_performs_no_database_writes():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    before = db.scalar(select(func.count()).select_from(Politician))
    report = _report()
    after = db.scalar(select(func.count()).select_from(Politician))
    assert before == after == 0
    assert report["database_writes"] == 0
    assert report["records_ingested"] == 0
    db.close()


def test_audit_redacts_secrets_and_does_not_claim_complete_coverage():
    sources, fetcher = load_fixture(FIXTURE)
    sources[0] = {
        **sources[0],
        "source_name": "DATABASE_URL=postgresql://user:password@db.example/test",
        "source_url": "https://user:password@www.parliament.gov.za/members",
        "risks": ["token=super-secret"],
    }
    report = audit_sources(sources, fetcher)
    blob = json.dumps(report)
    assert "user:password" not in blob
    assert "super-secret" not in blob
    assert "[REDACTED]" in blob
    assert report["expected_universe_available"] is False
    assert report["cannot_claim_all_mps"] is True
