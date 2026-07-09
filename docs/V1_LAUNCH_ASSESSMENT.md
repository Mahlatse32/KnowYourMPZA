# KnowYourMPZA V1 Launch Assessment

Assessment date: 2026-07-09

## Recommendation

GO WITH KNOWN LIMITATIONS, pending PR4 merge/CI and deployment from latest `main`.

The product is now valuable for a first-time public user because the MP profile journey can answer the core questions with source-backed evidence. The main remaining risk is over-claiming completeness. PR4 addresses that by making empty and partial sections explicit in the UI.

## Evidence Reviewed

- PR #76 merged: party enrichment from explicit PMG attendance data.
- PR #77 merged: question docsjson metadata enrichment.
- PR #78 merged: MP attendance endpoint and frontend panel; CI run `28998338744` passed.
- PMG meeting backfill run `28994456199`: `22656/34713 = 65.27%`, cursor completed at page 462.
- Parliament questions backfill run `28995667052`: `3994/44036 = 9.07%`, `processed=194`, `updated=194`, `failed=6` permanent 404s, workflow green.
- Scheduled ingestion run `28921400351`: frontend production smoke `15/15` checks passed.

## User-Journey Assessment

| User question | Current answer quality | Evidence |
|---|---|---|
| Who is this MP? | Good for V1 | 521 source-backed politician records; profile pages load in smoke tests. |
| Which party do they belong to? | Good with caveat | Party enrichment has moved production from one `Unknown` party to 16 parties; unconfirmed MPs must say so. |
| Which committees do they serve on? | Good for linked MPs | 34 committees and 521 memberships; empty states explain missing links. |
| What parliamentary work have they done? | Good with historical limits | 22,656 PMG meetings, 209,192 attendance rows, 70 PMG documents, 3,994 questions, 897 vote events. |
| Where can this information be verified? | Good | Latest reports show 0 missing source URLs; frontend exposes evidence links. |

## Known Limitations

- PMG meeting coverage is 65.27%, below the old 80% historical threshold, but already large enough to show meaningful work history.
- Parliament questions coverage is 9.07%; useful but clearly partial.
- Current production artifacts still show many question dates missing, so UI copy must say when a date or text has not been extracted.
- Vote records remain sparse (`5` explicit records); do not market voting-history completeness.
- People's Assembly remains enrichment-only because source access from runners is unreliable.
- Deployment is still an operational step outside this repository.

## Launch Conditions

1. Merge PR4 with green CI.
2. Deploy backend/frontend from latest `main`.
3. Verify production smoke after deployment.
4. Keep the PMG meeting and Parliament questions backfill workflows running.
5. Use launch copy that says coverage is source-backed and still expanding.

## Post-V1 Roadmap

1. Continue PMG meeting backfill to at least 80% and then disable/reduce the high-frequency cron.
2. Continue Parliament questions backfill and improve date/title extraction reporting.
3. Improve question-to-MP linking beyond raw asker strings.
4. Expand vote/division records beyond the current explicit named-record sample.
5. Add an authoritative Parliament MP universe reconciliation once an official source is validated.
