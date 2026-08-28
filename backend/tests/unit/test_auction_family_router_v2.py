from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_family_router_v2 import (
    balance_boundary_reclaim_qualifies,
    first_balance_boundary_reclaim,
    plan_trigger_event,
    planned_geometry,
    simulate_structural_management,
    trigger_is_fresh,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, iso


def bar(
    opened: datetime,
    minutes: int,
    open_: float,
    high: float,
    low: float,
    close: float,
) -> dict[str, object]:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": iso(opened),
        "close_at": iso(closed),
        "available_at": iso(closed),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "source_record_hash": canonical_hash(
            [iso(opened), minutes, open_, high, low, close]
        ),
    }


def layer(point: datetime, timeframe: str = "M5") -> dict[str, object]:
    return {
        "identity": "semantic-layer",
        "event_identity": "native-event",
        "family": "M5_ENTRY_REFINEMENT" if timeframe == "M5" else "M15_STRUCTURE_TRANSITION",
        "timeframe": timeframe,
        "direction": "LONG",
        "break_at": iso(point),
        "known_at": iso(point),
        "broken_swing_identity": "broken",
        "broken_level": 101.0,
        "protected_swing_identity": "protected",
        "protected_level": 98.0,
        "transition_origin_at": iso(point - timedelta(minutes=5)),
        "transition_origin_adverse": 98.5,
        "transition_atr": 2.0,
        "break_buffer": 0.2,
    }


def plan(point: datetime) -> dict[str, object]:
    return {
        "components": {
            "local_trigger": {
                "setup_transition": layer(point - timedelta(minutes=15), "M15"),
                "entry_refinement": layer(point, "M5"),
            }
        }
    }


def classification(direction: str = "LONG", family: str = "RANGE_ROTATION") -> dict[str, object]:
    fill = 100.0
    stop = 98.0 if direction == "LONG" else 102.0
    target = 104.0 if direction == "LONG" else 96.0
    geometry = planned_geometry(
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=0.1,
        direction=direction,
    )
    payload = {
        "ruleset": "synthetic",
        "decision_at": "2022-01-03T08:00:00Z",
        "direction": direction,
        "family": family,
        "admitted": True,
        "primary_disposition": "ADMIT",
        "fill": fill,
        "stop": stop,
        "target": target,
        "structural_price_risk_per_ounce": geometry["structural_risk_per_ounce"],
        "cost_per_ounce": 0.1,
        "planned_loss_per_ounce": geometry["planned_loss_per_ounce"],
        "quantity_ounces": geometry["quantity_ounces"],
        "classification_hash": None,
    }
    payload["classification_hash"] = canonical_hash(
        {key: value for key, value in payload.items() if key != "classification_hash"}
    )
    return payload


def stream(rows: list[dict[str, object]], end: datetime) -> dict[str, object]:
    return {
        "end_exclusive": iso(end),
        "timeframes": {"1m": rows, "5m": [], "15m": []},
    }


def test_named_balance_reclaim_requires_level_sweep_and_is_mirrored() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    long = bar(point, 5, 99.8, 101.0, 98.9, 100.5)
    middle_wick = bar(point, 5, 100.2, 101.0, 99.1, 100.6)
    short = bar(point, 5, 100.2, 101.1, 99.0, 99.5)
    assert balance_boundary_reclaim_qualifies(long, boundary=100.0, direction="LONG")
    assert not balance_boundary_reclaim_qualifies(middle_wick, boundary=99.0, direction="LONG")
    assert balance_boundary_reclaim_qualifies(short, boundary=100.0, direction="SHORT")
    assert not balance_boundary_reclaim_qualifies(short, boundary=100.0, direction="LONG")


def test_balance_route_takes_first_and_expires_after_six_bars() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    neutral = [bar(point + timedelta(minutes=5 * i), 5, 100.2, 101, 100.0, 100.3) for i in range(6)]
    reclaim = bar(point + timedelta(minutes=30), 5, 99.8, 101, 98.9, 100.5)
    assert first_balance_boundary_reclaim(
        neutral + [reclaim],
        signal_at=point,
        session_end=point + timedelta(hours=4),
        boundary=100.0,
        boundary_identity="balance",
        direction="LONG",
    ) is None
    routed = first_balance_boundary_reclaim(
        [neutral[0], reclaim],
        signal_at=point,
        session_end=point + timedelta(hours=4),
        boundary=100.0,
        boundary_identity="balance",
        direction="LONG",
    )
    assert routed is not None
    assert routed["within_route_occurrence"] == 2
    assert routed["boundary_identity"] == "balance"


def test_plan_uses_refinement_and_native_bar_freshness() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    event = plan_trigger_event(plan(point))
    assert event is not None
    assert event["timeframe"] == "M5"
    assert event["identity"] == "native-event"
    assert trigger_is_fresh(event, signal_at=point + timedelta(minutes=5))
    assert not trigger_is_fresh(event, signal_at=point + timedelta(minutes=5, seconds=1))


def test_actual_fill_geometry_requires_room_and_whole_ounce() -> None:
    boundary = planned_geometry(
        fill=100.0, stop=98.0, target=103.0, cost_per_ounce=0.1, direction="LONG"
    )
    consumed = planned_geometry(
        fill=102.0, stop=98.0, target=103.0, cost_per_ounce=0.1, direction="LONG"
    )
    oversized = planned_geometry(
        fill=100.0, stop=40.0, target=200.0, cost_per_ounce=0.1, direction="LONG"
    )
    assert boundary["passes_actual_fill_1p5r"] is True
    assert consumed["passes_actual_fill_1p5r"] is False
    assert oversized["passes_whole_ounce_risk"] is False


def test_management_has_no_numeric_break_even_and_retains_initial_stop() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    rows = [
        bar(point, 1, 100.0, 102.5, 99.8, 102.0),
        bar(point + timedelta(minutes=1), 1, 102.0, 102.1, 97.8, 98.2),
    ]
    result = simulate_structural_management(
        classification=classification(),
        stream=stream(rows, point + timedelta(minutes=2)),
        fill_at=iso(point),
        m5_trail_events=[],
        m15_trail_events=[],
    )
    assert result["numeric_break_even_used"] is False
    assert result["resolution"] == "INITIAL_AUCTION_INVALIDATION"
    assert result["structural_stop_changes"] == []


def test_completed_m5_structure_can_advance_stop() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    rows = [
        bar(point, 1, 100.0, 101.5, 99.8, 101.0),
        bar(point + timedelta(minutes=1), 1, 101.0, 101.2, 100.3, 100.5),
    ]
    event = {
        "identity": "trail",
        "break_at": iso(point + timedelta(minutes=1)),
        "protected_level": 100.5,
        "atr": 1.0,
    }
    result = simulate_structural_management(
        classification=classification(),
        stream=stream(rows, point + timedelta(minutes=2)),
        fill_at=iso(point),
        m5_trail_events=[event],
        m15_trail_events=[],
    )
    assert result["resolution"] == "STRUCTURAL_TRAIL_INVALIDATION"
    assert len(result["structural_stop_changes"]) == 1
    assert result["structural_stop_changes"][0]["new_stop"] == 100.4


def test_full_destination_exit_and_stop_first_are_mirrored() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    long_target = simulate_structural_management(
        classification=classification("LONG"),
        stream=stream([bar(point, 1, 100, 104.5, 99.5, 104)], point + timedelta(minutes=1)),
        fill_at=iso(point),
        m5_trail_events=[],
        m15_trail_events=[],
    )
    assert long_target["resolution"] == "EXPLICIT_LIQUIDITY_DESTINATION"
    ambiguous_short = simulate_structural_management(
        classification=classification("SHORT"),
        stream=stream([bar(point, 1, 100, 102.5, 95.5, 96)], point + timedelta(minutes=1)),
        fill_at=iso(point),
        m5_trail_events=[],
        m15_trail_events=[],
    )
    assert ambiguous_short["resolution"] == "INITIAL_AUCTION_INVALIDATION"
