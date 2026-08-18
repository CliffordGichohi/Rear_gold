# GC Microstructure Research — Step 2 Engineering Pilot

Status: **COMPLETE — TECHNICAL QUALITY PASS**

Completion date: 2026-07-30  
Classification: **ENGINEERING_ONLY**  
Research and validation exclusion: **PERMANENT**

## Frozen acquisition

- Provider: Databento
- Dataset: `GLBX.MDP3`
- Symbol: `GC.v.0`
- Schema: `mbo`
- Start: `2024-01-09T00:00:00Z`
- End: `2024-01-10T00:00:00Z`
- Provider job: `GLBX-20260730-WB9AXCVFET`
- Expected ceiling: $0.25
- Absolute authorized hard cap: $1.00
- Fresh estimate: $0.218068085611
- Actual charge: **$0.21806808561087**

The actual charge remained below both the expected ceiling and the absolute
hard cap.

## Submission audit

The first submission attempt was rejected by the provider with HTTP 422 before
a job or charge was created because DBN binary output requires
`map_symbols=false`. The rejected intent was retained at:

`data/raw/databento_gc_mbo_engineering_pilot/rejected_intent_map_symbols_true.json`

Only that transport flag was corrected. The estimate was refreshed and the
valid job was submitted exactly once. Databento reported a live batch-processing
backlog during processing and explicitly advised customers not to resubmit
queued jobs.

## Acquired source

- Downloaded files: 4
- Total downloaded bytes: 39,814,062
- Raw MBO DBN bytes: 39,811,823
- Raw MBO records: 2,322,905
- Raw MBO SHA-256:
  `09c962f45ed5738e1056f2f5447bad3389a8a0138e566276db629425b66b8763`

Point-in-time symbology resolved:

- Continuous symbol: `GC.v.0`
- Instrument ID: `41512`
- Underlying raw contract: `GCG4`
- Mapping interval: 2024-01-09 through 2024-01-10, end-exclusive

## Normalization

The complete source was normalized with:

- nanosecond UTC receive and event timestamps;
- fixed-point integer prices at provider precision `1e-9`;
- unaltered order IDs, actions, sides, sizes, sequence numbers, flags,
  channels, publisher IDs, and instrument IDs;
- source-file and row-ordinal lineage; and
- Zstandard-compressed Parquet output.

Normalized output:

- Records: 2,322,905
- Bytes: 31,661,220
- SHA-256:
  `43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3`

## Data-quality findings

The initial quality policy incorrectly required every `ts_event` to be inside
the requested interval. That gate failed because historical MBO contains a
synthetic order-book snapshot received at the start of each UTC day:

- Snapshot records: 2,744
- Book-reset records: 1
- Snapshot add records: 2,743
- Every snapshot record was received exactly at `2024-01-09T00:00:00Z`
- No receive timestamp was outside the frozen request

The original failed quality record and seal were preserved. A versioned
amendment corrected only the request-window rule to use `ts_recv`, consistent
with MBO snapshot semantics. The normalized payload was not changed.

Final checks:

- Provider metadata count equals decoded DBN count: **PASS**
- Decoded DBN count equals Parquet count: **PASS**
- DBN schema is MBO: **PASS**
- Every receive timestamp is inside the requested interval: **PASS**
- Receive timestamps are nondecreasing: **PASS**
- No receive timestamp precedes its event timestamp: **PASS**
- Required fields are complete: **PASS**
- Sizes are nonnegative: **PASS**
- Continuous-contract lineage is complete: **PASS**
- Snapshot structure is valid: **PASS**

Final technical quality gate: **PASS**

## Seal

Final seal SHA-256/canonical hash:

`d83b02bba366d25b9cdfedbedd7e32cea8c3b224e9749f87a2e663818e6568a4`

An independent verification reopened only artifact metadata, recalculated
hashes, checked Parquet row counts, and confirmed:

- one raw DBN source verified;
- 2,322,905 normalized records verified;
- permanent engineering-only exclusion present; and
- final quality gate `PASS`.

## Research guardrails

This date is permanently excluded from:

- relationship discovery;
- candidate creation or selection;
- development performance;
- validation performance; and
- any claim of trading edge.

No book reconstruction, directional statistics, signals, outcomes, execution
rules, PnL, or edge tests were calculated during Step 2.

Step 3 has not started.
