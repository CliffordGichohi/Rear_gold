# Multi-Asset Session Behaviour, Archetype and Monetization Discovery Contract V1

Status: **FROZEN BEFORE SESSION-BEHAVIOUR OR OUTCOME ACCESS**  
Branch: `MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_MONETIZATION_V1`

## Authority and preserved history

This branch was authorized to census how six non-gold markets actually behave before proposing another strategy. It preserves every prior result and seal. In particular:

- Multi-asset Milestone 3 remains **`REJECT_NO_MULTI_ASSET_PORTFOLIO_EDGE`**.
- The observed gold policy `TARGET_TAKE_25_RUN_75` remains frozen, excluded, and carries no independent-validation claim.
- XAUUSD is not a target instrument or case in this branch.
- No negative result is inverted, renamed, filtered, or granted new validation credit.

The held gold result remains bound to `64a250affd1d781db10de1231170b415e688309f39e81212eeff2cb26c82a246` and the multi-asset Milestone-3 seal to `2515b0b3c3cd5f339f346f359c9c15f928f66d2a5ba5dcf2a976fab2753273c8`.

## Research question

For each eligible instrument and session, what complete path repeatedly occurs; how large, frequent, and stable is each path archetype; what conditions were genuinely observable beforehand; and only afterward, how much of that behaviour could a fixed point-in-time execution policy plausibly retain?

This is discovery, not an attempt to prove the four rejected Milestone-3 concepts. No predefined trigger receives privileged status.

## Partitions and lock

- Development: `2021-08-01T00:00:00Z <= t < 2025-01-01T00:00:00Z`.
- Calendar 2025: locked until a complete policy is frozen; never used to define an archetype, relationship, threshold, or execution rule.
- Calendar 2026: locked for later robustness and prospective tracking.
- Milestone 1 accesses development timestamp metadata only. It creates no session behaviour values.

## Frozen instrument-session census

Every Monday-Friday local session identity remains in the registry, including incomplete and unavailable identities. Missing timestamps are not silently called holidays.

| Instrument | Session unit |
|---|---|
| EURUSD (`EURUSD`) | `ASIA_SESSION` |
| EURUSD (`EURUSD`) | `LONDON_SESSION` |
| EURUSD (`EURUSD`) | `NEW_YORK_SESSION` |
| US500 (`US500`) | `LONDON_SESSION` |
| US500 (`US500`) | `US_CASH_SESSION` |
| USDJPY (`USDJPY`) | `ASIA_SESSION` |
| USDJPY (`USDJPY`) | `LONDON_SESSION` |
| USDJPY (`USDJPY`) | `NEW_YORK_SESSION` |
| NAS100 (`USTEC`) | `LONDON_SESSION` |
| NAS100 (`USTEC`) | `US_CASH_SESSION` |
| XAGUSD (`XAGUSD`) | `ASIA_SESSION` |
| XAGUSD (`XAGUSD`) | `LONDON_SESSION` |
| XAGUSD (`XAGUSD`) | `NEW_YORK_SESSION` |
| WTI (`XTIUSD`) | `LONDON_SESSION` |
| WTI (`XTIUSD`) | `US_ENERGY_SESSION` |

Decision time is the local session start converted with its IANA timezone. The neutral path coordinate is the open of the exact M1 bar one minute after that decision. Observation ends at the frozen local session close. This coordinate is not an entry or fill.

## Decision-state boundary

Only facts with `available_at <= decision_at` may enter `decision_state`. All weekly, daily, H4, H1, M15, and M5 candles must be completed. Strict two-left/two-right swings become known only after the second right candle closes. COT becomes usable on publication, never Tuesday observation. Revisions enter only at their own release. Missing and unverified data are `UNKNOWN`, never neutral.

The state includes book-traceable mechanics, higher-timeframe structure, pre-existing levels, macro regime, expectations, catalysts, positioning where applicable, session context, and cross-market context. Institutional motives remain `INFERRED` unless directly sourced.

## Frozen outcome-neutral measurements

Future Milestone 2 may calculate, but Milestone 1 only defines:

- signed and absolute displacement at 5, 15, 30, 60, 120 minutes and session close;
- range, maximum upward and downward excursion, high/low timing and order;
- symmetric long/short MFE and MAE from the fixed neutral coordinate;
- first passage to ±0.25, ±0.50, ±1.00, ±1.50, ±2.00, and ±3.00 pre-decision ATR;
- close location, path efficiency, completed-M5 turns, and realized path volatility;
- interactions with levels already known at the decision; and
- deterministic descriptive archetypes.

MFE/MAE here are symmetric descriptive coordinates. They assume no trade, entry, stop, target, size, fill, or PnL. If both passage thresholds occur within the same M1 bar, the order is `AMBIGUOUS_SAME_BAR`; no stop-first convention is imported.

## Frozen archetype taxonomy

Classification order is fixed before outcomes:

1. data unavailable;
2. sweep and reversal;
3. failed break;
4. breakout and hold;
5. one-sided auction;
6. two-sided expansion;
7. directional trend;
8. balanced compression;
9. rotational path; and
10. mixed/unclassified.

Each directional family records `UP`, `DOWN`, `BOTH`, `NONE`, or `UNKNOWN`. Exact ATR, close-location, acceptance, reclaim, and efficiency thresholds are in the machine protocol. The taxonomy describes realised paths; it is never supplied to a decision checkpoint.

## Milestone sequence

1. **Milestone 1 — current:** contract, traceability, identity registry, case schema, metadata-only coverage audit, state, and seal.
2. Milestone 2: materialize all eligible decision states and descriptive session paths once.
3. Milestone 3: describe archetype frequencies and matched hypothetical capture ceilings without selecting execution.
4. Milestone 4: inspect simple conditions, then bounded interactions, and derive a small frozen shortlist.
5. Milestone 5: test point-in-time execution and economics on development only.
6. Milestone 6: if candidates survive, open locked forward segments once and unchanged.

## Milestone 1 prohibition and stop

Milestone 1 may inspect identifiers, hashes, filenames, timestamps, schema metadata, and counts. It may not inspect OHLC, spread values, volume values, outcomes, excursions, directions, relationships, hypothetical returns, trades, R, PnL, or 2025/2026 market values. It incurs no charge.

Completion of the Milestone-1 state and seal is a mandatory stop. No case matrix is materialized in this milestone.
