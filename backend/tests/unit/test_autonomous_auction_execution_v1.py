from __future__ import annotations

import unittest

from gold_intel.analytics.autonomous_auction_execution_v1 import (
    simulate_autonomous_auction_trade_v1,
)


def _bar(minute: int, *, open_: float, high: float, low: float, close: float) -> dict[str, object]:
    return {
        "open_at": f"2022-01-03T08:{minute:02d}:00Z",
        "close_at": f"2022-01-03T08:{minute + 1:02d}:00Z",
        "available_at": f"2022-01-03T08:{minute + 1:02d}:00Z",
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "spread_price": 0.20,
        "complete": True,
    }


def _signal(direction: str, stop: float, target: float) -> dict[str, object]:
    return {
        "disposition": "SIGNAL",
        "direction": direction,
        "signal_at": "2022-01-03T08:05:00Z",
        "plan": {
            "components": {
                "structural_invalidation": {"price": stop},
                "liquidity_destination": {"level": target},
            }
        },
    }


class AutonomousAuctionExecutionV1Tests(unittest.TestCase):
    def test_long_target_uses_next_minute_and_whole_ounce_risk(self) -> None:
        stream = {
            "end_exclusive": "2022-01-03T08:08:00Z",
            "timeframes": {
                "1m": [
                    _bar(5, open_=100.0, high=100.2, low=99.8, close=100.0),
                    _bar(6, open_=100.0, high=102.2, low=99.8, close=102.0),
                    _bar(7, open_=102.0, high=102.1, low=101.8, close=102.0),
                ]
            },
        }
        result = simulate_autonomous_auction_trade_v1(
            stream=stream, signal=_signal("LONG", 99.0, 102.0)
        )
        self.assertEqual(result["disposition"], "EXECUTED")
        self.assertEqual(result["fill_at"], "2022-01-03T08:06:00Z")
        self.assertEqual(result["exit_reason"], "LIQUIDITY_DESTINATION")
        self.assertLessEqual(result["planned_risk_usd"], 50.0)

    def test_same_bar_stop_and_target_resolves_stop_first(self) -> None:
        stream = {
            "end_exclusive": "2022-01-03T08:07:00Z",
            "timeframes": {
                "1m": [
                    _bar(5, open_=100.0, high=100.2, low=99.8, close=100.0),
                    _bar(6, open_=100.0, high=102.5, low=98.5, close=100.0),
                ]
            },
        }
        result = simulate_autonomous_auction_trade_v1(
            stream=stream, signal=_signal("LONG", 99.0, 102.0)
        )
        self.assertEqual(result["exit_reason"], "STOP_FIRST")
        self.assertLess(result["net_r50"], 0)

    def test_short_geometry_and_target(self) -> None:
        stream = {
            "end_exclusive": "2022-01-03T08:07:00Z",
            "timeframes": {
                "1m": [
                    _bar(5, open_=100.0, high=100.2, low=99.8, close=100.0),
                    _bar(6, open_=100.0, high=100.1, low=97.5, close=98.0),
                ]
            },
        }
        result = simulate_autonomous_auction_trade_v1(
            stream=stream, signal=_signal("SHORT", 101.0, 98.0)
        )
        self.assertEqual(result["exit_reason"], "LIQUIDITY_DESTINATION")
        self.assertGreater(result["net_r50"], 0)


if __name__ == "__main__":
    unittest.main()
