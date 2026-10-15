# Improvement log

## 14 October 2026 — local MVP review

Scope: the supplied architecture blueprint and the current synthetic, localhost demonstration. These scores are reviewer judgments, not measured product outcomes. No project-specific hackathon scoring rubric is present in the repository.

| Category | Before | After | Evidence or remaining constraint |
| --- | ---: | ---: | --- |
| Problem–solution fit | 6 | 6 | Evidence and portfolio disagreement is clear in the demo; real filings and market data are absent. |
| Innovation | 6 | 6 | Frozen dual-context comparison and explicit abstention are useful, but not validated on real research tasks. |
| Technical execution | 7 | 7 | Deterministic pipeline, immutable reports and 28 passing tests; local architecture only. |
| UI/UX | 7 | 7 | Desktop and 500 px layouts inspected; navigation freshness improved. Narrower mobile viewport was not reliably emulated by the available headless Chrome mode. |
| Functional completeness | 6 | 6 | Advertised synthetic flows work; imported data remains staged and cannot be analyzed. |
| Reliability | 7 | 8 | Stale evaluation responses no longer replace the page reached after navigation. |
| Security | 4 | 6 | Loopback-only binding, Host and mutation Origin checks, JSON-only mutations, and response security headers; no user authentication. |
| Performance | 7 | 7 | Local benchmark exists, but no production load test or multi-user evaluation. |
| Architecture | 7 | 7 | Clear modules and source contracts; fixture assumptions still run throughout analysis. |
| Demo impact | 7 | 7 | The three scenarios and saved evidence are easy to show; synthetic scope limits the claim. |

### Cycle 1: local API boundary

- **P1, resolved for local use — `contra/server.py`:** the unauthenticated API could be bound to a non-loopback interface and accepted untrusted Host and browser Origin values. A malicious site or network client could attempt to modify local profiles or create runs. The server now refuses non-loopback bind addresses; requests require a loopback Host; mutations require JSON and reject foreign Origin values. Static and API responses add content, referrer and framing controls. `tests/test_http.py` exercises both rejected and valid requests.
- **Remaining P1 for public use:** there is no authentication, authorization, TLS termination, abuse control or deployed database. Public hosting is outside the safe operating envelope of this local server.

### Cycle 2: navigation freshness

- **P2, resolved — `web/app.js`:** a slow evaluation, report or evidence response could paint content after the user had navigated elsewhere. Each render now carries a token and drops stale responses. `tests/ui_smoke.js` simulates a delayed evaluation response and verifies that the terminal stays visible.
- **Verification:** Python unit and HTTP suite: 28 passing tests. JavaScript syntax and UI runtime smoke passed. The local server was restarted on the updated code; desktop and 500 px screenshots were inspected. No type checker, bundler or lint configuration exists for this dependency-free repository.

### Cycle 3: async action replay

- **P2, resolved — `web/app.js`:** a benchmark response could arrive after leaving Evaluation and write into a missing result element, creating an unhandled client error. The benchmark now ignores results and failures from a prior render. `tests/ui_smoke.js` delays the response, navigates away, and waits for the action to settle without replacing the terminal.
- **Verification:** all 28 Python tests and the UI runtime smoke still pass after this change.

### Cycle 4: evidence drawer freshness

- **P2, resolved — `web/app.js`:** a late evidence response could reopen the drawer after navigation. Source details and errors now appear only while their originating render is current. The UI smoke delays a source request, navigates away, and confirms the drawer stays closed.
- **Verification:** 28 Python tests, JavaScript syntax check and UI runtime smoke pass. No new high-impact local issue was found in this pass; public-use gaps below remain.

### Current highest-impact gaps

1. **P1 for real-world use — data and provenance:** `contra/fixtures.py`, `contra/core.py`, `contra/import_data.py`. Imported snapshots are validated and staged, but analysis still uses synthetic fixtures. Licensed feeds, issuer filing verification and a trustworthy interpretation method are not implemented.
2. **P1 for public use — identity and deployment:** `contra/server.py`, `contra/store.py`. The server is intentionally local and unauthenticated. Hosted access requires an identity model, access controls and durable storage.
3. **P2 — broader client verification:** `web/app.js`, `web/style.css`. The current smoke harness covers main page rendering and three navigation races. A full browser journey across the report, portfolio edit and error states would give stronger confidence.

## 15 October 2026 — problem statement alignment

Scope: PS 04 (VibeFinance): a multi-agent investment intelligence system with at least three parallel agents, financial document RAG, personalized portfolio insights and explainable recommendations. These scores are reviewer judgments against that statement.

| Category | Before | After | Evidence |
| --- | ---: | ---: | --- |
| Problem–solution fit | 5 | 8 | Each report now ends in a sized, cited, personalized action; filings can be questioned; holdings get limit insights. |
| Innovation | 6 | 7 | The same frozen market produces different, explained actions per investor, with counterfactuals. |
| Technical execution | 7 | 8 | Retrieval bugs fixed; 33 Python tests and the extended UI smoke test pass. |
| UI/UX | 7 | 8 | Action card, Ask the filings and insights table inspected at 1440 px and at 390 px using DevTools device emulation. |
| Functional completeness | 5 | 8 | All four statement requirements have a working, tested path. |
| Reliability | 8 | 8 | New routes validate input and return typed 400/404/409 errors. |
| Security | 6 | 6 | Unchanged local-only boundary; the new routes are read-only GET requests. |
| Demo impact | 6 | 8 | The scenario cards, demo script and evaluation matrix now show the action. |

### Cycle 5: explainable personalized action (P1)

- **Problem:** the statement asks for explainable recommendations, but a report ended at a state label without saying what this investor should do.
- **Change (`contra/core.py` `recommend`):** the change adds a deterministic priority policy over validated agent outputs and the saved profile. Every report records the action, the rule that fired, cited reasons, sizing (trim to restore the larger breached limit, or room to add bounded by caps and cash), and what would change the action. The report checksum covers this output. Older runs show a notice instead.
- **Verification:** tests cover all actions, the sector-trim arithmetic, the cash bound and the wording for unheld stocks. The scenario matrix now also checks the expected action.

### Cycle 6: filing question answering (P1)

- **Change:** `GET /v1/analyses/{run_id}/ask?q=` searches only that run's frozen, as-of eligible filings. It returns exact passages with age and relevance, or `NO_SUPPORTING_PASSAGE`. The report page adds the Ask panel with suggested questions.

### Cycle 7: retrieval correctness (P2)

- **Problem:** stopwords such as "the" matched unrelated passages. Query plurals did not match singular filing words, so the positive ALPHA.NS contract excerpt was never retrieved. A 220-day-old excerpt drove current filing tone.
- **Change:** stopword removal, plural folding, and a 180-day window for the tone signal. ALPHA.NS still resolves to NEGATIVE / CONFLICTED, now from three recent excerpts.

### Cycle 8: portfolio insights and integrity coverage

- `GET /v1/profiles/{id}/insights` and the Portfolio page now show weight against cap, the trim that would restore a breached cap, and room to add for each holding.
- `verify_run` checked frozen snapshot hashes only for `rules-1.1`. It now checks every versioned `rules-*` run, so the new version cannot skip the check.

### Remaining gaps

- The LLM adapter is still unverified against a live key. All agent reasoning runs in labeled deterministic fallback here.
- The data is synthetic, and the analysis API accepts only the built-in dataset.

## 15 October 2026 — accounts, live data and hosting readiness

### Cycle 9: model key configuration
- `.env` (ignored by Git) is loaded at startup without overriding shell variables. The startup log states whether model reasoning is on. HTTP tests pin `CONTRA_LLM=0`, so a developer's key never turns tests into paid calls.

### Cycle 10: real market data (P1)
- Users add NSE/BSE symbols; CONTRA fetches real daily closes from Yahoo Finance and caches them. A forming same-day bar is excluded. The report labels LIVE data, the source URL and any cache-fallback warning.
- Users paste dated filing excerpts. These are hashed, tone-tagged by a disclosed word-list heuristic or by the user's label, searchable through Ask the filings, and never eligible before their publication date.

### Cycle 11: accounts and isolation (P1)
- Sign-up, login, guest sessions and logout. Every API route requires a session, and all data is scoped to its owner. Login, sign-up, symbol additions and analyses are rate-limited.

### Cycle 12: hosting readiness
- Hosted mode (`CONTRA_PUBLIC=1`) accepts configured or Render-provided hostnames, sets Secure cookies and HSTS, and takes the client IP from the proxy-appended `X-Forwarded-For` entry. A Dockerfile and Render Blueprint are included.
- **Verification:** 42 Python tests, including hosted-mode rules, pass. The UI smoke test passes with a guest session. A browser flow was inspected at 1440 px and 390 px: guest login → add RELIANCE.NS (real Yahoo data) → upload a filing → set holdings → LIVE report with a sized action. Docker was unavailable, so the container image was not built.

### Remaining gaps
- No deployment has been made. Free hosting loses data on restart unless a persistent disk is attached.
- Yahoo's endpoint is unofficial and unlicensed. Filings are user-supplied and unverified. Tone is a heuristic.
- No email verification or password reset. Rate limits are per process.

## 15 October 2026 — grounded model briefings and semantic filing search

### Cycle 13: model-written agent briefings (AI depth)
- Market and Research agents now get a one-to-three sentence model summary, verified by code before display.
- Real-model findings drove the rules:
  1. The first run produced no inline citations. The fix attaches every eligible source ID, not only the focus IDs, after one summary described a contract without citing its excerpt.
  2. The checker rejected "no breaches" until it became negation-aware.
  3. A summary passed a "numbers must exist in the facts" check while attaching the cap (10%) to the position weight. Numbers were therefore banned from summaries entirely; exact values stay code-computed.
  4. Risk summaries invented an "acceptable" HHI range. Risk now always uses its exact rule summary, and judgment and limit words are rejected for the other agents.
- Final warm-up with gpt-4.1-nano: 15 paid calls, 14/14 Market and Research briefings verified. Each was reviewed by hand.

### Cycle 14: semantic filing search
- Hybrid embeddings + TF-IDF in Ask the filings. The 0.38 threshold was calibrated on separate questions. On held-out paraphrases, Recall@3 is 100% (keywords only: 86%), and 4/4 unrelated questions abstain. The corpus is synthetic.
- Embeddings are cached, durable, shipped for the demo texts, and capped per account and per day. Provider failure falls back to keywords with a visible note.

### Cycle 15: concurrency fix
- Three agent threads opening a fresh database at once could run the schema migration concurrently (`OperationalError`). First-time migration is now locked.
- **Verification:** 59 Python tests and the UI smoke test pass. The report, evaluation and mobile views were inspected in a browser.
