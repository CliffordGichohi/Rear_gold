# Gold Coherent-Auction Human-Policy V2 — Fresh Block Scope Correction C

Status: `AMENDMENT_B_SUPERSEDED_BEFORE_ANY_DECISION_OR_OUTCOME_EVALUATION`

On 2026-08-20, Amendment B incorrectly interpreted the user's instruction as authorization for another human-labeling block. The user clarified that the requested operation was an automatic application of the exact frozen rules that produced the exposed `+10.681846581267534R` result.

No fresh decision was submitted, no result was calculated, and no 2025/2026 value was opened. The validation UI was launched and could have rendered the initial pre-decision view of `GAV-2022-001`; no future path or aggregate result was released. The append-only validation decision ledger remained absent at the correction checkpoint.

The exact frozen V2 policy cannot be applied directly to raw sessions because its input contract requires an operator-supplied sealed direction, actual fill, structural stop, liquidity target, and written auction context. Those inputs came from the 16 exposed human trades. V2 then applied contextual vetoes, risk sizing, protection, and runner management. It did not freeze an autonomous setup-discovery rule.

Therefore:

- Amendment B is preserved but is not active authorization for human labeling.
- The 50-case block must not be evaluated under V2 unless valid point-in-time setup records exist.
- Creating a deterministic setup generator would be a new pre-outcome rule freeze and a new complete-strategy test; it cannot be represented as an unchanged replication of the exposed `+10.68R` overlay.
- Calendar 2025 and calendar 2026 remain locked.
