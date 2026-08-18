# Gold Multi-Timeframe Trend and Continuation Census Contract V1

Status: `SEALED_BEFORE_CENSUS_MATERIALIZATION`

## Objective

Create a comprehensive descriptive census of gold structure on M15, H1 and H4
from 2021-08-01 through 2024-12-31. This milestone does not search for an edge,
rank a signal, optimize execution, or calculate PnL.

The census must record trends, swings, structure switches, continuation breaks,
pullbacks that continued, pullbacks that failed, and pullbacks unresolved at the
development boundary. Fundamentals, sessions, liquidity, candle shapes, costs
and order flow are not eligibility filters. They may be joined later using the
point-in-time timestamps created here.

All prior results and rejections remain unchanged. Calendar 2025 and 2026 stay
locked for later frozen testing.

## Bars and timeframes

- Source: sealed IC Markets MT5 XAUUSD M1 history and its deterministic closed
  15-minute, 1-hour and 4-hour aggregates in the immutable casebook.
- Timeframes: `M15`, `H1`, `H4`.
- A bar is usable only after its close. Forming candles are prohibited.
- Closed intervals containing normal no-tick minutes remain observable; retain
  their component-completeness classification as data quality.
- Enumerate three structural scales independently: micro 1-left/1-right,
  standard 2-left/2-right, and major 3-left/3-right.

## Confirmed swings

For span `s`, a swing high must be strictly higher than every high in the `s`
bars on both sides. A swing low is mirrored. The swing becomes known only at the
close of the `s`th right-hand bar. Equal extrema do not form a swing.

Record every swing with timeframe, scale, pivot timestamp, known timestamp,
price, side, evidence, and quality. A swing cannot be broken by the same bar
that first makes it known; the level must have been known strictly before the
breaking close.

## Structural state and events

Each timeframe/scale begins `NEUTRAL`.

- First close above one or more known unbroken swing highs creates a
  `BULLISH_STRUCTURE_SWITCH`; first close below known unbroken swing lows creates
  a bearish switch.
- When already bullish, a later close above a known unbroken swing high is a
  `BULLISH_CONTINUATION_BREAK`. Bearish is mirrored.
- A bar breaking multiple same-direction swing levels creates one event listing
  every broken swing, preventing duplicate counting.
- When an opposite-direction break occurs, the previous trend segment ends and
  a new segment begins.
- Repeated closes beyond an already broken swing create no new event.

Record every structure event, including transitions without a confirmed
pullback and continuations with one or more confirmed pullbacks.

## Pullback cases and resolutions

After a directional structure event, every newly confirmed opposite-side pivot
whose pivot timestamp follows the most recent directional break is a pullback
case:

- bullish trend -> confirmed swing low;
- bearish trend -> confirmed swing high.

Record every such case, including overlapping structural scales. Its decision
timestamp is the pivot-known timestamp, never the visual pivot timestamp.

Resolution is descriptive and stored separately from decision-time facts:

- `CONTINUED`: the next same-direction structure break occurs first;
- `FAILED_STRUCTURE_SWITCH`: an opposite-direction structure switch occurs
  first;
- `RESOLVED_BEFORE_CONFIRMATION`: price had already broken the continuation
  reference before the pivot became knowable;
- `UNRESOLVED_AT_BOUNDARY`: neither occurred before 2025-01-01.

This complete denominator prevents survivor bias. No resolution field may later
be used as an input feature before its `resolved_at` timestamp.

## Trend segments

Record every neutral-to-directional or opposite-direction structure segment
with start/end timestamps, direction, timeframe, scale, initiating event,
terminating event, bar count, swing count, continuation-event count and
pullback-case count. Open segments at the boundary are marked unresolved.

## Canonicalization and exclusions

- Timeframe and structural scale remain separate populations.
- Do not merge visually similar events across timeframes or scales.
- Canonical identity is based only on timeframe, scale, direction, known level
  identities and breaking close timestamp.
- The six previously engineering-only dates remain in the descriptive census
  with `research_eligible=false`; they receive no later discovery credit.
- Record missing or malformed source intervals honestly. Do not interpolate.

## Required outputs and integrity

- immutable bar-coverage audit;
- complete confirmed-swing registry;
- complete structure-event registry;
- complete pullback-case registry;
- complete trend-segment registry;
- counts by timeframe, scale, direction, year and resolution;
- primary/reference exact reproduction and checksums;
- census report and final seal.

Do not join fundamentals or forward returns, calculate hit rates, create
candidates, inspect 2025/2026, optimize entries/exits, or calculate trades, R,
PnL or account returns. Stop after the descriptive census is sealed.
