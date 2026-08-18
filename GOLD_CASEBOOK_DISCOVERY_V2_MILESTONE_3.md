# Gold Casebook Discovery V2 — Milestone 3

## Verdict

V2 Milestone 3 is complete.

The bounded 2021-2024 relationship screen found several economically
interesting development relationships, concentrated in intraday Treasury and
currency direction. It found **zero new discovery leads** under the gates
frozen before the screen was run.

This is not evidence that gold has no conditional behaviour. It means that no
new relationship in this 88-feature, 17-interaction screen was strong enough to
survive all of:

- fixed spread, slippage, and commission;
- support and calendar-stability requirements;
- long-versus-short selection adjustment;
- ISO-week cluster-bootstrap uncertainty;
- correction for all support-eligible tests within its session; and
- the known-hypothesis exclusions.

No edge is declared. Calendar 2025 remains unopened.

## Authorization and frozen design

The user's Milestone 3 authorization was:

> If everything looks great, lets move to milestone 3, or there is contract
> renegotiation you need?

No contract amendment was needed. Before any new feature/outcome relationship
was calculated, the exact design was frozen in:

`research_manifests/gold_casebook_discovery_v2_relationship_discovery_v01.json`

Canonical manifest hash:

`9e86a05f32c7f5c52b8e3c57b704531fa34a75586b3af3807e5b68ab119718ab`

The screen reused, without additions or retuning, the previously declared:

- 88 point-in-time features;
- 17 explicit two-condition interactions;
- five transparent transform types; and
- feature-design fingerprint
  `bee30eaf3e27cb0b03ac8d1be938ca8b63a443a93953b48b66b0d6aeac3fe695`.

London and New York were evaluated as independent research units. The outcome
was the frozen 08:01-to-12:00 local-session return after observed spread,
frozen slippage, and frozen commission. No stop, target, entry timing, leverage,
account size, MFE, MAE, or requested return target entered the screen.

## Frozen gates

| Gate | Frozen value |
|---|---:|
| Individual-state minimum cases | 80 |
| Interaction-state minimum cases | 60 |
| Maximum state prevalence | 80% |
| Minimum ISO-week clusters | 30 |
| Years with at least 10 cases | 3 of 4 |
| COT reports for positioning relationships | 18 |
| Positive calendar years for a lead | At least 3 |
| Positive chronological halves | Both |
| Cluster bootstrap | 2,000 ISO-week resamples |
| Bootstrap lead gate | Lower 95% bound above zero |
| Multiplicity | Benjamini-Hochberg within session |
| Maximum reported q-value for a lead | 0.10 |
| Maximum conditions | 2 |

The exact single-variable ZN four-hour states were calculated for honest
context but were prohibited from receiving new-discovery credit:

- London: `KNOWN_POSTHOC`;
- New York: `PRIOR_REJECTED_RULE_COMPONENT`.

## Screen coverage

| Measurement | London | New York | Total |
|---|---:|---:|---:|
| Development cases | 833 | 826 | 1,659 |
| Evaluated relationship states | 420 | 478 | 898 |
| Support-eligible states | 244 | 276 | 520 |
| Stable positive-after-cost states | 38 | 61 | 99 |
| Bootstrap lower bound above zero | 11 | 5 | 16 |
| BH q-value at or below 0.10 | 0 | 0 | 0 |
| New discovery leads | 0 | 0 | 0 |

Nine London states and four New York states passed every lead gate except the
predeclared multiple-testing gate. They are provisional development evidence,
not validated candidates.

## Strongest London development relationships

| Rank | Frozen state | Direction | Cases | Win rate | Mean net return | Profit factor | Weekly-bootstrap 95% interval | BH q |
|---:|---|---|---:|---:|---:|---:|---:|---:|
| 1 | EURUSD 4h positive AND ZN 4h positive | Long | 192 | 59.38% | +6.09 bps | 1.85 | +2.74 to +9.30 bps | 0.304 |
| 2 | ZN 4h positive | Long | 389 | 57.07% | +4.26 bps | 1.47 | +1.53 to +6.86 bps | 0.394 |
| 3 | EURUSD 4h positive AND ZN 4h negative | Short | 210 | 56.67% | +5.03 bps | 1.62 | +2.00 to +8.12 bps | 0.661 |
| 4 | ZN 4h negative | Short | 388 | 54.90% | +3.45 bps | 1.39 | +1.40 to +5.62 bps | 0.873 |
| 5 | ZN 1h positive | Long | 390 | 53.59% | +3.14 bps | 1.36 | +0.48 to +5.68 bps | 1.000 |

The rank-one London state was positive in every calendar year:

| Year | Cases | Mean net return |
|---:|---:|---:|
| 2021 partial year | 20 | +6.42 bps |
| 2022 | 62 | +5.37 bps |
| 2023 | 53 | +3.54 bps |
| 2024 | 57 | +9.11 bps |

It was also positive in both chronological halves: +5.29 and +6.95 bps. Its
selection-adjusted raw p-value was 0.00125, but the corrected q-value was 0.304
across the complete London test family. It therefore failed the frozen lead
gate.

The two exact ZN four-hour rows are not new discoveries even apart from their
q-values. They are the already-known London post-hoc relationship and remain
governed as `LONDON_ZN_4H_POSTHOC_V0_1`.

## Strongest New York development relationships

| Rank | Frozen state | Direction | Cases | Win rate | Mean net return | Profit factor | Weekly-bootstrap 95% interval | BH q |
|---:|---|---|---:|---:|---:|---:|---:|
| 1 | EURUSD 4h negative AND ZN 4h negative | Short | 200 | 56.50% | +7.54 bps | 1.55 | +1.48 to +13.48 bps | 1.000 |
| 2 | Silver 4h positive AND gold 4h negative | Long | 80 | 56.25% | +9.10 bps | 1.78 | +1.14 to +17.72 bps | 1.000 |
| 3 | ZT 4h negative | Short | 410 | 55.12% | +5.20 bps | 1.39 | +1.09 to +9.50 bps | 1.000 |
| 4 | ZN 4h negative | Short | 417 | 53.72% | +4.62 bps | 1.33 | +0.68 to +8.78 bps | 1.000 |
| 5 | EURUSD 4h negative AND ZN 4h positive | Long | 184 | 56.52% | +8.10 bps | 1.55 | +0.62 to +15.71 bps | 1.000 |

The rank-one New York state was positive in all four development years:

| Year | Cases | Mean net return |
|---:|---:|---:|
| 2021 partial year | 19 | +2.15 bps |
| 2022 | 59 | +8.63 bps |
| 2023 | 63 | +11.78 bps |
| 2024 | 59 | +3.64 bps |

It was positive in both chronological halves: +10.33 and +4.95 bps. Its
selection-adjusted raw p-value was 0.02276 and its BH q-value was 1.000. It is
not a discovery lead.

The New York ZN four-hour row is also ineligible for new-discovery credit
because it was a component of the previously rejected universal rule.

## What the broader casebook contributed

All frozen domain families were evaluated. The best support-eligible
single-variable state in each family was:

| Family | London best state | Result | New York best state | Result |
|---|---|---|---|---|
| Fundamental engine | Positioning-flow component bullish → long | +1.45 bps; interval crosses zero | Macro confidence low → short | +3.02 bps; interval crosses zero |
| Fundamental series changes | Daily volatility change negative → long | +0.75 bps; unstable | Financial-stress change negative → long | +1.69 bps; interval crosses zero |
| COT positioning | COT net change positive → long | +0.59 bps; unstable | COT percentile low → long | +2.82 bps; interval crosses zero |
| Market structure | 15m trend bullish → long | +2.26 bps; interval crosses zero | 5m trend bullish → short | +4.99 bps; interval crosses zero |
| Session/liquidity | Prior same-session return negative → long | +0.42 bps; unstable | Pre-NY London range high → short | +3.79 bps; interval crosses zero |
| Intraday cross-market | ZN 4h positive → long | Known post-hoc; not a new lead | ZT 4h negative → short | +5.20 bps; q = 1.00 |

The aggregate macro, fundamental-series, COT, structure, and session fields did
not independently clear the uncertainty and multiplicity gates in this fixed
four-hour outcome. Their failure does not prove they are useless. It says the
current recorded representations did not isolate a robust directional edge
when screened as declared.

The most coherent development pattern is:

1. the sign of recent Treasury-price movement carried most of the directional
   information;
2. a session-specific EURUSD context strengthened that relationship in the
   development data; and
3. the apparent strength was not sufficient to survive the full search budget.

This is a hypothesis for internal stability work, not permission to trade or
to relax the q-value after seeing it.

## Integrity and reproduction

Canonical bundle:

`research_artifacts/gold_casebook_discovery_v2_relationships_v01`

| Artifact | Hash |
|---|---|
| M3 research manifest | `9e86a05f32c7f5c52b8e3c57b704531fa34a75586b3af3807e5b68ab119718ab` |
| Bundle manifest | `0ffc6d7b5f243d21490b23fa5af649cc94b921bd8223f188b5e81004427591b2` |
| Rankings document | `10f79db594a00e36e747e679d5a6306581d165fe4e00579927ab6b3bde08399d` |
| Semantic validation | `3de9f676d875217a86164c8234dcdaea9c3bc8dce27dfe19e7fdd1c58cd51e44` |
| Feature ledger SHA-256 | `bc11401075c160dad03c967146644b18576e43d29c4b8c0604db16993d41896c` |
| Relationship ledger SHA-256 | `b5634b806905d295c4837819c03a8932c0b5fc6f9eb8892d840c2414313880f2` |

The independent validator reconstructed all 1,659 feature cases, all 25
session-specific tertile threshold sets, all 898 relationship states, all
weekly bootstrap intervals, support gates, p-values, BH q-values, known-rule
exclusions, lead flags, and rankings.

A second clean run produced byte-identical:

- `development_features.jsonl.gz`;
- `relationships.jsonl.gz`;
- `rankings.json`; and
- `manifest.json`.

The semantic-validation result is `PASS_SEMANTIC_VALIDATION`. The full backend
test suite passed: **160 tests**. Ruff lint passed across `backend/src`,
`backend/tests`, and `backend/tools`. The new Milestone 3 source and test files
also pass Ruff's format check.

The repository-wide format check remains red on 78 pre-existing files outside
this milestone. They were not mechanically rewritten because the worktree
contains unrelated user changes; this does not affect the passing lint, tests,
artifact reconstruction, or byte-for-byte reproduction reported above.

## Contract state after Milestone 3

Milestone 4 was not run and is not authorized by this report.

Under the frozen Milestone 3 lead policy, no new relationship advances as a
discovery lead. The separately recognized
`LONDON_ZN_4H_POSTHOC_V0_1` remains exactly where the V2 contract placed it:
an inherited post-hoc London candidate with no independent validation credit.
Milestone 3 neither validates nor erases it.

The q-value threshold, feature set, interactions, and rankings must not now be
relaxed or changed to rescue the provisional relationships. Calendar 2025
remains the one-time locked holdout.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/run_gold_casebook_discovery_v2_relationships.py `
  --research-manifest /workspace/research_manifests/gold_casebook_discovery_v2_relationship_discovery_v01.json `
  --feature-design-manifest /workspace/research_manifests/gold_casebook_relationship_discovery_v01.json `
  --casebook-bundle /workspace/research_artifacts/gold_casebook_v01 `
  --outcome-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_v01 `
  --output /workspace/research_artifacts/gold_casebook_discovery_v2_relationships_repro_v01

docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/validate_gold_casebook_discovery_v2_relationships.py `
  --bundle /workspace/research_artifacts/gold_casebook_discovery_v2_relationships_repro_v01 `
  --research-manifest /workspace/research_manifests/gold_casebook_discovery_v2_relationship_discovery_v01.json `
  --feature-design-manifest /workspace/research_manifests/gold_casebook_relationship_discovery_v01.json `
  --casebook-bundle /workspace/research_artifacts/gold_casebook_v01 `
  --outcome-bundle /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_v01
```
