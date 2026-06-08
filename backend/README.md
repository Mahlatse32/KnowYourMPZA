# KnowYourMPZA Backend

FastAPI backend for verified South African MP data. It ingests People's Assembly profiles and PMG documents, archives fetched HTML, resolves MP aliases, and exposes quality/API endpoints.
It also ingests parliamentary questions as source-backed backend data, including direct PDF URLs and archive pages that link to PDFs, without adding AI, chatbot, frontend, auth, or search infrastructure.

## Run

```bash
docker compose up --build
```

## Migrate

```bash
alembic upgrade head
```

## Seed Fallback

Seed data is for demo fallback only. Real source ingestion should be used for normal development.

```bash
curl -X POST http://localhost:8000/ingest/seed
```

## Real Ingestion

```bash
python scripts/ingest_people_assembly.py data/people_assembly_urls.txt
python scripts/ingest_pmg_documents.py data/pmg_urls.txt
python scripts/ingest_parliamentary_questions.py data/parliamentary_question_urls.txt
```

Parliamentary question ingestion stores `parliamentary_questions`, `question_mentions`, and unresolved MP names in `unresolved_entities`. It preserves `asked_by_name`, `source_url`, and `archive_path` even when the asker cannot be linked to a politician yet.
PDF files are archived under `data/raw/parliament_questions/` and `data/raw/pdfs/` before text extraction.

## Parliamentary Question Discovery

```bash
python scripts/discover_parliamentary_questions.py --limit 100 --dry-run
python scripts/discover_parliamentary_questions.py --limit 100
python scripts/ingest_all_parliamentary_questions.py --limit 50 --sleep 0.5
```

Useful flags:

```text
--file data/parliamentary_question_urls.txt
--limit 100
--dry-run
--year 2026
--sleep 0.5
```

## Bulk Source Discovery

Discover and ingest source-backed records in batches:

```bash
python scripts/ingest_all_people_assembly.py --limit 100
python scripts/ingest_all_people_assembly.py --discover-only
python scripts/ingest_all_people_assembly.py --write-discovered
python scripts/ingest_all_committees.py --limit 100
python scripts/ingest_all_committees.py --discover-only
python scripts/ingest_all_committees.py --write-discovered
python scripts/regenerate_aliases.py
python scripts/ingest_all_pmg.py --limit 50
```

Useful flags:

```text
--file data/people_assembly_urls.txt
--file data/pmg_urls.txt
--limit 50
--dry-run
--sleep 0.5
--discover-only
--write-discovered
```

The bulk scripts merge URLs from local text files with discovered URLs, archive raw HTML, continue after failed URLs, and record ingestion runs/errors. `--write-discovered` updates `data/people_assembly_urls.txt` or `data/committee_urls.txt` with canonical discovered URLs without duplicates.

People’s Assembly ingestion stores source status and last-seen timestamps, normalizes party names/short names, preserves profile/photo URLs, and updates existing politicians by profile URL or slug. Committee ingestion normalizes committee names and roles, upserts memberships, and creates `unresolved_entities` rows for member names that cannot be safely resolved.

## Ingestion Runs

```bash
curl "http://localhost:8000/ingestion/runs?limit=20&offset=0"
curl http://localhost:8000/ingestion/runs/{run_id}
```

## Browse APIs

```bash
curl "http://localhost:8000/parties?limit=50&offset=0"
curl http://localhost:8000/parties/{party_id}/politicians
curl "http://localhost:8000/committees?limit=50&offset=0"
curl http://localhost:8000/committees/{committee_id}/politicians
curl "http://localhost:8000/documents?limit=50&offset=0"
curl http://localhost:8000/documents/{document_id}
curl "http://localhost:8000/questions?limit=50&offset=0"
curl "http://localhost:8000/questions?department=Basic%20Education"
curl http://localhost:8000/questions/{question_id}
curl "http://localhost:8000/politicians/{politician_id}/questions?limit=50&offset=0"
```

## Quality

```bash
python scripts/quality_check.py
python scripts/dataset_report.py
curl http://localhost:8000/quality/summary
curl http://localhost:8000/quality/issues
```

The quality summary includes totals, alias coverage, parliamentary question counts, PDF question source counts, parse failures/partials, unresolved entity status counts, active/inactive/unknown politician status, ingestion run/error counts, archive-path coverage, committees without memberships, and duplicate slug/party/membership/source URL checks.

`/quality/issues` returns structured cleanup queues. `scripts/dataset_report.py` writes `reports/dataset_report.json`, which is ignored by Git for milestone tracking.

## Unresolved Entities

```bash
curl "http://localhost:8000/unresolved-entities?status=OPEN"
curl http://localhost:8000/unresolved-entities/{entity_id}
curl -X POST http://localhost:8000/unresolved-entities/{entity_id}/resolve \
  -H "Content-Type: application/json" \
  -d '{"politician_id":"POLITICIAN_UUID","create_alias":true,"alias_type":"SOURCE_VARIANT","notes":"Resolved from committee page"}'
curl -X POST http://localhost:8000/unresolved-entities/{entity_id}/ignore \
  -H "Content-Type: application/json" \
  -d '{"notes":"Not an MP"}'
```

Known limitation: parliamentary question PDF parsing is text extraction first. Scanned PDFs, detailed question/reply matching, and source-specific layouts still need deeper handling.
Committee discovery currently uses People’s Assembly committee/organisation pages and may include historical committees; quality reports show remaining cleanup gaps.

## Tests

```bash
pytest
```

No chatbot, AI, OpenSearch, pgvector, frontend, auth, payments, or voting records are included in this MVP.
