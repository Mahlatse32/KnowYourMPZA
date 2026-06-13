import json
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.party import Party
from app.models.politician import Politician
from scripts.report_data_coverage_dashboard import (
    build_report,
    collect_discovery_status,
    render_markdown,
    write_report_files,
)


REPO_ROOT = Path(__file__).resolve().parents[2]
ACCOUNTABILITY_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "accountability-sweep.yml"
SCHEDULED_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"


def _session(create_tables: bool = True):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    if create_tables:
        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def test_report_files_are_created_and_json_is_valid(tmp_path):
    with _session() as db:
        report = build_report(db)
    json_path, markdown_path = write_report_files(report, tmp_path)

    assert json_path.exists()
    assert markdown_path.exists()
    assert json.loads(json_path.read_text(encoding="utf-8"))["executive_summary"]["total_politicians"] == 0


def test_missing_tables_are_reported_as_unavailable():
    with _session(create_tables=False) as db:
        report = build_report(db)

    assert report["executive_summary"]["total_politicians"] is None
    assert report["availability"]["politicians"] == "unavailable"
    assert all(row["status"] == "unavailable" for row in report["source_coverage"])


def test_missing_source_url_is_counted():
    with _session() as db:
        party = Party(name="Evidence Test Party", short_name="ETP", source_url=None)
        db.add(party)
        db.flush()
        db.add(
            Politician(
                full_name="Evidence Test Person",
                display_name="Evidence Test",
                slug="evidence-test-person",
                party=party,
                profile_url=None,
            )
        )
        db.commit()
        report = build_report(db)

    people = next(row for row in report["source_coverage"] if row["source"] == "People's Assembly")
    assert people["records_count"] == 2
    assert people["records_missing_source_url"] == 2
    assert next(risk for risk in report["data_quality_risks"] if risk["risk"] == "Missing source URLs")["level"] == "red"


def test_markdown_contains_required_sections_and_next_actions():
    with _session() as db:
        markdown = render_markdown(build_report(db))

    assert "# Data Coverage Dashboard" in markdown
    assert "## Executive Summary" in markdown
    assert "## Source Coverage" in markdown
    assert "## Accountability Coverage" in markdown
    assert "## Data Quality Risk Table" in markdown
    assert "## Next Recommended Ingestion Actions" in markdown


def test_report_does_not_include_secrets():
    with _session() as db:
        report = build_report(db)
    blob = json.dumps(report)

    assert "DATABASE_URL" not in blob
    assert "password" not in blob.lower()
    assert "postgresql://" not in blob


def test_workflows_run_dashboard_non_blocking():
    accountability = ACCOUNTABILITY_WORKFLOW.read_text(encoding="utf-8")
    scheduled = SCHEDULED_WORKFLOW.read_text(encoding="utf-8")

    assert "python scripts/report_data_coverage_dashboard.py || true" in accountability
    assert scheduled.count("python scripts/report_data_coverage_dashboard.py || true") == 2


def test_collect_discovery_status_none_and_missing(tmp_path):
    assert collect_discovery_status(None) == []
    assert collect_discovery_status(tmp_path / "does-not-exist") == []


def test_collect_discovery_status_reads_discovery_reports(tmp_path):
    (tmp_path / "iec_source_discovery.json").write_text(
        json.dumps({"source": "IEC", "status": "discovery-only", "total_sources": 4, "reachable_count": 3,
                    "sources": [1, 2, 3, 4]}),
        encoding="utf-8",
    )
    statuses = collect_discovery_status(tmp_path)
    assert len(statuses) == 1
    assert statuses[0]["source"] == "IEC"
    assert statuses[0]["sources_listed"] == 4
    assert statuses[0]["ingested"] is False


def test_dashboard_markdown_has_discovery_section():
    session = _session()
    try:
        markdown = render_markdown(build_report(session))
    finally:
        session.close()
    assert "## Source Discovery Status" in markdown


def test_iec_coverage_available_when_tables_exist():
    session = _session()  # creates all tables incl. iec_*
    try:
        report = build_report(session)
    finally:
        session.close()
    iec = report["iec_coverage"]
    assert iec["status"] == "available"
    assert iec["iec_elections_count"] == 0
    assert iec["iec_source_manifests_count"] == 0
    assert iec["vote_totals_ingested"] is False
    assert "## IEC Coverage" in render_markdown(report)


def test_iec_coverage_unavailable_when_tables_missing():
    session = _session(create_tables=False)
    try:
        report = build_report(session)
    finally:
        session.close()
    assert report["iec_coverage"]["status"] == "unavailable"
    assert report["iec_coverage"]["vote_totals_ingested"] is False
