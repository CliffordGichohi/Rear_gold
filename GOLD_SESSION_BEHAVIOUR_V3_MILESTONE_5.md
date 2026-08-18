# Gold Session Behaviour V3 — Milestone 5

## Status

V3 Milestone 5 is complete under Amendment A.

**Process verdict:** `PASS_V3_MILESTONE_5_INDEPENDENT_VALIDATION_MANDATORY_STOP`

This verdict means that the four authorized post-hoc families were defined
and sealed before chronology-aware calculation, the unchanged protocol was
run against the sealed development matrix, all results and failures were
retained, and an independent exact reproduction passed. It is not a
forward-validation or trading-edge verdict.

The empirical shortlist is:

- London: `LONDON_VOLATILITY_DIRECTION_V0_1`
- New York: `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1`

Both carry the mandatory label
`INTERNALLY_STABLE_POST_HOC_NO_FORWARD_VALIDATION_CREDIT`.

The other two authorized families were rejected:

- `LONDON_ASIA_DIRECTION_REVERSAL_V0_1`
- `NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1`

Milestone 4's zero-candidate verdict remains unchanged. Amendment A did not
retroactively promote any M4 relationship or give it validation credit.

## Scope and partition controls

Only the sealed 2021-08-01 through 2024-12-31 development case matrix was
used:

- London cases: 833
- New York cases: 826
- total cases: 1,659
- case artifact SHA-256:
  `d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9`

The following remained outside the calculation:

- 2025 values and outcomes: not inspected
- 2026 values and outcomes: not inspected
- execution variants, trades, returns, PnL, and R multiples: not calculated
- COT as a pass gate: not used
- rejected ZN rules: not reopened
- extra, repaired, inverted, or retuned candidates: none

## Pre-result freeze

Amendment A and the executable protocol were sealed before chronological
results were calculated.

- readable amendment: `GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_A.md`
- frozen pre-result manifest:
  `research_manifests/gold_session_behaviour_v3_m5_amendment_a_v01.json`
- embedded pre-result manifest hash:
  `adbeed7d029fab23ec72c3866f58bc041d48fe9f8607f65508246f6240917dab`
- candidate-registry fingerprint:
  `8be5f55d427958e68a70350f59357522ef802fa802e3e456455120f7383cc45f`
- authorized candidate families: exactly four
- London families: two
- New York families: two
- maximum internally stable shortlist per session: two

The freeze fixed each condition and complement, support floors, effect
thresholds, calendar blocks, rolling-window construction, stability gates,
Holm-Bonferroni procedure, ranking order, rejection rules, and interpretation
boundary. The freeze step did not deserialize case chronology or outcomes.

## Frozen method

The outcome remained the neutral `SESSION_CLOSE` direction:

- UP: signed displacement greater than +$0.01/oz
- DOWN: signed displacement less than -$0.01/oz
- FLAT: absolute displacement at or below $0.01/oz

Flat cases remained in descriptive path summaries but were excluded from
the binary UP/DOWN contingency test. The primary effect was the condition
UP rate minus its frozen complement UP rate.

The full-period screen required support and source-lineage floors, a positive
Newcombe-Wilson 95% interval, positive condition median, the applicable
negative complement median, and an effect of at least:

- +7.5 percentage points for each complementary-state family
- +10.0 percentage points for the SOFR/2-year interaction

Two-sided Fisher p-values for the fixed family of four were adjusted together
using Holm-Bonferroni at alpha 0.10. No unsupported hypothesis could be
removed from the family.

Calendar stability used 2021-08-01 through 2021-12-31, then calendar 2022,
2023, and 2024. Rolling stability used 126-session-row windows stepped by 63
rows, with a terminal window appended. Overlapping rolling windows are
diagnostics, not independent observations or sources of p-values.

## Full-development results

The support columns below count non-flat binary outcomes. The Holm-adjusted
p-value is identical because all four raw p-values fell within the same
step-down bound.

| Session | Candidate | Condition / complement | Condition n | Complement n | Condition UP | Complement UP | Effect | 95% effect interval | Raw p | Holm p | Result |
|---|---|---|---:|---:|---:|---:|---:|---:|---:|---:|---|
| London | `LONDON_ASIA_DIRECTION_REVERSAL_V0_1` | Asia DOWN / Asia UP | 385 | 446 | 54.29% | 46.41% | +7.87 pp | +1.06 to +14.59 pp | 0.02602 | 0.09654 | Rejected |
| London | `LONDON_VOLATILITY_DIRECTION_V0_1` | Volatility FALLING / RISING | 460 | 365 | 53.70% | 45.75% | +7.94 pp | +1.07 to +14.70 pp | 0.02499 | 0.09654 | Internally stable |
| New York | `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1` | Stress FALLING / RISING | 381 | 444 | 53.28% | 45.27% | +8.01 pp | +1.17 to +14.75 pp | 0.02535 | 0.09654 | Internally stable |
| New York | `NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1` | SOFR cut-dominant and 2Y FALLING / all other jointly known states | 142 | 282 | 57.04% | 45.39% | +11.65 pp | +1.57 to +21.36 pp | 0.02414 | 0.09654 | Rejected |

The respective condition/complement median signed close displacements were:

| Candidate | Condition median | Complement median | Joint-known coverage |
|---|---:|---:|---:|
| `LONDON_ASIA_DIRECTION_REVERSAL_V0_1` | +$0.535 | -$0.330 | 100.00% |
| `LONDON_VOLATILITY_DIRECTION_V0_1` | +$0.500 | -$0.415 | 100.00% |
| `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1` | +$0.890 | -$0.770 | 100.00% |
| `NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1` | +$2.225 | -$0.990 | 51.45% |

All four passed the frozen full-period effect, interval, multiplicity, median,
and applicable support gates. That was necessary but not sufficient:
chronological stability gates decided the final shortlist.

## Calendar stability

Effects are condition UP rate minus complement UP rate. `N/E` means the
block was not eligible under the frozen support rules.

| Candidate | 2021 partial | 2022 | 2023 | 2024 | Positive / eligible | Median | Minimum |
|---|---:|---:|---:|---:|---:|---:|---:|
| `LONDON_ASIA_DIRECTION_REVERSAL_V0_1` | -8.88 pp | +11.41 pp | +14.37 pp | +4.99 pp | 3 / 4 | +8.20 pp | -8.88 pp |
| `LONDON_VOLATILITY_DIRECTION_V0_1` | +20.06 pp | +5.06 pp | +2.84 pp | +11.48 pp | 4 / 4 | +8.27 pp | +2.84 pp |
| `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1` | +5.64 pp | +5.85 pp | +11.50 pp | +9.11 pp | 4 / 4 | +7.48 pp | +5.64 pp |
| `NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1` | N/E | N/E | +24.71 pp | +5.54 pp | 2 / 2 | +15.13 pp | +5.54 pp |

The London Asia-reversal family failed the catastrophic-reversal rule
because its eligible 2021 partial effect, -8.88 points, was at or below the
negative of its frozen 7.5-point minimum. The SOFR/2-year family had only two
eligible annual blocks versus the required three.

## Rolling stability

| Candidate | Eligible blocks | Positive blocks | Positive share | Median effect | Minimum effect | Latest effect | Rolling gate |
|---|---:|---:|---:|---:|---:|---:|---|
| `LONDON_ASIA_DIRECTION_REVERSAL_V0_1` | 13 | 10 | 76.92% | +9.87 pp | -3.13 pp | -2.43 pp | Fail |
| `LONDON_VOLATILITY_DIRECTION_V0_1` | 13 | 13 | 100.00% | +6.52 pp | +0.24 pp | +7.98 pp | Pass |
| `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1` | 13 | 11 | 84.62% | +9.48 pp | -7.07 pp | +15.48 pp | Pass |
| `NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1` | 6 | 4 | 66.67% | +6.21 pp | -3.61 pp | -2.20 pp | Fail |

Every rolling-block result, including ineligible and negative blocks, is
retained in the sealed result document. The decisive failures were:

- London Asia reversal:
  `ANNUAL_CATASTROPHIC_REVERSAL_PRESENT` and
  `LATEST_ELIGIBLE_ROLLING_EFFECT_NOT_POSITIVE`
- New York SOFR cut/2Y falling:
  `ANNUAL_ELIGIBLE_BLOCKS_BELOW_MINIMUM`,
  `ROLLING_POSITIVE_EFFECT_FRACTION_BELOW_MINIMUM`, and
  `LATEST_ELIGIBLE_ROLLING_EFFECT_NOT_POSITIVE`

No failed family was repaired, narrowed, or re-estimated.

## Frozen shortlist

### London

`LONDON_VOLATILITY_DIRECTION_V0_1` is frozen at internal rank 1.

Within this development matrix, London closed UP more often when the frozen
volatility-change field was FALLING than when it was RISING. The difference
was positive in every eligible annual and rolling block. This is an
association in a post-hoc development screen; it does not establish
causality, profitability, an entry method, or forward persistence.

### New York

`NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1` is frozen at internal rank 1.

Within this development matrix, New York closed UP more often when the
frozen financial-stress-change field was FALLING than when it was RISING.
All four annual effects were positive and 11 of 13 rolling effects were
positive. This remains a post-hoc association with no forward-validation or
execution claim.

## Integrity and reproducibility

- stability result:
  `research_artifacts/gold_session_behaviour_v3_m5_stability_v01/stability_results.json`
- stability result hash:
  `e399534950756933905d2cbfb69bc03e69c5fba60910830b879da08db138f508`
- stability result file SHA-256:
  `f1bcf4c8f84e2aa44e7a6bb77e30bda36e478bd8d89b4f12761cbfe5422a5743`
- result-manifest embedded hash:
  `3fc550f8c18279742b82c3176246e862f571cbbc759966ac9bf441d7e3c38fdb`
- build semantic-validation hash:
  `f79bfa1897beba0804c66624cf6b7b7348e6f529f5d128ae7d5682b684cd40dd`
- independent validation:
  `research_artifacts/gold_session_behaviour_v3_m5_validation_v01.json`
- independent validation hash:
  `9b6f9da28c67cf13f90f13e062f6d1106059777d0baa89d64dd590184f191c11`
- independent checks: 18 passed, 0 failed
- exact full-result reproduction: passed

## Honest conclusion

Milestone 5 found internal chronological stability for one authorized
post-hoc family in each session. It also showed why full-period significance
alone was not enough: the London Asia-reversal family and the New York
SOFR/2-year family both looked positive in aggregate but failed frozen
chronology gates.

The two survivors are now immutable candidates for a separately authorized
next stage. They are not yet proven directional edges, and this milestone
does not answer how to enter, exit, size risk, or make money from them.

Milestone 6 is not authorized. This milestone stops here after documentation,
independent reproduction, and state sealing.
