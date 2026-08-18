# Scoring Engine Design

## 1. Design intent

The engine ranks evidence; it does not predict with a hidden model and it does not
turn a macro opinion directly into a trade. Its outputs are:

- directional gold intelligence score `[-100,+100]`;
- bullish and bearish evidence points `[0,100]`;
- neutrality and conflict scores `[0,100]`;
- evidence coverage and analysis confidence `[0,100]`;
- separate execution confidence and entry state;
- dominant driver, principal contradiction, and highest-risk assumption;
- upcoming catalyst and risk warnings;
- explicit confirmation and invalidation conditions; and
- a human-readable causal chain whose nodes cite stored facts.

The initial method is deterministic, configuration-driven, versioned, bounded, and
exactly reproducible.

## 2. Signal contract

Every signal contains:

| Field | Rule |
|---|---|
| `name` / definition version | Stable semantic identity and immutable rule version |
| `layer` | One of the seven layers |
| `driver_family` | Correlation/capping group such as `REAL_YIELD` or `USD` |
| `direction` | `-1` bearish gold to `+1` bullish gold |
| `strength` | Magnitude of evidence `[0,100]`, independent of direction |
| `confidence` | Rule's confidence in the interpretation `[0,100]` |
| `freshness` | Time-decay value `[0,100]` |
| `data_quality` | Input integrity/granularity/completeness `[0,100]` |
| `source_summary` | Provider/series or calculation identity |
| `epistemic_status` | `OBSERVED`, `CALCULATED`, `INFERRED`, or `UNKNOWN` |
| `explanation` | Deterministic statement of observation and interpretation |
| `timestamp` / `available_at` | What it describes and when it became eligible |
| `expires_at` or decay policy | Hard expiry or half-life |
| supporting facts | Typed lineage relations |
| contradicting facts | Typed lineage relations |

`OBSERVED` is normally reserved for facts, not interpretive direction. For example,
“10-year real yield is 1.82%” is observed; “falling real yield supports gold” is a
calculated signal. “Probable short covering” is inferred.

An unknown signal is explicit: direction and strength are zero, confidence is zero,
and the explanation names the absent, stale, or quarantined inputs.

## 3. Freshness and quality

Default continuous decay uses a configured half-life:

```text
freshness = 100 * exp(-ln(2) * age / half_life)
```

Hard-expiry signals become unknown after `expires_at`. Event surprises may decay
rapidly; regime features decay slowly; COT receives a weekly-data half-life and must
never be treated as live positioning.

Quality starts from the weighted product or configured blend of:

- schema validity;
- completeness;
- timestamp precision;
- source/revision reliability;
- appropriate granularity for the proposed use; and
- open data-quality issues.

Daily delayed USD data can have high source quality for daily regime analysis but low
fitness for one-minute event confirmation. The use-context fitness is therefore part
of the signal quality, not a claim that the source itself is poor.

## 4. Driver budgets instead of a flat average

Signals are grouped into named driver families so correlated evidence cannot vote
multiple times. Core CPI month-on-month and year-on-year, for example, are related
components inside an inflation driver; they are not two independent full-weight
votes. Ten-year nominal yield, real yield, and breakeven decomposition are similarly
capped.

Initial layer budgets are configuration defaults, not hard-coded constants:

| Layer/role | Baseline point budget |
|---|---:|
| 1. Regime | 18 |
| 2. Expectations and pricing | 18 |
| 3. Positioning and observed flows | 10 |
| 4. Released catalyst information | 10 |
| 5. Session/liquidity confirmation | 4 |
| 6. Cross-market confirmation | 25 |
| 7. Price acceptance/structure confirmation | 15 |
| **Total** | **100** |

Layer 7 directional points describe whether price accepts or rejects the story. They
do not set `TRIGGERED`; the execution state machine separately requires a trigger,
invalidation, and viable risk.

Crowding by itself does not consume directional points. Crowded longs are not a
bearish forecast; they create downside amplification risk and reduce confidence in
chasing a bullish move. Directional Layer 3 points require evidence such as observed
ETF flow or a clearly defined change in positioning, while price/open-interest motive
remains inferred.

## 5. Calculation

For signal `i`, convert fields to unit intervals and calculate effective evidence:

```text
x_i = direction_i
      * strength_i
      * confidence_i
      * freshness_i
      * data_quality_i
```

Each term after direction is divided by 100. An expected signal has a configured
within-driver coefficient `alpha_i`. Unknown signals contribute zero and their
coefficient remains in the denominator; missing inputs therefore reduce coverage
instead of allowing the remaining signal to take the entire budget.

For driver `j`:

```text
driver_value_j = clamp(sum(alpha_i * x_i), -1, +1)
known_coverage_j = sum(alpha_i for eligible, non-UNKNOWN signals)
```

Coefficients within a driver sum to one. Driver and layer caps are applied before
aggregation and recorded on every score component.

Reaction profile multiplier `r_j` changes budgets, after which they are normalized
back to 100 available points:

```text
effective_budget_j =
    100 * base_budget_j * r_j / sum(base_budget_k * r_k)

contribution_j = effective_budget_j * driver_value_j
overall_score = sum(contribution_j)
```

Because effective budgets sum to 100 and each driver is bounded, the score is
mathematically constrained to `[-100,+100]`. Missing or weak evidence cannot create
an extreme score.

```text
bullish_score = sum(max(contribution_j, 0))
bearish_score = sum(max(-contribution_j, 0))
```

These are gross evidence points, each bounded by 100. The headline score is bullish
minus bearish points.

### Neutrality and conflict

```text
gross = bullish_score + bearish_score
neutrality = 100 - min(100, gross)

conflict = 0                                      if gross = 0
conflict = 100 * 2 * min(bullish, bearish)/gross otherwise

neutral_conflict = max(neutrality, conflict)
```

Neutrality is high when evidence has low directional magnitude; conflict is high
when substantial evidence exists on both sides. The API returns both values as well
as the combined field so the UI does not hide why conviction is low.

## 6. Confidence is not probability of profit

Define values on `[0,1]`:

```text
coverage  = budget-weighted known_coverage
integrity = budget-weighted mean(signal_confidence * freshness * data_quality)
agreement = 1 - 0.5 * conflict

analysis_confidence = 100 * sqrt(coverage * integrity) * agreement
```

Optional parameter-stability testing can apply a disclosed stability multiplier.
Until calibrated on untouched data, this number means “confidence in the evidence
bundle and interpretation,” not a 74% chance that gold rises or a trade wins.

Execution confidence is separate:

```text
execution_confidence = analysis_confidence
                       * price_confirmation_factor
                       * catalyst_risk_factor
                       * liquidity_factor
                       * risk_feasibility_factor
```

Every factor and penalty is returned in score components. A major event approaching,
abnormal spread, absent trigger, or unacceptable stop distance can reduce execution
confidence without reversing macro bias.

## 7. Reaction-function profiles

Only one named, versioned profile is active at an `as_of` time. Profile selection is
itself rule-based and evidenced; uncertainty between profiles lowers confidence.

| Profile | Upweighted evidence | Downweighted/changed role |
|---|---|---|
| `BASELINE` | Fed path, real yield, USD, balanced macro | None |
| `INFLATION_FOCUS` | CPI/core, wages, breakevens, real yields, Fed repricing | Growth data unless materially surprising |
| `GROWTH_LABOUR_FOCUS` | Payrolls, unemployment, claims, GDP/retail, 2Y repricing | Minor inflation components |
| `FINANCIAL_STRESS` | Liquidity, volatility, safe-haven behaviour, USD/gold co-rise | Conventional risk-on/off assumptions |
| `STAGFLATION_CONFLICT` | Inflation, growth contraction, real-vs-breakeven decomposition | Confidence receives conflict penalty |

Weights change prospectively from facts available at the time. A backtest cannot
choose a profile later because it best explains the realized return.

## 8. Layer rules

### Layer 1: regime

Calculate separate, bounded state axes:

- growth level, direction, and rate of change;
- inflation level, direction, persistence, and rate of change;
- labour tightness/deterioration;
- policy stance/path;
- financial/liquidity stress; and
- yield/USD confirmation.

The deterministic mapping supports:

| Growth | Inflation | Additional condition | Regime candidate |
|---|---|---|---|
| strengthening/stable | falling toward target | no material stress | Goldilocks or soft landing |
| strengthening | rising/sticky | restrictive repricing | Overheating |
| slowing/contracting | rising/sticky | policy conflict | Stagflation |
| slowing | falling | no formal contraction | Slowdown |
| contracting | falling but positive | labour deterioration | Recession/disinflation |
| contracting | below zero/falling | broad price decline | Deflationary stress |
| any | any | stress axis exceeds override threshold | Financial/liquidity crisis |

Thresholds, trend windows, and target bands are versioned. If competing membership
scores are close, the output is mixed/conflicted rather than a forced label.

### Layer 2: expectations and surprise

For event component `e`:

```text
raw_surprise_e = actual_e - last_eligible_consensus_e
standardized_surprise_e = raw_surprise_e /
    rolling_std(prior point-in-time surprises of the same component)
```

The standardization window uses only earlier events, requires a minimum sample, and
is capped at a configured absolute value. Low history lowers confidence rather than
borrowing a future full-sample standard deviation.

Raw surprise, actual-versus-previous, contemporaneously displayed previous value,
and revisions are separate features. A mapping converts the economic surprise into
hawkish/dovish policy pressure; the active reaction profile then maps policy pressure
to gold direction. Higher unemployment, for example, has a different orientation
from higher CPI.

Fed repricing compares complete eligible path snapshots: next-meeting probability,
first expected move, cumulative changes, and destination rate. An expected cut with
a higher subsequent path can therefore be classified hawkish relative to pricing.

### Layer 3: positioning

- Managed-money net = long minus short.
- Percentile uses only COT reports published by the calculation time; it never uses
  the final full-history distribution.
- Weekly changes and crowding thresholds are versioned.
- Producer/commercial shorts are labelled hedging context, not bearish conviction.
- ETF and COT divergence is reported without claiming all institutional demand is
  absent.

Price/open-interest rules create explicitly inferred hypotheses:

| Price | Open interest | Inference |
|---|---|---|
| Up | Up | Probable fresh bullish participation |
| Up | Down | Probable short covering/contract reduction |
| Down | Up | Probable fresh bearish participation |
| Down | Down | Probable long liquidation/contract reduction |

Confidence depends on time alignment, exchange coverage, magnitude, volume, and
absence of roll distortion. Each explanation uses “probable” rather than asserting
participant identity.

### Layer 4: catalysts

Before release, a catalyst is a risk/attention object and cannot contribute the yet
unknown result. After release, impact combines separately displayed components:

```text
impact = importance_component
         * surprise_component
         * positioning_amplifier
         * liquidity_amplifier
         * reaction_function_relevance
```

Each component is normalized, capped, and preserved. Market reactions at 1 minute,
5 minutes, 15 minutes, 1 hour, 4 hours, and daily close are calculated facts, not
inputs available before those horizons complete.

### Layer 5: session and liquidity

Session identity comes from materialized DST-aware intervals. Session direction is
only scored when an explicit breakout/acceptance/rejection rule is satisfied.
Rollover or spread anomalies reduce execution confidence and can explain a temporary
move without changing macro bias.

The implemented `broker-liquidity-1` rule compares the latest 15 completed
one-minute bars with observations from the prior 20 calendar days that share the
same DST-aware primary session and special-window state. Spread or bar-range
percentiles at or above 90 classify `ELEVATED`; at or above 97.5 classify
`ABNORMAL`. Very low broker tick activity combined with a wide spread can also
elevate the state. The corresponding execution-confidence multipliers are 1.00,
0.75, and 0.50. Missing current spreads or fewer than 100 eligible baseline spread
observations produce `UNKNOWN` and a conservative 0.50 multiplier. None of these
states contributes bullish or bearish direction.

The implemented `market-structure-1` research surface uses confirmed fractal pivots
with configurable left/right bars and minimum ATR prominence. The pivot timestamp is
never treated as the detection timestamp: the swing becomes available only after
the required right-side bars close. It deterministically labels HH/HL/LH/LL,
support/resistance, BOS/MSS, ranges, compression/expansion, displacement, and
momentum. Acceptance, rejection, retest, failed-breakout, and trapped-participant
interpretations are labelled `INFERRED`.

One-minute inputs are aggregated without interpolation to 5m, 15m, 1h, 4h, and
provider-session daily bars. The IC Markets daily template is versioned separately
from the detector configuration and respects its observed Sunday open and recurring
maintenance pause. Any other missing minute still makes the aggregate incomplete.

### Layer 6: cross-market

The initial causal priority is configurable but follows the book:

1. Fed expectations;
2. real-yield movement;
3. USD movement;
4. safe-haven or gold-specific demand; and
5. gold price acceptance/rejection.

Conventional confirmation and exception templates are separate. Gold and USD rising
together with falling equities and higher volatility may support a safe-haven
interpretation; it is not automatically an error. Nominal-yield moves are decomposed
into real yield and breakeven inflation before receiving a gold interpretation.

### Layer 7: execution and risk

The state machine is independent of the bias score:

```text
NOT_ACTIONABLE -> WAIT -> ARMED -> TRIGGERED
                         \-> INVALIDATED
```

- `NOT_ACTIONABLE`: evidence/coverage below policy.
- `WAIT`: bias exists but trigger absent, event risk too high, or liquidity abnormal.
- `ARMED`: named confirmation is close and a valid invalidation/risk plan exists.
- `TRIGGERED`: the deterministic closed-bar trigger is satisfied and risk is viable.
- `INVALIDATED`: a stored invalidation condition is satisfied.

No state places an order in Phase 1. Suggested size is a transparent calculation
from user-supplied maximum money risk and loss per unit; a wider logical stop reduces
size. Portfolio-cluster and daily-loss policies can block `TRIGGERED` without
changing bias.

## 9. Explanation and contradiction model

Reasoning is stored as a directed acyclic graph. A typical instantiated path is:

```text
cooler CPI vs eligible consensus
  -> more easing in the next Fed-path snapshot
  -> 2Y yield falls
  -> real yield falls
  -> broad USD weakens
  -> gold receives macro support
```

An edge is emitted only when its required facts exist and their time order is valid.
Correlation is never described as demonstrated causation; templates use language
such as “consistent with” unless the rule observes the intermediate repricing.

The dominant driver is the largest absolute final contribution. The main
contradiction is the largest eligible contribution opposing the headline direction.
The highest-risk assumption is the material contribution with the weakest quality,
most inferential status, or greatest sensitivity to nearby parameter values.

Confirmation and invalidation are stored rule expressions with current status:

```text
confirmation: two closed 5m bars above resistance while real yield and USD do not reverse
invalidation: close below accepted support plus real yield and USD reversal
```

The UI renders the condition, its data dependencies, and whether each dependency is
currently met.

## 10. Optional AI narration

The AI service receives only:

- finalized score fields;
- approved insight claims and reasoning edges;
- evidence IDs and display-safe values;
- unknown/stale fields; and
- a prohibited-claims policy.

It cannot call providers, create a score, select a trade, or fill missing facts. Its
output must be decomposable into sentences that cite input claim IDs. Unsupported
sentences fail validation and the deterministic narrative is served instead.

## 11. Required scoring tests

- Exact boundary and property tests keep all values within specified ranges.
- Unknown input reduces coverage and cannot become neutral observed evidence.
- Duplicated correlated signals cannot exceed their driver/layer cap.
- Stale COT receives the configured decay and becomes unknown after expiry.
- Pre-release events reduce execution confidence but contribute no event direction.
- A revision is invisible before its revision availability.
- Changing a reaction profile changes only documented weights.
- Crowded positioning alone cannot reverse directional bias.
- A bullish score without a trigger never becomes `TRIGGERED`.
- Every non-unknown signal and every insight has complete lineage.
- Recalculation with the same fact/config/code hashes is byte-for-byte deterministic.

## 12. Implemented seven-layer decision (ruleset `gold-reference-book-7-layer-v1`)

The executable directional budget is intentionally fixed at 100 points and is not
renormalized around missing inputs:

| Driver | Budget |
|---|---:|
| point-in-time Fed path | 18 |
| 10Y real yield | 15 |
| broad USD | 12 |
| 2Y yield | 10 |
| inflation regime | 10 |
| catalyst surprise | 8 |
| growth regime | 6 |
| labour regime | 6 |
| positioning flow | 5 |
| equity risk | 4 |
| nominal/real/breakeven decomposition | 4 |
| financial stress | 2 |

For an available component:

```text
normalized_direction = clamp(raw_change / configured_scale, -1, +1)
certainty_fraction = confidence * freshness * data_quality / 100^3
contribution = budget * normalized_direction * certainty_fraction
```

`strength = abs(normalized_direction) * 100` is displayed but is not multiplied a
second time into the score. Missing components contribute zero *and* reduce coverage;
they are labelled `UNKNOWN`, not neutral. Aggregate confidence is the weighted
certainty of available components multiplied by the square root of evidence
coverage. It is explicitly not a probability of profit.

The current public slice activates real yield, USD, 2Y yield, nominal decomposition,
published COT flow, equity/VIX risk sentiment, and a financial-stress composite.
The stress composite uses the St. Louis Fed Financial Stress Index and US
high-yield option-adjusted spread. Both cross-market interpretations are
`INFERRED`: they can support defensive gold demand, but the reasoning also records
that severe deleveraging can initially liquidate gold.

The catalyst component activates only when an original release has an eligible
pre-release forecast. A major known event inside four hours lowers execution
confidence without adding pre-release direction. ALFRED inflation, growth, and
labour vintages are active under a conservative next-day availability rule.
Historical MT5 consensus whose first-observed time is unknown is eligible at the
release boundary only: it supports surprise and reaction research but cannot become
a pre-release backtest feature. Real Atlanta Fed quarterly SOFR probability
distributions can contribute a conservatively delayed Fed-path component; they are
never relabelled as exact meeting-level FedWatch. The factor-coverage endpoint
exposes all 97 registered factors, including unavailable licensed contracts, so
partial coverage cannot be mistaken for the finished engine.

When ALFRED vintages are present, the engine activates three additional transparent
components:

- inflation: weighted CPI/core CPI/PCE/core PCE year-over-year level plus the
  three-month change in that rate;
- growth: real-GDP annualized sequential growth and retail-sales year-over-year
  momentum; and
- labour: payroll change versus its prior three-month pace, unemployment change,
  wage inflation change, and initial-claims four-week momentum.

The regime classifier can then emit Goldilocks, soft landing, overheating,
slowdown, recession/disinflation, stagflation, or deflationary stress. It does not
emit financial crisis without a connected stress composite.

`FED_PATH` consumes the complete meeting probability surface, not one headline
probability. Its direction combines destination versus the current effective rate
with repricing across meetings common to the latest and prior snapshots. Missing
prior history lowers confidence rather than fabricating a repricing comparison.

The active reaction function selects one of four transparent 100-point profiles:
`BASE`, `INFLATION_FOCUS`, `GROWTH_LABOUR_FOCUS`, or
`FINANCIAL_STRESS_FOCUS`. The selected profile and every effective weight are stored
in the reasoning payload.

The canonical persisted artifact is
`gold-reference-book-7-layer-v1-decision-v1`. It combines the directional
components with all seven layer assessments:

```text
Layers 1-4 and 6 -> signed directional evidence
Layer 5          -> session, liquidity, and price-confirmation gate
Layer 7          -> trigger, invalidation, portfolio-risk, and action gate
```

Layer 5 or 7 can reduce execution confidence or force a `WAIT` state, but neither
can manufacture bullish or bearish points. The decision stores directional score,
bullish and bearish pressure, connected-evidence conflict, directional confidence,
execution confidence, stable book coverage, live usable coverage, dominant driver,
contradiction, catalyst, execution plan, reasoning chain, and all evidence hashes.
It is created and read through `/api/v1/decisions/snapshots`; the older
`/api/v1/intelligence/*` endpoints are deprecated compatibility surfaces.
