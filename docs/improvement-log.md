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

### Cycle 16: real-company filings and quote-grounded research briefings
- Added a one-click Infosys example: live NSE prices plus 8 exact excerpts from its SEC filings (Q4 FY26 and Q1 FY27 results releases, 2026 Form 20-F). Each excerpt keeps its form, filing date and EDGAR URL. `python -m contra.public_filings` re-checks every excerpt against EDGAR; all 8 matched.
- On the first real run, a verified Research briefing said Infosys's revenue guidance was "revised upward". The filing narrowed the range from 1.5%-3.5% to 1.5%-3.0%. Word-level checks could not catch a direction borrowed from another excerpt.
- Research briefings are now claims: each sentence with one source ID and an exact quote from it. Code rejects the claim when the quote is not exact text, or when the sentence names a topic, direction, quality word or negation that the quote does not contain. The original error is a regression test.
- A real Market briefing read above-typical volume as "a decline in market activity". Market briefings may no longer interpret the measurements, and may not describe price direction against the measured sign.
- Re-warm with gpt-4.1-nano (briefing-2.1): 15 paid calls, 10 of 14 briefings verified, 4 replaced by labeled rule summaries. Reasons: a sentence naming revenue that its quote lacked, and "suggest a bullish market condition".

### Cycle 17: three investor profiles and an all-investor comparison
- Added a third sample profile, Starter: a newer, cash-heavy investor with a 15% single-name cap and a 40% sector cap, who does not hold ALPHA. Existing accounts receive it on their next profile listing.
- The report has a new **Same evidence, every investor** panel. It runs the frozen snapshot for every saved profile and shows each holding, action and headline, with a check that the market snapshot is identical.
- On ALPHA the three actions differ: reduce by about 5,000, hold and review, do not open a position. On GAMMA the room to add is 5,000, 25,000 and 10,000.


## 15 October 2026: Wild Bugs PS 04 audit

Official weights were taken from the problem statement linked on the Wild Bugs overview, not from Arkiv. The participant dashboard itself was not accessible to this audit.

### Fixed

- P1: sizing reconstructed holdings from rounded percentages. Amounts now come from original saved positions; near-cap regressions cover both adding and trimming.
- P1: a full exit from one stock could leave a sector breach while claiming limits were cleared. The recommendation now reports residual excess; an unheld stock is not given a sell instruction.
- P1: interrupted NSE HTTP responses could escape the graceful fallback. Truncated responses now leave flows unavailable or use eligible cache.
- P2: profile comparisons now retain sector classifications as well as original bars, filings and flows.
- P2: Evaluation runs seven visible fault-injection checks, with expected and observed values. They are explicitly regression checks, not financial accuracy measurements.
- P2: architecture and acceptance documentation contained obsolete synthetic-only and not-deployed claims. Updated to match verified capabilities and verification limits.
- P2: refreshed the demo sequence to include the fourth signal and an explicit unsupported weather question.

### Verification

- `python -m unittest discover -s tests`: 77 tests passed after these changes.
- Public deployment `/health`: OK; model and semantic-search configuration enabled. This does not prove a paid model call or the full deployed user journey.
- Public GitHub CI for prior commit `30438fe`: success, including Python, UI runtime and container checks. Current changes require their own CI run after publication.
- Updated video is recorded with model and embedding calls disabled, using an isolated local database.

### Internal rubric review, not an official judging score

These estimates identify remaining work, not a probability of winning.

| Criterion | Before | After | Maximum | Evidence and remaining gap |
| --- | ---: | ---: | ---: | --- |
| Signal analysis | 14 | 14 | 20 | Four cited dimensions; heuristic thresholds remain uncalibrated |
| Agent execution and synthesis | 16 | 16 | 20 | Three parallel contracts, explicit conflict and partial states |
| Retrieval and attribution | 11 | 11 | 15 | Exact passages and small-corpus evaluation; larger real-corpus validation remains |
| Personalization and risk | 11 | 13 | 15 | Exact sizing and residual exposure corrected; profiles remain manually valued |
| Engineering and reliability | 7 | 8 | 10 | More failure coverage; temporary hosting storage remains |
| Evaluation quality | 6 | 7 | 10 | Visible degraded-input checks; no return backtest |
| Explanation and commercial fit | 7 | 8 | 10 | Rubric proof map and updated demo; no user/pricing validation |
| Total | 72 | 77 | 100 | Provisional internal review |

Remaining external requirements: inspect the participant dashboard for exact submission fields and rules; upload a playable video; confirm the submitted revision is deployed; keep the app available during judging. No automatic submission or paid hosting change was made.

### Cycle 18: model filing tone and a higher briefing pass rate
- **Filing tone from a model.** The word list had marked "Revenue growth of 1.5%-3.5%" positive because it contains "growth", and the lowered guidance range neutral. A model now classifies each excerpt as positive, negative or neutral and must quote the excerpt exactly. A new upload is classified when it is saved. If the model is unavailable, over budget or fails the quote check, the word-list tone is kept and labeled. The eight Infosys excerpts ship with their verified tones, so the demo costs nothing at runtime. In the source drawer the tone shows its model, its source and the quote.
- **Briefing pass rate.** Verified model briefings passed 15 of 21 before institutional flows were added to the Market facts, and 12 of 21 on the first re-warm after. Reading the rejected text showed two verifier rules were wrong, not the model. "Buying" and "selling" are measured facts for institutional flows, so only directive uses ("consider buying") count as advice. "Volume rose" no longer counts as a price-direction contradiction. The prompts also name the words the verifier rejects. After the fixes, 21 of 21 Market and Research briefings passed, and each was read by hand. The prompt version is now `briefing-2.3`.

### Cycle 19: walk-forward backtest of the price signals
- `python -m contra.backtest` fetches about five years of daily closes for 20 NSE large caps, recomputes the Market agent's momentum label at past dates from bars up to that date only, and compares it with the next 21 sessions. One window per symbol per horizon, a 70/30 chronological split, a baseline set (always-bullish, held-out majority class, a seeded permutation test) and Wilson intervals. The settings were fixed before the first run.
- **The result is unflattering and is published as measured.** Of 689 directional windows, 45.9% were right (95% interval 42.2% to 49.6%), against 52.0% for always guessing up (permutation p = 0.99). On the held-out period the rate was 40.3%. Windows labeled BEARISH were followed by a higher average return than windows labeled BULLISH, so one-month momentum behaved like mean reversion over this sample. Elevated volume was followed by only slightly larger absolute moves (5.1% against 4.8%).
- The thresholds were not changed to improve the number. The UI states "no predictive edge demonstrated". Caveats are listed in the report: only price signals are tested, survivorship bias, dividend-unadjusted closes, no costs, and correlated stocks narrow the intervals.

### Cycle 20: a disagreement investigator, and a verifier fix it exposed
- When the Market and Research agents point in opposite directions, a model agent now works in three steps. It plans one or two questions from the titles and dates of the available excerpts, code runs them through the same issuer-gated hybrid search as "Ask the filings", and the model writes one-sentence findings from only the passages that came back. Each finding must carry an exact quote and passes the Research-briefing rules, with no numbers, advice, judgments or portfolio talk.
- The balance is read by code from the tone tags of every returned passage, so a one-sided summary cannot hide a passage that pointed the other way. Passages the findings skip are listed. The recommended action still comes from the fixed policy; the report says so.
- It runs only on a conflict, costs two calls, is cached by the evidence, shipped for the ALPHA scenario, and never fails a run: a budget limit, a timeout or a rejected answer is recorded with its reason. In the first real run the planner copied the instruction words into a question and asked only one side, so the prompt now names which side each question tests, and brackets are rejected.
- **Verifier fix.** A test of the new agent showed the Research-claim rules accepted "margin improved as costs rose" against a quote that said "narrowed as component costs rose", because "rose" appeared in both and satisfied the check for a rise word. Every rise or fall word in a sentence must now also appear, by stem, in its quote. This tightens Research briefings too, and all 21 Market and Research briefings still passed.
