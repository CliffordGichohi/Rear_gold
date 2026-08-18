# GC Microstructure Research — Step 3B.2

Status: **FAIL — VENDOR MBP-10 BENCHMARK NOT REPRODUCED EXACTLY**

Amended pass gates: **15 OF 22 PASSED**  
Integrity checks: **11 OF 11 PASSED**  
Completion date: 2026-07-31  
Classification: **ENGINEERING-ONLY BOOK BENCHMARK**  
Research or validation credit: **NONE**

## Preserved predecessor state

- Original Step 3A remains **FAIL**.
- Step 3A.1 remains **PASS**, with no retroactive research or validation
  credit.
- Step 3B.1 remains **FAIL — PRE-ACQUISITION READINESS**.
- No predecessor artifact or verdict was modified.

## Amendment A

Amendment A was frozen before the fresh quote, acquisition, or MBP-10 value
access.

- Amendment SHA-256:
  `dc437c6f8a6f01c9c6c04a28133d9dfed5b9eeff9f87b8f62e87f113651a2709`
- Freeze-receipt SHA-256:
  `5f13cf74f8598fcb15e21202bafee9a0f42211cfffa577aff355688f5b63053f`

The sole protocol change made every vendor MBP-10 record the comparison
population. Every vendor record still had to align exactly and uniquely to an
MBO `F_LAST` boundary using:

1. publisher ID;
2. instrument ID;
3. sequence;
4. event timestamp; and
5. receive timestamp.

All 60 top-ten book fields retained zero tolerance. MBO boundaries not emitted
in MBP-10 were reported separately.

## Acquisition

| Item | Result |
|---|---:|
| Fresh estimate | $0.329837784171 |
| Authorized maximum | $0.40 |
| Actual cost | **$0.3298377841711** |
| Provider records | **1,924,786** |
| Downloaded files | 4 |
| Downloaded bytes | 50,589,276 |
| Normalized records | **1,924,786** |
| Source-quality gate | **PASS** |

The normalized source seal hash is:

`3082c0e0421a503a180554f25ea9dffefaed1d664f392d2aba0ee8e0eb73e0bd`

The source passed record-count, request-window, timestamp-ordering,
instrument-lineage, bad-book-flag, empty-level, price-level-ordering, and
nonnegative depth/count checks.

## Independent comparison results

The primary explicit-level reconstruction, independent order-map
reconstruction, and deterministic repeat produced identical counts and the
same comparison checksum:

`59f4c28a2a6343eea88a274b4d8fdd13fdb39d07c26d1df9056a679455724492`

| Result | Count | Rate |
|---|---:|---:|
| MBO `F_LAST` boundaries | 2,062,923 | 100% of MBO boundaries |
| Vendor MBP-10 records | 1,924,786 | 100% of vendor records |
| Exact-key matched vendor records | **1,855,409** | **96.395599303%** |
| Unmatched vendor records | **69,377** | **3.604400697%** |
| MBO boundaries without vendor rows | **212,024** | **10.277843623%** |
| Duplicate vendor alignment keys | **6,167** | — |
| Duplicate MBO boundary keys | **25** | — |
| Matched rows with one or more field mismatches | **4,510** | **0.243073091% of matches** |
| Exact book fields compared | 111,324,540 | — |
| Individual field mismatches | **59,004** | **0.053001791%** |

All 59,004 field mismatches and all 69,377 unmatched vendor rows occurred
during continuous matching.

Maintenance produced one exact-key match. Pre-open produced 70 exact-key
matches and 310 MBO-only boundaries. Neither segment produced a reported book
field mismatch.

## Relation-state result

Despite the exact alignment and depth-field failures:

- continuous vendor locked/crossed rows: 0;
- continuous reconstructed locked/crossed rows: 0; and
- vendor/reconstruction relation-state mismatches: 0.

This means the compared records agreed on whether the top of book was
uncrossed, locked, crossed, or missing-sided. It does not satisfy the stricter
ten-level equality requirement.

## Failed formal gates

The following frozen gates failed:

- every MBP-10 record has exactly one MBO `F_LAST` match;
- unmatched MBP-10 records equal zero;
- MBP-10 alignment keys are unique;
- duplicate matched MBO keys equal zero;
- every MBP-10 record is compared;
- book-field mismatches equal zero; and
- the formal unrepresented-boundary reconciliation check.

The last item is a conservative bookkeeping failure: the MBO-only count was
reported by market state, but duplicate keys make the simple
`MBO boundaries - matched vendor records` identity unequal. This does not
change the formal verdict because the six substantive alignment and equality
gates also failed.

## Passed integrity evidence

All 11 integrity checks passed:

- exact MBO source-record and boundary counts;
- exact MBP-10 source-record count;
- primary and reference book/index invariants;
- identical MBO input and boundary hashes;
- identical vendor input hashes;
- identical final reconstructed state and structure hashes;
- identical primary/reference comparison counts;
- identical primary/reference mismatch counts;
- identical primary/reference comparison checksum; and
- an identical independent repeat.

## Verdict and limit

Step 3B.2 is an honest **FAIL**. Under the frozen exact five-field alignment
and zero-tolerance 60-field comparison, the local reconstruction did not
reproduce the complete vendor MBP-10 benchmark exactly.

This result does **not** establish that the MBO reconstructor is generally
wrong, because the remaining discrepancies may involve provider emission,
event grouping, duplicate-key, or snapshot conventions. Determining their
cause would require a separately authorized diagnostic protocol.

It also says nothing about directional edge, signals, strategy performance, or
PnL.

## Seal and guardrails

Step 3B.2 manifest hash:

`9fcdde66ca1f5d605f92fd5aba83de1b042fc01b3020e53d3f3bda904d850e8f`

The seal independently verified nine artifacts and preserved every earlier
verdict.

- No market price or depth value was reported.
- No market outcome was inspected.
- No directional statistic, feature, or signal was created.
- No execution rule was optimized.
- No trade, PnL, R multiple, or account return was calculated.
- No failed rule was repaired or retuned.
- Work stopped after Step 3B.2.
