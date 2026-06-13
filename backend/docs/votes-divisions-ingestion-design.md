# Parliamentary Votes / Divisions Ingestion — Design

Status: **audit + design**. Vote ingestion exists today only from explicit
vote/division language in PMG committee-meeting minutes
(`scripts/ingest_votes.py`). This document defines limitations and the rules
any expansion must follow. See `reports/votes_divisions_source_audit.json`.

## Source limitations

- There is **no dedicated public vote/division API**.
- The only implemented source is PMG committee minutes, which yield
  committee-level decisions and, occasionally, explicit aggregate counts.
- MP-level division lists are not reliably available from a structured public
  source; Parliament minutes/Hansard may contain them in PDF/HTML narrative
  form requiring parser design and risky speaker attribution.

## Vote event vs vote record rules

- **VoteEvent** = a vote/division happened (title, date, chamber, type,
  result, `source_url`). Created when explicit vote/division language exists.
- **VoteRecord** = a tallied position. Created **only** from explicit data:
  - aggregate counts ("X in favour, Y against, Z abstentions") →
    `record_level = "aggregate"`;
  - party-level tallies when explicitly stated → `record_level = "party"`;
  - named MP votes when an official division list exists →
    `record_level = "mp"`.
- An outcome-only division ("agreed to") creates a VoteEvent with **no**
  records.

## Party-level vs MP-level distinction

Party-level and MP-level records must never be conflated. A party tally is not
evidence of how any individual MP voted, and an individual vote is never
inferred from the party's position.

## Abstention / absence uncertainty

Abstentions and absences are recorded only when the source states them.
Silence is not an abstention and not an absence; unknown remains unknown.

## Source evidence retention

Every vote event and record stores the official/PMG `source_url`. Where the
evidence is a PDF/minute, the archived document path is retained outside Git.

## Idempotency strategy

VoteEvents upsert by unique `source_url`; vote records upsert by
(`vote_event_id`, `record_level`, `party_id`/`politician_id`, `vote_value`).
Re-running updates rather than duplicates.

## What must remain unknown

- Individual MP votes when only party or aggregate data exists.
- The result of a division when the source states none.
- Whether an absent member abstained or was simply not present.
