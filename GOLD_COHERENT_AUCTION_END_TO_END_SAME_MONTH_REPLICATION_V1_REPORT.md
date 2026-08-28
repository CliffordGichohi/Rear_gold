# Gold Coherent-Auction End-to-End Same-Month Replication V1

Verdict: `PASS_EXPOSED_END_TO_END_REPLICATION_ZERO_VALIDATION_CREDIT`

## Direct result

The raw-stream-only autonomous process reproduced the exposed human-input V2 result:

- autonomous: `+10.69354658R` / `$+534.68`;
- human-input V2: `+10.68184658R` / `$+534.09`;
- drift: `+0.01170000R` / `$+0.59`;
- signals/no-signals: `16` / `14`;
- admitted/rejected: `11` / `5`;
- win rate: `72.73%`;
- profit factor: `11.8253`;
- maximum drawdown: `0.9878R`.

| Gate | Result |
|---|---|
| prepath_semantic_pass | PASS |
| prepath_geometry_pass | PASS |
| sixteen_signal_minutes_exact | PASS |
| fourteen_no_trade_days_exact | PASS |
| eleven_admit_five_reject_exact | PASS |
| thesis_families_exact | PASS |
| stop_levels_within_0p01 | PASS |
| target_levels_within_0p01 | PASS |
| pnl_within_1R | PASS |
| primary_reference_exact | PASS |
| two_complete_rerun_hashes_exact | PASS |
| fresh_years_locked | PASS |

## Every exposed case

| Case | Human | Autonomous signal | Decision | Family | Autonomous R | Human V2 R |
|---|---|---|---|---|---:|---:|
| CBR-2022-001 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-002 | LONG | 2022-01-04T15:35:00Z | ADMIT | CONTINUATION_WITH_ROOM | +1.7521 | +1.7485 |
| CBR-2022-003 | LONG | 2022-01-06T14:30:00Z | NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE | CONTINUATION_WITH_ROOM | +0.0000 | +0.0000 |
| CBR-2022-004 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-005 | LONG | 2022-01-11T14:01:00Z | ADMIT | RANGE_ROTATION | -0.9878 | -0.9802 |
| CBR-2022-006 | LONG | 2022-01-12T14:55:00Z | ADMIT | CONTINUATION_WITH_ROOM | +0.9687 | +0.9663 |
| CBR-2022-007 | LONG | 2022-01-13T14:50:00Z | EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION | CONTINUATION_WITH_ROOM | +0.0000 | +0.0000 |
| CBR-2022-008 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-009 | LONG | 2022-01-17T15:25:00Z | HTF_PREMIUM_RANGE_ROTATION_CONFLICT | RANGE_ROTATION | +0.0000 | +0.0000 |
| CBR-2022-010 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-011 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-012 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-013 | LONG | 2022-01-21T14:50:00Z | ADMIT | CONTINUATION_WITH_ROOM | -0.0000 | +0.0000 |
| CBR-2022-014 | LONG | 2022-01-24T15:00:00Z | ADMIT | CONTINUATION_WITH_ROOM | -0.0000 | +0.0000 |
| CBR-2022-015 | LONG | 2022-01-25T14:05:00Z | ADMIT | CONTINUATION_WITH_ROOM | +1.5794 | +1.5794 |
| CBR-2022-016 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-017 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-018 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-019 | LONG | 2022-02-01T15:50:00Z | SEVERE_OPPOSING_HTF_IMPULSE | STRUCTURAL_REPAIR | +0.0000 | +0.0000 |
| CBR-2022-020 | LONG | 2022-02-02T14:00:00Z | ADMIT | STRUCTURAL_REPAIR | +0.3790 | +0.3700 |
| CBR-2022-021 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-022 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-023 | LONG | 2022-02-07T10:30:00Z | ADMIT | CONTINUATION_WITH_ROOM | +0.8125 | +0.8120 |
| CBR-2022-024 | LONG | 2022-02-08T14:00:00Z | ADMIT | CONTINUATION_WITH_ROOM | +2.2782 | +2.2694 |
| CBR-2022-025 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-026 | LONG | 2022-02-10T14:05:00Z | UNRESOLVED_TIER1_EVENT_AUCTION | CONTINUATION_WITH_ROOM | +0.0000 | +0.0000 |
| CBR-2022-027 | LONG | 2022-02-11T13:45:00Z | ADMIT | CONTINUATION_WITH_ROOM | +2.2250 | +2.2330 |
| CBR-2022-028 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-029 | NO_TRADE | NONE | NO_SIGNAL | NONE | +0.0000 | +0.0000 |
| CBR-2022-030 | LONG | 2022-02-16T13:45:00Z | ADMIT | CONTINUATION_WITH_ROOM | +1.6866 | +1.6836 |

## What this proves—and what it does not

This passes the requested translation check: when the frozen translator is
given the same exposed raw streams, it autonomously reconstructs the same
sixteen setup minutes, stop/target geometry, V2 selection and approximately
the same +10.68R result without reading human decisions during inference.

It remains in-sample. The semantic tree has 59 nodes and depth 27, was fitted
to these thirty exposed days, and supports LONG only. Consequently this is
evidence that the policy can be encoded, not evidence that it predicts unseen
days. No fresh block, 2025 or 2026 value was opened.
