# Gold Casebook Discovery V2 — Milestone 4

## Verdict

V2 Milestone 4 is complete.

`LONDON_ZN_4H_POSTHOC_V0_1` received:

**PASS_INTERNAL_WALK_FORWARD_STABILITY**

The unchanged London rule passed every frozen expanding-training and annual
forward-fold gate. It was positive after costs in 2022, 2023, and 2024; both
the positive-ZN-to-long and negative-ZN-to-short mappings remained positive;
every fold beat its better matched always-long or always-short control; and
every fold remained positive at 1.5 times frozen transaction costs.

This is internal development stability only. It is not independent validation,
does not establish a tradable edge, and does not authorize execution research.
Calendar 2025 remains unopened.

## Why no contract amendment was required

Milestone 3 produced zero new discovery leads. None of its q-failed provisional
relationships entered this milestone.

The governing V2 contract separately and explicitly recognizes one inherited
post-hoc candidate:

`LONDON_ZN_4H_POSTHOC_V0_1`

Milestone 4 therefore had one lawful candidate, one session, and no candidate
selection:

- session: London only;
- ZN four-hour change positive: long;
- ZN four-hour change negative: short;
- flat, unknown, unavailable, stale, or roll-crossing input: no bias;
- no threshold;
- no confirmation variable;
- fixed 08:01-to-12:00 London execution; and
- no retuning.

New York was not evaluated. The provisional EURUSD×ZN, ZT, silver, structure,
COT, macro, and session relationships from Milestone 3 were not evaluated.

## Authorization and frozen design

The user's authorization was:

> if everything looks great and no contract negotiation needed lets proceed to
> milestone 4

Before the walk-forward calculation, the complete machine-readable design was
frozen in:

`research_manifests/gold_casebook_discovery_v2_walk_forward_v01.json`

Canonical manifest hash:

`db1a7231e9e66a3de6608998024b9a19b38d21708d32d93defd7faae55e4d138`

The test used three non-overlapping calendar-year forward folds:

| Fold | Expanding training window | Forward test window |
|---|---|---|
| F01 | 2021-08-01 through 2021-12-31 | Calendar 2022 |
| F02 | 2021-08-01 through 2022-12-31 | Calendar 2023 |
| F03 | 2021-08-01 through 2023-12-31 | Calendar 2024 |

The rule has no fitted parameter. The expanding training windows measure
whether its evidence and directional mapping remained eligible at each
boundary; they do not refit or select the rule.

## Frozen gates

Every training boundary had to satisfy:

- at least 75 directional cases;
- at least 30 cases in each directional state;
- at least 15 ISO-week clusters per directional state;
- positive mean net return;
- profit factor above one;
- performance above the better matched unconditional control; and
- positive mean returns in both directional states.

Every forward test fold had to satisfy:

- at least 180 directional cases;
- at least 80 cases in each directional state;
- at least 35 ISO-week clusters per directional state;
- positive mean net return after frozen costs;
- profit factor above one;
- performance above the better matched unconditional control;
- positive positive-ZN-to-long and negative-ZN-to-short cells; and
- positive mean P&L at 1.5 times frozen costs.

The final verdict additionally required:

- all three training boundaries to pass;
- all three forward test folds to pass;
- the combined 2022-2024 ISO-week bootstrap lower 95% mean-return bound to be
  above zero; and
- the one-candidate cluster sign-flip BH q-value to be at most 0.10.

All gates were frozen before these results were calculated.

## Forward-fold results

| Test fold | Cases | Win rate | Mean net P&L per ounce | Mean net return | Profit factor | Weekly-bootstrap 95% interval | Better-control excess | Mean P&L at 1.5× costs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2022 | 236 | 52.12% | +$0.510 | +2.98 bps | 1.26 | -0.75 to +6.67 bps | +3.61 bps | +$0.404/oz |
| 2023 | 225 | 55.56% | +$0.625 | +3.26 bps | 1.41 | +0.72 to +5.75 bps | +4.03 bps | +$0.514/oz |
| 2024 | 232 | 57.76% | +$1.202 | +5.19 bps | 1.56 | +1.82 to +8.44 bps | +4.09 bps | +$1.087/oz |

Every test fold passed its predeclared gates.

The 2022 weekly-bootstrap interval crossed zero. This is reported explicitly.
Per-fold statistical significance was diagnostic rather than a frozen fold
gate; the predeclared stability requirement was positive economic performance,
mapping consistency, matched-control outperformance, support, and cost stress
in every fold, followed by positive aggregate cluster-aware evidence.

## Expanding-training results

| Boundary | Directional cases | Mean net return | Profit factor | Weekly-bootstrap 95% interval | Both mappings positive | Gates |
|---|---:|---:|---:|---:|---|---|
| Before 2022 | 84 | +4.22 bps | 1.66 | +1.36 to +7.12 bps | Yes | Pass |
| Before 2023 | 320 | +3.30 bps | 1.33 | +0.47 to +6.10 bps | Yes | Pass |
| Before 2024 | 545 | +3.28 bps | 1.36 | +1.29 to +5.31 bps | Yes | Pass |

The candidate retained its original sign mapping at every expanding boundary.

## Combined forward evidence

The combined forward-fold interval contains calendar 2022 through 2024 once
each. The partial 2021 warm-up period is excluded.

| Measurement | Result |
|---|---:|
| Directional cases | 693 |
| Long decisions | 347 |
| Short decisions | 346 |
| Net win rate | 55.12% |
| Mean net P&L per ounce | +$0.779 |
| Mean net return | +3.81 bps |
| Profit factor | 1.41 |
| Weekly-bootstrap 95% mean interval | +1.97 to +5.73 bps |
| Cluster sign-flip p-value | 0.00005 |
| One-candidate BH q-value | 0.00005 |
| Mean P&L at 1.5× costs | +$0.668/oz |
| Profit factor at 1.5× costs | 1.35 |

Directional mapping:

| ZN four-hour state | Frozen decision | Cases | Mean net return |
|---|---|---:|---:|
| Positive | Long | 347 | +4.19 bps |
| Negative | Short | 346 | +3.43 bps |

Matched controls on the same 693 directional cases:

| Control | Mean net return | Profit factor |
|---|---:|---:|
| Always long | -0.71 bps | 0.94 |
| Always short | -1.49 bps | 0.87 |

The frozen selector exceeded the better matched control by +4.52 basis points
per case.

The accumulated +$539.75 figure in the raw artifact is the arithmetic sum of
693 separate one-ounce research outcomes. It is not a $10,000-account return,
does not include account-risk sizing, and must not be scaled into a performance
claim. Risk-based execution is outside this milestone.

## Why this does not contradict Milestone 3

Milestone 3 asked whether any state in a 520-test, session-separated discovery
family qualified as a **new** relationship after multiplicity correction. None
did. The known London ZN rows were also explicitly barred from new-discovery
credit because their post-hoc origin was already known.

Milestone 4 asked a different and narrower question:

> Does the one candidate already named in the V2 contract retain its unchanged
> mapping and positive economics through expanding development boundaries and
> three annual forward folds?

The answer is yes. The one-candidate q-value does not erase its post-hoc origin
or transform these development folds into independent validation.

## Integrity and reproduction

Canonical bundle:

`research_artifacts/gold_casebook_discovery_v2_walk_forward_v01`

| Artifact | Hash |
|---|---|
| Frozen M4 research manifest | `db1a7231e9e66a3de6608998024b9a19b38d21708d32d93defd7faae55e4d138` |
| Bundle manifest | `8609875313770bbcb947d1e785633471c1a706ee775abf132b87cd49529ba7b5` |
| Results document | `057a53e8fb992c2a947f826b7af7dc8fd18a9bb8147fccd370af1a035b2725a0` |
| Semantic validation | `5fba52ab9e2dfbbf2c0a111b815f45fab74b12955f78e9b3b82d3525ae6fd991` |
| Decision ledger SHA-256 | `e859b1139b916e5ba94e464992859ef5039aab33a930059a7a07f14b3d7c0cc4` |
| Results file SHA-256 | `e6e2c918fd99e767d4644e3367264af383f2304efb1fc35a55bd61b2ebf6e559` |

The independent validator reconstructed:

- all 833 London decisions;
- all feature/outcome joins and cost identities;
- every expanding training boundary;
- all three non-overlapping forward folds;
- all matched controls;
- every state, fold, and aggregate metric;
- every bootstrap interval and cluster sign-flip p-value;
- the one-candidate BH q-value; and
- every frozen gate and the final verdict.

Validation result:

`PASS_SEMANTIC_VALIDATION`

A second clean run produced byte-identical decision ledger, result document,
and bundle manifest.

Quality checks:

- Ruff lint: passed across backend source, tests, and tools;
- Ruff format: all four new Milestone 4 code/test files passed;
- backend tests: **164 passed**.

## Contract state after Milestone 4

Milestone 4 stops here.

The London ZN candidate is eligible for consideration in Milestone 5's frozen
shortlist. New York has zero candidates. No Milestone 3 q-failed relationship
is eligible.

Milestone 5 must explicitly freeze:

- whether the London candidate occupies a shortlist slot;
- its unchanged rule and point-in-time lineage;
- fixed execution and costs;
- missing and roll-crossing input handling;
- the highest-risk assumption and invalidation evidence;
- exact calendar-2025 pass/reject gates; and
- candidate-specific 2025 input-readiness requirements.

Milestone 5 was not started. Calendar 2025 values and outcomes remain locked.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/run_gold_casebook_discovery_v2_walk_forward.py `
  --research-manifest /workspace/research_manifests/gold_casebook_discovery_v2_walk_forward_v01.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --milestone-3-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_relationships_v01 `
  --outcome-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_v01 `
  --output /workspace/research_artifacts/gold_casebook_discovery_v2_walk_forward_repro_v01

docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/validate_gold_casebook_discovery_v2_walk_forward.py `
  --bundle /workspace/research_artifacts/gold_casebook_discovery_v2_walk_forward_repro_v01 `
  --research-manifest /workspace/research_manifests/gold_casebook_discovery_v2_walk_forward_v01.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --milestone-3-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_relationships_v01 `
  --outcome-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_v01
```
