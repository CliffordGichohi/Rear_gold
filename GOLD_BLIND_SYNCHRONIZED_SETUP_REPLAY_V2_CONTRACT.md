# Gold Blind Synchronized Setup Replay V2 Contract

Status: `FROZEN_BEFORE_V2_VALUE_MATERIALIZATION_OR_IMPLEMENTATION`

Authorized: 2026-08-14

Predecessor: Gold Blind Discretionary Replay V1 UI Amendment F, with zero human decisions and next case `P-001`.

## 1. Objective and boundary

V2 tests the human's ability to recognize and execute a setup as it develops after a certified point-in-time checkpoint. It is a practice-only engineering and usability stage with zero research or validation credit.

- Population: exactly the existing twenty `P-001` through `P-020` practice cases.
- Initial shared cursor: relative minute `0`, the existing certified session-open-plus-sixty-minute checkpoint.
- Maximum cursor: relative minute `180`, the existing sealed session-end boundary.
- Initially visible information: only bars and context available at or before relative minute `0`.
- Scored cases `S-001` through `S-240`: closed and unavailable throughout V2.
- Calendars 2025 and 2026: remain locked.
- Acquisition and charge: prohibited.

Pre-checkpoint history may be inspected, but a V2 decision can be placed only at the current one-way cursor at or after minute `0`. This prevents a user who has already seen the original checkpoint from retrospectively executing at an earlier historical candle.

## 2. Synchronized point-in-time timeline

Supported chart timeframes are `1w`, `1d`, `4h`, `1h`, `15m`, `5m`, and `1m`.

Every bar receives:

- `bar_id`: deterministic hash identity;
- `close_offset_minutes`: integer minutes from the original certified checkpoint;
- `available_offset_minutes`: the first integer relative minute at which the completed bar was available;
- normalized OHLC and observed volume.

A bar is visible only when both offsets are less than or equal to the current shared cursor. Switching timeframe never changes the cursor and never causes a bar with later availability to enter the browser payload.

Cursor movement is one-way and append-only. Permitted increments are 1, 5, or 15 minutes, bounded by minute 180. No rewind, seek-back, return-to-final-checkpoint, or client-side possession of unrevealed future bars is permitted.

## 3. Context policy

The existing point-in-time fundamental, structure, session, level, positioning, cross-market, liquidity, released-event, and GC context at minute 0 is the frozen context prior. It is never recomputed from later information during this practice stage. The interface must label it as `CONTEXT FROZEN AT T0`; increasing staleness is observable from the cursor.

At decision lock, the complete public context object and its canonical SHA-256 are stored in the setup record. No later market reaction or outcome field may enter that context.

## 4. Cross-timeframe drawings

Drawings are case-global rather than timeframe-local. Every anchor stores:

- `relative_minute` at an already-visible completed bar;
- `price_index`, normalized to the case's minute-0 reference price;
- `source_timeframe`.

Eligible objects are trend line, horizontal level, Fibonacci retracement, ruler, Long Position, and Short Position. For another timeframe, an anchor projects to the latest completed bar whose availability and close offset are no later than the anchor minute. If no such bar exists, that object is reported as incompatible on that timeframe rather than moved using future information.

Exactly one position object may exist. Non-position drawings may be selected or deleted before lock. All drawings become immutable after decision lock.

## 5. Decision and execution geometry

The decision action is `LONG`, `SHORT`, or `NO_TRADE`.

For a directional decision:

- The position must be drawn at `REPLAY NOW`.
- Entry, stop, and target are normalized price indices.
- Long geometry requires `stop < entry < target`.
- Short geometry requires `target < entry < stop`.
- Entry offset is measured from the latest visible M1 close using the latest point-in-time M15 ATR.
- Existing trigger-direction bounds remain: Market offset 0; pullback and breakout offsets no farther than 2 ATR in their permitted direction.
- Stop distance must be 0.25 through 3.00 M15 ATR.
- Target must be 0.50 through 5.00 R.
- Maximum planned risk is fixed at $50 on the frozen $10,000 account.
- Existing one-minute latency, spread, slippage, commission, stop-first ambiguity and append-only principles remain unchanged.

`NO_TRADE` has no position geometry but requires an explicit reason.

## 6. Atomic setup record

`Place & Play` must validate and append exactly one immutable decision record before any later bar is returned. The record contains:

- case alias and cursor minute;
- selected timeframe;
- action, confidence, trigger and normalized entry/stop/target geometry;
- latest visible M1 reference and point-in-time M15 ATR;
- all drawing objects and anchor coordinates;
- intuitive `trade_reason` plus trigger, invalidation and target explanations;
- selected evidence codes;
- per-timeframe visible bar counts, terminal bar IDs and SHA-256 hashes;
- aggregate visible-chart SHA-256;
- complete point-in-time context and SHA-256;
- complete submitted-setup SHA-256;
- idempotency key, prior ledger hash, lock timestamp and record hash.

The server, not the browser, recomputes visible-chart and context hashes from sealed sources. A stale cursor, future anchor, missing position, geometry mismatch, altered snapshot or reused idempotency key with different content is rejected.

Only after the record is durably appended and `fsync` succeeds may the practice response reveal bars after the decision cursor. The response remains zero-credit practice feedback.

## 7. User interface

- The replay cursor and Play/Pause/Step controls remain visible after timeframe changes.
- Timeframe switching is read-only with respect to cursor and revealed data.
- Drawings remain visible across compatible timeframes.
- A prominent `WHY THIS TRADE NOW?` field sits immediately with the chart trade ticket and remains visible before arming.
- `Place & Play` is disabled until geometry, evidence, reason, trigger, invalidation and target explanation are complete.
- After lock, drawings and text are immutable and only the practice resolution may animate.
- A persistent notice states that scored labeling is closed pending V2 certification.

## 8. Required certification gates

1. All V1 predecessor artifacts and hashes remain preserved.
2. Primary and independent reference timeline materializations are byte-identical.
3. Exactly twenty practice timelines exist; no scored timeline is materialized or served.
4. Every timeline covers cursor 0 through 180 with exactly 180 future M1 closes.
5. No initial or advanced snapshot contains a bar unavailable after its cursor.
6. Cross-timeframe switching cannot alter the cursor or visible-data hash.
7. Cursor records are monotonic, append-only, idempotent and tamper-evident.
8. Decision lock is atomic and precedes future-path disclosure.
9. Every drawing anchor is at or before the locked cursor and is independently reproducible.
10. The recorded setup can reconstruct the exact visible charts, drawings, context and trade ticket.
11. No rewind or later edit endpoint exists.
12. Backend unit/API tests, frontend tests, typecheck, lint, production build and live Docker checks pass.
13. Human decisions remain zero before the V2 certified application is opened.
14. No acquisition, charge, 2025 inspection or 2026 inspection occurs.

