# Municipal Councils and Office-Bearers Ingestion — Design

Status: **design + discovery only**. No municipal data is ingested. This
defines a safe future ingestion path for local-government councils and
office-bearers.

## Non-negotiable rules

- **No fabricated office-bearers.** Never record a councillor, mayor, speaker,
  or whip without official confirmation that the person holds the office.
- **Winners are not office-bearers.** An IEC election/ward result identifies a
  winning candidate or party allocation — not a seated, sworn-in council
  office-holder. Office terms require separate official confirmation.
- **Source evidence required.** Every record stores an official `source_url`
  and the `source_date`/term dates the source states.
- **Trusted vs candidate sources.** National Treasury (Municipal Money) and
  IEC are official. Individual municipal websites and associations (e.g.
  SALGA) are candidates and must be validated before trust.

## Candidate sources

See `reports/municipal_source_discovery.json`. Treasury Municipal Money
(finance/audit), IEC LGE results (ward/party composition), COGTA/SALGA
(council/office-bearer context — candidates).

## Proposed schema

- `municipalities` — `id`, `municipality_code` (official demarcation code,
  unique), `name`, `province`, `category` (A/B/C), `source_url`.
- `municipal_councils` — `id`, `municipality_id`, `term_start`, `term_end`,
  `source_url`; one per council term.
- `municipal_office_bearers` — `id`, `municipality_id`, `council_id`,
  `person_name_raw`, `resolved_politician_id` (nullable — unresolved stays
  unresolved), `role` (mayor/speaker/whip/councillor), `party_raw`,
  `ward` (nullable), `term_start`, `term_end`, `source_url`, `confidence`.

## Municipality identifiers

Use the official demarcation `municipality_code` as the stable key. Names
change and are ambiguous; codes are stable. Store name as a label only.

## Councillor identity risks

Councillor names are common and frequently non-unique across municipalities.
Resolution must be deterministic (exact/alias) and scoped to the municipality;
ambiguous names remain unresolved (consistent with #28). Never merge a
councillor into a national politician without explicit evidence.

## Ward / election period handling

Ward results are tied to a specific election and delimitation. Store the
election/term context with each record; never carry a ward councillor forward
across terms without confirmation.

## What cannot be inferred

- Seated office from election results alone.
- Continuation of office across terms.
- Party of an office-bearer when the source does not state it.
- A national-politician identity for a municipal councillor without evidence.

## Idempotency strategy

Upsert by `municipality_code` and by unique `source_url` for term/office
records. Per-item failures recorded with source URL + safe error; batch never
aborts on one bad municipality.
