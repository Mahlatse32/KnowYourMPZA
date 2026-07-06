# KnowYourMPZA V1 Launch Checklist

Last updated: 2026-07-06

## Current Decision

V1 is not launch-ready today, but **no engineering blockers remain** — see `docs/V1_LAUNCH_ASSESSMENT.md` for the full final assessment (including the 2026-07-06 gate review) and the measurable GO conditions.

2026-07-06 gate review: a binary `.xlsx` question document poisoned the new-record-first queue and made every questions backfill and daily ingestion run fail from 2026-07-05 onward (NUL bytes rejected by PostgreSQL; `DataError` aborts the batch). Fixed and production-verified in PR #74. Meetings backfill was unaffected and grew `3,915 → 12,000` (34.57%) in two days. The remaining blockers are unchanged in kind: coverage volumes (meetings ETA ~3–4 days, questions ~14–15 days or a human scope decision) plus the pre-existing external deployment blocker.

## Launch Gates

- [x] Production database coverage has been verified from GitHub Actions/Render `DATABASE_URL`.
- [x] Scheduled ingestion artifacts generate a consolidated V1 readiness report with counts, source totals, coverage percentages, blocker/pass status, last-run evidence, and next action.
- [x] Politicians table is non-zero in production.
- [x] Committees table is non-zero in production.
- [x] Committee attendance links to politician identities.
- [x] Committee meetings link to committee identities in the latest production report.
- [x] Parliamentary questions have source-backed identity links where resolvable.
- [x] Vote events and vote records have identity coverage in the latest production report.
- [x] Scheduled daily ingestion succeeds on `main`.
- [x] PMG scheduler sweep states show cursor safety and completed runs.
- [ ] PMG committee meeting coverage reaches a V1-acceptable threshold or is explicitly scoped for public launch.
  - 2026-07-04 (verified): the 90-minute timeout fix (PR #69) is production-proven — backfill run `28710353108` completed in 52 minutes, advanced the durable cursor from page 70 to page 80 (`last_status=completed`), and coverage grew `3416 → 3915` (11.28%) in one afternoon of backfill runs. The 2-hourly cron sustains ~6,000 meetings/day; **tick this gate when a scheduled readiness artifact reports `committee_meetings ≥ 27768` (80%), ETA ~4–5 days.**
- [ ] Parliament question coverage reaches a V1-acceptable threshold or is explicitly scoped for public launch.
  - 2026-07-04 (verified): the daily hang was the docsjson API ignoring the `page` parameter — discovery looped forever once the new-record-first window widened. Fixed in PR #70 (offset pagination + stale-batch bound) and production-verified in run `28711148489`: questions grew `139 → 189` with `created=50, updated=0, failed=0`. PR #72 adds a 2-hourly bounded questions backfill (200 URLs/run, ~2,300/day); **tick this gate when a scheduled artifact reports `parliamentary_questions ≥ 35229` (80%), ETA ~15–16 days, or when a narrower V1 question scope is explicitly approved.**
- [x] People's Assembly source access is either restored or permanently treated as enrichment-only with PMG fallback documented.
  - 2026-07-04: PA is formally enrichment-only for V1 with PMG as identity authority; the automatic PMG identity bootstrap fallback, recovery criteria, and operational runbook are documented in `docs/PEOPLES_ASSEMBLY_FALLBACK.md`.
- [x] Full backend test suite passes in a production-equivalent environment.
  - 2026-07-04: CI runs the full backend suite (`pytest -q`) against a PostgreSQL 16 service with `alembic upgrade head` applied — the same engine/migration path as production. Evidence: CI run `28705501325` on `main` (post PR #60/#61 merge) completed successfully on 2026-07-04, as did every `main` CI run this week. The known local-only failure mode (32 tests needing a PostgreSQL at 127.0.0.1) does not apply in CI.
- [x] Frontend production-data smoke test passes.
  - 2026-07-04: `backend/scripts/smoke_test_frontend_api.py` exercises every endpoint the frontend calls, requires non-empty core datasets, and runs daily against the production database. **Verified: `overall_status=pass` in the production artifacts of runs `28708619234` and `28711148489`** (all 15 checks green, including detail drill-downs and search).
- [x] Duplicate, unresolved entity, failed run, stale data, orphan, and mandatory-field checks are documented and callable.
  - 2026-07-04: `backend/scripts/check_data_quality.py` runs all six check families with pass/warn/fail thresholds, writes `data_quality_checks.json`/`.md` into the scheduled report artifacts (daily and weekly), and exits non-zero on failure for manual gating. Documented in `docs/DATA_QUALITY_CHECKS.md`.

## Latest Production Counts

Source: questions backfill run `28789135982` artifacts (2026-07-06 11:48 UTC, `inspect_db.json`/`data_coverage_dashboard.json`); trend vs the 2026-07-04 baseline (run `28711148489`).

| Table | Count | Trend since 2026-07-04 |
|---|---:|---|
| politicians | 521 | flat |
| parties | 1 | flat |
| committees | 34 | flat |
| parliamentary_questions | 565 | **+376, then frozen since 2026-07-05** (poison-document defect, fixed in PR #74) |
| documents | 70 | flat |
| bills | 1171 | flat |
| bill_events | 11168 | +47 |
| committee_meetings | 12000 | **+8,085 (~4,400/day)** |
| committee_attendance | 150297 | **+102,244** |
| committee_memberships | 521 | flat |
| document_mentions | 812 | flat |
| vote_events | 821 | +59 |
| vote_records | 5 | flat |
| ingestion_runs | 250 | +49 (36 failed in last 7 days — the poison-document failures) |
| unresolved_entities | 2 | +2 (two question-PDF asker names, OPEN, warn-level) |

## Source Denominator Coverage

| Dataset | Production count | Source denominator | Coverage | Launch status |
|---|---:|---:|---:|---|
| PMG bills | 1171 | 1246 | 93.98% | acceptable for V1 |
| PMG committee meetings | 12000 | 34710 | 34.57% | blocker; backfill healthy at ~4,400/day, ETA ~3–4 days to 80% (27,768) |
| Parliament question records | 565 | 44036 | 1.28% | blocker; queue unblocked by PR #74, ~2,400/day, ETA ~14–15 days to 80% (35,229) or a narrower approved scope |

## Identity Link Coverage

Source: `data_quality_checks.json` from scheduled ingestion run `28774789735` (2026-07-06). Link coverage temporarily lags the backfill because linking runs in the weekly PMG identity bootstrap; expect recovery after the next weekly run (or a manual weekly dispatch post-backfill). Note: the 2026-07-05 weekly run `28733837210` hit its 90-minute timeout in `run_weekly_ingestion.py` (report steps still completed) — watch the 2026-07-12 weekly run, and raise the timeout or bound the weekly sweep if it recurs.

| Domain | Total | Unlinked | Note |
|---|---:|---:|---|
| committee_meetings → committee | 11699 | 7160 (61.2%) | backfill outpacing weekly linker — expected during recovery |
| committee_attendance → politician | 147767 | 119245 (80.7%) | same lag |
| parliamentary_questions → politician | 565 | 565 | question linking is mention-based; direct FK links come from bootstrap |
| vote_records → politician | 5 | 5 | known limitation (phase 2) |

## Next Highest Priority

No engineering task remains. Monitor the backfills via the scheduled `v1_readiness_report` artifacts and tick the two coverage gates when their thresholds are met (see `docs/V1_LAUNCH_ASSESSMENT.md` for the exact GO conditions). Dispatch the weekly job once meeting backfill completes to restore identity-link coverage.

## Reporting Loop

Every scheduled daily and weekly ingestion run now writes `v1_readiness_report.json` and `v1_readiness_report.md` from the same artifact set as the dashboard and ingestion brief. Use those files to verify coverage progress after every backfill before changing this checklist.
