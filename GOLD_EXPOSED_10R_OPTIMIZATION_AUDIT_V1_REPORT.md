# Gold Exposed 10R Optimization Audit V1

Status: `COMPLETE_EXPOSED_HYPOTHESIS_GENERATION_ZERO_VALIDATION_CREDIT`

No fresh date was opened. This audit uses only the already-exposed 2022-01-03
through 2022-02-16 and 2022-03-01 through 2022-05-31 streams. Results are
post-hoc candidate evidence, not a validated edge.

## Verdict

The existing 28-trade stream can be improved materially, but it cannot be
honestly optimized to 10R/month by trade management alone.

The best bounded global policy among the 54 exposed management combinations
was:

- keep the existing entries and structural stops;
- require the existing actual-fill 1.50R room gate;
- take the full position at the nearer of the existing target and 2.00R;
- do not move the full position to break-even before target;
- do not use a runner.

This policy produced 18.096941R across five calendar-month blocks, or
3.619388R/month. It is the exposed candidate, not a live policy.

## Result comparison

| Result | Trades | Win rate | Net R | R/month | PF | Max DD R |
|---|---:|---:|---:|---:|---:|---:|
| Corrected Router V1-R1 control | 28 | 50.00% | +10.789857 | +2.157971 | 2.3292 | 3.3361 |
| Best exposed management: fixed 2R/no pre-target BE | 28 | 64.29% | +18.096941 | +3.619388 | 3.2293 | 3.3361 |
| All 38 control signals under the same fixed-2R management | 38 | 60.53% | +17.965465 | +3.593093 | 2.4362 | 4.4838 |
| Frozen bidirectional raw-M15 expansion | 90 | 36.67% | -18.888756 | -3.777751 | 0.4717 | 21.1849 |

Best-policy monthly R was:

- January: +5.907518R
- February through the exposed cutoff: +6.397296R
- March: +0.971334R
- April: +5.656395R
- May: -0.835601R

The neighboring global targets remained profitable but weaker:

- 1.50R target: +15.900743R total / +3.180149R per month
- 2.50R target: +13.256927R total / +2.651385R per month

The exact 2.00R optimum was selected post-hoc and therefore carries selection
bias despite the profitable neighboring values.

## Where the 7.307084R improvement came from

| Path class | Trades | Control R | Fixed-2R R | Change R |
|---|---:|---:|---:|---:|
| Profitable excursion recovered by removing premature protection | 4 | ~0.0000 | +7.4497 | +7.4497 |
| Winners under-retained by the original management | 4 | +5.6536 | +7.2780 | +1.6244 |
| Strong winners truncated by the 2R cap | 4 | +8.6992 | +6.9322 | -1.7671 |
| Stable winners | 6 | +4.5549 | +4.5549 | 0.0000 |
| Early/clean invalidations | 5 | -3.8683 | -3.8683 | 0.0000 |
| Failures after a partial favorable move | 4 | -3.2771 | -3.2771 | 0.0000 |
| High MFE but stop occurred before 2R | 1 | -0.9725 | -0.9725 | 0.0000 |

The four premature-protection cases were 2022-01-21, 2022-01-24,
2022-04-06 and 2022-05-10. Their favorable excursions ranged from 1.9404R to
3.7043R before the original full-position break-even logic later scratched
them. This is the clearest correctable execution defect.

The five early/clean invalidations are not exit-management mistakes. They did
not first offer enough favorable excursion for the 2R policy. Removing or
resizing them from this exposed sample would be outcome filtering.

## Why the same 28 trades cannot supply 10R/month

- Their combined post-entry MFE was 45.1273R, an impossible perfect-peak
  ceiling of only 9.02546R/month.
- Therefore even a hindsight exit at every individual peak cannot reach
  10R/month from these 28 trades.
- All 38 original control trades had a perfect-peak ceiling of 10.91762R/month,
  but reaching 10R would require capturing more than 91% of every peak while
  also avoiding first-passage stops. The executable fixed-2R result was only
  3.59309R/month.
- The ten setups excluded by the corrected router contributed -0.190053R as a
  complete group under fixed-2R management. Loosening admission is not the
  missing capacity.

At the observed 0.646319R expectancy, approximately 15.47 trades/month are
required for 10R/month. The candidate currently produces 5.6 trades/month.
It therefore needs roughly ten additional trades per month of comparable
quality, not more risk on the same trades.

At 1% account risk, the exposed candidate implies approximately $361.94 per
month on a $10,000 account. Sizing the same stream to $1,000/month would
require approximately 2.76% account risk per setup. That violates the prior
risk limit and is not an acceptable optimization.

## What the bidirectional capacity test established

The current autonomous translator is structurally narrow: all 28 corrected
trades were LONG, 27 were New York, and one was London. Its semantic tree was
trained on sixteen positive LONG operator timestamps and has depth 27 with 59
nodes, so it is not a valid short-side translator.

A frozen symmetric capacity scan therefore tested every new M15 transition in
both directions and both sessions using explicit structural invalidation,
active liquidity, the 1.50R room gate and the fixed 2R target. It found enough
frequency--90 trades or 18/month--but lost in every broad segment:

- London LONG: -2.302767R
- London SHORT: -3.448187R
- New York LONG: -7.414640R
- New York SHORT: -5.723161R

Only nine of the profitable stream's 28 session trades coincided with a fresh
M15 transition selected by the capacity scan. Most profitable decisions came
later, after internal auction state had developed. The capacity failure thus
rejects indiscriminate transition entry, not bidirectional auction trading.

## Optimization decision

Freeze the following as the only management candidate carried forward:

1. Structural stop remains unchanged.
2. Actual-fill external-liquidity room must be at least 1.50R.
3. Full exit occurs at the nearer of the named destination and 2.00R.
4. No full-position break-even before target.
5. No runner until fresh evidence shows incremental value.

Do not carry forward the raw-M15 bidirectional scanner.

The next bounded research must address selection, not management: build one
direction-normalized, point-in-time auction-state selector that waits for the
already-established M15 transition plus an observable internal liquidity
response (sweep/reclaim, acceptance/rejection or retest) before entry. It must
use identical semantics for LONG and SHORT, scan London and New York
separately, retain the management candidate above, and reject ambiguous or
unresolved plans. It may be translated on the exposed data, but it must be
frozen before any unopened block is used.

No claim that 10R/month has been achieved is supported by this audit.

## Integrity

- Management-grid result SHA-256: `85589d5f8412fa79ed3fbd435208a57ead9b3dc712ec1ab2dc77fb63ccb7aee8`
- Matched-trade attribution SHA-256: `520c6dc292cf7aa721f1affee6902fad8ac299230fd56f1c3ead385085d54ca9`
- Bidirectional capacity result SHA-256: `3f9172c041c274548219e1857af517aa12a6cd701a5a71719bc61fdb79b2a1db`
- Bidirectional primary/reference reproduction: exact
- Fresh data opened: no
- Validation credit: zero
