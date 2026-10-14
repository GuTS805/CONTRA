"""Reproducible, explicitly synthetic demo data."""
from __future__ import annotations

from datetime import date, timedelta
from hashlib import sha256
import json
import random

DATASET_ID = "contra_synthetic_v1"
AS_OF = "2026-10-13"
START = date(2026, 6, 8)

STOCKS = {
    "ALPHA.NS": {"name": "Alpha Systems (simulated)", "sector": "Technology", "scenario": "conflict", "trend": 0.0032, "seed": 11},
    "BETA.NS": {"name": "Beta Industries (simulated)", "sector": "Technology", "scenario": "neutral", "trend": 0.0003, "seed": 22},
    "GAMMA.NS": {"name": "Gamma Energy (simulated)", "sector": "Energy", "scenario": "aligned", "trend": 0.0035, "seed": 33},
    "DELTA.NS": {"name": "Delta Materials (simulated)", "sector": "Materials", "scenario": "missing_filing", "trend": -0.003, "seed": 44},
}

DOC_FACTS = {
    "ALPHA.NS": [
        (-1, "Quarterly margin update", "Operating margin narrowed as component costs rose despite stronger reported revenue.", -1),
        (-17, "Supply chain note", "Management reported higher procurement costs and a delayed customer delivery schedule.", -1),
        (-33, "Customer update", "A large customer renewed a multiyear contract, adding to the order book.", 1),
        (-220, "Historical business note", "An older update described margin pressure in a prior reporting period.", -1),
    ],
    "BETA.NS": [
        (-3, "Quarterly operations", "Revenue was steady while operating costs remained broadly unchanged.", 0),
        (-20, "Capital allocation", "The board maintained the existing capital expenditure plan.", 0),
        (-42, "Demand update", "Orders improved in one segment but weakened in another segment.", 0),
        (-70, "Annual statement", "Management noted mixed regional demand and stable cash balances.", 0),
    ],
    "GAMMA.NS": [
        (-2, "Quarterly results", "Operating margin improved and revenue increased after new contracts commenced.", 1),
        (-15, "Contract update", "The company reported new long term supply contracts with contracted revenue.", 1),
        (-31, "Cash flow note", "Operating cash flow rose and net debt decreased during the period.", 1),
        (-48, "Capacity statement", "A new facility entered service and increased production capacity.", 1),
    ],
    "DELTA.NS": [
        (2, "Future filing excluded", "This future dated document must not appear in an earlier analysis.", 1),
        (5, "Future operations excluded", "This later document is outside the analysis cutoff.", -1),
        (8, "Future cash note excluded", "Later cash information is unavailable at the selected date.", 0),
        (12, "Future outlook excluded", "This later outlook is unavailable at the selected date.", 1),
    ],
}


def bars_for(ticker: str) -> list[dict]:
    spec = STOCKS[ticker]
    rng = random.Random(spec["seed"])
    current = START
    close = 100.0 + spec["seed"]
    bars = []
    while current <= date.fromisoformat(AS_OF):
        if current.weekday() < 5:
            close *= 1 + spec["trend"] + rng.uniform(-0.002, 0.002)
            volume = int(100000 + rng.uniform(-12000, 12000))
            bars.append({"id": f"BAR-{ticker}-{current.isoformat()}", "ticker": ticker,
                         "trade_date": current.isoformat(), "close": round(close, 4),
                         "volume": volume, "mode": "SYNTHETIC", "origin": "generated_fixture",
                         "timezone": "Asia/Kolkata", "adjusted": False,
                         "fixture_as_of": AS_OF, "ingested_at": "2026-10-13T18:00:00+05:30"})
        current += timedelta(days=1)
    if ticker in ("ALPHA.NS", "GAMMA.NS"):
        bars[-1]["volume"] = 182000
    return bars


def documents() -> list[dict]:
    out = []
    cutoff = date.fromisoformat(AS_OF)
    for ticker, rows in DOC_FACTS.items():
        for index, (offset, title, text, tone) in enumerate(rows, 1):
            doc_id = f"DOC-{ticker.split('.')[0]}-{index:02d}"
            out.append({"id": f"E-{ticker.split('.')[0]}-{index:02d}", "document_id": doc_id,
                        "ticker": ticker, "title": title, "published_at": (cutoff + timedelta(days=offset)).isoformat(),
                        "excerpt": text, "char_start": 0, "char_end": len(text), "tone": tone,
                        "mode": "SYNTHETIC", "source_type": "synthetic_filing_excerpt",
                        "source_uri": f"fixture://{DATASET_ID}/{doc_id}",
                        "source_hash": "sha256:" + sha256(text.encode()).hexdigest()})
    return out


def dataset_hash() -> str:
    payload = {"bars": {ticker: bars_for(ticker) for ticker in STOCKS}, "documents": documents()}
    return "sha256:" + sha256(json.dumps(payload, sort_keys=True).encode()).hexdigest()
