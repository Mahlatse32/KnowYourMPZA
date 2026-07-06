# KnowYourMPZA — Final V1 Launch Assessment

Assessment date: 2026-07-04 (evidence through scheduled ingestion run `28711148489` and PMG meeting backfill run `28710353108`, both completed successfully on `main`). **Updated 2026-07-06 with the final launch gate review below; the 2026-07-06 section supersedes the figures further down.**

## 2026-07-06 final launch gate review

Verdict: **NO-GO today — unchanged in kind.** One new engineering blocker was found and fixed same-day (PR #74); the remaining blockers are coverage volume (production time), one product decision option, and the pre-existing external deployment step.

### Defect found and fixed during this review (PR #74)

Every Parliament questions backfill run and the daily scheduled ingestion job failed on every run from 2026-07-05 onward (16+ consecutive failures; evidence: runs `28789135982`, `28774789735`). Root cause: a binary `.xlsx` question document was fetched as text and parsed as HTML, inserting NUL (0x00) bytes into `question_text`; PostgreSQL rejects NUL, the resulting `DataError` is classified systemic and aborts the whole batch, and because the record was never created it stayed at the head of the new-record-first queue — a permanent poison pill. Questions were frozen at 565 for ~27 hours. PR #74 detects binary bodies (honest `parse_status=FAILED` record, no fabricated text, queue advances), routes misnamed PDFs to the PDF parser, and strips NUL bytes at the upsert choke point. **Production-verified in dispatched run `28799811463`: `attempted=200, processed=199, created=199, failed=1` (the 1 failure is a permanently-404 PDF, non-blocking HTTPError), questions `565 → 764`, workflow green.**

### Launch gates, 2026-07-06

| Gate | Status | Evidence |
|---|---|---|
| Engineering: repo clean, CI green, tests passing | PASS | CI run `28799795782` green on `main` post-merge; 601 tests pass; no open PRs; no V1-critical open issues |
| Production: scheduled workflows healthy | PASS (after fix) | Meeting backfill green on every run; daily/questions failures root-caused to the single PR #74 defect; weekly 90-min timeout on 2026-07-05 is a watch item for 2026-07-12 |
| Production: backfills progressing | PASS for meetings, RESUMED for questions | Meetings `3,915 → 12,199` in 2 days (~4,400/day); questions `565 → 764` in the post-fix verification run `28799811463` |
| Data quality: no critical corruption/duplicates | PASS | 0 duplicate groups on all 8 duplicate checks; 0 missing source URLs; 2 open unresolved entities (warn-level) |
| Data quality: identity-link coverage | FAIL (expected lag) | 61.2% meetings unlinked, 80.7% attendance unlinked — backfill outpaces the weekly linker by design; recovers via weekly bootstrap post-backfill |
| Frontend: production smoke | PASS | 15/15 checks pass in run `28774789735` artifacts (2026-07-06) |
| Operations: monitoring, rollback, deployment docs | PASS | Self-verifying artifacts on every run; `docs/ROLLBACK_RUNBOOK.md`; deployment steps in `README.md` (execution is the external blocker) |
| Coverage: meetings ≥ 27,768 (80%) | FAIL | 12,000/34,710 = 34.57%; ETA ~3–4 days at observed ~4,400/day |
| Coverage: questions ≥ 35,229 (80%) or approved narrower scope | FAIL | 565/44,036 = 1.28%; ETA ~14–15 days at ~2,400/day once resumed, or a product decision |
| Public deployment exists | FAIL (external) | No production backend/frontend URL; requires human infrastructure action (Render/Vercel per `README.md`) |

### Blocker classification, 2026-07-06

1. **Coverage volumes** (meetings, questions) — production operations; closing mechanically under scheduled backfills.
2. **Question scope decision** — product decision; can close the questions gate immediately.
3. **Public deployment** — external dependency; cannot be executed from this repository.
4. **Weekly ingestion 90-minute timeout** (2026-07-05 run `28733837210`) — production operations watch item; recurs → raise timeout or bound the weekly sweep.



## Recommendation

**NO-GO today — GO is now purely a function of production time, with zero open engineering blockers.**

Every launch gate that can be closed by engineering is closed. The two remaining blockers are coverage volumes that are now growing mechanically under verified, scheduled, bounded backfills. Meetings reach the 80% launch threshold in roughly 4–5 days; questions in roughly 15–16 days at current bounds (sooner if the batch variable is raised, or immediately if the launch scope for questions is explicitly narrowed — a human product decision).

### Exact measurable conditions to reach GO

1. `committee_meetings ≥ 27,768` (80% of the 34,710 PMG denominator) in a scheduled `v1_readiness_report` artifact. Current: 3,915 and growing ~6,000/day (12 backfill runs × ~500 meetings). **ETA ~4–5 days.**
2. `parliamentary_questions ≥ 35,229` (80% of the 44,036 docsjson denominator) in a scheduled artifact, **or** an explicit human-approved narrower question scope recorded in the checklist. Current: 189, growing ~2,300/day once the 2-hourly questions backfill (merged today) is in steady state. **ETA ~15–16 days**, tunable via the `MAX_QUESTION_BACKFILL_URLS` repository variable.
3. After backfills settle, `committee meetings without a committee link` back under the 10% warn threshold via the weekly PMG identity bootstrap (or one manual dispatch of the weekly job post-backfill). Current: 78.6% unlinked — expected lag, since the backfill outpaces the weekly linker by design.
4. The scheduled data-quality report clears its remaining fails: stuck-runs clears automatically on the next scheduled run (finalizer merged today); the link-coverage fails clear with condition 3.
5. The latest scheduled ingestion, meeting backfill, and questions backfill runs on `main` are green at decision time.

## Engineering readiness: COMPLETE

All engineering blockers found during launch hardening were fixed, merged, and production-verified today:

| Fix | PR | Production verification |
|---|---|---|
| PMG meeting backfill workflow (2-hourly, bounded, cursor-safe) | #61 | Run `28708377083`: +374 meetings/+4,603 attendance in 25 min |
| Backfill job timeout 45→90 min (cursor could never finalize) | #69 | Run `28710353108`: completed in 52 min, cursor advanced 70→80 |
| docsjson discovery hang — API ignores `page`, only `offset` paginates | #70 | Run `28711148489`: discovery in seconds, daily job fully green |
| New-record-first question ingestion | #60 | Same run: `created=50, updated=0, failed=0`; 139→189 |
| Zombie `running` run finalizer before quality checks | #71 | Clears the 2 timeout-orphaned rows on next scheduled run |
| 2-hourly bounded Parliament questions backfill | #72 | Cron live from 17:20 UTC; same entry point just verified in production |
| Scheduled ingestion hardening: job timeouts, PA systemic-block handling | #68 | Weekly job green with PA blocked; daily timeout bounded at 75 min |

Repository audit: no TODO/FIXME/HACK markers, no skipped tests, no disabled workflows, no placeholder code. Full backend suite passes in CI against PostgreSQL 16 with migrations applied (production-equivalent; latest `main` CI green). Stale June-23 status documents are bannered as superseded.

## Production readiness

| Area | Status | Evidence |
|---|---|---|
| Scheduled daily ingestion | green | Run `28711148489` daily job fully green end-to-end (first since the discovery fix) |
| Scheduled weekly ingestion | green | Same run, weekly job green with PA systemic block handled as enrichment-only |
| PMG meeting backfill | green | Run `28710353108` completed; durable cursor advanced beyond the stuck window |
| Parliament questions backfill | live | Merged today; cron `20 1-23/2 * * *`; entry point production-verified via the daily job |
| Frontend production-data smoke test | green | `overall_status=pass` in both artifact sets today (runs `28708619234`, `28711148489`) |
| Data quality gate | amber | Fails limited to: 2 zombie rows (fix merged, clears next run) and link-coverage lag behind the backfill (condition 3) |
| Rollback + operations | green | `docs/ROLLBACK_RUNBOOK.md`, persistent-DB runbook, sweep runbook, PA fallback runbook |
| Identity integrity | green | 0 unresolved entities, 0 duplicate identifiers, 0 missing source URLs |

## Data coverage by dataset (production, 2026-07-04 ~16:20 UTC)

| Dataset | Count | Denominator | Coverage | Trend today | Verdict |
|---|---:|---:|---:|---|---|
| Politicians | 521 | 521 PMG-derived | 100% | flat | pass |
| Committees | 34 | 34 PMG-derived | 100% | flat | pass |
| Committee memberships | 521 | 521 PMG-derived | 100% | flat | pass |
| Bills | 1,171 | 1,246 | 93.98% | flat | pass |
| Bill events | 11,121 | — | n/a | flat | pass |
| Committee meetings | 3,915 | 34,710 | 11.28% | **+499 today** (9.84%→11.28%), ~6,000/day capacity | blocker, closing ~4–5 days |
| Committee attendance | 48,053 | follows meetings | n/a | **+6,119 today** | monitor |
| Parliamentary questions | 189 | 44,036 | 0.43% | **+50 today**, first growth ever; ~2,300/day once backfill is in steady state | blocker, closing ~15–16 days |
| Vote events | 762 | — | n/a | flat | monitor |
| Vote records | 5 | explicit named votes only | n/a | flat | known limitation |
| Unresolved entities | 0 | — | — | flat | pass |

## Operational readiness

- Every scheduled and backfill run self-verifies: inspect_db, coverage dashboard, data-quality checks, frontend smoke (daily), consolidated V1 readiness report — all uploaded as 30-day artifacts.
- Kill switches, rollback, cursor-reset, and recovery procedures are documented and verified against real behavior (`docs/ROLLBACK_RUNBOOK.md`).
- Cursor safety was verified under the harshest condition observed: a mid-run cancellation left the durable cursor untouched and the next run resumed idempotently.

## Remaining external blockers (not solvable from the repository)

1. **Public deployment**: no production backend/frontend URL exists; deploying to Render/Vercel per `README.md` is a human infrastructure action. The daily smoke test already validates production data through the exact API contract the frontend uses.
2. **People's Assembly source access**: systemic HTTP 403 from GitHub runners (issue #47). Formally scoped as enrichment-only with a production-verified PMG fallback (`docs/PEOPLES_ASSEMBLY_FALLBACK.md`). Not launch-blocking.
3. **Question scope decision (optional accelerator)**: accepting a narrower V1 question surface (e.g., current parliamentary term) would reach GO sooner than full-corpus backfill.

## Top post-launch priorities

1. Individual vote records (5 records; divisions ingestion is issue #7 / phase 2).
2. Party enrichment — production has a single "Unknown" party from PMG fallback identities; PA recovery or an official source would enrich party affiliation.
3. Question→politician identity linking beyond mentions (bootstrap strategies for question PDFs).
4. Expansion sources: IEC results (#24), Gazette/Acts (#25), municipal councils (#26), Chapter 9 reports (#27), entity-resolution improvements (#28).
5. Disable the two backfill crons once their targets are reached (documented in each workflow header).
