# KnowYourMPZA Backend

FastAPI backend for verified South African MP data. It ingests People's Assembly profiles and PMG documents, archives fetched HTML, resolves MP aliases, and exposes quality/API endpoints.
It also ingests parliamentary questions as source-backed backend data, including direct PDF URLs and archive pages that link to PDFs, and exposes a source-backed AI ask endpoint.
V1 pairs this backend with a small public frontend in `../frontend`.

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
python scripts/ingest_all_pmg.py --discover-only --year 2026 --committee Health
python scripts/ingest_all_pmg.py --write-discovered
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
--year 2026
--committee Health
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
curl -X POST http://localhost:8000/ai/ask \
  -H "Content-Type: application/json" \
  -d '{"question":"Which MPs asked questions about Eskom?"}'
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
curl http://localhost:8000/quality/duplicates
curl http://localhost:8000/quality/archive-gaps
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

## Scheduled Ingestion

Scheduled scripts are safe by default and exit unless explicitly enabled:

```bash
python scripts/run_daily_ingestion.py
python scripts/run_weekly_ingestion.py
```

Required environment:

```text
DATABASE_URL
INGESTION_ENABLED=true
SOURCE_RATE_LIMIT_SLEEP
MAX_DAILY_INGESTION_URLS
MAX_WEEKLY_INGESTION_URLS
```

Daily ingestion refreshes PMG documents and parliamentary questions, then writes quality/dataset reports.
Weekly ingestion refreshes People’s Assembly MPs, committees, aliases, and the dataset report.

## Production Deployment

The Dockerfile is production friendly for a Docker host with managed PostgreSQL:

```bash
alembic upgrade head
uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

Set:

```text
DATABASE_URL=postgresql+psycopg://...
ENVIRONMENT=production
CORS_ORIGIN=https://your-frontend.example
OPENAI_API_KEY=sk-...
OPENAI_MODEL=gpt-5-mini
```

`OPENAI_API_KEY` is optional for deployment. Without it, `/ai/ask` returns a deterministic source-backed summary from retrieved records; with it, the configured model writes a more natural answer from the same evidence.

Health endpoints:

```bash
curl /health
curl /health/ready
```

Archive storage defaults to local filesystem via `app.services.archive_storage`. S3-compatible storage is stubbed/documented for a later phase.

Backup examples:

```bash
pg_dump "$DATABASE_URL" > backups/knowyourmpza.sql
psql "$DATABASE_URL" < backups/knowyourmpza.sql
tar -czf backups/raw-archives.tgz data/raw
```

## Tests

```bash
pytest
```

No OpenSearch, pgvector, auth, or payments are included in V1.
