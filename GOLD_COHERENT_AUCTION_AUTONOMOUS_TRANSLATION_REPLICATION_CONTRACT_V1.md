# Gold Coherent-Auction Autonomous Translation Replication Contract V1

Status: `AUTHORIZED_EXPOSED_SEMANTIC_CALIBRATION_ONLY`

## Purpose

Before the frozen Coherent-Auction Human-Policy V2 is applied to any unopened
month, prove that its implementation has not been mistranslated.  The proof is
performed only on the already exposed `CBR-2022-001` through `CBR-2022-030`
population (3 January through 16 February 2022).  This population has zero
validation credit.

The study has two separate gates.  They may not be conflated.

1. **Overlay reproduction:** with the sixteen sealed human setup records as
   inputs, the unchanged V2 classifier and lifecycle must reproduce every
   disposition, trade result, aggregate hash and the sealed
   `+10.681846581267534R` complete-policy result.
2. **Autonomous translation:** using only information visible at each replay
   cursor, software must reproduce the operator's setup/no-setup choice,
   direction, checkpoint, structural invalidation and opposing-liquidity
   target.  The unchanged V2 overlay is then applied to those autonomously
   generated records.

A pass at Gate 1 does not imply a pass at Gate 2.  No unopened data may be
opened unless both gates pass.

## Evidence boundary

Permitted during semantic calibration:

- the sealed visible human decision ledger;
- the certified primary and reference pre-decision replay streams;
- completed candles and point-in-time context available at a checkpoint;
- the operator's drawings and annotations as semantic labels;
- prior outcome-free detector diagnostics and rejected translations.

Prohibited while constructing or selecting the autonomous translator:

- post-decision bars or outcome fields;
- terminal direction, MFE, MAE, PnL or V2 economic contribution;
- case aliases, calendar dates or source-row identities as predictors;
- rules that recognize an individual case;
- future-formed pivots or levels;
- opening the fresh 50-case block, calendar 2025 or calendar 2026.

## Autonomous decision process

The translator must scan every eligible London and New York checkpoint.  It
may not receive the human decision timestamp as an input.  Its point-in-time
hierarchy is:

1. completed Weekly/Daily/H4/H1 auction state and phase;
2. pre-existing structural or liquidity location and remaining room;
3. completed M15 auction transition or an M5 response nested in M15;
4. first eligible entry checkpoint;
5. adverse structural invalidation;
6. next meaningful opposing liquidity destination.

Macro is context and conviction, not an unconditional veto.  Event-lock,
extreme H4 extension, severe opposing H4 damage and controlling-range conflict
remain the unchanged V2 contextual vetoes.

The translation may use a shallow, fully serialized decision tree to imitate
the operator's point-in-time semantic choices.  Training targets are human
decisions, never market outcomes.  Every input field and branch must be
reported.  Case aliases, dates and hashes are forbidden model inputs.

## Same-month replication gates

### Gate 1: exact overlay control

- all predecessor hashes and seals pass;
- all sixteen human setup records reproduce exactly in primary and reference;
- all sixteen V2 admission/rejection dispositions reproduce exactly;
- every complete-policy per-case result reproduces exactly to `1e-8R`;
- aggregate complete-policy result equals `+10.681846581267534R` within
  `1e-8R`;
- the sealed result bundle checksum reproduces.

### Gate 2: autonomous semantic fidelity

- all thirty sessions are scanned without a supplied decision timestamp;
- at least 14 of 16 human setup days are detected;
- no more than 2 of 14 human no-trade days produce an eligible setup;
- direction agrees on every matched setup;
- median absolute checkpoint difference is at most 15 minutes and the maximum
  is at most 45 minutes;
- the autonomous stop and target each identify an equivalent pre-existing
  structural/liquidity level within `0.50` of the selected timeframe ATR for at
  least 14 matched setups;
- V2 admission/rejection agrees on at least 15 of 16 human setups;
- primary and reference implementations have identical row identities,
  classifications, geometry, diagnostics and hashes.

### Gate 3: economic checksum after semantic freeze

Only after Gate 2 is frozen may already exposed post-decision paths be opened
once.  Apply the unchanged V2 overlay.  PASS requires:

- net complete-policy result between `+9.68184658R` and `+11.68184658R`;
- no case-specific exception;
- no outcome-driven adjustment;
- an explicit attribution of any difference from `+10.68184658R` to setup
  selection, timing, fill, stop, target, or V2 disposition.

## Verdicts

- `PASS_AUTONOMOUS_TRANSLATION_REPLICATION`: all three gates pass.
- `FAIL_OVERLAY_REPRODUCTION`: Gate 1 fails.
- `FAIL_AUTONOMOUS_SEMANTICS`: Gate 2 fails; no economic run is permitted.
- `FAIL_ECONOMIC_REPLICATION`: Gate 2 passes but Gate 3 fails.

Failure keeps every unopened month closed.  It is evidence that the automated
translation is not yet faithful; it does not alter the exposed human-input V2
result.

## Locks

- fresh 50-case block: `LOCKED_UNOPENED`;
- calendar 2025: `LOCKED_UNOPENED`;
- calendar 2026: `LOCKED_UNOPENED`;
- paid acquisition: prohibited;
- live execution: prohibited;
- original V2 artifacts and verdict: immutable.

