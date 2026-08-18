# GC Microstructure Step 3D — Metadata-Only Comparator

## Scope

- Permanently engineering-only date: `2024-01-09`.
- Only the previously sealed MBO and MBP-10 sources were used.
- Alignment used exact K5, action, side, flags, and within-identical-metadata occurrence.
- Book equality was not used to select a boundary.
- Unaligned rows were retained as formal failures; no fallback was attempted.

## Formal verdict

`FAIL_UNALIGNED_RESIDUAL`

- Vendor rows: 1,924,786.
- Metadata-aligned rows: 1,922,234 (99.867414%).
- Unaligned residual rows: 2,552.
- Exact aligned rows: 1,922,234.
- Aligned mismatch rows: 0.
- Aligned field mismatches: 0.
- Rows aligned to non-F_LAST MBO events: 74,168.
- Rows aligned to F_LAST MBO events: 1,848,066.

The rule is exact whenever it produces an alignment, but the frozen formal gate requires every vendor row to align. Therefore the residual population forces the formal failure; no partial-pass label is used.

## Independent reproduction

- Reproduction pass: `true`.
- Selector checksum: `79b33543386b3fac878da7fb176e44f266bbc660c135eb79c4ca5f90d6b6fd7f`.
- Comparison checksum: `3ea286ebc73479d86079c1dc0f0974cf18ab936749d76ecc54cd315b4837c75c`.

## Fixed recommendation

`NO_FURTHER_CORRECTION_RECOMMENDED_IN_STEP_3D` — preserve the verdict and all residuals unchanged and stop.

## Prohibited-work confirmation

No data was acquired. No residual was filtered, repaired, or tested against an alternate boundary. No outcomes, signals, execution optimization, trades, PnL, R multiples, or account returns were calculated.
