# Multi-Asset Session Behaviour V1 — Milestone 1-R1

## Verdict

**`PASS_MILESTONE_1_R1_DIAGNOSTIC_REPRODUCTION`**

This is a pass for the metadata diagnostic only. The original `FAIL_MILESTONE_1_COVERAGE_STOP` remains unchanged and Milestone 2 remains unauthorized.

Primary and reference implementations independently read only `open_time`, reconstructed every maximal gap, and matched exactly on source diagnostics, run identities, classifications, summaries and semantic checksum.

## Failed-unit findings

| Unit | Incomplete identities | Missing runs | Documented unavailable minutes | Normal no-tick minutes | Genuine source-gap minutes | Unresolved minutes |
|---|---:|---:|---:|---:|---:|---:|
| `EURUSD|ASIA_SESSION` | 610 | 1,263 | 0 | 126 | 0 | 9,667 |
| `US500|LONDON_SESSION` | 394 | 2,504 | 0 | 2,564 | 0 | 3,006 |
| `USDJPY|ASIA_SESSION` | 642 | 1,318 | 0 | 40 | 0 | 10,277 |
| `XAGUSD|ASIA_SESSION` | 892 | 1,652 | 0 | 793 | 0 | 63,817 |
| `XTIUSD|LONDON_SESSION` | 286 | 1,121 | 0 | 1,128 | 0 | 2,818 |

Aggregate target run classifications: `{"NORMAL_NO_TICK_BAR_EMISSION": 4409, "UNRESOLVED": 3449}`  
Aggregate target minute classifications: `{"DOCUMENTED_MARKET_UNAVAILABLE": 0, "GENUINE_SOURCE_GAP": 0, "NORMAL_NO_TICK_BAR_EMISSION": 4651, "RECOVERABLE_EXISTING_SEALED_SOURCE": 0, "UNRESOLVED": 89585}`

The universal every-minute rule is structurally too strict for tick-generated MT5 bars where short, isolated missing M1 intervals meet the frozen no-tick semantics. Current provider schedules were not allowed to rewrite historical expectations unless the same provider-clock absence recurred in every development year under the frozen 80% gate. Longer or systematic unexplained gaps remain `UNRESOLVED`; they were not repaired or relabelled.

## Single bounded recommendation

`OBSERVED_QUOTE_PATH_VALIDITY_V0_1` replaces wall-clock-grid completeness with an observed-quote path-validity rule while preserving all identities, sessions and the 90% unit floor. It permits only corroborated documented closures and tightly bounded one- or two-minute no-tick gaps. It prohibits OHLC imputation and carry-forward; unresolved or genuine gaps remain unavailable.

The recommendation was **not implemented**. A separately authorized metadata-only Milestone 1-R2 would be required to freeze it and recertify coverage.

## Scope controls

- OHLC, spread, volume and order-flow values: not accessed.
- Outcomes, paths, archetypes, relationships, strategies, hypothetical returns, trades and PnL: not calculated.
- Calendar 2025 and 2026 values: locked.
- Acquisition and charge: none; $0.00.
