from __future__ import annotations

import importlib.util
import sys
from datetime import date
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "msbam_m1", ROOT / "tools/prepare_multi_asset_session_behaviour_archetype_monetization_v1_m1.py"
)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)


def test_universe_excludes_gold_and_has_fifteen_units() -> None:
    assert "XAUUSD" not in module.INSTRUMENTS
    assert len(module.INSTRUMENTS) == 6
    assert len(module.session_units()) == 15


def test_frozen_identity_count_and_uniqueness() -> None:
    registry = module.build_identity_registry()
    assert registry["expected_identity_count"] == 13_380
    assert len({row["case_id"] for row in registry["rows"]}) == 13_380
    assert all(row["coverage_or_outcome_attached"] is False for row in registry["rows"])


def test_dst_boundaries_are_IANA_derived() -> None:
    winter = module.session_clock("LONDON_SESSION", date(2024, 1, 15))[0]
    summer = module.session_clock("LONDON_SESSION", date(2024, 7, 15))[0]
    assert (winter.hour, summer.hour) == (7, 6)
    winter_ny = module.session_clock("US_CASH_SESSION", date(2024, 1, 15))[0]
    summer_ny = module.session_clock("US_CASH_SESSION", date(2024, 7, 15))[0]
    assert (winter_ny.hour, summer_ny.hour) == (14, 13)


def test_traceability_keeps_outcomes_non_decision_eligible() -> None:
    trace = module.build_traceability()
    assert trace["decision_field_count"] > 50
    assert trace["outcome_field_count"] > 30
    assert all(row["decision_eligible"] is False for row in trace["subsequent_behaviour_fields"])


def test_mfe_mae_and_first_passage_definitions_are_frozen() -> None:
    protocol = module.build_protocol({"path": "synthetic", "bytes": 0, "sha256": "0" * 64})
    assert protocol["excursions"]["short_mfe"] == "LONG_MAE"
    assert protocol["excursions"]["short_mae"] == "LONG_MFE"
    assert protocol["first_passage"]["ATR_thresholds"] == [0.25, 0.5, 1.0, 1.5, 2.0, 3.0]
    assert protocol["neutral_reference"]["not_entry_or_fill"] is True


if __name__ == "__main__":
    test_universe_excludes_gold_and_has_fifteen_units()
    test_frozen_identity_count_and_uniqueness()
    test_dst_boundaries_are_IANA_derived()
    test_traceability_keeps_outcomes_non_decision_eligible()
    test_mfe_mae_and_first_passage_definitions_are_frozen()
    print("5 Multi-Asset Session Behaviour Milestone-1 design tests passed")
