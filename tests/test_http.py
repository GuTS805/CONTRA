"""Real local HTTP lifecycle checks against an isolated temporary database."""
import json
import os
import socket
import subprocess
import sys
import tempfile
import time
import unittest
from urllib.error import HTTPError
from urllib.request import Request, urlopen


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = {**os.environ, "CONTRA_DB": os.path.join(cls.tmp.name, "http.sqlite3"),
               "CONTRA_PORT": str(cls.port), "CONTRA_HOST": "127.0.0.1"}
        cls.process = subprocess.Popen([sys.executable, "-m", "contra.server"],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                with urlopen(cls.base + "/health", timeout=.3) as response:
                    if json.load(response)["status"] == "ok":
                        return
            except OSError:
                time.sleep(.05)
        cls.process.terminate()
        raise RuntimeError("CONTRA test server did not start")

    @classmethod
    def tearDownClass(cls):
        cls.process.terminate()
        try:
            cls.process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            cls.process.kill()
            cls.process.wait()
        cls.tmp.cleanup()

    def request_json(self, path, method="GET", data=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, data=body, method=method,
                          headers={"Content-Type": "application/json"})
        with urlopen(request, timeout=5) as response:
            return response.status, json.load(response)

    def test_analysis_replay_evidence_and_measured_evaluation(self):
        _, catalog = self.request_json("/v1/stocks")
        self.assertLess(catalog["stocks"][0]["first_date"], catalog["as_of"])
        _, library = self.request_json("/v1/evidence")
        self.assertEqual(library["count"], 16)
        _, filtered = self.request_json("/v1/evidence?ticker=DELTA.NS&as_of=2026-10-13")
        self.assertEqual(filtered["count"], 0)
        status, report = self.request_json("/v1/analyses", "POST",
                                           {"ticker": "ALPHA.NS", "investor_id": "demo_conservative"})
        self.assertEqual(status, 201)
        self.assertEqual(report["synthesis"]["state"], "CONFLICTED")
        self.assertTrue(report["metrics"]["agent_overlap"])
        self.assertGreater(len(report["market_snapshot"]["bars"]), 21)
        _, replay = self.request_json("/v1/analyses/" + report["run_id"])
        self.assertEqual(replay, report)
        _, history = self.request_json("/v1/analyses?investor_id=demo_conservative")
        self.assertIn(report["run_id"], [item["run_id"] for item in history["runs"]])
        bar_id = report["signals"]["momentum"]["evidence_ids"][0]
        _, bar = self.request_json("/v1/evidence/" + bar_id)
        self.assertEqual(bar["id"], bar_id)
        _, frozen_bar = self.request_json(f"/v1/analyses/{report['run_id']}/evidence/{bar_id}")
        self.assertEqual(frozen_bar, bar)
        doc_id = report["evidence"][0]["id"]
        _, frozen_doc = self.request_json(f"/v1/analyses/{report['run_id']}/evidence/{doc_id}")
        self.assertEqual(frozen_doc, report["evidence"][0])
        _, frozen_profile = self.request_json(f"/v1/analyses/{report['run_id']}/evidence/demo_conservative")
        self.assertEqual(frozen_profile, report["investor_snapshot"])
        _, evaluation = self.request_json("/v1/evaluations/summary")
        self.assertEqual(evaluation["scenario_checks"]["passed"], evaluation["scenario_checks"]["total"])
        self.assertEqual(evaluation["scenario_checks"]["citation_fabrication_count"], 0)
        _, benchmark = self.request_json("/v1/evaluations/benchmark")
        self.assertEqual(benchmark["repetitions"], 10)
        self.assertLessEqual(benchmark["latency_ms"]["p50"], benchmark["latency_ms"]["p95"])
        _, early = self.request_json("/v1/analyses", "POST", {"ticker": "ALPHA.NS",
                                      "investor_id": "demo_conservative", "as_of": "2026-06-12"})
        self.assertEqual(early["synthesis"]["state"], "INSUFFICIENT_EVIDENCE")

    def test_profile_revision_and_bad_input(self):
        _, before = self.request_json("/v1/profiles/demo_conservative/portfolio")
        _, updated = self.request_json("/v1/profiles/demo_conservative", "PUT",
                                       {"max_single_asset_weight": .18, "expected_revision": before["revision"]})
        self.assertEqual(updated["revision"], before["revision"] + 1)
        self.assertEqual(updated["max_single_asset_weight"], .18)
        _, stable_evaluation = self.request_json("/v1/evaluations/summary")
        self.assertEqual(stable_evaluation["scenario_checks"]["passed"], stable_evaluation["scenario_checks"]["total"])
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/profiles/demo_conservative", "PUT",
                              {"max_single_asset_weight": .19, "expected_revision": before["revision"]})
        self.assertEqual(raised.exception.code, 409)
        for path, payload, expected in (("/v1/analyses", {"ticker": "UNKNOWN", "investor_id": "demo_growth"}, 404),
                                        ("/v1/analyses", {"ticker": "ALPHA.NS", "investor_id": "missing"}, 404),
                                        ("/v1/analyses", {"ticker": "ALPHA.NS", "investor_id": "demo_growth", "as_of": "bad"}, 400)):
            with self.subTest(payload=payload), self.assertRaises(HTTPError) as raised:
                self.request_json(path, "POST", payload)
            self.assertEqual(raised.exception.code, expected)
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/profiles/demo_growth", "PUT", {"max_single_asset_weight": float("nan")})
        self.assertEqual(raised.exception.code, 400)
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/profiles/demo_growth", "PUT", {"risk_tier": ["GROWTH"]})
        self.assertEqual(raised.exception.code, 400)


if __name__ == "__main__":
    unittest.main()
