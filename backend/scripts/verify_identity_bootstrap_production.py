"""Run production-safe identity bootstrap verification.

The script never prints DATABASE_URL. It reports before/after table counts,
identity link coverage, and recent ingestion-run evidence as JSON so GitHub
Actions artifacts can be used as production verification records.
"""
from __future__ import annotations

import argparse
import json
from datetime import UTC, datetime
from pathlib import Path
import sys

from sqlalchemy import func, select

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.db import SessionLocal
from app.models.bill import Bill
from app.models.bill_event import BillEvent
from app.models.committee import Committee
from app.models.committee_attendance import CommitteeAttendance
from app.models.committee_meeting import CommitteeMeeting
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.ingestion_error import IngestionError
from app.models.ingestion_run import IngestionRun
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.politician import Politician
from app.models.question_mention import QuestionMention
from app.models.unresolved_entity import UnresolvedEntity
from app.models.vote_event import VoteEvent
from app.models.vote_record import VoteRecord
from scripts.identity_bootstrap_utils import run_pmg_identity_bootstrap


TABLES = {
    "politicians": Politician,
    "committees": Committee,
    "parliamentary_questions": ParliamentaryQuestion,
    "documents": Document,
    "bills": Bill,
    "bill_events": BillEvent,
    "committee_meetings": CommitteeMeeting,
    "committee_attendance": CommitteeAttendance,
    "vote_events": VoteEvent,
    "vote_records": VoteRecord,
    "ingestion_runs": IngestionRun,
    "ingestion_errors": IngestionError,
    "unresolved_entities": UnresolvedEntity,
}


def main() -> int:
    parser = argparse.ArgumentParser(description="Verify PMG identity bootstrap against the configured database.")
    parser.add_argument("--run-bootstrap", action="store_true", help="Execute PMG identity bootstrap between snapshots.")
    parser.add_argument("--output", default="reports/identity_bootstrap_verification.json")
    args = parser.parse_args()

    with SessionLocal() as db:
        before = snapshot(db)
        bootstrap = run_pmg_identity_bootstrap(db) if args.run_bootstrap else None
        after = snapshot(db)

    report = {
        "generated_at": datetime.now(UTC).isoformat(),
        "bootstrap_executed": bool(args.run_bootstrap),
        "bootstrap_summary": bootstrap,
        "before": before,
        "after": after,
        "deltas": {
            key: after["counts"][key] - before["counts"][key]
            for key in sorted(after["counts"])
        },
        "definition_of_done": {
            "politicians_nonzero": after["counts"]["politicians"] > 0,
            "committees_nonzero": after["counts"]["committees"] > 0,
            "attendance_has_identity_links": after["link_coverage"]["committee_attendance"]["linked_politician_count"] > 0,
            "questions_have_identity_links": after["link_coverage"]["parliamentary_questions"]["linked_politician_count"] > 0,
            "meetings_have_committee_links": after["link_coverage"]["committee_meetings"]["linked_committee_count"] > 0,
            "votes_have_committee_or_identity_links": (
                after["link_coverage"]["vote_events"]["linked_committee_count"] > 0
                or after["link_coverage"]["vote_records"]["linked_politician_count"] > 0
                or after["link_coverage"]["vote_records"]["linked_party_count"] > 0
            ),
        },
    }
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True, default=str) + "\n", encoding="utf-8")
    print(json.dumps(report, sort_keys=True, default=str))
    return 0 if all(report["definition_of_done"].values()) else 2


def snapshot(db) -> dict:
    return {
        "counts": {name: count_rows(db, model) for name, model in TABLES.items()},
        "link_coverage": link_coverage(db),
        "recent_identity_runs": recent_identity_runs(db),
        "identity_run_rollup": identity_run_rollup(db),
    }


def count_rows(db, model) -> int:
    return int(db.scalar(select(func.count()).select_from(model)) or 0)


def pct(numerator: int, denominator: int) -> float | None:
    if denominator == 0:
        return None
    return round(numerator * 100 / denominator, 2)


def link_coverage(db) -> dict:
    meetings_total = count_rows(db, CommitteeMeeting)
    meetings_linked = int(
        db.scalar(select(func.count()).select_from(CommitteeMeeting).where(CommitteeMeeting.committee_id.is_not(None)))
        or 0
    )
    attendance_total = count_rows(db, CommitteeAttendance)
    attendance_linked = int(
        db.scalar(select(func.count()).select_from(CommitteeAttendance).where(CommitteeAttendance.politician_id.is_not(None)))
        or 0
    )
    questions_total = count_rows(db, ParliamentaryQuestion)
    questions_linked = int(
        db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.politician_id.is_not(None))
        )
        or 0
    )
    vote_events_total = count_rows(db, VoteEvent)
    vote_events_linked = int(
        db.scalar(select(func.count()).select_from(VoteEvent).where(VoteEvent.committee_id.is_not(None))) or 0
    )
    vote_records_total = count_rows(db, VoteRecord)
    vote_records_politicians = int(
        db.scalar(select(func.count()).select_from(VoteRecord).where(VoteRecord.politician_id.is_not(None))) or 0
    )
    vote_records_parties = int(
        db.scalar(select(func.count()).select_from(VoteRecord).where(VoteRecord.party_id.is_not(None))) or 0
    )
    return {
        "committee_meetings": {
            "total": meetings_total,
            "linked_committee_count": meetings_linked,
            "linked_committee_pct": pct(meetings_linked, meetings_total),
        },
        "committee_attendance": {
            "total": attendance_total,
            "linked_politician_count": attendance_linked,
            "linked_politician_pct": pct(attendance_linked, attendance_total),
        },
        "parliamentary_questions": {
            "total": questions_total,
            "linked_politician_count": questions_linked,
            "linked_politician_pct": pct(questions_linked, questions_total),
            "question_mentions": count_rows(db, QuestionMention),
        },
        "vote_events": {
            "total": vote_events_total,
            "linked_committee_count": vote_events_linked,
            "linked_committee_pct": pct(vote_events_linked, vote_events_total),
        },
        "vote_records": {
            "total": vote_records_total,
            "linked_politician_count": vote_records_politicians,
            "linked_politician_pct": pct(vote_records_politicians, vote_records_total),
            "linked_party_count": vote_records_parties,
            "linked_party_pct": pct(vote_records_parties, vote_records_total),
        },
        "committee_memberships": {
            "total": count_rows(db, CommitteeMembership),
        },
        "pmg_derived_identities": {
            "politicians": int(
                db.scalar(select(func.count()).select_from(Politician).where(Politician.source_status == "PMG_DERIVED"))
                or 0
            ),
            "committees": int(
                db.scalar(
                    select(func.count()).select_from(Committee).where(Committee.source_url.ilike("%pmg.org.za%"))
                )
                or 0
            ),
        },
    }


def recent_identity_runs(db) -> list[dict]:
    runs = db.scalars(
        select(IngestionRun)
        .where(IngestionRun.run_type.in_(("bulk_people_assembly", "bulk_committees", "pmg_identity_bootstrap")))
        .order_by(IngestionRun.started_at.desc())
        .limit(20)
    )
    return [
        {
            "source_name": run.source_name,
            "run_type": run.run_type,
            "status": run.status,
            "started_at": run.started_at,
            "finished_at": run.finished_at,
            "attempted_count": run.attempted_count,
            "processed_count": run.processed_count,
            "created_count": run.created_count,
            "updated_count": run.updated_count,
            "failed_count": run.failed_count,
        }
        for run in runs
    ]


def identity_run_rollup(db) -> list[dict]:
    rows = db.execute(
        select(
            IngestionRun.source_name,
            IngestionRun.run_type,
            IngestionRun.status,
            func.count().label("runs"),
            func.coalesce(func.sum(IngestionRun.attempted_count), 0).label("attempted"),
            func.coalesce(func.sum(IngestionRun.processed_count), 0).label("processed"),
            func.coalesce(func.sum(IngestionRun.created_count), 0).label("created"),
            func.coalesce(func.sum(IngestionRun.updated_count), 0).label("updated"),
            func.coalesce(func.sum(IngestionRun.failed_count), 0).label("failed"),
        )
        .where(IngestionRun.run_type.in_(("bulk_people_assembly", "bulk_committees", "pmg_identity_bootstrap")))
        .group_by(IngestionRun.source_name, IngestionRun.run_type, IngestionRun.status)
        .order_by(IngestionRun.run_type, IngestionRun.status)
    )
    return [
        {
            "source_name": source_name,
            "run_type": run_type,
            "status": status,
            "runs": int(runs),
            "attempted": int(attempted),
            "processed": int(processed),
            "created": int(created),
            "updated": int(updated),
            "failed": int(failed),
        }
        for source_name, run_type, status, runs, attempted, processed, created, updated, failed in rows
    ]


if __name__ == "__main__":
    raise SystemExit(main())
