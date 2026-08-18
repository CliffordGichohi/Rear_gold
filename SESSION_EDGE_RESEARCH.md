# Fundamental-Biased Session and Liquidity Edge Research

## 1. Decision being researched

This protocol implements the reference book's reading chain:

```text
point-in-time fundamental state
-> session and level map
-> observed price interaction
-> inferred sweep/rejection or calculated acceptance
-> displacement and structure confirmation
-> separately defined invalidation and risk
```

The research question is not whether gold moves during London or New York. Gold
usually provides a measurable intraday path. The falsifiable question is:

> Given the fundamental state known before the session, does a defined interaction
> with an Asian or higher-timeframe reference level produce favourable excursion
> before adverse excursion often enough to survive costs out of sample?

Every eligible session is an observation. A session without a trigger remains in
the opportunity ledger with a reason; it is not silently dropped and it is not
forced into a trade.

This implements Chapters 5, 6, 16, 18, and 19 of the reference book:

- obvious highs and lows are areas where orders can concentrate, not magical
  lines;
- a sweep is an `INFERRED` interpretation, while the traded high/low and closes
  are `OBSERVED`;
- rejection, acceptance, displacement, and structure provide the trigger;
- the fundamental state provides directional permission, not an automatic order;
- bias, trigger, invalidation, and risk remain separate decisions; and
- session windows use IANA timezones so London and New York daylight-saving
  changes are reproducible.

## 2. Frozen candidate families

### Candidate C1: London sweep, reclaim, and displacement

This is the first implementation priority.

For a long candidate:

1. Freeze the fundamental state before the London research window.
2. Construct a complete Asian range and the available higher-timeframe level map.
3. Observe a London trade below a qualified lower level.
4. Require a close back above the swept level within the configured reclaim
   window.
5. Require bullish displacement through a pre-sweep micro-structure level.
6. Record a hypothetical next-complete-bar entry and a structural invalidation
   beyond the sweep.

The short definition is symmetric. The detector never claims to observe a stop
hunt or an institution. It records an inferred lower- or upper-liquidity sweep
supported by exact bar evidence.

### Candidate C2: London breakout, acceptance, and retest

This remains a control candidate, not the first implementation target. It must
improve on the rejected two-close Asia breakout by requiring:

- a qualified range/compression state;
- bias alignment;
- closed-bar acceptance;
- a retest that holds;
- displacement and acceptable execution liquidity; and
- sufficient distance to the next level and remaining daily range.

Candidate C2 must be compared with Candidate C1 over identical session dates.

### Candidate C3: New York continuation or exhaustion

This is implemented only after Candidate C1's ledger is stable.

- Continuation asks whether London moved with the causal bias, left sufficient
  daily range, and received intraday yield/USD confirmation.
- Exhaustion asks whether London consumed an extreme proportion of normal range,
  reached a qualified level, and was rejected while cross-markets contradicted
  continuation.
- US event days require exact release clocks and post-release confirmation.

Daily FRED closes cannot be relabelled as intraday New York confirmation.

## 3. Point-in-time clocks

All stored timestamps are timezone-aware. The initial IC Markets research
contract is:

| Clock | Definition |
|---|---|
| Asian range | 10:05-16:00 `Asia/Tokyo`, excluding the observed broker maintenance/reopen gap |
| Fundamental freeze | Five minutes before 08:00 `Europe/London` |
| London search window | 08:00-12:00 `Europe/London` |
| Signal time | Close of the completed five-minute displacement bar |
| Hypothetical entry | Open of the next complete contiguous five-minute bar |
| Outcome information | Bars closing after the hypothetical entry, bounded by the requested study cutoff |

Only the earliest immutable one-minute version whose `available_at` is no later
than its five-minute bucket close is eligible. A later revision cannot alter an
earlier opportunity. Fundamental, COT, forecast, release, and schedule facts are
evaluated independently at the freeze clock.

Unknown catalyst risk is not treated as safe. It is stored as `UNKNOWN` and
reported as its own cohort. Unlike a trade-execution gate, an observational study
does not erase the session merely because that field is unknown.

## 4. Initial deterministic detector

The versioned initial configuration is deliberately small and configurable:

| Parameter | Initial research value | Purpose |
|---|---:|---|
| Five-minute ATR lookback | 14 bars | Normalize sweep, body, and stop distances |
| Asian compression lookback | 20 complete sessions | Avoid comparing with future ranges |
| Compressed threshold | At or below prior 50th percentile | Feature and optional qualification |
| Minimum sweep depth | 0.02 ATR | Remove price-equality noise |
| Maximum sweep depth | 0.75 ATR | Separate raids from established repricing |
| Reclaim deadline | 2 complete five-minute bars | Define rejection speed |
| Displacement deadline | 3 bars after reclaim | Bound the causal trigger |
| Micro-structure lookback | 3 complete bars | Define the level displacement must break |
| Minimum body | 0.35 ATR | Require material directional movement |
| Minimum body/range ratio | 0.60 | Reject high-wick indecision bars |
| Minimum close location | 0.70 | Require a close near the directional extreme |
| Volume percentile feature | Prior 100 complete five-minute bars | Evidence; `UNKNOWN` does not become zero |
| Structural stop buffer | 0.10 ATR beyond sweep | Define a non-random invalidation for outcome normalization |
| Outcome horizons | 30, 60, 120, 240 minutes | Measure path, not only session close |

These values define research version `LONDON_SWEEP_RECLAIM_V0_1`. They are not
optimized or promoted trading parameters. Range compression, volume, spread, and
fundamental alignment are initially cohort features. Their incremental value must
be measured before any becomes a hard gate.

## 5. Reference-level hierarchy

The first ledger records:

1. Asian high, low, and midpoint;
2. current New York-roll trading-day open;
3. previous trading-day high, low, and close; and
4. previous trading-week high and low when warm-up coverage is complete.

Gold trading days are segmented at 17:00 `America/New_York`, which keeps rollover
and daylight-saving changes explicit. Confirmed one-hour/four-hour swings and
licensed option levels are later additions. Missing levels remain `UNKNOWN`; they
are never fabricated.

Candidate C1 initially triggers from the Asian boundary. The other recorded
levels show confluence and obstruction without changing the frozen detector.

## 6. Opportunity-ledger contract

One immutable row is stored per requested London session. It contains:

- session date and all decision/signal/entry clocks;
- completeness and exclusion reason;
- fundamental score, bias, regime, reaction function, dominant driver,
  contradiction, confidence, coverage, catalyst state, and evidence hash;
- Asian range, prior range percentile, and compression status;
- reference levels and distance/confluence evidence;
- lower and upper sweep evidence, including depth and timestamp;
- reclaim and displacement evidence;
- spread and tick-volume context with availability status;
- setup side, bias alignment, trigger status, and explicit no-trigger reason;
- entry reference, structural invalidation, and normalized risk distance;
- MFE, MAE, terminal return, and ordered target-before-stop outcomes at each
  configured horizon; and
- price, fundamental, configuration, and combined reproducibility hashes.

The status progression is:

```text
INCOMPLETE_SESSION
NO_SWEEP
SWEEP_NOT_RECLAIMED
RECLAIMED_NO_DISPLACEMENT
TRIGGERED
OUTCOME_INCOMPLETE
```

Both sides can be swept. If both later produce a complete trigger, the earliest
signal is the primary setup and the two-sided condition remains explicit evidence.

## 7. Cohorts and edge tests

The event-study summary must compare identical opportunity rows:

| Cohort | Question |
|---|---|
| All triggered | Does the price/liquidity pattern have unconditional asymmetry? |
| Fundamental aligned | Does point-in-time causal permission improve it? |
| Fundamental opposed | Does opposition weaken or reverse it? |
| Neutral/conflicted | Is direction absent when macro evidence conflicts? |
| Catalyst known-low | What happens away from known major events? |
| Catalyst unknown | How much does the incomplete calendar affect inference? |
| Compressed Asia | Does prior range compression improve delivery? |
| Non-compressed Asia | Is the setup merely selecting ordinary volatility? |
| Volume expansion / no expansion | Does displacement with at least prior-60th-percentile tick volume improve the path? |
| Normal / elevated spread | Does execution-liquidity state distinguish genuine delivery from disorderly movement? |
| Reference-level confluence | Do previous-day/week levels strengthen the Asian-boundary interaction? |
| Same-bar / delayed reclaim | Does rejection speed contain information? |
| Sweep-depth bucket | Is a shallow raid different from a move already repricing beyond balance? |
| Regime / dominant driver | Does the causal macro state matter in a driver-specific rather than headline-score form? |
| Long / short | Is an apparent edge directionally concentrated? |

Primary observational outcomes are:

- probability of +0.50R, +0.75R, +1.00R, and +2.00R before -1.00R;
- MFE and MAE distributions;
- conservative 1R-target/-1R-stop path outcome;
- terminal normalized return by horizon; and
- deterministic bootstrap confidence intervals.

An event-study result is not a backtest result. A strategy candidate is specified
only after the study freezes entry, exit, cost, catalyst, liquidity, and risk
rules.

## 8. Research partition and promotion boundary

The chronological protocol is:

- discovery: 1 April 2023 through 31 December 2024;
- locked validation: calendar year 2025;
- robustness only: 2026 history already inspected during earlier research; and
- prospective paper holdout: sessions recorded after this protocol is frozen.

Because earlier work inspected parts of 2023 and 2026, they are not described as
pristine holdouts. The 2025 slice must be evaluated once after Candidate C1 rules
are frozen; no result from it may be used to tune Candidate C1.

Promotion requires positive cost-adjusted out-of-sample expectancy, stable
performance across time and directions, an interval that does not depend on a few
sessions, parameter stability, cost stress, and complete reproducibility. Until
then the dashboard label is `RESEARCH / EDGE NOT YET ESTABLISHED`.

## 9. Observed-data discovery checkpoint

The frozen `LONDON_SWEEP_RECLAIM_V0_1` detector has now been run over the
development interval in two non-overlapping, immutable annual ledgers:

| Slice | Run ID | Requested sessions | Complete sessions | Triggers |
|---|---|---:|---:|---:|
| 2023-04-01 through 2023-12-31 | `19486952-7d58-4732-8ad9-a7320e61cab5` | 195 | 179 | 43 |
| 2024-01-01 through 2024-12-31 | `1a18ab7b-5712-41f3-93bc-da8d1374f24c` | 262 | 251 | 54 |
| Exact combined comparison | both ledgers | 457 | 430 | 97 |

The comparison hash is
`894b42df41ff189a62ff4b307af4fde1f7d696e33c556b965dda9ff9cfb5d80b`.
It proves which immutable opportunity rows were compared; it does not prove an
edge.

The conservative gross path proxy assigns `+1R` when the 1R target occurs before
the structural `-1R` stop, `-1R` when the stop occurs first, and the bounded
terminal R result when neither resolves. It deliberately contains no transaction
costs and is therefore an event-study outcome, not strategy expectancy.

| Cohort | Setups | Mean gross path outcome | Bootstrap 95% interval | +1R before -1R among resolved |
|---|---:|---:|---:|---:|
| All triggered | 97 | +0.037 R | [-0.169, +0.229] R | 52.08% |
| Fundamental aligned | 35 | -0.011 R | [-0.337, +0.332] R | 50.00% |
| Fundamental opposed | 47 | -0.106 R | [-0.362, +0.191] R | 44.68% |
| Fundamental neutral/insufficient | 15 | +0.600 R | [+0.200, +1.000] R | 80.00% |
| Normal broker spread | 59 | +0.163 R | [-0.098, +0.421] R | 58.62% |
| Quality price/liquidity | 24 | +0.109 R | [-0.308, +0.500] R | 56.52% |
| Same-bar reclaim | 78 | -0.026 R | [-0.256, +0.179] R | 48.72% |
| Delayed reclaim | 19 | +0.295 R | [-0.126, +0.684] R | 66.67% |
| Long | 35 | +0.160 R | [-0.183, +0.486] R | 58.82% |
| Short | 62 | -0.032 R | [-0.290, +0.194] R | 48.39% |

The correct result is **edge not established**:

- the unconditional interval crosses zero before costs;
- the apparently positive normal-spread cohort was +0.331 R in the 2023 slice
  but -0.037 R in 2024, so it did not replicate;
- delayed reclaim remained positive in both annual slices
  (`n=10`, +0.261 R; `n=9`, +0.333 R), making it a research lead, but its combined
  interval still crosses zero;
- the neutral/insufficient row is concentrated in 2023 (`12` of `15` setups) and
  mixes absence/conflict of directional evidence, so it cannot be promoted as a
  causal fundamental signal;
- the present pre-London fundamental direction does not improve the detector;
  daily and slow-moving macro states are too coarse to stand in for intraday
  Treasury/USD confirmation; and
- every historical catalyst state in these runs is `UNKNOWN`, so the event-risk
  interaction is not yet testable.

The IC Markets catalog exposes the current `DXY_U6` US Dollar Index CFD and
`UST10Y_U6` 10-year Treasury-note CFD, but a direct terminal probe returned no
bars for January 2024. No 2-year Treasury contract was found. These symbols are
therefore prospective confirmation sources only. They cannot be spliced into
the 2023-2024 ledger or used to relabel its daily fundamental state as intraday
confirmation.

Calendar year 2025 remains unopened. Before the one-shot validation, the next
development task is to specify a costed delayed-reclaim candidate and improve
the point-in-time bias contract with historically available intraday USD/rates
data or explicitly keep that evidence `UNKNOWN`.

That costed development stage is now complete. The 19-trade mechanical control
returned +0.164 R net expectancy after 249.74 USD of modeled friction and passed
the declared development checks. The eight-trade fundamental-aligned primary
returned -0.044 R, failed 2024 and failed cost stress. Because the primary failed,
the predeclared protocol keeps 2025 unopened. Exact rules, runs, hashes and
results are in `SESSION_EDGE_STRATEGY.md`.

## 10. Delivery milestones

1. **Opportunity kernel**: deterministic five-minute aggregation, DST-aware
   session construction, level map, C1 detector, path outcomes, and cohort summary.
2. **Persistence and API**: append-only study run and session opportunity
   entities, migration, run/list/detail endpoints, and exact provenance.
3. **Backtest Lab presentation**: display coverage, funnel, cohort comparison,
   sample sessions, and the research-status warning.
4. **Real-data discovery run**: execute the frozen kernel on the available
   observed IC Markets development interval and publish all exclusions.
5. **Candidate specification**: use discovery evidence to freeze a tradable
   C1 rule without consulting the 2025 validation data.
6. **One-shot validation**: execute 2025 once, stress costs, and accept or reject
   the candidate.
7. **New York extension**: add intraday Treasury/USD data and exact historical
   catalyst schedules before C3 claims full cross-market confirmation.
