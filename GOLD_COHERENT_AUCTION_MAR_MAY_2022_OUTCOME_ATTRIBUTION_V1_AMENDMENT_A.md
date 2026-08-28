# Gold Coherent-Auction March--May 2022 Outcome Attribution V1 — Amendment A

Status: `FROZEN_REPORTING_FLAG_CORRECTION`

The first sealed attribution pass correctly reproduced all trade outcomes,
primary categories, screens and the shadow-management diagnostic. During final
review, its independent `same_exit_bar_target_touch_ambiguous` flag was found
to mark any exit bar that touched the target, including an ordinary
`SEALED_TARGET` winner.

Change exactly one expression: the ambiguity flag is true only when the trade
resolved through a structural/gap stop and that same exit M1 bar also touched
the original target. Preserve the first sealed result unchanged. Reproduce the
complete attribution into a new R1 artifact set and require every field other
than this corrected independent flag and dependent hashes to remain identical.

No PnL, attribution category, screen, overlay, threshold or baseline rule may
change.
