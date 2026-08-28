from __future__ import annotations

from datetime import UTC, datetime, timedelta

from gold_intel.analytics.liquidity_shift_v3 import (
    build_persistent_liquidity_shift_study_v3,
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
    start = datetime(2024, 1, 8, tzinfo=UTC)
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
        m15.append(
            _bar(start + timedelta(minutes=15 * index), 15, *values, f"m15-{index}")
        )

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

    m1 = [
        _bar(
            start + timedelta(minutes=index),
            1,
            109.0,
            109.1,
            108.9,
            109.0,
            f"m1-{index}",
        )
        for index in range(36 * 15)
    ]
    return {"1m": m1, "5m": m5, "15m": m15, "1h": [], "4h": []}


def test_persistent_state_emits_repeated_causal_m5_impulses() -> None:
    bars = _scenario()

    study = build_persistent_liquidity_shift_study_v3(bars)

    assert len(study.states) == 1
    state = study.states[0]
    assert state.terminal_at == state.started_at + timedelta(hours=36)
    assert len(study.impulses) >= 2
    assert all(
        state.started_at < impulse.detected_at <= state.terminal_at
        for impulse in study.impulses
    )
    impulse_by_id = {impulse.identity: impulse for impulse in study.impulses}
    assert len(study.entry_intents) == 2 * len(study.impulses)
    assert all(
        intent.order_at == impulse_by_id[intent.impulse_identity].detected_at
        for intent in study.entry_intents
    )
    assert all(
        intent.triggered_at is None or intent.triggered_at >= intent.order_at
        for intent in study.entry_intents
    )


def test_cutoff_cannot_reveal_post_transition_impulses() -> None:
    bars = _scenario()
    full = build_persistent_liquidity_shift_study_v3(bars)
    cutoff = full.states[0].started_at

    truncated = build_persistent_liquidity_shift_study_v3(bars, cutoff=cutoff)

    assert truncated.states
    assert truncated.impulses == ()
    assert truncated.entry_intents == ()


def test_persistent_study_is_exactly_deterministic() -> None:
    bars = _scenario()

    primary = build_persistent_liquidity_shift_study_v3(bars)
    reference = build_persistent_liquidity_shift_study_v3(bars)

    assert primary == reference
