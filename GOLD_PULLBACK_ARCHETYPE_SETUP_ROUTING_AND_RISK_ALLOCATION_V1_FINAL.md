# Gold Pullback Archetype Setup Routing and Risk Allocation V1 — Final

Final status: **REJECT_NOT_ECONOMICALLY_TRADABLE**

The corrected 2021–2024 development system was frozen before the single 2025/2026 application. Both later periods are exposed historical robustness evidence and receive no independent-validation credit.

## Corrected development result

| Trades | Win rate | Expectancy | PF | Net PnL | Max DD | 95% CI |
|---:|---:|---:|---:|---:|---:|---|
| 450 | 35.555555555556% | -0.167502137565R | 0.757873724133 | $-1644.931589589985 | 17.2689766127% | [-0.28806500197364837, -0.04705056544555865] |

## Frozen router — exposed robustness

| Segment | Trades | Win rate | Expectancy | PF | Net PnL | Return | Max DD | 1.5x costs |
|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 2025 | 169 | 43.195266272189% | 0.099295427981R | 1.176019644708 | $397.457268179866 | 3.974572681799% | 2.395427649053% | 0.069813435823R |
| 2026_YTD | 104 | 35.576923076923% | -0.105353747148R | 0.85518162642 | $-254.06021428015 | -2.540602142801% | 3.44310657123% | -0.1201568717R |
| combined | 273 | 40.29304029304% | 0.021333837455R | 1.034060405016 | $143.397053899716 | 1.433970538997% | 3.343144121369% | -0.002556205138R |

## All-model equal-risk comparison

| Segment | Trades | Win rate | Expectancy | PF | Net PnL |
|---|---:|---:|---:|---:|---:|
| 2025 | 1940 | 39.278350515464% | -0.095956512533R | 0.845721709168 | $-5482.86119429992 |
| 2026_YTD | 1250 | 39.76% | -0.004484711859R | 0.992185977622 | $-308.472322730201 |
| combined | 3190 | 39.467084639498% | -0.060113330451R | 0.900333736441 | $-5791.33351703012 |

## Interpretation

The six archetypes are useful descriptions of realised paths, but the frozen point-in-time routing and risk schedule did not convert them into an economically tradable portfolio. Risk variation reduced exposure; it did not reverse negative conditional expectancy.

No paid data was acquired, no rule was retuned after development, and no live trading is authorized.
