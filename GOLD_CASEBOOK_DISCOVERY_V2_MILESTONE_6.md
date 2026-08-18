# Gold Casebook Discovery V2 - Milestone 6

## Verdict

V2 Milestone 6 is complete.

The frozen London candidate received the honest one-time holdout verdict:

`REJECT_CALENDAR_2025_HOLDOUT`

The calendar-2025 holdout was opened exactly once. The candidate, feature
mapping, missing-data policy, session clocks, execution, costs, support
thresholds, uncertainty procedure, and all twelve pass/reject gates remained
unchanged.

The rejection is final for:

`LONDON_ZN_4H_POSTHOC_V0_1`

The result must not be repaired by changing the ZN horizon, threshold,
direction mapping, session, entry, exit, stop, target, costs, or confirmation
variables.

## Acquisition and source seal

The exact authorized Databento request was acquired:

| Field | Result |
|---|---|
| Dataset | `GLBX.MDP3` |
| Continuous symbol | `ZN.v.0` |
| Schema | `ohlcv-1m` |
| Interval | 2025-01-01 inclusive through 2026-01-01 exclusive |
| Job | `GLBX-20260729-4KJJLBXRRH` |
| Fresh pre-submission estimate | $1.185062900186 |
| Actual cost | $1.18506290018559 |
| Authorized maximum | $1.25 |
| Normalized rows | 324,605 |
| Duplicate rows | 0 |
| Underlying contracts | 5 |
| Observed roll transitions | 4 |

The fresh estimate and actual charge were both below the authorized cap. No
duplicate paid request was submitted.

The value-bearing payload was normalized, hashed, and sealed before the
readiness audit. Before all readiness gates passed, no human or model
inspected its market values, calculated a ZN direction, joined a feature to an
outcome, or inspected a calendar-2025 chart.

## Metadata-only readiness

All five gates passed before the value boundary was opened:

| Gate | Result | Evidence |
|---|---|---|
| R01 XAUUSD timestamp coverage | Pass | 258 of 261 weekdays, 98.8506% |
| R02 licensed ZN archive sealed | Pass | 324,605 rows; four raw files verified |
| R03 ZN roll lineage sealed | Pass | five contracts, four transitions, zero duplicates |
| R04 timestamp-only case coverage | Pass | 258 of 258 cases, 100% |
| R05 clean pre-open audit | Pass | 22 source hashes; zero synthetic rows |

The absent XAUUSD dates were 1 January, 18 April, and 25 December 2025. They
were excluded by the predeclared timestamp-complete population rule, not by
their outcomes.

The readiness audit examined 354,160 XAUUSD timestamps and 324,605 ZN
timestamp-lineage rows without deserializing calendar-2025 OHLC values. A
second independent metadata-only build produced byte-identical readiness
files before the holdout was opened.

## Frozen holdout result

The case population contained 258 timestamp-complete London weekdays:

| Population | Cases |
|---|---:|
| Positive ZN four-hour change -> long | 105 |
| Negative ZN four-hour change -> short | 123 |
| Flat ZN four-hour change -> no bias | 30 |
| Directional cases | 228 |

Base-cost performance for the 228 directional cases:

| Metric | Result |
|---|---:|
| Net win rate | 46.0526% |
| Mean net P&L per one-ounce case | -$0.8306 |
| Mean net return | -2.2038 bps |
| Median net P&L per one-ounce case | -$0.9950 |
| Total net P&L at the fixed one-ounce research size | -$189.38 |
| Profit factor | 0.8601 |
| Long decisions | 105 |
| Short decisions | 123 |

These dollar figures are the contract's fixed one-ounce research measurement.
They are not account-level returns, a leverage simulation, or a claim about a
$10,000 account.

### Direction mapping

Both frozen mappings were non-positive:

| Mapping | Cases | Win rate | Mean net return | Profit factor |
|---|---:|---:|---:|---:|
| Positive ZN -> long gold | 105 | 54.2857% | -0.1444 bps | 0.9553 |
| Negative ZN -> short gold | 123 | 39.0244% | -3.9619 bps | 0.7770 |

The positive-to-long side was close to flat but still negative after the
frozen costs. The negative-to-short side was materially worse. The contract
does not permit retaining one side after seeing the holdout.

### Matched controls

The controls used exactly the same 228 directional dates and frozen costs:

| Rule | Mean net return | Profit factor | Total net P&L per ounce |
|---|---:|---:|---:|
| Frozen ZN selector | -2.2038 bps | 0.8601 | -$189.38 |
| Always long | +1.2940 bps | 1.0605 | +$73.60 |
| Always short | -2.7483 bps | 0.8638 | -$184.34 |

Always long was the better matched control. The candidate underperformed it by
3.4978 bps per case.

### Stability and uncertainty

| Test | Result |
|---|---:|
| Early-half cases / mean | 116 / -1.0375 bps |
| Late-half cases / mean | 112 / -3.4119 bps |
| Mean at 1.5x costs | -2.5674 bps |
| Profit factor at 1.5x costs | 0.8414 |
| ISO-week bootstrap 95% interval | -7.1718 to +3.0023 bps |
| Cluster sign-flip p-value | 1.0000 |
| One-candidate BH q-value | 1.0000 |

Both chronological halves were negative. The cluster interval crossed zero,
and its lower bound was below zero. Because the observed mean was negative,
the frozen one-sided sign-flip test provided no evidence for a positive edge.

## Gate record

Only four of twelve gates passed:

| Gate | Result |
|---|---|
| G01 point-in-time and lineage integrity | Pass |
| G02 at least 180 directional cases | Pass |
| G03 at least 80 cases per directional state | Pass |
| G04 at least 35 ISO weeks per directional state | Pass |
| G05 positive mean net return | Fail |
| G06 profit factor above one | Fail |
| G07 beat the better matched control | Fail |
| G08 both direction mappings positive | Fail |
| G09 both chronological halves positive | Fail |
| G10 survive 1.5x costs | Fail |
| G11 cluster-bootstrap lower bound above zero | Fail |
| G12 BH q-value at or below 0.10 | Fail |

The failure is not caused by insufficient sample support, missing data, DST,
provider identity, duplicate rows, synthetic data, or unresolved roll
lineage. It is an economic and stability rejection: the frozen mapping lost
after costs, lost in both halves, underperformed always long, failed cost
stress, and failed cluster-aware uncertainty.

## Independent validation

The independent validator:

- verified every source, readiness, open-intent, bundle, and record hash;
- proved each ZN endpoint was the latest point-in-time row using the sealed
  timestamp lineage;
- recomputed the four-hour feature sign and roll policy for every case;
- recomputed every XAUUSD source identity and long/short cost identity;
- reassigned chronological halves before removing no-bias cases;
- recomputed matched controls and 1.5x cost results;
- reran 5,000 ISO-week cluster bootstraps and 20,000 sign flips;
- recomputed the one-candidate BH q-value;
- recomputed all twelve gates and the rejection; and
- confirmed that New York and calendar 2026 were not opened.

Validation result:

`PASS_SEMANTIC_VALIDATION`

This means the rejection was reconstructed correctly. It does not turn the
candidate into a passing strategy.

## Integrity hashes

| Artifact | Hash |
|---|---|
| Frozen Milestone 6 research manifest | `e7d6abefd921c2a0ce690556c43a9d7640b3091a4b5bbec7400a3ceabb549c66` |
| Readiness document | `5ed5c996e694cda276b5cc4f037634a80441072411c79bfaded4b2e73678a672` |
| Readiness bundle manifest | `fb2fe6399aa14ed8e398dd7416b4b1c3a7756307357af6bca4733b25d7c6f9e2` |
| ZN normalization | `bed5f90e7b206780a6407bea2a1d6aad84cfe83ab82dab7eef710f16394cbf5e` |
| ZN normalized payload SHA-256 | `775050d1991b2df4e9fc53e8cdbed3abdc135b5618e31e95f54786446acf190f` |
| One-time open intent | `7ff81951d61d85887c5d9d833af4a868f899a0f811d9c443e430512923df8a3d` |
| Decision ledger SHA-256 | `bcbeb2a7fbf19d2d8e9d5c07c034d7db9c72c79b8fad2b918fa815532c18c397` |
| Holdout results | `b405c5acccb89befe1d3908127481488e587598e22e3a1a0b593c4b595a87890` |
| Holdout bundle manifest | `110018f6997b7b96c55398696f68a70b1935f9a488dfe39bcc204e9ea5bb6d68` |
| Semantic validation | `72dca983c179387adcf2fc324d318d3ccd8c34f9bb7d0fd5be0e3a1fad717e07` |

Canonical bundles:

- `research_artifacts/gold_casebook_discovery_v2_m6_readiness_v01`
- `research_artifacts/gold_casebook_discovery_v2_holdout_v01`

The one-time access receipt is:

`research_artifacts/gold_casebook_discovery_v2_holdout_v01_open_intent.json`

## Quality checks

- focused Milestone 6 unit and synthetic reconstruction tests: 16 passed;
- Ruff format and lint: passed for the Milestone 6 implementation;
- independent semantic validation: passed;
- full backend suite: 182 passed.

## Revalidate without reopening the raw holdout

The holdout runner is intentionally protected by the one-time open-intent
receipt and will refuse a second run. The sealed decision ledger can be
revalidated without reopening the raw value sources:

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  --workdir /workspace `
  backend-test python `
  backend/tools/validate_gold_casebook_discovery_v2_holdout.py `
  --output /tmp/gold-casebook-v2-m6-semantic-validation.json
```

## Contract state after Milestone 6

Milestone 6 stops here.

The sole V2 candidate is rejected. Under the existing V2 contract, Milestone
7 execution research is eligible only for a candidate that passes Milestone
6, so it is not eligible on this branch. No next milestone is authorized.
Calendar 2026 remains unopened and cannot be used to repair this result.
