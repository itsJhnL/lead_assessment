#!/usr/bin/env python3
"""
Part 2 - Weekly qualified lead report.

Reads two CSV files (leads and ad spend) and prints, for each client and
location and for each client total: qualified lead count, qualified lead IDs,
unknown-qualification count, ad spend, and cost per qualified lead.
It also lists every excluded row with the reason it was excluded.

Rules from the assessment, applied in this order to every lead row:

  1. created_at is UTC. Convert it to America/New_York before deciding which
     day the lead belongs to.
  2. Reporting week = 2026-09-01 to 2026-09-07 inclusive, in local time.
  3. Rows flagged "test" or "spam" are left out.
  4. Only kind = "inquiry" counts. Callbacks are not new inquiries.
  5. A lead ID is unique only within its own client. The key is
     (client_id, lead_id); a repeated key is counted once (first row kept).
  6. qualified = true  -> qualified
     qualified = false -> unqualified (a real inquiry, but not qualified)
     qualified blank   -> unknown, reported separately, never counted as either
  7. Cost per qualified lead = ad spend / qualified count.
     If a location has spend but no qualified leads, the cost is "not
     available" with a reason. It is never shown as 0.

Standard library only. Needs Python 3.9+ for zoneinfo.
On Windows, if zoneinfo cannot find America/New_York: pip install tzdata

Usage:
  python lead_report.py                 # human-readable report
  python lead_report.py --json          # same data as JSON (used by Part 4)
  python lead_report.py --week-start 2026-09-01 --tz America/New_York
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from zoneinfo import ZoneInfo

HERE = Path(__file__).resolve().parent
DEFAULT_LEADS = HERE / "data" / "leads.csv"
DEFAULT_SPEND = HERE / "data" / "ad_spend.csv"
DEFAULT_WEEK_START = date(2026, 9, 1)
DEFAULT_TZ = "America/New_York"

EXCLUDED_FLAGS = {"test", "spam"}
COUNTED_KIND = "inquiry"
BLANK_VALUES = {"", "(blank)", "null", "none", "n/a", "na"}

RULES = [
    "created_at is UTC and is converted to America/New_York before the day is decided.",
    "Reporting week is 2026-09-01 to 2026-09-07 inclusive, local time "
    "(UTC 2026-09-01T04:00:00Z up to but not including 2026-09-08T04:00:00Z).",
    "Rows flagged 'test' or 'spam' are excluded.",
    "Only kind = 'inquiry' is counted; callbacks are excluded because they are not new inquiries.",
    "A lead is identified by (client_id, lead_id); a repeated key within the week is counted once "
    "(first row kept). The same lead_id under a different client is a different lead.",
    "qualified = true counts as qualified; false counts as unqualified; "
    "blank is unknown and is reported separately, never counted as qualified or unqualified.",
    "Cost per qualified lead = ad spend / qualified count, rounded half-up to cents. "
    "Spend with zero qualified leads gives 'not available' with a reason, never 0.",
    "Ad spend is taken per client and location from the spend file; client totals sum every "
    "location in the spend file, including locations with no leads.",
]


# --------------------------------------------------------------------------- #
# Parsing helpers
# --------------------------------------------------------------------------- #

def parse_utc(value: str) -> datetime:
    """Parse an ISO-8601 UTC timestamp like 2026-09-02T14:10:00Z into an aware datetime."""
    text = value.strip()
    if text.endswith("Z") or text.endswith("z"):
        text = text[:-1] + "+00:00"
    parsed = datetime.fromisoformat(text)
    if parsed.tzinfo is None:
        raise ValueError(f"created_at has no timezone, refusing to guess: {value!r}")
    return parsed.astimezone(timezone.utc)


def parse_qualified(value: str) -> tuple[bool | None, str | None]:
    """Return (True | False | None, warning). None means unknown."""
    text = (value or "").strip().lower()
    if text == "true":
        return True, None
    if text == "false":
        return False, None
    if text in BLANK_VALUES:
        return None, None
    # Anything else is not a value we know. Treat it as unknown and say so,
    # rather than guessing or crashing the daily run.
    return None, f"unexpected qualified value {value!r} treated as unknown"


def parse_money(value: str) -> Decimal:
    return Decimal(value.strip().replace("$", "").replace(",", ""))


def money(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


# --------------------------------------------------------------------------- #
# Classification: which rows count, which are excluded, and why
# --------------------------------------------------------------------------- #

@dataclass
class Lead:
    row_number: int            # line number in the CSV (header is line 1)
    client_id: str
    lead_id: str
    location: str
    created_utc: datetime
    created_local: datetime
    source: str
    kind: str
    qualified: bool | None     # True / False / None (unknown)
    flag: str


@dataclass
class Classified:
    kept: list[Lead] = field(default_factory=list)
    excluded: list[dict] = field(default_factory=list)   # {row, client_id, lead_id, reason}
    warnings: list[str] = field(default_factory=list)


def classify(rows: list[dict], week_start: date, tz_name: str) -> Classified:
    tz = ZoneInfo(tz_name)
    week_end = week_start + timedelta(days=6)
    out = Classified()
    seen: dict[tuple[str, str], Lead] = {}

    for line_no, raw in enumerate(rows, start=2):
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        created_utc = parse_utc(row["created_at"])
        created_local = created_utc.astimezone(tz)
        qualified, warning = parse_qualified(row.get("qualified", ""))
        lead = Lead(
            row_number=line_no,
            client_id=row["client_id"],
            lead_id=row["lead_id"],
            location=row["location"],
            created_utc=created_utc,
            created_local=created_local,
            source=row.get("source", ""),
            kind=row.get("kind", ""),
            qualified=qualified,
            flag=row.get("flag", "").lower(),
        )

        def exclude(reason: str) -> None:
            out.excluded.append({
                "row": line_no,
                "client_id": lead.client_id,
                "lead_id": lead.lead_id,
                "reason": reason,
            })

        # Rule 3: test / spam
        if lead.flag in EXCLUDED_FLAGS:
            exclude(f"flagged as {lead.flag}")
            continue

        # Rule 4: only inquiries
        if lead.kind.lower() != COUNTED_KIND:
            exclude(f"kind is '{lead.kind}', not a new inquiry")
            continue

        # Rules 1 + 2: local day inside the reporting week
        local_day = created_local.date()
        if not (week_start <= local_day <= week_end):
            exclude(
                f"outside reporting week: {row['created_at']} UTC is "
                f"{created_local:%Y-%m-%d %H:%M} {created_local.tzname()}"
            )
            continue

        # Rule 5: one row per (client_id, lead_id)
        key = (lead.client_id, lead.lead_id)
        if key in seen:
            first = seen[key]
            reason = f"duplicate of row {first.row_number} (same client_id and lead_id)"
            same = (
                first.location == lead.location
                and first.created_utc == lead.created_utc
                and first.source == lead.source
                and first.qualified == lead.qualified
            )
            if not same:
                reason += "; values differ, first row kept"
                out.warnings.append(
                    f"row {line_no}: duplicate key {key} has different values than "
                    f"row {first.row_number}; first row kept, please check the source"
                )
            exclude(reason)
            continue
        seen[key] = lead

        if warning:
            out.warnings.append(f"row {line_no}: {warning}")
        out.kept.append(lead)

    return out


# --------------------------------------------------------------------------- #
# Aggregation
# --------------------------------------------------------------------------- #

def cost_per_qualified_lead(spend: Decimal | None, qualified_count: int) -> tuple[str | None, str | None]:
    """Return (cost as '123.45' or None, note explaining why it is not available)."""
    if spend is None:
        return None, "not available: no ad spend recorded for this location"
    if qualified_count == 0:
        return None, (
            f"not available: ${money(spend)} spend but 0 qualified leads "
            "(cost per lead is undefined, not zero)"
        )
    return money(spend / qualified_count), None


def summarize(client_id: str, location: str, leads: list[Lead], spend: Decimal | None) -> dict:
    qualified_ids = sorted(l.lead_id for l in leads if l.qualified is True)
    unqualified_ids = sorted(l.lead_id for l in leads if l.qualified is False)
    unknown_ids = sorted(l.lead_id for l in leads if l.qualified is None)
    cost, note = cost_per_qualified_lead(spend, len(qualified_ids))
    return {
        "client_id": client_id,
        "location": location,
        "qualified_leads": len(qualified_ids),
        "qualified_lead_ids": qualified_ids,
        "unknown_qualification": len(unknown_ids),
        "unknown_lead_ids": unknown_ids,
        "unqualified": len(unqualified_ids),
        "ad_spend": money(spend),
        "cost_per_qualified_lead": cost,
        "cost_note": note,
    }


def build_results(kept: list[Lead], spend_rows: list[dict]) -> list[dict]:
    spend: dict[tuple[str, str], Decimal] = {}
    for raw in spend_rows:
        row = {(k or "").strip(): (v or "").strip() for k, v in raw.items()}
        key = (row["client_id"], row["location"])
        spend[key] = spend.get(key, Decimal("0")) + parse_money(row["spend"])

    clients = sorted({c for c, _ in spend} | {l.client_id for l in kept})
    results: list[dict] = []
    for client in clients:
        locations = sorted(
            {loc for c, loc in spend if c == client} | {l.location for l in kept if l.client_id == client}
        )
        client_leads = [l for l in kept if l.client_id == client]
        for loc in locations:
            loc_leads = [l for l in client_leads if l.location == loc]
            results.append(summarize(client, loc, loc_leads, spend.get((client, loc))))
        client_spend_values = [v for (c, _), v in spend.items() if c == client]
        total_spend = sum(client_spend_values, Decimal("0")) if client_spend_values else None
        results.append(summarize(client, "TOTAL", client_leads, total_spend))
    return results


# --------------------------------------------------------------------------- #
# Public entry point (also used by weekly_update.py)
# --------------------------------------------------------------------------- #

def read_csv(path: Path) -> list[dict]:
    with open(path, newline="", encoding="utf-8-sig") as handle:
        return list(csv.DictReader(handle))


def run_report(
    leads_path: Path = DEFAULT_LEADS,
    spend_path: Path = DEFAULT_SPEND,
    week_start: date = DEFAULT_WEEK_START,
    tz_name: str = DEFAULT_TZ,
) -> dict:
    lead_rows = read_csv(Path(leads_path))
    spend_rows = read_csv(Path(spend_path))
    classified = classify(lead_rows, week_start, tz_name)
    results = build_results(classified.kept, spend_rows)
    return {
        "reporting_week": {
            "start": week_start.isoformat(),
            "end": (week_start + timedelta(days=6)).isoformat(),
            "timezone": tz_name,
        },
        "input_rows": len(lead_rows),
        "counted_rows": len(classified.kept),
        "results": results,
        "excluded": classified.excluded,
        "warnings": classified.warnings,
        "rules": RULES,
    }


# --------------------------------------------------------------------------- #
# Printing
# --------------------------------------------------------------------------- #

def format_text(report: dict) -> str:
    week = report["reporting_week"]
    lines = [
        f"Weekly qualified lead report: {week['start']} to {week['end']} ({week['timezone']})",
        f"Input rows: {report['input_rows']}   Counted rows: {report['counted_rows']}   "
        f"Excluded rows: {len(report['excluded'])}",
        "",
        f"{'client':<9} {'location':<9} {'qualified':>9}  {'qualified IDs':<24} {'unknown':>7} "
        f"{'unqual.':>7} {'spend':>9}  {'cost / qualified lead'}",
        "-" * 100,
    ]
    for r in report["results"]:
        ids = ", ".join(r["qualified_lead_ids"]) or "-"
        spend = f"${r['ad_spend']}" if r["ad_spend"] is not None else "-"
        cost = f"${r['cost_per_qualified_lead']}" if r["cost_per_qualified_lead"] else r["cost_note"]
        lines.append(
            f"{r['client_id']:<9} {r['location']:<9} {r['qualified_leads']:>9}  {ids:<24} "
            f"{r['unknown_qualification']:>7} {r['unqualified']:>7} {spend:>9}  {cost}"
        )
        if r["unknown_lead_ids"]:
            lines.append(f"{'':<9} {'':<9} {'':>9}  unknown qualification: {', '.join(r['unknown_lead_ids'])}")
    lines += ["", "Excluded rows:"]
    for e in report["excluded"]:
        lines.append(f"  row {e['row']:>2}  {e['client_id']} {e['lead_id']}: {e['reason']}")
    if report["warnings"]:
        lines += ["", "Warnings:"] + [f"  {w}" for w in report["warnings"]]
    lines += ["", "Rules applied:"] + [f"  {i}. {rule}" for i, rule in enumerate(report["rules"], 1)]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--leads", type=Path, default=DEFAULT_LEADS)
    parser.add_argument("--spend", type=Path, default=DEFAULT_SPEND)
    parser.add_argument("--week-start", type=date.fromisoformat, default=DEFAULT_WEEK_START,
                        help="first day of the 7-day reporting week, local time (YYYY-MM-DD)")
    parser.add_argument("--tz", default=DEFAULT_TZ, help="IANA timezone of the reporting week")
    parser.add_argument("--json", action="store_true", help="print JSON instead of text")
    args = parser.parse_args(argv)

    report = run_report(args.leads, args.spend, args.week_start, args.tz)
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(format_text(report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
