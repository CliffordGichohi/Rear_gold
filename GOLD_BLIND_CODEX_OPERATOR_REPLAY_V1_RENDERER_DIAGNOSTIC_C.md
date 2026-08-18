# Gold Blind Codex-Operator Replay V1 — Case 004 Renderer Diagnostic C

## Frozen scope

Diagnostic C may inspect only the sealed renderer exception and renderer lifecycle metadata. It may not expose or inspect market values, bars, prices, trade direction, entry, stop, target, fill, exit, resolution state, PnL, or any prior-case outcome. Every decision and ledger row is immutable.

## Frozen taxonomy

Exactly one primary classification must be selected:

1. `RENDERER_SOURCE_INTEGRITY`
2. `DEPENDENCY_OR_BROWSER_LAUNCH`
3. `LEDGER_INTEGRITY`
4. `PRIVATE_STREAM_INTEGRITY`
5. `PAYLOAD_CONSTRUCTION`
6. `BROWSER_PAGE_LIFECYCLE`
7. `VIDEO_FINALIZATION`
8. `MANIFEST_FINALIZATION`
9. `UNRESOLVED`

## Frozen tests

1. Verify the sealed stderr SHA-256 is exactly `b1f6ce28b761fab2d7e9e7083682170aa54ccead002b8d4fcc2fa8593c5db56c` before reading it.
2. Verify all predecessor hashes in the protocol state before and after the diagnostic.
3. Parse only exception class/code, message template, stack function names, repository-relative source locations, and renderer lifecycle stage.
4. Replace absolute paths with repository-relative paths.
5. Redact ISO timestamps, decimal values, signed numeric values, JSON payloads, and any token associated with price, bar, direction, entry, stop, target, fill, exit, resolution, return, PnL, or outcome.
6. Fail closed if the sanitized report contains a forbidden field name or any decimal number outside a source-code line/column location.
7. Prove the sanitizer on synthetic exception text containing planted outcome and market values before applying it to the sealed exception.
8. Produce the diagnostic independently with a primary parser and a reference parser. Require identical exception class/code, lifecycle classification, source locations, and redaction counts.

## Correction boundary

At most one correction may be implemented. It must be deterministic and artifact-only, and may change only hidden renderer lifecycle/finalization behavior. It may not alter source streams, payload values, decisions, execution, resolution logic, either ledger, the outcome definition, or any browser-visible pre-decision artifact.

Before Case 004 recovery, the correction must:

- pass unit tests on synthetic market/outcome-bearing exceptions;
- reproduce an existing synthetic outcome-vault artifact;
- reproduce an existing engineering-only artifact;
- leave the input ledgers and source hashes unchanged;
- generate byte-identical manifests and artifact checksums across two clean runs from separate temporary destinations.

Case 004 receives one corrected artifact-generation attempt. Another failure stops the branch. Case 005 remains unopened until Case 004 is fully certified.

