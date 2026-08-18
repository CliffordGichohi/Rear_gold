# Book-Aligned Gold Strategy Research Protocol

## Purpose

A “strong strategy” means a causal, point-in-time rule set that remains useful
outside the sample used to design it. It does not mean the most profitable
parameter combination on the currently loaded month. This protocol turns the
reference book into falsifiable hypotheses and defines the evidence required
before any strategy is promoted.

## Candidate A: regime-guided London acceptance

`BOOK_ALIGNED_ASIA_ACCEPTANCE_RESEARCH_V1` is the first complete research
candidate. Runtime version `1.5.0` separates four decisions.

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

Unknown catalyst risk and unknown broker liquidity also produce `WAIT` by default.
Research overrides are permitted only for explicitly labelled ablations and are
stored in the run provenance; they cannot be presented as strict book-aligned
evidence.

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

## Candidate C: fundamental-biased session liquidity delivery

The rejected Candidate A tested sustained breakout acceptance. It did not test
whether London first raids an Asian boundary and then rejects it. Candidate C
therefore starts a separate, predeclared research family rather than optimizing
Candidate A after failure.

Version `LONDON_SWEEP_RECLAIM_V0_1` implements Candidate C1:

```text
fundamental state frozen before London
-> complete Asian range and point-in-time reference levels
-> bounded trade beyond the Asian high or low
-> reclaim within two complete five-minute bars
-> directional displacement through pre-sweep micro structure
-> hypothetical next-complete-bar entry
-> structural invalidation beyond the excursion
-> 30/60/120/240-minute MFE, MAE, and target-before-stop paths
```

The fundamental state is a cohort and directional-permission feature; it does not
create the price trigger. Unknown catalyst risk remains `UNKNOWN` in the
opportunity study rather than deleting the session or being treated as safe.
Every requested London session receives a ledger row with an explicit funnel
status. This separates market opportunity from data completeness and from the
later decision to execute a trade.

The exact hypothesis, initial thresholds, reference-level hierarchy, research
partition, promotion boundary, persistence contract, and delivery milestones are
frozen in [SESSION_EDGE_RESEARCH.md](SESSION_EDGE_RESEARCH.md).

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

## Current evidence checkpoint — 27 July 2026

The observed IC Markets store now contains 1,771,271 completed XAUUSD one-minute
bars from 23 July 2021 through 27 July 2026. The canonical ruleset is
`gold-reference-book-7-layer-v1`; stable Phase 1 factor coverage is 69/80
(86.25%), full layered-book coverage is 69/95 (72.63%), and live usable coverage
is reported separately at each decision clock.

The untouched 1 April through 29 July 2023 interval contains 61 mechanical
candidates. Strategy v1.5 produced:

| Run | Trades | Expectancy | Profit factor | Net PnL | Max DD | Point-in-time status |
|---|---:|---:|---:|---:|---:|---|
| strict default | 0 | N/A | N/A | 0.00 USD | 0.00% | all 61 candidates correctly blocked because pre-release catalyst risk was `UNKNOWN` |
| catalyst-risk research override | 16 | -0.414617 R | 0.542568 | -649.48 USD | 11.333195% | ablation only; `allow_unknown_event_risk=true` |

The strict run is `fddda1a6-f5c2-432c-ae4b-ed9030ee2dbc`; the override is
`fd03a168-48e0-4f25-a9dd-c9bcfb6de956`. The override recorded 5 winners and still
lost after spread, slippage, and commission. Candidate A therefore remains
rejected. The strict result is also a data-availability finding: release-boundary
MT5 consensus is valid for post-release research, but cannot prove that the
schedule or consensus was knowable before a historical entry.

## Historical evidence checkpoint — 24 July 2026

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

All 18 permitted trades were shorts. The later MT5 import supplies real historical
releases and release-boundary consensus, but not a trustworthy first-known clock
for the pre-release schedule or forecast; exact meeting-level Fed-path history also
remains absent. The candidate therefore stays
`RESEARCH / INSUFFICIENT EVIDENCE`.

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

Candidate C1's all-session ledger and first observed-data discovery run are now
complete. Across 457 requested 2023-2024 London sessions, 430 were complete and
97 produced a sweep/reclaim/displacement trigger. The unconditional gross 1R path
proxy is +0.037 R with a bootstrap 95% interval of [-0.169, +0.229] R. This is
before transaction costs and is not an established edge.

Delayed reclaim is the only lead that stayed positive in both annual slices:
10 setups at +0.261 R in 2023 and 9 at +0.333 R in 2024. Its combined
19-observation result is +0.295 R with [-0.126, +0.684] R uncertainty, so it is
still insufficient. Fundamental-aligned setups returned -0.011 R and
fundamental-opposed setups -0.106 R. The current daily/static pre-London bias is
therefore not validated as the directional selector for this entry family.
`SESSION_EDGE_RESEARCH.md` contains the full frozen protocol, cohort table, run
IDs, and reproducibility hash.

The costed executable stage is now complete:

| Variant | Trades | Win rate | Net expectancy | Profit factor | Net PnL | Development gate |
|---|---:|---:|---:|---:|---:|---|
| delayed-reclaim price control | 19 | 63.16% | +0.164 R | 1.402 | +301.93 USD | PASS |
| delayed-reclaim fundamental aligned | 8 | 50.00% | -0.044 R | 0.904 | -37.23 USD | FAIL |

The control was positive in both annual slices, all nine declared
target/holding-period neighbourhood cells, and through 2.00x modeled costs.
However, its bootstrap interval remains [-0.255, +0.572] R and all catalyst
states are unverified. The primary failed the centre point, 2024, and cost stress.

The broader daily-session search is now complete through calendar 2024. It added
real IC Markets EURUSD history, extended FRED/ALFRED/COT history back far enough
for the 2021-2022 discovery block, and tested continuation, retest, rejection,
post-event, multilevel-reclaim, cross-market, trapped-breakout, session-carry,
opening-range, and adverse-auction families. `DAILY_SESSION_PLAYBOOK_RESEARCH.md`
contains the frozen contracts and full evidence checkpoint.

The apparent best blended result was P9 macro session carry at +36.51 R over 457
trades. It is rejected because discovery lost 52.02 R, 2023 lost 41.88 R, and the
entire gain came from +130.41 R in 2024. At 1% risk the full compounded path ended
below its 10,000 USD starting equity with 67.06% drawdown. Neither EURUSD
confirmation nor 1R/1.5R caps repaired it. No candidate was positive in all
development splits and no portfolio qualified.

The reaction-function and opportunity/label work is now complete. The
point-in-time diagnostic covered 826 London sessions and found only a weak
real-yield relationship with the side of the larger excursion; every annual
interval still included zero. A 25-feature transparent monthly walk-forward
model produced 696 predictions and only 52.59% all-period directional accuracy.

The final execution-level check predicted net R for 744 objective
liquidity-state signals using one fixed 2R manager. The least-bad declared
threshold accepted 150 non-overlapping trades and returned -0.024R expectancy
before stress and -0.104R at 1.50-times costs. It lost in 2022 and 2024, and no
threshold qualified. Exact annual results and reproduction commands are in
`AUCTION_EDGE_RESEARCH.md`.

The previously missing intraday Treasury/policy evidence has now been acquired:
3,083,147 pre-2025 CME ZT, ZN, ZQ, and SR3 minutes with roll identity retained.
Direct rates-led execution tested 14,051 signals and 112,136 outcomes; none of
48 candidates qualified. A broader four-market structure search found one
discovery candidate, but it lost in 2023.

Four configurations were then frozen and transferred unchanged to 7,595,984
minutes of previously untested AUDUSD, GBPUSD, USDJPY, USTEC, DE40, and XTIUSD
history. Every configuration and every instrument was negative overall. The
six-market transfer lost `-4.19R/month`; the frozen ten-market portfolio lost
`-4.02R/month`.

A final point-in-time gold fair-value diagnostic refit a transparent model daily
from prior-only EURUSD, silver, US500, ZT, and ZN observations. It produced
91,779 walk-forward predictions. Residual reversion was positive in discovery
and 2023 but decayed to slightly negative in 2024; no predeclared state/horizon
relationship passed target validity. A costed stop/target search was therefore
not authorized.

The immediate order is therefore:

1. Keep Candidate A, C1, P1-P11, delayed reclaim, auction, cross-market,
   liquidity-level, rates-led, multi-asset transfer, and fair-value variants
   rejected for live risk.
2. Preserve them as falsification and regression benchmarks; do not retune them
   against the same 2021-2024 outcomes.
3. Keep calendar year 2025 locked because no pre-holdout portfolio qualified.
4. Treat intraday ZT/ZN/ZQ/SR3 as a completed negative research branch, not as
   a reason to re-open rejected entries with new thresholds.
5. Obtain independent point-in-time pre-release consensus and schedule
   snapshots; never
   backfill a pre-event state from a later calendar.
6. Run the current engine prospectively in observation-only paper mode so later
   observations form a genuinely untouched forward sample.
7. Promote no strategy until cost stress, parameter stability, multiple regimes,
   and a genuine locked holdout pass. The current state remains
   `RESEARCH / NO DEPLOYABLE EDGE / PAPER ONLY`.
