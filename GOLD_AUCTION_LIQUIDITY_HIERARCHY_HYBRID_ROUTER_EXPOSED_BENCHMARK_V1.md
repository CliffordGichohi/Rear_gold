# Gold Auction Liquidity-Hierarchy Hybrid Router Exposed Benchmark V1

Status: `AUTHORIZED_SINGLE_POLICY_EXPOSED_BENCHMARK`

Preserve every prior result, rejection, artifact and seal. Use exactly the same
729-event population, including the same 648 mechanically executable setups,
from January-June 2022. Keep all overlapping signals and multiple simultaneous
trades. Do not impose a daily cap, one-trade rule, wait-for-resolution rule or
outcome-derived case exclusion. Keep 2025 and 2026 locked.

Freeze exactly one point-in-time direction policy for the 434
`CONTINUATION_REFRESH` setups. Evaluate the following hierarchy in order and
stop at the first matching disposition:

1. If `context_family` begins `RANGE_`, preserve the original direction.
2. Otherwise, if the selected unconsumed destination timeframe is H4, preserve
   the original direction.
3. Otherwise, if the local M15 liquidity level exactly equals the selected H1
   or H4 destination level, preserve the original direction.
4. Otherwise, if the destination was known for less than 240 minutes at the
   decision timestamp, preserve the original direction.
5. Otherwise negate the continuation plan: LONG becomes SHORT, SHORT becomes
   LONG, original absolute TP becomes the new SL and original absolute SL
   becomes the new TP.

These rules use completed, point-in-time plan fields only. Preserve all 214
non-continuation plans unchanged. Do not use macro, realised outcomes, case
identities, dates, PnL, MFE, MAE or future price to choose a route.

Run two execution tracks:

- `TRACK_A_FIXED_ORIGINAL_QUANTITY`: preserve every plan's sealed original
  whole-ounce quantity. This is the direct comparison with the sealed +45.7728R
  complete-portfolio diagnostic.
- `TRACK_B_NO_UPSIZE_50_USD_RISK`: calculate the selected plan's whole-ounce
  quantity as `min(original_quantity, floor(50 / selected_stop_distance))`.
  Never increase quantity after routing. Every executable trade must have no
  more than $50 displayed stop exposure. If one whole ounce exceeds the risk
  limit, retain the identity as `RISK_INFEASIBLE_WHOLE_OUNCE` rather than
  substituting, scaling or deleting it.

For both tracks preserve the existing one-minute latency, spread, slippage,
stop-first ambiguity treatment, absolute stop, absolute target, noon-New-York
deadline, costs and unrestricted overlap policy. Report actual concurrent
exposure; do not suppress a later valid setup because another trade is open.

The frozen exposed benchmark is the sealed complete replacement portfolio:

- Net R: `+45.772787857150256`
- Profit factor: `1.2406708931572503`
- Maximum drawdown: `21.758157857141946R`

`TRACK_B_NO_UPSIZE_50_USD_RISK` meets the benchmark only if it produces at least
`+45.772787857150256R`, preserves every technically risk-feasible identity,
keeps every displayed trade risk at or below $50, uses no quantity above the
original quantity, and independently reproduces exactly. Report monthly,
direction, route-reason and context-family contributions, win rate, expectancy,
profit factor, drawdown, stop exposure and concurrent exposure.

Freeze the route identities, selected plans, selected quantities, source hashes,
synthetic proofs and all gates before path resolution. Permit one result run
only. If either track misses the benchmark, record it honestly; do not retune,
add a condition, invert another family, change risk, or run an alternative.
Acquire no data, incur no charge, document, independently reproduce, seal and
stop.
