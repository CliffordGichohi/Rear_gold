# Gold Triple Macro-Acceptance Fade Validation Readiness V1

## Verdict

`BLOCKED_PENDING_FROZEN_SOURCE_ACQUISITION_AND_CALENDAR_REFRESH`

The exact post-hoc fade rule is frozen before any 2025 or 2026 relationship is calculated. XAUUSD and EURUSD are ready through 29 July 2026. Existing 2025 ZN is sealed and will be reused. No outcome, hit rate, effect, or relationship has been calculated.

## Passed readiness checks

- XAUUSD 2025: 354,160 unique one-minute timestamps; no duplicates or conflicts.
- XAUUSD 2026 YTD: 202,788 unique timestamps. The overlapping exports contain 321,578 repeated rows but zero conflicting timestamp groups, so exact deduplication is deterministic.
- EURUSD 2025: 372,561 unique one-minute timestamps; no duplicates or conflicts.
- EURUSD 2026 YTD: 214,137 unique one-minute timestamps; no duplicates or conflicts.
- ZN 2025: existing sealed Databento payload, 324,605 normalized rows. Duplicate acquisition is prohibited.
- Candidate contract SHA-256: `68554b9a1169ad50d8f89d63a65db3d9c87a390020ba1d2e1b7868c4c36bddd9`.
- Freeze-manifest SHA-256: `7c16670df2e6361c81c762ae34903fd27fc2427a53ec1ff900fe8e1f2b128c3f`.

## Exact missing futures data

| Frozen request | Estimated records | Estimate |
|---|---:|---:|
| `ZT.v.0`, 2025, `ohlcv-1m` | 281,078 | $1.026155 |
| `ZT.v.0` + `ZN.v.0`, 2026-01-01 through 2026-07-29, `ohlcv-1m` | 356,620 | $1.301943 |
| **Combined** | **637,698** | **$2.328098** |

This was a metadata-only quote. No job was submitted, nothing was downloaded, and the charge was $0.00. A $2.50 hard cap is sufficient at the present quote, but acquisition remains unauthorized.

## Calendar gap

The existing MT5 US calendar export was completed on 24 July 2026 and requested data only through 25 July. The frozen holdout ends at 00:00 UTC on 30 July. The same read-only MT5 script must therefore be rerun with `InpDateTo = 2026.07.30 00:00:00`, then collected and sealed. This is free.

## Next controlled action

After the calendar refresh and explicit Databento cap authorization, acquire only the two quoted requests, seal all sources, then open 2025 and 2026 once and apply `TRIPLE_MACRO_ACCEPTANCE_FADE_V0_1` unchanged. The formal conclusion can reject randomness only for this exact conditional state; failure will honestly reject the candidate.

Machine-readable evidence is in `research_artifacts/gold_triple_macro_acceptance_fade_validation_v01/readiness.json`.
