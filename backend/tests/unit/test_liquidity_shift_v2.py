from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gold_intel.analytics.liquidity_shift_v2 import (
    LiquidityPivotV2,
    build_liquidity_shift_study_v2,
    latest_swing_range_at,
    trend_state_at,
)
from gold_intel.analytics.structure import AggregateBar


def _bar(
    opened: datetime,
    minutes: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    identity: str,
) -> AggregateBar:
    return AggregateBar(
        open_time=opened,
        close_time=opened + timedelta(minutes=minutes),
        open=open_price,
        high=high,
        low=low,
        close=close,
        volume=1.0,
        complete=True,
        source_ids=(identity,),
    )


def _scenario() -> dict[str, list[AggregateBar]]:
    start = datetime(2024, 1, 8, 0, 0, tzinfo=UTC)
    m15: list[AggregateBar] = []
    specifications: dict[int, tuple[float, float, float, float]] = {
        10: (100.0, 105.0, 99.5, 100.5),
        17: (101.0, 101.2, 99.0, 100.0),
        18: (100.0, 108.0, 99.5, 107.5),
        19: (107.0, 107.2, 104.0, 105.0),
        20: (105.0, 106.0, 104.0, 105.0),
        21: (105.0, 106.0, 104.0, 105.0),
        22: (105.0, 106.0, 99.8, 104.0),
        23: (104.0, 110.5, 103.5, 110.0),
        24: (110.0, 110.2, 104.8, 108.5),
        25: (108.5, 111.5, 107.5, 111.0),
    }
    for index in range(36):
        default_close = 100.2 if index % 2 == 0 else 99.8
        values = specifications.get(index, (100.0, 101.0, 99.0, default_close))
        m15.append(_bar(start + timedelta(minutes=15 * index), 15, *values, f"m15-{index}"))

    m5: list[AggregateBar] = []
    for index, source in enumerate(m15):
        for sub in range(3):
            opened = source.open_time + timedelta(minutes=5 * sub)
            fraction = sub / 3
            next_fraction = (sub + 1) / 3
            open_price = source.open + (source.close - source.open) * fraction
            close = source.open + (source.close - source.open) * next_fraction
            high = max(open_price, close)
            low = min(open_price, close)
            if index == 22 and sub == 0:
                open_price, high, low, close = 105.0, 105.0, 99.8, 102.0
            elif index == 22 and sub == 1:
                open_price, high, low, close = 102.0, 104.5, 101.8, 104.0
            elif index == 24 and sub == 0:
                open_price, high, low, close = 110.0, 110.1, 105.0, 106.0
            elif index == 24 and sub == 1:
                open_price, high, low, close = 106.0, 108.0, 105.5, 107.8
            elif index == 24 and sub == 2:
                open_price, high, low, close = 107.8, 109.5, 107.6, 109.2
            m5.append(_bar(opened, 5, open_price, high, low, close, f"m5-{index}-{sub}"))

    m1: list[AggregateBar] = []
    total_minutes = 36 * 15
    for index in range(total_minutes):
        opened = start + timedelta(minutes=index)
        price = 109.0
        high = 109.1
        low = 108.9
        if opened == start + timedelta(minutes=15 * 24 + 1):
            price, high, low = 106.0, 106.1, 104.9
        m1.append(_bar(opened, 1, price, high, low, price, f"m1-{index}"))
    return {"1m": m1, "5m": m5, "15m": m15, "1h": [], "4h": []}


def test_causal_sequence_requires_zone_contact_before_transition() -> None:
    bars = _scenario()
    study = build_liquidity_shift_study_v2(bars)

    bullish = [zone for zone in study.zones if zone.direction == "BULLISH"]
    assert bullish
    zone = bullish[0]
    assert zone.detected_at == bars["15m"][18].close_time
    contact = next(item for item in study.contacts if item.zone_identity == zone.identity)
    transition = next(item for item in study.transitions if item.contact_identity == contact.identity)
    assert zone.detected_at < contact.contact_at < contact.reaction_at <= transition.transition_at
    assert transition.direction == "BULLISH"
    assert transition.retracement_lower < transition.half_retrace < transition.retracement_upper


def test_half_retrace_and_confirmation_are_separate_point_in_time_intents() -> None:
    study = build_liquidity_shift_study_v2(_scenario())
    intents = [item for item in study.entry_intents if item.direction == "BULLISH"]
    families = {item.family for item in intents}

    assert "SHIFT_HALF_RETRACE_LIMIT_V2" in families
    assert "SHIFT_M5_STRUCTURE_CONFIRMATION_V2" in families
    limit = next(item for item in intents if item.family == "SHIFT_HALF_RETRACE_LIMIT_V2")
    confirmation = next(
        item for item in intents if item.family == "SHIFT_M5_STRUCTURE_CONFIRMATION_V2"
    )
    assert limit.order_at < limit.triggered_at  # type: ignore[operator]
    assert confirmation.order_at < confirmation.triggered_at  # type: ignore[operator]
    assert limit.stop_distance_atr > 0
    assert confirmation.stop_distance_atr > 0


def test_cutoff_prevents_future_transition_from_appearing() -> None:
    bars = _scenario()
    cutoff = bars["15m"][22].close_time
    study = build_liquidity_shift_study_v2(bars, cutoff=cutoff)

    assert study.zones
    assert study.contacts
    assert study.transitions == ()
    assert study.entry_intents == ()


def test_trend_and_range_use_only_detected_pivots() -> None:
    start = datetime(2024, 1, 1, tzinfo=UTC)
    pivots = [
        LiquidityPivotV2("h1", "1h", "HIGH", start, start + timedelta(hours=2), 100, 1, 1, 1),
        LiquidityPivotV2("l1", "1h", "LOW", start, start + timedelta(hours=2), 90, 1, 1, 2),
        LiquidityPivotV2("h2", "1h", "HIGH", start, start + timedelta(hours=4), 105, 1, 1, 3),
        LiquidityPivotV2("l2", "1h", "LOW", start, start + timedelta(hours=4), 95, 1, 1, 4),
    ]

    assert trend_state_at(pivots, start + timedelta(hours=3)) == "UNKNOWN"
    assert trend_state_at(pivots, start + timedelta(hours=5)) == "BULLISH"
    assert latest_swing_range_at(pivots, start + timedelta(hours=5)) == (95, 105)
