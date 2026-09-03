# January stopped-then-direction audit

## Verdict

Of 8 stopped plans, 7 later reached the original target, 8 later reached at least +1R, and 0 never reclaimed entry before month-end.

Strict target-before-stop direction was 3/12 (25.0%). Ignoring the frozen stop, eventual original-target direction was 10/12 (83.3%).

## Stopped-plan matrix

| # | Decision UTC | Side | Reclaimed entry | Later +1R | Later +2R | Later original target | Post-stop max favourable | Classification |
|---:|---|---|---|---|---|---|---:|---|
| 1 | 2022-01-03 10:50:00 | LONG | yes | yes | yes | yes | +26.62R | EVENTUAL_ORIGINAL_TARGET |
| 2 | 2022-01-04 08:25:00 | SHORT | yes | yes | yes | yes | +13.23R | EVENTUAL_ORIGINAL_TARGET |
| 3 | 2022-01-05 04:10:00 | SHORT | yes | yes | yes | yes | +31.79R | EVENTUAL_ORIGINAL_TARGET |
| 4 | 2022-01-07 02:20:00 | SHORT | yes | yes | yes | yes | +24.35R | EVENTUAL_ORIGINAL_TARGET |
| 6 | 2022-01-13 22:55:00 | SHORT | yes | yes | yes | yes | +29.74R | EVENTUAL_ORIGINAL_TARGET |
| 7 | 2022-01-20 06:55:00 | LONG | yes | yes | yes | yes | +28.49R | EVENTUAL_ORIGINAL_TARGET |
| 10 | 2022-01-27 11:20:00 | SHORT | yes | yes | yes | yes | +41.16R | EVENTUAL_ORIGINAL_TARGET |
| 11 | 2022-01-28 14:45:00 | SHORT | yes | yes | yes | no | +4.31R | EVENTUAL_PLUS_2R_NOT_TARGET |

## Boundary

Every stopped trade remains a realised -1R under the frozen execution. A later move diagnoses entry/invalidation timing; it does not rewrite the trade as a win.
