# Gold Exposed Bidirectional Auction-Capacity Protocol V1

Status: `FROZEN_EXPOSED_HYPOTHESIS_GENERATION_ONLY`

This bounded study uses only the already-opened 2022-01-03 through
2022-02-16 and 2022-03-01 through 2022-05-31 streams. It receives zero
validation credit and cannot justify live capital.

## Purpose

Measure whether the current result is constrained by an accidental
long-only, nearly New-York-only, first-signal-per-day implementation. This is
not permission to delete losing trades, fit case-specific rules, or open a
fresh period.

## Frozen scanner

- Scan London 08:00--12:00 Europe/London and New York 08:00--12:00
  America/New_York separately with daylight-saving conversion.
- Generate a candidate only at a newly completed M15 structural-transition
  boundary. Evaluate LONG and SHORT symmetrically.
- Compile the point-in-time six-component auction plan using the existing
  semantic auction compiler: macro context, governing auction, controlling
  structure, local trigger, structural invalidation, and liquidity
  destination.
- Require the plan's M15 setup transition to be the new transition observed
  at that checkpoint. Stale transitions cannot initiate a trade.
- Refresh the existing lifecycle-aware destination hierarchy at the actual
  fill. An active destination must provide at least 1.50R of room from the
  actual fill; engaged liquidity remains eligible, consumed liquidity does
  not, and reactivated liquidity is intermediate rather than final.
- If simultaneous opposing transitions survive at the same checkpoint, mark
  the checkpoint ambiguous and take neither direction.
- Admit only the first eligible plan per session. Maximum one open position;
  every position is closed no later than its session close.

## Frozen execution

- Decision: completed M15 transition timestamp.
- Entry: first complete M1 bar opening strictly after the decision timestamp.
- Stop: compiler's point-in-time structural invalidation, unchanged.
- Target: the nearer of the active final liquidity destination and 2.00R.
- Management: no pre-target break-even and no runner.
- Ambiguous M1 bars: stop first.
- Cost and latency: existing IC Markets spread plus $0.05/oz slippage on each
  side; whole-ounce sizing; maximum planned loss $50 including costs.
- No trade when geometry, causality, destination, room, source, or whole-ounce
  sizing is unavailable.

## Reporting

Report all session decisions and no-trade dispositions, LONG/SHORT and
London/New-York contributions, trades/month, win rate, expectancy, profit
factor, R/month, dollars at $50 risk, maximum drawdown, monthly stability,
1.5x-cost stress, and exact primary/reference reproduction.

The current corrected 28-trade result and the exposed fixed-2R management
result remain controls. No result from this protocol is a validated edge.
