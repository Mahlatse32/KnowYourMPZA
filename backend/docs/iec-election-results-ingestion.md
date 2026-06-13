# IEC Election Results Ingestion - Design and Runbook

Status: **metadata, source-manifest, and one audited CSV vote-total parser
implemented**. The parser foundation is local-file driven; no live results
workflow is enabled.

## Implemented data

`iec_elections` stores official election metadata only when the source
explicitly identifies the election type. `iec_source_manifests` stores each
official source URL, format, fetch state, parser readiness, checksum when
available, and raw manifest metadata.

`iec_vote_totals` stores vote totals from one audited CSV profile:

`Contest_ID, Contest_Name, Province_ID, Province_Name, Party_ID, Party_Name,
Candidate_ID, Candidate_Name, Votes`.

Every vote row retains its manifest key, source URL, source row number, raw
row JSON, and row checksum. Source contest, geography, party, and optional
candidate identifiers are stored as supplied and are not mapped to internal
entities.

## Guarantees

- Source evidence is retained through the exact source URL, manifest, checksum
  metadata, raw row, and row checksum.
- Ingestion is idempotent. A stable identity is built from the manifest and
  explicit source identifiers, excluding the vote value so an official
  correction updates the existing row.
- Invalid rows are reported without aborting valid rows. A file where every
  data row fails returns a non-zero exit status.
- Reports redact credentials and are written under the gitignored `reports/`
  directory.
- Tests use tiny offline fixtures and never call IEC.

## Explicit non-goals

- No winner or outcome inference.
- No councillor or office-bearer creation.
- No internal party or candidate mapping.
- No ward, municipality, or other internal geography mapping.
- No invented dates, names, identifiers, or vote totals.
- No live or scheduled result-file download.

## Running

### Dry-run first

Every operator run starts with `--dry-run`. Do not ingest a result file until
its official source URL, manifest key, checksum, parser profile, row failures,
and safety flags have been reviewed.

Create or refresh metadata and manifests first:

```bash
python scripts/ingest_iec_metadata_manifest.py --limit 20 --sleep 1.0
```

For a no-network validation, use the tiny test fixture:

```bash
python scripts/ingest_iec_metadata_manifest.py \
  --dry-run \
  --offline-fixture tests/fixtures/iec/metadata_manifest_dry_run.json \
  --limit 1
```

### Select the manifest

Choose only a reachable structured manifest whose URL and checksum match the
reviewed local file. Query the database without printing the database
connection string:

```sql
SELECT manifest_key, source_url, source_type, checksum_sha256,
       election_type, election_year, geography_level
FROM iec_source_manifests
WHERE reachable = true
  AND parser_readiness = 'structured-candidate'
ORDER BY fetched_at DESC;
```

Dry-run a reviewed official CSV against its existing manifest:

```bash
python scripts/ingest_iec_vote_totals.py \
  --manifest-key "<existing-manifest-key>" \
  --input-file data/iec/official-party-vote-totals.csv \
  --dry-run
```

Remove `--dry-run` only after checking the manifest, checksum, row failures,
vote sum, unresolved source identifiers, and these explicit false flags:
`winners_ingested`, `office_bearers_ingested`, and
`internal_party_mapping_applied`.

The real command is the same without `--dry-run`:

```bash
python scripts/ingest_iec_vote_totals.py \
  --manifest-key "<reviewed-manifest-key>" \
  --input-file "<reviewed-local-official-file.csv>"
```

Rerunning the same manifest/file pair is idempotent: existing source identities
are updated and are not duplicated.

### Verify reports

Run both coverage views:

```bash
python scripts/report_data_coverage_dashboard.py
python scripts/report_iec_coverage.py
```

The dedicated IEC report must have no orphaned totals, missing source URLs,
missing manifest keys, or duplicate result keys. Yellow means coverage is
incomplete; red means an integrity issue must be fixed. Green does not imply
that winners or office-holders have been derived.

Reports are:

- `reports/iec_metadata_manifest_report.json`
- `reports/iec_metadata_manifest_report.md`
- `reports/iec_vote_totals_report.json`
- `reports/iec_vote_totals_report.md`
- `reports/iec_coverage_report.json`
- `reports/iec_coverage_report.md`

### Artifact hygiene

Do not commit official result downloads, raw archives, generated reports,
database exports, backups, `.env` files, or credentials. Keep reviewed source
files outside the repository. Only tiny intentional offline test fixtures may
be committed.

### Manual workflow

`.github/workflows/iec-ingestion-dry-run.yml` is manual-only. It applies the
schema to an ephemeral database, runs the metadata fixture in dry-run mode,
generates the IEC coverage report, and uploads reports as an Actions artifact.
It does not download IEC files and never invokes vote-total ingestion.

### Next live step

Before any bounded live workflow is proposed:

1. Review an official structured file and record its exact manifest/checksum.
2. Dry-run locally and inspect every row failure.
3. Run the dashboard and IEC quality report.
4. Confirm no winner, councillor, office-holder, or internal entity mapping
   was inferred.
5. Design a bounded, explicit-file workflow with per-file failure capture and
   no source discovery guesswork.

## Structured format audit

Run the structured format audit before parsing a result file:

```bash
python scripts/audit_iec_structured_formats.py \
  --offline-fixture tests/fixtures/iec/structured_format_audit.json
```

The audit writes `reports/iec_structured_format_audit.{json,md}` and performs
no DB writes or large downloads. A format is safe for a parser foundation only
when its audited header/schema contains an explicit vote-total column plus
source contest and party/candidate identifiers.

The tiny audit fixture selects **CSV** as the preferred parser foundation.
This is a header-profile decision, not a claim that live vote totals have been
downloaded or ingested. The exact source manifest and columns must be
revalidated before any operator run.

PR #40 implements that single audited CSV profile for **vote totals only**.
It preserves the manifest checksum, source identifiers, raw row, and row
checksum, while leaving source parties, candidates, and geographies unmapped.
No live IEC download or scheduled vote-total ingestion is enabled.

## Issue #24 status

Issue #24 (Ingest IEC election results) remains **open** — the foundation is in
place but full results ingestion is not complete.

- **Completed:** source discovery, structured-format audit, metadata/source
  manifests, one audited CSV vote-totals parser foundation, coverage quality
  report, and a manual dry-run workflow.
- **Pending review:** controlled live-download audit, reviewed-file ingestion
  workflow, and an unresolved source-identifiers report (open PRs).
- **Remaining:** one controlled reviewed real-file ingestion into real vote
  totals with coverage review; multiple official format parsers; historical
  coverage; corrected/revised release handling; explicit source-identifier
  registries and reconciliation. No winners, office-bearers, councillors, or
  internal party/geography mappings are produced or planned without a separate,
  source-backed design.

## Migrations

- `0011_add_iec_metadata_manifest.py` adds election metadata and source
  manifests.
- `0012_add_iec_vote_totals.py` adds source-backed vote totals.

Run `alembic upgrade head`.

## Next step

Run the dedicated coverage and quality report:

```bash
python scripts/report_iec_coverage.py
```

It writes `reports/iec_coverage_report.{json,md}` and reports manifest
coverage, orphaned rows, evidence gaps, unresolved source identifiers, and a
conservative red/yellow/green public-readiness status. Review it before
enabling any live ingestion path.
