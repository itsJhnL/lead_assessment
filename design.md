# Design

## Overview

Two small command-line scripts, standard-library Python, one folder, no services.

```
data/leads.csv  data/ad_spend.csv
        |
        v
lead_report.py ---- run_report() ----> results per client/location/total
        |                                      |
        |  (text or --json)                    v
        |                         weekly_update.py
        |                              build_client_payload(client)   one client only
        |                                      |
        |                              call_anthropic() | mock_llm_response() | --mock-file
        |                                      |
        |                              validate_ai_response()           reject or accept
        |                                      |
        |                              save_draft()  -> drafts/<client>_<week>.json + .md
```

Part 4 imports Part 2 rather than re-reading its output, so there is one definition of the
rules and the numbers in the draft are the same objects the report printed.

## Part 2: `lead_report.py`

**Data model.** Each CSV row becomes a `Lead` dataclass with both the UTC and the local
(America/New_York) timestamp and a three-state `qualified` field: `True`, `False`, or `None`
for unknown. Money is `Decimal`, never float, and is only rounded when formatted.

**Classification order.** `classify()` applies the rules in a fixed order and gives each
excluded row exactly one reason, the first rule that catches it:

1. flag is test or spam
2. kind is not inquiry
3. local date outside the week
4. duplicate (client_id, lead_id) among the rows that survived 1-3

Dedupe runs last so an excluded row never "uses up" a lead ID. A duplicate with different
values keeps the first row and adds a warning instead of guessing.

**Timezone.** The week is defined as local dates. Each UTC timestamp is converted with
`zoneinfo` and its local date is compared to the start and end dates. This is easier to read
and to test than converting the window to UTC, and it handles daylight-saving weeks for free.

**Aggregation.** `build_results()` takes the union of locations from the spend file and the
kept leads, so a location with spend and no leads (client-b south) and a location with leads
and no spend (not in this data) both appear. Client totals sum every spend row for the client.

**Cost per qualified lead.** `cost_per_qualified_lead()` returns `(value, note)`. When the
value cannot be computed the note says why, and the text and JSON output carry the note instead
of a number. There is no code path that produces `0.00` from spend with zero leads.

**Output.** One function formats text for people; `--json` emits the same dictionary for
machines. Both include the excluded rows, the warnings and the rule list, so a screenshot of a
run is a complete explanation of the numbers.

## Part 4: `weekly_update.py`

**Isolation of clients.** `build_client_payload()` filters the Part 2 results to one
`client_id` and returns a new dictionary. It also builds two allow-lists, `allowed_metrics`
(names like `south.cost_per_qualified_lead`) and `allowed_lead_ids` (qualified plus unknown
IDs). The AI step and the validator see only this object. A test asserts that the other
client's ID and lead IDs are absent.

**LLM step.** Three modes chosen at run time:

- `live`: POST to `https://api.anthropic.com/v1/messages` with `urllib`. The key is read
  from `ANTHROPIC_API_KEY` inside `call_anthropic()` and goes only into the request header.
  Any failure (HTTP error, network, timeout, empty content) raises `AIStepError` with a
  message that never includes the key.
- `mock`: `mock_llm_response()` builds a valid response from the payload. It is the default
  when no key is set, and every run prints a MOCK MODE banner and records `mode: mock`.
- `--mock-file`: any text file is used as the raw response. This is how bad responses are
  demonstrated and tested without a model.

The system prompt asks for bare JSON with an exact key set and forbids the claim types the
validator also rejects. The prompt is the first line of defence; the validator is the second;
the human review is the third.

**Validation.** `validate_ai_response()` returns `{ok, errors, warnings, draft}`. Any error
rejects the draft. Checks, in order:

| Check | Error code | Why |
| --- | --- | --- |
| JSON parses (a code fence is stripped with a warning) | `invalid_json` | Prose cannot be saved as a draft |
| Exact top-level keys; observation, next-step and limitation shapes and limits | `invalid_shape` | A defined shape is required by the task |
| Each observation cites at least one metric or lead ID | `missing_evidence` | Every claim must be traceable |
| Each cited metric and lead ID exists in the payload | `unknown_metric`, `unknown_lead_id` | Catches excluded, unqualified and other-client leads |
| No other client ID anywhere in the response | `other_client_data` | Clients must never mix |
| No word from `FORBIDDEN_CLAIMS` | `unsupported_claim` | Bookings, revenue, ROAS etc. cannot be proven from this data |
| Numbers in the text appear in the payload | `unverified_number` (warning) | Prose numbers are hard to match exactly, so this flags rather than rejects |

**Saved draft.** One JSON record and one Markdown rendering per client and week. The record
always carries the validated `metrics`, the `status`, `mode`, `model`, `validation`, and the
raw response (truncated), so a rejected draft is still useful and debuggable.

**Exit codes.** 0 draft pending review, 2 rejected or AI step failed, 1 usage error. A
scheduler alerts on non-zero.

## Decisions and trade-offs

- **Standard library only.** The task values correct numbers and clear reasoning over an
  application. `csv`, `decimal`, `zoneinfo`, `json`, `urllib` and `unittest` cover everything.
- **`unittest` over `pytest`.** Zero install; pytest still discovers and runs the same tests.
- **Word-list claim check.** Simple and visible. Known weakness: a differently phrased claim
  can pass. Mitigated by the prompt and human review; a stricter version would map each number
  in the text to the specific metric it claims.
- **Mock built from the real payload.** Keeps the demo honest (same numbers as the report) but
  means the mock always passes unless a bad file is supplied.
- **Single reporting week as a default.** `--week-start` and `--tz` change it; a config file
  would be the next step for many clients.

## Daily operation (planned, not built)

Cloud Scheduler -> Cloud Run job -> raw tables in BigQuery (partitioned by report date, with
`run_id`, `source`, `fetched_at`) -> same rules -> report table + JSON in Cloud Storage ->
`run_log` row. Secrets in Secret Manager. Auth errors fail fast and are not retried.
Completeness checks (pagination complete, every client/location has spend, counts within a
band of the trailing average, newest record fresh) mark a run `partial` and block publishing.
Alerts on failed or partial runs and on "no success row by 08:00". Details are in the
submission document.
