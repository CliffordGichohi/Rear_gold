# Gold Persistent Liquidity-Shift Auction-State V3 Report

## Verdict

`FAIL_SEMANTIC_REPRESENTATION`

V3 is terminated before development-outcome access. It receives zero economic or edge credit.

## What remained valid

- Same-direction prior liquidity-zone contact: 16/16 human trades (100%).
- Same-direction M15 transition under the preserved V2 definition: 11/16 (68.75%).
- Detector reproduction: identical primary/reference hashes.
- Detector population on the visible calibration period: 82 auction states, 323 M5 impulses and 646 entry intents.

These results support liquidity-shift zones as a useful location/context representation. They do not establish profitable timing.

## Engineering correction

The first V3 semantic output reported 16/16 matches because its comparator treated any historical triggered intent as permanently available. A trigger from 2021-12-31 was incorrectly allowed to match later January decisions. That output is preserved unchanged but classified as invalid engineering evidence with zero credit.

Correction A changed only availability from `triggered_at <= decision_at` to `triggered_at <= decision_at < expires_at`. No market outcome or PnL was accessed when identifying or correcting this defect.

## Corrected result

Under the corrected point-in-time availability rule, eligible triggered-or-pending entries at the human decision timestamp were 0/16, below the frozen 7/16 requirement.

The failure means the registered M5 impulse/retrace event did not describe the lower-timeframe trigger used at the actual human checkpoints. It does not test profitability and does not reject liquidity-shift location itself.

## Disposition

- Development outcomes remained unopened.
- Calendar 2025 remained unopened.
- Calendar 2026 remained unopened.
- No paid acquisition occurred.
- V3 must not be retuned or receive economic testing.

Any successor must first conduct a new outcome-blind diagnostic of the completed pre-decision M5 structure and freeze a materially different trigger definition before accessing economic outcomes.

