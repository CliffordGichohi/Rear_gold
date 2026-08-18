# GC Microstructure Research — Step 3A Order-Book Reconstruction

Status: **FORMAL FAIL — 24 OF 25 FROZEN GATES PASSED**

Completion date: 2026-07-30  
Classification: **ENGINEERING_ONLY**  
Research and validation exclusion: **PERMANENT**

## Scope

Step 3A used only the sealed one-day `GC.v.0` MBO engineering sample. It:

- reconstructed the order book event by event;
- handled clear, add, cancel, modify, trade, and fill actions;
- maintained individual orders, aggregate price levels, and FIFO queues;
- examined book state only at provider `F_LAST` event boundaries;
- performed two independent full-source replays;
- compared input, state, structure, lifecycle, and checkpoint hashes; and
- calculated technical book-health statistics only.

It did not acquire data or calculate directional relationships, features,
signals, outcomes, entries, exits, PnL, R multiples, or returns.

## Frozen provider semantics

The protocol was frozen before replay using Databento's documented rules:

- `A` adds an order.
- `C` subtracts the cancelled size and removes an order at zero.
- `M` changes price and/or size; a missing order is treated as an add.
- `R` clears the instrument's resting book.
- `T` and `F` do not directly mutate the book because accompanying cancel
  records update resting state.
- A price-changing or size-increasing modification loses queue priority.
- The book is examined only after `F_LAST`.
- A historical UTC-day snapshot begins with `R`, continues with `A`, and ends
  with `F_LAST`.

Protocol:

`research_manifests/gc_microstructure_step_3a_protocol_v01.json`

## Replay coverage

- Source records processed per replay: 2,322,905
- Event boundaries examined: 2,062,923
- Checkpoints compared: 11
- Snapshot records: 2,744
- Snapshot reset records: 1
- Snapshot add records: 2,743
- Snapshot-restored orders: 2,743
- Snapshot-restored price levels: 964
- Snapshot recovery: **PASS**

Technical action counts:

| Action | Records |
|---|---:|
| Add | 951,416 |
| Cancel | 948,472 |
| Modify | 222,863 |
| Fill | 125,625 |
| Trade | 74,528 |
| Clear | 1 |

## Independent reconstruction result

The primary implementation used:

- an order-ID map;
- explicit ask and bid price-level maps;
- aggregate level depth;
- insertion-ordered level queues; and
- lazy best-price heaps.

The independent reference implementation used:

- a separate order-only map;
- explicit priority ordinals; and
- level and queue reconstruction only at checkpoints.

Both implementations independently reread the complete Parquet source.

Results:

- Input stream hashes match: **PASS**
- All checkpoint state hashes match: **PASS**
- All checkpoint structure hashes match: **PASS**
- Final order-state hashes match: **PASS**
- Final level-and-queue hashes match: **PASS**
- Lifecycle counters match: **PASS**
- Final structural invariants: **PASS**

Input stream hash:

`cc090b6c6b64c580f3a374ffafdc1410b5526c866c069884f0f568767e53af6b`

Final state hash:

`126dde879acec948c2a19625bef18f3dcb3beb156ddec37eeb86acc3937eef0c`

Final structure hash:

`9d64e788c157bb7e8b988d4099b40110f4b4d5070e479f956e918237fe515caf`

## Lifecycle and integrity findings

The following all recorded zero violations:

- receive-timestamp regressions;
- live event-timestamp regressions;
- live sequence regressions;
- invalid actions;
- invalid sides;
- duplicate adds;
- orphan cancels;
- modifies without prior orders;
- oversized cancels;
- cancel-side mismatches;
- cancel-price mismatches;
- modify-side mismatches;
- nonpositive resting orders;
- inconsistent or negative level depth;
- queue-location inconsistencies;
- queue-priority inconsistencies;
- empty-side event boundaries;
- provider `F_MAYBE_BAD_BOOK` flags; and
- heap-versus-direct best-price disagreements.

Observed orphan-event rate: **0.000000%**

## Sole failed gate

The frozen protocol required zero locked or crossed books at every `F_LAST`
boundary.

Observed:

- Locked boundaries: 15
- Crossed boundaries: 24
- Total: 39 of 2,062,923 boundaries
- Rate: approximately 0.001891%

All 39 formed one contiguous episode:

- Start: `2024-01-09T22:58:46.958110838Z`
- End: `2024-01-09T22:59:59.992618042Z`
- Duration: 73.034507204 seconds
- Episode count: 1
- Heap/direct classification disagreements: 0
- Structural invariant violations: 0

The episode falls entirely in the documented Monday-through-Thursday Globex
pre-open window immediately before the 23:00 UTC open in January. During
pre-open the engine accepts and maintains orders without continuous matching,
so a locked or crossed resting book is not proof of reconstruction failure.

This is a technical interpretation supported by:

- Databento's per-instrument `F_LAST` and CME MDP 3.0 normalization:
  `https://databento.com/docs/knowledge-base/datasets/glbx-mdp3`
- Databento's order-management rules:
  `https://databento.com/docs/examples/order-book/order-tracking`
- CME's documented Monday-through-Thursday 4:45–5:00 p.m. CT pre-open:
  `https://www.cmegroup.com/content/dam/cmegroup/notices/ser/2026/06/ser-9766.pdf`

## Honest verdict

The reconstruction implementations are deterministic and internally
consistent. Every lifecycle, snapshot, depth, queue, timestamp, and independent
replay check passed.

However, the overall frozen Step 3A protocol is formally **FAIL**, because its
all-hours uncrossed-book gate did not distinguish continuous matching from
pre-open. The gate was not changed after seeing the result.

This failure does not demonstrate bad source data or a defective reconstructor.
It demonstrates that market trading status is required before applying the
uncrossed-book invariant.

## Seals

Step 3A manifest hash:

`0897e33856c5329ee59040ff5a6c15f48cb65fc17dcf3e63ec1f8c5bf3c6c59c`

Boundary diagnostic hash:

`62759b8d90f44f5875fe8fd7546fb61bc2f170555f1f3575e43e2271c06e33a0`

The Step 3A artifact seal independently verified all three replay artifacts.

## Required future decision

Step 3B has not started.

Before Step 3B, a prospective amendment would need to preserve this formal
failure and restrict the uncrossed-book invariant to continuous-matching
states, identified from a frozen point-in-time session/status policy. The
reconstruction algorithms and every other gate would remain unchanged.
