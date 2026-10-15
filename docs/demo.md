# Five-minute local demo

Start the server with `python -m contra.server`, open `http://localhost:8000` and click **Continue as guest**. The script below uses the synthetic scenarios, whose outcomes are known. To finish with real data, click **Load Infosys** on the terminal and run INFY.NS. Open a cited excerpt and follow its SEC EDGAR link, then ask "Do they have any debt?" to get the Form 20-F liquidity passage.

| Time | Action | What it proves |
| --- | --- | --- |
| 0:00–0:35 | Read the four **How it works** steps, then click **Run the 60-second demo**. It runs ALPHA.NS for the Conservative investor and opens the report with a short guide. | What the system does, before any detail; honest provenance and a frozen fixture date. |
| 0:35–1:20 | Run analysis. Read the **Personalized portfolio action**: reduce by about 5,000, from 15% to 10%. Open a cited reason. | An explainable, sized action with the rule that fired, cited reasons and what would change it. |
| 1:20–1:40 | Open the agent trace and timing. | Three independently executed pipelines with overlapping intervals; each labels model reasoning or deterministic fallback. |
| 1:40–2:20 | Read **What each agent found**. Then, in **Ask the filings**, click "Is profitability getting squeezed?" and type "weather forecast". | Verified model briefings with citations. Semantic search finds a paraphrase that shares no words with the excerpt, and returns nothing when no source supports an answer. |
| 2:20–2:50 | Expand **Show calculation and sources** and open the negative filing excerpt. | Dated numeric references, exact words, date and hash. |
| 2:50–3:35 | Click **Compare all 3 investors**, then **Compare Growth**. | Same market hash and signals for three saved profiles; the actions differ: reduce exposure, hold and review, do not open a position. |
| 3:35–4:10 | Run DELTA.NS. | No eligible filing by the as-of date; research abstains and the report is partial. |
| 4:10–4:35 | Open Portfolio. Show the personalized insights table. | Every holding is checked against this investor's limits, with the trim or room to add. |
| 4:35–5:00 | Open Evaluation. Show the scenario matrix, which checks both state and action, Recall@3 and the 10-run benchmark. | Reproducibility, metrics and persistence. |

The profile editor can change single-name and sector caps. These changes create a new profile revision; existing reports retain the profile snapshot used when they ran.

Demo boundaries: in the scripted scenarios, all quantities and filings are simulated. Actions come from a fixed, published policy over cited evidence and the saved profile limits. They are research suggestions, not financial advice or trade execution. No future-return accuracy is claimed.
