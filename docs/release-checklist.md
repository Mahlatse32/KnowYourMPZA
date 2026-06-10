# KnowYourMPZA V1 Release Checklist

Use this checklist before tagging `v1.0.0` and before any production deployment.

---

## Local verification

- [ ] `git checkout main && git pull origin main` — local main is up to date
- [ ] `docker compose up --build -d` — Docker stack builds and starts without errors
- [ ] `docker compose exec -T backend alembic upgrade head` — all 8 migrations apply cleanly
- [ ] `docker compose exec -T backend pytest -q` — backend tests pass
- [ ] `docker compose exec -T backend python scripts/quality_check.py` — quality script runs
- [ ] `docker compose exec -T backend python scripts/dataset_report.py` — dataset report generates

## API smoke tests (local)

- [ ] `curl http://localhost:8000/health` → `{"status": "ok"}`
- [ ] `curl http://localhost:8000/health/ready` → `{"status": "ready"}`
- [ ] `curl http://localhost:8000/quality/summary` → totals returned
- [ ] `curl http://localhost:8000/quality/issues` → structured issues returned
- [ ] `curl http://localhost:8000/quality/duplicates` → duplicate check returned
- [ ] `curl http://localhost:8000/quality/archive-gaps` → gap report returned
- [ ] `curl "http://localhost:8000/politicians?limit=10"` → list returned
- [ ] `curl "http://localhost:8000/questions?limit=10"` → list returned
- [ ] `curl "http://localhost:8000/documents?limit=10"` → list returned

## Frontend verification (local)

- [ ] `cd frontend && npm install && npm run build` — build passes with no errors
- [ ] `npm run dev` — dev server starts on port 5173
- [ ] Homepage loads without console errors
- [ ] Search page loads and returns results
- [ ] Politicians list page loads
- [ ] Politician detail page loads (with committees and documents)
- [ ] Parties page loads
- [ ] Committees page loads
- [ ] Documents page loads
- [ ] Questions page loads
- [ ] Quality page loads
- [ ] `frontend/.env.example` exists

## Security audit

- [ ] `git grep -in "password\|secret\|token\|api_key"` — no real credentials committed
- [ ] `backend/.env.example` contains no real secrets
- [ ] `frontend/.env.example` contains no real secrets
- [ ] `.gitignore` ignores `.env` files

## Environment variable audit

- [ ] `backend/.env.example` documents all backend env vars including ingestion guards
- [ ] `frontend/.env.example` documents `VITE_API_BASE_URL`
- [ ] README explains production env var requirements

## CI

- [ ] `ci.yml` backend-tests job passes on `main`
- [ ] `ci.yml` frontend-build job passes on `main`
- [ ] PostgreSQL service is configured in backend-tests job
- [ ] Scheduled ingestion workflow is guarded by `INGESTION_ENABLED` secret

## Production deployment

- [ ] Managed PostgreSQL database provisioned (Neon / Supabase / Render / Railway)
- [ ] `DATABASE_URL` set on backend service
- [ ] `ENVIRONMENT=production` set on backend service
- [ ] `CORS_ORIGIN=https://your-frontend.example` set on backend service
- [ ] Backend health check path set to `/health`
- [ ] `alembic upgrade head` runs on backend startup (baked into Dockerfile CMD)
- [ ] `curl https://your-api.example/health/ready` returns `{"status": "ready"}`
- [ ] Frontend deployed to Vercel/Netlify with root directory `frontend`
- [ ] `VITE_API_BASE_URL=https://your-api.example` set on frontend deployment
- [ ] Frontend loads against production backend without CORS errors

## Scheduled ingestion

- [ ] `DATABASE_URL` secret configured in GitHub Actions (or deliberately left out to disable)
- [ ] `INGESTION_ENABLED=true` secret configured (or deliberately left out to disable)
- [ ] Rate limit variables set as GitHub Actions variables (`SOURCE_RATE_LIMIT_SLEEP`, `MAX_DAILY_INGESTION_URLS`, `MAX_WEEKLY_INGESTION_URLS`)
- [ ] First production ingestion run completed and inspected at `GET /ingestion/runs`
- [ ] No unexpected ingestion errors in `GET /ingestion/runs/{run_id}`

## Post-deployment checks

- [ ] Source links in MP profiles open correctly
- [ ] PMG document source URLs are accessible
- [ ] Parliamentary question source URLs are accessible
- [ ] No broken images on MP profile pages
- [ ] Mobile layout is acceptable on small screens
- [ ] Empty states display correctly when no data is returned
- [ ] Loading states display correctly on slow connections

## Release tagging

- [ ] Stabilization PR merged into `main`
- [ ] `git checkout main && git pull origin main`
- [ ] `git tag -a v1.0.0 -m "KnowYourMPZA V1 public product"`
- [ ] `git push origin v1.0.0`
- [ ] GitHub Release created from tag with `docs/releases/v1.0.0.md` as release notes
