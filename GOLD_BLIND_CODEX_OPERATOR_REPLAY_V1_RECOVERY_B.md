# Gold Blind Codex-Operator Replay Audit V1 — Recovery B

## Scope

This is a deterministic, value-blind recovery for `CBR-2022-004` only. The visible decision was already committed exactly once and the backend reports four terminal cases. The certified hidden outcome renderer then exited before writing its recording manifest. No outcome artifact or value was exposed to the operator.

## Preserved facts

- The Case 004 decision, visible ledger row, hidden ledger row, pre-decision evidence, browser trace, browser video, and chronological action log remain immutable.
- The decision is not reopened, edited, resubmitted, or re-resolved.
- The outcome vault remains operator-inaccessible.
- Case 005 is not opened during this recovery.
- No market source, chart value, outcome value, 2025 data, or 2026 data is inspected.

## One-attempt recovery

1. Run the unchanged, previously certified hidden outcome renderer once for alias `CBR-2022-004`.
2. Redirect renderer stdout and stderr to sealed technical logs; expose only its exit code and the existence, byte size, and SHA-256 of the resulting manifest.
3. If the renderer succeeds, construct the complete Case 004 evidence manifest solely from the already sealed pre-decision manifest, complete action log, finalized browser trace/video, and hidden outcome-recording manifest.
4. Verify hashes and then restart the browser operator at the next server-selected case.
5. Any second renderer failure is a genuine integrity blocker and stops collection.

## Frozen Case 004 evidence

- Pre-decision manifest: `1bf5cad6d7e1f8e15e6528aa2d1812aa52b8509a822efa2ec986849ea46a0b7a`
- Complete action log: `e746531623e234da942f6c3e3695ea60a64be6eca737e87f5ca3a6342a54a4ac`
- Browser trace: `d9d7875ade9dd0f938c06ea5390cd56ea43d10b53100a6e9f73a50087f9bf3c5`
- Browser video: `eedf070bde1e06eab2627a7cbcd7f5809a3c68321b2f63fe7222cadb6c41c53d`

