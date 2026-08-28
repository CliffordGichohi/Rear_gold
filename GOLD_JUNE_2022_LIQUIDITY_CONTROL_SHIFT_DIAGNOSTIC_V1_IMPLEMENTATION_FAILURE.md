# Gold June 2022 Liquidity-Control Shift Diagnostic V1 — Implementation Failure

Verdict: `FAIL_SESSION_CALENDAR_CONSTRUCTION_ZERO_RESEARCH_CREDIT`

The original V1 artifacts are preserved unchanged but must not be used. The
New York session-atlas constructor converted midnight UTC into New York local
time before selecting the calendar date, which assigned some New York windows
to the preceding day. The trade-level timestamps were not shifted, but the
combined session atlas and its summary cannot receive analytical credit.

The only permitted correction is to construct each London or New York 08:00
session directly from the stream's declared `trading_date_utc` calendar date.
No threshold, price definition, event definition, outcome, or attribution may
change. The corrected output must be written as a separate R1 artifact and
must again reproduce exactly from the primary and reference streams.
