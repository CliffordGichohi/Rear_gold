# Gold Session Behaviour V3 — Milestone 6B

## Verdict

Milestone 6B completed under Amendment B. The process and independent reproduction passed, but **neither frozen candidate validated as a current directional-bias edge**.

- `LONDON_VOLATILITY_DIRECTION_V0_1`: `INCONCLUSIVE_NO_LOCKED_2026_PASS`
- `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1`: `INCONCLUSIVE_NO_LOCKED_2026_PASS`
- All four candidate/segment evaluations were `INCONCLUSIVE_MIXED_OR_UNDERPOWERED`.
- No support gate failed. The inconclusive verdicts came from weak or unstable effects, confidence intervals spanning zero, non-significant Holm-adjusted tests, and/or the frozen median-direction requirements.
- Calendar 2025 remains exposed historical evidence and receives no independent-validation credit.

## Source refresh and pre-open controls

- IC Markets MT5 XAUUSD: 3,756 real one-minute bars acquired for the missing interval through 29 July 2026.
- Free FRED public endpoint: only `US_VOLATILITY_INDEX` and `US_FINANCIAL_STRESS` refreshed; 24 records fetched and four new observations inserted.
- Paid acquisition: none.
- Final metadata readiness: `READY_WITH_LOW_POWER_EXPECTED_AND_RECORDED_COVERAGE_GAPS`.
- Terminal 27–29 July 2026 coverage gaps were cleared. Final complete-case counts were 257/257 for 2025 and 143 London / 142 New York for 2026 YTD.
- Final source snapshot hash: `855bf26184a471be0833dcca50b8af39d3e021e5323c7ff15a1d2577c6389df0`.
- Candidate definitions, thresholds, multiplicity, missing-data policy, and segment order were sealed before any candidate state or outcome was calculated.

## Frozen numerical results

Condition is `FALLING`; complement is `RISING`. UP rates use non-flat neutral session-close outcomes from 08:01 to 12:00 local time.

| Segment | Candidate | Condition n | Complement n | Condition UP | Complement UP | Effect | Newcombe 95% CI | Holm p | Condition median $ | Complement median $ | Verdict |
| --- | --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| EXPOSED_CALENDAR_2025 | LONDON_VOLATILITY_DIRECTION_V0_1 | 144 | 113 | 59.03% | 56.64% | +2.39 pp | [-9.59, +14.39] | 1.0000 | +2.63 | +2.18 | INCONCLUSIVE_MIXED_OR_UNDERPOWERED |
| EXPOSED_CALENDAR_2025 | NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1 | 120 | 137 | 53.33% | 54.01% | -0.68 pp | [-12.72, +11.36] | 1.0000 | +1.14 | +1.24 | INCONCLUSIVE_MIXED_OR_UNDERPOWERED |
| LOCKED_2026_YTD | LONDON_VOLATILITY_DIRECTION_V0_1 | 76 | 66 | 42.11% | 51.52% | -9.41 pp | [-25.06, +6.87] | 0.6247 | -3.09 | +1.76 | INCONCLUSIVE_MIXED_OR_UNDERPOWERED |
| LOCKED_2026_YTD | NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1 | 63 | 79 | 52.38% | 53.16% | -0.78 pp | [-16.88, +15.30] | 1.0000 | +2.77 | +1.84 | INCONCLUSIVE_MIXED_OR_UNDERPOWERED |

## What the numbers mean

For London in 2025, falling VIX was only 2.39 percentage points more bullish than rising VIX, and both condition medians were positive. That is not the frozen directional separation.

For London in locked 2026 YTD, the point estimate reversed to -9.41 percentage points and the medians also reversed (-$3.09 versus +$1.76). This is adverse evidence, but it did not satisfy the strict rejection gate because the 95% interval still crossed zero and Holm-adjusted p was 0.6247. It is therefore honestly inconclusive—not a pass and not a protocol-level rejection.

The New York financial-stress candidate was nearly flat in both periods (-0.68 pp in 2025 and -0.78 pp in 2026 YTD), with broad intervals around zero. It did not replicate the development relationship.

## Support and integrity

- Joint-known feature coverage: 100% for every candidate/segment.
- Duplicate source records or case keys: zero.
- All condition/complement sample, combined sample, source-signature, and episode floors passed.
- Both candidates were evaluated in both segments regardless of earlier results.
- Independent reproduction used the sealed forward cases and did not reopen the database.
- Final reproduction: 32/32 checks passed; hash `1558154e81e353d77679f6a55d1fabddc2eaba1a574109ce5624826a9bd47eda`.

The first sealed validation program halted on a result-field mapping error before producing an artifact. A preserved V02 attempt then exposed binary-float signature comparison in the validator only. V03 corrected validation arithmetic to decimal representation; it changed no case, statistic, or verdict.

## Prospective ledger

The append-only ledger was initialized empty before the next eligible session:

- Start: 31 July 2026
- End: 31 December 2026
- Existing decisions: 0
- Backfilled decisions: 0
- Interim inferential testing: prohibited

Neither candidate is currently an edge candidate because the frozen protocol requires a locked-2026 PASS plus a prospective PASS, and neither received the locked-2026 PASS.

## Research boundary

No variable was added, no threshold was retuned, no candidate was repaired or filtered, COT was not used as a pass gate, no rejected ZN rule was reopened, and no execution, trade, PnL, R-multiple, or account-return calculation was performed.

Milestone 6B is complete. Mandatory stop applies.
