"""The backtest: no look-ahead, correct metrics and a shipped report whose numbers agree with each other."""
import json
import unittest
from datetime import date, timedelta
from pathlib import Path

from contra import backtest


def bars(closes, ticker="TEST.NS", volumes=None):
    start, out = date(2024, 1, 1), []
    for i, close in enumerate(closes):
        day = start + timedelta(days=i)
        out.append({"id": f"BAR-{ticker}-{day}", "ticker": ticker, "trade_date": day.isoformat(), "close": float(close),
                    "volume": (volumes or [1000] * len(closes))[i], "mode": "LIVE"})
    return out


class BacktestTests(unittest.TestCase):
    def test_signals_use_only_bars_up_to_their_date(self):
        series = [100 + i * 0.5 + (i % 7) for i in range(160)]
        first, _ = backtest.observations(bars(series))
        # Move every later close by 10% (below the artefact filter). Labels up to the change must not move.
        shifted = series[:70] + [value * 1.10 for value in series[70:]]
        second, _ = backtest.observations(bars(shifted))
        cutoff = bars(series)[69]["trade_date"]
        early = lambda rows: [(r["date"], r["momentum"], r["volume"]) for r in rows if r["date"] <= cutoff]
        self.assertTrue(early(first))
        self.assertEqual(early(first), early(second), "rewriting the future must not change an earlier signal")
        self.assertNotEqual([r["forward"] for r in first], [r["forward"] for r in second], "the forward return does use the future")

    def test_forward_return_and_labels(self):
        rows, skipped = backtest.observations(bars([100 + i for i in range(100)]), horizon=21, stride=21)
        self.assertEqual(skipped, 0)
        self.assertTrue(rows and all(r["momentum"] == "BULLISH" for r in rows), "a steady rise is bullish")
        first = rows[0]
        self.assertAlmostEqual(first["forward"], (120 + 21) / 120 - 1, places=9)
        dates = [r["date"] for r in rows]
        self.assertEqual(len(dates), len(set(dates)))
        gaps = {(date.fromisoformat(b) - date.fromisoformat(a)).days for a, b in zip(dates, dates[1:])}
        self.assertEqual(gaps, {21}, "one window per horizon, so windows never overlap")

    def test_windows_with_a_data_artefact_are_excluded(self):
        series = [100.0] * 60 + [160.0] + [160.0] * 59
        rows, skipped = backtest.observations(bars(series))
        self.assertGreater(skipped, 0)
        self.assertFalse([r for r in rows if r["date"] in ("2024-02-29", "2024-03-01")], "no row spans the 60% jump")

    def test_hit_rate_baselines_and_interval(self):
        rows = [{"date": f"2024-01-{i + 1:02d}", "ticker": "T", "momentum": "BULLISH", "volume": "ORDINARY", "forward": .02}
                for i in range(8)]
        rows += [{"date": f"2024-02-{i + 1:02d}", "ticker": "T", "momentum": "BEARISH", "volume": "ELEVATED", "forward": .01}
                 for i in range(2)]
        result = backtest.evaluate(rows, permutations=200)
        self.assertEqual((result["directional"], result["hits"], result["hit_rate"]), (10, 8, 0.8))
        self.assertEqual(result["always_bullish_hit_rate"], 1.0)
        self.assertEqual(result["always_bearish_hit_rate"], 0.0)
        low, high = result["hit_rate_ci95"]
        self.assertTrue(low < 0.8 < high)
        self.assertEqual(backtest.wilson(0, 0), [0.0, 0.0])
        self.assertEqual(backtest.evaluate(rows, permutations=200), result, "the permutation baseline is seeded")

    def test_chronological_split_keeps_held_out_strictly_later(self):
        rows = [{"date": f"2024-{m:02d}-{d:02d}", "ticker": "T", "momentum": "BULLISH", "volume": "ORDINARY", "forward": .01}
                for m in range(1, 11) for d in (5, 20)]
        development, held_out, cut = backtest.split_by_date(rows)
        self.assertTrue(max(r["date"] for r in development) < cut <= min(r["date"] for r in held_out))
        self.assertEqual(len(development) + len(held_out), len(rows))
        self.assertEqual(backtest.majority_baseline(development, held_out)["guess"], "UP")

    def test_shipped_report_is_internally_consistent(self):
        # The container image copies only data/fixtures, so the report must live there to reach the hosted app.
        self.assertEqual(backtest.REPORT.parent.name, "fixtures")
        report = json.loads(backtest.REPORT.read_text(encoding="utf-8"))
        for key in ("all", "development", "held_out"):
            part = report[key]
            self.assertEqual(round(part["hits"] / part["directional"], 4), part["hit_rate"], key)
            low, high = part["hit_rate_ci95"]
            self.assertTrue(low <= part["hit_rate"] <= high, key)
            self.assertLessEqual(part["directional"], part["observations"], key)
        self.assertEqual(report["all"]["observations"], report["development"]["observations"] + report["held_out"]["observations"])
        self.assertEqual(len(report["sources"]), len(report["parameters"]["universe"]))
        self.assertTrue(all(len(s["closes_sha256"]) == 64 for s in report["sources"]))
        self.assertGreaterEqual(len(report["caveats"]), 4)
        self.assertEqual(report["parameters"]["stride_sessions"], report["parameters"]["horizon_sessions"])


if __name__ == "__main__":
    unittest.main()
