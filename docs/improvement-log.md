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

### Current highest-impact gaps

1. **P1 for real-world use — data and provenance:** `contra/fixtures.py`, `contra/core.py`, `contra/import_data.py`. Imported snapshots are validated and staged, but analysis still uses synthetic fixtures. Licensed feeds, issuer filing verification and a trustworthy interpretation method are not implemented.
2. **P1 for public use — identity and deployment:** `contra/server.py`, `contra/store.py`. The server is intentionally local and unauthenticated. Hosted access requires an identity model, access controls and durable storage.
3. **P2 — broader client verification:** `web/app.js`, `web/style.css`. The current smoke harness covers main page rendering and two navigation races. A full browser journey across the report, portfolio edit and error states would give stronger confidence.
