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
from datetime import date, datetime, timedelta, timezone
from http.cookiejar import CookieJar
from urllib.error import HTTPError
from urllib.request import HTTPCookieProcessor, Request, build_opener, urlopen


class HttpTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        with socket.socket() as sock:
            sock.bind(("127.0.0.1", 0))
            cls.port = sock.getsockname()[1]
        cls.base = f"http://127.0.0.1:{cls.port}"
        env = {**os.environ, "CONTRA_DB": os.path.join(cls.tmp.name, "http.sqlite3"),
               "CONTRA_PORT": str(cls.port), "CONTRA_HOST": "127.0.0.1",
               # Keep a developer's .env key from turning tests into paid model calls.
               "CONTRA_LLM": "0", "CONTRA_ENV_FILE": os.devnull}
        cls.process = subprocess.Popen([sys.executable, "-m", "contra.server"],
                                       env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        deadline = time.monotonic() + 6
        while time.monotonic() < deadline:
            try:
                with urlopen(cls.base + "/health", timeout=.3) as response:
                    if json.load(response)["status"] == "ok":
                        cls.opener = cls.session()
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

    @classmethod
    def session(cls, path="/v1/auth/guest", data=None):
        """A cookie-carrying client logged in through the given auth route."""
        opener = build_opener(HTTPCookieProcessor(CookieJar()))
        request = Request(cls.base + path, data=json.dumps(data or {}).encode(), method="POST",
                          headers={"Content-Type": "application/json"})
        with opener.open(request, timeout=5) as response:
            response.read()
        return opener

    def request_json(self, path, method="GET", data=None, opener=None):
        body = json.dumps(data).encode() if data is not None else None
        request = Request(self.base + path, data=body, method=method,
                          headers={"Content-Type": "application/json"})
        with (opener or self.opener).open(request, timeout=5) as response:
            return response.status, json.load(response)

    def db_path(self):
        return os.path.join(self.tmp.name, "http.sqlite3")

    def test_loopback_origin_and_json_guards(self):
        cases = [
            ("GET", "/v1/stocks", None, {"Host": "attacker.example"}, 403, "INVALID_HOST"),
            ("GET", "/", None, {"Host": "attacker.example"}, 403, "INVALID_HOST"),
            ("POST", "/v1/analyses", b"{}", {"Content-Type": "application/json", "Origin": "https://attacker.example"}, 403, "INVALID_ORIGIN"),
            ("PUT", "/v1/profiles/demo_growth", b"{}", {"Content-Type": "text/plain"}, 415, "UNSUPPORTED_MEDIA_TYPE"),
        ]
        for method, path, body, headers, expected, code in cases:
            with self.subTest(code=code):
                request = Request(self.base + path, data=body, method=method, headers=headers)
                with self.assertRaises(HTTPError) as caught:
                    urlopen(request, timeout=5)
                self.assertEqual(caught.exception.code, expected)
                self.assertEqual(json.load(caught.exception)["error"], code)
        status, health = self.request_json("/health")
        self.assertEqual((status, health["status"]), (200, "ok"))
        with urlopen(self.base + "/", timeout=5) as response:
            self.assertEqual(response.headers["X-Content-Type-Options"], "nosniff")
            self.assertIn("frame-ancestors 'none'", response.headers["Content-Security-Policy"])

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
        self.assertEqual(report["recommendation"]["action"], "REDUCE_EXPOSURE")
        _, history_row = self.request_json("/v1/analyses?investor_id=demo_conservative&limit=1")
        self.assertEqual(history_row["runs"][0]["action"], "REDUCE_EXPOSURE")
        _, answer = self.request_json(f"/v1/analyses/{report['run_id']}/ask?q=operating%20margin%20costs")
        self.assertEqual(answer["passages"][0]["id"], "E-ALPHA-01")
        _, cited_answer = self.request_json(f"/v1/analyses/{report['run_id']}/evidence/{answer['passages'][0]['id']}")
        self.assertEqual(cited_answer["excerpt"], answer["passages"][0]["excerpt"])
        for path, expected in ((f"/v1/analyses/{report['run_id']}/ask", 400),
                               (f"/v1/analyses/{report['run_id']}/ask?q=" + "x" * 301, 400),
                               ("/v1/analyses/run_missing/ask?q=margin", 404),
                               ("/v1/profiles/nobody/insights", 404)):
            with self.subTest(path=path[:60]):
                with self.assertRaises(HTTPError) as caught:
                    self.request_json(path)
                self.assertEqual(caught.exception.code, expected)
        _, insights = self.request_json("/v1/profiles/demo_growth/insights")
        self.assertEqual(insights["profile_id"], "demo_growth")
        self.assertTrue(all({"ticker", "weight", "cap", "breach", "trim_to_cap", "headroom_value"} <= set(h)
                            for h in insights["holdings"]))
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
            connection.request("POST", "/v1/analyses", body=b"", headers={"Content-Length": "-1", "Content-Type": "application/json",
                                                                          "Host": f"127.0.0.1:{self.port}"})
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
        db_path = self.db_path()
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

    def test_accounts_are_required_and_isolated(self):
        with self.assertRaises(HTTPError) as raised:
            urlopen(self.base + "/v1/profiles", timeout=5)
        self.assertEqual((raised.exception.code, json.load(raised.exception)["error"]), (401, "AUTH_REQUIRED"))
        with urlopen(self.base + "/", timeout=5) as response:
            self.assertEqual(response.status, 200, "the login page itself is public")
        alice = self.session("/v1/auth/signup", {"username": "alice_test", "password": "correct horse"})
        _, me = self.request_json("/v1/auth/me", opener=alice)
        self.assertEqual((me["username"], me["is_guest"]), ("alice_test", False))
        with self.assertRaises(HTTPError) as raised:
            self.session("/v1/auth/signup", {"username": "ALICE_test", "password": "another pass"})
        self.assertEqual(raised.exception.code, 400, "usernames are unique regardless of case")
        with self.assertRaises(HTTPError) as raised:
            self.session("/v1/auth/login", {"username": "alice_test", "password": "wrong password"})
        self.assertEqual(raised.exception.code, 401)
        with self.assertRaises(HTTPError) as raised:
            self.session("/v1/auth/signup", {"username": "bob", "password": "short"})
        self.assertEqual(raised.exception.code, 400)
        _, report = self.request_json("/v1/analyses", "POST", {"ticker": "ALPHA.NS", "investor_id": "demo_conservative"},
                                      opener=alice)
        _, updated = self.request_json("/v1/profiles/demo_growth", "PUT", {"max_single_asset_weight": .2}, opener=alice)
        self.assertEqual(updated["max_single_asset_weight"], .2)
        stranger = self.session()
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/analyses/" + report["run_id"], opener=stranger)
        self.assertEqual(raised.exception.code, 404, "another account cannot open this run")
        _, history = self.request_json("/v1/analyses", opener=stranger)
        self.assertEqual(history["total"], 0)
        _, theirs = self.request_json("/v1/profiles/demo_growth/portfolio", opener=stranger)
        self.assertEqual(theirs["max_single_asset_weight"], .3, "profile edits stay with their owner")
        again = self.session("/v1/auth/login", {"username": "alice_test", "password": "correct horse"})
        _, mine = self.request_json("/v1/analyses/" + report["run_id"], opener=again)
        self.assertEqual(mine["run_id"], report["run_id"])
        self.request_json("/v1/auth/logout", "POST", {}, opener=again)
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/auth/me", opener=again)
        self.assertEqual(raised.exception.code, 401)

    def test_live_symbol_with_uploaded_filing(self):
        user = self.session()
        _, me = self.request_json("/v1/auth/me", opener=user)
        today = date.today()
        bars, day = [], today - timedelta(days=60)
        while day < today:
            if day.weekday() < 5:
                bars.append({"id": f"BAR-TEST.NS-{day}", "ticker": "TEST.NS", "trade_date": day.isoformat(),
                             "close": float(100 + len(bars)), "volume": 1000 + len(bars), "mode": "LIVE",
                             "origin": "yahoo_finance_chart", "source_uri": "https://query1.finance.yahoo.com/x",
                             "timezone": "Asia/Kolkata", "adjusted": False})
            day += timedelta(days=1)
        # Seed the price cache directly so the test never calls Yahoo Finance.
        with closing(sqlite3.connect(self.db_path())) as db, db:
            db.execute("INSERT OR REPLACE INTO market_bars(ticker,payload,fetched_at) VALUES (?,?,?)",
                       ("TEST.NS", json.dumps(bars), datetime.now(timezone.utc).isoformat()))
            db.execute("INSERT INTO user_securities(owner_id,ticker,name,sector,added_at) VALUES (?,?,?,?,?)",
                       (me["id"], "TEST.NS", "Test Industries", "Industrials", "2026-01-01"))
        _, catalog = self.request_json("/v1/stocks", opener=user)
        listed = next(item for item in catalog["stocks"] if item["ticker"] == "TEST.NS")
        self.assertEqual((listed["mode"], listed["last_date"]), ("LIVE", bars[-1]["trade_date"]))
        _, filing = self.request_json("/v1/documents", "POST", {
            "ticker": "TEST.NS", "title": "Quarterly results", "published_at": (today - timedelta(days=5)).isoformat(),
            "excerpt": "Revenue grew and operating margin improved after record orders were awarded.",
            "source_uri": "https://example.com/filing.pdf"}, opener=user)
        self.assertGreater(filing["tone"], 0)
        self.assertEqual(filing["tone_source"], "LEXICON_HEURISTIC")
        bad_filings = ({"ticker": "ALPHA.NS", "title": "Fixture", "published_at": "2026-01-01", "excerpt": "x" * 30},
                       {"ticker": "TEST.NS", "title": "Future", "published_at": (today + timedelta(days=3)).isoformat(),
                        "excerpt": "A filing from the future should never be accepted."},
                       {"ticker": "TEST.NS", "title": "Bad link", "published_at": "2026-01-01",
                        "excerpt": "This filing has an unsafe source link.", "source_uri": "javascript:alert(1)"})
        for payload in bad_filings:
            with self.subTest(title=payload["title"]), self.assertRaises(HTTPError) as raised:
                self.request_json("/v1/documents", "POST", payload, opener=user)
            self.assertEqual(raised.exception.code, 400)
        self.request_json("/v1/profiles/demo_growth", "PUT", {"positions": [
            {"ticker": "TEST.NS", "value": 40000}, {"ticker": "CASH", "value": 60000}]}, opener=user)
        _, report = self.request_json("/v1/analyses", "POST", {"ticker": "TEST.NS", "investor_id": "demo_growth"},
                                      opener=user)
        self.assertEqual((report["data_mode"], report["dataset_id"]), ("LIVE", "yahoo_chart_daily_v1"))
        self.assertEqual(report["as_of"], bars[-1]["trade_date"])
        self.assertEqual(report["signals"]["momentum"]["label"], "BULLISH")
        self.assertEqual(report["evidence"][0]["id"], filing["id"])
        self.assertEqual(report["agents"]["risk"]["sector"], "Industrials")
        self.assertEqual(report["recommendation"]["action"], "REDUCE_EXPOSURE")
        _, replay = self.request_json("/v1/analyses/" + report["run_id"], opener=user)
        self.assertEqual(replay, report)
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/securities/TEST.NS", "DELETE", opener=user)
        self.assertEqual(raised.exception.code, 409, "a held symbol cannot be removed")
        self.request_json("/v1/documents/" + filing["id"], "DELETE", opener=user)
        with self.assertRaises(HTTPError) as raised:
            self.request_json("/v1/securities", "POST", {"ticker": "not a symbol", "sector": "Energy"}, opener=user)
        self.assertEqual(raised.exception.code, 400)


    def test_public_filings_example(self):
        user = self.session()
        _, me = self.request_json("/v1/auth/me", opener=user)
        today = date.today()
        bars, day = [], today - timedelta(days=60)
        while day < today:
            if day.weekday() < 5:
                bars.append({"id": f"BAR-INFY.NS-{day}", "ticker": "INFY.NS", "trade_date": day.isoformat(),
                             "close": float(1500 - len(bars)), "volume": 5000 + len(bars), "mode": "LIVE",
                             "origin": "yahoo_finance_chart", "source_uri": "https://query1.finance.yahoo.com/x",
                             "timezone": "Asia/Kolkata", "adjusted": False})
            day += timedelta(days=1)
        # Seed the symbol so the test never calls Yahoo Finance.
        with closing(sqlite3.connect(self.db_path())) as db, db:
            db.execute("INSERT OR REPLACE INTO market_bars(ticker,payload,fetched_at) VALUES (?,?,?)",
                       ("INFY.NS", json.dumps(bars), datetime.now(timezone.utc).isoformat()))
            db.execute("INSERT INTO user_securities(owner_id,ticker,name,sector,added_at) VALUES (?,?,?,?,?)",
                       (me["id"], "INFY.NS", "Infosys Limited", "Technology", "2026-01-01"))
        status, loaded = self.request_json("/v1/examples/public-filings", "POST", {}, opener=user)
        self.assertEqual((status, loaded["ticker"], loaded["added_documents"], loaded["document_count"]),
                         (201, "INFY.NS", 8, 8))
        _, again = self.request_json("/v1/examples/public-filings", "POST", {}, opener=user)
        self.assertEqual((again["added_documents"], again["document_count"]), (0, 8), "loading twice adds nothing")
        _, library = self.request_json("/v1/evidence", opener=user)
        sec = [doc for doc in library["documents"] if doc["ticker"] == "INFY.NS"]
        self.assertEqual({doc["mode"] for doc in sec}, {"PUBLIC_FILING"})
        self.assertTrue(all(doc["source_uri"].startswith("https://www.sec.gov/Archives/edgar/data/1067491/")
                            for doc in sec))
        _, report = self.request_json("/v1/analyses", "POST", {"ticker": "INFY.NS", "investor_id": "demo_growth"},
                                      opener=user)
        self.assertEqual(report["data_mode"], "LIVE")
        self.assertTrue(report["evidence"])
        self.assertTrue(all(item["id"].startswith("E-INFY-P") for item in report["evidence"]))
        _, answer = self.request_json(f"/v1/analyses/{report['run_id']}/ask?q=outstanding%20borrowings", opener=user)
        self.assertEqual(answer["passages"][0]["id"], "E-INFY-P07")
        _, cited = self.request_json(f"/v1/analyses/{report['run_id']}/evidence/E-INFY-P07", opener=user)
        self.assertEqual(cited["form"], "Form 20-F for the year ended March 31, 2026")
        _, other = self.request_json("/v1/evidence", opener=self.session())
        self.assertFalse([doc for doc in other["documents"] if doc["ticker"] == "INFY.NS"],
                         "one account's example stays out of another's library")

if __name__ == "__main__":
    unittest.main()
