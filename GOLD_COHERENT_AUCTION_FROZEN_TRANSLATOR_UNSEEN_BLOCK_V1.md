# Gold Coherent-Auction Frozen-Translator Unseen-Block Test V1

Status: `AUTHORIZED_AND_FROZEN_BEFORE_UNSEEN_STREAM_OPEN`

Authorization: on 2026-08-21 the user instructed that the already-running
algorithm be applied without any change to data following the exposed
same-month translation sample.

## Purpose

Test whether the frozen autonomous translator that returned `+10.69354658R`
on its exposed fitting month transfers to data whose labels, paths, and
outcomes were not used to fit the translator.

This is a one-shot historical unseen-translator test. It is stronger than the
same-month translation check but is not independent market validation because
the dates are historical and belong to the broader research archive.

## Frozen algorithm

- Translator artifact:
  `research_artifacts/gold_coherent_auction_end_to_end_same_month_v1/translator.json`
- Translator SHA-256:
  `c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841`
- Direction support: `LONG` only.
- Semantic timing tree, preprocessing schema, probability threshold, family
  tree, stop-distance tree, and target-distance tree remain byte-for-byte
  unchanged.
- The first minute checkpoint within the frozen session whose probability
  reaches the frozen threshold is the sole signal. If none qualifies, the
  case is `NO_SIGNAL`.
- The existing contextual V2 admission/veto logic, whole-ounce sizing,
  `$50` maximum planned case loss, spread, `$0.05` adverse slippage,
  `1.25R` protection, bounded runner, stop-first ambiguity rule, and session
  deadline remain unchanged.
- There is no fitting, threshold selection, inversion, repair, discretionary
  input, or second candidate.

The following implementation artifacts are frozen as the behavioural
reference before the unseen stream is opened:

- `tools/run_gold_coherent_auction_end_to_end_v1_inference.py`:
  `eff0abf5dac037668764b93c8435a0dffd00e7d5bd581a36af133e013d25aba8`
- `tools/gold_coherent_auction_end_to_end_v1_common.py`:
  `10e17637bc90da02dd5b37ead0a6615347856808285b2d97a03b5950877330d2`
- `backend/src/gold_intel/analytics/coherent_auction_human_policy_v2.py`:
  `694b441ddf8174921a4e2e689d892018473f075fa638225a805e76d25b43412f`
- `backend/src/gold_intel/analytics/coherent_auction_correction_v1.py`:
  `5d037652eff5148af05e7ab401c40c2374749c07af9901a80c4ff4b671d2b14d`

The new wrapper must first reproduce the complete exposed autonomous rows and
summary exactly before it may open the unseen stream.

## Frozen unseen population

Use exactly the previously sealed Gold Coherent-Auction Blind Validation V1
population:

- 50 cases: 25 London and 25 New York;
- frozen population SHA-256:
  `36a60ccfccedda19a39a48e6c38326b5f0d54f8bd7380cfd1595aa27d8c791f3`;
- date range: 2022-08-08 through 2022-12-30;
- population order: `GAV-2022-001` through `GAV-2022-050`;
- source selection was outcome-blind and sealed before this autonomous
  translator was fitted.

This is a month-equivalent of balanced session opportunities, not a contiguous
calendar month. Reusing it avoids choosing dates after seeing the translator.

Frozen certified stream inputs:

- primary and reference stream SHA-256:
  `b3f1628e30f1549253478fb45d628bd09eab3abf95fed492c715e030a9b819ef`;
- stream-certification SHA-256:
  `7d079c11c3b55dce81d0972ac82102cf8c8963e5e6ae4644e48fb4291e57014a`;
- private population registry SHA-256:
  `2faef0abde0bd677ec9712bb676c7114dcd39037d4d2da40b417d9ec4ff912ad`.

The possible rendering of the initial pre-decision view of `GAV-2022-001` is
preserved as a prior artifact. No fresh human decision, future path, aggregate
result, or fitted translator input came from this population.

## Isolation and one-shot procedure

Before opening stream values:

1. verify every predecessor and source hash;
2. seal the exact wrapper implementation and this contract;
3. prove the wrapper against the exposed 30-case result, requiring identical
   rows and summary;
4. confirm that no fresh decision ledger or fresh result exists.

Then open the complete primary stream once, process all 50 cases without an
interim result, repeat from the independently materialized reference stream,
and require exact row and summary equality. Inference may read the frozen
translator and certified point-in-time streams only. It must not read human
decisions, labels, stored signal timestamps, a fresh outcome ledger, or any
2025/2026 source.

## Frozen reporting and verdict

Report all 50 dispositions and, for admitted executions, net and stressed
results. Report combined and separately by London and New York:

- signals, admitted/rejected trades, and no-signals;
- wins, losses, scratches, win rate, expectancy, profit factor, net R,
  dollars at `$50/R`, and maximum drawdown;
- 1.5x-cost net R;
- chronological-half results, where cases are sorted by
  `(trading_date_utc, session start, case_alias)` and split 25/25;
- positive-gross-R concentration by session.

`PROVISIONAL_PASS` requires all of:

1. at least 20 admitted and executed trades;
2. positive combined net expectancy after costs;
3. profit factor at least 1.10;
4. positive net R in both frozen chronological halves;
5. neither session contributes more than 80% of positive gross R;
6. positive combined net R at 1.5x variable costs;
7. all integrity and exact-reproduction gates pass.

`REJECT` applies if combined expectancy is non-positive, profit factor is
below 1.00, or integrity/reproduction fails. Any other result is
`INCONCLUSIVE`.

No result authorizes live trading. Calendar 2025 and 2026 remain unopened.
No paid acquisition or charge is permitted.
