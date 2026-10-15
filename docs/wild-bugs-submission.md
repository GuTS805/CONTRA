# Wild Bugs: PS 04 VibeFinance

## Official context

Target: [Wild Bugs](https://wild-bugs.devfolio.co/overview), PS 04, VibeFinance: Multi-Agent Autonomous Financial Intelligence for Retail Investors. The overview links the [official problem statements and rubric](https://docs.google.com/document/d/1NZ5cmudvTcJNYeYYQToHDjrHK6IcQeLsJMojvfj5IHc/edit). Reviewed 15 October 2026. The public [schedule](https://wild-bugs.devfolio.co/schedule) lists the end as 15 October at 23:59 in Calcutta time. Dashboard-only submission fields, video limits and any subsequent organizer announcements still need to be checked in the participant dashboard.

## Submission summary

**CONTRA: intelligence through disagreement.**

A positive price signal is not enough to decide what fits an investor's portfolio. CONTRA exposes disagreements between market evidence and company filings, then applies that investor's saved exposure limits to produce an explainable, sized research action.

Three specialized agents run concurrently on a frozen snapshot. Market measures momentum and volume with institutional-flow context. Research retrieves dated filing passages and grounds its output in exact excerpts. Risk checks the investor's holdings against single-name and sector caps. A deterministic synthesis policy handles disagreements and missing evidence. Optional model briefings are accepted only after source and language checks; failures fall back visibly.

The strongest demonstration uses identical ALPHA.NS evidence for three saved profiles: reduce exposure for Conservative, hold and review for Growth, and do not open a position for Starter. Every result preserves its source inputs and investor revision. A source drawer opens the exact evidence behind the conclusion.

The dashboard supports real daily NSE/BSE symbol prices, a real Infosys filing example, uploaded excerpts, provisional FII/DII flows, four explicitly synthetic scenarios, portfolio editing, saved report replay, and extractive filing questions. Evaluation shows measured latency, agent overlap, citation validity, concentration, retrieval checks, and reproducible degraded-input checks.

Primary users are retail investors reviewing existing holdings. A possible business model is a research subscription or a research API for financial platforms. Pricing and user demand have not yet been validated. The prototype does not place trades or claim predictive return accuracy.

## Rubric-to-proof map

| Official criterion | Weight | What to show | Remaining limitation |
| --- | ---: | --- | --- |
| Signal classification and analytical quality | 20 | Four signal cards, formula details, dated citations, confidence components | Rule thresholds and evidence confidence are heuristic; no return calibration |
| Multi-agent architecture and synthesis | 20 | Three structured outputs, overlapping execution trace, ALPHA conflict, DELTA partial result | Rule-backed agents with optional model interpretation; no claim of autonomous trading |
| Retrieval and source attribution | 15 | Open a cited passage; ask a supported question and an unsupported question; evaluation Recall@3 | Small corpus; hybrid retrieval evaluation uses synthetic passages |
| Personalization and risk awareness | 15 | Compare all three investors on one frozen snapshot; inspect saved limits | Manually entered valuations, not brokerage synchronization |
| Engineering and reliability | 10 | Replay report; run seven degraded-data checks; tests and CI | Free hosting disk is temporary; live provider availability is external |
| Performance and evaluation | 10 | Saved-run metrics and ten-run p50/p95 benchmark | In-process benchmark excludes HTTP and market-provider latency |
| Explainability and commercial relevance | 10 | Action, sizing, evidence, what-would-change conditions, target user | No user study or demonstrated willingness to pay |

## Three-minute proof sequence

1. State the problem in one sentence: the same stock evidence can mean different actions for different investors.
2. Run ALPHA.NS for Conservative. Identify positive momentum versus negative filings and the breached position cap.
3. Open a cited reason. Show the exact excerpt, date and source identity.
4. Show concurrent agent intervals and the four signal dimensions. Explicitly identify the scenario as synthetic.
5. Compare Growth. Show equal frozen market inputs and the changed personal action.
6. Ask about operating margin; then ask about the weather. Show an exact passage followed by abstention.
7. Open Evaluation. Show scenario checks, retrieval metrics and degraded-data checks. Close with the public demo and repository.

For a longer live Q&A, load Infosys, inspect its SEC source links, and distinguish live data availability from the reproducible synthetic demo.

## Submission assets and honest claims

- App: https://contra-h0nw.onrender.com
- Source: https://github.com/GuTS805/CONTRA
- Architecture: [architecture.md](architecture.md)
- Test coverage and verification status: [acceptance.md](acceptance.md)
- Flow methodology: [institutional-flows.md](institutional-flows.md)
- Video generator: `python scripts/make_demo_video.py`; output is local under `data/demo/` and is not uploaded automatically.
- Use the final tested commit SHA in the submission. Describe any pre-existing work if the organizers ask. Do not rewrite history or imply every line was authored during the event without checking the applicable rules.
- Synthetic scenarios prove implementation behavior, not alpha, investment performance or real-world accuracy. Confidence means evidence support, not probability of profit.
- A paid model key is optional. Demo recording deliberately disables model calls and labels fallback mode. Do not describe that recording as live model inference.
