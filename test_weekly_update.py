"""
Tests for Part 4 (weekly_update.py).

Covers: a normal run, bad AI responses being rejected, and that switching
clients does not mix their data. All tests run in mock mode (no network).

Run:  python -m unittest -v test_weekly_update
  or: python -m pytest -q test_weekly_update.py
"""

import json
import os
import tempfile
import unittest
from pathlib import Path

import lead_report
import weekly_update as wu

HERE = Path(__file__).resolve().parent
MOCKS = HERE / "mock_responses"


def good_response(payload):
    """A minimal valid response for whichever client payload is passed in."""
    total = payload["total"]
    return json.dumps({
        "summary": f"{total['qualified_leads']} qualified leads on ${total['ad_spend']}.",
        "observations": [{
            "text": f"{total['qualified_leads']} qualified leads this week.",
            "evidence": {"metrics": ["total.qualified_leads"], "lead_ids": total["qualified_lead_ids"]},
        }],
        "next_steps": ["Review again next week."],
        "limitations": ["One week of data."],
    })


class NormalRun(unittest.TestCase):

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name)
        # Make sure a key in the environment cannot turn these tests into live calls.
        self.saved_key = os.environ.pop("ANTHROPIC_API_KEY", None)

    def tearDown(self):
        if self.saved_key is not None:
            os.environ["ANTHROPIC_API_KEY"] = self.saved_key
        self.tmp.cleanup()

    def test_mock_run_saves_a_draft_pending_review_with_part_2_numbers(self):
        record = wu.run_update("client-a", mode="mock", out_dir=self.out)
        self.assertEqual(record["status"], "draft_pending_review")
        self.assertTrue(record["human_review_required"])
        self.assertEqual(record["mode"], "mock")
        total = record["metrics"]["total"]
        self.assertEqual(total["qualified_leads"], 4)
        self.assertEqual(total["qualified_lead_ids"], ["L001", "L002", "L008", "L011"])
        self.assertEqual(total["unknown_qualification"], 1)
        self.assertEqual(total["unknown_lead_ids"], ["L009"])
        self.assertEqual(total["cost_per_qualified_lead"], "112.50")
        # the draft respects the limits and every observation carries evidence
        draft = record["ai_draft"]
        self.assertTrue(1 <= len(draft["observations"]) <= 3)
        self.assertTrue(1 <= len(draft["next_steps"]) <= 3)
        for obs in draft["observations"]:
            self.assertTrue(obs["evidence"]["metrics"] or obs["evidence"]["lead_ids"])
        # saved to disk, both formats
        saved = json.loads((self.out / "client-a_2026-09-01.json").read_text())
        self.assertEqual(saved["status"], "draft_pending_review")
        self.assertTrue((self.out / "client-a_2026-09-01.md").exists())

    def test_auto_mode_falls_back_to_mock_without_a_key(self):
        record = wu.run_update("client-b", mode="auto", out_dir=self.out)
        self.assertEqual(record["mode"], "mock")
        self.assertEqual(record["status"], "draft_pending_review")

    def test_live_mode_without_a_key_fails_safely_and_still_saves_metrics(self):
        record = wu.run_update("client-a", mode="live", out_dir=self.out)
        self.assertEqual(record["status"], "ai_step_failed_metrics_only")
        self.assertIsNone(record["ai_draft"])
        self.assertTrue(record["validation"]["errors"][0].startswith("ai_step_failed"))
        self.assertEqual(record["metrics"]["total"]["qualified_leads"], 4)
        self.assertTrue((self.out / "client-a_2026-09-01.json").exists())

    def test_unknown_client_is_refused(self):
        with self.assertRaises(ValueError):
            wu.run_update("client-z", mode="mock", out_dir=self.out)


class UnknownKeptSeparate(unittest.TestCase):

    def test_payload_separates_unknown_from_qualified(self):
        report = lead_report.run_report()
        payload = wu.build_client_payload(report, "client-a")
        south = next(l for l in payload["locations"] if l["location"] == "south")
        self.assertEqual(south["qualified_lead_ids"], ["L008", "L011"])
        self.assertEqual(south["unknown_lead_ids"], ["L009"])
        self.assertNotIn("L009", payload["total"]["qualified_lead_ids"])
        self.assertIn("L009", payload["allowed_lead_ids"])   # can be cited, as an unknown
        self.assertIn("total.unknown_qualification", payload["allowed_metrics"])


class BadAIResponses(unittest.TestCase):

    def setUp(self):
        self.report = lead_report.run_report()
        self.clients = sorted({r["client_id"] for r in self.report["results"]})
        self.payload = wu.build_client_payload(self.report, "client-a")

    def check(self, raw):
        return wu.validate_ai_response(raw, self.payload, self.clients)

    def test_good_response_passes(self):
        result = self.check(good_response(self.payload))
        self.assertTrue(result["ok"], result["errors"])
        self.assertIsNotNone(result["draft"])

    def test_not_json_is_rejected(self):
        result = self.check((MOCKS / "bad_not_json.txt").read_text())
        self.assertFalse(result["ok"])
        self.assertTrue(result["errors"][0].startswith("invalid_json"))

    def test_wrong_shape_is_rejected(self):
        result = self.check((MOCKS / "bad_wrong_shape.json").read_text())
        self.assertFalse(result["ok"])
        codes = {e.split(":")[0] for e in result["errors"]}
        self.assertEqual(codes, {"invalid_shape"})
        self.assertTrue(any("missing keys ['limitations']" in e for e in result["errors"]))

    def test_missing_evidence_and_unknown_citations_are_rejected(self):
        result = self.check((MOCKS / "bad_missing_evidence.json").read_text())
        self.assertFalse(result["ok"])
        codes = {e.split(":")[0] for e in result["errors"]}
        self.assertEqual(codes, {"missing_evidence", "unknown_metric", "unknown_lead_id"})

    def test_revenue_bookings_roas_claims_are_rejected(self):
        result = self.check((MOCKS / "bad_revenue_claim.json").read_text())
        self.assertFalse(result["ok"])
        joined = " ".join(result["errors"])
        for word in ("revenue", "bookings", "return on ad spend"):
            self.assertIn(word, joined)

    def test_other_clients_data_is_rejected(self):
        result = self.check((MOCKS / "bad_cross_client.json").read_text())
        self.assertFalse(result["ok"])
        self.assertTrue(any(e.startswith("other_client_data") for e in result["errors"]))
        # L003 is a client-b lead; for client-a it was flagged test and never qualified
        self.assertTrue(any("unknown_lead_id" in e and "L003" in e for e in result["errors"]))

    def test_numbers_not_in_the_data_are_flagged(self):
        raw = json.loads(good_response(self.payload))
        raw["observations"][0]["text"] = "4 qualified leads, up 37% on last week."
        result = self.check(json.dumps(raw))
        self.assertTrue(result["ok"])   # a warning, not a rejection
        self.assertTrue(any("unverified_number: '37'" in w for w in result["warnings"]))

    def test_too_many_observations_is_rejected(self):
        raw = json.loads(good_response(self.payload))
        raw["observations"] = raw["observations"] * 4
        result = self.check(json.dumps(raw))
        self.assertFalse(result["ok"])

    def test_rejected_response_still_saves_metrics(self):
        with tempfile.TemporaryDirectory() as tmp:
            record = wu.run_update("client-a", mock_file=MOCKS / "bad_revenue_claim.json", out_dir=Path(tmp))
            self.assertEqual(record["status"], "rejected_ai_output_metrics_only")
            self.assertIsNone(record["ai_draft"])
            self.assertEqual(record["metrics"]["total"]["cost_per_qualified_lead"], "112.50")
            saved = json.loads((Path(tmp) / "client-a_2026-09-01.json").read_text())
            self.assertEqual(saved["metrics"]["total"]["qualified_leads"], 4)


class SwitchingClients(unittest.TestCase):

    def setUp(self):
        self.report = lead_report.run_report()
        self.clients = sorted({r["client_id"] for r in self.report["results"]})

    def test_each_payload_holds_only_its_own_client(self):
        a = wu.build_client_payload(self.report, "client-a")
        b = wu.build_client_payload(self.report, "client-b")
        self.assertEqual(a["allowed_lead_ids"], ["L001", "L002", "L008", "L009", "L011"])
        self.assertEqual(b["allowed_lead_ids"], ["L001", "L003"])
        self.assertNotIn("client-b", json.dumps(a))
        self.assertNotIn("client-a", json.dumps(b))
        self.assertEqual(a["total"]["ad_spend"], "450.00")
        self.assertEqual(b["total"]["ad_spend"], "700.00")
        # client-b south: spend, no leads, cost not available
        b_south = next(l for l in b["locations"] if l["location"] == "south")
        self.assertIsNone(b_south["cost_per_qualified_lead"])
        self.assertIn("not available", b_south["cost_note"])

    def test_same_lead_id_is_valid_evidence_for_each_client_separately(self):
        # L001 exists under both clients and is a legitimate citation for either.
        for client in ("client-a", "client-b"):
            payload = wu.build_client_payload(self.report, client)
            self.assertIn("L001", payload["allowed_lead_ids"])
        # L002 is qualified for client-a but unqualified (not citable) for client-b.
        b = wu.build_client_payload(self.report, "client-b")
        result = wu.validate_ai_response(
            json.dumps({
                "summary": "ok", "observations": [{"text": "x", "evidence": {"metrics": [], "lead_ids": ["L002"]}}],
                "next_steps": ["ok"], "limitations": ["ok"],
            }), b, self.clients)
        self.assertFalse(result["ok"])
        self.assertTrue(any("unknown_lead_id" in e for e in result["errors"]))

    def test_running_both_clients_back_to_back_keeps_drafts_apart(self):
        with tempfile.TemporaryDirectory() as tmp:
            a = wu.run_update("client-a", mode="mock", out_dir=Path(tmp))
            b = wu.run_update("client-b", mode="mock", out_dir=Path(tmp))
            self.assertNotEqual(a["saved_to"]["json"], b["saved_to"]["json"])
            a_text = Path(a["saved_to"]["json"]).read_text()
            b_text = Path(b["saved_to"]["json"]).read_text()
            self.assertNotIn("client-b", a_text)
            self.assertNotIn("client-a", b_text)
            self.assertNotIn("L008", b_text)      # client-a-only lead never reaches the client-b draft
            self.assertEqual(b["metrics"]["total"]["qualified_leads"], 2)
            self.assertEqual(a["metrics"]["total"]["qualified_leads"], 4)


if __name__ == "__main__":
    unittest.main(verbosity=2)
