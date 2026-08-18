# Daily London and New York Playbook Research

## 1. Objective and constraint

This research expands Candidate C1 from one rare setup into a portfolio of
transparent session playbooks. The commercial hurdle requested by the user is an
average 1,000 USD per month on 10,000 USD capital. That is a 10% average monthly
return and is treated as an aggressive evaluation hurdle, not a target that rules
may be tuned to manufacture.

The research must report the return, trade frequency, drawdown, costs and
uncertainty actually supported by the data. It may reject the hurdle.

## 2. Research partition

| Period | Role |
|---|---|
| 2021-08-01 through 2023-12-31 | Discovery and transparent cohort research |
| Calendar year 2024 | Development forward check; no rule replacement after inspection |
| Calendar year 2025 | Locked validation; inaccessible until a complete portfolio is frozen |
| 2026 | Previously inspected robustness data; not a pristine holdout |
| Future sessions | Prospective paper/live holdout |

The 2024 aggregate session frequencies were inspected before strategy PnL, so it
is a forward development check rather than a pristine holdout. No 2025 Candidate
C1 or daily-playbook result has been calculated.

## 3. Common clocks and evidence

- Asian range: 10:05-16:00 `Asia/Tokyo`.
- London research window: 08:00-12:00 `Europe/London`.
- New York research window: 08:00-12:00 `America/New_York`.
- Bars: earliest complete one-minute versions available by bar close, aggregated
  into complete five-minute bars.
- Reference levels: Asian high/low initially; previous day/week and confirmed
  higher-timeframe levels are later cohorts.
- Threshold normalization: five-minute ATR(14), known at signal close.
- Entry: next contiguous five-minute bar open after a completed signal.
- Same-bar stop and target: stop first.
- Transaction costs: observed entry/exit broker spread, 0.05 USD/oz adverse
  slippage per side, and 7 USD/lot round-turn commission.
- Missing bars or spread: explicit exclusion, never forward-filled.

Every complete day stays in the denominator. A daily range visible after the fact
is not treated as an available trade.

## 4. Frozen initial playbooks

These are base hypotheses, not optimized final rules.

### P1: London acceptance continuation

1. London breaches one Asian boundary.
2. Two consecutive five-minute closes remain beyond that boundary.
3. The second acceptance bar has a directional body of at least 0.25 ATR, a
   body/range ratio of at least 0.55, and a close-location score of at least 0.65.
4. Enter next bar in the breakout direction.
5. Invalidate 0.15 ATR inside the Asian boundary.
6. Target 1.50R; maximum hold 240 minutes.

### P2: London accepted-breakout retest

1. P1 acceptance occurs.
2. Within the next eight bars, price touches a 0.15 ATR boundary zone and closes
   back beyond the boundary.
3. The retest response has at least a 0.15 ATR directional body, 0.50 body/range
   ratio and 0.60 close-location score.
4. Enter next bar.
5. Invalidate beyond the retest extreme plus 0.10 ATR.
6. Target 2.00R; maximum hold 240 minutes.

### P3: London sweep/rejection reversal

1. London breaches an Asian boundary.
2. Price closes back inside within two complete bars.
3. The reclaim or one of the next three bars displaces through the preceding
   three-bar micro structure with at least 0.25 ATR body, 0.55 body/range ratio
   and 0.65 close-location score.
4. Enter next bar opposite the sweep.
5. Invalidate beyond the sweep extreme plus 0.10 ATR.
6. Target 1.00R; maximum hold 240 minutes.
7. Same-bar and delayed reclaim remain separate cohorts.

### P4: New York confirmation continuation

1. The London morning closes beyond an Asian boundary.
2. The first 30 New York minutes define an opening range while price remains on
   the accepted side.
3. Before 10:30 New York, a directional bar closes beyond the opening range with
   at least 0.25 ATR body, 0.55 body/range ratio and 0.65 close-location score.
4. Enter next bar in the London direction.
5. The opening-range midpoint is the invalidation.
6. Target 1.50R; maximum hold 180 minutes.

### P5: New York handover rejection

1. The London morning closes beyond an Asian boundary.
2. Before 10:00 New York, price closes back inside the Asian range.
3. The rejection bar displaces through the preceding three-bar micro structure
   with the same 0.25/0.55/0.65 requirements.
4. Enter next bar opposite the London direction.
5. Invalidate beyond the New York session extreme plus 0.10 ATR.
6. Target 1.50R; maximum hold 180 minutes.

### P6/P7: multilevel delayed reclaim

The original C1 control found that delayed reclaims behaved differently from
same-bar reclaims. The multilevel extension preserves that distinction and adds
levels that were already knowable before the session:

- London: Asian high/low, rolling prior-24-hour high/low, and rolling prior-five-
  day high/low.
- New York: London high/low, Asian high/low, and rolling prior-24-hour high/low.

A valid delayed reclaim must close outside a level on the sweep bar, close back
inside on the following complete five-minute bar, and then displace through the
preceding three-bar micro structure within three bars. The stop remains beyond
the excursion plus 0.10 ATR. Same-bar reclaims are excluded rather than blended
into the cohort. Levels within 0.25 ATR on the same side are recorded as
confluence, not double-counted as separate trades. The first valid signal per
session is the control; broad-USD alignment is a separate fundamental cohort.

### Intraday USD confirmation cohort

IC Markets EURUSD one-minute bars are an observed, executable-market proxy for
intraday USD pressure. They are not relabelled as the licensed DXY. At a gold
signal close:

- rising EURUSD confirms a long-gold/weak-USD thesis;
- falling EURUSD confirms a short-gold/strong-USD thesis; and
- 15-minute and 60-minute confirmation clocks use completed EURUSD bars only.

The 15-minute, 60-minute, both-clock, daily-broad-USD, and daily-plus-intraday
cohorts are evaluated symmetrically. Intraday confirmation is a Layer 6 gate; it
cannot create a gold entry without a Layer 5/7 price trigger.

### P8: cross-market trapped-breakout fade

P8 is a materially different hypothesis from P1, not a relabelled losing trade.
After P1's two completed closes outside the Asian boundary, EURUSD must confirm
the opposite gold direction over a completed 15-minute or 60-minute clock. Entry
is still the next gold five-minute open, but the side is opposite the breakout.
Invalidation is beyond the two-bar acceptance extreme plus 0.10 gold ATR. The
centre target is 1.00R, the maximum hold is 180 minutes, and the
0.75R/1.00R/1.25R neighbourhood is reported. Without the cross-market
contradiction it remains a research control, not an execution signal.

### P9-P11: macro session-drift execution family

The point-in-time target-validity audit is diagnostic evidence, not a trade. It
found that the production engine's dominant-driver direction had a positive mean
signed London-open-to-New-York-close move in each 2021-2024 annual slice, while
every annual uncertainty interval still crossed zero. The following executable
family is frozen before its P&L is calculated:

- P9 macro session carry: require an absolute pre-London production score of at
  least 10, take the score direction, observe the first London five-minute bar,
  enter the next bar, invalidate beyond the opposite Asian boundary plus
  0.10 five-minute ATR, and otherwise exit at the New York research-window close.
  It has no profit target; a 1.00R and 1.50R cap are reported only as declared
  neighbourhoods.
- P10 macro London opening-range continuation: use the same frozen bias, define
  the first 30 London minutes, and require the first bias-direction close beyond
  that range before 10:30 London. The breakout bar must have at least a
  0.20-ATR body, 0.50 body/range ratio, and 0.60 close-location score. Entry is
  next bar, the opening-range midpoint is invalidation, the centre target is
  1.50R, and the trade cannot outlive the New York research-window close.
- P11 macro adverse-auction reclaim: use the same frozen bias, require at least
  0.50 ATR of adverse movement from the London open, then a completed bar that
  reclaims the London open in the bias direction and displaces through the prior
  three-bar micro structure before 10:30 London. Entry is next bar, invalidation
  is beyond the adverse session extreme plus 0.10 ATR, the centre target is
  1.50R, and the trade cannot outlive the New York research-window close.

For each playbook, completed 60-minute EURUSD confirmation is reported as a
predeclared Layer 6 cohort, not silently made mandatory. The central rule is
evaluated on 2021-08 through 2022 discovery, calendar-2023 validation, and
calendar-2024 development-forward data. Calendar 2025 remains unopened. A
positive average alone cannot qualify the family: it must meet the portfolio
boundary in section 7 after observed spread, slippage, and commission.

London expansion relative to its prior 20-session median, Asian compression,
volume, spread percentile, fundamental alignment, event proximity, regime and
driver are recorded as cohorts. They are not initial gates.

## 5. Frozen post-event New York playbooks

This family uses only information available after the release. Historical MT5
consensus is not claimed to have been known before release; it becomes eligible
at the stored release boundary, and every entry occurs after that boundary.

Simultaneous releases are treated as one macro-information set. Supported
components receive fixed economic weights, their configured gold directions are
aggregated, and disagreement reduces the composite rather than being hidden.
The minimum composite magnitude is 0.25 and the minimum component-agreement ratio
is 0.35.

- E1 five-minute event acceptance: the first five complete minutes move in the
  composite fundamental direction and accept beyond the pre-event 15-minute
  range; entry is the next minute.
- E2 accepted-event retest: after E1 acceptance, price retests the broken
  pre-event boundary within 15 minutes, holds it on a directional close, and
  enters on the following minute.
- E3 event continuation breakout: after aligned initial acceptance, price breaks
  the first five-minute reaction range during minutes 6-20; entry is the next
  minute.
- E4 first-move reversal: the first minute contradicts the fundamental composite,
  then price reclaims the pre-release reference in the expected direction within
  ten minutes and confirms with displacement; entry is the next minute.
- E5 event dual confirmation: the five-minute gold reaction and the simultaneous
  EURUSD reaction both confirm the surprise direction with at least 0.75 of
  their own pre-event one-minute ATR; entry is minute six.
- E6 USD-led gold catch-up: EURUSD confirms the surprise direction during the
  first five minutes while gold has not; gold then reclaims the pre-release
  reference with directional displacement by minute ten; entry is the next
  minute.

All four use the exact observed spread, 0.05 XAUUSD price-unit slippage per side,
7 USD per lot round-turn commission, stop-first ordering for ambiguous one-minute
bars, and 1.0R/1.5R/2.0R target-neighbourhood checks. E1/E3/E4 use 1.5R centres;
E2 uses a 2.0R centre. The full book candidate still requires intraday rates and
USD confirmation; this reduced candidate reports those inputs as unavailable and
tests whether fundamental surprise plus gold-price acceptance has standalone
value.

## 6. Development reporting

Each playbook reports:

- complete sessions, candidates, exclusions and trades;
- trades and expectancy by year, month, direction and session state;
- gross/net expectancy, win rate and profit factor;
- MFE, MAE and holding time;
- spread, slippage and commission;
- maximum drawdown and consecutive losses;
- bootstrap expectancy interval;
- average/median monthly R and percentage of positive months;
- 0.50%, 1.00% and 1.50% risk-per-trade capital paths;
- performance at 1.50x and 2.00x costs; and
- dependence on the best trades and dominant regime.

The initial target neighbourhood is `1.00R`, `1.50R`, and `2.00R`; the base target
above remains the centre. Results from neighbouring cells diagnose fragility and
cannot silently replace the base.

## 7. Portfolio boundary

Individual playbooks are evaluated first. A combined portfolio is frozen only
after discovery and must:

- resolve simultaneous signals with a predeclared priority;
- permit at most one open XAUUSD position;
- risk no more than 1.00% per trade during research;
- stop new entries after 2.00% realized daily loss;
- retain price-control and fundamental-context results separately; and
- never select a rule because it happens to meet the requested dollar output.

A development candidate requires at least 150 combined trades, positive net
expectancy in every full development year, profit factor above 1.25, positive
1.50x-cost expectancy, and no single playbook or direction contributing more than
60% of profit. The 2025 holdout remains locked until the portfolio, risk and
fundamental-resolution contracts are complete.

## 8. Evidence checkpoint — 27 July 2026

The observed pre-2025 ledger contains 826 complete sessions. London breached at
least one Asian boundary on 729 sessions (88.26%), closed outside the range on
403 (48.79%), and rejected a breach by London noon on 326 (39.47%). New York
confirmed the London outside close on 273 sessions (33.05%), rejected it on 94
(11.38%), and reversed through the other Asian boundary on 36 (4.36%). The
opportunity is real; a boundary event by itself is not an edge.

The first frozen executable family failed after observed spread, 0.05 USD/oz
slippage per side, and 7 USD/lot round-turn commission:

| Playbook | Trades | Net expectancy | Profit factor |
|---|---:|---:|---:|
| P1 London acceptance | 511 | -0.187 R | 0.726 |
| P2 accepted retest | 95 | -0.105 R | below 1 |
| P3 sweep/rejection | 425 | -0.168 R | below 1 |
| P4 New York confirmation | 169 | -0.122 R | below 1 |
| P5 New York rejection | 120 | -0.165 R | below 1 |

The original 19-trade delayed-reclaim control remained a weak lead at +0.164 R
per trade and +301.93 USD over 2023-2024, but the 442-trade multilevel extension
returned -0.089 R per trade with a 0.835 profit factor. That extension falsified
the idea that the small result generalized across known Asia, London, prior-day,
and prior-week levels.

The post-event family contained 191 real release sets. E1-E6 generated between
2 and 18 trades each; none produced stable positive evidence. E3 returned
-0.210 R, E4 -0.531 R, E5 -0.475 R, and E6 -0.273 R per trade. The two-trade E2
result is not evidence.

Observed EURUSD history added 255,140 complete five-minute bars and 1,283,406
source one-minute bars through 31 December 2024. No eligible 15-minute,
60-minute, daily-plus-intraday, or cost-aware confirmation rule was positive in
2021-2022 discovery, 2023 validation, and 2024 development-forward data. P8's
ungated trapped-breakout fade was strongly negative in all three splits:
-0.786 R, -0.809 R, and -0.997 R per trade respectively.

The target-validity audit confirms the user's opportunity premise. Across
2021-2024, median London ranges were 6.23, 7.81, 7.00, and 10.44 USD/oz; median
New York ranges were 10.31, 11.52, 10.55, and 13.95 USD/oz. The production
dominant-driver direction had a positive mean signed London-open-to-New-York-close
move in every annual slice, but directional accuracy ranged from 48.59% to
59.78% and every annual bootstrap interval crossed zero. Static pre-London
fundamentals are useful context, but not yet a statistically defensible daily
direction forecast.

The frozen P9-P11 execution results were:

| Playbook | Discovery | 2023 validation | 2024 forward | All trades / PF | Verdict |
|---|---:|---:|---:|---:|---|
| P9 macro session carry | -0.259 R | -0.332 R | +1.003 R | 457 / 1.101 | regime-dependent; reject |
| P10 macro opening range | -0.263 R | -0.271 R | -0.024 R | 317 / 0.719 | reject |
| P11 adverse-auction reclaim | -0.079 R | -0.409 R | +0.170 R | 301 / 0.850 | reject |

P9 illustrates why blended P&L is unsafe. It earned +130.41 R in 2024 and, at
1% risk, about 1,168.95 USD per active month in that slice. It lost 52.02 R in
2021-2022 and 41.88 R in 2023. The compounded full path ended at 8,852.98 USD
from 10,000 USD with 67.06% maximum drawdown even though arithmetic total R was
positive. Its 1R and 1.5R capped variants were negative in every split, and the
uncapped result became negative at 2x costs.

No playbook or cross-market cohort qualifies for a combined portfolio. The
requested 1,000 USD average month remains an aggressive research hurdle, not a
validated return expectation. Calendar 2025 has not been queried and remains
locked. The operational status is `RESEARCH / NO DEPLOYABLE EDGE / PAPER ONLY`.
