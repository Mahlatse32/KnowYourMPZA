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

Create or refresh metadata and manifests first:

```bash
python scripts/ingest_iec_metadata_manifest.py --limit 20 --sleep 1.0
```

Dry-run a reviewed official CSV against its existing manifest:

```bash
python scripts/ingest_iec_vote_totals.py \
  --manifest-key "<existing-manifest-key>" \
  --input-file data/iec/official-party-vote-totals.csv \
  --dry-run
```

Remove `--dry-run` only after checking the manifest, checksum, row failures,
and safety flags. Reports are:

- `reports/iec_metadata_manifest_report.json`
- `reports/iec_metadata_manifest_report.md`
- `reports/iec_vote_totals_report.json`
- `reports/iec_vote_totals_report.md`

## Migrations

- `0011_add_iec_metadata_manifest.py` adds election metadata and source
  manifests.
- `0012_add_iec_vote_totals.py` adds source-backed vote totals.

Run `alembic upgrade head`.

## Next step

Add a dedicated IEC coverage and quality report for manifest coverage, row
failures, source identifier completeness, and unresolved source actors.
Review that report before enabling any live ingestion path.
