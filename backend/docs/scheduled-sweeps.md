# Scheduled Accountability Sweeps

Accountability data (bills, bill lifecycle events, committee meetings,
attendance, vote events) is ingested progressively from the PMG public API by
the **accountability sweep**: a bounded batch that resumes from a durable
cursor (`ingestion_sweep_states`) on every run. The GitHub Actions workflow
[.github/workflows/accountability-sweep.yml](../../.github/workflows/accountability-sweep.yml)
runs it automatically.

## How it works

Daily at 02:30 UTC (and on manual dispatch) the workflow:

1. Installs the backend and runs `alembic upgrade head`.
2. Runs `scripts/run_scheduled_sweep.py --pages-per-run N --sleep 0.5`,
   which validates safety guards, snapshots before/after counts, runs
   `run_full_ingestion.py --accountability-sweep`, and writes JSON +
   Markdown run reports under `backend/reports/` (gitignored).
3. Runs `inspect_db.py --json-output`, the coverage report, and the search
   completeness checks.
4. Publishes the Markdown report to the Actions step summary and uploads
   everything in `backend/reports/` as a build artifact (30-day retention).

Sweep order per run: bills → bill lifecycle backfill → committee meetings +
attendance → votes from meeting minutes. Each stream advances its own cursor
only after a successful run; failed streams retry the same window next time.

## Validation mode vs real mode

| | Validation mode | Real mode |
|---|---|---|
| Trigger | No `DATABASE_URL` secret configured | `DATABASE_URL` secret configured |
| Database | Ephemeral Postgres service in the runner | Your persistent database |
| Writes | None — forced `--dry-run` | Bounded ingestion |
| Sweep state | Not persisted (warning emitted) | Persisted and advanced |

**Why the split:** an ephemeral database loses `ingestion_sweep_states`
between runs, so a "real" sweep against it would re-ingest page 0 forever.
`run_scheduled_sweep.py` therefore **refuses** real runs unless the database
is marked persistent (`SWEEP_DB_PERSISTENT=true`, which the workflow sets
automatically when the secret exists, or `--assume-persistent-db` on a host
that owns its database).

## Required GitHub secret

| Secret | Purpose |
|---|---|
| `DATABASE_URL` | SQLAlchemy URL of the persistent database, e.g. `postgresql+psycopg://user:pass@host:5432/knowyourmpza`. Without it the workflow runs validation-only. |

The workflow never prints `DATABASE_URL`.

## Safety guards

`run_scheduled_sweep.py` exits with code 2 and a clear message when:

- `--pages-per-run` is missing or < 1 (sweeps must be bounded),
- `--pages-per-run` exceeds the safety cap of 10 without `--allow-large-batch`,
- a real (non-dry) run has no `DATABASE_URL`,
- a real run targets a database not marked persistent.

## Batch size

- Default and recommended: `pages_per_run=3` (~150 meetings + ~150 bills +
  bounded detail/attendance calls per run, with 0.5s sleeps).
- Scale to `pages_per_run=6` only after **two consecutive clean runs**
  (the run report's "Next batch recommendation" tracks this).
- The hard cap is 10 unless `--allow-large-batch` is passed deliberately.

## Reading artifacts

Each run uploads `accountability-sweep-reports-<run number>` containing:

- `accountability_sweep_report.json` — machine-readable: mode, command,
  before/after/delta counts, per-stage summaries, sweep states, errors,
  source totals, estimated coverage, next-batch recommendation.
- `accountability_sweep_report.md` — the same as human-readable Markdown
  (also shown in the Actions step summary).
- `inspect_db.json`, `full_coverage_report.json`, search completeness
  reports.

## Inspecting sweep state

```bash
python scripts/inspect_db.py --samples 3 --show-sweep-state
python scripts/inspect_db.py --json-output            # machine readable
python scripts/ingest_bills.py --sweep --show-sweep-state
```

To intentionally restart a stream from page 0:

```bash
python scripts/ingest_bills.py --sweep --reset-sweep
```

## Disabling the schedule

Delete or comment out the `schedule:` block in
`.github/workflows/accountability-sweep.yml`. Manual dispatch keeps working.

## Data integrity guarantees

- Every record stores a public PMG source URL.
- Attendance rows come only from PMG's explicit attendance endpoint
  (P/A/AP codes) — **never inferred**.
- Vote events are created only from explicit division markers in meeting
  minutes; vote records only from explicit aggregate counts. Individual MP
  votes are **never** derived from party positions.
- All ingestion is idempotent: re-running a window updates rather than
  duplicates.
