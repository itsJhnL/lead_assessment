# memory.md

Working memory for this repository: decisions made, numbers verified, and things learned.
Append, do not rewrite, so the history stays readable.

## Verified numbers (reporting week 2026-09-01 to 2026-09-07, America/New_York)

| Client | Location | Qualified | Qualified IDs | Unknown | Unqualified | Spend | Cost / qualified lead |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| client-a | north | 2 | L001, L002 | 0 | 1 | 300.00 | 150.00 |
| client-a | south | 2 | L008, L011 | 1 (L009) | 0 | 150.00 | 75.00 |
| client-a | TOTAL | 4 | L001, L002, L008, L011 | 1 | 1 | 450.00 | 112.50 |
| client-b | north | 2 | L001, L003 | 0 | 1 | 500.00 | 250.00 |
| client-b | south | 0 | - | 0 | 0 | 200.00 | not available |
| client-b | TOTAL | 2 | L001, L003 | 0 | 1 | 700.00 | 350.00 |

Excluded: row 3 (client-a L001 duplicate), 5 (L003 test), 6 (L004 spam), 7 (L005 callback),
9 (L007 outside week), 16 (client-b L003 duplicate), 17 (L004 test). 16 input rows, 9 counted.

Verified three ways: by hand from the PDF table, by `lead_report.py`, and by an independent
script that filtered on UTC bounds (04:00Z Sep 1 to 04:00Z Sep 8) with set-based dedupe.

## Decisions

- **Local-date comparison, not UTC-window comparison.** Both give the same answer; local dates
  are easier to explain and handle daylight-saving weeks. The UTC window is quoted in `RULES`
  for readers who think in UTC.
- **Exclusions before dedupe.** A test or spam row must not consume a lead ID. No effect on
  this data (both duplicate pairs are identical rows).
- **Three qualification states.** `True`, `False`, `None`. Unqualified is counted and shown so
  the row totals reconcile; it never enters the qualified count or the cost.
- **Unexpected `qualified` values are unknown with a warning**, not an exception. A daily job
  should not crash on `yes`, but it must not silently decide either.
- **Cost not available is `None` plus a note**, carried through text, JSON, the payload and
  the draft. No code path yields 0.00 from spend with zero leads.
- **Cost divides by all qualified leads including organic**, as the task defines it. No
  organic lead is qualified this week, so paid-only gives identical numbers.
- **Client isolation by construction, then by check.** The payload is built from one client's
  rows; the validator additionally rejects any other client ID in the response, and any lead
  ID not in the client's allow-list.
- **Allow-lists for evidence.** `allowed_metrics` names and `allowed_lead_ids` make "does
  this citation exist" a set lookup rather than a judgement.
- **Word-list for unsupported claims**, as one visible constant. Known to be a backstop, not
  a guarantee.
- **Numbers check warns, does not reject.** Dates and counts in prose produce false matches.
- **Mock built from the real payload** so the demo numbers are the report numbers. Bad
  responses live in `mock_responses/` and are fed with `--mock-file`.
- **Anthropic Messages API for the live path**, `urllib` only, key from `ANTHROPIC_API_KEY`,
  model from `LLM_MODEL` or `--model`. No API access was bought for this exercise.
- **Exit code 2 for rejected or failed AI step** so a scheduler can alert while the metrics
  are still saved.

## Things learned the hard way

- Windows does not ship the IANA timezone database. `zoneinfo.ZoneInfo("America/New_York")`
  raises `ZoneInfoNotFoundError` until `pip install tzdata` is run. Documented in the README
  and in `agents.md`. The command is `pip install tzdata`, not `install tzdata`.
- `datetime.fromisoformat` accepts a trailing `Z` only from Python 3.11; `parse_utc()` replaces
  `Z` with `+00:00` so 3.9 and 3.10 work too.
- The numbers check must ignore digits inside lead IDs (`L001`) and dates (`2026-09-01`);
  a look-behind on letters, digits, `_` and `-` handles both.
- Keep the terminal font large for the recording; the excluded-rows block is the part a
  reviewer will pause on.

## Open items

- [ ] Fill in time spent in the submission document and the README.
- [ ] Add the GitHub link and the Loom link to the submission document.
- [ ] Record the video (target 8 minutes, hard stop 10).
- [ ] Confirm with the team: paid-only versus all-source cost per qualified lead; first-row
      versus last-row wins on conflicting duplicates.
