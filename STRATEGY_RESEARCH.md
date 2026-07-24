# Book-Aligned Gold Strategy Research Protocol

## Purpose

A “strong strategy” means a causal, point-in-time rule set that remains useful
outside the sample used to design it. It does not mean the most profitable
parameter combination on the currently loaded month. This protocol turns the
reference book into falsifiable hypotheses and defines the evidence required
before any strategy is promoted.

## Candidate A: regime-guided London acceptance

`FUNDAMENTAL_GUIDED_ASIA_ACCEPTANCE_V2` is the first complete research candidate.
It separates four decisions:

```text
bias
  = regime + Fed path + yields/USD + catalyst surprise + positioning

trigger
  = completed Asia range + London breakout + closed-bar acceptance

invalidation
  = ATR/structure stop or opposing macro/price evidence

risk
  = equity risk budget + broker lot rules + costs + event/liquidity guard
```

The candidate permits a long only when the price trigger is long and the eligible
fundamental score is sufficiently bullish; shorts are symmetric. Minimum evidence
coverage and confidence are independent gates. High or extreme event risk produces
`WAIT`. Once that catalyst clears, the engine may reconsider the still-valid price
setup from newly closed bars.

This tests one precise claim:

> London acceptance outside a complete Asia range has better cost-adjusted
> expectancy when its direction agrees with the contemporaneously knowable gold
> macro state, provided the market is not inside a major catalyst blackout.

The price-only strategy is the mandatory control. A direction-only macro gate and
the full macro-plus-catalyst gate are ablations. If the full version does not beat
those controls out of sample, it is rejected or simplified.

## Candidate B: post-event repricing acceptance

The next hypothesis targets CPI, PCE, NFP, wages, Fed decisions, GDP, retail sales,
and claims:

```text
eligible actual-versus-consensus surprise
-> change in the expected Fed path
-> 2Y and real-yield confirmation
-> USD confirmation or documented safe-haven exception
-> gold accepts beyond a pre-event structure level
-> enter only after the confirmation bar; invalidate on structure failure
```

This candidate stays disabled until timestamped historical consensus, CME path
snapshots, and intraday cross-market data are available. Daily FRED observations
cannot be relabelled as one-minute confirmation. If yields or USD contradict the
headline surprise, the state is `CONFLICTED` or `WAIT`, not a forced trade.

## Development dataset

The research dataset should cover at least five years and include materially
different environments: pandemic/liquidity stress, inflation acceleration,
aggressive tightening, disinflation, and easing expectations. Required clocks are:

- one-minute gold bar close and availability;
- original release, consensus, revision, and schedule-known times;
- daily Fed-path publication times;
- COT Tuesday observation and actual publication times; and
- session/DST transitions and provider maintenance windows.

Synthetic fixtures prove correctness only. They never enter performance claims.

## Evaluation sequence

1. Freeze the hypothesis, outcome definitions, and parameter ranges.
2. Keep the final chronological segment locked and unseen during design.
3. Use anchored walk-forward training and validation windows.
4. Compare price-only, macro-direction, and full-gate ablations.
5. Run a broad parameter grid; prefer stable plateaus over the single best cell.
6. Stress spread, slippage, and commission at 1.0x, 1.5x, and 2.0x assumptions.
7. Reshuffle trade order and bootstrap by regime/session blocks.
8. Report results by year, regime, direction, session, catalyst type, and
   positioning percentile.
9. Re-run once on the locked holdout without changing rules.

## Graduation criteria

No candidate is called a research champion unless all of the following hold:

- positive out-of-sample expectancy after modeled costs;
- the 95% expectancy interval does not rely on one year or one event type;
- no isolated parameter spike explains the result;
- drawdown remains within the predeclared risk budget under cost stress;
- results survive removal of the best trades and trade-order reshuffling;
- sufficient observations exist for the claimed scope;
- every decision can be reproduced from immutable facts available at that time;
- contradictions and excluded observations remain visible; and
- the locked holdout was evaluated once, with no post-hoc retuning.

These checks reduce overfitting; they do not guarantee future profit. Until they
pass, the dashboard must label the candidate `RESEARCH / INSUFFICIENT EVIDENCE`.

## Current evidence checkpoint — 24 July 2026

The observed IC Markets store now contains 1,770,267 completed XAUUSD one-minute
bars from 23 July 2021 through 24 July 2026. Real daily cross-market observations
and COT begin in January 2023, and the Atlanta Fed quarterly SOFR-expectations
history begins on 29 March 2023. The common full-fundamental research window
therefore begins in April 2023.

The first untouched retrospective slice exposed that the old 10:00 Tokyo range
started inside the broker's historical maintenance/reopen gap. Strategy version
1.3.0 moves the configurable default to 10:05–16:00 Tokyo and continues to reject,
rather than synthesize, any incomplete day. On 1 April through 29 July 2023, with
the previously frozen 1.5 ATR stop, 2.0R target, costs, and score gates:

| Candidate | Trades | Long / short | Expectancy | Profit factor | Net PnL | Max DD | Bootstrap 95% interval |
|---|---:|---:|---:|---:|---:|---:|---:|
| price-only control | 61 | 29 / 32 | -0.442 R | 0.534 | -2,397.23 USD | 24.32% | [-0.792, -0.093] R |
| real fundamental gate | 20 | 10 / 10 | -0.615 R | 0.399 | -1,166.82 USD | 13.31% | [-1.144, -0.023] R |

Run IDs are `723adeee-e1c4-4d86-9033-c9a33b7e1fc8` (control) and
`442c036c-bbce-4a5e-bcc2-71bc43d10d10` (fundamental). The fundamental layer
reduced exposure and drawdown but selected trades with worse average expectancy.
The current Asia/London entry hypothesis is therefore rejected; no parameter
search should be used to relabel it as an edge.

## Superseded short-sample checkpoint

The observed IC Markets dataset currently contains 99,489 completed XAUUSD
one-minute bars from 2026-04-13 14:05 UTC through 2026-07-23 08:15 UTC. The common
research interval begins on 2026-04-18 so the first decision has warm-up history.
This is a useful falsification sample, not a representative multi-regime dataset.

The longer interval overturned the attractive first-month result:

| Candidate | Trades | Expectancy | Profit factor | Net PnL | Max DD | Bootstrap 95% interval |
|---|---:|---:|---:|---:|---:|---:|
| price-only control, 1.5 ATR / 2.0R | 38 | -0.202 R | 0.715 | -744.37 USD | 12.65% | [-0.599, +0.269] R |
| V2 gate, 1.5 ATR / 2.0R | 18 | -0.070 R | 0.901 | -120.70 USD | 6.29% | [-0.736, +0.599] R |
| provisional V2, 2.0 ATR / 1.25R | 18 | +0.322 R | 1.735 | +549.78 USD | 3.94% | [-0.181, +0.822] R |

The control run is `576dbb20-685f-420e-bc1d-3aa349e4c983`, the default V2 run is
`f257b985-c245-44d1-bfbf-728a33b35ddb`, and the provisional parameter run is
`46103443-8d74-4ad8-8a99-2f5250aaef69`.

The gate rejected 20 of 38 mechanical candidates. On the control-sized matched
candidate ledger, rejected setups lost 601.44 USD while permitted setups lost
142.93 USD. All six rejected short candidates were losers. This is evidence that
the macro permission layer filters harmful trades in this sample; it is not
evidence that the surviving entry/exit rule has durable positive expectancy.

The exit sensitivity is not a single isolated cell: at a 1.5-ATR stop, targets from
1.0R through 1.5R were positive, and at a 1.25R target, stops from 1.25 through
3.0 ATR were broadly positive. The 2.0-ATR / 1.25R point is the centre of that
research region, not a promoted default. It was selected after inspecting the same
small sample, contains only 18 trades, and both expectancy intervals cross zero.
Its deterministic trade-order Monte Carlo reports 4.29% 95th-percentile drawdown,
but that reshuffle does not preserve regime clustering.

The candidate remained positive under the predeclared transaction-cost stress:
at 1.5x costs it returned +502.31 USD, +0.296 R expectancy, and 1.654 profit factor;
at 2.0x costs it returned +454.84 USD, +0.270 R, and 1.578 profit factor. Removing
the single best trade left +426.20 USD and +0.272 R; removing the two best left
+303.62 USD and +0.213 R. These are useful dependence checks, but they reuse the
same observations and do not convert the result into out-of-sample evidence.

All 18 permitted trades were shorts, historical catalyst schedules did not cover
the interval, and licensed consensus and Fed-path history remain absent. The
candidate therefore stays `RESEARCH / INSUFFICIENT EVIDENCE`.

The short-only result is a direct consequence of the symmetric gate, not a
hard-coded short strategy:

- the price trigger produced 24 short and 14 long candidates;
- 18 shorts had a score at or below -5 and were permitted (average -14.205);
- 6 shorts were rejected because their scores were above -5 (average +1.157);
- all 14 longs were rejected because none reached +5 (average -10.102, maximum
  +3.005); and
- most permitted observations were classified `OVERHEATING`.

This is directional and regime concentration. It does not show that shorts possess
a universal edge, and the system must not weaken the long threshold merely to force
symmetry. A confirmed edge requires an untouched holdout, materially more trades,
multiple regimes, both directions, and an expectancy interval excluding zero.

## Immediate research order

1. Keep Candidate A rejected and do not optimize its exit parameters further.
2. Use the loaded real release-boundary consensus, event, XAUUSD, COT, vintage
   macro, and Atlanta Fed MPT data to discover post-event reaction hypotheses.
3. Specify Candidate B before testing: surprise threshold, pre-event state,
   acceptance clock, invalidation, exit, and cost assumptions.
4. Freeze development, validation, and locked-holdout periods before calculating
   Candidate B performance.
5. Compare price-only, surprise-only, macro-direction, and full-gate ablations over
   identical observations and at 1.0x, 1.5x, and 2.0x costs.
6. Add licensed intraday yield/USD confirmation before claiming that a result
   validates the complete cross-market reaction chain from the reference book.
7. Promote no parameter set until walk-forward and the one-shot locked holdout pass.
