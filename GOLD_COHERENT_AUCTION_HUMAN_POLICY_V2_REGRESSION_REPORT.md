# Gold Coherent-Auction Human-Policy Reconstruction V2 Regression

Verdict: `PROMISING_EXPOSED_CALIBRATION_NOT_VALIDATED`

## What was corrected

V2 preserves the operator's sealed structural stop and liquidity target, resizes at the actual fill, treats macro and an engaged decision zone as context rather than universal vetoes, and applies only the five frozen conjunctive risk states. The result remains exposed calibration with zero validation credit.

## Economic result

| Track | Trades | Win rate | Net R | Net USD | PF | Max DD |
|---|---:|---:|---:|---:|---:|---:|
| All 16: faithful geometry, no selection | 16 | 50.00% | +5.2243 | $+261.22 | 1.7890 | 4.0778R |
| Selected: faithful fixed geometry | 11 | 72.73% | +8.8935 | $+444.68 | 4.0128 | 1.9717R |
| Selected: + completed-M15 1.25R protection | 11 | 72.73% | +10.8652 | $+543.26 | 12.0844 | 0.9802R |
| Complete V2: + bounded accepted runner | 11 | 72.73% | +10.6818 | $+534.09 | 11.8973 | 0.9802R |
| Complete V2 at 1.5x costs | 11 | 72.73% | +10.5099 | $+525.49 | 11.1719 | 0.9992R |

## Value-retention attribution

- Strict-risk fixed geometry across all 16: `+5.2243R`.
- Contextual selection contribution: `+3.6692R`.
- Completed-M15 protection contribution: `+1.9717R`.
- Bounded runner contribution: `-0.1834R`.
- Complete exposed V2 calibration: `+10.6818R`.

## Selection audit

The policy admitted 11 and rejected 5 cases. It rejected 0 directionally correct cases and admitted 0 directionally wrong cases. That separation is descriptive only: these contextual thresholds were constructed from the same exposed cases, so it is a calibration result, not predictive accuracy.

## Every trade

| Case | Right later | Decision | Family | Reason/warning | Fixed R | Protected R | Complete R | Final resolution |
|---|:---:|---|---|---|---:|---:|---:|---|
| `CBR-2022-002` | YES | ADMIT | CONTINUATION_WITH_ROOM | `NONE` | +1.3778 | +1.3778 | +1.7485 | PROTECTED_STOP |
| `CBR-2022-003` | NO | REJECT | CONTINUATION_WITH_ROOM | `NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE` | +0.0000 | +0.0000 | +0.0000 | NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE |
| `CBR-2022-005` | YES | ADMIT | RANGE_ROTATION | `MACRO_OPPOSED` | -0.9802 | -0.9802 | -0.9802 | STRUCTURAL_STOP |
| `CBR-2022-006` | YES | ADMIT | CONTINUATION_WITH_ROOM | `NONE` | +1.2078 | +1.2078 | +0.9663 | PROTECTED_STOP |
| `CBR-2022-007` | NO | REJECT | CONTINUATION_WITH_ROOM | `EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION` | +0.0000 | +0.0000 | +0.0000 | EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION |
| `CBR-2022-009` | NO | REJECT | RANGE_ROTATION | `HTF_PREMIUM_RANGE_ROTATION_CONFLICT` | +0.0000 | +0.0000 | +0.0000 | HTF_PREMIUM_RANGE_ROTATION_CONFLICT |
| `CBR-2022-013` | YES | ADMIT | CONTINUATION_WITH_ROOM | `MACRO_OPPOSED` | -0.9892 | +0.0000 | +0.0000 | PROTECTED_STOP |
| `CBR-2022-014` | YES | ADMIT | CONTINUATION_WITH_ROOM | `HIGH_HTF_LOCATION_WITHOUT_EXTENSION_CONJUNCTION` | -0.9825 | +0.0000 | +0.0000 | PROTECTED_STOP |
| `CBR-2022-015` | YES | ADMIT | CONTINUATION_WITH_ROOM | `NONE` | +1.8928 | +1.8928 | +1.5794 | RUNNER_NO_TARGET_ACCEPTANCE |
| `CBR-2022-019` | NO | REJECT | STRUCTURAL_REPAIR | `SEVERE_OPPOSING_HTF_IMPULSE` | +0.0000 | +0.0000 | +0.0000 | SEVERE_OPPOSING_HTF_IMPULSE |
| `CBR-2022-020` | YES | ADMIT | STRUCTURAL_REPAIR | `BOUNDED_STRUCTURAL_REPAIR_ONLY` | +0.3700 | +0.3700 | +0.3700 | UTC_DAY_TIME_EXIT |
| `CBR-2022-023` | YES | ADMIT | CONTINUATION_WITH_ROOM | `HIGH_HTF_LOCATION_WITHOUT_EXTENSION_CONJUNCTION` | +0.8120 | +0.8120 | +0.8120 | UTC_DAY_TIME_EXIT |
| `CBR-2022-024` | YES | ADMIT | CONTINUATION_WITH_ROOM | `HIGH_HTF_LOCATION_WITHOUT_EXTENSION_CONJUNCTION, MACRO_OPPOSED` | +2.2708 | +2.2708 | +2.2694 | RUNNER_NO_TARGET_ACCEPTANCE |
| `CBR-2022-026` | NO | REJECT | CONTINUATION_WITH_ROOM | `UNRESOLVED_TIER1_EVENT_AUCTION` | +0.0000 | +0.0000 | +0.0000 | UNRESOLVED_TIER1_EVENT_AUCTION |
| `CBR-2022-027` | YES | ADMIT | CONTINUATION_WITH_ROOM | `MACRO_OPPOSED` | +2.2306 | +2.2306 | +2.2330 | RUNNER_NO_TARGET_ACCEPTANCE |
| `CBR-2022-030` | YES | ADMIT | CONTINUATION_WITH_ROOM | `NONE` | +1.6836 | +1.6836 | +1.6836 | UTC_DAY_TIME_EXIT |

## Protection sensitivity (mandatory, not hidden)

| Completed-M15 close threshold | Net R | PF | Max DD |
|---|---:|---:|---:|
| 1.00R | +8.6346 | 9.8088 | 0.9802R |
| 1.50R | +9.8827 | 6.0351 | 0.9825R |
| 2.00R | +9.8827 | 6.0351 | 0.9825R |

## Honest interpretation

This V2 regression answers the narrow correction question: a faithful translation can monetize substantially more of the already-observed sample than the V1 zero-trade rulebook. It does not establish a durable edge because selection and the 1.25R protection threshold were calibrated on these same exposed trades. The complete policy is now frozen; changing it again before fresh evaluation would invalidate the next test.

The unopened 50-case block, 2025 and 2026 remain locked. No paid data was acquired.
