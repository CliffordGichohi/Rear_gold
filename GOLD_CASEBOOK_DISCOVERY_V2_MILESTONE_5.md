# Gold Casebook Discovery V2 — Milestone 5

## Verdict

V2 Milestone 5 is complete.

The shortlist and the complete one-time calendar-2025 evaluation protocol are
now frozen.

| Session | Frozen candidates | Candidate |
|---|---:|---|
| London | 1 | `LONDON_ZN_4H_POSTHOC_V0_1` |
| New York | 0 | None |

The shortlist status is:

`FROZEN_BLOCKED_PENDING_ZN_2025_ACQUISITION`

This is a data-readiness blocker, not a failed holdout result. No calendar-2025
price value, ZN value, feature direction, return, P&L, or chart was opened, and
no calendar-2025 outcome was calculated.

## What was frozen

The London candidate retains exactly the contract-recognized rule:

| ZN four-hour state at the 08:00 London decision | Bias |
|---|---|
| Positive | Long |
| Negative | Short |
| Flat, unknown, unavailable, stale, or roll-crossing | No bias |

There is:

- no threshold;
- no confirmation variable;
- no rule retuning;
- no proxy substitution;
- no New York reuse;
- no promotion of a Milestone 3 q-failed relationship; and
- no execution optimization.

Execution remains fixed at:

- decision: 08:00 Europe/London;
- entry: 08:01 Europe/London;
- exit: 12:00 Europe/London;
- size: one ounce for research comparability;
- spread: observed XAUUSD entry and exit spread;
- slippage: $0.05 per ounce per side; and
- commission: $7.00 per lot round turn.

The matched controls are always-long and always-short on exactly the same
directional cases, using the same costs. The better of those two controls is
the comparison benchmark.

## Why this candidate is on the shortlist

Milestone 4 found internal development stability for the unchanged candidate
over the 2022, 2023, and 2024 forward folds:

| Development measurement | Result |
|---|---:|
| Directional cases | 693 |
| Mean net return | +3.81 bps per case |
| Profit factor | 1.41 |
| Weekly-bootstrap 95% interval | +1.97 to +5.73 bps |
| Mean return at 1.5× costs | Positive |
| Better matched control | Beaten |

This evidence only justified freezing the candidate. It remains development
evidence because 2021–2024 had already been observed. It is not independent
validation and is not yet evidence of a deployable trading edge.

New York has no frozen candidate because Milestone 3 produced zero eligible
new discovery leads and the V2 contract does not permit inventing or
transferring a London rule into New York.

## Calendar-2025 source readiness

The XAUUSD execution source is ready:

- provider: IC Markets MT5;
- one-minute rows: 354,160;
- London timestamp-complete cases: 257 of 261 weekdays;
- timestamp coverage: 98.4674%;
- observed spread present on every row;
- synthetic rows: zero.

The required ZN feature source is not ready:

- expected provider: licensed Databento `GLBX.MDP3`;
- expected symbol: `ZN.v.0`;
- expected schema: one-minute OHLCV;
- existing sealed archive ends in calendar 2024 and explicitly records
  `2025 not loaded`.

Pre-open readiness is therefore:

| Gate | Status | Requirement |
|---|---|---|
| R01 | Pass | XAUUSD timestamp coverage at least 95% |
| R02 | Blocked | Licensed calendar-2025 ZN archive present and sealed |
| R03 | Blocked | ZN underlying-contract and roll lineage sealed |
| R04 | Blocked | Timestamp-only ZN case coverage at least 95% |
| R05 | Pending | Clean final metadata-only audit before value access |

The only lawful next data action is to acquire licensed calendar-2025
`ZN.v.0`, normalize it with explicit underlying-contract and roll-boundary
lineage, hash and seal it, and then repeat a metadata-only readiness audit.
Until every readiness gate passes, the holdout must remain unopened. A yield
series, ETF, another Treasury future, or any other proxy cannot replace ZN.

## Frozen one-time pass/reject gates

All twelve gates must pass:

1. zero point-in-time, timestamp, DST, provider, hash, or roll-lineage errors;
2. at least 180 directional London cases;
3. at least 80 positive-to-long and 80 negative-to-short cases;
4. at least 35 ISO-week clusters in each directional state;
5. positive mean net return after frozen costs;
6. profit factor strictly above one;
7. mean return above the better matched always-long/always-short control;
8. positive mean return in both frozen directional mappings;
9. at least 70 cases and positive mean return in each chronological half;
10. positive mean P&L and profit factor above one at 1.5× costs;
11. ISO-week cluster-bootstrap lower 95% mean-return bound above zero; and
12. one-candidate cluster sign-flip Benjamini-Hochberg q-value at or below
    0.10.

The uncertainty procedure is frozen at 5,000 ISO-week cluster-bootstrap
replications and 20,000 cluster sign-flip replications. The seeds will be
derived deterministically from the future Milestone 6 manifest hash and
candidate code.

The holdout may be opened once for the complete shortlist. Any failed gate
produces `REJECT_CALENDAR_2025_HOLDOUT`; a candidate cannot be repaired,
replaced, or retuned after opening.

## Highest-risk assumption

The highest-risk assumption is that the recent four-hour direction of a
correctly roll-normalized ZN continuous futures series retains causal or
reliably persistent information about the subsequent London gold session.

The rule is invalidated if the apparent relationship is instead explained by
development-period selection, shared trend, or a continuous-contract
construction artifact. It is also invalidated by either directional mapping
turning non-positive, failure against the matched controls, chronological-half
failure, cost-stress failure, or cluster-aware statistical failure.

## Integrity and independent validation

Canonical bundle:

`research_artifacts/gold_casebook_discovery_v2_shortlist_v01`

| Artifact | Hash |
|---|---|
| Governing V2 contract manifest | `81e39b469111bb92a46c0d2c70f863cba438b647345104d4b8e8bc1a9e4d8188` |
| Frozen Milestone 5 research manifest | `fd35254501f5ec15c5078c2defeb3953e007a2e4fa7e1ed983fe73a32a0a5b57` |
| Bundle manifest | `774655f1dcfb0ebd95b6ec3e50fd480e2c5d5ea75abd4221dd5e7e79986f22ac` |
| Shortlist document | `25e3f9632fa8b661ad556522836c74474c5e874174a824d727b4fa43cff94686` |
| Semantic validation | `0c38632109ca64ee4ecd88e97a61feac3f877c554707f2a8760d80449751996a` |
| `manifest.json` SHA-256 | `caf6c5147fb35dc428bdbd9b0245ef725bbcd72e6cb98de9740345353a55db95` |
| `shortlist.json` SHA-256 | `6e87e7e9532cb378f2451a4e6a837608c732500941b0390b4e7d9979077da822` |

The independent validator confirmed:

- the sole candidate is the unchanged Milestone 4 passer permitted by the
  contract;
- London and New York remain separated;
- rule, point-in-time lineage, execution, costs, controls, and missing-data
  handling are frozen;
- all five readiness gates and twelve evaluation gates are present;
- the highest-risk assumption and invalidation evidence are explicit;
- the candidate family size is one;
- the ZN blocker and XAUUSD readiness were independently recomputed;
- no prohibited relationship or proxy entered the shortlist; and
- calendar-2025 values and outcomes are absent.

Validation result:

`PASS_SEMANTIC_VALIDATION`

A clean second build produced byte-identical `manifest.json` and
`shortlist.json`.

Quality checks:

- Ruff lint: passed across backend source, tests, and tools;
- Ruff format: all four Milestone 5 code/test files passed;
- backend tests: **166 passed**.

## Contract state after Milestone 5

Milestone 5 stops here.

Milestone 6 has not started and the calendar-2025 holdout remains locked. The
shortlist cannot change. Milestone 6 can proceed only after its explicit
authorization and must first satisfy all five pre-open readiness gates. It
must then apply this one frozen rule once, record an honest pass or rejection,
and stop.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/run_gold_casebook_discovery_v2_shortlist.py `
  --research-manifest /workspace/research_manifests/gold_casebook_discovery_v2_shortlist_v01.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --execution-manifest /workspace/research_manifests/gold_casebook_constant_execution_v01.json `
  --milestone-3-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_relationships_v01 `
  --milestone-4-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_walk_forward_v01 `
  --coverage /workspace/research_artifacts/gold_casebook_discovery_v2_coverage.json `
  --output /workspace/research_artifacts/gold_casebook_discovery_v2_shortlist_repro_v01

docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/validate_gold_casebook_discovery_v2_shortlist.py `
  --bundle /workspace/research_artifacts/gold_casebook_discovery_v2_shortlist_repro_v01 `
  --research-manifest /workspace/research_manifests/gold_casebook_discovery_v2_shortlist_v01.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --execution-manifest /workspace/research_manifests/gold_casebook_constant_execution_v01.json `
  --milestone-3-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_relationships_v01 `
  --milestone-4-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_walk_forward_v01 `
  --coverage /workspace/research_artifacts/gold_casebook_discovery_v2_coverage.json
```
