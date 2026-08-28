# Gold Hierarchical Liquidity-Shift Edge Discovery Contract V2

## Purpose

This branch tests the operator's stated process as a chronological auction sequence:

`pre-existing H1/H4/M15 liquidity-shift location -> reaction -> M15 structure transition -> retracement/confirmation entry -> next meaningful external liquidity`

It preserves the formal rejection of `gold-auction-automation-1`. V1 remains unchanged. V2 does not redefine an entry as being physically inside the old origin zone; it asks whether price first reacted at a point-in-time-known shift zone and subsequently produced a tradable transition.

## Evidence partitions

1. **Semantic calibration only:** the 30 already-exposed matched replay cases `CBR-2022-001` through `CBR-2022-030`. Only the visible human decisions, annotations, drawings and bars available by each decision timestamp may be used. Outcome ledgers are prohibited. This partition receives zero economic credit.
2. **Historical development economics:** sealed XAUUSD and point-in-time casebook sources from 1 August 2021 through 31 December 2024, excluding every matched-replay date and the six permanent microstructure engineering dates. These results are development evidence, not independent validation.
3. **Forward years:** 2025 and 2026 remain closed. They may be opened only after a complete candidate is frozen and only under separate authorization.

No paid acquisition, broker order or live-order permission is authorized.

## Point-in-time structure

Use provider XAUUSD M1, M5, M15, H1 and H4 records. A bar becomes usable only at its recorded `available_at`, never at its opening time. All pivots require two completed bars on each side and are unavailable until the second right-hand bar closes.

For each M15, H1 and H4 timeframe:

- Calculate Wilder-style simple rolling ATR14 from known bars.
- A pivot must have at least 0.25 ATR prominence.
- A liquidity shift requires a completed displacement candle with true range at least 1.25 ATR and body/range at least 0.60.
- The displacement close must break the most recent already-confirmed same-side swing by at least 0.05 ATR.
- The origin is the last opposite-colour candle among the preceding six bars.
- A bullish zone spans the origin low through the greater of its open and close. A bearish zone spans the lesser of its open and close through its high.
- A zone is an `INFERRED` price-structure reference, never a claim of directly observed institutional inventory.
- A zone becomes usable only at the displacement close, expires after 45 calendar days, and invalidates after a same-timeframe close beyond its far edge by 0.10 creation ATR.
- At most the first two distinct contact episodes are eligible. Episodes must be separated by at least twelve M5 bars, and the first eligible contact must occur at least thirty minutes after zone creation.

## Frozen causal sequence

For each eligible zone contact:

1. A completed M5 bar must overlap the zone.
2. Within three completed M5 bars, price must close back beyond the near edge in the zone direction. The contact extreme is fixed at that reaction timestamp.
3. Within sixteen completed M15 bars, an aligned completed M15 candle must close through the latest opposing confirmed M15 pivot known at the reaction by at least 0.05 ATR. Its true range must be at least 0.90 ATR and body/range at least 0.55.
4. The transition leg is fixed from the contact extreme to the transition close.
5. The permitted retracement band is 38.2% through 78.6% of that leg.

No future archetype, extrema, MFE, MAE, session result or eventual direction may enter these calculations.

## Registered entry families

Exactly two entry families are permitted:

### `SHIFT_HALF_RETRACE_LIMIT_V2`

- Place a virtual limit at the 50% retracement of the frozen transition leg immediately after the transition closes.
- The order expires after twelve completed M5 bars or at session end, whichever comes first.
- It fills only when a later M1 bar actually touches the level.
- Stop: contact extreme plus an adverse 0.10 transition-M15 ATR buffer.

### `SHIFT_M5_STRUCTURE_CONFIRMATION_V2`

- After the transition, require a completed M5 bar to enter the frozen 38.2%-78.6% retracement band.
- Then require an aligned completed M5 candle with body/range at least 0.55 to close beyond the highs or lows of the preceding two completed M5 candles.
- Enter at the next available M1 open.
- Stop: the pullback extreme plus an adverse 0.10 transition-M15 ATR buffer.

For both families, stop distance must be between 0.10 and 1.50 transition-M15 ATR. There must be at least thirty minutes remaining in the active session.

## Higher-timeframe and macro routes

Analyse London and New York separately under exactly two routes:

1. `MACRO_ALIGNED_CONTINUATION`: the point-in-time casebook macro direction equals the trade direction; at least one of H1 or H4 is structurally aligned and neither is structurally opposite.
2. `RANGE_EXTREME_ROTATION`: the current price lies in the outer 35% of the latest already-confirmed H1 swing range in the proposed direction and H1 is not a clean opposite trend. Macro may align, be neutral, or contradict; the relationship must be reported and cannot be hidden or relabelled.

Macro direction uses the existing casebook gates: coverage at least 50, confidence at least 35, bullish score at least +20 or bearish score at most -20. Otherwise macro is `NEUTRAL_OR_UNKNOWN`.

## Target and execution rules

Target candidates must be known no later than order placement and may include only:

- confirmed H1 or H4 opposing swing levels;
- midpoint of an already-known opposing H1 or H4 shift zone;
- session-open-known Asia high/low and prior-day high/low.

Select the nearest candidate in the trade direction whose planned reward-to-risk is at least 1.50. M15 internal swings are management evidence only and cannot be the final target. A setup without such a target is not executable.

Execution is frozen as follows:

- maximum planned risk: $50 on a $10,000 reference account;
- whole-ounce position sizing by floor division;
- entry and adverse exits include observed half-spread plus $0.05 slippage; missing spread falls back to $0.20;
- commission: $0, matching the sealed replay baseline;
- stop-first resolution when stop and target occur in one M1 bar;
- time exit at the earlier of the relevant session close or four hours after entry;
- one trade per family, route, session and session date; earliest eligible setup wins;
- combined diagnostic: one earliest trade per session date and session across all registered cells;
- maximum effective fill-to-stop risk: $55; a violation is an immediate geometry rejection, not a silent resize.

## Semantic calibration gate

The exposed human sample is a representation test, not ground truth and not economic evidence. A human LONG or SHORT is a semantic match when the detector identifies, no later than the human decision:

- a same-direction eligible zone contact during the preceding 96 hours;
- a same-direction M15 transition after that contact; and
- either registered entry family triggered or was legitimately pending after the transition.

Report every stage separately. V2 represents the stated method only if at least 60% of human trades match the location/contact stage, at least 50% match the transition stage, and at least 40% reach a registered triggered-or-pending entry state. Thresholds cannot be changed after this contract is sealed.

## Development evaluation

If semantic calibration passes, test every frozen session x route x entry-family cell. Do not discard a registered cell after seeing another cell's result.

- Minimum support: 40 executed trades overall, at least 8 in two distinct calendar years, and at least 8 in three of four chronological validation blocks.
- Blocks: 2021-08-01--2022-06-30, 2022-07-01--2023-03-31, 2023-04-01--2023-12-31, and 2024-01-01--2024-12-31.
- Apply Holm correction across support-eligible cells separately for London and New York.
- Uncertainty: 20,000 deterministic week-cluster bootstrap samples with seed 20260820.
- Economic PASS requires net expectancy above zero, profit factor at least 1.10, positive clustered 95% lower bound, positive expectancy at 1.5-times costs, at least three positive blocks, at least two positive calendar years, maximum drawdown no greater than 15% of the reference account, and no single year or session carrying more than 70% of positive PnL.
- At most one candidate per entry family and two total candidates may pass. Zero is acceptable.

Report support, trigger and fill counts, trades per month, win rate, net expectancy, profit factor, R/month, dollars/month, drawdown, MFE, MAE, target/stop/time-exit frequencies, route, session, year, block, cost stress and the exact gate disposition.

## Prohibitions

- Do not modify or reopen V1.
- Do not use the human outcome ledger during semantic calibration.
- Do not tune thresholds, invert a failed rule, remove losses, select targets from future levels or use realised session labels.
- Do not inspect 2025 or 2026.
- Do not claim that a zone is observed institutional activity.
- Do not submit live, demo or paper broker orders.

Deterministic value-blind engineering corrections are permitted only when they cannot alter a frozen analytical definition and must be documented.

