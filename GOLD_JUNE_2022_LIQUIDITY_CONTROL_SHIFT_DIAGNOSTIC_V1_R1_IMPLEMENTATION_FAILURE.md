# Gold June 2022 Liquidity-Control Shift Diagnostic V1-R1 — Implementation Failure

Verdict: `FAIL_CONTROL_LIFECYCLE_EQUIVALENCE_ZERO_RESEARCH_CREDIT`

The R1 artifacts are preserved unchanged but must not be used. A direct
semantic-equivalence check against the existing `event_is_active` lifecycle
found that the optimized terminal timestamp calculation used the frozen 0.05
ATR break-detection buffer for invalidation. The preserved event lifecycle uses
a 0.10 ATR invalidation buffer with a $0.02 minimum floor. That difference can
terminate an inferred control state too early.

The only permitted R2 correction is to use the existing 0.10 ATR/$0.02
invalidation semantics when precomputing event terminal timestamps. Shift
detection, pivot, displacement, body, acceptance, session, macro and movement
definitions remain unchanged. R2 must pass direct lifecycle-equivalence tests
and independent primary/reference reproduction before receiving descriptive
credit.
