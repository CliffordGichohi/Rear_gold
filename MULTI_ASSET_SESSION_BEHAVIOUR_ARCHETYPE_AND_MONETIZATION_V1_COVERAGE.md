# Multi-Asset Session Behaviour V1 — Metadata-Only Coverage Audit

Verdict: **`FAIL_M1_SESSION_UNIT_COVERAGE`**

No OHLC, spread value, volume value, direction, return, excursion, relationship, hypothetical return, trade, PnL, or 2025/2026 market value was accessed. Only sealed source metadata and the `open_time` column for development files were used.

## Timestamp source inventory

| Instrument | Unique development M1 timestamps |
|---|---:|
| EURUSD | 1,274,793 |
| US500 | 1,202,006 |
| USDJPY | 1,274,223 |
| NAS100 | 1,210,217 |
| XAGUSD | 1,210,606 |
| WTI | 1,206,576 |

## Frozen session identity coverage

| Instrument | Session | Expected weekday identities | Complete eligible paths | Complete fraction | Unit gate |
|---|---|---:|---:|---:|---|
| EURUSD | `ASIA_SESSION` | 892 | 282 | 31.61% | FAIL |
| EURUSD | `LONDON_SESSION` | 892 | 872 | 97.76% | PASS |
| EURUSD | `NEW_YORK_SESSION` | 892 | 877 | 98.32% | PASS |
| US500 | `LONDON_SESSION` | 892 | 498 | 55.83% | FAIL |
| US500 | `US_CASH_SESSION` | 892 | 824 | 92.38% | PASS |
| USDJPY | `ASIA_SESSION` | 892 | 250 | 28.03% | FAIL |
| USDJPY | `LONDON_SESSION` | 892 | 872 | 97.76% | PASS |
| USDJPY | `NEW_YORK_SESSION` | 892 | 876 | 98.21% | PASS |
| NAS100 | `LONDON_SESSION` | 892 | 871 | 97.65% | PASS |
| NAS100 | `US_CASH_SESSION` | 892 | 850 | 95.29% | PASS |
| XAGUSD | `ASIA_SESSION` | 892 | 0 | 0.00% | FAIL |
| XAGUSD | `LONDON_SESSION` | 892 | 823 | 92.26% | PASS |
| XAGUSD | `NEW_YORK_SESSION` | 892 | 869 | 97.42% | PASS |
| WTI | `LONDON_SESSION` | 892 | 606 | 67.94% | FAIL |
| WTI | `US_ENERGY_SESSION` | 892 | 865 | 96.97% | PASS |

Every expected identity remains recorded. A session is complete only when every exact M1 timestamp from `decision + 1 minute` through the frozen session end is present. Partial sessions and zero-timestamp dates are not deleted or automatically labelled holidays.

Primary and reference coverage checksum: `1f13bd102c14d21f7a64723c294bb6438544ac58d3dc623491edfe503cedd71a`  
Exact reproduction: **true**

## Context-source disposition

The existing sealed macro inventory is reused without value access. Missing or partial sources—including exact meeting probabilities, complete historical consensus, non-gold COT, options/gamma, ETF/central-bank flows, Japan/euro differential curves, EIA inventories, and unscheduled news—remain explicit `UNKNOWN` or partial fields.

## Boundary

This audit certifies that the six-market development census is technically ready for a separately authorized Milestone 2. It does not calculate a single behaviour, archetype, relationship, hypothetical return, signal, or trade, and does not authorize Milestone 2.
