# GC Session Trigger Edge Discovery V2 Milestone 3-R1

Status: `AUTHORIZED_SERIALIZATION_ONLY_RECOVERY_BEFORE_SECOND_SOURCE_OPENING`

## Preserved failure

The sealed verdict `FAIL_M3_SINGLE_OUTCOME_OPEN_SERIALIZATION`, its source-opening count of one, and every predecessor
artifact and seal remain immutable. The first opening receives zero research credit. No relationship test, hit rate,
candidate, execution rule, trade, PnL, R multiple, or return was produced by it.

## Sole correction

The only permitted analytical implementation change is the positional argument order of the frozen Parquet writer:

- failed: `pq.write_table(temporary, table, ...)`
- corrected: `pq.write_table(table, temporary, ...)`

The original frozen implementation is not edited. R1 imports it unchanged and substitutes only a corrected writer
having the identical schema, compression, dictionary, statistics, data-page, version, and row-group parameters.

## Mandatory proof before source access

Before another market source may be opened, R1 must use the exact frozen outcome schema to:

1. write independently constructed synthetic primary and reference payloads;
2. require byte-identical Parquet files and identical SHA-256 checksums;
3. read both files back and require exact row, schema, null, and value equality;
4. verify that the original failed implementation, failure artifacts, pre-outcome freeze, population, tests, and
   protocol remain unchanged;
5. seal the R1 amendment, wrapper, proof, and pre-source freeze.

Any proof failure terminates R1 without another source opening.

## Recovery opening and analysis

After a proof pass, R1 permits exactly one additional controlled opening of the unchanged sealed development sources.
The cumulative opening count must remain two. The second opening must reconstruct and persist the unchanged 4,930-event
outcome join and reproduce primary/reference output exactly.

Only after the join is sealed may the unchanged Milestone 3 procedure run: all twelve Stage-1 tests, independent
Stage-1 reproduction and seal, then only the twenty-six frozen support-eligible Stage-2 tests while retaining the
thirty-four support failures. Candidate selection remains capped at two per session under the frozen ranking order.

## Boundaries

No outcome, event, test, context, threshold, seed, support status, missing-data rule, uncertainty method, multiplicity
method, stability gate, ranking, or candidate may be altered, inverted, repaired, retuned, or selectively filtered.
Calendar 2025 and 2026 remain locked. No data is acquired and no charge is incurred. Execution, trades, PnL, R
multiples, position sizes, and account returns remain prohibited.

A second R1 failure permanently terminates this milestone. R1 must independently verify, document, seal, and stop.
