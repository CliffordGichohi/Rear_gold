# GC Microstructure Step 3C — Engineering Diagnostic

## Scope and preserved state

- Permanently engineering-only date: `2024-01-09`.
- Sources: the previously sealed MBO and MBP-10 files only.
- No data was acquired; no market values are reported.
- Step 3A `FAIL`, Step 3A.1 `PASS`, Step 3B.1 readiness `FAIL`, and Step 3B.2 `FAIL` remain unchanged.
- The Step 3B.2 comparator was neither modified nor repaired.
- One unsealed primary implementation attempt was rejected and preserved before independent reproduction; its disposition is sealed with this report.

## Reproduction verdict

- Step 3C status: `PASS_DIAGNOSTIC_REPRODUCTION`.
- MBO records accounted: 2,322,905.
- MBP-10 records accounted: 1,924,786.
- Shared K3 native-event groups: 1,908,460.
- Strict Step 3B.2 failures reproduced: 73,887.
- Strict failures with at least one exact state in K3: 73,887.

## Frozen-taxonomy findings

### ALIGNMENT_KEY_INSUFFICIENCY

Classification: `CONFIRMED`.

The frozen K5 does not uniquely identify every vendor row; source-order occurrence restores identifier uniqueness.

Scope: vendor identifier multiplicity, not universal book-state causality.

Supporting counts: `{"augmented_identifier_collisions":0,"duplicate_vendor_k5_groups":5702,"vendor_records":1924786,"vendor_rows_beyond_first_under_k5":6167}`.

### EVENT_EMISSION_BOUNDARY

Classification: `CONFIRMED`.

The stated strict-failure subpopulation equals exactly one non-F_LAST pre/post state in its native event group.

Scope: exact counted subpopulation only.

Supporting counts: `{"coverage_fraction":1.0,"strict_failures":73887,"unique_non_f_last_resolutions":73887,"unqualified_unique_non_f_last_resolutions":0,"within_k5_occurrence_non_f_last_resolutions":73887}`.

### NATIVE_EVENT_GROUPING

Classification: `CONFIRMED`.

The stated strict-failure subpopulation resolves uniquely elsewhere inside the same K3 native-event group.

Scope: exact counted subpopulation only.

Supporting counts: `{"any_exact_state_coverage_fraction":1.0,"any_exact_state_in_k3":73887,"coverage_fraction":1.0,"strict_failures":73887,"unique_elsewhere_in_k3":73887,"unqualified_unique_elsewhere_in_k3":1402,"within_k5_occurrence_exact":73887}`.

### SNAPSHOT_HANDLING

Classification: `UNRESOLVED`.

Snapshot handling does not meet the frozen causal threshold.

Scope: strict failures classified from vendor F_SNAPSHOT.

Supporting counts: `{"snapshot_failures_with_snapshot_candidate":0,"snapshot_strict_failures":0,"strict_failures":73887,"within_snapshot_resolution_fraction":0.0}`.

### RECONSTRUCTION_OR_VENDOR_REPRESENTATION_SEMANTICS

Classification: `UNRESOLVED`.

The frozen isolating test did not establish a representation discrepancy.

Scope: representation discrepancy only; vendor versus reconstruction attribution remains unresolved.

Supporting counts: `{"single_mbo_exact_header_no_pre_or_post_match":0,"strict_failures":73887}`.

## Single bounded recommendation

`EXACT_PHASE_FALLBACK` — Prototype one deterministic fallback for strict F_LAST failures using POST_SAME_K5_OCCURRENCE, on the permanently excluded engineering date only.

No correction was implemented during Step 3C.

## Prohibited work confirmation

No outcomes, directional relationships, signals, execution optimization, trades, PnL, R multiples, or account returns were calculated.
