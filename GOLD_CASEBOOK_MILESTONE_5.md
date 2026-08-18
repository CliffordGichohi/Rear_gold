# Gold Casebook Milestone 5: Frozen Case Specification

## Status

Milestone 5, **Case specification**, is complete.

The user authorized one narrow contract amendment before any combined-selector
result was calculated. The resulting manifest was frozen at:

`research_manifests/gold_casebook_case_specification_v01.json`

Canonical manifest hash:

`a4696482f0db166fab9dd36a6d6742fb5589a1e5f2b6beeb705747a3d059c8de`

The candidate remains **exploratory and is not a validated edge**. Conditional
2024 features and outcomes were not deserialized. Calendar 2025 remained
locked. No entry, exit, stop, target, reward-to-risk, leverage, or position-size
research occurred.

## Frozen selector

Selector code: `UNIVERSAL_ZN_4H_SIGN_V0_1`

The same rule applies at the frozen 08:00 local London and New York decision
clocks:

| Four-hour ZN futures-price state | Gold bias |
|---|---|
| `POSITIVE` | `LONG` |
| `NEGATIVE` | `SHORT` |
| `FLAT` | `NO_BIAS` |
| `UNKNOWN` | `NO_BIAS` |

ZN is the continuous CME 10-year Treasury-note futures-price proxy. It is not
relabelled as an observed nominal or real yield. A positive futures-price move
is interpreted as downward nominal-yield pressure and a bullish gold bias; a
negative futures-price move is interpreted as upward nominal-yield pressure
and a bearish gold bias. That conclusion is `INFERRED`; the source price is
`OBSERVED` and its four-hour change is `CALCULATED`.

There is no non-zero movement threshold. A non-ready, stale, unavailable,
non-finite, missing-source, or continuous-contract-roll comparison becomes
`NO_BIAS`. It cannot fall back to ZT. ZT/ZN confirmation, session-specific proxy
selection, other horizons, and all additional macro, positioning, event,
session, liquidity, and structure gates are prohibited for this frozen case.

Execution remains the unchanged Milestone 3 contract:

- decision at 08:00 local;
- entry at the next one-minute bar, 08:01 local;
- exit at 12:00 local;
- one ounce;
- observed entry and exit spreads;
- USD 0.05 per ounce slippage on each side; and
- USD 7 per 100-ounce lot round-turn commission.

## Development-only result

The selector was applied once after freezing to 1,157 development cases from
1 August 2021 through 31 December 2023. It selected 1,101 directional cases:
545 long, 556 short, and 56 no-bias.

| Scope | Cases traded | Mean net return | Mean net P&L | Net win rate | Profit factor | ISO-week bootstrap 95% interval | Total net P&L |
|---|---:|---:|---:|---:|---:|---:|---:|
| London | 545 | +3.2842 bps | +USD 0.5927/oz | 55.23% | 1.3584 | +1.3336 to +5.1999 bps | +USD 322.995/oz |
| New York | 556 | +6.0757 bps | +USD 1.1401/oz | 54.32% | 1.4379 | +1.9457 to +10.2987 bps | +USD 633.905/oz |
| Combined | 1,101 | +4.6939 bps | +USD 0.8691/oz | 54.77% | 1.4074 | Reported by session | +USD 956.900/oz |

These are fixed one-ounce research results, not returns on a USD 10,000 account
and not a position-sizing recommendation.

The frozen direction mapping remained positive in all four development cells:

| Session | State and bias | Cases | Mean net return |
|---|---|---:|---:|
| London | ZN positive, long gold | 276 | +2.9392 bps |
| London | ZN negative, short gold | 269 | +3.6381 bps |
| New York | ZN positive, long gold | 269 | +5.9050 bps |
| New York | ZN negative, short gold | 287 | +6.2357 bps |

Both chronological development halves were positive:

| Session | Early half | Late half |
|---|---:|---:|
| London | +1.9850 bps | +4.5786 bps |
| New York | +4.7401 bps | +7.4404 bps |

The combined selector was also positive in each development year:

| Year | Cases | Mean net return | Profit factor |
|---|---:|---:|---:|
| 2021 partial | 172 | +7.0069 bps | 1.7545 |
| 2022 | 482 | +3.7445 bps | 1.2821 |
| 2023 | 447 | +4.8276 bps | 1.4561 |

For London, the better unconditional development control was always short at
-0.5777 bps; the selector exceeded it by +3.8619 bps. For New York, the better
control was always long at -0.9109 bps; the selector exceeded it by +6.9866
bps.

## What the result means

This is stronger than the separate descriptive states because one complete,
universal long/short/no-bias selector now remains positive after the frozen
costs across:

- both sessions;
- both sign directions;
- all three development-year buckets;
- both chronological development halves; and
- week-cluster bootstrap intervals whose lower bounds are above zero for each
  session.

It still does not prove an edge. The candidate originated from development
research in which no state passed the predeclared false-discovery correction.
The selector may therefore be a development-period coincidence. Its next
evidence must come from data that could not change the rule.

## Integrity and reproducibility

The content-addressed bundle is:

`research_artifacts/gold_casebook_case_specification_v01/`

| Artifact | Hash |
|---|---|
| Bundle manifest | `fb913282121ba527a002a499b3c68b1d175d78a9f1b91e10df2fc24133a4cdfd` |
| Development decisions payload | `1c86a2b3d576812ae2040a977774c7e184444e7ffde4f1c1c4d01269d768a6ad` |
| Development results document | `4194c2a8399c462c94720c040feb426355d375fcf38dd311e8efd4d315a361c9` |
| Development results file | `d9ec624053b9a8386b9417f5276843fa3ae0eabc46985afb02caf2f3a16a5d82` |
| Independent semantic validation | `ff97ea0f416daa59a3419c64b0dce372e2b04a1b1f62e2506fde2347026afd0f` |

Independent validation reconstructed:

- all 1,157 decisions from immutable feature records;
- all 1,101 directional outcomes from immutable fixed-execution trades;
- both session metrics, both direction cells, controls, years, halves, and
  week-cluster bootstrap intervals;
- exact record and artifact hashes;
- universal mapping with no threshold or fallback; and
- absence of conditional 2024 deserialization, 2025 access, and execution
  optimization.

The baseline payload contained 1,506 calendar-2024 control rows. The runner and
validator skipped those rows before JSON deserialization. A clean ephemeral
rerun reproduced the bundle manifest and both artifact hashes exactly.

Verification completed with:

- 135 backend tests passing; and
- focused Ruff checks passing.

## Next contracted step

The current incomplete milestone is Milestone 6, **Chronological validation**.

Milestone 6 may now open calendar 2024 once and apply this exact selector and
the unchanged execution contract. The pass/reject gates were frozen in the
Milestone 5 manifest before 2024 conditional results were inspected. Every
gate must pass; failure rejects the candidate and does not authorize retuning.
Calendar 2025 remains locked for Milestone 7.
