"""Measured synthetic fixture checks, distinct from financial prediction accuracy."""
from __future__ import annotations

import asyncio
import json
import platform
from copy import deepcopy
from datetime import date, timedelta
from pathlib import Path

from . import embeddings, flows
from .core import analyze, hybrid_rank, prepare, retrieve, numeric_signals
from .fixtures import AS_OF

HELDOUT_RETRIEVAL = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "heldout_retrieval.json"
HELDOUT_PARAPHRASE = Path(__file__).resolve().parent.parent / "data" / "fixtures" / "heldout_paraphrase.json"


def paraphrase_texts() -> list[str]:
    """Every question and eligible excerpt the paraphrase evaluation embeds (used by the warm-up)."""
    bundle = json.loads(HELDOUT_PARAPHRASE.read_text(encoding="utf-8"))
    texts = []
    for case in bundle["relevant"] + bundle["unrelated"]:
        texts += [case["question"]] + [doc["excerpt"] for doc in prepare(case["ticker"], AS_OF)["documents"]]
    return list(dict.fromkeys(texts))


def semantic_evaluation() -> dict:
    """Lexical versus hybrid retrieval on held-out paraphrases, from cached embeddings only."""
    bundle = json.loads(HELDOUT_PARAPHRASE.read_text(encoding="utf-8"))
    def cached(texts):
        vectors = embeddings.cached_only(texts)
        if vectors is None:
            raise LookupError("not cached")
        return vectors
    try:
        rows = []
        for case in bundle["relevant"]:
            docs = prepare(case["ticker"], AS_OF)["documents"]
            gold = set(case["expected_ids"])
            lexical = {d["id"] for d in retrieve({"as_of": AS_OF, "documents": docs}, case["question"], limit=3)}
            ranked, info = hybrid_rank(docs, case["question"], cached)
            if info["semantic_status"] != "OK":
                raise LookupError("not cached")
            rows.append((len(lexical & gold), len({d["id"] for d in ranked} & gold), len(gold)))
        abstained = 0
        for case in bundle["unrelated"]:
            ranked, info = hybrid_rank(prepare(case["ticker"], AS_OF)["documents"], case["question"], cached)
            if info["semantic_status"] != "OK":
                raise LookupError("not cached")
            abstained += not ranked
    except LookupError:
        return {"status": "NOT_CACHED", "note": "Run python -m contra.warm to cache the evaluation embeddings."}
    expected = sum(row[2] for row in rows)
    return {"status": "MEASURED", "relevant_questions": len(rows), "unrelated_questions": len(bundle["unrelated"]),
            "lexical_recall_at_3": round(sum(row[0] for row in rows) / expected, 3),
            "hybrid_recall_at_3": round(sum(row[1] for row in rows) / expected, 3),
            "unrelated_abstained": abstained,
            "note": "Held-out paraphrases written after the similarity threshold was fixed; synthetic excerpts only."}


async def scenario_matrix(conservative: dict, growth: dict) -> dict:
    cases = [
        ("market_document_conflict", "ALPHA.NS", conservative, "CONFLICTED", True, "REDUCE_EXPOSURE"),
        ("same_market_growth_profile", "ALPHA.NS", growth, "CONFLICTED", False, "HOLD_REVIEW"),
        ("aligned_evidence", "GAMMA.NS", conservative, "ALIGNED", False, "ELIGIBLE_TO_ADD"),
        ("missing_eligible_filing", "DELTA.NS", conservative, "PARTIAL", False, "HOLD_REVIEW"),
    ]
    reports = await asyncio.gather(*(analyze(case[1], case[2], AS_OF, allow_llm=False) for case in cases))
    rows = []
    for (name, ticker, investor, expected_state, expected_breach, expected_action), report in zip(cases, reports):
        observed = report["synthesis"]
        action = report["recommendation"]["action"]
        passed = observed["state"] == expected_state and observed["suitability_breach"] == expected_breach and \
            action == expected_action
        rows.append({"name": name, "ticker": ticker, "investor_id": investor["id"],
                     "expected_state": expected_state, "observed_state": observed["state"],
                     "expected_action": expected_action, "observed_action": action,
                     "expected_suitability_breach": expected_breach,
                     "observed_suitability_breach": observed["suitability_breach"], "passed": passed})
    same_market = reports[0]["market_snapshot_hash"] == reports[1]["market_snapshot_hash"]
    same_facts = reports[0]["signals"] == reports[1]["signals"]
    rows.append({"name": "profile_isolation", "ticker": "ALPHA.NS", "investor_id": "both",
                 "expected_state": "SAME_MARKET_DIFFERENT_SUITABILITY",
                 "expected_action": "DIFFERENT_ACTION",
                 "observed_action": "DIFFERENT_ACTION" if reports[0]["recommendation"]["action"] != reports[1]["recommendation"]["action"] else "SAME_ACTION",
                 "observed_state": "SAME_MARKET_DIFFERENT_SUITABILITY" if same_market and same_facts and reports[0]["synthesis"]["suitability_breach"] != reports[1]["synthesis"]["suitability_breach"] else "FAILED",
                 "passed": same_market and same_facts and reports[0]["synthesis"]["suitability_breach"] != reports[1]["synthesis"]["suitability_breach"]})
    # A small manually labeled fixture bundle, frozen separately from runtime ranking.
    retrieval_cases = json.loads(HELDOUT_RETRIEVAL.read_text(encoding="utf-8"))["cases"]
    hits = 0
    expected = 0
    for case in retrieval_cases:
        gold_ids = set(case["expected_ids"])
        retrieved_ids = {d["id"] for d in retrieve(prepare(case["ticker"], AS_OF),
                                                question=case["question"], limit=3)}
        hits += len(retrieved_ids & gold_ids)
        expected += len(gold_ids)
    available = {d["id"] for report in reports for d in report["evidence"]}
    cited = [source_id for report in reports for fact in report["agents"]["research"]["facts"] for source_id in fact["source_ids"]]
    fabricated = sum(source_id not in available for source_id in cited)
    return {"cases": rows, "passed": sum(row["passed"] for row in rows), "total": len(rows),
            "retrieval_recall_at_3": round(hits / expected, 3), "retrieval_expected_count": expected,
            "retrieval_case_count": len(retrieval_cases),
            "citation_fabrication_count": fabricated,
            "semantic_retrieval": semantic_evaluation(),
            "robustness": robustness_checks(),
            "note": "Curated synthetic fixtures test implementation behavior, not future returns."}


def robustness_checks() -> dict:
    """Visible fault-injection checks. These are regression cases, not held-out accuracy."""
    base = prepare("ALPHA.NS", AS_OF)
    rows = []
    def check(name, expected, observed):
        rows.append({"name": name, "expected": expected, "observed": observed, "passed": expected == observed})
    missing = {**base, "institutional_flows": []}
    check("missing_flows_abstain", "UNAVAILABLE", flows.signal(missing)["status"])
    check("opposite_flows_remain_divergent", "DIVERGENT", flows.signal(base)["label"])
    stale = {**base, "as_of": (date.fromisoformat(AS_OF) + timedelta(days=7)).isoformat()}
    check("stale_flows_abstain", "UNAVAILABLE", flows.signal(stale)["status"])
    short = {**base, "bars": base["bars"][-20:]}
    check("short_price_history_abstains", "UNAVAILABLE", numeric_signals(short)["momentum"]["status"])
    invalid = deepcopy(base)
    invalid["bars"][-1]["volume"] = 0
    check("zero_volume_abstains", "UNAVAILABLE", numeric_signals(invalid)["volume"]["status"])
    check("future_filings_excluded", 0, len(prepare("DELTA.NS", AS_OF)["documents"]))
    corrupt = deepcopy(base["institutional_flows"][0])
    corrupt["groups"]["DII"]["net"] += 1
    observed = "ACCEPTED"
    try:
        prepare("ALPHA.NS", AS_OF, institutional_flows=[corrupt])
    except ValueError:
        observed = "REJECTED"
    check("changed_flow_evidence_rejected", "REJECTED", observed)
    return {"passed": sum(row["passed"] for row in rows), "total": len(rows), "cases": rows,
            "method": "Deterministic fault injection on synthetic inputs. No provider requests or model calls. These are regression checks, not held-out financial prediction accuracy."}


async def benchmark_fixed(profile: dict, repetitions: int = 10) -> dict:
    """Repeated measured executions of one frozen fixture; no database writes."""
    samples = []
    for _ in range(repetitions):
        report = await analyze("ALPHA.NS", profile, AS_OF, allow_llm=False)
        samples.append(report["metrics"]["wall_latency_ms"])
    ordered = sorted(samples)
    def percentile(p: float) -> float:
        position = (len(ordered) - 1) * p
        lower = int(position)
        upper = min(lower + 1, len(ordered) - 1)
        return round(ordered[lower] + (ordered[upper] - ordered[lower]) * (position - lower), 2)
    return {"ticker": "ALPHA.NS", "investor_id": profile["id"], "repetitions": repetitions,
            "latency_ms": {"p50": percentile(.5), "p95": percentile(.95),
                           "min": ordered[0], "max": ordered[-1]},
            "environment": {"python": platform.python_version(), "platform": platform.system(),
                            "machine": platform.machine()},
            "measurement": "In-process analysis wall time; excludes HTTP and page rendering"}
