# Gold H1-Governed Trade Plan Semantics V1

## Purpose

Implement and visually certify the corrected auction hierarchy before using it
on observed price paths:

1. H1 defines the governing trend or range and the destination policy.
2. M15 defines the local pullback or range rotation and controlling swing.
3. M5 supplies the completed-candle turn, first valid retest, entry, and local
   structural invalidation.

This is an outcome-blind semantic implementation. It calculates no trade
result, PnL, R multiple, MFE, MAE, win rate, or edge statistic.

## Trend plans

- H1 must already be a completed-candle `UPTREND` or `DOWNTREND`.
- H1 is not the entry trigger.
- M15 must form a direction-aligned pullback into a known curvature/location
  zone around its controlling swing.
- M5 must form a direction-aligned turn followed by the first valid retest at a
  better extreme.
- Entry is the completed M5 retest close.
- The execution stop is beyond the M5 turn/retest curvature.
- The governing thesis invalidation remains the opposing H1 controlling level.
- The destination must be a pre-existing, unconsumed H1 liquidity swing in the
  direction of the trade.

## Range plans

- H1 must already be an objective `ACTIVE_RANGE` with exact known boundaries.
- A long may form from the lower half and a short from the upper half.
- M15 defines the boundary rotation; M5 supplies the same turn/retest entry.
- The destination must be pre-existing internal M15 liquidity strictly inside
  the range and forward from entry.
- The opposite range boundary is context and may never be selected as the
  automatic target.

## Liquidity semantics

- A swing remains unconsumed until later observed traded price moves strictly
  beyond it.
- Equality is engagement, not consumption.
- Liquidity roles are calculated auction references, not proof of resting
  institutional orders.

## Synthetic certification population

Exactly four symmetric outcome-free examples are required:

1. H1 downtrend, M15 pullback, M5 short, H1 low destination.
2. H1 uptrend, M15 pullback, M5 long, H1 high destination.
3. H1 range upper rotation, M15/M5 short, internal M15 destination.
4. H1 range lower rotation, M15/M5 long, internal M15 destination.

The visualization must show H1, M15, and M5 together, use a fixed light theme,
keep every entry/stop/target line bounded to the plan area, and clearly identify
whether the target is an H1 swing or internal range liquidity.

The default desktop candle geometry must match the supplied TradingView
reference: dense context, narrow bodies, and visible gaps. Synthetic context is
therefore deterministically expanded to 81 H1, 67 M15, and 64 M5 candles per
sample. Candle bodies use 58% of their slot with a 6.5 CSS-pixel desktop cap;
this is presentation-only and cannot change any plan identity or price level.
