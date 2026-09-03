# Gold January H1-Governed Trade-Plan Atlas V1

## Purpose

Apply the frozen H1-governed auction hierarchy to the already exposed January
2022 XAUUSD prices and make every admitted plan visually reviewable before any
post-entry path, result, or performance calculation is permitted.

## Frozen hierarchy

- H1 classifies the governing auction as trend or active range.
- In a trend, the direction follows H1 and the destination is a pre-existing,
  still-unconsumed H1 swing in front of price.
- In a range, entries must originate in the directional half and the destination
  is the nearest pre-existing internal M15 liquidity swing. The opposite H1
  boundary is not an automatic target.
- M15 supplies the point-in-time location and controlling swing.
- M5 supplies the completed-candle turn, first valid retest, entry, and local
  structural invalidation.

## Data and epistemic boundary

- Source: the sealed primary and reference XAUUSD replay streams already used by
  Gold Annotated TradingView-Style Replay V3.
- Period scanned: `[2022-01-01T00:00:00Z, 2022-02-01T00:00:00Z)`.
- All displayed candles end at or before each plan's decision timestamp.
- Overlapping source records must agree exactly.
- Primary and reference plans, identities, classifications, and visual payloads
  must reproduce exactly.
- Observed OHLC is labelled OBSERVED. Structure, liquidity lifecycle, and plan
  geometry are CALCULATED. Auction interpretation is INFERRED. Resting orders
  and institutional intent remain UNKNOWN.

## Prohibited in this stage

- No post-decision candles.
- No trade resolution, PnL, win rate, MFE, MAE, optimization, or edge verdict.
- No 2025 or 2026 data.
- No paid data or acquisition.

## Visual certification

Every admitted plan must show paired predecision H1, M15, and M5 charts with:

- the governing H1 state and local governing level;
- the exact H1 target in trends or exact internal M15 target in ranges;
- the M15 control and location band;
- the M5 turn and first valid retest;
- short, local entry, stop, and target annotations;
- narrow TradingView-like candles on a fixed light background.

