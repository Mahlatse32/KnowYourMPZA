"""Tests for the IEC unresolved-identifiers report (#24). SQLite, no network."""
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))

from app.db import Base
from app.models.iec_vote_total import IECVoteTotal

from report_iec_unresolved_identifiers import build_report, redact, render_markdown, write_report


def _engine(create=True):
    eng = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    if create:
        Base.metadata.create_all(eng)
    return eng


@pytest.fixture()
def db():
    eng = _engine(create=True)
    session = sessionmaker(bind=eng)()
    yield session
    session.close()
    Base.metadata.drop_all(eng)


def _vote(**kw):
    now = datetime.now(UTC)
    base = dict(
        result_key=kw.get("result_key", "k"), manifest_key="m1",
        election_key="national-2024", election_type="national", election_year=2024,
        source_url="https://results.elections.org.za/x.csv", source_format="csv",
        source_row_number=1, source_contest_id="NPE-NA", source_contest_name="National Ballot",
        geography_level="national", source_geography_id="ZA", source_geography_name="South Africa",
        source_party_id="P001", source_party_name="Alpha Party",
        source_candidate_id=None, source_candidate_name=None,
        vote_total=100, raw_row_json={}, row_checksum_sha256="c", created_at=now, updated_at=now,
    )
    base.update(kw)
    return IECVoteTotal(**base)


def _seed(db, rows):
    for r in rows:
        db.add(r)
    db.commit()


def test_unavailable_safe():
    eng = _engine(create=False)
    session = sessionmaker(bind=eng)()
    try:
        report = build_report(session)
    finally:
        session.close()
    assert report["status"] == "unavailable"
    assert report["total_rows"] == 0
    assert report["parties"] == []
    assert report["mapping_status"] == "unresolved"


def test_groups_parties(db):
    _seed(db, [
        _vote(result_key="a", source_party_id="P001", source_party_name="Alpha", vote_total=100),
        _vote(result_key="b", source_party_id="P001", source_party_name="Alpha", vote_total=50),
        _vote(result_key="c", source_party_id="P002", source_party_name="Beta", vote_total=10),
    ])
    report = build_report(db)
    parties = {p["source_id"]: p for p in report["parties"]}
    assert parties["P001"]["row_count"] == 2
    assert parties["P001"]["vote_total_sum"] == 150
    assert parties["P002"]["vote_total_sum"] == 10
    assert all(p["mapping_status"] == "unresolved" for p in report["parties"])


def test_groups_geographies_with_level(db):
    _seed(db, [
        _vote(result_key="a", geography_level="national", source_geography_id="ZA", source_geography_name="South Africa"),
        _vote(result_key="b", geography_level="provincial", source_geography_id="GP", source_geography_name="Gauteng"),
    ])
    report = build_report(db)
    geos = report["geographies"]
    assert len(geos) == 2
    assert any(g.get("geography_level") == "provincial" and g["source_id"] == "GP" for g in geos)


def test_groups_contests(db):
    _seed(db, [
        _vote(result_key="a", source_contest_id="C1", source_contest_name="Ballot 1"),
        _vote(result_key="b", source_contest_id="C1", source_contest_name="Ballot 1"),
        _vote(result_key="c", source_contest_id="C2", source_contest_name="Ballot 2"),
    ])
    report = build_report(db)
    contests = {c["source_id"]: c for c in report["contests"]}
    assert contests["C1"]["row_count"] == 2
    assert contests["C2"]["row_count"] == 1


def test_candidate_nullable_handling(db):
    _seed(db, [
        _vote(result_key="a", source_candidate_id=None, source_candidate_name=None),     # excluded
        _vote(result_key="b", source_candidate_id="CAND1", source_candidate_name="X"),    # included
    ])
    report = build_report(db)
    ids = {c["source_id"] for c in report["candidates"]}
    assert "CAND1" in ids
    assert None not in ids
    assert len(report["candidates"]) == 1


def test_counts_rows_and_vote_sums(db):
    _seed(db, [
        _vote(result_key="a", election_type="national", election_year=2024, vote_total=100),
        _vote(result_key="b", election_type="municipal", election_year=2021, vote_total=200),
    ])
    report = build_report(db)
    assert report["total_rows"] == 2
    assert report["counts_by_election_type"].get("national") == 1
    assert report["counts_by_election_type"].get("municipal") == 1


def test_no_internal_mapping_fields(db):
    _seed(db, [_vote(result_key="a")])
    report = build_report(db)
    blob = json.dumps({k: v for k, v in report.items() if k not in ("recommended_next_action", "integrity_rules")}).lower()
    for forbidden in ("politician_id", "party_id_internal", "internal_party", "winner", "office_bearer", "resolved_politician"):
        assert forbidden not in blob
    # every grouped record is explicitly unresolved
    for section in ("parties", "candidates", "geographies", "contests"):
        assert all(r["mapping_status"] == "unresolved" for r in report[section])


def test_json_and_markdown_output(db, tmp_path):
    _seed(db, [_vote(result_key="a")])
    report = build_report(db)
    json_path, md_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "available"
    md = md_path.read_text(encoding="utf-8")
    assert "IEC Unresolved Source Identifiers" in md
    assert "Recommended next action" in md


def test_redaction(db):
    _seed(db, [_vote(result_key="a", source_url="https://u:hunter2@results.elections.org.za/x.csv")])
    report = build_report(db)
    blob = json.dumps(report)
    assert "hunter2" not in blob
    assert redact("https://u:hunter2@h/x").count("[REDACTED]@") == 1


def test_no_db_writes(db):
    _seed(db, [_vote(result_key="a")])
    before = db.query(IECVoteTotal).count()
    build_report(db)
    build_report(db)
    assert db.query(IECVoteTotal).count() == before
