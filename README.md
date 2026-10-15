# CONTRA

CONTRA is an evidence-first investment research assistant. Three agents run concurrently on one frozen snapshot: Market (price momentum and volume), Research (retrieval over dated filing excerpts) and Risk (the investor's own limits). CONTRA then gives a personalized, sized portfolio action with cited reasons and the conditions that would change it.

It works on two kinds of data, and each report labels which one it used:

- **Live:** any NSE (`.NS`) or BSE (`.BO`) symbol you add. Prices are real daily closes from Yahoo Finance's public chart endpoint. Filings are excerpts you paste, stored with their publication date and hash.
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
CONTRA_MODEL=gpt-6-astra
```

The server loads `.env` at startup. Variables already set in the shell take precedence. The startup log states whether model reasoning is enabled. Each analysis makes up to three model calls, one per agent. The model may only pick a permitted focus and cite source IDs that the agent already holds; numbers, statuses and the action stay code-computed. An invalid or failed response falls back to deterministic reasoning, and the report labels each agent's mode. To protect a small credit balance, an identical agent input reuses the earlier validated answer instead of paying again, and `CONTRA_LLM_DAILY_LIMIT` (default 150, 60 in `.env` and on Render) caps paid calls per UTC day. After the cap, agents fall back with a visible warning; `/health` reports today's usage. The key is never sent to the browser or stored in a report. The model adapter has mocked tests only; a live call has not been verified from this workspace.

Implementation notes: [architecture](docs/architecture.md) · [five-minute demo](docs/demo.md) · [acceptance status](docs/acceptance.md) · [improvement log](docs/improvement-log.md).

## Using live data

1. On the terminal, add a symbol such as `RELIANCE.NS` and pick its sector. CONTRA fetches about six months of daily bars. A bar for the current day is skipped until the session closes.
2. In **Evidence library**, paste a filing excerpt for that symbol with its publication date and an optional HTTPS source link. Tone comes from a small finance word list unless you label it Positive, Neutral or Negative.
3. On **Portfolio**, enter your holding values. Every symbol you add appears there.
4. Run the analysis. The report freezes the bars and filings visible at the as-of date, hashes them, and saves the result to your account.

Prices are cached for six hours. If Yahoo Finance cannot be reached, CONTRA uses the cached prices and shows a warning in the report. With no cache, the request fails with a clear error. The Yahoo endpoint is unofficial: it can change, rate-limit or block hosting IP ranges, and it carries no redistribution licence. Closes are not adjusted for splits or dividends.

## Demo with the synthetic scenarios

1. Select **ALPHA.NS** and **Conservative**, then run the analysis. Price momentum is positive while cited filings are negative, and the 15% position exceeds the 10% cap. The action is **Reduce exposure** by about 5,000 (15% → 10%).
2. Click **Compare Growth**. The market hash and signals are identical, but the 30% cap changes the action to **Hold · review**.
3. In **Ask the filings**, ask "Any new contracts or orders?". The answer is the exact cited excerpt. A question that no filing supports returns no passage instead of a guess.
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
- **Data:** `GET /v1/stocks`, `/v1/evidence`, `/v1/evidence/{id}`; `POST /v1/securities` (`ticker`, `sector`); `DELETE /v1/securities/{ticker}`; `POST /v1/documents` (`ticker`, `title`, `published_at`, `excerpt`, optional `source_uri` and `tone`); `DELETE /v1/documents/{id}`.
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
- Hosted-mode Host, Origin and cookie rules.

With a server running, `node tests/ui_smoke.js` (or `CONTRA_BASE_URL=... node tests/ui_smoke.js`) starts a guest session and checks that every view renders without a runtime error.

## Scope and limits

- The live price source is unofficial. Filing text is user-supplied and not verified against the issuer.
- Filing tone uses a word-list heuristic unless you label it. It is crude, and it is shown as such.
- The thresholds are design choices, not calibrated predictors. No future-return accuracy is claimed.
- SQLite and in-memory rate limits suit a single instance.
- `python -m contra.import_data` still validates offline JSON snapshots for future provider work.
