from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools" / "prepare_gc_session_state_transition_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("state_transition_design", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_complete_registry_is_bounded_and_deterministic() -> None:
    module = load_module()
    first = module.build_registry()
    second = module.build_registry()
    assert first == second
    assert first["counts"] == {"stage1": 18, "stage2": 72, "total": 90, "per_session": 45}
    assert len(first["tests"]) == 90
    assert len({row["test_id"] for row in first["tests"]}) == 90


def test_contract_limits_candidates_and_locks_forward_years() -> None:
    import json

    protocol = json.loads((ROOT / "research_manifests/gc_session_state_transition_v1_protocol_v01.json").read_text())
    assert protocol["candidate_limit_per_session"] == 3
    assert protocol["development"]["locked_years"] == [2025, 2026]
    assert protocol["outcomes"]["primary_horizon_minutes"] == 60
    assert protocol["registry"]["total_per_session"] == 45
