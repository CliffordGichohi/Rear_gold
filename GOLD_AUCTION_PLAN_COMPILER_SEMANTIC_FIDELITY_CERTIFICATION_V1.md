# Gold Auction-Plan Compiler and Semantic-Fidelity Certification V1

Status: `FROZEN_BEFORE_IMPLEMENTATION_AND_FULL_CASE_ACCESS`

## 1. Scope

This is one engineering and semantic-fidelity milestone. It does not discover an edge, optimize a rule, calculate PnL, or open a fresh period.

All previous results, rejections, artifacts, and seals remain unchanged. The learned signal translator may continue to propose a timestamp and direction, but its learned stop-distance tree, target-distance tree, and learned thesis-family tree are prohibited inputs to the auction-plan compiler.

Permitted engineering populations are:

- the 30 exposed matched-human replay cases `CBR-2022-001` through `CBR-2022-030`, comprising 16 sealed human trade proposals and 14 sealed human no-trades;
- the 20 already-exposed signal identities in the frozen 50-case `GAV-2022-001` through `GAV-2022-050` block;
- only their certified primary/reference point-in-time streams and visible human annotations/drawings.

Outcome ledgers, post-decision paths, resolutions, MFE, MAE, trades, PnL, R, account returns, calendar 2025, calendar 2026, and any fresh month are prohibited.

The initial inventory inspected visible-ledger schema/examples and source metadata only. It opened no outcome artifact.

## 2. Compiler boundary

The compiler is not a direction generator. It receives:

- a proposed direction (`LONG` or `SHORT`);
- a point-in-time decision timestamp;
- an entry reference already visible at that timestamp;
- a certified replay stream.

For human trade cases, direction, timestamp, and entry reference come from the sealed visible decision. Human annotations, drawings, stop, and target are comparison evidence and may not choose the compiler plan.

For GAV cases, direction remains the frozen proposed `LONG`, timestamp comes from the sealed outcome-free signal registry, and entry reference is the latest completed M1 close available at that timestamp. No learned geometry or learned family is passed.

A human `NO_TRADE` supplies no direction proposal. The compiler must return `NO_TRADE_UNRESOLVED` with reason `NO_DIRECTION_PROPOSAL`; it must not search both directions after the fact.

## 3. Point-in-time structure primitives

The compiler reuses the existing deterministic causal structure engine:

- completed records require `complete = true` and `available_at <= decision_at`;
- ATR is the 14-member arithmetic mean of completed true ranges;
- a swing is a strict five-bar pivot with two bars on each side, minimum prominence `max(0.25 ATR, $0.02)`, and is known only when the second right-hand bar is available;
- a structural break is a completed close beyond a confirmed swing by `max(0.10 ATR, $0.02)`;
- transition origin is the latest opposite-colour completed candle among the four candles before the break, falling back to the break candle adverse extreme;
- a break remains active until a completed close invalidates its protected swing by the same structural buffer;
- balance definitions and level lifecycle reuse the frozen coherent-auction engine unchanged;
- macro context uses only the latest fundamental snapshot available at the decision timestamp.

No future extrema, eventual archetype, outcome, MFE, or MAE may enter any identity or price.

## 4. Six required plan components

An `EXECUTABLE_PLAN` requires all six components below. Otherwise disposition is `NO_TRADE_UNRESOLVED`, with every missing component recorded.

### 4.1 Macro context

Store state, score, confidence, quality, availability timestamp, record hash, dominant driver, and `OBSERVED/CALCULATED/INFERRED/UNKNOWN` status. Macro is context and a warning; alignment or opposition is not an admission filter in this milestone. A missing snapshot remains an explicit `UNKNOWN` component rather than invented data.

### 4.2 Governing auction

Classify in this fixed order:

1. `STRUCTURAL_REPAIR`: active H4 damage opposes the proposed direction, an aligned active H1 or M15 break exists after that damage, and the selected trigger is not earlier than the repair break.
2. `RANGE_ROTATION`: no qualifying directional progression exists and price is in the directional starting outer quarter of the latest active H4/H1 balance—lower quarter for `LONG`, upper quarter for `SHORT`—without an accepted breakout in the proposed direction.
3. `CONTINUATION_WITH_ROOM`: an active H4/H1 directional progression exists in the proposed direction, including an M15 balance nested inside that higher-timeframe progression; or an active balance has an accepted breakout in the proposed direction.
4. Otherwise unresolved.

The governing-auction object must include a deterministic identity, family, controlling timeframe, controlling structural/balance identity, known timestamp, and evidence classification.

### 4.3 Controlling structure/location

- Continuation: the selected active H4/H1 progression event or accepted breakout balance.
- Range rotation: the selected H4/H1 balance and directional boundary.
- Structural repair: the H4 damage identity plus the first later aligned H1/M15 repair break.

The object must include identity, timeframe, kind, relevant levels, known timestamp, and point-in-time evidence.

### 4.4 Local trigger

Eligible triggers are completed structural events, not narrative candle names:

- `M15_STRUCTURE_TRANSITION`: latest active M15 break in the proposed direction.
- `M5_INTERNAL_ROTATION`: latest active M5 break in the proposed direction when an active aligned M15 break or an unaccepted M15 balance supplies the containing auction.

If both exist, select the later event by `break_at`; ties prefer M15. The trigger remains eligible while its protected swing remains active. Age is reported in completed bars but is not a performance-derived veto.

The trigger must include identity, family, timeframe, break timestamp, broken swing, protected swing, transition origin, buffer, and containing-auction identity.

### 4.5 Structural invalidation

For `LONG`, use the minimum adverse value; for `SHORT`, the maximum adverse value among:

- trigger protected swing;
- trigger transition origin;
- containing M15 balance boundary for an internal M5 rotation;
- active aligned M15 protected swing when the local trigger is M5;
- structural-repair origin where applicable.

Place invalidation a further `0.10 × completed M15 ATR(14)` adverse, with a `$0.02` floor. The object must name every contributing identity and level. A geometry not adverse to entry is unresolved. The human mapped stop is comparison evidence only.

### 4.6 Liquidity destination

- Range rotation: opposite boundary of the controlling H4/H1 balance; midpoint is descriptive partial-realization evidence only.
- Continuation or structural repair: nearest still-active opposing H1 confirmed-swing zone ahead of entry; H4 is fallback only when H1 is absent.

Permitted lifecycle states are `ACTIVE_UNTOUCHED`, `ACTIVE_ENGAGED`, and `REACTIVATED_REVERSE`. A consumed, behind-entry, future-formed, or absent destination is unresolved. The destination must include identity, source timeframe, lifecycle, level, buffer, and known timestamp. The human mapped target is comparison evidence only.

## 5. Semantic comparison registry

Human annotations are parsed only after compiler output is frozen per case.

- Expected governing family is `RANGE_ROTATION` only when H1/H4 is explicitly the controlling range with premium/discount location; an M15 range nested in an H1/H4 trend remains `CONTINUATION_WITH_ROOM`. Explicit repair/reversal language maps to `STRUCTURAL_REPAIR`; otherwise a trade maps to `CONTINUATION_WITH_ROOM`.
- Expected trigger timeframe is M5 when the sealed transition/thesis explicitly says M5; otherwise M15 when it explicitly says M15; otherwise `UNSPECIFIED`.
- Human invalidation and target prices are reported against compiler prices in absolute and M15-ATR units. They do not retune the compiler.
- Human target timeframe is compared with compiler destination source.
- Every disagreement is retained by alias; no case is removed.

## 6. Certification gates

Technical certification passes only if:

1. primary and reference sources produce byte-identical plan payloads after removal of implementation labels and creation timestamps;
2. every cited `available_at`, `detected_at`, `break_at`, and `known_at` is not later than `decision_at`;
3. every executable plan contains all six components, stable identities, adverse invalidation, forward destination, and no learned geometry field;
4. every incomplete plan is `NO_TRADE_UNRESOLVED` and names all missing components;
5. all 14 human no-trades remain no-trades because no direction was proposed;
6. at least 13 of the 16 human trade proposals compile to complete executable plans;
7. governing-auction agreement is at least 75% among compiled human trades with a specified expected family;
8. trigger-timeframe agreement is at least 75% among compiled human trades with a specified expected trigger timeframe;
9. H1 destination-source agreement is at least 75% among compiled human trades whose annotation specifies H1;
10. every exposed GAV signal is resolved exactly once as either a complete executable plan or explicit unresolved no-trade;
11. two sequential implementations reproduce identities, dispositions, missingness, and checksums exactly;
12. no outcome or fresh-period artifact is opened.

A gate failure is an honest `FAIL_SEMANTIC_FIDELITY_CERTIFICATION`. It does not authorize threshold repair from outcomes. Mismatches may identify one subsequent engineering correction, but no correction is implemented after certification in this milestone.

## 7. Required artifacts and stop

Produce and seal:

- contract and source freeze;
- minimal outcome-free GAV signal-identity registry;
- compiler implementation and synthetic causal tests;
- primary/reference human and GAV plan registries;
- complete mismatch catalog;
- certification result and final seal.

Acquire no data, incur no charge, calculate no PnL, keep all fresh periods closed, and stop after certification.

