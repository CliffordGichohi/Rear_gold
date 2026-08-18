# Multi-Asset Session Behaviour V1 — Milestone 1-R2

Verdict: **`PASS_M1_R2_BRANCH_READY`**

| Instrument-session unit | Eligible | Expected | Fraction | Disposition |
|---|---:|---:|---:|---|
| `EURUSD|ASIA_SESSION` | 301 | 892 | 33.74% | UNAVAILABLE |
| `EURUSD|LONDON_SESSION` | 875 | 892 | 98.09% | PASS |
| `EURUSD|NEW_YORK_SESSION` | 877 | 892 | 98.32% | PASS |
| `US500|LONDON_SESSION` | 845 | 892 | 94.73% | PASS |
| `US500|US_CASH_SESSION` | 853 | 892 | 95.63% | PASS |
| `USDJPY|ASIA_SESSION` | 255 | 892 | 28.59% | UNAVAILABLE |
| `USDJPY|LONDON_SESSION` | 876 | 892 | 98.21% | PASS |
| `USDJPY|NEW_YORK_SESSION` | 876 | 892 | 98.21% | PASS |
| `USTEC|LONDON_SESSION` | 872 | 892 | 97.76% | PASS |
| `USTEC|US_CASH_SESSION` | 852 | 892 | 95.52% | PASS |
| `XAGUSD|ASIA_SESSION` | 0 | 892 | 0.00% | UNAVAILABLE |
| `XAGUSD|LONDON_SESSION` | 868 | 892 | 97.31% | PASS |
| `XAGUSD|NEW_YORK_SESSION` | 871 | 892 | 97.65% | PASS |
| `XTIUSD|LONDON_SESSION` | 857 | 892 | 96.08% | PASS |
| `XTIUSD|US_ENERGY_SESSION` | 866 | 892 | 97.09% | PASS |

Passing units: **12/15**. Eligible instruments: **6/6**.

Every identity remains in the ledger. Failed units are retained as `TECHNICALLY_UNAVAILABLE`; nothing was deleted, imputed or replaced. The original Milestone 1 failure and R1 diagnostic verdict remain preserved.
