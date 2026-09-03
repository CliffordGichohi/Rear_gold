# Gold January H1 probe-confirm-reclaim milestone V1

**Verdict:** `REJECT_EXPOSED_MATCHED_GROSS_IMPROVEMENT`

## Matched exposed-January comparison

| System | Cases | Wins | Win rate | Net R | PF | Expectancy | Max DD | $ at $50/R |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| Original control | 88 | 38 | 43.2% | +11.47 | 1.229 | +0.130 | 14.00 | +573.44 |
| Probe-confirm-reclaim | 88 | 44 | 50.0% | +12.00 | 1.405 | +0.136 | 9.38 | +599.98 |

Increment versus matched control: **+0.53R**.
Baseline winner R retained: **35.41/61.47R (57.6%)**.

## Route counts

| Route | Cases |
|---|---:|
| CONFIRMED_ADDITION_STOP | 22 |
| CONFIRMED_ADDITION_TARGET | 32 |
| PROBE_ONLY_TARGET | 6 |
| PROBE_STOP_H1_CLOSE_INVALIDATED | 11 |
| PROBE_STOP_LATER_H1_INVALIDATED | 6 |
| RECOVERY_STOP | 3 |
| RECOVERY_TARGET | 7 |
| RECOVERY_TIME_EXIT | 1 |

The comparison is gross, matched-population and exposed. Costs, overlap and whole-ounce sizing remain outside both sides of this isolated test.
No threshold or alternative implementation was tested after outcomes were opened.
