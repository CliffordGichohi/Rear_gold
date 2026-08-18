# Gold Session Behaviour V3 — Milestone 3

## Verdict

**`PASS_V3_MILESTONE_3_INDEPENDENT_VALIDATION_MANDATORY_STOP`**

V3 Milestone 3 is complete. The descriptive development behaviour atlas is
sealed. Independent read-back validation passed **17 / 17** checks after
re-reading and re-hashing all **1,659** source cases and reproducing the full
atlas document.

This verdict means that the atlas was built reproducibly within the contract.
It is not a claim that a directional edge, candidate, or executable strategy
has passed.

Milestone 4 is not authorized and was not started. No 2025 or 2026 value or
outcome was opened.

## Scope and measurement boundary

The atlas uses only the sealed development matrix:

- interval: **1 August 2021 through 31 December 2024**;
- London cases: **833**;
- New York cases: **826**;
- total cases: **1,659**; and
- neutral coordinate: the open of the complete **08:01 local** one-minute
  bar, not an entry or assumed fill.

London and New York are reported as separate research units. There is no
combined session result, cross-session ranking, or transfer claim.

All price displacements and ranges below are **USD per troy ounce**. Direction
is `UP` above +$0.01, `DOWN` below -$0.01, and `FLAT` within ±$0.01. Each
session path ends at 12:00 local. Percentiles use the frozen Hyndman–Fan type 7
method.

The atlas contains no:

- causal attribution;
- macro, positioning, event, structure, cross-market, or signal conditioning;
- correlation, regression, hypothesis test, or predictive metric;
- candidate creation, ranking, or shortlisting;
- entry, exit, stop, target, trade, P&L, R multiple, MFE, or MAE; or
- execution optimization.

## London behaviour atlas

### Direction frequencies

| Horizon | Up | Down | Flat |
|---|---:|---:|---:|
| 5 minutes | 390 (46.82%) | 417 (50.06%) | 26 (3.12%) |
| 15 minutes | 407 (48.86%) | 417 (50.06%) | 9 (1.08%) |
| 30 minutes | 397 (47.66%) | 425 (51.02%) | 11 (1.32%) |
| 60 minutes | 389 (46.70%) | 439 (52.70%) | 5 (0.60%) |
| Session close | 416 (49.94%) | 415 (49.82%) | 2 (0.24%) |

The unconditional London close split is nearly even in this development
sample. The 60-minute split is recorded as a path description only; it has not
been conditioned, significance-tested, or converted into a candidate.

### Selected points from the sealed 48-point path curve

The offset is the source five-minute bar's opening offset. Its close becomes
available five minutes later.

| Offset | Mean displacement | Median | P25 | P75 | Up | Down |
|---|---:|---:|---:|---:|---:|---:|
| 0m | -0.0124 | 0.00 | -0.30 | 0.30 | 48.62% | 47.90% |
| 25m | -0.0231 | -0.01 | -0.82 | 0.72 | 49.10% | 49.82% |
| 55m | 0.0358 | -0.12 | -1.14 | 1.14 | 46.46% | 52.70% |
| 115m | 0.0566 | 0.20 | -1.95 | 2.01 | 51.98% | 47.66% |
| 175m | 0.0123 | -0.10 | -2.73 | 2.66 | 49.34% | 50.30% |
| 235m | 0.0558 | 0.01 | -3.35 | 3.32 | 49.94% | 49.82% |

All 48 offsets, including counts, standard deviations, extrema, seven
percentiles, and three direction states, are retained in the sealed atlas.

### Excursions and close

| Neutral path measurement | Mean | P25 | Median | P75 | P90 | P95 |
|---|---:|---:|---:|---:|---:|---:|
| Signed close displacement | 0.0558 | -3.35 | 0.01 | 3.32 | 6.644 | 10.132 |
| Absolute close displacement | 4.3631 | 1.64 | 3.35 | 6.03 | 9.38 | 12.234 |
| Maximum upward displacement | 4.4943 | 1.64 | 3.49 | 6.21 | 9.618 | 12.43 |
| Maximum downward magnitude | 4.5424 | 1.67 | 3.49 | 6.14 | 9.442 | 12.576 |
| Session range | 9.0367 | 6.09 | 7.98 | 10.83 | 14.516 | 16.728 |
| Close-location fraction | 0.5050 | 0.2420 | 0.5095 | 0.7726 | 0.9031 | 0.9474 |
| Path efficiency | 0.4452 | 0.2394 | 0.4469 | 0.6585 | 0.7999 | 0.8510 |

Observed extrema remain in the artifact: session range **$2.16 to $37.52**,
signed close displacement **-$30.03 to +$21.34**, maximum upward displacement
up to **$34.76**, and maximum downward magnitude up to **$36.37**. These are
distribution endpoints, not expected moves or risk limits.

### Timing

| Extreme order | Count | Percentage |
|---|---:|---:|
| High first | 412 | 49.46% |
| Low first | 421 | 50.54% |
| Same bar | 0 | 0.00% |

| Time from decision | Session high | Session low |
|---|---:|---:|
| Median minute | 145 | 140 |
| Minutes 1–30 | 127 (15.25%) | 146 (17.53%) |
| Minutes 31–60 | 56 (6.72%) | 67 (8.04%) |
| Minutes 61–120 | 170 (20.41%) | 143 (17.17%) |
| Minutes 121–180 | 182 (21.85%) | 174 (20.89%) |
| Minutes 181–239 | 298 (35.77%) | 303 (36.37%) |

The high/low order is nearly even. More than one third of the recorded highs
and lows occurred in the final frozen time bin, but this is not a timing rule
or an execution conclusion.

### Level interactions

Percentages use eligible level instances as their denominator.

| Level type | Eligible | Touched | Accepted | Rejected | Failed break | Retested |
|---|---:|---:|---:|---:|---:|---:|
| Asia high | 833 | 431 (51.74%) | 349 (41.90%) | 82 (9.84%) | 240 (28.81%) | 240 (28.81%) |
| Asia low | 833 | 399 (47.90%) | 321 (38.54%) | 78 (9.36%) | 234 (28.09%) | 234 (28.09%) |
| Prior-day high | 772 | 318 (41.19%) | 307 (39.77%) | 11 (1.42%) | 53 (6.87%) | 53 (6.87%) |
| Prior-day low | 772 | 271 (35.10%) | 261 (33.81%) | 10 (1.30%) | 35 (4.53%) | 35 (4.53%) |
| Prior-week high | 768 | 341 (44.40%) | 337 (43.88%) | 4 (0.52%) | 32 (4.17%) | 32 (4.17%) |
| Prior-week low | 768 | 275 (35.81%) | 271 (35.29%) | 4 (0.52%) | 19 (2.47%) | 19 (2.47%) |

Median first-interaction minutes for touched Asia high and low instances were
**65** and **80**, respectively. For the prior-day and prior-week coordinates,
the median was minute **5** under the frozen interaction definition. Touch and
subsequent-state frequencies do not establish that any level predicts
direction.

### Calendar description

#### By year

The 2021 row is partial from 1 August.

| Year | Cases | Up | Down | Flat | Median close displacement | Median range | High first |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 partial | 92 | 48.91% | 51.09% | 0.00% | -0.06 | 6.23 | 46.74% |
| 2022 | 249 | 48.19% | 51.41% | 0.40% | -0.46 | 7.81 | 50.60% |
| 2023 | 241 | 46.47% | 53.11% | 0.41% | -0.24 | 7.02 | 48.96% |
| 2024 | 251 | 55.38% | 44.62% | 0.00% | 0.92 | 10.44 | 49.80% |

Across these four calendar rows, the recorded up-percentage span is
**46.47%–55.38%**, the down-percentage span is **44.62%–53.11%**, the median
close-displacement span is **-$0.46 to +$0.92**, and the median-range span is
**$6.23–$10.44**. These are descriptive ranges, not a stability gate.

#### By month of year

Months are pooled across the development years; August through December also
contain the partial 2021 segment.

| Month | Cases | Up | Down | Flat | Median close | Median range |
|---|---:|---:|---:|---:|---:|---:|
| Jan | 60 | 55.00% | 45.00% | 0.00% | 0.51 | 7.47 |
| Feb | 59 | 44.07% | 55.93% | 0.00% | -1.07 | 6.85 |
| Mar | 62 | 50.00% | 50.00% | 0.00% | -0.015 | 9.70 |
| Apr | 58 | 55.17% | 44.83% | 0.00% | 1.11 | 9.585 |
| May | 61 | 37.70% | 60.66% | 1.64% | -1.74 | 8.65 |
| Jun | 60 | 50.00% | 50.00% | 0.00% | 0.035 | 7.295 |
| Jul | 64 | 48.44% | 51.56% | 0.00% | -0.35 | 8.105 |
| Aug | 88 | 47.73% | 52.27% | 0.00% | -0.095 | 5.87 |
| Sep | 80 | 46.25% | 53.75% | 0.00% | -0.39 | 7.065 |
| Oct | 80 | 52.50% | 47.50% | 0.00% | 0.45 | 8.785 |
| Nov | 85 | 65.88% | 32.94% | 1.18% | 1.52 | 9.07 |
| Dec | 76 | 43.42% | 56.58% | 0.00% | -0.48 | 8.19 |

#### By weekday

| Weekday | Cases | Up | Down | Flat | Median close | Median range |
|---|---:|---:|---:|---:|---:|---:|
| Monday | 164 | 42.07% | 57.93% | 0.00% | -0.87 | 8.15 |
| Tuesday | 168 | 49.40% | 50.60% | 0.00% | -0.19 | 7.685 |
| Wednesday | 165 | 50.30% | 49.09% | 0.61% | 0.22 | 7.89 |
| Thursday | 169 | 55.62% | 44.38% | 0.00% | 0.85 | 8.05 |
| Friday | 167 | 52.10% | 47.31% | 0.60% | 0.46 | 8.07 |

Month and weekday rows have not been significance-tested, chronology-tested,
or evaluated for multiple comparisons. They are not candidates.

## New York behaviour atlas

### Direction frequencies

| Horizon | Up | Down | Flat |
|---|---:|---:|---:|
| 5 minutes | 423 (51.21%) | 388 (46.97%) | 15 (1.82%) |
| 15 minutes | 433 (52.42%) | 389 (47.09%) | 4 (0.48%) |
| 30 minutes | 416 (50.36%) | 404 (48.91%) | 6 (0.73%) |
| 60 minutes | 449 (54.36%) | 373 (45.16%) | 4 (0.48%) |
| Session close | 404 (48.91%) | 421 (50.97%) | 1 (0.12%) |

The unconditional 60-minute and close rows have different descriptive splits.
No persistence, reversal, predictive, or tradable interpretation is assigned
to that observation in Milestone 3.

### Selected points from the sealed 48-point path curve

| Offset | Mean displacement | Median | P25 | P75 | Up | Down |
|---|---:|---:|---:|---:|---:|---:|
| 0m | 0.0233 | 0.03 | -0.38 | 0.46 | 50.97% | 46.85% |
| 25m | -0.0193 | -0.035 | -1.0675 | 1.1275 | 48.67% | 50.61% |
| 55m | 0.1799 | 0.325 | -1.1925 | 1.7575 | 55.81% | 43.58% |
| 115m | 0.1134 | 0.42 | -1.88 | 2.525 | 53.75% | 45.64% |
| 175m | 0.0919 | 0.205 | -2.80 | 3.7775 | 51.45% | 47.94% |
| 235m | -0.0428 | -0.21 | -4.865 | 5.0975 | 48.91% | 50.97% |

The full 48-point curve is retained in the sealed atlas.

### Excursions and close

| Neutral path measurement | Mean | P25 | Median | P75 | P90 | P95 |
|---|---:|---:|---:|---:|---:|---:|
| Signed close displacement | -0.0428 | -4.865 | -0.21 | 5.0975 | 11.155 | 14.3675 |
| Absolute close displacement | 6.9187 | 2.43 | 4.995 | 9.0975 | 14.75 | 20.01 |
| Maximum upward displacement | 6.7326 | 2.39 | 5.20 | 9.3775 | 14.325 | 17.9075 |
| Maximum downward magnitude | 6.8030 | 2.165 | 4.875 | 9.0375 | 14.19 | 20.00 |
| Session range | 13.5357 | 8.53 | 11.835 | 16.2475 | 21.99 | 26.555 |
| Close-location fraction | 0.4996 | 0.2421 | 0.4918 | 0.7635 | 0.8972 | 0.9493 |
| Path efficiency | 0.4622 | 0.2487 | 0.4635 | 0.6680 | 0.8117 | 0.8726 |

Observed extrema remain in the artifact: session range **$2.65 to $70.42**,
signed close displacement **-$60.51 to +$37.19**, maximum upward displacement
up to **$43.42**, and maximum downward magnitude up to **$68.07**. These are
distribution endpoints, not expected moves or risk limits.

### Timing

| Extreme order | Count | Percentage |
|---|---:|---:|
| High first | 408 | 49.39% |
| Low first | 416 | 50.36% |
| Same bar | 2 | 0.24% |

| Time from decision | Session high | Session low |
|---|---:|---:|
| Median minute | 176 | 167 |
| Minutes 1–30 | 120 (14.53%) | 146 (17.68%) |
| Minutes 31–60 | 64 (7.75%) | 54 (6.54%) |
| Minutes 61–120 | 95 (11.50%) | 93 (11.26%) |
| Minutes 121–180 | 147 (17.80%) | 147 (17.80%) |
| Minutes 181–239 | 400 (48.43%) | 386 (46.73%) |

The high/low order is nearly even. The final frozen time bin contains the
largest share of recorded extreme timestamps, but that description is not an
entry or exit rule.

### Level interactions

| Level type | Eligible | Touched | Accepted | Rejected | Failed break | Retested |
|---|---:|---:|---:|---:|---:|---:|
| Asia high | 826 | 510 (61.74%) | 455 (55.08%) | 55 (6.66%) | 275 (33.29%) | 275 (33.29%) |
| Asia low | 826 | 439 (53.15%) | 369 (44.67%) | 70 (8.47%) | 217 (26.27%) | 217 (26.27%) |
| Other | 1,652 | 981 (59.38%) | 805 (48.73%) | 176 (10.65%) | 564 (34.14%) | 564 (34.14%) |
| Prior-day high | 765 | 348 (45.49%) | 339 (44.31%) | 9 (1.18%) | 78 (10.20%) | 78 (10.20%) |
| Prior-day low | 765 | 287 (37.52%) | 272 (35.56%) | 15 (1.96%) | 48 (6.27%) | 48 (6.27%) |
| Prior-week high | 761 | 345 (45.34%) | 339 (44.55%) | 6 (0.79%) | 46 (6.04%) | 46 (6.04%) |
| Prior-week low | 761 | 278 (36.53%) | 276 (36.27%) | 2 (0.26%) | 27 (3.55%) | 27 (3.55%) |

The M2 case transform mapped the decision-known London-session high and low
coordinates to the schema's `OTHER` level type. Consequently, the New York
`OTHER` row pools those two coordinates and must not be read as a single
specific level. This limitation is retained honestly; Milestone 3 did not
retroactively change the sealed case matrix or frozen atlas transform.

Median first-interaction minutes for touched Asia high and low instances were
**5** and **5**; their 75th percentiles were **128.75** and **147.5** minutes.
The `OTHER` median and 75th percentile were **65** and **155** minutes.

### Calendar description

#### By year

The 2021 row is partial from 1 August.

| Year | Cases | Up | Down | Flat | Median close displacement | Median range | High first |
|---|---:|---:|---:|---:|---:|---:|---:|
| 2021 partial | 92 | 45.65% | 54.35% | 0.00% | -0.625 | 10.305 | 50.00% |
| 2022 | 249 | 49.00% | 51.00% | 0.00% | -0.25 | 11.51 | 50.20% |
| 2023 | 234 | 47.44% | 52.14% | 0.43% | -0.375 | 10.545 | 49.57% |
| 2024 | 251 | 51.39% | 48.61% | 0.00% | 1.05 | 13.95 | 48.21% |

Across these four calendar rows, the recorded up-percentage span is
**45.65%–51.39%**, the down-percentage span is **48.61%–54.35%**, the median
close-displacement span is **-$0.625 to +$1.05**, and the median-range span is
**$10.305–$13.95**. These are descriptive ranges, not a stability gate.

#### By month of year

| Month | Cases | Up | Down | Flat | Median close | Median range |
|---|---:|---:|---:|---:|---:|---:|
| Jan | 60 | 45.00% | 55.00% | 0.00% | -0.87 | 12.56 |
| Feb | 59 | 47.46% | 52.54% | 0.00% | -0.99 | 12.67 |
| Mar | 61 | 59.02% | 40.98% | 0.00% | 2.98 | 14.20 |
| Apr | 57 | 49.12% | 50.88% | 0.00% | -0.25 | 13.02 |
| May | 60 | 43.33% | 56.67% | 0.00% | -0.935 | 12.485 |
| Jun | 60 | 53.33% | 46.67% | 0.00% | 0.865 | 11.23 |
| Jul | 62 | 43.55% | 56.45% | 0.00% | -0.885 | 10.795 |
| Aug | 88 | 48.86% | 51.14% | 0.00% | -0.185 | 9.85 |
| Sep | 79 | 46.84% | 53.16% | 0.00% | -0.86 | 10.29 |
| Oct | 80 | 51.25% | 48.75% | 0.00% | 0.355 | 10.70 |
| Nov | 84 | 47.62% | 51.19% | 1.19% | -0.27 | 13.085 |
| Dec | 76 | 51.32% | 48.68% | 0.00% | 0.84 | 12.455 |

#### By weekday

| Weekday | Cases | Up | Down | Flat | Median close | Median range |
|---|---:|---:|---:|---:|---:|---:|
| Monday | 164 | 44.51% | 55.49% | 0.00% | -0.86 | 10.485 |
| Tuesday | 166 | 44.58% | 55.42% | 0.00% | -0.89 | 10.96 |
| Wednesday | 162 | 58.64% | 41.36% | 0.00% | 1.79 | 11.13 |
| Thursday | 169 | 47.34% | 52.07% | 0.59% | -0.66 | 12.61 |
| Friday | 165 | 49.70% | 50.30% | 0.00% | -0.34 | 12.72 |

Month and weekday rows have not been significance-tested, chronology-tested,
or evaluated for multiple comparisons. They are not candidates.

## Honest Milestone 3 conclusion

The sealed development sample establishes a reproducible unconditional
description of how each session moved:

- both session atlases contain material intraday ranges and two-sided
  excursions;
- unconditional session-close direction is close to evenly divided;
- high-first and low-first ordering is close to evenly divided;
- many session extremes occur late in the four-hour observation window;
- decision-known levels are interacted with at measurable but non-uniform
  rates; and
- direction and range summaries vary across calendar rows.

Those statements describe **what occurred**, not why it occurred. The atlas
does not establish whether any macro, expectations, positioning, catalyst,
session, structure, liquidity, or cross-market condition explains or predicts
the paths. It also does not establish a profitable execution method.

Any calendar percentage that looks visually distinctive is still an
uncontrolled development observation. It has no validation credit and cannot
be called an edge without the separately authorized, preregistered work
required by later milestones.

## Integrity and validation

```text
Frozen pre-result atlas manifest:       PASS
Source cases read and re-hashed:        1,659 / 1,659
Source record-hash mismatches:          0
Build semantic validation:              11 passed, 0 failed
Independent reproduction:              exact document match
Independent validation:                 17 passed, 0 failed
London/New York separation:             PASS
Conditional relationships tested:      0
Candidates created or ranked:           0
Execution variants or trades:           0
2025 values opened:                     No
2026 values opened:                     No
```

The first independent validator run exposed a validator-only assumption that
JSON object key order would preserve the frozen horizon list after canonical
serialization. The semantic check was corrected to verify the exact horizon
set, and a sorted-JSON round-trip regression test was added. No measurement,
threshold, source case, atlas value, or artifact definition was changed.
The corrected independent run passed all 17 checks and reproduced the sealed
atlas exactly.

## Primary artifacts

- frozen pre-result manifest:
  `research_manifests/gold_session_behaviour_v3_m3_atlas_v01.json`;
- sealed atlas:
  `research_artifacts/gold_session_behaviour_v3_atlas_v01/atlas.json`;
- result manifest:
  `research_artifacts/gold_session_behaviour_v3_atlas_v01/manifest.json`;
- build validation:
  `research_artifacts/gold_session_behaviour_v3_atlas_v01/semantic_validation.json`;
- independent validation:
  `research_artifacts/gold_session_behaviour_v3_m3_validation_v01.json`; and
- V3 state:
  `research_artifacts/gold_session_behaviour_v3_state_v03.json`.

Core seals:

- pre-result manifest hash:
  `30ae532aeeb3c3639bc87adc089757b11d4b83ba698af689dbf312a8ad2c2cf2`;
- atlas hash:
  `08bdbe31e559f52623091ea52c79fcff6b9056536a0781ab02a5dc02d9a61fb4`;
- atlas file SHA-256:
  `d23a6be91a87dd577d80594a71cd55ce2862f98653247ac97f894434c114299d`;
- result-manifest hash:
  `534df4e54a9c137c0d6ef53b6bdb263f03ec51a7751c44c1a3b6ae4dc05e2fc8`;
- build-validation hash:
  `181b615551e58cb21f232f3254bff969da87a5bc409ba3ed94def4a4ce93bde0`;
  and
- independent-validation hash:
  `ce48373477d01918760dc849b5a303a6f521b871129955eb8d9785339c11f13c`.

## Mandatory stop

Repository state after the V3 state seal:

**`COMPLETE_MANDATORY_STOP`**

The next contracted step is
`V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY`. It is not authorized. Nothing from
Milestone 4 was calculated or started.
