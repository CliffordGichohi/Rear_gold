# Gold Auction Family Router V1-R1 Mechanical Correction — Result

Verdict: `PASS_MECHANICAL_CORRECTION_REPRODUCTION_ZERO_VALIDATION_CREDIT`

This is a reproducible exposed-data implementation correction with zero validation credit.

| Period | Router V1 R | Before overlay R | Corrected trades | Corrected R | Win % | PF | DD R |
|---|---:|---:|---:|---:|---:|---:|---:|
| JANUARY | +2.3686 | +2.3686 | 5 | +2.3686 | 40.00 | 3.4599426374090534 | 0.9629 |
| FEBRUARY_TO_DATE | +4.7773 | +7.0023 | 4 | +7.0023 | 100.00 | None | 0.0000 |
| MARCH | +3.5321 | +1.5915 | 7 | +1.5915 | 42.86 | 1.5442873890051805 | 1.9560 |
| APRIL | +1.8220 | +2.5030 | 5 | +2.5030 | 60.00 | 7.263763763764076 | 0.3996 |
| MAY | -3.7159 | -3.7159 | 7 | -2.6755 | 28.57 | 0.3016711930208354 | 3.3361 |
| COMBINED | +8.7841 | +9.7495 | 28 | +10.7899 | 50.00 | 2.3291509299680873 | 3.3361 |

## Exact attribution

- Removing the harmful overlay: +0.965396R.
- Enforcing delayed actual-fill room: +1.040400R.
- Total correction versus Router V1: +2.005796R.
- Corrected exposed result: +10.789857R / $+539.49.
- Delayed trades rejected by the room gate: 1.

No new market data or fresh date was opened. This result proves reproduction only; forward evidence is still required.
