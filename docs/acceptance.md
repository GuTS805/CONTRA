# Blueprint acceptance status

The supplied blueprint is the target specification. This table records what the current repository proves. Run `python -m unittest discover -s tests -v` and, with the server running, `node tests/ui_smoke.js` for repeatable checks.

| Blueprint test | Current proof | Status |
| --- | --- | --- |
| T01 — Valid synthetic analysis | ALPHA.NS HTTP analysis returns all three dimensions, as-of and data mode. | Local pass |
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
| T12 — Production inspection | Hosted-mode test checks public Host, Origin, Secure/HttpOnly cookie and HSTS. Dockerfile and Render Blueprint are included. The container was not built here (Docker unavailable) and no deployment has been made. | Deploy-ready; not deployed |

## Remaining blueprint work

- Live model requests have not been verified against an account. The optional adapter is tested with mocked responses and falls back deterministically when disabled or invalid.
- Accounts and hosting configuration exist, but no deployment has been made. Free-tier hosting has a temporary disk; durable storage needs a persistent disk or a managed database.
- The synthetic corpus and lexical retrieval do not establish real filing quality or financial predictive performance.
- Compliance review and licensed market-data access are prerequisites for any real investor-facing use.
