# Entry models, zone formation and pre-fill condition

1512 original trades, January2023-August2026. Original R=$50 planned risk. No trading rules, risk or execution changed. No filtered strategy, hypothetical savings or changed equity curve.
SUPPORT and BOX are different GJ zone models. UJ has a W structure, not a GJ parent zone. All history exposed; association is not causal or independent validation.

| Original route | Trades | Win % net | Mean R | Original R | PF | SL no observed +.5R close | SL after +.5R close |
|---|---:|---:|---:|---:|---:|---:|---:|
|USDJPY/W|393|23.4097|0.14916|58.62|1.273525|153|47|
|GBPJPY/DEMAND_W|897|38.2386|0.167959|150.659091|1.273512|315|212|
|GBPJPY/RESPONSE_MARKET|222|44.5946|0.374652|83.172727|1.70196|69|41|

## New predefined comparisons

| Route | Condition | True n / mean R / total R | False n / mean R / total R | Difference95 interval | Weaker years | Holm tail | Association |
|---|---|---:|---:|---|---:|---:|---|
|USDJPY/W|weaker_second_w_rebound|110 / 0.010485 / 1.153333|283 / 0.203062 / 57.466667|[-0.548447, 0.157992]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/DEMAND_W|weak_zone_departure|427 / 0.233851 / 99.854545|430 / 0.076406 / 32.854545|[-0.080563, 0.391662]|1|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/DEMAND_W|inefficient_formation|72 / 0.265025 / 19.081818|821 / 0.15346 / 125.990909|[-0.281065, 0.511329]|1|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/DEMAND_W|zone_age_ge_24h|74 / 0.214435 / 15.868182|823 / 0.16378 / 134.790909|[-0.352807, 0.476639]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/DEMAND_W|repeated_completed_revisits|254 / 0.283518 / 72.013636|462 / 0.083904 / 38.763636|[-0.102025, 0.481661]|0|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/DEMAND_W|deep_current_pullback|361 / 0.166784 / 60.209091|536 / 0.16875 / 90.45|[-0.193062, 0.174853]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/DEMAND_W|fill_over_1r_above_zone|37 / 0.197912 / 7.322727|860 / 0.16667 / 143.336364|[-0.552947, 0.675123]|3|1.0|SUPPORT_FAIL|
|GBPJPY/DEMAND_W|weaker_second_w_rebound|310 / 0.177654 / 55.072727|587 / 0.162839 / 95.586364|[-0.150959, 0.17705]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/RESPONSE_MARKET|weak_zone_departure|121 / 0.295342 / 35.736364|98 / 0.515909 / 50.559091|[-0.653696, 0.245905]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/RESPONSE_MARKET|inefficient_formation|212 / 0.342474 / 72.604545|10 / 1.056818 / 10.568182|[-1.846314, 0.620726]|2|1.0|SUPPORT_FAIL|
|GBPJPY/RESPONSE_MARKET|zone_age_ge_24h|5 / -0.252727 / -1.263636|217 / 0.389108 / 84.436364|[-1.396246, 0.027419]|2|0.823121|SUPPORT_FAIL|
|GBPJPY/RESPONSE_MARKET|repeated_completed_revisits|84 / 0.42803 / 35.954545|126 / 0.350036 / 44.104545|[-0.293637, 0.462547]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/RESPONSE_MARKET|deep_current_pullback|44 / 0.458574 / 20.177273|178 / 0.353907 / 62.995455|[-0.576632, 0.745773]|2|1.0|NOT_ESTABLISHED_AS_STABLE_ASSOCIATION|
|GBPJPY/RESPONSE_MARKET|fill_over_1r_above_zone|0 / None / 0.0|222 / 0.374652 / 83.172727|None|0|None|SUPPORT_FAIL|

## USDJPY/W: winning and losing-sequence controls

| Condition | Streak SL true/known | Winners true/known | Recovery winners true/known |
|---|---:|---:|---:|
|weaker_second_w_rebound|34/105 (0 unknown)|22/92 (0 unknown)|4/26 (0 unknown)|

| Fill / stop geometry | n | Original R | Winners |
|---|---:|---:|---:|
|fill_location: NO_PARENT_ZONE|393|58.62|92|
|stop_location: NO_PARENT_ZONE|393|58.62|92|

## GBPJPY/DEMAND_W: winning and losing-sequence controls

| Condition | Streak SL true/known | Winners true/known | Recovery winners true/known |
|---|---:|---:|---:|
|weak_zone_departure|206/430 (17 unknown)|171/327 (16 unknown)|40/78 (5 unknown)|
|inefficient_formation|34/446 (1 unknown)|29/340 (3 unknown)|8/81 (2 unknown)|
|zone_age_ge_24h|39/447 (0 unknown)|29/343 (0 unknown)|11/83 (0 unknown)|
|repeated_completed_revisits|117/351 (96 unknown)|107/274 (69 unknown)|37/59 (24 unknown)|
|deep_current_pullback|182/447 (0 unknown)|140/343 (0 unknown)|44/83 (0 unknown)|
|fill_over_1r_above_zone|16/447 (0 unknown)|16/343 (0 unknown)|3/83 (0 unknown)|
|weaker_second_w_rebound|154/447 (0 unknown)|117/343 (0 unknown)|27/83 (0 unknown)|

| Fill / stop geometry | n | Original R | Winners |
|---|---:|---:|---:|
|fill_location: ABOVE_GT_1R|37|7.322727|16|
|fill_location: ABOVE_LE_1R|425|51.395455|156|
|fill_location: INSIDE_ZONE|435|91.940909|171|
|stop_location: AT_OR_ABOVE_TOP|37|7.322727|16|
|stop_location: BELOW_OR_AT_FLOOR|525|91.418182|209|
|stop_location: INSIDE_ZONE|335|51.918182|118|

## GBPJPY/RESPONSE_MARKET: winning and losing-sequence controls

| Condition | Streak SL true/known | Winners true/known | Recovery winners true/known |
|---|---:|---:|---:|
|weak_zone_departure|45/79 (1 unknown)|49/99 (0 unknown)|5/7 (0 unknown)|
|inefficient_formation|77/80 (0 unknown)|93/99 (0 unknown)|6/7 (0 unknown)|
|zone_age_ge_24h|2/80 (0 unknown)|3/99 (0 unknown)|0/7 (0 unknown)|
|repeated_completed_revisits|29/76 (4 unknown)|38/92 (7 unknown)|2/6 (1 unknown)|
|deep_current_pullback|16/80 (0 unknown)|22/99 (0 unknown)|1/7 (0 unknown)|
|fill_over_1r_above_zone|0/80 (0 unknown)|0/99 (0 unknown)|0/7 (0 unknown)|

| Fill / stop geometry | n | Original R | Winners |
|---|---:|---:|---:|
|fill_location: ABOVE_LE_1R|190|86.05|86|
|fill_location: INSIDE_ZONE|32|-2.877273|13|
|stop_location: INSIDE_ZONE|222|83.172727|99|

## Complete descriptive formation x trigger x location matrix

Every cell retained, including zero and sparse cells. True means weaker formation/trigger under the recorded definition, not a proven bad setup. No matrix cell is a candidate.

| Route | Formation flag | Weak trigger | Fill location | n | Original R | Win % | Mean R |
|---|---|---|---|---:|---:|---:|---:|
|USDJPY/W|True|True|NO_PARENT_ZONE|65|0.133333|20.0|0.002051|
|USDJPY/W|True|False|NO_PARENT_ZONE|45|1.02|20.0|0.022667|
|USDJPY/W|True|None|NO_PARENT_ZONE|0|0.0|None|None|
|USDJPY/W|False|True|NO_PARENT_ZONE|107|34.406667|28.0374|0.321558|
|USDJPY/W|False|False|NO_PARENT_ZONE|176|23.06|22.7273|0.131023|
|USDJPY/W|False|None|NO_PARENT_ZONE|0|0.0|None|None|
|USDJPY/W|None|True|NO_PARENT_ZONE|0|0.0|None|None|
|USDJPY/W|None|False|NO_PARENT_ZONE|0|0.0|None|None|
|USDJPY/W|None|None|NO_PARENT_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|True|True|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|True|True|INSIDE_ZONE|86|21.090909|40.6977|0.245243|
|GBPJPY/DEMAND_W|True|True|ABOVE_LE_1R|92|31.968182|42.3913|0.34748|
|GBPJPY/DEMAND_W|True|True|ABOVE_GT_1R|7|2.822727|42.8571|0.403247|
|GBPJPY/DEMAND_W|True|False|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|True|False|INSIDE_ZONE|108|22.831818|37.963|0.211406|
|GBPJPY/DEMAND_W|True|False|ABOVE_LE_1R|125|18.331818|38.4|0.146655|
|GBPJPY/DEMAND_W|True|False|ABOVE_GT_1R|9|2.809091|55.5556|0.312121|
|GBPJPY/DEMAND_W|True|None|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|True|None|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|True|None|ABOVE_LE_1R|0|0.0|None|None|
|GBPJPY/DEMAND_W|True|None|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/DEMAND_W|False|True|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|False|True|INSIDE_ZONE|100|1.013636|34.0|0.010136|
|GBPJPY/DEMAND_W|False|True|ABOVE_LE_1R|89|-2.040909|31.4607|-0.022932|
|GBPJPY/DEMAND_W|False|True|ABOVE_GT_1R|7|-2.531818|14.2857|-0.361688|
|GBPJPY/DEMAND_W|False|False|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|False|False|INSIDE_ZONE|117|23.722727|41.0256|0.202758|
|GBPJPY/DEMAND_W|False|False|ABOVE_LE_1R|104|7.436364|36.5385|0.071503|
|GBPJPY/DEMAND_W|False|False|ABOVE_GT_1R|13|5.254545|53.8462|0.404196|
|GBPJPY/DEMAND_W|False|None|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|False|None|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|False|None|ABOVE_LE_1R|0|0.0|None|None|
|GBPJPY/DEMAND_W|False|None|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|True|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|True|INSIDE_ZONE|10|12.081818|60.0|1.208182|
|GBPJPY/DEMAND_W|None|True|ABOVE_LE_1R|4|-0.968182|25.0|-0.242045|
|GBPJPY/DEMAND_W|None|True|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|False|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|False|INSIDE_ZONE|14|11.2|50.0|0.8|
|GBPJPY/DEMAND_W|None|False|ABOVE_LE_1R|11|-3.331818|18.1818|-0.302893|
|GBPJPY/DEMAND_W|None|False|ABOVE_GT_1R|1|-1.031818|0.0|-1.031818|
|GBPJPY/DEMAND_W|None|None|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|None|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|None|ABOVE_LE_1R|0|0.0|None|None|
|GBPJPY/DEMAND_W|None|None|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|True|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|True|INSIDE_ZONE|15|-1.940909|33.3333|-0.129394|
|GBPJPY/RESPONSE_MARKET|True|True|ABOVE_LE_1R|54|22.786364|48.1481|0.42197|
|GBPJPY/RESPONSE_MARKET|True|True|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|False|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|False|INSIDE_ZONE|5|-0.445455|40.0|-0.089091|
|GBPJPY/RESPONSE_MARKET|True|False|ABOVE_LE_1R|47|15.336364|34.0426|0.326306|
|GBPJPY/RESPONSE_MARKET|True|False|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|None|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|None|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|None|ABOVE_LE_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|True|None|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|True|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|True|INSIDE_ZONE|5|-4.040909|20.0|-0.808182|
|GBPJPY/RESPONSE_MARKET|False|True|ABOVE_LE_1R|44|24.922727|52.2727|0.566426|
|GBPJPY/RESPONSE_MARKET|False|True|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|False|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|False|INSIDE_ZONE|6|4.590909|83.3333|0.765152|
|GBPJPY/RESPONSE_MARKET|False|False|ABOVE_LE_1R|43|25.086364|48.8372|0.583404|
|GBPJPY/RESPONSE_MARKET|False|False|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|None|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|None|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|None|ABOVE_LE_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|False|None|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|True|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|True|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|True|ABOVE_LE_1R|1|-1.040909|0.0|-1.040909|
|GBPJPY/RESPONSE_MARKET|None|True|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|False|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|False|INSIDE_ZONE|1|-1.040909|0.0|-1.040909|
|GBPJPY/RESPONSE_MARKET|None|False|ABOVE_LE_1R|1|-1.040909|0.0|-1.040909|
|GBPJPY/RESPONSE_MARKET|None|False|ABOVE_GT_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|None|BELOW_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|None|INSIDE_ZONE|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|None|ABOVE_LE_1R|0|0.0|None|None|
|GBPJPY/RESPONSE_MARKET|None|None|ABOVE_GT_1R|0|0.0|None|None|

## Annual detail USDJPY/W / weaker_second_w_rebound

W second upward leg has lower net body-close advance per observed candle than the first upward leg; GJ M5 and UJ M15 respectively.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|39 / 7.293333 / 0.187009|85 / 4.286667 / 0.050431|
|2024|28 / -6.253333 / -0.223333|83 / 38.46 / 0.463373|
|2025|33 / -5.473333 / -0.165859|72 / 3.58 / 0.049722|
|2026|10 / 5.586667 / 0.558667|43 / 11.14 / 0.25907|

## Annual detail GBPJPY/DEMAND_W / weak_zone_departure

GJ recorded M15 break candle fails bullish body>=50% range, close in upper25%, AND true range>=preceding ATR20.
Unknown: 40.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|120 / 20.177273 / 0.168144|123 / -8.6 / -0.069919|
|2024|120 / 17.281818 / 0.144015|134 / 28.027273 / 0.209159|
|2025|98 / 17.318182 / 0.176716|101 / -21.513636 / -0.213006|
|2026|89 / 45.077273 / 0.506486|72 / 34.940909 / 0.48529|

## Annual detail GBPJPY/DEMAND_W / inefficient_formation

GJ absolute net close-path movement / total close-path movement <0.5. SUPPORT origin through break; BOX origin through known-at birth. These are different formation types, never pooled.
Unknown: 4.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|22 / 7.068182 / 0.321281|240 / 4.427273 / 0.018447|
|2024|16 / 11.040909 / 0.690057|244 / 36.095455 / 0.147932|
|2025|16 / 4.004545 / 0.250284|188 / 2.677273 / 0.014241|
|2026|18 / -3.031818 / -0.168434|149 / 82.790909 / 0.555644|

## Annual detail GBPJPY/DEMAND_W / zone_age_ge_24h

At least24 clock hours since parent became known, including closed-market elapsed time.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|32 / 9.686364 / 0.302699|232 / 5.45 / 0.023491|
|2024|20 / 1.290909 / 0.064545|240 / 45.845455 / 0.191023|
|2025|13 / -3.109091 / -0.239161|192 / 12.768182 / 0.066501|
|2026|9 / 8.0 / 0.888889|159 / 70.727273 / 0.444826|

## Annual detail GBPJPY/DEMAND_W / repeated_completed_revisits

At least two completed M5 contact episodes after known-at, separated by an entirely-above-zone M5 bar. Initial departure must be observed. Incomplete observation window -> UNKNOWN.
Unknown: 181.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|69 / 7.572727 / 0.10975|131 / 1.359091 / 0.010375|
|2024|87 / 19.113636 / 0.219697|123 / 5.054545 / 0.041094|
|2025|52 / 21.268182 / 0.409003|112 / -14.418182 / -0.128734|
|2026|46 / 24.059091 / 0.523024|96 / 46.768182 / 0.487169|

## Annual detail GBPJPY/DEMAND_W / deep_current_pullback

Lowest completed M5 low in current attempt is below parent midpoint. GJ W starts at third-leg start; RESPONSE starts at recorded last bearish M15 pullback candle open.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|101 / 25.722727 / 0.25468|163 / -10.586364 / -0.064947|
|2024|109 / 28.986364 / 0.26593|151 / 18.15 / 0.120199|
|2025|87 / -4.145455 / -0.047649|118 / 13.804545 / 0.116988|
|2026|64 / 9.645455 / 0.15071|104 / 69.081818 / 0.664248|

## Annual detail GBPJPY/DEMAND_W / fill_over_1r_above_zone

Actual original fill more than one original planned stop distance above parent high.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|11 / 0.222727 / 0.020248|253 / 14.913636 / 0.058947|
|2024|12 / -2.436364 / -0.20303|248 / 49.572727 / 0.19989|
|2025|10 / 0.213636 / 0.021364|195 / 9.445455 / 0.048438|
|2026|4 / 9.322727 / 2.330682|164 / 69.404545 / 0.423198|

## Annual detail GBPJPY/DEMAND_W / weaker_second_w_rebound

W second upward leg has lower net body-close advance per observed candle than the first upward leg; GJ M5 and UJ M15 respectively.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|93 / 1.2 / 0.012903|171 / 13.936364 / 0.081499|
|2024|87 / 12.704545 / 0.146029|173 / 34.431818 / 0.199028|
|2025|69 / 7.172727 / 0.103953|136 / 2.486364 / 0.018282|
|2026|61 / 33.995455 / 0.557303|107 / 44.731818 / 0.418054|

## Annual detail GBPJPY/RESPONSE_MARKET / weak_zone_departure

GJ recorded M15 break candle fails bullish body>=50% range, close in upper25%, AND true range>=preceding ATR20.
Unknown: 3.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|27 / 7.654545 / 0.283502|16 / -3.404545 / -0.212784|
|2024|40 / 2.954545 / 0.073864|32 / 20.290909 / 0.634091|
|2025|28 / 7.490909 / 0.267532|27 / 21.113636 / 0.781987|
|2026|26 / 17.636364 / 0.678322|23 / 12.559091 / 0.546047|

## Annual detail GBPJPY/RESPONSE_MARKET / inefficient_formation

GJ absolute net close-path movement / total close-path movement <0.5. SUPPORT origin through break; BOX origin through known-at birth. These are different formation types, never pooled.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|43 / 4.25 / 0.098837|1 / -1.040909 / -1.040909|
|2024|67 / 11.481818 / 0.17137|7 / 9.681818 / 1.383117|
|2025|54 / 29.645455 / 0.54899|1 / -1.040909 / -1.040909|
|2026|48 / 27.227273 / 0.567235|1 / 2.968182 / 2.968182|

## Annual detail GBPJPY/RESPONSE_MARKET / zone_age_ge_24h

At least24 clock hours since parent became known, including closed-market elapsed time.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|3 / -0.9 / -0.3|41 / 4.109091 / 0.100222|
|2024|0 / 0.0 / None|74 / 21.163636 / 0.285995|
|2025|1 / 0.677273 / 0.677273|54 / 27.927273 / 0.517172|
|2026|1 / -1.040909 / -1.040909|48 / 31.236364 / 0.650758|

## Annual detail GBPJPY/RESPONSE_MARKET / repeated_completed_revisits

At least two completed M5 contact episodes after known-at, separated by an entirely-above-zone M5 bar. Initial departure must be observed. Incomplete observation window -> UNKNOWN.
Unknown: 12.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|12 / -4.218182 / -0.351515|25 / 7.036364 / 0.281455|
|2024|34 / 5.822727 / 0.171257|39 / 12.372727 / 0.317249|
|2025|23 / 15.445455 / 0.671542|30 / 11.322727 / 0.377424|
|2026|15 / 18.904545 / 1.260303|32 / 13.372727 / 0.417898|

## Annual detail GBPJPY/RESPONSE_MARKET / deep_current_pullback

Lowest completed M5 low in current attempt is below parent midpoint. GJ W starts at third-leg start; RESPONSE starts at recorded last bearish M15 pullback candle open.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|6 / 7.9 / 1.316667|38 / -4.690909 / -0.123445|
|2024|18 / 3.395455 / 0.188636|56 / 17.768182 / 0.317289|
|2025|12 / 0.131818 / 0.010985|43 / 28.472727 / 0.662156|
|2026|8 / 8.75 / 1.09375|41 / 21.445455 / 0.52306|

## Annual detail GBPJPY/RESPONSE_MARKET / fill_over_1r_above_zone

Actual original fill more than one original planned stop distance above parent high.
Unknown: 0.

| Year | True n / R / mean R | False n / R / mean R |
|---|---:|---:|
|2023|0 / 0.0 / None|44 / 3.209091 / 0.072934|
|2024|0 / 0.0 / None|74 / 21.163636 / 0.285995|
|2025|0 / 0.0 / None|55 / 28.604545 / 0.520083|
|2026|0 / 0.0 / None|49 / 30.195455 / 0.616234|

## Limitations

No new entry model was executed. Differences between UJ/GJ or GJ routes are confounded by instrument, opportunity selection and original management; they are not randomized causal effects.
No confirmed +.5R M5 close before SL is not proof that price immediately failed or never touched +.5R intrabar. Missing path observations are explicitly flagged.
Strict pre-entry M5 completeness can leave repeat-touch/depth UNKNOWN, particularly for older zones across closures. They remain in every ledger and no prices were fabricated.
All five DD and recovery intervals, all original entry-months and years and every negative/support-failed result are recorded. Broad repeated research makes nominal within-audit statistics exploratory only.
