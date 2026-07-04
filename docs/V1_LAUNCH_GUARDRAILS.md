# KnowYourMPZA V1 Launch Guardrails

Last updated: 2026-07-04

## Merge Rules

Do not merge a pull request if any of these are true:

- Required tests or CI checks fail.
- A migration can lose, rewrite, or silently reinterpret production data.
- Scheduler resilience is reduced.
- PMG timeout handling loses the 45-second timeout, exponential backoff, soft-failure behavior, or cursor safety.
- Ingestion creates fabricated politicians, committees, attendance, votes, or question links.
- Source attribution is removed or weakened.
- Secrets, tokens, production URLs with credentials, or private keys are exposed.
- Authentication or CORS security is weakened.
- Launch readiness decreases without an explicit blocker note in `docs/V1_READINESS_REPORT.md`.

## Source Authority Rules

- Parliament remains the authority for parliamentary question source records.
- PMG remains the authority for committee activity, attendance, meeting, bill, and vote-event evidence.
- People's Assembly is enrichment only while production runner access is blocked.
- PMG-derived identity bootstrap may create fallback identities only from existing source-backed PMG activity data.
- Do not infer individual vote records from party positions.
- Do not infer attendance or committee membership without source-backed evidence.

## Required Review Checks

For every launch-relevant PR:

1. Review the diff for data corruption, source attribution, and scheduler regressions.
2. Verify migrations are additive or otherwise production-safe.
3. Verify tests cover idempotency and failed-source behavior where ingestion changes.
4. Verify GitHub Actions checks pass.
5. Verify production or production-equivalent artifacts when the PR changes ingestion coverage.
6. Update `docs/V1_LAUNCH_CHECKLIST.md` and `docs/V1_READINESS_REPORT.md` when readiness changes.
7. For coverage-changing PRs, review the scheduled `v1_readiness_report` artifact before declaring V1 progress.

## Current No-Merge Risks

- PMG committee meeting coverage is `3915/34710` and Parliament question coverage is `189/44036`; both are recovering under verified 2-hourly backfills. Do not merge anything that alters backfill cadence, batch bounds, cursor semantics, or the docsjson `offset` pagination without fresh production evidence.
- The docsjson endpoint ignores the `page` parameter; only `offset` paginates. Any discovery change must keep the stale-batch bound and request caps from PR #70.
- People's Assembly production fetches still show systemic HTTP 403 failures; PA remains enrichment-only (`docs/PEOPLES_ASSEMBLY_FALLBACK.md`).
- Identity-link coverage temporarily lags the backfill until the weekly PMG identity bootstrap runs; do not "fix" the lag by weakening linker or bootstrap semantics.
- Local worktree hygiene: one leftover remains — an untracked `.github/workflows/committee-name-backfill.yml` (a one-time backfill workflow that was never committed); do not include it in launch PRs.

## Next Task Assignment

No engineering task remains (see `docs/V1_LAUNCH_ASSESSMENT.md`). Monitor scheduled `v1_readiness_report` artifacts; tick the two coverage gates at their thresholds; dispatch the weekly job after meeting backfill completes to restore identity-link coverage; disable each backfill cron when its target is reached.
