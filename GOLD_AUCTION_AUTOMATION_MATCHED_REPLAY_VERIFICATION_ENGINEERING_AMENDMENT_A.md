# Gold Auction Automation Matched-Replay Verification Engineering Amendment A

## Trigger

The first verification attempt began with the frozen 60,000-bar inputs and unchanged detector but exceeded 22 minutes of single-core computation. It was terminated before completion. The output directory remained empty, so no detector relationship, marking-agreement or performance result was observed.

## Permitted value-blind correction

The public `AuctionAutomationSnapshot` already returns only the final 24 zones and the corresponding final 48 proposals. The pre-amendment implementation nevertheless calculated proposals for every historical zone and discarded all but the final 48.

Amend only the computation path as follows:

1. Detect the complete zone sequence unchanged.
2. Select `zones[-24:]`, which is the exact existing public-zone output.
3. Calculate the two frozen proposal families only for those 24 public zones.
4. Return the same 24 zones and resulting 48 proposals without an additional truncation.

No event definition, threshold, source, lookback, case, timestamp, zone lifecycle, proposal rule, macro gate, liquidity gate, execution assumption, outcome rule or comparison gate may change.

## Required proof before rerun

- The existing auction-automation unit tests must pass.
- The complete backend unit suite must pass.
- Ruff must pass.
- Pre/post implementations must produce byte-identical public snapshots on the sealed synthetic fixture and at least two engineering cutoffs.
- The corrected implementation hash must be recorded before the second matched-replay run.

The first timeout remains preserved as a formal engineering failure. Amendment A receives no research credit.
