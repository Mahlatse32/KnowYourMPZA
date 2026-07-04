# KnowYourMPZA V1 Readiness Report

Last updated: 2026-07-04 (post engineering-complete milestone)

## Verdict

NO-GO for public V1 today; **zero open engineering blockers**. GO is a function of production backfill time only. Full assessment and exact measurable GO conditions: `docs/V1_LAUNCH_ASSESSMENT.md`.

- PMG committee meetings: `3915/34710 = 11.28%`, growing ~6,000/day under the verified 2-hourly backfill — ETA ~4–5 days to the 80% threshold.
- Parliament questions: `189/44036 = 0.43%`, first-ever growth verified today (+50, `created=50/updated=0/failed=0`), 2-hourly bounded backfill merged — ETA ~15–16 days to 80% at default bounds.

## Evidence Reviewed

- Scheduled ingestion run `28711148489` (`main`, 2026-07-04): **first fully green daily+weekly dispatch** since launch hardening — daily completed end-to-end including question ingestion; weekly green with the PA systemic block handled as enrichment-only.
- PMG meeting backfill run `28710353108` (`main`, 2026-07-04): completed in 52 minutes under the 90-minute timeout; durable cursor advanced `page 70 → 80`, `last_status=completed`.
- Earlier same-day runs `28708377083` and `28708619234`: proved ingestion volume works (+374 meetings / +4,603 attendance in 25 minutes) and isolated the two hang/timeout root causes now fixed.
- Latest `main` CI green (full backend suite vs PostgreSQL 16 + migrations; frontend build).
- Artifacts: `inspect_db.json`, `data_coverage_dashboard.json`, `data_quality_checks.json`, `frontend_smoke_report.json` (**pass**, twice), `parliamentary_questions_ingestion_summary.json`, `v1_readiness_report.json`.

## Production Readiness Summary

| Area | Status | Notes |
|---|---|---|
| Identity tables | green | `politicians=521`, `committees=34`, `memberships=521`, 0 unresolved entities. |
| Scheduled daily ingestion | green | Run `28711148489` fully green — the docsjson discovery hang (API ignores `page`; only `offset` paginates) fixed in PR #70. |
| Scheduled weekly ingestion | green | PA systemic 403 handled as enrichment-only (PR #68); PMG fallback keeps identity correctness. |
| PMG bills | green | `1171/1246 = 93.98%`. |
| PMG committee meetings | red → recovering | `3915/34710 = 11.28%`; backfill verified end-to-end (timeout fix PR #69), cursor advancing, ~6,000/day. |
| Parliament questions | red → recovering | `189/44036 = 0.43%`; growth mechanism verified; 2-hourly backfill (PR #72) live. |
| Frontend production smoke | green | `overall_status=pass` in both of today's production artifact sets. |
| Data quality gate | amber | Remaining fails: 2 zombie `running` rows (finalizer merged in PR #71, clears next run) and identity-link lag behind the backfill (recovers with the weekly bootstrap). |
| Operations | green | Rollback runbook, persistent-DB runbook, sweep runbook, PA fallback runbook; every run self-verifies with uploaded artifacts. |

## Scheduler State

From backfill run `28710353108` artifacts (2026-07-04 16:19 UTC):

| Stream | Next page | Source total | Total seen | Failed | Last status |
|---|---:|---:|---:|---:|---|
| pmg_committee_meetings | 80 | 34710 | 4000 | 17 | **completed** |

Cursor safety was verified under mid-run cancellation (cursor untouched, idempotent re-sweep) and under completion (cursor advanced).

## Launch-Blocking Items Remaining

1. **Production time**: meetings backfill to ≥ 27,768 (~4–5 days); questions backfill to ≥ 35,229 (~15–16 days) or an explicit human scope decision for V1 questions.
2. **Identity-link recovery after backfill**: run (or wait for) the weekly PMG identity bootstrap so meeting/attendance link coverage returns under thresholds.
3. **Public deployment** (external): backend/frontend deployment per `README.md` is a human infrastructure action; no deployed URL exists in the repository.

No V1.1 or V2 feature work should be accepted until GO is declared or the coverage scope is explicitly re-cut.
