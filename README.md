# CONTRA

An evidence-first, synthetic financial research demo based on `CONTRA_Architecture_and_Implementation_Blueprint.pdf` (14 October 2026). All tickers, prices, volumes, filings and investor portfolios in this repository are simulated. This is research software, not investment advice.

## Run locally

Requires Python 3.10+; no packages or API keys are needed.

```powershell
python -m contra.server
```

Open <http://localhost:8000>. The SQLite database is created at `data/contra.sqlite3` on first run. `CONTRA_DB` can point to a different database path.

Implementation notes: [architecture](docs/architecture.md) · [five-minute demo](docs/demo.md) · [acceptance status](docs/acceptance.md).

## Demo

1. Select **ALPHA.NS** and **Conservative**, then run analysis. Price momentum is positive while a cited filing is negative; the 15% position also exceeds the 10% cap.
2. Select **Growth** and run the same stock and date. Market facts and snapshot hash stay equal while the 30% cap changes suitability.
3. Select **GAMMA.NS** to see aligned positive evidence. Select **DELTA.NS** to see a missing-filing partial result.
4. Open cited excerpts and market bars from the signal cards. The report includes a chart computed from its frozen simulated closes.
5. Use **Compare** to see both investor outcomes side by side against the same market snapshot. Refresh a saved run URL to verify persistence.
6. Reopen a report from **Recent analyses**. Open Evaluation to execute the synthetic scenario matrix, inspect citation validity and Recall@3, then run the 10-execution latency benchmark.

The terminal also accepts an as-of date within the fixture range. Choosing an early date with fewer than 21 bars produces `INSUFFICIENT_EVIDENCE`; future-dated documents never enter that run.

The three analyzers execute concurrently. With no model configuration, they use independent deterministic fallback pipelines and the UI labels this explicitly. An optional server-side model adapter can select a constrained focus and source IDs; numeric values, statuses, assessments and canonical facts remain code-authoritative. A failed or invalid model response falls back per agent.

To enable model reasoning, set `CONTRA_LLM=1` and a valid `OPENAI_API_KEY` in the **server process** before starting it. `CONTRA_MODEL` defaults to `gpt-6-astra`; see [.env.example](.env.example). This makes up to three API calls per analysis. The Evaluation scenarios and ten-run benchmark always stay deterministic, so they do not make model calls. The key is never returned to the browser or stored in a run. The adapter is covered by mocked tests; this workspace has no API key, so no live model call was run here.

## API

`GET /health`, `/v1/stocks`, `/v1/profiles`, `/v1/profiles/{id}/portfolio`, `/v1/analyses`, `/v1/analyses/{run_id}`, `/v1/analyses/{run_id}/evidence/{id}`, `/v1/evidence` (optional `ticker` and `as_of` filters), `/v1/evidence/{id}`, `/v1/evaluations/summary`, `/v1/evaluations/benchmark`; `POST /v1/analyses`; `PUT /v1/profiles/{id}`. The run-scoped evidence route opens the exact frozen source used in that analysis. JSON errors have an `error` code and `message`.

An analysis POST accepts `ticker`, `investor_id`, `dataset_id` (optional, fixed to `contra_synthetic_v1`), and `as_of` (optional, the fixture end date). The response includes frozen market bars and eligible document text, a separate investor snapshot, both hashes, three signals, three timed agent results, synthesis, cited evidence, and measured metrics.

Profile updates may include `expected_revision`. A stale revision returns HTTP 409, so one investor's changes cannot silently overwrite a newer edit.

## Verify

```powershell
python -m unittest discover -s tests -v
```

The tests cover concurrency, source integrity, profile isolation, missing filings, future document exclusion, short history, persisted replay, and a real isolated HTTP lifecycle.

With the server running, an optional JavaScript runtime smoke test checks that the terminal, report, comparison, evaluation, evidence and portfolio views render without a runtime error. It creates two synthetic saved runs:

```powershell
node tests/ui_smoke.js
```

On this Windows machine, VS Code's bundled Node runtime can run the same script when `node` is not installed: set `ELECTRON_RUN_AS_NODE=1` for the `Code.exe tests/ui_smoke.js` command.

## Scope

This is an offline-capable MVP. It has four synthetic stocks, generated dated bars, 16 synthetic filing excerpts, two stored investor profiles, a local SQLite audit log, issuer/date filtered TF-IDF retrieval, and a measured evaluation view. The fixture corpus is deliberately small; it is not a production financial RAG system. There is no live feed, brokerage connection, trade action or hosted deployment. Model calls are optional and remain unverified against a live account in this workspace. The synthetic scenario checks shown in Evaluation measure fixture behavior, not market prediction accuracy.

For a clean restart, stop the Python process serving port 8000, then run `python -m contra.server` again. The browser URL only works while the process is running. Runtime databases and logs under `data/` are ignored by Git.
