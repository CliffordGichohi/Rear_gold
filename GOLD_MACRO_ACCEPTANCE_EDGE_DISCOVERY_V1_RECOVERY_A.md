# Gold Macro-Acceptance Edge Discovery V1 — Recovery A

## Preserved failure

The first execution stopped before anchor construction, relationship calculation, statistics, or candidate evaluation because the loader asserted 1,218,292 rows after reading 1,220,456 rows from the frozen 42-file XAUUSD source set.

Metadata diagnosis established that the final file, `xauusd_1m_ic_markets_mt5_20241204T1405_20250103T1404.csv`, spans the development boundary. It contains exactly 2,164 timestamps at or after 2025-01-01T00:00:00Z. The pre-2025 count remains exactly 1,218,292 unique timestamps with zero duplicates.

The failed attempt deserialized the six requested OHLC/metadata columns for those 2,164 2025 rows into process memory before the assertion stopped it. No row value was displayed, inspected, selected, joined, summarized, or used in a relationship. Nevertheless, this must be recorded as a technical 2025 source opening. Calendar 2025 already has zero independent-validation credit under the governing contract. Calendar 2026 remained unopened.

## Single permitted correction

Change only the XAUUSD boundary reader:

1. read `open_time` alone to identify the prefix with `open_time < 2025-01-01T00:00:00Z`;
2. read OHLC/availability columns only for that prefix using an exact `nrows` limit;
3. require 1,218,292 rows, 1,218,292 unique timestamps, and a maximum timestamp before the boundary.

Every source file, source hash, event population, feature, signal rule, endpoint, support floor, random seed, statistical method, multiplicity gate, stability gate, ranking rule, and candidate limit remains unchanged. One recovery run is permitted. Another failure ends this branch.
