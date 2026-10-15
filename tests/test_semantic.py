"""Grounded model briefings, hybrid filing search and the embedding cache."""
import asyncio
import io
import json
import os
import unittest
from unittest.mock import patch

from contra import embeddings, llm
from contra.core import analyze, ask_filings, hybrid_rank, SEMANTIC_THRESHOLD
from contra.store import baseline_profiles

MARKET = {"agent": "MARKET", "status": "OK", "assessment": "BULLISH",
          "facts": [{"key": "momentum_return", "value": 0.06795, "units": "fraction", "source_ids": ["BAR-A-1", "BAR-A-2"]},
                    {"key": "relative_volume", "value": 1.743, "units": "ratio", "source_ids": ["BAR-A-2"]}],
          "eligible_evidence_ids": ["BAR-A-1", "BAR-A-2"], "single_asset_breach": None, "sector_breach": None,
          "context": dict(llm.CONTEXT["MARKET"])}
RISK = {"agent": "RISK", "status": "OK", "assessment": "CAUTION",
        "facts": [{"key": "position_weight", "value": 0.15, "units": "fraction", "source_ids": ["demo_conservative"]},
                  {"key": "single_asset_cap", "value": 0.1, "units": "fraction", "source_ids": ["demo_conservative"]}],
        "eligible_evidence_ids": ["demo_conservative"], "single_asset_breach": True, "sector_breach": False,
        "context": {}}
RESEARCH = {"agent": "RESEARCH", "status": "OK", "assessment": "BEARISH",
            "facts": [{"key": "filing_excerpt", "value": "Revenue fell 12% while costs rose.", "source_ids": ["E-X-01"]}],
            "eligible_evidence_ids": ["E-X-01"], "single_asset_breach": None, "sector_breach": None,
            "context": {"cited_excerpt_count": 1}}


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())
        self.headers = {"x-request-id": "req_fixture"}


class SummaryVerificationTests(unittest.TestCase):
    def test_grounded_summaries_pass(self):
        for text, agent, facts in (
                ("Prices trended upward over recent sessions on heavier than usual volume [BAR-A-2].", "MARKET", MARKET),
                ("Momentum is positive and not bearish across these sessions [BAR-A-1].", "MARKET", MARKET),
                ("The momentum change clears the three percent threshold [BAR-A-1].", "MARKET", MARKET),
                ("The filing says revenue fell while costs rose [E-X-01].", "RESEARCH", RESEARCH)):
            with self.subTest(text=text):
                self.assertIsNone(llm.verify_summary(text, agent, facts))

    def test_unsafe_summaries_are_rejected(self):
        cases = (
            ("Price rose 6.8% over recent sessions [BAR-A-2].", "MARKET", MARKET, "states a number"),
            ("Price trended upward [BAR-X-9].", "MARKET", MARKET, "outside the eligible set"),
            ("Price trended upward on strong volume.", "MARKET", MARKET, "no citation"),
            ("Investors should buy while momentum lasts [BAR-A-2].", "MARKET", MARKET, "advice"),
            ("The stock will rise further after recent gains [BAR-A-2].", "MARKET", MARKET, "advice"),
            ("The trend looks bearish over recent sessions [BAR-A-2].", "MARKET", MARKET, "contradicts"),
            ("Prices declined across recent sessions [BAR-A-2].", "MARKET", MARKET, "contradicts"),
            ("Volume stays within acceptable bounds [BAR-A-2].", "MARKET", MARKET, "judgment"),
            # A real gpt-4.1-nano summary read above-typical volume as "a decline in market activity".
            ("Volume is above typical levels, suggesting heavier market activity [BAR-A-2].", "MARKET", MARKET,
             "speculates"),
            ("Momentum is positive, pointing to a bullish outlook [BAR-A-1].", "MARKET", MARKET, "speculates"),
            ("Volume is high and no breach of volume limits appears [BAR-A-2].", "MARKET", MARKET, "portfolio limits"),
            ("The filing looks bullish on balance [E-X-01].", "RESEARCH", RESEARCH, "contradicts"),
            ("Short.", "MARKET", MARKET, "length"),
            ("One [BAR-A-1]. Two. Three. Four.", "MARKET", MARKET, "three sentences"))
        for text, agent, facts, reason in cases:
            with self.subTest(text=text):
                self.assertIn(reason, llm.verify_summary(text, agent, facts) or "PASSED")

    def test_risk_agent_gets_no_model_summary(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)
        result = {"status": "OK", "assessment": "CAUTION", "facts": [
            {"key": "position_weight", "value": 0.15, "units": "fraction", "source_ids": ["demo_conservative"]}],
            "evidence_ids": ["demo_conservative"], "single_asset_breach": True, "sector_breach": False}
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"focus": "SINGLE_NAME_LIMIT", "supporting_ids": ["demo_conservative"]})}]}]}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_MODEL": "fixture-model"}), \
                patch("contra.llm.urlopen", return_value=FakeResponse(payload)) as request:
            answer = llm.reason("RISK", result)
        sent = json.loads(request.call_args.args[0].data)
        self.assertNotIn("summary", sent["text"]["format"]["schema"]["properties"])
        self.assertEqual(answer["summary"], {"text": None, "status": "NOT_REQUESTED"})

    def test_tone_needs_a_valid_label_and_an_exact_quote(self):
        text = "FY 27 Revenue Guidance Revised to 1.5%-3.0%, Margin guidance Retained at 20%-22%"
        good = {"tone": "NEGATIVE", "quote": "Revenue Guidance Revised to 1.5%-3.0%,"}
        self.assertIsNone(llm.verify_tone(good, text), "edge punctuation is not part of the quoted words")
        for choice, reason in (
                ({"tone": "BULLISH", "quote": "Revenue Guidance Revised"}, "not one of the allowed"),
                ({"tone": "POSITIVE", "quote": "Revenue guidance was raised"}, "not exact text"),
                ({"tone": "POSITIVE", "quote": ""}, "not exact text"),
                ({"tone": "POSITIVE", "quote": "Revised"}, "too short"),
                ("POSITIVE", "not one of the allowed")):
            with self.subTest(choice=choice):
                self.assertIn(reason, llm.verify_tone(choice, text) or "PASSED")

    def test_classify_tone_is_cached_budgeted_and_falls_back(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)
        text = "Management lowered the full year revenue range and reported a delayed customer delivery schedule."
        reply = {"model": "fixture-model", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"tone": "NEGATIVE", "quote": "lowered the full year revenue range"})}]}]}
        env = {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_MODEL": "fixture-model",
               "CONTRA_LLM_ACCOUNT_DAILY_LIMIT": "1"}
        with patch.dict(os.environ, env), patch("contra.llm.urlopen", return_value=FakeResponse(reply)) as request:
            first = llm.classify_tone(text, "owner-a")
            second = llm.classify_tone(text, "owner-a")
            self.assertEqual((first["tone"], first["label"], first["cached"]), (-1, "NEGATIVE", False))
            self.assertTrue(second["cached"])
            self.assertEqual(request.call_count, 1, "an identical excerpt is classified once")
            with self.assertRaises(llm.DailyLimitReached):
                llm.classify_tone(text + " Extra words keep this a new excerpt.", "owner-a")
        bad = {"model": "fixture-model", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"tone": "POSITIVE", "quote": "strong growth in every region"})}]}]}
        with patch.dict(os.environ, {**env, "CONTRA_LLM_ACCOUNT_DAILY_LIMIT": "9"}),                 patch("contra.llm.urlopen", return_value=FakeResponse(bad)):
            with self.assertRaises(ValueError):
                llm.classify_tone("A different excerpt about quarterly operating costs and orders.", "owner-b")
        with patch.dict(os.environ, {"CONTRA_LLM": "0"}):
            with self.assertRaises(RuntimeError):
                llm.classify_tone(text)

    def test_research_claims_must_match_their_own_quotes(self):
        guidance = "FY 27 Revenue Guidance Revised to 1.5%-3.0%, Margin guidance Retained at 20%-22%"
        quarter = "Q4 revenues were $5,040 million, growth of 4.1% year on year in constant currency."
        cash = "We have no outstanding borrowings. We believe that our working capital is sufficient."
        mercedes = "moving one of the automotive sector\u2019s largest hybrid cloud operations"
        margin = "Operating margin narrowed as component costs rose despite stronger reported revenue."
        excerpts = {"E-G": guidance, "E-Q": quarter, "E-C": cash, "E-M": mercedes, "E-A": margin}

        def claim(sentence, source, quote):
            return {"sentence": sentence, "source_id": source, "quote": quote}
        passing = (
            [claim("Revenue guidance for the year was revised.", "E-G", "Revenue Guidance Revised to")],
            [claim("Quarterly revenues showed year on year growth.", "E-Q", "Q4 revenues were $5,040 million, growth")],
            [claim("The company has no outstanding borrowings.", "E-C", "We have no outstanding borrowings.")],
            [claim("Revenue guidance was revised and margin guidance retained.", "E-G",
                   "Revenue Guidance Revised to 1.5%-3.0%, Margin guidance Retained at 20%-22%.")],
            [claim("It runs one of the automotive sector's largest cloud operations.", "E-M",
                   "one of the automotive sector's largest")],
        )
        for claims in passing:
            with self.subTest(claims=claims[0]["sentence"]):
                self.assertIsNone(llm.verify_claims(claims, excerpts))
        failing = (
            # A real gpt-4.1-nano summary of Infosys filings: the guidance range was narrowed, not raised.
            ([claim("Revenue guidance was revised upward.", "E-G", "Revenue Guidance Revised to")], "states an increase"),
            ([claim("Revenue guidance was raised.", "E-Q", "Q4 revenues were $5,040 million, growth")], "names guidance"),
            ([claim("Revenues grew strongly.", "E-Q", "Q4 revenues were $5,040 million, growth")], "calls something strong"),
            ([claim("The company has outstanding borrowings.", "E-C", "We have no outstanding borrowings.")], "negation"),
            ([claim("Revenue guidance was revised.", "E-G", "Revenue Guidance Revised upward to")], "not exact text"),
            ([claim("Guidance was revised.", "E-G", "Guidance Revised")], "not exact text"),
            ([claim("Revenue guidance was revised.", "E-X", "Revenue Guidance Revised to")], "outside the eligible set"),
            ([claim("Revenue guidance was revised. It was lowered.", "E-G", "Revenue Guidance Revised to")], "one sentence"),
            # A direction word that appears in the quote must not license a different one in the sentence.
            ([claim("Operating margin improved as costs rose.", "E-A", "Operating margin narrowed as component costs rose")],
             "direction word"),
            ([claim("Revenue guidance was revised.", "E-G", "Revenue Guidance Revised to")] * 4, "one to three"),
            (["Revenue guidance was revised."], "malformed"),
        )
        for claims, reason in failing:
            with self.subTest(reason=reason):
                self.assertIn(reason, llm.verify_claims(claims, excerpts) or "PASSED")

    def test_institutional_flows_and_volume_are_not_mistaken_for_advice_or_price_direction(self):
        falling = {**MARKET, "assessment": "BEARISH",
                   "facts": [{**MARKET["facts"][0], "value": -0.04}, MARKET["facts"][1]]}
        self.assertIsNone(llm.verify_summary(
            "Foreign institutions were net sellers while domestic institutions were net buyers across the market [BAR-A-1].",
            "MARKET", falling))
        self.assertIsNone(llm.verify_summary(
            "Net buying by domestic institutions was higher than net selling by foreign institutions [BAR-A-1].",
            "MARKET", falling))
        self.assertIsNone(llm.verify_summary(
            "Momentum fell over the window, and relative volume rose to a higher level [BAR-A-1].", "MARKET", falling))
        self.assertIsNone(llm.verify_summary(
            "There was a decrease in momentum and an increase in relative volume [BAR-A-1].", "MARKET", falling))
        self.assertIn("advice", llm.verify_summary("Consider buying while momentum lasts [BAR-A-1].", "MARKET", MARKET))
        self.assertIn("sign", llm.verify_summary("Momentum shows an increase over the window [BAR-A-1].", "MARKET", falling))

    def test_market_summary_must_match_the_sign_of_the_price_change(self):
        falling = {**MARKET, "assessment": "NEUTRAL",
                   "facts": [{**MARKET["facts"][0], "value": -0.012}, MARKET["facts"][1]]}
        self.assertIn("sign", llm.verify_summary("Prices drifted upward over recent sessions [BAR-A-1].", "MARKET", falling))
        self.assertIn("sign", llm.verify_summary("There was some upward price movement [BAR-A-1].", "MARKET", falling))
        self.assertIsNone(llm.verify_summary("Prices did not move upward over recent sessions [BAR-A-1].", "MARKET", falling))
        self.assertIsNone(llm.verify_summary("Prices drifted slightly lower over recent sessions [BAR-A-1].", "MARKET", falling))

    def test_rejected_claims_keep_focus_and_use_rule_briefing(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)
        result = {"status": "OK", "assessment": "BEARISH", "facts": [
            {"key": "filing_excerpt", "value": "Operating margin narrowed as component costs rose.", "source_ids": ["E-01"]}],
            "evidence_ids": ["E-01"]}
        claims = [{"sentence": "Margins fell sharply.", "source_id": "E-01", "quote": "Operating margin narrowed as component"}]
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"focus": "NEGATIVE_FACTS", "supporting_ids": ["E-01"], "summary": claims})}]}]}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_MODEL": "fixture-model"}), \
                patch("contra.llm.urlopen", return_value=FakeResponse(payload)) as request:
            answer = llm.reason("RESEARCH", result)
        schema = json.loads(request.call_args.args[0].data)["text"]["format"]["schema"]
        self.assertEqual(schema["properties"]["summary"]["items"]["properties"]["source_id"]["enum"], ["E-01"])
        self.assertEqual(answer["focus"], "NEGATIVE_FACTS")
        self.assertEqual(answer["summary"], {"text": None, "status": "REJECTED",
                                             "reason": "calls something sharp, which its quote does not",
                                             "rejected_text": "Margins fell sharply. [E-01]", "claims": claims})

    def test_verified_claims_cite_each_sentence(self):
        llm.reset_state()
        self.addCleanup(llm.reset_state)
        result = {"status": "OK", "assessment": "MIXED", "facts": [
            {"key": "filing_excerpt", "value": "Operating margin narrowed as component costs rose.", "source_ids": ["E-01"]},
            {"key": "filing_excerpt", "value": "A large customer renewed a multiyear contract.", "source_ids": ["E-02"]}],
            "evidence_ids": ["E-01", "E-02"]}
        claims = [{"sentence": "Operating margin narrowed as costs rose.", "source_id": "E-01",
                   "quote": "Operating margin narrowed as component costs rose"},
                  {"sentence": "A large customer renewed its contract.", "source_id": "E-02",
                   "quote": "A large customer renewed a multiyear contract."}]
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [{"type": "output_text", "text": json.dumps(
            {"focus": "MIXED_FACTS", "supporting_ids": ["E-01", "E-02"], "summary": claims})}]}]}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_MODEL": "fixture-model"}), \
                patch("contra.llm.urlopen", return_value=FakeResponse(payload)):
            answer = llm.reason("RESEARCH", result)
        self.assertEqual(answer["summary"], {"text": "Operating margin narrowed as costs rose. [E-01] "
                                                     "A large customer renewed its contract. [E-02]",
                                             "status": "VERIFIED", "claims": claims})

    def test_briefings_choose_verified_model_text_or_rules(self):
        def fake(agent, result):
            ids = result["evidence_ids"][:1]
            summary = {"text": "Margins narrowed [E-ALPHA-01].", "status": "VERIFIED"} if agent == "RESEARCH" else \
                {"text": None, "status": "REJECTED", "reason": "states a number"} if agent == "MARKET" else \
                {"text": None, "status": "NOT_REQUESTED"}
            return {"focus": next(iter(llm.allowed_focus(agent, result))), "supporting_ids": ids, "summary": summary,
                    "note": "fixture", "model_version": "fixture-model", "cached": False, "answered_at": "2026-10-15T00:00:00+00:00"}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key"}), \
                patch("contra.llm.reason", side_effect=fake), \
                patch("contra.investigator.investigate", return_value=None):
            report = asyncio.run(analyze("ALPHA.NS", baseline_profiles()[0]))
        agents = report["agents"]
        self.assertEqual(agents["research"]["briefing"]["source"], "MODEL_VERIFIED")
        self.assertEqual(agents["market"]["briefing"]["source"], "RULES")
        self.assertIn("rejected by verification: states a number", agents["market"]["briefing"]["model_note"])
        self.assertEqual(agents["risk"]["briefing"]["source"], "RULES")
        self.assertIsNone(agents["risk"]["briefing"]["model_note"])
        self.assertIn("15%", agents["risk"]["briefing"]["text"])

    def test_rule_briefings_exist_without_a_model(self):
        report = asyncio.run(analyze("DELTA.NS", baseline_profiles()[0], allow_llm=False))
        briefs = {name: agent["briefing"] for name, agent in report["agents"].items()}
        self.assertTrue(all(b["source"] == "RULES" and b["text"] for b in briefs.values()))
        self.assertIn("abstains", briefs["research"]["text"])
        for name, agent in report["agents"].items():
            self.assertTrue(set(llm.CITATION.findall(agent["briefing"]["text"])) <= set(agent["evidence_ids"]))


class HybridSearchTests(unittest.TestCase):
    DOCS = [{"id": "E-1", "excerpt": "Operating margin narrowed as component costs rose.", "published_at": "2026-10-01"},
            {"id": "E-2", "excerpt": "A large customer renewed a multiyear contract.", "published_at": "2026-09-01"}]

    @staticmethod
    def embed_with(similarities):
        """Vectors whose cosine with the question equals the given similarity per document."""
        def embed(texts):
            question = [1.0, 0.0]
            return [question] + [[s, (1 - s * s) ** 0.5] for s in similarities[:len(texts) - 1]]
        return embed

    def test_paraphrase_found_by_meaning_and_unrelated_question_abstains(self):
        ranked, info = hybrid_rank(self.DOCS, "Is profitability getting squeezed?", self.embed_with([0.51, 0.2]))
        self.assertEqual([d["id"] for d in ranked], ["E-1"])
        self.assertEqual(info["semantic_status"], "OK")
        self.assertEqual(ranked[0]["lexical_score"], 0)
        ranked, _ = hybrid_rank(self.DOCS, "What is the weather like?", self.embed_with([0.16, 0.07]))
        self.assertEqual(ranked, [])
        just_below = SEMANTIC_THRESHOLD - 0.001
        self.assertEqual(hybrid_rank(self.DOCS, "Anything?", self.embed_with([just_below, just_below]))[0], [])

    def test_lexical_match_still_counts_and_provider_failure_falls_back(self):
        ranked, _ = hybrid_rank(self.DOCS, "customer contract", self.embed_with([0.1, 0.3]))
        self.assertEqual([d["id"] for d in ranked], ["E-2"])
        def broken(texts):
            raise embeddings.EmbeddingUnavailable("today's search budget is used")
        ranked, info = hybrid_rank(self.DOCS, "customer contract", broken)
        self.assertEqual([d["id"] for d in ranked], ["E-2"])
        self.assertIn("today's search budget is used", info["semantic_status"])
        self.assertEqual(info["method"], "tfidf-1.0 lexical")

    def test_ask_reports_method_and_exact_passages(self):
        report = asyncio.run(analyze("ALPHA.NS", baseline_profiles()[0], allow_llm=False))
        docs = report["market_snapshot"]["documents"]
        similarities = [0.6 if d["id"] == "E-ALPHA-01" else 0.1 for d in docs]
        answer = ask_filings(report, "Is profitability getting squeezed?", self.embed_with(similarities))
        self.assertEqual([p["id"] for p in answer["passages"]], ["E-ALPHA-01"])
        self.assertTrue(answer["method"].startswith("hybrid"))
        stored = {d["id"]: d["excerpt"] for d in docs}
        self.assertEqual(answer["passages"][0]["excerpt"], stored["E-ALPHA-01"])
        lexical_only = ask_filings(report, "Is profitability getting squeezed?")
        self.assertEqual(lexical_only["passages"], [], "without embeddings the paraphrase finds nothing")


class EmbeddingCacheTests(unittest.TestCase):
    def setUp(self):
        embeddings.reset_state()
        self.addCleanup(embeddings.reset_state)
        env = patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key",
                                      "CONTRA_EMBED_DAILY_LIMIT": "3", "CONTRA_EMBED_ACCOUNT_DAILY_LIMIT": "2"})
        env.start()
        self.addCleanup(env.stop)

    @staticmethod
    def provider(request, timeout):
        body = json.loads(request.data)
        return FakeResponse({"data": [{"index": i, "embedding": [float(len(text) % 5 + 1)] * 256}
                                      for i, text in enumerate(body["input"])]})

    def test_only_missing_texts_are_fetched_in_one_batch(self):
        with patch("contra.embeddings.urlopen", side_effect=self.provider) as request:
            first = embeddings.embed(["alpha", "beta", "alpha"])
            self.assertEqual(request.call_count, 1)
            self.assertEqual(json.loads(request.call_args.args[0].data)["input"], ["alpha", "beta"])
            self.assertEqual(json.loads(request.call_args.args[0].data)["dimensions"], 256)
            again = embeddings.embed(["beta", "alpha"])
            self.assertEqual(request.call_count, 1, "cached vectors cost nothing")
        self.assertEqual(first[0], again[1])
        self.assertIsNone(embeddings.cached_only(["alpha", "gamma"]))

    def test_account_and_daily_limits(self):
        with patch("contra.embeddings.urlopen", side_effect=self.provider):
            embeddings.embed(["one"], owner="visitor")
            embeddings.embed(["two"], owner="visitor")
            with self.assertRaisesRegex(embeddings.EmbeddingUnavailable, "this account"):
                embeddings.embed(["three"], owner="visitor")
            embeddings.embed(["three"], owner="judge")
            with self.assertRaisesRegex(embeddings.EmbeddingUnavailable, "today's search budget"):
                embeddings.embed(["four"], owner="someone")

    def test_invalid_provider_vectors_are_rejected(self):
        bad = FakeResponse({"data": [{"index": 0, "embedding": [1.0] * 10}]})
        with patch("contra.embeddings.urlopen", return_value=bad):
            with self.assertRaisesRegex(embeddings.EmbeddingUnavailable, "invalid vector"):
                embeddings.embed(["text"])
        with patch.dict(os.environ, {"CONTRA_LLM": "0"}):
            self.assertFalse(embeddings.available())
            with self.assertRaises(embeddings.EmbeddingUnavailable):
                embeddings.embed(["text"])


if __name__ == "__main__":
    unittest.main()
