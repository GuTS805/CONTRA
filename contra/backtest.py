"""Walk-forward check of CONTRA's price signals against what the price did next.

    python -m contra.backtest

fetches about five years of daily NSE closes from Yahoo Finance, recomputes the Market agent's momentum
and volume signals at past dates with the same code the app uses (only bars up to that date), and
compares each directional label with the next 21 sessions (about 30 calendar days). The settings below
were fixed before the first run and were not tuned on the result. The report is written to
data/fixtures/backtest.json and shown in the Evaluation view.

Only the price signals can be tested this way. Filing tone and institutional flows need point-in-time
archives that CONTRA does not hold, so they are not backtested.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
import math
from pathlib import Path
import random
import sys
from urllib.parse import quote

from . import live
from .core import numeric_signals

REPORT = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "backtest.json"

UNIVERSE = ["RELIANCE", "TCS", "HDFCBANK", "ICICIBANK", "INFY", "HINDUNILVR", "ITC", "SBIN", "BHARTIARTL",
            "KOTAKBANK", "LT", "AXISBANK", "ASIANPAINT", "MARUTI", "SUNPHARMA", "TITAN", "NTPC", "ULTRACEMCO",
            "NESTLEIND", "POWERGRID"]
HISTORY_RANGE = "5y"
HORIZON = 21          # sessions ahead, about 30 calendar days
STRIDE = HORIZON      # one observation per symbol per horizon, so windows never overlap
DEVELOPMENT_SHARE = .7
MAX_DAILY_MOVE = .30  # a larger one-day move in a large cap is treated as a data artefact
PERMUTATIONS = 5000
SEED = 42
DIRECTION = {"BULLISH": 1, "BEARISH": -1}


def fetch_history(ticker: str) -> list[dict]:
    url = live.CHART_URL.format(symbol=quote(ticker)).replace("range=6mo", f"range={HISTORY_RANGE}")
    return live.parse_chart(ticker, live._get_json(url))[1]


def has_artefact(bars: list[dict], start: int, end: int) -> bool:
    return any(abs(bars[i]["close"] / bars[i - 1]["close"] - 1) > MAX_DAILY_MOVE for i in range(max(1, start), end + 1))


def observations(bars: list[dict], horizon: int = HORIZON, stride: int = STRIDE) -> tuple[list[dict], int]:
    """Signals at past dates from the bars up to that date only, with the return over the next `horizon` sessions."""
    rows, skipped = [], 0
    for t in range(20, len(bars) - horizon, stride):
        if has_artefact(bars, t - 20, t + horizon):
            skipped += 1
            continue
        window = bars[t - 20:t + 1]
        signals = numeric_signals({"bars": window, "as_of": window[-1]["trade_date"]})
        if signals["momentum"]["status"] != "OK":
            continue
        rows.append({"date": window[-1]["trade_date"], "ticker": window[-1]["ticker"],
                     "momentum": signals["momentum"]["label"], "volume": signals["volume"]["label"],
                     "forward": bars[t + horizon]["close"] / bars[t]["close"] - 1})
    return rows, skipped


def wilson(hits: int, n: int, z: float = 1.96) -> list[float]:
    """95% interval for a proportion. Cross-sectional correlation makes the real interval wider."""
    if n == 0:
        return [0.0, 0.0]
    p = hits / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return [round(centre - half, 4), round(centre + half, 4)]


def _hit(label: str, forward: float) -> bool:
    return (forward > 0) if DIRECTION[label] > 0 else (forward < 0)


def _mean(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 5) if values else None


def evaluate(rows: list[dict], seed: int = SEED, permutations: int = PERMUTATIONS) -> dict:
    """Hit rate of directional labels with a coin-flip-style baseline set, on one set of rows."""
    directional = [r for r in rows if r["momentum"] in DIRECTION]
    hits = sum(_hit(r["momentum"], r["forward"]) for r in directional)
    n = len(directional)
    up = sum(r["forward"] > 0 for r in directional)
    # Permutation baseline: the same labels dealt to random rows, so base rates and label mix are preserved.
    rng, labels, forwards = random.Random(seed), [r["momentum"] for r in directional], [r["forward"] for r in directional]
    at_least = 0
    for _ in range(permutations):
        rng.shuffle(labels)
        at_least += sum(_hit(label, forward) for label, forward in zip(labels, forwards)) >= hits
    by_label = {label: [r["forward"] for r in rows if r["momentum"] == label] for label in ("BULLISH", "NEUTRAL", "BEARISH")}
    elevated = [abs(r["forward"]) for r in rows if r["volume"] == "ELEVATED"]
    ordinary = [abs(r["forward"]) for r in rows if r["volume"] == "ORDINARY"]
    return {"observations": len(rows), "directional": n, "coverage": round(n / len(rows), 4) if rows else None,
            "hits": hits, "hit_rate": round(hits / n, 4) if n else None, "hit_rate_ci95": wilson(hits, n),
            "always_bullish_hit_rate": round(up / n, 4) if n else None,
            "always_bearish_hit_rate": round((n - up) / n, 4) if n else None,
            "permutation_p_value": round((at_least + 1) / (permutations + 1), 4) if n else None,
            "mean_forward_return": {label: {"n": len(values), "mean": _mean(values)} for label, values in by_label.items()},
            "bullish_minus_bearish": (round(_mean(by_label["BULLISH"]) - _mean(by_label["BEARISH"]), 5)
                                      if by_label["BULLISH"] and by_label["BEARISH"] else None),
            "volume_participation": {"elevated": {"n": len(elevated), "mean_abs_forward": _mean(elevated)},
                                     "ordinary": {"n": len(ordinary), "mean_abs_forward": _mean(ordinary)}}}


def split_by_date(rows: list[dict], share: float = DEVELOPMENT_SHARE) -> tuple[list[dict], list[dict], str]:
    """Chronological split on dates, so the held-out part is entirely later than the development part."""
    dates = sorted({r["date"] for r in rows})
    cut = dates[int(len(dates) * share)]
    return [r for r in rows if r["date"] < cut], [r for r in rows if r["date"] >= cut], cut


def majority_baseline(development: list[dict], held_out: list[dict]) -> dict:
    """Predict, for every held-out row, the direction that was more common in the development period."""
    dev = [r["forward"] > 0 for r in development if r["momentum"] in DIRECTION]
    guess_up = sum(dev) * 2 >= len(dev)
    rows = [r for r in held_out if r["momentum"] in DIRECTION]
    hits = sum((r["forward"] > 0) == guess_up for r in rows)
    return {"guess": "UP" if guess_up else "DOWN", "n": len(rows), "hit_rate": round(hits / len(rows), 4) if rows else None}


def by_year(rows: list[dict]) -> dict:
    out = {}
    for year in sorted({r["date"][:4] for r in rows}):
        part = [r for r in rows if r["date"][:4] == year and r["momentum"] in DIRECTION]
        hits = sum(_hit(r["momentum"], r["forward"]) for r in part)
        out[year] = {"directional": len(part), "hit_rate": round(hits / len(part), 4) if part else None}
    return out


def build_report(histories: dict[str, list[dict]], generated_at: str | None = None) -> dict:
    rows, skipped, sources = [], 0, []
    for ticker, bars in histories.items():
        part, dropped = observations(bars)
        rows += part
        skipped += dropped
        sources.append({"ticker": ticker, "bars": len(bars), "first": bars[0]["trade_date"], "last": bars[-1]["trade_date"],
                        "closes_sha256": sha256(json.dumps([[b["trade_date"], b["close"]] for b in bars]).encode()).hexdigest()})
    development, held_out, cut = split_by_date(rows)
    return {"generated_at": generated_at or datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "parameters": {"universe": list(histories), "history_range": HISTORY_RANGE, "horizon_sessions": HORIZON,
                           "stride_sessions": STRIDE, "development_share": DEVELOPMENT_SHARE, "split_date": cut,
                           "max_daily_move_excluded": MAX_DAILY_MOVE, "permutations": PERMUTATIONS, "seed": SEED,
                           "signal": "numeric_signals momentum label (±3% over 20 sessions), computed from bars up to each date"},
            "excluded_windows_with_data_artefacts": skipped,
            "all": evaluate(rows), "development": evaluate(development), "held_out": evaluate(held_out),
            "held_out_majority_baseline": majority_baseline(development, held_out),
            "hit_rate_by_year": by_year(rows), "sources": sources,
            "caveats": [
                "Only the Market agent's price momentum and volume are tested. Filing tone and institutional flows are not, because CONTRA holds no point-in-time archive of them.",
                "The universe is 20 NSE large caps chosen because they trade today, so survivorship bias flatters any result.",
                "Closes come from Yahoo Finance's unofficial endpoint and are not adjusted for dividends. No trading costs, slippage or position sizing are modelled.",
                "Observations are non-overlapping per symbol, but stocks move together in the same months, so the confidence intervals are narrower than the true uncertainty.",
                "The thresholds (±3% over 20 sessions) were fixed before this run and were not tuned on it. A hit rate close to the base rate means no demonstrated predictive edge. CONTRA's signals are descriptive."]}


def main() -> None:
    histories = {}
    for symbol in UNIVERSE:
        ticker = symbol + ".NS"
        try:
            histories[ticker] = fetch_history(ticker)
            print(f"{ticker}: {len(histories[ticker])} bars", file=sys.stderr)
        except (live.UpstreamError, ValueError) as exc:
            print(f"{ticker}: skipped ({exc})", file=sys.stderr)
    if len(histories) < 15:
        raise SystemExit("Too few symbols could be fetched; not writing a report.")
    report = build_report(histories)
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(json.dumps(report, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    held = report["held_out"]
    print(f"All: {report['all']['hit_rate']} over {report['all']['directional']} directional windows "
          f"(always-bullish {report['all']['always_bullish_hit_rate']}, permutation p {report['all']['permutation_p_value']})")
    print(f"Held-out: {held['hit_rate']} over {held['directional']} (majority baseline {report['held_out_majority_baseline']['hit_rate']})")
    print(f"Wrote {REPORT}")


if __name__ == "__main__":
    main()
