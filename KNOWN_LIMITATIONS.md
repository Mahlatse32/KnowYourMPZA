# Known Limitations

KnowYourMPZA V1 is a public beta built from source-backed parliamentary records. It is useful today, but it is not yet a complete historical archive.

## What This Means For Users

- Historical data is still being imported.
- Coverage improves automatically through scheduled backfills.
- Every record shown is source-backed.
- Users may occasionally encounter incomplete historical information during the backfill period.
- Missing sections mean "not linked or imported yet", not "no activity".

## Data Coverage

Current production evidence reviewed on 2026-07-09:

| Dataset | Current state | User-facing meaning |
|---|---|---|
| MPs | 521 source-backed identities | MP browsing/search is useful, but not an official all-MP completeness claim. |
| Parties | 16 source-observed parties | Some MPs still show party as unconfirmed. |
| Committees | 34 committees and 521 memberships | Committee context is available where linked. |
| PMG meetings | 22,656 of 34,713 records | Strong parliamentary activity evidence, still backfilling historical records. |
| Attendance | 209,192 records | Attendance panels work where rows are linked to an MP. |
| Questions | 3,994 of 44,036 records | Useful question browsing, but full historical question coverage is still incomplete. |
| Vote records | 5 explicit records | Do not treat V1 as a complete voting-history product. |

## Source Boundaries

- PMG is the V1 authority for committee activity, attendance, bills, meeting evidence, and vote-event signals.
- Parliament docsjson and question source documents are the V1 authority for parliamentary question records.
- People's Assembly is enrichment-only for V1 because automated access can return HTTP 403 from runners.
- The product does not infer missing parties, committee memberships, attendance, question askers, or vote records.

## What We Will Not Claim In V1

- Complete coverage of every MP.
- Complete historical committee meeting coverage.
- Complete historical parliamentary question coverage.
- Complete voting records.
- Complete attendance rates.
- That an empty MP section proves the MP did no work.

## How Coverage Improves

Scheduled production jobs continue to add and verify data:

- PMG meeting backfill runs every two hours while the historical meeting corpus is still below target.
- Parliament questions backfill runs every two hours for the docsjson question corpus.
- Scheduled ingestion produces readiness, coverage, data-quality, and smoke-test artifacts.
- Cursor-safe PMG sweeps continue refreshing bills, meetings, vote events, and related source-backed records.
