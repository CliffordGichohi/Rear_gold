# Gold Casebook Discovery V2 Coverage Audit

## Decision

V2 Milestone 1 is complete.

- The V2 contract is frozen at
  `81e39b469111bb92a46c0d2c70f863cba438b647345104d4b8e8bc1a9e4d8188`.
- The prior universal rule remains `REJECT_CHRONOLOGICAL_VALIDATION`.
- Calendar 2024 is development data with no independent validation credit.
- No calendar-2025 OHLC, market value, feature, outcome, return, P&L, or
  feature-outcome join was read or calculated.
- Relationship discovery did not begin.

Deterministic coverage hash:

`d5b84416bc75fa1cf9f3ddb35dc04af630b0fcf41a6b2ba8b731aebd12606eb6`

## Audit boundary

The audit used identifiers, timestamps, counts, completeness flags, non-null
counts, filenames, sizes, and hashes only. Eight SQL statements passed the
forbidden-value-column guard. Raw 2025 XAUUSD CSV content was hashed but never
deserialized.

## Development readiness

The immutable 2021-2024 casebook is reusable as V2 development data.

| Item | Evidence |
|---|---:|
| Casebook manifest | `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f` |
| London cases | 833 |
| New York cases | 826 |
| Session cases | 1659 |
| Cross-market snapshots | 4353 |
| Structure snapshots | 3270 |

This audit calculated no development outcome.

## Calendar-2025 metadata coverage

| Source | Metadata result | Status |
|---|---|---|
| IC Markets XAUUSD 1m | 354,160 unique observed rows; 2025-01-02T01:00:00+00:00 through 2025-12-31T23:58:00+00:00; spread and volume present on every row | READY |
| Timestamp-complete London cases | 257 of 261 weekdays (98.4674%) | AVAILABLE |
| Timestamp-complete New York cases | 257 of 261 weekdays (98.4674%) | AVAILABLE |
| Databento ZN.v.0 1m | Existing normalized request ends before 2025 | MISSING |
| Macro observations | 20 non-synthetic series have 2025 availability metadata | AVAILABLE, feature-specific checks still required |
| CFTC gold COT | 52 published reports | AVAILABLE |
| MT5 economic events | 107 event identities and 201 release components | POST-RELEASE AVAILABLE |
| Historical pre-event consensus | 0 of 186 forecast components verified for pre-event use | MISSING |
| Policy expectation windows | 251 observation dates | PARTIAL: quarterly-window source, not meeting-level FedWatch |

## Candidate readiness

`LONDON_ZN_4H_POSTHOC_V0_1` is currently
**BLOCKED_MISSING_ZN_2025**.

The frozen XAUUSD execution source is ready, but 2025 Databento `ZN.v.0`
one-minute history is not present. This is not a reason to open or approximate
the holdout. If the London ZN candidate reaches the frozen shortlist, acquire
the licensed 2025 ZN payload, normalize it with continuous-roll lineage, hash
and seal it, and only then run the one-time holdout.

Other future candidates remain `FEATURE_DEPENDENT`; their precise holdout
coverage cannot be certified before they exist.

## Material controls

- No proxy may silently replace missing 2025 ZN.
- Missing historical pre-event consensus remains `UNKNOWN`.
- Acquiring a source is not permission to inspect its values.
- A candidate-specific metadata audit is required after Milestone 5 and before
  Milestone 6.
- Calendar 2026 remains outside V2.

## Next contracted step

V2 Milestone 2 is the descriptive 2021-2024 fixed-outcome atlas, separately for
London and New York. It is not authorized by this run and was not started.

## Reproduce

```powershell
docker compose --profile test run --rm `
  -v "${PWD}:/workspace" `
  -e PYTHONPATH=/workspace/backend/src `
  backend-test python /workspace/backend/tools/audit_gold_casebook_discovery_v2_coverage.py `
  --mt5-directory /workspace/data/mt5 `
  --cme-normalization /workspace/data/raw/databento_cme_pre2025/GLBX-20260728-3SHU3737P8/normalized/normalization.json `
  --contract-manifest /workspace/research_manifests/gold_casebook_discovery_contract_v02.json `
  --casebook-manifest /workspace/research_artifacts/gold_casebook_v01/manifest.json `
  --prior-validation-manifest /workspace/research_artifacts/gold_casebook_chronological_validation_v01/manifest.json `
  --json-output /workspace/research_artifacts/gold_casebook_discovery_v2_coverage.json `
  --markdown-output /workspace/GOLD_CASEBOOK_DISCOVERY_V2_COVERAGE.md
```
