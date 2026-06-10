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
    args = parser.parse_args()

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

    # Stage 6: Unresolved match suggestions (report only, no --apply)
    if not args.dry_run:
        results["unresolved_suggestions"] = run_stage(
            "Unresolved entity match suggestions",
            "suggest_unresolved_matches.py",
            [],
            False,
        )

    # Stage 7: Full coverage report
    if not args.dry_run:
        results["coverage_report"] = run_stage(
            "Full coverage report",
            "full_coverage_report.py",
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
