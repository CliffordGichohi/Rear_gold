# Gold Casebook Milestone 3 — Constant-Execution Baseline

## Status

Milestone 3 is complete. It calculated only the controls required by
`GOLD_CASEBOOK_RESEARCH_CONTRACT.md`:

- London always long;
- London always short;
- London deterministic random direction;
- New York always long;
- New York always short; and
- New York deterministic random direction.

No fundamental, positioning, cross-market, session-state, or market-structure
variable selected a direction in this milestone. No entry, exit, stop, target,
reward-to-risk, leverage, or account-size parameter was searched. Calendar 2025
remained locked.

## Frozen inputs

The execution definition was frozen before the first result in
`research_manifests/gold_casebook_constant_execution_v01.json`.

| Evidence | SHA-256 / document hash |
|---|---|
| Execution manifest | `724a4fef0fa4b526b4d30b9743c2dfa013c53f87b19262a36b05f3fd07c87d76` |
| Immutable casebook manifest | `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f` |
| Immutable session artifact | `2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a` |
| Immutable price artifact | `0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e` |

The fixed execution was:

- decision at 08:00 in the session's IANA timezone;
- entry at the next one-minute bar's 08:01 open;
- exit at the one-minute bar closing at 12:00 local time;
- a fixed one-ounce XAUUSD position, equivalent to 0.01 of a 100-ounce lot;
- half the observed entry spread and half the observed exit spread paid
  adversely;
- USD 0.05/oz slippage per side;
- USD 7 per 100-ounce lot round-turn commission, or USD 0.07 for one ounce;
- no stop, target, early exit, financing, leverage, or account scaling; and
- exclusion rather than imputation for a missing bar or spread.

The random control is order-independent: SHA-256 is applied to the frozen
namespace and immutable case ID, with the first digest byte selecting direction.

## Coverage and integrity

The calculation covers 2 August 2021 through 31 December 2024:

| Session | Input cases | Eligible cases | Excluded |
|---|---:|---:|---:|
| London | 833 | 833 | 0 |
| New York | 826 | 826 | 0 |
| Total | 1,659 | 1,659 | 0 |

The output contains 4,977 trade records. Independent semantic validation
rechecked:

- 4,977 unique trade record hashes;
- all 1,659 immutable case joins;
- 3,318 exact immutable one-minute entry/exit-bar joins;
- session-local clocks and daylight-saving transitions;
- long, short, and seeded-random direction assignment;
- spread, slippage, commission, gross/net, and return identities;
- identical eligible cases across all three controls; and
- every reported aggregate from the trade ledger.

An ephemeral clean rerun produced the same bundle manifest hash and result hash.
The complete backend regression suite passed `116` tests, and Ruff reported no
issues in the baseline engine, runner, validator, or unit tests.

## Results

All amounts below are USD for the fixed one-ounce position. `Mean net bps` is
relative to entry notional; it is not an account return.

| Session | Control | N | Net win % | Mean gross USD | Mean net USD | Mean net bps (95% CI) | Profit factor | Total net USD |
|---|---|---:|---:|---:|---:|---|---:|---:|
| London | Always long | 833 | 49.10 | +0.0558 | -0.1651 | -0.9274 (-2.8467, +0.9920) | 0.9271 | -137.53 |
| London | Always short | 833 | 47.90 | -0.0558 | -0.2768 | -1.2927 (-3.2120, +0.6267) | 0.8808 | -230.55 |
| London | Deterministic random | 833 | 49.10 | -0.3024 | -0.5233 | -2.2554 (-4.1722, -0.3385) | 0.7858 | -435.93 |
| New York | Always long | 826 | 48.43 | -0.0428 | -0.2502 | -1.0375 (-4.2706, +2.1957) | 0.9303 | -206.63 |
| New York | Always short | 826 | 50.00 | +0.0428 | -0.1645 | -1.0384 (-4.2714, +2.1945) | 0.9535 | -135.91 |
| New York | Deterministic random | 826 | 47.58 | -0.3890 | -0.5964 | -2.7735 (-6.0039, +0.4570) | 0.8414 | -492.59 |

The average fixed cost was approximately USD 0.2209/oz per London case and USD
0.2073/oz per New York case. London had a very small unconditional gross long
drift; New York had a very small unconditional gross short drift. Both were
smaller than costs and their net-return confidence intervals include zero.
Neither unconditional direction is an edge.

The seeded-random controls are negative observations from one frozen,
deterministic allocation. Their losses are controls, not a tradable short signal
and not evidence that reversing the random allocation is an edge.

Year results change sign—for example, London always long was net negative in
2021–2023 and positive in 2024. This instability reinforces that an
unconditional session direction must remain a hurdle, not a strategy.

## Artifacts

| Artifact | Purpose | Hash |
|---|---|---|
| `research_artifacts/gold_casebook_baseline_v01/manifest.json` | Content-addressed bundle manifest | `dff92e13105b0b6fd6c9a71a5d9f7668384361d37475fac5fc8b2a33521ea032` |
| `research_artifacts/gold_casebook_baseline_v01/results.json` | Machine-readable eligibility, execution, and six result sets | `61624c9bcbf5ef25894c61cd02add0e0d56c2b9ffc9d3f26c54e5ea97a01ab6e` |
| `research_artifacts/gold_casebook_baseline_v01/trades.jsonl.gz` | Immutable 4,977-record evidence ledger | SHA-256 recorded in the bundle manifest |
| `research_artifacts/gold_casebook_baseline_v01/semantic_validation.json` | Independent source-join and arithmetic validation | `0f56004ea5f486f1d7bd9efc04510c05cecc2283c6fb2a0b7e454b93ee9dbdeb` |
| `backend/tools/run_gold_casebook_baseline.py` | Deterministic runner | Source-controlled implementation |
| `backend/tools/validate_gold_casebook_baseline.py` | Independent semantic validator | Source-controlled implementation |
| `backend/tests/unit/test_casebook_baseline.py` | Fill, cost, clock, random, and metric unit tests | Source-controlled test evidence |

The reproducible project-root commands are:

```powershell
docker compose --profile test run --rm `
  --volume "${PWD}:/workspace" `
  --workdir /workspace/backend `
  --env PYTHONPATH=/workspace/backend/src `
  backend-test python tools/run_gold_casebook_baseline.py `
  --casebook-bundle /workspace/research_artifacts/gold_casebook_v01 `
  --execution-manifest /workspace/research_manifests/gold_casebook_constant_execution_v01.json `
  --output /workspace/research_artifacts/gold_casebook_baseline_v01

docker compose --profile test run --rm `
  --volume "${PWD}:/workspace" `
  --workdir /workspace/backend `
  --env PYTHONPATH=/workspace/backend/src `
  backend-test python tools/validate_gold_casebook_baseline.py `
  --bundle /workspace/research_artifacts/gold_casebook_baseline_v01 `
  --casebook-bundle /workspace/research_artifacts/gold_casebook_v01 `
  --execution-manifest /workspace/research_manifests/gold_casebook_constant_execution_v01.json
```

The runner refuses to overwrite an existing bundle, and the validator refuses
to overwrite existing validation evidence.

## Contract conclusion

Milestone 3 establishes the fixed-execution hurdle. It does not test whether
fundamentals or market structure can select direction, so it cannot accept or
reject the planned information edge.

The next contracted step is Milestone 4, relationship discovery: rank
point-in-time variables and a bounded set of transparent interactions by
conditional direction, net return, support, stability, and uncertainty using
development data only. Milestone 4 has not started.
