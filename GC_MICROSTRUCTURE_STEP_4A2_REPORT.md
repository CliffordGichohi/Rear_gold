# GC Microstructure Step 4A.2 — Final Metadata Disposition

## Formal status

`PASS_DISPOSITION_REPRODUCTION`

## Crossed bucket-close classification

- Total crossed bucket closes: 60.
- Continuous crossed bucket closes: 0.

### By segment

- CONTINUOUS_00_22: 0 crossed of 79,200.
- CONTINUOUS_23_24: 0 crossed of 3,600.
- MAINTENANCE_22_2245: 0 crossed of 2,700.
- PRE_OPEN_2245_23: 60 crossed of 900.

### By market state

- CONTINUOUS_MATCHING: 0 crossed of 82,800.
- MAINTENANCE: 0 crossed of 2,700.
- PRE_OPEN: 60 crossed of 900.

## Finding

`CONTINUOUS_BUCKET_CLOSE_STATES_CLEAN`

## Binary recommendation

`RECERTIFY_WITH_SNAPSHOT_EXCEPTION_AND_CONTINUOUS_BUCKET_CLOSE_GATE_V0_1`

In a separately authorized amendment, permit BAD_TS_RECV only for rows satisfying the Step 4A.1 confirmed snapshot semantics; apply the crossed-book integrity gate only to CONTINUOUS_MATCHING one-second bucket-close states; report PRE_OPEN and MAINTENANCE crossed states separately without treating them as continuous-state failures; keep every other Step 4A definition and gate unchanged.

The recommendation was not implemented.

## Restrictions honored

Only the seven frozen metadata/classification columns were read. No source MBO/MBP rows, raw state ordinals, market values, other feature values, outcomes, signals, execution, trades, or PnL were accessed or reported.
