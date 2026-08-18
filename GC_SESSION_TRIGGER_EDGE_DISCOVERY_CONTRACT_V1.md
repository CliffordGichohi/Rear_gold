# GC Session Trigger Edge Discovery Contract V1

Status: `FROZEN_MILESTONE_1_BEFORE_EVENT_OR_OUTCOME_VALUE_ACCESS`

## Objective

After a preregistered London or New York price-level or liquidity/order-flow event is fully observable, does its preregistered direction predict the next fifteen minutes of XAUUSD more often and by more than chance, and does point-in-time macro or structure alignment materially strengthen that relationship?

This branch preserves the formal Step 5D-R3 zero-candidate result. It does not repair the failed fixed-cutoff tests. Fundamentals define context; an observable event defines the trigger; neutral forward behaviour defines the outcome. Execution remains separate.

## Development and holdouts

- Development is limited to the sealed 188-date sample from 8 November 2021 through 13 December 2024.
- The sample contains 38 calendar-selected month-week blocks and is not every trading day.
- Calendar 2025 remains locked and, if later opened, has exposed-historical-forward status only.
- Calendar 2026 remains the locked independent/prospective period.

## Trigger model

London and New York are analysed separately. Decisions occur only after a complete XAUUSD minute bar confirms one of six frozen event families: level sweep/reclaim, level acceptance, failed acceptance, flow-depth alignment onset, absorption onset, or fragility-with-flow onset. GC order-book inputs retain the sealed 85-column engineering definitions and `ts_recv` availability authority.

Price-level triggers may use the completed Asia range, prior-day range, London pre-New-York range, or the first fifteen session minutes. XAUUSD levels are never compared numerically with GC futures prices.

## Outcome boundary

The primary endpoint is signed XAUUSD displacement fifteen minutes after event confirmation. Five-, thirty-, and sixty-minute results and GC midpoint agreement are consistency outputs only. The anchor is a neutral measurement, not a fill. Stops, targets, trades, PnL, R multiples, and account returns are prohibited.

## Statistical governance

- Stage 1 permits at most six pooled, two-sided event-family tests per session.
- Stage 2 permits at most 33 event-by-one-context tests per session; no three-way interactions.
- Both bullish and bearish variants must meet support floors. A one-sided result cannot become a V1 candidate.
- Inference uses week-block bootstrap, deterministic cluster randomization, and Benjamini-Hochberg control at `q <= 0.05`.
- At most two provisional development candidates may advance per session; zero is acceptable.

## Power limitation

The 187-date-per-session ceiling can test large, recurrent event effects. It is not reliably powered for small conditional lifts after multiplicity and week clustering.
 Actual trigger support is intentionally unknown until an outcome-blind Milestone 2. If support is inadequate, the study must stop or seek a separately authorized outcome-blind sample expansion.

## Milestone sequence

1. Contract, registries, traceability, metadata coverage, and power audit — complete and sealed.
2. Full-session technical certification and outcome-blind trigger/support materialization — not authorized.
3. Exact test freeze followed by one development outcome join and discovery — not authorized.
4. Frozen-candidate calendar-2025 forward evaluation — not authorized.
5. Calendar-2026 independent/prospective evaluation — not authorized.

Milestone 1 stops here. No event values, forward outcomes, candidates, execution, or returns were inspected or calculated.
