# Chapter 9 Institution Reports Ingestion — Design

Status: **design + discovery only**. No Chapter 9 reports are ingested and no
findings are extracted. This defines a safe future path for official report
metadata and, later, structured findings.

## Non-negotiable rules

- **No fabricated findings.** Never record a finding, remedial action, or
  named subject that is not explicitly stated in an official report.
- **No allegation-as-finding.** Allegations, complaints, and media claims are
  not findings. Only an institution's own stated finding is a finding.
- **Media is never an official source.** News articles may not substitute for
  or stand in as official institution reports.
- **Evidence required.** Every record stores the official report `source_url`
  and, for any extracted finding, a page/section snippet locator proving it.
- **Named subjects** are recorded only when explicitly named in official
  report metadata/text — never inferred.

## Candidate sources

See `reports/chapter9_source_discovery.json`. Public Protector
(`pprotect.org`) and SAHRC (`sahrc.org.za`) official sites. Other Chapter 9
institutions are added only when an official, validatable source exists.

## Proposed schema

- `oversight_reports` — `id`, `institution`, `title`, `report_number`
  (nullable), `published_date`, `source_url` (unique), `document_url`,
  `archive_path`, timestamps.
- `oversight_findings` — `id`, `report_id` (FK), `finding_text`,
  `finding_type` (`finding` | `remedial_action`), `evidence_locator`
  (page/section snippet), `source_url`. Created ONLY from explicitly
  structured official content with a passing parser + tests.
- `oversight_report_subjects` — `id`, `report_id` (FK), `subject_name_raw`,
  `resolved_politician_id` (nullable — unresolved stays unresolved),
  `evidence_locator`, `source_url`.

## Findings / remedial action extraction rules

1. Phase 1 (this design): report **metadata only** — title, date, URL.
2. Phase 2 (future, separate PR): findings extraction only where the report
   exposes a structured, testable format. Each finding must carry an
   `evidence_locator` (page/section + snippet).
3. Free-text PDFs without reliable structure are stored as report metadata +
   archived document only; no findings are auto-extracted.

## Page/snippet evidence requirements

Any stored finding or named subject must include the exact page/section and a
short verbatim snippet locator so a reviewer can verify it against the source.

## Named subject matching risks

Subject names in reports are sensitive and often ambiguous. Resolution is
deterministic only; ambiguous names stay unresolved (consistent with #28).
Never assert that a named subject is a specific politician without explicit
evidence.

## Idempotency strategy

Upsert by unique report `source_url`. Findings/subjects upsert by
(`report_id`, `evidence_locator`). Per-item failures recorded with source URL
+ safe error; the batch never aborts on one bad report.
