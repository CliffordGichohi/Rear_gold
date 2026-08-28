# Gold Coherent-Auction Blind Validation Contract V1

Status: `APPROVED_AND_FROZEN_BEFORE_VALIDATION_VALUE_MATERIALIZATION`

Authorization: the user approved continuation after reviewing the matched-human calibration and its explicitly labelled hindsight ceilings. This is a new blind historical-robustness branch. It does not alter any prior result or convert calibration evidence into validation credit.

## 1. Question

Can the user's six-step auction process produce a positive, economically usable result on fresh replay cases when direction, entry, invalidation, and target are chosen using only information visible at the decision timestamp?

The process is:

1. Read point-in-time macro/fundamental context.
2. Locate price relative to pre-existing higher-timeframe structure and liquidity.
3. Classify the current auction family rather than forcing every chart into trend continuation.
4. Wait for an observable M15 transition or lower-timeframe response.
5. Invalidate at the structure that actually controls the entry.
6. Target the next opposing H1 liquidity area.

The study is a falsification test. The matched replay result of `+1.79318807R` is calibration evidence only. The hindsight direction and MFE figures are ceilings, not achieved returns.

## 2. Preserved evidence and locks

- All prior contracts, failures, rejections, reports, source artifacts, and seals remain unchanged.
- The 30 matched Human/Codex dates from 2022-01-03 through 2022-02-16 are exposed and permanently excluded.
- Every date opened in earlier practice, Codex, engineering, or matched-human work receives zero credit here.
- Calendar 2025 and calendar 2026 remain locked.
- No source acquisition, paid request, or charge is permitted.
- Aggregate results remain hidden until the complete initial block is sealed.

## 3. Frozen initial population

- Source universe: the already sealed, outcome-blind V1.1 scored-session registry and sealed Gold Casebook V0.1 sources.
- Calendar: 2022 only, strictly after 2022-02-16.
- Sessions: exactly 25 London and 25 New York sessions.
- Selection: retain the existing V1.1 outcome-blind randomized order within each session; select the first 25 metadata-eligible cases per session after exclusions.
- Eligibility uses timestamps and lineage only: at least 95% observed XAUUSD M1 close coverage from session start through session end, unique ordered timestamps, point-in-time availability, and required context lineage.
- The exact 50 identities, order, aliases, coverage counts, hashes, and exclusions must be sealed before price values are materialized.
- These are historical blind-operator robustness cases, not independent market validation, because the underlying year exists inside the broader development archive.

## 4. Information visible to the operator

At a shared one-way replay cursor, the interface may display only completed and available:

- weekly, daily, H4, H1, M15, M5, and M1 candles;
- point-in-time fundamental score, components, confidence, regime, contradictions, and scheduled/released event information;
- pre-existing session levels and time windows;
- drawings created by the operator;
- the operator's pending or active order state.

It must not expose future bars, future extrema, realised direction, MFE/MAE, final archetype, hidden outcomes, or aggregate performance. Timeframe changes must share the same replay cursor. Rewind is prohibited.

## 5. Frozen decision taxonomy

Every submitted trade must record one observable auction family:

- `CONTINUATION_WITH_ROOM`
- `RANGE_ROTATION`
- `STRUCTURAL_REPAIR`
- `OTHER_EXPLICIT`

Every trade must also record:

- controlling H4 state: `PULLBACK_WITH_ROOM`, `BALANCE_LOWER_ROTATION`, `BALANCE_UPPER_ROTATION`, `UPPER_BOUNDARY_EXTENDED`, `LOWER_BOUNDARY_EXTENDED`, `BEARISH_DAMAGE`, `BULLISH_DAMAGE`, `ACCEPTED_REPAIR`, or `UNKNOWN`;
- location assessment: `DISCOUNT`, `MIDRANGE`, `PREMIUM`, `AT_SUPPORT`, `AT_RESISTANCE`, or `UNKNOWN`;
- stop basis: `ACTIVE_M15_PROTECTED_SWING`, `CONTROLLING_M15_RANGE_BOUNDARY`, `POST_REPAIR_ORIGIN`, or `OTHER_EXPLICIT`;
- target timeframe: exactly `H1_OPPOSING_LIQUIDITY`;
- any reason for trading against the displayed macro direction;
- thesis, completed-candle trigger, structural invalidation, target logic, event risk, and confidence.

`NO_TRADE` is valid and must be retained. The application permits no more than one submitted order per session case.

## 6. Frozen execution

- Account reference: $10,000.
- Maximum planned loss: $50 per case.
- Quantity: whole ounces, floored from `$50 / |entry - stop|`; cases unable to trade one ounce within the cap are rejected before submission.
- Order types: market, limit, or stop.
- Market and stop latency: one minute.
- Spread: source spread when available, otherwise $0.20.
- Market/stop slippage: $0.05 in the adverse direction.
- Same-bar ambiguity: stop first.
- Entry, stop, target, direction, and original reasoning are immutable after fill.
- Pending orders may be amended at the current cursor with an append-only reason.
- No pyramiding and no overlapping positions inside a case.
- Original session deadline remains the time exit.

## 7. Frozen management tracks

Every operator trade is evaluated from the same sealed entry and stop under two policies. The operator does not choose between them after seeing a path.

### Track A — H1 control

- Exit 100% at the operator's frozen H1 opposing-liquidity target.
- Otherwise exit at stop or session deadline.

### Track B — protection plus core/runner challenger

- Before target, arm protection only after the trade has first reached `+1.0R` on an observed M1 path.
- Once armed, a completed M5 close that breaks the latest confirmed opposing five-bar M5 swing by at least `0.10 × ATR(14)` exits the entire position at the next available M1 open with frozen costs.
- If the H1 target is reached first, realise 80% there.
- Retain 20% only when the target-touch M15 candle closes beyond the target in the trade direction by at least `0.10 × ATR(14)`; otherwise close 100% at target.
- The retained 20% trails the latest confirmed protected five-bar M15 swing with a `0.10 × ATR(14)` buffer and exits on the first stop touch or session deadline.
- Swing confirmation, ATR, break, and acceptance use completed candles only. No future-formed pivot may be used.

Track B is a single preregistered challenger, not a parameter search.

## 8. Initial-block evaluation

The 50 cases form one indivisible initial block. No aggregate PnL, hit rate, failure attribution, or parameter feedback may be inspected before all cases are completed.

Report separately for London, New York, and combined:

- cases, trades, no-trades, and trades per month;
- direction accuracy as a diagnostic, not an edge claim;
- win rate, net R, expectancy, profit factor, average win/loss, maximum drawdown, and dollars at $50/R;
- planned versus actual risk and cost contribution;
- stopped-then-directionally-correct cases;
- H1-target capture and runner contribution;
- results by auction family, H4 state, location, stop basis, and macro alignment;
- calibration by confidence band;
- chronological-half and monthly stability;
- Track A versus Track B on identical trades.

## 9. Frozen dispositions

`PROVISIONAL_PASS` requires all of:

- at least 20 executed trades;
- positive combined net expectancy after costs;
- profit factor at least 1.10;
- positive result in both chronological halves;
- neither London nor New York contributes more than 80% of positive gross R;
- result remains positive at 1.5× frozen variable costs;
- no integrity or future-leakage failure.

`REJECT` applies if the combined expectancy is non-positive, PF is below 1.00, or an integrity failure invalidates the branch. Otherwise the result is `INCONCLUSIVE`.

A provisional pass does not establish a production edge. It authorizes one second blind 50-case block under unchanged rules, followed by prospective paper tracking. No 2025/2026 opening is authorized by this contract.

## 10. Engineering and audit requirements

- Preserve raw sources unchanged and verify predecessor hashes before materialization.
- Materialize primary and independent-reference replay streams and require value, identity, schema, diagnostic, and byte equality.
- Store decisions and lifecycle events in a new append-only, fsynced, hash-chained ledger isolated from all prior ledgers.
- Preserve the exact visible-state hash with each decision.
- Browser tests must prove one-way time, cross-timeframe synchronization, editable pending geometry, immutable filled geometry, working drawing deletion/resizing, order/no-trade persistence, and absence of future bars.
- Stop on source-seal failure, non-reproduction, future leakage, or potential charge.

