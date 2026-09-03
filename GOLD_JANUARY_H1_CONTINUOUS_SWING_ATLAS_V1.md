# Gold January H1 Continuous Swing Atlas V1

## Purpose

Render one continuous, fixed-light-theme XAUUSD H1 chart for January 2022 with every objective H1 swing clearly anchored to its pivot candle. This is a structural semantic review, not a strategy, entry, or PnL study.

## Frozen sources

- Reuse the certified primary and reference replay streams from `gold_matched_human_replay_v1`.
- Deduplicate overlapping H1 records by `open_at` only when every displayed and lineage field agrees exactly.
- Use context before January for ATR calculation and two completed H1 bars after a potential pivot for objective confirmation.
- Display only H1 candles whose `open_at` is within calendar January 2022 UTC.

## Swing definition

Use the existing `confirmed_swings` implementation unchanged:

- H1 timeframe.
- ATR window: 14 completed H1 candles.
- Pivot width: two completed candles on each side.
- Minimum prominence: `max(0.25 * ATR14, 0.02)`.
- Pivot time and later `detected_at` must remain separate.

## Required display

- One continuous January H1 tape, never separate cases.
- Fixed white chart background.
- TradingView-style green bullish and red bearish candles.
- Every HIGH swing marked above its exact pivot candle.
- Every LOW swing marked below its exact pivot candle.
- Short bounded pivot-to-confirmation segments only; no chart-wide structure lines.
- Sequential `H/HH/LH/EH` and `L/HL/LL/EL` labels.
- Clickable swing selector and markers with exact pivot, confirmation, level, prominence, and confirmation delay.
- Pan, zoom, fit, previous, and next controls.

## Guards

- Swing identity is descriptive at the pivot and becomes point-in-time known only at `detected_at`.
- No M15 or M5 cases, outcomes, entries, stops, targets, PnL, R multiples, 2025, or 2026 data may appear.
- Primary and reference H1 candles, swings, relations, and hashes must reproduce exactly.

## Browser certification

Verify the continuous candle count, every swing marker, high/low counts, bounded confirmation segments, exact selectors, controls, fixed light theme, no JavaScript errors, and responsive behavior at 1180, 736, and 360 CSS pixels.
