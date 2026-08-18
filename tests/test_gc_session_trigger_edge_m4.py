from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "audit_gc_session_trigger_edge_m4.py"
SPEC = importlib.util.spec_from_file_location("gc_m4", SCRIPT)
assert SPEC and SPEC.loader
M4 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M4)


def all_pass() -> dict[str, bool]:
    return {name: True for name in M4.FORMAL_GATE_ORDER}


class Milestone4AuditTests(unittest.TestCase):
    def test_taxonomy_order_is_deterministic(self) -> None:
        checks = all_pass()
        checks["frozen_effect_threshold"] = False
        checks["annual_stability"] = False
        self.assertEqual(M4.classify_checks(checks, "MIXED_OR_CONTRADICTORY"), "NO_MEASURABLE_RELATIONSHIP")

        checks = all_pass()
        checks["bh_q_lte_0_05"] = False
        self.assertEqual(M4.classify_checks(checks, "CONSISTENT"), "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED")

        checks = all_pass()
        checks["bh_q_lte_0_05"] = False
        checks["block_stability"] = False
        self.assertEqual(M4.classify_checks(checks, "CONSISTENT"), "UNSTABLE_RELATIONSHIP")

        checks = all_pass()
        checks["first_event_sensitivity"] = False
        self.assertEqual(M4.classify_checks(checks, "CONSISTENT"), "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS")

    def test_horizon_diagnostic_does_not_become_formal_gate(self) -> None:
        row = {
            "secondary_consistency": [
                {"horizon_minutes": 60, "effect_pp": 2.0, "p_value": 0.2, "holm_adjusted_p_value": 0.6},
                {"horizon_minutes": 5, "effect_pp": 1.0, "p_value": 0.3, "holm_adjusted_p_value": 0.6},
                {"horizon_minutes": 30, "effect_pp": -4.9, "p_value": 0.4, "holm_adjusted_p_value": 0.6},
            ]
        }
        result = M4.horizon_diagnostic(row)
        self.assertEqual(result["status"], "CONSISTENT")
        self.assertFalse(result["formal_m3_gate"])

    def test_receipt_round_trip(self) -> None:
        record = {"version": "TEST", "value": 7, "receipt": None}
        record["receipt"] = M4.canonical_hash(record)
        self.assertTrue(M4.receipt_valid(record, "receipt"))


if __name__ == "__main__":
    unittest.main()
