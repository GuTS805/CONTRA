import asyncio
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

    def test_structured_focus_accepts_only_validated_ids(self):
        result = {"status": "OK", "assessment": "BEARISH", "facts": [
            {"key": "filing_excerpt", "value": "Operating margin narrowed.", "source_ids": ["E-01"]}],
            "evidence_ids": ["E-01"]}
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["E-01"]})}]}],
            "usage": {"input_tokens": 12, "output_tokens": 8}}
        with patch.dict(os.environ, {"CONTRA_LLM": "1", "OPENAI_API_KEY": "test-only-key"}):
            with patch("contra.llm.urlopen", return_value=FakeResponse(payload)) as request:
                selected = llm.reason("RESEARCH", result)
            self.assertEqual(selected["supporting_ids"], ["E-01"])
            self.assertEqual(selected["model_request_id"], "req_fixture")
            sent = json.loads(request.call_args.args[0].data)
            self.assertEqual(sent["text"]["format"]["type"], "json_schema")
            self.assertEqual(sent["text"]["format"]["schema"]["additionalProperties"], False)
            payload["output"][0]["content"][0]["text"] = json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["MADE-UP"]})
            llm.reset_state()
            with patch("contra.llm.urlopen", return_value=FakeResponse(payload)):
                with self.assertRaises(ValueError):
                    llm.reason("RESEARCH", result)

    def test_repeat_inputs_use_cache_and_daily_limit_falls_back(self):
        result = {"status": "OK", "assessment": "BEARISH", "facts": [
            {"key": "filing_excerpt", "value": "Operating margin narrowed.", "source_ids": ["E-01"]}],
            "evidence_ids": ["E-01"]}
        payload = {"model": "fixture-model", "output": [{"type": "message", "content": [
            {"type": "output_text", "text": json.dumps({"focus": "NEGATIVE_FACTS", "supporting_ids": ["E-01"]})}]}]}
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
            self.assertTrue(any("daily model call limit" in warning for warning in market["warnings"]))

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


if __name__ == "__main__":
    unittest.main()
