import json
from datetime import UTC, datetime

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.party import Party
from app.models.politician import Politician
from app.models.source import Source
from app.models.unresolved_entity import UnresolvedEntity
from scripts.report_mp_coverage import build_report, write_report


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_unavailable_safe_when_people_table_is_absent():
    db = _session()
    try:
        db.execute(text("DROP TABLE politicians"))
        report = build_report(db)
    finally:
        db.close()
    assert report["status"] == "unavailable"
    assert report["total_people_records"] is None
    assert report["readiness"] == "red"


def test_counts_people_sources_duplicates_activity_and_unresolved_aliases():
    db = _session()
    try:
        party = Party(name="Evidence Party", short_name="EP")
        source = Source(
            name="PMG",
            base_url="https://pmg.org.za",
            source_type="document",
            reliability_score=0.9,
        )
        db.add_all([party, source])
        db.flush()
        first = Politician(
            full_name="Amina Evidence",
            display_name="Amina Evidence",
            slug="amina-evidence",
            party_id=party.id,
            profile_url="https://www.pa.org.za/person/amina-evidence/",
            is_active=True,
        )
        second = Politician(
            full_name=" Amina Evidence ",
            display_name="A. Evidence",
            slug="amina-evidence-2",
            party_id=party.id,
            profile_url=None,
            is_active=True,
        )
        third = Politician(
            full_name="Bongi Source",
            display_name="Bongi Source",
            slug="bongi-source",
            party_id=party.id,
            profile_url="https://www.parliament.gov.za/person/bongi-source",
            is_active=False,
        )
        db.add_all([first, second, third])
        db.flush()
        document = Document(
            title="Committee activity",
            document_type="committee_meeting",
            source_id=source.id,
            source_url="https://pmg.org.za/committee-meeting/123/",
            publication_date=None,
            raw_text="A source-backed meeting record.",
        )
        db.add(document)
        db.flush()
        db.add_all(
            [
                DocumentMention(
                    document_id=document.id,
                    politician_id=first.id,
                    snippet="Amina Evidence attended.",
                    source_url=document.source_url,
                    confidence_score=1.0,
                ),
                UnresolvedEntity(
                    source_name="People's Assembly",
                    source_url="https://www.pa.org.za/committee/example/",
                    raw_value="A. Unknown",
                    entity_type="politician_alias",
                    status="OPEN",
                    created_at=datetime.now(UTC),
                ),
            ]
        )
        db.commit()
        report = build_report(db)
    finally:
        db.close()

    assert report["total_people_records"] == 3
    assert report["people_with_source_url"] == 2
    assert report["people_without_source_url"] == 1
    assert report["current_mp_like_records"] == 2
    assert report["records_with_pa_profile"] == 1
    assert report["records_with_parliament_source"] == 1
    assert report["records_with_pmg_activity"] == 1
    assert report["possible_duplicate_names"] == 1
    assert report["unresolved_aliases"] == 1


def test_readiness_is_red_without_expected_universe():
    db = _session()
    try:
        report = build_report(db)
    finally:
        db.close()
    assert report["expected_universe_table_available"] is True
    assert report["expected_universe_available"] is False
    assert report["expected_representative_count"] == 0
    assert report["cannot_claim_all_mps"] is True
    assert report["missing_expected_representatives"] is None
    assert report["readiness"] == "red"


def test_reports_are_generated_without_secrets(tmp_path):
    db = _session()
    try:
        report = build_report(db)
    finally:
        db.close()
    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))
    assert payload["cannot_claim_all_mps"] is True
    assert "# MP Coverage Scoreboard" in blob
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob
