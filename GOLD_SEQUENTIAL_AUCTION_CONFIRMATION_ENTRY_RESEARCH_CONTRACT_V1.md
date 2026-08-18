# Gold Sequential Auction-Confirmation Entry Research Contract V1

Status: **FROZEN BEFORE DELAYED-ENTRY MATERIALIZATION OR OUTCOME ACCESS**

## Objective

Test whether replacing first-touch and first-break entries with a completed-candle auction sequence can convert the already-observed gold movement into a stable net economic edge. This is a new, explicitly post-hoc development branch. It preserves every prior rejection, including the rejection of structural-stop modification as a sufficient remedy.

The study separates two questions:

1. Does waiting for confirmation improve selection and entry timing while retaining the original stop, target and deadline?
2. Does a stop created by the confirmed response add value when everything else remains unchanged?

No realised behavioural archetype may be available to an entry decision.

## Sources and locks

- Development only: existing sealed 2021-08-01 through 2024-12-31 XAUUSD, structure, level, macro and context sources.
- Base population: the 22,193 previously executed frozen setup identities. No entry may be created for a previously non-executed setup.
- Calendar 2025 and 2026 values remain locked until the complete development system and shortlist are sealed.
- Existing GC MBO/MBP-10 data on the 188 covered dates may be used only as an incremental, point-in-time order-flow confirmation study. It cannot restrict the base XAUUSD population or resurrect a rejected base candidate.
- No acquisition, download purchase or card charge is permitted.

## Preserved setup facts

For every setup retain its frozen:

- `trade_id`, `pullback_id`, timeframe, source entry model and direction;
- original point-in-time fundamental snapshot and higher-timeframe location;
- confirmation extreme, pullback pivot, reference level and ATR14;
- original absolute stop for Track A;
- original absolute target for both tracks;
- original parent-bar deadline for both tracks.

The original entry timestamp is the new sequence anchor, not an executable fill.

## Signal-bar construction

Sequential decisions use complete XAUUSD bars derived deterministically from sealed M1 data:

| Setup timeframe | Signal timeframe |
|---|---:|
| M15 | M1 |
| H1 | M5 |
| H4 | M15 |

- Bars are UTC-epoch aligned half-open intervals `[open, close)`.
- Every expected constituent M1 bar must exist exactly once; otherwise the signal bar is unavailable.
- A signal bar is usable only at its close.
- Signal ATR is the simple mean of true range for the fourteen signal bars strictly preceding the tested bar.
- The first searchable signal bar must open at or after the frozen original entry timestamp.
- Entry occurs at the open of the signal bar immediately after the completed final retest bar.

## Point-in-time directional and location eligibility

Recompute the frozen macro score relative to the actual trade direction:

- `ALIGNED`: direction-adjusted score at least +20, coverage at least 50 and confidence at least 35.
- `OPPOSED`: direction-adjusted score at most -20 with the same quality floors.
- `NEUTRAL_OR_WEAK`: a valid snapshot not meeting either directional threshold.
- `UNKNOWN`: missing or stale snapshot.

`OPPOSED` and `UNKNOWN` are no-trade states. `ALIGNED` and `NEUTRAL_OR_WEAK` are eligible and must be reported separately.

Higher-timeframe location is recomputed relative to the actual trade direction from only known H1, H4, daily and weekly states appropriate to the setup timeframe. At least one known higher-timeframe component must align. Zero alignment is a no-trade state.

## Frozen source-model mapping

Exactly three entry families exist:

| Family | Frozen source models |
|---|---|
| `BREAKOUT_ACCEPTANCE_FIRST_RETEST` | `RUNAWAY_BREAKOUT`, `BREAK_RETEST_CONTINUATION` |
| `SWEEP_RECLAIM_STRUCTURE_FIRST_RETEST` | `FALSE_CONTINUATION_REVERSAL`, `IMMEDIATE_FAILURE_REVERSAL`, `TWO_SIDED_REFERENCE_RETEST` |
| `DEEP_PULLBACK_DISPLACEMENT_FIRST_RETEST` | `DEEP_RETRACE_CONTINUATION` |

No source model may migrate to another family after results.

## Primary sequence parameters

- Parent-ATR breakout clearance: 0.05 ATR.
- Parent-ATR sweep excursion: 0.05 ATR.
- Parent-ATR reclaim clearance: 0.02 ATR.
- Parent-ATR retest tolerance: 0.10 ATR.
- Parent-ATR retest closing clearance: 0.05 ATR.
- Initial-state search: first 12 signal bars.
- Transition/displacement search: next 8 signal bars.
- Retest search: next 8 signal bars.
- Displacement range: at least 1.25 times prior signal ATR14.
- Displacement body fraction: at least 0.60.
- Directional close location: outer 20% of the bar.
- Micro-structure lookback: the three complete signal bars preceding displacement.
- Track-B stop buffer: 0.05 parent ATR beyond the completed retest-bar adverse extreme.
- Minimum gross target room at delayed entry: 1.00R.

### Family 1: breakout acceptance then first retest

The frozen level is the directional confirmation extreme. Within the initial window, two consecutive signal bars must close beyond the level; the second must close at least the breakout clearance beyond it. The first later bar within the retest window is valid when it touches the level plus the retest tolerance, closes at least the retest closing clearance on the trade side, closes with an aligned body, and does not close more than the breakout clearance through the invalid side.

### Family 2: sweep/reclaim, structure break, then first retest

For reversal source models the frozen level is the confirmation extreme on the adverse side of the actual trade; for `TWO_SIDED_REFERENCE_RETEST` it is the frozen reference level. A sweep bar must exceed the level adversely by the sweep excursion and close reclaimed by the reclaim clearance. Within the transition window, an aligned displacement bar must satisfy the range, body and close-location gates and close through the directional extreme of the preceding three complete signal bars. The first later bar satisfying the common retest rule at that broken micro level completes the sequence.

### Family 3: deep pullback, displacement, then first retest

Starting at the frozen deep-pullback anchor, an aligned displacement bar within the initial window must satisfy the range, body and close-location gates and close through the directional extreme of the preceding three complete signal bars. The first later bar satisfying the common retest rule at that broken micro level completes the sequence.

## Pre-entry no-trade conditions

An entry is unavailable when:

- the macro or higher-timeframe gate fails;
- any required bar, ATR or level is unavailable;
- the complete sequence does not form before the original deadline;
- the original target was touched before the delayed entry;
- target or stop is not on the correct side of the delayed entry;
- gross target room is below 1.00R;
- whole-ounce sizing cannot keep planned stop-plus-cost risk at or below $50.

Pre-entry contact with the original stop does not itself invalidate a later reclaim setup because no position yet exists.

## Execution tracks

Both tracks are preregistered for every setup whose sequence forms:

- `TRACK_A_ORIGINAL_STOP`: delayed entry, original frozen absolute stop, original target and original deadline.
- `TRACK_B_CONFIRMED_RETEST_STOP`: same delayed entry, stop beyond the completed retest-bar adverse extreme by 0.05 parent ATR, original target and original deadline.

Retain observed entry spread or $0.30/oz fallback, $0.07/oz commission, $0.10/oz slippage, 1.5x and 2x cost stresses, stop-first treatment inside an ambiguous M1 bar, gap-aware stop fills, $50 planned risk, whole-ounce sizing, no compounding and one open XAUUSD position per candidate.

## Frozen sensitivity bundles

Sensitivity bundles receive no candidate credit and cannot replace the primary rule:

- `LENIENT`: clearance 0.00, sweep 0.025, reclaim 0.00, retest tolerance 0.15, retest close 0.00, displacement range 1.00 signal ATR, body 0.50, close location 2/3, Track-B stop buffer 0.00 parent ATR.
- `STRICT`: clearance 0.10, sweep 0.075, reclaim 0.05, retest tolerance 0.05, retest close 0.10, displacement range 1.50 signal ATR, body 2/3, close location 0.85, Track-B stop buffer 0.10 parent ATR.

A primary economic candidate requires positive OOF net expectancy under both bundles. Windows, levels, target-room gate and all other rules remain unchanged.

## GC order-flow incremental study

For a base candidate on an existing covered London or New York date, use only complete one-second GC buckets ending no later than its entry decision. Over the preceding 60 seconds calculate:

- signed aggressive-trade imbalance;
- signed quote OFI;
- opposing aggression absorbed when midpoint change does not move adversely;
- final valid depth and microprice pressure.

`GC_COMPOSITE_ALIGNED` requires at least two of: aligned aggression and OFI; aligned depth and microprice pressure; or qualifying opposing-flow absorption. All underlying buckets must be continuous, uncrossed, two-sided and technically available. The comparison is paired and incremental only. It cannot create a candidate or rescue a base rejection.

## Evaluation and gates

Candidate identity is timeframe x source model x execution track: 36 frozen primary tests. Apply one-position overlap independently within each candidate using entry timestamp then stable trade ID.

Primary performance is the blocked OOF validation union:

- Fold 1: 2022-07-01 through 2023-03-31.
- Fold 2: 2023-04-01 through 2023-12-31.
- Fold 3: 2024-01-01 through 2024-12-31.

Post-overlap support floors:

- M15: 100 trades, 75 dates and 40 ISO weeks.
- H1: 50 trades, 40 dates and 25 ISO weeks.
- H4: 30 trades, 25 dates and 15 ISO weeks.

Use 5,000 trading-date clustered bootstrap resamples and Benjamini-Hochberg correction at q=0.10 separately within each timeframe across all twelve primary tests. Formal PASS requires:

- all support floors;
- positive net expectancy and profit factor at least 1.05;
- clustered 95% confidence lower bound above zero;
- BH q no greater than 0.10;
- positive expectancy at 1.5x costs;
- at least two positive validation folds;
- at least two positive years and no one positive year contributing more than 70%;
- at least two positive session states and no one positive session contributing more than 70%;
- positive expectancy under both sensitivity bundles.

Rank passing candidates by confidence lower bound, stressed expectancy, profit factor, support, lower drawdown and stable ID. Freeze no more than two candidates per timeframe. Zero is acceptable.

## Forward and stopping policy

If the development shortlist is empty, do not inspect 2025/2026 and stop with rejection. Otherwise seal definitions and development results first, then apply once and unchanged to existing 2025 and 2026 through 2026-07-29 as exposed historical robustness evidence with no independent-validation credit. Initialize an append-only prospective paper ledger only for a development-passing frozen system.

Independently reproduce all materialization, outcomes, economics and summaries. Record every unavailable setup, support failure and negative result. Do not retune, invert, repair, relabel, remove losses or use future-formed levels.
