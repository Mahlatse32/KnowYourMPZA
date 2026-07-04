# Data Coverage Recovery Plan

> **Superseded (2026-07-04):** this is a point-in-time plan from 2026-06-23.
> Coverage recovery is now implemented and tracked via the `pmg-meeting-backfill`
> workflow, the new-record-first question ingestion, and the canonical
> [`V1_LAUNCH_CHECKLIST.md`](V1_LAUNCH_CHECKLIST.md) /
> [`V1_READINESS_REPORT.md`](V1_READINESS_REPORT.md). Do not use this file for
> launch decisions.

Generated: 2026-06-23

## Production Evidence

This report uses production database evidence from GitHub Actions artifacts, not the local Postgres snapshot.

Latest production evidence read:

- `Persistent DB readiness`, run `27439307324`, created 2026-06-12.
- `Accountability sweep`, run `28007034526`, created 2026-06-23.
- `Scheduled ingestion`, run `28008262668`, created 2026-06-23.

The `DATABASE_URL` secret value was not printed or read directly. GitHub Actions used it and uploaded redacted reports. The redacted production database target is:

`postgresql+psycopg://aws-1-eu-central-1.pooler.supabase.com:6543/postgres`

## Migration Check

Production readiness passed:

| Check | Result | Evidence |
|---|---|---|
| `DATABASE_URL` present | Pass | Secret present in workflow environment |
| PostgreSQL URL | Pass | `postgresql+psycopg` |
| Connect | Pass | `SELECT 1 succeeded` |
| Alembic revision | Pass | `current=0012_add_iec_vote_totals head=0012_add_iec_vote_totals` |
| Migrations current | Pass | `revision 0012_add_iec_vote_totals == head` |
| Required tables | Pass | All required tables present |
| Sweep state table | Pass | `ingestion_sweep_states` present |
| Sweep dry run | Pass | exited `0` |
| Real-mode guard | Pass | real sweeps require `SWEEP_DB_PERSISTENT=true` |

## Production Counts

| Dataset | Expected source count | Production count | Coverage | 80% target | Gap to 80% |
|---|---:|---:|---:|---:|---:|
| Politicians | 490 | 0 | 0% | 392 | 392 |
| Parties | 18 | 0 | 0% | 15 | 15 |
| Committees | 185 | 0 | 0% | 148 | 148 |
| Parliamentary Questions | 44,036 | 89 | 0.2% | 35,229 | 35,140 |
| PMG Documents | 130 | 70 | 53.8% | 104 | 34 |
| Bills | 1,246 | 1,166 | 93.6% | 997 | 0 |
| Committee Meetings | 34,676 | 1,911 | 5.5% | 27,741 | 25,830 |
| Attendance | Unknown | 23,185 | Unknown | Unknown | Unknown |
| Vote Events | Unknown | 421 | Unknown | Unknown | Unknown |
| Vote Records | Unknown | 0 | Unknown | Unknown | Unknown |

Known source denominators requested:

- PMG bills: `1,246`
- PMG committee meetings: `34,676`
- Parliament docsjson question-related records: `44,036`

Attendance and votes still need source-denominator discovery. PMG exposes attendance per meeting, not as a global count. PMG has no vote/division endpoint; vote events are derived from explicit vote signals in committee-meeting detail text.

## Impact Ranking

| Rank | Dataset | Production status | Impact | Incomplete because | Fastest path to 80% |
|---:|---|---|---|---|---|
| 1 | Politicians | 0 / 490 | Core identity layer for MPs, aliases, mentions, question askers, committee members, and attendance names. | People's Assembly / official member ingestion has not populated production at all. | Run full PA profile ingestion against production, then aliases. |
| 2 | Committees | 0 / 185 | Needed for "who sits on X committee" and committee browsing. | Committee ingestion has not populated production; member resolution also needs politicians first. | Run committee ingestion after politicians. |
| 3 | Parliamentary Questions | 89 / 44,036 | Main public query surface for topic, department, minister, and MP activity questions. | Scheduled ingestion is only landing a tiny docsjson subset; 33/89 lack linked MP and all 89 lack source dates in the dashboard. | Run question ingestion by bounded year/date windows after politicians exist. |
| 4 | PMG Documents | 70 / 130 | Source-backed activity evidence and document mentions. | Production has only 70 of the curated PMG URL list; mentions are limited because politicians are absent. | Run PMG document ingestion over remaining curated URLs after politician aliases. |
| 5 | Committee Meetings | 1,911 / 34,676 | Large accountability/activity corpus. | Accountability sweep is working but early: cursor at page 39, only 5.5% of source total loaded. | Continue/scalably increase `ingest_committee_activity.py` sweep. |
| 6 | Parties | 0 / 18 | Party filters and MP context. | Parties are mostly created as side effect of politician ingestion. | Covered by politician ingestion; add party reconciliation only if still low. |
| 7 | Votes | 421 events / unknown denominator | Accountability signal. | Vote denominator requires scanning PMG meeting details; no individual vote records are inferred. | Continue vote sweep and add denominator reporting. |
| 8 | Attendance | 23,185 rows / unknown denominator | Useful for meeting participation. | Attendance denominator requires probing meeting attendance endpoints. | Continue committee activity sweep and add attendance denominator reporting. |
| 9 | Bills | 1,166 / 1,246 | Accountability feature. | Already above 80%; remaining gap is small and sweep is healthy. | Continue normal bill sweep; not a top blocker. |

## Exact Backfill Commands For Top 4 Gaps

Run these in the production environment with the GitHub Actions/Render `DATABASE_URL` set. Do not print the URL.

### 1. Politicians

```bash
cd backend
python scripts/ingest_people_assembly_full.py --limit 500 --sleep 0.5
python scripts/regenerate_aliases.py
python scripts/report_data_coverage_dashboard.py --output-dir reports
```

Why this first: production has `0` politicians, and most downstream attribution depends on known people and aliases.

### 2. Committees

```bash
cd backend
python scripts/ingest_committees_full.py --limit 200 --sleep 0.5
python scripts/suggest_unresolved_matches.py
python scripts/report_data_coverage_dashboard.py --output-dir reports
```

Run after politician ingestion so committee member names can resolve instead of becoming unresolved entities.

### 3. Parliamentary Questions

Start with the current Parliament window, then repeat by older year windows until coverage reaches the chosen denominator.

```bash
cd backend
python scripts/ingest_questions_full.py --from-date 2024-05-29 --to-date 2026-06-23 --limit 5000 --sleep 0.5
python scripts/report_data_coverage_dashboard.py --output-dir reports
```

For true 80% of all `44,036` docsjson question-related records, repeat the same command with older `--from-date` / `--to-date` windows. The current gap to 80% is `35,140` records, so this is a multi-batch backfill, not a one-shot scheduled run.

### 4. PMG Documents

```bash
cd backend
python scripts/ingest_all_pmg.py --limit 130 --sleep 0.5
python scripts/report_data_coverage_dashboard.py --output-dir reports
```

Production needs only `34` more PMG documents to reach 80% of the current curated PMG URL list. Run this after politician alias regeneration so document mentions can resolve.

## Accountability Sweep Status

The production accountability sweep is real and healthy:

| Stream | Source total | Production count / created | Cursor | Latest run effect |
|---|---:|---:|---|---|
| PMG bills | 1,246 | 1,166 bills | next page `12` | Updated 150 bills; no failures |
| Bill lifecycle backfill | n/a | 11,104 bill events | next page `12` | 1,771 existing events found; no new events |
| PMG committee meetings | 34,676 requested denominator; workflow source total `34,669` | 1,911 meetings | next page `39` | +149 meetings, +1,887 attendance rows |
| PMG votes from meetings | meeting-derived | 421 vote events | next page `39` | +29 vote events |

Continue these, but they are not the top four launch blockers compared with zero politicians/parties/committees and only 89 parliamentary questions.

Recommended next accountability command:

```bash
cd backend
python scripts/run_full_ingestion.py --accountability-sweep --pages-per-run 6 --sleep 0.5
```

The latest sweep report says `pages_per_run=3` is healthy and recommends scaling to `6` after two consecutive clean runs.

## Production Data Quality Notes

- Missing source URLs: `0` red risk resolved in production.
- Open unresolved entities: `0`.
- Missing source dates: `309` yellow risk.
- Parliamentary questions: `89` total, `33` missing linked identity, `89` missing source date.
- Bills: `1,166` total, `451` missing identity-like fields, `218` missing source date.
- Vote records: `0`; current vote events are outcome-only/aggregate-signal events, not individual MP voting records.

## Recovery Order

1. Run politician ingestion and alias regeneration.
2. Run committee ingestion and unresolved match suggestions.
3. Run parliamentary question backfill in large but bounded year/date windows.
4. Run PMG document backfill over the curated 130 URLs.
5. Continue accountability sweeps, increasing `pages_per_run` from `3` to `6` once clean-run stability is confirmed.

## Bottom Line

Production is not uniformly empty. Bills are already above 80%, and committee meetings/attendance/vote events are actively growing through the accountability sweep. The real launch blockers are the V1 identity and browse layer:

- `0` politicians
- `0` parties
- `0` committees
- only `89` parliamentary questions
- only `70` PMG documents

Backfill those first.
