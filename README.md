# KnowYourMPZA

KnowYourMPZA is a verified South African political data backend. It stores MPs, parties, committee memberships, source documents, raw HTML archives, aliases, and document mentions so downstream products can answer evidence-backed questions about Members of Parliament.

It is not a chatbot. V1 intentionally excludes AI, OpenSearch, pgvector, authentication, payments, bills, and voting records.

V1 adds a simple public website for searching and browsing the source-backed dataset. V1 still intentionally excludes LLM summaries, chat, authentication, payments, bills, and voting records.

## MVP Features

- PostgreSQL-backed FastAPI API.
- SQLAlchemy 2.x models with Alembic migrations.
- Seed fallback data for demos.
- Real People's Assembly MP profile ingestion.
- Real PMG committee meeting/document ingestion.
- Parliamentary questions ingestion for source-backed MP questions and answers.
- PDF extraction for parliamentary question papers/replies and archive pages that link to PDFs.
- Bulk People's Assembly URL discovery for current MP profiles.
- Full MP coverage workflow using People’s Assembly discovery plus curated URL lists.
- Committee page discovery and committee membership ingestion.
- Bulk PMG URL discovery from PMG search pages.
- Raw HTML archiving under `backend/data/raw/`.
- Politician aliases, surname-safe fallback matching, and entity resolution.
- Ingestion run/error logging for API and CLI batches.
- Quality summary endpoint and CLI report.
- Quality issues endpoint for structured cleanup queues.
- Dataset report script for milestone tracking.
- Public React/Vite frontend under `frontend/`.
- CI and guarded scheduled ingestion workflows.
- Browse endpoints for parties, committees, and documents.
- Browse endpoints for parliamentary questions.
- Discovery scripts for parliamentary question listings and PDF sources.
- Basic pytest coverage for the main product path.

## Tech Stack

- Python 3.12
- FastAPI
- PostgreSQL
- SQLAlchemy 2.x
- Alembic
- Pydantic
- Docker Compose
- Requests
- BeautifulSoup4
- pytest

## Folder Structure

```text
backend/
  app/
    ingestion/      HTML fetch, archive, parse helpers
    models/         SQLAlchemy models
    routers/        FastAPI endpoints
    schemas/        Pydantic responses and requests
    services/       ingestion, quality, entity resolution
  alembic/          migrations
  data/
    people_assembly_urls.txt
    committee_urls.txt
    pmg_urls.txt
    parliamentary_question_urls.txt
    raw/
  scripts/
  tests/
```

## Start Docker

From the project root:

```bash
docker compose up --build
```

The API runs at `http://localhost:8000`. PostgreSQL is internal to Compose and persists in a Docker volume.

## Frontend

```bash
cd frontend
npm install
npm run dev
```

Set `VITE_API_BASE_URL` when the backend is not running on `http://localhost:8000`.

```bash
npm run build
```

## Migrations

The backend container runs migrations automatically before Uvicorn starts.

Manual migration commands from `backend/`:

```bash
alembic upgrade head
alembic revision --autogenerate -m "change description"
```

## Seed Fallback Data

Seed data is for demos and offline fallback only. Prefer real ingestion for normal development and use the seed endpoint only when you need a quick local smoke test:

```bash
curl -X POST http://localhost:8000/ingest/seed
```

## Real Ingestion

People's Assembly profiles:

```bash
curl -X POST http://localhost:8000/ingest/people-assembly \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://www.pa.org.za/person/julius-sello-malema/"]}'
```

PMG documents:

```bash
curl -X POST http://localhost:8000/ingest/pmg-documents \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://pmg.org.za/committee-meeting/43172/"]}'
```

Batch endpoints are idempotent and return:

```json
{
  "processed_count": 0,
  "created_count": 0,
  "updated_count": 0,
  "skipped_count": 0,
  "failed_count": 0,
  "errors": []
}
```

One failed URL does not stop the batch.

Parliamentary questions:

```bash
curl -X POST http://localhost:8000/ingest/parliamentary-questions \
  -H "Content-Type: application/json" \
  -d '{"urls":["https://www.parliament.gov.za/questions-and-replies"]}'
```

Question ingestion preserves the original `asked_by_name`, links to a politician when entity resolution is confident, stores unresolved MP names in `unresolved_entities`, and keeps the source URL and archive path as evidence.
It supports direct PDF URLs, HTML pages that link to PDFs, and Parliament archive pages with downloadable PDFs. PDF files are archived before extraction.

Every API ingestion call creates an ingestion run record. Inspect recent runs with:

```bash
curl "http://localhost:8000/ingestion/runs?limit=20&offset=0"
curl http://localhost:8000/ingestion/runs/{run_id}
```

## URL Lists

Edit these files, one URL per line:

```text
backend/data/people_assembly_urls.txt
backend/data/pmg_urls.txt
backend/data/parliamentary_question_urls.txt
```

Run CLI ingestion from the project root:

```bash
python backend/scripts/ingest_people_assembly.py backend/data/people_assembly_urls.txt
python backend/scripts/ingest_pmg_documents.py backend/data/pmg_urls.txt
python backend/scripts/ingest_parliamentary_questions.py backend/data/parliamentary_question_urls.txt
```

Inside the Docker backend container, use container-relative paths:

```bash
docker compose exec backend python scripts/ingest_people_assembly.py data/people_assembly_urls.txt
docker compose exec backend python scripts/ingest_pmg_documents.py data/pmg_urls.txt
docker compose exec backend python scripts/ingest_parliamentary_questions.py data/parliamentary_question_urls.txt
```

Discover and ingest parliamentary question sources:

```bash
docker compose exec backend python scripts/discover_parliamentary_questions.py --limit 100 --dry-run
docker compose exec backend python scripts/discover_parliamentary_questions.py --limit 100
docker compose exec backend python scripts/ingest_all_parliamentary_questions.py --limit 50 --sleep 0.5
```

Useful question discovery flags:

```text
--file data/parliamentary_question_urls.txt
--limit 100
--dry-run
--year 2026
```

## Bulk Discovery Ingestion

To grow from the seeded MVP to a larger real dataset, use the bulk scripts. They combine URLs from the local list files with discovered source URLs, skip duplicate URLs, keep going after per-URL failures, archive fetched HTML, and create ingestion run/error records.

People's Assembly:

```bash
docker compose exec backend python scripts/ingest_all_people_assembly.py --limit 100
docker compose exec backend python scripts/ingest_all_people_assembly.py --discover-only
docker compose exec backend python scripts/ingest_all_people_assembly.py --write-discovered
```

Committee coverage:

```bash
docker compose exec backend python scripts/ingest_all_committees.py --limit 100
docker compose exec backend python scripts/ingest_all_committees.py --discover-only
docker compose exec backend python scripts/ingest_all_committees.py --write-discovered
docker compose exec backend python scripts/regenerate_aliases.py
```

PMG:

```bash
docker compose exec backend python scripts/ingest_all_pmg.py --limit 50
docker compose exec backend python scripts/ingest_all_pmg.py --dry-run --limit 50
```

Useful flags:

```text
--file path/to/urls.txt
--limit 50
--dry-run
--sleep 0.5
--discover-only
--write-discovered
--year 2026
--committee Health
```

`--write-discovered` appends newly discovered canonical URLs to the relevant local URL list without duplicating existing lines:

```text
backend/data/people_assembly_urls.txt
backend/data/committee_urls.txt
```

People’s Assembly profile ingestion now stores `source_status`, `source_last_seen_at`, `profile_url`, `photo_url`, normalized party details, profile source evidence, and generated aliases. Re-ingestion updates matching politicians by profile URL or slug rather than creating duplicates.

Committee ingestion normalizes committee names and roles, resolves member names through the existing entity-resolution service, updates existing memberships, and stores unresolved committee member names in `unresolved_entities` when no safe match is found.

Raw HTML archives are written to:

```text
backend/data/raw/people_assembly/
backend/data/raw/pmg/
backend/data/raw/parliament_questions/
backend/data/raw/pdfs/
```

PMG documents store `archive_path`. People's Assembly profile pages are also stored as `MP_PROFILE` documents with source evidence.

## Quality Checks

API:

```bash
curl http://localhost:8000/quality/summary
curl http://localhost:8000/quality/issues
curl http://localhost:8000/quality/duplicates
curl http://localhost:8000/quality/archive-gaps
```

CLI:

```bash
python backend/scripts/quality_check.py
python backend/scripts/dataset_report.py
```

The report includes totals for politicians, parties, committees, memberships, documents, mentions, and records missing important links.
It also reports active/inactive/unknown politician counts, alias count, parliamentary question counts, PDF question source counts, parse failures/partials, unresolved entity status counts, ingestion runs/errors, missing archive paths, committees without memberships, and duplicate slug/party/membership/source URL checks.

`/quality/issues` returns structured cleanup lists for politicians without parties, active politicians without committees, committees without memberships, documents without mentions, open unresolved entities, and duplicate candidates.

`backend/scripts/dataset_report.py` writes `backend/reports/dataset_report.json`. Generated reports are ignored by Git unless intentionally tracked.

## Unresolved Entity Review

Unknown people from committee pages, MP pages, documents, and parliamentary questions are stored in `unresolved_entities` instead of being silently discarded.

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

## Tests

From `backend/` with a reachable `DATABASE_URL`:

```bash
pytest
```

Inside Docker:

```bash
docker compose exec backend pytest
```

## Scheduled Ingestion

GitHub Actions includes CI and a guarded scheduled ingestion workflow
(`.github/workflows/scheduled-ingestion.yml`).

**The scheduled workflow will not run unless `INGESTION_ENABLED=true` is
explicitly set as a GitHub Actions secret.** This prevents accidental ingestion
against the wrong database.

### Required GitHub secrets

| Secret | Description |
|---|---|
| `DATABASE_URL` | Production PostgreSQL connection string |
| `INGESTION_ENABLED` | Must be `true` to allow ingestion to proceed |

### Optional GitHub variables

| Variable | Default | Description |
|---|---|---|
| `SOURCE_RATE_LIMIT_SLEEP` | `0.5` | Seconds between source requests |
| `MAX_DAILY_INGESTION_URLS` | `50` | URL limit per daily run |
| `MAX_WEEKLY_INGESTION_URLS` | `100` | URL limit per weekly run |

### Schedule

| Job | Cron | Purpose |
|---|---|---|
| `daily` | 03:15 UTC every day | PMG discovery + ingestion, parliamentary question ingestion, quality check, dataset report |
| `weekly` | 04:45 UTC every Sunday | People’s Assembly MP refresh, committee refresh, alias regeneration, dataset report |

### How to enable safely

1. Deploy the backend to production with a real `DATABASE_URL`.
2. Add `DATABASE_URL` and `INGESTION_ENABLED=true` as GitHub Actions secrets.
3. Optionally set rate limit variables.
4. The next scheduled run will proceed. Use `workflow_dispatch` to trigger manually.
5. Inspect results at `GET /ingestion/runs`.

### How to disable

Remove the `INGESTION_ENABLED` secret or set it to anything other than `true`.
The workflow will exit cleanly without touching the database.

## Production Deployment

### Backend deployment

The backend Dockerfile runs `alembic upgrade head` before starting Uvicorn and
respects an external `DATABASE_URL`, so it can run on Render, Railway, Fly.io,
or any Docker host with a managed PostgreSQL instance.

**Recommended: Render Web Service (Docker)**

| Setting | Value |
|---|---|
| Environment | Docker |
| Docker context | `.` (repo root) |
| Dockerfile path | `backend/Dockerfile` |
| Health check path | `/health` |
| Port | `8000` |

Set the following environment variables in the Render dashboard:

```text
DATABASE_URL=postgresql+psycopg://<user>:<pass>@<host>/<db>
ENVIRONMENT=production
CORS_ORIGIN=https://your-frontend.example
INGESTION_ENABLED=false
```

The start command is baked into the Dockerfile:

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

**Alternative: Render/Railway/Fly.io Python service (no Docker)**

Build command:

```bash
pip install -r backend/requirements.txt
```

Start command (run from `backend/`):

```bash
alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}
```

### Frontend deployment

**Recommended: Vercel or Netlify**

| Setting | Value |
|---|---|
| Root directory | `frontend` |
| Build command | `npm run build` |
| Output directory | `dist` |
| Node version | 22 |

Set the environment variable:

```text
VITE_API_BASE_URL=https://your-backend-url.example
```

Copy `frontend/.env.example` to `frontend/.env.local` for local development:

```bash
cp frontend/.env.example frontend/.env.local
# Edit VITE_API_BASE_URL if your backend is not on http://localhost:8000
```

### Production database

Use a managed PostgreSQL 16 service (Neon, Supabase, Render Postgres, Railway Postgres).

1. Create a database and note the connection string.
2. Set `DATABASE_URL=postgresql+psycopg://<user>:<pass>@<host>/<db>` on the backend service.
3. Migrations run automatically on backend start via `alembic upgrade head`.
4. Verify the schema applied:

```bash
curl https://your-api.example/health/ready
```

### Backup and restore

```bash
# Backup
pg_dump "$DATABASE_URL" > backups/knowyourmpza.sql

# Restore
psql "$DATABASE_URL" < backups/knowyourmpza.sql

# Archive raw HTML/PDFs
tar -czf backups/raw-archives.tgz backend/data/raw
```

Raw archives in `backend/data/raw/` are not automatically backed up unless you
configure an S3-compatible storage backend (see `ARCHIVE_STORAGE_MODE` in
`backend/.env.example`).

### Health checks

```bash
curl https://your-api.example/health
curl https://your-api.example/health/ready
```

`/health` returns `200 {"status": "ok"}` immediately.
`/health/ready` returns `200 {"status": "ready"}` once the database is reachable,
or `503` if the database is not available.

## API Examples

```bash
curl http://localhost:8000/health
curl "http://localhost:8000/politicians?limit=50&offset=0"
curl "http://localhost:8000/search?name=malema"
curl "http://localhost:8000/search?name=Hon%20Malema"
curl http://localhost:8000/politicians/{politician_id}
curl http://localhost:8000/politicians/{politician_id}/committees
curl "http://localhost:8000/politicians/{politician_id}/documents?limit=50&offset=0"
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
curl "http://localhost:8000/ingestion/runs?limit=20&offset=0"
curl http://localhost:8000/quality/summary
curl http://localhost:8000/quality/issues
curl http://localhost:8000/quality/duplicates
curl http://localhost:8000/quality/archive-gaps
curl "http://localhost:8000/unresolved-entities?status=OPEN"
```

## V1 Release Checklist

- [ ] Backend migrations apply on a clean database.
- [ ] Backend tests pass.
- [ ] Frontend build passes.
- [ ] `/health` and `/health/ready` pass.
- [ ] Quality summary and issues are readable.
- [ ] PMG, People’s Assembly, committee, and question ingestion smoke tests pass.
- [ ] Scheduled ingestion secrets are configured or left disabled.
- [ ] Production `DATABASE_URL` and `CORS_ORIGIN` are set.

## Troubleshooting

- If `localhost:8000` is unavailable, check `docker compose ps` and `docker compose logs backend`.
- If migrations fail, run `docker compose logs backend` and confirm PostgreSQL is healthy.
- If host port `5432` is busy, this project is still fine because PostgreSQL is not exposed on the host.
- If a source URL fails, retry later; the batch response lists failed URLs without stopping successful ones.
- If PMG pages have no mentions, seed or ingest relevant PA politicians first so entity resolution has known names and aliases.
- If a parliamentary question source names an MP in a format that cannot be resolved, the question still stores `asked_by_name` and an `unresolved_entities` row for later cleanup.
- If a PDF has no extractable text or extraction fails, the PDF is still archived and the question record is kept with `parse_status` and `parse_notes`.
- PMG discovery depends on public PMG listing/search availability; not every PMG document contains politician mentions.

## Roadmap

- Broader official Parliament source ingestion.
- richer parliamentary question parsing for scanned PDFs, reply/question matching, and source-specific layouts.
- richer committee history and roles.
- current-only committee filtering once the source exposes clearer status markers.
- document source classification.
- confidence/audit UI.
- voting records later.
- AI features only after the verified data layer is stable.
