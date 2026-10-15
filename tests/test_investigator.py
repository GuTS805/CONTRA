"""The disagreement investigator: bounded plan, retrieval and verified findings, never changing the action."""
import asyncio
import os
import unittest
from unittest.mock import patch

from contra import investigator, llm
from contra.core import analyze, hybrid_rank
from contra.store import baseline_profiles

ENV = {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_MODEL": "fixture-model"}
PLAN = {"questions": ["Why is operating margin narrowing?", "Have any customers renewed contracts?"]}
FINDINGS = {"findings": [
    {"sentence": "Operating margin narrowed as costs rose.", "source_id": "E-ALPHA-01",
     "quote": "Operating margin narrowed as component costs rose"},
    {"sentence": "A large customer renewed its contract.", "source_id": "E-ALPHA-03",
     "quote": "A large customer renewed a multiyear contract"}]}
BUDGET_MESSAGE = "today's model budget is used"


class InvestigatorTests(unittest.TestCase):
    def setUp(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)
        env = patch.dict(os.environ, ENV)
        env.start()
        self.addCleanup(env.stop)
        no_embeddings = patch("contra.investigator.embeddings.available", return_value=False)
        no_embeddings.start()
        self.addCleanup(no_embeddings.stop)
        self.report = asyncio.run(analyze("ALPHA.NS", baseline_profiles()[0], allow_llm=False))
        self.documents = self.report["market_snapshot"]["documents"]

    def run_with(self, *answers):
        with patch("contra.llm.structured_call", side_effect=[(a, "fixture-model") for a in answers]) as call:
            result = investigator.investigate(self.report["agents"], self.documents, hybrid_rank, "owner")
        return result, call

    def test_completed_investigation_is_grounded_cached_and_leans_from_tone_tags(self):
        self.assertEqual(self.report["synthesis"]["state"], "CONFLICTED")
        result, call = self.run_with(PLAN, FINDINGS)
        self.assertEqual(result["status"], "COMPLETED", result)
        self.assertEqual(call.call_count, 2, "one plan call and one findings call")
        self.assertEqual(result["questions"], PLAN["questions"])
        self.assertTrue(all(s["ids"] for s in result["searched"]))
        self.assertEqual({f["source_id"] for f in result["findings"]}, {"E-ALPHA-01", "E-ALPHA-03"})
        returned = {i for found in result["searched"] for i in found["ids"]}
        tones = {d["id"]: d["tone"] for d in self.documents}
        balance = result["balance"]
        self.assertEqual(balance["positive"], sorted(i for i in returned if tones[i] > 0), "from tone tags, not the model")
        self.assertEqual(balance["negative"], sorted(i for i in returned if tones[i] < 0))
        self.assertEqual(balance["reading"], "BOTH_SIDES", "a favorable and an unfavorable passage came back")
        self.assertEqual(set(balance["not_summarized"]), returned - {"E-ALPHA-01", "E-ALPHA-03"},
                         "a passage the findings skip is still reported")
        self.assertIn("not changed", result["policy_note"])
        self.assertFalse(result["cached"])
        again, call_again = self.run_with()
        self.assertTrue(again["cached"])
        self.assertEqual((again["findings"], call_again.call_count), (result["findings"], 0),
                         "the same evidence costs nothing twice")

    def test_search_only_sees_the_frozen_excerpts_of_this_run(self):
        result, _ = self.run_with(PLAN, FINDINGS)
        known = {d["id"] for d in self.documents}
        self.assertTrue({i for s in result["searched"] for i in s["ids"]} <= known)

    def test_unsupported_findings_are_rejected_and_recorded(self):
        quote = "A large customer renewed a multiyear contract"
        cases = (
            ("direction the quote lacks", {"sentence": "Operating margin improved as costs rose.",
                                           "source_id": "E-ALPHA-01",
                                           "quote": "Operating margin narrowed as component costs rose"}, "direction word"),
            ("quote not in excerpt", {"sentence": "A large customer renewed its contract.", "source_id": "E-ALPHA-03",
                                      "quote": "A large customer renewed every contract"}, "exact text"),
            ("a number", {"sentence": "A large customer renewed 3 contracts.", "source_id": "E-ALPHA-03",
                          "quote": quote}, "number"),
            ("advice", {"sentence": "A large customer renewed so investors should buy.", "source_id": "E-ALPHA-03",
                        "quote": quote}, "advice"),
            ("portfolio talk", {"sentence": "A large customer renewed a contract within the cap.",
                                "source_id": "E-ALPHA-03", "quote": quote}, "portfolio"))
        for name, finding, expected in cases:
            with self.subTest(name):
                llm.reset_state()
                result, _ = self.run_with(PLAN, {"findings": [finding]})
                self.assertEqual(result["status"], "REJECTED")
                self.assertIn(expected, result["reason"])
                self.assertNotIn("findings", result)
                self.assertTrue(result["rejected_findings"])

    def test_questions_are_bounded_and_clean(self):
        for questions, expected in ((["a"], "8 to 200"), ([], "one to 2"), (["Why is margin falling?"] * 3, "one to 2"),
                                    (["Is revenue above 5 percent?"], "numbers"), (["Is margin falling (supports Market)?"], "brackets"), (["Should I buy this stock now?"], "advice")):
            with self.subTest(questions=questions):
                llm.reset_state()
                result, call = self.run_with({"questions": questions})
                self.assertEqual(result["status"], "REJECTED")
                self.assertIn(expected, result["reason"])
                self.assertEqual(call.call_count, 1, "no search or second call after a bad plan")

    def test_no_passage_means_no_findings_and_one_call(self):
        result, call = self.run_with({"questions": ["Where is the weather forecast heading?"]})
        self.assertEqual((result["status"], call.call_count), ("NO_EVIDENCE", 1))

    def test_budget_or_provider_failure_never_raises(self):
        with patch("contra.llm.structured_call", side_effect=llm.DailyLimitReached(BUDGET_MESSAGE)):
            result = investigator.investigate(self.report["agents"], self.documents, hybrid_rank, "owner")
        self.assertEqual((result["status"], result["reason"]), ("UNAVAILABLE", BUDGET_MESSAGE))
        with patch("contra.llm.structured_call", side_effect=OSError("network down")):
            result = investigator.investigate(self.report["agents"], self.documents, hybrid_rank, "owner")
        self.assertEqual(result["status"], "UNAVAILABLE")
        with patch.dict(os.environ, {"CONTRA_LLM": "0"}):
            self.assertEqual(investigator.investigate(self.report["agents"], self.documents, hybrid_rank)["status"],
                             "UNAVAILABLE")

    def test_analysis_runs_it_only_on_a_conflict_and_never_changes_the_action(self):
        profile = baseline_profiles()[0]
        with patch("contra.llm.reason", side_effect=RuntimeError("agents use fallback here")), \
                patch("contra.llm.structured_call",
                      side_effect=[(PLAN, "fixture-model"), (FINDINGS, "fixture-model")]) as call:
            conflicted = asyncio.run(analyze("ALPHA.NS", profile))
            calm = asyncio.run(analyze("GAMMA.NS", profile))
        self.assertEqual(conflicted["investigation"]["status"], "COMPLETED")
        self.assertEqual(call.call_count, 2, "only the conflicted run called the investigator")
        self.assertNotIn("investigation", calm)
        self.assertEqual(conflicted["recommendation"]["action"], self.report["recommendation"]["action"])
        self.assertEqual(conflicted["recommendation"]["sizing"], self.report["recommendation"]["sizing"])
        self.assertIn("investigation_ms", conflicted["metrics"])
        off = asyncio.run(analyze("ALPHA.NS", profile, allow_llm=False))
        self.assertNotIn("investigation", off)


if __name__ == "__main__":
    unittest.main()
