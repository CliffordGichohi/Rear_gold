# Gold Blind Discretionary Replay V1 — Coverage Amendment A

Status: `FROZEN_BEFORE_HUMAN_LABELING`

The initial past-only materialization reproduced exactly and passed its leakage checks, but a post-materialization coverage audit found that the casebook's strict aggregate `complete` flag rejects otherwise usable broker-day bars whenever one or more no-quote minutes exist. Consequently, 188 of 240 scored displays had fewer than 120 daily bars and 209 had fewer than 52 weekly bars. No human decision, trade outcome, relationship, 2025 value, or 2026 value was accessed.

The original population freeze, payloads, certification, and this formal coverage failure remain immutable.

This amendment changes only display-history eligibility:

1. A casebook daily bar is `OBSERVED_QUOTE_PATH_VALID` when its source count is at least 1,000 and `source_count / (source_count + missing_source_minutes) >= 0.95`. Its recorded OHLC is used unchanged; missing minutes are not interpolated.
2. A completed weekly display candle uses only such daily bars and requires at least four eligible daily bars in the prior ISO week. The ISO week containing the checkpoint is excluded.
3. Every scored case must have exactly 52 weekly, 120 daily, 90 H4, 120 H1, 160 M15, 180 M5, and 180 M1 display bars under the amended policy.
4. Practice cases retain their original identities and may show explicitly partial weekly/daily/H4 history because they carry zero research credit.
5. A scored case failing the new display gate is replaced by the next outcome-blind candidate in the same frozen year × session stratum under the original assignment and selection hashes. Passing scored identities remain unchanged. Aliases and presentation positions remain unchanged. No date may appear twice.
6. No price direction, return, extrema, event reaction, trade, or outcome may participate in replacement.

Every other contract definition, decision field, execution rule, risk rule, support floor, statistical gate, 2025/2026 lock, and prohibition remains unchanged.
