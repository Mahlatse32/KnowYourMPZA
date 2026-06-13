import json
import sys
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import create_engine, text
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.models.iec_source_manifest import IECSourceManifest
from app.models.iec_vote_total import IECVoteTotal
from report_iec_coverage import build_report, determine_public_readiness, render_markdown, write_report


def _session():
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _manifest(key="manifest-1", **overrides):
    values = {
        "manifest_key": key,
        "source_url": f"https://results.elections.org.za/{key}.csv",
        "source_domain": "results.elections.org.za",
        "source_type": "csv",
        "election_type": "national",
        "election_year": 2024,
        "geography_level": "national",
        "reachable": True,
        "parser_readiness": "structured-candidate",
        "fetched_at": datetime.now(UTC),
        "raw_manifest_json": {},
    }
    values.update(overrides)
    return IECSourceManifest(**values)


def _vote(key="vote-1", manifest_key="manifest-1", **overrides):
    values = {
        "result_key": key,
        "manifest_key": manifest_key,
        "source_url": "https://results.elections.org.za/manifest-1.csv",
        "source_format": "csv",
        "source_row_number": 2,
        "source_contest_id": "C1",
        "source_party_id": "P1",
        "source_candidate_id": "CAN1",
        "source_geography_id": "ZA",
        "vote_total": 42,
        "raw_row_json": {"Votes": "42"},
        "row_checksum_sha256": "a" * 64,
    }
    values.update(overrides)
    return IECVoteTotal(**values)


def test_vote_table_absence_is_unavailable_safe():
    db = _session()
    try:
        db.add(_manifest())
        db.commit()
        db.execute(text("DROP TABLE iec_vote_totals"))
        report = build_report(db)
    finally:
        db.close()
    assert report["vote_totals_table_available"] is False
    assert report["vote_total_rows_count"] is None
    assert report["manifests_without_vote_totals"] == 1
    assert report["public_readiness"]["status"] == "yellow"


def test_detects_manifests_without_vote_totals():
    db = _session()
    try:
        db.add_all([_manifest("manifest-1"), _manifest("manifest-2")])
        db.add(_vote())
        db.commit()
        report = build_report(db)
    finally:
        db.close()
    assert report["manifests_without_vote_totals"] == 1
    assert report["public_readiness"]["status"] == "yellow"


def test_detects_orphaned_totals():
    db = _session()
    try:
        db.add(_vote(manifest_key="missing-manifest"))
        db.commit()
        report = build_report(db)
    finally:
        db.close()
    assert report["vote_totals_without_manifest"] == 1
    assert report["public_readiness"]["status"] == "red"


def test_counts_unresolved_source_identifiers():
    db = _session()
    try:
        db.add(_manifest())
        db.add_all([
            _vote("vote-1", source_party_id="P1", source_candidate_id="C1", source_geography_id="ZA"),
            _vote("vote-2", source_party_id="P2", source_candidate_id=None, source_geography_id="ZA"),
        ])
        db.commit()
        report = build_report(db)
    finally:
        db.close()
    assert report["unresolved_source_party_count"] == 2
    assert report["unresolved_source_candidate_count"] == 1
    assert report["unresolved_source_geography_count"] == 1


def test_duplicate_detection_and_red_rule_are_explicit():
    db = _session()
    try:
        db.add(_manifest())
        db.add(_vote())
        db.commit()
        report = build_report(db)
    finally:
        db.close()
    assert report["duplicate_result_key_count"] == 0
    report["duplicate_result_key_count"] = 1
    assert determine_public_readiness(report)["status"] == "red"


def test_green_readiness_requires_complete_consistent_coverage():
    db = _session()
    try:
        db.add(_manifest())
        db.add(_vote())
        db.commit()
        report = build_report(db)
    finally:
        db.close()
    assert report["public_readiness"]["status"] == "green"
    assert report["winners_ingested"] is False
    assert report["office_bearers_ingested"] is False


def test_json_markdown_output_and_secret_safety(tmp_path):
    db = _session()
    try:
        report = build_report(db)
    finally:
        db.close()
    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    assert json.loads(json_path.read_text(encoding="utf-8"))["public_readiness"]["status"] == "yellow"
    assert "# IEC Coverage Quality Report" in render_markdown(report)
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob
