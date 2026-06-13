#!/usr/bin/env python3
"""Generate machine-readable and Markdown data coverage dashboards."""

import importlib
import json
from datetime import UTC, date, datetime
from pathlib import Path
import sys
from typing import Callable

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import String, func, inspect, or_, select
from sqlalchemy.exc import SQLAlchemyError


MODEL_SPECS = {
    "politicians": ("app.models.politician", "Politician"),
    "parties": ("app.models.party", "Party"),
    "committees": ("app.models.committee", "Committee"),
    "bills": ("app.models.bill", "Bill"),
    "bill_events": ("app.models.bill_event", "BillEvent"),
    "vote_events": ("app.models.vote_event", "VoteEvent"),
    "vote_records": ("app.models.vote_record", "VoteRecord"),
    "committee_meetings": ("app.models.committee_meeting", "CommitteeMeeting"),
    "committee_attendance": ("app.models.committee_attendance", "CommitteeAttendance"),
    "parliamentary_questions": ("app.models.parliamentary_question", "ParliamentaryQuestion"),
    "documents": ("app.models.document", "Document"),
    "unresolved_entities": ("app.models.unresolved_entity", "UnresolvedEntity"),
}

EXECUTIVE_MODELS = {
    "total_politicians": "politicians",
    "total_parties": "parties",
    "total_committees": "committees",
    "total_bills": "bills",
    "total_bill_events": "bill_events",
    "total_vote_events": "vote_events",
    "total_vote_records": "vote_records",
    "total_committee_meetings": "committee_meetings",
    "total_attendance_records": "committee_attendance",
    "total_parliamentary_questions": "parliamentary_questions",
    "total_source_documents": "documents",
}


class ModelAccess:
    def __init__(self, db, model_loader: Callable[[str], object | None] | None = None):
        self.db = db
        self.model_loader = model_loader or load_model
        self.inspector = inspect(db.get_bind())
        self._models: dict[str, object | None] = {}

    def model(self, key: str):
        if key not in self._models:
            model = self.model_loader(key)
            if model is None or not self.inspector.has_table(model.__tablename__):
                model = None
            self._models[key] = model
        return self._models[key]

    def count(self, key: str, where=None) -> int | None:
        model = self.model(key)
        if model is None:
            return None
        statement = select(func.count()).select_from(model)
        if where is not None:
            statement = statement.where(where)
        try:
            return int(self.db.scalar(statement) or 0)
        except SQLAlchemyError:
            self.db.rollback()
            return None

    def coverage(
        self,
        key: str,
        *,
        source_url_field: str | None,
        source_date_field: str | None,
        identity_fields: tuple[str, ...],
        where=None,
    ) -> dict:
        model = self.model(key)
        if model is None:
            return _unavailable_metric(key)
        total = self.count(key, where)
        if total is None:
            return _unavailable_metric(key)

        metric = {
            "domain": key,
            "status": "available",
            "records_count": total,
            "earliest_source_date": None,
            "latest_source_date": None,
            "records_missing_source_url": None,
            "records_missing_source_date": None,
            "source_date_applicable_count": 0,
            "records_missing_identity": 0,
        }
        if source_url_field and hasattr(model, source_url_field):
            column = getattr(model, source_url_field)
            metric["records_missing_source_url"] = self._count_missing(model, column, where)
        if source_date_field and hasattr(model, source_date_field):
            column = getattr(model, source_date_field)
            metric["records_missing_source_date"] = self._count_missing(model, column, where)
            metric["source_date_applicable_count"] = total
            metric["earliest_source_date"], metric["latest_source_date"] = self._date_range(model, column, where)

        identity_columns = [getattr(model, name) for name in identity_fields if hasattr(model, name)]
        if identity_columns:
            missing_identity = or_(*[_is_blank(column) for column in identity_columns])
            metric["records_missing_identity"] = self._count_where(model, missing_identity, where)
        return metric

    def duplicate_groups(self, key: str, field: str) -> int | None:
        model = self.model(key)
        if model is None or not hasattr(model, field):
            return None
        column = getattr(model, field)
        subquery = (
            select(column)
            .where(column.is_not(None))
            .group_by(column)
            .having(func.count() > 1)
            .subquery()
        )
        try:
            return int(self.db.scalar(select(func.count()).select_from(subquery)) or 0)
        except SQLAlchemyError:
            self.db.rollback()
            return None

    def unresolved_count(self, source_names: tuple[str, ...] | None = None) -> int | None:
        model = self.model("unresolved_entities")
        if model is None:
            return None
        if source_names == ():
            return 0
        where = model.status == "OPEN"
        if source_names:
            where = where & model.source_name.in_(source_names)
        return self.count("unresolved_entities", where)

    def _count_missing(self, model, column, where) -> int:
        return self._count_where(model, _is_blank(column), where)

    def _count_where(self, model, condition, where) -> int:
        statement = select(func.count()).select_from(model).where(condition)
        if where is not None:
            statement = statement.where(where)
        try:
            return int(self.db.scalar(statement) or 0)
        except SQLAlchemyError:
            self.db.rollback()
            return 0

    def _date_range(self, model, column, where) -> tuple[str | None, str | None]:
        statement = select(func.min(column), func.max(column)).select_from(model)
        if where is not None:
            statement = statement.where(where)
        try:
            earliest, latest = self.db.execute(statement).one()
        except SQLAlchemyError:
            self.db.rollback()
            return None, None
        return _iso(earliest), _iso(latest)


def load_model(key: str):
    spec = MODEL_SPECS.get(key)
    if spec is None:
        return None
    try:
        module = importlib.import_module(spec[0])
        return getattr(module, spec[1])
    except (ImportError, AttributeError):
        return None


def build_report(db, model_loader: Callable[[str], object | None] | None = None) -> dict:
    access = ModelAccess(db, model_loader)
    executive_summary = {}
    availability = {}
    for output_key, model_key in EXECUTIVE_MODELS.items():
        count = access.count(model_key)
        executive_summary[output_key] = count
        availability[model_key] = "available" if count is not None else "unavailable"

    people_metrics = [
        access.coverage(
            "politicians",
            source_url_field="profile_url",
            source_date_field="source_last_seen_at",
            identity_fields=("full_name", "slug"),
        ),
        access.coverage(
            "parties",
            source_url_field="source_url",
            source_date_field="source_last_seen_at",
            identity_fields=("name", "short_name"),
        ),
        access.coverage(
            "committees",
            source_url_field="source_url",
            source_date_field="source_last_seen_at",
            identity_fields=("name", "slug"),
        ),
    ]

    document_model = access.model("documents")
    pmg_filter = document_model.document_type.like("PMG%") if document_model is not None else None
    pmg_documents = access.coverage(
        "documents",
        source_url_field="source_url",
        source_date_field="publication_date",
        identity_fields=("title",),
        where=pmg_filter,
    )
    all_documents = access.coverage(
        "documents",
        source_url_field="source_url",
        source_date_field="publication_date",
        identity_fields=("title",),
    )

    meeting_model = access.model("committee_meetings")
    meeting_filter = None
    if meeting_model is not None:
        meeting_filter = or_(
            meeting_model.source_url.ilike("%pmg.org.za%"),
            meeting_model.pmg_url.is_not(None),
        )
    pmg_meetings = access.coverage(
        "committee_meetings",
        source_url_field="source_url",
        source_date_field="date",
        identity_fields=("title",),
        where=meeting_filter,
    )

    questions = access.coverage(
        "parliamentary_questions",
        source_url_field="source_url",
        source_date_field="asked_date",
        identity_fields=("question_number", "title"),
    )

    official_metrics = []
    for key, date_field, identity_fields in (
        ("bills", "introduced_date", ("bill_number", "title")),
        ("bill_events", "event_date", ("event_type",)),
        ("vote_events", "date", ("title",)),
    ):
        model = access.model(key)
        source_filter = model.source_url.ilike("%parliament.gov.za%") if model is not None else None
        official_metrics.append(
            access.coverage(
                key,
                source_url_field="source_url",
                source_date_field=date_field,
                identity_fields=identity_fields,
                where=source_filter,
            )
        )

    source_coverage = [
        _combine_source("People's Assembly", people_metrics, access.unresolved_count(("People's Assembly",))),
        _combine_source("PMG", [pmg_documents], access.unresolved_count(("PMG",))),
        _combine_source(
            "Parliamentary Monitoring Group committees",
            [pmg_meetings],
            access.unresolved_count(("PMG",)),
        ),
        _combine_source(
            "Parliamentary questions",
            [questions],
            access.unresolved_count(("Parliamentary Questions",)),
        ),
        _combine_source(
            "Parliament official sources",
            official_metrics,
            access.unresolved_count(()),
        ),
    ]

    accountability_specs = (
        ("bills", "source_url", "introduced_date", ("bill_number", "title")),
        ("bill_events", "source_url", "event_date", ("event_type",)),
        ("vote_events", "source_url", "date", ("title",)),
        ("vote_records", "source_url", None, ("vote_value",)),
        ("committee_meetings", "source_url", "date", ("title",)),
        ("committee_attendance", "source_url", None, ("name_raw",)),
        ("parliamentary_questions", "source_url", "asked_date", ("question_number", "title")),
    )
    accountability_coverage = {
        key: access.coverage(
            key,
            source_url_field=url_field,
            source_date_field=date_field,
            identity_fields=identity_fields,
        )
        for key, url_field, date_field, identity_fields in accountability_specs
    }

    duplicate_candidates = {
        "politician_slugs": access.duplicate_groups("politicians", "slug"),
        "party_short_names": access.duplicate_groups("parties", "short_name"),
        "committee_slugs": access.duplicate_groups("committees", "slug"),
        "document_source_urls": access.duplicate_groups("documents", "source_url"),
        "question_source_urls": access.duplicate_groups("parliamentary_questions", "source_url"),
        "vote_event_source_urls": access.duplicate_groups("vote_events", "source_url"),
        "committee_meeting_source_urls": access.duplicate_groups("committee_meetings", "source_url"),
    }
    total_unresolved = access.unresolved_count()
    quality_metrics = people_metrics + [all_documents] + list(accountability_coverage.values())
    risks = _build_risks(quality_metrics, total_unresolved, duplicate_candidates)
    actions = _build_actions(source_coverage, accountability_coverage, total_unresolved, risks)
    has_data = any((value or 0) > 0 for value in executive_summary.values() if value is not None)
    red_risks = [risk for risk in risks if risk["level"] == "red"]

    return {
        "generated_at": datetime.now(UTC).isoformat(),
        "executive_summary": executive_summary,
        "availability": availability,
        "source_coverage": source_coverage,
        "accountability_coverage": accountability_coverage,
        "data_quality_risks": risks,
        "duplicate_identifier_candidates": duplicate_candidates,
        "unresolved_entities_open": total_unresolved,
        "next_recommended_actions": actions,
        "public_claim_readiness": {
            "safe_for_public_facing_completeness_claims": has_data and not red_risks,
            "reason": (
                "No red data-quality risks were detected in the available tables."
                if has_data and not red_risks
                else "Coverage is incomplete, unavailable, or has red data-quality risks; qualify public claims."
            ),
        },
    }


def write_report_files(report: dict, output_dir: str | Path = "reports") -> tuple[Path, Path]:
    directory = Path(output_dir)
    directory.mkdir(parents=True, exist_ok=True)
    json_path = directory / "data_coverage_dashboard.json"
    markdown_path = directory / "data_coverage_dashboard.md"
    json_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    markdown_path.write_text(render_markdown(report), encoding="utf-8")
    return json_path, markdown_path


def render_markdown(report: dict) -> str:
    lines = [
        "# Data Coverage Dashboard",
        "",
        f"Generated: {report['generated_at']}",
        "",
        "## Executive Summary",
        "",
        "| Metric | Count |",
        "|---|---:|",
    ]
    for key, value in report["executive_summary"].items():
        lines.append(f"| {_label(key)} | {_display(value)} |")

    lines.extend(
        [
            "",
            "## Source Coverage",
            "",
            "| Source | Status | Records | Earliest | Latest | Missing URL | Missing date | Missing identity | Open unresolved |",
            "|---|---|---:|---|---|---:|---:|---:|---:|",
        ]
    )
    for row in report["source_coverage"]:
        lines.append(
            f"| {row['source']} | {row['status']} | {_display(row['records_count'])} | "
            f"{_display(row['earliest_source_date'])} | {_display(row['latest_source_date'])} | "
            f"{_display(row['records_missing_source_url'])} | {_display(row['records_missing_source_date'])} | "
            f"{_display(row['records_missing_identity'])} | {_display(row['unresolved_entities_open'])} |"
        )

    lines.extend(
        [
            "",
            "## Accountability Coverage",
            "",
            "| Domain | Status | Records | Missing URL | Missing date | Missing identity |",
            "|---|---|---:|---:|---:|---:|",
        ]
    )
    for key, row in report["accountability_coverage"].items():
        lines.append(
            f"| {_label(key)} | {row['status']} | {_display(row['records_count'])} | "
            f"{_display(row['records_missing_source_url'])} | {_display(row['records_missing_source_date'])} | "
            f"{_display(row['records_missing_identity'])} |"
        )

    lines.extend(
        [
            "",
            "## Data Quality Risk Table",
            "",
            "| Level | Risk | Value | Detail |",
            "|---|---|---:|---|",
        ]
    )
    for risk in report["data_quality_risks"]:
        lines.append(f"| {risk['level'].upper()} | {risk['risk']} | {_display(risk['value'])} | {risk['detail']} |")

    readiness = report["public_claim_readiness"]
    lines.extend(
        [
            "",
            "## Next Recommended Ingestion Actions",
            "",
            *[f"- {action}" for action in report["next_recommended_actions"]],
            "",
            "## Public Claim Readiness",
            "",
            f"Safe for completeness claims: **{'yes' if readiness['safe_for_public_facing_completeness_claims'] else 'no'}**",
            "",
            readiness["reason"],
            "",
        ]
    )
    return "\n".join(lines)


def main() -> int:
    from app.db import SessionLocal

    with SessionLocal() as db:
        report = build_report(db)
    json_path, markdown_path = write_report_files(report)
    print(json.dumps({"json_report": str(json_path), "markdown_report": str(markdown_path)}, sort_keys=True))
    return 0


def _combine_source(source: str, metrics: list[dict], unresolved: int | None) -> dict:
    available = [metric for metric in metrics if metric["status"] == "available"]
    if not available:
        return {
            "source": source,
            "status": "unavailable",
            "records_count": None,
            "earliest_source_date": None,
            "latest_source_date": None,
            "records_missing_source_url": None,
            "records_missing_source_date": None,
            "source_date_applicable_count": None,
            "records_missing_identity": None,
            "unresolved_entities_open": unresolved,
            "domains": [metric["domain"] for metric in metrics],
        }
    earliest = [metric["earliest_source_date"] for metric in available if metric["earliest_source_date"]]
    latest = [metric["latest_source_date"] for metric in available if metric["latest_source_date"]]
    return {
        "source": source,
        "status": "available",
        "records_count": sum(metric["records_count"] for metric in available),
        "earliest_source_date": min(earliest) if earliest else None,
        "latest_source_date": max(latest) if latest else None,
        "records_missing_source_url": _sum_available(available, "records_missing_source_url"),
        "records_missing_source_date": _sum_available(available, "records_missing_source_date"),
        "source_date_applicable_count": _sum_available(available, "source_date_applicable_count"),
        "records_missing_identity": _sum_available(available, "records_missing_identity"),
        "unresolved_entities_open": unresolved,
        "domains": [metric["domain"] for metric in metrics],
    }


def _build_risks(coverage_metrics: list[dict], unresolved: int | None, duplicates: dict) -> list[dict]:
    missing_urls = sum(row["records_missing_source_url"] or 0 for row in coverage_metrics)
    missing_dates = sum(row["records_missing_source_date"] or 0 for row in coverage_metrics)
    date_applicable = sum(row["source_date_applicable_count"] or 0 for row in coverage_metrics)
    duplicate_total = sum(value or 0 for value in duplicates.values())
    date_ratio = missing_dates / date_applicable if date_applicable else 0
    return [
        {
            "level": "red" if missing_urls else "green",
            "risk": "Missing source URLs",
            "value": missing_urls,
            "detail": "Every public record should retain direct source evidence.",
        },
        {
            "level": "red" if date_ratio > 0.25 else ("yellow" if missing_dates else "green"),
            "risk": "Missing source dates",
            "value": missing_dates,
            "detail": "Red above 25% of records where a source date field is available.",
        },
        {
            "level": "red" if (unresolved or 0) > 50 else ("yellow" if unresolved else "green"),
            "risk": "Open unresolved entities",
            "value": unresolved,
            "detail": "Unresolved names limit reliable entity-level attribution.",
        },
        {
            "level": "red" if duplicate_total else "green",
            "risk": "Duplicate identifiers",
            "value": duplicate_total,
            "detail": "Duplicate source or entity identifiers require review.",
        },
    ]


def _build_actions(
    source_coverage: list[dict],
    accountability: dict,
    unresolved: int | None,
    risks: list[dict],
) -> list[str]:
    actions = []
    missing_or_empty = [
        row["source"]
        for row in source_coverage
        if row["status"] == "unavailable" or not (row["records_count"] or 0)
    ]
    if missing_or_empty:
        actions.append(f"Ingest or validate the next empty source domain: {missing_or_empty[0]}.")
    weakest = max(
        (
            (key, row["records_missing_source_url"] or 0)
            for key, row in accountability.items()
            if row["status"] == "available"
        ),
        key=lambda item: item[1],
        default=None,
    )
    if weakest and weakest[1]:
        actions.append(f"Repair missing source URLs in {weakest[0]} ({weakest[1]} records).")
    if unresolved:
        actions.append(f"Review {unresolved} open unresolved entities before entity-level coverage claims.")
    if any(risk["level"] == "red" for risk in risks):
        actions.append("Keep public-facing completeness claims qualified until red risks are resolved.")
    if not actions:
        actions.append("Continue bounded ingestion and monitor coverage deltas after each scheduled run.")
    return actions


def _unavailable_metric(domain: str) -> dict:
    return {
        "domain": domain,
        "status": "unavailable",
        "records_count": None,
        "earliest_source_date": None,
        "latest_source_date": None,
        "records_missing_source_url": None,
        "records_missing_source_date": None,
        "source_date_applicable_count": None,
        "records_missing_identity": None,
    }


def _is_blank(column):
    return or_(column.is_(None), func.trim(func.cast(column, String)) == "")


def _sum_available(metrics: list[dict], key: str) -> int | None:
    values = [metric[key] for metric in metrics if metric[key] is not None]
    return sum(values) if values else None


def _iso(value: date | datetime | None) -> str | None:
    return value.isoformat() if value is not None else None


def _display(value) -> str:
    return "unavailable" if value is None else str(value)


def _label(value: str) -> str:
    return value.replace("_", " ").strip().title()


if __name__ == "__main__":
    raise SystemExit(main())
