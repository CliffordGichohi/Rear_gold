# Gold All-Transition Auction Scanner Liquidity and Range Semantics Amendment B Report

Verdict: `PASS_CORRECTED_LIQUIDITY_RANGE_SEMANTICS_AFTER_ENGINEERING_RESUME_STOP_FOR_USER_REVIEW`

- The original 729 control events and 24 review identities remain unchanged.
- Consumption now uses only a later observed traded price strictly beyond the exact confirmed pivot.
- Equality is classified as engagement, not consumption.
- Structural acceptance remains independent from pivot-liquidity consumption.
- The same M5/M15 control transition is described in both trend and qualified range contexts.
- Context counts: `{"RANGE_OPPOSITE_HALF_WITH_LTF_CONTROL": 37, "RANGE_ROTATION_WITH_LTF_CONTROL": 9, "TRANSITIONAL_CONTEXT_WITH_LTF_CONTROL": 355, "TREND_PULLBACK_WITH_LTF_CONTROL": 328}`.
- Protected internal-pivot states: `{"CONSUMED": 134, "UNCONSUMED_ENGAGED": 1, "UNCONSUMED_UNTOUCHED": 1323}`.
- Range states: `{"H1": {"ACTIVE_RANGE": 11, "NO_ACTIVE_RANGE": 718}, "H4": {"ACTIVE_RANGE": 35, "NO_ACTIVE_RANGE": 694}}`.
- Technical unknown classifications: `0`.
- Primary/reference overlays, diagnostics and chart bytes match exactly.
- No outcomes or performance fields were accessed.

Corrected atlas: `research_artifacts/gold_all_transition_auction_scanner_semantic_review_v1/predecision_atlas_v1_b.html`

The primary pass was reused unchanged after the sealed R1 engineering resume.
