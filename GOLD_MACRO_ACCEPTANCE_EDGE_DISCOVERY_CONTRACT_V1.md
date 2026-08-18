# Gold Macro-Acceptance Edge Discovery Contract V1

## Research claim and burden of proof

The null hypothesis is:

> Conditional on information genuinely available at the frozen decision timestamp, the direction of the subsequent XAUUSD move is no more predictable than its contemporaneous base rate or year-preserving shuffled outcomes.

This branch must reject that null before describing any condition as a provisional edge. Non-random volatility, session timing, or event clustering alone does not qualify as a directional edge.

## Boundaries

- Development interval: 2021-08-01T00:00:00Z through 2025-01-01T00:00:00Z, end exclusive.
- Population: the 346 unique release timestamps represented by 408 sealed scheduled US event cases inside that interval.
- Coincident releases are collapsed into one timestamp-level observation before any analysis.
- Calendar 2025 is exposed historical forward data and remains unopened in this milestone.
- Calendar 2026 remains the independent locked holdout and is unopened.
- Existing source hashes and dispositions are bound through the sealed Gold Macro-Acceptance Source Inventory V1.
- No acquisition, charge, parameter search, execution construction, PnL, R multiple, or account-return calculation is permitted.

## Eligible sources

Only these existing sealed inputs may be used:

1. `events.jsonl.gz`: event identity, release availability, standardized surprise gold direction, and fixed reaction snapshots.
2. `fundamentals.jsonl.gz`: the latest point-in-time fundamental engine snapshot available no later than the decision timestamp.
3. `positioning.jsonl.gz`: the latest COT report published no later than the decision timestamp.
4. Pre-2025 IC Markets MT5 XAUUSD one-minute bars: completed Asian range and five-minute acceptance/rejection state only.
5. The sealed fixed-horizon XAUUSD, EURUSD, ZT and ZN reaction facts contained in each event case.

No historical MT5 forecast is used before release. Standardized surprise direction is eligible only after the event is available and therefore only at the five-minute decision timestamp.

## Anchor and decision timestamp

- Anchor identity: exact `released_at` timestamp.
- Decision timestamp: `released_at + 5 minutes`.
- Every feature must have `available_at <= decision timestamp`.
- Every fixed-horizon input must be `READY`; otherwise the corresponding feature is `UNKNOWN`.
- A zero directional change is `UNKNOWN`, never forced bullish or bearish.

## Frozen features

### Fundamental impulse `F`

For all standardized surprise components belonging to all event cases at the same release timestamp:

1. retain only components available by the decision timestamp;
2. sum their frozen `gold_direction` values;
3. `F = +1` when the sum is positive, `F = -1` when negative, and `UNKNOWN` when absent or exactly zero.

No event-family weight, importance weight, threshold, inversion, or post-result component selection is allowed.

### Market repricing impulse `M`

At the fixed five-minute horizon:

- rising `ZT.v.0` price contributes `+1` for gold;
- rising `ZN.v.0` price contributes `+1` for gold;
- rising EURUSD contributes `+1` for gold;
- falling values contribute `-1`.

All three must be `READY` and nonzero. `M` is the sign of their three-vote sum. This is an observed market-repricing interpretation, not a cash-yield or DXY observation.

### Initial gold response `G`

`G` is the sign of the sealed XAUUSD reference-to-five-minute absolute change. It must be `READY` and nonzero.

### Prior macro bias `B`

Take the latest sealed fundamental snapshot with `available_at <= decision timestamp`. `B` is the sign of its frozen `engine_state.directional_score`; exactly zero or no eligible snapshot is `UNKNOWN`.

### COT crowding `C`

Take the latest report with `available_at <= decision timestamp`. Only the frozen inferred values `CROWDED_LONGS`, `CROWDED_SHORTS`, or another non-crowded state may be used. COT is context and never treated as direct observed institutional intent.

### Asian range and state

- Session date is the event timestamp converted to `Europe/London`, then interpreted as that calendar date.
- Asian range is exactly `[10:05, 16:00)` in `Asia/Tokyo`, matching the sealed casebook definition.
- The range is eligible only when all 355 expected one-minute opens exist exactly once and their bars were available before the event.
- Same-direction accepted break: the final two completed one-minute closes at or before the five-minute decision are both strictly beyond the Asian high for `+1`, or below the Asian low for `-1`.
- Same-direction failed break: at least one post-release bar through the decision breaches the corresponding Asian boundary by high/low, while the decision close is back inside the inclusive Asian range.

## Frozen endpoints

- Primary endpoint: sign of XAUUSD displacement from the five-minute snapshot to the fifteen-minute snapshot.
- Consistency endpoint: sign of displacement from the five-minute snapshot to the one-hour snapshot.
- Continuous effects: predicted-direction-signed absolute and percentage displacement over the same horizons.
- Flat or unavailable outcomes are excluded for that endpoint and reported explicitly.
- Fixed execution, stops, targets, spreads, slippage and PnL are not part of this milestone.

## Frozen Stage-1 tests

Each rule emits only `-1`, `+1`, or no signal:

1. `MACRO_FUNDAMENTAL_ONLY`: signal `F`.
2. `MARKET_REPRICING_ONLY`: signal `M`.
3. `INITIAL_GOLD_MOMENTUM`: signal `G`.
4. `FUNDAMENTAL_MARKET_CONSENSUS`: require `F = M`; signal `M`.
5. `MARKET_GOLD_ACCEPTANCE`: require `M = G`; signal `M`.
6. `TRIPLE_MACRO_ACCEPTANCE`: require `F = M = G`; signal `M`.
7. `TRIPLE_WITH_PRIOR_BIAS`: require `B = F = M = G`; signal `M`.
8. `TRIPLE_NOT_CROWDED`: require `F = M = G` and exclude bullish signals with `CROWDED_LONGS` and bearish signals with `CROWDED_SHORTS`; signal `M`.
9. `TRIPLE_ASIA_BREAK_ACCEPTANCE`: require `F = M = G` plus a same-direction accepted Asian-range break; signal `M`.
10. `MACRO_REJECTION_TOWARD_MACRO`: require `F = M` and `G = -M`; signal `M`.
11. `FUNDAMENTAL_MARKET_CONTRADICTION_TRUST_MARKET`: require `F = -M`; signal `M`.
12. `FAILED_ASIA_BREAK_STRUCTURE_OVERRIDE`: require `F = M` plus a same-direction failed Asian break; signal `-M`.

## Frozen Stage-2 interactions

After the complete Stage-1 result is sealed internally, test exactly these two rules separately within each of the seven event families `CPI`, `FOMC`, `GDP`, `JOBLESS_CLAIMS`, `NFP`, `PCE`, and `RETAIL_SALES`:

- `MARKET_GOLD_ACCEPTANCE::<EVENT_FAMILY>`
- `MACRO_REJECTION_TOWARD_MACRO::<EVENT_FAMILY>`

No other family slicing or interaction is allowed.

## Statistics and support

### Effect estimators

- Raw directional hit rate.
- Direction-balanced hit rate: arithmetic mean of bullish-signal and bearish-signal hit rates.
- Mean and median predicted-direction-signed displacement.
- Ninety-percent calendar-month block-bootstrap confidence interval using 10,000 resamples and seed `20260806`.
- Year-preserving outcome permutation p-value using 20,000 permutations and seed `20260806`; the signal and eligibility rows remain fixed.

### Multiplicity

Apply Benjamini-Hochberg correction at `q = 0.10` across every support-eligible Stage-1 and Stage-2 primary-endpoint test together. Unsupported tests remain `SUPPORT_FAIL` and are not replaced.

### Stage-1 support floor

- at least 40 primary-endpoint observations;
- at least 12 bullish and 12 bearish signals;
- at least four of the six frozen chronological blocks with five or more observations.

### Stage-2 support floor

- at least 18 primary-endpoint observations;
- at least five bullish and five bearish signals;
- at least three chronological blocks with four or more observations.

### Chronological blocks

1. 2021-08-01 through 2022-06-30
2. 2022-07-01 through 2022-12-31
3. 2023-01-01 through 2023-06-30
4. 2023-07-01 through 2023-12-31
5. 2024-01-01 through 2024-06-30
6. 2024-07-01 through 2024-12-31

## Candidate PASS gates

A support-eligible test is a provisional, unvalidated candidate only when every gate passes:

1. primary direction-balanced hit rate is at least 56%;
2. primary mean and median signed displacement are both positive;
3. ninety-percent month-block bootstrap lower bound for direction-balanced hit rate is greater than 50%;
4. BH-adjusted primary permutation `q <= 0.10`;
5. at least four eligible chronological blocks have raw hit rate above 50%;
6. no eligible block has raw hit rate below 42%;
7. one-hour direction-balanced hit rate is at least 47% and its mean signed displacement is nonnegative;
8. all availability, lineage, uniqueness and reproduction gates pass.

Stage-2 candidates must additionally have primary direction-balanced hit rate of at least 60% because of their smaller support floor.

At most three provisional candidates may advance, ranked by adjusted q-value, primary direction-balanced hit rate, primary median signed displacement, and support in that order. Zero candidates is acceptable.

## Independent reproduction

Two implementations must independently construct timestamp-level anchors, features, signals, endpoints and statistics. They must agree on:

- anchor identities and coincident-event grouping;
- feature availability and signs;
- rule eligibility and signals;
- endpoint values;
- every support count and test statistic to the stored precision;
- complete result checksum.

Any disagreement is a formal infrastructure failure, not an edge result.

## Interpretation

A development PASS is only a provisional candidate. It does not establish a live trading edge until the rule is frozen and survives forward validation. If all tests reject, the correct conclusion is limited to: this preregistered macro-acceptance family did not reject conditional directional randomness in the development data.
