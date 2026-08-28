# Gold Coherent-Auction Human-Policy V2 — Fresh Block Amendment B

Status: `APPROVED_AND_FROZEN_BEFORE_FRESH_DECISION_COLLECTION`

Authorization: on 2026-08-20 the user authorized opening another month-equivalent of previously unseen data to test the corrected V2 policy.

## Scope

This amendment opens the already sealed Gold Coherent-Auction Blind Validation V1 population: exactly 50 previously unreplayed sessions, balanced as 25 London and 25 New York sessions. This is approximately one trading month of two-session opportunities, selected in an outcome-blind randomized order from 2022-08-08 through 2022-12-30. It is not a contiguous calendar month.

The population, order, price streams, display rules, one-way cursor, execution costs, append-only ledger, and future-data protections remain unchanged. Calendar 2025 and calendar 2026 remain locked. No data acquisition or charge is authorized.

## What the operator must supply

The corrected V2 policy is not an autonomous setup detector. For each session the operator must either record `NO_TRADE` or seal a point-in-time setup containing direction, entry, structural invalidation, opposing-liquidity target, auction family, controlling H4 state, location, macro-override reason, and written rationale. No future bar may be visible before the decision is sealed.

## Frozen evaluation mapping

After all 50 sessions are complete, the sealed decisions will be evaluated once under `GOLD_COHERENT_AUCTION_HUMAN_POLICY_RECONSTRUCTION_V2` with Engineering Amendment A unchanged:

- the submitted human setup is the signal;
- the V2 contextual admission/rejection policy is unchanged;
- total planned loss, including frozen source costs, is capped at $50 using whole-ounce sizing;
- the operator's sealed entry, structural stop, target, and deadline remain authoritative;
- protection arms only after a completed M15 close reaches `+1.25` structural R and moves the stop to net break-even at the next M1 open;
- the frozen 20% bounded-runner policy remains unchanged even though its exposed-sample contribution was negative;
- the 1.00R, 1.50R, and 2.00R protection thresholds are diagnostics only and cannot replace the frozen 1.25R policy;
- no rule, threshold, classification, entry, stop, target, or management policy may be retuned after any fresh outcome is exposed.

The faithful fixed-geometry and protected fixed-geometry tracks may be reported as attribution controls. Only `COMPLETE_V2_POLICY` receives the formal fresh-block verdict.

## Frozen verdict gates

The original blind-validation gates are retained. `PROVISIONAL_PASS` requires all of:

1. at least 20 admitted and executed trades;
2. positive combined net expectancy after costs;
3. profit factor at least 1.10;
4. positive net result in both chronological halves;
5. neither London nor New York contributes more than 80% of positive gross R;
6. positive net result at 1.5 times frozen variable costs;
7. no integrity, point-in-time, or future-leakage failure.

`REJECT` applies if combined expectancy is non-positive, profit factor is below 1.00, or an integrity failure invalidates the block. Every other outcome is `INCONCLUSIVE`.

No interim aggregate PnL, hit rate, failure attribution, or outcome feedback may be released before all 50 sessions are sealed. A pass is historical robustness evidence, not independent validation or authorization for live trading.

## Preserved evidence

- V1 overfiltering rejection remains unchanged.
- V2 exposed result `+10.681846581267534R` remains explicitly calibration-only.
- The fresh-block population hash remains `36a60ccfccedda19a39a48e6c38326b5f0d54f8bd7380cfd1595aa27d8c791f3`.
- At freeze time, zero fresh decisions had been collected.
- Calendar 2025 and calendar 2026 remain `LOCKED_UNOPENED`.
