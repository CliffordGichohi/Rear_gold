# Gold Session Behaviour V3 — Milestone 2

## Verdict

**`PASS_V3_MILESTONE_2_INDEPENDENT_VALIDATION_MANDATORY_STOP`**

V3 Milestone 2 is complete. The development case matrix is sealed.
Milestone 3 is not authorized and was not started.

Independent read-back validation:

- checks passed: **18 / 18**;
- checks failed: **0**;
- records read back: **1,659 / 1,659**;
- validation hash:
  `2394ad0ff3dd71abe25757689b1655df78788dd9b76f86c2278e5f905b4e3893`;
- case-artifact SHA-256:
  `d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9`;
- result-manifest hash:
  `d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7`;
- V3 state hash:
  `26bc72f56c868a542b4cafce57b177f59df94fd26a4db39b342cd0b35244d46c`.

No 2025 or 2026 market, macro, positioning, event, structure, or outcome
value was opened. No frequency, distribution, relationship, candidate,
directional rule, trade, P&L, R multiple, MFE, MAE, or execution variant was
calculated.

## Authorization and frozen transform

Milestone 2 was separately authorized on 30 July 2026 by:

> if everything looks great, proceed to milestone 2

The transform was frozen before materialization in:

`research_manifests/gold_session_behaviour_v3_m2_case_matrix_v01.json`

Canonical pre-result manifest hash:

`2838beaf2af0b3a74dca7ac1280591505cadd1eb0fb8b6dd1e5f06ff45b1d8d9`

The original V3 contract was not rewritten. Its requirement for separate
milestone authorization was satisfied through this pre-result authority
manifest and the V3 state chain.

## Materialized case matrix

| Session | Cases |
|---|---:|
| London | 833 |
| New York | 826 |
| **Total** | **1,659** |

The grain is one immutable row per `session_code × session_date` from
1 August 2021 through 31 December 2024.

The sealed artifact is:

`research_artifacts/gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz`

Integrity:

- compressed bytes: **103,763,781**;
- SHA-256:
  `d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9`;
- unique case IDs: **1,659**;
- unique session keys: **1,659**;
- record-hash mismatches: **0**;
- schema-invalid records: **0**; and
- semantic-invalid records: **0**.

The artifact row order is deterministic: session date, then London before
New York when both are present. Gzip metadata uses `mtime=0`.

## What each row records

### Decision-known half

`decision_state.decision_eligible=true`

Each decision-state fact has:

- value and unit;
- `OBSERVED`, `CALCULATED`, `INFERRED`, or `UNKNOWN` status;
- observation and availability clocks;
- quality and method;
- explanation and evidence;
- source-record lineage; and
- an invalidation condition where applicable.

The row preserves:

- XAUUSD broker-feed identity, price, spread, and tick volume;
- deterministic structure on 1m, 5m, 15m, 1h, 4h, and daily timeframes;
- every source structure detection whose `detected_at` was decision-known;
- Asia and prior-session/day/week levels available at the clock;
- inflation, labour, growth, Fed-rate, yield, real-yield, breakeven, USD,
  equity, volatility, credit, and stress states;
- eligible release vintages and surprises;
- eligible Atlanta Fed quarterly SOFR probability windows, explicitly not
  labelled as exact FOMC meeting probabilities;
- CFTC managed-money, producer/merchant, swap-dealer, other-reportable, and
  open-interest states after publication;
- inferred positioning states explicitly labelled as inferences;
- recent released-event state and only reaction horizons already complete at
  the decision;
- session and liquidity clock context;
- synchronized cross-market state; and
- the existing transparent engine evidence, preserved as context rather than
  promoted to a V3 candidate.

All decision facts and source references passed
`available_at <= decision_at`. COT publication-timing violations were zero.

### Neutral subsequent-behaviour half

`subsequent_behaviour.decision_eligible=false`

The frozen neutral reference is the open of the complete 08:01 local
one-minute bar. It is explicitly **not** an entry or assumed fill.

Every row contains:

- **239** complete one-minute source bars from 08:01 through 12:00 local;
- **48** source five-minute path points covering 08:00 through 12:00 local;
- signed and absolute displacement after 5, 15, 30, and 60 minutes and at
  session close;
- maximum upward and downward displacement from the neutral coordinate;
- range, high, low, earliest high/low timestamps, and their order;
- close location using the frozen range-thirds calculation;
- deterministic neutral path state and path efficiency; and
- interaction state for every decision-known level: touch, breach,
  acceptance, rejection, failed break, and return/retest.

These measurements are descriptive price paths. They are not side-conditioned
excursions, trades, or profitability measurements.

## Honest UNKNOWN policy

Unavailable information remains visible and null. The matrix does not turn
missing data into a zero or neutral confirmation.

The main expected unavailable groups remain:

- COMEX intraday volume and historical depth, resilience, and price impact;
- exact meeting-by-meeting historical Fed probabilities and path;
- point-in-time ETF holdings and flows;
- vintage-aware central-bank demand;
- licensed historical options/dealer-gamma data;
- verified historical pre-release schedule publication times; and
- licensed unscheduled-news history.

All `UNKNOWN` facts were independently checked to have `value=null`.
Violations: **0**.

## Source and point-in-time integrity

Before deserialization, all seven immutable casebook artifact hashes were
recalculated and matched:

- price bars;
- market-structure snapshots;
- cross-market snapshots;
- positioning;
- events;
- fundamentals and policy windows; and
- session cases.

The immutable source bundle remains pinned at manifest hash:

`d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f`

Economic vintages remain separate. Later revisions do not overwrite original
release state. COT uses the Tuesday observation date and Friday publication
availability. DST uses the IANA London and New York timezones.

## Research boundary

Milestone 2 did only case construction and validation:

| Activity | Count/state |
|---|---:|
| Development case rows | 1,659 |
| Descriptive distributions | 0 |
| Feature-outcome joins | 0 |
| Relationship calculations | 0 |
| Candidates created | 0 |
| Execution variants | 0 |
| Trades or returns | 0 |
| 2025 values opened | No |
| 2026 values opened | No |

Therefore Milestone 2 does **not** claim to have found a behaviour frequency,
conditional bias, or edge. The rows are the controlled evidence base needed
to answer those questions in later separately authorized milestones.

## Validation and tests

```text
Build semantic validation:       11 passed, 0 failed
Independent all-row validation:  18 passed, 0 failed
Relevant unit tests:             15 passed, 0 failed
Ruff on new V3 Python:           passed
Frozen source hashes:            7 passed, 0 failed
Case record hashes:              1,659 passed, 0 failed
Frozen JSON schema:              1,659 passed, 0 failed
Point-in-time fact violations:   0
UNKNOWN non-null violations:     0
Structure/path violations:       0
```

Primary artifacts:

- `research_artifacts/gold_session_behaviour_v3_case_matrix_v01/manifest.json`;
- `research_artifacts/gold_session_behaviour_v3_case_matrix_v01/semantic_validation.json`;
- `research_artifacts/gold_session_behaviour_v3_m2_validation_v01.json`; and
- `research_artifacts/gold_session_behaviour_v3_state_v02.json`.

Implementation and regression coverage:

- `backend/src/gold_intel/analytics/session_behaviour_v3.py`;
- `backend/tools/build_gold_session_behaviour_v3_case_matrix.py`;
- `backend/tools/validate_gold_session_behaviour_v3_m2.py`; and
- `backend/tests/unit/test_session_behaviour_v3.py`.

## Reproduction

From the repository root:

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python `
  /workspace/backend/tools/build_gold_session_behaviour_v3_case_matrix.py `
  --root /workspace

docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python `
  /workspace/backend/tools/validate_gold_session_behaviour_v3_m2.py `
  --root /workspace
```

## Stop

Repository state:

**`COMPLETE_MANDATORY_STOP`**

The next contracted step is
`V3_M3_DEVELOPMENT_BEHAVIOUR_ATLAS`. It requires a new explicit user
instruction. Nothing from Milestone 3 was calculated or started.
