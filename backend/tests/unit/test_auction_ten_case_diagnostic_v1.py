from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_ten_case_diagnostic_v1 import (
    management_overlay,
    outcome_attribution,
    preentry_features,
)


def _result(net: float, mfe: float, direction: str = "LONG") -> dict:
    return {
        "direction": direction,
        "execution": {
            "net_r50": net,
            "mfe_r": mfe,
            "mae_r": 0.5,
            "fill_at": "2022-01-03T08:00:00Z",
            "exit_at": "2022-01-03T08:20:00Z",
            "actual_fill": 100.0,
            "fill_spread": 0.2,
        },
    }


def _plan(direction: str = "LONG") -> dict:
    return {
        "event_identity": "event-1",
        "case_alias": "case-1",
        "decision_at": "2022-01-03T08:00:00Z",
        "direction": direction,
        "session": "LONDON",
        "context_family": "TREND_PULLBACK_WITH_LTF_CONTROL",
        "event_class": "CONTINUATION_REFRESH",
        "entry": 100.0,
        "stop": 98.0 if direction == "LONG" else 102.0,
        "planned_r": 2.0,
        "target": {"level": 105.0 if direction == "LONG" else 95.0, "timeframe": "H1"},
        "protected_pivot": {"timeframe": "M5"},
        "broken_control": {"atr": 1.0},
        "distance_from_m5_break_atr": 0.25,
        "local_m15_liquidity": {"distance_price": 3.0},
        "macro_context": {"score": -20.0, "confidence": 70.0, "state": "BEARISH", "dominant_driver": "REAL_YIELD"},
        "higher_timeframe_context": {
            "H1": {"range_location": 0.4, "swing_relations": {"high": "HH", "low": "HL"}},
            "H4": {"range_location": 0.6, "swing_relations": {"high": "LH", "low": "LL"}},
        },
    }


def _bar(point: datetime, minutes: int, open_: float, high: float, low: float, close: float) -> dict:
    return {
        "open_at": point.isoformat().replace("+00:00", "Z"),
        "close_at": (point + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        "available_at": (point + timedelta(minutes=minutes)).isoformat().replace("+00:00", "Z"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "spread_price": 0.2,
    }


def test_outcome_categories_are_frozen() -> None:
    assert outcome_attribution(_result(1.0, 1.2))["category"] == "MONETIZED_SUCCESS"
    assert outcome_attribution(_result(-1.0, 1.0))["category"] == "DIRECTIONALLY_USEFUL_UNMONETIZED"
    assert outcome_attribution(_result(-1.0, 0.99))["category"] == "NO_MEANINGFUL_FAVOURABLE_AUCTION"


def test_preentry_macro_alignment_is_direction_symmetric() -> None:
    long = preentry_features(_plan("LONG"))
    short = preentry_features(_plan("SHORT"))
    assert long["macro_alignment_score"] == -20.0
    assert short["macro_alignment_score"] == 20.0
    assert long["risk_in_break_atr"] == short["risk_in_break_atr"] == 2.0


def test_completed_m5_one_r_activation_saves_long_loss() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    m5 = [_bar(point, 5, 100, 103, 99.5, 102.1)]
    m1 = [
        _bar(point, 1, 100, 101, 99.5, 100.5),
        _bar(point + timedelta(minutes=5), 1, 102.1, 103, 99.5, 100),
    ]
    primary = management_overlay(plan=_plan("LONG"), result=_result(-1.0, 1.2), m1_rows=m1, m5_rows=m5, implementation="primary")
    reference = management_overlay(plan=_plan("LONG"), result=_result(-1.0, 1.2), m1_rows=m1, m5_rows=m5, implementation="reference")
    assert primary == reference
    assert primary["changed"] is True
    assert primary["effective_r50"] == 0.0
    assert primary["saved_loss"] is True


def test_completed_m5_one_r_activation_is_short_symmetric() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    m5 = [_bar(point, 5, 100, 100.5, 97, 97.9)]
    m1 = [
        _bar(point, 1, 100, 100.5, 99, 99.5),
        _bar(point + timedelta(minutes=5), 1, 97.9, 100.5, 97, 100),
    ]
    primary = management_overlay(plan=_plan("SHORT"), result=_result(-1.0, 1.2, "SHORT"), m1_rows=m1, m5_rows=m5, implementation="primary")
    reference = management_overlay(plan=_plan("SHORT"), result=_result(-1.0, 1.2, "SHORT"), m1_rows=m1, m5_rows=m5, implementation="reference")
    assert primary == reference
    assert primary["changed"] is True


def test_target_before_activation_is_unchanged() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    m5 = [_bar(point, 5, 100, 106, 99.5, 102.1)]
    m1 = [_bar(point + timedelta(minutes=1), 1, 100, 105.5, 99.5, 105)]
    primary = management_overlay(plan=_plan("LONG"), result=_result(2.0, 2.5), m1_rows=m1, m5_rows=m5, implementation="primary")
    reference = management_overlay(plan=_plan("LONG"), result=_result(2.0, 2.5), m1_rows=m1, m5_rows=m5, implementation="reference")
    assert primary == reference
    assert primary["changed"] is False
    assert primary["effective_r50"] == 2.0
