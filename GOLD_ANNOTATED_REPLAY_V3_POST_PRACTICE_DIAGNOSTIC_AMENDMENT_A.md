# Gold Annotated Replay V3 Post-Practice Diagnostic Amendment A

Status: `AUTHORIZED_AND_FROZEN_BEFORE_FULL_OUTCOME_ACCESS`

Date: 2026-08-17

## Purpose and boundary

The user completed all twenty V3 practice days and explicitly authorized analysis. This amendment permits one deterministic post-practice diagnostic of the completed human ledger. It does not give these practice cases research, validation, or edge-discovery credit.

The one-year primary collection remains `CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE`. Calendar 2025 and calendar 2026 remain `LOCKED`. No data acquisition, paid request, strategy optimization, parameter fitting, risk scaling, or rule creation is permitted.

Two individual trade outcomes were previously viewed solely to confirm that the application recorded the first two trade lifecycles. No aggregate practice result was calculated before this amendment.

## Frozen population

- Cases: exactly `V3-P-001` through `V3-P-020`.
- Ledger: exactly 2,041 events through ledger head `fd347277b2cd312469689fd142fa78b30836208a60d26561baa478287f60a416`.
- Include every submitted order. A filled-trade record requires exactly one matching submission, fill, and terminal resolution.
- Report pending, expired, cancelled, and unfilled orders separately.
- Preserve every no-trade day. Do not infer that a trade should have been taken.
- Decision information comes only from the immutable order annotation and the latest sealed context record whose `available_at` is no later than `submitted_at`.
- Outcome information comes only from the recorded fill/resolution and sealed M1 bars at or after the fill.

## Frozen economic calculations

For direction sign `s` equal to +1 for LONG and -1 for SHORT:

- Net PnL = `s × (actual_exit_price − actual_fill_price) × quantity_ounces − commission`.
- Frozen commission is the execution-policy value, currently $0.00 per whole-ounce round turn. Recorded spread and slippage are already contained in actual fill and exit prices and must not be added twice.
- Primary normalized return is `R50 = net_PnL / 50`, using the frozen maximum case risk.
- Secondary planned-risk return is `net_PnL / submitted_order.risk_usd` when planned risk is positive.
- A win has net PnL greater than $0.01, a loss less than -$0.01, and otherwise is a scratch.
- Profit factor is gross winning dollars divided by absolute gross losing dollars.
- Drawdown is the largest peak-to-trough decline of chronological cumulative R50, including a zero starting peak.
- Report longest win and loss streak, average/median result, average win/loss, payoff ratio, and expectancy.
- Do not annualize, extrapolate a monthly return, or calculate required scaling from this outcome-blindly selected practice sample.
- Trade-level Sharpe and Sortino are `NOT_MEANINGFUL_SMALL_SAMPLE` unless at least 30 filled trades exist.

## Frozen path calculations

- MFE and MAE use sealed M1 high/low from actual `fill_at` through actual `exit_at`, inclusive.
- Directional MFE price is the maximum favorable difference from actual fill; directional MAE price is the maximum adverse difference.
- Dollar and R50 MFE/MAE multiply price excursion by whole-ounce quantity and divide by $50 where applicable.
- Holding time is `exit_at − fill_at` in minutes.
- Winner capture efficiency is positive net PnL divided by favorable excursion dollars; it is not defined when favorable excursion is nonpositive.
- A stopped-then-later-target diagnostic checks whether the original target is touched after stop exit and before the frozen order expiry/day end. This is descriptive and does not assume the stop could have been removed.
- Entry distance, stop distance, target distance, and planned reward-to-risk use the submitted immutable geometry. Effective reward-to-risk uses actual fill.

## Frozen uncertainty and support

- Win-rate uncertainty uses the Wilson 95% interval.
- Net expectancy uncertainty uses 20,000 deterministic completed-day cluster bootstrap samples with seed `20260817` and percentile 2.5%/97.5% bounds.
- Every segment is shown, but a segment with fewer than three filled trades is marked `LOW_SUPPORT_DESCRIPTIVE_ONLY`.
- Any repeated strength or weakness requires at least two occurrences. A one-off is explicitly labeled a single-case observation.
- No statistical or economic edge PASS is possible from this practice diagnostic. The overall evidence label must be `ZERO_CREDIT_DESCRIPTIVE`, with positive, negative, or inconclusive sample description.

## Frozen session and context mapping

Decision session uses `submitted_at` and the same practice-window boundaries displayed by the certified UI:

- Before 2021-10-31: London 07:00–16:00 UTC; afterward 08:00–17:00 UTC.
- Before 2021-11-07: New York 12:00–21:00 UTC; afterward 13:00–22:00 UTC.
- London–New York overlap has precedence when both windows are active.
- Asia runs from 00:00 UTC to London open. Rollover is the hour following New York close. Remaining time is `OTHER`.

The latest point-in-time fundamental engine snapshot is joined when `available_at <= submitted_at`. User-stated fundamental direction is aligned when LONG pairs with BULLISH or SHORT with BEARISH, contradicted for the opposite pair, and otherwise neutral/unknown. The engine score is confirming when its sign above +10 or below -10 matches the order direction, contradicting when it opposes, and neutral/conflicted otherwise. Engine confidence is not treated as win probability.

Structure alignment uses the latest point-in-time structure snapshot and the selected timeframe plus the next higher available timeframe. `BULLISH` confirms LONG and `BEARISH` confirms SHORT; the opposite contradicts; `RANGE`, `MIXED_OR_TRANSITIONING`, or missing is neutral/unknown.

## Frozen annotation taxonomy

All matching is case-insensitive and may assign multiple tags.

- `SWEEP_RECLAIM`: sweep, reclaim, liquidity grab, stop hunt.
- `BREAK_RETEST`: retest, break and retest, bos, break of structure, neckline.
- `REVERSAL_RESPONSE`: reversal, engulf, pin bar, hammer, shooting star, rejection, wick.
- `FIB_RETRACE`: fib, fibonacci, retrace, retracement, 38%, 50%, 61%, 62%.
- `MOMENTUM_DISPLACEMENT`: displacement, momentum, aggressive buyer, aggressive seller, impulse.
- `LEVEL_LOCATION`: support, resistance, previous high, previous low, swing high, swing low, liquidity.
- Unmatched triggers are `OTHER_WRITTEN_TRIGGER`; empty text is `MISSING`.

Reasoning specificity is reported separately—not combined into a fitted score:

- Macro-specific if the thesis or driver names yield, real yield, rate, Fed, dollar, DXY, inflation, CPI, PCE, payroll, NFP, employment, growth, risk, positioning, or liquidity.
- Higher-timeframe-specific if the field names a timeframe or trend/structure plus support, resistance, range, high, low, swing, bullish, or bearish.
- Invalidation-specific if it names a break/close/acceptance beyond a high, low, swing, support, resistance, structure, or numeric level. Generic phrases such as only “bearish structure” or “bullish structure” are marked generic, not specific.
- Target-specific if it names a prior high/low, swing, support/resistance, liquidity, benchmark, or numeric level. Generic “next level” language without an identified level is marked generic.
- Event-risk-specific if it names an event or explicitly states no known event risk.

Free-text conclusions are labeled `INFERRED_REVIEW`, quoted only in short excerpts, and must remain traceable to order IDs.

## Frozen report order

1. Ledger and lifecycle integrity.
2. Overall fixed-risk economics and uncertainty.
3. Chronological trade table.
4. Direction, timeframe, session, confidence, and resolution segments.
5. MFE/MAE, holding-time, stop, target, and capture diagnostics.
6. Fundamental and structure alignment.
7. Annotation taxonomy and reasoning-specificity audit.
8. Repeated strengths, repeated weaknesses, and bounded improvements.
9. Honest zero-credit verdict and next-study recommendation.

Primary and reference calculations must independently reproduce the complete trade table and summary checksum. All negative and ambiguous findings remain in the report.

