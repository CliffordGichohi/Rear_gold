# Gold All-Transition Auction Scanner Semantic Review V1 Report

Verdict: `PASS_OUTCOME_BLIND_ALL_TRANSITION_SEMANTIC_MATERIALIZATION_STOP_FOR_USER_REVIEW`

This is an outcome-blind semantic checkpoint. No trades, outcomes, R, PnL, MFE, MAE, 2025, or 2026 data were opened.

## Frequency

- Eligible New York days: **117**
- Total accepted auction events: **729**
- Days with at least one event: **117**
- Zero-event days: **0**
- Mean / median events per day: **6.23 / 6.00**
- Maximum events in one day: **15**

| Direction | Initial | Reversal | Reassertion | Continuation refresh | Total |
|---|---:|---:|---:|---:|---:|
| LONG | 62 | 31 | 25 | 253 | 371 |
| SHORT | 55 | 32 | 30 | 241 | 358 |

## Semantic disposition

- LONG and SHORT use the same structural and acceptance definitions.
- Normal same-direction continuation is emitted without requiring a failed opposite auction.
- Macro and H1/H4 state are recorded as context, not used as vetoes.
- Every chart and event ends at its completed-candle decision timestamp.
- User semantic confirmation is required before any economic regression.

Review atlas: `research_artifacts/gold_all_transition_auction_scanner_semantic_review_v1/predecision_atlas.html`
