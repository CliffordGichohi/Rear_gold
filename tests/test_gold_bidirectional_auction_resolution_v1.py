from __future__ import annotations

import sys
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_bidirectional_auction_resolution_v1 as subject  # noqa: E402


def frame(name: str, opens: list[int], closes: list[int], high: list[int], low: list[int], close: list[int]) -> subject.Frame:
    count = len(opens)
    return subject.Frame(
        name=name,
        open_ns=np.asarray(opens, dtype=np.int64),
        close_ns=np.asarray(closes, dtype=np.int64),
        available_ns=np.asarray(closes, dtype=np.int64),
        open_e8=np.asarray(close, dtype=np.int64),
        high_e8=np.asarray(high, dtype=np.int64),
        low_e8=np.asarray(low, dtype=np.int64),
        close_e8=np.asarray(close, dtype=np.int64),
        volume=np.ones(count, dtype=np.float64),
        spread=np.full(count, 0.30, dtype=np.float64),
        missing_minutes=np.zeros(count, dtype=np.int64),
        valid=np.ones(count, dtype=bool),
    )


def test_strict_prior_attempt_and_context_permissions() -> None:
    marker = {
        "checkpoint_feature_available": True,
        "acceptance_state": 1.0,
        "sweep_reclaim_state": 0.0,
    }
    reversal = {
        "checkpoint_feature_available": True,
        "acceptance_state": -1.0,
        "sweep_reclaim_state": 0.0,
        "local_structure_score": -1.0,
        "current_displacement_atr": -0.5,
        "fundamental_alignment_state": "OPPOSED",
        "higher_timeframe_alignment_fraction": 0.25,
    }
    assert subject.attempt_marker(marker)
    assert not subject.reverse_signal(reversal, False)
    assert subject.reverse_signal(reversal, True)
    assert subject.context_permitted(reversal, "REVERSAL")
    assert not subject.context_permitted(reversal, "TREND")


def test_reverse_geometry_is_observable_and_adverse() -> None:
    timestamp = 60_000_000_000
    price = subject.SCALE * 100
    m1 = frame("M1", [timestamp], [timestamp + 60_000_000_000], [price + subject.SCALE], [price - subject.SCALE], [price])
    m5 = frame("M5", [0], [timestamp], [price + 2 * subject.SCALE], [price - subject.SCALE], [price])
    row = {
        "checkpoint_at_utc": subject.ns_iso(timestamp),
        "timeframe": "H1",
        "direction": "UP",
        "setup_atr_e8": float(10 * subject.SCALE),
        "structural_stop_e8": 80 * subject.SCALE,
        "row_id": "row",
        "feature_lineage_hash": "lineage",
        "session_state": "LONDON",
    }
    preview, reason = subject.preview_leg(row, "REVERSAL", 50.0, {"M1": m1, "M5": m5}, "primary")
    assert reason == ""
    assert preview is not None
    assert preview["direction"] == "DOWN"
    assert preview["stop_e8"] == 103 * subject.SCALE
    assert preview["target_e8"] == 80 * subject.SCALE
    assert preview["risk_e8"] == 3 * subject.SCALE


def test_stop_first_and_independent_range_search_agree() -> None:
    minute = 60_000_000_000
    entry = 100 * subject.SCALE
    m1 = frame(
        "M1",
        [0, minute, 2 * minute],
        [minute, 2 * minute, 3 * minute],
        [111 * subject.SCALE, 105 * subject.SCALE, 103 * subject.SCALE],
        [89 * subject.SCALE, 95 * subject.SCALE, 97 * subject.SCALE],
        [entry, 101 * subject.SCALE, 102 * subject.SCALE],
    )
    preview = {
        "side": "TREND",
        "direction": "UP",
        "checkpoint_ns": 0,
        "entry_index": 0,
        "entry_e8": entry,
        "stop_e8": 90 * subject.SCALE,
        "target_e8": 110 * subject.SCALE,
        "risk_e8": 10 * subject.SCALE,
        "cost_usd_oz": 0.47,
        "spread_fallback": False,
        "ounces": 4,
        "budget_usd": 50.0,
        "session": "LONDON",
        "row_id": "row",
        "feature_lineage_hash": "lineage",
    }
    tree = subject.RangeTree(m1.high_e8, m1.low_e8)
    prefix = np.concatenate(([0], np.cumsum(~m1.valid.astype(bool), dtype=np.int64)))
    primary, reason_primary = subject.simulate_leg(preview, 3 * minute, m1, tree, prefix, "primary")
    reference, reason_reference = subject.simulate_leg(preview, 3 * minute, m1, tree, prefix, "reference")
    assert reason_primary == reason_reference == ""
    assert primary is not None and reference is not None
    assert primary["exit_reason"] == reference["exit_reason"] == "STRUCTURAL_STOP"
    assert primary["leg_lineage_hash"] == reference["leg_lineage_hash"]


def test_overlap_skips_second_case_without_deferral() -> None:
    rows = [
        {
            "pullback_id": "a",
            "plan_available": True,
            "traded": True,
            "first_entry_at_utc": "2024-01-01T10:00:00.000000000Z",
            "final_exit_at_utc": "2024-01-01T11:00:00.000000000Z",
        },
        {
            "pullback_id": "b",
            "plan_available": True,
            "traded": True,
            "first_entry_at_utc": "2024-01-01T10:30:00.000000000Z",
            "final_exit_at_utc": "2024-01-01T12:00:00.000000000Z",
        },
        {
            "pullback_id": "c",
            "plan_available": True,
            "traded": True,
            "first_entry_at_utc": "2024-01-01T11:00:00.000000000Z",
            "final_exit_at_utc": "2024-01-01T11:30:00.000000000Z",
        },
    ]
    result = subject.apply_overlap(rows)
    by_id = {row["pullback_id"]: row for row in result}
    assert by_id["a"]["_retained"]
    assert by_id["b"]["_overlap"] == "SKIPPED_OVERLAP"
    assert by_id["c"]["_retained"]

