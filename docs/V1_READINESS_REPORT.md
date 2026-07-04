# KnowYourMPZA V1 Readiness Report

Last updated: 2026-07-04

## Verdict

NO-GO for public V1 today.

Identity, CI, rollback, data-quality checks, and reporting gates are materially stronger, but two core production coverage gates remain below launch threshold:

- PMG committee meetings: `3790/34710 = 10.92%`.
- Parliament questions: `139/44036 = 0.32%`.

The engineering path for both is now in place: PMG meeting backfill has a dedicated scheduled workflow, and Parliament questions use new-record-first backfill. The first PMG backfill run proved production writes but hit the 45-minute workflow timeout before cursor finalization, so the remaining blocker is sustained verified production growth to the launch threshold.

## Evidence Reviewed

- Latest completed scheduled ingestion daily run: `28697697822`, `main`, completed successfully on 2026-07-04.
- Later scheduled ingestion dispatch: `28702236614`, `main@48c111a`; weekly produced artifacts but failed on PA source access, while daily remained stuck in `run_daily_ingestion.py`.
- Latest accountability sweep evidence: `28696975853`, completed successfully on 2026-07-04.
- Latest `main` CI after open-PR cleanup: `28707821896`, completed successfully on 2026-07-04.
- Latest PMG meeting backfill attempt: `28708377083`, `main@ffc11e5`, improved meeting coverage before the job timed out and uploaded readiness artifacts.
- Readiness artifacts reviewed: `inspect_db.json`, `dataset_report.json`, `data_coverage_dashboard.json`, `identity_bootstrap_after_weekly.json`, `ingestion_brief.json`, and `v1_readiness_report.json`.

## Production Coverage

| Dataset | Production count | Expected/source count | Coverage | Trend since previous scheduled artifact | Status |
|---|---:|---:|---:|---|---|
| Politicians | 521 | 521 PMG-derived identities | 100% of PMG-derived identity set | flat | pass |
| Committees | 34 | 34 PMG-derived committees | 100% of PMG-derived identity set | flat | pass |
| Committee memberships | 521 | 521 PMG-derived memberships | 100% of PMG-derived identity set | flat | pass |
| Committee meetings | 3790 | 34710 PMG meetings | 10.92% | +374 since pre-backfill readiness artifact | blocker |
| Committee attendance | 46537 | no authoritative denominator in artifact | n/a | +4603 since pre-backfill readiness artifact | monitor |
| Bills | 1171 | 1246 PMG bills | 93.98% | flat | pass |
| Parliamentary questions | 139 | 44036 Parliament docsjson question records | 0.32% | flat | blocker |
| Vote events | 762 | no authoritative denominator in artifact | n/a | flat since scheduled run; accountability sweep added +64 earlier | monitor |
| Vote records | 5 | explicit named/count vote records only | n/a | flat since scheduled run; accountability sweep added +4 earlier | monitor |
| Unresolved entities | 0 | 0 open unresolved entities | 100% cleared | flat | pass |

## Link Coverage

| Relationship | Linked | Total | Coverage |
|---|---:|---:|---:|
| Attendance -> politicians | 28522 | 41934 | 68.02% |
| Meetings -> committees | 627 | 3416 | 18.35% |
| Questions -> politicians | 0 | 139 | 0.0% |
| Vote events -> committees | 195 | 762 | 25.59% |
| Vote records -> politicians | 0 | 5 | 0.0% |

Identity fallback definition-of-done remains partially satisfied: politicians and committees are non-zero, attendance/meeting/vote links exist, but question identity links remain absent.

## Workflow State

| Workflow | Latest evidence | Status |
|---|---|---|
| CI | Run `28707821896` on latest `main` passed backend and frontend jobs. | pass |
| Scheduled ingestion daily | Run `28697697822` passed; later dispatch `28702236614` daily is stuck in `run_daily_ingestion.py`. | blocker until timeout fix is merged and rerun |
| Scheduled ingestion weekly | Run `28702236614` weekly produced artifacts but failed because PA returned systemic HTTP 403. | blocker until PA enrichment-only handling is merged and rerun |
| Accountability sweep | Run `28696975853` passed; cursor state shows soft failures without whole-sweep failure. | pass |
| PMG meeting backfill | Run `28708377083` created production records and raised coverage to `10.92%`, but the 45-minute timeout cancelled the sweep before `pmg_committee_meetings` cursor finalization (`last_status=running`, `next_page=70`). | blocker until timeout extension is merged and rerun |

## Current Engineering Fix In Progress

This branch hardens the remaining workflow blockers:

- Adds `timeout-minutes` to scheduled ingestion jobs so stale production runs cannot hang indefinitely.
- Extends the PMG meeting backfill workflow timeout to 90 minutes so the existing 10-page safety cap can finish and advance cursor state.
- Treats PA/committee systemic source-access failures as non-blocking enrichment failures only when their source summary explicitly proves `systemic_source_access_failure=true`.
- Keeps unclassified weekly failures red.
- Keeps PA source-access status amber in V1 readiness when PMG fallback identity is operationally isolated.

## Launch-Blocking Fixes Only

1. Merge and verify the PMG meeting backfill timeout extension, then rerun the workflow and confirm `pmg_committee_meetings` finishes with `last_status=completed` and `next_page` advanced beyond `70`.
2. Continue scheduled PMG meeting backfills until production meeting coverage reaches at least 80%.
3. Trigger scheduled Parliament question ingestion on latest `main` and verify question count grows beyond `139`.
4. Re-run readiness artifacts after production backfills and update this report with after-counts.

## Recommendation

NO-GO until production artifacts show material growth for PMG committee meetings and Parliament questions, and the scheduled ingestion workflow completes on the hardened latest `main`.
