# Gold Fundamental-Aligned Multi-Timeframe Auction Edge Discovery V1 — Final Report

Status: **REJECT_NO_ECONOMICALLY_TRADABLE_CANDIDATE**

## Honest verdict

No preregistered setup passed. The individual setup populations were below the frozen 60-trade support floor before any performance claim; any favourable descriptive statistic therefore cannot be promoted as a tradable edge.

## Development economics

| Test | Signals | Trades | Win rate | Net expectancy (R) | Profit factor | 95% CI | Verdict |
|---|---:|---:|---:|---:|---:|---|---|
| LONDON|FAMAE_ALIGNED_SWEEP_RECLAIM | 57 | 45 | 33.333333333333% | -1.075539393694 | 0.26929712409 | [-1.558564382551, -0.559099057551] | SUPPORT_FAIL |
| LONDON|FAMAE_ALIGNED_BREAK_RETEST | 38 | 24 | 20.833333333333% | -0.926253506715 | 0.255785563694 | [-1.422606703278, -0.355425503467] | SUPPORT_FAIL |
| LONDON|FAMAE_ALIGNED_FAILED_ACCEPTANCE | 50 | 36 | 27.777777777778% | -0.902714104824 | 0.309551027568 | [-1.397201562447, -0.380132385023] | SUPPORT_FAIL |
| NEW_YORK|FAMAE_ALIGNED_SWEEP_RECLAIM | 42 | 36 | 33.333333333333% | -0.651313130834 | 0.436349288612 | [-1.152957150292, -0.130950309443] | SUPPORT_FAIL |
| NEW_YORK|FAMAE_ALIGNED_BREAK_RETEST | 25 | 13 | 38.461538461538% | -0.196634247012 | 0.768218656254 | [-0.959822096197, 0.63470531615] | SUPPORT_FAIL |
| NEW_YORK|FAMAE_ALIGNED_FAILED_ACCEPTANCE | 36 | 32 | 40.625% | -0.24733466754 | 0.711580648703 | [-0.76062714802, 0.300221021451] | SUPPORT_FAIL |

## Session portfolio diagnostics

These pooled results were frozen as diagnostics, not candidate tests.

| Portfolio | Trades | Net expectancy (R) | Profit factor | Net PnL on $10k diagnostic | Max DD |
|---|---:|---:|---:|---:|---:|
| LONDON|EARLIEST_FROZEN_SETUP | 49 | -1.079219139298 | 0.25288674866 | $-2629.683200000001 | 26.296832% |
| NEW_YORK|EARLIEST_FROZEN_SETUP | 37 | -0.625509997291 | 0.441950149024 | $-1149.984400000003 | 14.17783185548% |

## GC incremental value

Only 4 covered executed trades had frozen same-direction GC confirmation; every GC test failed its preregistered support floor. No incremental-value claim is permitted.

## Forward and prospective disposition

Frozen development candidates: **0**. Because no candidate passed, 2025 and 2026 market values were not opened for this branch. The append-only prospective ledger was initialized with no active candidate.

## Reproduction and integrity

Primary and reference implementations produced byte-identical trade Parquet files and identical statistics. Development outcomes were opened once; forward values were not accessed; paid acquisition was $0.
