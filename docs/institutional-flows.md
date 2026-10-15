# Institutional flows: fourth signal dimension

## Research and scope

The [NSE report](https://www.nseindia.com/reports/fii-dii) separates NSE-only activity from combined NSE, BSE and MSEI capital-market activity. CONTRA uses the combined daily FII/FPI and DII rows from `https://www.nseindia.com/api/fiidiiTradeReact`. The live endpoint schema was checked during implementation on 15 October 2026.

The [MSE exchange methodology](https://beta.mseindia.com/markets/markets-information/fii-dii-trading-activities) explains that institutional categories are derived from member client classifications and that the figures are provisional, subject to custodial confirmation and modifications. It directs readers to NSDL/CDSL for final FPI data. These series have different coverage and are not silently substituted for one another.

## Interpretation

- Units are INR crore. One crore is ten million rupees.
- Each category's net equals gross purchases minus gross sales. Parsing permits at most 0.02 crore rounding difference.
- Opposite nonzero FII/FPI and DII signs produce `DIVERGENT`, even if their combined net is positive.
- Otherwise, the sum determines `NET_BUYING`, `NET_SELLING`, or `BALANCED`. These are descriptive labels, without calibrated predictive strength or invented thresholds.
- This is aggregate capital-market activity, not a stock's institutional ownership, holdings change, derivatives positioning, or an instruction to trade.
- Three agents remain. The Market agent receives two additional cited facts; synthesis adds institutional context. Flows do not override stock direction, portfolio caps or the sizing policy. `signal_completeness` covers all four dimensions; existing `evidence_completeness` still describes agent availability.

## Availability and time semantics

Live analyses fetch the public NSE endpoint with an eight-second timeout and retain successful observations in SQLite. The refresh interval is one hour, with a five-minute process-local retry cooldown after attempts. There is no promise of endpoint availability or exchange publication time. Provider outages use eligible cached observations and show a warning for the failed refresh.

Both categories must be present on the same trade date. Invalid numeric values, negative gross amounts, arithmetic errors and future-dated provider rows are rejected. Observations after the requested trade date are excluded. Missing observations remain unavailable, never zero. More than four calendar days of age makes the signal unavailable. This is a conservative product policy and can abstain during long exchange holidays.

The endpoint supplies the latest report, not a full historical archive. Earlier dates are available only if locally collected. `as_of` filters trade dates; the observation timestamp may be later than that date. Historical views are therefore **reconstructed observations, not point-in-time backtests**. Do not use this data for leakage-free historical performance claims. No rolling-flow trend is claimed from a single observation.

Synthetic stocks receive an explicitly labeled synthetic flow fixture on the fixture date. It is the same market context across all four stocks. Real provider data is never mixed into a synthetic snapshot.

## Evidence and replay

Each observation stores original provider rows, normalized gross/net values, trade date, observation time, units, scope, provisional status and source URL. A SHA-256 checksum covers this record. Flow inputs are also included in the market snapshot checksum and full report checksum. The evidence drawer opens the exact saved observation, including gross purchases and sales.

Profile comparisons send `source_run_id` and reuse that account's original bars, filings and flow observation without refetching. Old saved reports still replay; the UI labels their absent fourth dimension as not recorded. To collect a new flow observation, start a fresh live analysis.
