# Gold Blind Synchronized Setup Replay V2 Editable Drawing and Order Lifecycle Amendment D

Status: `FROZEN_AND_IMPLEMENTED`

Authorized scope: narrow post-certification drawing-editing and post-decision replay correction following Full-Screen Workflow Amendment C.

All prior verdicts, artifacts, seals, source rules, one-way cursor rules, point-in-time restrictions, practice-only status, and scored-labeling closure remain preserved.

This amendment changes only client-side drawing projection, pre-seal editing, and post-seal visualization:

- Every drawing retains case-global relative-time and normalized-price anchors and is projected deterministically onto every synchronized timeframe with available bars.
- Horizontal levels, trend lines, Fibonacci drawings, rulers, and long/short positions remain present across timeframe changes; off-camera anchors are not deleted or rewritten.
- Selecting an unlocked drawing exposes explicit resize handles. Dragging a handle updates only that anchor using completed visible data.
- Long/short ENTRY, SL, and TP remain resizable before annotation is completed. Directional geometry and the frozen ATR/R validity limits remain enforced during resizing.
- A valid position exposes Place & Play in the chart toolbar. It opens the annotation window; it does not seal or advance price by itself.
- Done & Play atomically submits the existing immutable decision payload. Only a successful response locks drawings and levels.
- After successful sealing, the primary chart switches to M1 and reveals post-decision practice candles sequentially. It does not render the entire path at once.
- A non-market order is `PENDING_ENTRY` until a revealed candle touches entry. It then becomes `ACTIVE`; entry visualization is removed while SL and TP remain visible.
- Market entry is active immediately after sealing. Stop/target state uses the frozen stop-first ambiguous-bar convention.
- Once Done & Play succeeds, ENTRY, SL, TP, other drawings, annotation, and evidence cannot be edited.
- The post-decision playback can be paused or advanced with the existing GUI controls, without rewind.
- No future bar is exposed before the immutable decision response, and no 2025/2026 source, acquisition, or charge is permitted.

At the amendment freeze, the user-controlled practice cursor is P-001 at T+180m. `total_locked` remains zero and the setup-ledger head remains the all-zero hash.

Certification requires exact cross-timeframe projection tests, unlocked resize tests, locked-handle exclusion, pending/active/stop/target lifecycle tests, annotation-before-seal testing, sequential post-seal reveal testing, the full frontend suite, TypeScript, zero-warning lint, production build, HTTP 200, deployment-image verification, and unchanged zero locked decisions.
