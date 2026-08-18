# Gold Trend-Pullback Continuation Economic Edge Validation Contract V1

Status: `FROZEN_BEFORE_POST_DECISION_PRICE_PATH_ACCESS`

## Objective and preserved predecessor

Determine whether any of the nine candidates sealed by Gold Trend-Pullback
Continuation Edge Discovery V1 is economically tradable after a constant,
point-in-time-correct execution model and realistic costs.

Preserve every earlier verdict, artifact and seal. Candidate identities,
conditions, thresholds, timeframes and ranking order are immutable. This branch
may reject all nine. A directional continuation relationship is not an
economic edge unless its net trade expectancy passes the gates below.

Development is 2021-08-01 through 2024-12-31. Only development candidates that
pass every economic gate may be applied to calendar 2025 and calendar 2026
through 2026-07-29. Those forward segments are exposed historical robustness
tests and receive no independent-validation credit. No paid acquisition is
authorized.

## Signal identities

Use exactly the nine frozen candidate IDs, in their sealed order. A case becomes
a signal only when its existing, sealed feature row satisfies that candidate.
Do not add fundamentals, sessions, retracement zones, candle labels or any
other filter. Signal time is the pullback `known_at_utc`; forming bars are
prohibited.

The nine candidates are tested independently first. Candidate overlap does not
create different entries, stops or targets for the same pullback.

## Constant execution

### Entry

- Enter at the open of the first available XAUUSD M1 bar whose open timestamp
  is at or after signal time.
- Maximum entry delay is five minutes. A later first bar is `NO_TRADE`.
- The M1 bar must be from IC Markets MT5 and have been available no later than
  its close.
- Entry is calculated from the observed bid OHLC open. Bid/ask friction is
  deducted through the frozen all-in cost model below.

### Structural stop

- ATR is the sealed same-timeframe ATR14 available at signal time.
- Bullish stop: confirmed pullback pivot minus 0.15 ATR14.
- Bearish stop: confirmed pullback pivot plus 0.15 ATR14.
- The stop must lie strictly beyond entry in the adverse direction. Otherwise
  classify `NO_TRADE_STOP_NOT_BEYOND_ENTRY`.
- A gap through the stop fills at the worse of the bar open and stop.

### Known-liquidity target

At entry, reconstruct the set of same-timeframe, same-scale swings whose
`known_at` is no later than signal time and which have not been broken by a
structure event no later than signal time.

- Bullish target: nearest unbroken `UPPER` swing strictly above entry.
- Bearish target: nearest unbroken `LOWER` swing strictly below entry.
- The exact swing price is the target; no future-formed level is eligible.
- If no eligible level exists, classify `NO_TRADE_NO_KNOWN_LIQUIDITY_TARGET`.
- No reward-to-risk filter is permitted. The observed target R must determine
  economic viability rather than selectively excluding unattractive trades.

### Path and exit

- Stop and target are active from the entry M1 bar.
- If both are touched in one M1 bar, assume the stop fills first.
- Target gaps fill at the target, never at a more favourable price.
- Otherwise exit at the last available M1 close before the close of the 16th
  completed parent-timeframe bar strictly following signal time: four hours for
  a continuously traded M15 sequence, 16 hours for H1, and 64 hours for H4.
- Parent bars, rather than assumed wall-clock minutes, establish the deadline,
  preserving normal weekend and maintenance gaps.
- An incomplete entry/holding path is unavailable, not a loss or win.

## Costs

Prices are dollars per ounce. Baseline round-trip friction is:

- observed, nonnegative IC Markets `spread_price` at the entry bar;
- commission: $0.07 per ounce round trip;
- slippage: $0.10 per ounce round trip.

If entry spread is missing or negative, use the frozen conservative fallback of
$0.30 per ounce and label it. Net R equals gross R minus total friction divided
by structural risk distance. Report baseline, 1.5x and 2.0x total-cost results.
Costs may never improve an outcome.

## Risk sizing

- Reference account: $10,000.
- Planned risk: fixed 0.5% of initial balance, or $50, per accepted trade.
- XAUUSD standard lot: 100 ounces; minimum step: 0.01 lot, or one ounce.
- Size is floored so stop loss plus baseline cost cannot exceed $50.
- If one ounce exceeds planned risk, classify
  `NO_TRADE_MINIMUM_LOT_EXCEEDS_RISK`.
- No compounding, leverage assumption or simultaneous gold exposure is used.

## Standalone and portfolio policies

Evaluate each candidate independently without suppressing overlapping cases.
Then construct one non-overlapping XAUUSD portfolio:

1. merge identical pullback signals and retain the earliest frozen candidate
   rank for audit attribution;
2. at identical timestamps prioritize H4, then H1, then M15; within a timeframe
   preserve frozen candidate order;
3. accept no new signal while a portfolio position is open, irrespective of
   direction; and
4. retain every skipped signal with an explicit overlap reason.

The portfolio policy is fixed and cannot select the historically best candidate
after results are seen.

## Development metrics and gates

For every candidate and the portfolio report signals, executed trades,
no-trade reasons, trade dates and weeks, direction, entry delay, target R,
gross/net R, net PnL, win rate, average/median win and loss, expectancy, profit
factor, maximum drawdown, maximum consecutive losses, MFE, MAE, holding time,
exit reasons, monthly return diagnostics, Sharpe/Sortino where meaningful,
annual results, four chronological blocks, side/session stability, profit
concentration and 1.5x/2.0x cost stress.

Uncertainty uses 5,000 deterministic New-York-trading-date cluster bootstrap
resamples. Apply Holm correction across all nine candidate mean-net-R tests.

Candidate support floors are:

- M15: 100 trades on 75 dates and 40 ISO weeks;
- H1: 50 trades on 40 dates and 25 ISO weeks;
- H4: 30 trades on 25 dates and 15 ISO weeks;
- every candidate: at least 15 net winners and 15 net losers.

A candidate is `PASS_DEVELOPMENT_ECONOMIC_CANDIDATE` only when all hold:

- baseline net expectancy is positive;
- the 95% cluster-bootstrap lower bound is strictly positive;
- Holm-adjusted one-sided p is at most 0.05;
- baseline net profit factor is at least 1.20;
- at least three of four chronological blocks have positive expectancy and no
  block with at least ten trades is below -0.15R;
- 1.5x-cost expectancy remains positive and profit factor is at least 1.05;
- maximum account drawdown is no more than 15%; and
- no single trade contributes more than 35% of total positive net R.

Unsupported candidates are `INCONCLUSIVE_SUPPORT`; supported failures are
`REJECT_DEVELOPMENT_ECONOMICS`. Passing candidates are frozen before forward
values are opened. Zero passing candidates is acceptable and leaves forward
values unopened for this branch.

## Forward robustness

Apply every development economic candidate once and unchanged to calendar 2025
and 2026 through 2026-07-29, reconstructing the same structures, features and
trade mechanics from the already sealed IC Markets sources.

Minimum forward support is 20 trades/15 dates in 2025 and 10 trades/8 dates in
2026. With adequate support, `PASS_EXPOSED_FORWARD_ROBUSTNESS` requires:

- positive net expectancy in 2025 and separately in 2026;
- positive combined net expectancy with a strictly positive 90% cluster-
  bootstrap lower bound;
- combined net profit factor at least 1.15; and
- positive combined expectancy at 1.5x costs.

Insufficient segment support is `INCONCLUSIVE_FORWARD_SUPPORT`; any supported
gate failure is `REJECT_EXPOSED_FORWARD_ROBUSTNESS`. Forward results may reject
but never repair or retune a development candidate.

## Prospective ledger and integrity

Initialize an append-only, paper-only decision ledger after final sealing.
Never backfill decisions between the last historical source timestamp and
ledger initialization. Only development candidates not rejected by supported
forward evidence may be marked eligible for prospective observation; none is
authorized for live trading.

Primary and reference implementations must reproduce signal membership, target
selection, complete paths, trades, portfolio decisions, statistics and
checksums exactly. Record every no-trade and negative result. Stop for a source,
lineage or seal failure, or any potential charge.
