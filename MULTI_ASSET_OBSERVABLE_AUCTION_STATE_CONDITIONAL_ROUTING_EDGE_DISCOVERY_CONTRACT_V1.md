# Multi-Asset Observable Auction-State Conditional Routing Edge Discovery Contract V1

## Mandate

This branch tests whether point-in-time observable auction state can identify a
small, economically tradable subset of the already frozen M15, H1 and H4
0.25-ATR checkpoints. It does not alter those checkpoints and does not interpret
the prior indiscriminate-routing failure as proof that every conditional policy
must fail.

The formal `FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY` verdict, all earlier
results and all seals remain unchanged. XAUUSD and its held candidate remain
outside this branch.

## Frozen population and sources

- Development: 2021-08-01 through 2024-12-31.
- Instruments: XAGUSD, EURUSD, USDJPY, USTEC, US500 and XTIUSD.
- Eligible population: the 10,388 Coverage Amendment A cases in the twelve
  passing instrument-session units.
- Checkpoints: the first frozen M15, H1 or H4 completed relative bar satisfying
  the prior 0.25-ATR displacement and outer-quarter close rule.
- Existing sealed IC Markets MT5 and point-in-time macro/event/COT sources only.
- No acquisition and no charge.
- Calendar 2025 and 2026 remain locked until a development candidate passes
  every frozen gate.

## Information boundary

Every router input must be available at the checkpoint. Eligible information is:

- point-in-time macro direction and confidence;
- completed W1, D1, H4, H1, M15 and M5 state;
- confirmed swings and levels known before the session;
- early-session displacement, range, efficiency and adverse excursion through
  the checkpoint;
- level acceptance, rejection or sweep/reclaim completed by the checkpoint;
- session phase, ATR, broker spread, observed quote density and tick-volume
  state;
- scheduled-event metadata available by the checkpoint.

Final descriptive archetypes, future session bars, MFE, MAE, future extrema,
eventual direction, target/stop result and realised return are forbidden router
inputs. Missing facts remain unknown and are never converted silently to a
neutral economic interpretation.

## Frozen endpoint and economics

The primary statistical endpoint is `+1R before -1R`. Target-first is one,
stop-first is zero, and unresolved time exits are censored for the probability
endpoint but retained in economic evaluation.

Entry, one-ATR stop, one-ATR target, session deadline, one-minute latency,
stop-first ambiguous-bar treatment, broker sizing, spread, 0.03R execution
allowance and 0.05R minimum cost remain unchanged from the predecessor.
Cost stress is 1.5 times observed cost. Maximum planned loss is $100 on the
frozen $10,000 account per concurrent correlation cluster. Only one active
position per cluster is allowed.

## Research order

1. Independently reproduce the complete outcome-blind checkpoint-feature tape.
2. Open the sealed development outcomes once.
3. Complete and seal every registered Stage-1 univariate test.
4. Run every registered Stage-2 interaction, regardless of Stage-1 favourability.
5. Fit the one frozen global shallow-tree probability router using expanding
   chronological folds and training-only transformations.
6. Produce strictly out-of-fold decisions for 2022-2024.
7. Apply the frozen economic and calibration gates.
8. Only after a development PASS, freeze the full candidate and open 2025 once,
   then 2026 once. Never retune after either segment.

## Statistical controls

- Stage 1 uses Benjamini-Hochberg at q=0.05 across the complete registry.
- Stage 2 uses Holm family-wise adjustment at 0.05.
- Each relationship requires at least 800 resolved observations, nontrivial
  effect, OOF Brier improvement and annual sign stability.
- The router is a depth-three decision tree with minimum 200 training rows per
  leaf and fixed random seed.
- Missing numeric inputs use training-only medians; numeric values are clipped
  to training-only 1st/99th percentiles. Categories use the sealed registry.
- A checkpoint is route-eligible only when its predicted net expectancy exceeds
  +0.05R after the observable cost estimate.
- Case routing chooses the earliest positive checkpoint; subsequent correlation
  cluster overlap is rejected deterministically.

## Economic PASS gates

The single router candidate passes only if all conditions hold out of fold:

- at least 180 accepted trades and five trades per month;
- positive net expectancy and profit factor at least 1.10;
- positive session-date clustered 95% confidence lower bound;
- positive expectancy at 1.5 times costs;
- at least four positive validation folds and two positive calendar years;
- positive Brier skill and expected calibration error no greater than 0.05;
- maximum drawdown no greater than 15R;
- no year or session supplies more than 70% of positive contribution.

At most one router candidate is created by this implementation, below the
authorized maximum of six. Zero passing candidates is acceptable.

## Prohibitions

The branch may not optimize directly for 10R/month, alter the frozen trigger or
execution, weaken gates, invert failed relationships, remove losses, use final
archetypes for routing, add an unregistered predictor, inspect forward values
before a development PASS, or purchase data.

## Terminal states

- `PASS_PROVISIONAL_UNVALIDATED_CANDIDATE`: freeze and test 2025 then 2026 once.
- `REJECT_NO_ECONOMICALLY_TRADABLE_CONDITIONAL_ROUTER`: keep both forward years
  unopened and stop.
- An integrity, reproducibility, required-source or potential-charge blocker is
  recorded honestly and stops the branch.

