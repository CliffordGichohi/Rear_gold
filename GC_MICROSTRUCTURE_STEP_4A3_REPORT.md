# GC Microstructure Step 4A.3 — Feature-Integrity Recertification

## Formal verdict

`PASS_FEATURE_INTEGRITY_RECERTIFICATION`

The original Step 4A feature calculations were rerun unchanged. Only the two sealed integrity classifications were replaced.

## Snapshot-semantic gate

- BAD_TS_RECV rows: 2,745.
- Rows satisfying every frozen snapshot predicate: 2,745.
- Violating rows: 0.
- No flag was cleared and no source row was filtered, dropped, repaired, or relabeled.

## Bucket-close crossed-book gate

- Continuous-matching crossed bucket closes: 0 of 82,800.
- Maintenance crossed bucket closes: 0 of 2,700.
- Pre-open crossed bucket closes: 60 of 900.
- Raw continuous crossed source rows reported but not gated: 1.

## Exact feature reproduction

- Feature rows: 86,400.
- Feature columns: 85.
- Complete-row checksum: `10e9282feaedd99bf13ad4e77415c49c3a6b193bf87a4fc184abce57da96fd30`.
- Feature Parquet SHA-256: `b559771bc332f400900da43e3c16619a5b75b9457c2a15975d390e977085eda3`.
- Independent reproduction pass: `true`.

## Preserved history and restrictions

Step 4A FAIL_FEATURE_INTEGRITY, Step 4A.1 FAIL_DIAGNOSTIC_INTEGRITY, and Step 4A.2 PASS_DISPOSITION_REPRODUCTION remain unchanged.

No additional data, other date, market-value inspection, outcome, edge discovery, signal, execution optimization, trade, PnL, R multiple, or account return was accessed or calculated.

This engineering-only date receives zero research or validation credit.
