# Gold Casebook Milestone 6: Chronological Validation

## Verdict

Milestone 6, **Chronological validation**, is complete.

`UNIVERSAL_ZN_4H_SIGN_V0_1` received the frozen verdict:

**`REJECT_CHRONOLOGICAL_VALIDATION`**

Eight of ten predeclared gates passed. Two failed:

- `G08_DIRECTION_MAPPING_CONSISTENCY`; and
- `G09_CHRONOLOGICAL_HALF_STABILITY`.

The candidate is therefore rejected as a universal London-and-New-York
directional edge. This verdict was produced without changing its variable,
horizon, threshold, sessions, execution, costs, or pass criteria.

Calendar 2025 remained locked. No execution optimization occurred.

## Pre-result freeze

Before any conditional 2024 feature or outcome was loaded, the operational
validation definition was frozen in:

`research_manifests/gold_casebook_chronological_validation_v01.json`

Canonical validation-manifest hash:

`4e070218bfe2be8d0113762bbc42d944e39fccf8916f9f7286a998c05e170269`

It froze:

- the exact immutable session, cross-market, and baseline sources;
- the unchanged positive-to-long, negative-to-short, flat/unknown-to-no-bias
  mapping;
- an equal-count chronological split assigned before removing no-bias cases;
- same-period always-long and always-short controls;
- ISO-week support and bootstrap definitions;
- 1.0x frozen execution costs;
- the exact 1.5x cost-stress formula; and
- ten all-or-nothing gates.

## Calendar-2024 sample

The validation contained 502 session cases:

| Session | Total cases | Directional | Long | Short | No bias |
|---|---:|---:|---:|---:|---:|
| London | 251 | 232 | 113 | 119 | 19 |
| New York | 251 | 238 | 108 | 130 | 13 |
| Combined | 502 | 470 | 221 | 249 | 32 |

Support was adequate. Every session-and-direction cell contained more than 100
cases and spanned 47 to 53 ISO-week clusters, well above the frozen minimums.

## Main validation results

| Session | Trades | Mean net return | Mean net P&L | Net win rate | Profit factor | Week-bootstrap 95% interval | Best control | Excess over control |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| London | 232 | +5.1949 bps | +USD 1.2019/oz | 57.76% | 1.5622 | +1.9879 to +8.3745 bps | Always long, +1.0131 bps | +4.1819 bps |
| New York | 238 | +0.4675 bps | +USD 0.2056/oz | 51.26% | 1.0516 | -6.1960 to +6.9376 bps | Always short, -0.5553 bps | +1.0228 bps |
| Combined | 470 | +2.8011 bps | +USD 0.6974/oz | 54.47% | 1.2270 | Reported by session | — | — |

The combined result was positive, but the contract deliberately did not permit
an aggregate profit to hide a failed direction or unstable time segment.

These remain fixed one-ounce research figures. They are not returns on a USD
10,000 account or a position-sizing recommendation.

## Why the candidate failed

### G08: direction mapping consistency

| Session | Frozen state and bias | Cases | Mean net return | Gate |
|---|---|---:|---:|---|
| London | ZN positive, long gold | 113 | +7.4883 bps | Pass |
| London | ZN negative, short gold | 119 | +3.0172 bps | Pass |
| New York | ZN positive, long gold | 108 | **-0.2366 bps** | **Fail** |
| New York | ZN negative, short gold | 130 | +1.0525 bps | Pass |

The bullish New York mapping did not retain a positive mean after frozen costs.
It cannot be deleted or changed to no-bias after seeing this result.

### G09: chronological-half stability

| Session | Early 2024 half | Late 2024 half | Gate |
|---|---:|---:|---|
| London | +8.3860 bps | +1.8344 bps | Pass |
| New York | **-3.4584 bps** | +4.3935 bps | **Fail** |

The New York result changed from negative in the early half to positive in the
late half. That is not the time stability required by the frozen contract.

London validated strongly, but promoting London alone now would be a
session-specific post-result rewrite explicitly prohibited by the manifest.
The universal candidate must be judged as frozen and is rejected.

## Gate ledger

| Gate | Result | Material evidence |
|---|---|---|
| G01 point-in-time integrity | Pass | Zero integrity issues |
| G02 directional session support | Pass | London 232; New York 238 |
| G03 directional state support | Pass | Every cell 108–130 cases |
| G04 ISO-week state support | Pass | Every cell 47–53 weeks |
| G05 session mean positive | Pass | London +5.1949; New York +0.4675 bps |
| G06 session profit factor | Pass | London 1.5622; New York 1.0516 |
| G07 beats best control | Pass | London +4.1819; New York +1.0228 bps excess |
| G08 direction mapping consistency | **Fail** | New York bullish cell -0.2366 bps |
| G09 chronological-half stability | **Fail** | New York early half -3.4584 bps |
| G10 1.5x cost stress | Pass | London +USD 1.0869/oz; New York +USD 0.0937/oz |

The New York 1.5x-stress mean return in basis points was approximately
-0.0040 while mean dollar P&L remained +USD 0.0937 per ounce because entry
notionals vary. The predeclared G10 threshold was mean net P&L, so G10 passed;
this detail does not change the two failed gates.

## Integrity and reproducibility

The content-addressed validation bundle is:

`research_artifacts/gold_casebook_chronological_validation_v01/`

| Artifact | Hash |
|---|---|
| Pre-result validation manifest | `4e070218bfe2be8d0113762bbc42d944e39fccf8916f9f7286a998c05e170269` |
| Bundle manifest | `e508b049961c622d09b8474815e0a4d3c8e3c814f03ce1f72b0154116594d3c4` |
| Validation decisions payload | `a71550c3e48e660d56f5b6287104f641ed0008746101f77296b9a603688a97c4` |
| Validation results document | `4580c8f11242cf1444f7e68de82292bb48c874f4a1195e982fd836e65d069a2d` |
| Validation results file | `e9a99e43462290eee74e62d84695d0f247a4186b7524a9cd2f86c61e06b0de69` |
| Independent semantic validation | `a6490e0d6297e6d2c3ef53a4625d6c8e064a636350a735c1485df74b4a55a099` |

Independent validation reconstructed:

- all 502 decisions directly from immutable 2024 session and cross-market
  records;
- all 470 selected outcomes from exact fixed-execution baseline trade hashes;
- decision clocks, source availability, ZN state, continuous-roll exclusions,
  and point-in-time lineage;
- every state, half, control, cost-stress, bootstrap, and aggregate metric; and
- all ten frozen gate decisions and the rejection verdict.

A clean ephemeral rerun reproduced the bundle manifest and both bundle
artifacts byte-for-byte.

Verification completed with:

- 139 backend tests passing; and
- focused Ruff checks passing.

## Contracted state after rejection

This research branch is closed.

- Calendar 2024 has now been consumed as validation data and cannot be used to
  retune or rename this candidate.
- Milestone 7 is not eligible because the information edge failed Milestone 6.
- Calendar 2025 remains unopened and locked.
- Milestone 8 execution research is not eligible.

Any future research requires a separately authorized contract for a genuinely
different hypothesis and new untouched or prospective validation. No such
branch was started here.
