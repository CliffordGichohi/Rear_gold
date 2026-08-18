# GC Microstructure Step 4A.1 — Failure Diagnostic

## Formal status

`FAIL_DIAGNOSTIC_INTEGRITY`

## BAD_TS_RECV snapshot semantics

- Finding: `CONFIRMED`.
- BAD_TS_RECV rows: 2,745.
- Non-snapshot BAD_TS_RECV rows: 0.
- Rows violating day-start receive semantics: 0.
- Rows violating pre-start event semantics: 0.
- Rows with event time after receive time: 0.
- Rows with a disallowed snapshot action: 0.

## Continuous crossed-book row

- Finding: `NOT_CONFIRMED`.
- Continuous crossed rows: 1.
- Continuous crossed F_LAST rows: 0.
- Crossed rows completing two-sided uncrossed: 0.
- Reproduced crossed-state bucket closes: 0.
- Crossed row was F_LAST: `false`.
- Unique terminal F_LAST existed later: `false`.
- Terminal state class: `None`.
- Completion delay in nanoseconds: None.
- Completion in the same one-second bucket: `false`.

## Recommendation

`NONE`

No correction is recommended under the frozen rule.

The recommendation was not implemented.

## Restrictions honored

No market values were emitted. No feature pipeline modification, data repair, acquisition, other date, outcome, signal, execution optimization, trade, or PnL calculation occurred.
