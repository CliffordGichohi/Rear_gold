# Gold Blind Discretionary Replay V1 — Pre-Label UI Amendment E

Status: `FROZEN_TRADINGVIEW_STYLE_CAMERA_AND_COMPACT_CONTEXT_BEFORE_IMPLEMENTATION`

Authorized on 2026-08-14 before any human decision was collected. UI Amendment D was verified with zero decisions, an absent decision ledger, and next case `P-001`.

## Observed defects

1. During visible-history replay, the revealed candles are rescaled across the entire chart. Zoom therefore changes the number of source bars but does not provide a stable camera around the current replay candle.
2. Distant known levels are included in the automatic price scale, compressing the visible auction into a narrow vertical band.
3. The fundamental component explanations occupy too much vertical space for a decision workspace.
4. Released point-in-time events are listed only as a count and are not located on the relative chart axis.

## Bounded correction

1. Separate the replay cursor from the camera. A fixed-slot viewport follows the latest revealed candle, reserves adjustable blank space on the right, and never renders an unrevealed price bar.
2. Zoom changes viewport density only. Horizontal chart shifting changes right-side blank space only. Neither operation changes the replay cursor, decision state, drawing state, or current timeframe.
3. Permit crosshair drag and explicit camera controls to shift the visible auction left or right within bounded blank space. Camera movement may rearrange only already-revealed bars.
4. Show an explicit `REPLAY NOW` cursor while replay is active and retain the frozen `CHECKPOINT` cursor at the actual decision checkpoint.
5. Autoscale from visible completed candles and active drawings. Do not let distant reference levels compress price action; report off-screen known levels at the upper or lower chart edge.
6. Replace expanded macro cards with a compact point-in-time pulse showing a short observable state such as `FALLING`, `RISING`, `WEAKENING`, `ACCELERATING`, or `UNKNOWN`, plus its gold impact. Preserve the full source explanation in a collapsed details section.
7. Plot only already-released events from the existing sealed `released_events` payload on the relative chart axis. A marker may appear only after its release point has been reached in history replay. It may display event identity, importance, and a release-time surprise sign already available at that checkpoint.
8. Do not fabricate or retrospectively expose upcoming scheduled events. The current historical calendar has no certified pre-release schedule availability (`schedule_verified_for_pre_event_use=false`), so the UI must state that future calendar markers are unavailable rather than infer them from later records.

Absolute dates, absolute times, absolute prices, post-checkpoint scored bars, unreleased actuals, and outcome fields remain hidden. No source, population, research rule, execution rule, or decision schema changes. No acquisition or charge is authorized.

