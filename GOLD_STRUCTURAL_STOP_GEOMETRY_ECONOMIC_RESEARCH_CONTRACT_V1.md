# Gold Structural Stop Geometry Economic Research Contract V1

Status: **FROZEN BEFORE STOP-PATH OR ECONOMIC RESULTS**

## Objective

Test whether alternative point-in-time structural invalidations can retain more of the already-measured post-entry gold movement while keeping every entry, direction, checkpoint, absolute target price, time deadline, cost assumption, and risk limit unchanged.

This branch preserves all prior rejections. A lower stop-hit rate is not an edge unless net expectancy remains positive after sizing and costs.

## Sources and periods

- Use only sealed 2021-08-01 through 2024-12-31 development sources for discovery and economic evaluation.
- Use only the 22,193 already-executed frozen model rows. Do not create an entry where the frozen model did not trade.
- Do not inspect or deserialize 2025 or 2026 values until a complete development candidate is frozen.
- If at least one candidate passes, 2025 and 2026 through 2026-07-29 may be applied once, unchanged, as exposed historical robustness evidence only.
- Acquire no data and incur no charge.

## Invariants

For every counterfactual stop retain unchanged:

- trade identity, model, direction, entry timestamp and entry price;
- original frozen absolute target price;
- original parent-bar deadline and time-exit close;
- stop-first treatment when stop and target occur in the same M1 candle;
- gap-aware stop fill;
- observed entry spread or $0.30/oz fallback, $0.07/oz commission, and $0.10/oz slippage;
- 1.5x and 2x cost stresses;
- whole-ounce sizing with $50 planned stop-plus-cost risk on a $10,000 account;
- no compounding and one open XAUUSD position.

## Frozen eligible stop registry

Exactly four primary geometries are eligible per entry model:

1. `STOP_BASELINE_FROZEN`: the original sealed stop price.
2. `STOP_CONFIRMATION_EXTREME_0P25_ATR`: for a long, confirmation low minus 0.25 ATR14; for a short, confirmation high plus 0.25 ATR14.
3. `STOP_PIVOT_0P25_ATR`: for a long, pullback pivot minus 0.25 ATR14; for a short, pullback pivot plus 0.25 ATR14.
4. `STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR`: the most recently known same-timeframe STANDARD lower swing below a long entry or upper swing above a short entry, plus a 0.10 ATR14 adverse buffer. `known_at <= entry_at` is mandatory.

If a required point-in-time level is unavailable or the calculated stop is not adverse to entry, that model row is `STOP_UNAVAILABLE`; it may not be repaired or substituted.

## Frozen parameter-neighbour diagnostics

Neighbours receive no candidate or multiplicity credit:

- confirmation 0.25 ATR: 0.15 and 0.35 ATR;
- pivot 0.25 ATR: 0.15 and 0.35 ATR;
- latest swing 0.10 ATR: 0.00 and 0.20 ATR;
- baseline confirmation 0.05 ATR: 0.00 and 0.15 ATR;
- baseline pivot 0.15 ATR: 0.05 and 0.25 ATR.

An economic candidate must have positive net expectancy at both registered neighbour buffers. Neighbours cannot replace or repair the primary geometry.

## Stage 1 — stop-survival analysis

Run Stage 1 completely and seal it before Stage 2 selection or economic ranking.

For every timeframe × model × stop × realised-archetype cell report:

- frozen entry rows and valid-stop coverage;
- stop distance in dollars/oz and ATR;
- stop hit before original target or deadline;
- target first, stop first, and time first;
- stop before or in the same minute as the full frozen-horizon MFE;
- full-horizon MFE and MAE;
- MFE and MAE before the actual counterfactual exit;
- first-passage and support counts.

An alternative stop is Stage-1 eligible only if, on its paired valid OOF rows:

- valid-stop and one-ounce sizing coverage are each at least 90% of the baseline population;
- the timeframe support floor is met;
- stop-before-global-MFE rate improves by at least 2.00 percentage points versus baseline;
- target-before-stop rate is not lower than baseline;
- median stop distance is no more than 3.0 ATR and its 90th percentile is no more than 6.0 ATR.

The baseline control always proceeds to economic reporting but receives no survival-improvement credit.

## Stage 2 — economic evaluation

Evaluate only the baseline controls and Stage-1-eligible alternatives. Analyse each timeframe × model × stop separately, applying its own one-position overlap policy in entry-time order. Preserve every rejected or unsupported row.

Primary performance population is the frozen blocked out-of-fold validation union:

- Fold 1: 2022-07-01 through 2023-03-31;
- Fold 2: 2023-04-01 through 2023-12-31;
- Fold 3: 2024-01-01 through 2024-12-31.

Full 2021-2024 results are descriptive diagnostics only.

Support floors after overlap:

- M15: 100 trades, 75 trading dates, 40 ISO weeks;
- H1: 50 trades, 40 trading dates, 25 ISO weeks;
- H4: 30 trades, 25 trading dates, 15 ISO weeks.

Apply Benjamini-Hochberg correction at q=0.10 separately within each timeframe across all economically evaluated model-stop tests. Cluster bootstrap by trading date with 5,000 resamples and deterministic candidate-specific seeds.

Formal economic PASS requires all of:

- positive OOF net expectancy;
- profit factor at least 1.05;
- clustered 95% confidence lower bound above zero;
- BH-adjusted q no greater than 0.10;
- positive expectancy at 1.5x costs;
- at least two positive validation folds;
- at least two positive OOF calendar years and no one year contributing more than 70% of positive annual net R;
- at least two positive session states and no one session contributing more than 70% of positive session net R;
- positive net expectancy at both frozen parameter neighbours;
- all support and Stage-1 survival gates.

Rank passing candidates by 95% confidence lower bound, 1.5x-cost expectancy, profit factor, trade support, lower drawdown, then stable identifier. Freeze no more than two candidates per timeframe; zero is acceptable.

## Required economic reporting

Report support, stop-hit and stop-before-MFE rates, MFE, MAE, win rate, average win and loss, gross and net expectancy, profit factor, $50-normalized PnL, actual whole-ounce PnL, maximum drawdown, annual results, fold results, session results, cost stresses, neighbour sensitivity, multiplicity, and exact failed gates.

## Forward and stopping policy

If no development candidate passes, do not open 2025/2026 and stop with a rejection. If candidates pass, seal their complete definitions and development results before opening existing forward sources, then apply once without retuning. Forward evidence cannot reverse a development rejection and receives no independent-validation credit.

Do not alter entries, targets, deadlines, classifier, router, risk tiers, or later remove losses. Independently reproduce all results, document negative findings, seal the final state, and stop.

