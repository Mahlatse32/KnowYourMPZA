# Post-Launch Monitoring

Monitor the first 30 days of public V1 around availability, data freshness, ingestion health, and user-facing correctness.

## Daily Checks

- Confirm latest `main` CI is green after any merge.
- Confirm scheduled ingestion runs are not failing.
- Confirm PMG meeting backfill and Parliament questions backfill runs continue succeeding while coverage is below target.
- Review latest artifacts:
  - `frontend_smoke_report.json`
  - `v1_readiness_report.json`
  - `data_coverage_dashboard.json`
  - `data_quality_checks.json`
  - `inspect_db.json`
- Check `/health` and `/health/ready` on the deployed backend.
- Smoke the deployed frontend:
  - Home
  - Search
  - MP profile
  - Committees
  - Questions
  - Quality

## Alerts And Triage

Treat these as launch-critical:

- `/health/ready` returns 503.
- Frontend cannot reach the backend.
- CI fails on `main`.
- Scheduled ingestion fails repeatedly.
- PMG meeting backfill or question backfill fails repeatedly.
- Artifacts stop uploading.
- Source URLs disappear from public cards.
- Public pages show misleading blank sections instead of honest empty states.

Treat these as known limitations unless they worsen sharply:

- Parliament question coverage below full corpus.
- PMG meeting coverage below full corpus.
- Some MPs with unconfirmed party.
- Some question dates/text missing.
- Sparse explicit vote records.

## First 30-Day Roadmap

1. Keep PMG meeting backfill enabled until at least 80% source coverage, then reduce or disable the high-frequency cron.
2. Keep Parliament questions backfill enabled and monitor partial/failed records.
3. Review unresolved entities weekly and resolve only with explicit source evidence.
4. Improve question date/title extraction reporting if missing-date counts remain high.
5. Expand explicit vote/division records after V1 stabilizes.
6. Validate an official Parliament MP universe source before making all-MP completeness claims.

## Rollback

Use `docs/ROLLBACK_RUNBOOK.md`.

Fast kill switches:

- Disable scheduled ingestion by setting `INGESTION_ENABLED` to anything other than `true`.
- Disable high-frequency backfill workflows in GitHub Actions if source load or data quality regresses.
- Revert the offending merge commit through a PR; do not force-push `main`.

## Reporting Cadence

- Daily for first week: review workflow artifacts and frontend smoke.
- Twice weekly for weeks 2-4: review coverage trends and unresolved entities.
- End of day 30: decide whether to remove beta wording or extend the known-limitations period.
