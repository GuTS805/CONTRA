import asyncio
from copy import deepcopy
import sqlite3
import unittest
from unittest.mock import patch

from contra import flows
from contra.core import analyze, digest, prepare
from contra.fixtures import AS_OF
from contra.store import baseline_profiles, verify_run, RunIntegrityError


class FlowTests(unittest.TestCase):
    def record(self):
        return flows.parse([
            {"category": "FII/FPI", "date": "14-Oct-2026", "buyValue": "16,381.85", "sellValue": "18239.29", "netValue": "-1857.44"},
            {"category": "DII", "date": "14-Oct-2026", "buyValue": "17428.61", "sellValue": "14758.17", "netValue": "2670.44"},
        ], "2026-10-15T02:00:00+00:00")

    def test_divergence_not_hidden_by_positive_combined_net(self):
        record = self.record()
        result = flows.signal({"institutional_flows": [record], "as_of": "2026-10-14"})
        self.assertEqual(result["label"], "DIVERGENT")
        self.assertEqual(result["value"], 813)
        self.assertEqual(result["evidence_ids"], [record["id"]])

    def test_invalid_provider_rows_are_rejected(self):
        rows = self.record()["raw_rows"]
        for field, value in (("buyValue", "NaN"), ("netValue", "100"), ("buyValue", "-1"),
                             ("date", "15-Oct-2026"), ("category", "FII/FPI")):
            with self.subTest(field=field, value=value):
                bad = deepcopy(rows)
                bad[1][field] = value
                with self.assertRaises(ValueError):
                    flows.parse(bad, "2026-10-15T02:00:00+00:00")
        for bad in (rows[:1], [None, {}], rows + rows, {}):
            with self.assertRaises(ValueError):
                flows.parse(bad)

    def test_missing_stale_and_future_abstain(self):
        record = self.record()
        for rows, day in (([], "2026-10-14"), ([record], "2026-10-19"), ([record], "2026-10-13")):
            result = flows.signal({"institutional_flows": rows, "as_of": day})
            self.assertEqual(result["status"], "UNAVAILABLE")
            self.assertIsNone(result["value"])
        self.assertEqual(flows.signal({"institutional_flows": [record], "as_of": "2026-10-18"})["status"], "OK")

    def test_context_is_frozen_and_tamper_evident(self):
        snapshot = prepare("ALPHA.NS", AS_OF)
        self.assertEqual(snapshot["institutional_flows"][0]["mode"], "SYNTHETIC")
        report = asyncio.run(analyze("ALPHA.NS", baseline_profiles()[0], snapshot=snapshot, allow_llm=False))
        verify_run(report)
        self.assertEqual(len(report["signals"]), 4)
        report["market_snapshot"]["institutional_flows"][0]["groups"]["DII"]["net"] += 1
        report["report_hash"] = digest({k: v for k, v in report.items() if k != "report_hash"})
        with self.assertRaises(RunIntegrityError):
            verify_run(report)

    def test_no_live_synthetic_mixing(self):
        record = self.record()
        with self.assertRaises(ValueError):
            prepare("ALPHA.NS", AS_OF, institutional_flows=[record])
        bad = deepcopy(flows.fixture(AS_OF)[0])
        bad["groups"]["DII"]["net"] = 999
        with self.assertRaises(ValueError):
            prepare("ALPHA.NS", AS_OF, institutional_flows=[bad])

    def test_cache_outage_and_asof(self):
        db = sqlite3.connect(":memory:")
        self.addCleanup(db.close)
        flows._last_attempt.clear()
        with patch.object(flows, "fetch", return_value=self.record()) as fetch:
            rows, warnings = flows.history(db, "2026-10-14")
            self.assertEqual(len(rows), 1)
            self.assertEqual(warnings, [])
            self.assertEqual(flows.history(db, "2026-10-13")[0], [])
            self.assertEqual(fetch.call_count, 1)
        flows._last_attempt.clear()
        with patch.object(flows, "fetch", side_effect=OSError("offline")):
            rows, warnings = flows.history(db, "2026-10-14")
        self.assertEqual(rows[0], self.record())
        self.assertTrue(warnings)

    def test_context_does_not_override_risk_action(self):
        person = baseline_profiles()[0]
        with_flows = asyncio.run(analyze("ALPHA.NS", person, allow_llm=False))
        without = asyncio.run(analyze("ALPHA.NS", person, allow_llm=False,
                                     snapshot=prepare("ALPHA.NS", AS_OF, institutional_flows=[])))
        self.assertEqual(with_flows["recommendation"]["action"], without["recommendation"]["action"])
        self.assertNotEqual(with_flows["market_snapshot_hash"], without["market_snapshot_hash"])


if __name__ == "__main__":
    unittest.main()
