"""Snapshot analysis, independent agents, citation checks, and synthesis."""
from __future__ import annotations

import asyncio
from datetime import datetime, date, timezone, timedelta
from hashlib import sha256
import json
import math
import re
from statistics import median
from threading import Barrier
from time import perf_counter, perf_counter_ns
import uuid
from collections import Counter

from .fixtures import AS_OF, DATASET_ID, STOCKS, bars_for, documents
from . import llm

METHOD_VERSION = "rules-1.2"
_CLOCK_ANCHOR = datetime.now(timezone.utc)
_MONOTONIC_ANCHOR = perf_counter_ns()


def stamp() -> str:
    elapsed_us = (perf_counter_ns() - _MONOTONIC_ANCHOR) // 1000
    return (_CLOCK_ANCHOR + timedelta(microseconds=elapsed_us)).isoformat(timespec="microseconds")


def digest(value) -> str:
    return "sha256:" + sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def confidence(coverage: float, freshness: float, margin: float, quality: float = 1.0) -> dict:
    coverage, freshness, margin, quality = (max(0, min(1, value)) for value in
                                            (coverage, freshness, margin, quality))
    parts = {"coverage": round(coverage, 3), "freshness": round(freshness, 3),
             "threshold_margin": round(margin, 3), "source_quality": round(quality, 3)}
    score = .35 * coverage + .30 * freshness + .20 * margin + .15 * quality
    return {"score": round(max(0, min(1, score)), 3), "components": parts,
            "meaning": "Heuristic evidence strength; not predictive accuracy"}


def validate_agent_payload(agent: str, result: dict) -> None:
    """Runtime contract for deterministic tool outputs before model interpretation."""
    if not isinstance(result, dict):
        raise ValueError(f"{agent} output must be an object")
    if result.get("status") not in {"OK", "PARTIAL", "UNAVAILABLE", "TIMEOUT", "ERROR"}:
        raise ValueError(f"{agent} has invalid status")
    if result.get("assessment") not in {"BULLISH", "BEARISH", "NEUTRAL", "MIXED", "CAUTION", "UNKNOWN"}:
        raise ValueError(f"{agent} has invalid assessment")
    for field in ("facts", "evidence_ids", "warnings"):
        if not isinstance(result.get(field), list):
            raise ValueError(f"{agent} has invalid {field}")
    if any(not isinstance(value, str) for value in result["evidence_ids"] + result["warnings"]):
        raise ValueError(f"{agent} has invalid source or warning text")
    for fact in result["facts"]:
        if not isinstance(fact, dict) or not isinstance(fact.get("key"), str) or \
                not isinstance(fact.get("source_ids"), list) or \
                any(not isinstance(value, str) for value in fact["source_ids"]):
            raise ValueError(f"{agent} has invalid fact contract")
        value = fact.get("value")
        if not isinstance(value, (str, int, float, bool, type(None))) or \
                (isinstance(value, float) and not math.isfinite(value)) or \
                ("units" in fact and not isinstance(fact["units"], str)):
            raise ValueError(f"{agent} has invalid fact value")
    evidence_confidence = result.get("evidence_confidence")
    if evidence_confidence is not None:
        if not isinstance(evidence_confidence, dict) or not isinstance(evidence_confidence.get("score"), (int, float)) or \
                not math.isfinite(evidence_confidence["score"]) or not 0 <= evidence_confidence["score"] <= 1:
            raise ValueError(f"{agent} has invalid evidence confidence")
        components = evidence_confidence.get("components")
        if not isinstance(components, dict) or set(components) != {"coverage", "freshness", "threshold_margin", "source_quality"} or \
                any(not isinstance(value, (int, float)) or
                not math.isfinite(value) or not 0 <= value <= 1 for value in components.values()):
            raise ValueError(f"{agent} has invalid evidence confidence components")


def prepare(ticker: str, as_of: str, bars: list[dict] | None = None, docs: list[dict] | None = None,
            dataset_id: str = DATASET_ID, mode: str = "SYNTHETIC") -> dict:
    """Freeze the dated bars and documents visible at `as_of`.

    Without `bars`, the built-in synthetic fixtures are used. Live callers pass
    provider bars and the user's filings along with their dataset ID and mode.
    """
    if bars is None:
        if ticker not in STOCKS:
            raise ValueError("Unknown ticker")
        bars, docs = bars_for(ticker), [d for d in documents() if d["ticker"] == ticker]
    if not isinstance(as_of, str):
        raise ValueError("as_of must be an ISO date")
    try:
        cutoff = date.fromisoformat(as_of)
    except ValueError as exc:
        raise ValueError("Invalid as_of date") from exc
    last_date = max((b["trade_date"] for b in bars), default=None)
    if last_date is None or cutoff > date.fromisoformat(last_date):
        raise ValueError(f"as_of is after the latest available bar ({last_date})" if last_date else "No price bars are available")
    bars = [b for b in bars if b["trade_date"] <= as_of]
    docs = [d for d in docs or [] if d["ticker"] == ticker and d["published_at"] <= as_of]
    if len({b["id"] for b in bars}) != len(bars) or len({d["id"] for d in docs}) != len(docs):
        raise ValueError("Duplicate source ID in the frozen snapshot")
    if any(d["source_hash"] != "sha256:" + sha256(d["excerpt"].encode()).hexdigest() for d in docs):
        raise ValueError("Document excerpt integrity check failed")
    if any(b["ticker"] != ticker or b["mode"] != mode for b in bars):
        raise ValueError("Invalid market bar provenance")
    market_hash = digest({"dataset": dataset_id, "ticker": ticker, "as_of": as_of,
                          "bars": bars, "documents": docs})
    return {"ticker": ticker, "as_of": as_of, "bars": bars, "documents": docs,
            "market_snapshot_hash": market_hash, "data_mode": mode, "dataset_id": dataset_id}


def numeric_signals(snapshot: dict) -> dict:
    bars = snapshot["bars"]
    if len(bars) < 21 or any(not isinstance(b.get("close"), (int, float)) or
                             not isinstance(b.get("volume"), (int, float)) or
                             not math.isfinite(b["close"]) or not math.isfinite(b["volume"]) or
                             b["close"] <= 0 or b["volume"] <= 0 for b in bars[-21:]):
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


RESEARCH_QUERY = "quarterly revenue operating margin costs cash debt contracts demand orders"
FILING_MAX_AGE_DAYS = 180
STOPWORDS = {"the", "and", "for", "with", "that", "this", "what", "which", "who", "how", "why", "when", "where",
             "did", "does", "was", "were", "are", "has", "had", "have", "from", "into", "about", "any", "its",
             "their", "there", "than", "then", "they", "say", "said", "tell", "show", "excerpt", "excerpts",
             "filing", "filings", "company", "report", "reports", "reported", "during", "after", "while", "not"}


def _terms(value: str) -> list[str]:
    """Lowercase terms with stopwords removed and a plural suffix folded (orders -> order)."""
    words = (word for word in re.findall(r"[a-z]{3,}", value.lower()) if word not in STOPWORDS)
    return [word[:-1] if len(word) > 4 and word.endswith("s") and not word.endswith("ss") else word
            for word in words]


def _age_days(snapshot: dict, doc: dict) -> int:
    return (date.fromisoformat(snapshot["as_of"]) - date.fromisoformat(doc["published_at"])).days


def retrieve(snapshot: dict, question: str = RESEARCH_QUERY, limit: int = 3,
             max_age_days: int | None = None) -> list[dict]:
    """Issuer and date gated TF-IDF cosine search over exact fixture passages."""
    corpus = [doc for doc in snapshot["documents"]
              if max_age_days is None or _age_days(snapshot, doc) <= max_age_days]
    if not corpus:
        return []
    counts = [Counter(_terms(doc["excerpt"])) for doc in corpus]
    query = Counter(_terms(question))
    if not query:
        return []
    df = Counter(word for row in counts for word in row)
    n = len(corpus)
    def weight(word: str, frequency: int) -> float:
        return (1 + math.log(frequency)) * (math.log((n + 1) / (df[word] + 1)) + 1)
    query_vector = {word: weight(word, frequency) for word, frequency in query.items()}
    query_norm = math.sqrt(sum(value * value for value in query_vector.values()))
    ranked = []
    for doc, row in zip(corpus, counts):
        vector = {word: weight(word, frequency) for word, frequency in row.items()}
        norm = math.sqrt(sum(value * value for value in vector.values()))
        dot = sum(query_vector.get(word, 0) * value for word, value in vector.items())
        score = dot / (norm * query_norm) if norm and query_norm else 0
        if score > 0:
            ranked.append({**doc, "retrieval_score": round(score, 5)})
    return sorted(ranked, key=lambda d: (d["retrieval_score"], d["published_at"]), reverse=True)[:limit]


def ask_filings(report: dict, question) -> dict:
    """Extractive answer: ranked exact passages from the run's frozen, as-of eligible filings.

    No text is generated; an unanswerable question returns no passages.
    """
    if not isinstance(question, str) or not 3 <= len(question.strip()) <= 300:
        raise ValueError("Question must be 3-300 characters")
    documents = (report.get("market_snapshot") or {}).get("documents")
    if documents is None:
        raise LookupError("This saved run predates frozen document storage")
    snapshot = {"as_of": report["as_of"], "documents": documents}
    terms = _terms(question)
    passages = [{key: doc[key] for key in ("id", "document_id", "title", "published_at", "excerpt",
                                          "source_hash", "retrieval_score")} | {"age_days": _age_days(snapshot, doc)}
                for doc in retrieve(snapshot, question, limit=3)] if terms else []
    return {"run_id": report["run_id"], "ticker": report["ticker"], "as_of": report["as_of"],
            "question": question.strip(), "query_terms": terms, "passages": passages,
            "searched_document_count": len(documents), "method": "tfidf-1.0 extractive retrieval",
            "answer_status": "ANSWERED_FROM_SOURCES" if passages else "NO_SUPPORTING_PASSAGE",
            "note": "Passages are exact stored text from filings published by the as-of date; nothing is generated."}


def filing_signal(snapshot: dict, retrieved: list[dict]) -> dict:
    if not retrieved:
        reason = (f"Filings exist, but none was published within {FILING_MAX_AGE_DAYS} days of the as-of date."
                  if snapshot["documents"] else "No eligible filing excerpt existed by the as-of date.")
        return {"status": "UNAVAILABLE", "label": "UNKNOWN", "value": None, "evidence_confidence": None,
                "evidence_ids": [], "reason": reason}
    # Fixture tone tags are attached to stored excerpts. No sentence is generated beyond cited facts.
    tone = sum(d["tone"] for d in retrieved) / len(retrieved)
    label = "POSITIVE" if tone > .2 else "NEGATIVE" if tone < -.2 else "MIXED"
    mixed = any(d["tone"] > 0 for d in retrieved) and any(d["tone"] < 0 for d in retrieved)
    if mixed and abs(tone) <= .2:
        label = "MIXED"
    ages = [_age_days(snapshot, d) for d in retrieved]
    fresh = sum(max(0, 1 - age / 180) for age in ages) / len(ages)
    stale = any(age > 120 for age in ages)
    status = "PARTIAL" if all(age > 120 for age in ages) else "OK"
    return {"status": status, "label": label, "value": round(tone, 3), "unit": "fixture fact-tone mean",
            "evidence_confidence": confidence(min(1, len(retrieved) / 3), fresh, min(1, abs(tone) / .8), .8),
            "evidence_ids": [d["id"] for d in retrieved],
            "reason": "Filing tone is the mean of the cited excerpts' tone tags; contradictory tags produce MIXED.",
            "warning": "At least one cited filing is over 120 days old" if stale else None}


async def timed_agent(name: str, compute, use_model: bool = True, eligible_ids: set[str] | None = None,
                      owner: str | None = None):
    start = stamp()
    clock = perf_counter()
    execution_mode = "DETERMINISTIC_FALLBACK"
    model_metadata = {}
    try:
        # Independent pipelines run in the thread pool so blocking tools can
        # overlap; asyncio.gather controls their common run and timeout boundary.
        result = await asyncio.to_thread(compute)
        validate_agent_payload(name, result)
        sources_valid = eligible_ids is None or (set(result["evidence_ids"]) <= eligible_ids and
            all(set(fact["source_ids"]) <= eligible_ids for fact in result["facts"]))
        if not sources_valid:
            result["warnings"].append("Agent cited a source outside its eligible evidence set")
        if sources_valid and use_model and llm.configured() and result["status"] in ("OK", "PARTIAL"):
            try:
                extra = {"owner": owner} if owner else {}
                model_metadata = await asyncio.to_thread(llm.reason, name, result, **extra)
                execution_mode = "LLM_REASONED"
            except Exception as exc:
                if isinstance(exc, llm.DailyLimitReached):
                    note = f"Model reasoning paused: {exc}. Rule-based reasoning was used; facts and the action are unaffected."
                else:
                    note = f"Model reasoning unavailable; deterministic fallback ({type(exc).__name__})."
                result.setdefault("warnings", []).append(note)
    except Exception as exc:
        result = {"status": "ERROR", "assessment": "UNKNOWN", "facts": [],
                  "evidence_ids": [], "warnings": [str(exc)], "evidence_confidence": None}
    result.update({"agent": name, "started_at": start, "finished_at": stamp(),
                   "latency_ms": round((perf_counter() - clock) * 1000, 2),
                   "execution_mode": execution_mode, "model_version": model_metadata.get("model_version"),
                   "method_version": METHOD_VERSION})
    if model_metadata:
        result["reasoning"] = model_metadata
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


def risk_agent(profile: dict, ticker: str, sectors: dict | None = None) -> dict:
    positions = profile["positions"]
    total = sum(p["value"] for p in positions if p["value"] is not None)
    if not total or any(p["value"] is None for p in positions):
        return {"status": "PARTIAL", "assessment": "UNKNOWN", "evidence_confidence": None,
                "facts": [], "evidence_ids": [], "warnings": ["Incomplete portfolio valuation"]}
    weight = sum(p["value"] for p in positions if p["ticker"] == ticker) / total
    cap = profile["max_single_asset_weight"]
    sector = _sector_of(ticker, sectors)
    sector_weight = sum(p["value"] for p in positions if p["ticker"] != "CASH" and
                        _sector_of(p["ticker"], sectors) == sector) / total
    sector_cap = profile["max_sector_weight"]
    hhi = sum((p["value"] / total) ** 2 for p in positions)
    single_breach = weight > cap
    sector_breach = sector_weight > sector_cap
    breach = single_breach or sector_breach
    return {"status": "OK", "assessment": "CAUTION" if breach else "NEUTRAL",
            "evidence_confidence": confidence(1, 1, min(1, abs(weight - cap) / cap)),
            "facts": [{"key": "position_weight", "value": round(weight, 4), "units": "fraction", "source_ids": [profile["id"]]},
                      {"key": "single_asset_cap", "value": cap, "units": "fraction", "source_ids": [profile["id"]]},
                      {"key": "sector_weight", "value": round(sector_weight, 4), "units": "fraction", "source_ids": [profile["id"]]},
                      {"key": "sector_cap", "value": sector_cap, "units": "fraction", "source_ids": [profile["id"]]},
                      {"key": "portfolio_hhi", "value": round(hhi, 4), "units": "index", "source_ids": [profile["id"]]}],
            "evidence_ids": [profile["id"]],
            "warnings": (["Position exceeds configured single-name cap"] if single_breach else []) +
                        (["Sector exposure exceeds configured sector cap"] if sector_breach else []),
            "position_weight": round(weight, 4), "single_asset_cap": cap, "single_asset_breach": single_breach,
            "sector": sector, "sector_weight": round(sector_weight, 4), "sector_cap": sector_cap,
            "sector_breach": sector_breach, "hhi": round(hhi, 4), "breach": breach}


def synthesize(agents: dict, signals: dict) -> dict:
    market, research, risk = (agents[x] for x in ("market", "research", "risk"))
    available = [a["status"] == "OK" for a in (market, research, risk)]
    conflict = market["assessment"] in ("BULLISH", "BEARISH") and research["assessment"] in ("BULLISH", "BEARISH") and market["assessment"] != research["assessment"]
    direction_gap = market["assessment"] != research["assessment"] and not conflict
    breach = bool(risk.get("breach"))
    if signals["momentum"]["status"] != "OK" and signals["volume"]["status"] != "OK":
        state = "INSUFFICIENT_EVIDENCE"
    elif not all(available):
        state = "PARTIAL"
    elif conflict:
        state = "CONFLICTED"
    elif breach or direction_gap:
        state = "CAUTION"
    else:
        state = "ALIGNED"
    reasons = []
    if conflict:
        reasons.append({"text": "Price momentum and dated filing tone point in different directions.",
                        "evidence_ids": market["evidence_ids"][:2] + research["evidence_ids"][:2]})
    if research["assessment"] == "MIXED":
        reasons.append({"text": "Cited filing excerpts have mixed fact-tone evidence.",
                        "evidence_ids": research["evidence_ids"][:3]})
    elif direction_gap and all(available):
        reasons.append({"text": "The available market and filing views are not directly aligned.",
                        "evidence_ids": market["evidence_ids"][:2] + research["evidence_ids"][:2]})
    if risk.get("single_asset_breach"):
        reasons.append({"text": f"Current weight {risk['position_weight']:.0%} exceeds this profile's {risk['single_asset_cap']:.0%} single-name limit.",
                        "evidence_ids": [risk["evidence_ids"][0]]})
    if risk.get("sector_breach"):
        reasons.append({"text": f"{risk['sector']} exposure {risk['sector_weight']:.0%} exceeds this profile's {risk['sector_cap']:.0%} sector limit.",
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


ACTIONS = {"REDUCE_EXPOSURE", "HOLD_REVIEW", "HOLD", "ELIGIBLE_TO_ADD", "AVOID_ADDING", "NO_VIEW"}


def _sector_of(ticker: str, sectors: dict | None = None) -> str:
    """Sector for a holding; `sectors` adds user-registered tickers to the synthetic universe."""
    if ticker == "CASH":
        return "Cash"
    known = {**{key: spec["sector"] for key, spec in STOCKS.items()}, **(sectors or {})}
    return known.get(ticker, "Unclassified")


def portfolio_insights(profile: dict, sectors: dict | None = None) -> dict:
    """Per-holding limit checks with the trim or headroom each configured cap implies.

    Sizing assumes trims are held as cash, so the portfolio total stays constant.
    """
    positions = profile["positions"]
    total = sum(p["value"] for p in positions)
    cap, sector_cap = profile["max_single_asset_weight"], profile["max_sector_weight"]
    if not total:
        return {"profile_id": profile["id"], "revision": profile["revision"], "total_value": 0,
                "holdings": [], "sectors": [], "breach_count": 0, "hhi": None,
                "summary": "The portfolio has no valued holdings."}
    sector_values = {}
    for p in positions:
        sector = _sector_of(p["ticker"], sectors)
        sector_values[sector] = sector_values.get(sector, 0) + p["value"]
    sector_rows = []
    for name, value in sorted(sector_values.items(), key=lambda item: -item[1]):
        limited = name not in ("Cash", "Unclassified")
        sector_rows.append({"sector": name, "value": value, "weight": round(value / total, 4),
                        "cap": sector_cap if limited else None,
                        "breach": limited and value > sector_cap * total,
                        "excess_value": round(max(0, value - sector_cap * total), 2) if limited else 0})
    holdings = []
    for p in positions:
        if p["ticker"] == "CASH":
            continue
        sector = _sector_of(p["ticker"], sectors)
        excess = max(0, p["value"] - cap * total)
        headroom = max(0, min(cap * total - p["value"], sector_cap * total - sector_values[sector]))
        holdings.append({"ticker": p["ticker"], "sector": sector, "value": p["value"],
                         "weight": round(p["value"] / total, 4), "cap": cap,
                         "breach": p["value"] > cap * total, "trim_to_cap": round(excess, 2),
                         "headroom_value": round(headroom, 2)})
    breaches = sum(h["breach"] for h in holdings) + sum(s["breach"] for s in sector_rows)
    hhi = sum((p["value"] / total) ** 2 for p in positions)
    summary = ("All holdings are within this profile's configured limits." if not breaches else
               f"{breaches} configured limit{'s are' if breaches > 1 else ' is'} exceeded; see the trims below.")
    return {"profile_id": profile["id"], "revision": profile["revision"], "total_value": total,
            "holdings": holdings, "sectors": sector_rows, "breach_count": breaches, "hhi": round(hhi, 4),
            "summary": summary, "sizing_assumption": "Trims are held as cash, so the portfolio total is unchanged."}


def recommend(ticker: str, profile: dict, agents: dict, synthesis: dict, sectors: dict | None = None) -> dict:
    """Deterministic, explainable portfolio action for this investor.

    The action comes from a fixed policy over the validated agent outputs and saved
    profile. Every reason carries the source IDs that support it.
    """
    state = synthesis["state"]
    market, research, risk = agents["market"], agents["research"], agents["risk"]
    market_ids = market["evidence_ids"][:2]
    research_ids = research["evidence_ids"][:3]
    profile_ids = [profile["id"]]
    reasons, would_change = [], []
    sizing = None
    if state == "INSUFFICIENT_EVIDENCE":
        action, rule = "NO_VIEW", "Fewer than 21 valid dated bars: no market view is formed."
        headline = "No view. There is not enough dated market history."
        would_change.append("An as-of date with at least 21 valid trading sessions would allow a full analysis.")
    elif risk["status"] != "OK" or risk.get("position_weight") is None:
        action, rule = "NO_VIEW", "The portfolio valuation is incomplete, so suitability cannot be sized."
        headline = "No view. The saved portfolio cannot be valued."
        would_change.append("Entering a value for every holding would allow suitability sizing.")
    else:
        insight = portfolio_insights(profile, sectors)
        total = insight["total_value"]
        held = risk["position_weight"] * total
        sector_value = risk["sector_weight"] * total
        cap, sector_cap = risk["single_asset_cap"], risk["sector_cap"]
        hold = f"Hold {ticker}" if held > 0 else f"Do not open a position in {ticker}"
        if risk.get("breach"):
            trim = min(held, max(held - cap * total, sector_value - sector_cap * total, 0))
            action = "REDUCE_EXPOSURE"
            rule = "A configured position or sector limit is breached, so the limit takes precedence over market signals."
            headline = f"Reduce {ticker} by about {trim:,.0f} to bring it within this profile's limits."
            sizing = {"current_value": round(held, 2), "current_weight": risk["position_weight"],
                      "change_value": -round(trim, 2), "target_weight": round((held - trim) / total, 4),
                      "portfolio_value": total, "assumption": insight["sizing_assumption"]}
            if risk.get("single_asset_breach"):
                reasons.append({"text": f"{ticker} is {risk['position_weight']:.0%} of the portfolio; the cap is {cap:.0%}.",
                                "evidence_ids": profile_ids})
                would_change.append(f"A single-name cap of at least {risk['position_weight']:.0%} would remove the size breach.")
            if risk.get("sector_breach"):
                reasons.append({"text": f"{risk['sector']} is {risk['sector_weight']:.0%} of the portfolio; the sector cap is {sector_cap:.0%}.",
                                "evidence_ids": profile_ids})
                would_change.append(f"A sector cap of at least {risk['sector_weight']:.0%} would remove the sector breach.")
        elif state == "CONFLICTED":
            action = "HOLD_REVIEW"
            rule = "Price momentum and dated filing tone disagree, so no addition is suggested until it is resolved."
            headline = (f"{hold} and do not add while price and filings disagree." if held > 0 else
                        f"{hold} while price and filings disagree.")
        elif state == "PARTIAL":
            action = "HOLD_REVIEW"
            rule = "At least one perspective is missing, so the evidence cannot support a change."
            headline = f"{hold}. One perspective is missing, so evidence is incomplete."
        elif state == "ALIGNED" and market["assessment"] == research["assessment"] == "BULLISH":
            limit_room = max(0, min(cap * total - held, sector_cap * total - sector_value))
            cash = sum(p["value"] for p in profile["positions"] if p["ticker"] == "CASH")
            headroom = min(limit_room, cash)
            action = "ELIGIBLE_TO_ADD" if headroom > 0 else "HOLD"
            rule = "Price and filings agree on a positive view and the position is below its limits."
            headline = (f"Eligible to add up to about {headroom:,.0f} to {ticker} within this profile's limits."
                        if headroom > 0 else
                        f"{hold}. The evidence is positive, but the position is already at its limit." if not limit_room else
                        f"{hold}. The evidence is positive, but there is no cash to fund an addition.")
            sizing = {"current_value": round(held, 2), "current_weight": risk["position_weight"],
                      "change_value": round(headroom, 2), "target_weight": round((held + headroom) / total, 4),
                      "portfolio_value": total, "available_cash": cash,
                      "assumption": "Additions are funded from cash, so the portfolio total is unchanged."}
            would_change.append("Momentum falling below +3% or a negative dated filing would end the alignment.")
        elif state == "ALIGNED" and market["assessment"] == research["assessment"] == "BEARISH":
            action = "AVOID_ADDING"
            rule = "Price and filings agree on a negative view."
            headline = f"Avoid adding to {ticker}. Price and filings are both negative."
            would_change.append("Momentum above -3% or a positive dated filing would end the negative alignment.")
        else:
            action = "HOLD"
            rule = "The evidence is mixed or neutral and no limit is breached."
            headline = f"{hold}. The evidence does not point clearly in either direction."
            would_change.append("Price momentum and filing tone both turning clearly positive or negative would allow a directional view.")
        if state == "CONFLICTED":
            reasons.append({"text": f"Price momentum is {market['assessment'].lower()} while dated filing tone is {research['assessment'].lower()}.",
                            "evidence_ids": market_ids + research_ids})
            would_change.append("Filing tone and price momentum pointing the same way would remove the disagreement.")
        if research["status"] != "OK":
            reasons.append({"text": "No eligible filing supports a research view at this as-of date.", "evidence_ids": []})
            would_change.append(f"A filing published within {FILING_MAX_AGE_DAYS} days before the as-of date would allow a research view.")
        if research["assessment"] == "MIXED":
            reasons.append({"text": "The cited filing excerpts are mixed.", "evidence_ids": research_ids})
        if state == "ALIGNED":
            reasons.append({"text": f"Price momentum and filing tone are both {market['assessment'].lower()}.",
                            "evidence_ids": market_ids + research_ids})
        if not risk.get("breach"):
            reasons.append({"text": f"{ticker} is {risk['position_weight']:.0%} of the portfolio, within the {cap:.0%} cap; "
                                    f"{risk['sector']} is {risk['sector_weight']:.0%}, within the {sector_cap:.0%} sector cap.",
                            "evidence_ids": profile_ids})
    return {"action": action, "headline": headline, "rule": rule, "reasons": reasons, "sizing": sizing,
            "would_change": list(dict.fromkeys(would_change)),
            "evidence_completeness": synthesis["evidence_completeness"], "policy_version": METHOD_VERSION,
            "basis": "Deterministic policy over cited evidence and this saved profile. It is not personalized financial advice."}


async def analyze(ticker: str, profile: dict, as_of: str = AS_OF, allow_llm: bool = True,
                  snapshot: dict | None = None, sectors: dict | None = None, warnings: list[str] | None = None,
                  owner: str | None = None) -> dict:
    """Run the three agents on a frozen snapshot. Pass `snapshot` from prepare() for live data."""
    wall_start = perf_counter()
    snapshot = snapshot or prepare(ticker, as_of)
    as_of = snapshot["as_of"]
    numeric = numeric_signals(snapshot)
    retrieved = retrieve(snapshot, max_age_days=FILING_MAX_AGE_DAYS)
    signals = {**numeric, "filing_tone": filing_signal(snapshot, retrieved)}
    start_gate = Barrier(3)
    def parallel(work):
        start_gate.wait(timeout=1)
        return work()
    allowed_by_agent = {"market": set(numeric["momentum"]["evidence_ids"] + numeric["volume"]["evidence_ids"]),
                        "research": {doc["id"] for doc in retrieved}, "risk": {profile["id"]}}
    tasks = [timed_agent("MARKET", lambda: parallel(lambda: market_agent(signals)), allow_llm, allowed_by_agent["market"], owner),
             timed_agent("RESEARCH", lambda: parallel(lambda: research_agent(signals["filing_tone"], retrieved)), allow_llm, allowed_by_agent["research"], owner),
             timed_agent("RISK", lambda: parallel(lambda: risk_agent(profile, ticker, sectors)), allow_llm, allowed_by_agent["risk"], owner)]
    outcomes = await asyncio.gather(*(asyncio.wait_for(task, timeout=10 if allow_llm and llm.configured() else 2) for task in tasks), return_exceptions=True)
    agents = {}
    for key, outcome in zip(("market", "research", "risk"), outcomes):
        if isinstance(outcome, BaseException):
            outcome = {"agent": key.upper(), "status": "TIMEOUT" if isinstance(outcome, TimeoutError) else "ERROR",
                       "assessment": "UNKNOWN", "evidence_confidence": None, "facts": [], "evidence_ids": [],
                       "warnings": [type(outcome).__name__], "started_at": stamp(), "finished_at": stamp(),
                       "latency_ms": None, "execution_mode": "DETERMINISTIC_FALLBACK", "method_version": METHOD_VERSION}
        agents[key] = outcome
    raw_research_citations = list(dict.fromkeys(agents["research"]["evidence_ids"] +
        [source_id for fact in agents["research"]["facts"] for source_id in fact["source_ids"]]))
    retrieved_ids = allowed_by_agent["research"]
    invalid_research_citations = sum(source_id not in retrieved_ids for source_id in raw_research_citations)
    for name, agent in agents.items():
        allowed = allowed_by_agent[name]
        original_ids = agent["evidence_ids"]
        original_facts = agent["facts"]
        agent["evidence_ids"] = [source_id for source_id in original_ids if source_id in allowed]
        agent["facts"] = [fact for fact in original_facts if all(source_id in allowed for source_id in fact["source_ids"])]
        if len(agent["evidence_ids"]) != len(original_ids) or len(agent["facts"]) != len(original_facts):
            agent["warnings"].append("Unsupported source reference removed during citation validation")
            if agent["agent"] == "RESEARCH" and not agent["facts"]:
                agent["status"] = "UNAVAILABLE"
                agent["assessment"] = "UNKNOWN"
                agent["evidence_confidence"] = None
            elif agent["status"] == "OK":
                agent["status"] = "PARTIAL"
    synthesis = synthesize(agents, signals)
    recommendation = recommend(ticker, profile, agents, synthesis, sectors)
    cited = list(dict.fromkeys(x for a in agents.values() for x in a["evidence_ids"] if x.startswith("E-")))
    evidence = [d for d in retrieved if d["id"] in cited]
    run_id = "run_" + uuid.uuid4().hex[:12]
    wall_ms = round((perf_counter() - wall_start) * 1000, 2)
    report = {"run_id": run_id, "status": "COMPLETE" if synthesis["state"] not in ("PARTIAL", "INSUFFICIENT_EVIDENCE") else "PARTIAL",
            "created_at": stamp(), "ticker": ticker, "investor_id": profile["id"], "profile_revision": profile["revision"],
            "dataset_id": snapshot["dataset_id"], "as_of": as_of, "data_mode": snapshot["data_mode"],
            "data_warnings": list(warnings or []),
            "method_version": METHOD_VERSION, "retrieval_method_version": "tfidf-1.0",
            "market_snapshot_hash": snapshot["market_snapshot_hash"],
            "run_context_hash": digest({"snapshot": snapshot["market_snapshot_hash"], "profile": profile}),
            "market_snapshot": {"bars": snapshot["bars"], "documents": snapshot["documents"],
                                "document_ids": [d["id"] for d in snapshot["documents"]]},
            "investor_snapshot": profile,
            "signals": signals, "agents": agents, "synthesis": synthesis, "recommendation": recommendation,
            "evidence": evidence,
            "metrics": {"wall_latency_ms": wall_ms,
                        "citation_validity": round((len(raw_research_citations) - invalid_research_citations) / len(raw_research_citations), 3) if raw_research_citations else None,
                        "citation_count": len(cited), "citation_fabrication_count": invalid_research_citations,
                        "portfolio_concentration": agents["risk"].get("position_weight"),
                        "agent_overlap": max(a["started_at"] for a in agents.values()) < min(a["finished_at"] for a in agents.values())}}
    report["report_hash"] = digest(report)
    return report
