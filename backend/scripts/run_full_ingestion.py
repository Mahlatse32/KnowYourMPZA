"""Full coverage ingestion pipeline runner.

Runs the full data coverage pipeline in sequence:
  1. People's Assembly politician profiles
  2. Parliament official member pages (if accessible)
  3. Committee pages and memberships
  4. PMG meeting documents
  5. Parliamentary questions
  6. Unresolved match suggestions
  7. Full coverage report

Failures in one stage do not stop subsequent stages unless fatal.

Examples:
    python scripts/run_full_ingestion.py --dry-run
    python scripts/run_full_ingestion.py \\
        --from-date 2024-05-29 --to-date 2026-06-10 \\
        --politician-limit 500 --committee-limit 500 \\
        --pmg-limit 2000 --question-limit 1000 \\
        --sleep 0.5
    python scripts/run_full_ingestion.py --skip-pmg --politician-limit 200 --sleep 0.5
"""
import argparse
import subprocess
import sys
from datetime import date
from pathlib import Path

SCRIPTS_DIR = Path(__file__).resolve().parent
PYTHON = sys.executable


def run_stage(label: str, script: str, extra_args: list[str], dry_run: bool) -> bool:
    args = [PYTHON, str(SCRIPTS_DIR / script)] + extra_args
    if dry_run:
        args.append("--dry-run")
    print(f"\n{'=' * 60}")
    print(f"STAGE: {label}")
    print(f"CMD: {' '.join(args)}")
    print(f"{'=' * 60}")
    try:
        result = subprocess.run(args, check=False)
        if result.returncode != 0:
            print(f"WARNING: {label} exited with code {result.returncode} — continuing pipeline.")
            return False
        return True
    except Exception as exc:
        print(f"ERROR: {label} raised exception: {exc} — continuing pipeline.")
        return False


# ---------------------------------------------------------------------------
# Incremental accountability sweep orchestration
# ---------------------------------------------------------------------------

def build_accountability_sweep_stages(args) -> list[tuple[str, str, list[str]]]:
    """Ordered, skippable sweep stages: bills -> bill lifecycle -> committee
    meetings -> votes from minutes. Returns (label, script, extra_args)."""
    common = ["--sweep", "--pages-per-run", str(args.pages_per_run), "--sleep", str(args.sleep), "--json-output"]
    if getattr(args, "discover", False):
        common = common + ["--discover"]
    stages: list[tuple[str, str, list[str]]] = []
    if not args.skip_bill_sweep:
        stages.append(("Bills sweep (pmg_bills)", "ingest_bills.py", common))
    if not args.skip_bill_lifecycle_sweep:
        stages.append(("Bill lifecycle sweep (pmg_bill_lifecycle_backfill)", "backfill_legislative_history.py", common))
    if not args.skip_committee_meeting_sweep:
        stages.append(("Committee meetings sweep (pmg_committee_meetings)", "ingest_committee_activity.py", common))
    if not args.skip_vote_sweep:
        stages.append(("Votes sweep (pmg_votes_from_meetings)", "ingest_votes.py", common))
    return stages


def run_accountability_sweep(args) -> dict[str, bool]:
    results: dict[str, bool] = {}
    for label, script, extra in build_accountability_sweep_stages(args):
        results[label] = run_stage(label, script, list(extra), args.dry_run)
    return results


def main() -> None:
    parser = argparse.ArgumentParser(description="Full KnowYourMPZA data coverage pipeline.")
    parser.add_argument("--dry-run", action="store_true", help="Pass --dry-run to all stages.")
    parser.add_argument("--sleep", type=float, default=0.5, help="Seconds between requests.")
    parser.add_argument("--from-date", default=None, help="Start date for PMG/questions (YYYY-MM-DD).")
    parser.add_argument("--to-date", default=None, help="End date for PMG/questions (YYYY-MM-DD).")
    parser.add_argument("--politician-limit", type=int, default=None)
    parser.add_argument("--committee-limit", type=int, default=None)
    parser.add_argument("--pmg-limit", type=int, default=None)
    parser.add_argument("--question-limit", type=int, default=None)
    parser.add_argument("--include-former", action="store_true", help="Include former MPs in PA ingestion.")
    parser.add_argument("--skip-parliament-members", action="store_true")
    parser.add_argument("--skip-committees", action="store_true")
    parser.add_argument("--skip-pmg", action="store_true")
    parser.add_argument("--skip-questions", action="store_true")
    parser.add_argument("--skip-bills", action="store_true")
    parser.add_argument("--skip-votes", action="store_true")
    parser.add_argument("--skip-committee-activity", action="store_true")
    parser.add_argument("--bills-limit", type=int, default=None)
    parser.add_argument("--votes-max-pages", type=int, default=20)
    parser.add_argument("--meetings-max-pages", type=int, default=20)
    parser.add_argument("--accountability-sweep", action="store_true",
                        help="Run the incremental accountability sweep stages (bills, lifecycle, meetings, votes) and exit.")
    parser.add_argument("--pages-per-run", type=int, default=3, help="Bounded page window per sweep stream.")
    parser.add_argument("--discover", action="store_true", help="With --dry-run: allow bounded live fetches in sweep stages.")
    parser.add_argument("--skip-accountability-sweep", action="store_true")
    parser.add_argument("--skip-bill-sweep", action="store_true")
    parser.add_argument("--skip-bill-lifecycle-sweep", action="store_true")
    parser.add_argument("--skip-committee-meeting-sweep", action="store_true")
    parser.add_argument("--skip-vote-sweep", action="store_true")
    parser.add_argument("--json-output", action="store_true", help="Also print the stage results as one JSON line.")
    args = parser.parse_args()

    if args.accountability_sweep and not args.skip_accountability_sweep:
        results = run_accountability_sweep(args)
        print(f"\n{'=' * 60}")
        print("ACCOUNTABILITY SWEEP SUMMARY")
        print(f"{'=' * 60}")
        for stage, success in results.items():
            print(f"  {stage}: {'OK' if success else 'FAILED'}")
        failed = [k for k, v in results.items() if not v]
        if failed:
            print(f"\n{len(failed)} sweep stage(s) reported failures — cursors did not advance for failed streams.")
        if args.json_output:
            import json as _json

            print(_json.dumps({"accountability_sweep_stages": results, "failed_stage_count": len(failed)}))
        sys.exit(1 if failed else 0)

    sleep_args = ["--sleep", str(args.sleep)]
    date_args = []
    if args.from_date:
        date_args += ["--from-date", args.from_date]
    if args.to_date:
        date_args += ["--to-date", args.to_date]

    results: dict[str, bool] = {}

    # Stage 1: People's Assembly profiles
    pa_args = sleep_args[:]
    if args.politician_limit:
        pa_args += ["--limit", str(args.politician_limit)]
    if args.include_former:
        pa_args.append("--include-former")
    results["people_assembly"] = run_stage(
        "People's Assembly full profile ingestion",
        "ingest_people_assembly_full.py",
        pa_args,
        args.dry_run,
    )

    # Stage 2: Official Parliament members (optional)
    if not args.skip_parliament_members:
        parl_args = sleep_args[:]
        if args.politician_limit:
            parl_args += ["--limit", str(args.politician_limit)]
        results["parliament_members"] = run_stage(
            "Official Parliament member ingestion",
            "ingest_parliament_members_full.py",
            parl_args,
            args.dry_run,
        )

    # Stage 3: Committees
    if not args.skip_committees:
        committee_args = sleep_args[:]
        if args.committee_limit:
            committee_args += ["--limit", str(args.committee_limit)]
        results["committees"] = run_stage(
            "Full committee and membership ingestion",
            "ingest_committees_full.py",
            committee_args,
            args.dry_run,
        )

    # Stage 4: PMG documents
    if not args.skip_pmg:
        pmg_args = sleep_args + date_args
        if args.pmg_limit:
            pmg_args += ["--limit", str(args.pmg_limit)]
        results["pmg"] = run_stage(
            "Full PMG document ingestion",
            "ingest_pmg_full.py",
            pmg_args,
            args.dry_run,
        )

    # Stage 5: Parliamentary questions
    if not args.skip_questions:
        q_args = sleep_args + date_args
        if args.question_limit:
            q_args += ["--limit", str(args.question_limit)]
        results["questions"] = run_stage(
            "Full parliamentary questions ingestion",
            "ingest_questions_full.py",
            q_args,
            args.dry_run,
        )

    # Stage 9: Bills
    if not args.skip_bills:
        bills_args: list[str] = []
        results["bills"] = run_stage(
            "Bills ingestion (PMG + parliament.gov.za)",
            "ingest_bills.py",
            bills_args,
            args.dry_run,
        )

    # Stage 10: Vote events
    if not args.skip_votes:
        votes_args = ["--max-pages", str(args.votes_max_pages)]
        results["votes"] = run_stage(
            "Vote events ingestion (PMG)",
            "ingest_votes.py",
            votes_args,
            args.dry_run,
        )

    # Stage 11: Committee activity (meetings + attendance)
    if not args.skip_committee_activity:
        meetings_args = ["--max-pages", str(args.meetings_max_pages)]
        results["committee_activity"] = run_stage(
            "Committee meeting activity ingestion (PMG)",
            "ingest_committee_activity.py",
            meetings_args,
            args.dry_run,
        )

    # Stage 6: Unresolved match suggestions (report only, no --apply)
    if not args.dry_run:
        results["unresolved_suggestions"] = run_stage(
            "Unresolved entity match suggestions",
            "suggest_unresolved_matches.py",
            [],
            False,
        )

    # Stage 7: Full coverage report (JSON + Markdown)
    if not args.dry_run:
        results["coverage_report"] = run_stage(
            "Full coverage report",
            "report_full_coverage.py",
            [],
            False,
        )

    # Stage 8: Search completeness checks
    if not args.dry_run:
        results["search_completeness"] = run_stage(
            "Search completeness checks",
            "check_search_completeness.py",
            [],
            False,
        )

    print(f"\n{'=' * 60}")
    print("PIPELINE SUMMARY")
    print(f"{'=' * 60}")
    for stage, success in results.items():
        status = "OK" if success else "FAILED"
        print(f"  {stage}: {status}")

    failed = [k for k, v in results.items() if not v]
    if failed:
        print(f"\n{len(failed)} stage(s) reported failures: {', '.join(failed)}")
        print("Check output above for details. Failed stages do not invalidate successful ones.")
    else:
        print("\nAll stages completed successfully.")


if __name__ == "__main__":
    main()
