# KnowYourMPZA V1 Release Package

Date: 2026-07-09

## 1. Production Architecture Summary

KnowYourMPZA V1 is a FastAPI + PostgreSQL backend with a React/Vite static frontend.

- Backend: FastAPI, SQLAlchemy, Alembic, PostgreSQL 16.
- Frontend: React 19, Vite, static build output in `frontend/dist`.
- Ingestion: GitHub Actions scheduled workflows and bounded backfills write to the production PostgreSQL database using repository secrets.
- Verification: CI, health endpoints, readiness endpoint, production-data smoke test, readiness reports, data-quality reports, and coverage dashboard artifacts.
- Source evidence: records retain source URLs; public frontend cards link to original sources where available.

## 2. Deployment Checklist

Use `DEPLOYMENT_CHECKLIST.md`.

Minimum deploy requirements:

- Backend deployed from latest `main`.
- Frontend deployed from latest `main`.
- Backend `DATABASE_URL`, `ENVIRONMENT=production`, and `CORS_ORIGIN` configured.
- Frontend `VITE_API_BASE_URL` configured.
- GitHub Actions `DATABASE_URL` and `INGESTION_ENABLED=true` configured for production backfills.
- `/health` and `/health/ready` pass after deploy.

## 3. Environment Variable Checklist

Backend service:

- `DATABASE_URL`
- `ENVIRONMENT=production`
- `CORS_ORIGIN`
- `INGESTION_ENABLED=false` unless intentionally ingesting from the web service

Frontend service:

- `VITE_API_BASE_URL`

GitHub Actions:

- Secret `DATABASE_URL`
- Secret `INGESTION_ENABLED=true`
- Optional variables `SOURCE_RATE_LIMIT_SLEEP`, `MAX_DAILY_INGESTION_URLS`, `MAX_WEEKLY_INGESTION_URLS`, `MAX_QUESTION_BACKFILL_URLS`

## 4. Operational Runbook

- Deploy backend and frontend from latest `main`.
- Confirm `/health` and `/health/ready`.
- Confirm frontend navigation, search, profile, committees, questions, and quality pages.
- Keep PMG meeting and Parliament questions backfills enabled until target coverage is reached.
- Use GitHub Actions artifacts as the production truth for coverage and readiness.
- Use `docs/ROLLBACK_RUNBOOK.md` for bad deploys, bad merges, or bad ingestion runs.

## 5. Monitoring Checklist

Use `POST_LAUNCH_MONITORING.md`.

Core checks:

- CI on `main`.
- Scheduled ingestion.
- PMG meeting backfill.
- Parliament questions backfill.
- Frontend production smoke artifacts.
- `v1_readiness_report`.
- `data_quality_checks`.
- Backend health/readiness endpoints.

## 6. Release Notes

Use `RELEASE_NOTES_V1.md`.

Launch headline:

KnowYourMPZA V1 is a public beta for source-backed South African MP profiles, committee work, attendance evidence, parliamentary questions, and original-source links.

## 7. Known Limitations

Use `KNOWN_LIMITATIONS.md`.

Short version:

- Historical data is still being imported.
- Coverage improves automatically through scheduled backfills.
- Every record shown is source-backed.
- Users may occasionally encounter incomplete historical information during the backfill period.

## 8. First 30-Day Roadmap

1. Monitor ingestion/backfill workflows daily for week one.
2. Continue PMG meeting backfill to at least 80% coverage.
3. Continue Parliament questions backfill and track missing metadata.
4. Review unresolved entities weekly.
5. Improve question-to-MP linking only where source evidence supports it.
6. Plan explicit vote/division coverage after V1 launch.
7. Validate an official Parliament expected-MP source before any all-MP completeness claim.

## 9. Launch Announcement Draft

KnowYourMPZA V1 beta is live.

It helps the public search South African MPs and view source-backed parliamentary work: committee service, PMG evidence, attendance records where linked, parliamentary questions, and links back to original public sources.

V1 is intentionally transparent about its limits. Historical records are still being imported, coverage improves automatically through scheduled backfills, and the site avoids guessing when a party, committee link, attendance record, question, or vote is not yet source-backed.

This is a public beta for accountability data that can be inspected and verified.

## Final Release Recommendation

YES - READY TO DEPLOY WITH KNOWN LIMITATIONS, once production backend/frontend deployments are made from latest `main` and the deployment checklist passes.
