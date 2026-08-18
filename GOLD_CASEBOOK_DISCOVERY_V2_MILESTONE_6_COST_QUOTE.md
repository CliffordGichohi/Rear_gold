# Gold Casebook Discovery V2 — Milestone 6 Cost-Quote Checkpoint

## Result

The authorized metadata-only Databento cost estimate is complete.

| Field | Result |
|---|---|
| Dataset | `GLBX.MDP3` |
| Symbol | `ZN.v.0` |
| Schema | `ohlcv-1m` |
| Interval | 2025-01-01 inclusive through 2026-01-01 exclusive |
| Provider endpoint | `Historical.metadata.get_cost` |
| Observed estimate | **$1.185062900186 USD** |
| Rounded estimate | **$1.19 USD** |
| SDK | Databento 0.82.0 |

The endpoint did not provide an expiry for the estimate, so the acquisition
tool must obtain a fresh estimate immediately before submission and refuse to
submit if it exceeds the user's explicit cost cap.

## Authorization boundary

This checkpoint did not authorize or perform acquisition.

- batch job submitted: no;
- charge incurred: no;
- paid download started: no;
- API key recorded in an artifact: no;
- 2025 market values accessed: no;
- ZN direction or feature calculated: no;
- holdout outcome accessed: no; and
- calendar-2026 market values accessed: no.

The cost utility deliberately exposes no submit or download action. The
temporary Databento SDK installation used for the metadata call was removed
after the quote was validated.

## Integrity

Canonical bundle:

`research_artifacts/gold_casebook_discovery_v2_m6_zn_quote_v01`

| Artifact | Hash |
|---|---|
| Frozen quote research manifest | `25b4a24ebb01b783d567da3bb3cf9fa825e5e97f435dcb13281b7f3518ae1bcc` |
| Quote bundle manifest | `c67518d0507fcf01da39f0b943bcaa0259b698fe22a55def61b61023529a51b4` |
| Quote document | `6e7303f94adcd4930cc7ee93c28230c50bdee39db7b6a16bc9235b848144e122` |
| Semantic validation | `ad6902ce61009ce82f4bd31b3aac31c900bdccb7d057038d886e852eec36497b` |
| Research-manifest file SHA-256 | `ffde722357590f8620ee721259a2da4cfa4ce999bfe8c976a6f01874273e2c98` |
| Bundle-manifest file SHA-256 | `49183920de02544036f9f135808c30c5744a8e7bb224ad162fa372f23ce5c563` |
| Quote file SHA-256 | `71f1bd08d073f9c88da637d73d08cc20be78d10d3850be69936173024cfde832` |
| Validation file SHA-256 | `49a0aec33ea4a92f3a9834bfccc4a41ed3829da14df1d455a448f76537bc85c7` |

Independent semantic validation result:

`PASS_SEMANTIC_VALIDATION`

Repository quality checks:

- Ruff: passed;
- focused quote and guardrail tests: 5 passed;
- complete backend suite: **171 passed**.

## Required next authorization

No contract amendment is required. The shortlist, rule, execution, costs, and
holdout gates remain unchanged.

Before a chargeable batch job may be submitted, the user must provide an
explicit maximum cost. A $1.25 cap is sufficient for the observed $1.1851
quote while limiting unexpected price movement. The acquisition tool must
re-quote immediately before submission and stop if the new estimate exceeds
that cap.

The next authorization can be:

> Continue V2 Milestone 6. Authorize acquisition of the frozen calendar-2025
> Databento `GLBX.MDP3 ZN.v.0` one-minute request with a maximum charge of
> $1.25. Re-check the estimate before submission and stop if it exceeds the
> cap. Acquire, normalize, hash, and seal the source without human inspection
> of market values or outcomes; complete all metadata-only readiness gates;
> then open the 2025 holdout once, apply the frozen candidate unchanged,
> record pass or rejection, and stop.

Until that authorization is received, Milestone 6 remains at the cost-quote
checkpoint and the holdout remains locked.
