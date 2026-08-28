# Gold Matched Human Coherent Auction — Improvement Decomposition V1

## Evidence boundary

This is a post-result attribution of the already exposed 16-trade matched sample. It does not change any prior result and cannot validate a filter or management rule. Calendar 2025 and 2026 remain untouched.

## Reconciliation

- Fifteen decisions retained coherent M15 structural geometry.
- The complete point-in-time executable result was `+1.7932R`.
- The eleven hindsight direction-correct cases contributed `+6.0267R`.
- The four hindsight direction-wrong cases contributed `-4.2335R`.
- `CBR-2022-003` was rejected before execution because no active bullish M15 break remained.

At the frozen `$50 = 1R` reporting unit, the losing subset is `-$211.67`, or approximately `-2.12%` of the `$10,000` account. It is `-4.2335R`, not automatically `-4.2335%`.

## Direction-correct cases: what remained uncaptured

The eleven direction-correct cases produced `+6.0267R` but their non-tradable stop-feasible MFE ceiling totalled `+24.0043R`; the fixed-H1 policy retained 25.11% of that ceiling. The ceiling uses the future maximum and is not a strategy, but it identifies where value was lost.

### Correct direction but stopped

| Case | Fixed-H1 result | Stop-feasible MFE before stop | Interpretation |
|---|---:|---:|---|
| `CBR-2022-005` | -1.0372R | +1.0164R | Range/recovery thesis responded correctly, then fully round-tripped. A favourable-response protection rule is relevant. |
| `CBR-2022-014` | -1.0195R | +1.8102R | Correct bullish outer direction in a two-sided internal auction; meaningful profit was surrendered before the later continuation. |
| `CBR-2022-030` | -1.0709R | +0.6370R | The generic latest protected-M15-low stop was too tight for the annotated M5-within-M15-range setup. The original wider invalidation had produced +1.6926R. This is primarily a stop-semantics problem, not merely missing profit management. |

### Correct direction but open profit was poorly retained

| Case | Fixed-H1 result | Stop-feasible MFE | Capture |
|---|---:|---:|---:|
| `CBR-2022-013` | +0.0544R time exit | +1.4704R | 3.70% |
| `CBR-2022-020` | +0.3700R time exit | +0.7700R | 48.05% |
| `CBR-2022-023` | +2.1112R time exit | +2.9120R | 72.50% |

`CBR-2022-013` is the clearest management failure. A simple local-level rejection exit improved it in the exposed diagnostic, but applying that exit universally damaged larger winners.

### H1 target hit before additional extension

| Case | Fixed-H1 result | Stop-feasible MFE | Capture |
|---|---:|---:|---:|
| `CBR-2022-002` | +0.7654R | +2.6180R | 29.24% |
| `CBR-2022-006` | +0.7247R | +1.6155R | 44.86% |
| `CBR-2022-015` | +0.4206R | +2.4688R | 17.04% |
| `CBR-2022-024` | +2.4773R | +2.4972R | 99.20% |
| `CBR-2022-027` | +2.2306R | +6.1888R | 36.04% |

Four of five target winners had meaningful later extension. `CBR-2022-024` did not: its H1 target captured almost the entire available move. This supports a bounded runner after the H1 realization, not replacing the H1 realization with an uncapped full-position runner.

## Direction-wrong cases: point-in-time warnings

### `CBR-2022-007`

- H4 24-bar range location: `0.854`.
- H4 15-bar displacement: `+4.395 ATR`.
- The annotation itself said price was approaching a prior H4 liquidity-shift area.
- The error was treating a defensible bullish trend label as sufficient despite poor continuation location and limited unobstructed H4 room.

### `CBR-2022-009`

- H4 24-bar range location: `0.836`.
- H4 was balanced near its upper boundary, not discounted on the controlling timeframe.
- The thesis called an H1 internal range discounted while ignoring that the H4 auction was already near premium/opposing liquidity.
- This was a timeframe-location conflict, not simply a wrong trend label.

### `CBR-2022-019`

- Confirmed H4 relations were `HH + LL`, a mixed/transitioning sequence.
- H4 15-bar displacement was `-3.707 ATR`.
- Several prior lows had been displaced through. The rise into entry was a corrective recovery within bearish damage.
- The thesis incorrectly described the H4 state as an intact bullish retracement. A continuation long required accepted structural repair first; otherwise it had to be explicitly treated as a tactical countertrend recovery.

### `CBR-2022-026`

- H4 24-bar range location: `0.924`.
- H4 15-bar displacement: `+6.423 ATR`.
- Displayed macro pressure was strongly bearish (`-26.2`).
- The decision occurred around unresolved CPI volatility.
- The claimed M15-range discount was embedded inside extreme H4 premium/extension. Lower-timeframe discount did not create higher-timeframe continuation room.

## Important counterexamples

These warnings cannot become simplistic thresholds:

- `CBR-2022-024` was directionally correct despite a `0.902` H4 range location.
- `CBR-2022-020` was directionally correct as a local recovery even though its H4 swing sequence remained bearish.
- Strongly bearish displayed macro pressure also existed in several correct-direction cases.

Therefore, a hard rule such as “never long above 0.80 H4 range location,” “never trade against macro,” or “never long bearish H4 structure” would be post-hoc and would reject valid tactical auction responses.

## Evidence-based improvement hierarchy

1. **Classify the auction family before entry.** Separate bullish continuation, range rotation and countertrend structural repair. Do not label all three as continuation.
2. **Record controlling-timeframe phase and room.** Distinguish pullback-with-room, upper-boundary extension and bearish structural damage. Lower-timeframe discount cannot override higher-timeframe premium silently.
3. **Require repair when H4 is damaged.** A local bullish M15 break may permit a tactical response, but an H4 continuation claim requires accepted repair of the broken H4 reference.
4. **Treat event auctions explicitly.** A strong M5 response immediately after CPI is not sufficient until the event-driven range has accepted a direction.
5. **Tie the stop to the actual setup family.** A continuation transition may use the protected M15 origin; an M5 rotation inside an M15 range may require the controlling M15 range/shift invalidation rather than the latest generic protected low.
6. **Protect favourable responses without exiting every local rejection.** The exposed evidence supports testing protection only after a measurable favourable auction and a genuine opposite structure transition, not after a single level rejection.
7. **Preserve the H1 core and add only a bounded runner.** Realize the core at the preselected H1 destination; allow a minority runner only after completed acceptance beyond that destination.

The two largest prospective questions are therefore whether the operator can identify the four adverse auction states without future direction and whether a pre-frozen profit-state management rule can preserve `CBR-2022-005`, `013` and `014` without truncating `023`, `024` and `027`.

