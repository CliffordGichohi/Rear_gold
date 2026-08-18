# Gold Blind Discretionary Replay V1 — Pre-Label UI Amendment B

Status: `FROZEN_INTERACTION_AND_DISPLAY_ONLY_BEFORE_IMPLEMENTATION`

Authorized on 2026-08-13 before any human decision was collected. The sealed UI Amendment A predecessor was verified with zero mismatches; the decision ledger remained absent and the next case remained `P-001`.

## Purpose

Provide a light, TradingView-like chart workstation and the point-in-time drawing aids needed to express a retracement setup consistently.

## Permitted changes

1. Make the replay route and workspace use a white/light, low-fatigue visual theme without changing any value or field.
2. Add client-local chart tools:
   - cursor and crosshair;
   - trend line;
   - horizontal level;
   - Fibonacci retracement with frozen levels `0`, `0.236`, `0.382`, `0.5`, `0.618`, `0.786`, and `1`;
   - long-position and short-position geometry;
   - ruler/measurement;
   - undo and clear drawings;
   - visible-history zoom.
3. Synchronize a completed valid long/short position drawing to the existing frozen decision form. The mapping must remain arithmetic and value-blind:
   - entry relative to checkpoint index `100` determines `MARKET`, `PULLBACK_LIMIT`, or `BREAKOUT_STOP` under the existing direction-specific sign rules;
   - stop distance is absolute entry-to-stop distance divided by displayed M15 ATR;
   - target R is absolute entry-to-target distance divided by entry-to-stop distance;
   - geometry outside the existing frozen bounds is rejected, never clamped or repaired.
4. Add a replay control that animates only candles already present in the certified past-only display payload. It must never fetch, materialize, infer, or reveal a post-checkpoint scored candle. Decisions may be locked only with the chart returned to its actual checkpoint.
5. Add a concise point-in-time fundamental summary using only fields already present in the certified payload.
6. Add a retracement checklist, tooltips, legends and accessibility labels.

## Prohibited changes

This amendment may not change or inspect:

- population, aliases, order, dates, checkpoints, sources, histories, context values or hashes;
- practice/scored outcome construction or post-checkpoint scored paths;
- any 2025 or 2026 value;
- action, confidence, entry, stop, target, risk, cost, latency, fill, expiry, ambiguity, overlap or scoring semantics;
- evaluation, statistics, support, calibration, multiplicity or PASS/REJECT gates;
- any case-specific advice, automated trade recommendation or automatic confidence score.

Drawings are unscored decision aids and stay in browser memory for the active case only. They are cleared when the next case loads and are not inserted into the evidence payload. A position drawing only fills the existing participant-controlled form; the participant must review and lock it manually.

The predecessor freeze remains permanently preserved. A successor seal may pass only if the application still has zero decisions and `P-001`, all research/data/backend predecessor hashes remain unchanged, the tool mappings pass automated tests, the deployed route is healthy, and no potential charge or data acquisition occurs.
