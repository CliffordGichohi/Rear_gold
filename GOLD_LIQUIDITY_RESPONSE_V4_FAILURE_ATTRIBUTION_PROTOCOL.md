# Gold Liquidity-Response V4 Failure Attribution Protocol

Use only the sealed V4 detector/result, the sealed pre-decision diagnostic and information visible at or before each human decision or NO_TRADE session timestamp. Do not access post-decision outcomes or PnL.

For every unmatched trade, classify whether the otherwise matching M5 activation was absent, source-location-expired, or terminated only by an opposite M5 pivot break before the decision. Recalculate a diagnostic-only natural four-hour terminal that ignores the opposite-M5 termination but retains the source-location terminal.

At each trade checkpoint and each V4 false-positive control state, report a frozen higher-timeframe eligibility observation:

- aligned H1 or H4 confirmed-pivot trend; or
- inward direction from the outer 35% of the latest point-in-time-known H1 or H4 confirmed swing range.

Report counts for the diagnostic natural state alone and natural state plus higher-timeframe eligibility. These are semantic failure-attribution counts with zero research/economic credit, not candidate results. Recommend at most one materially different successor definition. Independently reproduce and keep every outcome partition locked.

