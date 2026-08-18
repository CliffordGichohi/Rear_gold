# Gold Pullback Behavioural Archetypes Contract V1

Status: `FROZEN_BEFORE_ARCHETYPE_ASSIGNMENT`

## Objective

Partition the sealed 2021-08-01 through 2024-12-31 STANDARD-scale M15, H1 and H4
trend-pullback population into deterministic, mutually exclusive path archetypes.
The purpose is to describe the recurring ways in which pullbacks resolve and to
identify point-in-time facts that may later distinguish those archetypes.

This is post-hoc development description. It does not create a trading candidate,
receive validation credit, or authorize opening calendar 2025 or 2026.

## Population and technical coverage

The governing denominator is every research-eligible, feature-available,
point-in-time actionable STANDARD pullback whose frozen structural resolution is
either `CONTINUED` or `FAILED_STRUCTURE_SWITCH`.

A behavioural assignment requires:

- a complete sealed movement-anatomy path;
- exactly one sealed status row for each of `CONFIRMATION_EXTREME_BREAK`,
  `RESPONSE_HALF_RETRACE_LIMIT`, and `BREAK_RETEST_CONFIRM`; and
- valid trigger timestamps whenever a trigger status is `FORMED`.

Cases failing these requirements remain in the denominator as
`UNAVAILABLE_TECHNICAL`. They must not be forced into a behavioural archetype,
discarded, imputed, or repaired.

## Frozen archetype precedence

Apply the following rules in this exact order. Trigger formation uses the already
sealed maximum wait of four completed parent bars.

### Structurally continued cases

1. `DEEP_RETRACE_CONTINUATION`
   - `RESPONSE_HALF_RETRACE_LIMIT` formed; and
   - `BREAK_RETEST_CONFIRM` did not form, or the half-retrace timestamp was no
     later than the break-retest timestamp.

2. `BREAK_RETEST_CONTINUATION`
   - not assigned to the preceding group; and
   - `BREAK_RETEST_CONFIRM` formed.

3. `RUNAWAY_CONTINUATION`
   - not assigned above;
   - `CONFIRMATION_EXTREME_BREAK` formed; and
   - `RESPONSE_HALF_RETRACE_LIMIT` did not form.

4. `TWO_SIDED_CHOPPY`
   - every remaining structurally continued case.

### Structurally failed cases

5. `FALSE_CONTINUATION`
   - `CONFIRMATION_EXTREME_BREAK` formed before the later opposing structure
     switch.

6. `IMMEDIATE_FAILURE`
   - the confirmation-extreme break did not form; and
   - the adverse 0.50-ATR barrier was reached before the favourable barrier.

7. `TWO_SIDED_CHOPPY`
   - every remaining structurally failed case, including favourable-first,
     same-bar, neither-barrier, or otherwise residual completed paths.

Every technically eligible case must receive exactly one of the six unique labels:
`RUNAWAY_CONTINUATION`, `BREAK_RETEST_CONTINUATION`,
`DEEP_RETRACE_CONTINUATION`, `FALSE_CONTINUATION`, `IMMEDIATE_FAILURE`, or
`TWO_SIDED_CHOPPY`.

## Measurements

Report separately by timeframe and archetype:

- cases, share, dates, weeks and monthly recurrence;
- direction, session and year counts;
- complete visual-pivot-to-maximum and post-confirmation MFE/MAE in ATR and
  dollars per ounce;
- time to maximum favourable and adverse excursion;
- confirmation-break, half-retrace, break-retest and reference-retest formation;
- completed-candle response, level interaction, higher-timeframe, fundamental
  and COT summaries available by the decision timestamp; and
- the already defined oracle account ceiling in which continued cases capture
  their visual-pivot-to-maximum distance and failed cases lose exactly 1R.

The oracle ledger uses fixed $50 risk and a constant 1-ATR risk unit. It excludes
costs, overlaps, confirmation delay, fill feasibility and compounding and must be
labelled as a non-tradable opportunity ceiling.

## Integrity

- Run independent primary and reference assignments.
- Require identical population identities, technical-unavailability identities,
  archetype assignments, summaries and checksums.
- Preserve every source and predecessor artifact unchanged.
- Do not retune the taxonomy after counts are visible.
- Do not inspect 2025 or 2026, optimize execution, or claim an edge.

