# GC Microstructure Research — Step 1 Metadata Quote

Status: **COMPLETE — NO PURCHASE SUBMITTED**

Provider observation date: 2026-07-30  
Provider: Databento Historical Metadata API  
SDK: `databento 0.82.0`

## Frozen quote request

- Dataset: `GLBX.MDP3`
- Symbol: `GC.v.0`
- Input symbology: `continuous`
- Start: `2024-01-09T00:00:00Z`
- End: `2024-01-10T00:00:00Z`
- Duration: one non-holiday 24-hour period

## Metadata results

| Schema | Records | Billable bytes | Estimated cost (USD) |
|---|---:|---:|---:|
| `mbo` | 2,322,905 | 130,082,680 | $0.218068 |
| `mbp-10` | 1,924,786 | 708,321,248 | $0.329838 |
| `trades` | 74,528 | 3,577,344 | $0.093287 |
| `definition` | 1 | 360 | $0.00000057 |

The provider reported 2024-01-09 and 2024-01-10 as `available`.

## Historical coverage

- `mbo`: available from 2017-05-21
- `mbp-10`: available from 2010-06-06
- `trades`: available from 2010-06-06
- `definition`: available from 2010-06-06

All schemas therefore cover the intended 2021-08-01 through 2024-12-31
development period.

## Finding

The prior planning assumption that MBO would necessarily be larger and more
expensive was incorrect for this representative GC day. MBO contained more
records but had:

- 81.6% lower billable size than MBP-10; and
- 33.9% lower estimated cost than MBP-10.

MBO is therefore the preferred candidate for the one-day engineering pilot,
subject to explicit user approval of a new cost cap. It is also richer than
MBP-10, but reconstructing and validating the order book is computationally
more involved.

## Guardrails observed

- Metadata endpoints only
- No batch job submitted
- No timeseries data endpoint called
- No file downloaded
- No market values inspected
- No charge authorized
- No strategy or hypothesis tested

## Required next authorization

Before Step 2, obtain an explicit maximum charge for a one-day MBO engineering
pilot. Re-check the live metadata estimate immediately before any submission
and stop if it exceeds the approved cap.
