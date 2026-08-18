# Gold Session Behaviour V3 — Amendment B

## Status and authority

This amendment is authorized solely for V3 Milestone 6A by the user's
instruction dated 2026-07-30.

Milestone 6A is a pre-result protocol and metadata-only readiness stage. It
does not authorize opening calendar-2025 or calendar-2026 market, macro,
feature, candidate-state, path, or outcome values.

This amendment preserves:

- the V3 contract and all earlier state seals;
- Milestone 4's zero-candidate discovery verdict;
- all rejected candidates and rejected ZN rules;
- Amendment A's post-hoc interpretation boundary; and
- the exact Milestone 5 shortlist.

It completes the exact forward-gate freeze required before V3 Milestone 6
may open any forward values.

## Immutable forward candidates

Exactly two candidates may enter forward evaluation. No other candidate,
condition, complement, direction, threshold, field, or interaction may be
added.

### `LONDON_VOLATILITY_DIRECTION_V0_1`

- session: London
- decision clock: 08:00 `Europe/London`
- observation window: 08:01 through 12:00 `Europe/London`
- feature: `MACRO_VOLATILITY_CHANGE`
- frozen source series: `US_VOLATILITY_INDEX`
- transform: sign of the latest point-in-time observation-to-observation
  absolute change available at the decision clock
- condition: `FALLING`
- exact complement: `RISING`
- excluded known state: `UNCHANGED`
- unknown state: any missing, stale, unverified, synthetic, unavailable, or
  otherwise ineligible feature fact
- expected effect: condition UP rate minus complement UP rate is positive
- minimum material forward effect: +7.5 percentage points
- material reverse effect: -7.5 percentage points

### `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1`

- session: New York
- decision clock: 08:00 `America/New_York`
- observation window: 08:01 through 12:00 `America/New_York`
- feature: `MACRO_FINANCIAL_STRESS_CHANGE`
- frozen source series: `US_FINANCIAL_STRESS`
- transform: sign of the latest point-in-time observation-to-observation
  absolute change available at the decision clock
- condition: `FALLING`
- exact complement: `RISING`
- excluded known state: `UNCHANGED`
- unknown state: any missing, stale, unverified, synthetic, unavailable, or
  otherwise ineligible feature fact
- expected effect: condition UP rate minus complement UP rate is positive
- minimum material forward effect: +7.5 percentage points
- material reverse effect: -7.5 percentage points

The candidates retain the label
`INTERNALLY_STABLE_POST_HOC_NO_FORWARD_VALIDATION_CREDIT` until a forward
verdict explicitly changes their evidence status. Milestone 6A itself cannot
change that label.

## Neutral outcome

The outcome remains the frozen neutral session measurement and is not a trade:

- reference: open of the first complete observed XAUUSD one-minute bar
  timestamped 08:01 in the session's IANA timezone;
- close: the final complete observed bar through 12:00 local;
- signed displacement: close minus reference;
- UP: displacement greater than +$0.01/oz;
- DOWN: displacement less than -$0.01/oz; and
- FLAT: absolute displacement at or below $0.01/oz.

FLAT outcomes remain in descriptive path summaries but are excluded from the
UP/DOWN contingency table. No entry, fill, stop, target, return, PnL, MFE,
MAE, R multiple, or account result may be inferred.

## Forward segments and fixed reporting order

The forward evaluator must report segments separately and in this order:

1. `EXPOSED_CALENDAR_2025`
   - session dates 2025-01-01 through 2025-12-31;
   - historical forward evidence only;
   - no independent-validation credit;
   - cannot tune any later calculation.
2. `LOCKED_2026_YTD`
   - session dates 2026-01-01 through 2026-07-29;
   - one-time independent holdout;
   - values remain locked until separately authorized.
3. `PROSPECTIVE_2026_POST_FREEZE`
   - session dates 2026-07-31 through 2026-12-31;
   - 2026-07-30 is excluded because no Amendment-B-compliant decision record
     was sealed before both session outcomes;
   - every decision record must be sealed before its session observation
     window begins;
   - no interim inferential verdict is permitted before 2026-12-31.

The 2025 result must be sealed before 2026 YTD is opened. Both frozen
candidates must still be evaluated in 2026 even if either receives a
calendar-2025 rejection, so selective stopping cannot hide later evidence.

No prospective session may be backfilled. A session without a decision record
sealed before 08:01 local is permanently `NOT_PROSPECTIVELY_ELIGIBLE`.

## Case eligibility and missing-data policy

A case may enter a candidate's binary comparison only when all of the
following are true:

- the session date belongs to the frozen segment;
- required XAUUSD bars are observed, complete, non-synthetic, uniquely
  canonicalized, and point-in-time available;
- the neutral reference and close are available;
- the candidate feature is derived by the frozen transform from at least two
  eligible source observations known at the decision clock;
- the feature state is exactly the condition or exact complement;
- the outcome is UP or DOWN; and
- field lineage and source record identifiers are preserved.

The following rules are immutable:

- missing, stale, unverified, synthetic, revised-over-original, or
  after-decision information is `UNKNOWN`;
- `UNKNOWN` never becomes neutral, confirmation, condition, or complement;
- `UNCHANGED` is a known excluded feature state;
- FLAT is a known excluded binary outcome;
- missing bars and sessions are never synthesized;
- overlapping MT5 exports are deduplicated by canonical database identity and
  source hash;
- no source may be substituted after forward values are opened; and
- unavailable cases remain in the coverage ledger with an explicit reason.

Original point-in-time records control. Later revisions cannot replace the
record that was knowable at the decision clock.

## Per-segment support floors

Support is assessed separately for each candidate and segment before its
inferential p-value is assigned.

Every gate below is required:

- joint-known feature coverage: at least 50% of complete session cases;
- condition binary cases: at least 25;
- complement binary cases: at least 25;
- combined condition-plus-complement binary cases: at least 80;
- distinct condition source signatures: at least 4;
- distinct complement source signatures: at least 4;
- condition state episodes: at least 4;
- complement state episodes: at least 4; and
- zero source-record or case-key duplication.

An unsupported candidate remains in its fixed multiplicity family with raw
p-value 1.0. Insufficient support produces `INCONCLUSIVE_INSUFFICIENT_SUPPORT`,
not PASS or REJECT.

Metadata readiness uses only an upper bound on potentially complete session
cases. It cannot certify condition, complement, signature, episode, or
non-flat support without opening values. A metadata-ready label therefore
means only that the source inventory does not make the frozen support floors
impossible.

## Effect, uncertainty, and multiplicity

For each supported candidate and segment:

- primary effect: condition UP rate minus complement UP rate, in percentage
  points;
- contingency test: two-sided Fisher exact test;
- effect interval: Newcombe-Wilson 95% confidence interval;
- condition and complement median signed close displacements are reported;
- all path summaries remain neutral descriptive measurements; and
- no observation-level independence is claimed for repeated source states.

Multiplicity is fixed before values:

- method: Holm-Bonferroni step-down;
- family: exactly the two frozen candidates;
- family size: 2 in every segment, even if one lacks support;
- family alpha: 0.10;
- unsupported candidate raw p-value: 1.0; and
- no candidate or segment may be removed to improve an adjusted p-value.

The power audit uses a conservative planning calculation only:

- planned absolute effect: 7.5 percentage points;
- condition and complement planning probabilities: 53.75% and 46.25%;
- two-sided normal approximation;
- alpha 0.05, representing the first Holm threshold and the 95% interval
  requirement;
- balanced support is the best-case allocation; and
- power calculations cannot inspect or estimate forward feature states or
  outcomes.

Power is readiness information, not a gate that may alter a later verdict.

## Exact segment verdicts

Verdicts are assigned independently by candidate and segment.

### `PASS_MATERIAL_POSITIVE_REPLICATION`

Every condition below must hold:

- all support floors pass;
- effect is at least +7.5 percentage points;
- the Newcombe-Wilson 95% interval lower bound is greater than zero;
- the Holm-adjusted two-sided Fisher p-value is at most 0.10;
- condition median signed close displacement is greater than zero; and
- complement median signed close displacement is less than zero.

### `REJECT_MATERIAL_REVERSE_REPLICATION`

Every condition below must hold:

- all support floors pass;
- effect is at most -7.5 percentage points;
- the Newcombe-Wilson 95% interval upper bound is less than zero;
- the Holm-adjusted two-sided Fisher p-value is at most 0.10;
- condition median signed close displacement is less than zero; and
- complement median signed close displacement is greater than zero.

### `INCONCLUSIVE_INSUFFICIENT_SUPPORT`

This verdict applies when any frozen support floor fails.

### `INCONCLUSIVE_MIXED_OR_UNDERPOWERED`

This verdict applies when support passes but neither the complete PASS gate
nor the complete REJECT gate passes.

No isolated sign, p-value, interval, median, year, or source state can
override the complete conjunctive verdict.

## Candidate and research-branch verdicts

Calendar 2025 is real negative evidence but cannot earn independent credit:

- a 2025 PASS is labelled
  `EXPOSED_FORWARD_SUPPORTIVE_NO_INDEPENDENT_CREDIT`;
- a 2025 REJECT permanently rejects the candidate; and
- an inconclusive 2025 result neither validates nor rejects it.

The locked 2026 YTD result is independently credited:

- a PASS earns `PASS_INDEPENDENT_2026_YTD`;
- a REJECT permanently rejects the candidate; and
- an inconclusive result earns no forward-validation credit.

The prospective 2026 result is credited only at its fixed year-end endpoint:

- a PASS earns `PASS_PROSPECTIVE_2026`;
- a REJECT permanently rejects the candidate; and
- an inconclusive result earns no prospective-validation credit.

A candidate may be called a `CURRENT_DIRECTIONAL_BIAS_EDGE_CANDIDATE` only
when:

- it is not rejected in any forward segment;
- locked 2026 YTD passes; and
- prospective 2026 passes.

Otherwise its overall verdict is REJECTED if any segment rejects, or
INCONCLUSIVE if no segment rejects but the two clean-forward PASS
requirements are not both present.

The research branch may claim at least one current directional-bias candidate
only if at least one of the two candidates meets that complete rule. This
still does not authorize a trade or imply profitability.

## Metadata-only readiness rules

Milestone 6A may read only:

- provider, instrument, timeframe, series, and source identifiers;
- observation, availability, bar, and file timestamps;
- row and distinct-timestamp counts;
- completeness, synthetic, revision, and point-in-time-ordering counts;
- non-null spread and volume counts without retrieving their values;
- source file byte size and SHA-256; and
- sealed manifest metadata and hashes.

The candidate and historical segment are metadata-ready only when:

- the exact frozen macro series identifier is present;
- at least two distinct source observation periods predate the segment;
- interval metadata contains at least one valid observation;
- no candidate-series row is synthetic;
- every interval row respects availability not preceding observation;
- the exact IC Markets XAUUSD one-minute source is present;
- XAU timestamps can potentially form at least 80 complete session cases for
  the candidate's session; and
- no metadata integrity or predecessor-seal check fails.

Forward state counts, UP/DOWN counts, effects, medians, paths, prices, macro
values, charts, and row payloads are forbidden in Milestone 6A.

If metadata is ready but the best-case planned power is below 80%, the status
is `READY_WITH_LOW_POWER_EXPECTED`; this does not weaken any gate.

## Prospective tracking protocol

Milestone 6A freezes the prospective ledger requirements but creates no
market decision:

- immutable candidate code and protocol hash;
- session date and session code;
- decision clock and `as_of` timestamp;
- condition, complement, excluded, or unknown state;
- exact source record IDs and availability timestamps;
- source and decision-record hashes;
- seal timestamp before 08:01 local;
- later neutral outcome attached append-only; and
- explicit eligibility and missing reason.

Before the 2026-12-31 endpoint, only counts, missingness, and operational
health may be reported. No interim p-value, candidate verdict, threshold
change, or retrospective decision record is permitted.

## Prohibitions and mandatory stop

Milestone 6A may not:

- inspect or deserialize 2025 or 2026 market or macro values;
- derive candidate states or session outcomes;
- calculate a relationship, effect, p-value, or verdict from forward values;
- open the holdouts;
- add, remove, repair, invert, rename, filter, or retune a candidate;
- change the condition, complement, effect threshold, support floor, or
  statistical method after metadata is observed;
- add a confirming variable or use COT as a gate;
- reopen either rejected candidate or any rejected ZN rule;
- optimize execution or calculate trades, returns, PnL, or R multiples; or
- infer source readiness from pseudo or synthetic replacement data.

Milestone 6A ends after Amendment B, its machine-readable pre-result manifest,
the candidate-specific metadata-only readiness and power audit, independent
validation, documentation, and state sealing.

Opening calendar 2025 or 2026 values requires a new explicit Milestone 6B
authorization.
