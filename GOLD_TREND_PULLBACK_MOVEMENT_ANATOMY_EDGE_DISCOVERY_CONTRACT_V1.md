# Gold Trend-Pullback Movement Anatomy and Execution Edge Discovery Contract V1

Status: `FROZEN_BEFORE_NEW_MOVEMENT_ANATOMY_ACCESS`

## Objective

Determine whether the already-demonstrated trend-pullback continuation behaviour can be monetized by an objective, point-in-time entry and payoff geometry. This is a new development branch. It preserves every earlier result and rejection, including the nine relationship candidates and the rejection of their first fixed economic implementation.

The branch must distinguish:

- a repeatable structural relationship;
- a trade trigger observable in real time;
- the complete post-trigger movement path; and
- a positive net economic edge after costs.

## Population and periods

Use all research-eligible, feature-available, resolved STANDARD-scale M15, H1 and H4 pullbacks from 2021-08-01 through 2024-12-31. A resolved case has the frozen census outcome `CONTINUED` or `FAILED_STRUCTURE_SWITCH`. The nine frozen relationship conditions remain tags; they are not changed, inverted, or assumed profitable.

MICRO and MAJOR scales may be reported as sensitivity diagnostics but cannot be counted as independent trades because they overlap STANDARD cases. Calendar 2025 and 2026 remain locked until an exact execution candidate passes every development gate. No paid acquisition is authorized.

## Point-in-time predictors

Use only fields sealed in the 93-column predecessor feature matrix and facts known no later than `known_at_utc`. This includes trend age and impulse, retracement depth and efficiency, confirmation geometry, objective levels, sessions, completed-candle higher-timeframe state, point-in-time fundamental context, rates/USD contributions, COT context, and evidence lineage.

No post-decision price, structural resolution, MFE, MAE, target hit, or future market state may become a predictor.

## Movement-anatomy ledger

For every eligible case, anchor the path at the first available IC Markets XAUUSD M1 open at or after `known_at_utc`, with a maximum five-minute delay. Preserve exact source lineage.

In trend-normalized ATR14 units record:

- open/high/low/close displacement at 1, 5, 15, 30 and 60 minutes;
- displacement, MFE and MAE at 1, 2, 4, 8 and 16 completed parent bars;
- complete-horizon MFE, MAE, terminal displacement, time to maximum favourable and adverse excursion;
- first-passage time to favourable and adverse 0.25, 0.50, 0.75, 1.00, 1.50, 2.00 and 3.00 ATR levels;
- first passage ordering for symmetric barriers;
- continuation, rejection, reversal and unresolved path classifications;
- objective entry-trigger availability, delay and fill facts; and
- all missingness, incomplete-path, weekend, maintenance and timestamp classifications.

The sealed raw M1 path remains the lossless candle record. The anatomy ledger is a deterministic normalized index of every economically relevant path property; it never substitutes or repairs source candles.

## Frozen entry triggers

Each trigger is active only after `known_at_utc`. Maximum trigger wait is four completed parent bars.

1. `IMMEDIATE`: first available M1 open.
2. `CONFIRMATION_EXTREME_BREAK`: first trend-side trade through the completed confirmation-bar extreme; adverse gaps fill at the M1 open.
3. `RESPONSE_HALF_RETRACE_LIMIT`: first touch of the midpoint between decision close and confirmed pivot price; fill at the frozen limit, never a more favourable price.
4. `REFERENCE_LEVEL_RETEST_LIMIT`: first touch of the known reference structure level when it lies between decision price and structural invalidation.
5. `BREAK_RETEST_CONFIRM`: after a confirmation-extreme break, first later M1 touch of that level which closes back on the trend side; entry is the next available M1 open within five minutes.

No hindsight pivot entry is permitted.

## Frozen stops, targets and exits

Stops:

- confirmed pullback pivot plus/minus 0.05 ATR;
- confirmed pullback pivot plus/minus 0.15 ATR; and
- completed confirmation-bar adverse extreme plus/minus 0.05 ATR.

Targets:

- 1.0R, 1.5R and 2.0R; and
- nearest known, unbroken, trend-side STANDARD swing.

Time exits are the close before 4, 8 or 16 completed parent bars after entry. Stop is assumed first when stop and target touch in the same M1 candle. Stops gap adversely; targets never improve on gaps.

This creates exactly 180 execution specifications per frozen relationship condition: five triggers by three stops by four targets by three time exits. Specifications that cannot form a valid point-in-time entry, stop, target or complete path are explicit `NO_TRADE`, not silently removed.

## Costs and sizing

Retain the earlier frozen cost and sizing model:

- observed entry spread, or $0.30/oz fallback;
- $0.07/oz round-trip commission;
- $0.10/oz round-trip slippage;
- baseline, 1.5x and 2.0x cost stresses;
- fixed $50 planned risk on a $10,000 reference account;
- one ounce minimum, whole-ounce sizing, no compounding; and
- one open XAUUSD portfolio position.

## Discovery and validation

Analyse M15, H1 and H4 separately. Preserve the nine relationship conditions as the only initial pattern filters. Search the complete frozen execution grid without adding a rule after seeing results.

Use three expanding, chronological walk-forward folds:

1. train 2021-08-01–2022-06-30; validate 2022-07-01–2023-03-31;
2. train through 2023-03-31; validate 2023-04-01–2023-12-31; and
3. train through 2023-12-31; validate calendar 2024.

Within each fold, rank specifications using training data only by: positive 95% date-cluster-bootstrap lower bound, expectancy, profit factor, support, lower drawdown, then canonical specification ID. Retain at most three training selections per relationship condition. OOF performance consists only of the corresponding next validation block.

An exact specification can become a provisional development candidate only if it is selected in at least two folds and has at least:

- M15: 120 OOF trades on 75 dates;
- H1: 60 OOF trades on 40 dates;
- H4: 30 OOF trades on 25 dates;
- 15 OOF winners and 15 OOF losers;
- positive OOF net expectancy and a strictly positive 95% date-cluster-bootstrap lower bound;
- Holm-adjusted one-sided p at most 0.05 across shortlisted specifications;
- OOF profit factor at least 1.20;
- positive expectancy in at least two of the three validation folds and none below -0.10R with adequate support;
- positive 1.5x-cost expectancy and profit factor at least 1.05;
- maximum reference-account drawdown no more than 15%; and
- no single trade exceeding 25% of total positive net R.

Permit no more than three development candidates per timeframe. Zero is acceptable. Report the complete grid, training selections, OOF results, no-trades and negative results.

## Forward and portfolio

Freeze every development candidate before opening forward values. Apply the exact candidates once, unchanged, to calendar 2025 and 2026 through 2026-07-29. Require positive expectancy in each supported segment, combined 90% confidence lower bound above zero, profit factor at least 1.15, and positive 1.5x-cost expectancy. Forward evidence may reject but never repair a candidate.

Build the non-overlapping portfolio only from candidates surviving forward robustness. Prioritize H4, H1, then M15 and preserve frozen ranking within timeframe. Initialize an append-only paper ledger; authorize no live trading.

## Integrity and stopping rule

Primary and reference calculations must agree on case identities, anatomy, triggers, trades, statistics and hashes. Keep 2025/2026 locked if no development candidate passes. Do not acquire data, add filters, weaken gates, inspect rejected alternatives selectively, or claim an edge from in-sample hit rate. Complete this branch without intermediate authorization and stop with an honest economic verdict unless a genuine source/seal failure or potential charge occurs.
