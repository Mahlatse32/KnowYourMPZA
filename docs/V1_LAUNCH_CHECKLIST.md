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
  - 2026-07-04 diagnosis: nothing is failing — throughput is structurally capped. The daily accountability sweep advances every stream by `pages_per_run=3` pages (150 meetings/day) against a ~695-page source (34,710 meetings), so the cursor at page 70 is exactly on schedule and 80% coverage would take ~160 more days. Fix: a dedicated `pmg-meeting-backfill` workflow sweeps only the `pmg_committee_meetings` stream every 2 hours at the existing 10-page safety cap (~6,000 meetings/day capacity, ~4–5 days to 80%), sharing the daily sweep's concurrency group and cursor so runs never overlap. The meetings fetcher also gains the same 45s-timeout/exponential-backoff behavior as the bills fetcher.
- [ ] Parliament question coverage reaches a V1-acceptable threshold or is explicitly scoped for public launch.
  - 2026-07-04 diagnosis: source access is working, but scheduled ingestion was spending its `50` URL daily limit on already-ingested docsjson URLs. The backfill path now prioritizes newly discovered question URLs before refreshing existing records.
- [ ] People's Assembly source access is either restored or permanently treated as enrichment-only with PMG fallback documented.
- [ ] Full backend test suite passes in a production-equivalent environment.
- [ ] Frontend production-data smoke test passes.
- [x] Duplicate, unresolved entity, failed run, stale data, orphan, and mandatory-field checks are documented and callable.
  - 2026-07-04: `backend/scripts/check_data_quality.py` runs all six check families with pass/warn/fail thresholds, writes `data_quality_checks.json`/`.md` into the scheduled report artifacts (daily and weekly), and exits non-zero on failure for manual gating. Documented in `docs/DATA_QUALITY_CHECKS.md`.

## Latest Production Counts

Source: scheduled ingestion run `28697697822`, `main`, completed successfully on 2026-07-04.

| Table | Count |
|---|---:|
| politicians | 521 |
| parties | 1 |
| committees | 34 |
| parliamentary_questions | 139 |
| documents | 70 |
| bills | 1171 |
| bill_events | 11121 |
| committee_meetings | 3416 |
| committee_attendance | 41934 |
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
| PMG committee meetings | 3416 | 34710 | 9.84% | blocker; dedicated 2-hourly backfill workflow in progress |
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
