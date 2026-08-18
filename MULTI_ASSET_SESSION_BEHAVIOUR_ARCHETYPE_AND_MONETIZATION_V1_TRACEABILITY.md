# Multi-Asset Session Behaviour V1 — Traceability Registry

The Reference Book is bound at `3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a`. The registry freezes **112** fields: 73 point-in-time decision fields and 39 subsequent-behaviour fields.

| Development source status | Decision fields |
|---|---:|
| DERIVABLE_NOT_MATERIALIZED | 40 |
| MISSING | 8 |
| PRESENT_AND_ADEQUATE | 18 |
| PRESENT_BUT_PARTIAL | 7 |

Every decision fact carries value, unit, epistemic classification, `as_of`, `available_at`, quality, method, explanation, and source hashes. Every subsequent-behaviour field is permanently `decision_eligible=false`.

Important limitations remain visible: no complete cross-asset exchange order book, no exact historical meeting-probability curve, no verified full historical consensus feed, no options/gamma surface, no versioned ETF/central-bank flow panel, no licensed unscheduled-news history, incomplete Japan/euro rate differentials, and no verified EIA inventory history. These are `UNKNOWN` or partial—not neutral.

XAUUSD may appear only as a contemporaneous cross-market context for silver where point-in-time coverage permits. It is not a target instrument and the held gold policy is not reopened.
