# Gold Market Intelligence Engine

Production-oriented research, analysis, ranking, dashboard, event-study, and
backtesting platform for XAUUSD and COMEX gold.

## Current status

The architecture checkpoint, runnable platform, point-in-time fundamental core,
economic-event research slice, deterministic sessions/market-structure slice, and
broker spread/tick-activity execution-liquidity slice, plus the first real-data
strategy/control comparison are implemented. The reference book was read in full
before the domain model was designed and remains the primary business and
market-logic specification.

The platform can ingest observed IC Markets XAUUSD one-minute bars from a locally
logged-in MetaTrader 5 terminal, preserve their source and availability timestamps,
ingest official public Treasury/real-yield/breakeven/dollar/Fed-rate,
equity/volatility/financial-stress, and CFTC gold-positioning history, ingest
official ALFRED vintages, versioned calendar/consensus/release bundles, and complete
Fed-path probability surfaces; calculate economic surprises and post-release gold
reactions; calculate a transparent fundamental permission score; run a DST-aware
Asian-range acceptance strategy; model spread/slippage/commission; and compare the
macro-filtered version with its price-only control. Every trade stores the exact
fundamental snapshot used at its decision clock. The 88-factor reference-book
registry keeps every unconnected factor explicitly `UNKNOWN` or `PARTIAL`. The
Coverage & Health page now renders all 88 factors—including later licensed
contracts—and the Executive Overview surfaces the book decision brief: driver,
catalyst, session, price confirmation, execution state, confirmation, invalidation,
and highest-risk assumptions.

The currently loaded ALFRED sync added 2,754 revision-aware macro vintages and the
MT5 store contains 1,770,267 completed one-minute bars from 2021-07-23 through
2026-07-24. The MT5 economic-calendar import adds 588 grouped US releases, 1,117
observed component values, and 1,059 consensus snapshots over the same five-year
window. MT5's chart-history limit is verified at 100,000,000 bars. Phase 1 factor
coverage is 82.19% and the latest fundamental snapshot has 77% evidence coverage.
These are coverage measurements, not performance claims.

## Run locally

Prerequisites: Docker Desktop with Compose v2. The demo path requires no broker or
paid-data credentials.

```powershell
Copy-Item .env.example .env  # only when .env does not already exist
docker compose up -d --build
docker exec gold-market-intelligence-api-1 python -m gold_intel.seed_demo
```

Open:

- dashboard: <http://localhost:3000>
- macro ledger: <http://localhost:3000/macro>
- positioning: <http://localhost:3000/positioning>
- expectations and event studies: <http://localhost:3000/events>
- sessions and market structure: <http://localhost:3000/structure>
- factor coverage: <http://localhost:3000/data-health>
- backtest lab: <http://localhost:3000/backtests>
- OpenAPI: <http://localhost:8000/docs>
- readiness: <http://localhost:8000/api/v1/health/ready>

The seed is idempotent: running it again reuses the original ingestion batches and
intelligence snapshot. It deliberately includes one missing minute so Data Health
reports a warning instead of silently fabricating a candle.

Sync the credential-free official public slice and calculate a snapshot:

```powershell
$body = @{ start = "2023-01-01"; end = "2026-07-23" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/providers/public/sync -ContentType application/json -Body $body

$snapshot = @{ instrument = "XAUUSD"; as_of = (Get-Date).ToUniversalTime().ToString("o") } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/fundamentals/snapshots -ContentType application/json -Body $snapshot
```

The public sync is content-hash idempotent. It stores raw payloads and normalized
records in one transaction; a failed provider leg exposes no partial dataset.
The current public market slice covers ten FRED series plus the CFTC gold report.
Equity/VIX and financial-stress interpretations are explicitly `INFERRED`; severe
deleveraging remains a documented contradiction because it can initially liquidate
gold even when defensive demand is rising.

## Point-in-time sessions and structure

The Structure dashboard calculates six horizons from complete one-minute bars:
1-minute, 5-minute, 15-minute, 1-hour, 4-hour, and daily. It exposes confirmed
swings, HH/HL/LH/LL, support/resistance, break of structure, market-structure shift,
range, compression/expansion, displacement, momentum, acceptance/rejection, failed
breakouts, trapped-breakout risk, and retests. Every detection includes its pivot
clock, later detection clock, method, confidence, source-bar evidence, epistemic
classification, and invalidation.

Daily XAUUSD aggregation uses a versioned provider session template rather than a
24-hour UTC bucket. The current IC Markets template handles the observed Sunday
open and recurring maintenance pause; unscheduled missing minutes still make the
aggregate incomplete. Asia, London, New York, overlap, LBMA, rollover, and close
windows use IANA timezones so daylight-saving changes are deterministic.

## Point-in-time events and event studies

Open the Events dashboard to upload a JSON event bundle and run a reaction study.
The executable example at
`data/sample/economic_event_bundle.synthetic.json` is deliberately marked
synthetic. Real and synthetic rows are selected by mutually exclusive data modes.

The event contract preserves separate clocks for:

```text
schedule known -> forecast as-of -> forecast available -> release -> release available
-> later revision available -> research cutoff
```

A forecast timestamped after the release is rejected by request validation and is
also excluded by the calculation engine. Surprise standardization uses earlier
eligible releases only. Event reactions use the last complete pre-release XAUUSD
minute and report 1m, 5m, 15m, 1h, 4h, daily-close, MFE, MAE, and whether the first
move held. Runs with no eligible real events return `COMPLETED_NO_DATA`; the system
does not manufacture a sample.

### Import the read-only MT5 economic calendar

The MetaTrader Python package does not expose the terminal's economic-calendar
database, so `tools/mt5/GoldIntelCalendarExport.mq5` performs the read-only export
inside MT5's permitted file sandbox. It contains no order, position, or account
mutation calls.

1. Compile the script in MetaEditor and run it once from **Navigator → Scripts →
   GoldIntel** while the IC Markets terminal is connected.
2. Confirm `GoldIntel calendar export completed` in MT5's **Experts** tab.
3. Collect, audit, normalize, and upload the result from the repository root:

```powershell
python tools\mt5_calendar_bridge.py collect
python tools\mt5_calendar_bridge.py normalize
python tools\mt5_calendar_bridge.py upload
```

The collector rejects schema drift, duplicate conflicts, clock inconsistencies,
and an unvalidated broker timezone policy. Historical consensus in this export has
no first-observed timestamp, so it becomes eligible at the release boundary only:
it supports post-release surprise and reaction research but is prohibited as a
historical pre-release feature. Future snapshots use the actual retrieval clock.

The same intake surface accepts complete Fed-path probability distributions. For
each snapshot the engine derives next-meeting pricing, first expected move, total
easing/tightening, destination rate, and hawkish/dovish repricing across common
meetings. Probabilities must sum to 100% per meeting.

## Add the free vintage-macro feed

The rates/USD/CFTC slice needs no credential. Vintage-aware CPI, core CPI, PCE,
core PCE, GDP, retail sales, payrolls, unemployment, wages, and jobless claims use
the official ALFRED API, which requires a free FRED API key.

1. Register at <https://fred.stlouisfed.org/docs/api/api_key.html>.
2. Put the key after `FRED_API_KEY=` in the gitignored root `.env`.
3. Restart the API and sync a range that begins at least 16 months before the
   first research decision.

```powershell
docker compose up -d --build api
$vintage = @{ start = "2022-01-01"; end = "2026-07-23" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/providers/alfred/sync -ContentType application/json -Body $vintage
```

ALFRED supplies real-time dates rather than guaranteed intraday publication
timestamps. The adapter therefore delays each vintage to the following midnight
New York time. Exact 08:30 release reactions still use the separate event bundle.

## Add real market-implied Fed-path history without an API key

The Atlanta Fed publishes historical quarterly average SOFR probability
distributions estimated from CME options. This is real market-derived data, not a
synthetic fixture, and the engine labels it separately from exact meeting-by-meeting
FedWatch probabilities.

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/providers/atlanta-fed-mpt/sync
```

The official workbook currently covers 29 March 2023 through 22 July 2026. Its
embedded terms permit personal and educational use only; commercial deployment
requires separate permission or a licensed replacement. Historical rows become
eligible only at the end of the next US business day because exact historical
website publication times are unavailable.

## Add optional licensed consensus and Fed expectations

The MT5 import provides a useful historical consensus series for post-release
research. A separately timestamped institutional consensus feed and a licensed full
Fed-probability path are still not assumed to be free. The optional adapters use:

- Trading Economics Economic Calendar for US schedules, consensus, original
  releases, and prior-value revisions; and
- CME FedWatch End-of-Day API for meeting-by-meeting rate-range probabilities.

Put credentials only in the root `.env`:

```dotenv
TRADING_ECONOMICS_API_KEY=
CME_FEDWATCH_CLIENT_ID=
CME_FEDWATCH_CLIENT_SECRET=
```

Restart the API, then use the source cards on <http://localhost:3000/events> or:

```powershell
$calendar = @{ start = "2026-01-01"; end = "2026-07-23" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/providers/trading-economics/sync -ContentType application/json -Body $calendar

$fedPath = @{ start = "2026-06-01"; end = "2026-07-23" } | ConvertTo-Json
Invoke-RestMethod -Method Post -Uri http://localhost:8000/api/v1/providers/cme-fedwatch/sync -ContentType application/json -Body $fedPath
```

Historical Trading Economics consensus has the same first-publication limitation as
the MT5 archive and receives the same release-boundary treatment. Live snapshots use
the time this engine actually observed them. CME vintages use CME's documented
01:45 UTC business-day publication clock.

Run validation:

```powershell
docker compose --profile test run --rm backend-test
docker build --target test -t gold-market-intelligence-web-test ./frontend
```

## Import observed XAUUSD history from MT5

The bridge is intentionally read-only and runs on Windows, outside Docker, because
the MetaTrader Python package communicates with the local terminal. It reuses the
session already saved in MT5; no broker password belongs in this repository.

1. Keep the IC Markets MT5 terminal open and logged in.
2. In **Tools → Options → Charts**, set **Max bars in chart** high enough for
   the requested history and restart MT5. The default 100,000 bars exposes only
   about 100 calendar days of this market.
3. Install the small host-side bridge dependencies once.
4. Check the connection, then import completed one-minute bars.

```powershell
python -m pip install -r tools\requirements-mt5.txt
python tools\mt5_bridge.py status
python tools\mt5_bridge.py history --days 30
python tools\mt5_bridge.py history --after-existing
python tools\mt5_bridge.py history --days 365 --before-existing
```

The history command writes an audit CSV under `data\mt5` and uploads it through the
normal idempotent ingestion API. Long backfills are split into bounded,
non-overlapping files; `--before-existing` ends strictly before the database's
earliest stored bar, while `--after-existing` starts at the latest stored close and
appends through the current completed UTC minute without overlap. The status reports
any leading history shortfall instead of silently claiming full coverage. It does
not place or modify trades. After import,
open <http://localhost:3000/backtests>, change the experiment parameters, and press
**Run point-in-time backtest**.

Current implemented research strategy:

```text
complete Tokyo-session range
-> configurable London breakout and closed-bar acceptance
-> decision after the confirmation bar closes
-> fill at the next completed 5-minute bar open
-> ATR stop, fixed-R target, or New York time exit
```

The Backtest Lab exposes two modes with otherwise identical execution:

```text
PRICE_ONLY_CONTROL
FUNDAMENTAL_ALIGNED = same mechanical candidate
  + directional score/coverage/confidence gate
  + high-impact catalyst blackout
  + post-blackout re-evaluation
```

The first one-month diagnostic looked profitable and was correctly challenged with
the longer available sample. Across 38 mechanical candidates, the price-only
control lost 744.37 USD with -0.202 R expectancy and 12.65% drawdown. The same
fundamental gate kept 18 candidates and reduced the loss to 120.70 USD, -0.070 R,
and 6.29% drawdown. This supports the gate as a filter in this sample, but the
surviving default entry/exit is not profitable.

A provisional 2.0-ATR stop / 1.25R target produced +549.78 USD, +0.322 R
expectancy, 1.735 profit factor, and 3.94% drawdown. It remains
`RESEARCH / INSUFFICIENT EVIDENCE`: there are only 18 trades, all are shorts, and
both parametric and deterministic-bootstrap 95% intervals cross zero. The Backtest
Lab now shows those intervals and seeded trade-order Monte Carlo drawdown instead
of presenting a positive P&L as proof. Real Atlanta Fed quarterly SOFR path history
is now connected; exact meeting-date CME FedWatch, ETF, options, and intraday
cross-market evidence remain visibly separate or absent until licensed sources are
connected.

The Cross-market page is no longer a placeholder. It synchronizes the eligible
daily gold, 2Y/10Y nominal yield, 10Y real yield, breakeven, broad USD, equity, and
VIX histories while preserving each observation's `available_at` clock. It does
not relabel daily observations as intraday event confirmation.

Each run records the input-data SHA-256 hash, timing policy, session definitions,
parameters, equity curve, transaction costs, and a trade-by-trade evidence ledger.
It is research software, not an execution bot or a claim of future performance.

## cTrader status

The cTrader integration is optional for the demo slice. Put credentials only in the
gitignored root `.env`; never add them to `.env.example`. Historical development and
MT5 ingestion continue normally while a Spotware application is being reviewed. An
approved application still requires a separate read-only OAuth grant for a cTrader
trading account; an MT5 account is not exposed through the cTrader Open API.

After approval:

1. Add this exact redirect URI to the approved application:
   `http://localhost:8000/api/v1/providers/ctrader/oauth/callback`.
2. Keep `CTRADER_SCOPE=accounts`; the platform rejects trading permission.
3. Rebuild and start the API, then open
   <http://localhost:8000/api/v1/providers/ctrader/oauth/start>.
4. Sign in directly on cTrader's page, select the intended cTrader account, and
   approve view-only access.
5. Verify the secret-free result at
   <http://localhost:8000/api/v1/providers/ctrader/oauth/status>.

The callback validates a signed, short-lived browser state and immediately exchanges
the one-minute authorization code. Access and rotating refresh tokens are
authenticated-encrypted before database storage and are never returned by a health
endpoint or browser page. In production, set an independent
`PROVIDER_TOKEN_ENCRYPTION_KEY`; local development can derive isolated key material
from the application secret. Uvicorn query-string access logs are disabled because
an OAuth callback contains a short-lived code.

Do not paste a cTrader password, authorization code, access token, or refresh token
into chat or any tracked file. Account discovery through cTrader's Protobuf API is
the next adapter boundary after OAuth; until that is verified, the read-only MT5
bridge remains the active IC Markets price-data path.

## Non-negotiable product rules

- A macro bias is not a trade signal.
- Bias, trigger, invalidation, and risk are separate outputs.
- Every conclusion carries an epistemic label: `OBSERVED`, `CALCULATED`,
  `INFERRED`, or `UNKNOWN`.
- Institutional behaviour inferred from price and open interest is never presented
  as directly observed activity.
- Every result is reproducible from immutable source records, versioned rules, and
  a point-in-time cutoff.
- Historical calculations may use only information whose `available_at` timestamp
  is at or before the simulated clock.
- Missing data lowers coverage and confidence; it is never silently converted to a
  neutral observation or zero.

## Planning documents

| Document | Purpose |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | Architecture, assumptions, MVP boundaries, repository structure, and risks |
| [DATA_MODEL.md](DATA_MODEL.md) | Entity model, temporal contract, ER diagrams, and proposed schema |
| [DATA_SOURCES.md](DATA_SOURCES.md) | Phase 1 source and licensing plan |
| [SCORING_ENGINE.md](SCORING_ENGINE.md) | Transparent signal, score, confidence, and reasoning design |
| [BACKTESTING.md](BACKTESTING.md) | Point-in-time event-study and strategy-backtest design |
| [STRATEGY_RESEARCH.md](STRATEGY_RESEARCH.md) | Book-aligned strategy hypotheses and graduation protocol |
| [API_DESIGN.md](API_DESIGN.md) | Initial REST contracts and response shapes |
| [DASHBOARDS.md](DASHBOARDS.md) | Page map and wireframe descriptions |
| [MILESTONES.md](MILESTONES.md) | Incremental Phase 1 plan and exact first vertical slice |

## Default implementation choices

- Python 3.12, FastAPI, Pydantic v2, SQLAlchemy 2, and Alembic
- PostgreSQL with TimescaleDB for high-volume time-series tables
- Redis and Celery for idempotent background work
- pandas, NumPy, SciPy, and statsmodels for transparent analytics
- A custom event-driven backtester because point-in-time macro vintages and event
  availability are first-class requirements
- Next.js, React, TypeScript, Tailwind CSS, and Recharts
- Docker Compose for a credential-free demo path and optional live public adapters

The default Phase 1 dollar measure is the Federal Reserve nominal broad dollar
index, not a silently substituted or unlicensed DXY feed. Gold OHLCV enters through
a documented CSV contract first; licensed exchange or spot feeds can later implement
the same provider interface.
