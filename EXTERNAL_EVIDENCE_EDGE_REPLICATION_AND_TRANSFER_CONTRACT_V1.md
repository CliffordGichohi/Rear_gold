# External Evidence Edge Replication and Transfer Contract V1

Status: `FROZEN_PRE_OUTCOME`

Freeze date: 2026-08-13 (Africa/Nairobi)

## 1. Purpose and boundary

This branch tests externally documented, completely specified trading rules. It does not invent a new strategy, reopen a rejected rule, or use a published observation as permission to tune a local variant.

Every previous verdict, artifact, hash and seal remains authoritative. Calendar 2021 through 2024 is historical replication, not fresh independent discovery. Previously exposed 2025 and 2026 evidence has no independent-validation credit. Only observations recorded after the final policy freeze can provide genuinely prospective evidence.

The branch may use existing sealed sources and no-charge public or IC Markets MT5 sources. It must stop before any charge or licensing uncertainty. No paid acquisition is authorized.

## 2. Evidence-search protocol

The bounded search universe consists of primary academic papers, official central-bank or exchange research, author-hosted manuscripts, and transparent institutional research found through the search queries recorded in the evidence catalog. Social-media claims, screenshots, proprietary black boxes, rules with missing decision semantics, and results that require choosing parameters after observing the replication period are ineligible.

Candidate ranking is outcome-blind and ordered by:

1. complete point-in-time rule;
2. explicit economic mechanism;
3. publication before 2021;
4. direct compatibility with sealed sources;
5. transaction-cost observability;
6. independent-observation support;
7. non-overlap with prior repository tests.

At most three candidate rules may be tested. Zero passing rules is acceptable.

## 3. Frozen selected families and candidates

### Family EER_F01: U.S. equity market intraday momentum

Primary evidence: Gao, Han, Li and Zhou, *Market Intraday Momentum*, Journal of Financial Economics 129 (2018), 394-414, DOI `10.1016/j.jfineco.2018.05.009`.

Mechanism stated by the authors: information incorporated from the previous close through the first half hour is revisited near the close through infrequent institutional rebalancing and late-informed trading.

Eligible instrument mapping: `SPY -> US500` and the paper's documented `QQQ` extension -> `USTEC`. Both IC Markets instruments are cash-index CFDs. This is one mechanism-preserving mapping; it is not a claim that CFD returns are identical to ETF returns.

Frozen candidate `EER_C01_EQUITY_MIM_R1`:

- `p0`: previous eligible U.S. cash-session 16:00 America/New_York close.
- `p1`: current eligible session 10:00 close.
- `p12`: current eligible session 15:30 close.
- `p13`: current eligible session 16:00 close.
- `r1 = p1 / p0 - 1`.
- At 15:30, long when `r1 > 0`; short when `r1 <= 0`.
- Exit at 16:00 the same day.

Frozen candidate `EER_C02_EQUITY_MIM_R1_R12`:

- Retain `p0`, `p1`, `p12`, and `p13` above.
- `p11`: current eligible session 15:00 close.
- `r12 = p12 / p11 - 1`.
- At 15:30, long only when `r1 > 0` and `r12 > 0`.
- At 15:30, short only when `r1 <= 0` and `r12 <= 0`.
- Otherwise take no position.
- Exit at 16:00 the same day.

The source-style return is `direction * (p13 / p12 - 1)`. No stop, target, filter, volatility condition, macro condition or discretionary override may be added.

### Family EER_F02: crude-oil market intraday momentum

Primary evidence: Wen et al., *Intraday momentum and return predictability: Evidence from the crude oil market*, Economic Modelling 95 (2021), 374-384, DOI `10.1016/j.econmod.2020.03.004`.

Mechanism and rule: the paper documents that the first half-hour return of USO predicts its last half-hour return and evaluates the exact sign-timing rule.

Eligible instrument mapping: `USO -> XTIUSD` during the same 09:30-16:00 America/New_York cash-ETF clock. This is a single, declared transfer test from the oil ETF to the IC Markets WTI cash CFD.

Frozen candidate `EER_C03_WTI_MIM_R1` uses the exact `p0`, `p1`, `p12`, `p13`, `r1`, direction, entry and exit definitions of `EER_C01`, applied only to `XTIUSD`.

## 4. Explicit exclusions

- Twelve-month time-series momentum is not tested because the papers use liquid futures and forwards, excess returns, roll yield and ex-ante volatility. The sealed cash-CFD data do not contain historical financing or futures roll returns. Substitution would not be an exact replication.
- Gold macro-announcement studies are descriptive response studies and do not publish a complete entry, exit and risk rule. The repository also already rejected a broad macro-acceptance search and retains one separate, inconclusive prospective macro-fade candidate. No new gold rule will be invented here.
- Pre-FOMC equity drift is excluded because pre-2021 follow-up evidence documents that the effect essentially disappeared after 2015.
- Opening-range breakout research overlaps prior frozen opening-range branches and typically selects probing times or thresholds from outcomes.
- Order-flow imbalance research establishes short-horizon price impact but not a complete executable rule and would require continuous order-book coverage not present outside the existing 188 engineering/research dates.
- Turn-of-the-month, FX carry, volatility-managed portfolios, cross-sectional momentum and futures-basis strategies fail at least one of rule completeness, current source compatibility, independent support, financing/forward data, or capacity criteria.

## 5. Point-in-time and timestamp policy

All session clocks use `America/New_York` with IANA daylight-saving conversion.

M1 bar timestamps are bar-open timestamps. A close at clock time `T` is the close of the bar whose open timestamp is `T - 1 minute`; it is available at `T`. The decision at 15:30 uses only bars available at or before 15:30. The exit uses the 15:59 bar close available at 16:00.

A session is eligible only when all required timestamps are unique, ordered and available. Missing anchors make that instrument-session `UNAVAILABLE_TECHNICAL`; no nearest-bar substitution or imputation is permitted. Observed holidays and closures are unavailable, not losses.

## 6. Frozen economic transfer

The exact percentage-return replication is reported separately from the account implementation.

For the $10,000 account implementation:

- `1 portfolio R = $100`.
- Planned concurrent risk is at most `1R` per correlation cluster.
- `US500` and `USTEC` share `US_EQUITY_INDICES`; simultaneous positions split the $100 ex-ante risk budget equally. A single eligible equity position receives the complete budget.
- `XTIUSD` is the `ENERGY` cluster and receives at most $100 ex-ante risk.
- Ex-ante risk distance is the sample standard deviation of the preceding 60 eligible last-half-hour percentage returns, using a minimum of 20 and excluding the current day.
- Position volume is rounded down to the frozen broker volume step and may never exceed the ex-ante cluster budget.
- Gross notional is capped at five times the $10,000 account per cluster.
- No hard stop or target is introduced because the source strategies have neither.

MT5 bars are bid-chart prices. A long pays the observed entry spread; a short pays the observed exit spread. Spread is `spread_points * point`. A deterministic latency/slippage charge of `0.03R` is added, with total round-trip cost floored at `0.05R`. Cost stresses are `1.0x`, `1.5x`, and `2.0x`. No commission is added to the commission-free IC Markets index/energy CFD mapping; any financing is irrelevant because every position is intraday.

Broker metadata is frozen as:

| Symbol | point | contract size | volume step |
|---|---:|---:|---:|
| US500 | 0.01 | 1 | 0.1 |
| USTEC | 0.01 | 1 | 0.1 |
| XTIUSD | 0.01 | 100 | 0.5 |

## 7. Frozen sample, folds and support

- Historical replication window: `2021-08-01T00:00:00Z` through `2025-01-01T00:00:00Z` exclusive.
- Partial calendar 2021 is reported but receives no annual-stability credit.
- Stability years: 2022, 2023 and 2024.
- Chronological folds: 2022-H1, 2022-H2, 2023-H1, 2023-H2, 2024-H1 and 2024-H2.
- Minimum support: 300 executed candidate-days overall, at least 80 in each stability year, and at least 40 in every half-year fold.
- Equity-family support is measured after same-cluster aggregation by trading date. Oil support is measured by eligible trading date.

## 8. Frozen inference, multiplicity and economic gates

Primary statistical unit: trading date. Bootstrap resampling uses 5,000 date-cluster draws with seed `20260813`. A one-sided sign-randomization test uses 20,000 draws with seed `20260814`. Holm adjustment is applied in fixed candidate order `C01`, `C02`, `C03`.

A candidate passes only when every gate passes:

- support requirements;
- net expectancy greater than zero;
- profit factor at least 1.10;
- clustered 95% confidence lower bound for mean daily net R greater than zero;
- Holm-adjusted one-sided randomization p-value at most 0.05;
- net expectancy at `1.5x` costs greater than zero;
- at least four of six positive half-year folds;
- at least two of three positive stability years;
- maximum drawdown no greater than `15R`;
- no single positive year supplies more than 70% of positive PnL;
- for equity candidates, neither instrument supplies more than 70% of positive PnL.

Candidate ranking is frozen as `C01`, then `C02`, then `C03`. At most one candidate from `EER_F01` can enter a portfolio; if both pass, `C01` has priority. `C03` may combine with the selected equity candidate. The portfolio may not exceed `1R` concurrent risk per cluster or `15R` maximum drawdown.

The result must report raw and net return, support, win rate, expectancy, profit factor, trades per month, R per month, dollars per month, drawdown, costs, stressed costs, years, folds, instruments and cluster contributions. It must report distance from 10R/month without selecting toward that target.

## 9. Outcome opening, reproduction and forward disposition

After the contract, evidence catalog, deduplication matrix, source-readiness audit and pre-outcome freeze are hashed and sealed, the 2021-2024 replication paths may be opened once.

Primary and reference implementations must independently reproduce row identities, directions, raw returns, cost inputs, volume, PnL, statistics and verdicts. Any value-blind engineering correction must be documented and may not alter a frozen rule or gate.

Only a passing development-replication candidate may be frozen and applied unchanged to available 2025 and then 2026 data. Those years remain exposed robustness evidence. If no candidate passes, 2025 and 2026 remain unopened in this branch and no prospective ledger is initialized for a failed rule.

## 10. Stop conditions

Stop before any paid request, licensing uncertainty, missing required source, predecessor-seal failure, point-in-time violation, outcome access before freeze, irreproducibility, or need to reinterpret a published rule. No post-hoc inversion, threshold change, candidate addition or cosmetic repair is permitted.
