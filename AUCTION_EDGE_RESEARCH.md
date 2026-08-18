# Auction, Liquidity, and Fundamental-Bias Edge Research

## Decision

Current status: **RESEARCH / NO DEPLOYABLE EDGE / PAPER ONLY**.

Calendar 2025 remains the locked holdout. The accepted result set uses an
exclusive `2025-01-01T00:00:00Z` database boundary. Earlier research loaders
requested a harmless post-end buffer, but no post-end row entered a feature,
signal, trade, model, or metric. The loaders are now hard-capped at the declared
exclusive end, and the strict reruns produced identical pre-2025 counts.

No candidate or portfolio tested here justifies live risk. In particular, none
supports an expectation of 10R per calendar month, which is the approximate
hurdle for averaging 1,000 USD per month on a 10,000 USD reference account at
1% risk per trade.

## Book contract

The Reference Book remains the business specification:

```text
point-in-time regime, expectations, positioning, and catalyst state
-> active session and liquidity window
-> acceptance, retest, rejection, or failed auction at a known level
-> contemporaneous cross-market confirmation or contradiction
-> next-bar trigger
-> structural invalidation
-> sized risk and costed execution
```

Bias never creates an entry by itself. Every historical state uses only
evidence available by the signal timestamp. Observed, calculated, inferred, and
unknown facts remain distinct.

## Frozen research slices

| Slice | Role |
|---|---|
| 2021-08-01 through 2022-12-31 | discovery and candidate selection |
| calendar 2023 | validation |
| calendar 2024 | development-forward check |
| calendar 2025 | locked holdout; not evaluated |

All execution results use observed IC Markets XAUUSD minute bars. Signals are
formed only after a completed five-minute bar and enter at the next one-minute
open. A stop is placed beyond the last three or five completed one-minute bars.
When stop and target occur inside one minute, the stop is assumed first.
Friction is observed entry and exit spread, 0.05 USD/oz adverse slippage per
side, and 7 USD/lot round-turn commission. Every discovery candidate is also
tested at 1.50 times those costs.

## Where gold actually moves

The pre-2025 ledger contains 826 complete sessions and 5,263 complete auction
window/day observations.

| Window | Median post-window range | Broke prior range | Closed outside prior range | Continued pre-window direction |
|---|---:|---:|---:|---:|
| London open | 2.77 USD | 86.79% | 45.22% | 49.49% |
| LBMA AM | 4.55 USD | 87.33% | 46.12% | 47.09% |
| COMEX open | 3.80 USD | 84.82% | 47.37% | 50.57% |
| US data window | 3.79 USD | 87.44% | 46.69% | 47.94% |
| LBMA PM | 5.35 USD | 92.48% | 55.92% | 49.83% |
| COMEX settlement | 6.11 USD | 75.65% | 39.59% | 52.05% |

This confirms abundant daily opportunity. It does **not** establish directional
edge: raw continuation is approximately a coin flip, while a range breach often
fails to become accepted value.

## Price-state and one-minute execution results

The generic session state-transition ledger generated 4,361 signals and tested
126 predeclared archetype/context/manager hypotheses. Zero qualified on
discovery. Its best discovery result, handover confirmation with elevated
volume and a 1.50R target, returned +0.129R over 66 trades, but failed in 2023
at -0.165R expectancy and a 0.739 profit factor.

The auction-specific ledger generated 7,564 triggers. Five-minute execution
selected no candidate. One-minute structural stops produced 53,988 fully costed
outcomes and 864 hypotheses, again with zero selection.

The strongest development lead was:

```text
COMEX settlement
-> accepted break
-> prior-window direction opposed the break
-> three-minute structural stop
-> fixed 2R target
```

| Slice | Trades | Net expectancy | Profit factor |
|---|---:|---:|---:|
| discovery | 18 | +0.393R | 2.057 |
| 2023 | 9 | +0.621R | 2.706 |
| 2024 | 13 | +0.175R | 1.283 |

The pattern is too sparse and its discovery confidence interval includes zero.
It accumulated only about 14.9R across 41 calendar months, approximately
0.36R/month before portfolio overlap. It is a paper-research building block,
not the requested commercial edge.

## Transparent auction-bias result

A deterministic depth-2 tree was fitted separately for each auction window
using only discovery data. It used price location, range, volume, spread,
completed gold momentum, and completed EURUSD momentum. Minimum leaf support was
60, minimum Gini gain was 0.005, and a leaf required at least 55% directional
probability. This was an interpretable rule generator, not an opaque trading
model.

Only COMEX settlement retained a modest directional tendency in both later
years:

| Slice | Predictions | Directional accuracy | Average net close return |
|---|---:|---:|---:|
| discovery | 297 | 60.94% | +0.621 USD |
| 2023 | 220 | 56.82% | +0.175 USD |
| 2024 | 221 | 55.20% | +0.086 USD |

Applying those frozen bias permissions to one-minute auction entries left
2,387 aligned signals and 17,784 managed outcomes. No execution candidate
qualified. The best candidate with at least 40 discovery trades returned
+0.099R in discovery and then -0.400R in 2023. The directional tendency is not
yet an executable edge.

## Exact fundamental permission result

The point-in-time evaluator switched among inflation, growth/labour,
financial-stress, and mixed reaction functions. Its evidence included real
yields, 2-year yields, broad USD, inflation and labour vintages, growth,
financial-stress proxies, COT, and post-release surprises. Average evidence
coverage rose from about 75% in 2021-2022 to 94.9% in 2024.

Historical pre-release schedule snapshots are not available, so pre-event risk
is correctly `UNKNOWN`; the engine does not pretend a later-known schedule was
known earlier. Released event surprises remain point-in-time eligible.

The exact book-aligned auction execution run contained:

- 7,564 auction-state triggers;
- 53,988 costed one-minute outcomes;
- 8,998 unique micro-stop decision states;
- 2,160 predeclared fundamental-rule/trigger/manager hypotheses; and
- zero discovery-selected candidates.

The best adequately sampled discovery lead was LBMA AM failed-auction,
five-minute structural invalidation, macro score at least +10 in trade
direction, and a 3R target:

| Slice | Trades | Net expectancy | Profit factor |
|---|---:|---:|---:|
| discovery | 46 | +0.161R | 1.300 |
| 2023 | 22 | -0.398R | 0.451 |
| 2024 | 15 | -0.723R | 0.149 |

The discovery interval was `[-0.257R, +0.601R]`, and both later slices failed.
Fundamentals as a slow/static permission layer therefore did not rescue the
current entry families.

## Exact post-event reaction result

A separate release-clock study grouped 742 eligible surprise components into
191 real event sets. It required the surprise to be available at release,
formed a weighted gold-direction composite, measured one-minute XAUUSD and
EURUSD from the exact release timestamp, waited for acceptance, retest,
continuation, reversal, dual confirmation, or USD-led gold catch-up, and then
charged the same execution friction.

Only 62 strict signals formed across the six predeclared playbooks, and zero
passed discovery selection.

| Playbook | Discovery trades / expectancy | 2023 expectancy | 2024 expectancy | All-period expectancy |
|---|---:|---:|---:|---:|
| 5m event acceptance | 2 / +0.445R | -0.446R | no trades | -0.001R |
| accepted retest | 0 / n/a | -1.279R | +1.787R (1 trade) | +0.254R (2 trades) |
| continuation breakout | 6 / -0.343R | +0.363R | -1.136R | -0.210R |
| first-move reversal | 5 / -0.215R | -1.256R | +0.051R | -0.531R |
| gold + EURUSD confirmation | 10 / -0.358R | -0.349R | -1.378R | -0.475R |
| EURUSD-led gold catch-up | 2 / +0.071R | -0.701R | +0.091R | -0.273R |

The result does not support trading every macro surprise, the first spike, or
EURUSD confirmation alone. Intraday Treasury confirmation was unavailable and
remains `UNKNOWN`; daily yields were not substituted into the release window.

## What this falsifies

The evidence rejects these claims:

1. frequent movement alone implies a capturable daily edge;
2. an Asian or pre-window range break should be traded mechanically;
3. a daily fundamental score is sufficient directional timing for intraday
   gold;
4. a 55%-60% directional auction classifier automatically produces profitable
   stop/target execution; and
5. sparse positive results can be scaled to 10R/month safely.

It does not reject the Reference Book. It narrows the missing mechanism to
contemporaneous reaction and confirmation: how gold, USD, rates, silver, and
risk assets respond at the active catalyst or auction, followed by price
acceptance.

## Cross-market confirmation result

The connected IC Markets catalogue supplied real XAGUSD and US500 history. The
broker's TLT.NAS history supplied an observed long-duration Treasury ETF price,
which the research contract labels as an **inferred inverse nominal-yield
proxy**, never an observed Treasury yield. The pre-2025 run used 255,140
complete EURUSD, 242,046 XAGUSD, 236,527 US500, and 65,376 TLT five-minute
buckets.

The frozen cross-market run retained the same 7,564 auction triggers and 53,988
costed one-minute outcomes, then tested 1,440 fixed USD, silver, TLT, breadth,
risk-on, and defensive-gold hypotheses. Zero qualified.

The best adequately sampled discovery lead was LBMA AM acceptance, a
three-minute structural stop, two-of-three four-hour breadth, and a fixed 2R
target:

| Slice | Trades | Net expectancy | Profit factor | Average R/month |
|---|---:|---:|---:|---:|
| discovery | 51 | +0.110R | 1.185 | +0.329R |
| 2023 | 24 | -0.477R | 0.427 | -1.034R |
| 2024 | 28 | +0.068R | 1.116 | +0.159R |

Its discovery interval was `[-0.262R, +0.502R]`. Cross-market momentum helped
describe some moves, but it did not create a stable permission rule.

## Objective liquidity-level result

A separate minute-level state machine tested only levels known before the
decision: Asian high/low, rolling prior-24-hour high/low, and the
London-to-New-York handover range. It distinguished fast rejection, accepted
retest, handover confirmation, and handover rejection; entered only after a
completed one-minute displacement; and kept structural stops, next-minute
fills, fixed 1.5R/2R/3R targets, real costs, and 1.50-times cost stress.

The broad multilevel delayed-reclaim precursor generated 445 signals. Its
442-trade price control returned `-0.089R` expectancy and a `0.835` profit
factor. The 218-trade broad-USD-aligned cohort returned `-0.118R`, with negative
expectancy in every calendar year. Every declared target/holding neighbourhood
and both cost stresses were negative.

The stricter liquidity state machine produced 744 unique signals and 4,464
managed outcomes. V0.1 and V0.2 selected nothing. V0.3 added only the
real-yield permissions justified by the independent target-validity diagnostic;
it evaluated 924 hypotheses and again selected zero.

Its strongest adequately sampled discovery row was New York confirmation of an
Asian-range break with estimated cost at most 0.20R and a fixed 2R target:

| Slice | Trades | Net expectancy | Profit factor | Average R/month |
|---|---:|---:|---:|---:|
| discovery | 45 | +0.268R | 1.441 | +0.710R |
| 2023 | 14 | -0.933R | 0.125 | -1.088R |
| 2024 | 40 | -0.186R | 0.758 | -0.619R |

The result is regime-instability, not a deployable edge. Adding Asian
compression, sweep depth, level confluence, macro agreement/conflict,
real-yield agreement, EURUSD, or silver did not repair it.

## Fundamental target-validity result

The point-in-time fundamental state was frozen at each DST-aware London
decision clock and tested against five distinct targets: London close,
New-York close from London open, larger London excursion, first Asian-range
break, and London close outside Asia. This was a diagnostic with no fill,
stop, target, or P&L.

The cleanest recurring relationship was real-yield direction versus the side
of the larger London excursion:

| Calendar year | Observations | Directional accuracy |
|---|---:|---:|
| 2021 | 89 | 51.69% |
| 2022 | 245 | 55.51% |
| 2023 | 224 | 56.25% |
| 2024 | 235 | 53.62% |

Every annual confidence interval still included zero edge. Overall score,
dominant driver, USD, 2-year yield, event surprise, and positioning were less
stable across the five targets. The conclusion is precise: the current
slow/daily fundamental state is a weak prior, not a London-open timing signal.

## Transparent walk-forward result

Two transparent ridge models then tested whether interactions missed by
one-factor rules mattered. Both refit only at month boundaries from earlier
completed months, exposed every coefficient and per-prediction contribution,
and excluded calendar 2025.

The first model predicted the side of the larger London excursion from 25
point-in-time macro, Asia, gold, EURUSD, silver, prior-session, and weekday
features. It produced 696 genuinely walk-forward predictions:

| Calendar year | Predictions | Accuracy | Mean excursion advantage |
|---|---:|---:|---:|
| 2022 | 211 | 54.98% | +0.475 five-minute ATR |
| 2023 | 234 | 48.29% | +0.209 five-minute ATR |
| 2024 | 251 | 54.58% | +0.632 five-minute ATR |

The all-period accuracy was 52.59% with a Wilson interval of
`[48.87%, 56.27%]`. Higher model confidence did not improve stability. This is
not a reliable directional engine.

The second model predicted realized net R for the already-confirmed liquidity
signals using one fixed 2R manager. It produced 586 walk-forward predictions,
then applied one-position overlap control and a -2R realized daily stop. The
best declared threshold (`predicted net R >= 0.10`) accepted 150 trades:

| Calendar year | Trades | Net expectancy | Profit factor | 1.50x-cost expectancy |
|---|---:|---:|---:|---:|
| 2022 | 58 | -0.077R | 0.896 | -0.159R |
| 2023 | 46 | +0.073R | 1.108 | -0.010R |
| 2024 | 46 | -0.055R | 0.923 | -0.128R |
| all pre-2025 | 150 | -0.024R | 0.966 | -0.104R |

The model's prediction/realization correlation was only `0.104`. It filtered
much of the mechanical loss but did not manufacture positive expectancy.

## Exchange rates and policy-futures result

The missing intraday rates evidence was subsequently acquired rather than
approximated. Databento job `GLBX-20260728-3SHU3737P8` supplied 3,083,147
pre-2025 one-minute CME records for volume-led ZT, ZN, ZQ, and SR3 continuous
contracts. Contract identity is retained and returns crossing a roll are
unknown. No 2025 row entered research.

Four increasingly direct tests did not establish a frequent executable rates
edge:

| Test | Signals / executions | Hypotheses | Discovery-selected |
|---|---:|---:|---:|
| rates/policy permissions on liquidity states | 744 / 5,952 | 312 | 0 |
| rates-guided session breakouts | 1,872 / 14,976 | 160 | 0 |
| direct ZT/ZN lead execution | 14,051 / 112,136 | 48 | 0 |
| post-event rates aftershock | 298 / 2,376 | 96 | 1 |

The frequent direct rates-lead branch's best discovery rule already lost
`-0.072R` per trade, followed by `-0.186R` in 2023 and `-0.124R` in 2024.
The one event-aftershock candidate was sparse and unstable: its accepted
portfolio averaged `+1.599R/month` in discovery, `+0.296R/month` in 2023, and
`-0.331R/month` in 2024. Across all pre-2025 months it averaged
`+0.653R/month`, had a negative median month, and failed the annual and 10R
gates.

The target-validity diagnostic found only a tiny gross relationship after large
ZT/ZN shocks. It was not strong enough to survive structural entries and real
friction. Intraday rates are therefore present; their earlier absence is no
longer the explanation for the failed strategy.

## Broader market and structure search

A cost-aware opening-range screen expanded the study to real XAUUSD, XAGUSD,
EURUSD, and US500 histories. London, COMEX, and New-York cash sessions were
DST-aware. Stops were widened to at least 0.75 ATR and far enough to cap
estimated friction at 0.15R; stops above 2.50 ATR were rejected.

That run produced 4,046 signals, 32,368 executions, and 792 fixed hypotheses.
Zero qualified.

A separate screen tested four explicit structure families: completed six-hour
Donchian breaks, failed Donchian breaks, one-hour compression releases, and
two-hour extension rejections. It produced 4,401 signals, 34,968 executions,
and 576 hypotheses. One EURUSD compression/4R candidate passed discovery:

| Slice | Trades | Expectancy | Average R/month |
|---|---:|---:|---:|
| discovery | 63 | +0.483R | +1.791R |
| 2023 | 42 | -0.142R | -0.497R |
| 2024 | 30 | +0.081R | +0.203R |
| all pre-2025 | 135 | +0.199R | +0.657R |

It failed the first validation year and the target by a wide margin. A
month-by-month transparent ridge manager then generated 3,882 walk-forward
predictions. Prediction/realization correlation was `0.0039`; the highest
predicted quintile actually realized `-0.161R` per signal. No calendar-2022
threshold qualified.

## Frozen cross-instrument transfer

To distinguish a real structural mechanism from an instrument-specific
coincidence, four configurations were frozen before six new histories were
evaluated:

- Donchian breakout + relative volume + fixed 3R;
- failed Donchian + relative volume + fixed 3R;
- compression + aligned four-hour trend + fixed 4R; and
- compression + volatility expansion + fixed 2R.

The untouched transfer set contained 7,595,984 observed IC Markets minutes for
AUDUSD, GBPUSD, USDJPY, USTEC, DE40, and XTIUSD, all ending before 2025. Natural
liquid sessions, point sizes, commissions, observed spreads, slippage,
1.50-times friction, cluster exposure, and account capacity were declared
before the results were read.

The transfer generated 7,477 signals and 59,504 costed executions. Every
mechanism was negative overall and every new instrument was negative overall.

| Frozen mechanism | Trades | Expectancy | Average R/month |
|---|---:|---:|---:|
| compression + 240-minute trend, 4R | 431 | -0.108R | -1.138R |
| compression + volatility expansion, 2R | 407 | -0.044R | -0.432R |
| Donchian + relative volume, 3R | 369 | -0.172R | -1.544R |
| failed Donchian + relative volume, 3R | 610 | -0.168R | -2.501R |

The fixed six-market account portfolio was negative in every development
period:

| Slice | Trades | Expectancy | Profit factor | Average R/month |
|---|---:|---:|---:|---:|
| discovery | 608 | -0.134R | 0.807 | -4.783R |
| 2023 | 392 | -0.120R | 0.822 | -3.923R |
| 2024 | 376 | -0.116R | 0.830 | -3.627R |
| all pre-2025 | 1,376 | -0.125R | 0.818 | -4.193R |

The already-frozen ten-market portfolio combined the four source instruments
with all six transfer instruments. It remained negative: 2,042 trades,
`-0.081R` expectancy, a `0.881` profit factor, `-4.021R/month`, and
`195.09R` maximum drawdown before compounding. Its maximum pairwise accepted
daily-return correlation was only `0.062`, so diversification was not the
failure. The signals had negative expectancy.

## Point-in-time fair-value dislocation result

The final predeclared diagnostic tested a different mechanism rather than
another chart-pattern permutation. A transparent ridge model was refit once per
day on only the prior 60 calendar days. It estimated the completed five-minute
gold move from simultaneous completed EURUSD, silver, US500, ZT, and ZN moves.
The current day never entered its own fit. It then tested:

- gold lagging a strong fair-value move;
- gold and fair value already confirming; and
- reversion of an unusually large gold/fair-value residual.

The model processed 92,857 synchronized observations and produced 91,779
walk-forward predictions. Its contemporaneous prediction/gold correlation was
stable—`0.765` in discovery, `0.744` in 2023, and `0.730` in 2024—so it
described the current move well. Description did not become a stable forecast:

| State / horizon | Discovery | 2023 | 2024 | All-period 95% interval |
|---|---:|---:|---:|---:|
| fair-value confirmation, 15m | +0.002 ATR | -0.023 ATR | +0.025 ATR | [-0.021, +0.025] |
| lag catch-up, 15m | +0.071 ATR | -0.006 ATR | -0.029 ATR | [-0.061, +0.091] |
| residual reversion, 15m | +0.102 ATR | +0.020 ATR | -0.006 ATR | [+0.012, +0.082] |
| residual reversion, 30m | +0.123 ATR | +0.027 ATR | -0.010 ATR | [+0.005, +0.104] |
| residual reversion, 60m | +0.095 ATR | -0.009 ATR | -0.006 ATR | [-0.036, +0.109] |

The large sample detects a small historical residual-reversion average at
15-30 minutes, but the effect decayed to slightly negative in the untouched
2024 development slice. No state/horizon relationship met the rule requiring
positive discovery, 2023, and 2024 performance plus a positive all-period
bootstrap lower bound. Per the frozen research contract, no stop/target search
was allowed after target validity failed.

## Research boundary

No stable 10R candidate exists from which to construct a legitimate portfolio.
This conclusion now includes real intraday rates/policy futures, ten real
broker markets, cross-instrument transfer, and a point-in-time cross-market
fair-value model. Consequently:

1. calendar 2025 remains unopened;
2. no strategy from this branch is integrated as a live or paper signal;
3. no risk increase is used to force the requested dollar return;
4. the observed session range remains an opportunity statistic, not P&L;
5. the small residual-reversion relationship remains a descriptive research
   clue, not an executable edge; and
6. a future independent dataset or later untouched time period is required to
   validate a materially new mechanism. Recombining the same pre-2025 samples
   would be parameter mining.

At 1% account risk, the requested average is approximately 10R/month. The best
discovery-only structure candidate reached `+1.79R/month` before failing 2023.
The six-market transfer lost `-4.19R/month`, and the frozen ten-market book lost
`-4.02R/month`. The gap is evidence, not a sizing problem.

## Local evidence hashes

The original reports remain under `C:\tmp`; the expanded research reports are
under the gitignored `data/raw/research_results/` directory. Their SHA-256
hashes make accidental replacement detectable:

| Report | SHA-256 |
|---|---|
| cross-market auction/micro | `D7EDC4705A41EDDF8D0B69D6164847CD3CA577801A994BB55AC2D4CE9089F66F` |
| multilevel delayed reclaim | `827C80AE33B2267C84F821FC5DE93FF258D69A84E31DB2470FBEED9A87B0F57C` |
| liquidity state machine V0.3 | `CA52EEB9C21CF51646C516B4CC4D628C0B16ACE9592FEFDFBC66B6DBE3E4746F` |
| fundamental target validity | `1AF1668EE50A5BC9ECC0055AA10B0C9B2CBFE2D674F382ACF2B598249A2BEE86` |
| walk-forward session bias | `C1538CA00FF5507AFF85236EC3E79F45A87EDA3175326338ED23B2D0F73B8F14` |
| walk-forward liquidity execution | `0DB51950958A7821A31E29EB96A62D3AF591A92B1F39AD39C5021A8C83216E9D` |
| direct rates-lead execution | `6ED565D15C8216BA1DA022D22CF43D6E8DE2739E19F8748E1BEB492BEBD9B8EF` |
| event/rates aftershock | `A8E13AFCDE75BF54820F716B9DC66BDA0C820A379DC998A9707FBAA87CF6FBC8` |
| cost-aware four-market sessions | `27546B5383A1AE8E0852E3E1565BB30CDCF7F9D8BDBA87BD4CCF89699E6E0F61` |
| structure/trend screen | `A68CFF12379FA39F8F361ABC9993E9080A7483182878DED6E6A45928F090382D` |
| structure walk-forward model | `EB508B1D9521AE1E98AE2B4D45EE4AE0D8C38FE69445F199F870A7183927E715` |
| six-market frozen transfer | `278653B29A62C5B5B17565CCE1C52E9BDCEDA5CA117B425CA655AA298C747090` |
| frozen ten-market portfolio | `D373F33C28CBAA814C38C08B5113BD96C6592B741C00F4359ADF4139E79C412C` |
| gold fair-value dislocation | `A1D9B700C574F08F8D13DA1534ED5ACEEE4B0F149C53F7D90CBD504080994AC6` |

## Reproduce the evidence

Run from the repository root:

```powershell
docker compose --profile test run --rm backend-test `
  python tools/research_gold_auction_windows.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm backend-test `
  python tools/research_one_minute_auction_execution.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm backend-test `
  python tools/research_interpretable_bias_micro_execution.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm backend-test `
  python tools/research_fundamental_auction_micro_execution.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm backend-test `
  python tools/research_post_event_playbooks.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm --no-deps `
  -v C:\tmp:/host-tmp backend-test `
  python tools/research_cross_market_auction_micro_execution.py `
  --start 2021-08-01 --end 2025-01-01 `
  --xagusd-csv-dir /host-tmp/gold_xagusd_pre2025 `
  --us500-csv-dir /host-tmp/gold_us500_pre2025 `
  --tlt-csv-dir /host-tmp/gold_tlt_pre2025

docker compose --profile test run --rm --no-deps backend-test `
  python tools/research_multilevel_delayed_reclaim.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm --no-deps backend-test `
  python tools/research_liquidity_level_state_machine.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm --no-deps backend-test `
  python tools/research_bias_target_validity.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm --no-deps backend-test `
  python tools/research_walk_forward_session_bias.py `
  --start 2021-08-01 --end 2025-01-01

docker compose --profile test run --rm --no-deps backend-test `
  python tools/research_walk_forward_liquidity_execution.py `
  --start 2021-08-01 --end 2025-01-01

docker compose run --rm --no-deps `
  -v C:\tmp:/host-tmp `
  -v "$($PWD.Path)\data\raw\research_results:/results" `
  backend-test python tools/research_cross_instrument_transfer.py `
  --start 2021-08-01 --end 2025-01-01 `
  --input AUDUSD=/host-tmp/gold_audusd_pre2025 `
  --input DE40=/host-tmp/gold_de40_pre2025 `
  --input GBPUSD=/host-tmp/gold_gbpusd_pre2025 `
  --input USDJPY=/host-tmp/gold_usdjpy_pre2025 `
  --input USTEC=/host-tmp/gold_ustec_pre2025 `
  --input XTIUSD=/host-tmp/gold_xtiusd_pre2025 `
  --cache-output /results/cross_instrument_transfer_context_v01.csv.gz `
  --output /results/cross_instrument_transfer_v01.json

docker compose run --rm --no-deps `
  -v "$($PWD.Path)\data\raw\research_results:/results" `
  backend-test python tools/research_frozen_ten_market_portfolio.py `
  --source-cache /results/multi_asset_trend_reversion_context_v01.csv.gz `
  --transfer-cache /results/cross_instrument_transfer_context_v01.csv.gz `
  --output /results/frozen_ten_market_portfolio_v01.json

docker compose run --rm `
  -v C:\tmp:/host-tmp `
  -v "$($PWD.Path)\data\raw\research_results:/results" `
  -v "$($PWD.Path)\data\raw\databento_cme_pre2025\GLBX-20260728-3SHU3737P8\normalized:/rates:ro" `
  backend-test python tools/research_gold_fair_value_dislocation.py `
  --rates-dir /rates `
  --us500-csv-dir /host-tmp/gold_us500_pre2025 `
  --start 2021-08-01 --end 2025-01-01 `
  --output /results/gold_fair_value_dislocation_v01.json
```

Every command rejects an end timestamp after `2025-01-01`. The cross-market
loader validates monotonic timestamps and complete five-minute buckets and
fails closed when a required observed history is absent.
