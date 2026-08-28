from __future__ import annotations

from gold_intel.analytics.auction_family_router_v2_r1 import (
    direct_legacy_signal_route,
    m15_setup_event,
    pre_entry_invalidation_disposition,
    select_destination_hierarchy,
)


def _layer(identity: str, timeframe: str, break_at: str) -> dict:
    return {
        "identity": f"semantic-{identity}",
        "event_identity": identity,
        "timeframe": timeframe,
        "direction": "LONG",
        "break_at": break_at,
        "broken_swing_identity": f"broken-{identity}",
        "broken_level": 101.0,
        "protected_swing_identity": f"protected-{identity}",
        "protected_level": 98.0,
        "transition_origin_at": "2022-01-03T07:00:00Z",
        "transition_origin_adverse": 97.5,
        "transition_atr": 2.0,
        "break_buffer": 0.2,
    }


def _zone(identity: str, level: float, state: str, source: str = "H1") -> dict:
    return {
        "identity": identity,
        "source": source,
        "state": state,
        "level": level,
        "buffer": 0.2,
        "known_at": "2022-01-03T07:00:00Z",
        "prominence_atr": 1.0,
    }


def _bar(*, high: float, low: float) -> dict:
    return {
        "open_at": "2022-01-03T08:01:00Z",
        "close_at": "2022-01-03T08:02:00Z",
        "available_at": "2022-01-03T08:02:00Z",
        "open": 100.0,
        "high": high,
        "low": low,
        "close": 100.5,
        "complete": True,
        "source_record_hash": "bar-1",
    }


def test_m15_setup_is_used_instead_of_optional_m5_refinement() -> None:
    plan = {
        "components": {
            "local_trigger": {
                "setup_transition": _layer(
                    "m15-event", "M15", "2022-01-03T08:00:00Z"
                ),
                "entry_refinement": _layer(
                    "m5-event", "M5", "2022-01-03T08:05:00Z"
                ),
                "execution_anchor": {
                    "identity": "anchor",
                    "timeframe": "M15",
                    "break_at": "2022-01-03T08:00:00Z",
                },
            }
        }
    }
    event = m15_setup_event(plan)
    assert event is not None
    assert event["identity"] == "m15-event"
    assert event["timeframe"] == "M15"
    assert event["break_at"] == "2022-01-03T08:00:00Z"


def test_continuation_uses_one_direct_signal_anchor() -> None:
    route = direct_legacy_signal_route(
        signal_at="2022-01-03T08:05:00Z", direction="LONG"
    )
    assert route["confirmation_at"] == "2022-01-03T08:05:00Z"
    assert route["second_trigger_required"] is False


def test_destination_uses_active_level_and_keeps_reactivated_as_intermediate() -> None:
    result = select_destination_hierarchy(
        [
            _zone("near-reactivated", 101.0, "REACTIVATED_REVERSE"),
            _zone("final-engaged", 103.0, "ACTIVE_ENGAGED"),
            _zone("far-untouched", 105.0, "ACTIVE_UNTOUCHED", "H4"),
            _zone("consumed", 102.0, "CONSUMED_ACCEPTED"),
        ],
        entry=100.0,
        direction="LONG",
    )
    assert result is not None
    assert result["final"]["identity"] == "final-engaged"
    assert result["intermediate"]["identity"] == "near-reactivated"
    assert result["eligible_final_count"] == 2


def test_consumed_or_reactivated_only_cannot_be_final_destination() -> None:
    assert (
        select_destination_hierarchy(
            [
                _zone("reactivated", 101.0, "REACTIVATED_REVERSE"),
                _zone("consumed", 102.0, "CONSUMED_ACCEPTED"),
            ],
            entry=100.0,
            direction="LONG",
        )
        is None
    )


def test_target_touch_does_not_cancel_delayed_entry() -> None:
    result = pre_entry_invalidation_disposition(
        [_bar(high=115.0, low=99.0)],
        signal_at="2022-01-03T08:00:00Z",
        fill_at="2022-01-03T08:03:00Z",
        stop=98.0,
        direction="LONG",
    )
    assert result["disposition"] == "CLEAR_TO_DELAYED_ENTRY"


def test_structural_stop_touch_cancels_delayed_entry() -> None:
    result = pre_entry_invalidation_disposition(
        [_bar(high=115.0, low=97.5)],
        signal_at="2022-01-03T08:00:00Z",
        fill_at="2022-01-03T08:03:00Z",
        stop=98.0,
        direction="LONG",
    )
    assert result["disposition"] == "STRUCTURAL_INVALIDATION_TOUCHED_PRE_ENTRY"

