# Multi-Asset Session Behaviour V1 — Milestone 1 Failure Disposition

## Formal disposition

Milestone 1 is sealed as **`FAIL_MILESTONE_1_COVERAGE_STOP`**.

The design, traceability registry, 13,380-case identity census, comprehensive case-matrix schema, source-hash verification, and two independent timestamp-only coverage calculations completed successfully. The two coverage implementations produced the same semantic checksum.

The frozen readiness rule required at least 90% of expected weekday identities in every instrument-session unit to contain every required M1 timestamp. Ten of fifteen units passed. Five failed:

| Instrument | Session | Complete identities | Expected | Complete rate |
|---|---|---:|---:|---:|
| EURUSD | Asia | 282 | 892 | 31.61% |
| USDJPY | Asia | 250 | 892 | 28.03% |
| XAGUSD | Asia | 0 | 892 | 0.00% |
| US500 | London | 498 | 892 | 55.83% |
| XTIUSD | London | 606 | 892 | 67.94% |

Across all frozen units, 10,235 of 13,380 identities are timestamp-complete. Incomplete identities remain recorded and were not deleted, imputed, relabelled as holidays, or silently admitted.

## Integrity boundary

- Predecessor seals and all certified source hashes passed.
- Gold policy `TARGET_TAKE_25_RUN_75` remains unchanged and excluded.
- XAUUSD has no target cases in this branch.
- Only development-period source metadata and `open_time` timestamps were accessed.
- No OHLC, spread, volume, direction, return, path, archetype, relationship, hypothetical return, entry, trade, PnL, 2025 value, or 2026 value was accessed or calculated.
- No source was acquired and the charge was $0.00.

## Stop boundary

Milestone 2 is **not authorized** under the failed readiness state. The generic future-milestone description in the contract and milestone summary does not override this formal failure disposition.

Any continuation requires a separately authorized, outcome-blind coverage-disposition amendment that explains the systematic market-hours/session-window mismatch without weakening a gate after observing outcomes. No such amendment is implemented here.
