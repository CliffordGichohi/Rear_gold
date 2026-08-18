# Gold Blind Codex-Operator Replay V1 — Renderer Correction C1

Status: **FROZEN BEFORE IMPLEMENTATION**

Scope: artifact renderer only. No ledger, decision, execution, resolution, outcome, source-stream, case-population, or research rule may change.

## Confirmed failure mechanism

The authoritative backend writes and verifies each JSONL record with Python canonical JSON bytes. The renderer instead parsed each record and reserialized it with JavaScript before hashing. Equivalent IEEE-754 numbers are not guaranteed to have byte-identical Python and JavaScript JSON spellings. The sealed technical exception therefore represents a renderer-side false integrity rejection, not permission to alter the ledger.

Classification: `LEDGER_INTEGRITY_VERIFIER_CROSS_RUNTIME_CANONICALIZATION`.

## Single permitted correction

Replace only the renderer's calculated-record-hash input:

- Read each non-empty JSONL record as its original UTF-8 line.
- Split only top-level JSON object members with a deterministic string/escape/nesting scanner.
- Require exactly one top-level `record_sha256` member.
- Remove that member and its delimiter while preserving every other source byte and member order.
- SHA-256 the resulting original canonical body bytes.
- Parse the original line only for the unchanged version, sequence, prior-hash and idempotency checks and for existing renderer use.

The verifier must reject malformed JSON, duplicate or absent top-level hash members, broken sequence/version/chain, duplicate idempotency keys, or any record-hash mismatch. It must never rewrite a source ledger.

## Proof gates before Case 004

1. Synthetic Python-canonical JSONL vectors include nested values, escaped strings, Unicode, integers, ordinary decimals and cross-runtime-sensitive numeric spellings.
2. Valid vectors pass both the corrected JavaScript verifier and an independent Python verifier.
3. Tampered body, hash, sequence, prior-hash, duplicate-idempotency and duplicate-hash-member vectors fail.
4. A planted nested `record_sha256` string cannot be mistaken for the top-level member.
5. The existing engineering-only synthetic operator artifact passes without modification.
6. Two independent proof runs produce identical counts and checksums.

## One corrected production attempt

Only after every proof gate passes, the renderer may make exactly one corrected artifact-generation attempt for `CBR-2022-004`. The attempt may create only the missing hidden screenshot, hidden video, and hidden recording manifest. Those artifacts remain sealed and operator-inaccessible. All predecessor hashes must remain unchanged. A second failure stops the branch.

After independent manifest and hash verification, the missing complete Case 004 evidence manifest may be reproduced from already sealed components. Collection may then resume at unopened `CBR-2022-005`.

