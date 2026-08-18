# Gold Session Behaviour V3 — Milestone 1

## Verdict

**`PASS_V3_MILESTONE_1_MANDATORY_STOP`**

V3 Milestone 1 is complete. Milestone 2 is not authorized and was not started.

Independent governance validation:

- checks passed: **24 / 24**;
- checks failed: **0**;
- validation hash:
  `f18125174104f23dd75e4b46ea6c9669f0aa7ec572cc6eaa57938ed5979b504e`;
- validation artifact SHA-256:
  `9d6f4b6a2d32b966fa1f1e7975e58c624bcc6b06bacd6c224fc3b0fe6ad527b1`;
- state hash:
  `058757c85ccbb657b6a5525d1f9e21521a75b29152f9bd88bc8a37fcc8339d3b`.

No 2025 or 2026 market, macro, positioning, release, forecast,
probability, feature, or outcome value was inspected. No relationship,
candidate, trade direction, or execution rule was calculated.

## Completed artifacts

| Deliverable | Path | Integrity |
|---|---|---|
| Human contract | `GOLD_SESSION_BEHAVIOUR_DISCOVERY_CONTRACT_V3.md` | Frozen |
| Machine contract | `research_manifests/gold_session_behaviour_discovery_contract_v03.json` | Manifest hash `79a74f81…140b` |
| Human traceability catalog | `GOLD_SESSION_BEHAVIOUR_V3_TRACEABILITY.md` | 75 requirements |
| Machine traceability catalog | `research_manifests/gold_session_behaviour_v3_traceability_v01.json` | Catalog hash `8707c39e…6bb4` |
| Human metadata audit | `GOLD_SESSION_BEHAVIOUR_V3_COVERAGE.md` | Metadata only |
| Machine metadata audit | `research_artifacts/gold_session_behaviour_v3_coverage_v01.json` | Data hash `35e03c1b…6bcd` |
| Human case-matrix specification | `GOLD_SESSION_BEHAVIOUR_V3_CASE_MATRIX.md` | No rows created |
| JSON case-matrix schema | `research_schemas/gold_session_behaviour_v3_case_matrix.schema.json` | SHA-256 `33d47e45…92a7` |
| V3 state | `research_artifacts/gold_session_behaviour_v3_state_v01.json` | State hash `058757c8…9d3b` |
| This milestone report | `GOLD_SESSION_BEHAVIOUR_V3_MILESTONE_1.md` | Mandatory stop |

Supporting implementation and validation:

- `backend/src/gold_intel/analytics/casebook_discovery_v3.py`;
- `backend/tools/audit_gold_session_behaviour_v3_coverage.py`;
- `backend/tools/validate_gold_session_behaviour_v3_m1.py`;
- `backend/tests/unit/test_casebook_discovery_v3.py`; and
- `research_artifacts/gold_session_behaviour_v3_m1_validation_v01.json`.

## Frozen research partitions

| Partition | Classification | V3 rule |
|---|---|---|
| 2021-08-01 through 2024-12-31 | Development already observed | Later case construction, description, bounded discovery, and internal stability only |
| Calendar 2025 | Exposed historical forward test | No discovery and no independent-validation credit |
| 2026-01-01 through 2026-07-29 | Locked independent YTD holdout | Values locked until a frozen shortlist and explicit Milestone 6 authorization |
| Post-freeze 2026, never before 2026-07-30 | Prospective | Decision records sealed before outcomes |

The prospective start is not retroactive. It is the first complete eligible
session strictly after the future immutable shortlist-freeze timestamp.

## Preserved prior results

Nothing was erased or relabelled:

1. `UNIVERSAL_ZN_4H_SIGN_V0_1` remains
   **`REJECT_CHRONOLOGICAL_VALIDATION`**.
2. `LONDON_ZN_4H_POSTHOC_V0_1` retains its positive internal-development
   evidence as exactly that: internal development evidence.
3. The same London rule remains
   **`REJECT_CALENDAR_2025_HOLDOUT`**.
4. The rejected rules cannot be inverted, filtered, thresholded, renamed, or
   presented as active V3 candidates.
5. The original immutable casebook remains preserved at manifest hash
   `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f`.

## Reference Book alignment

The complete book was re-read and verified at SHA-256:

`3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a`

Its reading chain has been mapped into 75 field requirements:

| Development status | Count |
|---|---:|
| Present | 34 |
| Derivable but not calculated | 14 |
| Partial | 18 |
| Unavailable | 6 |
| Execution-only and out of scope | 3 |

The six unavailable groups are visible rather than guessed:

- order-book depth, resilience, and price impact;
- exact meeting-level historical Fed probabilities;
- ETF holdings and flows;
- central-bank demand;
- options chains, volatility surfaces, and dealer gamma; and
- point-in-time unscheduled-news history.

These remain `UNKNOWN`, not neutral.

## Case-matrix decision

The schema uses one row per `session_code × session_date` and strictly
separates:

```text
decision_state: available_at <= decision_at
subsequent_behaviour: decision_eligible = false
```

The outcome side permits descriptive neutral path measurements:

- 5m, 15m, 30m, 60m, and close displacement;
- maximum upward and downward displacement;
- range, high/low time and order;
- complete path;
- level touch, breach, acceptance, rejection, failed break, and retest; and
- close location and deterministic path class.

The neutral reference is the 08:01 local one-minute bar open. It is not an
entry or assumed fill.

The schema fixes all trade, candidate, execution, MFE/MAE, P&L, R-multiple,
and account-return flags to `false`.

## Metadata-only coverage result

### Development

The immutable bundle contains 833 London and 826 New York cases. V3 created
zero new case rows and calculated zero outcomes or relationships in this
milestone.

### Exposed 2025

Metadata records:

- 354,160 unique IC Markets XAUUSD one-minute timestamps;
- 257 timestamp-complete London cases from 261 weekdays;
- 257 timestamp-complete New York cases from 261 weekdays;
- 20 macro-series identifiers;
- 52 COT publication records;
- 107 economic-event identities;
- zero forecasts verified for historical pre-event use; and
- 324,605 sealed Databento ZN rows declared by metadata.

No underlying value was opened by V3 Milestone 1.

### Locked 2026 YTD

Metadata records:

- 199,032 unique IC Markets XAUUSD one-minute timestamps;
- 140 timestamp-complete London cases from 150 weekdays;
- 139 timestamp-complete New York cases from 150 weekdays;
- 20 macro-series identifiers;
- 30 COT publication records;
- 348 economic-event identities;
- zero forecasts verified for pre-event use;
- 29 overlapping raw-XAU filename pairs; and
- no 2026 CME-rates archive.

The latest database XAU timestamp metadata ends before the contracted 29 July
YTD boundary. Therefore the 2026 source is not yet a complete holdout source.
Missing dates may not be synthesized, and overlapping exports may not be
double-counted.

This is not a candidate blocker yet because no candidate exists. A
candidate-specific metadata audit is required only after an immutable
Milestone 5 shortlist.

## Audit proof

The audit:

- ran its database transaction read-only;
- rechecked eight SQL statements against a forbidden-value-column guard;
- queried identifiers, timestamps, counts, and quality flags only;
- hashed raw files without invoking a CSV value parser;
- parsed only the sealed Databento normalization metadata, not its OHLCV
  payload;
- calculated no feature value or feature-outcome join; and
- produced deterministic coverage hash
  `35e03c1b9b63e9a9e399fd9d9f6d0a9dd39ce40490723a8057b103ce843a6bcd`.

## Verification

```text
V3 unit tests:          10 passed
Ruff on new V3 Python:  passed
Governance validation: 24 passed, 0 failed
Schema JSON parse:      passed
Contract hash:          passed
Traceability hash:      passed
Coverage hash:          passed
State/output hashes:    passed
Prior rejections:       preserved
2025 access boundary:   passed
2026 lock boundary:     passed
```

## Stop

The repository state is:

**`COMPLETE_MANDATORY_STOP`**

The next contracted step would be
`V3_M2_DEVELOPMENT_CASE_MATRIX`, but it is not authorized. Nothing from
Milestone 2 was started.
