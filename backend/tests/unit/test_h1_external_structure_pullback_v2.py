from gold_intel.analytics.h1_external_structure_pullback_v2 import (
    external_structure_state,
    synthetic_proof,
)


def _swing(number: int, kind: str, level: float) -> dict:
    hour = number + 1
    return {
        "identity": f"S{number}",
        "kind": kind,
        "timeframe": "H1",
        "pivot_at": f"2022-01-01T{hour:02d}:00:00Z",
        "known_at": f"2022-01-01T{hour + 1:02d}:00:00Z",
        "level": level,
        "state": "UNCONSUMED_UNTOUCHED",
    }


def test_synthetic_proof_passes() -> None:
    assert synthetic_proof()["passed"] is True


def test_contained_pivots_do_not_reverse_external_long_structure() -> None:
    rows = [
        _swing(0, "LOW", 100.0),
        _swing(1, "HIGH", 110.0),
        _swing(2, "LOW", 104.0),
        _swing(3, "HIGH", 115.0),
        _swing(4, "LOW", 109.0),
        _swing(5, "HIGH", 113.0),
        _swing(6, "LOW", 107.0),
    ]
    state = external_structure_state(rows)
    assert state["direction"] == "LONG"
    assert state["external_high"]["level"] == 115.0
    assert state["external_low"]["level"] == 104.0


def test_external_low_break_reverses_to_short() -> None:
    rows = [
        _swing(0, "LOW", 100.0),
        _swing(1, "HIGH", 110.0),
        _swing(2, "LOW", 104.0),
        _swing(3, "HIGH", 115.0),
        _swing(4, "LOW", 99.0),
    ]
    assert external_structure_state(rows)["direction"] == "SHORT"

