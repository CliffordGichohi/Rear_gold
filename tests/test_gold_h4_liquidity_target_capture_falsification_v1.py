from __future__ import annotations

import json
import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_gold_h4_liquidity_target_capture_falsification_v1 as study


def test_protocol_and_policy_registry_are_exact() -> None:
    protocol = json.loads(study.PROTOCOL.read_text(encoding="utf-8"))
    assert protocol["status"] == "FROZEN_BEFORE_2021_2024_POST_TARGET_PATH_ACCESS"
    assert [item["id"] for item in protocol["policies"]] == [item[0] for item in study.POLICIES]
    assert [item["take_fraction"] for item in protocol["policies"]] == [item[1] for item in study.POLICIES]
    assert protocol["population"]["executable"] == 248
    assert protocol["pass_gates"]["r_per_month_gte"] == 10.0
    assert protocol["locked_periods"]["calendar_2025"] is True
    assert protocol["locked_periods"]["calendar_2026"] is True


def test_synthetic_target_state_and_liquidity_proof() -> None:
    proof = study.synthetic_proof()
    assert proof["status"] == "PASS_SYNTHETIC_TARGET_STATE_AND_LIQUIDITY_PROOF"
    assert proof["atr_primary_reference_equal"] is True
    assert proof["pivot_primary_reference_equal"] is True


def test_whole_ounce_allocation_is_conservative() -> None:
    for ounces in range(1, 21):
        for _, fraction in study.POLICIES:
            take = max(1, __import__("math").ceil(fraction * ounces))
            runner = ounces - take
            assert 1 <= take <= ounces
            assert 0 <= runner < ounces


def test_holm_family_has_exactly_three_research_policies() -> None:
    metrics = [
        {"policy_id": study.CONTROL, "incremental_bootstrap": {"one_sided_p": 1.0}},
        *[
            {"policy_id": policy, "incremental_bootstrap": {"one_sided_p": value}}
            for (policy, _), value in zip(study.POLICIES, (0.01, 0.02, 0.03), strict=True)
        ],
    ]
    study.holm_adjust(metrics)
    adjusted = [metric["holm_incremental_p"] for metric in metrics if metric["policy_id"] != study.CONTROL]
    assert adjusted == [0.03, 0.04, 0.04]
