# Gold Structural Trend-Retracement Continuation Edge Discovery Contract V1

Status: `SEALED_BEFORE_ANY_BRANCH_OUTCOME_ACCESS`

## Purpose and prior-result preservation

This is a new research branch. It preserves every prior result, rejection,
artifact, source seal, and exposed-data classification. In particular, the Gold
Fundamental-Aligned Multi-Timeframe Auction V1 rejection remains final and may
not be retuned or inverted.

The proposition is that gold continuation may become economically predictable
only after a complete auction sequence is known point in time:

`external-liquidity sweep -> structural transition -> displacement -> orderly
retracement -> completed lower-timeframe continuation confirmation`.

The study is research, not a mandate to prove the proposition. Zero candidates
is acceptable.

## Data and chronology

- Development: 2021-08-01 through 2024-12-31.
- Exclude the six permanently engineering-only GC dates already registered.
- Exposed robustness only: calendar 2025 and 2026 through 2026-07-29, opened
  only after development candidates are frozen. These periods receive no
  independent-validation credit.
- Use the existing sealed XAUUSD M1 history and its deterministically aggregated
  closed H1/H4 periods. A closed aggregate may contain normal no-tick minutes;
  its `complete` component-count flag is a quality diagnostic, not permission to
  use a forming candle.
- Use the existing point-in-time macro, rates, USD, COT, risk-market, session,
  and GC sources. No paid acquisition is authorized.
- Fundamentals and structural states must be available at the session cutoff.
  A bar cannot be used before its close timestamp. A pivot cannot be used before
  both right-hand confirmation bars have closed.

## Sessions and directional permission

- London and New York are separate statistical families.
- London uses `Europe/London`; New York uses `America/New_York`.
- Signal scan: 08:00 inclusive through 11:00 local, DST aware.
- Forced exit: the earlier of 180 minutes after entry or 13:00 local.
- Fundamental permission is the existing transparent Reference-Book engine:
  bullish score at least +20 or bearish score at most -20, coverage at least
  50%, and confidence at least 35%.
- COT remains a point-in-time crowding/risk diagnostic and is not allowed to
  manufacture an entry direction.

## Frozen H1 structural trend state

### Confirmed swings

- A swing high is strictly higher than the two completed H1 highs on each side.
- A swing low is strictly lower than the two completed H1 lows on each side.
- It becomes known only when the second right-hand H1 bar closes.

### Bullish transition

1. A completed H1 bar trades strictly below the latest known swing low and
   closes back above that level. This arms a bullish liquidity-sweep state.
2. The opposite reference is the latest known swing high at the sweep time.
3. Within the next 12 completed H1 bars, a bar must close strictly above that
   reference with true range at least ATR14(H1), body at least 50% of range, and
   its close in the upper third.
4. Confirmation creates a bullish structural state. The protected low is the
   minimum low from sweep through confirmation; the broken swing high is the
   breakout level; and the confirmation high is the first impulse extreme.

Bearish transition is the exact mirror.

### Persistence, update, invalidation, and H4 veto

- In a bullish state, later confirmed higher H1 swing lows may raise—but never
  lower—the protected low. New completed highs extend the impulse extreme and
  refresh its timestamp. Bearish treatment is mirrored.
- A bullish state ends on a completed H1 close strictly below its protected low,
  on a confirmed bearish transition, or after 15 calendar days without an
  extension of its impulse extreme. Bearish treatment is mirrored.
- The identical transition algorithm is calculated on H4 bars. A confirmed
  opposite H4 state vetoes a trade; a same-direction or neutral H4 state is
  permitted.
- The H1 state direction must equal the pre-session fundamental direction.

These states are `CALCULATED/INFERRED`; a liquidity sweep is observed price
behaviour, not proof of an institution or its motive.

## Frozen retracement locations

All locations are fixed at the session open and known before a trigger:

1. `BROKEN_STRUCTURE_ZONE`: the transition breakout level plus or minus 0.15
   ATR14(H1).
2. `IMPULSE_RETRACEMENT_ZONE`: 38.2% through 78.6% retracement of the active
   protected-swing-to-impulse-extreme range.
3. `ASIA_EXTERNAL_LIQUIDITY`: the completed 00:00-08:00 local Asian range.

Prior-day high/low, Asia high/low, active impulse extreme, and confirmed H1
swings known at entry form the eligible external-liquidity target registry.
Future-formed levels are prohibited.

## Frozen M5 continuation setups

M5 bars are deterministic aggregates of sealed M1 observations. ATR means
ATR20(M5). Only the first occurrence of each setup per session-date is retained.

### `STRC_BREAK_LEVEL_RETEST_REJECTION`

- Price touches the broken-structure zone without closing beyond the active
  protected structural invalidation.
- The confirming M5 candle points in the trend direction, has body at least 50%
  of its range, range at least 0.80 ATR, and closes in the directional outer
  third.

### `STRC_IMPULSE_ZONE_INTERNAL_BOS`

- Price enters the frozen impulse-retracement zone.
- Within the next six completed M5 bars, a trend-direction candle closes beyond
  the directional extreme of the three completed M5 bars immediately preceding
  the first zone touch.
- The confirming candle has body at least 40% of range and closes within the
  directional outer 40%.

### `STRC_ASIA_SWEEP_CONTINUATION`

- In an active bullish state, an M5 candle trades below the frozen Asia low and
  closes back above it; bearish is mirrored at the Asia high.
- It has a trend-direction body at least 40% of range and closes in the
  directional outer third without closing beyond structural invalidation.

No generic pin-bar, engulfing, institutional-order, or smart-money label is
permitted.

## Frozen execution and no-trade rules

- Entry is the next M1 open after the completed M5 confirmation.
- Long stop is 0.15 ATR20(M5) below the minimum low from first retracement touch
  through confirmation; short is mirrored.
- Risk distance must be 0.75 through 3.00 ATR20(M5), inclusive.
- Baseline round-trip cost is $0.47 per ounce. The trade is rejected when this
  exceeds 0.20R, preventing transaction costs from dominating the structural
  risk unit.
- Target is the nearest directional external-liquidity level known at entry
  offering at least 1.50R. A farther objective is capped at 3.00R. No qualifying
  objective means no trade.
- Stop and target are live from the entry bar. If both occur in one M1 bar, stop
  is assumed first.
- Otherwise exit at the earlier of 180 minutes or 13:00 local.
- Cost stresses are 1.5x and 2.0x. Account diagnostics use $10,000, fixed 0.5%
  planned risk, 100 ounces per standard lot, 0.01 lot step, and no same-session
  compounding.
- At most one portfolio trade per session-date is retained: earliest signal,
  then lexical setup ID.

Outcome-blind sensitivity diagnostics use stop buffers 0.10, 0.15, and 0.20 ATR
with all other rules fixed. Only the 0.15 base specification may create a
candidate; sensitivity cannot rescue it.

## Outcomes and evaluation

- Primary endpoint: baseline-cost net R.
- Report gross/net expectancy, win rate, average win/loss, profit factor,
  first-passage exit, MFE, MAE, holding time, costs, PnL, drawdown, consecutive
  losses, monthly Sharpe/Sortino where meaningful, annual/session/side/block
  stability, sensitivity, and cost stress.
- Use deterministic 5,000-resample session-date cluster bootstrap.
- Apply Holm correction across the three setups within each session.
- Chronological blocks are 2021-08-01–2022-06-30, 2022-07-01–2023-03-31,
  2023-04-01–2023-12-31, and 2024-01-01–2024-12-31.

A setup needs at least 40 executed trades, 30 dates, 20 ISO weeks, 10 bullish
and 10 bearish trades, and eight trades in each of 2022, 2023, and 2024.

A development candidate passes only when all gates pass:

- positive net expectancy and strictly positive 95% bootstrap lower bound;
- Holm-adjusted one-sided p at most 0.05;
- profit factor at least 1.25;
- at least three positive chronological blocks and none below -0.10R;
- supported 2022, 2023, and 2024 and both directions have positive expectancy;
- 1.5x cost expectancy remains positive with profit factor at least 1.10;
- no single trade contributes more than 35% of positive total R;
- account maximum drawdown is at most 15%; and
- the 0.10/0.20 ATR stop-buffer sensitivity does not reverse the base effect in
  both neighbouring specifications.

Verdicts are `PROVISIONAL_UNVALIDATED_EDGE`, `REJECT`, and `SUPPORT_FAIL`.
At most three candidates per session may advance; zero is acceptable.

## GC incremental order-flow diagnostic

On the existing 188 covered dates only, report whether the sealed same-direction
GC aggression/OFI/absorption/depth events in the preceding five minutes add net
expectancy. Require 20 confirmed trades on 15 dates and 30 known-unconfirmed
trades on 20 dates before any claim. GC absence outside coverage is unknown.

## Forward and prospective policy

- Freeze development candidates before opening 2025/2026.
- Apply them once and unchanged to 2025 and 2026 through 2026-07-29.
- Never pool exposed periods or use them to retune.
- Initialize an append-only prospective paper ledger before the next eligible
  session. Never backfill a missed decision.

## Integrity and stopping

Primary and reference implementations must reproduce exact state identities,
signals, entries, paths, trades, statistics, and artifact checksums. Record all
negative and unsupported results. Stop only for a genuine source/integrity
blocker or potential charge. The final verdict must distinguish directional
information from an economically tradable edge.
