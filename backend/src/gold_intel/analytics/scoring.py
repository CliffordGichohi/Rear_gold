from __future__ import annotations

from typing import Any

from gold_intel.domain.signals import ScoreResult, SignalResult, clamp

DRIVER_BUDGETS = {"REAL_YIELD": 0.20, "PRICE_CONFIRMATION": 0.10}


def calculate_partial_score(signals: list[SignalResult], *, session_name: str) -> ScoreResult:
    contributions: list[dict[str, Any]] = []
    available_budget = 0.0
    bullish = 0.0
    bearish = 0.0

    for signal in signals:
        budget = DRIVER_BUDGETS.get(signal.driver, 0.0)
        available = signal.epistemic_status != "UNKNOWN"
        if available:
            available_budget += budget
        contribution = (
            budget * signal.direction * signal.strength * signal.certainty if available else 0.0
        )
        bullish += max(0.0, contribution)
        bearish += max(0.0, -contribution)
        contributions.append(
            {
                "signal_id": str(signal.id),
                "name": signal.name,
                "driver": signal.driver,
                "budget": budget,
                "certainty": round(signal.certainty, 6),
                "contribution": round(contribution, 3),
                "available": available,
                "formula": "budget × direction × strength × confidence × freshness × data_quality",
            }
        )

    overall = clamp(bullish - bearish, -100, 100)
    coverage = clamp(available_budget * 100, 0, 100)
    activity = min(100.0, bullish + bearish)
    neutrality = max(0.0, 100.0 - activity)
    conflict = (
        200 * min(bullish, bearish) / (bullish + bearish) if bullish > 0 and bearish > 0 else 0.0
    )
    eligible = [signal for signal in signals if signal.epistemic_status != "UNKNOWN"]
    average_certainty = (
        sum(signal.certainty for signal in eligible) / len(eligible) * 100 if eligible else 0.0
    )
    confidence = min(coverage, average_certainty * available_budget)
    dominant = max(contributions, key=lambda item: abs(float(item["contribution"])), default=None)
    opposing = [item for item in contributions if float(item["contribution"]) * overall < 0]
    contradiction = max(opposing, key=lambda item: abs(float(item["contribution"])), default=None)
    acceptance = next((signal for signal in signals if signal.driver == "PRICE_CONFIRMATION"), None)
    execution_state = (
        "ARMED"
        if acceptance
        and acceptance.direction > 0
        and acceptance.epistemic_status != "UNKNOWN"
        and overall > 0
        else "WAIT"
        if eligible
        else "NOT_ACTIONABLE"
    )

    return ScoreResult(
        overall_score=round(overall, 3),
        bullish_score=round(bullish, 3),
        bearish_score=round(bearish, 3),
        neutrality_score=round(neutrality, 3),
        conflict_score=round(conflict, 3),
        confidence=round(confidence, 3),
        coverage=round(coverage, 3),
        bias_label=_bias_label(overall),
        execution_state=execution_state,
        dominant_driver=str(dominant["driver"]) if dominant and dominant["contribution"] else None,
        main_contradiction=str(contradiction["name"]) if contradiction else None,
        contributions=contributions,
        layers=_layer_statuses(signals, session_name),
        reasoning={
            "summary": _summary(overall, signals),
            "session": session_name,
            "confirmation_requirement": "Two complete 5m closes above buffered resistance.",
            "invalidation_requirement": "Gold loses accepted support while real yield reverses higher.",
            "confidence_is_probability_of_profit": False,
        },
    )


def _bias_label(score: float) -> str:
    if score >= 20:
        return "MODERATELY_BULLISH"
    if score >= 5:
        return "SLIGHTLY_BULLISH"
    if score <= -20:
        return "MODERATELY_BEARISH"
    if score <= -5:
        return "SLIGHTLY_BEARISH"
    return "NEUTRAL_OR_CONFLICTED"


def _layer_statuses(signals: list[SignalResult], session_name: str) -> list[dict[str, object]]:
    by_layer = {signal.layer: signal for signal in signals}
    names = {
        1: "MARKET_REGIME",
        2: "EXPECTATIONS_AND_PRICING",
        3: "POSITIONING",
        4: "CATALYSTS",
        5: "SESSIONS_AND_LIQUIDITY",
        6: "CROSS_MARKET",
        7: "EXECUTION_AND_RISK",
    }
    rows: list[dict[str, object]] = []
    for layer in range(1, 8):
        signal = by_layer.get(layer)
        if layer == 5:
            status = "PARTIAL"
            summary = f"Current session: {session_name}; liquidity inputs unavailable."
        elif signal and signal.epistemic_status != "UNKNOWN":
            status = "PARTIAL"
            summary = signal.explanation
        else:
            status = "UNKNOWN"
            summary = signal.explanation if signal else "Required Phase 1 inputs are unavailable."
        rows.append({"number": layer, "name": names[layer], "status": status, "summary": summary})
    return rows


def _summary(score: float, signals: list[SignalResult]) -> str:
    known = [signal.explanation for signal in signals if signal.epistemic_status != "UNKNOWN"]
    if not known:
        return "No eligible evidence is available; directional bias is not actionable."
    direction = "bullish" if score > 0 else "bearish" if score < 0 else "neutral"
    return f"The partial evidence set is {direction}. " + " ".join(known)
