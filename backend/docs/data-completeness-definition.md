# Data Completeness Definition

## Core rule

Completeness is a comparison between:

1. a clearly defined, source-backed expected universe; and
2. the records actually stored with valid source evidence.

A large record count is not completeness. When an expected universe is not
available, the status is **unknown**, not complete.

## Evidence requirements

A completeness claim must identify:

- the represented domain and time period;
- the authoritative or explicitly qualified source;
- the expected count or source list;
- the observed records and matching method;
- records missing source URLs or stable evidence locators;
- unresolved, duplicate-like, and unmatched records;
- the report generation time and source freshness.

People and representative records must not be fabricated or inferred from
party lists, election totals, surnames, committee text, or probable roles.
Party membership, chamber, province, role, and office-holder status require
explicit source evidence.

## Representative coverage

MP/person coverage is complete only when a reproducible expected universe for
the relevant chamber exists and every expected representative is:

- matched through explicit source identifiers or reviewed evidence;
- represented by one non-duplicate person record;
- linked to the source record used for the claim;
- assigned party and role data only where explicitly supplied.

Until that universe exists, reports must include:

- `expected_universe_available: false`;
- `cannot_claim_all_mps: true`;
- missing/unresolved coverage as unknown rather than zero.

The `expected_representative_universe` table is the evidence contract for that
future denominator. Table existence alone is insufficient: it must contain
reviewed source rows, and reconciliation must have no missing, ambiguous, or
unresolved representatives before `cannot_claim_all_mps` may become false.
Expected rows are not internal person mappings and do not infer party,
membership, role, or current-office status.

People's Assembly is enrichment and cross-check evidence. Parliament official
member sources are the preferred baseline candidates. PMG supports activity
linkage. IEC election context is not current-office authority unless an
official source explicitly states that role.

## Domain completeness

- **People/parties:** expected-universe reconciliation and direct evidence.
- **Parliamentary activity:** coverage of available source documents and
  explicit links, not an assumption that silence means no activity.
- **IEC:** manifest and reviewed-file coverage only; issue #24 remains open.
- **Source inventory:** every source is labelled implemented, limited,
  supporting, or candidate.
- **Operations:** recent scheduled reports exist and source-access failures are
  visible. The People's Assembly blocker in #47 is an operational coverage
  constraint, not permission to invent or bypass data.

## Readiness interpretation

- **Red:** core evidence or expected-universe gates are missing; core data
  cannot be trusted for completeness claims.
- **Amber:** useful source-backed data exists, but material measured or unknown
  gaps remain.
- **Green:** all required V1 gates pass for the explicitly defined scope.

Readiness never converts unknown data into complete data.
