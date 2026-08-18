# GC Microstructure Step 4A — Deterministic Feature Engineering

## Scope

- Permanently engineering-only date: `2024-01-09`.
- Vendor MBP-10 is authoritative for top-ten book state.
- MBO contributes receive-time one-second event-flow aggregates only.
- No MBO-to-MBP row alignment or comparator correction was performed.

## Formal verdict

`FAIL_FEATURE_INTEGRITY`

- MBO source rows: 2,322,905.
- MBP-10 source rows: 1,924,786.
- Output buckets: 86,400.
- Feature columns: 85.
- Buckets with MBO records: 63,560.
- Buckets with MBP-10 updates: 59,590.
- State-available buckets: 85,943.
- Two-sided buckets: 85,943.
- Continuous crossed-book rows: 1.
- Empty-level violations: 0.
- Negative size/count values: 0.

## Independent reproduction

- Reproduction pass: `true`.
- Complete-row checksum: `10e9282feaedd99bf13ad4e77415c49c3a6b193bf87a4fc184abce57da96fd30`.
- Feature payload SHA-256: `b559771bc332f400900da43e3c16619a5b75b9457c2a15975d390e977085eda3`.

## Restrictions honored

No additional data, other date, future outcome, signal, candidate, execution optimization, trade, PnL, R multiple, or account return was accessed or calculated.

Feature payload values were sealed without human or model inspection and receive zero research or validation credit.
