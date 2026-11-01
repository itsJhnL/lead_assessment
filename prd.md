# PRD: Weekly lead report and AI-assisted client update

## Problem

The team turns marketing and lead data into weekly reports and draft recommendations for
review. Done by hand, the weekly numbers are slow to produce and easy to get wrong: timestamps
are in UTC, lead IDs repeat across clients, rows arrive duplicated, test and spam rows are
mixed in, and some leads have no qualification decision yet. Draft commentary written from
those numbers must never claim more than the data shows.

## Users

- **Account team** reads the weekly numbers and the draft update, edits it, and sends it on.
- **Engineer on rotation** runs or schedules the job, and is the person alerted when it fails.
- **Reviewer** (this assessment) needs to see the rules, the numbers, and the checks clearly.

## Scope

In scope: one reporting week of synthetic data for two clients; qualified lead counts, lead IDs,
unknown-qualification counts, ad spend and cost per qualified lead per client and location and
per client total; a draft weekly update for one selected client, generated with an LLM step and
checked before it is saved; tests; a plan for running daily on Google Cloud.

Out of scope: real CRM or ad platform connections, sending or publishing anything, changing ad
campaigns, a web interface, multi-week trends, and any use of real client data.

## Requirements

### R1. Weekly report (`lead_report.py`)

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| R1.1 | Reporting week is 2026-09-01 to 2026-09-07 in America/New_York | L007 (2026-09-01T00:30Z) excluded; L011 (2026-09-08T02:00Z) included |
| R1.2 | `created_at` is UTC and is converted before deciding the day | Window edge tests at 03:59:59Z and 04:00:00Z pass |
| R1.3 | Lead ID is unique only within a client | client-a L001 and client-b L001 are both counted |
| R1.4 | Repeated (client_id, lead_id) rows count once | Row 3 and row 16 excluded as duplicates |
| R1.5 | Rows flagged test or spam are left out | Rows 5, 6, 17 excluded |
| R1.6 | Callbacks are not new inquiries | Row 7 excluded |
| R1.7 | Blank qualified is unknown, reported separately, counted as neither | client-a south shows 1 unknown (L009) and 2 qualified |
| R1.8 | Spend with no qualified leads shows "not available" with a reason, never 0 | client-b south |
| R1.9 | Every excluded row is listed with its reason | 7 rows printed under "Excluded rows" |
| R1.10 | Output per client and location and per client total | 6 result rows |

### R2. AI-assisted update (`weekly_update.py`)

| ID | Requirement | Acceptance check |
| --- | --- | --- |
| R2.1 | User selects one client; only that client's metrics and lead IDs reach the AI step | Payload for client-b contains no client-a ID or client-a-only lead |
| R2.2 | Unknown qualification stays separate from qualified | `unknown_lead_ids` is its own field; L009 never in `qualified_lead_ids` |
| R2.3 | Draft has a summary, up to 3 observations, up to 3 next steps, and limitations | Shape check |
| R2.4 | Every observation names the metric or lead IDs that support it | `missing_evidence` rejection |
| R2.5 | Real LLM request path with the key from an environment variable | `call_anthropic`; no key in code or output |
| R2.6 | Clearly labelled mock response when no API access | MOCK MODE banner; `mode: mock` in the saved file |
| R2.7 | Response is checked before saving: JSON shape, evidence, other client's data, unsupported claims | Five bad response files all rejected |
| R2.8 | If the AI step fails, validated metrics are still saved | `ai_step_failed_metrics_only` status |
| R2.9 | Output is a local draft with a clear status; nothing is sent, published or changed | `drafts/<client>_<week>.json` and `.md` |
| R2.10 | Tests for a normal run, a bad response, and client switching | 17 tests in `test_weekly_update.py` |

## Success criteria

- All numbers in the output match a hand count of the assessment table.
- `python -m unittest` passes on Windows, Mac and Linux with Python 3.9+ and no third-party packages (Windows needs `tzdata` for the timezone database).
- A reviewer can run the demo in under two minutes from the README alone.
- Every rejection names the rule it broke in plain words.

## Open questions for the team

- Should cost per qualified lead divide by all qualified leads or paid-source leads only? Both are one line apart; the task's definition (all leads) is implemented.
- What should happen when a duplicate (client_id, lead_id) pair has different values? First row is kept with a warning; the team may prefer last-write-wins from the CRM.
