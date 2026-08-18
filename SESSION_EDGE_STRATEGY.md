# Candidate C1 Delayed-Reclaim Executable Strategy

## 1. Frozen decision

This document freezes the first executable strategy derived from the observational
protocol in `SESSION_EDGE_RESEARCH.md`. It was written before the Candidate C1
calendar-year 2025 opportunity ledger or strategy result was calculated.

The frozen candidate version is:

```text
C1_DELAYED_RECLAIM_EXECUTION_V1
```

It consumes opportunities produced by:

```text
LONDON_SWEEP_RECLAIM_V0_1
```

The discovery evidence used to select this candidate is limited to 1 April 2023
through 31 December 2024. The delayed-reclaim cohort contained 19 observations,
was positive in each annual slice, and remained statistically inconclusive. The
purpose of this strategy stage is to determine whether that lead survives an
executable fill, cost, exit, and risk contract. It is not a declaration of an
edge.

## 2. Predeclared variants

Two variants are evaluated over identical source opportunity ledgers:

| Variant | Role | Directional permission |
|---|---|---|
| `DELAYED_RECLAIM_PRICE_CONTROL` | Mechanical benchmark only | No fundamental gate |
| `DELAYED_RECLAIM_FUNDAMENTAL_ALIGNED` | Primary book-aligned candidate | `bias_alignment == ALIGNED` at the pre-London freeze |

The control cannot be promoted as the intended book-aligned strategy. The primary
candidate asks whether causal permission adds value to the same mechanical setup.
Results will not be used to choose whichever variant happens to perform better on
the validation period.

Historical catalyst status is currently `UNKNOWN`. The run may retain these
sessions for research, but it must disclose `CATALYST_UNVERIFIED` and cannot be
described as a production-ready event-risk strategy. Unknown is never relabelled
as low risk.

## 3. Eligibility and entry

A source opportunity is eligible only when:

1. it was created by the exact detector version above;
2. its session and four-hour outcome path are complete;
3. its primary qualified attempt produced a setup side, signal, entry reference,
   structural invalidation, and positive risk distance;
4. the reclaim completed after the sweep bar rather than in the sweep bar;
5. the next five-minute bar begins exactly at the displacement bar close;
6. every required one-minute price record is the earliest point-in-time eligible
   version and is complete;
7. observed broker spread is available at entry and exit; and
8. for the primary variant, the frozen fundamental state is aligned and has
   already satisfied the detector's score, coverage, and confidence thresholds.

The order is a research market order at the open of the next complete five-minute
bar after displacement. The stored XAUUSD reference is treated as a mid/reference
path for deterministic simulation. Execution cost applies the observed entry and
exit broker spread plus adverse slippage; the engine does not improve fills.

No compression, volume-expansion, spread-percentile, confluence, regime, or
direction gate is added. Discovery did not establish a stable incremental edge
for those filters. Adding them now would be unrecorded optimization.

## 4. Invalidation, target, and exit

| Item | Frozen rule |
|---|---|
| Logical stop | Sweep extreme plus the detector's 0.10 ATR structural buffer |
| Target | `1.00R` from the reference entry |
| Maximum holding period | 240 minutes from entry |
| Bar resolution | Earliest complete one-minute versions |
| Same-minute stop and target | Stop first |
| Time exit | Last complete reference close at or before the 240-minute boundary |
| Missing path | Exclude with an explicit reason; never forward-fill |
| Overlap | At most one primary setup per London session |

Stops and targets are evaluated against the reference path. Entry and exit costs
are then deducted, so a stopped trade can lose more than `-1.00R` net and a target
trade earns less than `+1.00R` net. This makes cost visibility explicit.

## 5. Cost and risk contract

| Parameter | Frozen value |
|---|---:|
| Initial equity | 10,000 USD |
| Planned risk per trade | 1.00% of current equity |
| XAUUSD contract size | 100 ounces per lot |
| Minimum / step | 0.01 / 0.01 lot |
| Maximum position | 10.00 lots |
| Entry spread | Observed broker spread at entry |
| Exit spread | Observed broker spread at exit |
| Slippage | 0.05 USD/oz per side |
| Commission | 7.00 USD per lot round turn |
| Base cost multiplier | 1.00x |

Position size is rounded down to the broker lot step:

```text
planned risk USD = current equity * 1%
raw lots = planned risk USD / (risk distance * contract size)
filled lots = floor(raw lots / lot step) * lot step
```

The research report also calculates 1.50x and 2.00x cost stress without changing
the signal, stop, target, or time exit.

## 6. Development checks

The frozen centre point is `1.00R / 240 minutes`. A declared neighbourhood is
reported to diagnose fragility, not to select a new winner:

- target: `0.75R`, `1.00R`, `1.25R`;
- maximum hold: `180`, `240`, `300` minutes; and
- cost multiplier: `1.00x`, `1.50x`, `2.00x`.

The centre point remains the candidate regardless of which neighbouring cell is
best. A candidate that is positive only in the selected cell fails the stability
test.

Development continuation requires:

1. positive net expectancy at the centre point;
2. positive net expectancy in both the 2023 and 2024 slices;
3. positive net expectancy at 1.50x costs;
4. no single trade contributing more than half of total net profit; and
5. an economically coherent result that is not solely one direction or one
   regime.

If the primary fundamental-aligned candidate fails these development hurdles,
calendar year 2025 remains locked for a future materially improved bias contract.
There is no scientific value in consuming a holdout for a candidate already
rejected in development.

## 7. Locked validation and promotion

If and only if the primary passes the development continuation gate, its exact
version and configuration hash are recorded before running calendar year 2025
once.

Validation evidence must report:

- observation and trade counts;
- gross and net expectancy in R;
- win rate, profit factor, and total costs;
- maximum drawdown;
- bootstrap confidence interval;
- annual, direction, regime, and driver concentration;
- 1.50x and 2.00x cost stress; and
- the complete opportunity/trade exclusion funnel.

Positive 2025 expectancy is necessary but not sufficient. Fewer than 30 genuinely
out-of-sample trades, a confidence interval crossing zero, or heavy concentration
leaves the result `INSUFFICIENT EVIDENCE`. A negative centre-point validation
rejects this candidate version. Validation parameters are never retuned.

## 8. Audit boundary

Every run must retain:

- source study run IDs and hashes;
- immutable opportunity IDs and hashes;
- strategy configuration and SHA-256 hash;
- exact bar record keys or a deterministic source-data hash;
- entry, exit, stop, target, quantity, gross PnL, each cost component, and net PnL;
- eligibility/exclusion reason for every triggered opportunity; and
- code versions for the detector, evaluator, metric summary, and bootstrap seed.

The output label remains:

```text
RESEARCH / EDGE NOT YET ESTABLISHED
```

until the full promotion contract is satisfied.

## 9. Development result

The frozen evaluator was executed on the two immutable 2023-2024 source ledgers.
Calendar year 2025 was not queried.

### Mechanical price control

Run `dd497b15-5e7f-4c94-84f8-4ce7f1d54c9e`, data hash
`3c42ffc0a221f884d1547b32d98b8e66ffd3ad03802b6aab609f39b9205405f9`:

| Metric | Result |
|---|---:|
| Trades | 19 |
| Winners | 12 |
| Win rate | 63.16% |
| Gross expectancy | +0.295 R |
| Net expectancy | +0.164 R |
| Bootstrap 95% interval | [-0.255, +0.572] R |
| Profit factor | 1.402 |
| Net PnL on 10,000 USD | +301.93 USD |
| Modeled costs | 249.74 USD |
| Maximum drawdown | 3.27% |

The control returned +0.099 R over 10 trades in 2023 and +0.236 R over 9 trades
in 2024. It remained positive at 1.50x costs (+0.099 R) and 2.00x costs
(+0.034 R). All nine predeclared target/holding-period neighbourhood cells were
positive. Nine longs averaged +0.070 R and ten shorts +0.250 R. The largest
winner represented 31.52% of total net profit, and the largest regime contained
47.37% of trades.

The mechanical control therefore passes the predeclared development gate, but its
confidence interval still crosses zero and all 19 catalyst states are unverified.
It remains a small-sample lead, not a proven strategy.

### Fundamental-aligned primary

Run `a349c39b-3a7c-40a4-b634-d7ddfd1797fc`, data hash
`ec93e7356653e41726a9b42b607672ede3d8882b5859afbb5c199bd5f7df41f4`:

| Metric | Result |
|---|---:|
| Trades | 8 |
| Winners | 4 |
| Win rate | 50.00% |
| Gross expectancy | +0.076 R |
| Net expectancy | -0.044 R |
| Bootstrap 95% interval | [-0.698, +0.627] R |
| Profit factor | 0.904 |
| Net PnL on 10,000 USD | -37.23 USD |
| Modeled costs | 96.30 USD |
| Maximum drawdown | 2.93% |

The primary returned +0.186 R over five 2023 trades but -0.428 R over three 2024
trades. Expectancy deteriorated to -0.104 R at 1.50x costs and -0.164 R at 2.00x.
Only one of the nine target/holding-period neighbourhood cells was marginally
positive.

The book-aligned primary fails the development continuation gate. In accordance
with the predeclared protocol, 2025 remains locked. The result does not invalidate
fundamental analysis generally; it rejects the current slow daily/static
pre-London score as the directional gate for this specific intraday setup.
Historically available intraday USD/rates confirmation and point-in-time catalyst
schedules are required before defining a materially improved primary candidate.
