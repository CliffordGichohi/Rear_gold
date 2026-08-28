# Gold Coherent-Auction Consecutive Calendar-Month Test V1 — Amendment A

Status: `FROZEN_AFTER_METADATA_COVERAGE_STOP_BEFORE_INFERENCE`

The first run stopped before stream persistence, inference or PnL because the
implementation used an unstated 95% per-session minute-coverage threshold and
`2022-05-16` contained 217 of 240 expected London-session minute closes
(`90.42%`).

This amendment changes only that technical readiness threshold:

- use the previously established outcome-blind observed-quote-path floor of
  90% for each London and New York session window;
- retain all 65 frozen dates, including `2022-05-16`;
- preserve every missing timestamp and use no imputation, alternate provider,
  refresh, deletion or date substitution;
- stop if any frozen date has less than 90% coverage in either session;
- leave the translator, feature definitions, missing-value behaviour, first
  signal policy, admission rules, geometry, execution and reporting unchanged.

The failed 95% readiness attempt retains no performance result because no
inference or PnL was calculated.
