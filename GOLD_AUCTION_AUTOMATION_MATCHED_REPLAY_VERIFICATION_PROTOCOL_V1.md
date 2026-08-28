# Gold Auction Automation Matched-Replay Verification Protocol V1

## Status and evidence credit

This is a post-result, zero-credit calibration and falsification audit requested on 20 August 2026. It applies the already frozen `gold-auction-automation-1` detector to the exact 30 exposed matched human/Codex replay days. It cannot validate an edge and cannot promote any result to independent evidence.

The automation implementation is frozen by SHA-256 `70166c63c908317d9ffd552253ac49a5b681dae6e442fb71f4650c3293ee399d`. The matched population is frozen by SHA-256 `6b69a13af3ee2909046615d05282c6f863b892e067ec04f11622d048b83e37f9`.

No detector threshold, proposal definition, entry, stop, target, macro gate or liquidity gate may be changed after calculation begins.

## Frozen population and sources

- Cases: `CBR-2022-001` through `CBR-2022-030`.
- Dates: 3 January through 16 February 2022, using only the 30 dates in the sealed matched registry.
- Price source: real IC Markets MT5 XAUUSD M1 bars already stored in `market.price_bars`.
- Lookback: at most the latest 60,000 point-in-time eligible M1 bars at each checkpoint, matching the production endpoint default.
- Human evidence: the sealed matched-human visible ledger, including 16 trades, 14 no-trades and 68 horizontal levels.
- Codex evidence: the sealed matched-comparison cases, including 23 trades and 7 no-trades.
- Outcomes: already exposed matched-replay paths; all results retain zero research credit.
- No 2025 or 2026 data may be inspected.

## Source-integrity gates

1. Verify the frozen automation-module hash and population hash.
2. Verify the append-only human ledger chain.
3. Verify all primary replay stream hashes used to recover point-in-time fundamental snapshots.
4. Require the stored M1 bars for every case day to match the sealed private replay stream on timestamp and OHLC values.
5. Stop on any source, ordering, uniqueness or lineage mismatch.

## Marking-agreement audit

Run the unchanged detector at every human and Codex trade checkpoint. Only bars closed and available at or before the checkpoint are eligible.

The frozen spatial tolerance is `max($0.50, 0.20 × current M15 ATR14)`.

Report:

1. Human horizontal-level agreement with an already-confirmed automatic swing at the same source timeframe.
2. Human horizontal-level agreement with any already-confirmed M15/H1/H4 swing.
3. Human horizontal-level intersection with, or proximity within the tolerance to, an active automatic M15 shift zone.
4. Human and Codex entry proximity to any active automatic zone.
5. Human and Codex entry proximity to an active same-direction automatic zone.
6. Whether an unchanged automatic proposal of the same direction had triggered no later than the operator decision.

Human drawings are a comparison reference, not ground truth. These measurements are agreement proxies and must not be described as detector accuracy or recall.

The frozen marking-agreement gate requires both:

- at least 60% of human horizontal levels to match either an already-known M15/H1/H4 swing or an active shift zone; and
- at least 50% of human trade entries to be within the frozen tolerance of an active same-direction shift zone.

Failure of either gate is `FAIL_MARKING_MISMATCH`. Passing both is `PASS_MARKING_AGREEMENT_ONLY`; it is not an economic-edge pass.

## Automatic proposal eligibility

For each case, run the unchanged detector at the case end and retain proposals whose frozen trigger timestamp falls inside that UTC case day.

A technical proposal is support-eligible only when it has:

- a trigger and entry reference;
- a positive whole-ounce quantity;
- planned risk no greater than $50;
- a previously known target;
- reward-to-risk of at least 1.25.

Reapply the frozen point-in-time gates using the latest sealed context snapshot available no later than the trigger:

- macro snapshot age no greater than 24 hours;
- proposal direction aligned with the stored macro bias;
- broker-liquidity status `NORMAL` or `ELEVATED` from the frozen liquidity engine at the trigger.

Report technical eligibility and full `PAPER_READY` eligibility separately.

## Frozen economic resolution

Evaluate the two families separately. Each family may take at most its earliest fully eligible proposal per case. A combined diagnostic takes at most the earliest fully eligible proposal of either family per case; exact timestamp ties prefer `CONFIRMED_RETEST_V0_1`.

- Direction: proposal direction.
- Reference entry, structural stop, target and quantity: unchanged detector output.
- Effective fill: reference entry plus adverse half observed spread and $0.05 slippage for longs; minus both for shorts.
- Missing spread fallback: $0.20.
- Effective-risk ceiling: $55; violations use the existing immediate-flatten matched-replay policy.
- First-passage ordering: stop first when stop and target are both touched in one M1 bar.
- Stop exit: adverse half spread plus $0.05 slippage.
- Target exit: frozen target without additional slippage, matching the sealed replay policy.
- Unresolved exit: final observed M1 close of the UTC case day, with adverse half spread and $0.05 slippage.
- Commission: $0, matching the sealed replay policy.
- Risk normalizer: $50 maximum planned risk; report both dollars and R50.

Report support, wins, losses, time exits, net R50, net dollars, expectancy, profit factor, maximum drawdown, MFE, MAE and 1.5-times transaction-cost stress. With fewer than 20 trades, uncertainty is explicitly insufficient regardless of the point estimate.

## Reproduction and verdict

Run a primary and independently ordered reference calculation. Require identical case identities, markings, eligibility classifications, trade rows, metrics and canonical checksums.

Possible verdicts:

- `PASS_MARKING_AGREEMENT_ONLY`: the detector materially agrees with the operator evidence, while economic evidence remains unvalidated.
- `FAIL_MARKING_MISMATCH`: agreement proxies show that the automated interpretation does not represent the operators' method.
- `FAIL_NO_ACTIONABLE_PROPOSALS`: technical markings exist but frozen macro/liquidity/economic gates yield no usable sample.
- `REJECT_NEGATIVE_MATCHED_ECONOMICS`: sufficient matched proposals exist but net expectancy is non-positive.
- `INCONCLUSIVE_SMALL_MATCHED_SAMPLE`: point estimates are positive but support is below 20 trades or uncertainty remains unresolved.

The economic disposition uses the combined one-trade-per-day diagnostic. Zero fully eligible trades is `FAIL_NO_ACTIONABLE_PROPOSALS`. A non-positive point estimate is `REJECT_NEGATIVE_MATCHED_ECONOMICS`. A positive point estimate with fewer than 20 trades is `INCONCLUSIVE_SMALL_MATCHED_SAMPLE`. At least 20 trades, positive expectancy, profit factor of at least 1.10, positive 95% bootstrap lower bound and positive 1.5-times-cost expectancy are all required for a descriptive `PASS_EXPOSED_MATCHED_ECONOMICS`; such a pass still receives zero validation credit.

No correction or retuning is authorized during this audit.
