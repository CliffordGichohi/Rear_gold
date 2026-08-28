from gold_intel.analytics.auction_direction_symmetry_v1 import (
    directional_fill,
    directional_geometry,
    mirror_feature_row,
    orient_feature_row,
)


def test_feature_mirror_is_an_exact_involution() -> None:
    row = {
        "checkpoint_at": "2022-01-03T14:00:00Z",
        "session": "NEW_YORK",
        "15m_return_3_atr": 0.75,
        "15m_swing_range_position": 0.2,
        "15m_candle_direction": "BULLISH",
        "15m_trend": "BEARISH",
        "15m_latest_high_age_minutes": 30.0,
        "15m_latest_low_age_minutes": 45.0,
        "15m_close_below_latest_high_atr": 0.4,
        "15m_close_above_latest_low_atr": 1.2,
        "15m_bullish_break_age_minutes": 5.0,
        "15m_bearish_break_age_minutes": 20.0,
        "bull_active_v3_state_count": 2,
        "bear_active_v3_state_count": 1,
        "long_event_locked": False,
        "short_event_locked": True,
        "long_macro_state": "ALIGNED",
        "short_macro_state": "OPPOSED",
    }

    mirrored = mirror_feature_row(row)

    assert mirrored["15m_return_3_atr"] == -0.75
    assert mirrored["15m_swing_range_position"] == 0.8
    assert mirrored["15m_candle_direction"] == "BEARISH"
    assert mirrored["15m_trend"] == "BULLISH"
    assert mirrored["15m_latest_low_age_minutes"] == 30.0
    assert mirrored["15m_latest_high_age_minutes"] == 45.0
    assert mirrored["15m_bearish_break_age_minutes"] == 5.0
    assert mirrored["15m_bullish_break_age_minutes"] == 20.0
    assert mirrored["bear_active_v3_state_count"] == 2
    assert mirrored["bull_active_v3_state_count"] == 1
    assert mirrored["long_event_locked"] is True
    assert mirrored["short_event_locked"] is False
    assert mirrored["long_macro_state"] == "OPPOSED"
    assert mirrored["short_macro_state"] == "ALIGNED"
    assert mirror_feature_row(mirrored) == row
    assert orient_feature_row(row, "LONG") == row
    assert orient_feature_row(row, "SHORT") == mirrored


def test_geometry_and_execution_costs_are_symmetric() -> None:
    long_stop, long_target = directional_geometry(
        reference=2000.0,
        atr=10.0,
        stop_distance_atr=0.5,
        target_distance_atr=1.5,
        direction="LONG",
    )
    short_stop, short_target = directional_geometry(
        reference=2000.0,
        atr=10.0,
        stop_distance_atr=0.5,
        target_distance_atr=1.5,
        direction="SHORT",
    )

    assert (long_stop, long_target) == (1995.0, 2015.0)
    assert (short_stop, short_target) == (2005.0, 1985.0)
    assert directional_fill(
        mid_open=2000.0, spread_price=0.2, slippage=0.05, direction="LONG"
    ) == 2000.15
    assert directional_fill(
        mid_open=2000.0, spread_price=0.2, slippage=0.05, direction="SHORT"
    ) == 1999.85
