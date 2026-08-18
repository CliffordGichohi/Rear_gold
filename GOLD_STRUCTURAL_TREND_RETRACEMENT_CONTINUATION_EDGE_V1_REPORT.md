# Gold Structural Trend-Retracement Continuation Edge Discovery V1 — Final Report

Status: **REJECT_NO_ECONOMICALLY_TRADABLE_CANDIDATE**

## Verdict

No frozen trend-retracement setup passed. All setup populations were below the support floor; descriptive performance is reported but cannot establish an edge.

## Development results

| Test | Signals | Trades | Win rate | Gross exp. | Net exp. | PF | 95% CI | Verdict |
|---|---:|---:|---:|---:|---:|---:|---|---|
| LONDON|STRC_BREAK_LEVEL_RETEST_REJECTION | 9 | 0 | None% | None | None | None | [None, None] | SUPPORT_FAIL |
| LONDON|STRC_IMPULSE_ZONE_INTERNAL_BOS | 11 | 0 | None% | None | None | None | [None, None] | SUPPORT_FAIL |
| LONDON|STRC_ASIA_SWEEP_CONTINUATION | 11 | 3 | 33.333333333333% | 0.333333333333 | 0.159995418565 | 1.205493124784 | [-1.185052119733, 2.815763942652] | SUPPORT_FAIL |
| NEW_YORK|STRC_BREAK_LEVEL_RETEST_REJECTION | 9 | 1 | 0.0% | -1.0 | -1.178407052772 | 0.0 | [-1.178407052772, -1.178407052772] | SUPPORT_FAIL |
| NEW_YORK|STRC_IMPULSE_ZONE_INTERNAL_BOS | 10 | 4 | 25.0% | -0.230992672362 | -0.383135255045 | 0.556601293014 | [-1.164029771587, 1.156967469451] | SUPPORT_FAIL |
| NEW_YORK|STRC_ASIA_SWEEP_CONTINUATION | 9 | 1 | 100.0% | 1.973106290966 | 1.814311777823 | None | [1.814311777823, 1.814311777823] | SUPPORT_FAIL |

## Portfolio diagnostics

| Session | Trades | Net expectancy | PF | Net PnL | Max DD |
|---|---:|---:|---:|---:|---:|
| LONDON|EARLIEST_FROZEN_SETUP | 3 | 0.159995418565 | 1.205493124784 | $21.882599999999 | 0.57186675% |
| NEW_YORK|EARLIEST_FROZEN_SETUP | 4 | 0.354645732994 | 1.611580054955 | $68.0766 | 0.568330216139% |

## Integrity

Primary/reference trade paths and statistics reproduced exactly. Outcomes were opened once. No 2025/2026 values or paid data were accessed. Only frozen development candidates could advance; zero candidates left the exposed periods closed.
