# Gold Session Behaviour V3 — Milestone 4

## Status

Milestone 4 is complete and sealed under the existing V3 research
contract.

**Verdict:** `PASS_V3_MILESTONE_4_INDEPENDENT_VALIDATION_MANDATORY_STOP`

This is a process verdict: the bounded discovery was performed exactly as
preregistered and independently reproduced. It is **not** an edge verdict.
The empirical result is:

- London provisional candidates advanced: **0**
- New York provisional candidates advanced: **0**
- 2025 values inspected: **no**
- 2026 values inspected: **no**
- execution variants, trades, returns, R multiples, entries, exits, stops,
  and targets tested: **0**
- rejected ZN rules reopened: **no**

Zero candidates was an explicitly permitted Milestone 4 outcome. Nothing
was weakened, inverted, renamed, or repaired to force a candidate through.

## Frozen scope

The analysis used only the sealed development case matrix:

- period: 2021-08-01 through 2024-12-31
- London cases: 833
- New York cases: 826
- total cases: 1,659
- case artifact SHA-256:
  `d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9`

The complete Reference-Book-traceable design was frozen before relationship
calculation:

- pre-result manifest:
  `research_manifests/gold_session_behaviour_v3_m4_discovery_v01.json`
- embedded manifest hash:
  `e024ceba35a6d3af1c384f8c66eec299aab8cdcd23b666eb9f33ac672a24fbf4`
- file SHA-256:
  `e11b86385c1d7594a48ef1d11fc04b65ac979c952251078528ed727f0fd91127`
- eligible features: 102
- tested feature states: 230
- permitted exact two-condition interactions: 40
- Reference Book factors with explicit disposition: 75 of 75

London had 97 applicable features, 213 registered single-state conditions,
and 36 applicable interactions. New York had all 102 features, 230
single-state conditions, and all 40 interactions.

## Frozen method

The primary outcome was the `SESSION_CLOSE` displacement from the neutral
session reference:

- `UP`: greater than +$0.01/oz
- `DOWN`: less than -$0.01/oz
- `FLAT`: absolute displacement at or below $0.01/oz

Flat cases were recorded but excluded from the binary UP/DOWN contingency
test. Each condition was compared with all other known, non-flat cases for
that feature and session.

Individual variables were completed before the exact preregistered
interactions. The statistical method was:

- two-sided Fisher exact test
- Wilson 95% intervals for each UP proportion
- Newcombe-Wilson 95% interval for the difference
- Benjamini-Hochberg false-discovery control, applied separately by session
  and stage
- frozen FDR threshold: `q <= 0.10`

A single condition also required:

- frozen support floors
- absolute UP-rate difference of at least 7.5 percentage points
- difference interval excluding zero
- median signed close displacement agreeing with the association

An interaction required a 10-point effect, all common gates, supported
constituents, and at least 3 points of incremental absolute effect over each
constituent. Ranking was frozen before calculation, and no more than two
candidates per session could advance.

## Baseline session behaviour

| Session | Cases | UP | DOWN | FLAT | UP share of non-flat | Median signed close | Median absolute close | Median session range |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| London | 833 | 416 | 415 | 2 | 50.06% | $0.01 | $3.35 | $7.98 |
| New York | 826 | 404 | 421 | 1 | 48.97% | -$0.21 | $5.00 | $11.84 |

The unconditional direction was almost balanced. The task in Milestone 4
was therefore to determine whether any frozen condition shifted that
baseline strongly and reliably enough to survive the complete screen.

## Complete relationship inventory

| Session | Singles recorded | Singles support-eligible | Interactions recorded | Interactions support-eligible | Total recorded | Candidate-gate passes | Advanced |
|---|---:|---:|---:|---:|---:|---:|---:|
| London | 213 | 142 | 36 | 28 | 249 | 0 | 0 |
| New York | 230 | 158 | 40 | 32 | 270 | 0 | 0 |

All 519 applicable relationships are present in
`research_artifacts/gold_session_behaviour_v3_m4_discovery_v01/relationships.json`.
Unsupported conditions, null tests, contradictory directions, weak effects,
and every other negative result are retained in that file. No failed row was
dropped from the reporting record, and no support-eligible row was dropped
from its frozen multiplicity family.

## Why no candidate advanced

No support-eligible relationship achieved the frozen `q <= 0.10` gate.

| Session | Stage | Support-eligible tests | Smallest raw p | Smallest BH q |
|---|---|---:|---:|---:|
| London | Singles | 142 | 0.00837898 | 0.63619988 |
| London | Interactions | 28 | 0.03895848 | 0.66057301 |
| New York | Singles | 158 | 0.00615987 | 0.84250871 |
| New York | Interactions | 32 | 0.02413526 | 0.44954256 |

The raw development associations below passed every frozen gate except
false-discovery control. They are recorded to show what the screen saw, but
they are **rejected M4 relationships, not candidates**.

| Session | Stage | Condition | n | Direction | Difference | Raw p | BH q |
|---|---|---|---:|---|---:|---:|---:|
| London | Single | Volatility change falling | 460 | Bullish | +8.14 pp | 0.02133 | 0.63620 |
| London | Single | Volatility change rising | 365 | Bearish | -7.68 pp | 0.03031 | 0.63620 |
| London | Single | Asian direction down | 385 | Bullish | +7.87 pp | 0.02602 | 0.63620 |
| London | Single | Asian direction up | 446 | Bearish | -7.87 pp | 0.02602 | 0.63620 |
| London | Single | 15-minute trend bearish | 243 | Bearish | -9.10 pp | 0.01814 | 0.63620 |
| London | Single | 1-minute momentum negative | 417 | Bullish | +9.27 pp | 0.00838 | 0.63620 |
| London | Single | 1-minute momentum positive | 405 | Bearish | -7.58 pp | 0.03149 | 0.63620 |
| London | Interaction | Engine score and 1-hour bearish | 90 | Bullish | +11.15 pp | 0.05728 | 0.66057 |
| New York | Single | Nearest known level near versus 1-hour ATR | 349 | Bearish | -7.90 pp | 0.02883 | 0.84251 |
| New York | Single | Financial-stress change falling | 381 | Bullish | +8.01 pp | 0.02535 | 0.84251 |
| New York | Single | Financial-stress change rising | 444 | Bearish | -8.01 pp | 0.02535 | 0.84251 |
| New York | Single | Asian spread expansion wide | 600 | Bearish | -10.89 pp | 0.00616 | 0.84251 |
| New York | Single | Decision price above Asian range | 234 | Bearish | -8.11 pp | 0.03725 | 0.84251 |
| New York | Single | 4-hour compression detected | 92 | Bullish | +12.17 pp | 0.03512 | 0.84251 |

The apparently opposite London response after Asian UP/DOWN conditions and
the short-horizon momentum reversals are development observations only.
They do not receive a label such as “mean reversion edge,” because that
would be a post-result causal interpretation and candidate repair.

### Accumulated rejection reasons

Rows may have more than one rejection reason.

| Failure tag | London | New York |
|---|---:|---:|
| BH q above 0.10 | 249 | 270 |
| Difference interval includes zero | 233 | 251 |
| Absolute effect below frozen minimum | 226 | 239 |
| Median sign disagrees | 28 | 60 |
| State episodes below minimum | 51 | 54 |
| Condition prevalence below minimum | 36 | 37 |
| Condition cases below minimum | 35 | 36 |
| Distinct source signatures below minimum | 29 | 32 |
| Known complement below minimum | 11 | 11 |
| Feature known coverage below 50% | 6 | 6 |
| Interaction incremental effect below 3 pp | 30 | 30 |
| Constituent single support ineligible | 12 | 12 |

## Coverage findings

Coverage was broad but not universal:

| Session | Applicable features | At least 50% known | Below 50% known | Fully unknown |
|---|---:|---:|---:|---:|
| London | 97 | 94 | 3 | 0 |
| New York | 102 | 99 | 3 | 0 |

The three sub-50% features in each session were catalyst impact, the
synthesis catalyst-surprise direction, and the high-yield-spread change.
They remained in the complete audit record but could not pass the frozen
single-feature coverage floor.

Positioning and COT were explored, not omitted. No positioning single was
support-eligible. Inferred crowding and participation states lacked eight
distinct frozen source signatures; persistent net-sign states also lacked
enough state episodes or a sufficiently large complement. Their descriptive
effects remain recorded, but no COT relationship was promoted or presented
as observed institutional intent.

## Implementation incident record

Three implementation defects were encountered and corrected without
changing the frozen research design:

1. Before any relationship calculation, the outcome adapter expected bare
   numbers while the sealed case schema stores audit facts under `value`.
   It was changed only to unwrap the frozen `SESSION_CLOSE`, 60-minute,
   excursion, range, and extreme-order facts.
2. A full pre-statistics vocabulary audit found two raw source labels not
   expressed in the frozen vocabulary. The deterministic aliases are:
   `MIXED_MACRO_REACTION_FUNCTION -> BALANCED_REACTION_FUNCTION` and
   structure `RANGE -> MIXED_OR_TRANSITIONING`. No state was added, removed,
   or made testable.
3. After relationships were calculated in memory, sealing stopped because
   the validator compared a difference made from rounded proportions with
   the engine's difference made from exact proportions. The validator was
   corrected to recompute from contingency counts. No relationship value,
   p/q value, gate, ranking, or result was changed.

The failed attempts wrote no result artifact. The final run was recomputed
from the sealed source, sealed once, and then reproduced independently.

## Integrity and reproducibility

- relationship document hash:
  `c8d011c69446df3f287dae9e77a4d0e78057c8850e811299302b689ff09d6b70`
- relationship file SHA-256:
  `f8a4e55da149ec22f29f3455251f7c69bcf9e316b2fbad75f7a7580d8a04412b`
- result manifest hash:
  `c12a71ac9decf0d2cd3f6866528809c937edab8cd6fc3e42072a5bbf8187c40c`
- build semantic validation hash:
  `bebca06e34f9fcf1233613c0986663750a47dfa38ac3a5ae9c4f37d4aa0bafb4`
- independent validation hash:
  `f34f1910fc4d18a5a41d00928c8baf1954f62404abe90e5939834677f280014a`
- independent validation checks: 16 passed, 0 failed
- independent exact-document reproduction: passed

## Honest conclusion

The bounded V3 Milestone 4 screen did **not** discover a provisional
session-direction candidate that survived its preregistered multiplicity
and robustness gates. Several raw development associations were large enough
to be interesting, but the screen was deliberately broad, and none survived
false-discovery control.

This does not prove that fundamentals, structure, sessions, liquidity, or
positioning contain no useful information. It establishes a narrower fact:
under the frozen one-state and exact two-state definitions, neutral
session-close outcome, support floors, and FDR procedure, this development
matrix produced no relationship strong enough to advance.

Milestone 5 is not authorized and has not started. Any proposal to change
the outcome, reduce the hypothesis family, repair source lineage, introduce
chronology-aware stability, create a hierarchical confirmatory family, or
use a path target would require explicit contract authorization. It cannot
be smuggled into this completed result.
