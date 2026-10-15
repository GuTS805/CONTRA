# Blueprint acceptance status

The supplied blueprint is the target specification. This table records what the current repository proves. Run `python -m unittest discover -s tests -v` and, with the server running, `node tests/ui_smoke.js` for repeatable checks.

| Blueprint test | Current proof | Status |
| --- | --- | --- |
| T01 — Valid synthetic analysis | ALPHA.NS HTTP analysis returns all four dimensions, as-of and data mode. | Local pass |
| T02 — Agent overlap | Timed Market, Research and Risk intervals overlap; concurrency assertion runs in tests. | Local pass |
| T03 — Cited research source opens | Run-scoped evidence endpoint returns exact frozen excerpt, date, locator and hash. | Local pass |
| T04 — Same market, changed investor | A/B tests assert equal market hash and signals with different suitability. | Local pass |
| T05 — Saved run reopens | SQLite replay returns the exact stored report after POST. | Local pass |
| T06 — Missing eligible filing | DELTA.NS research abstains; no fabricated citation appears. | Local pass |
| T07 — Contradictory perspectives | ALPHA.NS yields source-backed CONFLICTED state. | Local pass |
| T08 — Evaluation metrics | Saved-run latency, citation validity and concentration; fixture matrix, Recall@3 and ten-run benchmark. | Local pass |
| T09 — Short/invalid bars | Fewer than 21 bars, zero or non-finite volume cannot produce a numeric signal. | Local pass |
| T10 — Future filing excluded | As-of filter excludes all future-dated DELTA.NS excerpts. | Local pass |
| T11 — Invalid identifiers | HTTP API returns typed 400/404 errors; stale profile revision returns 409. | Local pass |
| T13 — Explainable personalized action | Same ALPHA.NS market gives Reduce exposure (−5,000 to the 10% cap) for Conservative and Hold · review for Growth; every reason carries source IDs; additions are bounded by caps and available cash. | Local pass |
| T14 — Filing question answering | Ask route returns exact stored passages from as-of eligible filings, abstains on unsupported questions, and never searches future filings. | Local pass |
| T15 — Portfolio insights | Per-holding cap checks with trim-to-cap and room-to-add values for each saved profile. | Local pass |
| T16 — Accounts and isolation | Sign-up, login, guest and logout over HTTP; another account gets 404 for a run and sees its own profiles; usernames are unique regardless of case. | Local pass |
| T17 — Live symbol analysis | Yahoo chart parsing drops forming, null and zero-volume bars; a LIVE analysis with an uploaded filing runs from a seeded cache; provider failure falls back to cache with a warning. | Local pass (parser on recorded payloads; RELIANCE.NS and TCS.NS fetched manually in a browser session) |
| T18 — Grounded model briefings | Code verifies each model-written Market/Research briefing: allowed citations only, no digits, no advice or judgment words, no contradiction; failures fall back to labeled rule summaries. In a real gpt-4.1-nano warm-up, 14 of 14 briefings passed after these rules, and each was reviewed by hand. | Local pass |
| T19 — Semantic filing search | Hybrid embeddings + TF-IDF on held-out paraphrases: Recall@3 100% versus 86% for keywords only; 4 of 4 unrelated questions abstain. | Local pass (synthetic corpus) |
| T20 — Real filings | 8 Infosys excerpts from SEC EDGAR: `python -m contra.public_filings` confirms all 8 match their filings exactly. Research claims must match an exact quote's topic, direction, quality words and negation; the real "guidance revised upward" error is a regression test. | Local pass |
| T12 - Hosted operation | Public health endpoint returned OK on 15 October 2026. GitHub CI for commit 30438fe passed, including UI runtime and container checks. This is health/build verification, not a complete production user journey. | Verified with stated scope |
| T21 - Institutional flows | Official NSE endpoint fetched and parsed; synthetic/live isolation, arithmetic, as-of, missing/stale data and frozen evidence checks. | Local pass; live source verified |
| T22 - Precise sizing | Near-cap holdings use original amounts; residual sector excess is disclosed; unheld stock does not receive a sell instruction. | Regression tested |
| T23 - Visible degradation evaluation | Seven fault-injection checks execute on Evaluation with expected and observed results. | Local pass |

## Verification boundaries

- The 15 October audit added sizing regressions and visible degradation checks. Run the test suite for the current count; prior counts in the improvement log refer to earlier commits.
- The prior FII/DII browser check inspected four cards, source drawer and mobile overflow. Current evaluation UI is checked separately before handoff.
- No new paid model requests were made in this audit. Warm-up artifacts and prior manual verification are historical evidence, not a fresh production model test.
- Free-tier hosting has temporary storage. A persistent disk or managed database is still needed for durable accounts and reports.
- Synthetic retrieval and scenario checks do not establish real filing quality or financial predictive performance.
- The Wild Bugs participant dashboard can contain additional submission requirements. Public problem statement mapping is in [wild-bugs-submission.md](wild-bugs-submission.md).
