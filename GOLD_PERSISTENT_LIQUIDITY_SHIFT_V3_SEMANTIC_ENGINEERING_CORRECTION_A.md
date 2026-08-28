# Gold Persistent Liquidity-Shift V3 Semantic Engineering Correction A

## Preserved result

Preserve the first V3 semantic-calibration artifacts and their reported `PASS_SEMANTIC_REPRESENTATION` unchanged. That result receives no semantic or economic credit because its availability comparator allowed a triggered entry intent to remain matchable indefinitely after its frozen expiry.

The defect is directly visible in technical timestamps: for example, a 2021-12-31 trigger was classified as available to later January 2022 decisions. No market outcome, return, PnL, MFE, MAE, 2025 value or 2026 value was accessed to identify the defect.

## Single correction

Change only the triggered-intent availability test:

- before: `triggered_at <= decision_at`;
- after: `triggered_at <= decision_at < expires_at`.

The pending-intent rule remains `order_at <= decision_at < expires_at` where no trigger was yet observable. The existing active-session and minimum-thirty-minutes-to-session-close requirements remain unchanged.

No zone, contact, reaction, transition, state, impulse, entry, stop, threshold, duration, session, support gate or pass requirement may change. The frozen semantic hurdle remains at least seven of sixteen human trades. The existing source and detector implementation remain unchanged.

## Disposition

Permit one deterministic corrected semantic reproduction using the same visible human decisions and with all outcome ledgers prohibited. Preserve both the invalid engineering run and the corrected result. If the corrected result fails, stop before development outcomes. If it passes, seal the implementation before development economics.

