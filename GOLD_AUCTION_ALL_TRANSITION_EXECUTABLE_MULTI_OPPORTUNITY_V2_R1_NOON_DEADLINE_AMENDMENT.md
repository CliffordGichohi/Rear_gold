# Gold Auction All-Transition Executable Multi-Opportunity V2-R1 Noon-Deadline Amendment

Status: `AUTHORIZED_NARROW_EXECUTION_CORRECTION`

Preserve the V2 prevalue freeze and its stopped execution attempt unchanged.
V2 produced no primary, reference, performance, or PnL artifact because the
resolver stopped at the first transition whose decision timestamp equalled the
frozen noon-New-York deadline.

Change exactly one pre-outcome classification:

- A transition with `decision_at >= noon New York` is
  `NO_TIME_REMAINING_BEFORE_NOON_DEADLINE` and mechanically inexecutable.

The twelve affected transitions are all exactly 12:00 New York.  Preserve the
noon deadline; do not extend it.  The corrected population must contain exactly
729 scanner transitions, 648 executable setups, and 81 hard-inexecutable
setups.  Any different count is a mandatory stop.

Keep every other V2 rule unchanged:

- No A3 or other fitted selector.
- No 1.5R minimum, one-ATR chase limit, continuation-event rejection, or
  local-M15-room filter.
- No daily/session cap and no wait-for-previous-resolution rule.
- Execute all 648 setups independently, including overlaps.
- Preserve original direction, structural stop, known H1/H4 liquidity target,
  one-minute latency, costs, stop-first ambiguity, whole-ounce sizing, $50
  maximum planned risk per setup, and the noon-New-York deadline.
- Use only the already exposed January-June 2022 sources; keep the February gap,
  2025, and 2026 closed.
- Independently reproduce, report, and seal the result with zero validation
  credit.
