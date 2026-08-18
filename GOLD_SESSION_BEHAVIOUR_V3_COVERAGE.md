# Gold Session Behaviour V3 — Metadata-Only Coverage Audit

## Decision

The V3 Milestone 1 coverage audit is complete.

- Contract hash:
  `79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b`
- Traceability hash:
  `8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4`
- Deterministic coverage hash:
  `35e03c1b9b63e9a9e399fd9d9f6d0a9dd39ce40490723a8057b103ce843a6bcd`
- 2025 values or outcomes inspected: **no**
- 2026 values or outcomes inspected: **no**
- Relationships calculated: **zero**
- Candidates created: **zero**

This audit does not authorize Milestone 2.

## Audit boundary

The database transaction was read-only. Eight SQL statements passed a
forbidden-value-column guard. They selected identifiers, timestamps, counts,
completeness/synthetic/revision flags, point-in-time ordering counts, and
non-null spread/volume counts only.

Raw XAUUSD files were byte-streamed only to calculate SHA-256, size, filename
time bounds, and overlap metadata. No CSV parser was invoked. The sealed 2025
Databento normalization manifest was read, but its OHLCV payload was not
deserialized.

No market, macro, release, forecast, positioning, probability, feature,
direction, return, excursion, P&L, or outcome value was selected.

## Development: 2021-08-01 through 2024-12-31

The immutable source bundle is present:

| Item | Metadata |
|---|---:|
| Casebook manifest | `GOLD_CASEBOOK_V0_1` / `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f` |
| London cases already recorded | 833 |
| New York cases already recorded | 826 |
| Session cases | 1659 |
| Structure snapshots | 3270 |
| Cross-market snapshots | 4353 |
| Positioning reports | 260 |
| Event cases | 412 |

V3 case rows were not materialized. No development outcome or relationship was
calculated by this audit.

## Exposed calendar 2025

Calendar 2025 is real but already exposed by V2. This run inspected metadata
only.

| Source family | Metadata observed |
|---|---:|
| IC Markets XAUUSD 1m rows | 354,160 |
| XAUUSD timestamp-complete London cases | 257 / 261 weekdays |
| XAUUSD timestamp-complete New York cases | 257 / 261 weekdays |
| Macro series identifiers | 20 |
| Published COT report metadata rows | 52 |
| Economic event identities | 107 |
| Verified pre-event forecast rows | 0 |
| Raw XAU files overlapping interval | 14 |
| Sealed Databento ZN rows declared by metadata | 324,605 |

These counts do not grant 2025 independent-validation status and do not expose
the underlying values.

## Locked 2026 YTD

The independent YTD date boundary is session dates 1 January through
29 July 2026. Values remain locked.

| Source family | Metadata observed |
|---|---:|
| IC Markets XAUUSD 1m rows | 199,032 |
| XAUUSD timestamp-complete London cases | 140 / 150 weekdays |
| XAUUSD timestamp-complete New York cases | 139 / 150 weekdays |
| Macro series identifiers | 20 |
| Published COT report metadata rows | 30 |
| Economic event identities | 348 |
| Verified pre-event forecast rows | 0 |
| Raw XAU files overlapping interval | 18 |
| Overlapping raw-XAU filename pairs | 29 |
| 2026 CME rates archive | NOT_PRESENT |

The timestamp audit shows that the locked YTD source is not yet a complete
weekday set. Missing sessions are retained in the JSON artifact and may not be
synthesized. Several raw 2026 MT5 exports overlap; canonical database
uniqueness and source hashes must prevent double counting.

## Book-field coverage

The 75 frozen Reference Book requirements have the following development
status:

| Status | Count |
|---|---:|
| Present | 34 |
| Derivable, not calculated | 14 |
| Partial | 18 |
| Unavailable | 6 |
| Execution out of scope | 3 |

The unavailable fields remain order-book depth/resilience/impact, exact
meeting-level Fed probabilities, ETF flows, central-bank demand, options/gamma,
and unscheduled-news history.

## Preserved negative evidence

- `UNIVERSAL_ZN_4H_SIGN_V0_1` remains
  `REJECT_CHRONOLOGICAL_VALIDATION`.
- `LONDON_ZN_4H_POSTHOC_V0_1` remains
  `REJECT_CALENDAR_2025_HOLDOUT`.

The 2025 ZN archive remains a sealed real source, but the rejected rule is not
reopened, inverted, filtered, or renamed.

## Readiness interpretation

This is a source-family audit, not candidate readiness:

- the development bundle is available for a separately authorized V3
  Milestone 2;
- 2025 remains excluded from discovery;
- 2026 source coverage is incomplete and its values remain locked;
- exact future candidate coverage cannot be certified before candidates exist;
  and
- no paid 2026 acquisition is justified in Milestone 1.

## Mandatory stop

V3 Milestone 1 ends after governance validation and state sealing. V3
Milestone 2 is not authorized and was not started.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/audit_gold_session_behaviour_v3_coverage.py `
  --mt5-directory /workspace/data/mt5 `
  --cme-2025-normalization /workspace/data/raw/databento_cme_2025_zn/GLBX-20260729-4KJJLBXRRH/normalized/normalization.json `
  --cme-2026-directory /workspace/data/raw/databento_cme_2026 `
  --contract-manifest /workspace/research_manifests/gold_session_behaviour_discovery_contract_v03.json `
  --traceability-catalog /workspace/research_manifests/gold_session_behaviour_v3_traceability_v01.json `
  --case-matrix-schema /workspace/research_schemas/gold_session_behaviour_v3_case_matrix.schema.json `
  --casebook-manifest /workspace/research_artifacts/gold_casebook_v01/manifest.json `
  --original-rejection-manifest /workspace/research_artifacts/gold_casebook_chronological_validation_v01/manifest.json `
  --v2-rejection-manifest /workspace/research_artifacts/gold_casebook_discovery_v2_holdout_v01/manifest.json `
  --reference-book /workspace/Gold_USD_Market_Intelligence_Reference_Book.pdf `
  --json-output /workspace/research_artifacts/gold_session_behaviour_v3_coverage_v01.json `
  --markdown-output /workspace/GOLD_SESSION_BEHAVIOUR_V3_COVERAGE.md
```
