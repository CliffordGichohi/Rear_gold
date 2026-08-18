# Gold Session Behaviour V3 — Milestone 6A

## Status

V3 Milestone 6A is complete under Amendment B.

**Process verdict:**
`PASS_V3_MILESTONE_6A_INDEPENDENT_VALIDATION_MANDATORY_STOP`

**Metadata readiness verdict:**
`READY_WITH_LOW_POWER_EXPECTED_AND_RECORDED_COVERAGE_GAPS`

This is not a candidate, edge, or trading verdict. Calendar-2025 and
calendar-2026 market values, macro values, candidate states, session paths,
and outcomes remain unopened by V3 Milestone 6.

Milestone 6A completed only:

- the exact forward decision protocol;
- the immutable two-candidate registry;
- a candidate-specific metadata-only source audit;
- a power calculation based only on frozen planning assumptions and timestamp
  upper bounds;
- independent metadata reproduction;
- documentation and state sealing; and
- the mandatory stop before holdout access.

## Preserved shortlist

Exactly two candidates remain:

| Session | Candidate | Condition | Exact complement | Source series |
|---|---|---|---|---|
| London | `LONDON_VOLATILITY_DIRECTION_V0_1` | volatility change FALLING | RISING | `US_VOLATILITY_INDEX` |
| New York | `NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1` | financial-stress change FALLING | RISING | `US_FINANCIAL_STRESS` |

`UNCHANGED` remains a known excluded state. Missing, stale, synthetic,
unverified, or after-decision information remains `UNKNOWN`.

No M5 definition, direction, complement, source field, or interpretation was
changed. The two M5 rejections and all rejected ZN rules remain closed.

## Pre-result protocol freeze

Amendment B and the executable audit implementation were sealed before the
metadata audit.

- Amendment B: `GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_B.md`
- pre-result manifest:
  `research_manifests/gold_session_behaviour_v3_m6a_amendment_b_v01.json`
- pre-result manifest hash:
  `218564c0459f711f08c32529b095e06bfd47a092dbd1d5bfa3f6d483afae133d`
- pre-result manifest file SHA-256:
  `6665c5ef61df449fde035e9b6404908a00141640d52f9fa526e226f5bfe14a4c`
- protocol fingerprint:
  `308ff594d85b478b755f85397d19ed7e76faad50fa447af29f7ee8692dcd54de`
- candidates frozen: 2
- forward values read before freeze: 0

The protocol fixes the reporting order:

1. exposed calendar 2025;
2. locked independent 2026 YTD through 29 July; and
3. prospective 2026 from 31 July through 31 December.

The 30 July prospective session is excluded because no Amendment-B-compliant
decision record was sealed before both session outcomes.

## Exact forward verdict gates

Support is tested independently by candidate and segment. It requires:

- joint-known feature coverage of at least 50%;
- at least 25 condition binary cases;
- at least 25 complement binary cases;
- at least 80 combined binary cases;
- at least 4 distinct source signatures on each side;
- at least 4 state episodes on each side; and
- no duplicate source records or case keys.

The fixed family contains both candidates. Each segment uses a two-sided
Fisher exact test and Holm-Bonferroni correction across exactly two
candidates at family alpha 0.10. An unsupported candidate stays in the family
with raw p-value 1.0.

### PASS

`PASS_MATERIAL_POSITIVE_REPLICATION` requires all of:

- support passes;
- effect of at least +7.5 percentage points;
- Newcombe-Wilson 95% interval lower bound above zero;
- Holm-adjusted p-value at most 0.10;
- positive condition median signed close; and
- negative complement median signed close.

### REJECT

`REJECT_MATERIAL_REVERSE_REPLICATION` is exactly symmetric:

- support passes;
- effect at or below -7.5 percentage points;
- 95% interval upper bound below zero;
- Holm-adjusted p-value at most 0.10;
- negative condition median; and
- positive complement median.

### INCONCLUSIVE

- any support failure:
  `INCONCLUSIVE_INSUFFICIENT_SUPPORT`;
- otherwise, when neither complete PASS nor complete REJECT holds:
  `INCONCLUSIVE_MIXED_OR_UNDERPOWERED`.

Calendar-2025 PASS is supportive exposed evidence only. A material 2025
REJECT remains terminal negative evidence. A current directional-bias
candidate requires both an independent 2026-YTD PASS and a prospective-2026
PASS, with no segment rejection.

These rules do not authorize a trade or imply profitability.

## Metadata-only guard

The database transaction was read-only. Three SQL statements passed the
existing forbidden-value-column guard. They selected only:

- exact provider, instrument, timeframe, and series identifiers;
- bar, observation, and availability timestamps;
- row and distinct-timestamp counts;
- completeness, synthetic, revision, and point-in-time ordering counts; and
- timestamp-only session coverage.

The audit did not select OHLC, macro values, candidate states, UP/DOWN
outcomes, paths, returns, scores, effects, p-values, or PnL.

## Candidate-specific readiness

All four historical candidate/segment combinations passed the metadata
readiness gates:

| Segment | Candidate | Potential complete session upper bound | Candidate-series periods | Synthetic rows | Metadata status |
|---|---|---:|---:|---:|---|
| Exposed 2025 | London volatility | 257 | 258 | 0 | Ready, low power expected |
| Exposed 2025 | New York financial stress | 257 | 52 | 0 | Ready, low power expected |
| Locked 2026 YTD | London volatility | 140 | 145 | 0 | Ready, low power expected |
| Locked 2026 YTD | New York financial stress | 139 | 29 | 0 | Ready, low power expected |

Every candidate-series interval row had valid availability ordering. Each
series also had more than two distinct pre-segment observation periods.

Metadata readiness does not reveal how many FALLING, RISING, UNCHANGED,
UNKNOWN, UP, DOWN, or FLAT cases exist. Exact support remains unknown until
a separately authorized one-time opening.

## XAUUSD timestamp coverage

| Segment | Requested weekdays | London potential cases | New York potential cases | IC Markets one-minute rows | Last stored bar |
|---|---:|---:|---:|---:|---|
| Exposed 2025 | 261 | 257 | 257 | 354,160 | 2025-12-31 23:58 UTC |
| Locked 2026 YTD | 150 | 140 | 139 | 199,032 | 2026-07-27 07:20 UTC |

The incomplete weekday set is retained honestly; no session may be
synthesized. The terminal timestamp gaps cover 27, 28, and 29 July 2026.
A source refresh is recommended before Milestone 6B. If IC Markets or the
public source cannot supply a missing record, it remains missing.

No paid API, CME archive, ZN archive, cTrader access, COT feed, ETF source, or
options source is required for these two frozen candidates.

## Power audit

Power used no forward values or observed candidate prevalence. It assumed:

- the frozen +7.5-point effect;
- condition probability 53.75%;
- complement probability 46.25%;
- balanced condition/complement support;
- every potential session becoming a non-flat binary case in the best case;
- two-sided alpha 0.05, reflecting the first Holm threshold and the 95%
  interval requirement.

| Segment | Best-case split per candidate | Best-case approximate power | Power if 80% become binary cases |
|---|---:|---:|---:|
| Exposed 2025 | 128 / 129 | 22.45% | 18.83% |
| Locked 2026 YTD — London | 70 / 70 | 14.32% | 12.40% |
| Locked 2026 YTD — New York | 69 / 70 | 14.25% | 12.33% |
| Prospective 2026 weekday upper bound | 55 / 55 | 12.26% | 10.76% |

The planning calculation requires approximately 697 cases per side, or 1,394
balanced binary cases, for 80% power at a true 7.5-point effect. Approximately
932 per side are required for 90% power.

These are optimistic upper bounds. The complete conjunctive PASS probability
is no greater and can be lower because real data include missing, unchanged,
unknown, and flat cases plus median requirements.

The honest implication is:

- M6B can still detect a very large replication or a material reversal;
- the finite historical segments are unlikely to prove a true 7.5-point
  effect under the strict confirmatory gate; and
- an `INCONCLUSIVE` result is scientifically expected and cannot be repaired
  by relaxing the gate after outcomes are known.

Power did not change any threshold.

## Prospective readiness

The prospective segment is fixed at 2026-07-31 through 2026-12-31:

- weekday upper bound: 110;
- decision records created by M6A: 0;
- market values or outcomes read: 0;
- retroactive decisions permitted: no;
- interim inferential testing permitted: no; and
- formal endpoint: 2026-12-31.

Milestone 6B must initialize the append-only decision ledger before an
eligible session. A missing pre-session decision can never be backfilled.

## Integrity and reproducibility

- readiness audit:
  `research_artifacts/gold_session_behaviour_v3_m6a_readiness_v01/readiness_audit.json`
- readiness audit hash:
  `38fff196a4ef6ca45c8d545506531dbddfdf0b7b17113248a4227e6be736cd4d`
- readiness audit file SHA-256:
  `11b2030b47188d2faba1f16d519a62b5dbd143e6d1fffc7676622047e61bfaed`
- result manifest hash:
  `567087285b78edc79dab9e7f1ff83fb5dd998c2c6f74f27c5068ff8132e42c2c`
- build semantic-validation hash:
  `b58a5a22ff64fb3d41a72c75f1f8fe18566ac647479ba3256f10b9947eedf2b0`
- independent validation hash:
  `56b20cff499f1a06985909c5f8f153de79477fb33c8b551dd9addb72aaa6eae1`
- independent checks: 19 passed, 0 failed
- exact metadata-audit reproduction: passed
- relevant regression tests: 40 passed, 0 failed
- M6A lint errors: 0

## Honest conclusion and stop

The exact sources needed by both candidates exist for 2025 and locked 2026
YTD, and their timestamp upper bounds do not make the support floors
impossible. The sources therefore pass metadata readiness.

The audit simultaneously shows that the one-year and YTD samples are
statistically weak for the strict frozen PASS standard. This is information
we learned without opening a single forward value or outcome.

Milestone 6B is not authorized. Calendar-2025 and calendar-2026 values remain
locked, no candidate verdict has been calculated, and Milestone 6A stops here.
