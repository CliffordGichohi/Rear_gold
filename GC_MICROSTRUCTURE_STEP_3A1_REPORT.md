# GC Microstructure Research — Step 3A.1 Market-State Amendment

Status: **PASS — 25 OF 25 AMENDED GATES PASSED**

Completion date: 2026-07-30  
Classification: **POST-RESULT ENGINEERING SEMANTICS CORRECTION**  
Research or validation credit: **NONE**

## Predecessor preservation

The original Step 3A formal verdict remains **FAIL**.

Before Step 3A.1, the following predecessor files were frozen by byte count and
SHA-256 and reverified:

- Step 3A protocol;
- unchanged reconstruction implementation;
- primary replay;
- reference replay;
- original comparison;
- original manifest; and
- locked/crossed boundary diagnostic.

The original Step 3A manifest hash remains:

`0897e33856c5329ee59040ff5a6c15f48cb65fc17dcf3e63ec1f8c5bf3c6c59c`

No predecessor file or verdict was changed.

## Sole amendment

The original gate required zero locked or crossed books at every `F_LAST`
boundary, irrespective of market state.

Step 3A.1 replaced only that gate with:

> Locked or crossed boundaries must equal zero during
> `CONTINUOUS_MATCHING`.

Maintenance and pre-open boundaries remain reported but are not rejected by
this specific invariant.

Every other Step 3A gate, source record, action rule, queue rule, checkpoint,
and reconstruction implementation remained unchanged.

Frozen UTC intervals for 2024-01-09:

| State | Start | End |
|---|---|---|
| Continuous matching | 00:00 | 22:00 |
| Maintenance | 22:00 | 22:45 |
| Pre-open | 22:45 | 23:00 |
| Continuous matching | 23:00 | 24:00 |

## Exact replay reproduction

Both implementations reread all 2,322,905 sealed records.

- Primary predecessor result hash reproduced exactly: **PASS**
- Reference predecessor result hash reproduced exactly: **PASS**
- Original comparison reproduced exactly: **PASS**
- Input stream hash unchanged: **PASS**
- All 11 checkpoint hashes unchanged: **PASS**
- Final order-state hash unchanged: **PASS**
- Final queue-and-level hash unchanged: **PASS**
- All 24 unchanged gates equal their predecessor values: **PASS**

Input stream hash:

`cc090b6c6b64c580f3a374ffafdc1410b5526c866c069884f0f568767e53af6b`

Final state hash:

`126dde879acec948c2a19625bef18f3dcb3beb156ddec37eeb86acc3937eef0c`

Final structure hash:

`9d64e788c157bb7e8b988d4099b40110f4b4d5070e479f956e918237fe515caf`

## Market-state boundary audit

All 2,062,923 `F_LAST` boundaries were classified exactly once.

| Market state | Boundaries | Uncrossed | Locked | Crossed |
|---|---:|---:|---:|---:|
| Continuous matching | 2,062,542 | 2,062,542 | 0 | 0 |
| Maintenance | 1 | 1 | 0 | 0 |
| Pre-open | 380 | 341 | 15 | 24 |
| **Total** | **2,062,923** | **2,062,884** | **15** | **24** |

Technical audit:

- Classification gaps: 0
- Classification overlaps: 0
- Heap/direct best-price disagreements: 0
- Final structural invariant violations: 0
- All-hours counts equal original Step 3A counts: **PASS**

The 39 original locked/crossed observations remain present and recorded. They
were not deleted or reclassified as uncrossed; they are assigned to the frozen
pre-open state.

## Verdict

The amended engineering verdict is **PASS**:

- Amended gates passed: 25/25
- Integrity checks passed: 11/11
- Continuous-matching locked/crossed boundaries: 0
- Original Step 3A formal FAIL preserved: yes
- Retroactive research or validation credit: none

This establishes that the deterministic GC MBO reconstruction is technically
ready for an independent MBP-10 comparison. It does not establish a trading
edge.

## Seal

Step 3A.1 manifest hash:

`334b67560ee5912ed1939305715078b3f9460d389feb8cc17723a062543d657c`

The seal independently verified:

- primary replay;
- reference replay;
- market-state boundary audit;
- amended comparison;
- unchanged predecessor hashes;
- unchanged replay-tool hash; and
- Step 3A.1 orchestration-tool hash.

## Guardrails

No additional data was acquired. No price levels were reported. No
directional statistics, features, signals, outcomes, execution rules, trades,
PnL, R multiples, or account returns were calculated.

Step 3B has not started.
