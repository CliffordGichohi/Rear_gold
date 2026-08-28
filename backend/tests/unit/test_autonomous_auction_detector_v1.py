from __future__ import annotations

import unittest
from unittest.mock import patch

from gold_intel.analytics.autonomous_auction_detector_v1 import (
    detect_autonomous_auction_signal_v1,
)


def _stream() -> dict[str, object]:
    return {
        "case_alias": "SYNTHETIC-001",
        "session_code": "LONDON",
        "trading_date_utc": "2022-01-03",
        "start_inclusive": "2022-01-03T08:00:00Z",
        "end_exclusive": "2022-01-03T12:00:00Z",
        "timeframes": {
            "1m": [
                {
                    "open_at": "2022-01-03T08:04:00Z",
                    "close_at": "2022-01-03T08:05:00Z",
                    "available_at": "2022-01-03T08:05:00Z",
                    "close": 1800.0,
                    "complete": True,
                },
                {
                    "open_at": "2022-01-03T08:09:00Z",
                    "close_at": "2022-01-03T08:10:00Z",
                    "available_at": "2022-01-03T08:10:00Z",
                    "close": 1801.0,
                    "complete": True,
                },
            ],
            "5m": [],
            "15m": [],
        },
    }


def _plan(direction: str, checkpoint: str, executable: bool) -> dict[str, object]:
    trigger = (
        {
            "setup_transition": {"timeframe": "M15"},
            "entry_refinement": None,
            "execution_anchor": {
                "timeframe": "M15",
                "break_at": checkpoint,
            },
        }
        if executable
        else None
    )
    return {
        "disposition": "EXECUTABLE_PLAN" if executable else "NO_TRADE_UNRESOLVED",
        "direction": direction,
        "entry_reference": 1800.0,
        "missing_components": [] if executable else ["local_trigger"],
        "components": {
            "macro_context": {},
            "governing_auction": {} if executable else None,
            "controlling_structure": {} if executable else None,
            "local_trigger": trigger,
            "structural_invalidation": {"price": 1799.0} if executable else None,
            "liquidity_destination": {"level": 1802.0} if executable else None,
        },
        "learned_geometry_used": False,
        "plan_sha256": f"{checkpoint}-{direction}-{executable}",
    }


class AutonomousAuctionDetectorV1Tests(unittest.TestCase):
    def test_unique_direction_is_selected_without_direction_input(self) -> None:
        checkpoint = "2022-01-03T08:05:00Z"

        def compile_fake(**kwargs: object) -> dict[str, object]:
            return _plan(str(kwargs["direction"]), str(kwargs["decision_at"]), kwargs["direction"] == "LONG")

        with patch(
            "gold_intel.analytics.autonomous_auction_detector_v1._candidate_times",
            return_value=[checkpoint],
        ), patch(
            "gold_intel.analytics.autonomous_auction_detector_v1.plan_integrity_violations",
            return_value=[],
        ):
            result = detect_autonomous_auction_signal_v1(
                _stream(), verify_prefix=False, compiler=compile_fake
            )
        self.assertEqual(result["disposition"], "SIGNAL")
        self.assertEqual(result["direction"], "LONG")
        self.assertEqual(result["signal_at"], checkpoint)

    def test_ambiguous_checkpoint_is_skipped_for_later_unique_state(self) -> None:
        first = "2022-01-03T08:05:00Z"
        second = "2022-01-03T08:10:00Z"

        def compile_fake(**kwargs: object) -> dict[str, object]:
            checkpoint = str(kwargs["decision_at"])
            direction = str(kwargs["direction"])
            executable = checkpoint == first or direction == "SHORT"
            return _plan(direction, checkpoint, executable)

        with patch(
            "gold_intel.analytics.autonomous_auction_detector_v1._candidate_times",
            return_value=[first, second],
        ), patch(
            "gold_intel.analytics.autonomous_auction_detector_v1.plan_integrity_violations",
            return_value=[],
        ):
            result = detect_autonomous_auction_signal_v1(
                _stream(), verify_prefix=False, compiler=compile_fake
            )
        self.assertEqual(result["signal_at"], second)
        self.assertEqual(result["direction"], "SHORT")
        self.assertEqual(result["ambiguous_checkpoint_count"], 1)

    def test_no_complete_direction_returns_no_signal(self) -> None:
        checkpoint = "2022-01-03T08:05:00Z"

        def compile_fake(**kwargs: object) -> dict[str, object]:
            return _plan(str(kwargs["direction"]), str(kwargs["decision_at"]), False)

        with patch(
            "gold_intel.analytics.autonomous_auction_detector_v1._candidate_times",
            return_value=[checkpoint],
        ), patch(
            "gold_intel.analytics.autonomous_auction_detector_v1.plan_integrity_violations",
            return_value=[],
        ):
            result = detect_autonomous_auction_signal_v1(
                _stream(), verify_prefix=False, compiler=compile_fake
            )
        self.assertEqual(result["disposition"], "NO_SIGNAL")
        self.assertIsNone(result["direction"])


if __name__ == "__main__":
    unittest.main()
