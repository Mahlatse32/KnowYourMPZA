# Data Coverage Guide

KnowYourMPZA ingests South African political data from three public sources. This document explains what each source contributes, how to run ingestion safely, and how to inspect coverage.

---

## Sources

### 1. People's Assembly (`pa.org.za`)

**What it provides:**
- MP profile pages: name, party, province, photo, bio, contact, committee memberships
- Committee listing pages: portfolio, standing, and NCOP committees
- Committee membership details: role and source URL

**Discovery URLs used:**
- `/member/parliament/` — current Parliament members
- `/member/national-assembly/` — current NA members
- `/member/ncop/` — current NCOP members
- `/person/all/` — all persons (includes historical)
- `/organisation/parliament/` — Parliament committees
- `/organisation/ncop/` — NCOP committees
- `/organisation/is/` — ad hoc/select committees

**Scripts:**
```
python scripts/ingest_people_assembly_full.py --dry-run --limit 50
python scripts/ingest_committees_full.py --dry-run --limit 50
```

**Rate limits:** Default 0.5 s between requests. Do not go below 0.3 s.

---

### 2. PMG (`pmg.org.za`)

**What it provides:**
- Committee meeting minutes and published documents
- Each document may mention MPs — these are extracted as `DocumentMention` records with confidence scores
- Archive paths for downloaded HTML

**Discovery:** Keyword search + year filter via PMG's search interface.

**Script:**
```
python scripts/ingest_pmg_full.py --dry-run --from-date 2024-01-01 --to-date 2026-06-10 --limit 200
```

**Rate limits:** Default 0.5 s. PMG is a small NGO — be conservative.

---

### 3. Parliament (`parliament.gov.za`)

**What it provides:**
- Parliamentary questions (questions asked by MPs to ministers)
- Question PDFs via the docsjson API
- Each question may have a resolved `politician_id` (the asker) when entity resolution succeeds

**Discovery:** Parliament's `/docsjson` API, filtered by year.

**Script:**
```
python scripts/ingest_questions_full.py --dry-run --from-date 2024-01-01 --limit 100
```

**Rate limits:** Default 0.5 s.

---

## Running Full Ingestion

The `run_full_ingestion.py` script runs all stages in sequence. Stage failures do not stop the pipeline.

### Safe first run (dry-run):
```bash
cd backend
python scripts/run_full_ingestion.py --dry-run
```

### Incremental run (recommended):
```bash
python scripts/run_full_ingestion.py \
  --from-date 2024-05-29 \
  --to-date 2026-06-10 \
  --politician-limit 500 \
  --committee-limit 500 \
  --pmg-limit 500 \
  --question-limit 500 \
  --sleep 0.5
```

### Skip stages:
```bash
python scripts/run_full_ingestion.py --skip-pmg --skip-questions --politician-limit 200
```

### Include former MPs:
```bash
python scripts/run_full_ingestion.py --include-former --politician-limit 1000
```

All ingestion scripts are **idempotent**: re-running them updates existing records but does not create duplicates (upsert by slug or source URL).

---

## Inspecting Coverage

### Coverage report (file):
```bash
cd backend
python scripts/full_coverage_report.py
cat reports/full_coverage_report.json
```

### Coverage via API:
```
GET /quality/full-coverage
GET /quality/summary
GET /quality/issues
GET /quality/duplicates
GET /quality/archive-gaps
```

The `/quality/full-coverage` endpoint returns the same data as the script, queried live from the database.

**Key fields to check:**

| Field | What it tells you |
|---|---|
| `politician_coverage.with_party_pct` | % of politicians with a known party |
| `politician_coverage.with_aliases_pct` | % with generated aliases (needed for mention matching) |
| `committee_coverage.committees_without_memberships` | Committees with no members ingested |
| `pmg_coverage.with_mentions_pct` | % of PMG docs that mention at least one politician |
| `question_coverage.resolved_asker_pct` | % of questions linked to a known MP |
| `unresolved_entity_coverage.open` | Names not yet matched to any politician |
| `recommendations` | Actionable list of what to fix next |

---

## Unresolved Entity Handling

Unresolved entities are names encountered during ingestion that could not be matched to a known politician. They are stored in the `unresolved_entities` table with `status=OPEN`.

### Review open entities:
```
GET /unresolved-entities?status=OPEN&limit=100
GET /unresolved-entities?status=OPEN&name=Dlamini
GET /unresolved-entities?entity_type=POLITICIAN
```

### Generate match suggestions (safe, read-only):
```bash
python scripts/suggest_unresolved_matches.py
cat reports/unresolved_match_suggestions.json
```

### Auto-resolve high-confidence matches:
```bash
# Review the report first, then:
python scripts/suggest_unresolved_matches.py --apply --threshold 0.9
```

**Threshold floor is 0.9** — the script refuses `--apply` below this.

### Manual resolution via API:
```
POST /unresolved-entities/{id}/resolve
{ "politician_id": "...", "notes": "Confirmed match", "create_alias": true }

POST /unresolved-entities/{id}/ignore
{ "notes": "Not an MP — journalist name" }
```

---

## Safe Re-run Guide

All scripts are safe to re-run:

1. **Politicians and committees** are upserted by slug — no duplicate rows
2. **Committee memberships** are upserted by `(politician_id, committee_id, role)`
3. **PMG documents** are upserted by source URL
4. **Parliamentary questions** are upserted by source URL
5. **Ingestion runs** create a new row each time (run history is preserved)
6. **Unresolved entities** are inserted only when a name cannot be resolved

To re-process a specific source from scratch, set `--from-date` and `--to-date` to the target window.

---

## Known Limitations

- **Politician totals**: The exact current count of NA + NCOP members is not automatically verified. Coverage % for politicians is marked `null` rather than using an invented denominator.
- **Former MP coverage**: People's Assembly `person/all/` includes historical persons. Use `--include-former` to ingest them.
- **PMG corpus size**: The full PMG archive is very large. Recommend incremental ingestion by year with a reasonable `--pmg-limit`.
- **PDF parsing**: Some Parliament question PDFs fail `pypdf` extraction. Failed parses are logged as `parse_status=FAILED` and do not crash the pipeline.
- **Entity resolution recall**: The resolution algorithm matches on full name, display name, slug, and aliases. Names that differ significantly (e.g. nicknames not in aliases) will remain unresolved until aliases are added.
- **S3 archive**: Archive storage currently uses local disk only. `ARCHIVE_STORAGE_MODE=s3` is stubbed and not yet implemented.

---

## Personal-Use Workflow

For a local research database, the recommended cadence is:

1. **Initial load** (once):
   ```bash
   python scripts/run_full_ingestion.py \
     --from-date 2019-05-29 \
     --politician-limit 1000 --committee-limit 500 \
     --pmg-limit 2000 --question-limit 2000 \
     --sleep 0.5
   ```

2. **Weekly top-up** (scheduled):
   ```bash
   python scripts/run_full_ingestion.py \
     --from-date $(date -d '7 days ago' +%Y-%m-%d) \
     --pmg-limit 500 --question-limit 500 \
     --sleep 0.5
   ```

3. **After new Parliament session** (ad hoc):
   ```bash
   python scripts/ingest_people_assembly_full.py --limit 600 --sleep 0.5
   python scripts/ingest_committees_full.py --limit 300 --sleep 0.5
   ```

4. **Unresolved entity triage** (periodic):
   ```bash
   python scripts/suggest_unresolved_matches.py
   # Review reports/unresolved_match_suggestions.json
   python scripts/suggest_unresolved_matches.py --apply --threshold 0.92
   ```

5. **Coverage check**:
   ```bash
   python scripts/full_coverage_report.py
   ```
