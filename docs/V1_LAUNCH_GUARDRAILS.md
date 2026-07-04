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

- PMG committee meeting coverage is only `3416/34710` in the latest production report.
- Parliament question coverage is only `139/44036` in the latest production report. The known ingestion risk is repeated refresh of already-ingested docsjson URLs; fixes must preserve source URLs, PDF archiving, idempotent upserts, and soft failure reporting.
- People's Assembly production fetches have shown systemic HTTP 403 failures; fallback is required.
- Local worktree hygiene: the unrelated unstaged deletions were restored to match `main`, and downloaded run-artifact directories (`.tmp-gh-run-*/`) are now gitignored. One leftover remains: an untracked `.github/workflows/committee-name-backfill.yml` (a one-time backfill workflow that was never committed); do not include it in launch PRs.

## Next Task Assignment

Claude should work on exactly one V1 task next:

Recover PMG committee meeting coverage toward at least 80% of the PMG source denominator while preserving scheduler resilience, idempotency, source attribution, and cursor safety.
