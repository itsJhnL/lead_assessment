"""
Tests for Part 2 (lead_report.py), focused on the trickiest rules.

Run:  python -m unittest -v test_lead_report
  or: python -m pytest -q test_lead_report.py
"""

import unittest
from datetime import date

import lead_report as lr

WEEK = date(2026, 9, 1)
TZ = "America/New_York"


def lead(client="client-a", lead_id="L100", location="north", created="2026-09-03T12:00:00Z",
         source="google_ads", kind="inquiry", qualified="true", flag=""):
    """One CSV row as csv.DictReader would give it."""
    return {
        "client_id": client, "lead_id": lead_id, "location": location, "created_at": created,
        "source": source, "kind": kind, "qualified": qualified, "flag": flag,
    }


def spend(client, location, amount):
    return {"client_id": client, "location": location, "spend": amount}


def result_for(results, client, location):
    return next(r for r in results if r["client_id"] == client and r["location"] == location)


class TimezoneBoundary(unittest.TestCase):
    """Rule: created_at is UTC; the day is decided in America/New_York (UTC-4 in September)."""

    def test_utc_sep_1_00_30_is_still_aug_31_in_new_york_and_is_excluded(self):
        out = lr.classify([lead(lead_id="L007", created="2026-09-01T00:30:00Z")], WEEK, TZ)
        self.assertEqual(out.kept, [])
        self.assertIn("outside reporting week", out.excluded[0]["reason"])
        self.assertIn("2026-08-31 20:30", out.excluded[0]["reason"])

    def test_utc_sep_8_02_00_is_still_sep_7_in_new_york_and_is_included(self):
        out = lr.classify([lead(lead_id="L011", created="2026-09-08T02:00:00Z")], WEEK, TZ)
        self.assertEqual([l.lead_id for l in out.kept], ["L011"])
        self.assertEqual(out.kept[0].created_local.date(), date(2026, 9, 7))

    def test_exact_window_edges(self):
        rows = [
            lead(lead_id="first", created="2026-09-01T04:00:00Z"),   # 00:00 local on Sep 1 -> in
            lead(lead_id="before", created="2026-09-01T03:59:59Z"),  # 23:59:59 local on Aug 31 -> out
            lead(lead_id="last", created="2026-09-08T03:59:59Z"),    # 23:59:59 local on Sep 7 -> in
            lead(lead_id="after", created="2026-09-08T04:00:00Z"),   # 00:00 local on Sep 8 -> out
        ]
        out = lr.classify(rows, WEEK, TZ)
        self.assertEqual(sorted(l.lead_id for l in out.kept), ["first", "last"])
        self.assertEqual(sorted(e["lead_id"] for e in out.excluded), ["after", "before"])


class LeadIdentity(unittest.TestCase):
    """Rule: a lead ID is only unique within its client; repeated rows count once."""

    def test_same_lead_id_under_two_clients_is_two_leads(self):
        rows = [lead(client="client-a", lead_id="L001"), lead(client="client-b", lead_id="L001")]
        out = lr.classify(rows, WEEK, TZ)
        self.assertEqual(len(out.kept), 2)
        self.assertEqual(out.excluded, [])

    def test_exact_duplicate_row_is_counted_once(self):
        rows = [lead(lead_id="L001"), lead(lead_id="L001")]
        out = lr.classify(rows, WEEK, TZ)
        self.assertEqual(len(out.kept), 1)
        self.assertEqual(len(out.excluded), 1)
        self.assertIn("duplicate of row 2", out.excluded[0]["reason"])
        self.assertEqual(out.warnings, [])

    def test_duplicate_with_different_values_is_dropped_with_a_warning(self):
        rows = [lead(lead_id="L001", qualified="true"), lead(lead_id="L001", qualified="false")]
        out = lr.classify(rows, WEEK, TZ)
        self.assertEqual(len(out.kept), 1)
        self.assertIs(out.kept[0].qualified, True)   # first row wins
        self.assertEqual(len(out.warnings), 1)
        self.assertIn("values differ", out.excluded[0]["reason"])


class Exclusions(unittest.TestCase):
    """Rule: test and spam rows are left out; callbacks are not new inquiries."""

    def test_test_spam_and_callback_rows_are_excluded_with_reasons(self):
        rows = [
            lead(lead_id="T", flag="test"),
            lead(lead_id="S", flag="spam"),
            lead(lead_id="C", kind="callback"),
            lead(lead_id="OK"),
        ]
        out = lr.classify(rows, WEEK, TZ)
        self.assertEqual([l.lead_id for l in out.kept], ["OK"])
        reasons = {e["lead_id"]: e["reason"] for e in out.excluded}
        self.assertEqual(reasons["T"], "flagged as test")
        self.assertEqual(reasons["S"], "flagged as spam")
        self.assertIn("callback", reasons["C"])


class UnknownQualification(unittest.TestCase):
    """Rule: blank qualified is unknown, reported separately, counted as neither."""

    def test_blank_is_unknown_not_qualified_not_unqualified(self):
        rows = [lead(lead_id="Q", qualified="true"), lead(lead_id="U", qualified=""),
                lead(lead_id="N", qualified="false")]
        out = lr.classify(rows, WEEK, TZ)
        results = lr.build_results(out.kept, [spend("client-a", "north", "100.00")])
        north = result_for(results, "client-a", "north")
        self.assertEqual(north["qualified_leads"], 1)
        self.assertEqual(north["qualified_lead_ids"], ["Q"])
        self.assertEqual(north["unknown_qualification"], 1)
        self.assertEqual(north["unknown_lead_ids"], ["U"])
        self.assertEqual(north["unqualified"], 1)
        # cost uses only the qualified count: 100 / 1, not 100 / 2 or 100 / 3
        self.assertEqual(north["cost_per_qualified_lead"], "100.00")

    def test_unexpected_value_is_unknown_with_a_warning(self):
        out = lr.classify([lead(lead_id="X", qualified="maybe")], WEEK, TZ)
        self.assertIsNone(out.kept[0].qualified)
        self.assertEqual(len(out.warnings), 1)


class CostPerQualifiedLead(unittest.TestCase):
    """Rule: spend with no qualified leads is 'not available', never 0."""

    def test_spend_but_no_qualified_leads_is_not_available(self):
        results = lr.build_results([], [spend("client-b", "south", "200.00")])
        south = result_for(results, "client-b", "south")
        self.assertEqual(south["ad_spend"], "200.00")
        self.assertIsNone(south["cost_per_qualified_lead"])
        self.assertIn("not available", south["cost_note"])
        self.assertIn("0 qualified leads", south["cost_note"])

    def test_cost_rounds_half_up_to_cents(self):
        self.assertEqual(lr.cost_per_qualified_lead(lr.Decimal("100.00"), 3), ("33.33", None))
        self.assertEqual(lr.cost_per_qualified_lead(lr.Decimal("100.00"), 8), ("12.50", None))
        self.assertEqual(lr.cost_per_qualified_lead(lr.Decimal("0.05"), 2), ("0.03", None))

    def test_location_with_leads_but_no_spend_row_is_not_available(self):
        out = lr.classify([lead(lead_id="W", location="west")], WEEK, TZ)
        results = lr.build_results(out.kept, [spend("client-a", "north", "10.00")])
        west = result_for(results, "client-a", "west")
        self.assertEqual(west["qualified_leads"], 1)
        self.assertIsNone(west["ad_spend"])
        self.assertIn("no ad spend recorded", west["cost_note"])


class AssessmentData(unittest.TestCase):
    """End-to-end check against the numbers worked out by hand from the PDF table."""

    def setUp(self):
        self.report = lr.run_report()
        self.results = self.report["results"]

    def test_client_a(self):
        north = result_for(self.results, "client-a", "north")
        south = result_for(self.results, "client-a", "south")
        total = result_for(self.results, "client-a", "TOTAL")
        self.assertEqual((north["qualified_leads"], north["qualified_lead_ids"]), (2, ["L001", "L002"]))
        self.assertEqual((north["ad_spend"], north["cost_per_qualified_lead"]), ("300.00", "150.00"))
        self.assertEqual((south["qualified_leads"], south["qualified_lead_ids"]), (2, ["L008", "L011"]))
        self.assertEqual((south["unknown_qualification"], south["unknown_lead_ids"]), (1, ["L009"]))
        self.assertEqual((south["ad_spend"], south["cost_per_qualified_lead"]), ("150.00", "75.00"))
        self.assertEqual(total["qualified_leads"], 4)
        self.assertEqual(total["qualified_lead_ids"], ["L001", "L002", "L008", "L011"])
        self.assertEqual(total["unknown_qualification"], 1)
        self.assertEqual((total["ad_spend"], total["cost_per_qualified_lead"]), ("450.00", "112.50"))

    def test_client_b(self):
        north = result_for(self.results, "client-b", "north")
        south = result_for(self.results, "client-b", "south")
        total = result_for(self.results, "client-b", "TOTAL")
        self.assertEqual((north["qualified_leads"], north["qualified_lead_ids"]), (2, ["L001", "L003"]))
        self.assertEqual((north["ad_spend"], north["cost_per_qualified_lead"]), ("500.00", "250.00"))
        self.assertEqual(south["qualified_leads"], 0)
        self.assertEqual(south["ad_spend"], "200.00")
        self.assertIsNone(south["cost_per_qualified_lead"])
        self.assertEqual(total["qualified_leads"], 2)
        self.assertEqual((total["ad_spend"], total["cost_per_qualified_lead"]), ("700.00", "350.00"))

    def test_exactly_seven_rows_are_excluded_for_the_right_reasons(self):
        excluded = {(e["client_id"], e["lead_id"], e["row"]): e["reason"] for e in self.report["excluded"]}
        self.assertEqual(len(excluded), 7)
        self.assertIn("duplicate", excluded[("client-a", "L001", 3)])
        self.assertEqual(excluded[("client-a", "L003", 5)], "flagged as test")
        self.assertEqual(excluded[("client-a", "L004", 6)], "flagged as spam")
        self.assertIn("callback", excluded[("client-a", "L005", 7)])
        self.assertIn("outside reporting week", excluded[("client-a", "L007", 9)])
        self.assertIn("duplicate", excluded[("client-b", "L003", 16)])
        self.assertEqual(excluded[("client-b", "L004", 17)], "flagged as test")
        self.assertEqual(self.report["warnings"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
