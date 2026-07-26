# Deployment Checklist

Use this checklist for the public V1 deployment from latest `main`.

## Pre-Deploy Evidence

- [ ] Latest `main` CI is green.
- [ ] No open release-blocking PRs.
- [ ] `docs/V1_READINESS_REPORT.md` says GO WITH KNOWN LIMITATIONS.
- [ ] `KNOWN_LIMITATIONS.md` is linked or copied into public launch messaging.
- [ ] `RELEASE_NOTES_V1.md` has been reviewed.

## Backend

- [ ] Deploy from latest `main`.
- [ ] Runtime: Python 3.12.
- [ ] Start command runs migrations before Uvicorn:
  `alembic upgrade head && uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}`.
- [ ] If using Docker, use `backend/Dockerfile`.
- [ ] Health check path: `/health`.
- [ ] Readiness check path: `/health/ready`.
- [ ] Managed PostgreSQL 16 is available.
- [ ] Raw archive storage expectations are understood: local disk is acceptable for V1 beta, but provider disk persistence/backups should be configured if archives must survive redeploys.

## Frontend

- [ ] Deploy from `frontend/`.
- [ ] Runtime/build Node version: 22.
- [ ] Build command: `npm run build`.
- [ ] Output directory: `dist`.
- [ ] `VITE_API_BASE_URL` points at the deployed backend API.
- [ ] Frontend can load:
  - `/`
  - `/search`
  - `/politicians`
  - `/committees`
  - `/questions`
  - `/quality`

## Environment Variables

Backend service:

| Name | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Production PostgreSQL connection string using `postgresql+psycopg://...`. |
| `ENVIRONMENT` | yes | Set to `production`. |
| `CORS_ORIGIN` | yes | Comma-separated frontend origins. |
| `AI_API_KEY` | no | Enables model-written `/ai/ask` answers using an OpenAI-compatible provider. If omitted, the endpoint returns deterministic source-backed summaries. Legacy `OPENAI_API_KEY` is also accepted. |
| `AI_MODEL` | no | Defaults to `gpt-5-mini`. For free-tier beta usage, set this to the selected provider model id. Legacy `OPENAI_MODEL` is also accepted. |
| `AI_BASE_URL` | no | Defaults to `https://api.openai.com/v1`. Use `https://openrouter.ai/api/v1` for OpenRouter or another OpenAI-compatible provider base URL. Legacy `OPENAI_BASE_URL` is also accepted. |
| `AI_APP_URL` | no | Public frontend URL, sent as provider metadata for OpenRouter-style providers. |
| `AI_APP_TITLE` | no | Defaults to `KnowYourMPZA`, sent as provider metadata for OpenRouter-style providers. |
| `INGESTION_ENABLED` | no for web service | Keep `false` on the web service unless intentionally ingesting from the service process. |
| `PEOPLE_ASSEMBLY_BASE_URL` | no | Default is `https://www.pa.org.za`. |
| `PEOPLE_ASSEMBLY_MEMBER_LIST_URLS` | no | Optional PA member list override. |

GitHub Actions secrets:

| Secret | Required | Notes |
|---|---|---|
| `DATABASE_URL` | yes | Same production DB target used by scheduled jobs. Do not print it. |
| `INGESTION_ENABLED` | yes | Must be `true` for scheduled ingestion and question backfill. |

GitHub Actions variables:

| Variable | Required | Default |
|---|---|---|
| `SOURCE_RATE_LIMIT_SLEEP` | no | `0.5` |
| `MAX_DAILY_INGESTION_URLS` | no | `50` |
| `MAX_WEEKLY_INGESTION_URLS` | no | `100` |
| `MAX_QUESTION_BACKFILL_URLS` | no | `200` |

Frontend service:

| Name | Required | Notes |
|---|---|---|
| `VITE_API_BASE_URL` | yes | Public backend URL, no trailing slash preferred. |

## Post-Deploy Verification

- [ ] `GET /health` returns `200 {"status":"ok"}`.
- [ ] `GET /health/ready` returns `200 {"status":"ready"}`.
- [ ] `GET /politicians?limit=10` returns records.
- [ ] `GET /parties?limit=10` includes non-Unknown party records.
- [ ] `GET /questions?limit=10` returns source-backed records.
- [ ] `POST /ai/ask` returns an answer with source links and a coverage notice.
- [ ] If `AI_API_KEY` is configured, `POST /ai/ask` reports the configured model in `model_used`; if quota is exhausted, it safely reports `deterministic-source-summary`.
- [ ] Frontend search returns at least one known MP.
- [ ] An MP profile opens and displays source links.
- [ ] Attendance panel either shows records or the honest in-progress empty state.
- [ ] Quality page loads.
- [ ] Dispatch or wait for scheduled ingestion, then confirm artifacts upload.

## Release Decision

Deploy only if all required checks pass. If deployment succeeds but a data workflow fails afterward, keep the site live only if the public UI still renders source-backed records and `KNOWN_LIMITATIONS.md` remains accurate.
