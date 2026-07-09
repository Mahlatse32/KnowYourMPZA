# KnowYourMPZA V1 Release Notes

Release target: public V1 beta

## Recommendation

KnowYourMPZA V1 is ready to deploy publicly with known limitations, provided the backend and frontend are deployed from the latest `main` and production environment variables are configured as listed in `DEPLOYMENT_CHECKLIST.md`.

## What V1 Provides

- Source-backed MP profile browsing.
- MP search by name/alias signals.
- Party display where explicit source-backed party evidence exists.
- Committee memberships and committee context where linked.
- PMG parliamentary work evidence, including documents, meetings, attendance records, and vote-event signals where present.
- Parliamentary questions from Parliament source records, with docsjson metadata enrichment where available.
- Evidence links back to original public sources.
- Honest empty states for sections still being imported or linked.

## Current Production Evidence

Evidence reviewed on 2026-07-09:

| Area | Evidence |
|---|---|
| CI | Latest `main` CI run `28998884475` passed backend tests and frontend build. |
| Parties | Production artifacts show `parties=16`, no longer only `Unknown`. |
| MP identities | `politicians=521`. |
| Committees | `committees=34`, `committee_memberships=521`. |
| PMG meetings | `22656/34713 = 65.27%`; backfill run `28994456199` succeeded. |
| Attendance | `committee_attendance=209192`. |
| Questions | `3994/44036 = 9.07%`; question backfill run `28995667052` succeeded. |
| Smoke tests | Scheduled ingestion run `28921400351` reported frontend production smoke `15/15` passing; PR #80 adds direct attendance endpoint coverage for the next smoke artifact. |

## Known Launch Limits

- V1 is not a complete historical archive yet.
- Meeting and question coverage continue to grow through scheduled backfills.
- Some party affiliations, committee links, question dates, and question text remain incomplete.
- Vote records are intentionally limited in V1.
- People's Assembly is enrichment-only for V1 because runner access can be blocked.

See `KNOWN_LIMITATIONS.md` for public-facing wording.

## Operational Notes

- Backend deployment should run migrations on startup (`alembic upgrade head`).
- Frontend deployment must set `VITE_API_BASE_URL` to the deployed backend.
- GitHub Actions secrets must include `DATABASE_URL` and `INGESTION_ENABLED=true` for production ingestion/backfills.
- Leave PMG meeting and Parliament question backfill workflows enabled until coverage targets are reached.
