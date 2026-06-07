# KnowYourMPZA Backend

FastAPI backend for verified South African MP data. It ingests People's Assembly profiles and PMG documents, archives fetched HTML, resolves MP aliases, and exposes quality/API endpoints.

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
```

## Bulk Source Discovery

Discover and ingest source-backed records in batches:

```bash
python scripts/ingest_all_people_assembly.py --limit 50
python scripts/ingest_all_pmg.py --limit 50
```

Useful flags:

```text
--file data/people_assembly_urls.txt
--file data/pmg_urls.txt
--limit 50
--dry-run
--sleep 0.5
```

The bulk scripts merge URLs from local text files with discovered URLs, archive raw HTML, continue after failed URLs, and record ingestion runs/errors.

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
```

## Quality

```bash
python scripts/quality_check.py
curl http://localhost:8000/quality/summary
```

The quality summary includes totals, alias coverage, active/inactive politician status, ingestion run/error counts, archive-path coverage, and duplicate slug/source URL checks.

## Tests

```bash
pytest
```

No chatbot, AI, OpenSearch, pgvector, frontend, auth, payments, or voting records are included in this MVP.
