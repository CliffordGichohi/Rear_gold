from __future__ import annotations

import unittest
from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_plan_compiler_v1 import (
    _accepted_breakout_identity,
    causality_violations,
    compile_auction_plan_v1,
    plan_integrity_violations,
)


def _bar(opened: datetime, minutes: int, price: float, timeframe: str) -> dict[str, object]:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": opened.isoformat().replace("+00:00", "Z"),
        "close_at": closed.isoformat().replace("+00:00", "Z"),
        "available_at": closed.isoformat().replace("+00:00", "Z"),
        "open": price,
        "high": price + 0.25,
        "low": price - 0.25,
        "close": price,
        "complete": True,
        "timeframe": timeframe,
    }


def _stream() -> dict[str, object]:
    start = datetime(2022, 1, 1, tzinfo=UTC)
    definitions = {"1m": 1, "5m": 5, "15m": 15, "1h": 60, "4h": 240}
    timeframes: dict[str, list[dict[str, object]]] = {}
    for timeframe, minutes in definitions.items():
        count = 180 if timeframe in {"1m", "5m", "15m"} else 80
        timeframes[timeframe] = [
            _bar(start + timedelta(minutes=minutes * index), minutes, 100 + (index % 7) * 0.05, timeframe)
            for index in range(count)
        ]
    cutoff = timeframes["1m"][-1]["available_at"]
    return {
        "timeframes": timeframes,
        "context_timeline": {
            "fundamentals": [
                {
                    "available_at": cutoff,
                    "engine_state": {
                        "directional_score": 0.0,
                        "confidence": 50.0,
                        "dominant_driver": "REAL_YIELD",
                        "bias_label": "NEUTRAL",
                        "components": [
                            {"code": "REAL_YIELD", "data_quality": 90.0},
                            {"code": "USD", "data_quality": 90.0},
                        ],
                    },
                }
            ],
            "sessions": [],
            "events": [],
        },
    }


class AuctionPlanCompilerV1Tests(unittest.TestCase):
    def test_accepted_breakout_identity_supports_both_schema_generations(self) -> None:
        self.assertEqual(
            _accepted_breakout_identity({"row_identity": "legacy"}, "LONG"),
            "legacy",
        )
        self.assertEqual(
            _accepted_breakout_identity({"identity": "current"}, "SHORT"),
            "current",
        )
        fallback = _accepted_breakout_identity(
            {"retest_at": "2022-01-01T03:00:00Z", "level": 100.0},
            "LONG",
        )
        self.assertEqual(
            fallback,
            _accepted_breakout_identity(
                {"retest_at": "2022-01-01T03:00:00Z", "level": 100.0},
                "LONG",
            ),
        )

    def test_no_direction_never_invents_a_trade(self) -> None:
        result = compile_auction_plan_v1(
            stream=_stream(),
            decision_at="2022-01-01T03:00:00Z",
            direction=None,
            entry_reference=None,
        )
        self.assertEqual(result["disposition"], "NO_TRADE_UNRESOLVED")
        self.assertEqual(result["unresolved_reason"], "NO_DIRECTION_PROPOSAL")
        self.assertFalse(result["learned_geometry_used"])
        self.assertEqual(plan_integrity_violations(result), [])

    def test_same_point_in_time_payload_is_deterministic(self) -> None:
        stream = _stream()
        first = compile_auction_plan_v1(
            stream=stream,
            decision_at="2022-01-01T03:00:00Z",
            direction="LONG",
            entry_reference=100.0,
        )
        second = compile_auction_plan_v1(
            stream=stream,
            decision_at="2022-01-01T03:00:00Z",
            direction="LONG",
            entry_reference=100.0,
        )
        self.assertEqual(first, second)
        self.assertFalse(first["learned_geometry_used"])
        self.assertEqual(causality_violations(first), [])
        self.assertEqual(plan_integrity_violations(first), [])

    def test_causality_audit_rejects_future_component_timestamp(self) -> None:
        result = compile_auction_plan_v1(
            stream=_stream(),
            decision_at="2022-01-01T03:00:00Z",
            direction="LONG",
            entry_reference=100.0,
        )
        result["components"]["macro_context"]["available_at"] = "2022-01-02T00:00:00Z"
        violations = causality_violations(result)
        self.assertEqual(len(violations), 1)
        self.assertEqual(violations[0]["component"], "macro_context")


if __name__ == "__main__":
    unittest.main()
