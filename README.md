# CONTRA

**Live demo:** <https://contra-h0nw.onrender.com>. Click **Continue as guest**. The free instance sleeps when idle, so the first load can take up to a minute.

CONTRA is an evidence-first investment research assistant. Three agents run concurrently on one frozen snapshot: Market (price momentum, volume and institutional-flow context), Research (retrieval over dated filing excerpts) and Risk (the investor's own limits). CONTRA then gives a personalized, sized portfolio action with cited reasons and the conditions that would change it.

It works on two kinds of data, and each report labels which one it used:

- **Live:** any NSE (`.NS`) or BSE (`.BO`) symbol you add. Prices are real daily closes from Yahoo Finance's public chart endpoint. Filings are excerpts you paste, stored with their publication date and hash.
- **Real-company example:** click **Load Infosys** on the terminal. This adds INFY.NS with live prices and 8 exact excerpts from Infosys's SEC filings (the April and July 2026 results releases and the 2026 Form 20-F), each linked to its filing on SEC EDGAR.
- **Synthetic:** four built-in scenario stocks with known expected outcomes, used for demos and the evaluation suite.

This is research software, not investment advice. It never places trades.

## Run locally

Requires Python 3.10+. There are no third-party packages.

```powershell
python -m contra.server
```

Open <http://localhost:8000>. You can create an account or continue as a guest. Each account gets its own investor profiles, holdings, live symbols, filings and saved reports. The SQLite database is created at `data/contra.sqlite3`; `CONTRA_DB` can point elsewhere.

On Windows, the background starter checks health before launching a hidden server:

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\start-local.ps1
```

### Model reasoning (optional)

Put your key in `.env` in the project root. Git ignores this file.

```
OPENAI_API_KEY=sk-...
CONTRA_LLM=1
```

The key is enough. Without `CONTRA_MODEL`, the server lists the models your key can access (a free call) and uses the first available of `gpt-4.1-nano`, `gpt-4o-mini`, `gpt-4.1-mini`, `gpt-5-nano` and `gpt-5-mini`. Set `CONTRA_MODEL` to override this choice.

The server loads `.env` at startup. Variables already set in the shell take precedence. The startup log states whether model reasoning is enabled. Each analysis makes up to three model calls, one per agent. The model may only pick a permitted focus and cite source IDs that the agent already holds; numbers, statuses and the action stay code-computed. An invalid or failed response falls back to deterministic reasoning, and the report labels each agent's mode. To protect a small credit balance, an identical agent input reuses the earlier validated answer instead of paying again, and `CONTRA_LLM_DAILY_LIMIT` (default 150, 60 in `.env` and on Render) caps paid calls per UTC day. After the cap, agents fall back with a visible warning; `/health` reports today's usage. The key is never sent to the browser or stored in a report. The model adapter has mocked tests only; a live call has not been verified from this workspace.

#### What the model does

- **Agent briefings:** under "What each agent found", the Market and Research agents each get one to three plain-language sentences from the model, written only from that agent's validated facts. Code then checks every briefing. It must cite only that agent's sources. For Research, each sentence must come with the exact words it rests on from one cited excerpt. Any topic (revenue, guidance, debt…), direction of change (rose, cut…), quality word (strong, stable…) or negation in the sentence must also appear in that quote. On real Infosys filings, the model once wrote that revenue guidance was "revised upward" when the range had been narrowed. This rule now rejects that. Market summaries may not interpret the measurements ("suggests", "outlook", "sentiment"), and may not describe the price direction against the sign of the measured change. It may not contain any digit, because a correct number can still be attached to the wrong quantity, so the exact values come from code on the cards. It may not use advice or prediction words (buy, sell, should, will rise), judgment words (acceptable, healthy, undervalued) or portfolio-limit terms. It may not contradict the agent's direction; "not bearish" is not treated as bearish. A briefing that fails any check is dropped and replaced by a rule-based summary, which the card labels. The Risk agent always uses its exact rule-based summary.
- **Filing search:** "Ask the filings" combines OpenAI `text-embedding-3-small` similarity (256 dimensions) with TF-IDF. A passage qualifies if it shares a meaningful word with the question or reaches a similarity of 0.38. That threshold was set on calibration questions: relevant ones scored 0.43–0.67, unrelated ones 0.04–0.32. Only exact stored excerpts are returned, and nothing is generated. Without embeddings, search falls back to keywords and says so.
- On the held-out paraphrase set in Evaluation (7 questions plus 4 unrelated ones), Recall@3 is 86% with keywords only and 100% with hybrid search, and all 4 unrelated questions return nothing. One relevant question scored 0.389, just above the threshold. These questions use the synthetic excerpts, so the numbers do not establish quality on real filings.

#### Keeping a small credit balance safe for judges

- **Cache:** an identical agent input reuses its earlier validated answer, and the database keeps those answers across restarts.
- **Embeddings:** these are cached the same way and have their own limits: `CONTRA_EMBED_ACCOUNT_DAILY_LIMIT` (default 40 requests per account per day) and `CONTRA_EMBED_DAILY_LIMIT` (default 300). `CONTRA_EMBEDDINGS=0` turns semantic search off.
- **Daily limits:** each account may trigger at most `CONTRA_LLM_ACCOUNT_DAILY_LIMIT` paid calls per day (default 9, about three analyses). The whole server stops at `CONTRA_LLM_DAILY_LIMIT`. One visitor therefore cannot use up the budget before a judge arrives. Once a limit is reached, the agents continue rule-based and the report says the model is paused. Facts and the action do not change.
- **Warm-up:** before judging, run `python -m contra.warm` once. It answers every synthetic scenario for all three sample profiles. Repeated inputs are answered once, so this needs 19 paid calls. In the latest warm-up, 15 of 21 Market and Research briefings passed verification, and the other 6 fell back to labeled rule summaries. It saves the answers to `data/fixtures/model_cache.json`, and the vectors for the synthetic filings, the Infosys excerpts, suggested questions and evaluation questions to `data/fixtures/embedding_cache.json`. Commit that file, and the server preloads it, including on a fresh hosted instance whose disk was wiped. Judges then see model reasoning on every scenario at no cost. Each reused answer is labeled "cached answer from <date>". The cache is keyed by model name, so run the warm-up again if you change `CONTRA_MODEL`.

Implementation notes: [architecture](docs/architecture.md) · [five-minute demo](docs/demo.md) · [acceptance status](docs/acceptance.md) · [improvement log](docs/improvement-log.md).

## Using live data

1. On the terminal, add a symbol such as `RELIANCE.NS` and pick its sector. CONTRA fetches about six months of daily bars. A bar for the current day is skipped until the session closes.
2. In **Evidence library**, paste a filing excerpt for that symbol with its publication date and an optional HTTPS source link. Tone comes from a small finance word list unless you label it Positive, Neutral or Negative.
3. On **Portfolio**, enter your holding values. Every symbol you add appears there.
4. Run the analysis. The report freezes the bars and filings visible at the as-of date, hashes them, and saves the result to your account.

For a ready example, **Load Infosys** does steps 1–2 with real filings. `data/fixtures/public_filings.json` holds each excerpt with its form, filing date and SEC URL. Excerpts are copied exactly; only whitespace is collapsed. To re-check all of them against SEC EDGAR:

```powershell
$env:SEC_USER_AGENT = "Your Name you@example.com"   # SEC asks automated clients to identify themselves
python -m contra.public_filings
```

Prices are cached for six hours. If Yahoo Finance cannot be reached, CONTRA uses the cached prices and shows a warning in the report. With no cache, the request fails with a clear error. The Yahoo endpoint is unofficial: it can change, rate-limit or block hosting IP ranges, and it carries no redistribution licence. Closes are not adjusted for splits or dividends.

## Demo with the synthetic scenarios

1. Select **ALPHA.NS** and **Conservative**, then run the analysis. Price momentum is positive while cited filings are negative, and the 15% position exceeds the 10% cap. The action is **Reduce exposure** by about 5,000 (15% → 10%).
2. Click **Compare all 3 investors**. The same frozen snapshot is run for Conservative (10% cap), Growth (30% cap) and Starter (a newer, cash-heavy investor who does not hold ALPHA). The market hash and signals are identical, but the actions differ: reduce by about 5,000, hold and review, and do not open a position. **Compare Growth** shows the full side-by-side for one pair.
3. In **Ask the filings**, click "Is profitability getting squeezed?". No excerpt contains those words, but semantic search finds the margin passage. The answer is the exact cited excerpt. A question that no filing supports returns no passage instead of a guess.
4. Select **GAMMA.NS** to see aligned evidence and a sized room to add, or **DELTA.NS** to see an honest partial result with no eligible filing.
5. Open **Evaluation** to run the scenario matrix (state and action), check citation validity and Recall@3, and run a 10-execution latency benchmark.

## Deploy

The repository includes a `Dockerfile` and a Render Blueprint (`render.yaml`).

1. Push this repository to GitHub, which is already done for `GuTS805/CONTRA`.
2. In Render, choose **New → Blueprint** and select the repository.
3. When Render asks, enter `OPENAI_API_KEY`, or leave it empty to run without a model.
4. Open the `onrender.com` URL once the deploy is live.

Hosted mode is enabled by `CONTRA_PUBLIC=1`, which the Dockerfile sets. The server then accepts only the hostnames in `CONTRA_ALLOWED_HOSTS`, plus `RENDER_EXTERNAL_HOSTNAME`, which Render sets automatically. Session cookies become `Secure`, and HSTS is sent. On another host, set `CONTRA_ALLOWED_HOSTS=your.domain` and `PORT`.

On Render's free plan, the disk is temporary: accounts and saved reports are lost on each redeploy or restart. To keep them, attach a persistent disk mounted at `/data` (a paid plan). Free instances also sleep when idle, so the first request after a pause takes a while.

Security in hosted mode:

- Passwords are hashed with scrypt.
- Sessions use random tokens; only their hashes are stored, and cookies are HttpOnly and SameSite=Lax.
- Every API route except `/health` requires a session.
- Each user's data is scoped to their account.
- Mutations require JSON and a same-origin `Origin` header.
- Login, sign-up, guest creation, symbol additions and analyses are rate-limited per process.
- There is no email verification or password reset.

## API

All `/v1` routes except the auth routes require the session cookie.

- **Auth:** `POST /v1/auth/signup`, `/v1/auth/login`, `/v1/auth/guest`, `/v1/auth/logout`; `GET /v1/auth/me`.
- **Data:** `GET /v1/stocks`, `/v1/evidence`, `/v1/evidence/{id}`; `POST /v1/securities` (`ticker`, `sector`); `DELETE /v1/securities/{ticker}`; `POST /v1/documents` (`ticker`, `title`, `published_at`, `excerpt`, optional `source_uri` and `tone`); `DELETE /v1/documents/{id}`; `POST /v1/examples/public-filings` (adds the Infosys example; repeating it adds nothing).
- **Profiles:** `GET /v1/profiles`, `/v1/profiles/{id}/portfolio`, `/v1/profiles/{id}/insights`; `PUT /v1/profiles/{id}`.
- **Analyses:** `POST /v1/analyses` (`ticker`, `investor_id`, optional `as_of`); `GET /v1/analyses`, `/v1/analyses/{run_id}`, `/v1/analyses/{run_id}/evidence/{id}`, `/v1/analyses/{run_id}/ask?q=`.
- **Evaluation:** `GET /v1/evaluations/summary`, `/v1/evaluations/benchmark`.

JSON errors have an `error` code and a `message`.

## Verify

```powershell
python -m unittest discover -s tests -v
```

The tests cover:

- Agent concurrency and source integrity.
- Recommendation sizing.
- Filing retrieval and abstention.
- Yahoo response parsing, including forming bars, nulls and provider failures. The tests use recorded payloads and never call the network.
- Accounts, session expiry and per-user isolation.
- A live-symbol analysis served from a seeded price cache.
- The Infosys example: exact-quote verification, as-of filtering and per-account isolation.
- Hosted-mode Host, Origin and cookie rules.

With a server running, `node tests/ui_smoke.js` (or `CONTRA_BASE_URL=... node tests/ui_smoke.js`) starts a guest session and checks that every view renders without a runtime error.

## Commercial relevance

**Who it serves.** Retail investors who already hold a few stocks and want to know whether a new signal fits *their* portfolio. A second audience is the platforms that serve them: brokers, wealth apps and registered advisers.

**How it could make money.**
- **Freemium research tool for investors.** The free tier covers guest use and the demo scenarios. A paid tier adds more live symbols, filing ingestion for a watchlist, and an alert when a holding crosses the investor's own single-name or sector cap.
- **API for fintech platforms and advisers.** A platform sends a symbol and a client profile, and gets back a sized action with cited reasons and a checksummed report. Advisers already have to record why they gave a recommendation. Each saved CONTRA report is that record: the frozen evidence, the profile revision and the rule that fired.

**Why the unit cost stays low.**
- Actions come from deterministic rules, so a run needs no model call.
- The model only writes the short briefings. It is the cheapest suitable one (`gpt-4.1-nano`), its answers are cached by input, and every call is capped per account and per day.
- The demo scenarios currently cost zero paid calls.

**What is not yet validated.** No user research or pricing test has been run. Giving personalized advice to the public in India requires SEBI registration. CONTRA therefore stays a research and record-keeping tool. Any advice would come from the registered party using it.

## Scope and limits

- The live price source is unofficial. Uploaded filing text is not verified against the issuer. The Infosys excerpts are verified against SEC EDGAR by `python -m contra.public_filings`.
- On numeric results releases, model briefings are often rejected because the model copies numbers. The card then shows the rule summary and the reason, which is intended.
- Filing tone uses a word-list heuristic unless you label it. It is crude, and it is shown as such.
- The thresholds are design choices, not calibrated predictors. No future-return accuracy is claimed.
- SQLite and in-memory rate limits suit a single instance.
- `python -m contra.import_data` still validates offline JSON snapshots for future provider work.

## Fourth signal: institutional flows

Analysis now includes FII/FPI and DII net activity in INR crore, with a dated source drawer and explicit divergence when the two groups take opposite sides. Live runs use provisional combined-exchange NSE data; synthetic scenarios stay labeled synthetic. Missing or stale flows abstain. Saved comparisons reuse the original observation. See [methodology, official sources and historical-data limits](docs/institutional-flows.md).
