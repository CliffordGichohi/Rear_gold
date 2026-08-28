# Gold Continuation True-Negation Matched-Case Attribution Audit V1

Status: `AUTHORIZED_EXPOSED_POST_RESULT_ATTRIBUTION`

Preserve every prior result, artifact and seal. Use exactly the 434 matched
`CONTINUATION_REFRESH` identities from the sealed original V2-R1 execution and
the sealed fixed-original-quantity true-negation execution. Use their existing
January-June 2022 M1 paths only. Keep every overlapping setup; impose no daily
cap, one-trade rule, wait-for-resolution rule, filter or position suppression.

This audit may explain existing results only. It may not create, alter, invert,
filter or optimize a strategy, change execution, open another date, inspect
2025/2026, or claim validation credit.

For every matched identity freeze and calculate:

1. Original-versus-negated net-result sign and execution-resolution matrices.
2. Original and negated stop attribution: stop then target, stop then entry
   reclaim, stop confirmed through the deadline, favourable excursion before
   stop, ambiguous stop-first, and structural-versus-execution disagreement.
3. Original and negated profit attribution: target-to-deadline extension,
   actual target exit versus the unchanged deadline exit, available MFE,
   realised capture, time-exit giveback, latency degradation and explicit
   spread/slippage drag.
4. Point-in-time explanatory groupings: original direction, month, context
   family, macro alignment, H1/H4 structure state and alignment, target
   timeframe, exact local-M15/HTF target-level agreement, frozen former-quality
   flags, planned-R bin, break-distance bin, decision phase, time remaining,
   pivot age, target age, and ordinal within the uninterrupted same-direction
   continuation run. Grouping is descriptive and must not suppress any setup.
5. R attribution: original R, negated R, change from negation, cost drag,
   deadline-versus-actual-exit difference, stopped-then-target opportunity and
   MFE not captured. Dollar values use each sealed original quantity; comparative
   R remains dollars divided by the unchanged $50 benchmark.

Frozen classifications:

- Result sign: `WIN` when net dollars are positive, `LOSS` when negative and
  `SCRATCH` only at absolute value no greater than `1e-12`.
- A post-exit bar starts at or after the sealed exit timestamp and before the
  sealed noon-New-York deadline.
- Stopped-trade disposition is `STOP_THEN_TARGET` if its frozen target is later
  touched, otherwise `STOP_THEN_ENTRY_RECLAIM` if entry is later revisited,
  otherwise `STOP_CONFIRMED_TO_DEADLINE`.
- Target opportunity compares the actual frozen target exit with a deterministic
  close at the final complete M1 bar before the same deadline using the existing
  spread and slippage assumptions.
- H1/H4 structure is `UP_TREND` only for HH+HL, `DOWN_TREND` only for LH+LL and
  `MIXED_OR_RANGE` otherwise.
- Macro alignment uses the sealed macro state: bullish with original LONG or
  bearish with original SHORT is `ALIGNED`; the opposite is `CONTRADICTED`; all
  neutral, conflicted or unavailable states are `NEUTRAL_OR_UNKNOWN`.
- Planned-R bins: `<0.5`, `0.5-1.0`, `1.0-1.5`, `1.5-2.0`, `>=2.0`.
- Break-distance ATR bins: `<1`, `1-2`, `2-4`, `>=4`.
- Time remaining bins: `<30m`, `30-60m`, `60-120m`, `>=120m`.
- Pivot-age bins: `<15m`, `15-30m`, `30-60m`, `>=60m`.
- Target-age bins: `<1h`, `1-4h`, `4-24h`, `>=24h`.
- New-York phases: `08:00-09:30`, `09:30-10:30`, `10:30-11:30`, and
  `11:30-12:00`, with DST resolved by `America/New_York`.
- A continuation run is the uninterrupted chronological sequence of same-day
  `CONTINUATION_REFRESH` signals retaining the same original direction; a
  direction change begins a new run. This is attribution only.

Freeze the exact matched identities, definitions, source hashes and synthetic
proof before path analysis. Run independent primary and reference calculations,
require exact row, matrix, aggregate and checksum agreement, document every
result honestly, seal the audit and stop. Acquire no data and incur no charge.
