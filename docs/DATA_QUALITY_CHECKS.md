# Data Quality Checks

Last updated: 2026-07-04

The V1 launch checklist requires that duplicate, unresolved entity, failed
run, stale data, orphan, and mandatory-field checks are documented and
callable. `backend/scripts/check_data_quality.py` is that single callable
entry point.

## How to run

Locally (uses `DATABASE_URL` via the app settings, same as every other
script):

```bash
cd backend
python scripts/check_data_quality.py
```

Options:

| Flag | Default | Meaning |
|---|---|---|
| `--reports-dir` | `reports` | Where `data_quality_checks.json` and `data_quality_checks.md` are written. |
| `--failed-run-window-days` | `7` | Window for counting failed ingestion runs. |
| `--stale-data-max-age-days` | `7` | Maximum age of the latest completed run per source before that source is stale. |
| `--stuck-run-max-age-hours` | `24` | Age after which a run still in `running` counts as stuck. |
| `--json-only` | off | Print a one-line JSON summary instead of the Markdown table. |

Exit code is `0` when the overall status is `pass` or `warn`, and `1` when
any check fails, so the script can gate manual verification. In the
scheduled ingestion workflow it runs non-blocking (`|| true`) like the other
report steps, and its JSON/Markdown output ships with the daily and weekly
report artifacts.

## Checks

Every check reports `pass`, `warn`, or `fail`. A missing table is reported
as `fail` — missing data is never treated as passing.

### Duplicates (fail when any duplicate group exists)

- duplicate politician slugs, committee slugs, party short names
- duplicate document / question / vote event / committee meeting source URLs
- duplicate `(politician, committee, role)` membership tuples

Most of these columns are also protected by database unique constraints;
the checks are defense-in-depth and catch constraint regressions or data
loaded outside the ORM.

### Unresolved entities

- open unresolved entities: `warn` above 0, `fail` above 50 (same
  thresholds as the data coverage dashboard risk table).

### Ingestion runs

- failed ingestion runs: `warn` when any run has `status=failed` inside the
  window. Failed runs are triaged via the ingestion brief and
  `triage_ingestion_alert.py`.
- stuck ingestion runs: `fail` when a run is still `running` after the
  stuck threshold — the job died without finalizing its run row.

### Stale data

- stale ingestion sources: `warn` when any source that has ever recorded an
  ingestion run has no *completed* run inside the stale window (including
  sources whose runs have only ever failed).

### Orphaned relationships

Identity-link orphans are records whose source name could not be resolved
to an identity (the FK is intentionally nullable):

- committee meetings without a committee link
- attendance rows without a politician link
- vote records without a politician link
- questions without a politician link

Each reports `unlinked`, `total`, and `unlinked_pct`: `warn` above 10%
unlinked, `fail` above 50%. Structural orphans:

- committees without memberships: `warn` when a committee has no
  membership rows (renders an empty public page).

### Mandatory fields (fail when violated)

- blank politician full/display names, committee names, party names
- committee meetings / questions / vote events / documents missing a
  source URL (every public record must keep direct source evidence)
- politicians without a party link (`warn`; the column is NOT NULL today,
  so this is a constraint-regression guard)

## Relationship to other reports

- `report_data_coverage_dashboard.py` reports coverage volumes and risk
  levels for dashboards; this script is the pass/fail gate over hygiene
  invariants, including the run-level checks the dashboard does not cover.
- `report_v1_readiness.py` aggregates report artifacts into the launch
  verdict; `data_quality_checks.json` is written to the same reports
  directory and ships in the same artifact bundle.
- `quality_check.py` prints the legacy `quality_service` summary counts for
  interactive inspection; it has no thresholds or exit-code contract.
