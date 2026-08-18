# Gold Blind Synchronized Setup Replay V2 Regression Correction Amendment E

Status: `FROZEN_AND_IMPLEMENTED`

This narrow client-side correction preserves every prior research artifact, source rule, one-way cursor restriction, immutable-decision rule, practice-only status, and scored-labeling closure.

The following regressions are corrected:

- The Play control remains actionable before a decision. With an editable position it opens the existing Place & Play annotation transaction instead of advancing an unsealed setup. At the T+180 blind-window boundary it explains that the user must seal a position or record NO TRADE; it does not expose future candles.
- Position resizing uses the selected handle and an immutable drag-start snapshot. ENTRY, SL, and TP are independent price anchors: dragging one preserves the exact other two values. The decision timestamp remains unchanged.
- Backspace and Delete remove the selected unlocked drawing. Keyboard deletion is ignored while focus is inside an input, textarea, select, or editable text region, and all drawing deletion remains disabled after the setup is sealed.

No replay cursor was rewound, no setup was submitted, no outcome was inspected, no data was acquired, and no charge was incurred.

Certification requires focused regression tests for actionable Play at the blind-window limit, Play-to-annotation routing with an editable ticket, independent SL/TP resizing, Backspace/Delete removal, and immutable locked drawings; the complete frontend suite, TypeScript, zero-warning lint, production build, deployed-container identity, HTTP 200, and unchanged zero-decision ledger must also pass.
