# KnowYourMPZA — V1 Launch Checklist

**Mission:** ship public V1 as quickly as possible. V1 is not new features — V1 means
the product has enough **verified political data coverage** to be publicly useful.

This checklist is the single tracking document for V1 launch work. Work items are
ordered by priority: data coverage → ingestion reliability → verification → launch
confidence. Each work item should land as a small, focused PR. Do not merge your own
PRs; stop after each PR and wait for Codex review.

Related documents:

- `backend/docs/v1-completion-plan.md` — product definition, readiness levels (Red/Amber/Green), completion gates.
- `docs/release-checklist.md` — mechanical pre-tag / pre-deploy checklist.
- `V1_READINESS_REPORT.md` — **output** of workstream 1 (generated, committed at repo root).

Legend: `[ ]` not started · `[~]` in progress / partially done · `[x]` done and verified.

---

## Workstream 1 — Production coverage verification

Goal: know exactly what is in the production database, compared against source-system
totals, and publish it as `V1_READINESS_REPORT.md`.

- [ ] **1.1 Connect to production database (read-only first).**
  Use `DATABASE_URL` from the production environment / GitHub Actions secret. Never
  print or commit the URL (follow the redaction pattern in
  `backend/scripts/report_v1_readiness.py`). Verify connectivity with
  `backend/scripts/check_persistent_db_ready.py`.
- [ ] **1.2 Count core tables in production:**
  MPs (`politicians`), `committees`, `committee_meetings`, `parliamentary_questions`,
  `committee_attendance`, `committee_memberships`, aliases (`politician_aliases`),
  `unresolved_entities`, `ingestion_runs` (+ `ingestion_errors`), `documents`,
  `bills`, `vote_events` / `vote_records`.
  Existing tooling: `backend/scripts/report_data_coverage_dashboard.py` (counts +
  Markdown/JSON dashboard) and `backend/scripts/inspect_db.py`. The in-flight
  `verify_identity_bootstrap_production.py` (branch
  `codex/production-identity-bootstrap-verification`) already counts most of these —
  land that PR or fold its table census into the readiness report.
- [ ] **1.3 Compare production counts against source-system totals** (see Workstream 2
  for per-source expected universes). Record absolute counts, expected counts, and
  coverage percentage per domain.
- [ ] **1.4 Generate `V1_READINESS_REPORT.md`** at the repo root.
  Extend `backend/scripts/report_v1_readiness.py` (currently aggregates report JSONs
  from `backend/reports/`) so a single rerunnable command produces the report:
  production table counts, source comparisons, quality-gate results (Workstream 4),
  ingestion-run health, and an explicit Red/Amber/Green verdict per the gates in
  `backend/docs/v1-completion-plan.md`. The report must state **whether V1 is
  launch-ready** and list every blocker.
- [ ] **1.5 Report is rerunnable.** Document the exact command(s) in the report header;
  a fresh run against production must regenerate it end to end.

## Workstream 2 — Source-system comparison

Goal: for each source system, know the expected universe and record missing coverage
explicitly. Unknown stays unknown — no inferred or fabricated completeness claims
(per `backend/docs/v1-completion-plan.md`).

- [ ] **2.1 PMG (pmg.org.za):** compare production committee meetings / documents /
  attendance against PMG listings (`backend/app/ingestion/pmg.py` discovery).
  Record per-committee and per-year meeting coverage; count PMG-derived
  `unresolved_entities`.
- [ ] **2.2 People's Assembly (pa.org.za):** compare MP profiles, memberships, and
  attendance against PA. **Known blocker:** PA source-access failures (issue #47)
  must stay visible; PA is enrichment, not the baseline MP authority.
- [ ] **2.3 Parliamentary Questions:** compare stored `parliamentary_questions`
  against the discovered question universe
  (`backend/scripts/discover_parliamentary_questions.py`,
  `ingest_all_parliamentary_questions.py`). Record coverage by year and house.
- [ ] **2.4 Internal expected-universe fixtures:** reconcile production `politicians`
  against the `expected_representative_universe` table and reviewed fixtures
  (PR #56 landed reviewed-fixture ingestion). If the expected MP universe is
  unavailable, the readiness report must say so — that alone keeps MP coverage red.
- [ ] **2.5 Record missing coverage** in `V1_READINESS_REPORT.md` as a per-source
  table: expected, present, missing, and whether the gap is launch-blocking.

## Workstream 3 — Ingestion / backfill completion

Goal: launch-critical data is backfilled, and one bad record can never kill a job.

- [ ] **3.1 Inventory pipeline completeness.** For each pipeline (PMG documents,
  PMG meetings/attendance, People's Assembly, parliamentary questions, committees,
  bills, votes, IEC), record: last successful run, cursor position, and remaining
  backlog. Sources: `ingestion_runs` / `ingestion_errors` tables,
  `backend/scripts/generate_ingestion_brief.py`, `GET /ingestion/runs`.
- [ ] **3.2 Land the in-flight identity-bootstrap work.** Branch
  `codex/production-identity-bootstrap-verification` (committee_name on meetings,
  4-strategy question/meeting linker, production verification script) must be
  PR'd, reviewed, and merged before backfills rerun — reingestion must preserve
  identity links (commit 82c4a31 behaviour).
- [ ] **3.3 Run or create safe backfill jobs** for missing launch-critical data only
  (MPs, committees, meetings, questions, attendance, memberships). Use the existing
  batch pattern in `backend/scripts/ingestion_batch_utils.py` (bounded URLs,
  per-record soft failure, systemic-failure detection). The untracked
  `.github/workflows/committee-name-backfill.yml` needs to be committed on its own
  branch, reviewed, and run.
- [ ] **3.4 Preserve cursor safety.** Backfills must not reset or corrupt ingestion
  cursors; reruns must be idempotent (upsert-by-source-URL/checksum, no duplicate
  rows). Add a test where one is missing.
- [ ] **3.5 Verify scheduler resilience — required properties:**
  - 45-second request timeout,
  - exponential backoff retries,
  - soft failure per record (log to `ingestion_errors`, continue),
  - no full-job crash from one bad PMG record.

  **Current state (audit finding):** fetchers use 20–30s timeouts
  (`app/ingestion/*.py`) and `ingestion_batch_utils.py` retries are linear
  (`retry_attempts=2`, fixed sleep) — the 45s timeout and exponential backoff do
  **not** exist on `main` yet. Either they live in unmerged work (verify when 3.2
  lands) or they must be implemented as a small PR with tests. Per-record soft
  failure exists in the batch utils; confirm every launch-critical pipeline
  actually goes through that path.
- [ ] **3.6 Remaining gaps become explicit blockers.** Any launch-critical backfill
  that cannot complete before launch is listed in `V1_READINESS_REPORT.md` as a
  named blocker with reason (e.g. PA access blocked, source down).

## Workstream 4 — Data quality launch gates

Goal: rerunnable scripts that fail loudly on launch-blocking data problems, wired
into the readiness report.

Existing tooling to extend (do not build parallel systems):
`backend/scripts/quality_check.py` + `app/services/quality_service.py`,
`report_mp_coverage.py`, `report_entity_resolution_candidates.py`,
`suggest_unresolved_matches.py`, `/quality/*` API endpoints.

- [ ] **4.1 Duplicate MPs** — same person under multiple `politicians` rows
  (name/alias collision check; use `politician_aliases` + `regenerate_aliases.py`).
- [ ] **4.2 Missing names** — politicians with null/empty/placeholder names.
- [ ] **4.3 Missing party fields** — politicians with no party where the source
  provides one (missing party evidence stays missing — flag, don't infer).
- [ ] **4.4 Missing committee memberships** — committees with zero members; MPs with
  activity records but no memberships.
- [ ] **4.5 Unresolved PMG / People's Assembly entities** — count and trend of
  `unresolved_entities` per source; a rising count is a gate failure.
- [ ] **4.6 Stale ingestion runs** — no successful run for a launch-critical pipeline
  within its expected cadence (daily/weekly per `run_daily_ingestion.py` /
  `run_weekly_ingestion.py` / `run_scheduled_sweep.py`).
- [ ] **4.7 Failed ingestion runs** — recent runs with systemic failures or error
  rates above threshold.
- [ ] **4.8 Wire all gates into the readiness report.** Each gate reports pass/fail +
  offending counts; the aggregate feeds the Red/Amber/Green verdict in
  `V1_READINESS_REPORT.md`. All gates rerunnable with one documented command.

## Workstream 5 — Public V1 readiness

Goal: the public product serves the verified production data, and launch risks are
written down. No cosmetic features unless required to make existing data usable.

- [ ] **5.1 Frontend serves verified production data.** Against the production API:
  politicians list + detail (party, committees, sources), committees, meetings,
  questions, search, quality page. Empty states must be honest where coverage is
  missing (no fake completeness).
- [ ] **5.2 Backend health/readiness endpoints verified in production:**
  `GET /health` → `{"status":"ok"}`, `GET /health/ready` → `{"status":"ready"}`,
  `/quality/summary` returns real totals.
- [ ] **5.3 Deployment docs accurate.** Walk `docs/release-checklist.md` and
  `backend/docs/persistent-db-runbook.md` against the actual production setup;
  fix drift (env vars, migration count, workflow secrets).
- [ ] **5.4 Public launch risks documented** in `V1_READINESS_REPORT.md`: known
  coverage gaps and qualified public wording, PA access blocker (#47), IEC
  limitations (#24 — context only, no inferred winners/office-holders), stale-data
  risk if scheduled ingestion fails, and rollback plan.
- [ ] **5.5 Scheduled ingestion is live in production** (`scheduled-ingestion.yml`
  gated by `INGESTION_ENABLED`), first production run inspected via
  `GET /ingestion/runs`.

---

## Execution rules

1. Work **one checklist item at a time**, in workstream order unless a blocker forces resequencing.
2. Prioritize: data coverage → ingestion reliability → verification → launch confidence.
3. No unrelated features. No refactors unless required to unblock V1.
4. Small focused branches and PRs. Run tests before opening every PR.
5. Every PR description must state: **what changed, why it matters for V1, tests run, risks, rollback plan.**
6. Do not merge your own PRs. Stop after each PR and wait for Codex review.
7. No fabricated records; unknown or missing data stays unknown or missing.

## Definition of done for V1

- [ ] Production data coverage is known (counts published in `V1_READINESS_REPORT.md`).
- [ ] Missing coverage is documented per source system.
- [ ] Launch-critical backfills are complete **or** explicitly listed as blockers.
- [ ] Verification scripts can be rerun with documented commands.
- [ ] `V1_READINESS_REPORT.md` states whether V1 is launch-ready (Red/Amber/Green).
- [ ] Frontend and backend serve the verified production data.
