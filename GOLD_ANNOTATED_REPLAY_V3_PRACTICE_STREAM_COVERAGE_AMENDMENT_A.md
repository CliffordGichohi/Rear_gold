# Gold Annotated Replay V3 — Practice Stream Coverage Amendment A

Status: `FROZEN_BEFORE_CORRECTED_MATERIALIZATION`

## Preserved result

The original `PASS_V3_PRACTICE_STREAM_MATERIALIZATION` artifact and its two byte-identical streams remain immutable. Its gate result is preserved, but the payload is not application-eligible because the source field named `complete` measures exact expected-minute coverage rather than whether a historical candle has closed. Applying that field to daily bars removed usable, already-closed daily observations and consequently every derived weekly bar for some practice dates.

## One bounded correction

Only daily/weekly display eligibility changes, reusing the sealed outcome-blind `OBSERVED_QUOTE_PATH_VALIDITY` rule already established for the predecessor replay:

- A daily bar is eligible after its recorded `close_time` and `available_at` only when `source_count >= 1000` and `source_count / (source_count + missing_source_minutes) >= 0.95`.
- Its original `complete` and `missing_source_minutes` fields remain visible as source-quality lineage; they are not relabelled.
- A weekly display bar is a deterministic aggregation of at least four eligible daily bars in a completed ISO week. It becomes visible only at the final constituent daily bar's `available_at`.
- M1, M5, M15, H1, and H4 eligibility, every timestamp boundary, all OHLC values, the twenty practice identities, context handling, execution policy, and ledger policy remain unchanged.

## Recertification gates

The corrected primary and reference streams must remain byte-identical; all original gates must pass; every practice case must contain at least one completed weekly bar and at least five eligible daily bars at its initial cursor; no collection-year or holdout payload may be materialized. The original streams are not deleted or overwritten.
