from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "run_gc_session_trigger_edge_m3.py"
SPEC = importlib.util.spec_from_file_location("gc_session_trigger_edge_m3", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
m3 = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m3)


def test_frozen_outcome_threshold_is_strict() -> None:
    assert m3.displacement_state(None) == "UNKNOWN"
    assert m3.displacement_state(1_000_000) == "FLAT"
    assert m3.displacement_state(-1_000_000) == "FLAT"
    assert m3.displacement_state(1_000_001) == "UP"
    assert m3.displacement_state(-1_000_001) == "DOWN"


def test_seed_is_deterministic_and_method_specific() -> None:
    first = m3.seed_for("LONDON", 1, "S1:LONDON:LEVEL_SWEEP_RECLAIM", "DATE_CLUSTER_SIGN_FLIP_15M")
    assert first == m3.seed_for("LONDON", 1, "S1:LONDON:LEVEL_SWEEP_RECLAIM", "DATE_CLUSTER_SIGN_FLIP_15M")
    assert first != m3.seed_for("LONDON", 1, "S1:LONDON:LEVEL_SWEEP_RECLAIM", "SELECTED_MONTH_WEEK_BLOCK_BOOTSTRAP_15M")


def test_bh_and_holm_adjustment() -> None:
    bh = [{"test_id": "a", "p_value": 0.01}, {"test_id": "b", "p_value": 0.04}]
    m3._bh_adjust(bh)
    assert [item["bh_q_value"] for item in bh] == [0.02, 0.04]
    holm = [
        {"horizon_minutes": 5, "p_value": 0.01},
        {"horizon_minutes": 30, "p_value": 0.03},
        {"horizon_minutes": 60, "p_value": 0.20},
    ]
    m3._holm_adjust(holm)
    assert [item["holm_adjusted_p_value"] for item in holm] == [0.03, 0.06, 0.2]


def test_independent_synthetic_reproduction() -> None:
    m3.self_test()
