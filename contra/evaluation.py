"""Measured synthetic fixture checks, distinct from financial prediction accuracy."""
from __future__ import annotations

import asyncio
import platform

from .core import analyze, prepare, retrieve
from .fixtures import AS_OF


async def scenario_matrix(conservative: dict, growth: dict) -> dict:
    cases = [
        ("market_document_conflict", "ALPHA.NS", conservative, "CONFLICTED", True),
        ("same_market_growth_profile", "ALPHA.NS", growth, "CONFLICTED", False),
        ("aligned_evidence", "GAMMA.NS", conservative, "ALIGNED", False),
        ("missing_eligible_filing", "DELTA.NS", conservative, "PARTIAL", False),
    ]
    reports = await asyncio.gather(*(analyze(ticker, investor, AS_OF, allow_llm=False) for _, ticker, investor, _, _ in cases))
    rows = []
    for (name, ticker, investor, expected_state, expected_breach), report in zip(cases, reports):
        observed = report["synthesis"]
        passed = observed["state"] == expected_state and observed["suitability_breach"] == expected_breach
        rows.append({"name": name, "ticker": ticker, "investor_id": investor["id"],
                     "expected_state": expected_state, "observed_state": observed["state"],
                     "expected_suitability_breach": expected_breach,
                     "observed_suitability_breach": observed["suitability_breach"], "passed": passed})
    same_market = reports[0]["market_snapshot_hash"] == reports[1]["market_snapshot_hash"]
    same_facts = reports[0]["signals"] == reports[1]["signals"]
    rows.append({"name": "profile_isolation", "ticker": "ALPHA.NS", "investor_id": "both",
                 "expected_state": "SAME_MARKET_DIFFERENT_SUITABILITY",
                 "observed_state": "SAME_MARKET_DIFFERENT_SUITABILITY" if same_market and same_facts and reports[0]["synthesis"]["suitability_breach"] != reports[1]["synthesis"]["suitability_breach"] else "FAILED",
                 "passed": same_market and same_facts and reports[0]["synthesis"]["suitability_breach"] != reports[1]["synthesis"]["suitability_breach"]})
    # A small manually labeled fixture bundle, frozen independently of ranking.
    retrieval_labels = {
        "ALPHA.NS": {"E-ALPHA-01", "E-ALPHA-02"},
        "GAMMA.NS": {"E-GAMMA-01", "E-GAMMA-03"},
    }
    hits = 0
    expected = 0
    for ticker, gold_ids in retrieval_labels.items():
        retrieved_ids = {d["id"] for d in retrieve(prepare(ticker, AS_OF), limit=3)}
        hits += len(retrieved_ids & gold_ids)
        expected += len(gold_ids)
    available = {d["id"] for report in reports for d in report["evidence"]}
    cited = [source_id for report in reports for fact in report["agents"]["research"]["facts"] for source_id in fact["source_ids"]]
    fabricated = sum(source_id not in available for source_id in cited)
    return {"cases": rows, "passed": sum(row["passed"] for row in rows), "total": len(rows),
            "retrieval_recall_at_3": round(hits / expected, 3), "retrieval_expected_count": expected,
            "citation_fabrication_count": fabricated,
            "note": "Curated synthetic fixtures test implementation behavior, not future returns."}


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
