from __future__ import annotations

import math

from gold_intel.analytics.continuation_true_negation_attribution_v1 import (
    analyse_track,
    assign_run_ordinals,
    break_distance_bin,
    decision_phase,
    macro_alignment,
    planned_r_bin,
    result_sign,
    structure_state,
)


def _bar(minute: str, *, open_price: float, high: float, low: float, close: float) -> dict:
    hour, minute_value = minute.split(":")
    total = int(hour) * 60 + int(minute_value)
    close_total = total + 1
    close_hour, close_minute = divmod(close_total, 60)
    return {
        "open_at": f"2022-01-03T{minute}:00Z",
        "close_at": f"2022-01-03T{close_hour:02d}:{close_minute:02d}:00Z",
        "available_at": f"2022-01-03T{close_hour:02d}:{close_minute:02d}:00Z",
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "spread_price": 0.0,
        "complete": True,
    }


def _result(*, resolution: str, exit_at: str, raw_exit: float, actual_exit: float, net: float) -> dict:
    return {
        "event_identity": "synthetic",
        "direction": "LONG",
        "entry": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "structural": {"resolution": "STOP_FIRST" if resolution == "STOPPED" else "TARGET_FIRST"},
        "execution": {
            "resolution": resolution,
            "fill_at": "2022-01-03T15:01:00Z",
            "exit_at": exit_at,
            "deadline": "2022-01-03T17:00:00Z",
            "actual_fill": 100.1,
            "raw_fill": 100.0,
            "raw_exit": raw_exit,
            "actual_exit": actual_exit,
            "quantity_ounces": 10,
            "net_pnl_usd": net,
            "ambiguous_stop_first": False,
        },
    }


def test_frozen_sign_bins_structure_macro_and_dst_phase():
    assert result_sign(1.0) == "WIN"
    assert result_sign(-1.0) == "LOSS"
    assert result_sign(1e-13) == "SCRATCH"
    assert planned_r_bin(0.5) == "0.5-1.0"
    assert planned_r_bin(2.0) == ">=2.0"
    assert break_distance_bin(1.0) == "1-2"
    assert structure_state({"swing_relations": {"high": "HH", "low": "HL"}}) == "UP_TREND"
    assert structure_state({"swing_relations": {"high": "LH", "low": "HL"}}) == "MIXED_OR_RANGE"
    assert macro_alignment({"state": "BULLISH"}, "LONG") == "ALIGNED"
    assert macro_alignment({"state": "BEARISH"}, "LONG") == "CONTRADICTED"
    assert decision_phase("2022-01-03T15:00:00Z") == "09:30-10:30"


def test_stop_then_target_is_distinguished_from_entry_reclaim_and_confirmation():
    stopped = _result(
        resolution="STOPPED",
        exit_at="2022-01-03T15:03:00Z",
        raw_exit=98.0,
        actual_exit=97.9,
        net=-22.0,
    )
    prefix = [
        _bar("15:01", open_price=100.0, high=101.0, low=99.0, close=100.0),
        _bar("15:02", open_price=100.0, high=100.2, low=97.9, close=98.0),
    ]
    target = analyse_track(
        stopped,
        prefix + [_bar("15:03", open_price=98.0, high=104.1, low=97.8, close=104.0)],
    )
    reclaim = analyse_track(
        stopped,
        prefix + [_bar("15:03", open_price=98.0, high=100.1, low=97.8, close=100.0)],
    )
    confirmed = analyse_track(
        stopped,
        prefix + [_bar("15:03", open_price=98.0, high=99.0, low=96.0, close=97.0)],
    )
    assert target["stopped_disposition"] == "STOP_THEN_TARGET"
    assert reclaim["stopped_disposition"] == "STOP_THEN_ENTRY_RECLAIM"
    assert confirmed["stopped_disposition"] == "STOP_CONFIRMED_TO_DEADLINE"


def test_target_exit_reports_post_target_extension_and_deadline_difference():
    target_result = _result(
        resolution="TARGET_HIT",
        exit_at="2022-01-03T15:03:00Z",
        raw_exit=104.0,
        actual_exit=104.0,
        net=39.0,
    )
    rows = [
        _bar("15:01", open_price=100.0, high=101.0, low=99.5, close=100.5),
        _bar("15:02", open_price=100.5, high=104.1, low=100.4, close=104.0),
        _bar("15:03", open_price=104.0, high=106.2, low=103.8, close=106.0),
    ]
    audit = analyse_track(target_result, rows)
    assert math.isclose(audit["post_exit_extension_usd"], 22.0)
    assert math.isclose(audit["deadline_exit_net_pnl_usd"], 58.5)
    assert math.isclose(audit["deadline_minus_actual_usd"], 19.5)


def test_run_ordinals_reset_on_direction_change_and_new_day():
    def row(identity: str, day: str, minute: str, direction: str) -> dict:
        return {
            "event_identity": identity,
            "trading_date_utc": day,
            "decision_at": f"{day}T{minute}:00Z",
            "direction": direction,
            "event_class": "CONTINUATION_REFRESH",
            "mechanically_executable": True,
        }

    assigned = assign_run_ordinals(
        [
            row("a", "2022-01-03", "14:00", "LONG"),
            row("b", "2022-01-03", "14:05", "LONG"),
            row("c", "2022-01-03", "14:10", "SHORT"),
            row("d", "2022-01-04", "14:00", "SHORT"),
        ]
    )
    assert assigned["a"]["continuation_ordinal_in_run"] == 1
    assert assigned["b"]["continuation_ordinal_in_run"] == 2
    assert assigned["c"]["continuation_ordinal_in_run"] == 1
    assert assigned["d"]["continuation_ordinal_in_run"] == 1
