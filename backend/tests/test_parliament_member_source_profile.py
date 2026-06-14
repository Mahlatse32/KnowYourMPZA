import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.politician import Politician
from scripts.profile_parliament_member_sources import (
    build_report,
    is_official_parliament_url,
    load_fixture,
    write_report,
)


FIXTURE = (
    Path(__file__).parent
    / "fixtures"
    / "parliament"
    / "member_source_profile.json"
)


def _report():
    sources, fetcher = load_fixture(FIXTURE)
    return build_report(sources, fetcher)


def test_offline_fixture_profiles_official_source():
    report = _report()
    official = next(item for item in report["sources"] if item["official_source"])
    assert official["source_owner"] == "Parliament of the Republic of South Africa"
    assert official["recommended_use"] == "baseline authority"
    assert official["ingestion_candidate"] is True


def test_non_official_source_is_rejected():
    pa = next(item for item in _report()["sources"] if "pa.org.za" in item["source_url"])
    assert pa["official_source"] is False
    assert pa["parser_readiness"] == "rejected-non-official"
    assert pa["ingestion_candidate"] is False
    assert pa["recommended_use"] == "not safe yet"


def test_parser_readiness_uses_explicit_detected_fields():
    official = next(item for item in _report()["sources"] if item["official_source"])
    assert official["format"] == "html"
    assert official["parser_readiness"] == "html-parser-candidate"
    assert {"person name", "party", "role", "contact/profile URL"} <= set(
        official["detected_fields"]
    )


def test_official_domain_check_is_strict():
    assert is_official_parliament_url("https://www.parliament.gov.za/members")
    assert not is_official_parliament_url("https://parliament.gov.za.example.test/members")
    assert not is_official_parliament_url("https://www.pa.org.za/members")


def test_profile_performs_no_database_writes():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    before = db.scalar(select(func.count()).select_from(Politician))
    report = _report()
    after = db.scalar(select(func.count()).select_from(Politician))
    assert before == after == 0
    assert report["database_writes"] == 0
    assert report["records_ingested"] == 0
    assert report["full_mp_coverage_claimed"] is False
    db.close()


def test_reports_generated_and_secrets_redacted(tmp_path):
    sources, fetcher = load_fixture(FIXTURE)
    sources[0] = {
        **sources[0],
        "source_url": "https://user:password@www.parliament.gov.za/members",
    }
    report = build_report(sources, fetcher)
    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "profile-only"
    assert "user:password" not in blob
    assert "[REDACTED]" in blob
