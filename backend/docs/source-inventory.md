# KnowYourMPZA Source Inventory and Ingestion Backlog

Last reviewed: 2026-06-13

This is the living register of public sources considered by KnowYourMPZA. It
separates sources that have working ingestion code from candidates that still
require source validation, schema design, tests, and operational reporting.

## Non-negotiable data rules

### No fabricated records

Never create a person, office, vote, attendance record, question, bill event,
finding, or result merely because it is likely. Missing data remains missing.
Derived values must state the derivation method and may not be presented as
direct source facts.

### Source evidence required

Every ingested record must retain a stable public `source_url` or equivalent
official evidence locator. Where supported, raw HTML/PDF archives are retained
outside Git. An ingestion path is not production-ready until idempotency,
failure capture, and evidence retention are tested.

### Status vocabulary

- **Implemented:** active code writes source-backed records.
- **Implemented, limited:** code exists, but source accessibility or the
  available evidence restricts coverage.
- **Candidate / not implemented:** no production ingestion path exists. A link
  here is research input, not a claim that the source is ingested.
- **Demo fallback only:** seeded examples; never evidence for public claims.

## Implemented sources

| Source | URL | Domain | Data type | Current status | Ingestion script | Evidence/source URL retained? | Update frequency | Risk/notes | Priority |
|---|---|---|---|---|---|---|---|---|---|
| People's Assembly member profiles | https://www.pa.org.za/position/member/parliament/ | National politicians | Names, parties, photos, status, aliases, committee links | Implemented | `scripts/ingest_people_assembly_full.py`; `scripts/ingest_all_people_assembly.py` | Yes: `profile_url`; raw HTML archive | Weekly full refresh; bounded scheduled runs | Third-party civic source; page markup can change; former/current classification needs monitoring | P0 |
| People's Assembly committee pages | https://www.pa.org.za/committees/ | Parliamentary committees | Committees, memberships, roles, unresolved member names | Implemented | `scripts/ingest_committees_full.py`; `scripts/ingest_all_committees.py` | Yes: committee and membership `source_url`; raw HTML archive | Weekly | Membership naming and roles vary; unresolved names must remain explicit | P0 |
| PMG committee documents | https://pmg.org.za/committee-meetings/ | Parliamentary oversight | Meeting documents, reports, briefings, mentions | Implemented | `scripts/ingest_pmg_full.py`; `scripts/ingest_all_pmg.py` | Yes: human PMG URL; raw HTML archive | Daily | Broad corpus; discovery is bounded and source pages can reject or throttle requests | P0 |
| PMG public bills API | https://api.pmg.org.za/bill/ | Legislation | Bills and bill lifecycle metadata | Implemented | `scripts/ingest_bills.py`; `scripts/backfill_legislative_history.py` | Yes: stored human URL such as `pmg.org.za/bill/<id>/` | Daily accountability sweep | API is the reliable machine-readable source; HTML bill pages are JavaScript shells | P0 |
| PMG public committee meeting API | https://api.pmg.org.za/committee-meeting/ | Committee accountability | Meetings, dates, summaries, explicit attendance | Implemented | `scripts/ingest_committee_activity.py` | Yes: stored human committee-meeting URL | Daily accountability sweep | Attendance is stored only when the explicit endpoint supplies it; absence is not inferred | P0 |
| PMG meeting minutes vote signals | https://api.pmg.org.za/committee-meeting/ | Voting/accountability | Vote events and explicit aggregate vote records | Implemented, limited | `scripts/ingest_votes.py` | Yes: PMG meeting URL | Daily accountability sweep | No dedicated vote API; only explicit vote/division language is accepted; outcome-only events may have zero vote records | P0 |
| Parliament questions, replies, papers, and archive | https://www.parliament.gov.za/questions-and-replies | Parliamentary questions | Question/reply HTML and PDFs, asker resolution, mentions | Implemented | `scripts/ingest_questions_full.py`; `scripts/ingest_all_parliamentary_questions.py` | Yes: official URL plus HTML/PDF archive | Daily | Uses official docsjson endpoints and archive listings; PDF text quality varies | P0 |
| Parliament official member listings | https://www.parliament.gov.za/members | National politicians | Discovery of People's Assembly profile links from official listings | Implemented, limited | `scripts/ingest_parliament_members_full.py` | Yes when an official page resolves to a PA profile; final record retains PA profile URL | Full pipeline/manual | This is a cross-reference bridge, not direct official-profile ingestion; official pages may expose no PA links | P1 |
| Parliament bills HTML pages | https://www.parliament.gov.za/bills | Legislation | Bill listing parser/fallback | Implemented, limited | Parser in `app/ingestion/bills.py`; primary scheduled ingestion is `scripts/ingest_bills.py` via PMG API | Yes when parsed | Manual/fallback | Static page may be a JavaScript shell; do not claim scheduled Parliament HTML coverage | P2 |
| Seed/demo fallback | Local `app/ingestion/seed_data.py` | Development only | Sample politicians, parties, committees, and documents | Demo fallback only | `/ingest/seed` | No: sample URLs are not proof of real ingestion | Manual only | Never use seed records for production coverage or public claims | Not applicable |

## Candidate sources and backlog

Every row below is **candidate / not implemented**. URLs were reviewed as
public entry points, but their terms, stability, identifiers, pagination,
download formats, and evidence model still need technical validation.

| Source | URL | Domain | Data type | Current status | Ingestion script | Evidence/source URL retained? | Update frequency | Risk/notes | Priority |
|---|---|---|---|---|---|---|---|---|---|
| IEC election results | https://results.elections.org.za/home/ | Elections | National, provincial, municipal, and by-election results; downloadable CSV/Excel/PDF reports | Candidate / not implemented | None | Required before implementation | Event-driven plus by-elections | Multiple election types and geographies need stable composite identifiers and reproducible download manifests | P0 |
| Municipal Money / National Treasury API | https://municipaldata.treasury.gov.za/ | Local government finance | Municipal budgets, actuals, audit opinions, financial performance | Candidate / not implemented | None | Required before implementation | Quarterly/source release cadence | Large longitudinal datasets; municipality code/version mapping and revised releases require care | P1 |
| Parliament Hansard | https://www.parliament.gov.za/hansard | Parliamentary proceedings | Debate transcripts and speaker references | Candidate / not implemented | None | Required before implementation | Sitting days | PDF/document formats and speaker attribution need robust parsing and entity resolution | P1 |
| Parliament ATC | https://www.parliament.gov.za/announcements-tablings-committee-reports | Parliamentary papers | Announcements, tablings, committee reports | Candidate / not implemented | None | Required before implementation | Parliamentary publication days | High-value lifecycle evidence, but document types and identifiers need inventory first | P1 |
| Parliament minutes of proceedings | https://www.parliament.gov.za/minutes-proceedings | Parliamentary proceedings | Formal minutes, decisions, divisions, motions | Candidate / not implemented | None | Required before implementation | Sitting days | Potential vote evidence; only explicit records may be stored | P1 |
| Government Gazette notices | https://www.gov.za/documents/notices | Law and public administration | Gazette notices, proclamations, regulations | Candidate / not implemented | None | Required before implementation | Frequent | Document taxonomy, duplicate publication, amendments, and PDF extraction need a provenance-first design | P1 |
| Acts and enacted legislation | https://www.gov.za/documents/acts | Legislation | Acts, dates, document files, amendment context | Candidate / not implemented | None | Required before implementation | On publication | Must reconcile Parliament bill identifiers with final act numbers without guessing | P0 |
| Parliament Acts | https://www.parliament.gov.za/acts | Legislation | Parliament-hosted act documents | Candidate / not implemented | None | Required before implementation | On publication | Candidate corroborating source for gov.za acts; define canonical-source and duplicate rules | P2 |
| Municipal councils and office-bearers | Official municipal websites; cross-check IEC ward councillor reports at https://results.elections.org.za/home/ | Local political representation | Councillors, mayors, speakers, whips, party/ward roles | Candidate / not implemented | None | Required before implementation | After elections and council changes | Official data is fragmented across municipalities; never infer office-holders from election winners alone | P0 |
| Presidency cabinet announcements and statements | https://www.thepresidency.gov.za/ | Executive | Cabinet appointments, changes, official statements | Candidate / not implemented | None | Required before implementation | Event-driven | Statements are strong appointment evidence but supersession and effective dates must be modelled | P1 |
| SA Government leader profiles and statements | https://www.gov.za/about-government/contact-directory/profile | Executive and provincial leadership | President, deputy president, ministers, deputy ministers, premiers, profiles | Candidate / not implemented | None | Required before implementation | Event-driven/periodic | Useful official cross-check; titles and portfolios change and require dated office terms | P1 |
| Public Protector reports | https://www.pprotect.org/ | Chapter 9 oversight | Investigation reports, findings, remedial action | Candidate / not implemented | None | Required before implementation | On publication | Site accessibility and report indexing require validation; findings must link to report evidence, not media summaries | P1 |
| SAHRC reports | https://www.sahrc.org.za/ | Chapter 9 oversight | Human-rights investigations, reports, findings | Candidate / not implemented | None | Required before implementation | On publication | Report taxonomy and named-entity sensitivity require review before ingestion | P2 |

## Source discovery progress

Discovery/audit scripts annotate official candidate sources (fetch status,
format, granularity, parser readiness) and write reports under `reports/`.
**Discovery/audit is not ingestion** — no records are created and no schema is
added until a parser is validated and tested.

| Candidate | Discovery script | Report | Status |
|---|---|---|---|
| IEC election results | `scripts/discover_iec_sources.py`; `scripts/audit_iec_structured_formats.py`; metadata/manifest ingestion `scripts/ingest_iec_metadata_manifest.py` (design: `docs/iec-election-results-ingestion.md`) | Discovery, metadata-manifest, and structured-format audit reports under `reports/` | **Metadata + source manifests ingested**; CSV header profile is the preferred parser candidate after offline audit — **no vote totals, winners, office-bearers, or geography/party mappings** |
| Gazette / Acts / Bills metadata | `scripts/discover_gazette_acts_sources.py` (design: `docs/gazette-acts-bills-ingestion-design.md`) | `reports/gazette_acts_source_discovery.json` / `.md` | Discovery + design only — no gazettes/acts ingested |
| Municipal councils & office-bearers | `scripts/discover_municipal_sources.py` (design: `docs/municipal-councils-ingestion-design.md`) | `reports/municipal_source_discovery.json` / `.md` | Discovery + design only — no councils/office-bearers ingested |
| Chapter 9 institution reports | `scripts/discover_chapter9_report_sources.py` (design: `docs/chapter9-reports-ingestion-design.md`) | `reports/chapter9_source_discovery.json` / `.md` | Discovery + design only — no reports ingested, no findings extracted |
| Parliamentary votes / divisions | `scripts/audit_votes_divisions_sources.py` (design: `docs/votes-divisions-ingestion-design.md`) | `reports/votes_divisions_source_audit.json` / `.md` | Audit + design only — PMG minutes implemented (limited); no MP-level expansion yet |

## Priority scoring

Backlog priority is assigned from five review dimensions, each scored 1-5:

1. **Public accountability impact**
2. **Official/source reliability**
3. **Machine accessibility**
4. **Fit with existing entities and identifiers**
5. **Operational maintainability**

The total guides ordering, but it does not override evidence quality:

- **P0:** 20-25, or foundational to core political representation.
- **P1:** 15-19, high value after source/schema validation.
- **P2:** below 15, useful but dependent on harder parsing or prior entities.

Security, legal access, and source-evidence failures can lower or block a
candidate regardless of score.

## Issue-ready ingestion backlog

| Backlog item | Goal | Minimum report |
|---|---|---|
| Ingest IEC election results | Reproducible election, contest, geography, party/candidate, and result records from official downloads | Coverage by election/geography; missing evidence; duplicates; failed files |
| Ingest Government Gazette / Acts / Bills metadata | Connect official publication and enactment evidence to existing bill records | Bills-to-acts linkage coverage; unmatched identifiers; source-file failures |
| Ingest municipal councils and office-bearers | Source-backed councils, councillors, mayors, speakers, and dated terms | Municipality coverage; role/source gaps; unresolved people and parties |
| Ingest Chapter 9 institution reports and findings | Searchable official reports and structured findings/remedial actions | Institution/year coverage; parse failures; unresolved actors; missing PDFs |
| Improve entity resolution for unresolved political actors | Resolve aliases and source names without unsafe surname-only merges | Precision test set; proposed/applied matches; unresolved delta; rejected ambiguities |

Each implementation issue must include tests for idempotency, per-item failure
handling, source URL retention, duplicate prevention, and report generation.
No issue is complete merely because a scraper returns rows.
