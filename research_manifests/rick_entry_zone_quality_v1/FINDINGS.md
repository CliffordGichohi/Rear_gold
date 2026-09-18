# Entry-model and zone-formation audit: findings

## Result

Completed on all 1,512 unchanged original trades, January 2023 through August 2026. No entry, stop, target, risk, cost, management, candidate selection or trading filter changed. These are exposed historical comparisons, not independent validation or new strategy returns.

There are useful **model-specific differences**, but none of the 14 newly specified univariate comparisons established a sufficiently supported, year-stable association after the audit's descriptive uncertainty/multiplicity checks. This does not reject either original strategy or prove that entry quality cannot be improved.

## 1. The entry models have different economic profiles

| Original entry model | Trades | Net profitable trades | Mean net R/trade | Original total R | Profit factor |
|---|---:|---:|---:|---:|---:|
| UJ M15 W | 393 | 23.41% | +0.149 | +58.62 | 1.274 |
| GJ M5 demand-zone W | 897 | 38.24% | +0.168 | +150.66 | 1.274 |
| GJ M15 range-response market entry | 222 | 44.59% | +0.375 | +83.17 | 1.702 |

Win rate here means positive net R, not directional accuracy. UJ also has 101 original BE exits; costs mean these are not counted as net winners. R retains the original $50 planned-risk unit.

GJ range-response was stronger per trade in this exposed sample. GJ W supplied more trades and total R, but also **527 of GJ's 637 full stops**. Different sample populations and execution rules mean this is not proof that switching a W trade to a market-response entry improves it.

## 2. The same entry location can mean different things

**GJ W:** fills inside their parent demand zone: 435 trades, **+91.94R**. Fills above the zone but no more than one original R above its top: 425 trades, **+51.40R**. Another 37 higher fills totaled +7.32R.

**GJ range-response:** fills inside the old range: 32 trades, **-2.88R**. Fills above its top: 190 trades, **+86.05R**.

That is a descriptive difference consistent with the two models having different intended entry geometry. It does not justify imposing one shared location filter.

The 32 inside-range response trades were not all bad: 13 net winners contributed **+15.50R**, while the 19 net losers contributed **-18.38R**. Their yearly totals were -3.05R in 2023, +3.03R in 2024, -6.48R in 2025 and +3.63R through August 2026. Therefore removing them is not an established stable improvement or a demonstrated drawdown repair.

**Deduplication:** all 32 already belong to the previous `trigger_not_held` warning cohort. This is a clearer entry-location description of an existing lead, not a new independent discovery. No second evidence credit is claimed.

## 3. Freshness and large break candles are not reliable blanket requirements here

- GJ W with at least two observed completed revisit episodes: 254 trades, **+72.01R**, mean +0.284R. Fewer episodes: 462 trades, **+38.76R**, mean +0.084R. The revisit group's mean was higher in each year, but the clustered difference interval **[-0.102, +0.482]R** spans zero. Another 181 trades have incomplete observation windows and remain UNKNOWN.
- GJ W with the predefined weaker zone-departure candle: 427 trades, **+99.85R**. Strong departure: 430 trades, **+32.85R**. Forty cases are unknown. Strong means the frozen body, close-location and prior-ATR conditions, not an assertion about trader intent.
- GJ W deep current pullbacks and shallow ones had nearly identical mean results: approximately **+0.167R versus +0.169R**.

These facts do not establish that repeated touches or weaker candles cause profits. They do warn against automatically excluding older/tested zones or demanding a visually stronger candle without model-specific evidence.

## 4. Losses are not all profit giveback

| Model | Full stops before any observed +0.5R M5 close | Full stops after an observed +0.5R M5 close |
|---|---:|---:|
| UJ W | 153 | 47 |
| GJ W | 315 | 212 |
| GJ range-response | 69 | 41 |

On GJ W, about 60% of its full stops never established an observed completed M5 close at +0.5R before the stop. The other 40% did respond before failing. These require different explanations; blanket profit protection cannot account for all losses.

This is a reuse of the sealed response measurement, not a new path simulation. Absence of a +0.5R M5 close does **not** prove immediate failure or rule out an intrabar touch. Original missing-path flags are retained. Nor does reaching +0.5R prove an executable exit there or guarantee later targets.

## 5. Relationship to the major drawdowns

In the four largest sealed decline phases, GJ W supplied 311 entries whose eventual original results summed to **-82.87R**. Its entry cohorts in the corresponding recoveries totaled **+93.31R** across 178 entries. These are final results grouped by entry phase, not marked-to-market drawdown contributions or prospective regime labels.

The drawdown investigations should therefore continue to distinguish the GJ W mechanism from the smaller range-response mechanism. Simply restricting all entries to stronger candles, fresh zones, or positions above a zone does not follow from this audit. The negative 32-trade range-response cohort is too small and unstable to be presented as the solution to the large account drawdowns.

## Decision

Preserve both profitable originals. No new filter is justified as a proven way to meet the 9R drawdown objective, and no changed equity curve was calculated. The completed comparison gives a more precise problem statement: **GJ W entry selection is the larger source of both losses and recovery profits; range-response entry back inside its range is a separate, already-known weakness.** Neither should be silently treated as the other.

No additional filter search, execution change or backtest is started by this report.

## Reproduction and scope

- Eleven new synthetic tests and all 19 existing pre-entry regression tests passed.
- Independent scalar/vector feature calculations, cohort statistics and uncertainty calculations matched; paired serialized artifacts have identical hashes.
- All 14 comparisons, all 81 formation/trigger/location cells (including empty and sparse cells), annual/monthly results, 123 losing-sequence controls and five decline/recovery intervals were retained.
- UJ's W formation is not mislabeled as a GJ parent zone. GJ W confirmation uses M5, while its parent is M15.
- Formation, geometry and trigger features use only source information available by the original fill. Future parent invalidation/closure fields are removed from feature inputs. Existing outcomes are joined only after feature reproduction.
- No data acquisition, charges, repairs, imputation, live orders or changed strategy files.

Detailed evidence: `REPORT.md`, `features.json`, `comparisons.json`, `matrix.json`, and `cohorts.json`. All results remain exposed and exploratory; prior research multiplicity is not erased by this audit's protocol freeze.
