# Gold Macro-Acceptance Edge Discovery V1 Result

## Verdict

Formal verdict: `REJECT_NO_PROVISIONAL_MACRO_ACCEPTANCE_EDGE`.

The frozen study tested 26 preregistered conditions. 13 met support, 13 failed support, and 13 support-eligible tests were rejected.

Provisional unvalidated candidates: none.

This is a development result only. It contains no entries, exits, costs, trades, PnL, R multiples, or account-return claims. No 2025 observation was used. The preserved failed loader deserialized 2,164 January-2025 XAUUSD rows before stopping, so 2025 retains zero validation credit; 2026 remained unopened.

## Population and reproduction

- Event cases: 408
- Unique release anchors: 346
- Coincident release timestamps: 62
- Primary/reference anchor checksum: `9e159ea157d305ea858c082299667d09e80dd187951390ac1e852c02d08d7133`
- Complete result checksum: `ab3eff67a54cc25d97fcc548d2c7648a6433786aa3d3a0f30b6c0bd109b1a518`
- Independent reproduction: `PASS_EXACT_PRIMARY_REFERENCE_REPRODUCTION`

## Test results

| Test | Stage | N | Bull/Bear | Balanced hit | 90% block CI | Permutation p | BH q | Verdict | Failed gates |
|---|---:|---:|---:|---:|---:|---:|---:|---|---|
| `MACRO_FUNDAMENTAL_ONLY` | 1 | 308 | 148/160 | 50.52% | 46.18%–54.79% | 0.43293 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks |
| `MARKET_REPRICING_ONLY` | 1 | 309 | 137/172 | 45.46% | 40.36%–50.50% | 0.95355 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `INITIAL_GOLD_MOMENTUM` | 1 | 340 | 188/152 | 47.38% | 42.71%–52.01% | 0.84226 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47 |
| `FUNDAMENTAL_MARKET_CONSENSUS` | 1 | 175 | 77/98 | 46.34% | 39.99%–52.59% | 0.84376 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `MARKET_GOLD_ACCEPTANCE` | 1 | 140 | 70/70 | 42.14% | 35.53%–49.00% | 0.97440 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `TRIPLE_MACRO_ACCEPTANCE` | 1 | 87 | 43/44 | 39.14% | 30.96%–47.32% | 0.97950 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `TRIPLE_WITH_PRIOR_BIAS` | 1 | 40 | 22/18 | 29.29% | 17.81%–41.56% | 0.99535 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47 |
| `TRIPLE_NOT_CROWDED` | 1 | 68 | 34/34 | 36.76% | 27.44%–46.57% | 0.99005 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `TRIPLE_ASIA_BREAK_ACCEPTANCE` | 1 | 24 | 14/10 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MACRO_REJECTION_TOWARD_MACRO` | 1 | 88 | 34/54 | 52.78% | 42.16%–62.67% | 0.31963 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, bootstrap_lower_gt_half, bh_q_lte_0_10, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `FUNDAMENTAL_MARKET_CONTRADICTION_TRUST_MARKET` | 1 | 104 | 48/56 | 44.05% | 36.40%–52.04% | 0.90745 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `FAILED_ASIA_BREAK_STRUCTURE_OVERRIDE` | 1 | 7 | 4/3 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MARKET_GOLD_ACCEPTANCE::CPI` | 2 | 17 | 9/8 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MACRO_REJECTION_TOWARD_MACRO::CPI` | 2 | 8 | 4/4 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MARKET_GOLD_ACCEPTANCE::FOMC` | 2 | 13 | 6/7 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MACRO_REJECTION_TOWARD_MACRO::FOMC` | 2 | 0 | 0/0 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MARKET_GOLD_ACCEPTANCE::GDP` | 2 | 17 | 5/12 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MACRO_REJECTION_TOWARD_MACRO::GDP` | 2 | 12 | 5/7 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MARKET_GOLD_ACCEPTANCE::JOBLESS_CLAIMS` | 2 | 71 | 33/38 | 39.63% | 30.19%–50.00% | 0.96745 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_mean_signed_positive, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `MACRO_REJECTION_TOWARD_MACRO::JOBLESS_CLAIMS` | 2 | 49 | 21/28 | 53.57% | 38.70%–66.85% | 0.36348 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42, one_hour_dbhr_gte_0_47, one_hour_mean_signed_nonnegative |
| `MARKET_GOLD_ACCEPTANCE::NFP` | 2 | 11 | 7/4 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MACRO_REJECTION_TOWARD_MACRO::NFP` | 2 | 19 | 6/13 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MARKET_GOLD_ACCEPTANCE::PCE` | 2 | 17 | 12/5 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MACRO_REJECTION_TOWARD_MACRO::PCE` | 2 | 8 | 4/4 | — | — | — | — | `SUPPORT_FAIL` | support |
| `MARKET_GOLD_ACCEPTANCE::RETAIL_SALES` | 2 | 20 | 7/13 | 54.40% | 38.33%–68.75% | 0.40358 | 0.99535 | `REJECT` | primary_dbhr_gte_threshold, primary_median_signed_positive, bootstrap_lower_gt_half, bh_q_lte_0_10, at_least_four_positive_blocks, no_eligible_block_below_0_42 |
| `MACRO_REJECTION_TOWARD_MACRO::RETAIL_SALES` | 2 | 9 | 1/8 | — | — | — | — | `SUPPORT_FAIL` | support |

## Controls

- The protocol and complete 26-test registry were hashed before outcomes were opened.
- Coincident releases were collapsed to one timestamp-level anchor.
- Signals used information available no later than release plus five minutes.
- Multiplicity was applied across all support-eligible primary tests.
- No test was inverted, retuned, added, or removed after outcome access.
- No provider request, download, or charge occurred.
- No 2025 value entered this analysis. Recovery A records the failed loader's technical deserialization of 2,164 January-2025 rows; 2026 remained unopened.

## Interpretation boundary

A PASS is only a provisional development candidate requiring forward validation. A zero-candidate result rejects this bounded family; it does not prove that every possible gold process is random.
