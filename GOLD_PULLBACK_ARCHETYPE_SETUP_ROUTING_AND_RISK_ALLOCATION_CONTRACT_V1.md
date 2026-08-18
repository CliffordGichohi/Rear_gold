# Gold Pullback Archetype Setup Routing and Risk Allocation Contract V1

Status: `FROZEN_BEFORE_NEW_MODEL_BY_ARCHETYPE_PERFORMANCE_MEASUREMENT`

## Objective

Treat the sealed gold pullback population as a mixture of six recurring path
archetypes rather than as one universal setup.  Define a distinct, observable
entry model for each archetype, measure every entry model against every realised
archetype, estimate archetype probabilities only from facts available at the
decision checkpoint, and compare constant-risk execution with a single
non-overlapping probability-routed portfolio.

This is post-hoc research.  The 2021-08-01 through 2024-12-31 results receive
development credit only.  Calendar 2025 and 2026 are exposed historical
robustness periods and receive no independent-validation credit.

## Preserved predecessor evidence

All predecessor results, including every rejection, remain valid and unchanged.
The governing archetype source is the sealed six-group atlas with 8,653 STANDARD
M15, H1 and H4 cases, of which 8,205 have a technically available archetype and
448 remain `UNAVAILABLE_TECHNICAL`.  An unavailable case may not be imputed,
relabeled or silently dropped from coverage reporting.

The predecessor execution grid and its outcomes were already exposed during
earlier research.  They may be reused as development evidence, but they provide
no validation credit.  The mapping from an archetype entry model to an exact
execution specification is frozen below before calculating the new payoff
matrix.

## Observable checkpoints and entry models

Every entry occurs on an M1 open at or after an observable state transition.
The eventual archetype is never supplied to the decision.  A model may be
evaluated only when its own point-in-time trigger exists.

1. `RUNAWAY_BREAKOUT`
   - checkpoint: first confirmation-extreme break within four parent bars;
   - direction: existing trend;
   - entry: frozen confirmation-extreme break fill;
   - stop: opposite confirmation-candle extreme plus 0.05 ATR;
   - target: fixed 2.0R;
   - time exit: eight parent bars;
   - intended archetype: `RUNAWAY_CONTINUATION`.

2. `BREAK_RETEST_CONTINUATION`
   - checkpoint: first completed confirmation-extreme break, retest and close
     back on the trend side within four parent bars;
   - direction: existing trend;
   - entry: next available M1 open;
   - stop: opposite confirmation-candle extreme plus 0.05 ATR;
   - target: fixed 1.5R;
   - time exit: eight parent bars;
   - intended archetype: `BREAK_RETEST_CONTINUATION`.

3. `DEEP_RETRACE_CONTINUATION`
   - checkpoint: first touch of the frozen halfway level between the completed
     confirmation close and confirmed pullback pivot within four parent bars;
   - direction: existing trend;
   - entry: frozen halfway limit price;
   - stop: confirmed pullback pivot plus 0.15 ATR;
   - target: fixed 2.0R;
   - time exit: sixteen parent bars;
   - intended archetype: `DEEP_RETRACE_CONTINUATION`.

4. `FALSE_CONTINUATION_REVERSAL`
   - checkpoint: an opposing completed structure switch after a previously
     observed confirmation-extreme break;
   - direction: opposite the former trend;
   - entry: first available M1 open at or after the structure-switch timestamp;
   - stop: former confirmation extreme plus 0.05 ATR;
   - target: fixed 2.0R;
   - time exit: eight parent bars;
   - intended archetype: `FALSE_CONTINUATION`.

5. `IMMEDIATE_FAILURE_REVERSAL`
   - checkpoint: an opposing completed structure switch without a prior
     confirmation-extreme break;
   - direction: opposite the former trend;
   - entry: first available M1 open at or after the structure-switch timestamp;
   - stop: former confirmation extreme plus 0.05 ATR;
   - target: fixed 1.5R;
   - time exit: eight parent bars;
   - intended archetype: `IMMEDIATE_FAILURE`.

6. `TWO_SIDED_REFERENCE_RETEST`
   - checkpoint: first retest of a pre-existing, still-valid reference level
     lying between the completed confirmation close and structural invalidation;
   - direction: existing trend, treating the reference as a range boundary;
   - entry: frozen reference-level limit price;
   - stop: confirmed pullback pivot plus 0.15 ATR;
   - target: fixed 1.0R;
   - time exit: four parent bars;
   - intended archetype: `TWO_SIDED_CHOPPY`.

Stop-first handling applies when stop and target are both touched in the same M1
bar.  Missing or discontinuous paths produce `NO_TRADE`; they are never filled
or repaired.

## Information available to the probability model

Models may use only completed-candle facts already sealed at `known_at_utc`, plus
metadata observable by the model checkpoint: trigger identity, trigger delay,
entry displacement from the completed confirmation close, distance from the
confirmed pivot, and checkpoint session.  The frozen registry covers:

- impulse, pullback, compression and retracement measurements;
- completed pivot and confirmation candle geometry;
- response displacement and efficiency;
- pre-existing reference, prior-day and Asian-range interactions;
- completed H1/H4/daily/weekly structure alignment;
- session state;
- point-in-time fundamental score, confidence, coverage, regime, reaction
  function and component contributions;
- point-in-time COT state and freshness; and
- checkpoint facts listed above.

All missing values receive explicit missing indicators or an `UNKNOWN` category.
No later-formed price path, realised resolution, MFE, MAE, trade result or
archetype label may enter a continuation-model prediction.  At an already
completed opposing structure switch, the observed break/no-break and barrier
ordering may deterministically identify the corresponding failure state because
the reversal entry occurs only after that state transition.

## Probability model and chronological evaluation

- Fit separate deterministic shallow multiclass probability trees for every
  timeframe and non-deterministic entry checkpoint.
- Maximum depth is four.  Minimum leaves are 80 for M15, 30 for H1 and 15 for H4.
- Numeric split candidates are the training-only 20th, 40th, 60th and 80th
  percentiles.  Categorical candidates are training categories with at least the
  applicable minimum-leaf support.  Missing numeric values route left.
- Leaf probabilities use one-count Dirichlet/Laplace smoothing over all six
  archetypes.
- Choose one temperature from `[0.75, 1.00, 1.25, 1.50, 2.00]` using only the
  final chronological 20% of the applicable training period, then refit the tree
  on the complete training period without changing that temperature.
- Use the three already sealed expanding walk-forward folds ending in calendar
  2022/2023/2024 validation periods.
- Report top-one accuracy, prior-only accuracy, multiclass Brier score and skill,
  log loss, expected calibration error, reliability bins and confusion matrix.

A probability model is calibration-eligible only with at least 100 OOF rows for
M15, 50 for H1 or 25 for H4, positive Brier skill versus its fold-specific prior,
log loss no worse than the prior, top-one accuracy no worse than the prior, and
ECE no greater than 0.12.  Failure disables variable-risk routing for that
timeframe/model but does not erase its equal-risk diagnostic.

## Payoff matrix and risk routing

Run all six frozen entry models wherever their observable trigger exists and
report every entry-model by realised-archetype cell.  Cell statistics include
support, win rate, expectancy, profit factor, average win/loss, MFE, MAE, holding
time and costs.  Empty and low-support cells remain explicit.

For a validation decision, estimate the entry model's net expected R from
training-only archetype-cell payoffs and its probability vector.  Cell means use
a frozen 20-observation shrinkage toward the entry-model-wide training mean.
The conservative score is expected R minus one estimated standard error.  A
cell with fewer than two observations uses the entry-model-wide variance.

Constant-risk benchmark:

- initial account: USD 10,000;
- planned risk: USD 50 per accepted trade;
- whole-ounce sizing; no compounding.

Variable-risk tiers, using the conservative score:

- score `<= 0.00R`: no trade;
- `(0.00R, 0.10R]`: USD 25 risk;
- `(0.10R, 0.20R]`: USD 50 risk;
- `(0.20R, 0.30R]`: USD 75 risk;
- `> 0.30R`: USD 100 risk.

Only one XAUUSD position may be open across all models and timeframes.  At equal
timestamps, the higher conservative score wins; remaining ties use the frozen
priority: immediate-failure reversal, false-continuation reversal, break-retest,
deep retrace, runaway breakout, two-sided reference retest.  The all-model
equal-risk benchmark uses timestamp order and that same priority without seeing
probabilities.  No open-risk compounding is permitted.

## Costs, reports and gates

Use observed entry spread when available, otherwise USD 0.30 per ounce, plus USD
0.07 commission and USD 0.10 slippage per ounce.  Report 1.0x, 1.5x and 2.0x
costs.

Report M15, H1 and H4 separately, every model separately, the all-model equal-risk
portfolio and the routed variable-risk portfolio.  Include net PnL, expectancy
in R, win rate, average win/loss, profit factor, drawdown, monthly result,
Sharpe/Sortino where meaningful, MFE/MAE, fold/year/session stability and
bootstrap confidence intervals clustered by New York trading date.

The routed development system is economically viable only if it has at least 100
OOF trades, positive net expectancy, profit factor at least 1.05, a positive 95%
cluster-bootstrap lower confidence bound, positive expectancy under 1.5x costs,
positive expectancy in at least two of three validation folds, and no single
entry model supplying more than 70% of positive gross R.  A failure remains a
valid negative result and may not be repaired post hoc.

## Forward and prospective handling

Only after the full-development entry models, probability trees, payoff tables,
risk tiers and router are hashed and sealed may calendar 2025 and available 2026
through 2026-07-29 be opened for this branch.  Apply the frozen system once and
unchanged.  Missing forward fundamental fields remain `UNKNOWN` under the frozen
policy and may not be backfilled from future information.  Report 2025, 2026 and
combined results separately as exposed historical robustness evidence only.

Initialize an append-only paper ledger for the next eligible setup.  Never
backfill a missed prospective decision.  Live order placement is not authorized.

## Integrity and stopping rules

- Verify every predecessor source hash before calculation.
- Produce primary and reference calculations from the corresponding sealed
  sources and require identical row identities, model definitions, predictions,
  trades, statistics and checksums.
- Acquire no data and incur no charge.
- Preserve all negative findings and technically unavailable rows.
- Do not retune, invert, selectively filter or add a seventh model after viewing
  results.
- Stop only on a failed integrity gate, an unavailable required source or a
  potential charge.

