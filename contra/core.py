"""Snapshot analysis, independent agents, citation checks, and synthesis."""
from __future__ import annotations

import asyncio
from datetime import datetime, date, timezone
from hashlib import sha256
import json
from statistics import median
from time import perf_counter
import uuid

from .fixtures import AS_OF, DATASET_ID, STOCKS, bars_for, documents

METHOD_VERSION = "rules-1.0"


def stamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def digest(value) -> str:
    return "sha256:" + sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def confidence(coverage: float, freshness: float, margin: float, quality: float = 1.0) -> dict:
    parts = {"coverage": round(coverage, 3), "freshness": round(freshness, 3),
             "threshold_margin": round(margin, 3), "source_quality": round(quality, 3)}
    score = .35 * coverage + .30 * freshness + .20 * margin + .15 * quality
    return {"score": round(max(0, min(1, score)), 3), "components": parts,
            "meaning": "Heuristic evidence strength; not predictive accuracy"}


def prepare(ticker: str, as_of: str) -> dict:
    if ticker not in STOCKS:
        raise ValueError("Unknown ticker")
    try:
        cutoff = date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError("Invalid as_of date") from exc
    if cutoff > date.fromisoformat(AS_OF):
        raise ValueError("as_of exceeds available fixture dates")
    bars = [b for b in bars_for(ticker) if b["trade_date"] <= as_of]
    docs = [d for d in documents() if d["ticker"] == ticker and d["published_at"] <= as_of]
    market_hash = digest({"dataset": DATASET_ID, "ticker": ticker, "as_of": as_of,
                          "bars": bars, "documents": docs})
    return {"ticker": ticker, "as_of": as_of, "bars": bars, "documents": docs,
            "market_snapshot_hash": market_hash, "data_mode": "SYNTHETIC"}


def numeric_signals(snapshot: dict) -> dict:
    bars = snapshot["bars"]
    if len(bars) < 21 or any(b["close"] <= 0 or b["volume"] <= 0 for b in bars[-21:]):
        missing = {"status": "UNAVAILABLE", "label": "UNKNOWN", "value": None,
                   "evidence_confidence": None, "evidence_ids": [],
                   "reason": "At least 21 valid dated bars are required."}
        return {"momentum": dict(missing), "volume": dict(missing)}
    latest, prior = bars[-1], bars[-21]
    days_old = (date.fromisoformat(snapshot["as_of"]) - date.fromisoformat(latest["trade_date"])).days
    freshness = 1.0 if days_old <= 3 else max(0, 1 - days_old / 30)
    change = latest["close"] / prior["close"] - 1
    label = "BULLISH" if change > .03 else "BEARISH" if change < -.03 else "NEUTRAL"
    margin = min(1, abs(change - (.03 if change >= 0 else -.03)) / .1)
    momentum = {"status": "OK", "label": label, "value": round(change, 5), "unit": "20 trading day return",
                "evidence_ids": [prior["id"], latest["id"]], "evidence_confidence": confidence(1, freshness, margin),
                "reason": f"Close changed {change:+.1%} over 20 trading sessions; thresholds are ±3%."}
    typical = median(b["volume"] for b in bars[-21:-1])
    ratio = latest["volume"] / typical
    vlabel = "ELEVATED" if ratio > 1.5 else "SUPPRESSED" if ratio < .7 else "ORDINARY"
    vmargin = min(1, abs(ratio - (1.5 if ratio >= 1 else .7)) / 1.5)
    volume = {"status": "OK", "label": vlabel, "value": round(ratio, 3), "unit": "latest / prior 20 median",
              "evidence_ids": [latest["id"]], "evidence_confidence": confidence(1, freshness, vmargin),
              "reason": f"Latest volume is {ratio:.2f}× the median of the prior 20 sessions; volume is participation, not direction."}
    return {"momentum": momentum, "volume": volume}


def retrieve(snapshot: dict) -> list[dict]:
    """Tiny, reproducible lexical ranking over eligible, issuer-filtered excerpts."""
    terms = {"margin", "revenue", "cost", "cash", "debt", "contract", "demand", "order", "quarterly"}
    def score(doc):
        words = set(doc["excerpt"].lower().replace(".", "").split())
        return len(words & terms)
    return sorted(snapshot["documents"], key=lambda d: (score(d), d["published_at"]), reverse=True)[:5]


def filing_signal(snapshot: dict, retrieved: list[dict]) -> dict:
    if not retrieved:
        return {"status": "UNAVAILABLE", "label": "UNKNOWN", "value": None, "evidence_confidence": None,
                "evidence_ids": [], "reason": "No eligible filing excerpt existed by the as-of date."}
    # Fixture tone tags are attached to stored excerpts. No sentence is generated beyond cited facts.
    tone = sum(d["tone"] for d in retrieved) / len(retrieved)
    label = "POSITIVE" if tone > .2 else "NEGATIVE" if tone < -.2 else "MIXED"
    mixed = any(d["tone"] > 0 for d in retrieved) and any(d["tone"] < 0 for d in retrieved)
    if mixed:
        label = "MIXED"
    newest = max(date.fromisoformat(d["published_at"]) for d in retrieved)
    age = (date.fromisoformat(snapshot["as_of"]) - newest).days
    fresh = max(0, 1 - age / 180)
    status = "PARTIAL" if age > 120 else "OK"
    return {"status": status, "label": label, "value": round(tone, 3), "unit": "fixture fact-tone mean",
            "evidence_confidence": confidence(min(1, len(retrieved) / 3), fresh, min(1, abs(tone) / .8), .8),
            "evidence_ids": [d["id"] for d in retrieved],
            "reason": "Filing tone is computed from the cited synthetic excerpt tags; contradictory tags produce MIXED.",
            "warning": "Older filing evidence" if age > 120 else None}


async def timed_agent(name: str, compute):
    start = stamp()
    clock = perf_counter()
    try:
        # Each coroutine starts independently before the first await. The event loop
        # then gives each pipeline its own execution interval and timeout boundary.
        await asyncio.sleep(.025)
        result = compute()
    except Exception as exc:
        result = {"status": "ERROR", "assessment": "UNKNOWN", "facts": [],
                  "evidence_ids": [], "warnings": [str(exc)], "evidence_confidence": None}
    result.update({"agent": name, "started_at": start, "finished_at": stamp(),
                   "latency_ms": round((perf_counter() - clock) * 1000, 2),
                   "execution_mode": "DETERMINISTIC_FALLBACK", "model_version": None,
                   "method_version": METHOD_VERSION})
    return result


def market_agent(signals: dict) -> dict:
    m, v = signals["momentum"], signals["volume"]
    return {"status": "OK" if m["status"] == "OK" else "UNAVAILABLE",
            "assessment": m["label"], "evidence_confidence": m["evidence_confidence"],
            "facts": [{"key": "momentum_return", "value": m["value"], "units": "fraction", "source_ids": m["evidence_ids"]},
                      {"key": "relative_volume", "value": v["value"], "units": "ratio", "source_ids": v["evidence_ids"]}],
            "evidence_ids": list(dict.fromkeys(m["evidence_ids"] + v["evidence_ids"])), "warnings": []}


def research_agent(signal: dict, retrieved: list[dict]) -> dict:
    return {"status": signal["status"], "assessment": {"POSITIVE": "BULLISH", "NEGATIVE": "BEARISH",
            "MIXED": "MIXED"}.get(signal["label"], "UNKNOWN"), "evidence_confidence": signal["evidence_confidence"],
            "facts": [{"key": "filing_excerpt", "value": d["excerpt"], "source_ids": [d["id"]]} for d in retrieved],
            "evidence_ids": signal["evidence_ids"], "warnings": [signal["warning"]] if signal.get("warning") else []}


def risk_agent(profile: dict, ticker: str) -> dict:
    positions = profile["positions"]
    total = sum(p["value"] for p in positions if p["value"] is not None)
    if not total or any(p["value"] is None for p in positions):
        return {"status": "PARTIAL", "assessment": "UNKNOWN", "evidence_confidence": None,
                "facts": [], "evidence_ids": [], "warnings": ["Incomplete portfolio valuation"]}
    weight = sum(p["value"] for p in positions if p["ticker"] == ticker) / total
    cap = profile["max_single_asset_weight"]
    hhi = sum((p["value"] / total) ** 2 for p in positions)
    breach = weight > cap
    return {"status": "OK", "assessment": "CAUTION" if breach else "NEUTRAL",
            "evidence_confidence": confidence(1, 1, min(1, abs(weight - cap) / cap)),
            "facts": [{"key": "position_weight", "value": round(weight, 4), "units": "fraction", "source_ids": [profile["id"]]},
                      {"key": "single_asset_cap", "value": cap, "units": "fraction", "source_ids": [profile["id"]]},
                      {"key": "portfolio_hhi", "value": round(hhi, 4), "units": "index", "source_ids": [profile["id"]]}],
            "evidence_ids": [profile["id"]], "warnings": ["Position exceeds configured single-name cap"] if breach else [],
            "position_weight": round(weight, 4), "single_asset_cap": cap, "hhi": round(hhi, 4), "breach": breach}


def synthesize(agents: dict, signals: dict) -> dict:
    market, research, risk = (agents[x] for x in ("market", "research", "risk"))
    available = [a["status"] == "OK" for a in (market, research, risk)]
    conflict = market["assessment"] in ("BULLISH", "BEARISH") and research["assessment"] in ("BULLISH", "BEARISH") and market["assessment"] != research["assessment"]
    breach = bool(risk.get("breach"))
    if signals["momentum"]["status"] != "OK" and signals["filing_tone"]["status"] != "OK":
        state = "INSUFFICIENT_EVIDENCE"
    elif not all(available):
        state = "PARTIAL"
    elif conflict:
        state = "CONFLICTED"
    elif breach:
        state = "CAUTION"
    else:
        state = "ALIGNED"
    reasons = []
    if conflict:
        reasons.append({"text": "Price momentum and dated filing tone point in different directions.",
                        "evidence_ids": market["evidence_ids"][:2] + research["evidence_ids"][:2]})
    if breach:
        reasons.append({"text": f"Current weight {risk['position_weight']:.0%} exceeds this profile's {risk['single_asset_cap']:.0%} single-name limit.",
                        "evidence_ids": [risk["evidence_ids"][0]]})
    for name, agent in agents.items():
        if agent["status"] != "OK":
            reasons.append({"text": f"{name.title()} perspective is {agent['status'].lower()}.", "evidence_ids": []})
    if not reasons:
        reasons.append({"text": "Available price and filing evidence do not show a directional conflict.",
                        "evidence_ids": market["evidence_ids"][:2] + research["evidence_ids"][:2]})
    return {"state": state, "reasons": reasons, "market_research_disagreement": conflict,
            "suitability_breach": breach, "evidence_completeness": round(sum(available) / 3, 3),
            "next_step": "Inspect the cited filings and portfolio limits before forming a view."}


async def analyze(ticker: str, profile: dict, as_of: str = AS_OF) -> dict:
    wall_start = perf_counter()
    snapshot = prepare(ticker, as_of)
    numeric = numeric_signals(snapshot)
    retrieved = retrieve(snapshot)
    signals = {**numeric, "filing_tone": filing_signal(snapshot, retrieved)}
    tasks = [timed_agent("MARKET", lambda: market_agent(signals)),
             timed_agent("RESEARCH", lambda: research_agent(signals["filing_tone"], retrieved)),
             timed_agent("RISK", lambda: risk_agent(profile, ticker))]
    outcomes = await asyncio.gather(*(asyncio.wait_for(task, timeout=2) for task in tasks), return_exceptions=True)
    agents = {}
    for key, outcome in zip(("market", "research", "risk"), outcomes):
        if isinstance(outcome, BaseException):
            outcome = {"agent": key.upper(), "status": "TIMEOUT" if isinstance(outcome, TimeoutError) else "ERROR",
                       "assessment": "UNKNOWN", "evidence_confidence": None, "facts": [], "evidence_ids": [],
                       "warnings": [type(outcome).__name__], "started_at": stamp(), "finished_at": stamp(),
                       "latency_ms": None, "execution_mode": "DETERMINISTIC_FALLBACK", "method_version": METHOD_VERSION}
        agents[key] = outcome
    allowed = {d["id"] for d in retrieved} | {b["id"] for b in snapshot["bars"]} | {profile["id"]}
    for agent in agents.values():
        agent["evidence_ids"] = [x for x in agent["evidence_ids"] if x in allowed]
        agent["facts"] = [f for f in agent["facts"] if all(x in allowed for x in f["source_ids"])]
    synthesis = synthesize(agents, signals)
    cited = list(dict.fromkeys(x for a in agents.values() for x in a["evidence_ids"] if x.startswith("E-")))
    evidence = [d for d in retrieved if d["id"] in cited]
    run_id = "run_" + uuid.uuid4().hex[:12]
    wall_ms = round((perf_counter() - wall_start) * 1000, 2)
    return {"run_id": run_id, "status": "COMPLETE" if synthesis["state"] not in ("PARTIAL", "INSUFFICIENT_EVIDENCE") else "PARTIAL",
            "created_at": stamp(), "ticker": ticker, "investor_id": profile["id"], "profile_revision": profile["revision"],
            "dataset_id": DATASET_ID, "as_of": as_of, "data_mode": "SYNTHETIC",
            "market_snapshot_hash": snapshot["market_snapshot_hash"],
            "run_context_hash": digest({"snapshot": snapshot["market_snapshot_hash"], "profile": profile}),
            "signals": signals, "agents": agents, "synthesis": synthesis, "evidence": evidence,
            "metrics": {"wall_latency_ms": wall_ms, "citation_validity": 1.0 if cited else None,
                        "citation_count": len(cited), "portfolio_concentration": agents["risk"].get("position_weight"),
                        "agent_overlap": max(a["started_at"] for a in agents.values()) < min(a["finished_at"] for a in agents.values())}}
