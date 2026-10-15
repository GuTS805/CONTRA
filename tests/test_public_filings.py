"""The real-company example: exact SEC excerpts with checkable provenance."""
from datetime import date
from hashlib import sha256
import html
import unittest

from contra import llm, public_filings
from contra.core import prepare


class PublicFilingTests(unittest.TestCase):
    def test_documents_are_dated_hashed_and_sourced(self):
        spec = public_filings.example()
        docs = public_filings.documents()
        self.assertEqual(len(docs), 8)
        self.assertEqual(len({doc["id"] for doc in docs}), len(docs))
        for doc in docs:
            with self.subTest(doc=doc["id"]):
                self.assertEqual(doc["ticker"], "INFY.NS")
                self.assertEqual(doc["mode"], "PUBLIC_FILING")
                self.assertEqual(doc["source_hash"], "sha256:" + sha256(doc["excerpt"].encode()).hexdigest())
                self.assertTrue(doc["source_uri"].startswith("https://www.sec.gov/Archives/edgar/data/1067491/"))
                self.assertLessEqual(date.fromisoformat(doc["published_at"]), date.fromisoformat(spec["retrieved_at"]))
                self.assertTrue(20 <= len(doc["excerpt"]) <= 4000)
                self.assertEqual(doc["excerpt"], " ".join(doc["excerpt"].split()), "whitespace is collapsed")
                self.assertIn(doc["tone"], (-1.0, 0.0, 1.0))

    def test_shipped_model_tones_carry_an_exact_quote(self):
        docs = public_filings.documents()
        modelled = [doc for doc in docs if doc["tone_source"] == "MODEL_VERIFIED"]
        self.assertEqual(len(modelled), len(docs), "every shipped excerpt has a classified tone")
        for doc in modelled:
            with self.subTest(doc=doc["id"]):
                self.assertIsNone(llm.verify_tone({"tone": {1: "POSITIVE", -1: "NEGATIVE", 0: "NEUTRAL_OR_MIXED"}[doc["tone"]],
                                                   "quote": doc["tone_quote"]}, doc["excerpt"]))
                self.assertTrue(doc["tone_model"])

    def test_documents_pass_snapshot_integrity_checks(self):
        bars = [{"id": f"BAR-INFY.NS-2026-{month:02d}-{day:02d}", "ticker": "INFY.NS",
                 "trade_date": f"2026-{month:02d}-{day:02d}", "close": 1500.0, "volume": 1000, "mode": "LIVE"}
                for month in (6, 7, 8) for day in range(1, 29)]
        snapshot = prepare("INFY.NS", "2026-08-28", bars, public_filings.documents(), "yahoo_chart_daily_v1", "LIVE")
        self.assertEqual(len(snapshot["documents"]), 8)
        earlier = prepare("INFY.NS", "2026-07-01", bars, public_filings.documents(), "yahoo_chart_daily_v1", "LIVE")
        self.assertEqual(sorted(doc["id"] for doc in earlier["documents"]),
                         ["E-INFY-P05", "E-INFY-P06", "E-INFY-P07", "E-INFY-P08"], "July filings are not visible on July 1")

    def test_verify_matches_exact_text_across_markup(self):
        excerpts = public_filings.example()["excerpts"]

        def page(url, drop=None):
            parts = []
            for item in excerpts:
                if item["source_uri"] == url and item["id"] != drop:
                    words = html.escape(item["excerpt"], quote=False).split(" ")
                    middle = len(words) // 2
                    # Markup and line breaks inside a passage must not affect the match.
                    parts.append("<p>" + " ".join(words[:middle]) + "\n <span>" + " ".join(words[middle:]) + "</span></p>")
            return "<html><body>" + "<div>unrelated text</div>".join(parts) + "</body></html>"

        self.assertEqual(public_filings.verify("test", fetch=page), [])
        problems = public_filings.verify("test", fetch=lambda url: page(url, drop="E-INFY-P07"))
        self.assertEqual(len(problems), 1)
        self.assertTrue(problems[0].startswith("E-INFY-P07: not found in https://www.sec.gov/"))


if __name__ == "__main__":
    unittest.main()
