# KnowYourMPZA Data Product Roadmap

Last reviewed: 2026-06-13

The data is the product: source-backed public South African political data,
no fabricated records, automation-first. This roadmap states what is built,
what is discovery-only, and what comes next — so coverage can expand
systematically without overreach.

## 1. Current capabilities

- **Persistent database** (Supabase PostgreSQL) configured for scheduled runs.
- **Alembic migrations** at head (`0010_add_ingestion_sweep_states`).
- **Scheduled ingestion** (`.github/workflows/scheduled-ingestion.yml`) — daily
  and weekly, secret-gated (`INGESTION_ENABLED`, `DATABASE_URL`).
- **Accountability sweep** (`.github/workflows/accountability-sweep.yml`) —
  bounded, resumable PMG sweeps with durable cursor state.
- **Source resilience** (`scripts/ingestion_batch_utils.py`) — per-item
  failure handling so one bad URL does not abort a run; systemic failures
  still fail the job.
- **Reports / artifacts** — ingestion brief, data coverage dashboard, DB
  readiness, ingestion-alert triage; uploaded as CI artifacts (never
  committed), summarized to the Actions step summary.
- **Coverage dashboard** (`scripts/report_data_coverage_dashboard.py`) — counts,
  source/accountability coverage, data-quality risk table, public-claim
  readiness, and a source-discovery-status section.
- **Source inventory** (`docs/source-inventory.md`) — living register of
  implemented vs candidate sources.

## 2. Currently implemented data sources

- People's Assembly member profiles and committee pages.
- PMG committee documents (HTML corpus).
- PMG public bills API (bills + lifecycle events).
- PMG public committee-meeting API (meetings + explicit attendance).
- PMG meeting-minutes vote signals (vote events; explicit aggregate vote
  records only).
- Parliament questions, replies, papers, and archive.
- Parliament official member listings (cross-reference bridge, limited).

## 3. Discovery-only areas (no ingestion yet)

These have discovery/audit scripts and design docs, but **no ingestion and no
schema**:

- IEC election results — `scripts/discover_iec_sources.py`.
- Government Gazette / Acts / Bills metadata —
  `scripts/discover_gazette_acts_sources.py` (+ design doc).
- Municipal councils and office-bearers —
  `scripts/discover_municipal_sources.py` (+ design doc).
- Chapter 9 institution reports —
  `scripts/discover_chapter9_report_sources.py` (+ design doc).
- Parliamentary votes / divisions expansion —
  `scripts/audit_votes_divisions_sources.py` (+ design doc).

## 4. Open issues mapped to phases

| Phase | Issue | Theme |
|---|---|---|
| Operate | #18 | Automated red-brief alert (triage; root cause: Supabase pooler prepared statements) |
| Quality | #28 | Entity resolution for unresolved political actors |
| Expand: elections | #24 | IEC election results |
| Expand: accountability | #7 | Parliamentary voting / division records |
| Expand: legislation | #25 | Gazette / Acts / Bills metadata |
| Expand: local govt | #26 | Municipal councils and office-bearers |
| Expand: oversight | #27 | Chapter 9 institution reports and findings |

## 5. Not yet (explicit non-goals for now)

- **No AI / RAG / chatbot.**
- **No OpenSearch.**
- **No frontend.**
- **No public completeness claims** without coverage thresholds and source
  evidence (the dashboard's public-claim-readiness gate must be green).

## 6. Recommended sequence

1. Triage / resolve the red ingestion alert (#18) — fix the Supabase
   transaction-pooler prepared-statement issue so real sweeps run clean.
2. Entity resolution reporting (#28) — improve unresolved-actor quality
   before adding larger datasets.
3. IEC discovery → schema → bounded ingestion (#24).
4. Votes / divisions audit → bounded expansion only where explicit (#7).
5. Gazette / Acts discovery → bill↔act linkage on explicit identifiers (#25).
6. Municipal discovery → councils/office-bearers with confirmed terms (#26).
7. Chapter 9 discovery → report metadata, then evidence-located findings (#27).

## 7. Public-readiness checklist

Before any public-facing completeness claim:

- [ ] Source URL coverage: no implemented domain has records missing
      `source_url` (dashboard red risk = 0).
- [ ] Source date coverage: date-bearing domains within the accepted
      missing-date threshold.
- [ ] Duplicate / alias risk: duplicate identifier candidates reviewed.
- [ ] Unresolved entity risk: open unresolved entities within threshold and
      trending down (#28).
- [ ] Coverage thresholds: per-domain coverage meets the stated bar.
- [ ] Report artifacts: latest ingestion brief and dashboard are green (not
      red); no unaddressed red alert.

No fabricated records, ever. Missing data stays missing.
