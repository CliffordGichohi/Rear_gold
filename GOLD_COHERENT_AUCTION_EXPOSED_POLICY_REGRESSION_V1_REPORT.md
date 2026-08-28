# Gold Coherent-Auction Exposed-Policy Regression V1 — Report

## Verdict

The software and calculation regression passed, but the newly frozen protection-plus-runner challenger failed on the exposed calibration sample.

The corrected fixed-H1 control reproduced its prior result exactly in R:

| Policy | Trades | Wins | Win rate | Net R | Expectancy | Profit factor | Max drawdown |
|---|---:|---:|---:|---:|---:|---:|---:|
| Corrected M15 stop + fixed H1 target | 15 | 8 | 53.33% | **+1.7932R** | **+0.1195R** | **1.2436** | 4.0375R |
| Frozen +1R protection + 80/20 runner | 15 | 8 | 53.33% | **-0.8654R** | **-0.0577R** | **0.8350** | 2.0920R |

The challenger lost `2.6586R` relative to the control. This is zero-credit exposed calibration, not validation, but it is sufficient to reject spending the fresh 50-case block on that challenger unchanged.

## Did the frozen rules catch the identified corrections?

Only partially.

### Correct-direction round trips

| Case | Control | Track B | Change | Disposition |
|---|---:|---:|---:|---|
| `CBR-2022-005` | -1.0372R | -0.6006R | +0.4366R | Loss reduced, not converted |
| `CBR-2022-014` | -1.0195R | -0.3318R | +0.6877R | Loss reduced, not converted |
| `CBR-2022-030` | -1.0709R | -1.0709R | 0.0000R | Range-stop semantic error not caught |

The +1R/M5 protection logic helped two cases but did not fully monetize either move. It did nothing for `CBR-2022-030`, whose problem was using the generic protected-M15 stop for an M5 rotation inside an M15 range.

### Large winners

| Case | Control | Track B | Value lost |
|---|---:|---:|---:|
| `CBR-2022-023` | +2.1112R | +0.2782R | -1.8330R |
| `CBR-2022-024` | +2.4773R | +0.5028R | -1.9745R |
| `CBR-2022-027` | +2.2306R | +0.3120R | -1.9186R |

All three remained positive, but the pre-target M5 protection exited them before their H1 destinations. Those three cuts surrendered `5.7261R`, overwhelming the smaller savings elsewhere. The frozen runner itself was rarely the problem: the pre-target protection rule prevented the core from reaching its target.

### Direction-wrong cases

The policy did not automatically reject any of the four known wrong-direction decisions:

- `CBR-2022-007`: -1.0351R
- `CBR-2022-009`: reduced from -1.0837R to -0.0936R
- `CBR-2022-019`: -1.0617R
- `CBR-2022-026`: -1.0530R

The mandatory auction-family, H4-state, location, and macro-override fields would force the operator to record the conflicts, but they are observations rather than deterministic entry filters. The current contract therefore surfaces these warnings but cannot honestly claim to catch them automatically.

## Complete case disposition

- Improved: 6 cases (`002`, `005`, `006`, `009`, `013`, `014`).
- Degraded: 4 cases (`015`, `023`, `024`, `027`).
- Unchanged: 6 cases (`003`, `007`, `019`, `020`, `026`, `030`).
- M5 protection exits: 7.
- Accepted H1 runners: 2.
- Structurally ineligible before entry: 1 (`003`).

The complete case table is `research_artifacts/gold_coherent_auction_exposed_policy_regression_v1/regression_cases.csv`.

## Integrity and reproduction

- Exact population: all 16 exposed human trade decisions retained.
- Fixed-H1 control: all resolutions and eight-decimal R values reproduced exactly.
- Primary and independent event-table implementations: exact case rows, summaries, and payload checksum.
- Reproduction SHA-256: `b2cf8983b2a8e8ce3beec2e32bc5641611ec5aa2c490f247973fe6610f46b759`.
- Two stopped engineering attempts remain recorded. The first was an optional-null output-shape mismatch; the second was a `$0.00000010` maximum serialization-precision mismatch. Neither changed a rule or result.
- Fresh 50-case decisions collected: 0.
- Calendar 2025: locked.
- Calendar 2026: locked.
- Acquisition and charge: none, `$0.00`.

## Formal dispositions

- Mechanical regression: `PASS_EXACT_REPRODUCTION`.
- Corrected fixed-H1 control: `PRESERVE_AS_EXPOSED_CALIBRATION_CANDIDATE`.
- Frozen protection/runner challenger: `REJECT_NEGATIVE_EXPOSED_REGRESSION`.
- Automatic capture of directional conflicts: `NOT_IMPLEMENTED_AND_NOT_CLAIMED`.
- Current dual-track fresh-validation readiness: `PAUSED_PENDING_NARROW_PREVALUE_AMENDMENT`.

## Required next gate

Before collecting a fresh decision, amend the validation policy narrowly:

1. Score the corrected fixed-H1 control as the sole economic management policy; retain Track B only as a sealed rejected calibration artifact.
2. Enforce setup-family-to-stop-basis consistency at submission:
   - continuation with room → active M15 protected swing;
   - range rotation → controlling M15 range boundary;
   - structural repair → post-repair origin;
   - other explicit → written structural construction required.
3. Keep the conflict fields descriptive. Do not manufacture post-hoc automatic filters from the four known losing cases.
4. Re-run browser and lifecycle regression after the amendment, confirm the fresh ledger still contains zero decisions, and only then open the 50 blind cases.

This sequence tests the actual correction without pretending the exposed sample proved a directional filter.

