# Gold Auction All-Transition Executable Multi-Opportunity Exposed Regression V2

Status: `AUTHORIZED_CORRECTIVE_IMPLEMENTATION`

## Purpose

Correct the V1 mapping error while preserving its sealed 35-trade result as an
explicit wrong-mapping diagnostic.  V2 applies the existing auction-transition
scanner to every already exposed New York M15/M5 transition without importing
the ten-example sampler or its fitted Fresh-and-Clear selector.

## Frozen population

- Use exactly the existing 729 sealed transition identities across the 117
  already exposed New York session-days from 2022-01-03 through 2022-06-30.
- Preserve the unopened 2022-02-17 through 2022-02-28 gap.
- Open no additional date, 2025 value, or 2026 value.
- Acquire no data and incur no charge.

## Exact admission rule

Compile the existing point-in-time plan for every transition.  A setup is
mechanically executable unless at least one of these hard conditions applies:

1. M15 control is not aligned with the transition direction.
2. M5 control is not aligned with the transition direction.
3. The M5 protected structural pivot is unresolved.
4. The M5 protected structural pivot is already consumed.
5. Structural risk is nonpositive.
6. No known unconsumed H1/H4 directional liquidity destination exists.
7. The known-liquidity target is not beyond the entry in the trade direction.

Ignore only these former quality-filter dispositions; they may be recorded but
must not block an otherwise executable setup:

- `DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR`
- `TARGET_ROOM_BELOW_1P5R`

Explicitly prohibited admission filters:

- The `A3_FRESH_AND_CLEAR` selector or any other fitted selector.
- Rejection of `CONTINUATION_REFRESH` as an event class.
- A local-M15-liquidity minimum-room rule.
- A minimum reward-to-risk threshold.
- A distance-from-break threshold.
- A one-candidate-per-day or one-candidate-per-session cap.
- A requirement that an earlier position resolve before a later setup enters.

The pre-outcome freeze must contain exactly 729 transitions and exactly 660
mechanically executable setups.  Any difference is a mandatory stop.

## Execution

- Scan all transitions chronologically.
- Execute every mechanically executable setup independently, including while
  one or more earlier positions remain open.
- Preserve each setup's original direction, completed-M5 decision, one-minute
  latency, protected-M5-pivot structural stop, nearest known unconsumed H1/H4
  liquidity target, noon-New-York deadline, stop-first ambiguity treatment,
  whole-ounce sizing, spread, slippage, and maximum $50 planned risk.
- Do not suppress, defer, merge, net, resize, or otherwise alter an executable
  setup because of another position.
- Report concurrency and a matched non-overlap diagnostic from the identical
  signals.  The unrestricted all-executable-signals track is primary.

## Integrity

- Prove hard-versus-soft reason classification, all-event retention, overlap
  execution, direction symmetry, and no daily cap synthetically.
- Freeze all identities, dispositions, source hashes, governing code, and
  output schemas before resolving any path.
- Run independent primary and reference passes and require exact results and
  checksums.
- Report every trade, monthly result, direction result, concurrency, and the
  non-overlap diagnostic.
- This exposed regression receives zero validation credit and may not be used
  to claim a validated edge.
