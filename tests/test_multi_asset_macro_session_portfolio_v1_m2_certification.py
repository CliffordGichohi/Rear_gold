from __future__ import annotations

import hashlib
import json
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
CERTIFICATION = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
SEAL = ROOT / "research_manifests/multi_asset_macro_session_portfolio_edge_v1_milestone2_seal.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


class MultiAssetMilestone2CertificationTests(unittest.TestCase):
    def test_all_seven_instruments_are_adequate_and_reproduced(self) -> None:
        result = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
        self.assertEqual(result["verdict"], "PASS_MILESTONE_2_ALL_SEVEN_INSTRUMENTS_SOURCE_CERTIFIED")
        self.assertTrue(result["seven_instrument_discovery_ready"])
        self.assertEqual(result["classification_counts"], {"PRESENT_AND_ADEQUATE": 7})
        self.assertEqual(len(result["instrument_certifications"]), 7)
        self.assertTrue(result["independent_reproduction"]["passed"])
        self.assertEqual(
            result["independent_reproduction"]["primary_sha256"],
            result["independent_reproduction"]["reference_sha256"],
        )
        for item in result["instrument_certifications"]:
            self.assertEqual(item["classification"], "PRESENT_AND_ADEQUATE")
            self.assertTrue(item["lineage_row_count_match"])
            self.assertTrue(item["coverage"]["eligible"])
            self.assertTrue(all(item["coverage"]["gates"].values()))

    def test_research_forward_and_charge_controls_remained_locked(self) -> None:
        result = json.loads(CERTIFICATION.read_text(encoding="utf-8"))
        controls = result["controls"]
        self.assertEqual(controls["charge_incurred_usd"], 0.0)
        for key in (
            "paid_data_acquired",
            "XAUUSD_or_EURUSD_reacquired",
            "calendar_2025_market_values_accessed",
            "calendar_2026_market_values_accessed",
            "relationships_calculated",
            "trades_or_PnL_calculated",
            "market_values_humanly_inspected_or_reported",
            "raw_source_files_modified_filtered_or_deleted",
        ):
            self.assertFalse(controls[key], key)

    def test_final_seal_artifacts_are_intact(self) -> None:
        seal = json.loads(SEAL.read_text(encoding="utf-8"))
        self.assertEqual(seal["gold_only_10r_branch"], "TERMINATED_AND_NOT_REOPENED")
        self.assertFalse(seal["next_action_authorized"])
        self.assertTrue(seal["stop_required"])
        for item in seal["artifacts"]:
            path = ROOT / item["path"]
            self.assertTrue(path.is_file(), item["path"])
            self.assertEqual(path.stat().st_size, item["bytes"], item["path"])
            self.assertEqual(sha256_file(path), item["sha256"], item["path"])


if __name__ == "__main__":
    unittest.main()
