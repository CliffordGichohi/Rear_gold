# GC Microstructure Step 5D-R1 Report

Formal status: `PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION`

This was a metadata-only coverage diagnostic. No OHLC, displacement, direction, return, outcome, 2025/2026 value, signal, trade, or PnL field was accessed.

## Verdict

- Independent reproduction: `PASS`
- Existing sealed source can currently construct all 374 non-holiday outcomes: `FALSE`
- Constructible now: `359 / 374`
- Classification counts: `{"RECOVERABLE_EXISTING_SEALED_SOURCE": 1, "RECOVERABLE_TARGETED_MT5_REFRESH": 2, "UNRESOLVED": 13}`
- Step 5D remains `FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE`; no Stage-1 or Stage-2 test was run.

## Missing-key audit

| Date | Session | 1m valid / 239 | Missing | Ineligible | V3 builder exclusion | Classification |
|---|---:|---:|---:|---:|---|---|
| 2021-12-13 | LONDON | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2021-12-13 | NEW_YORK | 237 | 2 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2021-12-15 | LONDON | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2021-12-15 | NEW_YORK | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2022-07-12 | LONDON | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2022-07-12 | NEW_YORK | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2022-10-11 | LONDON | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2022-10-11 | NEW_YORK | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2023-03-15 | NEW_YORK | 230 | 9 | 0 | NEW_YORK(1 missing) | RECOVERABLE_TARGETED_MT5_REFRESH |
| 2023-08-15 | LONDON | 196 | 43 | 0 | LONDON(7 missing) | RECOVERABLE_TARGETED_MT5_REFRESH |
| 2023-08-15 | NEW_YORK | 239 | 0 | 0 | LONDON(7 missing) | RECOVERABLE_EXISTING_SEALED_SOURCE |
| 2023-09-11 | LONDON | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2023-09-11 | NEW_YORK | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2023-09-13 | NEW_YORK | 236 | 3 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2024-05-13 | LONDON | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |
| 2024-05-13 | NEW_YORK | 239 | 0 | 0 | CONTRADICTION_PREDICTED_EMISSION_MISMATCH | UNRESOLVED |

## Bounded recommendation

`SEPARATE_SOURCE_RESOLUTION_PROTOCOL` — Do not restart research until a separately authorized source-resolution protocol resolves the affected keys.

The recommendation was not implemented. All prior artifacts and verdicts remain unchanged.
