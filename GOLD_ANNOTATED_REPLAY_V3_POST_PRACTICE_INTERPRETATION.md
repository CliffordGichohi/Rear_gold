# Gold Annotated Replay V3 Post-Practice Interpretation

Status: `INFERRED_REVIEW_FROM_SEALED_ZERO_CREDIT_RESULTS`

Source: the sealed 20-day V3 post-practice diagnostic. This document does not change the recorded trades, the formal zero-credit status, or the closed 2022/2025/2026 populations.

## 1. What is directly established

Observed:

- Twenty practice days were completed.
- Thirteen market orders were submitted, filled, and resolved across thirteen traded days; seven days had no trade.
- Six trades made money and seven lost money.
- Five positions hit their target profitably, five stopped, one nominal target resolution lost money because the market fill had crossed beyond the planned target, and two reached the day-end time exit.
- Every order included all required annotation fields.

Calculated:

- Net: `+3.013R`, or `+$150.66` at the frozen $50 risk unit.
- Win rate: `46.2%`.
- Expectancy: `+0.232R/trade`.
- Profit factor: `1.365`.
- Maximum drawdown: `3.612R`, or `$180.60`.
- Wilson 95% win-rate interval: `23.2%–70.9%`.
- Completed-day cluster-bootstrap 95% expectancy interval: `-0.646R to +1.115R`.

Verdict: descriptively profitable, statistically inconclusive, and not an edge claim.

## 2. The most important behavioural hypothesis

After seeing the sealed results, one annotation-defined family stands out. It is classified post hoc and receives no validation credit.

`M15_STRUCTURE_TRANSITION_AT_LIQUIDITY_POST_HOC_V0_1` means that the original entry-trigger text explicitly described an M15/minute-15 structure switch or transition at a previous liquidity-shift point. It contains exactly:

- `V3-P-008`
- `V3-P-012`
- `V3-P-013`
- `V3-P-015`
- `V3-P-017`
- `V3-P-018`
- `V3-P-019`

Calculated behaviour:

- Support: 7 trades.
- Wins/losses: 5/2.
- Win rate: 71.4%.
- Net: `+7.705R`.
- Expectancy: `+1.101R/trade`.
- Profit factor: `5.451`.
- All seven were M15 decisions during the London–New York overlap.
- All seven achieved at least `+0.5R` favourable excursion before resolution.
- Both losing cases (`V3-P-015` and `V3-P-017`) later touched the original target after first stopping out.

The remaining six trades collectively produced `-4.692R`:

- The two Fibonacci/reversal descriptions lost `-3.612R`; one was also affected by a severe market-fill geometry failure.
- The four broad trend/liquidity descriptions produced `-1.080R`.

Inferred review: your potentially useful skill was not simply forecasting “bullish or bearish gold.” It was recognizing an auction transition on M15 at a level you considered institutionally meaningful. The deterministic structure engine often still labeled the old trend, while you annotated that structure had just switched. That explains why the mechanically “contradicting structure” segment looked unusually profitable: you may have been identifying the transition before the slower classifier confirmed it.

This is a hypothesis, not proof. It was isolated after viewing outcomes, the support is seven, and the operator was learning throughout practice.

## 3. Chronological learning effect

- First five trades: `-3.300R`.
- Last eight trades: `+6.313R`.

The later trades coincided with more consistent use of the M15 transition/liquidity narrative. This could represent genuine learning, different market conditions, chance, or all three. The practice dates are scattered across several months, so these figures cannot be converted into a monthly return.

Seven no-trade days are a positive process sign: the user did not force a trade on every visible day. No conclusion is drawn about missed trades because no-trade outcomes were not scored.

## 4. The critical market-order problem

`V3-P-002` exposed a material execution/risk issue:

- Planned short entry: `1799.62`.
- Actual one-minute-latency market fill: `1790.07`.
- Original target: `1794.51`, now on the wrong side of the actual short fill.
- Submitted planned risk: `$49.60`.
- Effective fill-to-stop exposure: `$307.44`.
- Recorded result: nominal `TARGET_HIT`, but economically `-2.397R`.

The replay correctly retained this loss; it must not be deleted. However, a target resolution should never be mistaken for a winning trade, and the planned $50 cap did not cap gap risk after submission.

Across all thirteen trades:

- Eight actual fill-to-stop exposures exceeded $50.
- Three exceeded $62.50.
- Maximum effective exposure was $307.44.

Before scored collection, the workflow must distinguish:

- `MARKET`: the entry drawing is only a reference; the next eligible fill controls actual geometry.
- `LIMIT` or `STOP`: the entry line is the requested trigger price.

A market fill that places the target on the wrong side, or raises effective stop exposure materially beyond the cap, needs an explicit frozen disposition. Options to discuss are a mandatory pre-submit warning, an immediate post-fill emergency exit, conservative quantity reserve, or using a pending order instead. This must be decided before seeing scored outcomes.

## 5. Trade-management evidence

- Five trades stopped.
- Three of those five later touched the original target.
- Four losing trades had already achieved at least `+0.5R` MFE.
- `V3-P-015` reached `+1.544R` MFE before closing at `-0.575R` and later touching target.
- `V3-P-017` reached `+0.807R` MFE before closing at `-1.156R` and later touching target.
- Mean winner capture efficiency was 75.9%.

Inferred review: target placement was not the dominant problem. The strongest unresolved issue is how to handle a valid initial response that subsequently retraces. Moving every trade to breakeven is not justified from seven cases and could damage winners. A single management policy must be frozen before the scored year—for example, hold unchanged, scratch only after a defined failure/reclaim, or protect only after a specified structure event—and compared without post-hoc intervention.

## 6. Fundamentals and confidence

Fundamental alignment did not rank outcomes in this small sample:

- User-labeled fundamental confirmation: 7 trades, `+1.018R`.
- User-labeled contradiction: 6 trades, `+1.995R`.
- System-macro confirmation: 4 trades, `+1.463R`.
- System-macro contradiction: 4 trades, `+3.528R`.
- System neutral/unknown: 5 trades, `-1.978R`.

Inferred review: the traded horizon was often minutes to hours, while the macro label described a broader regime. Several profitable trades were tactical auction reversals against the broader macro direction. The scored form should therefore distinguish:

1. Macro-regime direction.
2. Immediate release/repricing impulse.
3. Intraday auction direction.
4. Whether the trade is macro-aligned continuation or explicitly counter-macro tactical reversal.

Confidence was not properly ranked:

- Below-50% confidence: 7 trades, 57.1% wins.
- Exactly 50%: 2 trades, 50.0% wins.
- 60% confidence: 4 trades, 25.0% wins.

Mean confidence happened to be close to overall win rate, but the buckets were inverted. One confidence slider appears to mix setup quality, macro agreement, and execution quality. Those should become separate fields.

## 7. Annotation quality

Strengths:

- All required fields were completed.
- Twelve of thirteen trades named a macro driver.
- Every trade recorded event-risk awareness.
- The repeated later trigger language makes a behavioural family traceable.

Weaknesses:

- The dedicated higher-timeframe field used only generic labels such as “bullish,” “bearish,” or “range” in all thirteen cases. It did not record the timeframe, swing sequence, or precise location.
- All thirteen invalidation explanations were generic, even though the drawing stored an exact stop.
- All thirteen target explanations were generic, even though the drawing stored an exact target.
- The session field often said only “New York session.” It did not identify Asia/London highs or lows, a sweep, acceptance, rejection, overlap state, or liquidity condition.
- All event fields said `NONE_KNOWN`. The cases included trades five minutes after CPI, two hours after CPI, three hours after NFP, and seventy-five minutes after jobless claims. Two pre-release schedules were not safely available in the historical source, which is partly a data-display limitation rather than an operator error.

For scored collection, write levels as testable statements. Example:

> H4 range; M15 swept the Asia low and closed back above the prior M15 swing. Long only after a higher low. Invalid below 1772.14 on a completed M15 close. Target the London high at 1778.54. Counter-macro tactical reversal; CPI released 120 minutes ago.

## 8. Proposed discussion before opening the scored year

Do not open 2022 yet. First align on and freeze:

1. The observable definition of an M15 structure transition.
2. What qualifies as a pre-existing liquidity-shift level without hindsight.
3. Whether fundamentals are a direction rule, confidence modifier, or only a regime label for this setup.
4. A safe market/pending-order and post-fill geometry rule.
5. One management rule for favourable movement followed by structural failure.
6. Separate macro, setup, and execution confidence fields.
7. Exact invalidation and target-level annotations.
8. Automatic recent/upcoming event timing.

Then freeze the interface and decision rubric, open the complete scored year without interim performance feedback, and determine whether the seven-case hypothesis repeats across chronological quarters and realistic costs. Until that occurs, the honest result is: **promising human-process evidence, not yet a validated trading edge**.

