# Gold Liquidity-Shift Pre-Decision Trigger Diagnostic V1

## Purpose

Identify the completed-candle structure actually visible when the human chose to trade, after V3 proved that a fresh high-displacement M5 break followed by a sixty-minute retracement did not represent those decisions.

This is trigger-semantics research, not profitability research. It may access only information visible at or before each sealed decision timestamp. Post-decision bars, resolution ledgers, MFE, MAE, returns and PnL are prohibited.

## Frozen population

- The same 30 visible matched-replay decisions.
- Sixteen LONG decisions are descriptive positive examples of the operator's setup semantics.
- Fourteen NO_TRADE decisions remain negative day-level controls, but their 17:00 UTC terminal timestamps must not be treated as like-for-like entry checkpoints.
- No case receives economic or validation credit.

## Frozen measurements

For completed M5, M15, H1 and H4 bars at each decision timestamp, record:

1. last two already-confirmed swing highs and lows and their HH/HL/LH/LL trend state;
2. latest close through an already-confirmed same-side pivot, its age, range/ATR, body/range and normalized break margin;
3. current close's point-in-time position inside the latest confirmed swing range;
4. latest confirmed swing distances in ATR units;
5. last one-, three- and six-bar signed movement, directional efficiency and alternating-candle count;
6. completed-candle rejection, sweep/reclaim and inside/outside classifications;
7. latest qualifying V2 zone contact and M15 transition ages;
8. whether a same-direction V3 auction state is active, and the age of its latest M5 impulse;
9. the human entry, stop and target geometry relative to current price and known swings; and
10. DST-aware active session and time remaining.

Report continuous values and missingness honestly. Do not select thresholds, construct candidates or open outcomes in this diagnostic.

## Reproduction

Run primary and reversed-input reference calculations and require identical row identities, fields and checksums. A mismatch stops the diagnostic.

