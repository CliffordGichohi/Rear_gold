# Gold Matched Human–Codex Replay Comparison Contract V1

## Purpose

Determine whether the Codex operator misunderstood or departed from the user's auction method by having the user replay the exact same early-stop population independently and comparing decisions case by case afterward.

## Frozen population

- Exactly `CBR-2022-001` through `CBR-2022-030`.
- Calendar dates: 2022-01-03 through 2022-02-16, in the existing frozen order.
- Identical certified point-in-time private streams, session windows, chart timeframes, macro context, structure, levels and event visibility used by the Codex audit.
- Case 031 and all later cases are outside this comparison.

## Isolation

- Human decisions use a new append-only visible ledger and a new sealed outcome ledger.
- The completed Codex ledgers, decisions, outcomes, reports and evidence remain unchanged.
- The interface must not expose Codex decisions or per-case outcomes during human collection.
- Because the aggregate Codex result and repository outcome artifacts now exist, this exercise is diagnostic calibration—not independent blind validation and not evidence of an edge.

## Matched rules

- Same one-way cursor and completed-candle visibility.
- Same required W1, D1, H4, H1 and M15 inspection.
- Same permitted entry sessions: London, London–New York overlap and New York.
- Same LONG, SHORT and terminal NO_TRADE choices.
- Same market-next-M1 fill, one-minute latency, whole-ounce sizing, maximum $50 planned risk, spread, slippage, stop-first ambiguity, one trade per case and end-of-day time exit.
- Same structured decision fields: macro role, higher-timeframe state/location, M15 transition, session/liquidity context, invalidation and target.

## Comparison after completion

After all 30 human cases are sealed, compare matched cases on:

- trade versus no-trade;
- direction and decision session;
- macro interpretation;
- higher-timeframe state and location;
- M15 trigger;
- entry, stop, target and realised outcome;
- net R, expectancy, profit factor and drawdown;
- exact disagreements and which operator interpretation better matched the user's stated method.

No threshold, decision or execution rule may be altered after collection begins.

