# GC Microstructure Step 3E — Residual Metadata Semantics

## Scope

- Step 3D `FAIL_UNALIGNED_RESIDUAL` is preserved.
- Only sealed metadata columns were loaded; no price, size, order ID, or bid/ask book field was loaded.
- No book was reconstructed and no candidate book state was compared.
- Reproduced Step 3D residual records: 2,552.

## Official semantics used

- [Databento MBO schema](https://databento.com/docs/schemas-and-data-formats/mbo)
- [Databento MBP-10 schema](https://databento.com/docs/schemas-and-data-formats/market-by-price)
- [Databento common fields and enums](https://databento.com/docs/standards-and-conventions/common-fields-enums-types)
- [Databento order-state and F_LAST guidance](https://databento.com/docs/examples/order-book/order-tracking)
- [Databento release notes](https://databento.com/docs/release-notes)

The reviewed pages define actions, side N, flags, and F_LAST, but do not guarantee that an MBP-10 header is a byte-for-byte copy of one MBO row.

## Findings

### ACTION_PRESERVATION

Classification: `CONFIRMED`.

Residual MBP-10 action is present in its same-K5 MBO group.

Support: `{"action_present":2552,"coverage_fraction":1.0,"residual_records":2552}`.

### UNSPECIFIED_SIDE

Classification: `UNRESOLVED`.

Vendor side N contributes to the residual population; official semantics define N as no side specified.

Support: `{"coverage_fraction":0.9212382445141066,"residual_records":2552,"vendor_side_n":2351}`.

### PUBLISHER_SPECIFIC_NORMALIZATION

Classification: `LIKELY`.

F_PUBLISHER_SPECIFIC is set on the stated share of residual vendor headers.

Support: `{"coverage_fraction":0.9643416927899686,"publisher_specific_flag_set":2461,"residual_records":2552}`.

### FLAGS_AS_NONIDENTITY_METADATA

Classification: `UNRESOLVED`.

Action-and-side matches can exist even where exact action/side/flags identity does not.

Support: `{"action_side_present":155,"difference":155,"exact_tuple_present":0,"residual_records":2552}`.

### MULTI_RECORD_EVENT_EMISSION

Classification: `LIKELY`.

The stated share of residuals belongs to same-K5 groups with multiple MBO records.

Support: `{"coverage_fraction":0.9988244514106583,"multi_record_groups_at_row_level":2549,"residual_records":2552,"vendor_matches_any_f_last_tuple":0}`.

### UNRESOLVED_HEADER_DERIVATION

Classification: `LIKELY`.

The recommended selector is a reproduced metadata rule, but the reviewed official pages do not explicitly guarantee this MBP-10 header derivation.

Support: `{"eligible_complete_candidate_found":true,"recommended_candidate":"C04_ACTION_ONLY"}`.

## Frozen candidate results

- `C01_MASK_PUBLISHER_SPECIFIC_FLAG`: 0/2,552 available; residual reuse 0; Step 3D reuse 0.
- `C02_IGNORE_FLAGS`: 155/2,552 available; residual reuse 0; Step 3D reuse 0.
- `C03_SIDE_IF_SPECIFIED_IGNORE_FLAGS`: 2,506/2,552 available; residual reuse 0; Step 3D reuse 0.
- `C04_ACTION_ONLY`: 2,552/2,552 available; residual reuse 0; Step 3D reuse 0.
- `C05_K5_OCCURRENCE_DIAGNOSTIC_ONLY`: 2,552/2,552 available; residual reuse 0; Step 3D reuse 9.

## Recommendation

`ONE_VALUE_BLIND_CORRECTION_RECOMMENDED`

Freeze this candidate as a post-hoc engineering fallback in a separate amendment; do not implement or validate it in Step 3E.

No correction was implemented. No additional data, outcomes, signals, execution optimization, trades, or PnL were used.
