# Gold Annotated TradingView-Style Replay and Human Edge Audit Contract V3

Status: `APPROVED_AND_FROZEN_FOR_IMPLEMENTATION`

Date: 2026-08-14

## 1. Purpose

Build a historical gold-market simulator that behaves like TradingView Replay Trading while adding an immutable research annotation layer.

The human—not the application—decides whether, when, where, and why to trade. The human will replay and annotate approximately one calendar year. After collection, the system will join those decisions to the already available point-in-time market information and evaluate performance, reasoning quality, recurring strengths, recurring mistakes, and possible improvements.

This is a new research branch. Every prior result, rejection, artifact, and seal remains preserved.

## 2. Formal correction of V2

V2 remains preserved as a completed engineering branch. Its preselected `SESSION_OPEN_PLUS_60_MINUTES` checkpoint, `T+0` through `T+180` clock, current P-001 cursor, and ledgers must not be edited or reused as V3 research evidence.

V3 removes all of the following:

- The preselected decision checkpoint.
- The three-hour forced decision window.
- The implication that the application decides when a trade should be placed.
- The requirement to complete annotations before the position-order dialog can open.
- The rule that merely drawing a position disables replay.
- The one-decision-per-session restriction.

`T+180` is not used as the V3 user-facing clock.

## 3. Replay behavior

V3 follows the TradingView-style manual workflow:

1. The user selects an initial historical date and time before replay begins.
2. Only bars available through that cursor are sent to the browser.
3. The user controls Play, Pause, speed, single-step, timeframe, and chart camera.
4. The user may draw and analyse without placing an order.
5. The user may place a market, limit, or stop order at any currently visible replay time.
6. Replay continues and the simulated broker fills or expires the order under frozen rules.
7. The user may take multiple sequential trades over the collection period.
8. The application records every order, annotation, fill, exit, and amendment.
9. The system computes performance and reasoning diagnostics after sufficient data are collected.

The replay is chronological. The user may inspect any already revealed bar but may never place an order retroactively. Moving the camera left over revealed data is not rewind. Returning the decision cursor to an earlier time is prohibited after later bars have been revealed.

## 4. Historical collection universe

Use only existing sealed, no-charge data:

- IC Markets MT5 XAUUSD M1 from 2021-07-23 through 2024-12-31.
- Deterministic completed-candle M5, M15, H1, H4, daily, and weekly bars.
- Existing session, structure, level, macro, event, rates, USD, risk-market, positioning, COT, and available liquidity sources.
- Existing GC MBO/MBP-10 information only on its sealed covered dates and only as optional point-in-time context.

No paid data may be acquired. Calendar 2025 and 2026 remain closed.

Before materialization, perform a metadata-only coverage audit and freeze:

- Twenty zero-credit practice trading days selected outcome-blindly from the partial 2021 history.
- One complete chronological calendar year from 2022–2024 for the primary human collection run.
- Later available years for frozen historical robustness replay after the primary collection policy is sealed.

The exact primary year must be selected using coverage and chronology only, never price outcomes or strategy performance. Historical replay evidence is not represented as fresh independent validation; genuine independent evidence requires later prospective tracking.

## 5. Market timeline and navigation

The primary display uses actual exchange/broker date and time, not an artificial decision-relative clock. The bottom axis displays date and time.

The replay covers the available XAUUSD trading day continuously, preserving maintenance, rollover, weekends, holidays, DST, and no-tick intervals. Asia, London, London–New York overlap, New York, benchmark, event, and rollover windows are shaded and labeled; they do not constrain when the user may trade.

Controls include:

- Play and Pause.
- Step forward by one replay interval.
- Replay intervals of 1, 5, and 15 minutes.
- Multiple playback speeds.
- Advance to the next trading day or named session while flat; skipped time becomes revealed history and is logged as not observed in real-time.
- Weekly, daily, H4, H1, M15, M5, and M1 switching at one synchronized cursor.
- GUI zoom and horizontal/vertical camera movement.
- Normal and fullscreen parity.

No position drawing, annotation draft, or timeframe selection may silently disable Play. A button may be disabled only for a genuine state constraint, and the reason must be visible.

## 6. Drawings and position plans

- Drawings use case-global timestamp and normalized-price anchors.
- Drawings persist across all compatible timeframes.
- An unlocked drawing can be selected, moved, resized, or deleted.
- Backspace and Delete remove the selected unlocked drawing unless the user is typing in a form field.
- Long and short position plans have distinct ENTRY, SL, and TP handles.
- Moving ENTRY preserves the exact SL and TP prices.
- Moving SL preserves the exact ENTRY and TP prices.
- Moving TP preserves the exact ENTRY and SL prices.
- A position drawing is only an unsubmitted plan. It cannot fill until the user explicitly confirms an order.

## 7. Order and position lifecycle

The lifecycle is deterministic and append-only:

### `UNSUBMITTED_PLAN`

The user may alter ENTRY, SL, TP, order type, and drawings freely. Replay remains available.

### `ANNOTATING_ORDER`

Clicking `Place Order` pauses replay and opens the trade annotation dialog. It does not submit an order or reveal a candle. The user may cancel and return to the editable plan.

### `PENDING_ORDER`

Clicking `Confirm Order & Resume` first seals the visible-data hashes, cursor, timeframe, market context, drawings, order type, ENTRY, SL, TP, planned risk, and human annotation. Only after durable sealing may replay advance.

A pending limit or stop order may be modified or cancelled before fill at the current replay cursor. Every amendment stores the previous and new values, amendment timestamp, visible-data hash, and optional reason. No amendment is retroactive.

### `ACTIVE_POSITION`

When subsequently revealed price activates ENTRY:

- The actual fill price and timestamp are recorded.
- ENTRY, SL, TP, direction, planned risk, and original reasoning become immutable.
- No handle may move and no field may be rewritten.
- The chart retains visible SL and TP levels and clearly marks the actual fill.

This lock is absolute. The application must reject client-side and API attempts to modify an active position.

### Resolution

The position resolves as `STOPPED`, `TARGET_HIT`, `MANUAL_CLOSE`, `TIME_EXIT`, or `UNRESOLVED`.

The user may optionally execute `Close Position Now`, but it is a new timestamped, annotated action; it does not rewrite the original ENTRY, SL, or TP. The analysis reports both the actual discretionary result and what the untouched original plan would have produced.

Only one active gold position is allowed at a time. A new trade may be placed after the prior position resolves. Pending-order concurrency, pyramiding, partial exits, and moving SL/TP after fill are excluded from V3.

## 8. Frozen execution assumptions

Before historical order paths are opened, freeze:

- Market, limit, and stop fill semantics.
- Bid/ask and spread handling.
- Commission, slippage, and latency.
- Conservative limit-touch requirements.
- Stop-order gaps.
- Same-bar ambiguity with stop-first treatment when sequence is unknowable.
- Session-end and weekend behavior.
- Order expiry choices.
- One-active-position enforcement.
- Exactly $50 maximum planned risk per trade on a nominal $10,000 account for the primary skill audit.
- Whole-unit and normalized-R reporting.

The human selects ENTRY, SL, and TP; position quantity is calculated from the frozen $50 risk so discretionary sizing does not obscure signal and execution quality.

## 9. Human annotation

The annotation dialog opens only after the user chooses to place an order. It must be immediately visible and convenient rather than located below the chart.

For every submitted order, record the human's original words plus structured selections for:

- Why this trade exists now.
- Fundamental direction and dominant driver.
- Higher-timeframe structure and location.
- Session and liquidity context.
- Observable entry trigger.
- Invalidation logic.
- Target logic.
- Event risk.
- Confidence.
- Optional screenshot-state hash and drawing snapshot.

The application may show point-in-time facts but may not recommend LONG, SHORT, ENTRY, SL, or TP during collection. Post-hoc machine classification of the human's text must preserve the original immutable text and be stored as a separate derived artifact.

## 10. Point-in-time context

At every replay cursor, display only information the market could have known by then:

- Completed candles only.
- Pre-existing structure, support, resistance, liquidity, and session levels.
- Latest available point-in-time macro regime and directional components.
- Scheduled event name, forecast, previous value, and scheduled time before release.
- Actual value, revision, surprise, and reaction only after release.
- Rates, USD, risk, positioning, COT, and liquidity inputs only after their availability timestamps.

Every fact is labeled `OBSERVED`, `CALCULATED`, `INFERRED`, or `UNKNOWN`. Context updates as replay time advances; it is not permanently frozen at an arbitrary earlier checkpoint.

## 11. Persistent ledgers and recovery

Maintain separate append-only ledgers for:

- Cursor progression and observed/skipped intervals.
- Unsubmitted local drafts where recoverable.
- Submitted orders.
- Pending-order amendments and cancellations.
- Entry fills.
- Position resolutions and manual closes.
- Original annotations.
- Derived post-study annotation classifications.

Refresh, browser restart, server restart, and network interruption must restore the last durable cursor and all live order/position state without duplication. Automated tests must use isolated temporary ledgers and must never mutate the human collection ledger.

## 12. Post-collection evaluation

After the agreed collection period or minimum sample is complete, calculate:

- Observed-market coverage and skipped intervals.
- Number of submitted orders, unfilled orders, cancelled orders, and filled trades.
- Win rate, loss rate, scratch rate, net expectancy in R, profit factor, average win/loss, and payoff ratio.
- Net PnL at constant $50 risk and normalized percentage return.
- Maximum drawdown, streaks, Sharpe/Sortino where meaningful, MFE, MAE, holding time, and capture efficiency.
- Performance by year/month, weekday, session, time of day, direction, volatility, event regime, macro regime, structure state, location, trigger, and confidence.
- Confidence calibration and Brier-style probability diagnostics where applicable.
- Original-plan result versus discretionary manual-close result.
- Entry lateness, chasing, stop placement, target realism, fundamental alignment, structure alignment, event exposure, overtrading, and session-selection diagnostics.
- Repeated strengths and repeated error patterns supported by counts and uncertainty.

Win rate alone is not an edge. The final verdict requires positive net expectancy after costs, realistic support, chronological stability, and prospective confirmation. The analysis must distinguish observation, calculation, inference, and advice.

## 13. Required browser-level certification

The system cannot be presented as working solely because unit tests pass. Certification requires an isolated Docker environment and automated browser interaction against the real frontend and API.

At minimum test:

1. Initial date/time selection and future-bar hiding.
2. Play, Pause, speed, and every step interval.
3. Arbitrary order placement at multiple non-preselected timestamps.
4. Replay continuing with an unsubmitted plan.
5. Timeframe changes while playing, paused, pending, active, and resolved.
6. Drawing persistence, selection, independent resize, move, Backspace, and Delete.
7. Normal/fullscreen control parity.
8. `Place Order` opening annotation without cursor movement.
9. Cancel returning to the identical editable plan.
10. `Confirm Order & Resume` sealing before the next bar.
11. Market, limit, stop, modify, cancel, fill, stop, target, manual-close, and expiry paths.
12. Exact post-fill rejection of ENTRY/SL/TP modifications in both UI and API.
13. Multiple sequential trades with one-active-position enforcement.
14. Refresh/restart/idempotency recovery for every lifecycle state.
15. Event and fundamental point-in-time updates with no future leakage.
16. Natural maintenance, weekend, holiday, DST, and missing-bar transitions.
17. Correct fixed-risk quantity, costs, and trade-ledger calculations.
18. No unexplained disabled control.
19. Complete frontend/backend test suites, type checking, linting, and production builds.
20. Captured browser screenshots, interaction trace, deployed-image identity, and live HTTP health checks.

Any failed gate blocks certification and labeling. The entire regression matrix must be rerun after any correction.

## 14. Delivery sequence

1. Approve and seal this contract.
2. Complete a no-charge metadata-only full-year coverage and deduplication audit.
3. Freeze the practice days, primary collection year, execution model, risk, and ledger schemas.
4. Materialize independent primary/reference chronological replay streams without inspecting outcomes.
5. Implement the replay server, broker state machine, annotation ledger, analysis-ready schema, and interface.
6. Complete browser-level certification in isolated test ledgers.
7. Open only the twenty zero-credit practice days for human usability testing.
8. Correct and recertify usability defects without opening the primary collection year.
9. Freeze the final interface.
10. Open the one-year human collection run only under separate explicit authorization.
11. Evaluate the completed immutable ledger and initialize prospective tracking.

## 15. Stop conditions

Stop before implementation or opening a new segment if predecessor seals fail, point-in-time coverage is insufficient, outcomes would be exposed during engineering, a paid source is required, a charge is possible, or results cannot be independently reproduced.

No edge, win rate, PnL, or advice is calculated during engineering and practice usability certification.
