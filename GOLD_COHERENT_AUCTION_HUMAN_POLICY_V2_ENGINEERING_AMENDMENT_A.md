# Gold Coherent-Auction Human-Policy V2 Engineering Amendment A

Status: `FROZEN_PRE_PATH_SEMANTIC_CORRECTION`

The original V2 freeze and its first pre-path artifact remain unchanged. Before any V2 post-fill path was simulated, that artifact showed that the phrase “discounted M15 range on an H1 bullish trend” was assigned `RANGE_ROTATION`. This contradicts the frozen rule that an M15 range nested inside directional H1/H4 context remains `CONTINUATION_WITH_ROOM`.

Amendment A changes only the controlling-range text parser:

- `RANGE_ROTATION` requires explicit language that H1/H4 **is/was in a range**, or explicit discounted/premium language naming an H1/H4 range.
- Proximity between the words `range` and `H1/H4` is insufficient.
- “M15 range on/within an H1 bullish trend” remains continuation.

No contextual veto, threshold, geometry, sizing, protection, runner, cost, outcome, population or lock changes. No V2 outcome path had been simulated when this correction was made.
