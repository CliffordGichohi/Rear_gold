# Gold Triple Macro-Acceptance Fade Acquisition Authorization V1

## Authorization

On 7 August 2026, the user authorized acquisition of exactly the two frozen Databento requests below with a maximum combined charge of `$2.50`, using available account credits only. No card charge is authorized.

1. `GLBX.MDP3`, `ZT.v.0`, `ohlcv-1m`, continuous symbology, `2025-01-01T00:00:00Z` through `2026-01-01T00:00:00Z`.
2. `GLBX.MDP3`, `ZT.v.0` and `ZN.v.0`, `ohlcv-1m`, continuous symbology, `2026-01-01T00:00:00Z` through `2026-07-30T00:00:00Z`.

Existing sealed `ZN.v.0` calendar-2025 data must be reused and must not be reacquired.

## Mandatory pre-submission gates

- Recalculate both estimates immediately before submission.
- Stop without submitting if their combined estimate exceeds `$2.50`.
- Stop if the frozen request parameters change.
- Stop if the corrected MT5 calendar export does not cover the frozen 2026 endpoint.
- Stop if the Databento SDK version differs from `0.82.0`.
- Never record or print the API key.

The Databento historical API does not expose a funding-source switch or credit-balance endpoint. Credit sufficiency is therefore based on the user's explicit statement that the newly installed key belongs to the fresh-credit account. If the provider rejects a request for billing or entitlement reasons, the process must stop rather than alter the request or use another payment route.

## Post-acquisition rules

Preserve raw downloads unchanged; record provider job IDs, actual costs, hashes, schemas, record counts, timestamp bounds and symbology. Normalize deterministically, hash and seal the sources before any 2025 or 2026 relationship is calculated. No additional request is authorized by this amendment.
