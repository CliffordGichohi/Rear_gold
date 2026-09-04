from __future__ import annotations

import unittest
from datetime import timedelta

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, iso, parse_dt
from gold_intel.analytics.h1_confirmation_geometry_audit_v1 import (
    CONTROL_ENTRY,
    CONTROL_STOP,
    M5_STOP,
    RETEST_ENTRY,
    SPLIT_ENTRY,
    M1Path,
    evaluate_policy,
    find_retest_fill,
    stop_geometry,
    synthetic_proof,
)


def bar(at: str, *, high: float, low: float, close: float) -> dict:
    opened = parse_dt(at)
    return {
        "open_at": iso(opened),
        "available_at": iso(opened + timedelta(minutes=1)),
        "open": 101.0,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
    }


class H1ConfirmationGeometryAuditTests(unittest.TestCase):
    def setUp(self) -> None:
        self.case = {
            "trade_identity": "T1",
            "direction": "LONG",
            "control_entry_at": "2022-01-03T10:00:00Z",
            "control_entry_price": 101.0,
            "control_stop": 99.0,
            "target": 103.0,
            "deadline": "2022-01-03T10:04:00Z",
            "broken_m5_control_level": 100.5,
            "source_h1_swing_identity": "H1_LOW",
            "source_h1_detected_at": "2022-01-03T09:00:00Z",
            "source_h1_level": 99.0,
        }
        self.geometry = {
            "requested_policy": CONTROL_STOP,
            "effective_policy": CONTROL_STOP,
            "stop": 99.0,
            "geometry_sha256": canonical_hash(["control", 99.0]),
        }

    def test_complete_synthetic_proof(self) -> None:
        self.assertEqual(synthetic_proof()["verdict"], "PASS")

    def test_retest_is_cancelled_when_target_and_limit_are_ambiguous(self) -> None:
        path = M1Path([bar("2022-01-03T10:00:00Z", high=103.1, low=100.4, close=102.0)])
        result = find_retest_fill(
            path,
            order_at=self.case["control_entry_at"],
            limit=100.5,
            stop=99.0,
            target=103.0,
            direction="LONG",
            deadline=self.case["deadline"],
        )
        self.assertFalse(result["filled"])
        self.assertEqual(result["disposition"], "AMBIGUOUS_TARGET_AND_LIMIT_SAME_BAR_CANCEL")

    def test_control_and_retest_use_distinct_fill_semantics(self) -> None:
        path = M1Path(
            [
                bar("2022-01-03T10:00:00Z", high=101.0 + 1.5, low=100.4, close=101.2),
                bar("2022-01-03T10:01:00Z", high=103.1, low=100.6, close=103.0),
            ]
        )
        control = evaluate_policy(self.case, self.geometry, path, CONTROL_ENTRY)
        retest = evaluate_policy(self.case, self.geometry, path, RETEST_ENTRY)
        split = evaluate_policy(self.case, self.geometry, path, SPLIT_ENTRY)
        self.assertTrue(control["filled"])
        self.assertTrue(retest["filled"])
        self.assertFalse(control["retest_used"])
        self.assertTrue(retest["retest_used"])
        self.assertTrue(split["retest_used"])
        self.assertAlmostEqual(
            split["net_r"], 0.25 * control["net_r"] + 0.75 * retest["net_r"]
        )

    def test_future_swing_cannot_define_stop(self) -> None:
        at = parse_dt(self.case["control_entry_at"])
        registry = {
            "5m": {
                "swings": [
                    {
                        "identity": "KNOWN",
                        "kind": "LOW",
                        "pivot_at": iso(at - timedelta(minutes=10)),
                        "detected_at": iso(at - timedelta(minutes=5)),
                        "level": 100.0,
                    },
                    {
                        "identity": "FUTURE",
                        "kind": "LOW",
                        "pivot_at": iso(at),
                        "detected_at": iso(at + timedelta(minutes=5)),
                        "level": 100.8,
                    },
                ],
                "atr_timeline": [(at - timedelta(minutes=5), 1.0)],
            },
            "15m": {"swings": [], "atr_timeline": []},
            "1h": {"swings": [], "atr_timeline": []},
        }
        result = stop_geometry(self.case, registry, M5_STOP)
        self.assertEqual(result["source_identity"], "KNOWN")
        self.assertTrue(result["replaced_control"])


if __name__ == "__main__":
    unittest.main()
