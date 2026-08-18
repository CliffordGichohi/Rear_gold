# Gold H4 Half-Retrace Final Falsification V1

Status: `AUTHORIZED_POST_HOC_FINAL_FALSIFICATION`

## Purpose and provenance

This is one final, deliberately post-hoc falsification of the sole named H4
near-miss from Gold Conditional Movement-Policy Edge V1. All earlier PASS,
FAIL, REJECT and INCONCLUSIVE records remain unchanged. All 2021-08-01 through
2024-12-31 evidence has hypothesis-generation credit only and no validation
credit.

The only eligible policy is:

`CMP::H4::RESPONSE_HALF_RETRACE_LIMIT::PIVOT_BUFFER_0P05_ATR::FIXED_2P0_R::TIME_8_PARENT_BARS`

No second policy, inverse, alternative execution, feature, threshold, model,
filter, or post-result repair is permitted.

## Model freeze

Before any calendar-2025 or calendar-2026 market value is accessed, fit one
full-development transparent regression tree using the predictor registry and
implementation frozen in Gold Conditional Movement-Policy Edge V1:

- numeric predictors and categorical predictors are unchanged;
- training-only 1st/99th percentile clipping and median imputation;
- training-state one-hot encoding with unknown categories ignored;
- squared-error best splitter, maximum depth 3;
- minimum H4 leaf size 15;
- minimum impurity decrease 0.0005;
- deterministic random-state provenance 731911; and
- take a trade only when the fitted leaf predicts at least +0.05 net R.

The transform state, complete tree, split fields, execution specification,
training identities, source hashes, and forward decision gates must be hashed
and sealed before forward access.

## Frozen execution

Execution remains exactly:

- H4 response half-retrace limit entry;
- pivot structural stop plus 0.05 ATR;
- fixed 2.0R target;
- time exit after 8 completed parent H4 bars;
- the previously frozen spread, commission, slippage, latency, risk sizing,
  ambiguous-bar and overlap rules; and
- stressed results at 1.5 times baseline transaction cost.

## Forward population

Apply the sealed policy once and unchanged to:

- calendar 2025; and
- calendar 2026 from 2026-01-01 through 2026-07-29 inclusive.

The two segments must be reported separately and combined. Existing sealed IC
Markets XAUUSD, point-in-time fundamental, rate, USD, COT, session and
structure sources are the only allowed inputs. No paid acquisition is
authorized.

## Frozen disposition gates

Segment support requires at least 20 trades on 15 New-York trading dates in
2025 and at least 10 trades on 8 New-York trading dates in 2026. Failure of
either support floor is `INCONCLUSIVE_FORWARD_SUPPORT`.

With both segments supported, `PASS_EXPOSED_FORWARD_ROBUSTNESS` requires every
condition below:

1. net expectancy is strictly positive in 2025;
2. net expectancy is strictly positive in 2026;
3. combined net expectancy is strictly positive;
4. the lower bound of the deterministic 5,000-resample New-York-trading-date
   cluster-bootstrap 90% confidence interval is strictly positive;
5. combined baseline net profit factor is at least 1.15;
6. combined 1.5x-cost net expectancy is strictly positive; and
7. maximum reference-account drawdown is no more than 15%.

If support is adequate and any gate fails, the verdict is
`REJECT_EXPOSED_FORWARD_ROBUSTNESS`. No multiplicity credit is claimed: this is
a post-hoc single-candidate falsification, not independent validation.

## Reporting and stop rule

Report support, trades/dates, win rate, net expectancy, confidence interval,
profit factor, net R, reference-account PnL, maximum drawdown, and 1.5x-cost
expectancy and profit factor for 2025, 2026 and combined. Independently
reproduce identities, predictions, executions and results. Seal an honest
PASS, REJECT or INCONCLUSIVE verdict and stop. No live trading is authorized.
