# GC Microstructure Step 4B.1 — Multi-Day Metadata Readiness

## Formal verdict

`PASS_METADATA_QUOTE_READINESS`

## Frozen engineering dates

- `2024-01-05` — LABOUR_STANDARD_TIME; UTC-06:00_CST.
- `2024-01-11` — INFLATION_STANDARD_TIME; UTC-06:00_CST.
- `2024-01-30` — FIRST_FRONT_CONTRACT_TRANSITION_PAIR_PREVIOUS_DAY; UTC-06:00_CST.
- `2024-01-31` — FIRST_FRONT_CONTRACT_TRANSITION_PAIR_EFFECTIVE_DAY; UTC-06:00_CST.
- `2024-03-20` — FOMC_DAYLIGHT_TIME; UTC-05:00_CDT.

Roll metadata: `GCG4` / instrument `41512` on 2024-01-30, changing to `GCJ4` / instrument `44740` on 2024-01-31.

## Metadata estimates

| Date | Schema | Cost (USD) | Records | Billable bytes |
|---|---:|---:|---:|---:|
| 2024-01-05 | mbo | 0.306501 | 3,264,913 | 182,835,128 |
| 2024-01-05 | mbp-10 | 0.462647 | 2,699,804 | 993,527,872 |
| 2024-01-11 | mbo | 0.358945 | 3,823,552 | 214,118,912 |
| 2024-01-11 | mbp-10 | 0.548897 | 3,203,119 | 1,178,747,792 |
| 2024-01-30 | mbo | 0.013471 | 143,495 | 8,035,720 |
| 2024-01-30 | mbp-10 | 0.024036 | 140,265 | 51,617,520 |
| 2024-01-31 | mbo | 0.303214 | 3,229,893 | 180,874,008 |
| 2024-01-31 | mbp-10 | 0.453824 | 2,648,313 | 974,579,184 |
| 2024-03-20 | mbo | 0.312984 | 3,333,973 | 186,702,488 |
| 2024-03-20 | mbp-10 | 0.455936 | 2,660,637 | 979,114,416 |

## Totals

- mbo: `$1.295115`, 13,795,826 records, 772,566,256 billable bytes.
- mbp-10: `$1.945340`, 11,352,138 records, 4,177,586,784 billable bytes.
- Combined: `$3.240456`, 25,147,964 records, 4,950,153,040 billable bytes.

## Restrictions honored

Only calendar metadata, instrument symbology, and Databento metadata estimate endpoints were used. No batch job, time-series request, download, charge, market value, outcome, signal, execution, or PnL was accessed.

All five dates are permanently engineering-only and receive zero research or validation credit.
