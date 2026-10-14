# CONTRA

An evidence-first, synthetic financial research demo based on `CONTRA_Architecture_and_Implementation_Blueprint.pdf` (14 October 2026). All tickers, prices, volumes, filings and investor portfolios in this repository are simulated. This is research software, not investment advice.

## Run locally

Requires Python 3.10+; no packages or API keys are needed.

```powershell
python -m contra.server
```

Open <http://localhost:8000>. The SQLite database is created at `data/contra.sqlite3` on first run. `CONTRA_DB` can point to a different database path.

## Demo

1. Select **ALPHA.NS** and **Conservative**, then run analysis. Price momentum is positive while a cited filing is negative; the 15% position also exceeds the 10% cap.
2. Select **Growth** and run the same stock and date. Market facts and snapshot hash stay equal while the 30% cap changes suitability.
3. Select **GAMMA.NS** to see aligned positive evidence. Select **DELTA.NS** to see a missing-filing partial result.
4. Open cited excerpts, timings and the evaluation page. Refresh a saved run URL to verify persistence.

The three analyzers execute concurrently as independent deterministic fallback pipelines. The UI labels this explicitly; it does not claim LLM reasoning. A future model adapter can interpret the validated facts, but cannot override calculated figures or source IDs.

## API

`GET /health`, `/v1/stocks`, `/v1/profiles`, `/v1/profiles/{id}/portfolio`, `/v1/analyses/{run_id}`, `/v1/evidence/{id}`, `/v1/evaluations/summary`; `POST /v1/analyses`; `PUT /v1/profiles/{id}`. JSON errors have an `error` code and `message`.

An analysis POST accepts `ticker`, `investor_id`, `dataset_id` (optional, fixed to `contra_synthetic_v1`), and `as_of` (optional, the fixture end date). The response includes the frozen market snapshot hash, three signals, three timed agent results, synthesis, cited evidence, and measured metrics.

## Verify

```powershell
python -m unittest discover -s tests -v
```

The tests cover concurrency, source integrity, profile isolation, missing filings, future document exclusion, short history, and persisted replay.

## Scope

This is an offline MVP. It has four synthetic stocks, generated dated bars, 16 synthetic filing excerpts, two stored investor profiles, a local SQLite audit log, deterministic lexical retrieval, and a measured evaluation view. The lexical retriever is deliberately small; it is not a production financial RAG system. There is no live feed, brokerage connection, trade action, hosted deployment, or LLM call. The synthetic scenario checks shown in Evaluation measure fixture behavior, not market prediction accuracy.
