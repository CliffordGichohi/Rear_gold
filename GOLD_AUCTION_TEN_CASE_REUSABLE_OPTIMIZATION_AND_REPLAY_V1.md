# Gold Auction Ten-Case Reusable Optimization and Replay V1

Status: `FROZEN_EXPOSED_FIT_AND_IMPLEMENTATION_REPLAY_PROTOCOL`

## Purpose and evidence status

Use exactly the ten already exposed auction-placement examples to fit a small,
reusable auction policy and then rerun those same ten cases end to end.  No
unopened date or additional market source may be accessed until this replay
passes.

The result has zero validation credit.  It answers only two questions:

1. can a compact policy improve the exposed ten-case training population; and
2. can the implementation reproduce that policy directly from the sealed
   point-in-time inputs and price streams?

It cannot establish that another trade will have the same market outcome.
"Reusable" means the same observable rule and execution lifecycle will be
applied without alteration to another trade.

## Frozen population and hard new-data gate

- Exactly the ten event identities in the sealed Gold Auction Trade Placement
  Examples V1 population.
- Reconstruct the plans independently from the sealed primary and reference
  event and liquidity-semantic sources; do not use outcome labels to compile a
  plan.
- Resolve the ten paths again from their already exposed sealed M1 and M5
  streams.
- Do not access another case, day, month, 2025, or 2026.
- Do not acquire data or incur a charge.
- A failed primary/reference reproduction stops the branch before any new-data
  authorization can be considered.

## Anti-overfit restrictions

An admission or management rule must:

- use fields available at the decision or at a later completed-candle
  checkpoint;
- be direction symmetric;
- contain no date, case alias, event identity, exact historical price, realised
  archetype, MFE, MAE, resolution, PnL, or outcome label;
- use a round structural threshold with an auction interpretation;
- affect at least two exposed cases when it changes admission or management;
- retain both LONG and SHORT examples and at least three of the four original
  profitable trades; and
- leave a minimum of four executable trades.

No exception may be created to rescue or reject one named trade.

## Frozen admission registry

All policies retain the original aligned M15/M5 control, protected-pivot,
maximum-one-M5-ATR chase, structural stop, and minimum-1.5R H1/H4 target-room
requirements.

1. `A0_ORIGINAL`: no additional admission condition.
2. `A1_FRESH_TRANSFER_OR_CONTROL`: reject `CONTINUATION_REFRESH`; require an
   initial transfer, reversal transfer, or control reassertion rather than a
   same-direction refresh.
3. `A2_CLEAR_LOCAL_PATH`: require the nearest known unconsumed M15 destination
   to be at least `1.00` displayed structural R from entry.
4. `A3_FRESH_AND_CLEAR`: apply both A1 and A2.

The `1.00R` threshold is a round risk-unit boundary and is not fitted between
two adjacent case values.

## Frozen management grid

Every admitted trade keeps its original fill latency, structural stop,
absolute H1/H4 liquidity target, noon-New-York deadline, costs, and whole-ounce
$50 risk sizing.

The bounded grid is the Cartesian product of:

- early realization fractions `0`, `0.25`, `1/3`, and `0.50`; and
- target-runner fractions `0`, `0.25`, and `1/3`.

Early realization occurs only after the first completed M5 close at or beyond
`+1.00` effective fill-to-stop R.  The fraction is closed at the first
subsequent M1 open with adverse spread and slippage.  The remaining quantity
retains the original stop, target, and deadline; no break-even move is allowed.

For a target runner, the non-runner quantity exits at the original target.  The
runner begins only after that target-touch M1 bar completes, uses the original
target as a non-worsening floor, and exits on the first return to that floor or
at the unchanged deadline.  Adverse spread and slippage apply to a runner stop
or time exit.  No future liquidity level is introduced.

Fractions use deterministic whole-ounce floor allocation and must leave at
least one ounce in every remaining tranche.  If that is impossible, the
component is unavailable for that trade.

## Frozen candidate eligibility and ranking

Evaluate all 48 admission-management combinations on all ten cases.  A
candidate is selection-eligible only when:

- all anti-overfit restrictions pass;
- every nonzero management component activates on at least two trades;
- its net R is positive;
- its leave-one-executed-trade-out net R is positive for every admitted trade;
  and
- the neighboring registered fractions for each selected nonzero management
  component also produce positive net R under the same admission policy.

Rank eligible candidates in this fixed order:

1. highest total net R;
2. highest profit factor;
3. lowest maximum drawdown;
4. fewer nonzero management components;
5. more admitted trades; and
6. lexical candidate identity.

This is exposed fitting.  The selected candidate must not be described as an
edge or validated policy.

## Replay and reproduction gates

- Prove admission symmetry, no forbidden selector fields, completed-M5
  activation, whole-ounce allocation, target-runner timing, and long/short
  execution symmetry on synthetic cases.
- Reconstruct all ten plans and require exact equality to the sealed plan
  population.
- Run complete primary and reference passes separately from their raw sealed
  streams.
- Require exact equality of plan identities, admission decisions, management
  actions, executions, candidate matrix, selected policy, summaries, and
  checksums.
- Report every admitted and rejected trade, including valid winners rejected.
- Stop after the same-ten replay.  Opening later data requires a separate user
  instruction.
