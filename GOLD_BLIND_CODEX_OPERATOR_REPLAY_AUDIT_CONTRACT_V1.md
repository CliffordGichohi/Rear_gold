# Gold Blind Codex-Operator Replay Audit Contract V1

Status: `APPROVED_AND_FROZEN_BEFORE_2022_VALUE_ACCESS`

Approved: 2026-08-18

## 1. Purpose

Test whether Codex can apply the user's discretionary gold-auction process through the same rendered replay interface used by a human, without direct market-file access, future leakage, interim outcome feedback, or post-outcome rule changes.

This is a companion branch to the Gold Annotated TradingView-Style Replay and Human Edge Audit V3. It does not alter V3, its twenty zero-credit practice days, its human ledger, its post-practice interpretation, or any earlier research result.

The audit is a blinded historical operator test, not pristine independent market validation. Genuine independent evidence still requires prospective decisions after the final freeze.

## 2. Frozen population

- Calendar year: 2022 only.
- Include every full UTC trading date passing the already frozen V3 metadata rules: at least 1,000 observed XAUUSD M1 bars, complete London and New York session metadata, unique ordered timestamps, and point-in-time context coverage.
- The frozen V3 metadata audit reports 249 eligible 2022 dates. The preparation implementation must independently reproduce exactly those 249 identities using timestamps and metadata only.
- Order cases chronologically and assign aliases `CBR-2022-001` through `CBR-2022-249`.
- Use one case per eligible UTC trading date and at most one submitted trade per case.
- No date may be selected, removed, replaced, ranked, or reordered using OHLC values, outcomes, volatility, strategy performance, prior research results, or human decisions.
- A technically unavailable case remains in the registry with an explicit disposition; it is never silently dropped.

Calendar 2025 and 2026 remain locked. No paid source may be acquired.

## 3. Operator isolation

Codex may use only pixels and controls rendered by the certified browser application. During collection Codex is prohibited from accessing:

- Raw or normalized XAUUSD files.
- Private replay streams or registries containing values.
- API response bodies, browser network payloads, DOM-resident chart arrays, browser storage, source maps, or developer tools.
- Future candles, resolution records, PnL, outcome screenshots, outcome videos, or aggregate progress performance.
- Human decisions for the same 2022 cases.

Permitted operator inputs are browser screenshots of the visible application, visible text, and ordinary browser controls. Engineering scripts may materialize sources and resolve trades, but their value-bearing outputs must not be displayed to Codex before the outcome-opening gate.

The application must send only bars and context available at the current cursor to the browser. Future rows may not be preloaded or merely hidden with CSS.

## 4. Frozen decision process

Codex applies this six-part process:

1. Use point-in-time macro and fundamental information to characterize the broader environment, its strength, freshness, catalyst risk, and likely persistence. Macro is context and is not an unconditional trade-direction veto.
2. Using completed weekly, daily, H4, and H1 candles, identify a pre-existing higher-timeframe trend or range and an already visible liquidity, support/resistance, or premium/discount location.
3. Wait for a completed M15 structure transition that originates at that location. Record the broken or defended structure and the visible evidence; a context-free M15 break is ineligible.
4. Enter in the new local auction direction only during London, the London-New York overlap, or New York. Asia may supply range and liquidity context but is not an entry session.
5. Place the stop beyond the exact visible opposing structural level or originating zone whose breach invalidates the thesis. Record the timeframe, price, and whether the logical invalidation is a touch, close, or acceptance condition. The simulated protective stop remains price-touch executable.
6. Place the target at a pre-existing opposing liquidity area visible before submission. Record its timeframe, price, and whether it is internal or external liquidity.

Every trade is classified at decision time as exactly one of:

- `MACRO_ALIGNED_CONTINUATION`
- `COUNTER_MACRO_RANGE_ROTATION`
- `MACRO_NEUTRAL_AUCTION_TRADE`

`COUNTER_MACRO_RANGE_ROTATION` is permitted only when the higher-timeframe context is recorded as a pre-existing range, price is at its premium or discount/liquidity extreme, and an aligned M15 transition originates there.

Codex records `NO_TRADE` if any required component is absent or if no qualifying setup appears by the frozen end of the New York observation window.

## 5. Cursor and display rules

- Each case begins at 00:00 UTC with only completed historical bars available by that instant.
- The cursor moves forward only.
- Codex may inspect weekly, daily, H4, H1, M15, M5, and M1 through the synchronized cursor.
- The primary decision chart is M15. Higher timeframes provide context; M5/M1 may refine execution but cannot create a setup absent an M15 transition.
- The operator may scan the day sequentially through the end of the frozen New York window. It may not jump backward or retroactively place an order.
- Already revealed history may be panned and zoomed without moving the decision cursor.
- Point-in-time fundamentals, sessions, event information, structure, and known levels update only when their availability timestamp is reached.

## 6. Decision record

Every submitted trade must record and seal before resolution:

- LONG or SHORT.
- Setup class.
- Cursor timestamp and selected timeframe.
- Macro regime, directional pressure, freshness, catalyst risk, and whether macro is driver or context only.
- Higher-timeframe trend/range classification.
- Exact pre-existing location and source timeframe.
- Exact M15 transition evidence.
- Entry, stop, target, and order type.
- Exact invalidation and target explanations.
- Session/liquidity context.
- Confidence scores separated into macro confidence, setup quality, and execution quality.
- Written reasoning in the operator's original words.
- Visible-state, chart, drawing, screenshot, and decision hashes.

`NO_TRADE` records require the terminal cursor, visible-state hash, inspected-timeframe evidence, and a structured reason.

Records are append-only and immutable after sealing.

## 7. Frozen execution

- Reuse the sealed V3 spread, latency, slippage, fill, same-bar stop-first, whole-ounce sizing, time-exit, weekend, and session-end semantics unchanged.
- Primary order type is market at the first eligible M1 open after the sealed decision plus the frozen latency and costs.
- Planned risk is capped at $50 on a nominal $10,000 account.
- Quantity is calculated from entry to stop using whole ounces.
- If the actual fill places the target on the wrong side, makes stop geometry nonpositive, or raises effective fill-to-stop exposure above $55, classify the order `POST_FILL_GEOMETRY_INVALID`, flatten at the first permitted observation, retain the economic result, and record an execution-integrity failure. Never rewrite entry, stop, target, or quantity.
- One live order or position and no more than one submitted trade per case.
- No pyramiding, partial exits, stop movement, target movement, manual discretionary close, or post-fill amendment in this audit.
- Unresolved trades time-exit at the final observed M1 close of their UTC trading date.

## 8. Evidence preservation

For every case preserve:

- Initial full-page screenshot.
- A screenshot for every inspected timeframe state.
- Final pre-decision full-page screenshot and chart crop.
- Completed decision form screenshot.
- Full browser interaction video.
- Playwright trace and chronological action log.
- Visible-state, screenshot, video, trace, and decision SHA-256 hashes.
- Outcome screenshot and outcome video created by an independent resolver.

Pre-decision evidence is stored separately from outcome evidence. Outcome-bearing files live in an append-only sealed outcome vault and are not made available to Codex until all 249 cases are terminal and the outcome-opening manifest is sealed.

Each evidence manifest binds the case alias, browser build identity, API build identity, source hashes, cursor, viewport, timezone, selected timeframe, and prior ledger head.

Recordings use local storage only. No external upload is permitted. Stop before 2022 value access if available storage is below 25 GiB. Stop during collection before usable space falls below 10 GiB.

## 9. Ledger and restartability

- Maintain a new `CODEX_BLIND` append-only JSONL hash chain; never reuse the human ledger.
- Maintain separate cursor, decision, evidence, and outcome-vault manifests.
- Every browser action has a monotonic sequence, wall-clock timestamp, replay timestamp, action, target, selected timeframe, and visible-state hash.
- Restart restores the exact last sealed case/cursor/decision state without duplication.
- Cases run in restartable chronological batches. Batch boundaries do not permit rule changes or outcome review.
- No interim hit rate, PnL, win/loss state, target/stop state, or aggregate performance is exposed.

## 10. Browser certification

Before any 2022 value is rendered, certify on synthetic timestamp-boundary fixtures and the existing zero-credit practice interface:

- Future bars are absent from browser responses and DOM state.
- Cursor movement is one-way.
- Every timeframe is point-in-time synchronized.
- The separate ledger cannot mutate the human ledger.
- LONG, SHORT, and NO_TRADE records seal before resolution.
- Outcome responses contain no direction, price path, resolution, or PnL.
- Outcome-vault files are created without being returned to the operator.
- Screenshots, videos, traces, action logs, and hashes reproduce.
- Restart and idempotency work at pre-decision, sealed-decision, and terminal states.
- 2025 and 2026 routes remain inaccessible.

Any certification failure blocks 2022 opening.

## 11. Evaluation freeze

Open the sealed outcome vault exactly once after all 249 cases are terminal. Report:

- Observed minutes and timeframe inspections.
- Trade and no-trade counts.
- Win rate, expectancy in R, profit factor, average win/loss, payoff ratio, net R, dollars, and normalized account return.
- Drawdown, streaks, MFE, MAE, holding time, capture efficiency, stopped-then-target frequency, and post-fill geometry failures.
- Results by quarter, month, direction, setup class, session, macro relation, higher-timeframe state, confidence tier, and event proximity.
- Confidence calibration and Brier score where defined.
- Chronological stability and 1.5x stressed costs.
- Human/Codex agreement only for cases independently completed by both operators; otherwise report comparison unavailable without opening human decisions.

Use deterministic completed-case bootstrap intervals clustered by trading date with seed `20260818` and 20,000 resamples.

### PASS

All integrity gates pass, at least 30 filled valid-geometry trades exist, net expectancy after costs is positive, PF is at least 1.10, the clustered 95% expectancy lower bound is positive, expectancy remains positive at 1.5x costs, at least three calendar quarters are positive, maximum drawdown does not exceed 15% of the nominal account, and no single quarter contributes more than 70% of positive PnL.

### REJECT

Support is sufficient but any economic PASS gate fails, or a reproducible operator policy produces nonpositive net expectancy.

### INCONCLUSIVE

Integrity passes but fewer than 30 valid filled trades exist, uncertainty cannot be estimated reliably, or technical unavailability prevents the full frozen population from being completed without imputing decisions.

An integrity or leakage failure is a formal `FAIL_INTEGRITY`, not `INCONCLUSIVE`.

## 12. Prohibitions and stop conditions

Do not change the population, rubric, execution, evidence requirements, or evaluation gates after 2022 values are rendered. Do not directly optimize decisions, thresholds, or risk toward a monetary target. Do not inspect 2025 or 2026. Do not acquire data, incur a charge, or upload evidence.

Stop before opening 2022 for a predecessor-seal failure, mismatched population, browser leakage, failed isolated certification, inadequate storage, unreproducible artifact, unavailable required source, or possible charge.

