# IEC Election Results Ingestion — Design & Runbook

Status: **metadata + source-manifest ingestion implemented**. Vote totals and
result rows are **not** ingested yet. This document covers what this stage
does, the rules it enforces, and the next safe step.

## What this PR ingests (#24)

- `iec_elections` — official election/event **metadata** only: `election_type`
  (national/provincial/municipal/by-election), `election_year` (when
  explicit), `name` (only if explicitly curated), `geography_level`,
  `source_url`, `source_identifier`, `source_date`, `raw_metadata_json`. A row
  is created **only** when a source explicitly labels a concrete electoral
  type; portal/landing ("all"/"unknown") sources get a manifest only.
- `iec_source_manifests` — a reproducible record of each official IEC source:
  `manifest_key` (unique), `source_url`, `source_domain`, `source_type`
  (format), election linkage (`election_key`/type/year), `content_type`,
  `status_code`, `reachable`, `parser_readiness`, `fetched_at`,
  `checksum_sha256` (when a body is fetched), `byte_size`, `raw_manifest_json`.

Ingestion script: `scripts/ingest_iec_metadata_manifest.py` (reuses
`discover_iec_sources.KNOWN_IEC_SOURCES`, official IEC sources only).

## What this PR does NOT do

- **No vote totals / results.** No tables for them are created.
- **No winners.** Election outcomes are never recorded or inferred.
- **No councillors / office-bearers.**
- **No party mappings.**
- **No geography (ward/municipality) mappings.**
- **No invented dates or names** — only explicit/curated labels are stored.

## Guarantees

- **Source evidence retained:** every manifest keeps its exact `source_url`
  and `raw_manifest_json`.
- **Idempotent:** rows upsert on `manifest_key` / `election_key`; reruns update
  rather than duplicate (`created_at` and `source_url` are preserved).
- **Bounded + resilient:** per-source failures are captured (redacted) in the
  report and never abort the batch; if all sources fail, the run exits
  non-zero. Live mode does not download large bodies (checksum left null and
  noted); offline-fixture mode is used by tests.
- **Credential-safe:** `DATABASE_URL` is never printed; URL credentials are
  redacted from reports.

## Running

```bash
# offline validation (no DB writes, no network)
python scripts/ingest_iec_metadata_manifest.py --dry-run --offline-fixture <fixture.json>

# real ingestion (needs DATABASE_URL)
python scripts/ingest_iec_metadata_manifest.py --limit 20 --sleep 1.0
```

Reports: `reports/iec_metadata_manifest_report.{json,md}` (gitignored).

## Migration

`alembic/versions/0011_add_iec_metadata_manifest.py` adds `iec_elections` and
`iec_source_manifests`. Run `alembic upgrade head`.

## Next recommended IEC PR

Parse **one** official structured IEC result format (e.g. a specific CSV/XLSX
export reachable from a manifest with `parser_readiness =
structured-candidate`) into **vote totals only**, behind fixture tests:

- Add a `iec_result_rows` (or similar) table keyed to a manifest + explicit
  geography/contest identifiers **from the source** — never inferred.
- Parse only that one format; store the manifest `checksum_sha256` as
  provenance; keep unmatched geography/party identifiers unresolved.
- Still **no winner inference** and **no office-bearer creation**.
- Bounded, idempotent, fixture-tested before any live run.
