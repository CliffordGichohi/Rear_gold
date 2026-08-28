# Gold Auction-Semantic Family Router V2 — Implementation-Failure Diagnostic

Status: `FAIL_SEMANTIC_INTEGRATION_NOT_STRATEGY_REJECTION`

This append-only diagnostic does not alter Router V2, its sealed result, or any
predecessor. Router V2 remains a reproducible record of a failed implementation.
Its `-1.069473R` result is not admissible as a rejection of the auction idea.

## Confirmed implementation defects

### 1. Incompatible signal and trigger lifecycles were combined

Router V2 reused the legacy control signal timestamp, compiled a new semantic
plan at that timestamp, selected `entry_refinement` ahead of
`execution_anchor`, and then often demanded another retest.

The semantic detector's own invariant requires the plan's execution anchor to
be the current checkpoint. In the 38 legacy-admitted signals:

- only 3 execution anchors were current at the legacy signal;
- 35 execution anchors were already stale;
- all 38 routes selected an M5 refinement;
- in 17 cases that selected layer did not match the preserved execution anchor
  by timeframe and break timestamp.

This was not a fair implementation of either lifecycle. It superimposed the
new semantic trigger lifecycle on an already-formed legacy signal.

The trigger-route dispositions rejected seven valid control winners carrying
`+7.495149R` in the exposed control ledger.

### 2. Liquidity engagement was treated as target consumption

For delayed routes, Router V2 reused a fixed-price first-passage helper that
cancels the setup as soon as the target price is touched. All ten
`ORIGINAL_TARGET_TOUCHED_PRE_ENTRY` cases used H1 destinations classified by
the compiler as `REACTIVATED_REVERSE`, an active liquidity state.

The sealed liquidity state machine distinguishes:

- touch/engagement: `ACTIVE_ENGAGED`;
- sustained acceptance through the level: `CONSUMED_ACCEPTED`;
- later reverse acceptance: `REACTIVATED_REVERSE`.

A touch alone therefore cannot be used as proof that liquidity was consumed.
This also conflicts with the Reference Book's acceptance/rejection distinction.

### 3. The compiler collapsed destination hierarchy into one fixed price

The compiler selects the nearest eligible H1 level whenever any H1 candidate
exists, otherwise H4, and Router V2 treats that one level as the final target.
It does not distinguish internal liquidity, partial-realization liquidity, and
the governing external destination. It also does not refresh the destination
lifecycle at a delayed entry checkpoint.

Consequently:

- ten routes were cancelled by raw target touch;
- eight routes failed the 1.5R room gate against that fixed destination;
- seven of those eight used `REACTIVATED_REVERSE` H1 levels and one used an
  `ACTIVE_UNTOUCHED` H1 level.

Together, target-touch and target-room dispositions rejected nine valid
control winners carrying `+12.159935R`.

### 4. The downstream management result is not a strategy test

Only two of 38 legacy-admitted signals reached execution. Structural
management therefore received no representative opportunity to demonstrate
or falsify its value. The `-1.069473R` terminal result is dominated by upstream
semantic routing failures.

## Correct disposition

- Preserve the sealed Router V2 run as `FAIL_SEMANTIC_INTEGRATION`.
- Do not label the auction strategy, the family-router hypothesis, or gold as
  rejected from this run.
- Retain the last correctly integrated control and Router V1 as rollback
  baselines.
- Permit no fresh-period or forward-test use until the correction reproduces
  the exposed operating lifecycle without semantic mismatches.

## Bounded correction order

1. Use one signal lifecycle only. For the existing exposed regression, the
   frozen legacy signal is the decision/entry anchor; an optional historical
   M5 refinement must not create a second mandatory trigger.
2. Restore the already-defined family routing around that anchor: continuation
   direct, structural repair confirmed, and range rotation confirmed at its
   named boundary.
3. Re-evaluate liquidity state at a delayed confirmation. Treat a touch as
   engagement; cancel or advance the destination only after causal acceptance
   establishes consumption.
4. Represent internal/partial and external/final destinations separately, and
   calculate the actual-fill room gate against the governing final destination.
5. Keep the known harmful extra +1R full-position break-even overlay removed.
6. Run only the same exposed regression first. This is an implementation
   certification and receives zero validation credit.

