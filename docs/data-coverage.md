# Data Coverage Guide

KnowYourMPZA ingests South African political data from three public sources and exposes coverage metrics through both a CLI report and a live API endpoint. This document explains what each source contributes, how to run ingestion safely, and how to interpret coverage.

---

## What "full coverage" means in this project

**Full coverage** means: every record that was reachable from the listed public source URLs during the most recent ingestion run has been ingested, deduplicated, and stored with its source URL preserved.

It does **not** mean:
- That the database contains every MP, committee, or document that Parliament has ever produced
- That coverage percentages are measured against an independently verified authoritative total
- That historical data is complete

Where the authoritative total is unknown, coverage fields return `null` rather than an invented number.

---

## Sources

### 1. People's Assembly (`pa.org.za`)

**What it provides:**
- MP profile pages: name, party, province, photo, bio, committee memberships
- Committee listing pages: portfolio, standing, and NCOP committees
- Committee membership details: role and source URL

**What it does not provide:**
- Complete historical records for all former MPs
- Exact mandate start/end dates in a structured format
- Vote records or attendance data

**Discovery URLs:**
- `/member/parliament/` — current Parliament members
- `/member/national-assembly/` — current NA members
- `/member/ncop/` — current NCOP members
- `/person/all/` — all persons including historical
- `/organisation/parliament/` — Parliament committees
- `/organisation/ncop/` — NCOP committees
- `/organisation/is/` — ad hoc/select committees

**Official Parliament member pages:** The Parliament website (`parliament.gov.za`) has member listing pages, but they do not reliably link to People's Assembly profile URLs. `ingest_parliament_members_full.py` fetches those pages and extracts any PA profile links it finds. In practice most of the useful ingestion comes from People's Assembly directly.

**Scripts:**
```bash
python scripts/ingest_people_assembly_full.py --dry-run --limit 50
python scripts/ingest_parliament_members_full.py --dry-run --limit 50
python scripts/ingest_committees_full.py --dry-run --limit 50
```

**Rate limits:** Default 0.5 s between requests. Do not go below 0.3 s.

---

### 2. PMG (`pmg.org.za`)

**What it provides:**
- Committee meeting minutes and published documents
- Document titles, dates, committee names
- Each document may mention MPs by name — these become `DocumentMention` records with confidence scores
- Downloaded HTML archives

**What it does not provide:**
- A complete structured API — PMG is scraped via search/browse pages
- Full verbatim transcripts in all cases (some are summary minutes)

**Discovery:** Keyword search + year filter via PMG's search interface.

**Script:**
```bash
python scripts/ingest_pmg_full.py --dry-run --from-date 2024-01-01 --to-date 2026-06-10 --limit 200
```

**Rate limits:** Default 0.5 s. PMG is a small NGO — be conservative.

---

### 3. Parliament (`parliament.gov.za`)

**What it provides:**
- Parliamentary questions (questions asked by MPs to ministers)
- Question PDFs via the docsjson API
- Question number, asker name, department, answer text where available
- Each question may resolve the asker to a known politician when entity resolution succeeds

**What it does not provide:**
- A complete structured database of all questions ever asked
- Full Hansard transcripts
- Committee Bills or voting records

**Discovery:** Parliament's `/docsjson` API, filtered by year.

**Script:**
```bash
python scripts/ingest_questions_full.py --dry-run --from-date 2024-01-01 --limit 100
```

**Rate limits:** Default 0.5 s.

---

## Running Full Ingestion

The `run_full_ingestion.py` script runs all stages in order. Stage failures do not stop the pipeline.

### Dry-run first (always start here):
```bash
cd backend
python scripts/run_full_ingestion.py --dry-run
```

### Incremental run (recommended for regular use):
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

**Pipeline stages (in order):**
1. People's Assembly politician profiles
2. Official Parliament member pages
3. Committee pages and memberships
4. PMG meeting documents
5. Parliamentary questions
6. Unresolved entity match suggestions
7. Full coverage report (JSON + Markdown)
8. Search completeness checks

All ingestion scripts are **idempotent**: re-running updates existing records without creating duplicates (upsert by slug or source URL).

---

## Inspecting Coverage

### Coverage report (files):
```bash
cd backend
python scripts/report_full_coverage.py
cat reports/full_coverage_report.json
cat reports/full_coverage_report.md
```

### Coverage via API:
```
GET /quality/full-coverage     — live full coverage report
GET /quality/summary           — quick count summary
GET /quality/issues            — list of data quality issues
GET /quality/duplicates        — duplicate detection
GET /quality/archive-gaps      — records missing archive paths
```

### Search completeness checks:
```bash
python scripts/check_search_completeness.py
cat reports/search_completeness_report.json
cat reports/search_completeness_report.md
```

Search completeness checks exercise the same database queries the API uses. Each check reports PASS/FAIL/WARN/SKIP:
- **PASS** — lookup returned at least one result
- **FAIL** — lookup returned zero results for a value that should be findable
- **WARN** — results exist but have a data quality concern (e.g., no committee_name on a PMG document)
- **SKIP** — no records of this type exist yet

### Key coverage fields to monitor:

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

Unresolved entities are names encountered during ingestion that could not be matched to a known politician, party, or committee. They are stored in the `unresolved_entities` table with `status=OPEN`.

### Review open entities:
```
GET /unresolved-entities?status=OPEN&limit=100
GET /unresolved-entities?status=OPEN&name=Dlamini
GET /unresolved-entities?entity_type=POLITICIAN
```

### How suggestions work:
The `suggest_unresolved_matches.py` script queries all OPEN unresolved entities and runs each name through the entity resolution service. It generates a JSON report of suggested politician matches ranked by confidence score.

Suggestions are **never auto-applied** unless you explicitly pass `--apply`. Always review the report first.

```bash
python scripts/suggest_unresolved_matches.py
cat reports/unresolved_match_suggestions.json

# After reviewing, apply only high-confidence matches:
python scripts/suggest_unresolved_matches.py --apply --threshold 0.92
```

**Threshold floor is 0.9** — the script refuses `--apply` with any lower value.

### Manual resolution via API:
```
POST /unresolved-entities/{id}/resolve
{ "politician_id": "...", "notes": "Confirmed match", "create_alias": true }

POST /unresolved-entities/{id}/ignore
{ "notes": "Not an MP — journalist name" }
```

---

## Where raw archives are stored

Raw archives (downloaded HTML pages, PDF files) are stored under:

```
backend/data/raw/
  pmg/          — PMG meeting pages
  parliament_questions/   — Question PDFs
```

**Raw archives are gitignored.** They are large binary/HTML files that have no place in version control. The `.gitignore` already excludes `backend/data/raw/`.

If you need to back up archives, use an external storage solution (e.g., local NAS, S3-compatible store). S3 support is stubbed in the codebase (`ARCHIVE_STORAGE_MODE=s3`) but not yet implemented.

---

## Safe re-run guide

All scripts are safe to re-run:

1. **Politicians and committees** — upserted by slug, no duplicate rows
2. **Committee memberships** — upserted by `(politician_id, committee_id, role)`
3. **PMG documents** — upserted by source URL
4. **Parliamentary questions** — upserted by source URL
5. **Ingestion runs** — new row per run (full run history preserved)
6. **Unresolved entities** — inserted only when a name cannot be resolved

To re-process a specific time window, set `--from-date` and `--to-date`.

---

## Source politeness rules

- Default sleep between requests: **0.5 seconds** (`--sleep 0.5`)
- Do not set sleep below 0.3 s for People's Assembly or PMG
- Use `--dry-run` before any production ingestion
- If a source returns HTTP 429 (rate limited), back off and retry after several minutes
- Never use concurrent requests against these sources — they are small NGOs

---

## Troubleshooting failed downloads / PDF extraction

**Failed HTML download:**
- Check network connectivity and source availability
- Look in `reports/full_coverage_report.json` → `latest_ingestion_errors`
- Re-run the specific ingestion script with `--limit 1` and the URL as input

**Failed PDF extraction:**
- The question is stored with `parse_status=FAILED`
- The PDF is still archived at `archive_path`
- Check `quality/issues` → `documents_without_mentions`
- `pypdf` may fail on scanned/image-only PDFs — these cannot be extracted without OCR

**Unresolved entities not matching:**
- Run `scripts/suggest_unresolved_matches.py` to get suggestions
- If confidence is below 0.9, manually inspect and resolve via API
- Check that `scripts/regenerate_aliases.py` has been run after adding new politicians

---

## Known limitations

- **Politician totals**: The exact current count of NA + NCOP members is not automatically verified. Coverage % fields return `null` rather than an invented denominator.
- **Former MP coverage**: Use `--include-former` flag to ingest historical MPs from People's Assembly.
- **PMG corpus size**: The full PMG archive spans many years and is very large. Incremental ingestion by year is recommended.
- **PDF parsing**: Some Parliament question PDFs fail `pypdf` extraction (image-only scans). These are logged as `parse_status=FAILED`.
- **Entity resolution recall**: Names that differ significantly from any stored alias (e.g., nicknames, titles, transliteration differences) will remain unresolved until aliases are added.
- **S3 archive**: `ARCHIVE_STORAGE_MODE=s3` is stubbed and not yet implemented.
- **No AI or OpenSearch**: This project deliberately excludes AI/embedding search. All lookups use PostgreSQL full-text and ILIKE queries.

---

## Personal-use workflow

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
   python scripts/report_full_coverage.py
   python scripts/check_search_completeness.py
   ```
