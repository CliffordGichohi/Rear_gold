# Gold Matched Human Coherent Auction Geometry and Management Calibration Protocol V1

## Purpose and evidence boundary

This protocol refines the stop and target together and then measures whether point-in-time level response can retain more favourable movement than a mandatory first-target exit.

Every prior result and rejection remains unchanged. The 30 matched cases and their outcomes are already exposed. This study is therefore `POST_RESULT_ZERO_CREDIT_CALIBRATION`; it may explain and encode the operator's intended semantics, but it cannot validate an edge. Calendar 2025 and 2026 remain untouched.

The population is all 16 sealed human LONG decisions in `CBR-2022-001` through `CBR-2022-030`. No case may be removed because of its outcome.

## Point-in-time source policy

- Structural construction may use only completed M15, M5 and H1 candles whose `available_at` is no later than the relevant decision or management timestamp.
- Entry, actual fill, original operator-drawn H1 target, original UTC-day deadline and recorded per-ounce cost remain unchanged.
- Position size is recalculated at the actual fill as `floor($50 / initial_stop_distance)` whole ounces.
- The same M1 path, one-minute execution timing, stop-first same-bar convention and round-trip cost are retained.
- A management decision becomes executable only at the first M1 open after its completed-candle evidence is available.

## Frozen structural primitives

### ATR and confirmed swings

- ATR is the arithmetic mean of the latest 14 true ranges, including the current completed candle.
- A confirmed swing uses two completed candles on each side. The pivot must be the unique extreme in the five-candle window.
- A swing must have prominence of at least `0.25 * ATR`, with a two-tick minimum of `$0.02`.
- A swing becomes available only when the second right-hand candle completes.

### Bullish M15 structural break and protected low

- On each completed M15 candle, locate the latest confirmed M15 swing high available before that candle opened.
- A bullish structural break occurs when the candle closes above that swing high by more than `max(0.10 * M15 ATR, $0.02)`.
- The protected low is the latest confirmed M15 swing low available before the breaking candle opened.
- A broken swing high may create only one break event.
- At the trade decision, select the most recent bullish break whose protected low has not subsequently been invalidated by a completed M15 close below `protected_low - max(0.10 * break_ATR, $0.02)`.
- The protective stop is that buffered protected-low level. The intended entry and actual fill must both remain above it. Otherwise the case is a point-in-time structural no-trade.

This stop represents the level at which the most recently confirmed bullish auction transition is no longer intact. It is not an assertion that every wick at the level observes institutional liquidity.

## Frozen pre-entry liquidity-level registry

Build the registry before path simulation from levels available at the decision:

1. confirmed M15 swing highs;
2. confirmed H1 swing highs;
3. the sealed operator-drawn H1 target.

For calculated swings:

- Retain only levels that have not been touched again by a completed candle of their own timeframe after their confirmation and before the decision. Name this state `UNTOUCHED_AFTER_CONFIRMATION`; do not call it observed unconsumed liquidity.
- After the actual fill, retain only levels above `fill + max(0.10 * decision_M15_ATR, $0.02)`.
- Merge prices inside that engagement band into one zone, retaining H1 over M15 and the operator-drawn H1 target over a calculated swing at the same price.
- Sort the immutable registry from nearest to farthest above the fill. Do not add future-formed levels.

The nearest registered level is the first meaningful decision level. A level inside the engagement band is already being auctioned at the fill and is not a fresh destination.

## Frozen comparison tracks

### Track A — original H1 fixed-target control

Use the reconstructed protected-low stop and exit the full position at the original operator-drawn H1 target, the stop, or the original deadline.

### Track B — first meaningful level fixed exit

Use the same stop and exit the full position at the first registered decision level, the stop, or the original deadline. If no calculated level precedes the original H1 target, the original target is the first level.

### Track C — full structural runner

- Before the first decision-level touch, retain the initial protected-low stop.
- After a level is first touched, evaluate completed M5 candles beginning strictly after that touch.
- Acceptance requires two consecutive M5 closes above `level + max(0.05 * decision_M15_ATR, $0.02)`.
- Rejection occurs first if an eligible M5 candle closes below `level - max(0.05 * decision_M15_ATR, $0.02)`.
- If neither disposition occurs within the first three eligible completed M5 candles, classify `NO_ACCEPTANCE` and exit at the next M1 open.
- Rejection or no-acceptance exits the full position; there is no hindsight partial.
- Acceptance preserves the full position, retires that level and activates the next higher frozen level.
- After the first accepted level, each new completed bullish M5 structural break may raise the stop to its buffered protected M5 low. The stop may never move downward.
- If an accepted level later receives a completed M5 close below its lower buffer before a higher structural trail becomes active, exit at the next M1 open as `FAILED_ACCEPTANCE`.
- After the highest frozen level is accepted, the position continues under the structural trail until stopped or the original deadline. There is no fixed terminal profit target.

No breakeven rule, partial exit, future maximum, later-formed liquidity level or outcome label is available to Track C.

## Non-tradable ceiling

For attribution only, calculate the maximum favourable excursion available before the initial structural stop or deadline, with the stop treated first on an ambiguous M1 candle. This is `STOP_FEASIBLE_MFE_ORACLE`; it is not a strategy and receives no economic or validation credit.

## Required reporting

Report per case and aggregate:

- structural eligibility and exact failure reason;
- protected low, stop, initial risk and whole-ounce quantity;
- immutable decision-level registry and first level;
- planned H1 reward/risk;
- Track A, B and C resolution, net R and dollars;
- accepted, rejected and timed-out level counts;
- trail changes and exit reason;
- stop-feasible oracle R and capture efficiency;
- win rate, expectancy, profit factor, maximum drawdown and total R;
- the exact cases improved or degraded by management.

Do not select a winning track, threshold or parameter from this exposed sample. Independently reproduce all outputs byte-for-byte. Any later edge claim requires a frozen policy and fresh outcome-hidden or prospective cases.

