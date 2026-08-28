# Gold Auction Trade Placement Examples V1 Outcome Reveal

## Authorization and boundary

The user authorized opening the post-decision paths for the exact ten plans
sealed by Gold Auction Trade Placement Examples V1. No plan identity, direction,
entry, stop, target, context, or selection rule may change.

Use only the already-exposed 2022 source streams associated with the ten plans.
Do not open any additional case, 2025, or 2026.

## Frozen resolution

### Structural first-passage view

- Entry reference is the displayed decision price.
- Begin with the first complete M1 bar whose `open_at` is at or after the sealed
  decision timestamp.
- End at 12:00 America/New_York local time on that trading date.
- LONG: stop when M1 low is at or below the fixed stop; target when M1 high is at
  or above the fixed target. SHORT is directionally symmetric.
- If both occur in one M1 bar, resolve STOP first.
- If neither occurs, exit at the last observed M1 close before the deadline.
- Gross R uses the displayed absolute entry-to-stop distance.

### Execution-aware view

- One-minute latency.
- Fill at the first observed M1 open at or after decision plus one minute.
- Market fill includes directional half-spread and 0.05 price slippage.
- Missing or negative spread uses the frozen 0.20 fallback.
- Position size is floor($50 / displayed entry-to-stop distance), whole ounces,
  with a minimum of one ounce.
- The absolute stop, target, and deadline remain unchanged.
- Stop exits use gap-adverse raw price, half-spread, and 0.05 slippage.
- Target exits use the fixed target price.
- Time exits use the final observed close, half-spread, and 0.05 slippage.
- Same-bar ambiguity remains STOP first.
- Report net dollars, net R divided by $50, MFE, MAE, and effective fill risk.

## Integrity

- Run primary and reference source passes independently.
- Require identical case identities, bar allocations, first-passage states,
  timestamps, prices, costs, MFE/MAE, PnL, and checksums.
- Report every result; do not delete, relabel, repair, or reinterpret a loss.
- Ten observations are descriptive and cannot validate an edge.

