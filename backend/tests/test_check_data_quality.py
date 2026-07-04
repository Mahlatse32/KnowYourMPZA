import json
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import Base
from app.models.committee import Committee
from app.models.committee_meeting import CommitteeMeeting
from app.models.ingestion_run import IngestionRun
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.models.unresolved_entity import UnresolvedEntity
from scripts.check_data_quality import build_report, render_markdown, write_report

REPO_ROOT = Path(__file__).resolve().parents[2]
SCHEDULED_WORKFLOW = REPO_ROOT / ".github" / "workflows" / "scheduled-ingestion.yml"

NOW = datetime(2026, 7, 4, 12, 0, 0, tzinfo=UTC)


def _session(create_tables: bool = True):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    if create_tables:
        Base.metadata.create_all(engine)
    return sessionmaker(bind=engine)()


def _check(report: dict, name: str) -> dict:
    return next(check for check in report["checks"] if check["name"] == name)


def _completed_run(source_name: str = "PMG", started_at: datetime | None = None) -> IngestionRun:
    started = started_at or (NOW - timedelta(hours=6))
    return IngestionRun(
        source_name=source_name,
        run_type="scheduled",
        started_at=started,
        finished_at=started + timedelta(minutes=30),
        status="completed",
    )


def test_empty_database_with_recent_run_passes():
    with _session() as db:
        db.add(_completed_run())
        db.commit()
        report = build_report(db, now=NOW)

    assert report["overall_status"] == "pass"
    assert report["summary"]["checks_fail"] == 0
    assert report["summary"]["checks_warn"] == 0
    assert report["summary"]["checks_total"] == report["summary"]["checks_pass"]


def test_missing_tables_fail_instead_of_passing():
    with _session(create_tables=False) as db:
        report = build_report(db, now=NOW)

    assert report["overall_status"] == "fail"
    assert all(check["status"] == "fail" for check in report["checks"])
    assert "never treated as passing" in report["checks"][0]["detail"]


def test_failed_run_inside_window_warns_and_old_failed_run_does_not():
    with _session() as db:
        db.add(_completed_run())
        failed = _completed_run(started_at=NOW - timedelta(days=2))
        failed.status = "failed"
        old_failed = _completed_run(started_at=NOW - timedelta(days=30))
        old_failed.status = "failed"
        db.add_all([failed, old_failed])
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "failed ingestion runs")
    assert check["status"] == "warn"
    assert check["value"] == 1


def test_stuck_running_run_fails():
    with _session() as db:
        db.add(_completed_run())
        stuck = IngestionRun(
            source_name="PMG",
            run_type="scheduled",
            started_at=NOW - timedelta(days=3),
            status="running",
        )
        db.add(stuck)
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "stuck ingestion runs")
    assert check["status"] == "fail"
    assert check["value"] == 1
    assert report["overall_status"] == "fail"


def test_stale_source_is_flagged_with_source_name():
    with _session() as db:
        db.add(_completed_run(source_name="PMG"))
        db.add(_completed_run(source_name="People's Assembly", started_at=NOW - timedelta(days=30)))
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "stale ingestion sources")
    assert check["status"] == "warn"
    assert check["value"] == 1
    assert "People's Assembly" in check["detail"]
    assert "PMG" not in check["detail"].replace("People's Assembly", "")


def test_source_with_only_failed_runs_is_stale():
    with _session() as db:
        db.add(_completed_run(source_name="PMG"))
        failed_only = _completed_run(source_name="Parliament", started_at=NOW - timedelta(hours=2))
        failed_only.status = "failed"
        db.add(failed_only)
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "stale ingestion sources")
    assert check["status"] == "warn"
    assert "Parliament" in check["detail"]
    assert "never" in check["detail"]


def test_orphan_percentage_thresholds():
    with _session() as db:
        db.add(_completed_run())
        committee = Committee(name="Portfolio Committee on Testing", slug="pc-testing")
        db.add(committee)
        db.flush()
        for index in range(4):
            db.add(
                CommitteeMeeting(
                    committee_id=committee.id if index == 0 else None,
                    title=f"Meeting {index}",
                    source_url=f"https://pmg.org.za/committee-meeting/{index}/",
                )
            )
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "committee meetings without a committee link")
    assert check["status"] == "fail"
    assert check["value"] == {"unlinked": 3, "total": 4, "unlinked_pct": 75.0}

    membership_check = _check(report, "committees without memberships")
    assert membership_check["status"] == "warn"
    assert membership_check["value"] == 1


def test_unlinked_questions_warn_between_thresholds():
    with _session() as db:
        db.add(_completed_run())
        party = Party(name="Test Party", short_name="TP")
        db.add(party)
        db.flush()
        politician = Politician(
            full_name="Test Person",
            display_name="T. Person",
            slug="test-person",
            party_id=party.id,
        )
        db.add(politician)
        db.flush()
        for index in range(10):
            db.add(
                ParliamentaryQuestion(
                    question_number=f"NW{index}",
                    politician_id=politician.id if index < 8 else None,
                    source_url=f"https://questions.example/{index}",
                )
            )
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "questions without a politician link")
    assert check["status"] == "warn"
    assert check["value"]["unlinked_pct"] == 20.0


def test_duplicate_group_detection_counts_groups():
    from scripts.check_data_quality import _Checker

    with _session() as db:
        db.add_all(
            [
                Committee(name="Same Name", slug="slug-one"),
                Committee(name="Same Name", slug="slug-two"),
                Committee(name="Other Name", slug="slug-three"),
            ]
        )
        db.commit()
        checker = _Checker(db, NOW)
        assert checker.duplicate_groups(Committee, Committee.name) == 1


def test_unresolved_entity_thresholds():
    def _entity(index: int) -> UnresolvedEntity:
        return UnresolvedEntity(
            source_name="PMG",
            raw_value=f"Unknown Person {index}",
            entity_type="politician",
            status="OPEN",
        )

    with _session() as db:
        db.add(_completed_run())
        db.add(_entity(0))
        db.commit()
        warn_report = build_report(db, now=NOW)
        db.add_all([_entity(index) for index in range(1, 60)])
        db.commit()
        fail_report = build_report(db, now=NOW)

    assert _check(warn_report, "open unresolved entities")["status"] == "warn"
    fail_check = _check(fail_report, "open unresolved entities")
    assert fail_check["status"] == "fail"
    assert fail_check["value"] == 60


def test_blank_mandatory_name_fails():
    with _session() as db:
        db.add(_completed_run())
        db.add(Committee(name="   ", slug="blank-name"))
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "committees with a blank name")
    assert check["status"] == "fail"
    assert check["value"] == 1
    assert report["overall_status"] == "fail"


def test_missing_source_url_fails():
    with _session() as db:
        db.add(_completed_run())
        db.add(CommitteeMeeting(title="No URL meeting", source_url=None))
        db.commit()
        report = build_report(db, now=NOW)

    check = _check(report, "committee meetings missing a source URL")
    assert check["status"] == "fail"
    assert check["value"] == 1


def test_report_files_are_written_and_secret_safe(tmp_path):
    with _session() as db:
        db.add(_completed_run())
        db.commit()
        report = build_report(db, now=NOW)

    json_path, markdown_path = write_report(report, tmp_path)
    blob = json_path.read_text(encoding="utf-8") + markdown_path.read_text(encoding="utf-8")
    payload = json.loads(json_path.read_text(encoding="utf-8"))

    assert payload["overall_status"] == "pass"
    assert "# Data Quality Checks" in blob
    assert "DATABASE_URL" not in blob
    assert "postgresql://" not in blob
    assert "password" not in blob.lower()


def test_markdown_renders_every_check_row():
    with _session() as db:
        db.add(_completed_run())
        db.commit()
        report = build_report(db, now=NOW)

    markdown = render_markdown(report)
    assert "| Status | Category | Check | Value | Threshold | Detail |" in markdown
    for check in report["checks"]:
        assert check["name"] in markdown


def test_scheduled_workflow_runs_checks_non_blocking():
    scheduled = SCHEDULED_WORKFLOW.read_text(encoding="utf-8")
    assert scheduled.count("python scripts/check_data_quality.py --json-only || true") == 2
