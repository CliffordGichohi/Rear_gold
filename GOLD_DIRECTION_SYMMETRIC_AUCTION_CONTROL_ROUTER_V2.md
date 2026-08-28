# Gold Direction-Symmetric Auction-Control Router V2

Status: frozen design before the exposed January–June 2022 regression.

## Correction being tested

V1 incorrectly constructed a separate reversal-only SHORT plan requiring a failed buyer auction, a six-bar retest, and 1.5R to the nearest liquidity. Preserve that zero-trade result as a rejected over-constrained implementation.

V2 does not create a new SHORT setup. It combines two already implemented components:

1. the sealed direction-symmetric translator, which applies the same frozen semantic model, family model, geometry model, costs, routing, and management to LONG and mirrored SHORT observations; and
2. the sealed mutually exclusive M5/M15 auction-control state from V1.

## Exact routing rule

- Operate only during the existing New York scan.
- Preserve the direction-symmetric translator's first candidate, timestamp, probability, direction, family, entry, stop, target, costs, result, and every existing rejection unchanged.
- Admit an otherwise executable LONG only when the accepted control state at its original signal timestamp is `BUYER_CONTROL`.
- Admit an otherwise executable SHORT only when the accepted control state at its original signal timestamp is `SELLER_CONTROL`.
- `CONFLICTED` and `UNRESOLVED` admit neither direction.
- Do not require a prior opposite-side failure, sweep, additional retest, or new target-room calculation.
- The translator's existing `CONTINUATION_WITH_ROOM`, `RANGE_ROTATION`, and `STRUCTURAL_REPAIR` families remain distinct and unchanged.

The control gate may veto a candidate; it may not move, repair, reconstruct, or create one.

## Tracks

1. `FROZEN_LONG_CONTROL`: existing frozen LONG benchmark.
2. `BUYER_CONTROL_VETO_LONG`: sealed V1 LONG-veto result.
3. `DIRECTION_SYMMETRIC_UNGATED`: sealed symmetric translator result before the new gate.
4. `CONTROL_ROUTED_SYMMETRIC`: the symmetric result after its direction-appropriate gate.
5. `HELD_LONG_PLUS_ROUTED_SHORT`: the earliest of the held buyer-control LONG and a gated symmetric SHORT, maximum one trade per day.

## Population and evidence status

Use every already-opened eligible day from 2022-01-03 through 2022-02-16 and 2022-03-01 through 2022-06-30. Preserve the 2022-02-17 through 2022-02-28 gap as unopened. Do not open July 2022, 2025, or 2026.

All January–June outcomes are exposed and receive zero validation credit. This regression tests semantic translation and historical behaviour only.

## Integrity

Preserve every V1 artifact and seal. Reuse the sealed January–May direction-symmetric rows and reproduce June with the same frozen translator. Run independent primary and reference passes. Require identical candidate identities, control states, gate decisions, results, metrics, and checksums.

No threshold, feature, family, entry, stop, target, management rule, session, or cost may change after results are viewed. Acquire no data and incur no charge.
