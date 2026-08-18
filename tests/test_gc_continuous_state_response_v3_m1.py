from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "tools" / "prepare_gc_continuous_state_response_v3_m1.py"
SPEC = importlib.util.spec_from_file_location("gc_csr_v3_m1", SCRIPT)
assert SPEC and SPEC.loader
M1 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(M1)


class ContinuousStateResponseM1Tests(unittest.TestCase):
    def test_power_implementations_match(self) -> None:
        for n in (150, 187, 2394, 2992):
            for tests in (6, 10):
                alpha = 0.05 / tests
                self.assertAlmostEqual(M1.correlation_mde(n, alpha), M1.correlation_mde_reference(n, alpha), places=12)
                self.assertAlmostEqual(M1.accuracy_mde(n, alpha), M1.accuracy_mde_reference(n, alpha), places=12)

    def test_registry_is_bounded(self) -> None:
        features = M1.feature_registry_payload()
        models = M1.model_registry_payload()
        self.assertEqual(features["feature_count"], 12)
        self.assertEqual(len(M1.STAGE1_IDS), 10)
        self.assertEqual(len(M1.MODIFIER_IDS), 2)
        self.assertEqual(len(models["stage2"]["interactions"]), 6)

    def test_anchor_grid_is_non_overlapping_for_primary_horizon(self) -> None:
        offsets = M1.model_registry_payload()["sampling"]["offset_minutes"]
        self.assertEqual(offsets, list(range(0, 240, 15)))
        self.assertTrue(all(right - left == 15 for left, right in zip(offsets, offsets[1:])))

    def test_deferred_fields_are_visible(self) -> None:
        deferred = M1.feature_registry_payload()["deferred_visible_fields"]
        domains = {item["domain"] for item in deferred}
        self.assertIn("POSITIONING", domains)
        self.assertIn("CATALYSTS", domains)


if __name__ == "__main__":
    unittest.main()
