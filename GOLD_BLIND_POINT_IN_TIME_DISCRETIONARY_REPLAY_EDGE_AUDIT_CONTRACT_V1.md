# Gold Blind Point-in-Time Discretionary Replay Edge Audit Contract V1

Status: `FROZEN_BEFORE_CASE_VALUE_MATERIALIZATION`

Frozen on 2026-08-13. This is a new human-decision audit. It preserves every prior result and rejection and does not reopen or retune any rejected mechanical rule.

## 1. Research question

The audit tests whether a human can extract economically useful information from the Reference-Book framework when viewing only facts available at a historical decision checkpoint. It separates three questions:

1. Can the participant select direction and no-trade states better than chance and with calibrated confidence?
2. Can the participant specify executable entries, structural invalidations, and targets without future information?
3. Do the resulting trades have positive net expectancy after realistic friction and chronological stability controls?

This audit is not evidence of an edge until all scored decisions are locked and the frozen evaluation passes. Practice cases receive zero research or validation credit. Results from 2021–2024 are development evidence; 2025 and 2026 remain closed.

## 2. Sources and integrity boundary

Only the sealed `GOLD_CASEBOOK_V0_1` artifacts and the already sealed Step 5C GC decision-feature payloads may be used:

- IC Markets MT5 XAUUSD M1, M5, M15, H1, H4, and daily bars;
- point-in-time fundamental snapshots;
- session and deterministic structure snapshots;
- cross-market snapshots;
- CFTC positioning snapshots;
- released scheduled-event records.
- genuine GC MBO/MBP-10-derived decision states on the existing 188 covered dates only.

The sealed casebook covers `2021-08-01T00:00:00Z` through `2025-01-01T00:00:00Z` exclusively and declares `holdout_loaded=false`. Every source hash in its manifest must verify before replay materialization. Step 5C primary and reference payloads must be byte/hash verified and agree exactly on the joined state fields. They may not restrict case eligibility: uncovered dates display `UNKNOWN`. No source may be acquired, refreshed, replaced, or charged.

The display materializer may access only records with `available_at <= checkpoint_at`. It must remove all subsequent-session fields, fixed-horizon event reactions, future extrema, future labels, MFE, MAE, direction, return, trade, and outcome fields. Scored future paths must not be materialized into the replay application.

## 3. Frozen case population

The source population is every `COMPLETE` London and New York session case in the sealed casebook. The official session decision clocks are 08:00 in `Europe/London` and 08:00 in `America/New_York`, using the IANA time-zone database. Each replay checkpoint is exactly 60 minutes after the recorded session decision time.

One date may appear at most once in the complete audit. A date is eligible only when both source sessions are complete, the selected checkpoint has a complete M1 bar available at the boundary, and all display joins obey point-in-time availability.

Date-to-session assignment is outcome-blind: SHA-256 of `GOLD_BLIND_REPLAY_V1_ASSIGN|session_date|20260813`; an even low-order bit assigns London and an odd bit assigns New York. Within each stratum, dates are ordered by SHA-256 of `GOLD_BLIND_REPLAY_V1_SELECT|mode|year|session|session_date|20260813`.

- Practice: exactly 20 dates from 2021-08-01 through 2021-12-31, ten London and ten New York.
- Scored: exactly 240 dates from 2022-01-01 through 2024-12-31, forty for each calendar-year × session stratum.

Case presentation order is a second outcome-blind SHA-256 permutation. All practice cases precede scored cases. Public aliases contain only mode and ordinal; the API must not expose the date, year, UTC timestamp, source record ID, absolute price, or source path.

## 4. Frozen replay display

All prices are divided by the latest complete M1 close available at the checkpoint and multiplied by 100. The checkpoint reference is therefore `100.0000`. Absolute prices are never sent to the browser.

The replay displays completed candles only:

- 52 completed weekly candles constructed from completed daily candles;
- 120 daily candles;
- 90 H4 candles;
- 120 H1 candles;
- 160 M15 candles;
- 180 M5 candles;
- 180 M1 candles.

The x-axis uses relative ordinals or minutes to checkpoint, never calendar dates. Displayed context is limited to:

- session type and phase;
- prior-day, prior-week, Asia, London-to-date, and other pre-existing known levels;
- point-in-time structure trend, range, support, resistance, momentum, compression, and confirmed detections;
- fundamental bias, score, confidence, coverage, regime, dominant driver, contradiction, event risk, reasoning, and epistemic classifications;
- cross-market state whose observations were available by the checkpoint;
- latest published COT positioning state;
- scheduled events already released and available during the previous six hours, stripped of later reaction fields;
- observed broker spread, tick activity, and range diagnostics calculated only from the previous 120 minutes.
- on covered dates, the sealed pre-session GC flow-pressure, depth-pressure, activity-shift, fragility, absorption, and flow-depth-alignment states, explicitly labeled as futures order-flow context available at session open.

Unavailable or stale information remains explicitly `UNKNOWN`; it is never neutralized or imputed. IC Markets tick volume and spread are labeled broker-observed, not centralized COMEX order flow.

## 5. Frozen decision form

Each case must receive exactly one append-only decision:

- action: `LONG`, `SHORT`, or `NO_TRADE`;
- confidence: integer 50–100, interpreted for a trade as the probability that net R is positive;
- entry trigger: `MARKET`, `PULLBACK_LIMIT`, or `BREAKOUT_STOP`;
- entry offset in M15 ATR units;
- structural stop distance in M15 ATR units;
- target in R;
- one or more evidence codes;
- concise thesis, trigger condition, invalidation explanation, and target explanation.

For `NO_TRADE`, all execution fields are null and confidence means confidence in abstention; it is reported but excluded from trade calibration. For a trade:

- `MARKET` fixes entry offset to zero;
- long pullback offset is from −2.0 through 0 ATR and short pullback offset is 0 through +2.0 ATR;
- long breakout offset is 0 through +2.0 ATR and short breakout offset is −2.0 through 0 ATR;
- stop distance is 0.25 through 3.0 ATR;
- target is 0.50 through 5.0R.

The M15 ATR is the latest complete 14-bar ATR available at checkpoint. A missing or nonpositive ATR makes the case technically unavailable and it must be replaced only before labeling by the next outcome-blind date in the same frozen stratum.

Evidence codes are `FUNDAMENTAL_ALIGNMENT`, `HTF_TREND`, `SUPPORT_RESISTANCE`, `LIQUIDITY_SWEEP`, `ACCEPTANCE_REJECTION`, `BREAK_RETEST`, `SESSION_RANGE`, `CROSS_MARKET_CONFIRMATION`, `POSITIONING`, and `OTHER`.

Decisions cannot be edited, deleted, backfilled, reordered, or resubmitted. Every record includes an idempotency key, prior-record hash, payload hash, and chained record hash. Scored outcomes remain hidden until all 240 scored decisions are locked.

## 6. Frozen execution

The checkpoint reference price and ATR convert the participant's offsets to absolute levels only inside the sealed evaluator.

- Latency: one complete M1 bar after checkpoint.
- Market entry: first eligible M1 open after latency.
- Limit/stop order expiry: the earlier of 120 minutes after checkpoint or official session end.
- Limit fill: requested level when touched; no favorable gap improvement.
- Stop fill: requested level when touched, or the less favorable bar open after a gap.
- Stop and target: derived from the filled entry, submitted stop distance, and submitted target R.
- Holding deadline: earlier of 240 minutes after fill or official session end.
- Same-bar ambiguity: entry first when eligible, then stop before target; an already active stop always has priority.
- No re-entry, scaling, break-even move, trailing stop, discretionary exit, or direction switch.
- At most one position per case. Unique dates make cross-case overlap impossible; any unexpected overlap skips the later case and is reported.

Friction uses the observed IC Markets spread at entry and exit, $0.05 XAUUSD slippage per side, and $7.00 commission per standard-lot round trip. Cost stress is 1.0× and 1.5×. Position size is rounded down to the broker's 0.01-lot step so gross stop risk does not exceed $50 on the frozen $10,000 account. Contract size is 100 troy ounces per lot. Cases below the 0.01-lot minimum are unfilled and reported.

## 7. Frozen outcomes and metrics

Economic evaluation reports submitted decisions, action rate, fill rate, trades per month, win rate, net expectancy R, clustered 95% interval, profit factor, average win/loss, net R, dollars, MFE, MAE, holding time, maximum drawdown, and results by year, half-year fold, session, confidence bin, trigger, and evidence code.

Directional accuracy uses the sign of the 120-minute XAUUSD displacement from checkpoint. A deadband of ±0.10 checkpoint M15 ATR is neutral and counts as a directional miss for `LONG` or `SHORT`; no-trade accuracy is reported separately and is not an economic PASS gate.

Trade confidence is assessed against `net_r > 0` using Brier score, equal-width 10-point confidence bins, expected calibration error, and Brier skill versus the constant in-sample win-rate forecast. No outcome is shown between scored decisions.

Calendar-week cluster bootstrap uses 10,000 draws and seed `20260813`. The preregistered hypotheses are combined, London-only, and New-York-only. Holm correction at family-wise alpha 0.05 applies to their one-sided clustered tests.

## 8. PASS, REJECT, and support rules

Evaluation is authorized only after all 240 scored decisions exist and all source, population, display, and decision-ledger seals verify.

Combined support requires at least 80 directional intentions, 60 filled trades, 15 filled trades per year, 20 per session, and eight per half-year fold. Session-specific support requires 30 fills, eight per year, and four per half-year fold.

An evaluated hypothesis passes only when all applicable gates hold:

- positive net expectancy and positive total net R;
- profit factor at least 1.10;
- calendar-week clustered 95% lower bound above zero and Holm-adjusted significance at 0.05;
- positive expectancy at 1.5× costs;
- maximum drawdown no greater than 15R;
- at least two of three calendar years and four of six half-year folds positive;
- no single year contributes more than 70% of positive R for the combined hypothesis;
- Brier score below the constant-rate reference and expected calibration error no greater than 0.15;
- no source-integrity, point-in-time, leakage, reproduction, or ledger-integrity failure.

`PASS_COMBINED_DISCRETIONARY_EDGE` requires the combined hypothesis to pass. `PASS_SESSION_SPECIFIC_DISCRETIONARY_EDGE` requires at least one Holm-adjusted session hypothesis to pass and freezes only that session. Otherwise the verdict is `REJECT_NO_DISCRETIONARY_EDGE`; inadequate filled support is `INCONCLUSIVE_INSUFFICIENT_HUMAN_TRADE_SUPPORT`, not permission to lower a floor.

At most two passing session policies may be frozen. No decision may be relabeled, excluded, inverted, or explained away after outcome opening.

## 9. Practice, evaluation, and forward policy

Practice decisions are stored in a separate append-only namespace. After a practice decision is locked, the application may reveal only that practice case's normalized post-checkpoint path and frozen execution result. Practice feedback may be used to learn the interface but never to change this contract or score the research population.

After the twentieth practice decision, the scored phase begins. During scored labeling the application reveals only progress and the fact that a decision was locked.

The present milestone ends when the protocol, registry, display payloads, replay application, tests, and pre-labeling seal are complete. It does not calculate scored outcomes or claim an edge. Calendar 2025 and 2026 remain closed. A passing development policy must be sealed before any later forward action is separately authorized.
