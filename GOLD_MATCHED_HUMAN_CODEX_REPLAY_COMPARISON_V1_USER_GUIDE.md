# Gold Matched Human-Codex Replay Comparison V1 - User Guide

## Purpose

This replay gives the human operator the exact same 30 calendar-2022 cases that
the Codex blind audit used. It is a matched diagnostic: after the human ledger
is complete, the two ledgers can be compared case by case to determine whether
the negative Codex result came from the market sample, a misunderstanding of the
six-step auction method, different trade selection, or different execution.

It is not fresh validation and it must not be used to retune decisions while the
30 cases are being labelled.

## Frozen sample

- Case IDs: `CBR-2022-001` through `CBR-2022-030`.
- Calendar dates: 2022-01-03 through 2022-02-16.
- Tradable windows: London, London-New York overlap and New York.
- Visible timeframes: W1, D1, H4, H1 and M15.
- Maximum planned risk: $50 per case, with at most one trade per case.
- Codex decisions and all case outcomes remain hidden until collection is
  complete.

## Start the application

From the repository root:

```powershell
docker compose up -d --build
```

Open <http://localhost:3000/replay/matched>. The page should identify itself as
`Matched Human Replay`, show case 1 of 30, and report that the human matched
ledger has zero completed cases on a fresh run.

## Label each case

1. Inspect W1, D1, H4, H1 and M15 before making the final decision.
2. Move the one-way replay cursor only through visible candles. Do not use any
   external chart for the same date.
3. Apply the stated method using only information visible at the cursor:
   fundamentals for context, higher-timeframe location, M15 auction transition,
   active-session confirmation, structural invalidation and the next opposing
   liquidity target.
4. Choose `LONG`, `SHORT` or `NO_TRADE`. For a trade, set entry, stop and target
   before submission and complete the written reasoning fields.
5. Submit once. The decision is appended to the separate human ledger and cannot
   be edited. The application silently resolves the case without showing the
   result and advances to the next case.
6. Repeat until the status reports 30 of 30 complete.

`NO_TRADE` is a terminal decision for the case; it is not an instruction to wait
for hindsight confirmation.

## What is recorded

Each sealed human decision includes the case and cursor identity, inspected
timeframes, visible-state hash, direction, decision session, entry geometry,
macro interpretation, higher-timeframe state/location, M15 trigger, session and
liquidity context, invalidation, target and free-form reasoning. Human and Codex
ledgers remain physically separate.

The private price streams, human ledgers, screenshots and outcome vault stay in
`research_artifacts/` and are intentionally excluded from Git. Compact hashes,
contracts and audit manifests are versioned in the repository; do not move
private replay payloads into source control.

## After case 30

Stop labelling and do not revise the method. The comparison pass should then
open both sealed ledgers once and report:

- trade/no-trade and direction agreement;
- session, location, transition and target differences;
- matched net R, expectancy, profit factor and drawdown;
- cases where one operator was directionally correct but execution failed;
- cases where targets were too close or invalidations were too tight; and
- concrete rubric corrections supported by the matched evidence.

Read the frozen
[contract](GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_CONTRACT_V1.md) and
[readiness certificate](GOLD_MATCHED_HUMAN_CODEX_REPLAY_COMPARISON_V1_READINESS.md)
before beginning.
