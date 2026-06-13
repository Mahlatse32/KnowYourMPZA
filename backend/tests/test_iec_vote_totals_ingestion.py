import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine, inspect, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.ingestion.iec_vote_totals import parse_vote_totals_csv, result_key_for
from app.models.iec_source_manifest import IECSourceManifest
from app.models.iec_vote_total import IECVoteTotal
from ingest_iec_vote_totals import redact, run_ingest, write_report


FIXTURE = Path(__file__).parent / "fixtures" / "iec" / "party_vote_totals.csv"


@pytest.fixture()
def db():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    session = sessionmaker(bind=engine)()
    yield session
    session.close()


@pytest.fixture()
def manifest(db):
    row = IECSourceManifest(
        manifest_key="https://results.elections.org.za/download/npe-2024.csv#national-2024",
        source_url="https://results.elections.org.za/download/npe-2024.csv",
        source_domain="results.elections.org.za",
        source_type="csv",
        election_key="national-2024",
        election_type="national",
        election_year=2024,
        geography_level="national",
        reachable=True,
        parser_readiness="structured-candidate",
        fetched_at=datetime.now(UTC),
        checksum_sha256="a" * 64,
        raw_manifest_json={"audited_profile": "party-vote-totals-csv"},
    )
    db.add(row)
    db.commit()
    return row


def test_migration_model_creates_vote_totals_table(db):
    assert "iec_vote_totals" in inspect(db.get_bind()).get_table_names()


def test_parser_preserves_raw_rows_and_isolates_invalid_votes(manifest):
    parsed = parse_vote_totals_csv(FIXTURE, manifest)
    assert parsed["input_rows"] == 3
    assert [row["vote_total"] for row in parsed["rows"]] == [1234, 567]
    assert parsed["rows"][0]["raw_row_json"]["Party_Name"] == "Alpha Party"
    assert parsed["failures"][0]["row_number"] == 4


def test_parser_rejects_missing_required_columns(tmp_path, manifest):
    path = tmp_path / "missing-party-id.csv"
    path.write_text("Contest_ID,Party_Name,Votes\nC1,Example Party,12\n", encoding="utf-8")
    parsed = parse_vote_totals_csv(path, manifest)
    assert parsed["rows"] == []
    assert parsed["failures"][0]["error_type"] == "MissingColumns"
    assert "Party_ID" in parsed["failures"][0]["error"]


def test_parser_model_has_no_winner_or_office_fields():
    columns = {column.name for column in IECVoteTotal.__table__.columns}
    assert not any("winner" in column or "office" in column or "councillor" in column for column in columns)


def test_dry_run_writes_no_rows(db, manifest):
    report = run_ingest(db, manifest, FIXTURE, dry_run=True)
    assert report["valid_rows"] == 2
    assert db.scalar(select(IECVoteTotal).limit(1)) is None


def test_real_run_inserts_and_rerun_updates(db, manifest):
    first = run_ingest(db, manifest, FIXTURE)
    second = run_ingest(db, manifest, FIXTURE)
    assert first["created_count"] == 2
    assert second["created_count"] == 0
    assert second["updated_count"] == 2
    assert len(list(db.scalars(select(IECVoteTotal)))) == 2


def test_source_manifest_checksum_and_url_are_retained(db, manifest):
    report = run_ingest(db, manifest, FIXTURE)
    row = db.scalar(select(IECVoteTotal).limit(1))
    assert row.source_url == manifest.source_url
    assert row.manifest_key == manifest.manifest_key
    assert report["manifest_checksum_sha256"] == manifest.checksum_sha256


def test_result_key_is_stable_when_vote_total_changes(manifest):
    row = parse_vote_totals_csv(FIXTURE, manifest)["rows"][0]
    key = result_key_for(manifest.manifest_key, row)
    row["vote_total"] = 999
    assert result_key_for(manifest.manifest_key, row) == key


def test_all_invalid_rows_return_nonzero_summary(tmp_path, db, manifest):
    path = tmp_path / "invalid.csv"
    path.write_text("Contest_ID,Party_ID,Votes\nC1,P1,nope\n", encoding="utf-8")
    report = run_ingest(db, manifest, path)
    assert report["valid_rows"] == 0
    assert report["exit_code"] == 1


def test_report_flags_and_unresolved_counts(db, manifest):
    report = run_ingest(db, manifest, FIXTURE, dry_run=True)
    assert report["unresolved_party_count"] == 2
    assert report["unresolved_candidate_count"] == 0
    assert report["winners_ingested"] is False
    assert report["office_bearers_ingested"] is False
    assert report["internal_party_mapping_applied"] is False


def test_report_files_are_created_and_secret_safe(tmp_path, db, manifest):
    report = run_ingest(db, manifest, FIXTURE, dry_run=True)
    report["failures"].append(
        {"row_number": 9, "error_type": "Example", "error": "postgresql://user:hunter2@host/db"}
    )
    report["failures"][-1]["error"] = redact(report["failures"][-1]["error"])
    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert "hunter2" not in blob
    assert json.loads(json_path.read_text(encoding="utf-8"))["source_url"] == manifest.source_url
