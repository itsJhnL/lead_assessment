# Goals

## The one goal

Correct weekly numbers with the rules written down, and an AI draft that cannot say more than
the numbers support. Everything else is secondary.

## Goals, in priority order

| # | Goal | Done when | Status |
| --- | --- | --- | --- |
| 1 | The six result rows match a hand count of the assessment table | `test_lead_report.AssessmentData` passes; values listed in `memory.md` | Done |
| 2 | Every rule is visible: in the code, in the output, and in the submission document | `RULES` printed on every run; rules section in the doc | Done |
| 3 | Every excluded row is listed with one reason | 7 rows printed under "Excluded rows" | Done |
| 4 | Tests for the trickiest rules | Timezone edges, per-client IDs, duplicates, unknown, cost not available | Done (15 tests) |
| 5 | One client at a time reaches the AI step, unknown kept separate | `SwitchingClients` and `UnknownKeptSeparate` tests | Done |
| 6 | Bad AI output is rejected with a plain reason and the numbers are still saved | Five bad files rejected; `rejected_ai_output_metrics_only` keeps metrics | Done (17 tests) |
| 7 | Real request path with the key from the environment, mock mode for the demo | `call_anthropic`; MOCK MODE banner; live-without-key test | Done |
| 8 | A reviewer can run everything from the README in two minutes | README + `demo.sh` | Done |
| 9 | Daily run on Google Cloud designed, with failure and alerting behaviour | Section in the submission document | Done (design only) |
| 10 | 5-10 minute video showing a normal run, client switch, a rejection, the saved draft, and the Sage answer | Loom link in the document | To do |

## Non-goals (deliberately not built)

- Real CRM or ad platform integrations
- A web interface or hosting
- Sending, publishing, or changing anything outside the local `drafts/` folder
- Multi-week trends or comparisons
- Configuration for many clients and timezones (a `--week-start`/`--tz` flag is enough here)

## Time box

The assessment estimates 4 hours total: Part 1 about 45 minutes, Part 2 about 75, Part 3
about 30, Part 4 about 90 including the video. Stop at the limit and write down what would come
next; that list is in the submission document under "What I would do next with more time".

## How success is checked

- `python -m unittest -v` reports `Ran 32 tests ... OK` on the author's machine and on a clean
  unzip.
- A second, independent calculation of the Part 2 numbers (UTC-bounds filter, set-based
  dedupe, float arithmetic) agrees with the script.
- The saved draft for client-a reads correctly as a document a person could edit and send.
- The submission document, the README and the code quote the same numbers.
