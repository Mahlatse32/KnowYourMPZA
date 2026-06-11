# Accountability Data Layer

This document covers the parliamentary accountability layer added to KnowYourMPZA, which tracks bills, voting records, and committee meeting activity.

## Overview

The accountability layer models the lifecycle of legislation and the voting and attendance behaviour of Parliament's members and parties.

It deliberately avoids AI-driven inference. Where source data is unavailable (e.g. individual division lists are not published), the model supports party-level or aggregate records with a clear `record_level` and `confidence` field rather than invented data.

## Models

### `bills` / `bill_events`

Tracks the legislative lifecycle of bills from introduction through assent or rejection.

| Field | Notes |
|---|---|
| `bill_number` | e.g. `B11` |
| `year` | Parliamentary year |
| `house` | `National Assembly`, `NCOP`, or null |
| `status` | `introduced`, `passed`, `assented`, `rejected`, `withdrawn`, `lapsed`, `unknown` |
| `introduced_date`, `passed_date`, `assented_date` | Date fields, all nullable |
| `source_url` | Unique per bill — the canonical source page |
| `source_type` | `pmg` or `parliament` |

`bill_events` records individual steps in a bill's journey (reading, committee referral, signing etc.), linked back to the parent bill.

### `vote_events` / `vote_records`

A `vote_event` is a single division or vote (e.g. "Third reading vote on NHI Bill").

`vote_records` stores the outcome per party or individual:

| Field | Values |
|---|---|
| `record_level` | `individual` \| `party` \| `aggregate` \| `unknown` |
| `vote_value` | `yes` \| `no` \| `abstain` \| `absent` \| `present` \| `unknown` |
| `confidence` | `high` \| `medium` \| `low` |
| `count` | For party/aggregate records, the number of votes cast |

When only party-level data is available (e.g. PMG summary tables), records are stored with `record_level = "party"` and `confidence = "high"`. When individual MP division lists are unavailable, records are not invented.

### `committee_meetings` / `committee_attendance`

`committee_meetings` records a single committee sitting, linked to the committee record.

`committee_attendance` records each name found in the meeting's attendance section. If the name resolves to a known politician via exact match, `politician_id` is set; otherwise `name_raw` is preserved and the record should be reviewed via the unresolved entities workflow.

## Ingestion

| Script | Source |
|---|---|
| `scripts/ingest_bills.py` | PMG bills index + parliament.gov.za bills page |
| `scripts/ingest_votes.py` | PMG vote/division pages (index → individual pages) |
| `scripts/ingest_committee_activity.py` | PMG committee meeting pages |

All scripts are idempotent. Re-running them updates existing records. Missing or unreachable pages log `WARN`/`SKIP` and do not abort the pipeline.

### Rate limiting

`ingest_votes.py` and `ingest_committee_activity.py` accept `--max-pages` (default 20) to limit how many individual pages are fetched per run. Increase carefully to avoid aggressive scraping.

## API Endpoints

| Method | Path | Description |
|---|---|---|
| `GET` | `/bills` | List bills. Filter by `status`, `year`, `house`. |
| `GET` | `/bills/{id}` | Get a single bill by UUID. |
| `GET` | `/bills/{id}/events` | List events for a bill. |
| `GET` | `/votes` | List vote events. Filter by `chamber`. |
| `GET` | `/votes/{id}` | Get a single vote event. |
| `GET` | `/votes/{id}/records` | List vote records for an event. |
| `GET` | `/committee-meetings` | List committee meetings. Filter by `committee_id`. |
| `GET` | `/committee-meetings/{id}` | Get a single meeting. |
| `GET` | `/committee-meetings/{id}/attendance` | List attendance records for a meeting. |

All list endpoints support `limit` (default 50) and `offset` pagination.

## Coverage Reporting

The `/quality/full-coverage` endpoint and `scripts/report_full_coverage.py` now include an `accountability_coverage` section:

```json
{
  "accountability_coverage": {
    "bills_total": 0,
    "bills_with_source_url_pct": null,
    "bills_introduced": 0,
    "bills_passed": 0,
    "bills_assented": 0,
    "vote_events_total": 0,
    "vote_records_total": 0,
    "vote_records_individual": 0,
    "vote_records_party": 0,
    "committee_meetings_total": 0,
    "committee_attendance_total": 0,
    "attendance_resolved_pct": null
  }
}
```

## Migration

`alembic/versions/0009_add_accountability_layer.py` creates all six new tables in dependency order: `bills` → `bill_events` → `vote_events` → `vote_records` → `committee_meetings` → `committee_attendance`.

Run with: `alembic upgrade head`

## Known Limitations

- Individual MP division lists are not consistently available from public sources. Where absent, only party-level aggregates are stored (`record_level = "party"`).
- The PMG bills page structure varies — the parser extracts what it can from table rows and anchor links.
- Committee attendance parsing depends on PMG structuring attendance as `<ul>` lists under recognizable headings. Pages that use other layouts will yield zero attendance records (logged as SKIP, not error).
