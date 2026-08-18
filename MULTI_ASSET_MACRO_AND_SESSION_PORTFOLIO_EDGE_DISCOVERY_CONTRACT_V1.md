# Multi-Asset Macro and Session Portfolio Edge Discovery Contract V1

Status: **FROZEN BEFORE MARKET-OUTCOME ACCESS**  
Branch: `MULTI_ASSET_MACRO_SESSION_PORTFOLIO_EDGE_V1`

## 1. Purpose and preserved verdicts

This is a new multi-asset research branch. It preserves every previous result, rejection, artifact, and seal, including the final `TERMINATE_GOLD_ONLY_10R_BRANCH` verdict. Nothing in this contract reopens, repairs, or grants validation credit to a rejected gold rule.

The objective is to determine whether a diversified portfolio of transparent macro-and-session edges can produce economically credible out-of-fold performance and whether the resulting opportunity set happens to reach 10 portfolio R per month. Ten R is a reported capacity diagnostic, not an optimization target or a pass criterion used to select thresholds.

One portfolio R equals 1% of the initial $10,000 account, or $100. No result may be described as capable of the $1,000 monthly objective unless it produces at least 10 portfolio R/month after costs under the frozen risk constraints.

Development is 2021-08-01 through 2024-12-31. Calendar 2025 remains closed until every eligible instrument, feature, trigger, execution rule, and portfolio policy is frozen. Calendar 2026 is reserved for a later robustness test followed by append-only prospective tracking. This milestone performs only contract creation and a metadata-only coverage/deduplication audit.

## 2. Requested instrument universe and aliases

The requested economic instruments and exact IC Markets KE MT5 symbols are frozen as:

| Economic instrument | MT5 symbol | Asset class |
|---|---|---|
| Gold spot | `XAUUSD` | Precious metal |
| Silver spot | `XAGUSD` | Precious metal |
| Euro/US dollar | `EURUSD` | FX |
| US dollar/Japanese yen | `USDJPY` | FX |
| Nasdaq 100 CFD | `USTEC` | US equity index |
| S&P 500 CFD | `US500` | US equity index |
| WTI crude CFD | `XTIUSD` | Energy |

`NAS100` and `WTI` are research labels only; they are not additional symbols. Spot CFDs are never relabelled as exchange futures or official cash indices.

An instrument is research-eligible only after a value-blind certification demonstrates:

- exact one-minute timestamp lineage from IC Markets MT5;
- coverage across all 41 development months;
- the first usable development session no later than 2021-08-02 and the final usable session on 2024-12-31;
- unique canonical `(symbol, open_time)` identities after deterministic source-preserving deduplication;
- monotonically ordered, minute-aligned timestamps and `close_time = open_time + 1 minute`;
- at least 90% of active weekdays supplying a usable bar and at least 90% of eligible primary-session windows containing at least 90% of expected minutes;
- point-in-time spread metadata on at least 95% of canonical bars; and
- no use of calendar-2025 or calendar-2026 market values.

Catalog availability alone does not satisfy price-history eligibility. A partial cross-market snapshot does not substitute for one-minute outcome paths. Instruments failing a gate remain `SUPPORT_FAIL_SOURCE` and cannot be silently dropped, proxied, or replaced.

## 3. Source and point-in-time policy

Permitted existing sources are:

- IC Markets MT5 one-minute bars and broker symbol metadata;
- the sealed FRED/ALFRED vintage-aware macro observations and snapshots;
- sealed MT5 scheduled US macro events;
- sealed ZT, ZN, ZQ, and SR3 intraday proxies;
- sealed EURUSD, XAUUSD, XAGUSD, US500, VIX, S&P 500, financial-stress, and credit-risk contexts where their actual coverage permits;
- sealed CFTC gold positioning for XAUUSD/XAGUSD context only; and
- existing deterministic session, structure, and liquidity code, recalculated separately per eligible instrument.

No paid data may be acquired. Existing XAUUSD and EURUSD histories must be reused rather than reacquired. A later acquisition milestone may request only missing IC Markets histories and must preserve raw files unchanged.

Every feature carries `observed`, `calculated`, `inferred`, or `unknown` epistemic status, source identifier, source timestamp, `available_at`, and lineage hash. A value is usable only if `available_at <= decision_at`. Revisions never replace the vintage available at the decision. Missing data remains unknown; no forward fill may cross a release, session, or market closure unless explicitly registered below.

Historical MT5 event forecasts are not verified pre-release vintages and may not be used before release. Post-release actuals become usable only at their sealed release availability. EURUSD is an inverse-dollar proxy and must never be called DXY. Front-continuous futures are repricing proxies and must retain rollover warnings.

## 4. Frozen point-in-time feature registry

Only the following feature families may enter discovery. All transforms are fitted on outer-training data only.

### Slow macro and regime

- CPI, core CPI, PCE, core PCE, payrolls, unemployment, wages where available, claims, GDP, retail sales, and Fed rate: latest point-in-time level, direction, standardized training-only change, and age.
- Two-year, ten-year, ten-year real yield, breakeven inflation, curve slope, policy-path proxy, EURUSD dollar proxy, S&P 500, VIX, financial stress, and credit spread: latest level state, direction, and training-only percentile.
- Event risk: minutes to/from a sealed scheduled release, event family, and importance.
- COT for metals only: publication-available net percentile, weekly change, age, and stale flag. COT can contextualize but cannot independently pass a signal.

### Completed-candle and higher-timeframe state

- Completed weekly, daily, H4, H1, M15, and M5 direction and ATR-normalized displacement.
- Confirmed two-left/two-right swings known only when the second right candle closes.
- Break of structure, structure shift, trend age, impulse efficiency, pullback depth/duration, compression, and expansion.
- Pre-existing prior-week, prior-day, prior-session, confirmed-swing, opening-range, support, resistance, and liquidity levels.

### Session and trigger state

- Session phase, minutes from session open/close, prior-session range, opening range, range percentile, realized volatility, tick-volume ratio, and point-in-time spread/ATR.
- Sweep/reclaim, breakout/acceptance, rejection, first retest, displacement, compression release, and failed-break state from completed candles only.
- Cross-market macro impulse from registered rate, dollar, equity-risk, and volatility proxies, excluding the target instrument's future response.

Exactly one interaction layer is permitted: a registered price/session trigger multiplied by the frozen instrument-specific macro state `ALIGNED`, `OPPOSED`, `NEUTRAL`, or `UNKNOWN`. No three-condition interaction is permitted in V1.

## 5. Frozen directional macro mapping

Macro context is computed before the trigger from the registered sources:

- `XAUUSD`, `XAGUSD`: lower real/front-end yields and weaker USD are positive; higher yields and stronger USD are negative. Financial stress is reported separately and is not forced to one sign.
- `EURUSD`: weaker USD is positive; stronger USD is negative. Rate repricing must be interpreted as the US leg only because a complete euro-rate curve is absent.
- `USDJPY`: stronger US front-end repricing is positive and weaker repricing negative; missing Japanese-rate history caps macro confidence at 60%.
- `USTEC`, `US500`: falling yields with non-stress risk conditions are positive; rising yields or worsening stress are negative. Growth-stress and inflation-rate shocks remain distinct states.
- `XTIUSD`: stronger growth/risk context and weaker USD are positive; weaker growth/risk and stronger USD are negative. EIA inventory effects are `UNKNOWN` because no verified EIA source is present.

Conflicting components create `NEUTRAL_OR_CONFLICTED`; they may not be manually resolved after outcomes.

## 6. Frozen sessions and DST treatment

All intervals are half-open and converted with IANA timezones for each date:

- `ASIA_BUILD`: 00:00-07:00 `Europe/London`.
- `LONDON_DECISION`: 07:00-12:00 `Europe/London`.
- `NEW_YORK_DECISION`: 08:00-12:00 `America/New_York`.
- `US_CASH_OPEN`: 09:30-12:00 `America/New_York`.
- `US_ENERGY`: 08:00-14:30 `America/New_York`.

FX and metals use Asia Build, London Decision, and New York Decision. `USTEC` and `US500` use US Cash Open only. `XTIUSD` uses US Energy and may use London Decision only for context, not a separate entry family.

The first 30 completed minutes form an opening range for US Cash Open and US Energy; the first 15 minutes form it for London and New York Decision. Holidays and early closes are inferred only from already-frozen calendar metadata and actual timestamp availability. A session with less than 90% of expected source minutes is `UNAVAILABLE_TECHNICAL`.

## 7. Frozen edge-family registry

Every definition is symmetric by direction; long and short are one registered signed hypothesis rather than two independently selected tests.

### E1 — post-macro acceptance or rejection

Applicable to all eligible instruments. Following CPI, PCE, NFP, GDP, retail sales, claims, or FOMC, cross-market rate/USD/risk movement through minute 5 establishes the observable macro direction. Between minutes 5 and 30, the first completed M5 close at least 0.10 ATR outside the pre-release 30-minute range is `ACCEPTANCE`; a sweep followed by a close at least 0.05 ATR back inside is `REJECTION`. Entry is the next M1 open in the accepted direction or opposite the rejected break.

### E2 — prior-session sweep and reclaim

Applicable to XAUUSD, XAGUSD, EURUSD, and USDJPY. During London or New York Decision, price must sweep the preceding Asia or London extreme by at least 0.05 M15 ATR and close back inside within three completed M5 bars. Entry is the next M1 open toward the opposite side of the swept range. Strongly opposed macro context causes no trade; neutral/unknown is retained as its own registered state.

### E3 — primary-session break, acceptance, and retest

Applicable to every eligible instrument in its primary decision session. A completed M15 close must exceed the frozen opening/prior-session boundary by at least 0.10 ATR with body fraction at least 0.60 and directional close location at least 0.70. The first retest within four completed M5 bars must close on the breakout side. Entry is the next M1 open.

### E4 — higher-timeframe pullback resolution

Applicable to every eligible instrument. H4 direction requires two successive confirmed swing breaks. Price must retrace 0.35-0.75 of the last known H4 impulse into a pre-existing H1/H4 swing or prior-day level. A completed M15 displacement candle of at least 0.80 ATR, body fraction at least 0.60, and aligned minor-structure break triggers entry at the next M1 open. Strongly opposed macro context causes no trade.

No additional family, candle label, direction inversion, or threshold may be added after development outcomes are opened.

## 8. Frozen execution and cost model

For every family:

- Entry: exact next M1 open after the completed trigger, with one-minute latency.
- Stop: trigger/retest structural extreme plus 0.10 M15 ATR; no trade if distance is below 0.25 ATR or above 1.50 ATR.
- Target: nearest pre-existing direction-aligned liquidity level between 1.25R and 3.00R; if none exists, fixed 2.00R.
- Exit order: stop first, target second, then session/deadline time exit.
- Ambiguous M1 bar: stop first. Gap through stop: worse of stop and M1 open.
- Maximum one open position per instrument. No re-entry within the same instrument/family/session.
- Missing M1 bar in an active path invalidates the case; it is never interpolated.

Base round-trip cost in R is `max(point-in-time spread in R + 0.03R commission/slippage allowance, 0.05R)`. Spread uses the greater of entry- and exit-bar recorded spreads. Results must also be positive at 1.5x costs; 2.0x costs are reported. Whole broker volume steps and minimum sizes are enforced, and planned risk may never be rounded upward.

## 9. Chronological development and support

The expanding folds are frozen as:

1. train 2021-08-01–2021-12-31; validate 2022-01-01–2022-06-30;
2. train through 2022-06-30; validate 2022-07-01–2022-12-31;
3. train through 2022-12-31; validate 2023-01-01–2023-06-30;
4. train through 2023-06-30; validate 2023-07-01–2023-12-31;
5. train through 2023-12-31; validate 2024-01-01–2024-06-30;
6. train through 2024-06-30; validate 2024-07-01–2024-12-31.

Only strictly out-of-fold decisions receive development credit. A standalone test requires at least 90 eligible cases, 60 dates, 15 cases in every validation fold, and 30 cases in each signed direction. A macro interaction requires at least 60 cases, 40 dates, 10 per fold, and 20 per state. Failed support remains recorded as `SUPPORT_FAIL`.

## 10. Multiplicity, uncertainty, and candidate gates

Stage 1 evaluates every registered standalone instrument × family × session test. Benjamini-Hochberg FDR is fixed at 0.05 across the complete Stage-1 registry, including support failures as p=1. Stage 2 evaluates every support-eligible registered trigger × macro-state interaction regardless of favorable Stage-1 results. Holm family-wise correction is fixed at 0.05 across the complete Stage-2 registry.

Uncertainty uses 5,000 decision-date clustered bootstrap resamples with seed `731947`. A candidate may advance only if:

- net out-of-fold expectancy is positive;
- profit factor is at least 1.15;
- clustered 95% expectancy lower bound is positive;
- adjusted significance passes its stage's multiplicity rule;
- expectancy remains positive at 1.5x costs;
- at least four of six folds and two of three scored calendar years are positive;
- parameter-neighbour signs agree in at least two of three frozen neighbours;
- no single session supplies more than 70% of positive PnL; and
- normalized drawdown at 0.25% single-trade risk is no more than 10%.

No more than two candidates per instrument, one candidate per instrument/family, and eight candidates portfolio-wide may advance. Zero is acceptable. Ranking is adjusted-significance status, median fold expectancy, profit factor, support, then candidate ID; the distance from 10R/month is never a ranking input.

## 11. Portfolio clusters, risk, and capacity decision

Static risk clusters are:

- `PRECIOUS_METALS`: XAUUSD, XAGUSD;
- `USD_FX`: EURUSD, USDJPY;
- `US_EQUITY_INDICES`: USTEC, US500;
- `ENERGY`: XTIUSD.

Each accepted trade risks 0.25 portfolio R, or 0.25% of the initial account. Maximum concurrent planned loss is 1 portfolio R per cluster and 2 portfolio R across all clusters. From 15 minutes before through 120 minutes after a tier-one US release, every position also belongs to a temporary `US_MACRO_SUPERCLUSTER` capped at 1 portfolio R. If capacity is exceeded, earlier trigger timestamp wins, followed by instrument ID and candidate ID lexicographically. Risk is never increased to meet the return target.

The portfolio must have positive net out-of-fold expectancy, PF at least 1.15, positive clustered 95% lower bound, positive expectancy at 1.5x costs, at least four positive folds and two positive years, maximum drawdown no more than 15%, and no instrument or static cluster supplying more than 50% of positive PnL.

`PORTFOLIO_EDGE_PASS` is independent of the target. `TARGET_CAPACITY_PRESENT` is reported only if the frozen passing portfolio independently produces at least 10 portfolio R/month after costs. A credible edge below 10R remains an edge but does not satisfy the account objective.

## 12. Forward locks and milestone stopping rule

Calendar 2025 may be opened exactly once only after the complete development portfolio is frozen and sealed. It is exposed historical robustness evidence, not independent validation. Calendar 2026 remains locked through that evaluation and may then be opened once for year-to-date robustness before append-only prospective decisions begin. No retuning follows either period.

Milestone 1 ends after the metadata-only source inventory, deduplication audit, coverage classifications, minimal free acquisition list, independent reproduction, and seal. It must not inspect OHLC values, calculate returns or relationships, construct cases, simulate trades, calculate PnL, or access 2025/2026 market outcomes.
