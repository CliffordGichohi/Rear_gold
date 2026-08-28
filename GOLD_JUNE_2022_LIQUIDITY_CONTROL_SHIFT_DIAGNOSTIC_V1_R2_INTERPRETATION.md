# Gold June 2022 Liquidity-Control Shift Diagnostic V1-R2 — Interpretation

## Confirmed implementation gap

The frozen LONG classifier asks whether at least one bullish M15 structural
break remains active. It does not compare that break with the latest active
bearish break and therefore does not identify the currently controlling side.
At all nine June entries, the legacy function reported both LONG and SHORT M15
breaks as active. It then admitted LONG because the policy was hard-coded
LONG-only.

This explains why an H4 swing label was insufficient. H4 describes the broader
auction backdrop; it does not say which side currently controls the lower-
timeframe auction. For example:

- 8 June had a bearish H4 sequence but LONG M5/M15 control at entry and ended
  positive.
- 21 June had a bullish H4 sequence but SHORT M5/M15 control at entry and ended
  negative.

## Exposed June evidence

| Point-in-time M5/M15 state at LONG entry | Trades | Winners | Net R |
|---|---:|---:|---:|
| LONG confluence | 4 | 2 | -0.898292 |
| SHORT confluence | 3 | 0 | -2.241912 |
| Conflicted or unresolved | 2 | 0 | -1.900451 |

The three already seller-controlled entries were 13, 21 and 23 June. The two
conflicted entries were 24 and 27 June. Removing those five LONG entries would
have avoided no June winner, but the remaining four trades would still have
lost 0.898292R. Therefore control routing explains a large part of the failure,
not all of it.

Seller control appeared before eight of nine frozen LONG exits, but it also
appeared during both winning trades. A single opposite break cannot therefore
be used as an automatic exit or reversal.

Across every June London and New York session, requiring causal M5/M15
agreement for two completed M5 closes produced 23 accepted SHORT shifts. Eleven
reached +1 M15 ATR before -1 M15 ATR and twelve did not. The raw shift alone is
not an edge. Descriptively, New York was stronger (9/14 favourable first) than
London (2/9), but this is one exposed month and receives no validation credit.

## Bounded bidirectional design implied by the evidence

1. Treat H4 structure and fundamentals as directional context, not as the
   lower-timeframe trigger.
2. Replace the legacy `any active LONG break` boolean with one mutually
   exclusive point-in-time state: `BUYER_CONTROL`, `SELLER_CONTROL`,
   `CONFLICTED`, or `UNRESOLVED`.
3. Require accepted M5/M15 agreement for directional eligibility. LONG is
   prohibited in seller control; SHORT is prohibited in buyer control; no new
   position is allowed while conflicted or unresolved.
4. Do not trade control agreement indiscriminately. A SHORT plan additionally
   requires an already-known premium/resistance or buy-side-liquidity location,
   observable rejection or failed bullish auction, seller displacement and
   acceptance, a point-in-time invalidation above the controlling structure,
   and room to the next known sell-side-liquidity destination. LONG is the
   exact directional analogue.
5. An opposite accepted shift may invalidate or scratch an existing position,
   but a direction flip requires the complete opposite-side plan; it is never
   automatic.
6. Macro alignment changes confidence and risk treatment. It must not overwrite
   an already observed lower-timeframe transfer of control.

The next bounded engineering regression should apply these semantics to the
same exposed June days first and report veto-only, SHORT-only and combined
tracks separately. It must not open another month until direction symmetry and
semantic fidelity are demonstrated on this already-exposed block.
