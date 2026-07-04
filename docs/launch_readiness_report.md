# KnowYourMPZA V1 Launch Readiness Report

> **Superseded (2026-07-04):** this is a point-in-time snapshot from 2026-06-23.
> The canonical, continuously updated launch documents are
> [`V1_READINESS_REPORT.md`](V1_READINESS_REPORT.md) and
> [`V1_LAUNCH_CHECKLIST.md`](V1_LAUNCH_CHECKLIST.md). Do not use this file for
> launch decisions.

Generated: 2026-06-23

## Decision

**V1 should not launch yet.**

Launch Readiness Score = **10 / 100 = 10%**

This score counts only questions that the current data can answer with source-backed evidence. Questions that the schema could support but current ingestion coverage cannot reliably answer are counted as partially answerable, not launch-ready.

## Evidence Snapshot

The latest available local coverage snapshot is `backend/reports/data_coverage_dashboard.json`, generated on 2026-06-13.

| Area | Current coverage |
|---|---:|
| Politicians | 15 |
| Parties | 11 |
| Committees | 15 |
| Parliamentary questions | 4 |
| Source documents | 19 |
| PMG source documents | 1 |
| Bills | 0 |
| Bill events | 0 |
| Vote events | 0 |
| Vote records | 0 |
| Committee meetings | 0 |
| Committee attendance records | 0 |
| Open unresolved entities | 4 |
| Missing source URLs | 18 |
| Missing source dates | 39 |

The dashboard marks public-facing completeness claims as unsafe because coverage is incomplete and red data-quality risks remain.

## Classification Summary

| Classification | Count |
|---|---:|
| Answerable | 10 |
| Partially answerable | 40 |
| Not answerable | 50 |
| Total | 100 |

## Table Key

| Short name | Tables |
|---|---|
| politicians | `politicians`, `parties`, `politician_aliases` |
| committees | `committees`, `committee_memberships`, `politicians`, `parties` |
| questions | `parliamentary_questions`, `question_mentions`, `politicians`, `parties`, `sources` |
| documents | `documents`, `document_mentions`, `politicians`, `sources` |
| quality | `unresolved_entities`, source fields on public tables |
| accountability | `bills`, `bill_events`, `vote_events`, `vote_records` |
| meetings | `committee_meetings`, `committee_attendance`, `committees`, `politicians` |
| IEC | `iec_elections`, `iec_source_manifests`, `iec_vote_totals` |

## 100-Question Readiness Matrix

| # | Realistic user question | Required tables | Can current data answer it? | Is coverage sufficient? | Source-backed? | Classification |
|---:|---|---|---|---|---|---|
| 1 | Show all parliamentary questions currently in the system. | questions | Yes, for the 4 ingested records. | Yes for current records only. | Yes, question source URLs are present. | Answerable |
| 2 | Show the source links for ingested parliamentary questions. | questions | Yes. | Yes for current records. | Yes. | Answerable |
| 3 | Which ingested parliamentary questions are missing a linked MP? | questions, quality | Yes. | Yes for current records. | Yes, as a data-quality answer. | Answerable |
| 4 | Which ingested parliamentary questions are missing asked dates? | questions, quality | Yes. | Yes for current records. | Yes, as a data-quality answer. | Answerable |
| 5 | List the MPs currently ingested in the database. | politicians | Yes, for the 15 ingested politicians. | Yes for current records only. | Partly dependent on per-row profile URL, but answer is bounded to current data. | Answerable |
| 6 | List the parties currently ingested in the database. | politicians | Yes, for the 11 ingested parties. | Yes for current records only. | Partly dependent on per-row source URL, but answer is bounded to current data. | Answerable |
| 7 | List the committees currently ingested in the database. | committees | Yes, for the 15 ingested committees. | Yes for current records only. | Partly dependent on per-row source URL, but answer is bounded to current data. | Answerable |
| 8 | Show PMG documents currently stored. | documents | Yes, for the 1 PMG document. | Yes for current records only. | Yes. | Answerable |
| 9 | Which unresolved names are blocking clean attribution? | quality | Yes, for the 4 open unresolved entities. | Yes for current records. | Yes, as a data-quality answer. | Answerable |
| 10 | Which current records are missing source URLs? | quality | Yes. | Yes for current records. | Yes, as a data-quality answer. | Answerable |
| 11 | Which MPs asked questions about Eskom? | questions, politicians | Maybe, only if one of the 4 ingested questions mentions Eskom and resolves to an MP. | No. | Yes for any matched record. | Partially answerable |
| 12 | Show questions mentioning illegal immigration. | questions | Maybe, only across 4 ingested questions. | No. | Yes for any matched record. | Partially answerable |
| 13 | Which MPs from Limpopo raised unemployment concerns? | questions, politicians | Maybe by text search and party/profile data, but province/geography is not a reliable MP field. | No. | Partial. | Partially answerable |
| 14 | Who sits on the police committee? | committees | Maybe if the committee and memberships are among the small ingested subset. | No. | Partial because committee baseline is not complete. | Partially answerable |
| 15 | Who sits on the health committee? | committees | Maybe if represented in current committee memberships. | No. | Partial. | Partially answerable |
| 16 | Which committees does a named ingested MP sit on? | committees, politicians | Yes for an ingested MP, but not reliable for all MPs. | No. | Partial. | Partially answerable |
| 17 | Which MPs from the DA asked questions about policing? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for any matched records. | Partially answerable |
| 18 | Which ANC MPs have committee memberships recorded? | committees, politicians | Yes for ingested ANC politicians only. | No. | Partial. | Partially answerable |
| 19 | Which EFF MPs appear in PMG documents? | documents, politicians | Maybe across 1 PMG document. | No. | Yes for that document. | Partially answerable |
| 20 | Which MPs are mentioned in committee meeting documents? | documents, politicians | Maybe across 1 PMG document. | No. | Yes for that document. | Partially answerable |
| 21 | Show questions answered by a specific minister. | questions | Maybe if present in the 4 question records. | No. | Yes for any matched records. | Partially answerable |
| 22 | Show questions sent to Basic Education. | questions | Maybe if present in the 4 question records. | No. | Yes for any matched records. | Partially answerable |
| 23 | Show questions sent to Home Affairs. | questions | Maybe if present in the 4 question records. | No. | Yes for any matched records. | Partially answerable |
| 24 | Show questions sent to Police. | questions | Maybe if present in the 4 question records. | No. | Yes for any matched records. | Partially answerable |
| 25 | Show questions sent to Mineral Resources and Energy. | questions | Maybe if present in the 4 question records. | No. | Yes for any matched records. | Partially answerable |
| 26 | Which ingested MPs have no committee memberships? | committees, politicians | Yes for current records, but cannot support an all-MP claim. | No. | Partial. | Partially answerable |
| 27 | Which ingested committees have no members? | committees | Yes for current records, but not complete nationally. | No. | Partial. | Partially answerable |
| 28 | Which source documents mention a named ingested MP? | documents, politicians | Yes for current documents, but coverage is tiny. | No. | Yes for matching documents. | Partially answerable |
| 29 | Which parliamentary questions mention a named ingested MP? | questions, politicians | Yes for current questions, but coverage is tiny. | No. | Yes for matching questions. | Partially answerable |
| 30 | Which politicians have aliases recorded? | politicians | Yes for current records, but alias coverage is not proven complete. | No. | Partial. | Partially answerable |
| 31 | Which parties have MPs in the ingested dataset? | politicians | Yes for current records only. | No. | Partial. | Partially answerable |
| 32 | Which committees have source URLs? | committees, quality | Yes for current records. | No for launch completeness. | Yes as a data-quality answer. | Partially answerable |
| 33 | Which MPs have profile URLs? | politicians, quality | Yes for current records. | No for full MP coverage. | Yes as a data-quality answer. | Partially answerable |
| 34 | Which questions have extracted text available? | questions, quality | Yes for current question records. | No. | Yes as a data-quality answer. | Partially answerable |
| 35 | Which questions have parse failures or partial parses? | questions, quality | Yes for current question records. | No. | Yes as a data-quality answer. | Partially answerable |
| 36 | Which PMG documents lack politician mentions? | documents, quality | Yes for current PMG documents. | No. | Yes as a data-quality answer. | Partially answerable |
| 37 | Show documents by committee name. | documents, committees | Maybe for stored documents. | No. | Yes for matching documents. | Partially answerable |
| 38 | Show all questions asked by a named ingested MP. | questions, politicians | Yes if the MP is among the resolved question askers. | No. | Yes for matching questions. | Partially answerable |
| 39 | Show all questions mentioning a named ingested MP. | questions, politicians | Yes for current `question_mentions`. | No. | Yes for matching questions. | Partially answerable |
| 40 | Which MPs asked questions in June 2026? | questions, politicians | Maybe, but 3 of 4 question records are missing source dates. | No. | Partial. | Partially answerable |
| 41 | Which questions were answered in June 2026? | questions | Maybe if answered dates exist. | No. | Partial. | Partially answerable |
| 42 | Which MPs have appeared in PMG evidence notes? | documents, politicians | Maybe across 1 PMG document and sample evidence. | No. | Partial. | Partially answerable |
| 43 | Which committee memberships came from People's Assembly? | committees, politicians | Yes for current records, but PA is enrichment rather than official baseline. | No. | Partial. | Partially answerable |
| 44 | Which public records came from Parliament question PDFs? | questions, sources | Maybe for current question records. | No. | Yes for matching records. | Partially answerable |
| 45 | Which current records have open unresolved entity links? | quality | Yes for current records. | No for launch completeness. | Yes as a quality answer. | Partially answerable |
| 46 | Which MPs are active versus inactive? | politicians | Yes for current records only. | No; expected MP universe is not proven complete. | Partial. | Partially answerable |
| 47 | Which parties have no ingested active MPs? | politicians | Yes for current records only. | No. | Partial. | Partially answerable |
| 48 | Which committee roles are recorded for a named ingested MP? | committees, politicians | Yes if the MP has memberships. | No. | Partial. | Partially answerable |
| 49 | Which ingested committees are portfolio committees? | committees | Maybe by name text. | No. | Partial. | Partially answerable |
| 50 | Which MPs asked questions mentioning schools? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for matching records. | Partially answerable |
| 51 | Which MPs asked questions mentioning grants? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for matching records. | Partially answerable |
| 52 | Which MPs asked questions mentioning corruption? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for matching records. | Partially answerable |
| 53 | Which MPs asked questions mentioning hospitals? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for matching records. | Partially answerable |
| 54 | Which MPs asked questions mentioning water? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for matching records. | Partially answerable |
| 55 | Which MPs asked questions mentioning crime? | questions, politicians | Maybe across 4 ingested questions. | No. | Yes for matching records. | Partially answerable |
| 56 | Which questions mention a party name? | questions, politicians | Maybe through text search and mentions. | No. | Yes for matching records. | Partially answerable |
| 57 | Which source documents mention the Health committee? | documents, committees | Maybe across stored documents. | No. | Yes for matching documents. | Partially answerable |
| 58 | Which source documents mention the Police committee? | documents, committees | Maybe across stored documents. | No. | Yes for matching documents. | Partially answerable |
| 59 | Which MPs have both question records and committee memberships? | questions, committees, politicians | Maybe for ingested records. | No. | Partial. | Partially answerable |
| 60 | Which ingested MPs have no source profile URL? | politicians, quality | Yes for current records. | No for launch completeness. | Yes as a data-quality answer. | Partially answerable |
| 61 | Which MPs asked the most parliamentary questions this year? | questions, politicians | No reliable answer; only 4 questions and dates are mostly missing. | No. | Partial at best. | Not answerable |
| 62 | Which MPs asked questions about Eskom during the current Parliament term? | questions, politicians | No; term-wide question coverage is absent. | No. | No complete source backing. | Not answerable |
| 63 | Which MPs from Limpopo asked about unemployment during the current Parliament term? | questions, politicians | No; province/geography and term-wide question coverage are not reliable. | No. | No. | Not answerable |
| 64 | Which MPs asked the most questions by department? | questions, politicians | No; only 4 question records. | No. | No complete source backing. | Not answerable |
| 65 | Which ministers answer late most often? | questions | No; answer due dates and broad answered-date coverage are not sufficient. | No. | No. | Not answerable |
| 66 | Which departments have the most unanswered questions? | questions | No; coverage is too sparse. | No. | No. | Not answerable |
| 67 | Which MPs sit on every police-related committee? | committees, politicians | No; committee universe and memberships are not complete. | No. | No. | Not answerable |
| 68 | Who chairs the police committee? | committees | No reliable launch answer; current committee roles are not proven complete. | No. | No. | Not answerable |
| 69 | Who is the deputy chair of the health committee? | committees | No reliable answer; role coverage is incomplete. | No. | No. | Not answerable |
| 70 | Which committees changed membership this month? | committees | No; membership history coverage is not complete. | No. | No. | Not answerable |
| 71 | Which MPs left committees in 2026? | committees | No; start and end date coverage is not complete. | No. | No. | Not answerable |
| 72 | Which MPs joined committees in 2026? | committees | No; membership history is not complete. | No. | No. | Not answerable |
| 73 | Which MPs attended the most committee meetings? | meetings, politicians | No; committee attendance records are 0. | No. | No. | Not answerable |
| 74 | Which MPs missed committee meetings? | meetings, politicians | No; committee attendance records are 0. | No. | No. | Not answerable |
| 75 | Which committee meetings discussed Eskom? | meetings | No; committee meeting records are 0. | No. | No. | Not answerable |
| 76 | Which committee meetings had attendance recorded? | meetings | No; committee meeting and attendance records are 0. | No. | No. | Not answerable |
| 77 | Which MPs voted for the NHI Bill? | accountability, politicians | No; vote events and vote records are 0. | No. | No. | Not answerable |
| 78 | Which MPs voted against the BELA Bill? | accountability, politicians | No; vote records are 0. | No. | No. | Not answerable |
| 79 | Which parties voted for a specific bill? | accountability | No; vote records are 0. | No. | No. | Not answerable |
| 80 | Which bills were passed this year? | accountability | No; bills and bill events are 0. | No. | No. | Not answerable |
| 81 | Which bills are awaiting assent? | accountability | No; bills are 0. | No. | No. | Not answerable |
| 82 | Show the lifecycle of a named bill. | accountability | No; bills and bill events are 0. | No. | No. | Not answerable |
| 83 | Which MPs sponsored or introduced a bill? | accountability, politicians | No; sponsor/introduction attribution is not populated. | No. | No. | Not answerable |
| 84 | Which bills were discussed by the health committee? | accountability, meetings | No; bills and committee meetings are 0. | No. | No. | Not answerable |
| 85 | Which MPs spoke in committee meetings about immigration? | meetings, documents, politicians | No; no committee meeting attendance/speaker data. | No. | No. | Not answerable |
| 86 | Which MPs were absent for votes? | accountability, politicians | No; vote records are 0. | No. | No. | Not answerable |
| 87 | Which MPs changed party affiliation? | politicians | No; party history is not modeled/populated. | No. | No. | Not answerable |
| 88 | Which MPs represent each province? | politicians | No; province representation is not reliable in current model/data. | No. | No. | Not answerable |
| 89 | Which MPs are constituency office contacts for Limpopo? | politicians | No; constituency office data is not present. | No. | No. | Not answerable |
| 90 | Which MPs have declared interests? | documents, politicians | No; declaration-of-interest ingestion is not present. | No. | No. | Not answerable |
| 91 | Which MPs have disciplinary records? | documents, politicians | No; disciplinary record source ingestion is not present. | No. | No. | Not answerable |
| 92 | Which MPs have the highest attendance rate? | meetings, politicians | No; attendance records are 0. | No. | No. | Not answerable |
| 93 | Which MPs have the lowest attendance rate? | meetings, politicians | No; attendance records are 0. | No. | No. | Not answerable |
| 94 | Which MPs asked questions and then attended related committee meetings? | questions, meetings, politicians | No; meeting attendance is empty. | No. | No. | Not answerable |
| 95 | Which municipalities does an MP represent? | politicians | No; municipal representation is not modeled/populated for V1. | No. | No. | Not answerable |
| 96 | Who won the latest national election by province? | IEC | No; IEC vote totals are not ingested. | No. | No. | Not answerable |
| 97 | What were party vote totals in the 2024 election? | IEC | No; IEC audit is metadata-only and vote totals are not ingested. | No. | No. | Not answerable |
| 98 | Which MPs came from each party list? | IEC, politicians | No; party-list linkage is not present. | No. | No. | Not answerable |
| 99 | Which MPs are currently ministers or deputy ministers? | politicians | No; executive office-holder data is not modeled/populated. | No. | No. | Not answerable |
| 100 | Which MPs should I contact about a service delivery issue in my area? | politicians | No; constituency/contact-area mapping is not present. | No. | No. | Not answerable |

## Launch-Blocking Fixes Only

1. **Populate a source-backed V1 baseline dataset before public launch.**  
   The current dataset is too small for realistic MP, committee, and parliamentary-question discovery. At minimum, V1 needs enough official/source-backed politicians, parties, committees, committee memberships, and parliamentary questions to support the core browse/search product without misleading users.

2. **Remove red evidence-quality risks from public domains.**  
   The current snapshot has 18 missing source URLs, 39 missing source dates, and 4 open unresolved entities. V1 should not launch with public claims until public records retain direct source evidence and unresolved attribution is either resolved or clearly excluded from user-facing answers.

3. **Establish an official expected MP universe and reconciliation gate.**  
   The system cannot safely claim all-MP coverage without a source-backed expected universe. People's Assembly data can enrich records, but it should not be treated as the authoritative baseline.

4. **Ingest enough parliamentary questions for the example query class.**  
   The current 4-question dataset is not enough for queries such as Eskom, illegal immigration, unemployment, department comparisons, or MP activity ranking.

5. **Ingest and validate committee membership coverage from a launch-safe source.**  
   Committee lookup is central to V1 user expectations, but current coverage is not sufficient for public answers such as "who sits on the police committee?"

## Non-Blockers For V1

The following should not block a narrow V1 launch if the product explicitly excludes them from public claims and UI affordances: bills, bill lifecycle, votes, attendance, IEC vote totals, ministerial office-holder data, constituency offices, declarations of interest, disciplinary records, and AI/chat functionality.

## Final Launch Call

**Do not launch V1 as a public source-backed MP accountability product yet.**

The system has the right schema direction and evidence-first posture, but the current data is not broad enough for the realistic user questions V1 is likely to receive. A narrow internal/demo launch could be acceptable only if it is labeled as a tiny ingested subset and avoids completeness claims.
