# Gold January H1 Swing Loss Attribution V1

Status: **FROZEN BEFORE THIS ATTRIBUTION RUN**

Research credit: **EXPOSED JANUARY 2022 DIAGNOSTIC ONLY**

## Fixed population and execution

- Reconstruct the same January H1 local-pivot population shown in the approved
  continuous atlas: pivot width two bars on each side, 14-bar ATR, minimum
  prominence 0.25 ATR and the existing tick floor.
- A pivot becomes actionable only at its recorded confirmation timestamp.
- Enter at the first M1 open at or after confirmation.
- For a confirmed H1 low, go LONG, stop at that low and target the most recent
  causally known preceding H1 high. Reverse the geometry for a confirmed high.
- Exclude only a confirmation outside January, missing causal geometry, or an
  entry not strictly between stop and target.
- Resolve every executable case independently through 2022-02-01T00:00:00Z.
  If stop and target occur in one M1 bar, count stop first.
- Do not apply costs, overlap controls or position-size rounding in this
  diagnostic. One stopped trade equals -1R; a target equals its point-in-time
  target distance divided by its stop distance.

## Preregistered R-room views

Report the unchanged all-trade control, then admit trades whose target room at
entry is at least 1.5R and at least 2.0R. These are descriptive exposed views,
not optimized thresholds. Report support, wins, losses, win rate, gross winning
R, losing R, net R, profit factor, expectancy, winners rejected, winning R
rejected and losses avoided.

## Loss-path attribution

For every stopped case, report whether its unchanged target was reached later
before month-end. Conservatively measure favorable excursion before the stop
bar and classify it as below 0.25R, 0.25-0.5R, 0.5-1R or at least 1R.

Compare target-first and stopped cases using only facts available at entry:

- current same-kind H1 swing relation;
- contained/internal versus external-break role;
- H1 and H4 external-structure alignment;
- whether an H1 close had already consumed the target level;
- session;
- planned target R.

These comparisons are attribution, not causal proof. Do not change a rule,
create a candidate or open another period during this run.

