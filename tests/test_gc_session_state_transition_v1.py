from __future__ import annotations

from datetime import UTC, datetime, timedelta
import importlib.util
from pathlib import Path
import sys


ROOT = Path(__file__).resolve().parents[1]
TOOL = ROOT / "tools/run_gc_session_state_transition_v1.py"


def load_module():
    spec = importlib.util.spec_from_file_location("state_transition_v1", TOOL)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_first_passage_is_symmetric_and_same_bar_is_ambiguous() -> None:
    module = load_module()
    now = datetime(2024, 1, 2, 12, 0, tzinfo=UTC)
    anchor = 2000 * module.SCALE
    atr = module.SCALE
    base = {"anchor_close_e8": anchor, "atr20_5m_e8": atr, "direction": "UP"}
    bars = [module.Bar(now, now + timedelta(minutes=1), anchor, anchor + atr, anchor - atr, anchor, "x", "x")]
    assert module.passage_for_path(base, bars, "primary") == ("BOTH_SAME_BAR", 0)
    assert module.passage_for_path(base, bars, "reference") == ("BOTH_SAME_BAR", 0)


def test_engineering_dates_remain_excluded() -> None:
    module = load_module()
    assert module.ENGINEERING_DATES == {
        "2024-01-05", "2024-01-09", "2024-01-11", "2024-01-30", "2024-01-31", "2024-03-20"
    }


def test_registered_limits_remain_frozen() -> None:
    import json

    protocol = json.loads((ROOT / "research_manifests/gc_session_state_transition_v1_protocol_v01.json").read_text())
    assert protocol["candidate_limit_per_session"] == 3
    assert protocol["inference"]["bootstrap_resamples"] == 5000
    assert protocol["registry"]["total_per_session"] == 45
