# Gold Casebook Discovery V2 Milestone 2: Descriptive Outcome Atlas

## Decision

V2 Milestone 2 is complete.

The atlas describes the fixed 08:01-to-12:00 London and New York targets over
2021-08-01 through 2024-12-31. It does not test why a move occurred and does not
claim an edge.

- Calendar 2025 remained locked.
- Calendar 2026 was not accessed.
- London and New York remained separate.
- No macro, structure, positioning, event, session-state, or cross-market
  explanatory feature was loaded.
- No relationship discovery, candidate evaluation, session pairing, MFE/MAE,
  or execution optimization occurred.

## Overall fixed-clock behaviour

| Session | Cases | Up | Down | Neither side net-profitable | Median absolute move | 75th percentile | 90th percentile | Median frozen cost |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| London | 833 | 50.06% | 49.94% | 3.0012% | USD 3.35/oz | USD 6.03/oz | USD 9.38/oz | USD 0.22/oz |
| New York | 826 | 48.9104% | 51.0896% | 1.5738% | USD 5.00/oz | USD 9.10/oz | USD 14.75/oz | USD 0.21/oz |

`Neither side net-profitable` means the four-hour absolute price change did not
clear the frozen spread, slippage, and commission hurdle. It is not a trading
filter.

The observed move cleared that hurdle in 96.9988% of London cases and
98.4262% of New York cases. Direction itself remained nearly balanced,
so this is evidence of opportunity frequency, not directional predictability.

## Absolute move-size distribution

| Session | Below USD 2 | USD 2-5 | USD 5-10 | USD 10-20 | USD 20 or more |
|---|---:|---:|---:|---:|---:|
| London | 31.4526% | 34.8139% | 24.3697% | 8.7635% | 0.6002% |
| New York | 20.0969% | 29.9031% | 27.9661% | 16.9492% | 5.0847% |

## Fixed-direction controls

| Session | Control | Mean net return | Net win rate | Profit factor |
|---|---|---:|---:|---:|
| London | Always Long | -0.9274 bps | 49.0996% | 0.9271 |
| London | Always Short | -1.2927 bps | 47.8992% | 0.8808 |
| New York | Always Long | -1.0375 bps | 48.4262% | 0.9303 |
| New York | Always Short | -1.0384 bps | 50.0000% | 0.9535 |

These controls apply one direction every day. They describe unconditional
drift under the frozen execution and are not candidate strategies.

## Chronological atlas

The machine-readable atlas contains the same frozen summaries in ascending:

- calendar year;
- calendar quarter; and
- calendar month.

These buckets are not ranked or selected. They are descriptive stability
records for the later bounded-discovery milestone.

### Calendar-year summaries

| Session | Year | Cases | Up | Down | Neither side net-profitable | Mean signed move | Median absolute move | 90th-percentile absolute move |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| London | 2021 | 92 | 48.913% | 51.087% | 5.4348% | USD 0.10/oz | USD 2.23/oz | USD 6.54/oz |
| London | 2022 | 249 | 48.1928% | 51.8072% | 2.008% | USD -0.10/oz | USD 3.49/oz | USD 9.42/oz |
| London | 2023 | 241 | 46.888% | 53.112% | 3.7344% | USD -0.24/oz | USD 2.84/oz | USD 7.33/oz |
| London | 2024 | 251 | 55.3785% | 44.6215% | 2.3904% | USD 0.48/oz | USD 4.48/oz | USD 12.10/oz |
| New York | 2021 | 92 | 45.6522% | 54.3478% | 1.087% | USD 0.18/oz | USD 4.27/oz | USD 12.26/oz |
| New York | 2022 | 249 | 48.996% | 51.004% | 1.2048% | USD -0.10/oz | USD 4.19/oz | USD 14.55/oz |
| New York | 2023 | 234 | 47.4359% | 52.5641% | 1.2821% | USD 0.05/oz | USD 5.03/oz | USD 14.05/oz |
| New York | 2024 | 251 | 51.3944% | 48.6056% | 2.3904% | USD -0.16/oz | USD 5.96/oz | USD 16.64/oz |

## Integrity and reproducibility

| Artifact | Hash |
|---|---|
| Pre-result measurement manifest | `549dc7bbd6a3768bc8a5d779670163debb5d5f1485749695cc374ebc144fab2c` |
| Outcome ledger | `ed2d4c85de8bdebe6d3c020710a5af8607034c8d6790202c4606fc3e76fc01f8` |
| Atlas document | `db6d95cf798aaee4bb334a03eac7416c2b8c191dbaa27ed6a4a6afac712619d1` |
| Bundle manifest | `e1493d2734109a07b83da1f60768def696201c9a67df1cd75e3d11bec5a484fc` |
| Independent semantic validation | `d3f569517c8f68c3a0e04fb56921f716b889758d449caa216edbafe4b3a5ac83` |

Independent validation reconstructed all
1659 outcome cases from
3318 frozen long/short
baseline records and reproduced every overall, year, quarter, and month
summary.

## What this milestone establishes

It establishes the size, sign balance, cost hurdle, and chronological
distribution of the target we will later try to explain. It does not establish
which information predicts direction.

## Next contracted step

V2 Milestone 3 is bounded relationship discovery. It remains unauthorized and
was not started.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/run_gold_casebook_discovery_v2_outcome_atlas.py `
  --measurement-manifest /workspace/research_manifests/gold_casebook_discovery_v2_outcome_atlas_v01.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --execution-manifest /workspace/research_manifests/gold_casebook_constant_execution_v01.json `
  --casebook-manifest /workspace/research_artifacts/gold_casebook_v01/manifest.json `
  --coverage /workspace/research_artifacts/gold_casebook_discovery_v2_coverage.json `
  --baseline-root /workspace/research_artifacts/gold_casebook_baseline_v01 `
  --output-root /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_repro_v01

docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/validate_gold_casebook_discovery_v2_outcome_atlas.py `
  --measurement-manifest /workspace/research_manifests/gold_casebook_discovery_v2_outcome_atlas_v01.json `
  --baseline-root /workspace/research_artifacts/gold_casebook_baseline_v01 `
  --atlas-root /workspace/research_artifacts/gold_casebook_discovery_v2_outcome_atlas_repro_v01 `
  --markdown-output /workspace/GOLD_CASEBOOK_DISCOVERY_V2_MILESTONE_2_REPRO.md
```
