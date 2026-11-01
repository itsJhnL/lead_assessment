# Lead report and AI-assisted weekly update

Code for Parts 2 and 4 of the Senior Full-Stack AI & Systems Engineer practical assessment.
Everything is standard-library Python; there is nothing to install.

```
lead_report.py          Part 2: weekly qualified lead report
test_lead_report.py     Part 2 tests (15)
weekly_update.py        Part 4: one client -> LLM step -> checks -> local draft
test_weekly_update.py   Part 4 tests (17)
data/leads.csv          the assessment's lead table, copied as given
data/ad_spend.csv       the assessment's spend table
mock_responses/         bad AI responses used to demo and test the checks
drafts/                 saved drafts (client-a and client-b from a mock run,
                        plus drafts/rejected_examples/ showing a rejected one)
demo.sh                 the sequence used in the video
prd.md                  requirements and acceptance checks
design.md               how the two scripts work and the decisions behind them
goals.md                goals, non-goals, time box, and how success is checked
memory.md               verified numbers, decisions, lessons, open items
agents.md               rules for anyone (person or AI agent) changing this repo
```

## Requirements

Python 3.9 or newer (uses `zoneinfo`). No third-party packages.
On Windows, if you see `ZoneInfoNotFoundError`, run `pip install tzdata` once.

## Part 2: weekly report

```
python lead_report.py            # readable table + excluded rows + rules
python lead_report.py --json     # same data as JSON (Part 4 reads this)
python -m unittest -v test_lead_report
```

Output for the assessment data (reporting week 2026-09-01 to 2026-09-07, America/New_York):

| client | location | qualified | qualified IDs | unknown | unqualified | spend | cost / qualified lead |
| --- | --- | ---: | --- | ---: | ---: | ---: | --- |
| client-a | north | 2 | L001, L002 | 0 | 1 | $300.00 | $150.00 |
| client-a | south | 2 | L008, L011 | 1 (L009) | 0 | $150.00 | $75.00 |
| client-a | TOTAL | 4 | L001, L002, L008, L011 | 1 (L009) | 1 | $450.00 | $112.50 |
| client-b | north | 2 | L001, L003 | 0 | 1 | $500.00 | $250.00 |
| client-b | south | 0 | - | 0 | 0 | $200.00 | not available: $200.00 spend but 0 qualified leads |
| client-b | TOTAL | 2 | L001, L003 | 0 | 1 | $700.00 | $350.00 |

Excluded rows (CSV line numbers, header is line 1):

| row | client | lead | reason |
| ---: | --- | --- | --- |
| 3 | client-a | L001 | duplicate of row 2 (same client_id and lead_id) |
| 5 | client-a | L003 | flagged as test |
| 6 | client-a | L004 | flagged as spam |
| 7 | client-a | L005 | kind is 'callback', not a new inquiry |
| 9 | client-a | L007 | outside reporting week: 2026-09-01T00:30:00Z is 2026-08-31 20:30 EDT |
| 16 | client-b | L003 | duplicate of row 15 (same client_id and lead_id) |
| 17 | client-b | L004 | flagged as test |

The rules, in the order the script applies them, are listed at the top of `lead_report.py` and printed
under every run. The two rows that catch a naive implementation are L007 (inside the week in UTC, outside
in New York) and L011 (outside the week in UTC, inside in New York).

## Part 4: AI-assisted weekly update

```
python weekly_update.py --client client-a                      # mock mode unless ANTHROPIC_API_KEY is set
python weekly_update.py --client client-b --mock               # force mock mode
python weekly_update.py --client client-a --mock-file mock_responses/bad_cross_client.json
ANTHROPIC_API_KEY=sk-... python weekly_update.py --client client-a --live   # real request path
python -m unittest -v test_weekly_update
```

What happens on each run:

1. The Part 2 report is computed from the CSVs.
2. Only the selected client's metrics and lead IDs are put in the payload. Unknown-qualification
   leads stay in their own fields and are never added to the qualified list.
3. The payload goes to the LLM step. In live mode this is a POST to the Anthropic Messages API
   (`https://api.anthropic.com/v1/messages`) with the key read from `ANTHROPIC_API_KEY`; the key is
   never stored in code, in the draft, or in logs. In mock mode a clearly labelled stand-in response is
   built from the same payload and no network call is made. `--mock-file` feeds any text in as the
   AI response, which is how the bad responses are demonstrated.
4. The response is checked before anything is saved:
   - strict JSON and a defined shape: `summary`, 1-3 `observations` each with `text` and
     `evidence {metrics, lead_ids}`, 1-3 `next_steps`, 1+ `limitations`, no extra keys
   - every observation must cite at least one metric or lead ID, and each one must exist in this
     client's payload (`missing_evidence`, `unknown_metric`, `unknown_lead_id`)
   - any other client's ID anywhere in the response (`other_client_data`)
   - any mention of bookings, revenue, sales, profit, ROAS, return on ad spend, appointments, or
     conversion/close rates (`unsupported_claim`); the list is the `FORBIDDEN_CLAIMS` constant
   - numbers in the text that are not in the payload are flagged as warnings (`unverified_number`)
5. A draft is saved to `drafts/<client>_<week-start>.json` and `.md` with one of three statuses:
   `draft_pending_review`, `rejected_ai_output_metrics_only`, or `ai_step_failed_metrics_only`.
   The validated metrics are always in the file. Nothing is emailed, published, or changed.

Exit code 0 means a draft is waiting for review; 2 means the AI output was rejected or the AI step
failed (metrics still saved); 1 is a usage or data error. A scheduler can alert on non-zero.

Sample saved draft: `drafts/client-a_2026-09-01.md` (and `.json`).
Rejected example: `drafts/rejected_examples/client-a_2026-09-01.md`.

## Test results

```
$ python -m unittest -v
...
Ran 32 tests in 0.016s

OK
```

15 tests for Part 2 (timezone boundaries including the exact window edges, per-client lead IDs,
exact and conflicting duplicates, test/spam/callback exclusion, blank qualified as unknown,
cost not available, rounding, and the full assessment dataset) and 17 for Part 4 (normal run,
auto fallback to mock, live mode without a key failing safely, unknown client, unknown kept separate,
each bad response file, numbers flagged, too many observations, rejected output still saving metrics,
and three client-switching checks).

## Notes

**Mock mode.** I do not have approved LLM API access for this exercise and did not buy any, so the
demo runs in mock mode. The live request path (`call_anthropic`) is real and is exercised by the
"live mode without a key" test, which checks that it fails safely and still saves the metrics.
To use it: `export ANTHROPIC_API_KEY=...` and run with `--live`. The model id can be set with
`LLM_MODEL` or `--model`.

**Limits.** The forbidden-claims check is a word list, so a claim phrased differently could pass;
the numbers check only flags, because dates and counts in prose are hard to match exactly; the
mock response is built from the same payload, so it will always pass the checks unless a bad file is
supplied. One reporting week is hard-coded as the default and can be changed with
`lead_report.py --week-start`.

**Time spent.** About [X] hours in total: Part 2 about [X] minutes, Part 4 about [X] minutes
including the video. (Fill in before submitting.)

**AI tools used.** Claude (Anthropic) was used to draft the code, tests and text. I checked the
output by comparing every number in the report to a hand count of the table, tracing L007 and L011
by hand, running the tests, running both clients and every bad response file, and reading the
generated text line by line.
