# Gold Continuation-Refresh Direct Inversion Exposed Diagnostic V1

Status: `AUTHORIZED_POST_HOC_EXPOSED_DIAGNOSTIC`

Use exactly the sealed V2-R1 population of 648 executable setups.  Change only
the 434 `CONTINUATION_REFRESH` plans:

- `LONG` becomes `SHORT`; `SHORT` becomes `LONG`.
- The original absolute target price becomes the inverted stop price.
- The original absolute stop price becomes the inverted target price.

Retain the same decision timestamp, one-minute latency, noon-New-York deadline,
spread, slippage, stop-first ambiguity, whole-ounce sizing, maximum $50 planned
risk per setup, and unrestricted-overlap policy.  Recalculate quantity from the
inverted fill-to-stop geometry.  Do not change or filter any identity.

Keep the remaining 214 non-continuation plans unchanged.  Report:

1. the original continuation subtotal;
2. the executable inverted continuation subtotal; and
3. the complete 648-trade replacement portfolio.

Use only the already exposed January-June 2022 sources.  Do not open the
February gap, 2025, or 2026.  Do not test an alternative inversion, threshold,
filter, entry, stop, target, deadline, management rule, or overlap policy after
viewing results.  Independently reproduce and seal the result.  This post-hoc
diagnostic receives zero validation credit.
