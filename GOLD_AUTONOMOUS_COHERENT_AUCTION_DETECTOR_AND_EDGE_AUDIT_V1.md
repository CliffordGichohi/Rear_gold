# Gold Autonomous Coherent-Auction Detector and Edge Audit V1

Status: `DESIGN_FIXED_PENDING_PREVALUE_SEAL`

## 1. Question and preserved evidence

Can the semantically certified coherent-auction plan be discovered autonomously and produce positive net expectancy when direction, decision time, entry reference, invalidation, and destination are not supplied by a human?

All previous results, failures, rejections, artifacts, and seals remain unchanged. In particular:

- the V1 compiler failure remains a formal failure;
- Semantic Amendment A remains an outcome-free semantic PASS;
- the fitted, long-only 59-node translator and every previously rejected automation branch remain rejected and are prohibited inputs;
- the original 30 human cases and original 50 GAV cases are exposed engineering populations with zero edge credit;
- no human annotation is market truth or an admission label.

## 2. Autonomous detector

The detector receives only one certified point-in-time session stream. It is not supplied a direction, signal timestamp, entry, human decision, outcome, MFE, MAE, or realised archetype.

It operates as follows:

1. Enumerate completed M15 and M5 structural-break boundaries inside the frozen London or New York session using the unchanged causal swing and break primitives.
2. Sort those timestamps chronologically.
3. At each timestamp, use the latest completed and available M1 close as the visible entry reference.
4. Compile both `LONG` and `SHORT` plans with Semantic Amendment A.
5. A direction qualifies only when the plan is complete, integrity-clean, and its frozen V1 execution anchor is the structural event completed at that checkpoint.
6. If exactly one direction qualifies, seal the first such plan as the session proposal.
7. If both directions qualify, classify that checkpoint as `AMBIGUOUS_TWO_SIDED` and continue. If neither qualifies, continue.
8. If no unique plan occurs before the session deadline, return `NO_SIGNAL`.

The implementation may precompute causal event identities to avoid repeatedly reconstructing identical histories. Every selected signal must then reproduce exactly when the source is truncated at the signal timestamp. This prefix-only proof is mandatory and prevents later bars from selecting an earlier signal.

Macro remains traceable context and is not an admission veto. No probability model, fitted threshold, minimum-reward filter, manual label, or performance-derived condition is permitted.

## 3. Engineering and historical-robustness populations

The 30 matched-human and 50 exposed GAV streams may be used only for synthetic, causal, support, and deterministic-reproduction engineering. Their outcomes and prior PnL may not select or change this detector.

Before opening new values, freeze a 50-case historical-robustness block using metadata only:

- source: the sealed Gold Blind Discretionary Replay V1.1 `SCORED` registry;
- dates: calendar 2022 through 2024 only;
- sessions: exactly 25 London and 25 New York cases;
- exclusions: every date and source identity in the 30 matched-human cases and exposed 50 GAV cases;
- coverage: at least 95% of expected session M1 closes with ordered unique timestamps and point-in-time lineage;
- selection: the first 25 remaining eligible cases per session in the already-sealed outcome-blind `mode_sequence` order.

This block is a one-shot historical robustness test, not pristine independent validation, because 2021–2024 have been used elsewhere in the project. Calendar 2025 and 2026 remain closed for this audit.

## 4. Frozen execution

- One proposal and at most one trade per session case.
- Signal entry: first observed M1 open strictly after the signal timestamp.
- Directional fill cost: half the observed spread plus $0.05 adverse slippage; missing or invalid spread falls back to $0.20.
- Structural stop and liquidity destination: exactly the certified compiler outputs.
- Stop exit: structural stop plus adverse half-spread and $0.05 slippage.
- Target exit: frozen destination price with no favourable slippage.
- Same-bar ambiguity: stop first.
- Deadline: final observed M1 close of the session, charged adverse half-spread and $0.05 slippage.
- Commission: $0 under the existing IC Markets replay assumption.
- Planned risk: maximum $50 on a $10,000 reference account.
- Quantity: whole ounces, `floor($50 / effective stop loss per ounce)`; fewer than one ounce is `REJECT_RISK_GEOMETRY`.
- A fill whose stop is not adverse or whose destination is not forward is rejected as an integrity failure.
- Cost stress: multiply spread and slippage by 1.5 while preserving the signal and structural prices.

No trailing, partial exit, break-even, runner, second entry, direction flip, or discretionary management is permitted in V1. Management research is authorized only if the base signal demonstrates positive net expectancy.

## 5. Reproduction and economic gates

Primary and reference source loaders and detector passes must agree exactly on populations, source identities, signals, directions, timestamps, plans, dispositions, trades, and metrics.

Report cases, signals, ambiguous checkpoints, risk rejections, trades, direction split, family split, wins/losses/time exits, win rate, net R50, dollars, expectancy, profit factor, maximum drawdown, 95% case-bootstrap expectancy interval, 1.5x-cost result, chronological halves, London/New York contributions, and monthly opportunity rate.

`PROVISIONAL_EDGE_PASS` requires all of:

- at least 20 executed trades;
- positive net expectancy after costs;
- profit factor at least 1.10;
- positive 95% bootstrap lower bound for expectancy;
- positive net result at 1.5x costs;
- positive net result in both chronological halves;
- neither session contributes more than 80% of positive gross R;
- maximum drawdown no greater than 30R, equivalent to 15% at fixed $50 risk;
- exact reproduction and zero integrity or causality failures.

`REJECT` applies to non-positive expectancy, profit factor below 1.0, future leakage, source failure, or reproduction failure. Other failures are `INCONCLUSIVE`.

A PASS remains historical evidence and authorizes prospective paper tracking, not live execution. Do not retune after opening the block. Acquire no data, incur no charge, and do not inspect 2025 or 2026.
