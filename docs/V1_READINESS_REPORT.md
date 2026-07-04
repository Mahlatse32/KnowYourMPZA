# KnowYourMPZA V1 Readiness Report

Last updated: 2026-07-04

## Verdict

Not ready for public V1.

The identity bootstrap and scheduled maintenance path are now production-verified, but data coverage is not yet launch-grade for two core user promises: committee activity and parliamentary questions.

## Evidence Reviewed

- GitHub Actions scheduled ingestion run `28697697822` on `main`, completed successfully on 2026-07-04.
- GitHub Actions workflow dispatch run `28265387060` on `codex/production-identity-bootstrap-verification`, completed successfully on 2026-06-26.
- Latest daily production artifacts: `inspect_db.json`, `dataset_report.json`, `data_coverage_dashboard.json`, `pmg_ingestion_summary.json`, `parliamentary_questions_ingestion_summary.json`.
- Earlier weekly production artifacts: `identity_bootstrap_before_after.json`, `identity_bootstrap_after_weekly.json`.

## Production Readiness Summary

| Area | Status | Notes |
|---|---|---|
| Identity tables | green | `politicians=521`, `committees=34` in latest production run. |
| Scheduled ingestion | green | Latest daily run on `main` succeeded. |
| PMG bills | green | `1171/1246`, about `93.98%` coverage. |
| PMG committee meetings | red | `3416/34710`, about `9.84%` coverage. |
| Parliament questions | red | `139/44036`, about `0.32%` coverage. |
| People's Assembly | yellow | Production runner still sees systemic HTTP 403 source access failures; PMG fallback prevents empty identity tables. |
| Unresolved entities | green | `0` unresolved entities in latest production report. |
| Duplicate identifiers | green | Dashboard reports duplicate identifier risk as green. |
| Missing source URLs | green | Dashboard reports `0` missing source URLs. |
| Missing source dates | yellow | Dashboard reports `359` missing source dates. |

## Production Counts

| Dataset | Count |
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

## Scheduler State

Latest sweep state from run `28697697822`:

| Stream | Next page | Source total | Total seen | Failed | Last status |
|---|---:|---:|---:|---:|---|
| pmg_bills | 15 | 1246 | 3242 | 1 | completed |
| pmg_bill_lifecycle_backfill | 21 | unknown | 3513 | 131 | completed |
| pmg_committee_meetings | 70 | 34710 | 3500 | 17 | completed |
| pmg_votes_from_meetings | 70 | 34710 | 3471 | 35 | completed |

The cursor state indicates forward progress with soft failures rather than whole-sweep failure.

## Launch-Blocking Fixes Only

1. Increase PMG committee meeting backfill throughput safely until coverage approaches at least 80% of the source denominator.
2. Increase Parliament question ingestion coverage against the docsjson denominator or formally narrow the V1 question surface.
3. Keep People's Assembly failures visible; do not depend on PA for V1 identity correctness unless source access is restored from the production runner.
4. Run full backend and frontend verification on the merge candidate after coverage recovery.

No V1.1 or V2 feature work should be accepted until these are resolved or explicitly scoped out of V1.
