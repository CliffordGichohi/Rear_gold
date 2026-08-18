# GC Microstructure Research — Step 3B.1

Status: **FAIL — NOT READY FOR PAID ACQUISITION**

Quote compliance: **PASS — 11 OF 11 GATES PASSED**  
Book comparison: **NOT RUN**  
Completion date: 2026-07-30  
Classification: **ENGINEERING-ONLY METADATA**  
Research or validation credit: **NONE**

## Predecessor preservation

Before freezing the Step 3B.1 protocol, all declared predecessor byte counts
and SHA-256 hashes were reverified.

- Original Step 3A verdict remains **FAIL**.
- Step 3A manifest hash remains
  `0897e33856c5329ee59040ff5a6c15f48cb65fc17dcf3e63ec1f8c5bf3c6c59c`.
- Step 3A.1 verdict remains **PASS** with no research or validation credit.
- Step 3A.1 manifest hash remains
  `334b67560ee5912ed1939305715078b3f9460d389feb8cc17723a062543d657c`.
- No predecessor file was modified.

## Frozen comparison protocol

The protocol was frozen and sealed before the metadata quote:

- Protocol SHA-256:
  `07860e02cf4f76487a0f334faa2987e0a0cf97f8977ca61f995c533f617022c5`
- Freeze-receipt SHA-256:
  `b418883b2c94ff3b7efcf3e8bc4bf3bd121760cd036aeef0adae7806a099f681`

It froze:

- exact alignment by publisher, instrument, sequence, event timestamp, and
  receive timestamp;
- sampling the reconstructed MBO book only at `F_LAST`;
- exact equality of price, aggregate size, and order count for ten bid and ten
  ask levels—60 fields per aligned record;
- zero timestamp, price, size, and order-count tolerance;
- no nearest-time join, interpolation, forward fill, resampling, row dropping,
  or post-result repair;
- the Step 3A.1 continuous, maintenance, and pre-open market-state windows; and
- two independent future comparison implementations with matching checksums.

Official provider basis:

- [Databento MBP-10 schema](https://databento.com/docs/schemas-and-data-formats/mbp-10)
- [Databento MBO schema](https://databento.com/docs/schemas-and-data-formats/mbo)
- [CME Globex MDP 3.0 conventions](https://databento.com/docs/knowledge-base/datasets/glbx-mdp3)
- [Databento limit-order-book construction](https://databento.com/docs/examples/order-book/limit-order-book)

## Metadata-only quote

Frozen request:

| Field | Value |
|---|---|
| Dataset | `GLBX.MDP3` |
| Symbol | `GC.v.0` |
| Schema | `mbp-10` |
| Input symbology | `continuous` |
| Start | `2024-01-09T00:00:00Z` |
| End | `2024-01-10T00:00:00Z` |

Returned metadata:

| Item | Result |
|---|---:|
| Estimated cost | **$0.329837784171** |
| Estimated records | **1,924,786** |
| Estimated billable size | **708,321,248 bytes** |
| Databento SDK | `0.82.0` |

Only these endpoints were called:

- `metadata.get_cost`
- `metadata.get_record_count`
- `metadata.get_billable_size`

No batch endpoint or time-series endpoint was called. No job was submitted,
no data was downloaded, and no charge was incurred.

## Readiness blocker

The frozen protocol assumed exactly one MBP-10 row for every sealed MBO
`F_LAST` boundary.

| Population | Count |
|---|---:|
| Sealed MBO `F_LAST` boundaries | 2,062,923 |
| Estimated MBP-10 records | 1,924,786 |
| Difference | **138,137** |
| MBP-10/MBO-boundary ratio | 93.3038218101% |

The counts are unequal by **6.69617819%** of the MBO-boundary population.
Therefore, the frozen one-to-one population requirement is incompatible with
the metadata before acquisition.

No row values were opened, so this step does not claim why the rows differ.
The likely emission semantics must not be assumed or repaired after seeing
values.

## Verdict

Step 3B.1 quote compliance is **PASS**: all 11 metadata and non-acquisition
gates passed.

Step 3B.1 acquisition readiness is **FAIL**. Buying the file under the
unchanged protocol would knowingly enter a test whose frozen one-to-one
coverage gates cannot be satisfied.

This is not a Step 3B book-comparison failure because the comparison was not
run. It is a pre-acquisition protocol-readiness failure.

## Guardrails

- The date remains permanently **engineering-only**.
- No MBP-10 values or market outcomes were inspected.
- No directional statistics, relationships, features, signals, execution
  rules, trades, PnL, R multiples, or account returns were calculated.
- No paid acquisition was performed.
- Work stopped before Step 3B value comparison.

A future amendment would require separate authorization. It could freeze a
provider-semantics-based deterministic subset of MBO events represented by
MBP-10, but it must be defined before any paid acquisition or value access.
