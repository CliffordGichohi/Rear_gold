# Gold Auction Ten-Case Reusable Optimization and Replay V1 Report

Status: `PASS_SAME_TEN_REUSABLE_EXPOSED_FIT_AND_REPLAY_ZERO_VALIDATION_CREDIT`

## Direct verdict

The frozen algorithm reran exactly the same ten exposed trades from the sealed raw streams before any later data was opened. Primary and reference passes matched exactly. This is exposed fitting and implementation certification, not validation of an edge.

- Original ten-trade control: **+2.4296R / $+121.48**, PF 1.51, max drawdown 2.17R.
- Selected reusable policy: `A3_FRESH_AND_CLEAR::E0::R0`.
- Optimized exposed replay: **+5.6978R / $+284.89**, 4 trades, 75.00% win rate, PF 7.43, max drawdown 0.89R.
- Improvement over the unchanged control: **+3.2682R**.

## Same-ten decisions

| Date | Side | Event | Decision | Reason / management | Baseline R | Selected R |
|---|---|---|---|---|---:|---:|
| 2022-01-10 | LONG | CONTINUATION_REFRESH | NO_TRADE | SAME_DIRECTION_CONTINUATION_REFRESH | -0.9552 | +0.0000 |
| 2022-01-03 | LONG | INITIAL_CONTROL | NO_TRADE | LOCAL_M15_LIQUIDITY_ROOM_BELOW_1R | -1.1693 | +0.0000 |
| 2022-01-12 | LONG | REVERSAL_TRANSFER | ADMIT | original structural lifecycle | +1.5900 | +1.5900 |
| 2022-01-31 | LONG | CONTROL_REASSERTION | ADMIT | original structural lifecycle | +2.5330 | +2.5330 |
| 2022-02-02 | LONG | INITIAL_CONTROL | NO_TRADE | LOCAL_M15_LIQUIDITY_ROOM_BELOW_1R | -0.8124 | +0.0000 |
| 2022-05-30 | SHORT | INITIAL_CONTROL | NO_TRADE | LOCAL_M15_LIQUIDITY_ROOM_BELOW_1R | +0.5840 | +0.0000 |
| 2022-01-17 | SHORT | CONTINUATION_REFRESH | NO_TRADE | SAME_DIRECTION_CONTINUATION_REFRESH; LOCAL_M15_LIQUIDITY_ROOM_BELOW_1R | -0.8649 | +0.0000 |
| 2022-01-21 | SHORT | INITIAL_CONTROL | ADMIT | original structural lifecycle | -0.8857 | -0.8857 |
| 2022-01-11 | SHORT | CONTROL_REASSERTION | NO_TRADE | LOCAL_M15_LIQUIDITY_ROOM_BELOW_1R | -0.0504 | +0.0000 |
| 2022-01-14 | SHORT | INITIAL_CONTROL | ADMIT | original structural lifecycle | +2.4605 | +2.4605 |

Valid original winners rejected: **1** (2022-05-30)

## Complete frozen candidate matrix

| Candidate | Trades | Net R | PF | Max DD | Eligible | Failed gates |
|---|---:|---:|---:|---:|:---:|---|
| `A0_ORIGINAL::E0::R0` | 10 | +2.4296 | 1.51 | 2.17 | NO | NONPOSITIVE_LEAVE_ONE_TRADE_OUT_NET |
| `A0_ORIGINAL::E0::R25` | 10 | +2.2088 | 1.47 | 2.17 | NO | NONPOSITIVE_LEAVE_ONE_TRADE_OUT_NET |
| `A0_ORIGINAL::E0::R33` | 10 | +2.1408 | 1.45 | 2.17 | NO | NONPOSITIVE_LEAVE_ONE_TRADE_OUT_NET |
| `A0_ORIGINAL::E25::R0` | 10 | +2.6465 | 1.62 | 2.12 | YES | - |
| `A0_ORIGINAL::E25::R25` | 10 | +2.4545 | 1.58 | 2.12 | YES | - |
| `A0_ORIGINAL::E25::R33` | 10 | +2.3925 | 1.56 | 2.12 | YES | - |
| `A0_ORIGINAL::E33::R0` | 10 | +2.7232 | 1.66 | 2.12 | YES | - |
| `A0_ORIGINAL::E33::R25` | 10 | +2.5372 | 1.62 | 2.12 | YES | - |
| `A0_ORIGINAL::E33::R33` | 10 | +2.4752 | 1.60 | 2.12 | YES | - |
| `A0_ORIGINAL::E50::R0` | 10 | +2.9398 | 1.77 | 2.12 | YES | - |
| `A0_ORIGINAL::E50::R25` | 10 | +2.7826 | 1.73 | 2.12 | YES | - |
| `A0_ORIGINAL::E50::R33` | 10 | +2.7206 | 1.71 | 2.12 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E0::R0` | 8 | +4.2497 | 2.46 | 1.22 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E0::R25` | 8 | +4.0289 | 2.38 | 1.22 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E0::R33` | 8 | +3.9609 | 2.36 | 1.22 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E25::R0` | 8 | +4.4665 | 2.84 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E25::R25` | 8 | +4.2745 | 2.76 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E25::R33` | 8 | +4.2125 | 2.73 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E33::R0` | 8 | +4.5432 | 2.97 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E33::R25` | 8 | +4.3572 | 2.89 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E33::R33` | 8 | +4.2952 | 2.86 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E50::R0` | 8 | +4.7598 | 3.39 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E50::R25` | 8 | +4.6026 | 3.31 | 1.17 | YES | - |
| `A1_FRESH_TRANSFER_OR_CONTROL::E50::R33` | 8 | +4.5406 | 3.28 | 1.17 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E0::R0` | 5 | +4.7426 | 3.58 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E0::R25` | 5 | +4.5218 | 3.46 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E0::R33` | 5 | +4.4538 | 3.42 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E25::R0` | 5 | +4.7303 | 4.37 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E25::R25` | 5 | +4.5383 | 4.24 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E25::R33` | 5 | +4.4763 | 4.19 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E33::R0` | 5 | +4.7306 | 4.70 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E33::R25` | 5 | +4.5446 | 4.56 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E33::R33` | 5 | +4.4826 | 4.51 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E50::R0` | 5 | +4.7180 | 5.89 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E50::R25` | 5 | +4.5608 | 5.73 | 0.96 | YES | - |
| `A2_CLEAR_LOCAL_PATH::E50::R33` | 5 | +4.4988 | 5.67 | 0.96 | YES | - |
| `A3_FRESH_AND_CLEAR::E0::R0` | 4 | +5.6978 | 7.43 | 0.89 | YES | - |
| `A3_FRESH_AND_CLEAR::E0::R25` | 4 | +5.4770 | 7.18 | 0.89 | YES | - |
| `A3_FRESH_AND_CLEAR::E0::R33` | 4 | +5.4090 | 7.11 | 0.89 | YES | - |
| `A3_FRESH_AND_CLEAR::E25::R0` | 4 | +5.6855 | 13.71 | 0.45 | YES | - |
| `A3_FRESH_AND_CLEAR::E25::R25` | 4 | +5.4935 | 13.28 | 0.45 | YES | - |
| `A3_FRESH_AND_CLEAR::E25::R33` | 4 | +5.4315 | 13.15 | 0.45 | YES | - |
| `A3_FRESH_AND_CLEAR::E33::R0` | 4 | +5.6858 | 18.66 | 0.32 | YES | - |
| `A3_FRESH_AND_CLEAR::E33::R25` | 4 | +5.4998 | 18.08 | 0.32 | YES | - |
| `A3_FRESH_AND_CLEAR::E33::R33` | 4 | +5.4378 | 17.89 | 0.32 | YES | - |
| `A3_FRESH_AND_CLEAR::E50::R0` | 4 | +5.6732 | 651.49 | 0.01 | YES | - |
| `A3_FRESH_AND_CLEAR::E50::R25` | 4 | +5.5160 | 633.46 | 0.01 | YES | - |
| `A3_FRESH_AND_CLEAR::E50::R33` | 4 | +5.4540 | 626.35 | 0.01 | YES | - |

## Integrity and next-data gate

- Exactly ten previously exposed cases were reopened; no additional case or market period was accessed.
- The plans were reconstructed from the sealed point-in-time event and liquidity inputs rather than copied into the result.
- Baseline executions reproduced the prior sealed outcomes exactly.
- Primary and reference plans, executions, candidate matrix, selection, and checksums matched exactly.
- No 2025 or 2026 data was opened and no acquisition or charge occurred.
- The selected result has zero validation credit. A later period remains prohibited until separately authorized.
