from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping
from dataclasses import asdict, dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Literal

from gold_intel.analytics.fundamentals import FundamentalComponent, FundamentalState
from gold_intel.domain.rulesets import BOOK_RULESET_VERSION
from gold_intel.domain.signals import clamp

DECISION_RULESET_VERSION = f"{BOOK_RULESET_VERSION}-decision-v1"
MINIMUM_DIRECTIONAL_SCORE = 5.0
MINIMUM_DIRECTIONAL_COVERAGE = 35.0
MINIMUM_DIRECTIONAL_CONFIDENCE = 25.0
MAX_LIVE_PRICE_AGE_SECONDS = 15 * 60
TRIGGER_MAX_AGE_MINUTES = 30

LayerRole = Literal["DIRECTIONAL", "EXECUTION_GATE"]

LAYER_NAMES: dict[int, str] = {
    1: "MARKET_REGIME",
    2: "EXPECTATIONS_AND_PRICING",
    3: "POSITIONING_AND_INSTITUTIONAL_BEHAVIOUR",
    4: "CATALYSTS_AND_EVENT_RISK",
    5: "SESSIONS_AND_LIQUIDITY",
    6: "CROSS_MARKET_CONFIRMATION",
    7: "EXECUTION_AND_RISK",
}


@dataclass(frozen=True, slots=True)
class LayerAssessment:
    number: int
    name: str
    role: LayerRole
    status: str
    operational_status: str
    book_factor_count: int
    known_factor_count: int
    usable_factor_count: int
    book_coverage_pct: float
    phase1_coverage_pct: float
    directional_contribution: float | None
    confidence: float | None
    summary: str
    supporting_evidence: tuple[str, ...]
    contradicting_evidence: tuple[str, ...]
    unknown_factors: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SevenLayerDecision:
    as_of: datetime
    epistemic_status: Literal["INFERRED"]
    directional_score: float
    bullish_score: float
    bearish_score: float
    neutral_conflict_score: float
    directional_confidence: float
    execution_confidence: float
    directional_evidence_coverage_pct: float
    phase1_factor_coverage_pct: float
    book_factor_coverage_pct: float
    book_usable_coverage_pct: float
    bias: str
    regime: str
    reaction_function: str
    dominant_driver: str | None
    main_contradiction: str | None
    highest_risk_assumption: str
    upcoming_catalyst: dict[str, Any] | None
    event_risk: str
    current_session: str
    liquidity_state: str
    price_macro_alignment: str
    execution_state: str
    layers: tuple[LayerAssessment, ...]
    components: tuple[FundamentalComponent, ...]
    execution_plan: dict[str, Any]
    reasoning: dict[str, Any]
    fundamental_data_hash: str
    structure_data_hash: str | None
    registry_hash: str
    data_hash: str
    ruleset_version: str


def calculate_seven_layer_decision(
    fundamental: FundamentalState,
    *,
    structure: Mapping[str, Any] | None,
    coverage: Mapping[str, Any],
) -> SevenLayerDecision:
    """Combine the seven book layers while keeping direction and execution separate.

    Layers 1-4 and 6 contribute directional evidence. Layers 5 and 7 can reduce
    execution confidence or block a setup, but they never manufacture direction.
    """

    as_of = fundamental.as_of.astimezone(UTC)
    bullish_score = sum(
        max(component.contribution, 0.0)
        for component in fundamental.components
        if component.epistemic_status != "UNKNOWN"
    )
    bearish_score = sum(
        max(-component.contribution, 0.0)
        for component in fundamental.components
        if component.epistemic_status != "UNKNOWN"
    )
    directional_pressure = bullish_score + bearish_score
    neutral_conflict_score = (
        100.0
        * (1.0 - abs(bullish_score - bearish_score) / directional_pressure)
        if directional_pressure > 0
        else 0.0
    )
    side = _directional_side(fundamental.directional_score)
    structure_context = _structure_context(structure, side=side, as_of=as_of)
    calendar_known = _factor_is_usable(coverage, "SCHEDULED_EVENT_CALENDAR")
    portfolio_risk_known = all(
        _factor_is_usable(coverage, code)
        for code in ("PORTFOLIO_CLUSTER_RISK", "TOTAL_OPEN_RISK", "DAILY_LOSS_STATUS")
    )

    execution_state = _execution_state(
        fundamental,
        structure_context=structure_context,
        calendar_known=calendar_known,
        portfolio_risk_known=portfolio_risk_known,
    )
    execution_confidence = _execution_confidence(
        fundamental,
        structure_context=structure_context,
    )
    book_coverage, usable_coverage = _book_coverage(coverage)
    phase1_coverage = float(coverage.get("phase1_coverage_pct", 0.0))
    layers = _layer_assessments(
        fundamental,
        coverage=coverage,
        structure_context=structure_context,
        execution_state=execution_state,
    )
    warnings = _risk_warnings(
        fundamental,
        structure_context=structure_context,
        calendar_known=calendar_known,
        portfolio_risk_known=portfolio_risk_known,
        coverage=coverage,
    )
    highest_risk_assumption = warnings[0] if warnings else (
        "No material unresolved assumption was found in the connected evidence."
    )
    confirmation_requirements = _confirmation_requirements(
        side,
        calendar_known=calendar_known,
    )
    invalidation_requirements = _invalidation_requirements(
        fundamental,
        side=side,
        structure_context=structure_context,
    )
    execution_plan = {
        "bias": {
            "state": fundamental.bias_label,
            "side": side,
            "epistemic_status": "INFERRED",
            "score": fundamental.directional_score,
            "confidence": fundamental.confidence,
            "evidence_component_codes": [
                component.code
                for component in fundamental.components
                if component.epistemic_status != "UNKNOWN"
            ],
        },
        "trigger": structure_context["trigger"],
        "invalidation": {
            "epistemic_status": (
                "CALCULATED"
                if structure_context["invalidation_level"] is not None
                else "UNKNOWN"
            ),
            "price_level": structure_context["invalidation_level"],
            "price_condition": structure_context["invalidation_condition"],
            "fundamental_conditions": invalidation_requirements,
        },
        "risk": {
            "epistemic_status": (
                "CALCULATED"
                if structure_context["stop_distance_price"] is not None
                else "UNKNOWN"
            ),
            "research_risk_budget_pct": (
                0.5 if structure_context["trigger"]["state"] == "CONFIRMED" else 0.0
            ),
            "suggested_stop_distance_price": structure_context["stop_distance_price"],
            "suggested_position_size_lots": None,
            "position_size_status": (
                "UNKNOWN_ACCOUNT_EQUITY_AND_CONTRACT_SPECIFICATION"
            ),
            "target_zone": structure_context["target_zone"],
            "reward_to_risk": structure_context["reward_to_risk"],
            "portfolio_cluster_risk": (
                "AVAILABLE" if portfolio_risk_known else "UNKNOWN"
            ),
            "total_open_risk": "AVAILABLE" if portfolio_risk_known else "UNKNOWN",
            "daily_loss_status": "AVAILABLE" if portfolio_risk_known else "UNKNOWN",
            "event_risk_warning": fundamental.event_risk,
            "slippage_risk_warning": structure_context["liquidity_state"],
        },
        "confirmation_requirements": confirmation_requirements,
        "invalidation_requirements": invalidation_requirements,
        "warnings": warnings,
        "is_trade_instruction": False,
    }
    reasoning_chain = _reasoning_chain(fundamental)
    reasoning = {
        "summary": _decision_summary(
            fundamental,
            structure_context=structure_context,
            execution_state=execution_state,
        ),
        "directional_chain": reasoning_chain,
        "contradictions": _contradictions(fundamental, structure_context),
        "weight_profile": fundamental.reasoning.get("weight_profile"),
        "effective_weights": fundamental.reasoning.get("effective_weights", {}),
        "directional_scoring_policy": (
            "Only Layers 1-4 and 6 contribute signed points. Unknown inputs add "
            "neither bullish nor bearish points."
        ),
        "execution_gating_policy": (
            "Layers 5 and 7 may reduce confidence or force WAIT; they cannot turn "
            "a macro bias into a trade."
        ),
        "neutral_conflict_score_definition": (
            "Opposition within connected signed evidence. Missing evidence is "
            "reported as coverage, never converted into neutrality."
        ),
        "confidence_is_not_win_probability": True,
        "score_is_not_trade_signal": True,
        "all_outputs_traceable_to": {
            "fundamental_data_hash": fundamental.data_hash,
            "structure_data_hash": (
                str(structure.get("data_hash")) if structure is not None else None
            ),
            "registry_hash": str(coverage.get("registry_hash", "")),
        },
    }
    structure_hash = str(structure.get("data_hash")) if structure is not None else None
    registry_hash = str(coverage.get("registry_hash", ""))
    decision_hash = _decision_hash(
        as_of=as_of,
        fundamental_data_hash=fundamental.data_hash,
        structure_data_hash=structure_hash,
        registry_hash=registry_hash,
        execution_state=execution_state,
        execution_plan=execution_plan,
    )
    return SevenLayerDecision(
        as_of=as_of,
        epistemic_status="INFERRED",
        directional_score=round(clamp(fundamental.directional_score, -100, 100), 3),
        bullish_score=round(clamp(bullish_score, 0, 100), 3),
        bearish_score=round(clamp(bearish_score, 0, 100), 3),
        neutral_conflict_score=round(clamp(neutral_conflict_score, 0, 100), 3),
        directional_confidence=round(clamp(fundamental.confidence, 0, 100), 3),
        execution_confidence=round(clamp(execution_confidence, 0, 100), 3),
        directional_evidence_coverage_pct=round(
            clamp(fundamental.coverage, 0, 100),
            3,
        ),
        phase1_factor_coverage_pct=round(clamp(phase1_coverage, 0, 100), 3),
        book_factor_coverage_pct=round(clamp(book_coverage, 0, 100), 3),
        book_usable_coverage_pct=round(clamp(usable_coverage, 0, 100), 3),
        bias=fundamental.bias_label,
        regime=fundamental.regime_label,
        reaction_function=fundamental.reaction_function,
        dominant_driver=fundamental.dominant_driver,
        main_contradiction=_main_contradiction(fundamental, structure_context),
        highest_risk_assumption=highest_risk_assumption,
        upcoming_catalyst=fundamental.upcoming_catalyst,
        event_risk=fundamental.event_risk,
        current_session=structure_context["current_session"],
        liquidity_state=structure_context["liquidity_state"],
        price_macro_alignment=structure_context["price_macro_alignment"],
        execution_state=execution_state,
        layers=layers,
        components=fundamental.components,
        execution_plan=execution_plan,
        reasoning=reasoning,
        fundamental_data_hash=fundamental.data_hash,
        structure_data_hash=structure_hash,
        registry_hash=registry_hash,
        data_hash=decision_hash,
        ruleset_version=DECISION_RULESET_VERSION,
    )


def _directional_side(score: float) -> str:
    if score >= MINIMUM_DIRECTIONAL_SCORE:
        return "LONG"
    if score <= -MINIMUM_DIRECTIONAL_SCORE:
        return "SHORT"
    return "NONE"


def _structure_context(
    structure: Mapping[str, Any] | None,
    *,
    side: str,
    as_of: datetime,
) -> dict[str, Any]:
    unknown: dict[str, Any] = {
        "available": False,
        "stale": True,
        "source_age_seconds": None,
        "current_session": "UNKNOWN",
        "special_windows": [],
        "liquidity_state": "UNKNOWN",
        "liquidity_multiplier": 0.5,
        "price_macro_alignment": "UNKNOWN",
        "five_minute_trend": "UNKNOWN",
        "trigger": {
            "state": "UNKNOWN",
            "side": side,
            "epistemic_status": "UNKNOWN",
            "timeframe": "5m",
            "detection": None,
            "explanation": "No point-in-time market-structure snapshot is available.",
        },
        "invalidation_level": None,
        "invalidation_condition": None,
        "stop_distance_price": None,
        "target_zone": None,
        "reward_to_risk": None,
        "support": None,
        "resistance": None,
        "last_close": None,
        "structure_summary": "Market structure is unavailable.",
    }
    if structure is None:
        return unknown

    age = _integer_or_none(structure.get("source_staleness_seconds"))
    stale = age is None or age > MAX_LIVE_PRICE_AGE_SECONDS
    session = structure.get("session")
    session_map = session if isinstance(session, Mapping) else {}
    liquidity = structure.get("liquidity")
    liquidity_map = liquidity if isinstance(liquidity, Mapping) else {}
    timeframes = structure.get("timeframes")
    timeframe_rows = timeframes if isinstance(timeframes, list) else []
    five_minute = next(
        (
            row
            for row in timeframe_rows
            if isinstance(row, Mapping) and row.get("timeframe") == "5m"
        ),
        None,
    )
    five = five_minute if isinstance(five_minute, Mapping) else {}
    trend = str(five.get("trend", "UNKNOWN"))
    expected_trend = "BULLISH" if side == "LONG" else "BEARISH" if side == "SHORT" else None
    if expected_trend is None or not five:
        alignment = "UNKNOWN"
    elif trend == expected_trend:
        alignment = "CONFIRMING"
    elif trend in {"MIXED_OR_TRANSITIONING", "RANGE", "UNKNOWN"}:
        alignment = "CONFLICTED"
    else:
        alignment = "CONTRADICTING"

    latest_bar_at = _datetime_or_none(structure.get("latest_bar_at"))
    detections = five.get("detections")
    detection_rows = detections if isinstance(detections, list) else []
    trigger = _trigger_state(
        detection_rows,
        side=side,
        latest_bar_at=latest_bar_at,
        stale=stale,
    )
    last_close = _float_or_none(five.get("last_close"))
    support = _float_or_none(five.get("support"))
    resistance = _float_or_none(five.get("resistance"))
    invalidation_level = (
        support if side == "LONG" else resistance if side == "SHORT" else None
    )
    invalidation_condition = (
        f"A complete 5m close below {invalidation_level:.2f}"
        if side == "LONG" and invalidation_level is not None
        else f"A complete 5m close above {invalidation_level:.2f}"
        if side == "SHORT" and invalidation_level is not None
        else None
    )
    stop_distance = (
        last_close - invalidation_level
        if side == "LONG"
        and last_close is not None
        and invalidation_level is not None
        and last_close > invalidation_level
        else invalidation_level - last_close
        if side == "SHORT"
        and last_close is not None
        and invalidation_level is not None
        and invalidation_level > last_close
        else None
    )
    target_zone = _target_zone(timeframe_rows, side=side, last_close=last_close)
    reward_to_risk = (
        abs(target_zone - last_close) / stop_distance
        if target_zone is not None
        and last_close is not None
        and stop_distance is not None
        and stop_distance > 0
        else None
    )
    liquidity_state = str(liquidity_map.get("status", "UNKNOWN"))
    liquidity_multiplier = _float_or_none(
        liquidity_map.get("execution_confidence_multiplier")
    )
    special_windows = session_map.get("special_windows")
    return {
        "available": True,
        "stale": stale,
        "source_age_seconds": age,
        "current_session": str(session_map.get("primary", "UNKNOWN")),
        "special_windows": (
            list(special_windows) if isinstance(special_windows, list | tuple) else []
        ),
        "liquidity_state": liquidity_state,
        "liquidity_multiplier": (
            clamp(liquidity_multiplier, 0, 1)
            if liquidity_multiplier is not None
            else 0.5
        ),
        "price_macro_alignment": alignment,
        "five_minute_trend": trend,
        "trigger": trigger,
        "invalidation_level": (
            round(invalidation_level, 6) if invalidation_level is not None else None
        ),
        "invalidation_condition": invalidation_condition,
        "stop_distance_price": (
            round(stop_distance, 6) if stop_distance is not None else None
        ),
        "target_zone": round(target_zone, 6) if target_zone is not None else None,
        "reward_to_risk": (
            round(reward_to_risk, 3) if reward_to_risk is not None else None
        ),
        "support": support,
        "resistance": resistance,
        "last_close": last_close,
        "structure_summary": (
            f"5m trend is {trend}; price-versus-macro alignment is {alignment}."
        ),
        "as_of": as_of.isoformat(),
    }


def _trigger_state(
    detections: list[Any],
    *,
    side: str,
    latest_bar_at: datetime | None,
    stale: bool,
) -> dict[str, Any]:
    if side == "NONE":
        return {
            "state": "NOT_APPLICABLE",
            "side": side,
            "epistemic_status": "CALCULATED",
            "timeframe": "5m",
            "detection": None,
            "explanation": "No directional macro permission exists to confirm.",
        }
    if stale or latest_bar_at is None:
        return {
            "state": "UNKNOWN",
            "side": side,
            "epistemic_status": "UNKNOWN",
            "timeframe": "5m",
            "detection": None,
            "explanation": "Price evidence is missing or stale.",
        }
    accepted_kinds = {
        "LONG": {
            "ACCEPTANCE_ABOVE_RESISTANCE",
            "RETEST_HELD_ABOVE_RESISTANCE",
        },
        "SHORT": {
            "ACCEPTANCE_BELOW_SUPPORT",
            "RETEST_HELD_BELOW_SUPPORT",
        },
    }
    opposite = "SHORT" if side == "LONG" else "LONG"
    cutoff = latest_bar_at - timedelta(minutes=TRIGGER_MAX_AGE_MINUTES)
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    for item in detections:
        if not isinstance(item, Mapping):
            continue
        detected_at = _datetime_or_none(item.get("detected_at"))
        if detected_at is None or detected_at < cutoff or detected_at > latest_bar_at:
            continue
        if item.get("kind") in accepted_kinds[side] | accepted_kinds[opposite]:
            eligible.append((detected_at, item))
    if not eligible:
        return {
            "state": "WAITING",
            "side": side,
            "epistemic_status": "INFERRED",
            "timeframe": "5m",
            "detection": None,
            "explanation": (
                "No fresh two-close acceptance or held-retest detection confirms "
                f"the {side.lower()} macro bias."
            ),
        }
    _, latest = max(eligible, key=lambda item: item[0])
    kind = str(latest.get("kind"))
    aligned = kind in accepted_kinds[side]
    return {
        "state": "CONFIRMED" if aligned else "CONTRADICTING",
        "side": side,
        "epistemic_status": str(latest.get("epistemic_status", "INFERRED")),
        "timeframe": "5m",
        "detection": dict(latest),
        "explanation": (
            f"{kind} confirms the {side.lower()} macro bias."
            if aligned
            else f"{kind} contradicts the {side.lower()} macro bias."
        ),
    }


def _target_zone(
    timeframes: list[Any],
    *,
    side: str,
    last_close: float | None,
) -> float | None:
    if side == "NONE" or last_close is None:
        return None
    candidates: list[float] = []
    for item in timeframes:
        if not isinstance(item, Mapping):
            continue
        for key in ("resistance", "range_high") if side == "LONG" else ("support", "range_low"):
            value = _float_or_none(item.get(key))
            if value is None:
                continue
            if (side == "LONG" and value > last_close) or (
                side == "SHORT" and value < last_close
            ):
                candidates.append(value)
    if not candidates:
        return None
    return min(candidates) if side == "LONG" else max(candidates)


def _execution_state(
    fundamental: FundamentalState,
    *,
    structure_context: Mapping[str, Any],
    calendar_known: bool,
    portfolio_risk_known: bool,
) -> str:
    if not structure_context["available"] or structure_context["stale"]:
        return "WAIT_STALE_OR_MISSING_PRICE"
    if not calendar_known:
        return "WAIT_CATALYST_CALENDAR_UNKNOWN"
    if fundamental.event_risk == "UNKNOWN":
        return "WAIT_CATALYST_RISK_UNKNOWN"
    if fundamental.event_risk in {"HIGH", "EXTREME"}:
        return "WAIT_EVENT_RISK"
    liquidity = structure_context["liquidity_state"]
    if liquidity == "UNKNOWN":
        return "WAIT_LIQUIDITY_UNKNOWN"
    if liquidity in {"ELEVATED", "ABNORMAL"}:
        return "WAIT_LIQUIDITY_RISK"
    side = _directional_side(fundamental.directional_score)
    if side == "NONE":
        return "WAIT_NO_DIRECTIONAL_BIAS"
    if fundamental.coverage < MINIMUM_DIRECTIONAL_COVERAGE:
        return "WAIT_INSUFFICIENT_DIRECTIONAL_COVERAGE"
    if fundamental.confidence < MINIMUM_DIRECTIONAL_CONFIDENCE:
        return "WAIT_LOW_DIRECTIONAL_CONFIDENCE"
    trigger_state = structure_context["trigger"]["state"]
    if trigger_state == "CONTRADICTING":
        return "WAIT_PRICE_CONTRADICTS_MACRO"
    if trigger_state != "CONFIRMED":
        return "WAIT_FOR_PRICE_ACCEPTANCE"
    if not portfolio_risk_known:
        return "WAIT_ACCOUNT_RISK_STATE_UNKNOWN"
    return "RESEARCH_SETUP_CONFIRMED"


def _execution_confidence(
    fundamental: FundamentalState,
    *,
    structure_context: Mapping[str, Any],
) -> float:
    if not structure_context["available"] or structure_context["stale"]:
        return 0.0
    alignment_multiplier = {
        "CONFIRMING": 1.0,
        "CONFLICTED": 0.80,
        "CONTRADICTING": 0.60,
        "UNKNOWN": 0.70,
    }.get(str(structure_context["price_macro_alignment"]), 0.70)
    trigger_multiplier = {
        "CONFIRMED": 1.0,
        "WAITING": 0.75,
        "CONTRADICTING": 0.50,
        "NOT_APPLICABLE": 0.60,
        "UNKNOWN": 0.50,
    }.get(str(structure_context["trigger"]["state"]), 0.50)
    return (
        fundamental.confidence
        * float(structure_context["liquidity_multiplier"])
        * alignment_multiplier
        * trigger_multiplier
    )


def _layer_assessments(
    fundamental: FundamentalState,
    *,
    coverage: Mapping[str, Any],
    structure_context: Mapping[str, Any],
    execution_state: str,
) -> tuple[LayerAssessment, ...]:
    layer_coverage = {
        int(row["layer"]): row
        for row in coverage.get("layers", [])
        if isinstance(row, Mapping) and isinstance(row.get("layer"), int)
    }
    factors = [
        row for row in coverage.get("factors", []) if isinstance(row, Mapping)
    ]
    output: list[LayerAssessment] = []
    for layer_number in range(1, 8):
        row = layer_coverage.get(layer_number, {})
        members = [
            component
            for component in fundamental.components
            if component.layer == layer_number
        ]
        known_components = [
            component for component in members if component.epistemic_status != "UNKNOWN"
        ]
        contribution = (
            sum(component.contribution for component in known_components)
            if layer_number in {1, 2, 3, 4, 6}
            else None
        )
        confidence = _component_confidence(known_components)
        book_count = int(row.get("factor_count", 0))
        known_count = int(row.get("known_factor_count", 0))
        usable_count = int(row.get("usable_factor_count", known_count))
        book_pct = float(
            row.get(
                "book_coverage_pct",
                known_count / book_count * 100 if book_count else 0,
            )
        )
        phase1_pct = float(row.get("phase1_coverage_pct", 0.0))
        status = (
            "COMPLETE"
            if book_count > 0 and known_count == book_count
            else "PARTIAL"
            if known_count > 0
            else "UNKNOWN"
        )
        role: LayerRole = (
            "DIRECTIONAL" if layer_number in {1, 2, 3, 4, 6} else "EXECUTION_GATE"
        )
        operational_status, summary = _layer_operational_summary(
            layer_number,
            known_components=known_components,
            structure_context=structure_context,
            execution_state=execution_state,
        )
        supporting = tuple(
            component.explanation
            for component in known_components
            if contribution is None
            or contribution == 0
            or component.contribution * contribution >= 0
        )
        contradicting = tuple(
            component.explanation
            for component in known_components
            if contribution is not None
            and contribution != 0
            and component.contribution * contribution < 0
        )
        unknown_factors = tuple(
            str(factor.get("code"))
            for factor in factors
            if factor.get("layer") == layer_number
            and factor.get("current_epistemic_status") == "UNKNOWN"
        )
        output.append(
            LayerAssessment(
                number=layer_number,
                name=LAYER_NAMES[layer_number],
                role=role,
                status=status,
                operational_status=operational_status,
                book_factor_count=book_count,
                known_factor_count=known_count,
                usable_factor_count=usable_count,
                book_coverage_pct=round(book_pct, 2),
                phase1_coverage_pct=round(phase1_pct, 2),
                directional_contribution=(
                    round(contribution, 3) if contribution is not None else None
                ),
                confidence=round(confidence, 3) if confidence is not None else None,
                summary=summary,
                supporting_evidence=supporting,
                contradicting_evidence=contradicting,
                unknown_factors=unknown_factors,
            )
        )
    return tuple(output)


def _layer_operational_summary(
    layer: int,
    *,
    known_components: list[FundamentalComponent],
    structure_context: Mapping[str, Any],
    execution_state: str,
) -> tuple[str, str]:
    if layer == 5:
        if not structure_context["available"]:
            return "UNKNOWN", "Session and liquidity evidence is unavailable."
        if structure_context["stale"]:
            return "STALE", "Session and liquidity evidence exists but price is stale."
        return (
            "ACTIVE",
            (
                f"Session is {structure_context['current_session']}; liquidity is "
                f"{structure_context['liquidity_state']}."
            ),
        )
    if layer == 7:
        return (
            "GATED" if execution_state.startswith("WAIT") else "ACTIVE",
            (
                f"Execution state is {execution_state}; bias, trigger, invalidation, "
                "and risk are evaluated separately."
            ),
        )
    if not known_components:
        return "UNKNOWN", "No eligible point-in-time directional component is available."
    contribution = sum(component.contribution for component in known_components)
    direction = (
        "gold-supportive"
        if contribution > 0
        else "gold-negative"
        if contribution < 0
        else "balanced"
    )
    return (
        "ACTIVE",
        (
            f"{len(known_components)} connected component(s) contribute "
            f"{contribution:+.2f} points and are {direction}."
        ),
    )


def _component_confidence(
    components: list[FundamentalComponent],
) -> float | None:
    if not components:
        return None
    total_weight = sum(component.weight for component in components)
    if total_weight <= 0:
        return 0.0
    return sum(
        component.weight
        * component.confidence
        * component.freshness
        * component.data_quality
        / 10_000
        for component in components
    ) / total_weight


def _factor_is_usable(coverage: Mapping[str, Any], code: str) -> bool:
    for factor in coverage.get("factors", []):
        if not isinstance(factor, Mapping) or factor.get("code") != code:
            continue
        if "usable_now" in factor:
            return factor.get("usable_now") is True
        return factor.get("current_epistemic_status") != "UNKNOWN"
    return False


def _book_coverage(coverage: Mapping[str, Any]) -> tuple[float, float]:
    if "book_factor_coverage_pct" in coverage:
        return (
            float(coverage.get("book_factor_coverage_pct", 0.0)),
            float(
                coverage.get(
                    "book_usable_coverage_pct",
                    coverage.get("book_factor_coverage_pct", 0.0),
                )
            ),
        )
    layer_rows = [
        row for row in coverage.get("layers", []) if isinstance(row, Mapping)
    ]
    total = sum(int(row.get("factor_count", 0)) for row in layer_rows)
    known = sum(int(row.get("known_factor_count", 0)) for row in layer_rows)
    usable = sum(
        int(row.get("usable_factor_count", row.get("known_factor_count", 0)))
        for row in layer_rows
    )
    return (
        known / total * 100 if total else 0.0,
        usable / total * 100 if total else 0.0,
    )


def _risk_warnings(
    fundamental: FundamentalState,
    *,
    structure_context: Mapping[str, Any],
    calendar_known: bool,
    portfolio_risk_known: bool,
    coverage: Mapping[str, Any],
) -> list[str]:
    warnings: list[str] = []
    if not structure_context["available"]:
        warnings.append("No point-in-time price structure is available.")
    elif structure_context["stale"]:
        age = structure_context["source_age_seconds"]
        suffix = f" ({age} seconds old)" if age is not None else ""
        warnings.append(f"Price structure is stale{suffix}.")
    if not calendar_known:
        warnings.append(
            "The upcoming-catalyst calendar is unavailable or stale, so event risk is unknown."
        )
    elif fundamental.event_risk in {"HIGH", "EXTREME"}:
        warnings.append(
            f"Upcoming catalyst risk is {fundamental.event_risk.lower()}."
        )
    if structure_context["liquidity_state"] != "NORMAL":
        warnings.append(
            f"Liquidity state is {str(structure_context['liquidity_state']).lower()}."
        )
    if not portfolio_risk_known:
        warnings.append(
            "Portfolio-cluster exposure, total open risk, or daily-loss status is unknown."
        )
    stale_factors = [
        str(factor.get("code"))
        for factor in coverage.get("factors", [])
        if isinstance(factor, Mapping) and factor.get("freshness_status") == "STALE"
    ]
    if stale_factors:
        warnings.append(
            "Stale factor evidence: " + ", ".join(stale_factors[:8]) + "."
        )
    missing = fundamental.reasoning.get("missing_drivers", [])
    if isinstance(missing, list) and missing:
        warnings.append(
            "Missing directional drivers: " + ", ".join(str(item) for item in missing) + "."
        )
    crowding = fundamental.reasoning.get("crowding")
    if isinstance(crowding, Mapping) and crowding.get("state") in {
        "CROWDED_LONGS",
        "CROWDED_SHORTS",
    }:
        warnings.append(
            f"Positioning is {str(crowding['state']).lower()}, increasing forced-flow risk."
        )
    return warnings


def _confirmation_requirements(
    side: str,
    *,
    calendar_known: bool,
) -> list[str]:
    if side == "NONE":
        return [
            "Directional score must first clear +5 or -5 with sufficient connected evidence.",
            "Price cannot create macro permission on its own.",
        ]
    direction = "above resistance" if side == "LONG" else "below support"
    return [
        (
            f"Directional score remains {'at or above +5' if side == 'LONG' else 'at or below -5'} "
            "with at least 35% directional evidence coverage and 25% confidence."
        ),
        (
            "A fresh two-close 5m acceptance or held retest confirms price "
            f"{direction}."
        ),
        "Broker liquidity is NORMAL.",
        (
            "The catalyst calendar is connected and no high/extreme event blackout applies."
            if calendar_known
            else "Connect a point-in-time catalyst calendar before execution can be assessed."
        ),
        "Portfolio exposure and daily-loss gates are known and within configured limits.",
    ]


def _invalidation_requirements(
    fundamental: FundamentalState,
    *,
    side: str,
    structure_context: Mapping[str, Any],
) -> list[str]:
    if side == "NONE":
        return ["No directional thesis exists while the macro score is neutral or conflicted."]
    price_condition = structure_context.get("invalidation_condition")
    output = [str(price_condition)] if price_condition else [
        "A deterministic price invalidation level is not yet available."
    ]
    if side == "LONG":
        output.append(
            "The long macro thesis weakens if real yields and the USD reverse higher "
            "and the directional score falls below +5."
        )
    else:
        output.append(
            "The short macro thesis weakens if real yields and the USD reverse lower "
            "and the directional score rises above -5."
        )
    if fundamental.dominant_driver:
        output.append(
            f"Reversal or expiry of dominant driver {fundamental.dominant_driver} "
            "requires the thesis to be recalculated."
        )
    return output


def _reasoning_chain(fundamental: FundamentalState) -> list[dict[str, Any]]:
    ordered = sorted(
        (
            component
            for component in fundamental.components
            if component.epistemic_status != "UNKNOWN" and component.direction != 0
        ),
        key=lambda component: abs(component.contribution),
        reverse=True,
    )
    return [
        {
            "step": index,
            "component": component.code,
            "layer": component.layer,
            "direction": component.direction,
            "contribution": component.contribution,
            "epistemic_status": component.epistemic_status,
            "explanation": component.explanation,
            "evidence": component.evidence,
        }
        for index, component in enumerate(ordered, start=1)
    ]


def _contradictions(
    fundamental: FundamentalState,
    structure_context: Mapping[str, Any],
) -> list[str]:
    output = [
        str(item)
        for item in fundamental.reasoning.get("contradictions", [])
        if isinstance(item, str)
    ]
    raw_score = fundamental.directional_score
    for component in fundamental.components:
        if (
            component.epistemic_status != "UNKNOWN"
            and raw_score != 0
            and component.contribution * raw_score < 0
        ):
            output.append(component.explanation)
    if structure_context["price_macro_alignment"] == "CONTRADICTING":
        output.append(str(structure_context["structure_summary"]))
    return list(dict.fromkeys(output))


def _main_contradiction(
    fundamental: FundamentalState,
    structure_context: Mapping[str, Any],
) -> str | None:
    if structure_context["price_macro_alignment"] == "CONTRADICTING":
        return str(structure_context["structure_summary"])
    return fundamental.main_contradiction


def _decision_summary(
    fundamental: FundamentalState,
    *,
    structure_context: Mapping[str, Any],
    execution_state: str,
) -> str:
    driver = fundamental.dominant_driver or "no connected dominant driver"
    return (
        f"Gold bias is {fundamental.bias_label} at {fundamental.directional_score:+.2f}, "
        f"led by {driver}. Regime is {fundamental.regime_label}; the reaction "
        f"function is {fundamental.reaction_function}. Price versus macro is "
        f"{structure_context['price_macro_alignment']}. Execution remains "
        f"{execution_state}."
    )


def _decision_hash(
    *,
    as_of: datetime,
    fundamental_data_hash: str,
    structure_data_hash: str | None,
    registry_hash: str,
    execution_state: str,
    execution_plan: Mapping[str, Any],
) -> str:
    payload = {
        "as_of": as_of.isoformat(),
        "fundamental_data_hash": fundamental_data_hash,
        "structure_data_hash": structure_data_hash,
        "registry_hash": registry_hash,
        "execution_state": execution_state,
        "execution_plan": execution_plan,
        "ruleset_version": DECISION_RULESET_VERSION,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def decision_to_dict(decision: SevenLayerDecision) -> dict[str, Any]:
    return {
        **asdict(decision),
        "layers": [asdict(layer) for layer in decision.layers],
        "components": [asdict(component) for component in decision.components],
    }


def _float_or_none(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _integer_or_none(value: Any) -> int | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _datetime_or_none(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else None
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(UTC) if parsed.tzinfo else None
