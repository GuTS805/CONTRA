import asyncio
from contextlib import redirect_stdout
import io
import json
import os
import tempfile
import unittest
from unittest.mock import patch

from contra import llm
from contra.core import analyze
from contra.store import connect, profile


class FakeResponse(io.BytesIO):
    def __init__(self, payload):
        super().__init__(json.dumps(payload).encode())
        self.headers = {"x-request-id": "req_fixture"}


class ModelAdapterTests(unittest.TestCase):
    def setUp(self):
        llm.reset_state()
        model = patch.dict(os.environ, {"CONTRA_MODEL": "fixture-model"})
        model.start()
        self.addCleanup(model.stop)
        self.addCleanup(llm.reset_state)

    def test_model_is_picked_from_the_account_when_not_set(self):
        listing = {"data": [{"id": "gpt-4.1-mini"}, {"id": "gpt-4o-mini"}, {"id": "text-embedding-3-small"}]}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_MODEL": ""}):
            with patch("contra.llm.urlopen", return_value=FakeResponse(listing)) as request:
                self.assertEqual(llm.resolve_model(), "gpt-4o-mini", "cheapest preferred model the key can use")
                self.assertEqual(llm.resolve_model(), "gpt-4o-mini")
                self.assertEqual(request.call_count, 1, "models are listed once per process")
                self.assertTrue(request.call_args.args[0].full_url.endswith("/v1/models"))
            llm.reset_state()
            with patch("contra.llm.urlopen", return_value=FakeResponse({"data": [{"id": "some-other-model"}]})):
                self.assertIsNone(llm.resolve_model())
                with self.assertRaisesRegex(RuntimeError, "No usable model"):
                    llm.reason("RESEARCH", {"status": "OK", "assessment": "BEARISH", "facts": [], "evidence_ids": []})
            with patch.dict(os.environ, {"CONTRA_MODEL": "my-model"}):
                self.assertEqual(llm.resolve_model(), "my-model")

    def test_structured_focus_accepts_only_validated_ids(self):
        result = {"status": "OK", "assessment": "BEARISH", "facts": [
            {"key": "filing_excerpt", "value": "Operating margin narrowed.", "source_ids": ["E-01"]}],
            "evidence_ids": ["E-01"]}
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["E-01"], "summary": "The cited filing reports a narrower operating margin [E-01]."})}]}],
            "usage": {"input_tokens": 12, "output_tokens": 8}}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key"}):
            with patch("contra.llm.urlopen", return_value=FakeResponse(payload)) as request:
                selected = llm.reason("RESEARCH", result)
            self.assertEqual(selected["supporting_ids"], ["E-01"])
            self.assertEqual(selected["model_request_id"], "req_fixture")
            sent = json.loads(request.call_args.args[0].data)
            self.assertEqual(sent["text"]["format"]["type"], "json_schema")
            self.assertEqual(sent["text"]["format"]["schema"]["additionalProperties"], False)
            properties = sent["text"]["format"]["schema"]["properties"]
            self.assertEqual(properties["focus"]["enum"], ["NEGATIVE_FACTS"], "only the valid focus is offered")
            self.assertEqual(properties["supporting_ids"]["items"]["enum"], ["E-01"], "only eligible IDs are offered")
            payload["output"][0]["content"][0]["text"] = json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["MADE-UP"], "summary": "Margins narrowed [E-01]."})
            llm.reset_state()
            with patch("contra.llm.urlopen", return_value=FakeResponse(payload)):
                with self.assertRaises(ValueError):
                    llm.reason("RESEARCH", result)

    def test_repeat_inputs_use_cache_and_daily_limit_falls_back(self):
        result = {"status": "OK", "assessment": "BEARISH", "facts": [
            {"key": "filing_excerpt", "value": "Operating margin narrowed.", "source_ids": ["E-01"]}],
            "evidence_ids": ["E-01"]}
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["E-01"], "summary": "The cited filing reports a narrower operating margin [E-01]."})}]}]}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_LLM_DAILY_LIMIT": "1"}):
            with patch("contra.llm.urlopen", side_effect=lambda *a, **k: FakeResponse(payload)) as request:
                first = llm.reason("RESEARCH", result)
                again = llm.reason("RESEARCH", result)
                self.assertEqual(request.call_count, 1, "an identical input must not be paid for twice")
                self.assertEqual((first["cached"], again["cached"]), (False, True))
                changed = {**result, "assessment": "MIXED"}
                with self.assertRaises(llm.DailyLimitReached):
                    llm.reason("RESEARCH", changed)
                self.assertEqual(request.call_count, 1)
            self.assertEqual(llm.usage()["calls"], 1)
            with tempfile.TemporaryDirectory() as folder:
                db = connect(folder + "/limit.sqlite3")
                investor = profile(db, "demo_conservative")
                db.close()
            with patch("contra.llm.urlopen") as request:
                report = asyncio.run(analyze("GAMMA.NS", investor))
            request.assert_not_called()
            market = report["agents"]["market"]
            self.assertEqual(market["execution_mode"], "DETERMINISTIC_FALLBACK")
            self.assertTrue(any("Model reasoning paused: today's model budget is used" in warning
                                for warning in market["warnings"]))

    def test_one_account_cannot_use_the_whole_budget_and_answers_survive_restart(self):
        def result(n):
            return {"status": "OK", "assessment": "BEARISH", "facts": [
                {"key": "filing_excerpt", "value": f"Margin narrowed {n}.", "source_ids": ["E-01"]}], "evidence_ids": ["E-01"]}
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["E-01"], "summary": "The cited filing reports a narrower operating margin [E-01]."})}]}]}
        durable = {}
        class Store:
            def get(self, key):
                return durable.get(key)
            def put(self, key, answer):
                durable[key] = answer
        env = {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_LLM_DAILY_LIMIT": "10",
               "CONTRA_LLM_ACCOUNT_DAILY_LIMIT": "2"}
        with patch.dict(os.environ, env), patch.object(llm, "persistent_cache", Store()),              patch("contra.llm.urlopen", side_effect=lambda *a, **k: FakeResponse(payload)) as request:
            llm.reason("RESEARCH", result(1), owner="visitor")
            llm.reason("RESEARCH", result(2), owner="visitor")
            with self.assertRaisesRegex(llm.DailyLimitReached, "this account"):
                llm.reason("RESEARCH", result(3), owner="visitor")
            judge = llm.reason("RESEARCH", result(3), owner="judge")
            self.assertFalse(judge["cached"], "a later visitor still gets model reasoning")
            self.assertEqual(request.call_count, 3)
            llm.reset_state()  # A restart clears memory but not the durable store.
            again = llm.reason("RESEARCH", result(1), owner="someone")
            self.assertTrue(again["cached"])
            self.assertEqual(request.call_count, 3)
            llm.reset_state()
            with patch.object(llm, "persistent_cache", None):
                self.assertEqual(llm.preload(dict(durable)), 3)
                self.assertTrue(llm.reason("RESEARCH", result(2))["cached"], "shipped warm-up answers cost nothing")
            self.assertEqual(request.call_count, 3)

    def test_three_model_paths_are_independent_when_enabled(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(folder + "/model.sqlite3")
            investor = profile(db, "demo_conservative")
            db.close()
            def fake_reason(agent, result):
                return {"focus": next(iter(llm.allowed_focus(agent, result))),
                        "supporting_ids": result["evidence_ids"][:1],
                        "note": "Validated fixture focus", "model_version": "mock-model",
                        "prompt_version": llm.PROMPT_VERSION, "token_usage": {"input_tokens": 1, "output_tokens": 1}}
            with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key"}):
                with patch("contra.llm.reason", side_effect=fake_reason) as mocked:
                    report = asyncio.run(analyze("ALPHA.NS", investor))
                self.assertEqual(mocked.call_count, 3)
            self.assertTrue(all(a["execution_mode"] == "LLM_REASONED" for a in report["agents"].values()))
            self.assertEqual(report["synthesis"]["state"], "CONFLICTED")

    def test_model_outage_keeps_canonical_report(self):
        with tempfile.TemporaryDirectory() as folder:
            db = connect(folder + "/fallback.sqlite3")
            investor = profile(db, "demo_conservative")
            db.close()
            with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key"}):
                with patch("contra.llm.reason", side_effect=ValueError("invalid source")) as mocked:
                    report = asyncio.run(analyze("DELTA.NS", investor))
                self.assertEqual(mocked.call_count, 2)  # Research has no eligible evidence.
            self.assertEqual(report["agents"]["research"]["status"], "UNAVAILABLE")
            self.assertEqual(report["synthesis"]["state"], "PARTIAL")
            self.assertTrue(all(a["execution_mode"] == "DETERMINISTIC_FALLBACK" for a in report["agents"].values()))
            self.assertEqual(report["evidence"], [])

    def test_warm_up_writes_reusable_answers_for_every_scenario(self):
        from pathlib import Path
        from contra import embeddings, warm
        def answer(request, timeout):
            body = json.loads(request.data)
            if request.full_url.endswith("/embeddings"):
                rows = [{"index": i, "embedding": [((i + 1) * (j + 3)) % 7 / 7 for j in range(256)]}
                        for i, _ in enumerate(body["input"])]
                return FakeResponse({"data": rows})
            facts = json.loads(body["input"])
            focus = next(iter(llm.allowed_focus(facts["agent"], {**facts, "evidence_ids": facts["eligible_evidence_ids"]})))
            ids = facts["eligible_evidence_ids"][:1]
            choice = {"focus": focus, "supporting_ids": ids}
            if facts["agent"] != "RISK":
                choice["summary"] = f"This view rests on [{ids[0]}]." if ids else "No source was eligible for this view."
            return FakeResponse({"model": "fixture-model", "output": [{"type": "message", "content": [
                {"type": "output_text", "text": json.dumps(choice)}]}]})
        with tempfile.TemporaryDirectory() as folder:
            target, vectors_file = Path(folder) / "model_cache.json", Path(folder) / "embedding_cache.json"
            env = {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key", "CONTRA_DB": folder + "/warm.sqlite3",
                   "CONTRA_ENV_FILE": os.devnull, "CONTRA_LLM_DAILY_LIMIT": "100"}
            embeddings.reset_state()
            self.addCleanup(embeddings.reset_state)
            with patch.dict(os.environ, env), patch.object(warm, "WARM_CACHE", target),                     patch.object(warm, "WARM_EMBEDDINGS", vectors_file), patch("contra.server.WARM_CACHE", target),                     patch("contra.server.WARM_EMBEDDINGS", vectors_file),                     patch("contra.llm.urlopen", side_effect=answer) as request,                     patch("contra.embeddings.urlopen", side_effect=answer) as embed_request,                     patch.object(llm, "persistent_cache", None), patch.object(embeddings, "persistent_cache", None):
                output = io.StringIO()
                with redirect_stdout(output):
                    warm.main()
                self.assertNotIn("Not model-reasoned", output.getvalue())
                self.assertIn("model-written and verified, 0 replaced by rule summaries", output.getvalue())
                paid = request.call_count
                shipped = json.loads(target.read_text(encoding="utf-8"))["answers"]
                self.assertEqual(len(shipped), 15)
                self.assertEqual(paid, 15, "identical scenario inputs are answered once")
                self.assertEqual(embed_request.call_count, 1, "all warm-up texts are embedded in one batch")
                vectors = json.loads(vectors_file.read_text(encoding="utf-8"))["vectors"]
                llm.reset_state()
                embeddings.reset_state()
                llm.preload(shipped)
                embeddings.preload(vectors)
                report = asyncio.run(analyze("ALPHA.NS", store_profiles()[0]))
                self.assertEqual(request.call_count, paid, "a preloaded scenario costs nothing")
                self.assertTrue(all(a["reasoning"]["cached"] for a in report["agents"].values()))
                self.assertEqual([a["briefing"]["source"] for a in report["agents"].values()],
                                 ["MODEL_VERIFIED", "MODEL_VERIFIED", "RULES"], "risk keeps its exact rule briefing")
                from contra.evaluation import semantic_evaluation
                self.assertEqual(semantic_evaluation()["status"], "MEASURED", "evaluation runs from shipped vectors")
                self.assertEqual(embed_request.call_count, 1)


def store_profiles():
    from contra.store import baseline_profiles
    return baseline_profiles()


if __name__ == "__main__":
    unittest.main()
