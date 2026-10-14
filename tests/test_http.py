"""Real local HTTP lifecycle checks against an isolated temporary database."""
import json
from contextlib import closing
import http.client
import os
import socket
import sqlite3
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
        self.assertTrue(report["report_hash"].startswith("sha256:"))
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
        _, two_run_evaluation = self.request_json("/v1/evaluations/summary")
        expected_median = (report["metrics"]["wall_latency_ms"] + early["metrics"]["wall_latency_ms"]) / 2
        self.assertAlmostEqual(two_run_evaluation["latency_ms"]["median"], expected_median)

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
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/profiles/demo_growth", "PUT",
                              {"positions": [{"ticker": "ALPHA.NS", "value": 10 ** 1000}]})
        self.assertEqual(raised.exception.code, 400)
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/analyses/not-a-run/extra")
        self.assertEqual(raised.exception.code, 404)
        connection = http.client.HTTPConnection("127.0.0.1", self.port, timeout=3)
        try:
            connection.request("POST", "/v1/analyses", body=b"", headers={"Content-Length": "-1"})
            response = connection.getresponse()
            self.assertEqual(response.status, 400)
            self.assertEqual(json.load(response)["error"], "BAD_INPUT")
        finally:
            connection.close()

    def test_portfolio_holdings_update_changes_suitability(self):
        _, before = self.request_json("/v1/profiles/demo_growth/portfolio")
        positions = [{"ticker": "ALPHA.NS", "value": 60000}, {"ticker": "BETA.NS", "value": 0},
                     {"ticker": "GAMMA.NS", "value": 0}, {"ticker": "DELTA.NS", "value": 0},
                     {"ticker": "CASH", "value": 40000}]
        _, updated = self.request_json("/v1/profiles/demo_growth", "PUT",
                                       {"positions": positions, "expected_revision": before["revision"]})
        self.assertEqual(updated["revision"], before["revision"] + 1)
        _, report = self.request_json("/v1/analyses", "POST",
                                      {"ticker": "ALPHA.NS", "investor_id": "demo_growth"})
        self.assertEqual(report["agents"]["risk"]["position_weight"], .6)
        self.assertTrue(report["synthesis"]["suitability_breach"])
        self.assertEqual(report["investor_snapshot"]["positions"], positions)

    def test_history_pagination_and_limits(self):
        for _ in range(3):
            self.request_json("/v1/analyses", "POST", {"ticker": "GAMMA.NS", "investor_id": "demo_growth"})
        _, first = self.request_json("/v1/analyses?investor_id=demo_growth&limit=2&offset=0")
        _, second = self.request_json("/v1/analyses?investor_id=demo_growth&limit=2&offset=2")
        self.assertEqual((first["count"], first["total"], first["has_more"]), (2, 3, True))
        self.assertEqual((second["count"], second["total"], second["has_more"]), (1, 3, False))
        self.assertFalse({item["run_id"] for item in first["runs"]} &
                         {item["run_id"] for item in second["runs"]})
        for query in ("limit=0", "limit=101", "offset=-1", "limit=abc", "offset=9223372036854775808"):
            with self.subTest(query=query), self.assertRaises(HTTPError) as raised:
                self.request_json("/v1/analyses?" + query)
            self.assertEqual(raised.exception.code, 400)

    def test_saved_report_corruption_is_detected_on_replay(self):
        _, report = self.request_json("/v1/analyses", "POST",
                                      {"ticker": "GAMMA.NS", "investor_id": "demo_growth"})
        db_path = os.path.join(self.tmp.name, "http.sqlite3")
        with closing(sqlite3.connect(db_path)) as db, db:
            original = db.execute("SELECT payload FROM runs WHERE id=?", (report["run_id"],)).fetchone()[0]
            changed = json.loads(original)
            changed["synthesis"]["next_step"] = "Corrupted content"
            db.execute("UPDATE runs SET payload=? WHERE id=?", (json.dumps(changed), report["run_id"]))
        try:
            with self.assertRaises(HTTPError) as raised:
                self.request_json("/v1/analyses/" + report["run_id"])
            self.assertEqual(raised.exception.code, 500)
            with raised.exception as response:
                self.assertEqual(json.load(response)["error"], "DATA_INTEGRITY")
        finally:
            with closing(sqlite3.connect(db_path)) as db, db:
                db.execute("UPDATE runs SET payload=? WHERE id=?", (original, report["run_id"]))


if __name__ == "__main__":
    unittest.main()
