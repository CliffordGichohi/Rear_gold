# Point-in-Time Research and Backtesting Design

## 1. Why a custom event-driven core

Vectorized libraries are useful for secondary analysis, but the primary engine must
coordinate macro releases, forecast snapshots, revisions, delayed COT publication,
bar closure, session/DST boundaries, orders, latency, and costs on one virtual clock.
A small custom event-driven simulator is therefore the Phase 1 source of truth.

pandas/NumPy/SciPy/statsmodels may calculate features and statistics after the event
loop has produced eligible point-in-time states. A vectorized library may be used as
a benchmark on price-only strategies, never as a shortcut around availability.

## 1.1 Implemented Phase 1 price strategy

`ASIA_RANGE_ACCEPTANCE_V1` is the first runnable strategy. It exists to prove the
complete research path with observed broker bars; it is not yet the final
seven-layer gold strategy.

- Input: completed IC Markets MT5 `XAUUSD` one-minute bars.
- Asia range: 10:05–16:00 `Asia/Tokyo` by default. The five-minute buffer follows
  the observed IC Markets maintenance/reopen window in the historical archive.
  Both boundaries are recorded with each run, and a day is rejected rather than
  filled when a bar inside the selected range is missing.
- Decision window: 08:00–12:00 `Europe/London`, resolved through IANA time zones so
  DST changes do not rely on a fixed UTC offset.
- Trigger: one to three configurable completed five-minute bars closing beyond the
  Asia high/low plus an ATR buffer.
- Fill: the next eligible completed five-minute bar open. The trigger bar's unseen
  future path is unavailable to the decision.
- Risk: ATR-based stop, fixed-R target, risk-percent sizing, broker lot constraints,
  spread, slippage, and round-turn commission.
- Exit: stop, target, or 16:00 `America/New_York`. A bar touching both stop and
  target is resolved stop-first.
- Audit: source-data hash, parameter set, session/clock policy, per-trade evidence,
  cost decomposition, equity curve, and point-in-time eligibility counts.

Implemented API:

```text
GET  /api/v1/backtests/data-range
POST /api/v1/backtests/runs
GET  /api/v1/backtests/runs
GET  /api/v1/backtests/runs/{run_id}
```

The interactive client is at <http://localhost:3000/backtests>. Insufficient sample
size and confidence intervals crossing zero are explicitly warned about instead of
being hidden behind a positive headline return.

### First observed-data baseline

The stored baseline run `aa2c0d3d-ac28-44b2-87f1-dcefcd4f07b1` used 29,022 source
bars from 2026-06-29 through 2026-07-23, including warm-up, and produced 9 trades:
4 wins, 5 losses, +0.252 R mean expectancy, 1.416 profit factor, and +217.36 USD
net P&L on 10,000 USD initial equity after 70.97 USD modeled costs. Its 95%
confidence interval includes zero, so it is demonstration evidence only and does
not establish a durable edge.

## 2. Two separate research modes

### Event-study engine

Answers descriptive questions without manufacturing trades:

- How did gold respond after CPI surprises?
- Did response differ by surprise percentile, positioning regime, or session?
- Did the first one-minute spike hold or reverse?
- Did 2Y/real-yield/USD data confirm when timestamp granularity permits?
- What were 1m, 5m, 15m, 1h, 4h, and daily-close returns, MFE, and MAE?

### Strategy backtester

Simulates explicit decision rules, orders, fills, risk, and exits. A possible rule is:

```text
cooler CPI surprise
AND 2Y yield falling
AND real yield falling
AND USD weakening
AND gold accepts above resistance
AND crowding below configured threshold
-> submit long entry after the acceptance bar closes
```

The thesis, entry, invalidation, position sizing, and exit rules are separately
versioned. No discretionary interpretation is added after seeing results.

## 3. Virtual-clock model

Events are ordered by `(eligible_at, priority, stable_sequence)`:

1. source availability events (releases, forecasts, revisions, COT publication);
2. price-bar closes;
3. feature/signal recalculation events;
4. strategy decisions;
5. order eligibility and fills; and
6. risk/mark-to-market events.

The priority order is declared in the run manifest. Same-timestamp behaviour is not
left to database row order.

At clock `T`, the simulator requests an immutable snapshot from the point-in-time
repository. Eligibility requires `available_at <= T`; live replay can additionally
require `ingested_at <= T`. Provider and strategy latency are then added before a
decision or fill can occur.

### Closed-bar rule

A strategy cannot see a bar's high, low, close, volume, spread, or features until the
bar closes and becomes available. A close-based trigger submits after that time and
fills at the next eligible quote/bar under the configured latency model.

If only OHLC bars exist, the exact path inside a bar is unknown. When stop and target
are both touched in the same bar, the default is conservative/adverse ordering; the
run reports alternative-order sensitivity. Tick claims are prohibited.

## 4. Availability rules by data type

| Data | Eligibility rule |
|---|---|
| Price bar | Bar close plus declared provider latency |
| Macro actual | Exact release/source-availability timestamp plus latency |
| Consensus | Last snapshot available strictly before the release/decision cutoff |
| Macro revision | Its own later publication time; never retroactive |
| COT | Actual publication timestamp, not Tuesday observation date |
| Session | UTC interval generated from the then-active IANA-zone definition |
| Swing/structure | Detector confirmation time, including right-side bars |
| Event reaction at horizon H | Release plus H and required price availability |
| Derived feature/signal | Maximum availability of inputs plus calculation latency |

Future-dated facts, rows with unresolved temporal quality errors, and unavailable
revisions are excluded. Exclusions and counts appear in the run report.

## 5. Event-study algorithm

For each canonical event/component:

1. Find the final eligible forecast snapshot before release.
2. Select the initial actual observation available at release.
3. Calculate raw and point-in-time standardized surprise using prior events only.
4. Attach regime, reaction profile, positioning, crowding, and session states that
   were eligible immediately before release.
5. Select the last tradable pre-release price and first eligible prices at each
   horizon under a declared tolerance.
6. Calculate return, MFE, MAE, maximum spread, missing-bar status, and whether the
   first move held or reversed.
7. Attach cross-market reaction only where source timestamp precision supports the
   horizon; otherwise mark it unknown.
8. Store one immutable reaction record per event/instrument/horizon/config version.

First-move logic is configurable and explicit. A default definition may classify the
one-minute return direction as the first move and mark it “held” when the 15-minute
return has the same sign and has not retraced more than a configured fraction. The
definition is included in every report.

### Event-study outputs

- number of candidate and valid observations;
- exclusions by reason;
- mean/median return and robust dispersion;
- win/positive-response rate where direction is predeclared;
- MFE/MAE and first-move hold/reversal rate;
- percentile or economically meaningful surprise bins;
- breakdown by regime, session, positioning, year, and confirmation state;
- bootstrap confidence intervals with stored method/seed; and
- parameter/bin sensitivity.

Small samples are prominently labelled. Confidence intervals are not shown when the
configured minimum sample is absent.

## 6. Strategy simulation

### Strategy definition

A strategy is declarative JSON validated by a versioned schema:

```text
universe + date range
signal predicates
entry state/trigger
invalidation and stop rule
position-sizing rule
target/trailing/time exit
event blackout rules
cluster/daily risk constraints
commission/spread/slippage/latency models
benchmark and evaluation plan
```

Rules reference semantic feature/signal codes and versions, not arbitrary database
column expressions. The compiled rule tree and content hash are stored.

### Order lifecycle

```text
CREATED -> ELIGIBLE -> PARTIALLY_FILLED -> FILLED
                   \-> CANCELLED / EXPIRED / REJECTED
```

The run records decision, submission, eligibility, fill, cancellation, and exit
timestamps. The simulator supports market, stop, and limit research orders. Fill
models are conservative when quote/depth data is absent.

### Position sizing

```text
maximum_money_risk = equity * configured_risk_fraction
loss_per_unit = abs(planned_entry - logical_stop) * contract_value
quantity = floor(maximum_money_risk / loss_per_unit to allowed increment)
```

Spread, anticipated slippage, commission, gaps, and currency conversion may be added
to loss per unit. A position is rejected when the stop is invalid, data is stale,
quantity is below minimum, cluster risk is exceeded, or an event blackout is active.

### Costs

- **Spread:** observed bid/ask where present; otherwise a versioned static or
  time/session/event schedule.
- **Commission:** fixed, per-unit, or notional rate by instrument/provider.
- **Slippage:** base ticks/bps plus volatility, spread, event, liquidity, and size
  components, capped only where the model explicitly says so.
- **Latency:** source, calculation, decision, and order components.
- **Financing/roll:** configurable for multi-day spot/CFD research; no hidden zero.
- **Futures roll:** contract-aware schedule and explicit roll transaction costs when
  futures support is enabled.

Every gross and net result displays the cost decomposition.

## 7. Futures integrity

Phase 1's default price path is XAUUSD. Futures adapters nonetheless require:

- individual contract identity and expiry;
- contract-specific volume/open interest;
- deterministic roll policy known at the time (calendar, volume, or OI based);
- raw contract prices retained separately from any continuous series;
- back/forward/ratio adjustment policy used only for analysis, not executable fills;
- explicit roll trades and costs; and
- tests around expiry, first notice where relevant, and artificial-gap prevention.

A continuous adjusted price cannot be used as an actual fill price.

## 8. Evaluation plans

### In-sample/out-of-sample

The split is time ordered. Scaling, percentile thresholds, surprise distributions,
and parameter selection are fitted only on the training interval and frozen for the
test interval.

### Walk-forward

Each fold records train, validation, embargo, and test ranges. Configuration chosen
in a fold becomes eligible only after its training/validation period. Results are
combined from untouched test windows.

### Parameter stability

The engine runs a declared grid around selected thresholds and reports surfaces,
plateaus, and rank stability. A single narrow optimum is flagged as fragile rather
than promoted.

### Monte Carlo

Trade-order reshuffling uses stored seeds and preserves the empirical trade-return
set. Optional block/bootstrap methods preserve regime clusters. Reports include
drawdown and losing-streak distributions; reshuffling is not misrepresented as new
market paths.

### Benchmark comparison

Examples include buy-and-hold gold over the same eligible interval, a price-only
structure rule, or a simpler fixed-weight macro rule. Benchmark definition and costs
are stored with the run.

## 9. Metrics

Required overall and sliced metrics:

- observations/trades and exclusions;
- win rate;
- average and median return;
- expectancy in R;
- gross and net profit factor;
- maximum drawdown and duration;
- Sharpe and Sortino only when sampling assumptions are meaningful;
- MFE and MAE;
- average/median holding period;
- spread, slippage, commission, financing, and roll costs;
- performance by regime, session, year, event type, and confidence bucket;
- confidence intervals;
- parameter sensitivity; and
- exposure, turnover, and cluster-risk utilization.

Annualization frequency and risk-free-rate assumption are always displayed. Metrics
with insufficient observations return `UNKNOWN`, not zero.

## 10. Reproducibility manifest

Every run stores:

- experiment/rule hash;
- code commit and engine version;
- schema/migration version;
- scoring, session, structure, and quality configuration hashes;
- provider datasets and data watermark/content hashes;
- knowledge mode and latency policy;
- calendar and timezone database version;
- transaction-cost/fill/roll models;
- split and parameter-selection plan; and
- all random seeds.

Repeating a run against the same immutable inputs must produce the same orders,
trades, metrics, and result hash.

## 11. Correctness test suite

### Synthetic micro-scenarios

- A release at 08:30 cannot affect an 08:29 decision.
- A revised payroll value appears only at its later release.
- A Tuesday COT report is unavailable before its Friday/shifted publication.
- A forecast uploaded after release cannot become the event consensus.
- A pivot is invisible until all right-side confirmation bars close.
- A close-based breakout cannot fill at that same close without an explicit closing
  auction model.
- Missing bars prevent or delay a trigger according to policy.
- A DST transition produces correct London/New York sessions and overlap.
- A target and stop touched in one OHLC bar use conservative ordering.
- Spread and slippage worsen, rather than improve, an adverse fill.
- A futures roll cannot create artificial strategy profit from an adjusted series.

### Property and differential tests

- Adding latency cannot create an earlier fill.
- Adding non-negative costs cannot improve net PnL.
- Facts unavailable at `T` never appear in a snapshot at `T`.
- Reordering source ingestion without changing availability/content does not change
  historical results.
- A price-only subset agrees with a simple independent reference implementation.
- Metrics reconcile to stored trades and equity points within numerical tolerance.

## 12. Research guardrails

- The UI distinguishes descriptive event-study statistics from a trading strategy.
- Synthetic and real datasets cannot be compared without visible labels.
- No performance card hides sample size, costs, evaluation split, or exclusions.
- Saving a changed experiment creates a new version; prior results remain auditable.
- Export includes the reproducibility manifest and data-license warnings.

## 13. Implemented control-versus-fundamental experiment

`ASIA_RANGE_ACCEPTANCE_V1` is retained as the price-only control.
`FUNDAMENTAL_GUIDED_ASIA_ACCEPTANCE_V2` uses the exact same candidate, entry, exit,
risk, and cost rules, then asks the point-in-time fundamental state for permission.
Default gate requirements are:

```text
coverage >= 35%
confidence >= 25%
LONG:  directional_score >= +5
SHORT: directional_score <= -5
event risk: HIGH or EXTREME -> wait
```

At each candidate close the evaluator filters observations by `available_at` and COT
by `publication_at`. A rejected candidate records the reason, score, confidence,
coverage, bias, dominant driver, contradiction, and evidence hash. An accepted
trade embeds every fundamental component in its evidence ledger. Run hashes combine
price data, fundamental data, and parameters.

An event blackout is a temporary `WAIT`, not a permanent daily veto. The engine
records one rejection for the identified catalyst and can reconsider the still-valid
mechanical setup after the event-risk state clears. A later accepted entry still
requires closed-bar acceptance and occurs at the next bar; the macro bias never
creates the entry by itself. The blackout can be disabled only as an explicit,
stored research-control parameter.

The first 25-day sample looked positive, but the expanded observed interval
correctly falsified that headline. Latest like-for-like IC Markets diagnostic,
2026-04-18 14:05 UTC through 2026-07-23 08:15 UTC:

| Mode | Candidates | Trades | Wins | Net PnL | Expectancy | Profit factor | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| price-only control, 1.5 ATR / 2.0R | 38 | 38 | 11 | -744.37 USD | -0.202 R | 0.715 | 12.65% |
| V2 gate, 1.5 ATR / 2.0R | 38 | 18 | 6 | -120.70 USD | -0.070 R | 0.901 | 6.29% |
| provisional V2, 2.0 ATR / 1.25R | 38 | 18 | 11 | +549.78 USD | +0.322 R | 1.735 | 3.94% |

The control, default V2, and provisional runs are
`576dbb20-685f-420e-bc1d-3aa349e4c983`,
`f257b985-c245-44d1-bfbf-728a33b35ddb`, and
`46103443-8d74-4ad8-8a99-2f5250aaef69`. The provisional result is not a promoted
strategy: only 18 trades survived, all were shorts, its parametric interval is
`[-0.200, +0.844] R`, and its deterministic bootstrap interval is
`[-0.181, +0.822] R`. Both include zero.

The engine now emits deterministic bootstrap expectancy intervals, monthly,
regime, side, year, and signal-hour slices, plus a seeded realized-trade-order
Monte Carlo. The provisional run's 95th-percentile reshuffled drawdown is 4.29%.
This diagnoses sequence risk only; it does not preserve regime clustering or
manufacture unseen market paths.

Parameter sensitivity found a broad positive region rather than one isolated best
cell: with a 1.5-ATR stop, 1.0R–1.5R targets were positive; with a 1.25R target,
1.25–3.0 ATR stops were broadly positive. Because this region was inspected on the
same short dataset, it is a hypothesis for walk-forward testing, not an
out-of-sample result. Historical MT5 schedules, actuals, and release-boundary
consensus are now loaded, but their event-conditioned results have not yet passed a
locked walk-forward evaluation. Real quarterly SOFR path snapshots are now
connected, while exact historical CME meeting snapshots remain unavailable.
Neither a catalyst-blackout edge nor a Fed-path edge is claimed.

The provisional point stayed positive at 1.5x modeled costs
(`99d8d576-aee6-4dee-8fc2-00caff13a803`: +502.31 USD, +0.296 R) and 2.0x costs
(`072acc4b-0c78-4644-8fef-ebe5a7041aa1`: +454.84 USD, +0.270 R). Removing its
best one and best two trades left +426.20 USD and +303.62 USD respectively. These
are in-sample stress checks; the locked holdout remains unevaluated.

## 14. Implemented event-study engine

The event-study API now executes the algorithm in section 5 against immutable
one-minute XAUUSD bars. For each original release it:

1. selects the latest forecast that was both timestamped and available no later
   than the release;
2. standardizes the surprise using only earlier same-component surprises, with a
   documented fallback scale until five prior observations exist;
3. selects the last complete minute at or before release as the reference;
4. calculates 1m, 5m, 15m, 1h, 4h, and 17:00 New York reaction horizons;
5. records return, direction alignment, MFE, MAE, and first-move continuation or
   reversal; and
6. preserves missing consensus, stale reference prices, and missing horizons as
   explicit exclusions.

Each run declares `study_as_of` and exactly one data mode. A real-data run cannot
see synthetic events or bars, and a synthetic run cannot see real events or bars.
The Events dashboard exposes both bundle upload and event-study controls. The
MetaQuotes archive supplies release-boundary consensus for post-release studies;
because first-publication times are unavailable, those historical forecasts are
never exposed to pre-release decisions.

## 15. First real quarterly-expectations experiment

The Atlanta Fed MPT history is now part of the `REAL_ONLY` fundamental evaluator.
At every simulated decision, a quarterly SOFR distribution is usable only after
its conservative next-US-business-day availability time. The engine uses the four
nearest windows with probability surfaces to calculate path level and daily
repricing. It records that these are quarterly SOFR expectations—not exact FOMC
meeting probabilities—and never loads the synthetic policy-path fixture.

A like-for-like observed IC Markets experiment from 1 March through 29 June 2026
produced:

| Mode | Candidates | Trades | Long / short | Net PnL | Expectancy | Profit factor | Max DD |
|---|---:|---:|---:|---:|---:|---:|---:|
| Price-only control | 46 | 46 | 19 / 27 | -690.75 USD | -0.148 R | 0.783 | 13.51% |
| Real fundamental gate | 46 | 20 | 4 / 16 | -277.97 USD | -0.158 R | 0.798 | 6.37% |

The real-data gate reduced exposure and drawdown but did not create positive
expectancy. Its deterministic bootstrap 95% expectancy interval is
`[-0.758, +0.445] R`, which includes zero. Run IDs are
`9a1ec9f0-89db-4869-9c77-92a3423a491c` (control) and
`852b8174-435f-4c80-9c08-898a5358d8ef` (fundamental). This is evidence against
claiming an edge for the current entry/exit rule; it is not a reason to tune on
this same interval until it turns positive.

## 16. Untouched historical falsification and broker-session correction

The expanded IC Markets archive revealed that ordinary 2021–2023 trading days
often resume at 10:02–10:04 Tokyo after daily broker maintenance. The former
10:00 Asia-range boundary therefore made otherwise sound days fail the strict
completeness check. Version 1.3.0 uses configurable boundaries with a 10:05
default. It never forward-fills the unavailable maintenance minutes and still
excludes any day missing a bar within the selected 10:05–16:00 range.

The frozen default rule was then run on the previously uninspected 1 April through
29 July 2023 interval:

| Mode | Candidates | Trades | Long / short | Net PnL | Expectancy | Profit factor | Max DD | Bootstrap 95% interval |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Price-only control | 61 | 61 | 29 / 32 | -2,397.23 USD | -0.442 R | 0.534 | 24.32% | [-0.792, -0.093] R |
| Real fundamental gate | 61 | 20 | 10 / 10 | -1,166.82 USD | -0.615 R | 0.399 | 13.31% | [-1.144, -0.023] R |

Run IDs are `723adeee-e1c4-4d86-9033-c9a33b7e1fc8` and
`442c036c-bbce-4a5e-bcc2-71bc43d10d10`. Both intervals exclude zero on the
negative side. This rejects the current Asia/London acceptance candidate and
preserves the remaining history for a separately specified, event-driven
research hypothesis.
