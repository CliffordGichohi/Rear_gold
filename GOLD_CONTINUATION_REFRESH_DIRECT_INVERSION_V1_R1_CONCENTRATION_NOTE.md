# Gold Continuation-Refresh Direct Inversion V1-R1 Concentration Note

The sealed direct-inversion result is mechanically correct under its frozen
TP-to-SL, SL-to-TP and $50-risk sizing rules, but its headline performance is
not economically credible without an additional capacity constraint.

## Verified concentration

- Inverted continuation subtotal: `+467.0165R` across 434 trades.
- Largest single trade: `+385.3714R`, or 82.52% of the complete subtotal.
- Top five trades: `+486.8222R`, or 104.24% of the complete subtotal.
- Subtotal excluding the top five: `-19.8057R`.
- Maximum planned reward-to-risk: `406.3714R`.
- Maximum position size: `5,000` ounces.
- 99th-percentile position size: `1,000` ounces.
- Fourteen trades had invalid post-fill geometry after latency and costs.
- The replacement portfolio was negative in February, March and May.

## Cause

For some original continuation plans, the known-liquidity target was extremely
close to entry while the structural stop was much farther away.  Directly
swapping TP and SL therefore produced a microscopic inverted stop, a very large
whole-ounce position under fixed $50 planned risk, and an extremely distant
inverted target.  The largest case used 5,000 ounces and produced +385.37R.

## Honest interpretation

The result supports further examination of the contrarian direction premise,
but it does not establish an economically tradable edge.  Directional value
must be separated from position-size amplification using a frozen capacity or
constant-exposure diagnostic before any validation or paper-trading claim.
