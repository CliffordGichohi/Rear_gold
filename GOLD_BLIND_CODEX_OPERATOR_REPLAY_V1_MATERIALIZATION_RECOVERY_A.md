# Gold Blind Codex-Operator Replay Audit V1 — Materialization Recovery A

Status: frozen after Attempt 1 terminated and before Recovery A accesses source values.

## Preserved failure

The first private-stream materialization attempt was terminated by the shell's fixed 120-second command timeout. It completed only a consecutive primary prefix, started no reference pass, wrote no certification, rendered no chart, reported no market value, accessed no outcome, and made no operator decision.

All partial files remain immutable with zero research or validation credit. Recovery A records their filenames, sizes, hashes and internal stream-hash validity in `materialization_attempt_1_timeout.json`; it does not delete, overwrite, reuse or promote them.

## Bounded correction

Recovery A changes only the value-blind lookup implementation used to select an already frozen timeframe interval:

- Replace a full price-table scan for every case/timeframe with binary search over the same ordered `close_at` timestamps.
- Retain the exact prior `close_at`, `available_at`, `[start,end)`, history-limit, ordering, uniqueness, bar, context, case, hash and independent-reproduction definitions.
- Write both recovery passes to new append-only `private_streams_recovery_a` directories.
- Retain the same 249 cases, sources, case identities, output schema and certification gates.

This correction changes computational complexity only. It cannot change which row qualifies, any value, any decision field, any outcome, or any research rule.

## Gates

Recovery A may certify only when:

1. the pre-value freeze and browser-isolation certification remain intact;
2. Attempt 1 is structurally sealed as the failed consecutive prefix;
3. both complete 249-case recovery passes reproduce exact per-row hashes, counts, complete-set checksums and byte-identical gzip files;
4. no 2022 chart has been rendered and no outcome or human decision has been accessed; and
5. 2025/2026 remain locked and no charge or external upload occurs.
