# Multi-Asset Macro and Session Portfolio Edge Discovery V1 — Milestone 1 Coverage Audit

## Verdict

**PASS_MILESTONE_1_CONTRACT_AND_AUDIT — SOURCE BACKFILL REQUIRED BEFORE DISCOVERY.**

The contract is frozen and the audit reproduced exactly. The seven-instrument branch is not yet ready for relationship discovery: two instruments have adequate stored one-minute paths, two are partial, and three have catalog presence but no stored development path. This is a source-readiness result, not evidence for or against an edge.

The previous `TERMINATE_GOLD_ONLY_10R_BRANCH` verdict remains binding. No outcome, relationship, trade, PnL, or 2025/2026 market value was opened, and no charge was incurred.

## Instrument coverage

| Research instrument | Exact MT5 symbol | Classification | Unique development M1 timestamps | First | Last | Duplicate occurrences |
|---|---|---:|---:|---|---|---:|
| XAUUSD | `XAUUSD` | PRESENT_AND_ADEQUATE | 1,210,817 | 2021-08-02T01:02:00Z | 2024-12-31T23:58:00Z | 0 |
| XAGUSD | `XAGUSD` | PRESENT_BUT_PARTIAL | 0 | - | - | 0 |
| EURUSD | `EURUSD` | PRESENT_AND_ADEQUATE | 1,274,793 | 2021-08-02T00:03:00Z | 2024-12-31T23:58:00Z | 28,723 |
| USDJPY | `USDJPY` | MISSING | 0 | - | - | 0 |
| NAS100 | `USTEC` | MISSING | 0 | - | - | 0 |
| US500 | `US500` | PRESENT_BUT_PARTIAL | 0 | - | - | 0 |
| WTI | `XTIUSD` | MISSING | 0 | - | - | 0 |

Catalog presence is not history coverage. Partial casebook snapshots are context observations and cannot replace an M1 decision/outcome path. Existing XAUUSD and EURUSD sources must not be reacquired.

## Deduplication and reproduction

- Canonical identity: `(MT5 symbol, open_time)`.
- Duplicate resolution: lexicographically earliest source filename, then source row; raw files remain unchanged.
- XAUUSD duplicate occurrences in the development window: 0.
- EURUSD duplicate occurrences in the development window: 28,723.
- Primary/reference semantic hash: `59f4dbc3ebbe5689c1ad9fddd0a19a53e9f25f285dfacd781f3ff42e36c2ea56`.
- Independent reproduction: **PASS**.

## Reused sealed macro/context sources

| Requirement | Status | Fitness |
|---|---|---|
| `FRED_ALFRED_POINT_IN_TIME_MACRO` | PRESENT_AND_ADEQUATE | Point-in-time slow macro context; not an intraday substitute |
| `MT5_SCHEDULED_MACRO_EVENTS_POST_RELEASE` | PRESENT_AND_ADEQUATE | Post-release event taxonomy and response alignment |
| `CFTC_GOLD_COT` | PRESENT_AND_ADEQUATE | Weekly positioning context only |
| `DAILY_RISK_MARKET_CONTEXT` | PRESENT_AND_ADEQUATE | Slow risk-regime context |
| `ZT_INTRADAY_TWO_YEAR_PROXY` | PRESENT_AND_ADEQUATE | Intraday front-end Treasury repricing; roll transitions remain UNKNOWN |
| `ZN_INTRADAY_TEN_YEAR_PROXY` | PRESENT_AND_ADEQUATE | Intraday long-end nominal Treasury repricing; roll transitions remain UNKNOWN |
| `ZQ_FRONT_CONTINUOUS_POLICY_PROXY` | PRESENT_BUT_PARTIAL | Sparse front-contract proxy, not a complete meeting-by-meeting path |
| `SR3_FRONT_CONTINUOUS_POLICY_PROXY` | PRESENT_BUT_PARTIAL | Sparse front-contract proxy, not a complete SOFR curve |

The frozen limitations remain: EURUSD is an inverse-dollar proxy, not DXY; ZQ/SR3 are partial front-contract paths; COT is weekly metals context; historical MT5 forecasts are not verified pre-release vintages; Japanese rates and EIA inventory history are absent.

## Minimal missing-data acquisition list

- `XAGUSD` (XAGUSD): IC Markets MT5 M1, 2021-08-01 through 2024-12-31; expected paid-provider charge $0.
- `USDJPY` (USDJPY): IC Markets MT5 M1, 2021-08-01 through 2024-12-31; expected paid-provider charge $0.
- `USTEC` (NAS100): IC Markets MT5 M1, 2021-08-01 through 2024-12-31; expected paid-provider charge $0.
- `US500` (US500): IC Markets MT5 M1, 2021-08-01 through 2024-12-31; expected paid-provider charge $0.
- `XTIUSD` (WTI): IC Markets MT5 M1, 2021-08-01 through 2024-12-31; expected paid-provider charge $0.

This is a later, free MT5 backfill step. Nothing was downloaded in Milestone 1.

## Stop point

Milestone 1 is complete and sealed. Relationship discovery remains unauthorized until the five incomplete instruments pass the same value-blind M1 coverage gates. The 10R/month objective remains report-only and cannot influence candidate selection.
