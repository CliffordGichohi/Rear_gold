# GC Session State-Transition Edge Discovery Contract V1

Status: `FROZEN_BEFORE_OUTCOME_ACCESS`

Frozen: 2026-08-06T11:54:05Z

## Purpose

This branch asks a new and bounded research question: after a fully confirmed, point-in-time gold session state transition, does price reach an equally scaled favorable boundary before an adverse boundary, and is that behavior materially stronger when the event agrees with the already-known fundamental or structure context?

It is discovery, not an attempt to prove a preferred strategy. A zero-candidate result is valid. Every earlier rejection remains a rejection and receives no credit here.

## Frozen data boundary

- Development only: 2021-08-01 through 2024-12-31.
- XAUUSD: the complete sealed IC Markets MT5 one-minute source and the sealed V3 session-case decision projection.
- GC liquidity: only the already sealed primary/reference V2-R1 event rows on the existing 188 research dates. No new Databento request is permitted.
- Permanently engineering-only dates excluded from all research credit: 2024-01-05, 2024-01-09, 2024-01-11, 2024-01-30, 2024-01-31, and 2024-03-20.
- Calendar 2025 and calendar 2026 remain locked. A reader must stop before the first 2025 record.
- London and New York are separate research and multiplicity families.

## Causal and epistemic boundary

- Fundamentals are point-in-time directional context. They are never an entry or proof of causation.
- XAUUSD levels are compared only with XAUUSD prices. GC prices are never mixed numerically with broker spot prices.
- GC order-flow labels remain `INFERRED`; they do not assert that a named institution or motive was observed.
- Event confirmation occurs only after the confirming bar or GC bucket is complete and available.

## Frozen session clock

- London timezone: `Europe/London`.
- New York timezone: `America/New_York`.
- Candidate event confirmations: 08:15:00 through 11:00:00 local, inclusive.
- The primary 60-minute path therefore ends no later than 12:00 local.
- DST conversion uses the IANA timezone database for each session-date; hard-coded offsets are forbidden.

## Frozen XAUUSD event taxonomy

All one-minute and five-minute bars must be unique, complete, timely, and contiguous across each event window. A gap makes the affected event unavailable.

1. `LEVEL_SWEEP_RECLAIM`: price trades strictly beyond an eligible upper/lower level and closes back inside on the same or immediately following complete one-minute bar before two-close acceptance. Prior points toward the reclaim.
2. `LEVEL_BREAK_ACCEPT`: two consecutive complete one-minute closes occur strictly beyond an eligible level. Prior points with the break.
3. `LEVEL_FAILED_ACCEPTANCE`: within the next five complete one-minute bars after acceptance, price first closes back inside. Prior points toward the failure/reclaim.
4. `STRUCTURE_BREAK_CONTINUATION`: a complete five-minute close crosses the latest point-in-time confirmed two-left/two-right swing in the direction of the current structure regime, or establishes the initial regime. The swing becomes knowable only at the close of the second following five-minute bar.
5. `STRUCTURE_STATE_REVERSAL`: a complete five-minute close crosses a confirmed swing opposite the established structure regime and changes that regime. This is distinct from continuation and is never double-counted.
6. `COMPRESSION_EXPANSION_BREAK`: the preceding six complete five-minute bars have total high-low width no greater than 2.5 times the point-in-time ATR20; the confirming bar has true range at least 1.5 times ATR20 and closes strictly outside that six-bar range. Prior points with the close.

Eligible level families are `ASIA_RANGE`, `PRIOR_DAY_RANGE`, `SESSION_OPENING_RANGE_15`, and, for New York only, `LONDON_PRE_NEW_YORK_RANGE`. The opening range is the first fifteen complete local-session minutes. Asia and prior-day levels must come from the point-in-time sealed case state.

The point-in-time scale is simple ATR20 of complete five-minute true ranges, available at the event decision. At least twenty-one contiguous five-minute bars are required. No scale threshold is fitted from outcomes.

## Frozen GC event taxonomy

The existing sealed V2-R1 definitions and event identities are reused unchanged:

- `FLOW_DEPTH_ALIGNMENT_ONSET`
- `ABSORPTION_ONSET`
- `FRAGILITY_FLOW_ONSET`

Only events on the existing covered dates and inside the frozen session clock are eligible. No raw GC re-materialization or correction is authorized.

## Canonicalization

- First event per session-date, event family, direction, and level family.
- Simultaneous identical family/direction level events are merged with a sorted level-family list.
- At most three earliest canonical events per family and session-date.
- Structure, compression, and GC events retain at most the first event per family and direction per session-date.
- Event identity is a deterministic hash of source identity, family, direction, confirmation time, and evidence identity.
- The first-event-only sensitivity retains only the earliest event per family and session-date.

## Frozen point-in-time contexts

- `MACRO_CONCORDANT`: session-open macro engine bias is `BULLISH` for an UP event or `BEARISH` for a DOWN event. Neutral, conflicted, stale, and unknown are not concordant.
- `MACRO_REAL_USD_CONCORDANT`: `MACRO_CONCORDANT` and the point-in-time real-yield/USD confirmation is `GOLD_BULLISH` for UP or `GOLD_BEARISH` for DOWN.
- `SESSION_OPEN_STRUCTURE_CONCORDANT`: the sealed session-open 15-minute and one-hour trends are jointly bullish for UP or jointly bearish for DOWN.
- `GC_CONFIRMING_WITHIN_5M`: on a GC-covered date, another sealed eligible GC event of the same direction and a different event identity has confirmed in `[event_time-5m,event_time]`. For a GC trigger, the confirming event must also belong to a different GC event family. Its comparison population is restricted to GC-covered events with valid GC coverage and no such confirmation.

No context is dynamically backfilled after session open. A scheduled or released fact unavailable at the event time remains unknown.

## Frozen outcomes

The event anchor is the close of the complete XAUUSD one-minute bar ending at `decision_at`; it is a measurement anchor, not a fill.

- Scale: point-in-time ATR20 of complete five-minute bars.
- Barrier distance: exactly `1.0 * ATR20` on each side of the anchor.
- Primary horizon: 60 complete one-minute bars strictly after the event anchor.
- Diagnostic horizons: 30 and 120 minutes. Diagnostics cannot rescue a failed primary result.
- First passage: `FAVORABLE_FIRST`, `ADVERSE_FIRST`, `BOTH_SAME_BAR`, `NEITHER`, or `UNKNOWN`.
- Primary first-passage score: +1, -1, 0, 0, or unavailable respectively.
- Favorable excursion: maximum expected-direction intrabar displacement from anchor divided by ATR20.
- Adverse excursion: maximum opposite-direction intrabar displacement from anchor divided by ATR20.
- Path dominance: favorable excursion minus adverse excursion.

If both barriers occur in the same one-minute bar, order is unknowable and the score is zero. Missing, late, duplicate, or noncontiguous required bars make the corresponding horizon unknown. No interpolation is allowed.

These are neutral path measurements. This branch does not define an entry, fill, stop, target, spread, slippage, commission, position size, trade, PnL, R multiple, or account return.

## Frozen tests

Stage 1 tests each of the nine registered event families separately against zero expected first-passage score.

Stage 2 tests each event family with exactly one of the four registered contexts above against the known-context complement of the same session and event family. No three-way interaction is permitted. Every support-eligible Stage 2 test runs regardless of Stage 1 favorability.

The complete registry is therefore nine Stage 1 plus thirty-six Stage 2 tests per session before support disposition. Unsupported tests remain explicit `SUPPORT_FAIL` rows.

## Frozen support gates

Stage 1 requires at least 100 eligible events, 80 distinct dates, 24 distinct ISO-week clusters, 30 events and 25 dates in each direction, and at least 12 distinct dates in each of 2022, 2023, and 2024.

Stage 2 requires at least 50 condition events on 40 dates and 16 weeks; 75 comparison events on 60 dates and 20 weeks; at least 15 condition events and 12 condition dates in each direction; and at least eight condition dates in each of 2022, 2023, and 2024.

Unknown context rows never enter either arm. Events remain clustered by session-date and ISO week; they are not treated as independent observations.

## Frozen inference and pass gates

- Cluster-robust OLS by session-date supplies the preregistered one-sided primary p-value.
- Benjamini-Hochberg at q <= 0.05 is applied separately by session and stage across all support-eligible primary tests.
- A deterministic 5,000-resample session-date cluster bootstrap supplies 95% intervals for the absolute first-passage effect, Stage 2 lift, and median path dominance.
- Stage 1 absolute mean first-passage score must be at least +0.10. Stage 2 condition mean and condition-minus-comparison lift must each be at least +0.10.
- The 95% lower bound for the required absolute effect, Stage 2 lift where applicable, and conditioned median path dominance must be strictly positive.
- Favorable-first incidence must exceed adverse-first incidence by at least ten percentage points.
- 2022, 2023, and 2024 effects must each be positive when their frozen support floor is met; 2021 is reported but not required.
- Four chronological date blocks must show a positive effect in at least three blocks, and no adequately supported block may be below -0.05.
- UP and DOWN subgroups must each have a positive effect with their directional support floor.
- First-event-only effect must be positive and at least 50% of the all-event effect.
- Neither 30-minute nor available 120-minute diagnostics may show an effect at or below -0.05.

A test passes only every applicable gate. Verdicts are `PROVISIONAL_UNVALIDATED_CANDIDATE`, `REJECT`, and `SUPPORT_FAIL`.

## Candidate rules

- At most three provisional candidates per session; zero is acceptable.
- Rank by adjusted q-value, lower confidence bound, first-passage effect/lift, path-dominance lower bound, date support, then lexical test ID.
- Development candidates are not validated trading edges.
- No inversion, threshold repair, event relabeling, selective date filter, execution optimization, or post-result retuning is permitted.

## Reproduction and stop rule

Primary and reference implementations must reproduce exact population identities, event identities, outcome identities, support dispositions, test verdicts, and canonical result checksums. Any mismatch is a formal infrastructure failure. After the final verdict and seal, stop. Calendar 2025 and 2026 remain unopened.
