# Gold Triple Macro-Acceptance Fade Validation Contract V1

## Candidate status

`TRIPLE_MACRO_ACCEPTANCE_FADE_V0_1` is a post-hoc candidate discovered only after the preregistered continuation rule failed in 2021–2024. It receives no development-validation credit. This contract freezes it before any 2025 or 2026 relationship is calculated.

## Exact rule

For every unique scheduled US macro-release timestamp:

1. Decision time is release plus five minutes.
2. `F` is the sign of the sum of every eligible standardized event-component `gold_direction` available by decision time.
3. `M` requires all three five-minute reactions to be ready and nonzero: rising ZT futures price contributes `+1`, rising ZN futures price contributes `+1`, and rising EURUSD contributes `+1`; falling values contribute `-1`. `M` is the sign of the three-vote sum.
4. `G` is the sign of XAUUSD reference-to-five-minute displacement.
5. The rule is eligible only when `F = M = G`.
6. The frozen prediction is `-M`: fade the fully confirmed first five-minute move.

No threshold, event-family filter, volatility filter, COT filter, regime filter, price-level filter, exclusion, inversion, or execution rule may be added.

## Outcomes

- Primary: sign of XAUUSD displacement from release +5 minutes through release +15 minutes.
- Consistency diagnostic: sign of XAUUSD displacement from release +5 minutes through release +60 minutes.
- Coincident releases are one timestamp-level observation.
- Flat or technically unavailable endpoints are excluded and reported.
- No entry price, stop, target, spread, slippage, PnL, R multiple, or account-return calculation is permitted.

## Validation segments

1. Calendar 2025: exposed historical forward segment. It can corroborate or reject but receives no independent-validation credit.
2. Calendar 2026 YTD through 2026-07-29: independent locked segment, opened once only after all required sources are sealed.
3. Prospective ledger after the historical segments: append-only and never backfilled.

The first failed macro-acceptance loader technically deserialized 2,164 XAUUSD rows from 1–3 January 2025 without inspecting or using them. That incident remains disclosed. No 2025 relationship for this fade candidate has been calculated.

## Required unchanged sources

- MetaQuotes/IC Markets MT5 US macro calendar for released event components and release-boundary forecasts.
- IC Markets MT5 XAUUSD one-minute bars.
- IC Markets MT5 EURUSD one-minute bars.
- Databento `GLBX.MDP3 ZT.v.0 ohlcv-1m`.
- Databento `GLBX.MDP3 ZN.v.0 ohlcv-1m`.

Existing sealed 2025 ZN data must be reused. No duplicate purchase is permitted. Source acquisition may occur only under a separate explicit price cap.

## Point-in-time and integrity gates

- Every event fact must be available no later than decision time.
- Every price input must be from a completed one-minute bar available no later than its endpoint.
- Continuous-futures instrument changes across the reference/five-minute window make `M` unknown.
- Exact timestamps are required at reference, +5m, +15m and +60m.
- Duplicate timestamp conflicts fail closed.
- 2025 and 2026 are reported separately.
- Primary and reference implementations must reproduce anchor identities, features, eligibility, outcomes, statistics and checksums exactly.

## Frozen statistics

- Raw hit rate and direction-balanced hit rate.
- Bullish-fade and bearish-fade support and hit rates.
- Mean and median signal-aligned displacement.
- Calendar-month block-bootstrap 90% interval with 20,000 resamples and seed `20260807`.
- One-sided, year-segment-preserving permutation test with 50,000 permutations and seed `20260807`.
- No multiplicity correction is needed because exactly one candidate is tested.

## Support and disposition

### Calendar 2025

- Support: at least 20 observations and at least five signals in each direction.
- PASS: direction-balanced hit rate at least 56%, positive mean and median signal-aligned displacement, bootstrap lower bound above 50%, permutation `p <= 0.10`, and one-hour direction-balanced hit rate at least 50%.
- REJECT: adequate support but any directional/effect gate fails.
- INCONCLUSIVE: support is inadequate.

### Calendar 2026 YTD

- Support: at least 10 observations and at least three signals in each direction.
- PASS: direction-balanced hit rate at least 60%, positive mean and median signal-aligned displacement, one-sided permutation `p <= 0.10`, and one-hour direction-balanced hit rate at least 50%.
- REJECT: adequate support but direction-balanced hit rate is at or below 50%, mean signal-aligned displacement is nonpositive, or the one-hour direction-balanced hit rate is below 45%.
- INCONCLUSIVE: support is inadequate or the point estimate is positive but the remaining PASS gates are not met.

## Overall verdict

- `PASS_INDEPENDENT_DIRECTIONAL_NONRANDOMNESS`: both segments pass, including independent 2026.
- `REJECT_FADE_CANDIDATE`: independent 2026 rejects, regardless of 2025.
- `INCONCLUSIVE_CONTINUE_PROSPECTIVE`: 2026 is inconclusive; no edge claim is permitted.

The result may reject randomness only for this exact conditional state. It cannot prove that every gold movement is non-random.
