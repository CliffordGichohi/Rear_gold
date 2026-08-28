from __future__ import annotations

import sys
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import regress_gold_coherent_auction_frozen_policy_exposed_v1 as subject  # noqa: E402


BASE = datetime(2022, 1, 3, 10, 0, tzinfo=timezone.utc)


def stamp(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def minute_rows(*, high_by_minute: dict[int, float], close_after: float = 100.5) -> list[dict]:
    rows = []
    for index in range(21):
        opened = BASE + timedelta(minutes=index)
        close = close_after if index == 20 else 100.5
        rows.append(
            {
                "timeframe": "1m",
                "open_at": stamp(opened),
                "close_at": stamp(opened + timedelta(minutes=1)),
                "available_at": stamp(opened + timedelta(minutes=1)),
                "open": 100.5 if index else 100.0,
                "high": high_by_minute.get(index, 100.8),
                "low": 99.5,
                "close": close,
                "complete": True,
            }
        )
    return rows


def completed_row(
    timeframe: str,
    *,
    opened: datetime,
    minutes: int,
    close: float,
    swing_level: float | None = None,
) -> dict:
    return {
        "timeframe": timeframe,
        "open_at": stamp(opened),
        "close_at": stamp(opened + timedelta(minutes=minutes)),
        "available_at": stamp(opened + timedelta(minutes=minutes)),
        "open": 100.0,
        "high": max(102.5, close),
        "low": min(99.5, close),
        "close": close,
        "complete": True,
        "synthetic_swing_level": swing_level,
    }


def metadata(_: list[dict], row: dict, __: str) -> dict:
    level = row.get("synthetic_swing_level")
    return {"atr": 1.0, "swing": None if level is None else {"level": level}}


def simulate(stream: dict, *, target: float = 102.0) -> dict:
    return subject.simulate_track_b(
        stream=stream,
        fill_at=stamp(BASE),
        fill=100.0,
        stop=99.0,
        target=target,
        quantity=10,
        cost_per_ounce=0.0,
        planned_risk_usd=10.0,
        metadata=metadata,
    )


def simulate_reference(stream: dict, *, target: float = 102.0) -> dict:
    return subject.simulate_track_b_reference(
        stream=stream,
        fill_at=stamp(BASE),
        fill=100.0,
        stop=99.0,
        target=target,
        quantity=10,
        cost_per_ounce=0.0,
        planned_risk_usd=10.0,
        metadata=metadata,
    )


class FrozenPolicySyntheticTests(unittest.TestCase):
    def test_frozen_protection_arms_then_exits_only_after_completed_m5_break(self) -> None:
        stream = {
            "timeframes": {
                "1m": minute_rows(high_by_minute={0: 101.2}),
                "5m": [
                    completed_row(
                        "5m",
                        opened=BASE,
                        minutes=5,
                        close=99.2,
                        swing_level=99.5,
                    )
                ],
                "15m": [completed_row("15m", opened=BASE, minutes=15, close=100.0)],
            }
        }
        result = simulate(stream, target=105.0)
        self.assertEqual(result, simulate_reference(stream, target=105.0))
        self.assertEqual(result["resolution"], "M5_PROTECTION_EXIT")
        self.assertTrue(result["protection_armed"])
        self.assertTrue(result["protection_exit"])
        self.assertEqual(result["exits"][0]["at"], stamp(BASE + timedelta(minutes=5)))

    def test_target_without_completed_m15_acceptance_closes_conditional_runner(self) -> None:
        stream = {
            "timeframes": {
                "1m": minute_rows(high_by_minute={0: 102.2}, close_after=102.0),
                "5m": [],
                "15m": [completed_row("15m", opened=BASE, minutes=15, close=102.05)],
            }
        }
        result = simulate(stream)
        self.assertEqual(result, simulate_reference(stream))
        self.assertEqual(result["resolution"], "TARGET_NO_M15_ACCEPTANCE")
        self.assertTrue(result["target_core_realized"])
        self.assertFalse(result["target_accepted"])
        self.assertEqual([row["quantity"] for row in result["exits"]], [8, 2])
        self.assertEqual(result["exits"][1]["at"], stamp(BASE + timedelta(minutes=15)))

    def test_target_acceptance_activates_only_the_whole_ounce_runner(self) -> None:
        stream = {
            "timeframes": {
                "1m": minute_rows(high_by_minute={0: 102.2}, close_after=103.0),
                "5m": [],
                "15m": [
                    completed_row(
                        "15m",
                        opened=BASE,
                        minutes=15,
                        close=102.2,
                        swing_level=99.5,
                    )
                ],
            }
        }
        result = simulate(stream)
        self.assertEqual(result, simulate_reference(stream))
        self.assertEqual(result["resolution"], "RUNNER_TIME_EXIT")
        self.assertTrue(result["target_accepted"])
        self.assertTrue(result["runner_activated"])
        self.assertEqual([row["quantity"] for row in result["exits"]], [8, 2])


if __name__ == "__main__":
    unittest.main()
