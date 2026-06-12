# Persistent Database Runbook

How to know whether real scheduled sweeps are enabled, what each failure
means, and how to recover — without manually poking at the database.

## The two databases

| | Local Docker DB | Persistent scheduled DB |
|---|---|---|
| Where | `docker compose -p knowyourmpza up -d` on your machine | A hosted PostgreSQL you provide (any provider) |
| Used by | Local development, tests, manual bounded runs | GitHub Actions scheduled sweeps |
| Configured via | `docker-compose.yml` | `DATABASE_URL` repository secret |
| Sweep state | Persists while the volume exists | Persists across workflow runs |

**Why GitHub Actions' built-in Postgres can't run real sweeps:** the service
container is created fresh for every workflow run and destroyed afterwards.
`ingestion_sweep_states` (the cursor that remembers which PMG page to ingest
next) would reset every day, so the sweep would re-ingest page 0 forever and
never make progress. That's why `run_scheduled_sweep.py` refuses real runs
unless the database is marked persistent.

## How to check readiness (no manual DB inspection)

- **GitHub:** run the **"Persistent DB readiness"** workflow (Actions tab →
  Run workflow). The step summary states plainly whether real sweeps are
  enabled; artifacts contain `db_readiness.json` / `db_readiness.md`.
- **Locally / on a host:**
  ```bash
  cd backend
  python scripts/check_persistent_db_ready.py --run-migrations --check-sweep --json-output
  ```
  Exit codes: `0` ready · `2` configuration error · `3` database not ready.

The checker never prints credentials — output shows only
`scheme://host:port/dbname`.

## Diagnosing common failures

| Check that fails | Likely cause | Recovery |
|---|---|---|
| `url_present` | `DATABASE_URL` secret/env var missing | Add the repository secret (Settings → Secrets and variables → Actions). Format: `postgresql+psycopg://USER:PASSWORD@HOST:5432/DBNAME` |
| `url_is_postgres` | URL uses another scheme (mysql, sqlite, typo) | Use a PostgreSQL URL with the `postgresql+psycopg://` prefix |
| `connect` with `OperationalError ... Name or service not known` | Bad hostname | Verify the host in your provider's dashboard; check for typos |
| `connect` with `password authentication failed` | Bad username/password | Re-copy credentials; rotate the secret (below) |
| `connect` with `SSL required` / `no encryption` | Provider requires TLS | Append `?sslmode=require` to the URL |
| `alembic_revision` shows `current=none` | Fresh, never-migrated database | Re-run with `--run-migrations` (the readiness workflow does this by default) |
| `migrations_current` fails | DB is on an older revision | `--run-migrations`, or investigate if the revision is *ahead* of the code (deployed from a newer branch?) |
| `required_tables` reports missing tables | Partial migration or wrong database/schema | Confirm the URL points at the right database; `--run-migrations` |
| `sweep_dry_run` fails | Script/regression problem, not DB | Check CI on main; run `pytest -q` |
| `real_mode_guard` fails | The persistence guard was broken by a code change | Treat as a bug: real sweeps could run against ephemeral DBs. Fix before enabling schedules |

## Rotating the DATABASE_URL secret

1. Create the new credentials at your database provider.
2. Update the `DATABASE_URL` repository secret (overwrite in place).
3. Run the "Persistent DB readiness" workflow to confirm `connect` passes.
4. Revoke the old credentials at the provider.

Nothing in the repo or workflow logs ever contains the URL, so rotation
requires no code changes.

## Safe recovery principles

- Sweeps are idempotent: re-running any window updates rather than
  duplicates, so after fixing a problem you can simply let the next
  scheduled run proceed.
- A failed sweep never advances its cursor — the same window is retried.
- To deliberately restart a stream from page 0:
  `python scripts/ingest_bills.py --sweep --reset-sweep` (same flag on the
  other ingestion scripts).
- To test without any writes: dispatch the accountability sweep workflow
  with `dry_run=true`.
