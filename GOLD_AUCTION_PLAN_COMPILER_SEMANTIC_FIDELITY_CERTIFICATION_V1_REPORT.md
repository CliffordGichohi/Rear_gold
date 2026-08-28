# Gold Auction-Plan Compiler and Semantic-Fidelity Certification V1 — Result

Formal verdict: **FAIL_SEMANTIC_FIDELITY_CERTIFICATION**

This milestone used only exposed visible decisions, annotations, and certified point-in-time streams. It opened no outcome, PnL, post-decision path, fresh month, 2025, or 2026 artifact.

## Human semantic certification

- Trade proposals compiled: **16 / 16**.
- Human no-trades preserved: **14 / 14**.
- Governing-auction agreement: **11 / 16** (68.8%).
- Trigger-timeframe agreement: **9 / 16** (56.2%).
- H1-destination agreement: **16 / 16** (100.0%).

## Exposed GAV signal disposition

- Signal proposals: **20**.
- Complete executable plans: **18**.
- Explicit unresolved no-trades: **2**.
- Missing-component counts: `{"local_trigger": 2, "structural_invalidation": 2}`.

## Gates

- `synthetic_causal_proof`: **PASS**
- `human_primary_reference_exact`: **PASS**
- `gav_primary_reference_exact`: **PASS**
- `no_integrity_violations`: **PASS**
- `no_causality_violations`: **PASS**
- `human_no_trades_preserved`: **PASS**
- `human_trade_plan_coverage`: **PASS**
- `governing_auction_agreement`: **FAIL**
- `trigger_timeframe_agreement`: **FAIL**
- `h1_destination_agreement`: **PASS**
- `gav_resolved_exactly_once`: **PASS**
- `learned_geometry_absent`: **PASS**
- `outcomes_and_fresh_periods_unopened`: **PASS**

## Mismatches

- Human cases with at least one semantic mismatch: **9**.
- GAV proposals left unresolved: **2**.
- Every mismatch is stored in the sealed mismatch catalog; none was repaired after inspection.

## Interpretation

A PASS certifies point-in-time semantic translation and traceability only. It does not certify profitability. A FAIL identifies an implementation mismatch and does not authorize outcome-driven threshold changes.
