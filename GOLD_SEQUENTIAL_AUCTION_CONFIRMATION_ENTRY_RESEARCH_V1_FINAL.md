# Gold Sequential Auction-Confirmation Entry Research V1 — Final

Status: **REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE**

## Verdict

The sequential auction-confirmation idea did not produce a tradable development candidate under the preregistered rules. The result does **not** say that gold is random. It says that these exact completed-candle sequences, source-model assignments, unchanged targets/deadlines, two stop tracks, costs and robustness gates did not monetize the frozen pullback population.

- Frozen development setups: 22,193.
- A primary confirmation sequence formed in 4,628 setups (20.85%).
- Entry-eligible after Track-A gates: 3,446.
- Entry-eligible after Track-B gates: 4,345.
- Formal candidates tested: 36.
- Supported but economically rejected: 10.
- Support failures: 26.
- Positive-expectancy results: 5, all too small/unstable to satisfy support and robustness gates.
- Passing candidates: 0.

## Closest supported result

`M15::RUNAWAY_BREAKOUT::TRACK_A_ORIGINAL_STOP` was the least-negative supported candidate:

- OOF trades: 903 across 500 dates and 132 weeks.
- Win rate: 0.461794019934.
- Net expectancy: -0.059430614682 R/trade.
- Profit factor: 0.890248976995.
- Clustered 95% interval: [-0.13475968046, 0.01908447285].
- 1.5x-cost expectancy: -0.117523974786 R/trade.
- Normalized $50-risk PnL: $-2683.292252902412.
- Whole-ounce PnL: $-2212.771607350001.

It failed positive expectancy, PF, confidence, multiplicity, stressed-cost, fold-stability and neighbour-sensitivity gates.

## What the test learned

Waiting for a visible sequence reduced the population materially, but the surviving entries still did not have positive net expectancy. Track B's post-confirmation retest stop was generally worse: among supported Track-B tests, stop rates were roughly 82%–85%, compared with about 44%–62% for supported Track-A tests. The confirmation did not solve the selection problem, and tightening the stop after confirmation amplified it.

Every one of the 36 candidates failed the frozen lenient/strict neighbour requirement. No threshold was repaired, inverted or retuned after outcomes.

## Locked actions

- The GC MBO/MBP-10 incremental study was not run because the contract forbids order flow from rescuing a rejected base candidate.
- Calendar 2025 and 2026 remained locked and received no access.
- No forward robustness test was run.
- No prospective paper ledger was initialized because there is no frozen passing system.
- No data was acquired and no charge was incurred.

Complete candidate metrics, skipped reasons, MFE/MAE, stop/target diagnostics, folds, years, sessions, cost stresses and sensitivity bundles are sealed in `research_artifacts/gold_sequential_auction_confirmation_entry_v1_development/development_results.json` and the independently reproduced economic-row Parquet files.
