from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, inspect
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models import ExpectedRepresentativeUniverse
from app.models.expected_representative_universe import make_universe_key
from scripts.report_mp_coverage import build_report


MIGRATION = (
    Path(__file__).resolve().parents[1]
    / "alembic"
    / "versions"
    / "0013_add_expected_representative_universe.py"
)


def _session():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_model_metadata_creates_expected_universe_table_and_indexes():
    db = _session()
    try:
        inspector = inspect(db.get_bind())
        assert "expected_representative_universe" in inspector.get_table_names()
        columns = {item["name"] for item in inspector.get_columns("expected_representative_universe")}
        assert {
            "universe_key",
            "source_name",
            "source_url",
            "chamber",
            "representative_type",
            "full_name",
            "raw_source_json",
        } <= columns
        indexes = {
            column
            for item in inspector.get_indexes("expected_representative_universe")
            for column in item["column_names"]
        }
        assert {"chamber", "party_name", "province", "status", "full_name"} <= indexes
    finally:
        db.close()


def test_migration_creates_table_without_internal_person_mapping():
    text = MIGRATION.read_text(encoding="utf-8")
    assert 'op.create_table(\n        "expected_representative_universe"' in text
    assert "politician_id" not in text
    assert "person_id" not in text


def test_universe_key_is_stable_and_source_scoped():
    values = {
        "source_name": "Parliament of South Africa",
        "source_url": "https://www.parliament.gov.za/members",
        "chamber": "National Assembly",
        "term_label": "7th Parliament",
        "source_identifier": "MP-001",
        "full_name": "Source Evidence",
    }
    assert make_universe_key(**values) == make_universe_key(**values)
    assert make_universe_key(**values) != make_universe_key(
        **{**values, "source_identifier": "MP-002"}
    )


def test_empty_expected_universe_does_not_claim_full_coverage():
    db = _session()
    try:
        report = build_report(db)
    finally:
        db.close()
    assert report["expected_universe_table_available"] is True
    assert report["expected_universe_available"] is False
    assert report["expected_representative_count"] == 0
    assert report["cannot_claim_all_mps"] is True
    assert report["readiness"] == "red"


def test_expected_row_has_no_required_internal_mapping():
    row = ExpectedRepresentativeUniverse(
        universe_key="a" * 64,
        source_name="Official source",
        source_url="https://www.parliament.gov.za/members",
        chamber="National Assembly",
        representative_type="MP",
        full_name="Explicit Source Person",
        status="expected",
        first_seen_at=datetime.now(UTC),
        last_seen_at=datetime.now(UTC),
        raw_source_json={"full_name": "Explicit Source Person"},
    )
    assert row.party_name is None
    assert row.role_title is None
    assert not hasattr(row, "politician_id")
