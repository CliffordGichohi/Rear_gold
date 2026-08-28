# Gold Point-in-Time Swing and Liquidity-Shift Automation Contract V1

## Purpose

Automate the mechanical work of locating confirmed swings, inferred auction-shift zones, retests, and paper-order proposals without claiming that the resulting policy is a validated edge.

This is an engineering and prospective-calibration branch. It preserves every previous research result, rejection, artifact, and seal. It does not reopen rejected strategies or alter the matched human replay result.

## Scope and safety

- Inputs are completed XAUUSD candles and point-in-time fundamental context already available to the platform.
- No paid data may be acquired.
- No live broker order may be submitted.
- Outputs are chart evidence and `PAPER_PROPOSAL` state-machine records only.
- No historical PnL, strategy optimization, or 2025/2026 outcome inspection is authorized by this contract.
- A detector can automate a rule; it cannot establish profitability.

## Epistemic classifications

- Source candles and spreads are `OBSERVED` broker data.
- Confirmed pivots, ATR, structure breaks, order prices, and risk geometry are `CALCULATED`.
- Liquidity pools, auction-shift zones, macro alignment, and expected participant response are `INFERRED`.
- Missing or stale inputs remain `UNKNOWN`; they are never silently substituted.
- A price-derived liquidity zone must never be described as observed institutional inventory or resting exchange depth.

## Frozen completed-candle policy

- One-minute source bars must have `close_time <= as_of` and `available_at <= as_of`.
- Missing source minutes are not interpolated.
- M5, M15, H1, and H4 aggregates are eligible only when every expected source minute exists.
- Every event records both the historical event timestamp and the later timestamp at which it became knowable.

## Frozen swing definition

- Strict two-left/two-right pivots.
- Minimum prominence: `0.25 * ATR14`, with a floor of two ticks.
- A pivot becomes available only when the second right-side candle closes.
- Highs are classified as `SWING_HIGH`, `HIGHER_HIGH`, `LOWER_HIGH`, or `EQUAL_HIGH`.
- Lows are classified as `SWING_LOW`, `HIGHER_LOW`, `LOWER_LOW`, or `EQUAL_LOW`.
- H1/H4 context is `BULLISH` only with a higher high and higher low, `BEARISH` only with a lower high and lower low, `RANGE` only with equal high and equal low, and otherwise `MIXED_OR_TRANSITIONING`.

## Frozen M15 auction-shift zone definition

An inferred zone is created only after one completed M15 displacement candle:

1. True range is at least `1.80 * ATR14`.
2. Candle body is at least `65%` of its high-low range.
3. The close breaks the most recent eligible confirmed M15 swing in its direction by at least `0.10 * ATR14`, with a floor of two ticks.
4. The broken swing was confirmed no later than the displacement candle open.
5. The zone origin is the most recent opposite-colour completed M15 candle among the prior four candles. Absence of such a candle produces no zone.

For a bullish zone:

- distal boundary = origin low;
- proximal boundary = maximum of origin open and close.

For a bearish zone:

- proximal boundary = minimum of origin open and close;
- distal boundary = origin high.

The historical origin candle may be drawn on the chart, but the zone is not active until the displacement candle closes. Duplicate zones from the same broken swing are prohibited.

## Frozen zone lifecycle

- `ACTIVE_UNTOUCHED`: created and not revisited.
- `TOUCHED`: a later eligible candle overlaps the zone.
- `RETEST_CONFIRMED`: after a touch, an M5 candle closes back through the proximal boundary in the zone direction, has the same body direction, and has body/range of at least `55%`.
- `INVALIDATED`: an M15 close crosses the distal boundary against the zone by more than `0.10 * creation ATR14`.
- `EXPIRED`: 460 completed M15 bars elapse without an earlier invalidation.
- Once invalidated or expired, a zone cannot rearm.

Touches and confirmations outside London or New York may update the technical lifecycle but are not paper-entry eligible.

## Frozen paper-entry proposals

Exactly two transparent proposal families are emitted for technical comparison. They are not live orders.

### `RETEST_LIMIT_V0_1`

- Entry = zone midpoint.
- Activation requires the midpoint to trade during an eligible London or New York session before invalidation or expiry.
- Stop = distal boundary plus a `0.10 * creation ATR14` adverse buffer.
- Quantity = floor of `$50 / absolute(actual entry - stop)` whole ounces.

### `CONFIRMED_RETEST_V0_1`

- Trigger = the first eligible M5 retest confirmation.
- Entry reference = the first complete M1 open after the confirming M5 close.
- Stop and quantity use the same rules, recalculated from the actual entry reference.

For both families:

- Target = nearest opposing M15, H1, or H4 confirmed swing that was already knowable at the entry timestamp.
- The target must offer at least `1.25R`; otherwise the proposal is `BLOCKED_TARGET_GEOMETRY`.
- Fundamental direction must be known and agree with the proposal direction for `PAPER_READY`; disagreement is `COUNTER_MACRO`, and neutral/unknown context is `WAITING_MACRO`.
- A stored fundamental snapshot may be used only when it was available no later than the trigger and is no more than 24 hours old at that trigger; later snapshots are never backfilled.
- Abnormal or unknown execution liquidity prevents `PAPER_READY` but does not delete the technical event.
- Risk is calculated from the actual paper fill reference, preventing the matched replay's pre-fill sizing mismatch.

## Outputs and auditability

Every swing, zone, and proposal must expose:

- stable identity;
- direction and timeframe;
- event timestamp and `detected_at` timestamp;
- price boundaries;
- lifecycle state;
- epistemic status;
- exact method and configuration version;
- supporting source-bar identities;
- invalidation and expiry;
- macro relationship;
- target source;
- point-in-time data hash.

## Engineering certification gates

- Synthetic no-look-ahead proof for pivots and zones.
- No zone active before its displacement close.
- No target or macro fact available after entry may be used.
- Exact deterministic checksum across two independent invocations.
- DST-aware London/New York eligibility.
- Position size computed from actual paper entry-to-stop geometry and never above $50 planned risk.
- Existing market-structure and replay regression tests must remain passing.

## Next research gate

After engineering certification, the detector must first be visually calibrated against a bounded sample without outcomes. Only after the markings match the intended method may a new contract freeze fresh case identities and compare the two entry families. No result from this engineering branch receives edge-validation credit.
