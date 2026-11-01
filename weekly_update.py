#!/usr/bin/env python3
"""
Part 4 - AI-assisted weekly client update (a draft for human review).

What it does
  1. Runs the Part 2 report (lead_report.run_report) on the synthetic data.
  2. Selects ONE client and builds a payload with only that client's weekly
     metrics and supporting lead IDs. Unknown-qualification leads are kept
     separate from confirmed qualified leads.
  3. Sends the payload to the LLM step.
        live mode : Anthropic Messages API. The key comes from the environment
                    variable ANTHROPIC_API_KEY and is never stored in code.
        mock mode : a clearly labelled mock response built from the same
                    payload. No network call. This is the default when no key
                    is set, and the mode used for the demo.
  4. Checks the response BEFORE saving it:
        - strict JSON shape (summary, observations <= 3 with evidence,
          next_steps <= 3, limitations)
        - every observation names a metric or lead ID that exists in this
          client's payload (missing evidence is rejected)
        - no other client's ID anywhere in the response
        - no claims about bookings, revenue, ROAS or anything Part 2 cannot prove
        - numbers in the text that do not appear in the payload are flagged
  5. Saves a draft locally (drafts/<client>_<week>.json and .md) with a clear
     status. The validated Part 2 metrics are saved even when the AI step fails
     or its output is rejected. Nothing is emailed, published or changed.

Usage
  python weekly_update.py --client client-a                 # mock unless ANTHROPIC_API_KEY is set
  python weekly_update.py --client client-b --mock          # force mock mode
  python weekly_update.py --client client-a --mock-file mock_responses/bad_revenue_claim.json
  ANTHROPIC_API_KEY=... python weekly_update.py --client client-a --live

Exit codes: 0 draft saved for review, 2 AI output rejected or AI step failed
(the draft with metrics is still saved), 1 usage or data error.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

import lead_report

HERE = Path(__file__).resolve().parent
DEFAULT_OUT_DIR = HERE / "drafts"
ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
ANTHROPIC_VERSION = "2023-06-01"
DEFAULT_MODEL = os.environ.get("LLM_MODEL", "claude-sonnet-4-5")

MAX_OBSERVATIONS = 3
MAX_NEXT_STEPS = 3
REQUIRED_KEYS = {"summary", "observations", "next_steps", "limitations"}

# Claims the weekly lead data cannot support. Any of these words in the AI
# output rejects the draft. Kept as one visible list so it is easy to extend.
FORBIDDEN_CLAIMS = re.compile(
    r"\b(bookings?|booked|revenue|sales|profit|roas|return on ad spend|appointments?|conversion rate|close rate)\b",
    re.IGNORECASE,
)

SYSTEM_PROMPT = """You draft a short internal weekly update about one client's lead data.
Use ONLY the numbers and lead IDs in the JSON you are given. Do not invent anything.
Unknown-qualification leads are NOT qualified leads; keep them separate.
Never mention bookings, revenue, sales, profit, ROAS, return on ad spend, appointments or rates you were not given.
Return ONLY a JSON object, no prose and no code fences, with exactly these keys:
{
  "summary": string,
  "observations": [ {"text": string, "evidence": {"metrics": [metric names from allowed_metrics], "lead_ids": [lead IDs from the payload]}} ]  (1 to 3 items, each with at least one metric or lead ID),
  "next_steps": [string]  (1 to 3 items),
  "limitations": [string]  (1 or more items)
}"""


class AIStepError(Exception):
    """The LLM step could not produce a response (network, auth, timeout). Never contains the key."""


# --------------------------------------------------------------------------- #
# Step 2: one client's payload
# --------------------------------------------------------------------------- #

def build_client_payload(report: dict, client_id: str) -> dict:
    """Only this client's rows. Nothing from any other client leaves this function."""
    rows = [r for r in report["results"] if r["client_id"] == client_id]
    if not rows:
        known = sorted({r["client_id"] for r in report["results"]})
        raise ValueError(f"unknown client {client_id!r}; known clients: {known}")

    def metric_block(row: dict) -> dict:
        return {
            "location": row["location"].lower(),
            "qualified_leads": row["qualified_leads"],
            "qualified_lead_ids": row["qualified_lead_ids"],
            "unknown_qualification": row["unknown_qualification"],
            "unknown_lead_ids": row["unknown_lead_ids"],
            "unqualified": row["unqualified"],
            "ad_spend": row["ad_spend"],
            "cost_per_qualified_lead": row["cost_per_qualified_lead"],
            "cost_note": row["cost_note"],
        }

    locations = [metric_block(r) for r in rows if r["location"] != "TOTAL"]
    total = metric_block(next(r for r in rows if r["location"] == "TOTAL"))

    metric_fields = ("qualified_leads", "unknown_qualification", "unqualified", "ad_spend", "cost_per_qualified_lead")
    allowed_metrics = sorted(
        f"{block['location']}.{field}" for block in locations + [total] for field in metric_fields
    )
    allowed_lead_ids = sorted(set(total["qualified_lead_ids"]) | set(total["unknown_lead_ids"]))

    return {
        "client_id": client_id,
        "reporting_week": report["reporting_week"],
        "locations": locations,
        "total": total,
        "allowed_metrics": allowed_metrics,
        "allowed_lead_ids": allowed_lead_ids,
        "notes": [
            "qualified_lead_ids are confirmed qualified leads (qualified = true).",
            "unknown_lead_ids have a blank qualified value; they are not qualified and not unqualified.",
            "cost_per_qualified_lead is null where it is not available; cost_note says why.",
            "This data cannot show bookings, revenue, or return on ad spend.",
        ],
    }


# --------------------------------------------------------------------------- #
# Step 3: the LLM step (live or mock)
# --------------------------------------------------------------------------- #

def call_anthropic(payload: dict, model: str = DEFAULT_MODEL, timeout: int = 60) -> tuple[str, str]:
    """Real request path. Returns (response_text, model_used). Raises AIStepError on failure."""
    api_key = os.environ.get("ANTHROPIC_API_KEY")
    if not api_key:
        raise AIStepError("ANTHROPIC_API_KEY is not set; run with --mock or export the key")

    body = {
        "model": model,
        "max_tokens": 1024,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": json.dumps(payload, indent=2)}],
    }
    request = urllib.request.Request(
        ANTHROPIC_URL,
        data=json.dumps(body).encode("utf-8"),
        headers={
            "x-api-key": api_key,                 # read from the environment, never logged
            "anthropic-version": ANTHROPIC_VERSION,
            "content-type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            data = json.load(response)
    except urllib.error.HTTPError as err:
        raise AIStepError(f"LLM API returned HTTP {err.code}") from None
    except urllib.error.URLError as err:
        raise AIStepError(f"LLM API not reachable: {err.reason}") from None
    except TimeoutError:
        raise AIStepError(f"LLM API timed out after {timeout}s") from None

    text = "".join(block.get("text", "") for block in data.get("content", []) if block.get("type") == "text")
    if not text.strip():
        raise AIStepError("LLM API returned an empty response")
    return text, data.get("model", model)


def mock_llm_response(payload: dict) -> str:
    """A labelled stand-in for the LLM, built from the same payload so the demo is realistic."""
    total = payload["total"]
    observations = [{
        "text": (
            f"{total['qualified_leads']} qualified leads for the week on ${total['ad_spend']} of ad spend, "
            + (f"a cost per qualified lead of ${total['cost_per_qualified_lead']}."
               if total["cost_per_qualified_lead"] else "so cost per qualified lead is not available.")
        ),
        "evidence": {
            "metrics": ["total.qualified_leads", "total.ad_spend", "total.cost_per_qualified_lead"],
            "lead_ids": total["qualified_lead_ids"],
        },
    }]
    for loc in payload["locations"]:
        if loc["cost_per_qualified_lead"] is None and loc["ad_spend"]:
            observations.append({
                "text": f"{loc['location']} spent ${loc['ad_spend']} with 0 qualified leads, so its cost per qualified lead is not available.",
                "evidence": {"metrics": [f"{loc['location']}.ad_spend", f"{loc['location']}.qualified_leads"], "lead_ids": []},
            })
    if total["unknown_qualification"] > 0:
        observations.append({
            "text": f"{total['unknown_qualification']} lead has no qualification value yet and is not counted as qualified.",
            "evidence": {"metrics": ["total.unknown_qualification"], "lead_ids": total["unknown_lead_ids"]},
        })
    priced = [l for l in payload["locations"] if l["cost_per_qualified_lead"]]
    if len(priced) > 1 and len(observations) < MAX_OBSERVATIONS:
        cheapest = min(priced, key=lambda l: float(l["cost_per_qualified_lead"]))
        dearest = max(priced, key=lambda l: float(l["cost_per_qualified_lead"]))
        observations.append({
            "text": f"{cheapest['location']} cost ${cheapest['cost_per_qualified_lead']} per qualified lead against ${dearest['cost_per_qualified_lead']} in {dearest['location']}.",
            "evidence": {"metrics": [f"{cheapest['location']}.cost_per_qualified_lead", f"{dearest['location']}.cost_per_qualified_lead"], "lead_ids": []},
        })

    next_steps = []
    if total["unknown_qualification"] > 0:
        next_steps.append(f"Ask the client to qualify {', '.join(total['unknown_lead_ids'])} so next week's count is complete.")
    for loc in payload["locations"]:
        if loc["cost_per_qualified_lead"] is None and loc["ad_spend"]:
            next_steps.append(f"Review {loc['location']} targeting and landing page: spend with no qualified leads this week.")
    next_steps.append("Compare against next week before changing any budget; one week is too little to act on.")

    draft = {
        "summary": f"{payload['client_id']}: {total['qualified_leads']} qualified leads, ${total['ad_spend']} ad spend, "
                   + (f"${total['cost_per_qualified_lead']} per qualified lead " if total["cost_per_qualified_lead"] else "cost per qualified lead not available ")
                   + f"for {payload['reporting_week']['start']} to {payload['reporting_week']['end']}.",
        "observations": observations[:MAX_OBSERVATIONS],
        "next_steps": next_steps[:MAX_NEXT_STEPS],
        "limitations": [
            "One week of synthetic assessment data; no trend or comparison period.",
            "Unknown-qualification leads are excluded from the qualified count until the client confirms them.",
            "Ad spend is per location; organic leads have no spend attached.",
        ],
    }
    return json.dumps(draft, indent=2)


# --------------------------------------------------------------------------- #
# Step 4: check the response before saving it
# --------------------------------------------------------------------------- #

def _strings_in(value) -> list[str]:
    """Every string anywhere inside a parsed JSON value."""
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [s for v in value.values() for s in _strings_in(v)]
    if isinstance(value, list):
        return [s for v in value for s in _strings_in(v)]
    return []


def _numbers_in_payload(payload: dict) -> set[str]:
    """Every number the AI is allowed to quote, normalised like '150' or '112.5'."""
    allowed: set[str] = set()
    for block in payload["locations"] + [payload["total"]]:
        for key in ("qualified_leads", "unknown_qualification", "unqualified", "ad_spend", "cost_per_qualified_lead"):
            if block[key] is not None:
                allowed.add(_norm_number(str(block[key])))
    week = payload["reporting_week"]
    for part in re.findall(r"\d+", week["start"] + week["end"]):
        allowed.add(_norm_number(part))
    return allowed


def _norm_number(text: str) -> str:
    text = text.replace(",", "").lstrip("$")
    try:
        return str(float(text)).rstrip("0").rstrip(".") if "." in text or "e" in text.lower() else str(int(text))
    except ValueError:
        return text


def validate_ai_response(raw_text: str, payload: dict, all_client_ids: list[str]) -> dict:
    """Return {"ok": bool, "errors": [...], "warnings": [...], "draft": parsed or None}."""
    errors: list[str] = []
    warnings: list[str] = []

    text = raw_text.strip()
    if text.startswith("```"):
        # Tolerate a code fence, but say so: the prompt asked for bare JSON.
        text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text)
        warnings.append("response was wrapped in a code fence; stripped")
    try:
        draft = json.loads(text)
    except json.JSONDecodeError as err:
        return {"ok": False, "errors": [f"invalid_json: {err.msg} at position {err.pos}"], "warnings": warnings, "draft": None}

    if not isinstance(draft, dict):
        return {"ok": False, "errors": ["invalid_shape: top level is not an object"], "warnings": warnings, "draft": None}

    missing = REQUIRED_KEYS - set(draft)
    extra = set(draft) - REQUIRED_KEYS
    if missing:
        errors.append(f"invalid_shape: missing keys {sorted(missing)}")
    if extra:
        errors.append(f"invalid_shape: unexpected keys {sorted(extra)}")

    if not isinstance(draft.get("summary"), str) or not draft.get("summary", "").strip():
        errors.append("invalid_shape: summary must be a non-empty string")

    observations = draft.get("observations")
    if not isinstance(observations, list) or not 1 <= len(observations) <= MAX_OBSERVATIONS:
        errors.append(f"invalid_shape: observations must be a list of 1 to {MAX_OBSERVATIONS} items")
        observations = observations if isinstance(observations, list) else []

    allowed_metrics = set(payload["allowed_metrics"])
    allowed_ids = set(payload["allowed_lead_ids"])
    for index, obs in enumerate(observations, start=1):
        if not isinstance(obs, dict) or not isinstance(obs.get("text"), str) or not obs.get("text", "").strip():
            errors.append(f"invalid_shape: observation {index} needs a non-empty text")
            continue
        evidence = obs.get("evidence")
        if not isinstance(evidence, dict):
            errors.append(f"missing_evidence: observation {index} has no evidence object")
            continue
        metrics = evidence.get("metrics", [])
        lead_ids = evidence.get("lead_ids", [])
        if not isinstance(metrics, list) or not isinstance(lead_ids, list):
            errors.append(f"invalid_shape: observation {index} evidence.metrics and evidence.lead_ids must be lists")
            continue
        if not metrics and not lead_ids:
            errors.append(f"missing_evidence: observation {index} names no metric and no lead ID")
        for metric in metrics:
            if metric not in allowed_metrics:
                errors.append(f"unknown_metric: observation {index} cites '{metric}', which is not in this client's payload")
        for lead_id in lead_ids:
            if lead_id not in allowed_ids:
                errors.append(f"unknown_lead_id: observation {index} cites '{lead_id}', which is not one of this client's lead IDs")

    next_steps = draft.get("next_steps")
    if not isinstance(next_steps, list) or not 1 <= len(next_steps) <= MAX_NEXT_STEPS \
            or not all(isinstance(s, str) and s.strip() for s in next_steps):
        errors.append(f"invalid_shape: next_steps must be a list of 1 to {MAX_NEXT_STEPS} non-empty strings")

    limitations = draft.get("limitations")
    if not isinstance(limitations, list) or not limitations or not all(isinstance(s, str) and s.strip() for s in limitations):
        errors.append("invalid_shape: limitations must be a non-empty list of strings")

    # Another client's data anywhere in the response (keys or values).
    all_text = " ".join(_strings_in(draft) + list(draft.keys()))
    for other in all_client_ids:
        if other != payload["client_id"] and re.search(re.escape(other), all_text, re.IGNORECASE):
            errors.append(f"other_client_data: response mentions '{other}' but the selected client is '{payload['client_id']}'")

    # Claims the data cannot support.
    for match in sorted({m.lower() for m in FORBIDDEN_CLAIMS.findall(all_text)}):
        errors.append(f"unsupported_claim: response mentions '{match}', which Part 2 data cannot prove")

    # Numbers that do not come from the payload are flagged (a warning, not a rejection).
    allowed_numbers = _numbers_in_payload(payload)
    quoted = re.findall(r"(?<![A-Za-z0-9_-])\$?\d[\d,]*(?:\.\d+)?", all_text)
    for number in sorted({_norm_number(n) for n in quoted}):
        if number not in allowed_numbers:
            warnings.append(f"unverified_number: '{number}' appears in the text but not in this client's metrics")

    return {"ok": not errors, "errors": errors, "warnings": warnings, "draft": draft if not errors else None}


# --------------------------------------------------------------------------- #
# Step 5: save locally as a draft
# --------------------------------------------------------------------------- #

def render_markdown(record: dict) -> str:
    m = record["metrics"]
    week = m["reporting_week"]
    lines = [
        f"# Weekly update draft: {m['client_id']} ({week['start']} to {week['end']})",
        "",
        f"**Status:** {record['status']}   **Mode:** {record['mode']}   **Human review required:** yes",
        "",
        "## Validated metrics (from Part 2)",
        "",
        "| Location | Qualified | Qualified IDs | Unknown | Unqualified | Spend | Cost / qualified lead |",
        "| --- | ---: | --- | ---: | ---: | ---: | --- |",
    ]
    for block in m["locations"] + [m["total"]]:
        cost = f"${block['cost_per_qualified_lead']}" if block["cost_per_qualified_lead"] else (block["cost_note"] or "not available")
        spend = f"${block['ad_spend']}" if block["ad_spend"] else "-"
        lines.append(
            f"| {block['location']} | {block['qualified_leads']} | {', '.join(block['qualified_lead_ids']) or '-'} | "
            f"{block['unknown_qualification']}{' (' + ', '.join(block['unknown_lead_ids']) + ')' if block['unknown_lead_ids'] else ''} | "
            f"{block['unqualified']} | {spend} | {cost} |"
        )
    lines += ["", "## AI draft", ""]
    draft = record["ai_draft"]
    if draft:
        lines += [f"**Summary.** {draft['summary']}", "", "**Observations**", ""]
        for obs in draft["observations"]:
            ev = obs["evidence"]
            cites = ", ".join(ev.get("metrics", []) + ev.get("lead_ids", []))
            lines.append(f"- {obs['text']}  _(evidence: {cites})_")
        lines += ["", "**Suggested next steps**", ""] + [f"- {s}" for s in draft["next_steps"]]
        lines += ["", "**Limitations**", ""] + [f"- {s}" for s in draft["limitations"]]
    else:
        lines.append(f"_No AI draft saved: {record['status']}._")
    v = record["validation"]
    lines += ["", "## Checks", ""]
    lines += [f"- ERROR: {e}" for e in v["errors"]] or ["- all checks passed"]
    lines += [f"- warning: {w}" for w in v["warnings"]]
    return "\n".join(lines) + "\n"


def save_draft(record: dict, out_dir: Path) -> tuple[Path, Path]:
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = f"{record['metrics']['client_id']}_{record['metrics']['reporting_week']['start']}"
    json_path = out_dir / f"{stem}.json"
    md_path = out_dir / f"{stem}.md"
    json_path.write_text(json.dumps(record, indent=2) + "\n", encoding="utf-8")
    md_path.write_text(render_markdown(record), encoding="utf-8")
    return json_path, md_path


# --------------------------------------------------------------------------- #
# Orchestration
# --------------------------------------------------------------------------- #

def run_update(
    client_id: str,
    mode: str = "auto",
    mock_file: Path | None = None,
    out_dir: Path = DEFAULT_OUT_DIR,
    leads_path: Path = lead_report.DEFAULT_LEADS,
    spend_path: Path = lead_report.DEFAULT_SPEND,
    model: str = DEFAULT_MODEL,
) -> dict:
    """mode: 'auto' (live if ANTHROPIC_API_KEY is set, else mock), 'live', or 'mock'."""
    report = lead_report.run_report(leads_path, spend_path)
    all_client_ids = sorted({r["client_id"] for r in report["results"]})
    payload = build_client_payload(report, client_id)

    if mode == "auto":
        mode = "live" if os.environ.get("ANTHROPIC_API_KEY") else "mock"

    ai_raw: str | None = None
    ai_error: str | None = None
    model_used = "none"
    if mock_file is not None:
        mode_label = f"mock-file:{Path(mock_file).name}"
        ai_raw = Path(mock_file).read_text(encoding="utf-8")
        model_used = "mock"
    elif mode == "mock":
        mode_label = "mock"
        ai_raw = mock_llm_response(payload)
        model_used = "mock"
    else:
        mode_label = "live"
        try:
            ai_raw, model_used = call_anthropic(payload, model=model)
        except AIStepError as err:
            ai_error = str(err)

    if ai_raw is None:
        validation = {"ok": False, "errors": [f"ai_step_failed: {ai_error}"], "warnings": [], "draft": None}
        status = "ai_step_failed_metrics_only"
    else:
        validation = validate_ai_response(ai_raw, payload, all_client_ids)
        status = "draft_pending_review" if validation["ok"] else "rejected_ai_output_metrics_only"

    record = {
        "status": status,
        "human_review_required": True,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "mode": mode_label,
        "model": model_used,
        "metrics": payload,
        "ai_draft": validation["draft"],
        "validation": {"ok": validation["ok"], "errors": validation["errors"], "warnings": validation["warnings"]},
        "ai_raw_response": (ai_raw[:4000] if ai_raw else None),
    }
    json_path, md_path = save_draft(record, Path(out_dir))
    record["saved_to"] = {"json": str(json_path), "markdown": str(md_path)}
    return record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--client", required=True, help="client_id to report on, e.g. client-a")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--mock", action="store_true", help="use the labelled mock response (no network)")
    group.add_argument("--live", action="store_true", help="require the real LLM API (needs ANTHROPIC_API_KEY)")
    group.add_argument("--mock-file", type=Path, help="use this file's contents as the AI response (for demos and tests)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT_DIR, help="folder for saved drafts")
    parser.add_argument("--model", default=DEFAULT_MODEL, help="model id for live mode (or set LLM_MODEL)")
    args = parser.parse_args(argv)

    mode = "live" if args.live else "mock" if args.mock else "auto"
    try:
        record = run_update(args.client, mode=mode, mock_file=args.mock_file, out_dir=args.out, model=args.model)
    except ValueError as err:
        print(f"error: {err}", file=sys.stderr)
        return 1

    if record["mode"].startswith("mock"):
        print("=== MOCK MODE: no LLM API call was made; the AI response below is a labelled stand-in ===")
    print(f"client:  {args.client}")
    print(f"status:  {record['status']}")
    print(f"mode:    {record['mode']}  (model: {record['model']})")
    total = record["metrics"]["total"]
    print(f"metrics: {total['qualified_leads']} qualified, {total['unknown_qualification']} unknown, "
          f"${total['ad_spend']} spend, cost/qualified "
          f"{('$' + total['cost_per_qualified_lead']) if total['cost_per_qualified_lead'] else 'not available'}")
    for err in record["validation"]["errors"]:
        print(f"  REJECTED: {err}")
    for warn in record["validation"]["warnings"]:
        print(f"  warning:  {warn}")
    if record["ai_draft"]:
        print(f"summary: {record['ai_draft']['summary']}")
    print(f"saved:   {record['saved_to']['json']}")
    print(f"         {record['saved_to']['markdown']}")
    return 0 if record["status"] == "draft_pending_review" else 2


if __name__ == "__main__":
    sys.exit(main())
