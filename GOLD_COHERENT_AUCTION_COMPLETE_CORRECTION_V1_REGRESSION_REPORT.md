# Gold Coherent-Auction Complete Correction V1 Regression Report

Status: `COMPLETE_AND_SEALED_EXPOSED_REGRESSION`

## Verdict

`REJECT_ZERO_EXECUTABLE_TRADES_OVERFILTERED`

The complete frozen correction package admitted zero of the 16 exposed human trades. It therefore earned `0.0000R` / `$0.00`, but this is not a successful defensive result: it removed every valid control winner as well as every loser. The package lost `1.79318807R` (`$89.66`) relative to the corrected fixed-H1 control and captured none of the post-hoc approximately `11R` ceiling.

## Numbers

| Metric | Frozen correction | Corrected fixed-H1 control |
|---|---:|---:|
| Trades | 0 | 15 |
| Net R | 0.00000000 | 1.79318807 |
| Net USD at $50/R | $0.00 | $89.66 |
| Win rate | N/A | 53.33% |
| Profit factor | N/A | 1.2436 |
| Maximum drawdown | 0.0000R | 4.0375R |

- Directionally correct cases rejected: 11 — CBR-2022-002, CBR-2022-005, CBR-2022-006, CBR-2022-013, CBR-2022-014, CBR-2022-015, CBR-2022-020, CBR-2022-023, CBR-2022-024, CBR-2022-027, CBR-2022-030.
- Positive fixed-H1 control trades rejected: 8 — CBR-2022-002, CBR-2022-006, CBR-2022-013, CBR-2022-015, CBR-2022-020, CBR-2022-023, CBR-2022-024, CBR-2022-027.
- Direction-wrong cases rejected: 5 — CBR-2022-003, CBR-2022-007, CBR-2022-009, CBR-2022-019, CBR-2022-026.

## Every case

| Case | Control R | Direction right | Frozen thesis | Primary rejection | All rejection gates |
|---|---:|:---:|---|---|---|
| `CBR-2022-002` | +0.7654 | YES | RANGE_ROTATION | `NO_LIVE_FROZEN_TRIGGER` | NO_LIVE_FROZEN_TRIGGER; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-003` | +0.0000 | NO | RANGE_ROTATION | `NO_LIVE_FROZEN_TRIGGER` | NO_LIVE_FROZEN_TRIGGER; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-005` | -1.0372 | YES | CONTINUATION_WITH_ROOM | `FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE` | FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE; CONTINUATION_MACRO_OPPOSED |
| `CBR-2022-006` | +0.7247 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-007` | -1.0351 | NO | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-009` | -1.0837 | NO | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-013` | +0.0544 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-014` | -1.0195 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-015` | +0.4206 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-019` | -1.0617 | NO | STRUCTURAL_REPAIR | `NO_LIVE_FROZEN_TRIGGER` | NO_LIVE_FROZEN_TRIGGER; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-020` | +0.3700 | YES | STRUCTURAL_REPAIR | `NO_LIVE_FROZEN_TRIGGER` | NO_LIVE_FROZEN_TRIGGER; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-023` | +2.1112 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-024` | +2.4773 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-026` | -1.0530 | NO | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE; TIER1_DIRECTIONAL_ACCEPTANCE_RETEST_MISSING |
| `CBR-2022-027` | +2.2306 | YES | RANGE_ROTATION | `NO_LIVE_FROZEN_TRIGGER` | NO_LIVE_FROZEN_TRIGGER; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |
| `CBR-2022-030` | -1.0709 | YES | NONE | `NO_ACTIVE_FORWARD_TARGET` | NO_ACTIVE_FORWARD_TARGET; NO_TRADE_OUTWARD_FROM_UNACCEPTED_BALANCE_BOUNDARY; FILL_INSIDE_ACTIVE_ENGAGED_HTF_ZONE |

## Failure attribution

Every case was inside or beyond an active, engaged higher-timeframe zone without the rulebook's required two-close acceptance. Ten were simultaneously classified as outward trades from an unaccepted balance boundary and had no active forward target under the frozen registry. Five of the remaining cases lacked the exact frozen live trigger. The CPI case also failed the event-range acceptance/retest gate.

This proves the package is too restrictive for the operator's observed method. It does **not** prove the underlying method has no edge. It proves that this exact deterministic translation does not preserve the method: its specificity is zero on this exposed sample because it authorizes no trades.

No threshold, lifecycle rule, or classification was changed after the pre-path seal. Primary/reference results matched for all 16 cases. The fresh 50-case block, 2025, and 2026 remain unopened.
