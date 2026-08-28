from __future__ import annotations

from gold_intel.analytics.auction_family_router_v1_r1 import (
    corrected_router_lifecycle,
)


def _result(value: float) -> dict:
    return {
        "executed": True,
        "resolution": "TARGET",
        "net_r50": value,
        "net_usd": value * 50.0,
    }


def _lifecycle(*, family: str, room: float, before: float, after: float) -> dict:
    return {
        "admitted": True,
        "disposition": "TARGET",
        "family": family,
        "geometry": {"target_room_r": room},
        "pre_overlay_result": _result(before),
        "break_even_overlay": {"applied": True},
        "effective_result": _result(after),
    }


def test_pre_overlay_result_replaces_harmful_overlay() -> None:
    corrected = corrected_router_lifecycle(
        _lifecycle(
            family="CONTINUATION_WITH_ROOM", room=2.0, before=1.5, after=0.0
        )
    )
    assert corrected["admitted"] is True
    assert corrected["break_even_overlay_used"] is False
    assert corrected["effective_result"]["net_r50"] == 1.5


def test_delayed_fill_below_room_floor_is_rejected() -> None:
    corrected = corrected_router_lifecycle(
        _lifecycle(family="RANGE_ROTATION", room=1.49, before=-1.0, after=-1.0)
    )
    assert corrected["admitted"] is False
    assert corrected["disposition"] == "DELAYED_ACTUAL_FILL_TARGET_ROOM_LT_1P5R"
    assert corrected["effective_result"] is None


def test_delayed_fill_at_room_floor_is_retained() -> None:
    corrected = corrected_router_lifecycle(
        _lifecycle(family="STRUCTURAL_REPAIR", room=1.5, before=2.0, after=0.0)
    )
    assert corrected["admitted"] is True
    assert corrected["room_gate_passed"] is True
    assert corrected["effective_result"]["net_r50"] == 2.0


def test_existing_no_trade_remains_no_trade() -> None:
    corrected = corrected_router_lifecycle(
        {
            "admitted": False,
            "disposition": "NO_RANGE_RECLAIM_WITHIN_6_M5",
            "family": "RANGE_ROTATION",
            "geometry": None,
            "pre_overlay_result": None,
            "effective_result": None,
        }
    )
    assert corrected["admitted"] is False
    assert corrected["disposition"] == "NO_RANGE_RECLAIM_WITHIN_6_M5"

