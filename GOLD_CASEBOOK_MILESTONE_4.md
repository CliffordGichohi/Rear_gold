# Gold Casebook Milestone 4 — Relationship Discovery

## Status

Milestone 4 is complete. It evaluated only the feature and interaction universe
frozen before the first conditional result in
`research_manifests/gold_casebook_relationship_discovery_v01.json`.

The calculation used 2021–2023 development cases only. Conditional features and
returns from 2024 were skipped before deserialization and remain reserved for
Milestone 6. Calendar 2025 remains locked. Entry, exit, stop, target,
reward-to-risk, leverage, and account size were not changed or searched.

## Frozen research design

| Evidence | Hash |
|---|---|
| Milestone 4 research manifest | `044b0d1ca776a052b17e18068363f72d5a0edd61408bb94080a413219180b426` |
| Immutable casebook manifest | `d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f` |
| Milestone 3 baseline manifest | `dff92e13105b0b6fd6c9a71a5d9f7668384361d37475fac5fc8b2a33521ea032` |
| Frozen execution manifest | `724a4fef0fa4b526b4d30b9743c2dfa013c53f87b19262a36b05f3fd07c87d76` |

The manifest predeclared:

- 88 point-in-time features across fundamentals, regime, positioning, COT,
  sessions, market structure, and cross-markets;
- 17 transparent Reference-Book-aligned interactions;
- sign, category, range-relation, and development-only session-specific
  tertile transforms;
- the unchanged Milestone 3 next-minute entry, local-noon exit, one-ounce
  notional, observed spread, slippage, and commission;
- minimum case, year, ISO-week-cluster, prevalence, and COT-report support;
- 2,000-replication deterministic ISO-week cluster-bootstrap intervals;
- long/short selection adjustment and Benjamini–Hochberg multiplicity across
  all support-eligible states within each session; and
- stability across both chronological halves and at least two development-year
  buckets.

Prior-day and prior-week session features were disabled before outcomes because
their retained source levels have material stale gaps. Unknown, stale, rolled,
and unavailable cross-market changes remained `UNKNOWN`; they were not treated
as neutral.

## Coverage and validation

| Item | Count |
|---|---:|
| London development cases | 582 |
| New York development cases | 575 |
| Total development cases | 1,157 |
| Declared features per case | 88 |
| Declared interactions | 17 |
| Observed candidate states | 866 |
| Support-eligible states | 510 |
| Distinct point-in-time COT reports used | 126 |

Independent reconstruction verified:

- all source and output artifact hashes;
- all 1,157 feature-case joins to immutable session hashes;
- every feature transform and all 25 session-specific tertile thresholds;
- all 866 candidate memberships and fixed long/short outcomes;
- every bootstrap interval, support flag, year/half result, p-value,
  Benjamini–Hochberg q-value, and rank;
- COT publication availability; and
- exclusion of 2024 and 2025.

An ephemeral clean rerun reproduced the same bundle and rankings hashes.
The complete backend regression suite passed 120 tests, and Ruff reported no
issues in the feature engine, runner, validator, or relationship unit tests.

## Main discovered relationship

The clearest simple relationship was the direction of four-hour CME Treasury
futures:

- falling ZT/ZN futures prices, a market-pricing proxy for rising Treasury
  yields, were associated with bearish gold session returns; and
- rising ZT/ZN futures prices, a proxy for falling yields, were associated with
  bullish gold session returns.

This is consistent with the Reference Book's real-rate and policy-repricing
logic. ZT and ZN are observed futures-price proxies; they are not relabelled as
observed Treasury yields.

All figures below use the unchanged fixed-clock execution after observed
spread, slippage, and commission. USD values are for one ounce and are not
account returns.

| Session | Condition | Direction | N | Mean net bps | Mean net USD/oz | Win % | Profit factor | Week-bootstrap 95% CI bps | Positive years | Positive halves |
|---|---|---|---:|---:|---:|---:|---:|---|---:|---:|
| London | ZN 4h negative | Short | 269 | +3.6381 | +0.6739 | 56.51 | 1.4329 | +1.1603 to +6.2242 | 3/3 | 2/2 |
| London | ZN 4h positive | Long | 276 | +2.9392 | +0.5135 | 53.99 | 1.2937 | -0.1153 to +5.9643 | 3/3 | 2/2 |
| London | ZT 4h negative | Short | 265 | +2.8567 | +0.5215 | 54.34 | 1.3158 | +0.3037 to +5.5481 | 3/3 | 2/2 |
| London | ZT 4h positive | Long | 275 | +1.4794 | +0.2354 | 51.64 | 1.1273 | -1.6258 to +4.7185 | 3/3 | 2/2 |
| New York | ZT 4h negative | Short | 284 | +6.7267 | +1.2864 | 56.69 | 1.5304 | +1.3388 to +12.0868 | 3/3 | 2/2 |
| New York | ZT 4h positive | Long | 257 | +7.0733 | +1.2984 | 52.14 | 1.4743 | +0.9607 to +13.7425 | 3/3 | 2/2 |
| New York | ZN 4h negative | Short | 287 | +6.2357 | +1.1965 | 56.10 | 1.5095 | +1.3244 to +11.2428 | 3/3 | 2/2 |
| New York | ZN 4h positive | Long | 269 | +5.9050 | +1.0800 | 52.42 | 1.3756 | -0.7505 to +12.2800 | 3/3 | 2/2 |

This table reports separate discovered states. Combining them into a live
long/short/no-bias selector is Milestone 5 work and was not calculated here.

## Other informative findings

Seventeen support-eligible states were positive in both chronological halves,
positive across the required development years, and had a positive
week-cluster-bootstrap lower bound: nine London and eight New York states.
Examples include:

- London: positive EURUSD 4h with negative ZN 4h, short gold; 144 cases,
  +5.9932 mean net bps, 1.8338 profit factor, and a +2.6047 to +9.4154 bps
  cluster interval.
- New York: probable COT short covering with negative prior-day gold, long
  gold; 73 cases across 31 distinct COT reports, +14.4428 mean net bps, 2.1120
  profit factor, and a +2.7434 to +27.6897 bps interval.
- London: middle-tertile one-hour structure range location, short gold; 194
  cases, +3.9053 mean net bps, 1.4890 profit factor, and a +0.0900 to +7.7702
  bps interval.

The simpler Treasury-futures relationship is preferable for the next
specification decision because it has larger support, a direct economic
mechanism, consistent sign across both futures proxies, and less conditional
complexity.

The current aggregate macro score did not independently establish direction.
For example:

- London `macro_score=BEARISH` selected short but averaged -0.3705 net bps;
- London `macro_score=BULLISH` did not support its expected long direction;
- New York `macro_score=BEARISH` selected short but averaged -0.4332 net bps;
  and
- New York `macro_score=BULLISH` selected long but averaged -0.7511 net bps.

The evidence therefore says that current intraday rates repricing is more
informative than the slow aggregate macro label by itself. This does not make
fundamentals irrelevant; it identifies which available fundamental transmission
channel is actually showing a development-sample relationship.

## Multiplicity verdict

No candidate passed the predeclared 10% Benjamini–Hochberg false-discovery gate
across all 510 support-eligible states. The strict `discovery_lead` count is
therefore zero.

This does not erase the reported conditional relationships, but it means they
remain exploratory and cannot yet be called a validated edge. The apparently
strong states are numerous and correlated, and their direction was selected on
development data. The untouched 2024 and 2025 periods exist specifically to
determine whether the simple rates relationship survives.

The frozen Milestone 4 manifest states that only a `discovery_lead` is
automatically eligible for positive Milestone 5 case specification. Because the
count is zero, starting Milestone 5 with the ZT/ZN candidate would require an
explicit contract amendment that labels it exploratory and prohibits any
further threshold or variable changes. Without that amendment, the only
contract-compliant Milestone 5 specification is `NO_BIAS`.

## Artifacts

| Artifact | Purpose | Hash |
|---|---|---|
| `research_artifacts/gold_casebook_relationships_v01/manifest.json` | Content-addressed bundle manifest | `a89429d80b589ba3cc5eb64f5d9635f5468768a190900fadbbe95ad75ba75b80` |
| `research_artifacts/gold_casebook_relationships_v01/rankings.json` | Coverage, thresholds, baselines, rankings, and compact evidence | `a6b487de6fd13ff4bbfe0b2ff082a46b4838ca77faf7d7bfe5b6c6333a4291f2` |
| `research_artifacts/gold_casebook_relationships_v01/development_features.jsonl.gz` | 1,157 immutable feature cases | `66b98af507ce484089bad2af2f0d20e3a2dccaaeb88d5b2d8d6d6a6c96d0d691` |
| `research_artifacts/gold_casebook_relationships_v01/relationships.jsonl.gz` | Full 866-state evidence ledger | `2e6b90ac074a53bab2fa3140433ee42365b1fd7673b8536eda35bcdc85387125` |
| `research_artifacts/gold_casebook_relationships_v01/semantic_validation.json` | Independent deterministic reconstruction | `9c8c73e2af8006357e94da594047efbff86f7d6904351e77f64d89876f4f1d97` |
| `backend/tools/run_gold_casebook_relationship_discovery.py` | Frozen-universe runner | Source-controlled implementation |
| `backend/tools/validate_gold_casebook_relationship_discovery.py` | Independent reconstruction validator | Source-controlled implementation |
| `backend/tests/unit/test_casebook_relationships.py` | Transform, bootstrap, selection, multiplicity, and lead tests | Source-controlled tests |

## Next contracted step

Milestone 5 has not started. The evidence supports one clear candidate family:
four-hour ZT/ZN direction as the bias, with market structure reserved for later
entry research. However, the frozen multiplicity gate promoted no lead.

The next decision is therefore explicit:

1. amend the contract once to freeze the simple, economically pre-specified
   ZT/ZN sign rule as an **exploratory** Milestone 5 candidate, with no retuning,
   then expose it unchanged to 2024; or
2. retain the strict gate and record `NO_BIAS`, ending this discovery branch.

Neither option has been taken automatically.
