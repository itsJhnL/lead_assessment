# agents.md

Instructions for anyone, human or AI coding agent, working in this repository.

## What this is

Two standard-library Python scripts for the Senior Full-Stack AI & Systems Engineer practical
assessment: `lead_report.py` (weekly qualified lead report) and `weekly_update.py`
(AI-assisted weekly update draft with checks). Read `prd.md` for requirements, `design.md`
for how it works, `goals.md` for what done looks like, and `memory.md` for decisions already
made and numbers already verified. Do not re-derive those; build on them.

## Commands

```
python -m unittest -v                      # all 32 tests; must pass before and after any change
python lead_report.py                      # Part 2 report
python lead_report.py --json               # same as JSON
python weekly_update.py --client client-a --mock
python weekly_update.py --client client-a --mock-file mock_responses/bad_cross_client.json
bash demo.sh                               # the demo sequence (Mac/Linux; on Windows run the lines by hand)
```

Windows only, once: `pip install tzdata` (Python's `zoneinfo` needs the IANA database).

## Rules for changes

1. **Never put a secret in the repo.** The only credential is `ANTHROPIC_API_KEY`, read from
   the environment inside `call_anthropic()`. Do not log it, print it, write it to a draft, or
   add a `.env` file to git (`.gitignore` already excludes it).
2. **Only synthetic data.** `data/` holds the assessment's two tables. Do not add real client
   data, real names, or real lead records anywhere, including tests and mock responses.
3. **The rules in `lead_report.py` are the product.** If you change how a row is classified,
   update the `RULES` list, the docstring at the top of the file, the matching test, and
   `memory.md`. A rule change without a test change is a bug.
4. **Standard library only.** Do not add dependencies. If something truly needs a package,
   say so in the pull request and update the README's Requirements section.
5. **Every rejection must say why in plain words.** New validation checks in
   `validate_ai_response()` return an error string that starts with a code
   (`code: explanation`) and get a bad example file in `mock_responses/` plus a test.
6. **The AI step never acts.** `weekly_update.py` writes local drafts only. Do not add code
   that emails, posts, publishes, or touches an ad platform, even behind a flag.
7. **Keep it readable on a screen recording.** Short functions, explicit names, comments that
   say why. The author explains this code on video.
8. **Run the tests.** Before and after. If a test fails, fix the cause, not the test, unless
   the requirement changed and `prd.md` was updated first.

## When editing documentation

- `README.md` is for someone running the code. `design.md` is for someone changing it.
- Numbers quoted in any document must match a fresh run of `python lead_report.py`.
  The verified values are listed in `memory.md`.
- Do not describe features that do not exist. The daily Google Cloud run is a design, not code.

## Disclosure

AI tools were used to draft this repository (Claude, by Anthropic). The author reviewed the
output by hand-counting the assessment table, tracing the two timezone edge cases, running the
test suite and every bad response file, and reading each line. Keep that standard: anything an
agent writes here is checked by a person before it is committed.
