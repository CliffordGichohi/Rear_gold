# Gold Liquidity-Response V4 Failure Attribution Report

## Outcome-blind findings

- Actual V4 matches: 5/16 trades.
- Ignoring opposite-M5 noise while retaining the four-hour and source-location terminals: 10/16.
- Higher-timeframe eligibility at the human decision: 14/16.
- Natural four-hour state plus higher-timeframe eligibility: 9/16.
- NO_TRADE days with a natural state: 11/14.
- NO_TRADE days still passing the higher-timeframe eligibility test: 11/14.

Failure classifications across the sixteen trades:

- actual V4 match: 5;
- terminated only by an opposite M5 break: 5;
- no activation within four hours: 5; and
- source location already terminated: 1.

## Verdict

Replacing opposite-M5 termination with a durable invalidation is necessary but not sufficient. The frozen H1/H4 trend-or-outer-range filter does not distinguish the false signals: it retains all eleven false-positive days and reduces positive coverage from ten to nine.

Do not implement the initially contemplated V5 combination. The next bounded question must change the location selector itself: whether the small set of H1/H4 structural levels the human actually marked can be represented transparently and used as the location source, instead of treating every mechanically generated shift-zone contact as equally important.

No market outcome, PnL, 2025 value or 2026 value was accessed.

