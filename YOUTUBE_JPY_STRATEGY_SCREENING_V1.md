# YouTube JPY Strategy Screening V1

Status: `SCREENED_HYPOTHESIS_ONLY__NOT_AUTHORIZED_FOR_OUTCOME_TESTING`

Screened on 2026-08-13 without opening repository market outcomes.

## 1. Sources and transcript identity

| Video | Published | Role | Caption rows | Caption SHA-256 |
|---|---:|---|---:|---|
| `dR8IkbrMaiQ` — *My Textbook USD/JPY Strategy That Got Me To $300K Funding* | 2025-08-13 | Detailed USDJPY example and rules | 566 | `f06921332b76e79ae4814a9707efcccd08ea2b186299bb9950ca9fabc5da77e9` |
| `BVRKEu3xi0o` — *Exposing My Exact Strategy That Got Me 6 Figures Funding* | 2024-11-28 | Earlier description of the same JPY system | 493 | `978ac63749ee0ecbcd2f315887a22aa1b2f57236b959b8ee8074822ba8c3eb09` |
| `U8R2DoNNRMo` — *How I Backtest My 6 Figure Trading Strategies In 2026* | 2026-01-05 | Backtesting tutorial using the same pullback model plus a continuation model | 1,451 | `f7a52f250be5cf1db8d42e8c10e2cf6700ccb307ade27971c7146ba2647a1328` |

The hashes identify the public automatic-caption payloads used for this screening. They do not imply that the captions are author-supplied or error free.

## 2. Deduplication verdict

These links do **not** contain three independent strategies.

- Videos 1 and 2 describe the same JPY trend/pullback/W-pattern/neckline-retest family.
- Video 3 repeats that pullback family and adds a range-breakout/retest continuation entry. The creator explicitly says the tutorial omits other confluences and is not a complete recommended strategy.
- The common family overlaps the repository's rejected pullback, multi-timeframe continuation, break-retest and sequential-confirmation branches. Its potentially novel part is the instrument-specific combination of long-horizon JPY direction, previous-day directional persistence, daily support/resistance location, selected news exclusions and a fixed intraday timing/risk template.

Treating the three videos as three tests would be duplicate-count inflation.

## 3. Common observable rule skeleton

The following is stated consistently enough to form a hypothesis skeleton:

1. Trade JPY crosses, with USDJPY emphasized.
2. Determine one long-term direction from a zoomed-out daily chart; ignore the opposite direction.
3. Require the previous completed daily candle to close in the chosen direction.
4. Prefer a previous-day reaction from daily support/resistance; a level is described as valid after at least three historical touches.
5. On M15, wait for a meaningful pullback against the chosen direction after an impulse.
6. Pullback entry model: identify a W for longs or the symmetric M for shorts, wait for a neckline retest, and require the immediately preceding completed H1 candle to agree with the trade direction.
7. Video 3's additional continuation model: identify an M15 consolidation, require a directional candle-body breakout, and enter on the first retest.
8. Trade from 06:00 East Africa Time; Video 2 supplies an upper bound of 20:00 EAT.
9. Avoid selected high-impact releases. CPI, PPI and policy-rate decisions are common exclusions; NFP is mentioned inconsistently, including one reference to avoiding the complete NFP week.
10. The detailed USDJPY execution uses a 15-pip stop, 45-pip target and break-even after +20 pips. Video 3 uses roughly 15 pips and 3.5R for GBPJPY and does not present this as the complete strategy.
11. Video 3 additionally requires long entries above the previous day's open, uses the symmetric condition for shorts by implication, and excludes Fridays.

## 4. Claims that are not independently verified evidence

The videos report funding, payouts, selected journal summaries, approximate win rates and annual or monthly returns. They do not provide a complete immutable trade ledger, timestamped rule version, raw broker export or independently audited account statement sufficient to reproduce those claims. The material was published after 2021 and appears to have been developed using years overlapping the repository's 2021–2024 history.

Accordingly:

- the claims are hypothesis-generation evidence only;
- 2021–2024 can replicate or falsify the translated rule but cannot independently validate it;
- already exposed 2025/2026 results can supply robustness evidence only;
- genuine independent evidence must be prospective after a final freeze.

## 5. Missing definitions blocking an exact replication

| Item | What is stated | What remains undefined |
|---|---|---|
| Long-term trend | Zoom out on daily and choose one direction | Lookback, structural algorithm, tie/neutral state and exact update rule |
| Daily level | At least three touches; use a line or zone | Pivot definition, lookback, zone width, touch tolerance, minimum separation and broken-level handling |
| Bounce | Prior candle reacts from support/resistance | Required penetration, close location, wick/body rule and tolerance |
| Impulse | Use the most recent significant move | Minimum size, candle count, efficiency and pivot boundaries |
| Significant pullback | Visually proportionate; 50% Fibonacci is illustrative, not a rule | Exact depth, duration and invalidation |
| W/M pattern | Group runs of same-direction candles; start and finish beyond neckline | Minimum legs, pivot ties, maximum duration, symmetry, minimum excursion and invalidation |
| Neckline retest | Touch the neckline or an expanded zone | Zone width, entry price, order activation, order expiry and gap treatment |
| Consolidation | Small/ranging candles before breakout | Window, range/ATR threshold, overlap and maximum width |
| Breakout/retest | Body close outside range, then retest | Break buffer, retest tolerance, expiry and competing pattern policy |
| News exclusion | CPI/PPI/rates, sometimes NFP or NFP week | Currency scope, full-day versus time window, revisions/speeches and exact calendar source |
| Trade count | Examples usually show one setup | Maximum attempts/day, simultaneous JPY exposure and rule when both models trigger |
| Exits | Fixed stop/target and sometimes break-even | Pending-order expiry, day/time exit, spread-side triggering and weekend handling |
| Instrument transfer | Parameters may differ by JPY pair | Exact pair-specific stops, targets and permission to alter them |

Because these choices materially alter outcomes, silently choosing favourable definitions after looking at data would not replicate the videos.

## 6. Screening dispositions

| Candidate interpretation | Disposition | Reason |
|---|---|---|
| Three independent video strategies | `REJECT_DUPLICATE_COUNTING` | They are one core family, not three independent ideas. |
| Exact replication of the creator's claimed results | `NOT_REPRODUCIBLE_FROM_PUBLIC_RULES` | Critical detection and execution definitions plus the claimed trade ledger are unavailable. |
| GBPJPY tutorial model | `DEFER` | The creator says confluences are omitted; it would also require a new free MT5 source. |
| USDJPY common-core hypothesis | `ADVANCE_TO_PREOUTCOME_TRANSLATION` | Existing sealed USDJPY M1 and event data are adequate, the pair is the clearest stated application, and no paid acquisition is needed. |

## 7. Recommended bounded next study

Test exactly one hypothesis family on USDJPY. Before opening outcomes, freeze one value-blind deterministic mapping for every undefined term above. Then use an early-stop waterfall:

1. **Premise test:** determine whether long-horizon direction plus previous-day alignment and the stated news exclusions predict same-direction intraday first passage or displacement at all.
2. **Location increment:** measure whether a point-in-time three-touch daily level and prior-day bounce add value.
3. **Trigger increment:** only if the contextual premise survives, test the frozen M15 W/M neckline-retest trigger and H1 confirmation.
4. **Economics:** only if the trigger has a positive raw relation, apply the published 15-pip stop, 45-pip target, +20-pip break-even, spread, slippage and one-percent risk.
5. **Continuation model:** treat the range-break/retest model as a separate secondary candidate, not an undocumented rescue for the pullback model.

The study must report each retention step. It must stop the family when an upstream premise fails rather than mining alternative thresholds. It may not claim to reproduce the creator's private strategy; it tests a transparent, preregistered translation of the public hypothesis.

No repository market outcome was accessed and no candidate was tested during this screening.
