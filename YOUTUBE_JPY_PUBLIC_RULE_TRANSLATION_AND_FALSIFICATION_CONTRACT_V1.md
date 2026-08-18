# YouTube JPY Public-Rule Translation and Falsification Contract V1

Status: `FROZEN_PRE_OUTCOME`

Frozen on 2026-08-13 before this branch accessed any USDJPY market value or outcome.

## 1. Objective and epistemic status

This branch tests one transparent translation of the common public USDJPY hypothesis screened in `YOUTUBE_JPY_STRATEGY_SCREENING_V1.md`. It does not claim to reconstruct the creator's undisclosed/private strategy or verify promotional performance claims.

The source videos are hypothesis-generation evidence. Their rules were published during or after the historical period. Results from 2021–2024 therefore receive historical replication/falsification credit only. Calendar 2025 and calendar 2026 remain closed until a complete economic policy passes and is sealed; if opened later, both are exposed robustness evidence only. Genuine independent evidence begins prospectively after a final freeze.

Existing sealed sources only may be used. No acquisition, paid endpoint, card charge or licensing workaround is authorized.

## 2. Source population and time authority

- Instrument: IC Markets MT5 `USDJPY` only.
- Price resolution: M1 bid-chart OHLC and observed `spread_points`.
- Source window: `2021-08-01T00:00:00Z` inclusive through `2025-01-01T00:00:00Z` exclusive.
- Calendar source: existing MetaQuotes MT5 United States calendar export only.
- Canonical duplicate rule: earliest lexicographic sealed source path and then earliest source row for an identical UTC `open_time`.
- Timestamp authority: M1 `open_time` in UTC; a bar is usable only at its recorded `available_at`, which must be no earlier than `close_time`.
- Strategy clock: fixed `Africa/Nairobi` (`UTC+03:00`, no DST).
- All intervals are left-closed and right-open.
- A pip in USDJPY is `0.01`; one broker point is `0.001`.

Only Monday through Friday Nairobi session dates are eligible. A session requires the exact 06:00 and 19:59 Nairobi M1 bars and at least 95% of the 840 expected M1 opens from 06:00 through 19:59. Missing values are `UNAVAILABLE_TECHNICAL`, never imputed.

## 3. Frozen candle construction

Nairobi daily candles cover `[00:00, 24:00)`. A daily candle is complete with at least 1,200 unique observed M1 opens and exact chronological ordering. The previous day is the latest earlier complete weekday candle, so Friday may be the previous trading day for Monday.

M15 candles are aligned to Nairobi quarter-hours and require at least 14 of 15 expected M1 opens. H1 candles are aligned to Nairobi clock-hours and require at least 56 of 60 expected M1 opens. Aggregation is first open, maximum high, minimum low and last close in canonical source order. A higher-timeframe bar is available only at its interval end.

True range is `max(high-low, abs(high-prior_close), abs(low-prior_close))`. Daily ATR is the arithmetic mean of the latest 20 completed daily true ranges. M15 ATR is the arithmetic mean of the latest 14 completed M15 true ranges. No current incomplete bar contributes.

## 4. Frozen public-rule translation

### 4.1 Long-term daily trend

At 06:00 Nairobi, take the latest 252 complete daily closes ending with the prior trading day. Fit ordinary least squares `close = intercept + slope * ordinal_index`. Direction is `+1` when slope is strictly positive and `-1` when strictly negative. An exact zero, fewer than 252 closes or any non-finite value is `UNKNOWN` and no case.

This is the single outcome-blind mapping of the video's visual “zoom out” instruction. It may not be replaced by a moving average, swing narrative or later-favourable lookback.

### 4.2 Previous-day alignment

The immediately preceding complete daily candle must have `close > open` for a long-direction case or `close < open` for a short-direction case. A doji is no case.

### 4.3 News exclusions

The complete Nairobi session date is excluded when the existing U.S. MT5 calendar schedules any of:

- headline or core CPI (`event_id` 840030005 through 840030010, 840030033 through 840030036);
- headline or core PPI (`event_id` 840030001 through 840030004);
- Fed Interest Rate Decision (`event_id` 840050014).

For NFP (`event_id` 840030016), the Monday-through-Sunday Nairobi ISO week containing the release is excluded, implementing the most conservative public “NFP week” statement. Private payrolls are not NFP. The source time is `event_time_server`, already certified under the repository's fixed UTC+3 calendar policy. Actual, forecast and revised values are never used.

The existing calendar is U.S.-only. Japanese releases cannot be silently inferred; this limitation is reported but does not change the frozen mapping because USD is a component of USDJPY and the public examples also exclude U.S. events in JPY trading.

### 4.4 Pre-existing daily support/resistance

Daily pivots use strict two-left/two-right extrema. A pivot low at index `i` requires its low to be strictly below the lows at `i-2`, `i-1`, `i+1`, and `i+2`; a pivot high is symmetric. It becomes known only when daily candle `i+2` closes.

For a candidate session, use at most the 504 completed trading days before the previous day. Eligible pivots must have become known before the previous day opened. Same-side pivots are in one touch cluster when their prices lie within `0.15 * prior_day_ATR20` of the cluster's median. Greedy clustering is performed in chronological order and the median is recomputed after every accepted pivot. Touches must be separated by at least five completed daily bars. A valid level has at least three touches.

A support cluster is invalid if, after its latest qualifying touch and before the previous day, a completed daily close is below `level - 0.20 * ATR20`. Resistance invalidation is symmetric.

The previous day is a long bounce when its low is within `0.20 * ATR20` of valid support, it closes strictly above the level and it is bullish. A short bounce is symmetric at resistance. If multiple levels qualify, choose the smallest absolute distance from the previous-day extreme, then more touches, then the most recent touch, then the lower numerical level. The level must pre-exist; the previous day cannot create its third touch.

### 4.5 Impulse and meaningful pullback

M15 pivots use strict one-left/one-right extrema and become known at the close of the right-hand bar.

For a long W candidate, the frozen pullback structure is an ordered M15 pivot sequence `impulse_low, impulse_high, W_low_1, neckline_high, W_low_2`. The impulse low/high must be the latest ordered low/high pivots before `W_low_1`. The bullish impulse size must be at least `0.75 * ATR14` measured using the ATR available when `W_low_1` becomes known. Pullback depth is `(impulse_high - min(W_low_1, W_low_2)) / (impulse_high - impulse_low)` and must be from `0.382` through `1.000`, inclusive. Shorts are exactly sign-symmetric.

### 4.6 W/M pattern and confirmation

The W sequence is `low-high-low`; the M sequence is `high-low-high`. Each neckline-to-leg excursion must be at least `0.25 * ATR14` available at confirmation. Either second leg may be deeper, consistent with the public explanation. From first W/M leg through confirmation may span no more than 16 M15 bars.

Long confirmation is the first completed bullish M15 candle whose close is at least `0.02 * ATR14` above the neckline after the second low is known. Short confirmation is symmetric. The first leg may form from 00:00 Nairobi; confirmation must close from 06:00 through 19:45 Nairobi.

### 4.7 Neckline retest, H1 confirmation and orders

Decision time is the confirming M15 close. A one-minute latency applies. From the first eligible M1 bar after latency until 20:00 Nairobi:

- a long retest occurs when the M1 range reaches the neckline from above; a short retest is symmetric;
- the pending pattern is invalid before fill if price crosses the second-leg extreme by more than `0.02 * confirmation_ATR14`; when invalidation and retest occur in the same M1 bar, invalidation is assumed first;
- at retest, the latest fully completed H1 candle must close in the trade direction; otherwise that pattern is rejected permanently;
- fill price is the neckline with no favourable gap improvement;
- an unfilled order expires at 20:00 Nairobi.

After a rejected or expired pattern, a later independently completed pattern on the same session date may be considered. The first valid fill wins. There may be no second trade that day.

### 4.8 Overlap and holding deadline

At most one USDJPY order or open position exists at a time. A new session is skipped while a prior position is open. No re-entry follows a fill. A filled position has a maximum ten-hour holding period, reflecting the longest duration disclosed publicly; unresolved positions exit at the final observed M1 close at or before that deadline.

A filled outcome path requires the exact entry minute and at least 95% of the expected M1 opens through the ten-hour deadline. A deficient path is `UNAVAILABLE_TECHNICAL` and cannot contribute to support or economics.

## 5. Frozen waterfall and outcomes

### Stage 1 — contextual premise

Eligible cases require trend, previous-day alignment, clean news state and session coverage. From the exact 06:00 Nairobi open to the 19:59 close, calculate direction-signed displacement in pips, directional hit, MFE, MAE and the diagnostic first passage of +45 pips versus -15 pips with stop-first M1 ambiguity.

Stage 1 advances only if all gates pass over strict-credit years 2023–2024:

- at least 150 dates overall, 60 in each year and 25 in each of four half-year folds;
- mean signed session displacement greater than zero;
- 95% calendar-week cluster bootstrap lower bound for mean displacement greater than zero;
- one-sided week-cluster sign-randomization `p <= 0.05`;
- directional hit rate greater than 50%;
- both calendar years positive;
- at least three of four half-year folds positive.

### Stage 2 — location increment

Apply the frozen daily level and bounce only to Stage-1 cases. Advance only if:

- at least 50 location cases, at least 15 per year and at least eight per half-year fold;
- location mean signed displacement and its week-cluster 95% lower bound are positive;
- mean location displacement minus contemporaneous non-location displacement is positive with a week-cluster 95% lower bound above zero;
- location directional hit rate exceeds the Stage-1 hit rate;
- both years and at least three half-year folds are positive.

### Stage 3 — trigger increment

Apply the frozen M15 pattern, retest and H1 rules only to Stage-2 cases. From frozen neckline entry, evaluate the unchanged 15-pip adverse boundary and 45-pip favourable boundary, without break-even or costs, for ten hours. Ambiguous M1 bars are stop-first. Unresolved outcomes mark to the deadline and are bounded to `[-1R,+3R]`.

Advance only if:

- at least 30 fills overall, at least ten per year and five per half-year fold;
- gross expectancy and profit factor are respectively greater than zero and at least 1.10;
- week-cluster 95% expectancy lower bound is greater than zero;
- both years and at least three half-year folds have positive expectancy.

### Stage 4 — published economics

Use a 15-pip stop, 45-pip target and move the stop to entry after +20 favourable pips. On ambiguous bars the active stop is evaluated before target; when +20 activation and an entry-price revisit share a bar, break-even is assumed to activate before the revisit unless the original stop was also reached, in which case the original stop wins.

Base round-trip cost is the predecessor convention `max(max(entry_spread, exit_spread) * 0.001 / 0.15 + 0.03R, 0.05R)`. Cost stresses are 1.0x, 1.5x and 2.0x. Planned risk is exactly 1% or $100 on a frozen $10,000 account; R and dollar results use $100 per planned R. The position size is rounded down to the broker's 0.01-lot step and may not exceed one planned R, but normalized R is the primary economic measure.

Economic PASS requires:

- positive net expectancy;
- profit factor at least 1.10;
- week-cluster 95% net-expectancy lower bound above zero;
- positive expectancy at 1.5x costs;
- both years and at least three half-year folds positive;
- maximum drawdown no greater than 15R;
- no one year supplies more than 70% of positive R.

## 6. Statistical and reproduction policy

Strict-credit dates are 2023-01-01 through 2024-12-31. Earlier eligible dates are warmup/descriptive only. Half-year folds are 2023-H1, 2023-H2, 2024-H1 and 2024-H2.

Bootstrap resamples calendar-week clusters with replacement for 5,000 draws, seed `20260813`. The one-sided cluster sign-randomization uses 20,000 draws, seed `20260814`. The single preregistered hypothesis requires no cross-candidate multiplicity adjustment. Every test, support failure and negative result is retained.

Primary pandas and reference CSV-stream implementations must independently reproduce canonical M1 identities, aggregate candles, cases, levels, triggers, paths, costs, statistics, gates and verdicts. Float artifacts are rounded to 12 decimal places before checksumming. Any discrepancy is a formal integrity failure.

## 7. Early stopping, forward policy and prohibitions

Failure of Stage 1 terminates the branch before level-conditioned outcomes are calculated. Failure of Stage 2 terminates before trigger outcomes. Failure of Stage 3 terminates before economic results. A support failure is a failure, not permission to lower a floor.

Only a complete Stage-4 PASS may be frozen for calendar 2025 and then 2026 robustness. No source for those periods may be opened otherwise. If a pass occurs but existing free forward data are absent, record a genuine source blocker; acquisition remains prohibited by this contract.

No alternative trend, threshold, level algorithm, pattern, news filter, stop, target, break-even, session, direction inversion, losing-case deletion or creator-claim reinterpretation may be added after outcomes. No rejected repository strategy is reopened. No relationship may be described as the creator's private edge.
