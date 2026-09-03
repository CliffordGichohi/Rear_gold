# Gold January H1 Confirmation-Only Reclaim Milestone V2

## Status and authorized change

- Preserve the original January H1 swing control, the completed V1 probe-confirm-reclaim result and every artifact unchanged.
- This V2 implements only the authorized removal of the blanket `0.25R` probe.
- Use the identical exposed 88-attempt January 2022 population, H1 source swings, opposing H1 targets, M5 pivot detector, timestamp semantics, `0.02` recovery buffer, stop-first ambiguity rule and month-end deadline.
- Open no fresh period. Results have zero validation credit.

## Frozen confirmation-only state machine

Each source H1 swing arms one setup but opens no position.

1. At the original causal setup timestamp, freeze the most recently detected opposing M5 pivot: a confirmed M5 high for LONG and confirmed M5 low for SHORT.
2. Before the H1 swing or opposing H1 target is touched, confirmation occurs on the first subsequently completed M5 candle closing strictly beyond that frozen M5 pivot in the setup direction.
3. Enter one full `1.00R` position at the first M1 open at or after confirmation, only if entry remains strictly between the original H1 swing stop and unchanged H1 target.
4. Resolve that position at the original H1 stop, unchanged H1 target or January deadline. A stop consumes the complete setup risk budget; no second entry is permitted.
5. If the unchanged target is touched before confirmation, record `NO_TRADE_TARGET_BEFORE_CONFIRMATION`.
6. If the H1 swing is touched before any entry, open no position. Inspect the first subsequently completed H1 candle.
7. If the target is touched before that H1 review, record no trade. If the H1 candle closes strictly beyond the source swing, cancel the setup permanently.
8. If the H1 candle closes on the valid side, freeze the most recently detected opposing M5 pivot available at that H1 close. Require a later completed M5 close both on the valid side of the H1 swing and strictly beyond that frozen pivot.
9. Recovery confirmation must precede any later completed H1 close beyond the source swing. A simultaneous H1 breach has priority and cancels recovery. A target touch before recovery also cancels it.
10. Enter one full `1.00R` reclaim position at the first M1 open at or after recovery confirmation.
11. Its stop is the adverse M1 extreme from the original swing-touch bar through recovery confirmation plus an outward `0.02` XAUUSD price-unit buffer. Its target remains the unchanged opposing H1 swing.
12. Invalid geometry produces no trade. Only one full-risk position is permitted per setup; there is no probe, addition, scale-in or re-entry after a filled position stops.

LONG and SHORT logic are exact mirrors. Every signal uses completed bars and `available_at`; entries use the first eligible M1 open.

## Frozen accounting and comparison

- Position size is normalized so entry-to-stop loss equals `1.00R` or `$50` on the frozen account illustration.
- Target result is the unchanged target distance divided by the filled entry-to-stop distance.
- Stop is `-1.00R`. A position still open at month-end exits at the final complete M1 close and records signed R.
- Report both trade-level win rate and all-88-setup expectancy, including every no-trade setup.
- Compare V2 with the sealed original control (`+11.4687555R`) and V1 (`+11.999666837957694R`).
- Report confirmation route, reclaim route, no-trade dispositions, PF, expectancy, maximum drawdown, original-winner participation and R retention.
- V2 passes this exposed matched-gross milestone only if it exceeds both controls, no filled setup loses more than `1R`, and removing its largest positive case does not eliminate the entire improvement over the stronger control.
- Do not test another risk fraction, confirmation definition, expiry, stop, target, or filter after opening results.
- Primary and reference reconstructions must agree exactly and all artifacts must be sealed.

