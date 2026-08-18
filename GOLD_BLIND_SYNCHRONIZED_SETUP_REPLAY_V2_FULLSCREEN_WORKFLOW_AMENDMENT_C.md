# Gold Blind Synchronized Setup Replay V2 Full-Screen Workflow Amendment C

Status: `FROZEN_AND_IMPLEMENTED`

Authorized scope: narrow post-certification replay usability correction following Camera Input Amendment B.

All prior certifications, verdicts, artifacts, seals, point-in-time rules, one-way cursor rules, and practice-only restrictions remain preserved. This amendment changes only client-side chart navigation, position visualization, and the full-screen decision workflow:

- Horizontal camera buttons translate candles through a fixed-slot viewport without changing candle width or compressing the visible window.
- Up and down camera buttons provide bounded vertical translation; Reset restores horizontal, vertical, and zoom state.
- Mouse-wheel, touchpad, and drag camera changes remain disabled.
- Full screen includes Play/Pause, +1m/+5m/+15m, synchronized timeframe controls, and cursor status.
- A completed long or short position exposes a full-screen Place & Play button.
- Place & Play opens an in-fullscreen setup-details dialog; Done & Play uses the existing atomic immutable decision endpoint before revealing practice bars.
- The long/short tool renders red-risk and green-reward zones during drafting and after completion.
- Position construction remains three price levels: ENTRY followed by SL and TP in either order. The two boundaries are normalized deterministically by direction.
- Position drafting cannot begin while REPLAY NOW is outside the current camera.
- No future bar, realized outcome, research label, or hindsight field is added to the browser.

At the amendment freeze, the user-controlled practice cursor is P-001 at T+172m, `total_locked` remains zero, the setup-ledger head remains the all-zero hash, scored labeling remains closed, and no acquisition or charge occurred.

Certification requires the complete 24-test frontend suite, the eight focused replay tests, TypeScript, zero-warning lint, production build, live HTTP 200, the newly built container image, and unchanged zero locked decisions.
