# Government Gazette / Acts / Bills Ingestion — Design

Status: **design + discovery only**. No gazette/act ingestion exists. This
document defines how ingestion *would* work so it can be built safely later.
Bills metadata is already ingested from the PMG bill API; this design extends
toward enacted legislation (acts) and gazette notices and links them to bills.

## Non-negotiable rules

- **No fabricated records.** Never create an act, gazette notice, or
  bill→act link that is not directly evidenced by an official source.
- **Source evidence required.** Every record stores a stable official
  `source_url` and a `source_date`/`published_date` where the source states
  one. Raw PDFs are archived outside Git.
- **No inferred linkage.** A bill is linked to an act only when an official
  identifier (act number/year, or an explicit cross-reference) connects them.
  Name similarity alone is never sufficient.
- **Official sources only.** gov.za and parliament.gov.za. Media summaries are
  not evidence of enactment.

## Candidate sources

See `reports/gazette_acts_source_discovery.json` (from
`scripts/discover_gazette_acts_sources.py`). Primary: gov.za acts/notices/
regulations indexes; parliament.gov.za acts; PMG bill API (already ingested)
for the bill side of the linkage.

## Proposed tables / extensions

- `acts` — `id`, `act_number`, `year`, `title`, `source_url` (unique),
  `published_date`, `gazette_reference`, `source_owner`, `archive_path`,
  timestamps.
- `gazette_notices` — `id`, `gazette_number`, `notice_number`, `title`,
  `notice_type`, `published_date`, `source_url` (unique), `archive_path`.
- `bill_act_links` — `id`, `bill_id` (FK bills), `act_id` (FK acts),
  `linkage_evidence` (the explicit identifier/cross-reference used),
  `source_url`, `confidence` (`explicit` only — no inferred links stored).

Each table keeps `source_url` unique to guarantee idempotent upserts.

## Bills-to-acts linkage strategy

1. Parse the act's official metadata, including any "originating bill" or bill
   number reference where the source provides it.
2. Match to an existing `bills` row only on that explicit identifier.
3. If no explicit identifier exists, store the act unlinked and record the gap
   in the coverage report — never guess from titles.

## Idempotency strategy

Upsert by unique `source_url` (and natural key `act_number`+`year` where
present). Re-running a discovery/ingestion window updates rather than
duplicates. Per-item failures are recorded with source URL + safe error and do
not abort the batch (consistent with `scripts/ingestion_batch_utils.py`).

## Parser risk

gov.za and parliament.gov.za pages may be JavaScript shells or large PDFs.
Parser readiness is tracked per source in the discovery report. PDF text
extraction quality must be validated before any act text is trusted.

## What must not be inferred

- Enactment status or dates not stated by the source.
- Bill→act links without an explicit shared identifier.
- Amendment relationships between acts unless the source states them.
