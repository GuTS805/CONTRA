"""Pre-answer the demo scenarios with the configured model, once, before a presentation.

    python -m contra.warm

Runs every synthetic scenario for both sample profiles with model reasoning. Identical
agent inputs are answered once. The validated answers are kept in the database and written
to data/fixtures/model_cache.json, which the server preloads. A hosted copy can therefore
show model reasoning for the scenarios without spending credits again. Reports label every
reused answer as cached, with the time it was first answered.
"""
from __future__ import annotations

import asyncio
import json

from . import llm, store
from .core import analyze
from .fixtures import STOCKS
from .server import WARM_CACHE, install_model_cache
from .settings import load_env


def main() -> None:
    load_env()
    if not llm.configured():
        raise SystemExit("Set OPENAI_API_KEY and CONTRA_LLM=1 in .env first.")
    install_model_cache()
    before = llm.usage()["calls"]
    used_keys, failures = set(), []
    for investor in store.baseline_profiles():
        for ticker in STOCKS:
            report = asyncio.run(analyze(ticker, investor))
            for name, agent in report["agents"].items():
                if agent["execution_mode"] == "LLM_REASONED":
                    used_keys.add(agent["reasoning"]["cache_key"])
                elif agent["status"] in ("OK", "PARTIAL"):
                    failures.append(f"{ticker} / {investor['display_name']} / {name}: {'; '.join(agent['warnings'])}")
    answers = {key: value for key, value in store.ModelCache().all().items() if key in used_keys}
    WARM_CACHE.write_text(json.dumps({"model": answers and next(iter(answers.values()))["model_version"],
                                      "prompt_version": llm.PROMPT_VERSION, "answers": answers},
                                     indent=1, sort_keys=True), encoding="utf-8")
    print(f"Paid model calls: {llm.usage()['calls'] - before}. Cached scenario answers: {len(answers)}.")
    print(f"Wrote {WARM_CACHE}")
    for failure in failures:
        print("Not model-reasoned:", failure)


if __name__ == "__main__":
    main()
