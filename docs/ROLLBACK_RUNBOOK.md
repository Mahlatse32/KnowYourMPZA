# Rollback Runbook

Last updated: 2026-07-04

How to stop, undo, or recover from a bad deploy, a bad merge, or a bad
ingestion run — ordered from fastest kill switch to full data restore.

## Principles that make rollback safe here

- **Migrations are additive** (guardrail: no migration may lose, rewrite, or
  silently reinterpret production data), so rolling code back does not
  strand the schema: old code runs fine against a newer additive schema.
- **Ingestion is idempotent**: records upsert by `source_url`, so stopping
  mid-run, re-running, or replaying a window never duplicates records.
- **Sweep cursors are durable** (`ingestion_sweep_states`) and advance only
  after success, so pausing sweeps loses no progress and resuming is safe.
- Because of the three points above, the default recovery is **stop →
  revert → resume**, not data surgery.

## 1. Stop scheduled ingestion (fastest kill switches)

| What to stop | How | Takes effect |
|---|---|---|
| Daily + weekly scheduled ingestion | Set the repo Actions secret `INGESTION_ENABLED` to anything other than `true` (or remove it) | Next run exits at the validation step; `run_daily_ingestion.py`/`run_weekly_ingestion.py` also refuse independently |
| Accountability sweep (bills/meetings/votes) | GitHub → Actions → "Accountability sweep" → **Disable workflow** | Immediately; cron stops firing |
| PMG meeting backfill (2-hourly) | GitHub → Actions → "PMG meeting backfill" → **Disable workflow** (or delete its `schedule:` block via PR) | Immediately |
| Everything at once | Disable all workflows in the Actions tab | Immediately |

Note: the sweep and backfill workflows are **not** gated by
`INGESTION_ENABLED` — they are gated only by the `DATABASE_URL` secret (no
secret → forced dry-run validation mode). To stop them, disable the
workflows; do not remove the `DATABASE_URL` secret as a kill switch, since
other jobs (readiness checks, reports) legitimately read it.

A run that is already executing can be cancelled from its run page
(**Cancel workflow**). Cancelling mid-sweep is safe: the cursor only
advances after a completed stream, and partial upserts are idempotent.

## 2. Roll back code on `main`

1. `git revert <merge-commit> -m 1` on a branch, open a PR, let CI pass,
   merge. Never force-push `main`.
2. Each launch PR documents its own rollback plan; prefer reverting the
   single offending PR over batch reverts.
3. Workflow-file changes take effect on the next run after the revert
   merges — scheduled workflows always run the version on `main`.

## 3. Roll back a deployment

- **Backend (Render or equivalent):** use the provider's deploy history to
  redeploy the previous successful deploy/image. The Dockerfile start
  command runs `alembic upgrade head` on boot; with additive-only
  migrations, redeploying older code against the newer schema is safe.
- **Frontend (Vercel/Netlify):** promote the previous deployment from the
  provider's deploy history. The frontend is a static SPA; no data risk.
- Requires provider dashboard access (outside this repository).

## 4. Roll back a migration

Additive-only policy means you should almost never downgrade in
production. Prefer **roll-forward**: a new migration that corrects the
mistake. If a downgrade is unavoidable:

1. Take a provider snapshot/backup first.
2. Stop all ingestion (section 1) so nothing writes mid-downgrade.
3. `alembic downgrade -1` from a trusted host with the production
   `DATABASE_URL`.
4. Re-run `scripts/check_persistent_db_ready.py --check-sweep` and the
   "Persistent DB readiness" workflow before re-enabling anything.

## 5. Roll back bad data

For a bad ingestion batch (wrong parses, corrupted records):

1. Stop ingestion (section 1).
2. Scope the damage: `ingestion_runs` rows record source, run type, counts,
   and timestamps; `ingestion_errors` holds per-record failures; every
   record keeps its `source_url` for verification against the source.
3. If the bad records simply need re-parsing after a code fix: fix the
   parser, re-run the bounded ingestion for the affected URLs — upserts
   overwrite in place (this is the normal path).
4. If records must be removed or restored wholesale: restore from the
   managed PostgreSQL provider's backup/point-in-time recovery. This
   requires provider access (outside this repository). After a restore,
   sweep cursors reflect the restored point in time; sweeps resume from
   there safely.

## 6. Reset a sweep cursor (re-ingest a window)

Because upserts are idempotent, rewinding a cursor only costs time, never
correctness. To re-sweep a stream from the start:

```sql
UPDATE ingestion_sweep_states
SET next_page = 1, sweeps_completed = 0, updated_at = NOW()
WHERE source_name = 'PMG' AND stream_name = '<stream>';
```

Streams: `pmg_bills`, `pmg_bill_lifecycle_backfill`,
`pmg_committee_meetings`, `pmg_votes_from_meetings`.

## 7. Verify after any rollback

1. Run the **"Persistent DB readiness"** workflow — confirms connectivity,
   migration head, required tables, and the real-mode sweep guard.
2. Dispatch **"Scheduled ingestion"** and review its artifacts:
   `v1_readiness_report.md`, `data_coverage_dashboard.json`, and the data
   quality checks report.
3. Compare production counts against the last-known-good numbers in
   `docs/V1_LAUNCH_CHECKLIST.md`.
4. Re-enable the disabled workflows only after the readiness artifacts are
   clean.

## Related runbooks

- `backend/docs/persistent-db-runbook.md` — database readiness and failure
  diagnosis.
- `backend/docs/scheduled-sweeps.md` — sweep mechanics, validation vs real
  mode.
- `docs/PEOPLES_ASSEMBLY_FALLBACK.md` (PR #64) — People's Assembly outage
  posture.
- `README.md` → Production Deployment — deploy configuration being rolled
  back to.
