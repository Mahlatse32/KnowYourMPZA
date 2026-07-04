# People's Assembly: Enrichment-Only Decision and PMG Fallback

Last updated: 2026-07-04

## Decision

For V1, People's Assembly (pa.org.za) is treated as an **enrichment-only
source**. PMG is the identity authority. V1 launch readiness does not
depend on People's Assembly source access being restored.

This closes the launch-checklist gate "People's Assembly source access is
either restored or permanently treated as enrichment-only with PMG fallback
documented" via the second option. If PA access is later restored from the
production runner, PA resumes its enrichment role automatically — no code
change is needed — but the identity authority stays PMG unless a human
maintainer explicitly decides otherwise.

## Evidence behind the decision

- Issue #47: the weekly scheduled run `27493372919` (2026-06-14) saw all
  100 PA profile fetches fail systemically; later production runs continued
  to see systemic HTTP 403 failures from the GitHub Actions runner, while
  the same URLs return HTTP 200 from other networks. The block is
  runner-network-specific and outside our control.
- The PMG identity bootstrap fallback is production-verified: the latest
  scheduled run reports `politicians=521`, `committees=34`,
  `committee_memberships=521`, and 100% identity-link coverage for
  attendance, meetings, and vote events — all built from source-backed PMG
  activity data without People's Assembly.

## How the fallback works

1. The weekly job (`run_weekly_ingestion.py`) runs
   `ingest_all_people_assembly.py` as its first stage. Stages are
   isolated: a PA failure never blocks committees, alias regeneration, or
   reports, but any failed stage still turns the weekly job red.
2. `ingest_all_people_assembly.py` classifies an all-URLs-failed batch as
   `systemic_source_access_failure` in
   `reports/people_assembly_ingestion_summary.json`.
3. On systemic failure it automatically runs the PMG identity bootstrap
   (`scripts/identity_bootstrap_utils.run_pmg_identity_bootstrap`), which
   creates or links parties, committees, politicians, aliases,
   memberships, and question mentions **only from existing source-backed
   PMG activity records** — no fabricated identities. The summary records
   `"fallback": {"strategy": "pmg_identity_bootstrap", ...}` and
   `status=fallback_completed`.
4. The weekly workflow also runs
   `verify_identity_bootstrap_production.py --run-bootstrap` before the
   weekly ingestion and verifies identity links after it, writing
   `identity_bootstrap_before_after.json` and
   `identity_bootstrap_after_weekly.json` artifacts.
5. The V1 readiness report (`report_v1_readiness.py`) marks PA source
   access red whenever the latest summary shows systemic failure, keeping
   the blocker visible without making it launch-blocking for identity
   correctness.

## What People's Assembly adds when it is reachable

PA profile ingestion enriches politician records (profile URLs, party
detail, profile metadata) beyond what PMG activity pages provide. Under
the enrichment-only decision, missing PA data degrades profile richness,
never identity correctness or accountability evidence.

## Operational runbook

- **Check current state:** download the latest
  `scheduled-ingestion-weekly-reports-*` artifact and read
  `people_assembly_ingestion_summary.json`. `systemic_source_access_failure:
  true` means the block persists; `fallback.summary` shows what the PMG
  bootstrap created or linked in the same run.
- **On weekly-run red caused by the PA stage:** no manual action is
  required. Confirm the fallback ran (`status=fallback_completed`) and that
  identity counts in `inspect_db.json` are non-zero. The red job is
  intentional visibility, not an outage of our pipeline.
- **Do not disable the PA stage.** Keeping it running is what detects
  recovery and keeps the failure visible (readiness report rule: keep PA
  failures visible; never depend on PA for V1 identity correctness).
- **Recovery criteria:** two consecutive scheduled weekly runs where
  `people_assembly_ingestion_summary.json` shows
  `systemic_source_access_failure: false` and a non-zero
  `processed_count`. At that point update the readiness report's PA row to
  green and note the recovery date here. PA remains enrichment-only; any
  promotion back to identity authority is a human decision recorded in
  `docs/V1_LAUNCH_GUARDRAILS.md`.
- **Manual probe (optional diagnosis):** fetch
  `https://www.pa.org.za/position/member/parliament/` from another network
  to distinguish a runner-network block (403 only from Actions) from a
  site-wide outage.

## Guardrail restated

From `docs/V1_LAUNCH_GUARDRAILS.md`: People's Assembly is enrichment only
while production runner access is blocked, and the PMG-derived identity
bootstrap may create fallback identities only from existing source-backed
PMG activity data. This document makes that arrangement the accepted V1
posture rather than a temporary workaround.
