"""Pre-answer the demo scenarios with the configured model, once, before a presentation.

    python -m contra.warm

Runs every synthetic scenario for both sample profiles with model reasoning. Identical
agent inputs are answered once. The validated answers are kept in the database and written
to data/fixtures/model_cache.json, which the server preloads. A hosted copy can therefore
show model reasoning for the scenarios without spending credits again. Reports label every
reused answer as cached, with the time it was first answered.

It also embeds the synthetic filings, the real-company SEC excerpts, the suggested questions and the held-out evaluation
questions into data/fixtures/embedding_cache.json, so filing search and its evaluation
work without new embedding calls.
"""
from __future__ import annotations

import asyncio
import json

from . import embeddings, llm, public_filings, store
from .core import analyze
from .evaluation import paraphrase_texts
from .fixtures import STOCKS, documents
from .server import WARM_CACHE, WARM_EMBEDDINGS, install_model_cache
from .settings import load_env

# Keep in sync with the suggestion chips in web/app.js.
SUGGESTED_QUESTIONS = ["Is profitability getting squeezed?", "Any new contracts or orders?", "What about cash and debt?"]


def main() -> None:
    load_env()
    if not llm.configured():
        raise SystemExit("Set OPENAI_API_KEY and CONTRA_LLM=1 in .env first.")
    install_model_cache()
    before = llm.usage()["calls"]
    used_keys, failures, verified, by_rule, rejected = set(), [], 0, 0, []
    for investor in store.baseline_profiles():
        for ticker in STOCKS:
            report = asyncio.run(analyze(ticker, investor))
            for name, agent in report["agents"].items():
                if agent["execution_mode"] == "LLM_REASONED":
                    used_keys.add(agent["reasoning"]["cache_key"])
                    status = (agent["reasoning"].get("summary") or {}).get("status")
                    if agent["briefing"]["source"] == "MODEL_VERIFIED":
                        verified += 1
                    elif status == "NOT_REQUESTED":
                        by_rule += 1
                    else:
                        rejected.append(f"{ticker} / {investor['display_name']} / {name}: {agent['briefing']['model_note']}")
                elif agent["status"] in ("OK", "PARTIAL"):
                    failures.append(f"{ticker} / {investor['display_name']} / {name}: {'; '.join(agent['warnings'])}")
    answers = {key: value for key, value in store.ModelCache().all().items() if key in used_keys}
    WARM_CACHE.write_text(json.dumps({"model": answers and next(iter(answers.values()))["model_version"],
                                      "prompt_version": llm.PROMPT_VERSION, "answers": answers},
                                     indent=1, sort_keys=True), encoding="utf-8")
    print(f"Paid model calls: {llm.usage()['calls'] - before}. Cached scenario answers: {len(answers)}.")
    print(f"Agent briefings: {verified} model-written and verified, {len(rejected)} replaced by rule summaries, "
          f"{by_rule} rule-based by design (risk).")
    print(f"Wrote {WARM_CACHE}")
    for failure in failures:
        print("Not model-reasoned:", failure)
    for item in rejected:
        print("Summary rejected:", item)

    texts = list(dict.fromkeys([doc["excerpt"] for doc in documents() + public_filings.documents()]
                              + SUGGESTED_QUESTIONS + paraphrase_texts()))
    embed_before = embeddings.usage()["calls"]
    embeddings.embed(texts)
    vectors = {embeddings.key_for(text): vector for text, vector in zip(texts, embeddings.cached_only(texts))}
    WARM_EMBEDDINGS.write_text(json.dumps({"model": embeddings.MODEL, "dimensions": embeddings.DIMENSIONS,
                                           "vectors": vectors}, sort_keys=True, separators=(",", ":")),
                               encoding="utf-8")
    print(f"Embedding requests: {embeddings.usage()['calls'] - embed_before}. Cached vectors: {len(vectors)}.")
    print(f"Wrote {WARM_EMBEDDINGS}")


if __name__ == "__main__":
    main()
