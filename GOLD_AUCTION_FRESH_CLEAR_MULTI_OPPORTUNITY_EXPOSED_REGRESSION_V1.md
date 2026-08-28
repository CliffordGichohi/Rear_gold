# Gold Fresh-and-Clear Multi-Opportunity Exposed Regression V1

Status: `FROZEN_IMPLEMENTATION_MAPPING`

## Objective

Apply the already selected `A3_FRESH_AND_CLEAR::E0::R0` policy from the
ten-trade scanner to every eligible New York auction transition in the already
exposed January-June 2022 population.  This implements the previously proposed
day-trading architecture without refitting the selector or limiting the scan
to ten examples.

## Frozen sources and population

- Exactly 117 already exposed New York session-days from 2022-01-03 through
  2022-06-30, with the existing 2022-02-17 through 2022-02-28 gap unchanged.
- Exactly the sealed 729 point-in-time M15/M5 transition events and corrected
  liquidity/range overlays.
- Existing sealed primary/reference daily XAUUSD streams only.
- No additional day, month, 2025, or 2026 source may be accessed.
- No acquisition or charge is permitted.

## Unchanged selector and execution

For every transition, compile the existing auction trade plan.  Require all
original plan gates and then apply exactly:

1. event class is not `CONTINUATION_REFRESH`; and
2. the nearest known unconsumed M15 destination provides at least `1.00R` of
   local room.

Preserve the original direction, one-minute latency, completed-M5 decision,
protected-M5-pivot structural stop, nearest unconsumed H1/H4 target,
noon-New-York deadline, stop-first ambiguity, whole-ounce sizing, spread,
slippage, and fixed $50 maximum risk.  Use no partial exit, break-even move, or
runner (`E0::R0`).

## Multi-opportunity lifecycle

- Scan every eligible event in chronological order; do not stop after the
  first candidate of the day.
- Execute every independently emitted admitted event, including an event that
  forms while one or more earlier positions remain open.
- Every overlapping trade retains its own entry, structural stop, known-
  liquidity target, quantity, costs, and deadline.
- Do not suppress, defer, merge, net, or resize an admitted signal because of
  another open trade.
- Apply identical selector and lifecycle logic to LONG and SHORT.
- Report maximum concurrent positions, maximum concurrent planned risk, and a
  matched non-overlap diagnostic from the same frozen signals so overlap policy
  can be reviewed later.  The all-valid-signals track is primary.

## Integrity and stopping

- Freeze the mapping, source hashes, selector identity, tests, and output schema
  before resolving paths.
- Prove chronological multi-entry, overlapping-trade admission, direction
  symmetry, and no one-per-day cap synthetically.
- Run primary and reference sources independently and require exact event
  dispositions, executions, summaries, and checksums.
- Report all monthly counts and economics; make no new edge claim from this
  exposed regression.
- Do not add a filter, alter a threshold, optimize management, or inspect a new
  period after viewing results.
- Stop after reporting this implementation result.
