# Multi-Asset Macro and Session Portfolio Edge Discovery V1 — Milestone 2

## Verdict

**PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED**

All seven requested instruments now pass the frozen value-blind M1 source, timestamp, deduplication, session, spread, lineage, and independent-reproduction gates. Relationship discovery has not started; this milestone certifies research readiness only.

The first acquisition process was externally stopped at the command runtime limit. Its 49 complete files were hash-sealed and preserved. Timeout Recovery Amendment A reused those files, quarantined the interrupted temporary file, and requested only the 56 unfinished identical chunks. This was an engineering recovery, not a source or market-data failure.

## Certification

| Instrument | Exact MT5 symbol | Source | Classification | Canonical M1 rows | Duplicate occurrences | Minimum primary-session coverage |
|---|---|---|---|---:|---:|---:|
| XAUUSD | `XAUUSD` | REUSED_SEALED_MILESTONE_1 | PRESENT_AND_ADEQUATE | 1,210,817 | 0 | 98.77% |
| XAGUSD | `XAGUSD` | ACQUIRED_FREE_IC_MARKETS_MT5_MILESTONE_2 | PRESENT_AND_ADEQUATE | 1,210,606 | 0 | 98.77% |
| EURUSD | `EURUSD` | REUSED_SEALED_MILESTONE_1 | PRESENT_AND_ADEQUATE | 1,274,793 | 28,723 | 99.33% |
| USDJPY | `USDJPY` | ACQUIRED_FREE_IC_MARKETS_MT5_MILESTONE_2 | PRESENT_AND_ADEQUATE | 1,274,223 | 0 | 99.33% |
| NAS100 | `USTEC` | ACQUIRED_FREE_IC_MARKETS_MT5_MILESTONE_2 | PRESENT_AND_ADEQUATE | 1,210,217 | 0 | 98.77% |
| US500 | `US500` | ACQUIRED_FREE_IC_MARKETS_MT5_MILESTONE_2 | PRESENT_AND_ADEQUATE | 1,202,006 | 0 | 98.77% |
| WTI | `XTIUSD` | ACQUIRED_FREE_IC_MARKETS_MT5_MILESTONE_2 | PRESENT_AND_ADEQUATE | 1,206,576 | 0 | 98.99% |

- Newly certified canonical M1 timestamps: 6,103,628.
- Independent semantic checksum: `cd472656fc9bc967f595da2b8fb2b2e818a2188e51bbed68e0ac54ed54811ff3`.
- Primary/reference reproduction: **PASS**.
- Raw files are unchanged and canonical duplicates are resolved only by a frozen read policy.
- Existing XAUUSD and EURUSD histories were reused and were not requested again.
- Paid acquisition and card charge: **$0.00**.

## Locks and stopping point

The gold-only 10R branch remains terminated. Calendar 2025 and calendar 2026 market values remain locked. No relationships, trades, returns, or PnL were calculated. Milestone 2 stops here; a separately authorized Milestone 3 may materialize point-in-time features and open only 2021–2024 development outcomes under the already frozen research contract.
