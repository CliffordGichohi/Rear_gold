# Gold Coherent-Auction Complete Correction V1 Implementation Mapping

Status: `FROZEN_BEFORE_SYNTHETIC_PROOF_AND_MATCHED_PATH_ACCESS`

This mapping implements, but does not amend, the approved rulebook. It resolves only mechanical representations already implicit in the platform's existing point-in-time structure engine.

## Source and population

- Decision records: the 16 sealed human LONG decisions in the exposed matched-human comparison.
- Primary replay source: original primary stream where present, otherwise recovery-A primary.
- Reproduction source: recovery-A reference stream for the same alias.
- Decision evidence uses only complete records with `available_at <= submitted_at`.
- Actual fill is the already-sealed original fill. No replacement entry is searched.
- Post-fill path may be opened only after the synthetic proof passes.
- Deadline is the frozen UTC-trading-day final observed M1 close.

## Exact mechanical mappings

1. ATR is a rolling arithmetic mean of up to the latest 14 completed true ranges; a decision requiring ATR needs all 14 members.
2. A transition origin is the most recent opposite-colour completed candle among the four candles immediately preceding the breaking candle. If none exists, the breaking candle's adverse extreme is the origin.
3. A protected swing is the latest confirmed opposite-side five-bar swing known before the structural-break candle opened.
4. H4-zone acceptance uses H1; H1/session acceptance uses M15; M15 acceptance uses M5.
5. For a zone in direction `D`, two closes beyond its `0.10 ATR` buffer consume it. Two later closes back through the opposite buffer reactivate it in reverse.
6. An active engaged opposing zone blocks only when the sealed actual fill lies inside its buffered zone or has penetrated it without directional acceptance. A farther active zone is a destination, not an automatic blocker.
7. Fixed balances are enumerated chronologically. Among simultaneously qualifying boxes, use the latest-known box on the controlling timeframe; H4 precedes H1 only when the H4 boundary itself has a qualifying engagement/breakout event.
8. Trigger formation begins at the maximum availability timestamp of its thesis break/balance, controlling level, macro snapshot, and event state.
9. An earliest trigger remains live for 12 subsequent completed M5 candles and is cancelled by an opposite structural break, controlling-level invalidation, destination consumption, or stop invalidation.
10. For macro data quality, use the minimum data quality of the REAL_YIELD and USD components. A missing component or value below 60 produces `UNKNOWN`.
11. Event acceptance is directional. A proposed long after a Tier-1 event requires upside acceptance and retest of the fixed first-15-minute range; downside acceptance does not authorize the long.
12. Session boundary levels participate in obstruction/lifecycle evidence but continuation targets remain confirmed active H1 swing zones, falling back to H4 only when H1 is absent.
13. Planned loss per ounce is absolute fill-to-stop distance plus the sealed base round-trip cost per ounce. Quantity is `floor(50 / planned_loss_per_ounce)`.
14. Net PnL deducts the sealed base round-trip cost once for every exited ounce. The sealed actual fill already contains its historical entry slippage and is not adjusted again.
15. A completed-candle management signal executes at the next observed M1 open. Same-M1-bar ambiguity remains stop first.
16. If multiple formal blockers occur, the report retains all blockers and uses the approved ordered gate as the primary disposition.

## Deterministic ordering

- zone sort: price in trade direction, then H4, H1, session, M15, then confirmation timestamp and identity;
- balance sort: qualifying boundary event timestamp, source-timeframe priority, box-known timestamp, identity;
- trigger sort: confirmation timestamp, approved family precedence, break timestamp, identity;
- management event sort inside a minute: gap/stop, scheduled completed-candle exit, target/partial realization, then time exit;
- all serialized dictionaries use UTF-8 canonical JSON with sorted keys and compact separators.

No case alias, realised direction, MFE, MAE, terminal result, or later path value may enter classification.

