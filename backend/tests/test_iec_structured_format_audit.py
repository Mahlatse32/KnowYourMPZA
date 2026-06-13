import json
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.iec_source_manifest import IECSourceManifest
from scripts.audit_iec_structured_formats import build_report, load_fixture, write_report


FIXTURE = Path(__file__).parent / "fixtures" / "iec" / "structured_format_audit.json"


def test_offline_fixture_produces_json_and_markdown(tmp_path):
    report = build_report(load_fixture(FIXTURE))
    json_path, markdown_path = write_report(report, tmp_path)
    assert json.loads(json_path.read_text(encoding="utf-8"))["status"] == "audit-only"
    assert "# IEC Structured Source Format Audit" in markdown_path.read_text(encoding="utf-8")


def test_structured_formats_are_prioritized():
    report = build_report(load_fixture(FIXTURE))
    assert report["candidates"][0]["source_type"] == "csv"
    assert report["candidates"][0]["recommended_parser_priority"] == 1
    assert report["selected_parser_candidate"]["source_type"] == "csv"


def test_non_structured_format_is_not_parse_ready():
    pdf = next(item for item in build_report(load_fixture(FIXTURE))["candidates"] if item["source_type"] == "pdf")
    assert pdf["parser_readiness"] == "not-safe"
    assert pdf["recommended_parser_priority"] is None


def test_missing_vote_columns_are_not_safe():
    candidate = next(
        item for item in build_report(load_fixture(FIXTURE))["candidates"] if item["source_type"] == "json"
    )
    assert candidate["vote_total_columns_detectable"] is False
    assert candidate["parser_readiness"] == "not-safe"


def test_audit_performs_no_database_writes():
    engine = create_engine("sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    db = sessionmaker(bind=engine)()
    before = db.scalar(select(func.count()).select_from(IECSourceManifest))
    report = build_report(load_fixture(FIXTURE))
    after = db.scalar(select(func.count()).select_from(IECSourceManifest))
    assert before == after == 0
    assert report["database_writes"] == 0
    assert report["vote_totals_ingested"] is False
    db.close()


def test_secrets_are_redacted():
    report = build_report(
        [{
            "manifest_key": "DATABASE_URL=postgresql://user:password@db.example/test",
            "source_url": "https://user:password@results.elections.org.za/results.csv",
            "source_type": "csv",
            "columns": ["Contest_ID", "Party_ID", "Votes"],
        }]
    )
    blob = json.dumps(report)
    assert "password" not in blob
    assert "user:password" not in blob
    assert "[REDACTED]" in blob
