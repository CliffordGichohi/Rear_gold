# Gold Casebook Milestone 2 Evidence

## Result

Milestone 2, **Immutable casebook**, is complete.

The frozen bundle contains 1,606,819 unique, content-addressed records built
from real pre-2025 sources:

- 833 complete London cases;
- 826 complete New York cases;
- 1,570,471 XAUUSD price-bar records;
- 3,270 point-in-time six-timeframe structure snapshots;
- 4,353 cross-market snapshots;
- 26,394 fundamental observation/policy/snapshot records;
- 260 weekly CFTC positioning reports; and
- 412 scheduled event cases.

The build and the independent semantic audit both confirm:

- calendar 2025 was not loaded;
- session-close facts are separate from session-open decisions;
- every decision join was available by the decision clock;
- every structure detection was confirmed by its snapshot clock;
- COT Friday publication time was respected;
- all 412 historical event cases retain pre-event schedule and consensus as
  `UNKNOWN`;
- stale US500 values were marked `STALE`, not neutral;
- continuous CME changes crossing a contract roll are `UNKNOWN`; and
- no profitability, direction label, entry, exit, stop, target, MFE, MAE, or
  execution optimization was calculated.

## Primary evidence

- Bundle manifest:
  `research_artifacts/gold_casebook_v01/manifest.json`
- Manifest hash:
  `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f`
- Independent semantic validation:
  `research_artifacts/gold_casebook_v01/semantic_validation.json`
- Semantic-validation hash:
  `5ba0f3818dc717f4c8eeace6b69d73f64906a6aeef32f7e7a801fce77dc7a92f`
- JSON Schema:
  `research_schemas/gold_casebook_v01.schema.json`
- Schema SHA-256:
  `47c139c2de8dedcdaf171d87316e45a76d2111b3073ff1db168f8667df2172e7`
- Data dictionary:
  `GOLD_CASEBOOK_DATA_DICTIONARY.md`
- Builder:
  `backend/tools/build_gold_casebook.py`
- Independent validator:
  `backend/tools/validate_gold_casebook.py`

## Artifact ledger

| Artifact | Records | SHA-256 |
|---|---:|---|
| `price_bars.jsonl.gz` | 1,570,471 | `0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e` |
| `structure_snapshots.jsonl.gz` | 3,270 | `31eea2decc8ed3f8d3e498a9339e7f59ee101e7c787da47a831e63bfb97c1064` |
| `cross_market_snapshots.jsonl.gz` | 4,353 | `470a2e1c020cd2f97f2ad5b0d7f9c5220aff4f644689c4d680c24373964eb285` |
| `positioning.jsonl.gz` | 260 | `e6d1aabf0d4401f3af4e54dc8ef4c0e4074772ec3f2199cfe9009b5a0b267228` |
| `events.jsonl.gz` | 412 | `c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f` |
| `fundamentals.jsonl.gz` | 26,394 | `d2b776f60c4535978bbfb28706b4700e6d054a10f8d57cfee171c83b212b7235` |
| `sessions.jsonl.gz` | 1,659 | `2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a` |

The independent validator recomputed all seven artifact hashes and all
1,606,819 row hashes. It also counted 536,978 point-in-time structure
detections.

## Price and quality evidence

The price ledger contains:

| Timeframe | Records | Incomplete buckets |
|---|---:|---:|
| 1 minute | 1,218,292 | 0 |
| 5 minutes | 244,184 | 1,573 |
| 15 minutes | 81,407 | 1,534 |
| 1 hour | 20,366 | 1,503 |
| 4 hours | 5,329 | 1,821 |
| Daily | 893 | 631 |

Incomplete aggregates are retained and visibly flagged. They are excluded from
structure calculations and cannot admit a session case. Daily completeness is
strict: one absent underlying broker minute makes the daily bucket incomplete.
This is fail-closed and explains the higher daily incomplete count; missing
minutes are not fabricated.

The source-support interval begins
`2021-07-23T14:05:00Z`; the research case interval begins
`2021-08-01T00:00:00Z` and ends before `2025-01-01T00:00:00Z`.

## Build-gate audit

Two unpublished attempts correctly failed closed:

1. The reconstruction pass initially allowed an incomplete 5-minute aggregate
   to enter the session map. The complete-bucket filter was corrected before
   any bundle was accepted.
2. The first boundary validator rejected a 2024 aggregate whose interval
   legitimately closed exactly at the exclusive
   `2025-01-01T00:00:00Z` endpoint. The rule now permits that close boundary,
   rejects any close beyond it, and excludes a partial New York trading day
   whose actual close would occur inside 2025.

The final build then passed its internal verification, and the separately
implemented validator passed over the frozen outputs.

## Reproduction

From the repository root with the existing real-data Docker environment:

```powershell
docker compose --profile test run --rm `
  -e PYTHONPATH=/app/src `
  -v "${PWD}:/workspace" `
  backend-test python tools/build_gold_casebook.py

docker compose --profile test run --rm `
  -e PYTHONPATH=/app/src `
  -v "${PWD}:/workspace" `
  backend-test python tools/validate_gold_casebook.py
```

The builder refuses to overwrite an existing bundle. A new casebook definition
must receive a new version and output path.

## Remaining declared limitations

- Historical pre-event calendar and consensus vintages are not verified.
- No licensed historical unscheduled-event feed is present.
- US500 intraday history ends on 14 January 2022; 3,692 affected snapshots are
  explicitly stale.
- Intraday centralized COMEX gold volume/open interest is unavailable.
- The 5,028 Atlanta Fed policy records are quarterly SOFR distribution windows,
  not exact meeting-level FedWatch probabilities.

These limitations are recorded, not imputed.

## Next contracted step

Milestone 3 is **Constant-execution baseline**. It has not started. Its first
action is to freeze the machine-readable execution manifest before calculating
always-long, always-short, or deterministic-random controls.
