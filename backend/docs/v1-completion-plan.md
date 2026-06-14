# KnowYourMPZA V1 Completion Plan

## Product finish line

V1 is a source-backed South African political data product that can reliably
show:

- current public representatives where an explicit authoritative source is
  available;
- each representative's explicit roles, party, chamber or jurisdiction, and
  source evidence;
- parliamentary activity where source-backed records are available;
- ingestion and source-access health;
- missing, unresolved, and unavailable coverage;
- provenance through source URLs, manifests, checksums, raw archives where
  appropriate, and report timestamps.

V1 does not mean that every possible public office or historical record is
complete. It means the implemented core is useful, measurable, reproducible,
and honest about its limits.

## Required V1 domains

1. **People and representatives:** a measured current-representative baseline,
   beginning with National Assembly and NCOP members. Person records require
   source evidence; no person may be inferred from an election result.
2. **Parties:** explicit party names and memberships from the representative
   source. Missing party evidence stays missing.
3. **Parliamentary activity:** source-backed links between representatives and
   available questions, documents, committee activity, bills, or explicit
   vote records.
4. **Bills, questions, and committees:** reliable ingestion, provenance, and
   unresolved-entity reporting for existing accountability domains.
5. **IEC election context:** metadata, manifests, reviewed vote totals, and
   quality reporting without winner, office-holder, councillor, or internal
   entity inference. Issue #24 remains open. Full IEC ingestion is incomplete.
6. **Source inventory:** a maintained distinction between implemented,
   limited, supporting, and candidate sources.
7. **Data quality and readiness:** coverage scoreboards that expose missing
   source URLs, duplicates, unresolved identifiers, unavailable expected
   universes, and public-claim limits.
8. **Scheduled ingestion health:** bounded ingestion, failure isolation,
   persistent reports, and visible red status for systemic source failures.

## Required completion gates

V1 may be called green only when:

- an authoritative expected universe for current MPs is stored or reproducibly
  available and reconciled against person records;
- each claimed current representative has direct source evidence;
- missing and duplicate representative records are measured and reviewed;
- core parliamentary activity reports run successfully and retain provenance;
- IEC is described accurately as context with its remaining #24 limitations;
- source inventory and coverage reports are current;
- scheduled runs produce health reports, and unresolved systemic failures are
  visible rather than silently passing.

People's Assembly is valuable enrichment. The PA source-access blocker in #47
must remain visible in GitHub Actions. People's Assembly cannot be treated as
the sole authority for the expected MP universe.

## Out of scope for V1

- AI, RAG, or a chatbot.
- A frontend redesign.
- Inferred election winners.
- Inferred office-bearers or councillors.
- Inferred party, geography, or person mappings.
- Complete councillor coverage unless separately source-backed.
- Perfect historical coverage.
- Any completeness claim based on seeded/demo records.

## Readiness levels

### Red

Core data cannot yet support a trustworthy completeness claim. Examples:

- no authoritative expected MP universe;
- missing source evidence for core people;
- systemic scheduled-ingestion failure without a usable recent baseline;
- unresolved integrity failures or fabricated/inferred records.

### Amber

The product is usable for bounded, qualified purposes, but material gaps remain.
Every gap must be visible in reports and public wording must remain qualified.

### Green

The required V1 gates pass: the expected MP universe is source-backed,
reconciliation is measurable, core records retain evidence, operational health
is acceptable, and remaining gaps do not invalidate the stated product scope.

Green means "complete enough for the defined V1," not perfect or universal.

## Immediate completion sequence

1. Audit authoritative MP/member source candidates with
   `scripts/audit_mp_member_sources.py`. The audit classifies Parliament
   official member listings as baseline candidates, People's Assembly as
   enrichment, PMG as activity support, and IEC as election context rather
   than current-office authority. Its report remains audit-only:
   `expected_universe_available: false` and `cannot_claim_all_mps: true`.
2. Establish an explicit expected representative universe or report that it is
   unavailable. The `expected_representative_universe` schema stores only
   explicit source evidence and has no automatic link to internal politician
   records. An empty table is still unavailable for completeness claims.
3. Publish an MP coverage scoreboard with
   `scripts/report_mp_coverage.py`. It reports stored people/source/activity
   counts and unresolved review candidates, but remains red while the expected
   MP universe is unavailable. It must not claim all MPs.
4. Aggregate domain reports with `scripts/report_v1_readiness.py`. Green is
   allowed only when every required gate explicitly passes; missing reports,
   a missing MP universe, foundation-only IEC coverage, and systemic PA access
   failures remain visible blockers.
5. Address the resulting blockers in evidence-first PRs.

No fabricated records. Unknown or missing data remains unknown or missing.
