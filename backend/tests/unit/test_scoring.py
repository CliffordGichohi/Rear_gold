from datetime import UTC, datetime

from gold_intel.analytics.scoring import calculate_partial_score
from gold_intel.domain.signals import SignalResult


def make_signal(driver: str, direction: float, status: str = "CALCULATED") -> SignalResult:
    now = datetime(2026, 7, 17, tzinfo=UTC)
    return SignalResult(
        name=driver,
        layer=6 if driver == "REAL_YIELD" else 7,
        driver=driver,
        epistemic_status=status,  # type: ignore[arg-type]
        direction=direction,
        strength=100,
        confidence=100,
        freshness=100,
        data_quality=100,
        explanation="test",
        observed_at=now,
        available_at=now,
    )


def test_partial_score_is_bounded_and_coverage_is_explicit() -> None:
    result = calculate_partial_score(
        [make_signal("REAL_YIELD", 1), make_signal("PRICE_CONFIRMATION", 1)],
        session_name="LONDON",
    )
    assert result.overall_score == 30
    assert result.coverage == 30
    assert result.execution_state == "ARMED"
    assert -100 <= result.overall_score <= 100


def test_unknown_signal_does_not_become_neutral_evidence() -> None:
    result = calculate_partial_score(
        [make_signal("REAL_YIELD", 0, "UNKNOWN")], session_name="LONDON"
    )
    assert result.coverage == 0
    assert result.execution_state == "NOT_ACTIONABLE"
