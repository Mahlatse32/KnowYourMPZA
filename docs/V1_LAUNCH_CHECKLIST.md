# KnowYourMPZA V1 Launch Checklist

Last updated: 2026-07-09

## Current Decision

GO WITH KNOWN LIMITATIONS after production is deployed from latest `main`.

## Product Gates

- [x] MP identity records exist in production (`politicians=521`).
- [x] Party enrichment is no longer only `Unknown` (`parties=16`; samples include Democratic Alliance and MKP).
- [x] Committee records and memberships exist (`committees=34`, `committee_memberships=521`).
- [x] PMG meeting and attendance data is large enough to provide visible parliamentary work evidence (`committee_meetings=22656`, `committee_attendance=209192`).
- [x] MP profile attendance endpoint exists and is covered by CI (PR #78).
- [x] Parliament questions backfill is running and source-backed (`parliamentary_questions=3994`).
- [x] Question docsjson metadata enrichment is implemented and tested (PR #77).
- [x] Frontend smoke against production data passes in scheduled artifacts (`overall_status=pass`, run `28921400351`).
- [x] Source links are retained for public verification (0 missing source URLs in latest coverage reports).
- [x] Honest empty states and coverage notices are merged (PR #79).
- [x] Attendance endpoint is covered by the production smoke test (PR #80).
- [x] Final CI on release-readiness code is green (`28998884475`).
- [ ] Production frontend/backend are deployed from latest `main`.
- [ ] `DEPLOYMENT_CHECKLIST.md` is completed during deployment.

## Historical Coverage Gates

These are no longer treated as the only launch decision, but remain public-limit guardrails:

| Dataset | Count | Denominator | Coverage | Launch handling |
|---|---:|---:|---:|---|
| PMG bills | 1171 | 1246 | 93.98% | acceptable for V1 |
| PMG committee meetings | 22656 | 34713 | 65.27% | useful; disclose historical backfill still in progress |
| Parliament question records | 3994 | 44036 | 9.07% | useful; disclose partial corpus and missing dates/text |

## First-Time User Questions

- [x] Who is this MP? Profile pages show source-backed identity and source profile links where present.
- [x] Which party do they belong to? Shown when source-backed; otherwise "Party not confirmed yet."
- [x] Which committees do they serve on? Shown for linked committee memberships; empty state explains when no link exists yet.
- [x] What parliamentary work have they done? MP pages show PMG documents, attendance, committees, and questions where linked.
- [x] Where can this information be verified? Cards expose source links instead of unsourced summaries.

## Do Not Claim

- Do not claim complete all-MP coverage.
- Do not claim complete historical meeting/question/vote coverage.
- Do not present missing linked sections as proof of no activity.
- Do not infer parties, committees, question askers, or attendance without source-backed records.

## Release Assets

- `RELEASE_NOTES_V1.md`
- `KNOWN_LIMITATIONS.md`
- `DEPLOYMENT_CHECKLIST.md`
- `POST_LAUNCH_MONITORING.md`
- `V1_RELEASE_PACKAGE.md`
