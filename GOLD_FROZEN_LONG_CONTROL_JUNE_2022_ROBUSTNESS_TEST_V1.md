# Gold Frozen LONG Control — June 2022 Robustness Test V1

Status: authorized one-month chronological robustness test.

## Objective

Apply the currently preserved frozen LONG control once and unchanged to the next complete chronological month, calendar June 2022.

## Frozen policy

- Policy: the sealed `GOLD_AUCTION_FAMILY_ROUTER_V1_R1` mechanical correction that produced the preserved `FROZEN_LONG_CONTROL` result.
- Direction: LONG only.
- Scan: the existing chronological daily scan and existing London/New York session treatment.
- Opportunity policy: the existing first signal/one-decision-per-day policy.
- Execution: existing family routing, entry, structural stop, absolute liquidity target, deadline, spread, slippage, latency, quantity and transaction-cost conventions.
- Risk: $50 maximum planned risk per admitted trade on a $10,000 starting account.
- Management: the existing frozen control management.

The rejected multi-opportunity mechanism and rejected M5 structural-management overlay are prohibited.

## Population

- Include every weekday from 2022-06-01 through 2022-06-30, in chronological order.
- Require at least 90% M1 coverage in each frozen London and New York four-hour session window for every day.
- Do not remove a day based on signals, trades, returns, volatility or outcome.
- Stop on a coverage or lineage failure; do not replace, impute or retune.

## Evaluation

Run independent primary and reference source readers and require identical stream bytes, base inferences, policy decisions, executions and results. Report every day, including `NO_SIGNAL` and `NO_TRADE` days.

Report trades, wins, losses, scratches, win rate, net R, net dollars, expectancy, profit factor, maximum drawdown, stressed-cost net R, sessions, families and chronological account equity.

The fixed month-level robustness gates are:

- net R greater than zero;
- positive net R at 1.5x transaction costs;
- profit factor at least 1.10; and
- exact primary/reference reproduction.

Passing is exposed historical robustness evidence only, not independent validation. No rule may be changed after June values are opened. Do not access July 2022, 2025 or 2026, acquire data, incur a charge, test SHORT, or run another candidate.
