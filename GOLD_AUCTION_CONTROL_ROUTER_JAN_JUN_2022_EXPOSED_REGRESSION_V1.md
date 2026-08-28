# Gold Auction-Control Router — January–June 2022 Exposed Regression V1

Status: frozen design before the January–June regression.

## Purpose

This is a bounded, post-result diagnostic and implementation study. It tests whether replacing the legacy non-exclusive LONG structure flag with a mutually exclusive auction-control state can:

1. veto legacy LONG trades when buyers do not control both M5 and M15; and
2. admit a SHORT only after a complete, observable seller-auction plan exists.

January through June 2022 is already exposed. Every result receives zero validation credit. No later date may be opened.

## Population and tracks

The chronological population is every already-opened eligible weekday from 2022-01-03 through 2022-02-16, 2022-03-01 through 2022-05-31, and every June 2022 weekday already present in the sealed June source. The 2022-02-17 through 2022-02-28 gap, July 2022, 2025, and 2026 remain closed.

Four tracks are reported:

1. `ORIGINAL_LONG_CONTROL`: the frozen existing LONG results, unchanged.
2. `BUYER_CONTROL_VETO_LONG`: the same LONG trade and result only when the router reports `BUYER_CONTROL` at its original signal timestamp.
3. `SELLER_AUCTION_SHORT`: the first complete SHORT plan of the day.
4. `BIDIRECTIONAL_ONE_PER_DAY`: the earliest executable retained LONG or SHORT, with at most one trade per day.

## Auction-control state

- Swings are causal two-left/two-right pivots with minimum 0.25 ATR prominence and a $0.02 floor.
- A structural break closes 0.05 ATR beyond the pivot.
- M5 displacement requires range at least 0.80 ATR and body/range at least 0.55.
- M15 displacement requires range at least 0.90 ATR and body/range at least 0.55.
- A break remains active until a completed candle closes beyond its protected swing by 0.10 ATR, with a $0.02 floor.
- Each timeframe is controlled by its latest still-active qualifying break, irrespective of direction.
- `BUYER_CONTROL` or `SELLER_CONTROL` requires M5 and M15 agreement for two consecutive completed M5 closes.
- Disagreement is `CONFLICTED`. Missing or not-yet-accepted agreement is `UNRESOLVED`.
- These four states are mutually exclusive.

## SHORT plan

A seller-control transition is not itself a trade. A SHORT requires all of the following, using completed data only:

1. accepted `SELLER_CONTROL` during London or New York;
2. a failed buyer-auction antecedent in the same session, defined as either earlier accepted `BUYER_CONTROL` or a causal buy-side sweep and close-back-below reclaim;
3. within the next six completed M5 bars, the first bearish retest/rejection of the seller M5 break level: the high reaches the level minus 0.25 M5 ATR, the close is below the level, and close is below open;
4. entry at the first M1 open strictly after that M5 confirmation, with adverse half-spread and $0.05/oz slippage;
5. stop above the seller event's already-known protected M5 swing plus 0.10 M15 ATR (minimum $0.02);
6. target at the nearest already-known liquidity below entry. Eligible levels are confirmed M15, H1, and H4 swing lows plus the completed Asia low for London or completed London low for New York. A nearer level may not be skipped;
7. at least 1.5R room to that nearest level and at least one whole ounce under a $50 maximum planned loss including costs.

The SHORT uses the unchanged stop-first ambiguity convention, fixed structural stop, fixed liquidity target, UTC-day time exit, whole-ounce sizing, and 1.5× cost stress. Macro and H4 structure are recorded as context, not used as hard direction filters.

## LONG veto and combined policy

The veto does not move or reconstruct a LONG entry, stop, target, exit, size, or result. It only retains or rejects the frozen trade according to auction control at its original signal timestamp.

The combined track chooses the earliest fill timestamp among a retained LONG and a valid SHORT. It never flips, never takes a second trade, and never selects by outcome.

## Reporting and integrity

Report all days, NO_TRADE days, transition and rejection counts, admitted and vetoed LONG winners/losses, SHORT rejection reasons, monthly and combined trades, win rate, expectancy, PF, net R/USD, maximum drawdown, 1.5× cost performance, and session/direction contribution.

Primary and reference implementations must reproduce exact row identities, decisions, results, metrics, and checksums. Synthetic tests must prove state exclusivity, two-close acceptance, invalidation, retest expiry, nearest-target selection, adverse fills, and earliest-candidate selection before the exposed regression runs.

No threshold, rule, month, session, or candidate may be changed after results are viewed. No paid data may be acquired.
