#!/usr/bin/env python3
"""Callable V1 data quality gate.

Runs the launch-checklist data quality checks in one place: duplicate
identifiers, open unresolved entities, failed ingestion runs, stuck
ingestion runs, stale per-source data, orphaned relationships, and
mandatory-field completeness. Writes reports/data_quality_checks.json and
reports/data_quality_checks.md and exits non-zero when any check fails, so
it is callable both from operators' shells and from scheduled workflows
(where it is invoked non-blocking like the other report steps).
"""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import String, func, inspect, or_, select
from sqlalchemy.exc import SQLAlchemyError

PASS = "pass"
WARN = "warn"
FAIL = "fail"

DEFAULT_FAILED_RUN_WINDOW_DAYS = 7
DEFAULT_STALE_DATA_MAX_AGE_DAYS = 7
DEFAULT_STUCK_RUN_MAX_AGE_HOURS = 24
UNRESOLVED_FAIL_THRESHOLD = 50
ORPHAN_WARN_PCT = 10.0
ORPHAN_FAIL_PCT = 50.0


def _models() -> dict[str, object]:
    from app.models.committee import Committee
    from app.models.committee_attendance import CommitteeAttendance
    from app.models.committee_meeting import CommitteeMeeting
    from app.models.committee_membership import CommitteeMembership
    from app.models.document import Document
    from app.models.ingestion_run import IngestionRun
    from app.models.parliamentary_question import ParliamentaryQuestion
    from app.models.party import Party
    from app.models.politician import Politician
    from app.models.unresolved_entity import UnresolvedEntity
    from app.models.vote_event import VoteEvent
    from app.models.vote_record import VoteRecord

    return {
        "politicians": Politician,
        "parties": Party,
        "committees": Committee,
        "committee_memberships": CommitteeMembership,
        "committee_meetings": CommitteeMeeting,
        "committee_attendance": CommitteeAttendance,
        "vote_events": VoteEvent,
        "vote_records": VoteRecord,
        "parliamentary_questions": ParliamentaryQuestion,
        "documents": Document,
        "ingestion_runs": IngestionRun,
        "unresolved_entities": UnresolvedEntity,
    }


class _Checker:
    def __init__(self, db, now: datetime):
        self.db = db
        self.now = now
        self.checks: list[dict] = []
        self.models = _models()
        inspector = inspect(db.get_bind())
        self.available = {
            key: inspector.has_table(model.__tablename__) for key, model in self.models.items()
        }

    def add(self, category: str, name: str, status: str, value, threshold: str, detail: str) -> None:
        self.checks.append(
            {
                "category": category,
                "name": name,
                "status": status,
                "value": value,
                "threshold": threshold,
                "detail": detail,
            }
        )

    def unavailable(self, category: str, name: str, table: str) -> None:
        self.add(
            category,
            name,
            FAIL,
            None,
            "table must exist",
            f"Table '{table}' is unavailable; missing data is never treated as passing.",
        )

    def scalar(self, statement) -> int:
        try:
            return int(self.db.scalar(statement) or 0)
        except SQLAlchemyError:
            self.db.rollback()
            return 0

    def count(self, model, *conditions) -> int:
        statement = select(func.count()).select_from(model)
        for condition in conditions:
            statement = statement.where(condition)
        return self.scalar(statement)

    def duplicate_groups(self, model, column) -> int:
        subquery = (
            select(column)
            .where(column.is_not(None))
            .group_by(column)
            .having(func.count() > 1)
            .subquery()
        )
        return self.scalar(select(func.count()).select_from(subquery))


def _is_blank(column):
    return or_(column.is_(None), func.trim(func.cast(column, String)) == "")


def _pct(numerator: int, denominator: int) -> float:
    return round(numerator * 100 / denominator, 2) if denominator else 0.0


def _check_duplicates(checker: _Checker) -> None:
    specs = (
        ("politicians", "slug", "duplicate politician slugs"),
        ("committees", "slug", "duplicate committee slugs"),
        ("parties", "short_name", "duplicate party short names"),
        ("documents", "source_url", "duplicate document source URLs"),
        ("parliamentary_questions", "source_url", "duplicate question source URLs"),
        ("vote_events", "source_url", "duplicate vote event source URLs"),
        ("committee_meetings", "source_url", "duplicate committee meeting source URLs"),
    )
    for table, field, name in specs:
        if not checker.available[table]:
            checker.unavailable("duplicates", name, table)
            continue
        model = checker.models[table]
        value = checker.duplicate_groups(model, getattr(model, field))
        checker.add(
            "duplicates",
            name,
            PASS if value == 0 else FAIL,
            value,
            "0 duplicate groups",
            f"Duplicate values of {table}.{field} break stable identity and require review.",
        )

    if checker.available["committee_memberships"]:
        model = checker.models["committee_memberships"]
        subquery = (
            select(model.politician_id, model.committee_id, model.role)
            .group_by(model.politician_id, model.committee_id, model.role)
            .having(func.count() > 1)
            .subquery()
        )
        value = checker.scalar(select(func.count()).select_from(subquery))
        checker.add(
            "duplicates",
            "duplicate committee membership tuples",
            PASS if value == 0 else FAIL,
            value,
            "0 duplicate groups",
            "The same (politician, committee, role) tuple must not repeat.",
        )
    else:
        checker.unavailable("duplicates", "duplicate committee membership tuples", "committee_memberships")


def _check_unresolved(checker: _Checker) -> None:
    name = "open unresolved entities"
    if not checker.available["unresolved_entities"]:
        checker.unavailable("unresolved_entities", name, "unresolved_entities")
        return
    model = checker.models["unresolved_entities"]
    value = checker.count(model, model.status == "OPEN")
    if value > UNRESOLVED_FAIL_THRESHOLD:
        status = FAIL
    elif value > 0:
        status = WARN
    else:
        status = PASS
    checker.add(
        "unresolved_entities",
        name,
        status,
        value,
        f"warn above 0, fail above {UNRESOLVED_FAIL_THRESHOLD}",
        "Open unresolved entities limit reliable entity-level attribution.",
    )


def _check_ingestion_runs(
    checker: _Checker,
    failed_run_window_days: int,
    stale_data_max_age_days: int,
    stuck_run_max_age_hours: int,
) -> None:
    if not checker.available["ingestion_runs"]:
        checker.unavailable("ingestion_runs", "failed ingestion runs", "ingestion_runs")
        checker.unavailable("ingestion_runs", "stuck ingestion runs", "ingestion_runs")
        checker.unavailable("stale_data", "stale ingestion sources", "ingestion_runs")
        return

    model = checker.models["ingestion_runs"]
    window_start = checker.now - timedelta(days=failed_run_window_days)
    failed_recent = checker.count(model, model.status == "failed", model.started_at >= window_start)
    checker.add(
        "ingestion_runs",
        "failed ingestion runs",
        PASS if failed_recent == 0 else WARN,
        failed_recent,
        f"0 failed runs in the last {failed_run_window_days} days",
        "Failed runs must be triaged; soft per-record failures do not mark a run failed.",
    )

    stuck_cutoff = checker.now - timedelta(hours=stuck_run_max_age_hours)
    stuck = checker.count(model, model.status == "running", model.started_at < stuck_cutoff)
    checker.add(
        "ingestion_runs",
        "stuck ingestion runs",
        PASS if stuck == 0 else FAIL,
        stuck,
        f"0 runs still 'running' after {stuck_run_max_age_hours} hours",
        "Runs stuck in 'running' indicate an interrupted job that never finalized.",
    )

    try:
        source_rows = checker.db.execute(
            select(
                model.source_name,
                func.max(model.started_at).filter(model.status == "completed"),
                func.max(model.started_at),
            ).group_by(model.source_name)
        ).all()
    except SQLAlchemyError:
        checker.db.rollback()
        source_rows = []

    stale_cutoff = checker.now - timedelta(days=stale_data_max_age_days)
    stale_sources = []
    for source_name, last_completed, _last_any in source_rows:
        last = _as_utc(last_completed)
        if last is None or last < stale_cutoff:
            stale_sources.append(
                f"{source_name} (last completed run: {last.isoformat() if last else 'never'})"
            )
    checker.add(
        "stale_data",
        "stale ingestion sources",
        PASS if not stale_sources else WARN,
        len(stale_sources),
        f"every historically ingested source has a completed run within {stale_data_max_age_days} days",
        "; ".join(stale_sources) if stale_sources else "All ingested sources have a recent completed run.",
    )


def _check_orphans(checker: _Checker) -> None:
    fk_specs = (
        ("committee_meetings", "committee_id", "committee meetings without a committee link"),
        ("committee_attendance", "politician_id", "attendance rows without a politician link"),
        ("vote_records", "politician_id", "vote records without a politician link"),
        ("parliamentary_questions", "politician_id", "questions without a politician link"),
    )
    for table, field, name in fk_specs:
        if not checker.available[table]:
            checker.unavailable("orphans", name, table)
            continue
        model = checker.models[table]
        total = checker.count(model)
        unlinked = checker.count(model, getattr(model, field).is_(None))
        pct = _pct(unlinked, total)
        if pct > ORPHAN_FAIL_PCT:
            status = FAIL
        elif pct > ORPHAN_WARN_PCT:
            status = WARN
        else:
            status = PASS
        checker.add(
            "orphans",
            name,
            status,
            {"unlinked": unlinked, "total": total, "unlinked_pct": pct},
            f"warn above {ORPHAN_WARN_PCT}% unlinked, fail above {ORPHAN_FAIL_PCT}%",
            f"{table}.{field} is NULL when the source name could not be resolved to an identity.",
        )

    if checker.available["committees"] and checker.available["committee_memberships"]:
        committee = checker.models["committees"]
        membership = checker.models["committee_memberships"]
        value = checker.count(
            committee,
            committee.id.not_in(select(membership.committee_id).distinct()),
        )
        checker.add(
            "orphans",
            "committees without memberships",
            PASS if value == 0 else WARN,
            value,
            "0 childless committees",
            "Committees with no memberships render empty pages and need membership backfill.",
        )
    else:
        checker.unavailable("orphans", "committees without memberships", "committees/committee_memberships")


def _check_mandatory_fields(checker: _Checker) -> None:
    blank_specs = (
        ("politicians", "full_name", "politicians with a blank full name"),
        ("politicians", "display_name", "politicians with a blank display name"),
        ("committees", "name", "committees with a blank name"),
        ("parties", "name", "parties with a blank name"),
    )
    for table, field, name in blank_specs:
        if not checker.available[table]:
            checker.unavailable("mandatory_fields", name, table)
            continue
        model = checker.models[table]
        value = checker.count(model, _is_blank(getattr(model, field)))
        checker.add(
            "mandatory_fields",
            name,
            PASS if value == 0 else FAIL,
            value,
            "0 blank values",
            f"{table}.{field} is mandatory for public display.",
        )

    if checker.available["politicians"]:
        model = checker.models["politicians"]
        value = checker.count(model, model.party_id.is_(None))
        checker.add(
            "mandatory_fields",
            "politicians without a party",
            PASS if value == 0 else WARN,
            value,
            "0 politicians without a party link",
            "Party affiliation is a core public promise; missing links need source-backed backfill.",
        )
    else:
        checker.unavailable("mandatory_fields", "politicians without a party", "politicians")

    url_specs = (
        ("committee_meetings", "committee meetings missing a source URL"),
        ("parliamentary_questions", "questions missing a source URL"),
        ("vote_events", "vote events missing a source URL"),
        ("documents", "documents missing a source URL"),
    )
    for table, name in url_specs:
        if not checker.available[table]:
            checker.unavailable("mandatory_fields", name, table)
            continue
        model = checker.models[table]
        value = checker.count(model, _is_blank(model.source_url))
        checker.add(
            "mandatory_fields",
            name,
            PASS if value == 0 else FAIL,
            value,
            "0 records missing source evidence",
            "Every public record must retain a direct source URL.",
        )


def build_report(
    db,
    now: datetime | None = None,
    failed_run_window_days: int = DEFAULT_FAILED_RUN_WINDOW_DAYS,
    stale_data_max_age_days: int = DEFAULT_STALE_DATA_MAX_AGE_DAYS,
    stuck_run_max_age_hours: int = DEFAULT_STUCK_RUN_MAX_AGE_HOURS,
) -> dict:
    now = _as_utc(now) or datetime.now(UTC)
    checker = _Checker(db, now)
    _check_duplicates(checker)
    _check_unresolved(checker)
    _check_ingestion_runs(checker, failed_run_window_days, stale_data_max_age_days, stuck_run_max_age_hours)
    _check_orphans(checker)
    _check_mandatory_fields(checker)

    statuses = [check["status"] for check in checker.checks]
    if FAIL in statuses:
        overall = FAIL
    elif WARN in statuses:
        overall = WARN
    else:
        overall = PASS
    return {
        "generated_at": now.isoformat(),
        "overall_status": overall,
        "summary": {
            "checks_total": len(checker.checks),
            "checks_pass": statuses.count(PASS),
            "checks_warn": statuses.count(WARN),
            "checks_fail": statuses.count(FAIL),
        },
        "thresholds": {
            "failed_run_window_days": failed_run_window_days,
            "stale_data_max_age_days": stale_data_max_age_days,
            "stuck_run_max_age_hours": stuck_run_max_age_hours,
            "unresolved_fail_threshold": UNRESOLVED_FAIL_THRESHOLD,
            "orphan_warn_pct": ORPHAN_WARN_PCT,
            "orphan_fail_pct": ORPHAN_FAIL_PCT,
        },
        "checks": checker.checks,
    }


def render_markdown(report: dict) -> str:
    lines = [
        "# Data Quality Checks",
        "",
        f"- **Generated:** {report['generated_at']}",
        f"- **Overall status:** {report['overall_status']}",
        f"- **Pass / warn / fail:** {report['summary']['checks_pass']} / "
        f"{report['summary']['checks_warn']} / {report['summary']['checks_fail']}",
        "",
        "| Status | Category | Check | Value | Threshold | Detail |",
        "|---|---|---|---|---|---|",
    ]
    for check in report["checks"]:
        value = check["value"]
        if isinstance(value, dict):
            value = ", ".join(f"{key}={item}" for key, item in value.items())
        lines.append(
            f"| {check['status'].upper()} | {check['category']} | {check['name']} | "
            f"{value if value is not None else 'unavailable'} | {check['threshold']} | {check['detail']} |"
        )
    lines.append("")
    return "\n".join(lines)


def write_report(report: dict, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "data_quality_checks.json"
    markdown_path = directory / "data_quality_checks.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def _as_utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def main() -> int:
    parser = argparse.ArgumentParser(description="Run the callable V1 data quality checks.")
    parser.add_argument("--reports-dir", default="reports")
    parser.add_argument("--failed-run-window-days", type=int, default=DEFAULT_FAILED_RUN_WINDOW_DAYS)
    parser.add_argument("--stale-data-max-age-days", type=int, default=DEFAULT_STALE_DATA_MAX_AGE_DAYS)
    parser.add_argument("--stuck-run-max-age-hours", type=int, default=DEFAULT_STUCK_RUN_MAX_AGE_HOURS)
    parser.add_argument("--json-only", action="store_true")
    args = parser.parse_args()

    from app.db import SessionLocal

    with SessionLocal() as db:
        report = build_report(
            db,
            failed_run_window_days=args.failed_run_window_days,
            stale_data_max_age_days=args.stale_data_max_age_days,
            stuck_run_max_age_hours=args.stuck_run_max_age_hours,
        )
    json_path, markdown_path = write_report(report, args.reports_dir)
    if args.json_only:
        print(
            json.dumps(
                {
                    "overall_status": report["overall_status"],
                    "json_report": str(json_path),
                    "markdown_report": str(markdown_path),
                },
                sort_keys=True,
            )
        )
    else:
        print(render_markdown(report))
    return 1 if report["overall_status"] == FAIL else 0


if __name__ == "__main__":
    raise SystemExit(main())
