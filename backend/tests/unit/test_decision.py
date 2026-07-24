from dataclasses import replace
from datetime import UTC, datetime, timedelta

from gold_intel.analytics.decision import calculate_seven_layer_decision
from gold_intel.analytics.fundamentals import FundamentalComponent, FundamentalState

AS_OF = datetime(2026, 7, 24, 12, 0, tzinfo=UTC)


def _fundamental() -> FundamentalState:
    components = (
        FundamentalComponent(
            code="REAL_YIELD",
            layer=1,
            direction=1,
            strength=100,
            confidence=90,
            freshness=100,
            data_quality=90,
            weight=15,
            contribution=12.15,
            epistemic_status="CALCULATED",
            explanation="Falling real yield lowers gold's opportunity cost.",
            evidence={"change": -0.2},
        ),
        FundamentalComponent(
            code="USD",
            layer=6,
            direction=-0.5,
            strength=50,
            confidence=80,
            freshness=100,
            data_quality=90,
            weight=12,
            contribution=-4.32,
            epistemic_status="CALCULATED",
            explanation="The dollar is strengthening and pressures gold.",
            evidence={"change": 0.01},
        ),
    )
    return FundamentalState(
        as_of=AS_OF,
        directional_score=7.83,
        confidence=70,
        coverage=27,
        bias_label="SLIGHTLY_BULLISH",
        regime_label="PARTIAL_RATES_USD_SUPPORTIVE",
        reaction_function="BASE",
        dominant_driver="REAL_YIELD",
        main_contradiction="The dollar is strengthening and pressures gold.",
        event_risk="LOW",
        upcoming_catalyst=None,
        components=components,
        layers=(),
        reasoning={
            "missing_drivers": ["FED_PATH"],
            "crowding": {"state": "BALANCED", "percentile": 50},
            "contradictions": [],
            "weight_profile": "BASE",
            "effective_weights": {"REAL_YIELD": 15, "USD": 12},
        },
        data_hash="f" * 64,
    )


def _coverage(*, account_known: bool = False) -> dict[str, object]:
    factors: list[dict[str, object]] = [
        {
            "code": "SCHEDULED_EVENT_CALENDAR",
            "layer": 4,
            "current_epistemic_status": "OBSERVED",
            "freshness_status": "FRESH",
            "usable_now": True,
        }
    ]
    for code in ("PORTFOLIO_CLUSTER_RISK", "TOTAL_OPEN_RISK", "DAILY_LOSS_STATUS"):
        factors.append(
            {
                "code": code,
                "layer": 7,
                "current_epistemic_status": (
                    "CALCULATED" if account_known else "UNKNOWN"
                ),
                "freshness_status": "FRESH" if account_known else "UNKNOWN",
                "usable_now": account_known,
            }
        )
    layers = [
        {
            "layer": number,
            "factor_count": 10,
            "known_factor_count": 5,
            "usable_factor_count": 5,
            "book_coverage_pct": 50,
            "book_usable_coverage_pct": 50,
            "phase1_coverage_pct": 75,
        }
        for number in range(1, 8)
    ]
    return {
        "registry_hash": "r" * 64,
        "phase1_coverage_pct": 75,
        "book_factor_coverage_pct": 50,
        "book_usable_coverage_pct": 50,
        "layers": layers,
        "factors": factors,
    }


def _structure(*, stale: bool = False) -> dict[str, object]:
    detected_at = AS_OF - timedelta(minutes=5)
    return {
        "provider_code": "IC_MARKETS_MT5",
        "as_of": AS_OF,
        "latest_bar_at": AS_OF,
        "source_staleness_seconds": 3_600 if stale else 0,
        "data_hash": "s" * 64,
        "session": {
            "primary": "LONDON_NEW_YORK_OVERLAP",
            "special_windows": [],
        },
        "liquidity": {
            "status": "NORMAL",
            "execution_confidence_multiplier": 1,
        },
        "timeframes": [
            {
                "timeframe": "5m",
                "trend": "BULLISH",
                "last_close": 2_405,
                "support": 2_395,
                "resistance": 2_400,
                "range_low": 2_390,
                "range_high": 2_420,
                "detections": [
                    {
                        "kind": "ACCEPTANCE_ABOVE_RESISTANCE",
                        "direction": "BULLISH",
                        "detected_at": detected_at,
                        "timestamp": detected_at,
                        "price_level": 2_400,
                        "timeframe": "5m",
                        "epistemic_status": "INFERRED",
                    }
                ],
            },
            {
                "timeframe": "1h",
                "trend": "BULLISH",
                "last_close": 2_405,
                "support": 2_380,
                "resistance": 2_430,
                "range_low": 2_370,
                "range_high": 2_440,
                "detections": [],
            },
        ],
    }


def test_direction_and_execution_gates_remain_separate() -> None:
    decision = calculate_seven_layer_decision(
        _fundamental(),
        structure=_structure(),
        coverage=_coverage(),
    )

    assert decision.directional_score == 7.83
    assert decision.bullish_score == 12.15
    assert decision.bearish_score == 4.32
    assert decision.neutral_conflict_score > 0
    assert decision.execution_state == "WAIT_INSUFFICIENT_DIRECTIONAL_COVERAGE"
    assert decision.execution_plan["trigger"]["state"] == "CONFIRMED"
    assert decision.execution_plan["is_trade_instruction"] is False
    assert decision.layers[4].role == "EXECUTION_GATE"
    assert decision.layers[6].role == "EXECUTION_GATE"


def test_confirmed_setup_still_waits_when_account_risk_is_unknown() -> None:
    fundamental = _fundamental()
    fundamental = replace(fundamental, coverage=60)
    decision = calculate_seven_layer_decision(
        fundamental,
        structure=_structure(),
        coverage=_coverage(account_known=False),
    )

    assert decision.execution_state == "WAIT_ACCOUNT_RISK_STATE_UNKNOWN"
    assert (
        decision.execution_plan["risk"]["suggested_position_size_lots"]
        is None
    )
    assert decision.execution_plan["risk"]["total_open_risk"] == "UNKNOWN"


def test_stale_price_blocks_execution_without_changing_macro_direction() -> None:
    decision = calculate_seven_layer_decision(
        _fundamental(),
        structure=_structure(stale=True),
        coverage=_coverage(account_known=True),
    )

    assert decision.directional_score == 7.83
    assert decision.execution_confidence == 0
    assert decision.execution_state == "WAIT_STALE_OR_MISSING_PRICE"


def test_missing_evidence_is_coverage_not_neutrality() -> None:
    empty = FundamentalState(
        as_of=AS_OF,
        directional_score=0,
        confidence=0,
        coverage=0,
        bias_label="NEUTRAL_OR_CONFLICTED",
        regime_label="PARTIAL_RATES_USD_MIXED",
        reaction_function="UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE",
        dominant_driver=None,
        main_contradiction=None,
        event_risk="UNKNOWN",
        upcoming_catalyst=None,
        components=(),
        layers=(),
        reasoning={
            "missing_drivers": [],
            "crowding": {"state": "UNKNOWN"},
            "contradictions": [],
        },
        data_hash="e" * 64,
    )
    decision = calculate_seven_layer_decision(
        empty,
        structure=None,
        coverage={
            "registry_hash": "r" * 64,
            "phase1_coverage_pct": 0,
            "book_factor_coverage_pct": 0,
            "book_usable_coverage_pct": 0,
            "layers": [],
            "factors": [],
        },
    )

    assert decision.neutral_conflict_score == 0
    assert decision.directional_evidence_coverage_pct == 0
    assert decision.execution_state == "WAIT_STALE_OR_MISSING_PRICE"
