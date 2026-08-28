# Gold Auction Automation Matched-Replay Verification V1 Report

## Verdict

- Marking verdict: `FAIL_MARKING_MISMATCH`
- Economic verdict: `REJECT_NEGATIVE_MATCHED_ECONOMICS`
- Research credit: `ZERO_CREDIT_EXPOSED_MATCHED_CALIBRATION`

The detector identifies the price levels the human operator considered important, but its current narrow M15 liquidity-shift zones do **not** identify the human entry method. It therefore must not be promoted to automatic paper execution in its current form.

This is a rejection of this particular automation translation, not evidence that gold has no edge. The economic sample contains only two automatic trades and has no independent validation credit.

## Frozen comparison population

- Cases: all 30 matched replay days, `CBR-2022-001` through `CBR-2022-030`
- Period: 3 January through 16 February 2022
- Operators: the sealed human ledger and sealed Codex ledger
- Price source: the existing IC Markets MT5 XAUUSD M1 source
- Source rows available to the detector: 104,960
- Detector lookback: the production-default 60,000 M1 records at each decision checkpoint
- Future access: no 2025 or 2026 outcomes were accessed
- Calibration status: these cases were already exposed and receive zero research or validation credit

Every daily M1 stream used by the detector was checked against the certified private replay stream before comparison. The human ledger hash chain, case population, detector source identities and final result files were verified and sealed.

## Did it mark the chart correctly?

### Human-drawn level agreement

| Measurement | Result |
|---|---:|
| Human horizontal levels | 68 |
| Matched by a swing on the same timeframe | 47 / 68 (69.1%) |
| Matched by a swing on any supported timeframe | 61 / 68 (89.7%) |
| Matched by an active automated zone | 15 / 68 (22.1%) |
| Matched by either a swing or active zone | 62 / 68 (91.2%) |

| Human drawing timeframe | Levels | Same-timeframe swing | Any automated structure |
|---|---:|---:|---:|
| M15 | 3 | 3 | 3 |
| H1 | 22 | 21 | 22 |
| H4 | 38 | 23 | 35 |
| Daily | 5 | 0 | 2 |

The daily shortfall is expected because V1 calculates M5, M15, H1 and H4 swings but not daily swings. The strong aggregate level agreement means the completed-candle swing engine is broadly detecting the same structural prices the human marked.

### Entry-zone agreement

| Measurement | Result |
|---|---:|
| Human executed entries | 16 |
| Near any active automated zone | 2 / 16 (12.5%) |
| Near an active same-direction zone | 1 / 16 (6.25%) |
| Same-direction technical proposal present before decision | 1 / 16 (6.25%) |
| Codex executed entries | 23 |
| Codex entries near any active automated zone | 3 / 23 (13.0%) |
| Codex entries near an active same-direction zone | 0 / 23 (0%) |

Among the 15 human trades for which a same-direction zone existed, the entry was a median 6.01 M15 ATR away from that zone. Only `CBR-2022-023` matched a same-direction active zone. `CBR-2022-002` was near a zone pointing in the opposite direction.

The marking gate required at least 60% level agreement **and** 50% same-direction entry-zone agreement. The detector passed the first requirement and failed the second decisively.

## Proposal funnel

| Proposal family | Triggered | Technical geometry eligible | Fully paper-ready |
|---|---:|---:|---:|
| `RETEST_LIMIT_V0_1` | 74 | 9 | 3 |
| `CONFIRMED_RETEST_V0_1` | 42 | 0 | 0 |
| Total | 116 | 9 | 3 |

Blockers can overlap:

- Technical geometry: 107
- Counter-macro: 51
- Macro neutral: 11
- Liquidity abnormal: 4
- Liquidity unknown: 1

Every confirmed-retest proposal and 65 of 74 limit-retest proposals had reward-to-risk below the frozen 1.25 minimum. All had a target; the failure arose because the nearest already-known opposing swing was too close relative to the structural stop.

The three ready proposals occurred on only two days. The frozen earliest-one-per-case rule therefore produced two trades.

## Constant-execution economics

| Metric | Result |
|---|---:|
| Trades | 2 |
| Wins / losses | 1 / 1 |
| Win rate | 50.0% |
| Net PnL at $50 planned risk | -$2.46 |
| Net R | -0.0491R |
| Expectancy | -0.0246R per trade |
| Profit factor | 0.960 |
| Maximum drawdown | 1.2154R |
| Bootstrap 95% expectancy interval | -1.2154R to +1.1663R |
| Net result at 1.5x costs | -0.2206R |

The two trades were:

1. `CBR-2022-028`: bearish limit retest, target hit, `+1.1663R` (`+$58.32`).
2. `CBR-2022-030`: bearish limit retest, post-fill structural invalidation, `-1.2154R` (`-$60.77`).

Two trades cannot estimate an edge reliably. The negative result and zero confirmed-retest support are nevertheless sufficient to reject deployment of this exact automated policy.

## What the mismatch tells us

The error is not primarily swing detection. It is the translation from the human auction process into zones, entry timing, macro use and targets:

1. **Location and trigger were collapsed into one object.** The human method begins from a broader pre-existing H1/H4 liquidity or premium/discount location, then waits for an M15 transition. V1 expects the eventual entry to remain inside or retest the narrow last-opposing-M15-candle origin zone.
2. **The entry occurs after migration away from the origin.** The human commonly entered after the shift had already moved price several M15 ATR from that original zone. That is why levels agree while entries do not.
3. **Macro was used too rigidly.** The human sometimes took a technically justified range rotation against the broad macro bias. V1 blocks every counter-macro proposal instead of distinguishing aligned continuation from counter-macro range rotation.
4. **The target hierarchy was too local.** V1 selected the nearest known opposing swing. The stated method targets the next meaningful opposing liquidity area, which may be a higher-timeframe or prior liquidity-shift level rather than the nearest internal pivot.
5. **A structural transition was not represented as a sequence.** The intended setup is location contact, liquidity reaction, M15 structure transition, then a lower-timeframe entry opportunity. V1 treats a single displacement-origin zone and its retest as the whole setup.

## Bounded correction recommended

Do not tune the current zone threshold around these exposed outcomes. Replace the semantic model before any fresh test:

1. Maintain a hierarchy of pre-existing Daily/H4/H1 location and liquidity zones separately from M15/M5 trigger state.
2. Detect the chronological sequence: location contact or sweep, M15 transition, displacement, then first eligible M5/M1 pullback or acceptance trigger.
3. Separate two explicit setup families: macro-aligned continuation and counter-macro range rotation. The latter must require an objectively established range and extreme-location evidence.
4. Construct targets from the next meaningful opposing liquidity level in the hierarchy, while retaining nearer internal swings as management information rather than mandatory final targets.
5. Use the 30 exposed cases only to verify that the revised detector represents the operator's intended chart semantics. Freeze it before collecting fresh, outcome-hidden or prospective cases.

Until that bounded correction passes visual-semantic agreement and prospective economics, automated execution remains disabled and `live_order_permitted` remains false.

## Reproduction and artifacts

- Frozen protocol: `GOLD_AUCTION_AUTOMATION_MATCHED_REPLAY_VERIFICATION_PROTOCOL_V1.md`
- Engineering amendment: `GOLD_AUCTION_AUTOMATION_MATCHED_REPLAY_VERIFICATION_ENGINEERING_AMENDMENT_A.md`
- Sealed result: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/result.json`
- Per-decision marking comparison: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/marking_rows.csv`
- Per-level comparison: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/human_level_rows.csv`
- Proposal funnel: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/proposal_rows.csv`
- Executed automatic trades: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/combined_trade_rows.csv`
- Reproduction record: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/independent_reproduction.json`
- Final source seal: `research_artifacts/gold_auction_automation_matched_replay_verification_v1/final_seal.json`

