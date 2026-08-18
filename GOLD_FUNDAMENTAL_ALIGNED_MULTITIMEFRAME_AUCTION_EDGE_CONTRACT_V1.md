# Gold Fundamental-Aligned Multi-Timeframe Auction Edge Discovery Contract V1

Status: `FROZEN_BEFORE_NEW_BRANCH_OUTCOME_COMPUTATION`

## Purpose

This branch tests one bounded, book-traceable proposition:

> Does a point-in-time fundamental direction become economically tradable when
> gold reaches a level known before the decision, the completed weekly/daily/H4
> auction state does not contradict that direction, and London or New York
> confirms rejection, acceptance-and-retest, or failed acceptance?

The branch is research, not a mandate to prove the proposition. A zero-candidate
result is acceptable. Every earlier verdict and seal remains unchanged. In
particular, the rejected binary event-trigger, continuous state-response, session
state-transition, ZN-direction, and casebook candidates receive no validation
credit here.

## Epistemic boundary

- A candle is an observed OHLC summary. Its body, wick, close location, range,
  and sequence are calculated auction-response evidence, not direct order flow.
- GC MBO/MBP-10 measures anonymous futures messages and displayed book state.
  Aggression, OFI, absorption, depletion, and replenishment remain calculated or
  inferred; no institution or motive is identified.
- XAUUSD levels are compared only with XAUUSD. GC prices are never mixed with
  broker spot prices.
- Fundamentals supply directional permission, not an entry.
- Higher-timeframe state supplies context, not a trigger.
- A level and trigger supply location and invalidation, not certainty.
- Missing evidence remains `UNKNOWN`; it is never silently converted to neutral.

## Data boundary

- Development: 2021-08-01 through 2024-12-31.
- Base price/structure population: the complete existing IC Markets MT5 XAUUSD
  one-minute history and existing sealed casebook/session sources.
- Fundamental context: existing point-in-time FRED/ALFRED, MT5 calendar,
  transparent macro-engine, rates/USD, CFTC COT, and risk-market sources.
- GC incremental subset: only the existing 188 research dates and already sealed
  GC MBO/MBP-10-derived event/state artifacts. No GC acquisition is permitted.
- Engineering-only dates remain excluded: 2024-01-05, 2024-01-09, 2024-01-11,
  2024-01-30, 2024-01-31, and 2024-03-20.
- Existing 2025 and 2026 through 2026-07-29 may be opened only after development
  candidates are frozen. They are exposed historical robustness segments and
  receive no independent-validation credit.
- No paid acquisition or card charge is permitted.

## Decision clock

- London timezone: `Europe/London`.
- New York timezone: `America/New_York`.
- Session scan: completed decisions from 08:00 through 10:30 local.
- Forced exit: the earlier of 120 minutes after entry or 12:00 local.
- All local-to-UTC conversion uses the IANA timezone database.
- Weekly, daily, H4, H1, M5, and M1 evidence is eligible only after the source
  candle has completed and become available.

## Fundamental directional permission

The canonical development permission is the existing transparent reference-book
macro-engine score at session open:

- `BULLISH`: score at least +20, coverage at least 50%, confidence at least 35%.
- `BEARISH`: score at most -20, coverage at least 50%, confidence at least 35%.
- otherwise `NEUTRAL_OR_UNKNOWN` and no trade.

The score may contain real-yield, USD, 2Y, inflation, growth, labour, released
event, COT, equity-risk, nominal-decomposition, and stress components under the
existing engine. No component or weight may be fitted to outcomes in this branch.
COT is a crowding/risk modifier and never a standalone entry sign.

For exposed years, the identical engine and thresholds must be used with facts
available at the decision. If the required source coverage cannot reproduce the
permission, the session is `UNAVAILABLE_TECHNICAL`; a proxy must not be silently
substituted.

## Completed-candle higher-timeframe state

For each of W1, D1, H4, and H1, use the last completed bar and ATR14 of completed
bars. Define candle pressure:

- body sign = sign(close - open);
- close-location sign = +1 when close is in the upper third of the range, -1
  when in the lower third, otherwise 0;
- displacement sign is eligible when true range is at least ATR14 and body size
  is at least half the candle range;
- timeframe pressure is bullish when body and close-location are positive,
  bearish when both are negative, otherwise neutral; displacement is retained
  as strength evidence and does not change the sign.

`HTF_ALIGNED` requires the fundamental direction to match at least two of W1,
D1, and H4, with none of those three opposing by displacement, and requires H1
not to oppose by displacement. This is inferred auction pressure, never labelled
observed institutional flow.

## Levels known before use

Eligible XAUUSD level families are:

- completed prior-week high and low;
- completed prior-day high and low;
- completed Asia high and low;
- the two most recent confirmed H1 swing highs and lows, using strict two-left /
  two-right pivots that become knowable only when the second right bar closes;
- for New York, the completed London-to-New-York-open high and low;
- the session opening 15-minute high and low, usable only after 08:15 local.

A level expires after five trading days, except prior-day, prior-week, Asia, and
session ranges, which expire when their named period changes. Levels formed after
the decision are prohibited.

## Frozen setup families

Exactly three setup families are permitted per session.

1. `FAMAE_ALIGNED_SWEEP_RECLAIM`
   - Direction equals fundamental permission and `HTF_ALIGNED` is true.
   - A complete M1 bar trades strictly beyond an eligible support/resistance and
     that bar or the immediately following bar closes back through the level.
   - Longs reclaim lower/support levels; shorts reclaim upper/resistance levels.

2. `FAMAE_ALIGNED_BREAK_RETEST`
   - Direction equals fundamental permission and `HTF_ALIGNED` is true.
   - Two consecutive completed M5 closes accept beyond an eligible opposing
     level in the bias direction.
   - Within the next six completed M5 bars, price touches the broken level and a
     completed M5 bar closes on the accepted side in the bias direction without
     first completing two closes back inside.

3. `FAMAE_ALIGNED_FAILED_ACCEPTANCE`
   - Direction equals fundamental permission and `HTF_ALIGNED` is true.
   - Two completed M1 closes first accept through an eligible level against the
     fundamental direction.
   - Within the next five completed M1 bars, price closes back through the level
     in the fundamental direction.

Canonicalization retains only the first eligible setup per family and
session-date. Simultaneous identical-family events at multiple levels are merged.
No setup may rearm later that session.

## Frozen execution

- Signal time is the confirming candle close.
- Entry reference is the next complete M1 bar open; a missing next bar rejects
  the trade.
- Long structural invalidation is below the minimum low of the complete trigger
  sequence by 0.10 ATR20(M5); short invalidation is the exact mirror.
- Risk distance must be from 0.25 through 1.50 ATR20(M5), inclusive.
- Target is the nearest opposing eligible liquidity level known at entry that
  offers at least 1.25R. If farther than 2.50R, target is capped at 2.50R. If no
  target offers 1.25R, there is no trade.
- Stop and target are active from the entry bar. If both occur in the same M1
  bar, the stop is assumed first.
- If neither occurs, exit at the earlier of 120 minutes or 12:00 local.
- Baseline costs per ounce: $0.30 round-trip spread, $0.05 adverse slippage per
  side, and $0.07 commission (equivalent to $7 per 100-ounce lot).
- Cost stress is 1.5x and 2.0x every baseline cost.
- Account diagnostics use $10,000 starting equity and 0.5% planned risk per
  trade, 100 ounces per standard lot, 0.01 lot step, and no compounding within a
  session. R metrics remain authoritative.
- At most one base-portfolio trade per session-date is permitted: earliest
  signal, then lexical family ID as deterministic tie-break.

## GC incremental test

The base setup never requires GC coverage. On the existing 188 covered dates,
GC confirmation is true only when a sealed eligible same-direction GC event from
`FLOW_DEPTH_ALIGNMENT_ONSET`, `ABSORPTION_ONSET`, or
`FRAGILITY_FLOW_ONSET` completed in `[signal_time-5m, signal_time]`.

The underlying definitions retain the sealed W60/W900 aggression, displayed
pressure, quote OFI, depth imbalance, microprice, spread, book age, total depth,
activity, and absorption semantics. The incremental test compares confirmed and
known-unconfirmed base setups; GC absence on an uncovered date is `UNKNOWN`, not
false.

## Development evaluation

- London and New York are separate families.
- Every registered setup is evaluated; zero candidates is acceptable.
- Primary endpoint: net R under baseline costs.
- Diagnostics: gross R, win rate, average win/loss, profit factor, MFE, MAE,
  holding time, exit reason, maximum drawdown, consecutive losses, Sharpe and
  Sortino where meaningful, monthly distribution, and 1.5x/2.0x cost stress.
- Uncertainty: deterministic 5,000-resample session-date cluster bootstrap.
- Multiplicity: Holm family-wise adjustment across the three setups within each
  session; GC incremental tests form a separate family.
- Stability: 2022, 2023, and 2024; four chronological blocks; long and short;
  first-event is inherent; and parameter sensitivity is diagnostic only.
- Sensitivity cannot rescue the frozen base rule and may not create a candidate.

## Support and pass gates

A base setup needs at least 60 trades, 45 dates, 24 ISO weeks, 15 longs, 15
shorts, and 10 trades in each of 2022, 2023, and 2024. The exposed robustness
segments require at least 20 trades for a verdict; otherwise they are
`INCONCLUSIVE_SUPPORT`.

A development candidate passes only when every gate passes:

- baseline net expectancy is positive and its cluster-bootstrap 95% lower bound
  is strictly positive;
- Holm-adjusted one-sided p-value is at most 0.05;
- net profit factor is at least 1.25;
- average net win divided by absolute average net loss is at least 1.00, or the
  net win rate is sufficiently high for positive expectancy with a 10% margin
  above its empirical break-even rate;
- at least three of four chronological blocks are positive and no supported
  block is below -0.10R expectancy;
- supported 2022, 2023, and 2024 effects are positive;
- supported long and short subgroups are positive;
- 1.5x-cost profit factor is at least 1.10 and expectancy remains positive;
- no single trade contributes more than 35% of total net R;
- the $10,000/0.5%-risk path has no greater than 15% maximum drawdown.

GC adds value only if each arm meets its support floor (20 confirmed trades on
15 dates and 30 known-unconfirmed trades on 20 dates), confirmed-minus-
unconfirmed expectancy lift is positive with a strictly positive 95% lower
bound, adjusted p is at most 0.05, and confirmed net profit factor exceeds the
unconfirmed value without violating the base stability gates.

Verdicts are `PROVISIONAL_UNVALIDATED_EDGE`, `REJECT`, `SUPPORT_FAIL`, and
`INCONCLUSIVE_SUPPORT`. At most three candidates per session may advance.

## Exposed robustness and prospective policy

- Freeze all development candidates before opening 2025/2026 for this branch.
- Apply each frozen candidate once and unchanged to calendar 2025 and 2026
  through 2026-07-29.
- Report segments separately. Never pool exposed results to manufacture a pass.
- Do not retune, invert, add a filter, or change execution after viewing them.
- Initialize an append-only prospective ledger before the next eligible session.
  Never backfill a missed prospective decision.

## Reproduction, artifacts, and stop

Primary and reference implementations must agree on source identities, decision
states, levels, setup identities, entries, exits, costs, R results, support
dispositions, statistics, and canonical checksums. Every test and negative result
must be retained. The final report must say separately whether there is a
directional relationship and whether there is an economically tradable edge.

The branch stops after contract, certification, discovery, execution evaluation,
exposed robustness, prospective-ledger initialization, documentation, and seal.

