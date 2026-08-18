# GC Microstructure Step 3F — Two-Stage Comparator

## Scope

- Permanently engineering-only date: `2024-01-09`.
- Primary selector: exact K5, action, side, flags, and occurrence.
- Fallback only on primary metadata absence: exact K5, action, and within-action occurrence across all vendor rows.
- A selected row was final; book equality never selected or changed a boundary.
- No additional data or date was accessed.

## Formal verdict

`FAIL_BOOK_MISMATCH`

- Vendor records: 1,924,786.
- Primary-selected records: 1,922,234.
- Fallback-selected records: 2,552.
- Unaligned records: 0.
- Selected MBO reuse: 0.
- Selected exact rows: 1,923,539.
- Selected mismatch rows: 1,247.
- Selected field mismatches: 18,376.
- Compared book fields: 115,487,160.
- Primary mismatch rows: 0.
- Fallback mismatch rows: 1,247.

The frozen selector aligned every row without reuse, but 1247 selected rows contained book mismatches.

## Independent reproduction

- Reproduction pass: `true`.
- Selector checksum: `68f55459e3bb4b4826d075cb4a48c3b1e8a1d632e0c12fcb908c14825197fe43`.
- Comparison checksum: `b7fe2464745be913aeff99af907c9a329ee4d5a7eea7810fcb395aa64ec7fa48`.

## Completion policy

No additional correction is permitted in Step 3F. This result has no research or validation credit and is preserved as engineering-only.

No outcomes, signals, execution optimization, trades, PnL, R multiples, or account returns were calculated.
