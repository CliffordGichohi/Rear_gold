# Gold Continuation-Refresh True Negation Fixed-Quantity Exposed Diagnostic V1

Status: `AUTHORIZED_CORRECTIVE_TRUE_NEGATION`

Preserve every previous result and artifact.  Classify the +467R direct-
inversion result as a re-risked sizing diagnostic that does not answer the
requested strategy-negation question.

Use exactly the 434 continuation-refresh plans and 214 unchanged plans from the
sealed 648-trade V2-R1 population.  For each continuation-refresh plan:

- Preserve the original whole-ounce quantity calculated from the original
  entry-to-structural-stop distance and the $50 benchmark.
- Preserve the decision timestamp, one-minute latency, deadline and costs.
- Change `LONG` to `SHORT` and `SHORT` to `LONG`.
- Make the original absolute TP the new absolute SL.
- Make the original absolute SL the new absolute TP.
- Use the frozen original quantity without recalculation against the new stop.

Do not cap, scale, resize, normalize, filter or replace any quantity.  Do not
introduce a risk exception.  Report actual inverted stop exposure separately,
but calculate comparative R as net dollars divided by the unchanged $50
benchmark.

Keep the remaining 214 non-continuation plans and their execution unchanged.
Allow the same unrestricted overlaps.  Run independent primary and reference
passes using only the already exposed January-June 2022 sources.  Open no new
date, 2025 or 2026, test no alternative, and seal the result with zero
validation credit.
