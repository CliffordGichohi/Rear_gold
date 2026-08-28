# Gold Coherent-Auction Complete Correction Rulebook V1

Status: `DRAFT_FOR_USER_CONFIRMATION_NOT_AUTHORIZED_FOR_OUTCOME_CALCULATION`

## 1. Purpose and evidence boundary

This document converts the exposed matched-human review into one deterministic, point-in-time correction package. It is the rulebook that must be reviewed before any new performance calculation.

It does **not** claim that the approximately `+11R` post-hoc ceiling was achieved. That ceiling combined hindsight direction labels and selective case repairs. The purpose here is to replace those hindsight choices with rules that can be applied to every case without knowing the result.

The following remain unchanged:

- every previous result, rejection, artifact, and seal;
- the corrected fixed-H1 result of `+1.79318807R` as the exposed control;
- the 30 exposed January-February 2022 replay cases and their zero validation credit;
- the unopened 50-case coherent-auction block;
- the calendar-2025 and calendar-2026 locks;
- no acquisition, charge, or paid source access.

No outcome path, PnL, hit rate, or case disposition may be calculated under this draft. Approval must freeze a final copy first.

## 2. Reference-Book interpretation

The Reference Book defines liquidity as the market's ability to absorb orders with limited price disturbance, not as a horizontal line. A chart level is therefore an **inferred decision/liquidity zone**, never an observed institutional order. Price acceptance, rejection, displacement, and structure are calculated evidence about the auction around that zone.

The rulebook preserves the book's hierarchy:

1. macro and fundamentals provide directional context;
2. H4/H1 structure and pre-existing decision zones provide location and room;
3. M15/M5 completed-candle behaviour provides the trigger;
4. the structure controlling the trigger provides invalidation;
5. the next pre-existing opposing H1 decision zone provides the main destination;
6. bias, trigger, invalidation, and risk remain separate.

No macro score directly creates a trade. No lower-timeframe signal silently overrides higher-timeframe damage or an unresolved event auction.

## 3. Scope of the first regression

After approval, the first calculation is a matched-case correction regression, not a new strategy search:

- population: the same 16 sealed human LONG decisions in `CBR-2022-001` through `CBR-2022-030`;
- checkpoint: each original sealed human decision timestamp;
- unchanged: original decision direction, order identity, actual fill if filled, session deadline, source costs, and one-position policy;
- changed only by this rulebook: eligibility, thesis family, trigger geometry, structural stop, target construction, and family-specific management;
- a rejected original trade contributes `0R`, remains reported, and cannot be replaced by another trade;
- no new entry may be searched for later in the case;
- no rule may mention or branch on a case alias.

This makes the later comparison interpretable: it asks whether the complete observable correction package improves the same opportunities that produced the `+1.79318807R` control.

## 4. Common point-in-time primitives

All rules are symmetric. Let `D = +1` for LONG and `D = -1` for SHORT. A move is aligned when `D * (new_price - old_price) > 0`.

### 4.1 Candle availability

- A candle is usable only when it is complete and `available_at <= checkpoint`.
- Weekly, daily, H4, H1, M15, M5, and M1 use the existing timestamp and DST rules.
- ATR(14) is the arithmetic mean of the latest 14 completed true ranges, including the latest completed candle.
- A threshold's ATR belongs to the candle and timeframe on which the condition is decided.
- The price tick floor is `$0.02` for XAUUSD.

### 4.2 Confirmed swing

A swing is a strict five-bar fractal:

- two completed candles on the left and two on the right;
- a HIGH is strictly higher than all four neighbours; a LOW is strictly lower;
- prominence is at least `0.25 * ATR(14)`, with a `$0.02` floor;
- it becomes available only when the second right-hand candle completes;
- equal extremes do not qualify.

### 4.3 Break, acceptance, rejection, and retest

- Break buffer: `max(0.10 * ATR(14), $0.02)`.
- A structural break requires a completed close beyond a previously confirmed swing plus the break buffer.
- Acceptance requires two consecutive completed candles beyond the same level and buffer. The level must have been available before the first confirming candle opened.
- Rejection requires a wick beyond the buffered level followed by a completed close back on the prior side of the unbuffered level.
- A held retest occurs after acceptance when price touches within `0.25 * ATR(14)` of the level and the completed candle closes on the accepted side.
- One wick, one unfinished candle, or one transient tick is never acceptance.

### 4.4 Decision-zone registry and lifecycle

Eligible inferred decision zones are confirmed H1/H4 swing highs and lows, completed Asia/London session boundaries, and a fixed balance boundary defined below. M15 zones are internal execution references, not the final H1 destination.

Levels within `max(0.10 * ATR(14), $0.02)` are merged. Priority is H4, then H1, then completed session boundary, then M15. Each zone has one lifecycle:

- `ACTIVE_UNTOUCHED`: confirmed and not revisited after confirmation;
- `ACTIVE_ENGAGED`: touched or rejected, but not accepted through;
- `CONSUMED_ACCEPTED`: accepted through in the trade direction; it no longer blocks room in that direction;
- `REACTIVATED_REVERSE`: after consumption, two completed closes accept back through it in the opposite direction; it becomes an active opposing zone again.

An H4 range percentile is descriptive only. It is never a standalone entry filter. A high percentile is safe only when the nearby opposing zone has already been consumed and another valid destination remains ahead.

Acceptance is measured one execution layer below the source level so that it represents sustained session trading without being reduced to tick noise:

- H4 zone: two completed H1 closes;
- H1 or completed-session zone: two completed M15 closes;
- M15 zone: two completed M5 closes.

The acceptance buffer uses ATR(14) from that acceptance timeframe. A held retest is measured on the same acceptance timeframe.

### 4.5 Fixed balance

A candidate H1 or H4 balance box is the latest block of 20 completed candles satisfying all of:

- width no greater than `5.0 * ATR(14)` at the block's final candle;
- at least two confirmed highs and two confirmed lows inside the box;
- no accepted close outside its fixed high or low after the box first qualified.

The box boundaries remain fixed after qualification. The box expires on accepted breakout or after 40 additional completed candles, whichever occurs first. The lower quartile is normalized location `[0.00, 0.25]`; the upper quartile is `[0.75, 1.00]`.

A balance controls thesis classification only when price has engaged an outer quartile or has completed an accepted breakout/retest of that box. An unrelated broad balance containing price in its interior does not suppress a later valid directional-progression test. If both H4 and H1 boxes qualify at the same checkpoint, H4 has precedence only when its own boundary event qualifies; otherwise the qualifying H1 box controls.

## 5. Universal blockers

These gates run before thesis classification. The first failure ends the original decision as `NO_TRADE`:

1. required price, timestamp, or critical-context lineage is `UNKNOWN` or technically unavailable;
2. actual fill, structural stop, or forward target cannot be constructed from pre-decision information;
3. target is not beyond fill in direction `D` after costs;
4. whole-ounce size under the `$50` maximum planned loss is zero;
5. price is already inside an `ACTIVE_ENGAGED` opposing H1/H4 zone and no acceptance/retest through it exists;
6. the event-auction lock below is active;
7. the original decision is presented as continuation while the macro state is strongly opposed under Section 8.

### 5.1 Event-auction lock

Tier-1 events are CPI, core CPI, PCE, core PCE, NFP/payrolls, unemployment, FOMC rate decisions, FOMC projections, and the Fed press conference.

- No new trade from `T-15 minutes` through completion of the first `T+15 minute` range.
- From `T+15 minutes` to the original session deadline, eligibility requires two completed M5 closes beyond the fixed first-15-minute event range by `0.10 * M5 ATR(14)`, followed by the first held M5 retest.
- Until that sequence completes, the event auction is `UNRESOLVED`.
- The rule applies to both macro-aligned and counter-macro trades.

## 6. Higher-timeframe thesis classifier

Exactly one thesis family is assigned by the following ordered decision tree. There is no fallback to a more favourable family.

### 6.1 Structural damage test

For proposed direction `D`, H4 is damaged against `D` when the most recent protected H4 swing in direction `D` is breached by either:

- one opposing H4 displacement candle with true range at least `1.25 * H4 ATR(14)`, body/range at least `0.60`, and a close beyond the protected swing by `0.05 * H4 ATR(14)`; or
- two consecutive completed H4 closes beyond the protected swing by `0.10 * H4 ATR(14)`.

Damage remains active until H4 itself accepts back through the broken structural reference and holds its first H4 retest.

If H4 damage is active, the proposed trade cannot be labelled continuation. It proceeds only as `STRUCTURAL_REPAIR` if all of the following are true:

1. H1 or M15 has broken the latest opposing confirmed swing in direction `D`;
2. two completed candles on that repair timeframe accept beyond the broken swing;
3. the first held retest has completed;
4. the broken H4 reference or another active opposing H1 level remains ahead as a positive target.

Otherwise the decision is `NO_TRADE_H4_DAMAGE_UNREPAIRED`.

### 6.2 Active-balance test

If no active damage controls the decision and a qualifying H1/H4 balance boundary event controls price:

- `RANGE_ROTATION` is assigned only when price engages the outer quartile on the entry side, rejects or sweeps that boundary, then breaks and retests lower-timeframe structure toward the interior;
- `CONTINUATION_WITH_ROOM` is assigned only after an accepted breakout of the fixed balance boundary in direction `D` and the first held retest outside it;
- a trade pointing outward from an unaccepted upper/lower balance boundary is rejected;
- an interior trade without a completed boundary event is rejected.

### 6.3 Directional-progression test

If neither damage nor active balance controls the decision, `CONTINUATION_WITH_ROOM` requires all of:

1. H4 or H1 has an active structure break in direction `D` whose protected swing remains intact;
2. the latest confirmed high/low sequence is aligned with `D`, or the active break is later than the last opposite structure shift;
3. the pullback has not accepted through the protected structural swing;
4. no `ACTIVE_ENGAGED` opposing H1/H4 zone blocks the path;
5. the next active opposing H1 zone, or H4 zone when H1 is absent, remains ahead.

If these conditions fail, the decision is `NO_TRADE_UNCLASSIFIED_AUCTION`.

### 6.4 Precedence summary

1. universal blocker;
2. H4 damage -> repair or no trade;
3. active balance -> inward rotation, accepted breakout continuation, or no trade;
4. intact directional progression with room -> continuation;
5. otherwise no trade.

## 7. Trigger geometry and stop construction

The **thesis family** describes why/where the trade exists. The **trigger geometry** describes the local auction that controls invalidation. They are separate fields.

The setup-formation timestamp is the latest `available_at` among the thesis state, controlling level/balance, macro snapshot, and event state used by the decision. Only triggers beginning after that timestamp are eligible.

Only the earliest qualifying trigger that remains live at the sealed decision checkpoint is used. When two trigger families complete at the same timestamp, precedence is sweep/reclaim, M15 break/retest, then M5 internal rotation. A trigger expires after 12 completed M5 candles, an opposing structural break, invalidation of its controlling level, or consumption of its destination, whichever occurs first. No later trigger replaces a failed original decision in the matched-case regression.

### 7.1 `BOUNDARY_SWEEP_RECLAIM`

Required for a range rotation and allowed for structural repair:

1. price trades beyond the active boundary by at least `0.05 * M15 ATR(14)`;
2. the same or next completed M15 candle closes back inside the unbuffered boundary;
3. a completed M5 candle then breaks the latest opposing confirmed M5 swing by `0.05 * M5 ATR(14)`, with true range at least `0.80 * M5 ATR(14)` and body/range at least `0.55`;
4. the first held M5 retest completes within 12 M5 candles.

Stop: beyond the controlling H1/M15 balance boundary or sweep extreme, whichever is farther adverse, plus `0.10 * M15 ATR(14)`.

### 7.2 `M15_BREAK_RETEST`

1. a completed M15 candle breaks the latest opposing confirmed M15 swing by `0.05 * M15 ATR(14)`;
2. true range is at least `0.90 * M15 ATR(14)` and body/range at least `0.55`;
3. the first held M5 retest completes within 12 M5 candles.

Stop: beyond the M15 protected swing or transition origin, whichever is farther adverse, plus `0.10 * M15 ATR(14)`.

### 7.3 `M5_INTERNAL_ROTATION_IN_M15_BALANCE`

This trigger is permitted only when an M15 balance was already identifiable before the M5 impulse. It prevents an M5 entry from inheriting an unjustifiably tight M5 stop.

1. M15 is inside a fixed 20-bar balance with at least two confirmed highs and lows;
2. an M5 candle breaks the latest opposing confirmed M5 swing by `0.05 * M5 ATR(14)`;
3. true range is at least `0.80 * M5 ATR(14)` and body/range at least `0.55`;
4. the first held M5 retest completes within 12 M5 candles.

Stop: beyond the controlling M15 balance boundary or the M15 transition origin, whichever is farther adverse, plus `0.10 * M15 ATR(14)`. The latest M5 swing alone is never the stop.

### 7.4 Geometry validity

- Fill, stop, and target must be ordered correctly in direction `D`.
- The stop must still be structurally valid at the actual fill.
- The selected destination must still be active and ahead at the actual fill.
- Any internal M15 level already accepted through is marked consumed and skipped; it is not mistaken for the final target.
- Quantity is `floor($50 / planned_loss_per_ounce)`, including the frozen adverse entry/exit costs in planned loss. Zero quantity means no trade.

## 8. Fundamental and macro context

Use the existing point-in-time normalized gold score, confidence, data-quality flags, reaction function, and event record. No later revision is permitted.

- `ALIGNED`: score `>= +20` for LONG or `<= -20` for SHORT.
- `OPPOSED`: score `<= -20` for LONG or `>= +20` for SHORT.
- `NEUTRAL_OR_CONFLICTED`: score is strictly between `-20` and `+20`.
- `UNKNOWN`: the score is unavailable, data quality is below 60, or either the real-yield/USD critical context is unavailable.

Application:

- `UNKNOWN` blocks all trades; it is not silently converted to neutral.
- `CONTINUATION_WITH_ROOM` permits only `ALIGNED` or `NEUTRAL_OR_CONFLICTED` macro context.
- `RANGE_ROTATION` and `STRUCTURAL_REPAIR` may be `OPPOSED`, but must be labelled `TACTICAL_COUNTER_MACRO`; they use their bounded family target and are never eligible for the continuation runner.
- Macro agreement cannot override structural damage, an active opposing zone, or the event lock.

## 9. Target construction

Target selection happens before path access.

### 9.1 Continuation

- Core destination: nearest active opposing H1 zone ahead; use H4 only if no H1 zone exists.
- Consumed internal M15 zones are decision points, not final targets.
- A target inside or behind the fill is invalid.

### 9.2 Range rotation

- First realization: fixed balance midpoint.
- Final destination: opposite fixed balance boundary.
- If the midpoint is not ahead at entry, the trade is rejected as late.

### 9.3 Structural repair

- Destination: the nearer of the broken H4 structural reference and the next active opposing H1 zone, provided it is ahead.
- This is a repair target, not a claim that the full H4 trend has reversed.

## 10. Family-specific management

The rejected universal `+1R -> M5 break -> full exit` overlay is not reused.

### 10.1 Continuation management

Before the core target:

- retain the original structural stop;
- after the path first reaches `+1.0R`, exit the complete position only after a genuine opposing M15 structure shift: a completed M15 close beyond the latest confirmed protected M15 swing by `0.10 * M15 ATR(14)`;
- execute that structural exit at the next M1 open with frozen adverse costs;
- an M5 rejection or M5 swing break alone cannot exit the trade.

At the H1 target:

- close the whole-ounce core of `quantity - floor(0.20 * quantity)` at target;
- if the 20% runner rounds to zero, close all at target;
- retain the runner only if the target-touch M15 candle completes with acceptance beyond target by `0.10 * M15 ATR(14)`;
- otherwise close the runner at the next M1 open;
- an accepted runner trails the latest confirmed protected M15 swing plus the `0.10 * M15 ATR(14)` adverse buffer and exits on stop or original deadline.

### 10.2 Range-rotation management

- At first touch of the fixed balance midpoint, close `ceil(0.50 * quantity)` whole ounces.
- Move the remainder's stop only after a completed M15 close on the destination side of the midpoint. The new stop is `entry + D * total_frozen_round_trip_cost_per_ounce`; the normal adverse stop-fill slippage remains applied, so the execution engine solves the submitted stop level required to produce that net fill.
- Exit the remainder at the opposite balance boundary, structural stop, a completed opposing M15 structure shift, or the original deadline.
- No continuation runner is permitted.

### 10.3 Structural-repair management

- Retain the structural stop until target or genuine opposing M15 structure shift.
- Exit 100% at the frozen repair destination.
- No continuation runner is permitted unless a later, separately observable setup is created; the matched-case regression permits no second setup.

### 10.4 Universal execution rules

- Maximum planned loss: `$50` on the `$10,000` reference account.
- Whole-ounce quantity only.
- Existing source spread when available; otherwise `$0.20`.
- Entry/market/stop slippage: `$0.05` adverse.
- One-minute execution latency for completed-candle signals.
- Same-M1-bar ambiguity is stop first.
- One open position per case; no pyramiding, direction switch, hidden re-entry, or deadline extension.
- Each ounce incurs the frozen round-trip cost exactly once.

## 11. Why this is not a disguised winner filter

The rules do not use H4 percentile alone, macro agreement alone, or a case-specific outcome:

- the `0.80` H4-location shortcut is forbidden because a high-location winner existed;
- a nearby level blocks only while it remains active and unaccepted; accepted/consumed levels do not block the next auction;
- a bearish H4 state does not automatically forbid a long; it changes the thesis to structural repair or range rotation and bounds the target;
- strongly opposing macro blocks continuation but not a fully specified tactical range/repair response;
- a tight M5 stop cannot control an entry whose actual setup is an M5 rotation inside an M15 balance;
- management uses M15 structural failure, not the rejected universal M5 noise exit.

## 12. Exposed-case design audit (not a result)

This table records which general rule is intended to address each already-known failure mode. It does not assert how the deterministic implementation will classify a case.

| Known issue | General rule intended to address it |
|---|---|
| completed bearish H4 damage was called a normal bullish pullback (`003`, `019`) | H4 damage has precedence; continuation is prohibited until the specified repair sequence exists |
| long continuation entered an unaccepted upper H4/balance boundary (`007`, `009`) | active-zone lifecycle and outward-from-balance gate |
| high H4 location nevertheless continued (`024`) | percentile is not a gate; an accepted/consumed nearby level permits the next active destination |
| local recovery worked inside bearish/transitional H4 (`020`, `023`, possibly `027`) | structural-repair/range family instead of false H4-continuation label |
| unresolved CPI auction (`026`) | fixed Tier-1 event-range acceptance lock |
| correct range response round-tripped (`005`) | range midpoint realization plus family-specific structural protection |
| correct bullish direction gave back open profit (`013`, `014`) | opposing M15 shift after +1R, not a universal M5 rejection exit |
| M5 rotation inside M15 balance received a generic tight stop (`030`) | trigger geometry is separate; stop belongs beyond the controlling M15 balance/transition |
| H1 target winners later extended (`002`, `006`, `015`, `027`) | bounded 20% runner only after completed M15 acceptance beyond the H1 target |

## 13. Required pre-test audit and later comparison

Before any performance run, an implementation must prove on synthetic cases:

1. no future-formed swing is available early;
2. acceptance requires two completed candles;
3. a consumed level is skipped while an engaged unaccepted level blocks;
4. H4 damage outranks a stale bullish trend label;
5. active balance routes inward rejection and accepted breakout differently;
6. M5 internal rotation uses M15 invalidation;
7. event lock cannot be bypassed by macro or trigger state;
8. LONG/SHORT symmetry;
9. deterministic output and identical primary/reference hashes.

Only after user approval may the exposed matched-case regression report:

- control and corrected result case by case;
- exactly which trades were admitted or rejected and which pre-decision facts caused it;
- thesis family, trigger geometry, stop, target, and management lifecycle;
- net R, PF, drawdown, costs, and sensitivity only to the already frozen rules;
- whether valid winners were lost as well as whether losers were avoided;
- how much of the post-hoc `~11R` ceiling was actually captured.

No result may be described as an edge. If the exposed regression is coherent, a separate approval must decide whether to discard/rebuild the unopened 50-case contract under this complete policy or keep that block under its original frozen policy.
