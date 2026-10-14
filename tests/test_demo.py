import asyncio
from copy import deepcopy
from datetime import date
import tempfile
import unittest
from unittest.mock import patch

from contra.core import analyze, prepare, numeric_signals, retrieve
from contra.evaluation import scenario_matrix
from contra.fixtures import AS_OF, documents
from contra.store import RunIntegrityError, connect, profile, save_run, run, update_profile, verify_run


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.db = connect(self.tmp.name + "/demo.sqlite3")

    def tearDown(self):
        self.db.close()
        self.tmp.cleanup()

    def analyze(self, ticker, investor="demo_conservative", as_of=AS_OF):
        return asyncio.run(analyze(ticker, profile(self.db, investor), as_of))

    def test_conflict_source_integrity_and_parallel_trace(self):
        report = self.analyze("ALPHA.NS")
        self.assertEqual(report["synthesis"]["state"], "CONFLICTED")
        self.assertTrue(report["synthesis"]["market_research_disagreement"])
        self.assertTrue(report["synthesis"]["suitability_breach"])
        self.assertIn("At least one cited filing is over 120 days old", report["agents"]["research"]["warnings"])
        self.assertTrue(report["metrics"]["agent_overlap"])
        self.assertTrue(all(a["execution_mode"] == "DETERMINISTIC_FALLBACK" for a in report["agents"].values()))
        sources = {d["id"]: d for d in report["evidence"]}
        self.assertTrue(sources)
        for fact in report["agents"]["research"]["facts"]:
            self.assertEqual(fact["value"], sources[fact["source_ids"][0]]["excerpt"])
        self.assertEqual(report["metrics"]["citation_validity"], 1.0)

    def test_profile_swap_preserves_market_facts(self):
        a = self.analyze("ALPHA.NS")
        b = self.analyze("ALPHA.NS", "demo_growth")
        self.assertEqual(a["market_snapshot_hash"], b["market_snapshot_hash"])
        self.assertEqual(a["signals"], b["signals"])
        self.assertNotEqual(a["run_context_hash"], b["run_context_hash"])
        self.assertTrue(a["synthesis"]["suitability_breach"])
        self.assertFalse(b["synthesis"]["suitability_breach"])

    def test_missing_and_future_filings_are_excluded(self):
        report = self.analyze("DELTA.NS")
        self.assertEqual(report["synthesis"]["state"], "PARTIAL")
        self.assertEqual(report["agents"]["research"]["status"], "UNAVAILABLE")
        self.assertEqual(report["evidence"], [])
        self.assertIsNone(report["metrics"]["citation_validity"])
        future = [d for d in documents() if d["ticker"] == "DELTA.NS"]
        self.assertTrue(all(date.fromisoformat(d["published_at"]) > date.fromisoformat(AS_OF) for d in future))

    def test_short_history_abstains_without_nan(self):
        snapshot = prepare("ALPHA.NS", "2026-06-12")
        signals = numeric_signals(snapshot)
        self.assertEqual(signals["momentum"]["status"], "UNAVAILABLE")
        self.assertIsNone(signals["momentum"]["value"])
        short_report = self.analyze("ALPHA.NS", as_of="2026-06-12")
        self.assertEqual(short_report["synthesis"]["state"], "INSUFFICIENT_EVIDENCE")
        full = prepare("ALPHA.NS", AS_OF)
        full["bars"][-1]["volume"] = float("nan")
        self.assertEqual(numeric_signals(full)["volume"]["status"], "UNAVAILABLE")
        full["bars"][-1]["volume"] = 0
        self.assertEqual(numeric_signals(full)["momentum"]["status"], "UNAVAILABLE")

    def test_saved_run_and_profile_revision(self):
        report = self.analyze("GAMMA.NS")
        self.assertEqual(report["synthesis"]["state"], "ALIGNED")
        save_run(self.db, report)
        self.assertEqual(run(self.db, report["run_id"]), report)
        original = profile(self.db, "demo_conservative")
        updated = update_profile(self.db, "demo_conservative", {"max_single_asset_weight": .20})
        self.assertEqual(updated["revision"], original["revision"] + 1)
        self.assertEqual(profile(self.db, "demo_growth")["max_single_asset_weight"], .30)
        with self.assertRaises(ValueError):
            update_profile(self.db, "demo_growth", {"positions": [{"ticker": "ALPHA.NS", "value": 1},
                                                               {"ticker": "ALPHA.NS", "value": 2}]})

    def test_frozen_snapshot_and_retrieval_cutoff(self):
        report = self.analyze("ALPHA.NS")
        self.assertGreaterEqual(len(report["market_snapshot"]["bars"]), 21)
        self.assertEqual(report["market_snapshot"]["bars"][0]["timezone"], "Asia/Kolkata")
        self.assertFalse(report["market_snapshot"]["bars"][0]["adjusted"])
        self.assertEqual(report["investor_snapshot"]["id"], "demo_conservative")
        self.assertEqual(report["method_version"], "rules-1.1")
        self.assertEqual(report["market_snapshot"]["document_ids"],
                         [d["id"] for d in documents() if d["ticker"] == "ALPHA.NS" and d["published_at"] <= AS_OF])
        self.assertEqual(len(report["market_snapshot"]["documents"]), len(report["market_snapshot"]["document_ids"]))
        chunks = retrieve(prepare("ALPHA.NS", AS_OF))
        self.assertLessEqual(len(chunks), 3)
        self.assertTrue(all(0 < d["retrieval_score"] <= 1 for d in chunks))
        self.assertEqual(retrieve(prepare("DELTA.NS", AS_OF)), [])

    def test_tampered_document_is_rejected_before_analysis(self):
        fixtures = documents()
        fixtures[0]["excerpt"] = "A changed claim with an old source hash."
        with patch("contra.core.documents", return_value=fixtures):
            with self.assertRaisesRegex(ValueError, "integrity"):
                prepare("ALPHA.NS", AS_OF)

    def test_measured_scenario_matrix(self):
        matrix = asyncio.run(scenario_matrix(profile(self.db, "demo_conservative"), profile(self.db, "demo_growth")))
        self.assertEqual(matrix["passed"], matrix["total"])
        self.assertEqual(matrix["citation_fabrication_count"], 0)
        self.assertEqual(matrix["retrieval_recall_at_3"], 1.0)

    def test_sector_limit_changes_suitability(self):
        update_profile(self.db, "demo_growth", {"max_sector_weight": .04})
        report = self.analyze("GAMMA.NS", "demo_growth")
        self.assertEqual(report["signals"]["momentum"]["label"], "BULLISH")
        self.assertEqual(report["signals"]["filing_tone"]["label"], "POSITIVE")
        self.assertEqual(report["synthesis"]["state"], "CAUTION")
        self.assertTrue(report["agents"]["risk"]["sector_breach"])
        self.assertFalse(report["agents"]["risk"]["single_asset_breach"])
        alpha = self.analyze("ALPHA.NS", "demo_conservative")
        self.assertEqual(alpha["agents"]["risk"]["sector_weight"], .4)

    def test_mixed_filing_evidence_is_not_called_aligned(self):
        report = self.analyze("BETA.NS", "demo_growth")
        self.assertEqual(report["signals"]["filing_tone"]["label"], "MIXED")
        self.assertFalse(report["synthesis"]["suitability_breach"])
        self.assertEqual(report["synthesis"]["state"], "CAUTION")

    def test_one_agent_error_keeps_partial_report(self):
        with patch("contra.core.market_agent", side_effect=RuntimeError("fixture agent failure")):
            report = self.analyze("GAMMA.NS")
        self.assertEqual(report["agents"]["market"]["status"], "ERROR")
        self.assertEqual(report["agents"]["research"]["status"], "OK")
        self.assertEqual(report["synthesis"]["state"], "PARTIAL")
        self.assertEqual(report["status"], "PARTIAL")
        save_run(self.db, report)
        self.assertEqual(run(self.db, report["run_id"]), report)

    def test_invalid_agent_contract_is_typed_error(self):
        with patch("contra.core.market_agent", return_value={"status": "OK"}):
            report = self.analyze("GAMMA.NS")
        self.assertEqual(report["agents"]["market"]["status"], "ERROR")
        self.assertEqual(report["synthesis"]["state"], "PARTIAL")

    def test_fabricated_research_citation_is_removed_and_report_is_partial(self):
        from contra.core import research_agent as real_research_agent
        def invalid_research(signal, chunks):
            result = real_research_agent(signal, chunks)
            result["facts"].append({"key": "invented", "value": "Unsupported claim", "source_ids": ["E-FAKE"]})
            result["evidence_ids"].append("E-FAKE")
            return result
        with patch("contra.core.research_agent", side_effect=invalid_research):
            report = self.analyze("ALPHA.NS")
        self.assertEqual(report["agents"]["research"]["status"], "PARTIAL")
        self.assertEqual(report["synthesis"]["state"], "PARTIAL")
        self.assertEqual(report["metrics"]["citation_fabrication_count"], 1)
        self.assertLess(report["metrics"]["citation_validity"], 1)
        self.assertNotIn("E-FAKE", report["agents"]["research"]["evidence_ids"])
        self.assertTrue(all("E-FAKE" not in fact["source_ids"] for fact in report["agents"]["research"]["facts"]))

    def test_valid_market_bar_cannot_be_used_as_research_citation(self):
        from contra.core import research_agent as real_research_agent
        from contra.fixtures import bars_for
        bar_id = bars_for("ALPHA.NS")[-1]["id"]
        def invalid_research(signal, chunks):
            result = real_research_agent(signal, chunks)
            result["facts"].append({"key": "misattributed", "value": "A bar is not a filing", "source_ids": [bar_id]})
            result["evidence_ids"].append(bar_id)
            return result
        with patch("contra.core.research_agent", side_effect=invalid_research), \
             patch("contra.core.llm.configured", return_value=True), \
             patch("contra.core.llm.reason", return_value={"model_version": "mock"}) as model_reason:
            report = self.analyze("ALPHA.NS")
        research = report["agents"]["research"]
        self.assertEqual(research["status"], "PARTIAL")
        self.assertEqual(research["execution_mode"], "DETERMINISTIC_FALLBACK")
        self.assertNotIn(bar_id, research["evidence_ids"])
        self.assertTrue(all(bar_id not in fact["source_ids"] for fact in research["facts"]))
        self.assertEqual(report["metrics"]["citation_fabrication_count"], 1)
        self.assertNotIn("RESEARCH", [call.args[0] for call in model_reason.call_args_list])

    def test_unrelated_frozen_bar_cannot_support_market_signal(self):
        from contra.core import market_agent as real_market_agent
        from contra.fixtures import bars_for
        unrelated_bar = bars_for("ALPHA.NS")[0]["id"]
        def invalid_market(signals):
            result = real_market_agent(signals)
            result["evidence_ids"].append(unrelated_bar)
            result["facts"].append({"key": "unrelated_bar", "value": 1, "source_ids": [unrelated_bar]})
            return result
        with patch("contra.core.market_agent", side_effect=invalid_market):
            report = self.analyze("ALPHA.NS")
        market = report["agents"]["market"]
        self.assertEqual(market["status"], "PARTIAL")
        self.assertNotIn(unrelated_bar, market["evidence_ids"])
        self.assertTrue(all(unrelated_bar not in fact["source_ids"] for fact in market["facts"]))

    def test_legacy_report_replays_but_changed_frozen_input_fails_integrity(self):
        legacy = deepcopy(self.analyze("GAMMA.NS"))
        del legacy["report_hash"]
        self.assertIs(verify_run(legacy), legacy)
        legacy["market_snapshot"]["bars"][0]["close"] += 1
        with self.assertRaises(RunIntegrityError):
            verify_run(legacy)
        unversioned = deepcopy(legacy)
        del unversioned["method_version"]
        del unversioned["market_snapshot"]
        self.assertIs(verify_run(unversioned), unversioned)


if __name__ == "__main__":
    unittest.main()
