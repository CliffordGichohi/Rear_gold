# Gold Autonomous Extra-Signal PnL Attribution V1

Status before path access: `FROZEN_EXPOSED_ATTRIBUTION_ONLY`

This is a narrow answer to the question: what would the nine additional
same-month scanner detections have contributed? It does not repair the sealed
`FAIL_AUTONOMOUS_SEMANTICS` verdict, does not give the scanner validation
credit, and does not open another month, 2025, or 2026.

## Preserved results

- Human-input V2 overlay: 11 admitted, 5 rejected, `+10.68184658R`.
- Autonomous semantic gate: FAIL (13/16 human trade days matched, 9/14 human
  no-trade days signalled, median timing error 20 minutes).
- The nine rows below are false positives relative to the human labels. They
  were signals, not previously executable trades: the scanner had not supplied
  entry, stop, or target geometry.

## Frozen population and signal timestamps

All signals are LONG because the calibrated scanner represented the sixteen
human LONG examples only.

| Case | Signal UTC |
|---|---|
| CBR-2022-004 | 2022-01-10T14:10:00Z |
| CBR-2022-008 | 2022-01-14T13:40:00Z |
| CBR-2022-011 | 2022-01-19T14:10:00Z |
| CBR-2022-016 | 2022-01-27T13:40:00Z |
| CBR-2022-017 | 2022-01-28T16:10:00Z |
| CBR-2022-018 | 2022-01-31T15:55:00Z |
| CBR-2022-021 | 2022-02-03T13:40:00Z |
| CBR-2022-022 | 2022-02-04T14:45:00Z |
| CBR-2022-029 | 2022-02-15T16:10:00Z |

The final seal preserves the aggregate nine-signal finding. The live semantic
calibration payload was overwritten by a later rerun 33 seconds after the
seal and no longer matches the sealed hash. Therefore these identities are
explicitly preserved as recovered run-log identities and the result below is
reported as exposed attribution, not sealed autonomous validation.

## Frozen point-in-time control geometry

1. Decision is the recorded scanner timestamp. Only completed bars available
   at that timestamp may define geometry.
2. Entry is a market LONG at the first observed M1 open strictly after the
   signal. Actual entry adds half the observed spread and `$0.05/oz` slippage.
3. Stop reference is the protected low of the latest active bullish M15
   structural break. If unavailable, use the latest point-in-time confirmed
   M15 swing low strictly below the raw entry. The raw stop is the reference
   minus `0.10 × completed M15 ATR(14)`. Missing or non-adverse geometry makes
   the signal non-executable; it is not repaired.
4. Target is the nearest point-in-time active, forward H1 liquidity zone; if
   none exists, the nearest active forward H4 liquidity zone. Permitted states
   are `ACTIVE_UNTOUCHED`, `ACTIVE_ENGAGED`, and `REACTIVATED_REVERSE`. There is
   no fixed-R target fallback. Missing target makes the signal non-executable.
5. Whole-ounce size is `floor($50 / planned worst-case loss per ounce)`. The
   planned stop fill uses the entry-time spread and `$0.05/oz` stop slippage.
6. M1 first passage is stop-first on an ambiguous bar. A stop fills at the
   worse of the raw stop or opening gap, minus half the contemporaneous spread
   and `$0.05/oz` slippage. A target is a resting limit and fills at its raw
   price. Commission is the already frozen `$0.00/oz`.
7. After a completed M15 close reaches `+1.25` structural R, the stop is moved
   on the next M1 bar to a contemporaneously estimated net-break-even raw
   level. No runner is allowed because these rows have no human target-owner
   classification.
8. Any unresolved trade exits at the final observed M1 close of that UTC day,
   paying half the observed spread and `$0.05/oz` slippage.

## Frozen reporting

Report every signal, executable status, entry, stop, target, size, resolution,
net dollars, net R (`$50 = 1R`), MFE and MAE. Report:

- the nine-signal standalone total;
- the arithmetic hybrid `+10.68184658R + extra-signal total` requested by the
  user;
- the important limitation that the hybrid combines human geometry for the
  original setups with control geometry for the nine extras.

Run identical primary and reference source calculations and require identical
row and summary hashes. Do not change the geometry after path access.
