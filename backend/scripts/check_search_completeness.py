"""Search completeness checks — PostgreSQL only, no OpenSearch.

Exercises the common lookup paths used by the frontend and API, verifying
that data inserted during ingestion is actually reachable through the
search/browse queries the application uses.

Writes two output files:
    backend/reports/search_completeness_report.json
    backend/reports/search_completeness_report.md

Each check has a status of PASS, FAIL, SKIP, or WARN:
    PASS — the lookup returned at least one result
    FAIL — the lookup returned zero results for a known-ingested value
    SKIP — no records of this type exist yet (nothing to test)
    WARN — results returned but with a data quality concern

Examples:
    python scripts/check_search_completeness.py
    python scripts/check_search_completeness.py --json-only
"""
import argparse
import json
import sys
from dataclasses import asdict, dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from datetime import UTC, datetime

from sqlalchemy import func, or_, select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.models.committee import Committee
from app.models.committee_membership import CommitteeMembership
from app.models.document import Document
from app.models.document_mention import DocumentMention
from app.models.parliamentary_question import ParliamentaryQuestion
from app.models.party import Party
from app.models.politician import Politician
from app.models.politician_alias import PoliticianAlias
from app.models.unresolved_entity import UnresolvedEntity
from app.services.entity_resolution import resolve_politician_name

OUTPUT_DIR = Path("reports")
JSON_PATH = OUTPUT_DIR / "search_completeness_report.json"
MD_PATH = OUTPUT_DIR / "search_completeness_report.md"


@dataclass
class Check:
    name: str
    description: str
    status: str          # PASS | FAIL | SKIP | WARN
    result_count: int
    sample_value: str | None
    note: str


def run_checks(db: Session) -> list[Check]:
    checks: list[Check] = []

    # -----------------------------------------------------------------------
    # Politician lookup paths
    # -----------------------------------------------------------------------
    politician = db.scalars(select(Politician).limit(1)).first()
    if politician is None:
        checks.append(Check("politician_by_full_name", "Lookup politician by full_name", "SKIP", 0, None, "No politicians in DB"))
        checks.append(Check("politician_by_display_name", "Lookup politician by display_name", "SKIP", 0, None, "No politicians in DB"))
        checks.append(Check("politician_by_slug", "Lookup politician by slug", "SKIP", 0, None, "No politicians in DB"))
        checks.append(Check("politician_by_alias", "Lookup politician by alias", "SKIP", 0, None, "No politicians in DB"))
        checks.append(Check("politician_by_ilike", "Lookup politician by partial name (ILIKE)", "SKIP", 0, None, "No politicians in DB"))
    else:
        # By full_name
        count = db.scalar(select(func.count()).select_from(Politician).where(Politician.full_name == politician.full_name)) or 0
        checks.append(Check("politician_by_full_name", "Lookup by full_name exact", _status(count), count, politician.full_name, ""))

        # By display_name
        count = db.scalar(select(func.count()).select_from(Politician).where(Politician.display_name == politician.display_name)) or 0
        checks.append(Check("politician_by_display_name", "Lookup by display_name exact", _status(count), count, politician.display_name, ""))

        # By slug
        count = db.scalar(select(func.count()).select_from(Politician).where(Politician.slug == politician.slug)) or 0
        checks.append(Check("politician_by_slug", "Lookup by slug exact", _status(count), count, politician.slug, ""))

        # By alias (via PoliticianAlias)
        alias_row = db.scalars(select(PoliticianAlias).where(PoliticianAlias.politician_id == politician.id).limit(1)).first()
        if alias_row:
            found = db.scalars(
                select(Politician).where(
                    Politician.id.in_(select(PoliticianAlias.politician_id).where(PoliticianAlias.alias == alias_row.alias))
                )
            ).all()
            checks.append(Check("politician_by_alias", "Lookup via alias table", _status(len(found)), len(found), alias_row.alias, ""))
        else:
            checks.append(Check("politician_by_alias", "Lookup via alias table", "SKIP", 0, None, "Politician has no aliases"))

        # By partial ILIKE (the search endpoint strategy)
        name_fragment = politician.display_name.split()[0] if politician.display_name else ""
        if name_fragment:
            pat = f"%{name_fragment}%"
            found = db.scalars(
                select(Politician).where(
                    or_(
                        Politician.full_name.ilike(pat),
                        Politician.display_name.ilike(pat),
                        Politician.id.in_(select(PoliticianAlias.politician_id).where(PoliticianAlias.alias.ilike(pat))),
                    )
                ).limit(10)
            ).all()
            checks.append(Check("politician_by_ilike", f"ILIKE search on '{name_fragment}'", _status(len(found)), len(found), name_fragment, ""))
        else:
            checks.append(Check("politician_by_ilike", "ILIKE search (partial name)", "SKIP", 0, None, "No usable name fragment"))

    # -----------------------------------------------------------------------
    # Entity resolution
    # -----------------------------------------------------------------------
    politician2 = db.scalars(
        select(Politician).where(Politician.display_name.is_not(None)).limit(1)
    ).first()
    if politician2:
        result = resolve_politician_name(db, politician2.display_name)
        if result:
            checks.append(Check(
                "entity_resolution_by_display_name",
                "Entity resolution finds politician by display_name",
                "PASS", 1, politician2.display_name,
                f"score={result.confidence_score:.2f} reason={result.match_reason}"
            ))
        else:
            checks.append(Check(
                "entity_resolution_by_display_name",
                "Entity resolution finds politician by display_name",
                "FAIL", 0, politician2.display_name,
                "Entity resolution returned None — alias coverage may be insufficient"
            ))
    else:
        checks.append(Check("entity_resolution_by_display_name", "Entity resolution", "SKIP", 0, None, "No politicians"))

    # -----------------------------------------------------------------------
    # Party lookup
    # -----------------------------------------------------------------------
    party = db.scalars(select(Party).limit(1)).first()
    if party is None:
        checks.append(Check("party_by_short_name", "Lookup party by short_name", "SKIP", 0, None, "No parties in DB"))
        checks.append(Check("party_by_name_ilike", "Lookup party by name ILIKE", "SKIP", 0, None, "No parties in DB"))
    else:
        count = db.scalar(select(func.count()).select_from(Party).where(Party.short_name == party.short_name)) or 0
        checks.append(Check("party_by_short_name", "Lookup by short_name exact", _status(count), count, party.short_name, ""))

        name_frag = party.name[:4] if party.name else ""
        count = db.scalar(select(func.count()).select_from(Party).where(Party.name.ilike(f"%{name_frag}%"))) or 0
        checks.append(Check("party_by_name_ilike", f"Party ILIKE '{name_frag}'", _status(count), count, name_frag, ""))

    # -----------------------------------------------------------------------
    # Committee lookup
    # -----------------------------------------------------------------------
    committee = db.scalars(select(Committee).limit(1)).first()
    if committee is None:
        checks.append(Check("committee_by_slug", "Lookup committee by slug", "SKIP", 0, None, "No committees in DB"))
        checks.append(Check("committee_by_name_ilike", "Lookup committee by name ILIKE", "SKIP", 0, None, "No committees in DB"))
    else:
        count = db.scalar(select(func.count()).select_from(Committee).where(Committee.slug == committee.slug)) or 0
        checks.append(Check("committee_by_slug", "Lookup by slug exact", _status(count), count, committee.slug, ""))

        name_frag = committee.name.split()[0][:6] if committee.name else ""
        count = db.scalar(select(func.count()).select_from(Committee).where(Committee.name.ilike(f"%{name_frag}%"))) or 0
        checks.append(Check("committee_by_name_ilike", f"Committee ILIKE '{name_frag}'", _status(count), count, name_frag, ""))

    # -----------------------------------------------------------------------
    # Committee membership
    # -----------------------------------------------------------------------
    membership = db.scalars(select(CommitteeMembership).limit(1)).first()
    if membership is None:
        checks.append(Check("membership_by_politician", "Membership lookup by politician_id", "SKIP", 0, None, "No memberships"))
        checks.append(Check("membership_by_committee", "Membership lookup by committee_id", "SKIP", 0, None, "No memberships"))
    else:
        count = db.scalar(
            select(func.count()).select_from(CommitteeMembership).where(CommitteeMembership.politician_id == membership.politician_id)
        ) or 0
        checks.append(Check("membership_by_politician", "Membership by politician_id", _status(count), count, str(membership.politician_id), ""))

        count = db.scalar(
            select(func.count()).select_from(CommitteeMembership).where(CommitteeMembership.committee_id == membership.committee_id)
        ) or 0
        checks.append(Check("membership_by_committee", "Membership by committee_id", _status(count), count, str(membership.committee_id), ""))

    # -----------------------------------------------------------------------
    # PMG document lookup
    # -----------------------------------------------------------------------
    doc = db.scalars(select(Document).where(Document.document_type.like("PMG%")).limit(1)).first()
    if doc is None:
        checks.append(Check("pmg_doc_by_committee_name", "PMG doc lookup by committee_name", "SKIP", 0, None, "No PMG documents"))
        checks.append(Check("pmg_doc_by_source_url", "PMG doc lookup by source_url", "SKIP", 0, None, "No PMG documents"))
        checks.append(Check("pmg_doc_mention_join", "PMG doc joined to politician via mention", "SKIP", 0, None, "No PMG documents"))
    else:
        if doc.committee_name:
            count = db.scalar(
                select(func.count()).select_from(Document).where(Document.committee_name.ilike(f"%{doc.committee_name[:10]}%"))
            ) or 0
            checks.append(Check("pmg_doc_by_committee_name", f"PMG ILIKE committee '{doc.committee_name[:10]}'", _status(count), count, doc.committee_name, ""))
        else:
            checks.append(Check("pmg_doc_by_committee_name", "PMG doc by committee_name", "WARN", 0, None, "Document has no committee_name"))

        count = db.scalar(select(func.count()).select_from(Document).where(Document.source_url == doc.source_url)) or 0
        checks.append(Check("pmg_doc_by_source_url", "PMG doc by source_url exact", _status(count), count, (doc.source_url or "")[:60], ""))

        mention = db.scalars(select(DocumentMention).where(DocumentMention.document_id == doc.id).limit(1)).first()
        if mention:
            found = db.scalars(
                select(Politician).where(
                    Politician.id.in_(select(DocumentMention.politician_id).where(DocumentMention.document_id == doc.id))
                ).limit(5)
            ).all()
            checks.append(Check("pmg_doc_mention_join", "PMG doc → politician via document_mentions", _status(len(found)), len(found), None, ""))
        else:
            checks.append(Check("pmg_doc_mention_join", "PMG doc → politician via document_mentions", "WARN", 0, None, "Document has no mentions"))

    # -----------------------------------------------------------------------
    # Parliamentary question lookup
    # -----------------------------------------------------------------------
    q = db.scalars(select(ParliamentaryQuestion).limit(1)).first()
    if q is None:
        checks.append(Check("question_by_number", "Question by question_number", "SKIP", 0, None, "No questions in DB"))
        checks.append(Check("question_by_source_url", "Question by source_url", "SKIP", 0, None, "No questions in DB"))
        checks.append(Check("question_by_politician_id", "Question filtered by politician_id", "SKIP", 0, None, "No questions in DB"))
        checks.append(Check("question_by_department_ilike", "Question by department ILIKE", "SKIP", 0, None, "No questions in DB"))
    else:
        if q.question_number:
            count = db.scalar(
                select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.question_number == q.question_number)
            ) or 0
            checks.append(Check("question_by_number", "Question by question_number exact", _status(count), count, q.question_number, ""))
        else:
            checks.append(Check("question_by_number", "Question by question_number", "WARN", 0, None, "Question has no question_number"))

        count = db.scalar(
            select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.source_url == q.source_url)
        ) or 0
        checks.append(Check("question_by_source_url", "Question by source_url exact", _status(count), count, (q.source_url or "")[:60], ""))

        if q.politician_id:
            count = db.scalar(
                select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.politician_id == q.politician_id)
            ) or 0
            checks.append(Check("question_by_politician_id", "Question filtered by politician_id", _status(count), count, str(q.politician_id), ""))
        else:
            checks.append(Check("question_by_politician_id", "Question filtered by politician_id", "WARN", 0, None, "Question has no resolved politician_id"))

        if q.department:
            frag = q.department[:10]
            count = db.scalar(
                select(func.count()).select_from(ParliamentaryQuestion).where(ParliamentaryQuestion.department.ilike(f"%{frag}%"))
            ) or 0
            checks.append(Check("question_by_department_ilike", f"Question department ILIKE '{frag}'", _status(count), count, frag, ""))
        else:
            checks.append(Check("question_by_department_ilike", "Question by department ILIKE", "WARN", 0, None, "Question has no department"))

    # -----------------------------------------------------------------------
    # Unresolved entity lookup
    # -----------------------------------------------------------------------
    ue = db.scalars(select(UnresolvedEntity).limit(1)).first()
    if ue is None:
        checks.append(Check("unresolved_by_raw_value", "Unresolved entity by raw_value", "SKIP", 0, None, "No unresolved entities in DB"))
    else:
        count = db.scalar(
            select(func.count()).select_from(UnresolvedEntity).where(UnresolvedEntity.raw_value.ilike(f"%{ue.raw_value[:10]}%"))
        ) or 0
        checks.append(Check("unresolved_by_raw_value", f"Unresolved entity ILIKE '{ue.raw_value[:10]}'", _status(count), count, ue.raw_value[:40], ""))

    # -----------------------------------------------------------------------
    # Cross-table join health
    # -----------------------------------------------------------------------
    pol_with_party = db.scalar(
        select(func.count()).select_from(Politician).where(Politician.party_id.is_not(None))
    ) or 0
    pol_total = db.scalar(select(func.count()).select_from(Politician)) or 0
    if pol_total == 0:
        checks.append(Check("politician_party_join_health", "Politician → Party join integrity", "SKIP", 0, None, "No politicians"))
    elif pol_with_party == 0:
        checks.append(Check("politician_party_join_health", "Politician → Party join integrity", "WARN", 0, None, "Zero politicians have a party — party data may not be linked"))
    else:
        pct = round(pol_with_party / pol_total * 100, 1)
        status = "PASS" if pct >= 80 else "WARN"
        checks.append(Check("politician_party_join_health", "Politician → Party join", status, pol_with_party, None, f"{pct}% of politicians have a party"))

    return checks


def _status(count: int) -> str:
    return "PASS" if count > 0 else "FAIL"


def build_markdown(checks: list[Check], generated_at: str) -> str:
    lines: list[str] = []
    lines.append("# KnowYourMPZA — Search Completeness Report\n\n")
    lines.append(f"**Generated:** {generated_at}\n\n")
    lines.append(
        "> This report verifies that data inserted during ingestion is reachable through the lookup queries "
        "used by the application. It does **not** check live external sources.\n\n"
    )

    passed = [c for c in checks if c.status == "PASS"]
    failed = [c for c in checks if c.status == "FAIL"]
    warned = [c for c in checks if c.status == "WARN"]
    skipped = [c for c in checks if c.status == "SKIP"]

    lines.append(f"**Summary:** {len(passed)} PASS / {len(failed)} FAIL / {len(warned)} WARN / {len(skipped)} SKIP\n\n")

    if failed:
        lines.append("## Failures\n\n")
        lines.append("| Check | Sample Value | Note |\n|---|---|---|\n")
        for c in failed:
            lines.append(f"| {c.name} | {c.sample_value or ''} | {c.note} |\n")
        lines.append("\n")

    if warned:
        lines.append("## Warnings\n\n")
        lines.append("| Check | Sample Value | Note |\n|---|---|---|\n")
        for c in warned:
            lines.append(f"| {c.name} | {c.sample_value or ''} | {c.note} |\n")
        lines.append("\n")

    lines.append("## All Checks\n\n")
    lines.append("| Status | Check | Results | Sample Value | Note |\n|---|---|---|---|---|\n")
    for c in checks:
        emoji = {"PASS": "✓", "FAIL": "✗", "WARN": "⚠", "SKIP": "–"}.get(c.status, c.status)
        sample = (c.sample_value or "")[:50]
        note = c.note[:80]
        lines.append(f"| {emoji} {c.status} | {c.description} | {c.result_count} | {sample} | {note} |\n")
    lines.append("\n")

    return "".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Search completeness checks — PostgreSQL only.")
    parser.add_argument("--json-only", action="store_true")
    parser.add_argument("--md-only", action="store_true")
    args = parser.parse_args()

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    generated_at = datetime.now(UTC).isoformat()

    with SessionLocal() as db:
        checks = run_checks(db)

    passed = sum(1 for c in checks if c.status == "PASS")
    failed = sum(1 for c in checks if c.status == "FAIL")
    warned = sum(1 for c in checks if c.status == "WARN")
    skipped = sum(1 for c in checks if c.status == "SKIP")

    report = {
        "generated_at": generated_at,
        "summary": {"pass": passed, "fail": failed, "warn": warned, "skip": skipped, "total": len(checks)},
        "checks": [asdict(c) for c in checks],
        "caveat": (
            "Results are PASS/FAIL relative to data currently in the database. "
            "SKIP means no records of that type exist yet. "
            "WARN means data exists but has a quality concern."
        ),
    }

    if not args.md_only:
        JSON_PATH.write_text(json.dumps(report, indent=2, default=str), encoding="utf-8")
        print(f"json_report: {JSON_PATH}")

    if not args.json_only:
        md = build_markdown(checks, generated_at)
        MD_PATH.write_text(md, encoding="utf-8")
        print(f"md_report: {MD_PATH}")

    print(f"PASS={passed} FAIL={failed} WARN={warned} SKIP={skipped}")

    if failed:
        print("FAILED checks:")
        for c in checks:
            if c.status == "FAIL":
                print(f"  FAIL: {c.name} — {c.note}")
        sys.exit(1)


if __name__ == "__main__":
    main()
