# Gold Coherent-Auction Retrospective Process Audit V1

Status: `FROZEN_BEFORE_PREDECISION_PACKET_MATERIALIZATION`

## 1. Purpose and evidentiary status

This audit separates avoidable process defects from ordinary losing outcomes in the already-exposed 50-case frozen-translator block. It is not strategy optimization, fresh validation, or permission to change the frozen translator.

All prior results, rejections, artifacts, and seals remain unchanged. The existing block result remains `INCONCLUSIVE`: 20 signals, 15 admitted trades, 8 wins, 7 losses, `+3.6907126075569305R`, profit factor `1.9525484952987022`.

Because aggregate outcomes have already been reviewed, this audit receives zero validation credit. Its protection against hindsight is mechanical: classifications are first produced from sealed predecision-only packets that contain no post-signal bar, resolution, MFE, MAE, PnL, or win/loss field. Those classifications are sealed before any result join.

## 2. Population

- Source population: the 50 sealed `GAV-2022-001` through `GAV-2022-050` validation streams.
- Audit population: all 20 cases on which the frozen translator emitted a signal, including the five signals rejected by its contextual policy.
- The 30 no-signal cases remain reported as outside the setup-process audit.
- Direction remains the translator's frozen `LONG`; no inversion or alternative decision is permitted.
- Signal time, fill, stop, target, family, cost, and contextual admission decision remain unchanged.

## 3. Governing method

The audit uses the Reference Book and the corrected six-step human auction method:

1. Point-in-time macro/fundamentals describe directional environment and conviction.
2. Completed H4/H1 structure and pre-existing decision/liquidity areas define location and room.
3. Completed M15 structure, or completed M5 structure nested inside an M15 auction, supplies the local response/trigger.
4. The structure controlling that trigger supplies invalidation.
5. The next pre-existing opposing liquidity/decision area supplies destination.
6. Bias, trigger, invalidation, target, and risk remain separate.

Liquidity is treated as the market's ability to absorb orders and an inferred concentration of decisions—not as observed institutional orders or a magical line. A losing outcome alone can never prove bad process.

## 4. Outcome-isolated evidence packet

For each signal, the packet may contain only:

- case alias, session, frozen signal timestamp, and source hashes;
- records whose `available_at` is not later than the signal timestamp;
- frozen translator direction, family, fill, stop, target, cost, risk, and admission metadata;
- point-in-time macro, event, H4/H1/M15/M5 structure, balances, zones, lifecycle states, and reconstructed trigger evidence;
- exact identities and timestamps used to reconstruct controlling structure, invalidation, and destination;
- deterministic audit findings and their evidence hashes.

The packet must not contain later candles, results, exit timestamps, resolutions, MFE, MAE, PnL, R, hit/miss labels, or any proxy derived from those fields.

## 5. Frozen tests and ordered dispositions

### 5.1 Integrity

`OBJECTIVE_PROCESS_VIOLATION` if any frozen decision field is non-finite, `stop < fill < target` is false for LONG, quantity is below one whole ounce, planned loss exceeds `$50`, a cited record was unavailable at the signal timestamp, or a future-formed structure/level is used.

### 5.2 Required traceability

The autonomous implementation must name or allow deterministic predecision reconstruction of:

- thesis family and governing H4/H1 auction;
- live completed-candle trigger and confirmation timestamp;
- trigger-controlling adverse structure;
- structural invalidation price;
- next opposing liquidity/decision destination and its lifecycle state.

If the stored translator output omits an identity but the sealed predecision stream reconstructs one uniquely, the reconstructed identity may supply audit evidence without changing the trade. If it cannot be reconstructed uniquely, disposition is `UNVERIFIABLE_IMPLEMENTATION`, not a loss-derived rejection.

### 5.3 Trigger coherence

`OBJECTIVE_PROCESS_VIOLATION` if no approved completed-candle trigger was live at the frozen signal timestamp. Approved families are boundary sweep/reclaim followed by aligned break/retest, M15 break/retest, and M5 internal rotation within a controlling M15 balance. A wick, unfinished candle, or transient tick is insufficient.

If more than one trigger is simultaneously defensible and the stored output does not identify which controlled the trade, disposition is `UNVERIFIABLE_IMPLEMENTATION` unless all defensible triggers imply the same adverse controlling boundary.

### 5.4 Invalidation coherence

For LONG, the minimum structurally coherent invalidation is beyond the farthest adverse value among the selected trigger's protected swing, transition origin, controlling balance boundary, and sweep extreme where applicable, with the frozen `0.10 × M15 ATR` buffer.

- A frozen stop inside that boundary is `OBJECTIVE_PROCESS_VIOLATION: INVALIDATION_INSIDE_CONTROLLING_STRUCTURE`.
- A stop at or beyond it is structurally feasible.
- A stop more than `0.50 × M15 ATR` beyond the reconstructed minimum is reported as `DISCRETIONARY_QUALITY_CONCERN: EXCESS_INVALIDATION_WIDTH`, but is not a hard failure when risk remains capped.
- No future MAE percentile may define or repair a stop.

### 5.5 Destination coherence

The destination must be a pre-existing, still-active opposing H1 liquidity/decision area, with H4 fallback; a range rotation may use its midpoint for partial realization and opposite boundary as destination.

- A target before the first named destination without a frozen partial-realization rationale is `DISCRETIONARY_QUALITY_CONCERN: TARGET_TRUNCATED_BEFORE_NAMED_LIQUIDITY`.
- A target materially beyond the first active opposing area without an acceptance/runner rule is `OBJECTIVE_PROCESS_VIOLATION: TARGET_BEYOND_FIRST_UNRESOLVED_LIQUIDITY`.
- An absent, consumed, behind-fill, or future-formed destination is an objective violation.
- If the destination cannot be identified uniquely from the predecision stream, disposition is `UNVERIFIABLE_IMPLEMENTATION`.

Target equivalence uses the destination's existing frozen buffer. For a balance boundary without a stored zone buffer, equivalence uses `max(0.10 × M15 ATR, $0.02)`. No outcome-based tolerance is permitted.

### 5.6 Context coherence

- Unknown critical macro or unavailable critical structure is `UNVERIFIABLE_IMPLEMENTATION`.
- Macro opposition, H4 direction, H4 range percentile, and an engaged inferred zone are context/warnings, never standalone retrospective loss filters.
- A continuation under opposed macro is reported as a discretionary concern; a coherent range rotation or bounded structural repair may be counter-macro.
- Existing frozen severe-impulse, extreme-extension, unresolved Tier-1 event, invalid-geometry, and absent-active-M15-structure vetoes are retained exactly. A signal rejected by those gates is not retrospectively converted to a trade.

### 5.7 Ordered pre-outcome classification

Each signal receives exactly one primary process class:

1. `OBJECTIVE_PROCESS_VIOLATION` — at least one objective rule contradiction.
2. `UNVERIFIABLE_IMPLEMENTATION` — no proved contradiction, but required thesis/trigger/invalidation/destination identity cannot be established.
3. `PROCESS_COMPLIANT_WITH_QUALITY_CONCERN` — all hard requirements hold, with one or more frozen discretionary concerns.
4. `PROCESS_COMPLIANT` — all hard requirements and traceability requirements hold with no concern.

All findings are retained even when a higher-priority primary class applies. The original translator admission/rejection is reported separately and never changed.

## 6. Outcome join and interpretation

Only after every predecision packet and classification is hashed and sealed may existing results be joined by case alias.

Joined labels are descriptive:

- compliant win;
- compliant valid loss;
- quality-concern win/loss;
- process-violation win/loss;
- unverifiable win/loss;
- original contextual rejection.

A valid loss is not a mistake. A winning process violation remains a process violation. No finding becomes a new entry filter, and no counterfactual PnL receives edge or validation credit.

## 7. Required reporting

Report all 20 signals individually and aggregate:

- original admission, process class, objective violations, concerns, and unverifiable fields;
- exact thesis, trigger, controlling structure, stop boundary, and target identity where reconstructible;
- wins/losses and R only after the sealed join;
- process-compliant win rate and expectancy as descriptive exposed evidence;
- the number and R attributable to objective process violations versus compliant valid losses;
- valid winners that any proposed hard filter would have removed;
- implementation gaps that prevent a fair practice judgment.

Recommend only corrections to implementation fidelity or journaling/traceability. Do not retune thresholds, add a performance filter, remove losses, alter frozen trades, inspect 2025/2026, or claim a validated edge.

## 8. Reproduction and locks

- Primary and reference packets and classifications must match exactly by canonical checksum.
- The outcome join must be independently reproduced from the sealed classification registry.
- All new artifacts are append-only and hash-sealed.
- Frozen translator and fresh-block result: unchanged.
- 2025 and 2026: locked.
- Paid acquisition: prohibited.
