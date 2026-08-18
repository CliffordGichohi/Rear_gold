# Gold Annotated Replay V3 User Guide

Status: `PRACTICE_ONLY`

The twenty visible days are zero-credit practice. The one-year collection set, calendar 2025, and calendar 2026 remain closed.

## Open the replay

1. Start Docker Desktop.
2. From the repository root, run:

   ```powershell
   docker compose up -d --build api web
   ```

3. Open [http://localhost:3000/replay](http://localhost:3000/replay).
4. Select one of the twenty practice dates and an initial UTC time, then select **Start replay**.

Choosing a later initial time records the skipped interval as unobserved. It does not reveal that interval as if you had watched it.

## Read and navigate the chart

- Switch among W1, D1, H4, H1, M15, M5, and M1. Every timeframe uses the same replay clock.
- Use **Play/Pause**, **+1**, **+5**, **+15**, and the 1×/2×/4×/8× speed selector.
- Use only the chart buttons to zoom or move the viewport: `+`, `−`, `←`, `→`, `↑`, `↓`, and reset.
- Mouse-wheel zoom and drag-to-pan are deliberately disabled, so accidental scrolling cannot change the view.
- **Full screen** keeps the replay and order controls available.
- The lower time axis shows actual UTC timestamps. Blank space to the right is only viewing space; it does not expose future candles.
- The context panel summarizes point-in-time fundamentals and labels each item as observed, calculated, inferred, or unknown. Upcoming and released events are shown without future release values.

## Draw and prepare a trade

- Fibonacci, trend-line, horizontal-line, long-position, and short-position tools are available on the chart.
- Drawings persist when you change timeframe because they use synchronized time and price anchors.
- Select a drawing to show its handles. Drag the handles to resize it.
- Press **Delete** or **Backspace**, or use the chart **Delete** button, to remove the selected drawing before it is sealed.
- For a long or short position, place three independent points: **ENTRY**, **SL**, and **TP**. Adjusting one point does not move the other two.
- An unsubmitted plan does not pause replay. Pause when you want more time to inspect it.

## Place and manage an order

1. Choose `MARKET`, `LIMIT`, or `STOP` in the order ticket.
2. Draw the long or short position and resize ENTRY, SL, and TP.
3. Select **Place Order**. Replay pauses and the annotation window opens.
4. Record why the trade exists now, the fundamental direction and dominant driver, higher-timeframe context, session/liquidity context, observable trigger, invalidation, target logic, event risk, and confidence.
5. **Cancel** returns to the chart with the draft intact and no order submitted.
6. **Confirm Order & Resume** atomically seals the cursor, visible-data hashes, drawings, order geometry, selected timeframe, point-in-time context, and reasoning before replay resumes.

Order behavior:

- A market order fills at the next eligible replay event after submission.
- A limit or stop order remains pending until touched, cancelled, amended, or expired.
- A pending order may be resized and amended. The original annotation remains immutable, and the amendment can include a new reason.
- Once filled, direction, entry, stop, target, and original reasoning are locked.
- Stop and target resolution is automatic. If both are touched in the same bar, the frozen conservative rule records the stop first.
- Manual close requires a reason and creates a new ledger event; it never rewrites the original order.
- Only one pending order or active position may exist at once, but sequential trades are allowed after resolution.
- Planned risk is capped at $50 on the frozen $10,000 account and uses whole-ounce sizing.

## Recovery and completion

- Browser refresh restores the current case, drawings/draft, replay cursor, and durable server order state.
- API restart restores the event chain from the append-only ledger.
- Select **Finish day** only while flat. Remaining time is recorded as not observed.
- After completing a day, select **Choose another practice day**.

Practice deliberately reports no aggregate win rate, PnL, profit factor, or edge conclusion. Its purpose is to learn the interface and verify that decisions are captured correctly before a separate authorization opens scored human labeling.

