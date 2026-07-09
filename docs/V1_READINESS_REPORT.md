# KnowYourMPZA V1 Readiness Report

Last updated: 2026-07-09

## Verdict

GO WITH KNOWN LIMITATIONS once PR4 (`codex/honest-empty-states`) is merged, CI is green, and the frontend is deployed from latest `main`.

The launch decision has shifted from "raw historical coverage only" to "first-time user value with honest scope." Production now has enough source-backed data for a user to understand an MP profile, party affiliation where known, committee service, PMG attendance/work evidence, and verification links. The remaining limitations must be visible in the UI and launch copy.

## Product-Readiness Sequence

| Slice | Status | Evidence |
|---|---|---|
| PR1 party enrichment | merged | PR #76; production `parties=16`, with samples including Democratic Alliance and MKP rather than only `Unknown`. |
| PR2 question metadata | merged | PR #77; tests cover docsjson title/date/status enrichment; latest questions backfill run `28995667052` updated 194 question records and completed successfully. |
| PR3 attendance endpoint and MP panel | merged | PR #78; CI run `28998338744` passed backend and frontend. |
| PR4 honest empty states and coverage notices | in progress | Branch `codex/honest-empty-states`; frontend build passes locally. |

## Production Evidence

Latest evidence reviewed:

- PMG meeting backfill run `28994456199`, `main@211bfa5`, completed successfully on 2026-07-09.
- Parliament questions backfill run `28995667052`, `main@211bfa5`, completed successfully on 2026-07-09.
- Scheduled ingestion run `28921400351`, `main@211bfa5`, completed successfully on 2026-07-08.
- Main CI after PR #78 merge: `28998338744`, passed backend and frontend.

| Dataset | Production count | Source total | Coverage | User-facing status |
|---|---:|---:|---:|---|
| Politicians | 521 | PMG-derived identity set | n/a | enough for MP profile browsing; not an all-MP completeness claim |
| Parties | 16 | source-observed PMG parties | n/a | improved from all `Unknown`; some MPs may still be unconfirmed |
| Committees | 34 | PMG-derived committees | n/a | enough to show committee context |
| Committee memberships | 521 | PMG-derived memberships | n/a | enough to answer committee service for linked MPs |
| Committee meetings | 22,656 | 34,713 PMG meetings | 65.27% | useful and growing; historical corpus still incomplete |
| Committee attendance | 209,192 | follows meetings | n/a | enough to show MP attendance where linked |
| PMG bills | 1,171 | 1,246 PMG bills | 93.98% | acceptable for V1 |
| Parliamentary questions | 3,994 | 44,036 docsjson records | 9.07% | useful sample; full historical coverage still incomplete |
| Vote events | 897 | not established | n/a | visible as PMG evidence where present |
| Vote records | 5 | explicit named votes only | n/a | known limitation |
| Unresolved entities | 7 | 0 target | n/a | low, warn-level; no completeness claim |

## Verification Notes

- Party values are no longer all `Unknown`: scheduled ingestion artifacts show `parties=16`, including Democratic Alliance and MKP samples.
- MP pages can show attendance: PR #78 added `/politicians/{id}/attendance`; the smoke test now covers the attendance endpoint directly, and PR4 adds honest empty states for missing linked attendance/questions/evidence.
- Questions have source-backed records and the docsjson metadata path is merged/tested. Current production artifacts still show many missing question dates, so the UI must say "date not extracted yet" where metadata has not populated a record.
- Empty sections now explain "not linked yet" or "still being backfilled" rather than implying no activity.
- Every public-facing card keeps source links where the backend provides them.

## Remaining Limits

- Do not claim all MPs, all questions, all votes, or complete attendance rates.
- Parliament question coverage is still low against the full 44,036 docsjson denominator.
- PMG meeting coverage is useful but not yet at the historical 80% gate.
- Some party affiliations remain unconfirmed until source-backed enrichment touches those MPs.
- Public launch still requires the latest frontend/backend deployment from `main`.
