# Gold Blind Synchronized Setup Replay V2 Camera Input Amendment B

Status: `FROZEN_AND_IMPLEMENTED`

Authorized scope: narrow post-certification replay-camera and display correction.

The original V2 certification, Post-Certification Status Amendment A, all prior artifacts, and all replay rules remain preserved. This amendment changes only chart interaction and presentation:

- Mouse-wheel and touchpad scrolling over the chart must not zoom or pan the chart and remains available for normal page scrolling.
- Pointer dragging must not pan the chart.
- Zoom, horizontal movement, and camera reset are available only through the labeled GUI controls.
- A labeled Full screen / Exit full screen control may expand the chart and drawing toolbar using the browser Fullscreen API; `Esc` remains a valid browser exit.
- Full-screen state must not reset or alter the synchronized cursor, timeframe, drawings, position plan, visible-data hashes, context, or decision form.
- Drawing clicks and crosshair inspection remain unchanged.
- Practice remains zero-credit and scored labeling remains closed.
- No case, source, outcome, 2025/2026 value, acquisition, or charge is permitted by this amendment.

Certification requires the focused interaction regression, complete frontend suite, TypeScript check, zero-warning lint, production build, live replay HTTP readiness, and an unchanged zero-decision P-001-at-T0 status.
