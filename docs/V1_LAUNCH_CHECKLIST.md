# KnowYourMPZA V1 Launch Checklist

Last updated: 2026-07-04

## Current Decision

V1 is not launch-ready yet.

The production identity blocker is closed: production has non-zero politicians and committees, scheduled ingestion succeeds, and identity-linked accountability data now renders from production-backed scheduled reports. The remaining V1 blockers are coverage volume for PMG committee meetings and Parliament questions, plus launch documentation and verification hygiene.

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
  - 2026-07-04 diagnosis: nothing is failing in parsing or persistence; throughput is structurally capped. The first dedicated PMG meeting backfill run (`28708377083`) raised production coverage from `3416/34710 = 9.84%` to `3790/34710 = 10.92%`, but the 45-minute workflow timeout cancelled the run before cursor finalization (`last_status=running`, `next_page=70`). Fix in progress: keep the 10-page safety cap and shared `accountability-sweep` concurrency, but extend the workflow timeout to 90 minutes so each bounded batch can finish and advance the durable cursor.
- [ ] Parliament question coverage reaches a V1-acceptable threshold or is explicitly scoped for public launch.
  - 2026-07-04 diagnosis: source access is working, but scheduled ingestion was spending its `50` URL daily limit on already-ingested docsjson URLs. The backfill path now prioritizes newly discovered question URLs before refreshing existing records.
- [x] People's Assembly source access is either restored or permanently treated as enrichment-only with PMG fallback documented.
  - 2026-07-04: PA is formally enrichment-only for V1 with PMG as identity authority; the automatic PMG identity bootstrap fallback, recovery criteria, and operational runbook are documented in `docs/PEOPLES_ASSEMBLY_FALLBACK.md`.
- [x] Full backend test suite passes in a production-equivalent environment.
  - 2026-07-04: CI runs the full backend suite (`pytest -q`) against a PostgreSQL 16 service with `alembic upgrade head` applied — the same engine/migration path as production. Evidence: CI run `28705501325` on `main` (post PR #60/#61 merge) completed successfully on 2026-07-04, as did every `main` CI run this week. The known local-only failure mode (32 tests needing a PostgreSQL at 127.0.0.1) does not apply in CI.
- [ ] Frontend production-data smoke test passes.
  - 2026-07-04: `backend/scripts/smoke_test_frontend_api.py` now exercises every endpoint the frontend calls, requires non-empty core datasets, and runs daily in scheduled ingestion against the production database via `--start-local-server`, writing `frontend_smoke_report.json`/`.md` into the artifacts. Tick this gate when the first scheduled artifact reports `overall_status=pass`.
- [x] Duplicate, unresolved entity, failed run, stale data, orphan, and mandatory-field checks are documented and callable.
  - 2026-07-04: `backend/scripts/check_data_quality.py` runs all six check families with pass/warn/fail thresholds, writes `data_quality_checks.json`/`.md` into the scheduled report artifacts (daily and weekly), and exits non-zero on failure for manual gating. Documented in `docs/DATA_QUALITY_CHECKS.md`.

## Latest Production Counts

Source: scheduled ingestion run `28697697822`, plus PMG meeting backfill run `28708377083` where noted.

| Table | Count |
|---|---:|
| politicians | 521 |
| parties | 1 |
| committees | 34 |
| parliamentary_questions | 139 |
| documents | 70 |
| bills | 1171 |
| bill_events | 11121 |
| committee_meetings | 3790 |
| committee_attendance | 46537 |
| committee_memberships | 521 |
| document_mentions | 812 |
| vote_events | 762 |
| vote_records | 5 |
| ingestion_runs | 179 |
| unresolved_entities | 0 |

## Source Denominator Coverage

| Dataset | Production count | Source denominator | Coverage | Launch status |
|---|---:|---:|---:|---|
| PMG bills | 1171 | 1246 | 93.98% | acceptable for V1 |
| PMG committee meetings | 3790 | 34710 | 10.92% | blocker; dedicated 2-hourly backfill workflow needs timeout extension and rerun |
| Parliament question records | 139 | 44036 | 0.32% | blocker; new-record-first backfill fix in progress |

## Identity Link Coverage

Source: `data_coverage_dashboard.json` from scheduled ingestion run `28697697822`.

| Domain | Total | Linked | Link coverage |
|---|---:|---:|---:|
| bill_events | 11121 | 11121 | 100.00% |
| bills | 1171 | 719 | 61.40% |
| committee_attendance | 41934 | 41934 | 100.00% |
| committee_meetings | 3416 | 3416 | 100.00% |
| parliamentary_questions | 139 | 99 | 71.22% |
| vote_events | 762 | 762 | 100.00% |
| vote_records | 5 | 5 | 100.00% |

## Next Highest Priority

Assign Claude one task: recover PMG committee meeting coverage toward at least 80% of the PMG source denominator using the existing scheduler/backfill architecture without reducing scheduler resilience.

## Reporting Loop

Every scheduled daily and weekly ingestion run now writes `v1_readiness_report.json` and `v1_readiness_report.md` from the same artifact set as the dashboard and ingestion brief. Use those files to verify coverage progress after every backfill before changing this checklist.
