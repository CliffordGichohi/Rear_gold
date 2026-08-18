# Gold Blind Point-in-Time Discretionary Replay Edge Audit V1 — Pre-Label Report

Status: `PASS_PRELABEL_APPLICATION_READY`

Date: 2026-08-13

## Outcome

The frozen protocol and blinded replay application are complete. Human labeling has not begun and no edge has been evaluated.

- Practice population: 20 cases, zero research credit.
- Scored population: 240 cases, forty cases in each 2022–2024 year × London/New York stratum.
- First frozen case: `P-001`.
- Decision records at seal: zero.
- Calendars 2025 and 2026: locked and not inspected.
- Data acquired: none.
- Charge: USD 0.00.

## Coverage Amendment A

The initial display materialization was formally rejected because the casebook's universal completed-bar flag treated ordinary no-tick minutes as absent daily history. The failed attempt and all original artifacts remain unchanged.

Coverage Amendment A was frozen before human labeling. It permits a daily display bar only when the observed quote path has at least 1,000 source minutes and at least 95% quote coverage; a weekly display bar requires at least four eligible daily bars. Seventy-six scored aliases were reassigned outcome-blindly to the next eligible date in the same frozen year/session stratum. Aliases, presentation order, counts, and practice cases were preserved.

All 240 scored cases now have exactly:

- 52 weekly candles;
- 120 daily candles;
- 90 H4 candles;
- 120 H1 candles;
- 160 M15 candles;
- 180 M5 candles;
- 180 M1 candles.

## Integrity certification

Two independent parsers reproduced identical price inputs, practice inputs, display payloads, practice payloads, null classifications, payload hashes, and byte-identical gzip files. The following gates passed:

- amended population freeze and all predecessor hashes;
- exactly 260 unique frozen cases;
- exact chart histories for all scored cases;
- point-in-time context availability;
- normalized checkpoint reference of 100;
- no absolute date, time, or price in browser payloads;
- no scored future path materialized;
- GC primary/reference state equality;
- calendar 2025/2026 lock;
- no acquisition and no charge.

## Replay application

The local application is available at `http://localhost:3000/replay`.

The interface provides:

- normalized W1, D1, H4, H1, M15, M5, and M1 candles;
- pre-existing session and liquidity levels;
- point-in-time fundamentals, structure, positioning, cross-market, event, broker-liquidity, and optional GC order-flow context;
- strict `LONG`, `SHORT`, or `NO_TRADE` decision validation;
- confidence, observable entry trigger, ATR-based entry offset and invalidation, R target, evidence codes, and written reasoning;
- practice feedback only after the practice decision is irreversibly locked;
- no feedback during scored labeling;
- a single sequential append-only SHA-256 decision chain with idempotent submission and tamper detection.

The API is exposed under `/api/v1/blind-replay`. Only `GET /status`, `GET /next`, and `POST /decisions` are provided; arbitrary case browsing, decision updates, deletion, reset, and outcome access are absent.

## Frozen evaluation boundary

Evaluation remains unauthorized until all 240 scored decisions are locked. The preregistered fixed execution, costs, $50 risk, support requirements, clustered uncertainty, calibration tests, Holm correction, chronological-stability checks, and economic PASS/REJECT gates remain exactly as specified in `GOLD_BLIND_POINT_IN_TIME_DISCRETIONARY_REPLAY_EDGE_AUDIT_CONTRACT_V1.md`.

The current research conclusion is only:

`HUMAN_LABELING_REQUIRED_EDGE_NOT_EVALUATED`

