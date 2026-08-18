# Gold Trend-Pullback Continuation Edge Discovery Contract V1

Status: `FROZEN_BEFORE_CONDITIONAL_FEATURE_OR_OUTCOME_ACCESS`

## Research question

Starting from the sealed comprehensive trend-continuation census, determine
whether facts knowable when a pullback is confirmed distinguish gold pullbacks
that subsequently continue from those that fail through an opposing structure
switch.

The study is allowed to discover an honest relationship. It is not required to
prove that continuation is profitable. A development relationship is not called
an economically tradable edge until a separately frozen execution test remains
positive after costs.

## Preserved work and boundaries

- Preserve every prior result, rejection, artifact and seal.
- The governing denominator is the corrected V02 census built from the sealed
  IC Markets MT5 XAUUSD casebook.
- Development is 2021-08-01 through 2024-12-31.
- Calendar 2025 and 2026 remain locked.
- The six registered GC engineering dates retain zero research credit.
- No paid acquisition is authorized.
- M15, H1 and H4 are analysed separately. Their cases are never pooled.
- `STANDARD` span-two structure is the primary research scale. `MICRO` and
  `MAJOR` are outcome-blind sensitivity and replication populations; they may
  not rescue a failed standard-scale condition.

## Decision clock and population

The decision timestamp is the census `known_at_utc`: the close of the second
right-hand bar that confirms the pullback pivot. Every price input must come
from a completed bar with `close_time <= known_at_utc`. Every non-price fact
must satisfy `available_at <= known_at_utc`.

All census rows remain auditable. The actionable relationship population is
restricted to cases that were still live at `known_at_utc`, were research
eligible, and eventually received either `CONTINUED` or
`FAILED_STRUCTURE_SWITCH`. `RESOLVED_BEFORE_CONFIRMATION` remains in the
denominator audit but cannot represent a decision. Boundary-unresolved cases
are reported and excluded from fitted effects.

The primary endpoint is the frozen binary structural outcome:

- 1: `CONTINUED` -- the next structural break was in the existing trend
  direction;
- 0: `FAILED_STRUCTURE_SWITCH` -- the opposing structure switch occurred first.

No forward return, MFE, MAE, entry, stop, target or PnL is used in this branch.

## Objective technical evidence

Candlestick names are never accepted by visual judgement. The matrix stores
their underlying completed-candle measurements:

- range divided by ATR14;
- absolute body divided by range;
- direction-normalized close location;
- trend-side and opposite-side wick fractions;
- trend-aligned, opposed or doji body state;
- strict body engulfing, inside-bar, outside-bar and close-through-prior-extreme
  states;
- pivot-to-confirmation displacement, path efficiency, aligned-close count and
  volatility response.

Two named candle clues are deterministic summaries only:

- `PIVOT_REJECTION_STRONG`: trend-side wick is at least 40% of range,
  direction-normalized close location is at least 60%, and the candle body is
  not opposed to the trend.
- `CONFIRMATION_DISPLACEMENT`: confirmation range is at least 0.80 ATR14, body
  is at least 50% of range, direction-normalized close location is at least
  two-thirds, and the body points with the trend.

Retracement is measured from the post-reference-event impulse extreme back to
the pullback pivot, divided by the reference-level-to-impulse-extreme distance.
Store the continuous value without clipping and the frozen zones `<23.6%`,
`23.6-38.2%`, `38.2-50.0%`, `50.0-61.8%`, `61.8-78.6%`, and `>78.6%`.
Fibonacci labels describe location; they do not imply causation.

Other frozen technical evidence includes impulse extension and efficiency,
trend age, prior continuation count, pullback duration and efficiency,
retracement/impulse volatility compression, reference-level touch and
sweep/reclaim, previous New-York trading-day high/low interaction, completed
Asian-range interaction, session clock, H1/H4 structural alignment, and
completed daily/weekly momentum alignment.

## Fundamental and positioning evidence

Use the latest sealed Reference-Book `FUNDAMENTAL_SNAPSHOT` whose availability
does not exceed the decision time. Store age, score, confidence, coverage,
regime, reaction function, event risk and direction-normalized contributions
for real yield, Fed path, USD, two-year yield, positioning flow and financial
stress. A snapshot older than 96 hours is `UNKNOWN`; age is always reported.

`FUNDAMENTAL_ALIGNED` requires trend-normalized score at least +20, coverage at
least 50% and confidence at least 35%. `FUNDAMENTAL_OPPOSED` mirrors -20.

Use only COT reports published and available by the decision time. Store report
age, managed-money net percentile, direction-normalized weekly net change,
crowding and liquidation classifications. COT is a slow context and cannot be
presented as observed intraday institutional activity.

## Location and session conventions

- New-York trading days run from 17:00 America/New_York to the next 17:00;
  only the prior completed trading-day range is eligible.
- The Asian range is 10:00 through 16:00 Asia/Tokyo, constructed from completed
  M15 bars and usable only after 16:00 local.
- London is 08:00-12:00 Europe/London and New York is 08:00-12:00
  America/New_York, with the overlap reported separately. IANA time zones govern
  daylight-saving conversion.
- A level interaction is a numerical touch, cross, close and reclaim test. It
  is not evidence of an institution or motive.

## Registered discovery procedure

Stage 1 tests every frozen single-condition clue in the registry for each
timeframe. Stage 2 tests every frozen two-condition interaction regardless of
whether its Stage 1 members looked favourable. No condition, threshold,
direction, timeframe or state may be added, inverted or repaired after outcome
access.

For each test report support, continuation rate, complement rate, lift in
percentage points, odds ratio, deterministic trading-date cluster-bootstrap
90% and 95% intervals, one-sided bootstrap probability, Benjamini-Hochberg
adjustment within timeframe/stage, annual and four chronological-block effects,
bull/bear effects, first-case-per-segment robustness, and MICRO/MAJOR scale
replication diagnostics.

Chronological blocks are:

1. 2021-08-01 through 2022-06-30;
2. 2022-07-01 through 2023-03-31;
3. 2023-04-01 through 2023-12-31;
4. 2024-01-01 through 2024-12-31.

Support floors are M15 200 cases/100 dates, H1 75 cases/50 dates and H4 30
cases/25 dates, with at least 15 continued and 15 failed observations. A
condition becomes a `PROVISIONAL_DEVELOPMENT_RELATIONSHIP` only when:

- support passes;
- continuation lift is at least +5 percentage points;
- the 90% cluster-bootstrap lower bound is above zero;
- Stage-specific BH q is at most 0.10;
- at least three chronological blocks have nonnegative lift and none is below
  -10 percentage points; and
- first-case-per-segment lift is positive.

Side and adjacent-scale results are mandatory diagnostics, not rescue gates.
Rank passing conditions by 90% lower bound, lift, then support. Retain no more
than three provisional conditions per timeframe; zero is acceptable.

## Integrity and next boundary

Feature rows and outcomes are physically separate. Freeze and seal the feature
matrix before the first controlled outcome join. Primary and reference passes
must reproduce row identities, availability classifications, every feature,
schema, checksum, diagnostic and result exactly.

This authorization ends after conditional relationship discovery. It does not
authorize execution optimization, trades, R multiples, PnL, account-return
claims, or opening 2025/2026. If a provisional condition survives, the next
contract must freeze a small constant execution family before any profitability
claim.
