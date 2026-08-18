# GC Microstructure Step 4B.3 — Multi-Day Feature Robustness

## Formal verdict

`PASS_MULTIDAY_FEATURE_ROBUSTNESS`

| Engineering date | Verdict | MBO rows | MBP-10 rows | Duplicate emissions | Continuous crossed bucket closes |
|---|---:|---:|---:|---:|---:|
| 2024-01-05 | PASS_FEATURE_ROBUSTNESS | 3,264,913 | 2,699,804 | 166 | 0 |
| 2024-01-11 | PASS_FEATURE_ROBUSTNESS | 3,823,552 | 3,203,119 | 342 | 0 |
| 2024-01-30 | PASS_FEATURE_ROBUSTNESS | 143,495 | 140,265 | 3 | 0 |
| 2024-01-31 | PASS_FEATURE_ROBUSTNESS | 3,229,893 | 2,648,313 | 95 | 0 |
| 2024-03-20 | PASS_FEATURE_ROBUSTNESS | 3,333,973 | 2,660,637 | 170 | 0 |

## Reproduction and scope

- Dates passed: `5/5`.
- Each date contains `86,400` ordered one-second buckets and `85` frozen columns.
- All `776` sealed exact-adjacent MBP-10 provider emissions were processed and contributed to technical update counts.
- Primary and reference results were compared for schemas, null counts, per-column hashes, complete-row hashes, diagnostics, and byte-identical Parquet payloads.
- State was initialized empty for every date and cleared at every frozen market-segment boundary.

## Restrictions honored

No data was acquired. No prices, depths, order-flow values, feature values, outcomes, directional relationships, signals, execution, trades, PnL, R multiples, or account returns were inspected or reported.

All five dates remain permanently engineering-only and receive zero research or validation credit.
