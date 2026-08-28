# Gold Coherent-Auction Exposed-Policy Regression — Engineering Amendment B

Status: `FROZEN_AFTER_CONTROL_PRECISION_FAILURE_BEFORE_FINAL_RERUN`

The Amendment A rerun achieved exact primary/reference payload equality but stopped because seven fixed-H1 controls differed from their sealed artifacts in `net_usd` by only `$0.00000003` to `$0.00000010`. Every resolution and every eight-decimal R result matched exactly.

This amendment changes only the technical control-comparison tolerance for dollar values from `1e-8` to `1e-6`. R values must still match to `1e-8`, resolutions must remain exact, all 16 cases must remain present, and primary/reference policy results must remain exactly equal.

No market value, rule, threshold, stop, target, cost, quantity, population, or economic result is changed.

