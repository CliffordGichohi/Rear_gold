from datetime import UTC, datetime, timedelta
from uuid import uuid4

from gold_intel.analytics.real_yield import RealYieldPoint, calculate_real_yield_impulse

UTC = UTC


def test_falling_real_yield_is_bullish_and_future_revision_is_excluded() -> None:
    as_of = datetime(2026, 7, 17, 16, tzinfo=UTC)
    points = [
        RealYieldPoint(
            id=uuid4(),
            observation_time=as_of - timedelta(days=6 - index),
            available_at=as_of - timedelta(days=6 - index, hours=-1),
            value_percent=2.15 - index * 0.03,
            vintage="initial",
        )
        for index in range(6)
    ]
    points.append(
        RealYieldPoint(
            id=uuid4(),
            observation_time=points[-2].observation_time,
            available_at=as_of + timedelta(minutes=1),
            value_percent=4.0,
            vintage="future-revision",
        )
    )

    signal = calculate_real_yield_impulse(points, as_of)

    assert signal.epistemic_status == "CALCULATED"
    assert signal.direction > 0
    assert signal.evidence["delta_bp"] == -15.0


def test_stale_real_yield_becomes_unknown() -> None:
    as_of = datetime(2026, 7, 17, tzinfo=UTC)
    points = [
        RealYieldPoint(
            id=uuid4(),
            observation_time=as_of - timedelta(days=30 - index),
            available_at=as_of - timedelta(days=30 - index),
            value_percent=2.0,
            vintage="initial",
        )
        for index in range(6)
    ]
    assert calculate_real_yield_impulse(points, as_of).epistemic_status == "UNKNOWN"
