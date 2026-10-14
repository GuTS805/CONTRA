from datetime import date, datetime, timezone
import unittest
from unittest.mock import patch

from contra import live


def chart(stamps, closes, volumes):
    return {"chart": {"result": [{"meta": {"longName": "Reliance Industries Limited", "currency": "INR",
                                           "exchangeTimezoneName": "Asia/Kolkata"},
                                  "timestamp": stamps,
                                  "indicators": {"quote": [{"close": closes, "volume": volumes}]}}], "error": None}}


# 11:30 IST on 12-14 October 2026.
STAMPS = [1791784800, 1791871200, 1791957600]


class LiveDataTests(unittest.TestCase):
    def test_parse_keeps_completed_bars_and_drops_forming_or_invalid_ones(self):
        during_session = datetime(2026, 10, 14, 6, 0, tzinfo=timezone.utc)  # 11:30 IST
        name, bars = live.parse_chart("RELIANCE.NS", chart(STAMPS, [1150.5, None, 1170.0], [10, 20, 30]), during_session)
        self.assertEqual(name, "Reliance Industries Limited")
        self.assertEqual([b["trade_date"] for b in bars], ["2026-10-12"], "null close and today's forming bar are dropped")
        self.assertEqual(bars[0]["id"], "BAR-RELIANCE.NS-2026-10-12")
        self.assertEqual((bars[0]["mode"], bars[0]["currency"], bars[0]["adjusted"]), ("LIVE", "INR", False))
        after_close = datetime(2026, 10, 14, 12, 0, tzinfo=timezone.utc)  # 17:30 IST
        _, bars = live.parse_chart("RELIANCE.NS", chart(STAMPS, [1150.5, 1160.0, 1170.0], [10, 0, 30]), after_close)
        self.assertEqual([b["trade_date"] for b in bars], ["2026-10-12", "2026-10-14"], "zero-volume days are dropped")

    def test_unknown_symbol_and_bad_tickers(self):
        with self.assertRaisesRegex(ValueError, "delisted"):
            live.parse_chart("NOPE.NS", {"chart": {"result": None, "error": {"description": "symbol may be delisted"}}})
        for value in ("reliance", "RELIANCE", "../x.NS", "A" * 25 + ".NS", None):
            with self.subTest(value=value), self.assertRaises(ValueError):
                live.normalize_ticker(value)
        self.assertEqual(live.normalize_ticker(" reliance.ns "), "RELIANCE.NS")
        self.assertEqual(live.normalize_ticker("500325.BO"), "500325.BO")

    def test_provider_failure_falls_back_to_cache(self):
        cached = [{"trade_date": "2026-10-12"}]
        with patch("contra.live.store.cached_bars", return_value=(cached, "2026-01-01T00:00:00+00:00")), \
             patch("contra.live.fetch", side_effect=live.UpstreamError("Yahoo Finance could not be reached")):
            bars, warnings = live.bars(None, "RELIANCE.NS")
        self.assertEqual(bars, cached)
        self.assertIn("using prices cached", warnings[0])
        with patch("contra.live.store.cached_bars", return_value=(None, None)), \
             patch("contra.live.fetch", side_effect=live.UpstreamError("down")):
            with self.assertRaises(live.UpstreamError):
                live.bars(None, "RELIANCE.NS")

    def test_document_validation_and_tone(self):
        today = date(2026, 10, 14)
        doc = live.make_document("RELIANCE.NS", {"title": "Q2 results", "published_at": "2026-10-10",
                                                 "excerpt": "Net loss widened as refining margins declined."}, today)
        self.assertLess(doc["tone"], 0)
        self.assertTrue(doc["id"].startswith("E-RELIANCE-"))
        labeled = live.make_document("RELIANCE.NS", {"title": "Q2 results", "published_at": "2026-10-10", "tone": 1,
                                                     "excerpt": "Management commentary without clear tone words."}, today)
        self.assertEqual((labeled["tone"], labeled["tone_source"]), (1, "USER_LABEL"))
        for bad in ({"title": "Q2", "published_at": "2026-10-10", "excerpt": "x" * 30},
                    {"title": "Q2 results", "published_at": "2026-10-15", "excerpt": "x" * 30},
                    {"title": "Q2 results", "published_at": "2026-10-10", "excerpt": "x" * 30, "tone": True},
                    {"title": "Q2 results", "published_at": "2026-10-10", "excerpt": "x" * 30,
                     "source_uri": "http://insecure.example"}):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                live.make_document("RELIANCE.NS", bad, today)


if __name__ == "__main__":
    unittest.main()
