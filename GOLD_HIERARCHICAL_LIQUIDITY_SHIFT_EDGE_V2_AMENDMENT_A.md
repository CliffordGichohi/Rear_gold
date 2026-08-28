# Gold Hierarchical Liquidity-Shift Edge V2 Amendment A

## Preserved result

The original V2 semantic-calibration verdict remains `FAIL_SEMANTIC_REPRESENTATION`:

- Same-direction prior zone contact: 16/16 (100.0%).
- Post-contact M15 transition: 11/16 (68.75%).
- Frozen triggered-or-pending entry state: 1/16 (6.25%).

No matched outcome, development outcome, 2025 value or 2026 value was opened.

## Outcome-blind diagnosis

The 11 transition-matched human cases generated 24 transition instances and 48 registered entry intents. Thirty-eight of the 48 intents failed the frozen 1.50-M15-ATR maximum stop-distance gate. The median detected stop distance was 1.708 ATR for the half-retrace family and 2.056 ATR for the M5-confirmation family.

The human's sealed visible decisions independently show that the intended structural invalidation was commonly wider than the V2 cap:

- 16 observable human entry-to-stop geometries;
- median 2.340 M15 ATR;
- maximum 6.059 M15 ATR;
- only 6/16 at or below 1.50 M15 ATR;
- 9/16 at or below 2.50 M15 ATR.

These measurements use only the entry, stop and point-in-time M15 ATR visible at decision time. They do not use outcome, MFE, MAE, win/loss or later price data.

## Single permitted correction

Change only `maximum_stop_m15_atr` from `1.50` to `6.50`.

The new ceiling is the next half-ATR boundary above the maximum observable human geometry of 6.059 ATR. It is a representation bound, not an economically selected stop. Each setup must still use its unchanged structural stop, risk no more than $50, size in whole ounces, retain the $55 effective-risk ceiling, and have a point-in-time external-liquidity target offering at least 1.50 planned reward-to-risk.

Every other frozen definition remains unchanged, including zones, contact episodes, reactions, M15 transitions, retracement band, entry triggers, order expiry, target hierarchy, costs, sessions, macro routes, support floors, multiplicity and PASS/REJECT gates.

## One-attempt disposition

Repeat the outcome-blind semantic calibration once under the amended maximum. The original failure remains in the record. If the unchanged semantic rates fail again, stop this V2 branch. If they pass, seal the amended implementation and only then open the development outcomes once under the existing economic protocol.

Calendar 2025 and 2026 remain locked. No paid acquisition or broker order is permitted.
