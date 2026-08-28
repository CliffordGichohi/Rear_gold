from __future__ import annotations

import unittest

from gold_intel.analytics.auction_plan_compiler_v1_semantic_amendment_a import (
    _trigger_hierarchy_component,
    causality_violations,
    compile_auction_plan_v1_semantic_amendment_a,
    plan_integrity_violations,
)


def _event(identity: str, timeframe: str, break_at: str, level: float) -> dict[str, object]:
    return {
        "identity": identity,
        "timeframe": timeframe,
        "direction": "LONG",
        "break_at": break_at,
        "broken_identity": f"{identity}-broken",
        "broken_level": level + 1.0,
        "protected_identity": f"{identity}-protected",
        "protected_level": level - 1.0,
        "origin_at": "2022-01-01T09:00:00Z",
        "origin_adverse": level - 0.5,
        "atr": 1.0,
        "buffer": 0.1,
    }


class AuctionPlanCompilerSemanticAmendmentATests(unittest.TestCase):
    def test_no_direction_remains_unresolved(self) -> None:
        result = compile_auction_plan_v1_semantic_amendment_a(
            stream={"timeframes": {}, "context_timeline": {}},
            decision_at="2022-01-01T10:00:00Z",
            direction=None,
            entry_reference=None,
        )
        self.assertEqual(result["disposition"], "NO_TRADE_UNRESOLVED")
        self.assertEqual(result["unresolved_reason"], "NO_DIRECTION_PROPOSAL")
        self.assertEqual(plan_integrity_violations(result), [])

    def test_m15_setup_and_later_m5_refinement_are_both_retained(self) -> None:
        m15 = _event("m15-event", "M15", "2022-01-01T09:15:00Z", 100.0)
        m5 = _event("m5-event", "M5", "2022-01-01T09:25:00Z", 100.5)
        legacy = {
            "identity": "legacy-trigger",
            "family": "M5_INTERNAL_ROTATION",
            "timeframe": "M5",
            "break_at": "2022-01-01T09:25:00Z",
        }
        result = _trigger_hierarchy_component(
            legacy_trigger=legacy,
            active_m15=m15,
            active_m5=m5,
            m15_balance=None,
            direction="LONG",
            entry=101.0,
            cutoff="2022-01-01T10:00:00Z",
        )
        self.assertIsNotNone(result)
        self.assertEqual(result["setup_transition"]["timeframe"], "M15")
        self.assertEqual(result["entry_refinement"]["timeframe"], "M5")
        self.assertEqual(result["execution_anchor"]["timeframe"], "M5")

    def test_nested_future_timestamp_is_detected(self) -> None:
        plan = compile_auction_plan_v1_semantic_amendment_a(
            stream={"timeframes": {}, "context_timeline": {}},
            decision_at="2022-01-01T10:00:00Z",
            direction=None,
            entry_reference=None,
        )
        plan["components"]["local_trigger"] = {
            "setup_transition": {"known_at": "2022-01-01T10:01:00Z"}
        }
        violations = causality_violations(plan)
        self.assertEqual(len(violations), 1)
        self.assertIn("setup_transition", violations[0]["component"])


if __name__ == "__main__":
    unittest.main()
