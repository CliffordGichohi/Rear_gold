# Multi-Asset Session Behaviour V1 — Comprehensive Case Matrix

Schema: `research_schemas/multi_asset_session_behaviour_archetype_monetization_v1_case_matrix.schema.json`  
Frozen fields: **112**

One future row represents one frozen `instrument × session_code × local_session_date` identity.

```text
case
├── case_metadata
├── lineage
├── decision_state                 available_at <= decision_at
│   ├── mechanics and quality
│   ├── completed W1/D1/H4/H1/M15/M5 structure
│   ├── pre-existing levels
│   ├── macro, expectations, positioning and catalysts
│   ├── session and cross-market context
│   └── synthesis, contradictions and unknowns
├── subsequent_behaviour           decision_eligible = false
│   ├── fixed neutral reference
│   ├── fixed-horizon displacement
│   ├── range and symmetric MFE/MAE
│   ├── first-passage clocks
│   ├── high/low timing and path statistics
│   ├── known-level interactions
│   └── deterministic archetype
├── quality
└── research_policy                all execution/PnL flags false
```

The neutral reference is the exact M1 open at `decision_at + 1 minute`. It is not an assumed fill. `long_mfe`, `long_mae`, `short_mfe`, and `short_mae` are symmetric path coordinates; no trade direction is assigned.

A future case may be `VALID` only if its identity is frozen, its observation path has every expected M1 timestamp, IANA/DST conversion passes, duplicate identity checks pass, all decision facts satisfy availability, and source hashes match. Incomplete identities remain in the coverage ledger and cannot be silently deleted.

Milestone 1 defines this schema but creates **zero case rows**.
