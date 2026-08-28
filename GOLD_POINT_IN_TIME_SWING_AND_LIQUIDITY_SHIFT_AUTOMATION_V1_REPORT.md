# Gold Point-in-Time Swing and Liquidity-Shift Automation V1 Report

## Verdict

`PASS_ENGINEERING_PAPER_ONLY`

The platform now identifies completed-candle swings, inferred M15 auction-shift zones, zone lifecycle transitions, and two risk-sized paper-proposal families without manual chart labeling. The implementation does **not** submit broker orders and does **not** establish that either proposal family is profitable.

## Implemented vertical slice

1. Read only complete and available XAUUSD M1 candles at the requested `as_of` timestamp.
2. Aggregate M5, M15, H1 and H4 without filling missing minutes.
3. Confirm strict 2-left/2-right swings with ATR prominence and a separate `detected_at` timestamp.
4. Infer an M15 auction-shift zone only after a completed displacement candle breaks a previously known swing.
5. Track each zone as `ACTIVE_UNTOUCHED`, `TOUCHED`, `RETEST_CONFIRMED`, `INVALIDATED`, or `EXPIRED`.
6. Generate `RETEST_LIMIT_V0_1` and `CONFIRMED_RETEST_V0_1` paper proposals.
7. Calculate the structural stop, nearest already-known opposing swing target, whole-ounce quantity, actual planned risk and reward-to-risk ratio.
8. Require point-in-time macro alignment and usable liquidity before a proposal can become `PAPER_READY`.
9. Expose every result through `/api/v1/market-structure/snapshot` and render it on `/structure`.

## Chart semantics

- Orange and blue triangles: calculated, confirmed swing highs and lows.
- Green and red rectangles: inferred bullish and bearish auction-shift zones.
- Gold diamonds: `PAPER_READY` proposals.
- Grey diamonds: blocked, waiting, counter-macro, expired, or invalidated paper proposals.
- Every zone and proposal exposes its exact state, timestamps, method, evidence, invalidation, macro relationship and risk geometry.

These zones are price-derived inferences. They are not represented as directly observed institutional orders or exchange inventory.

## Point-in-time controls

- No source bar with `close_time > as_of` or `available_at > as_of` is eligible.
- A pivot is unavailable until both right-side confirmation candles close.
- A zone is unavailable until its displacement candle closes.
- A target must have been detected no later than the proposal trigger.
- A fundamental snapshot must be available before the trigger and no more than 24 hours old.
- A later fundamental snapshot is never backfilled into an earlier proposal.
- Risk is calculated from the actual proposal entry reference to the structural stop and is capped at $50 planned risk.
- `live_order_permitted` is hard-coded false for every proposal.

## Certification

| Gate | Result |
|---|---:|
| Dedicated auction-automation tests | 6 passed |
| Complete backend unit suite | 247 passed |
| Complete frontend suite | 29 passed |
| Python lint on changed backend files | passed |
| Frontend ESLint | passed |
| TypeScript type check | passed |
| Next.js production build | passed |
| API and web containers rebuilt | passed |
| API health/schema exercise on a 2024 cutoff | passed |
| `/structure` HTTP response | 200 |

The 2024 technical API exercise used 20,000 eligible source bars and returned a valid 64-character source hash. It produced 1,539 confirmed swing records, the capped 24 most recent zones and 48 corresponding paper-proposal records. All returned proposals retained `live_order_permitted = false`. These are detector counts, not trades or performance results.

## Scope restrictions preserved

- No 2025 or 2026 outcomes were evaluated.
- No PnL, win rate, profit factor or edge claim was calculated.
- No paid source was acquired.
- No live or demo broker order was submitted.
- No previously rejected strategy was reopened.

## How to use it

Open `http://localhost:3000/structure`. The local API and web containers are already running. Use the automation summary and recent proposal ledger below the chart to distinguish a technical zone from an actionable paper proposal and to see the exact blocker when a proposal is not ready.

## Required next gate

The next honest step is a bounded, outcome-hidden visual calibration: compare the automatically drawn swings and zones with the intended auction reading and record false positives, missed structures and timing disagreements. Thresholds may be corrected only under a new pre-outcome amendment. Once visual semantics are accepted, freeze fresh prospective paper cases and measure the two entry families. Live MT5 execution remains unauthorized until a prospectively tested policy demonstrates positive net expectancy and acceptable risk.
