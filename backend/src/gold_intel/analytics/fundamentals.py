from __future__ import annotations

import hashlib
import json
import math
from dataclasses import asdict, dataclass, replace
from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from gold_intel.domain.rulesets import (
    BASE_DIRECTIONAL_WEIGHTS,
    BOOK_RULESET_VERSION,
    weights_for_reaction,
)
from gold_intel.domain.signals import clamp

FUNDAMENTAL_RULESET_VERSION = f"{BOOK_RULESET_VERSION}-fundamentals"
FULL_DIRECTIONAL_BUDGET = 100.0
DRIVER_WEIGHTS: dict[str, float] = dict(BASE_DIRECTIONAL_WEIGHTS)


@dataclass(frozen=True, slots=True)
class FundamentalObservation:
    series_code: str
    observation_time: datetime
    available_at: datetime
    value: float
    source_record_key: str


@dataclass(frozen=True, slots=True)
class CotFundamentalPoint:
    observation_date: date
    publication_at: datetime
    availability_quality: str
    managed_money_long: int
    managed_money_short: int
    producer_long: int
    producer_short: int
    open_interest: int
    source_record_key: str

    @property
    def managed_money_net(self) -> int:
        return self.managed_money_long - self.managed_money_short


@dataclass(frozen=True, slots=True)
class EventSurprisePoint:
    event_id: str
    event_code: str
    event_name: str
    component_code: str
    released_at: datetime
    available_at: datetime
    gold_direction: float
    strength: float
    confidence: float
    importance: int
    epistemic_status: str
    data_hash: str


@dataclass(frozen=True, slots=True)
class FundamentalEventPoint:
    event_id: str
    event_code: str
    event_name: str
    scheduled_at: datetime
    available_at: datetime
    importance: int
    status: str
    source_record_key: str


@dataclass(frozen=True, slots=True)
class PolicyPathFundamentalPoint:
    provider_code: str
    snapshot_as_of: datetime
    meeting_date: date
    outcome_basis_points: int
    probability: float
    expected_rate: float | None
    available_at: datetime
    source_record_key: str


@dataclass(frozen=True, slots=True)
class QuarterlyPolicyExpectationPoint:
    provider_code: str
    observation_date: date
    snapshot_as_of: datetime
    reference_start: date
    reference_end: date
    rate_p25_basis_points: float
    rate_mean_basis_points: float
    rate_mode_basis_points: float
    rate_p75_basis_points: float
    probability_cut: float | None
    probability_hike: float | None
    probability_bins: tuple[dict[str, Any], ...]
    available_at: datetime
    availability_quality: str
    source_record_key: str


@dataclass(frozen=True, slots=True)
class FundamentalComponent:
    code: str
    layer: int
    direction: float
    strength: float
    confidence: float
    freshness: float
    data_quality: float
    weight: float
    contribution: float
    epistemic_status: str
    explanation: str
    evidence: dict[str, Any]


@dataclass(frozen=True, slots=True)
class FundamentalState:
    as_of: datetime
    directional_score: float
    confidence: float
    coverage: float
    bias_label: str
    regime_label: str
    reaction_function: str
    dominant_driver: str | None
    main_contradiction: str | None
    event_risk: str
    upcoming_catalyst: dict[str, Any] | None
    components: tuple[FundamentalComponent, ...]
    layers: tuple[dict[str, Any], ...]
    reasoning: dict[str, Any]
    data_hash: str

    def permission(
        self,
        side: Literal["LONG", "SHORT"],
        *,
        minimum_score: float,
        minimum_coverage: float,
        minimum_confidence: float,
    ) -> tuple[bool, str]:
        if self.coverage < minimum_coverage:
            return False, "FUNDAMENTAL_COVERAGE_BELOW_THRESHOLD"
        if self.confidence < minimum_confidence:
            return False, "FUNDAMENTAL_CONFIDENCE_BELOW_THRESHOLD"
        if side == "LONG" and self.directional_score < minimum_score:
            return False, "FUNDAMENTALS_NOT_BULLISH_ENOUGH"
        if side == "SHORT" and self.directional_score > -minimum_score:
            return False, "FUNDAMENTALS_NOT_BEARISH_ENOUGH"
        return True, "FUNDAMENTALS_ALIGNED"


def calculate_fundamental_state(
    observations: list[FundamentalObservation],
    cot_points: list[CotFundamentalPoint],
    *,
    as_of: datetime,
    event_surprises: list[EventSurprisePoint] | None = None,
    events: list[FundamentalEventPoint] | None = None,
    policy_path_points: list[PolicyPathFundamentalPoint] | None = None,
    quarterly_policy_expectations: list[QuarterlyPolicyExpectationPoint] | None = None,
    compute_data_hash: bool = True,
) -> FundamentalState:
    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    cutoff = as_of.astimezone(UTC)
    series = _eligible_series(observations, cutoff)
    eligible_cot = sorted(
        [point for point in cot_points if point.publication_at <= cutoff],
        key=lambda item: item.publication_at,
    )
    eligible_surprises = sorted(
        [
            point
            for point in (event_surprises or [])
            if point.available_at <= cutoff and point.released_at <= cutoff
        ],
        key=lambda item: (item.released_at, item.available_at),
    )
    upcoming_catalyst, event_risk = _upcoming_catalyst(events or [], cutoff)

    components = [
        _momentum_component(
            series,
            code="REAL_YIELD",
            layer=1,
            series_code="US_REAL_YIELD_10Y",
            inverse=True,
            normalization=0.20,
            as_of=cutoff,
            explanation_up="Falling real yield lowers gold's opportunity cost.",
            explanation_down="Rising real yield increases gold's opportunity cost.",
        ),
        _fed_path_component(
            series,
            policy_path_points or [],
            quarterly_policy_expectations or [],
            cutoff,
        ),
        _momentum_component(
            series,
            code="USD",
            layer=6,
            series_code="USD_BROAD_NOMINAL",
            inverse=True,
            normalization=0.01,
            percentage_change=True,
            as_of=cutoff,
            explanation_up="A weakening broad dollar supports dollar-priced gold.",
            explanation_down="A strengthening broad dollar pressures dollar-priced gold.",
        ),
        _momentum_component(
            series,
            code="TWO_YEAR_YIELD",
            layer=6,
            series_code="US_TREASURY_2Y",
            inverse=True,
            normalization=0.25,
            as_of=cutoff,
            explanation_up="A falling 2-year yield indicates more dovish near-term pricing.",
            explanation_down="A rising 2-year yield indicates more hawkish near-term pricing.",
        ),
        _inflation_regime_component(series, cutoff),
        _event_surprise_component(eligible_surprises, cutoff),
        _growth_regime_component(series, cutoff),
        _labour_regime_component(series, cutoff),
        _cot_component(eligible_cot, cutoff),
        _equity_risk_component(series, cutoff),
        _nominal_decomposition_component(series, cutoff),
        _financial_stress_component(series, cutoff),
    ]
    reaction_function = _reaction_function(components)
    weight_profile_name, effective_weights = weights_for_reaction(reaction_function)
    components = [
        _with_effective_weight(component, effective_weights[component.code])
        for component in components
    ]
    available = [component for component in components if component.epistemic_status != "UNKNOWN"]
    raw_score = sum(component.contribution for component in available)
    coverage = sum(component.weight for component in available) / FULL_DIRECTIONAL_BUDGET * 100
    coverage = clamp(coverage, 0, 100)
    if available:
        certainty = sum(
            component.weight
            * component.confidence
            * component.freshness
            * component.data_quality
            / 1_000_000
            for component in available
        ) / sum(component.weight for component in available)
        confidence = certainty * math.sqrt(coverage / 100) * 100
    else:
        confidence = 0.0

    contradictions: list[str] = []
    crowding = _crowding_state(eligible_cot)
    if raw_score > 0 and crowding["percentile"] is not None and crowding["percentile"] >= 90:
        confidence *= 0.80
        contradictions.append("Managed-money net longs are in the top decile.")
    if raw_score < 0 and crowding["percentile"] is not None and crowding["percentile"] <= 10:
        confidence *= 0.80
        contradictions.append("Managed-money net positioning is in the bottom decile.")
    event_confidence_multiplier = {
        "EXTREME": 0.60,
        "HIGH": 0.80,
        "ELEVATED": 0.93,
    }.get(event_risk, 1.0)
    confidence *= event_confidence_multiplier

    dominant = max(
        available,
        key=lambda component: abs(component.contribution),
        default=None,
    )
    opposing = [component for component in available if component.contribution * raw_score < 0]
    main_opposing = max(
        opposing,
        key=lambda component: abs(component.contribution),
        default=None,
    )
    main_contradiction = (
        contradictions[0]
        if contradictions
        else main_opposing.explanation
        if main_opposing
        else None
    )
    regime_label = _regime_label(raw_score, components)
    layers = _layer_statuses(components)
    evidence_hash = (
        _data_hash(
            series,
            eligible_cot,
            eligible_surprises,
            events or [],
            policy_path_points or [],
            quarterly_policy_expectations or [],
            cutoff,
        )
        if compute_data_hash
        else "NOT_COMPUTED"
    )
    known_explanations = [
        component.explanation for component in available if component.direction != 0
    ]
    missing_drivers = [
        component.code for component in components if component.epistemic_status == "UNKNOWN"
    ]
    return FundamentalState(
        as_of=cutoff,
        directional_score=round(clamp(raw_score, -100, 100), 3),
        confidence=round(clamp(confidence, 0, 100), 3),
        coverage=round(coverage, 3),
        bias_label=_bias_label(raw_score),
        regime_label=regime_label,
        reaction_function=reaction_function,
        dominant_driver=dominant.code if dominant else None,
        main_contradiction=main_contradiction,
        event_risk=event_risk,
        upcoming_catalyst=upcoming_catalyst,
        components=tuple(components),
        layers=tuple(layers),
        reasoning={
            "summary": (
                " ".join(known_explanations)
                if known_explanations
                else "No eligible fundamental evidence is available."
            ),
            "missing_drivers": missing_drivers,
            "crowding": crowding,
            "contradictions": contradictions,
            "event_risk": event_risk,
            "event_confidence_multiplier": event_confidence_multiplier,
            "upcoming_catalyst": upcoming_catalyst,
            "weight_profile": weight_profile_name,
            "effective_weights": dict(effective_weights),
            "weighting_policy": (
                "Layers 1-4 and 6 supply directional evidence. Reaction-function "
                "profiles change their budgets; Layers 5 and 7 gate execution."
            ),
            "score_is_not_trade_signal": True,
            "confidence_is_not_win_probability": True,
        },
        data_hash=evidence_hash,
    )


def _with_effective_weight(
    component: FundamentalComponent,
    weight: float,
) -> FundamentalComponent:
    certainty_fraction = (
        component.confidence
        * component.freshness
        * component.data_quality
        / 1_000_000
    )
    contribution = (
        weight * component.direction * certainty_fraction
        if component.epistemic_status != "UNKNOWN"
        else 0.0
    )
    return replace(
        component,
        weight=weight,
        contribution=round(contribution, 3),
    )


def _eligible_series(
    observations: list[FundamentalObservation], as_of: datetime
) -> dict[str, list[FundamentalObservation]]:
    def sort_key(
        item: FundamentalObservation,
    ) -> tuple[str, datetime, datetime]:
        return (
            item.series_code,
            item.observation_time,
            item.available_at,
        )

    ordered = observations
    if any(
        sort_key(observations[index]) > sort_key(observations[index + 1])
        for index in range(len(observations) - 1)
    ):
        ordered = sorted(observations, key=sort_key)
    canonical: dict[tuple[str, datetime], FundamentalObservation] = {}
    for point in ordered:
        if point.available_at <= as_of and point.observation_time <= as_of:
            canonical[(point.series_code, point.observation_time)] = point
    output: dict[str, list[FundamentalObservation]] = {}
    for point in canonical.values():
        output.setdefault(point.series_code, []).append(point)
    for values in output.values():
        values.sort(key=lambda item: item.observation_time)
    return output


def _momentum_component(
    series: dict[str, list[FundamentalObservation]],
    *,
    code: str,
    layer: int,
    series_code: str,
    inverse: bool,
    normalization: float,
    as_of: datetime,
    explanation_up: str,
    explanation_down: str,
    percentage_change: bool = False,
) -> FundamentalComponent:
    values = series.get(series_code, [])
    weight = DRIVER_WEIGHTS[code]
    if len(values) < 6:
        return _missing_component(
            code,
            layer=layer,
            explanation=f"At least six eligible {series_code} observations are required.",
        )
    latest = values[-1]
    prior = values[-6]
    change = (
        (latest.value / prior.value - 1)
        if percentage_change and prior.value
        else latest.value - prior.value
    )
    raw_direction = change / normalization
    direction = -raw_direction if inverse else raw_direction
    direction = clamp(direction, -1, 1)
    freshness = _freshness(latest.available_at, as_of, half_life_days=3, expiry_days=8)
    quality = 92.0
    confidence = 90.0
    strength = abs(direction) * 100
    certainty_fraction = confidence * freshness * quality / 1_000_000
    # Direction already carries normalized magnitude. Strength is exposed for
    # interpretation, not multiplied a second time into the score.
    contribution = weight * direction * certainty_fraction
    explanation = (
        explanation_up
        if direction > 0
        else explanation_down
        if direction < 0
        else (f"{series_code} is approximately unchanged over five observations.")
    )
    return FundamentalComponent(
        code=code,
        layer=layer,
        direction=round(direction, 6),
        strength=round(strength, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=weight,
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=explanation,
        evidence={
            "series_code": series_code,
            "latest_value": latest.value,
            "prior_value": prior.value,
            "change": change,
            "latest_observation_time": latest.observation_time.isoformat(),
            "latest_available_at": latest.available_at.isoformat(),
            "lookback_observations": 5,
            "normalization": normalization,
            "inverse_for_gold": inverse,
            "source_record_keys": [prior.source_record_key, latest.source_record_key],
        },
    )


def _nominal_decomposition_component(
    series: dict[str, list[FundamentalObservation]], as_of: datetime
) -> FundamentalComponent:
    nominal = series.get("US_TREASURY_10Y", [])
    real = series.get("US_REAL_YIELD_10Y", [])
    breakeven = series.get("US_BREAKEVEN_10Y", [])
    code = "NOMINAL_DECOMPOSITION"
    if min(len(nominal), len(real), len(breakeven)) < 6:
        return _missing_component(
            code,
            layer=6,
            explanation="Nominal, real and breakeven histories are required for decomposition.",
        )
    nominal_change = nominal[-1].value - nominal[-6].value
    real_change = real[-1].value - real[-6].value
    breakeven_change = breakeven[-1].value - breakeven[-6].value
    # Reward inflation-led nominal increases only when real yields are not rising;
    # penalize a real-yield-led increase. This avoids treating every nominal move
    # as the same gold signal.
    direction = clamp(
        (-real_change + 0.35 * breakeven_change) / 0.20,
        -1,
        1,
    )
    latest_available = max(
        nominal[-1].available_at,
        real[-1].available_at,
        breakeven[-1].available_at,
    )
    freshness = _freshness(latest_available, as_of, half_life_days=3, expiry_days=8)
    confidence = 82.0
    quality = 88.0
    strength = abs(direction) * 100
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    return FundamentalComponent(
        code=code,
        layer=6,
        direction=round(direction, 6),
        strength=round(strength, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            "The nominal-yield move is relatively gold-supportive after separating real yield and breakeven inflation."
            if direction > 0
            else "The nominal-yield move is real-yield-led and therefore pressures gold."
            if direction < 0
            else "Nominal, real and breakeven changes are balanced."
        ),
        evidence={
            "nominal_10y_change": nominal_change,
            "real_10y_change": real_change,
            "breakeven_10y_change": breakeven_change,
            "identity": "nominal_yield approximately equals real_yield plus breakeven",
            "latest_available_at": latest_available.isoformat(),
        },
    )


def _equity_risk_component(
    series: dict[str, list[FundamentalObservation]],
    as_of: datetime,
) -> FundamentalComponent:
    code = "EQUITY_RISK"
    equities = series.get("US_EQUITY_PROXY", [])
    volatility = series.get("US_VOLATILITY_INDEX", [])
    if len(equities) < 6 or len(volatility) < 6:
        return _missing_component(
            code,
            layer=6,
            explanation=(
                "Six point-in-time S&P 500 and volatility-index observations "
                "are required for the defensive-demand proxy."
            ),
        )
    equity_return = equities[-1].value / equities[-6].value - 1 if equities[-6].value else 0.0
    volatility_change = (
        volatility[-1].value / volatility[-6].value - 1 if volatility[-6].value else 0.0
    )
    direction = clamp(
        -0.55 * equity_return / 0.03 + 0.45 * volatility_change / 0.25,
        -1,
        1,
    )
    latest_available = max(
        equities[-1].available_at,
        volatility[-1].available_at,
    )
    freshness = _freshness(
        latest_available,
        as_of,
        half_life_days=3,
        expiry_days=8,
    )
    confidence = 68.0
    quality = 84.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    state = "DEFENSIVE" if direction > 0.20 else "RISK_ON" if direction < -0.20 else "MIXED"
    return FundamentalComponent(
        code=code,
        layer=6,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="INFERRED",
        explanation=(
            f"Equity/VIX risk sentiment is {state.lower()}. Defensive conditions "
            "can support gold, but severe deleveraging can initially liquidate it."
        ),
        evidence={
            "state": state,
            "sp500_five_observation_return_pct": round(equity_return * 100, 4),
            "vix_five_observation_change_pct": round(
                volatility_change * 100,
                4,
            ),
            "latest_available_at": latest_available.isoformat(),
            "classification_warning": (
                "Safe-haven demand is inferred from synchronized public daily "
                "proxies; it is not observed gold flow."
            ),
        },
    )


def _financial_stress_component(
    series: dict[str, list[FundamentalObservation]],
    as_of: datetime,
) -> FundamentalComponent:
    code = "FINANCIAL_STRESS"
    stress = series.get("US_FINANCIAL_STRESS", [])
    high_yield = series.get("US_HIGH_YIELD_OAS", [])
    parts: list[tuple[str, float, datetime]] = []
    evidence: dict[str, Any] = {}
    if len(stress) >= 2:
        change = stress[-1].value - stress[-2].value
        level = stress[-1].value
        signal = clamp(0.65 * change / 0.5 + 0.35 * max(level, 0) / 1.0, -1, 1)
        parts.append(("US_FINANCIAL_STRESS", signal, stress[-1].available_at))
        evidence["stl_fed_stress"] = {
            "level": level,
            "weekly_change": round(change, 6),
        }
    if len(high_yield) >= 6:
        change = high_yield[-1].value - high_yield[-6].value
        signal = clamp(change / 0.50, -1, 1)
        parts.append(("US_HIGH_YIELD_OAS", signal, high_yield[-1].available_at))
        evidence["high_yield_oas"] = {
            "level_pct": high_yield[-1].value,
            "five_observation_change_pp": round(change, 6),
        }
    if not parts:
        return _missing_component(
            code,
            layer=1,
            explanation="The public financial-stress composite is unavailable.",
        )
    direction = sum(part[1] for part in parts) / len(parts)
    freshness = sum(
        _freshness(
            available_at,
            as_of,
            half_life_days=7,
            expiry_days=21,
        )
        for _, _, available_at in parts
    ) / len(parts)
    confidence = 72.0 if len(parts) == 2 else 60.0
    quality = 86.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    state = (
        "HIGH_OR_RISING"
        if direction > 0.35
        else "EASING"
        if direction < -0.20
        else "NORMAL_OR_MIXED"
    )
    evidence["state"] = state
    evidence["crisis_classification_eligible"] = len(parts) == 2 and direction > 0.75
    return FundamentalComponent(
        code=code,
        layer=1,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="INFERRED",
        explanation=(
            f"Financial stress is {state.lower().replace('_', ' ')}. Rising "
            "stress supports defensive gold demand but also raises liquidation risk."
        ),
        evidence=evidence,
    )


def _inflation_regime_component(
    series: dict[str, list[FundamentalObservation]],
    as_of: datetime,
) -> FundamentalComponent:
    code = "INFLATION_REGIME"
    weights = {
        "US_CPI_HEADLINE": 0.20,
        "US_CPI_CORE": 0.30,
        "US_PCE_HEADLINE": 0.20,
        "US_PCE_CORE": 0.30,
    }
    metrics: list[tuple[str, float, float, float, datetime]] = []
    for series_code, weight in weights.items():
        values = series.get(series_code, [])
        yoy = _year_over_year_metrics(values)
        if yoy is None:
            continue
        level, prior_level = yoy
        metrics.append(
            (
                series_code,
                weight,
                level,
                level - prior_level,
                values[-1].available_at,
            )
        )
    if len(metrics) < 2:
        return _missing_component(
            code,
            layer=1,
            explanation=(
                "At least two vintage-aware CPI/PCE histories with 16 monthly "
                "observations are required."
            ),
        )
    total_weight = sum(item[1] for item in metrics)
    level = sum(weight * value for _, weight, value, _, _ in metrics) / total_weight
    momentum = sum(weight * change for _, weight, _, change, _ in metrics) / total_weight
    direction = clamp(
        -0.75 * momentum / 0.50 - 0.25 * (level - 2.5) / 1.5,
        -1,
        1,
    )
    freshness = sum(
        _freshness(
            available_at,
            as_of,
            half_life_days=30,
            expiry_days=75,
        )
        for _, _, _, _, available_at in metrics
    ) / len(metrics)
    confidence = 88.0 if len(metrics) == 4 else 76.0
    quality = 92.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    state = (
        "REFLATION_OR_ACCELERATION"
        if momentum > 0.15
        else "DISINFLATION"
        if momentum < -0.15
        else "STABLE_INFLATION"
    )
    return FundamentalComponent(
        code=code,
        layer=1,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            f"Inflation is classified as {state.lower().replace('_', ' ')}: "
            f"weighted year-over-year level {level:.2f}% and three-month "
            f"rate-of-change {momentum:+.2f} percentage points."
        ),
        evidence={
            "state": state,
            "weighted_yoy_pct": round(level, 4),
            "three_month_yoy_change_pp": round(momentum, 4),
            "series": [
                {
                    "series_code": series_code,
                    "configured_weight": weight,
                    "latest_yoy_pct": round(value, 4),
                    "three_month_yoy_change_pp": round(change, 4),
                    "latest_available_at": available_at.isoformat(),
                }
                for series_code, weight, value, change, available_at in metrics
            ],
            "interpretation": (
                "Direction reflects the configured rates-reaction template: "
                "disinflation is gold-supportive, while accelerating/high "
                "inflation is gold-negative unless market pricing proves otherwise."
            ),
        },
    )


def _fed_path_component(
    series: dict[str, list[FundamentalObservation]],
    points: list[PolicyPathFundamentalPoint],
    quarterly_points: list[QuarterlyPolicyExpectationPoint],
    as_of: datetime,
) -> FundamentalComponent:
    code = "FED_PATH"
    current_rates = series.get("US_FED_FUNDS_EFFECTIVE", [])
    if not current_rates:
        return _missing_component(
            code,
            layer=2,
            explanation=(
                "The expected Fed path requires both a current policy-rate "
                "observation and a point-in-time probability surface."
            ),
        )
    eligible = [
        point
        for point in points
        if point.available_at <= as_of
        and point.snapshot_as_of <= as_of
        and point.meeting_date >= as_of.date()
    ]
    snapshots: dict[
        tuple[str, datetime, datetime],
        list[PolicyPathFundamentalPoint],
    ] = {}
    for point in eligible:
        snapshots.setdefault(
            (
                point.provider_code,
                point.snapshot_as_of,
                point.available_at,
            ),
            [],
        ).append(point)
    if not snapshots:
        return _quarterly_fed_path_component(
            current_rate=current_rates[-1].value,
            points=quarterly_points,
            as_of=as_of,
        )
    ordered_snapshots = sorted(
        snapshots.items(),
        key=lambda item: (item[0][2], item[0][1]),
    )
    latest_key, latest_points = ordered_snapshots[-1]
    latest_path = _expected_meeting_path(latest_points)
    if not latest_path:
        return _missing_component(
            code,
            layer=2,
            explanation="No complete meeting probability distribution is available.",
        )
    current_rate = current_rates[-1].value
    destination_rate = latest_path[-1]["expected_rate"]
    destination_signal = clamp(
        (current_rate - destination_rate) / 1.0,
        -1,
        1,
    )
    previous_path: list[dict[str, Any]] = []
    for previous_key, previous_points in reversed(ordered_snapshots[:-1]):
        if previous_key[0] == latest_key[0]:
            previous_path = _expected_meeting_path(previous_points)
            if previous_path:
                break
    repricing_change: float | None = None
    repricing_signal = 0.0
    if previous_path:
        latest_by_meeting = {item["meeting_date"]: item["expected_rate"] for item in latest_path}
        prior_by_meeting = {item["meeting_date"]: item["expected_rate"] for item in previous_path}
        common = sorted(set(latest_by_meeting) & set(prior_by_meeting))
        if common:
            repricing_change = sum(
                latest_by_meeting[meeting] - prior_by_meeting[meeting] for meeting in common
            ) / len(common)
            repricing_signal = clamp(-repricing_change / 0.25, -1, 1)
    direction = (
        0.65 * repricing_signal + 0.35 * destination_signal
        if repricing_change is not None
        else destination_signal
    )
    direction = clamp(direction, -1, 1)
    freshness = _freshness(
        latest_key[2],
        as_of,
        half_life_days=1,
        expiry_days=7,
    )
    confidence = 88.0 if repricing_change is not None else 70.0
    quality = 80.0 if latest_key[0].startswith("MANUAL") else 90.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    first_move = next(
        (item for item in latest_path if abs(item["expected_rate"] - current_rate) >= 0.125),
        None,
    )
    stance = (
        "DOVISH_REPRICING"
        if direction > 0.15
        else "HAWKISH_REPRICING"
        if direction < -0.15
        else "LITTLE_NET_REPRICING"
    )
    return FundamentalComponent(
        code=code,
        layer=2,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            f"The complete expected policy path indicates "
            f"{stance.lower().replace('_', ' ')}; destination "
            f"{destination_rate:.3f}% versus current effective rate "
            f"{current_rate:.3f}%."
        ),
        evidence={
            "provider_code": latest_key[0],
            "snapshot_as_of": latest_key[1].isoformat(),
            "available_at": latest_key[2].isoformat(),
            "current_effective_rate": current_rate,
            "expected_destination_rate": round(destination_rate, 6),
            "total_expected_change_basis_points": round(
                (destination_rate - current_rate) * 100,
                3,
            ),
            "average_path_repricing_basis_points": (
                round(repricing_change * 100, 3) if repricing_change is not None else None
            ),
            "first_expected_move": first_move,
            "expected_path": latest_path,
            "stance": stance,
            "interpretation_warning": (
                "Expected-rate probabilities are market pricing, not a Federal "
                "Reserve promise. Easing driven by acute stress can produce a "
                "different gold reaction than benign disinflation."
            ),
        },
    )


def _expected_meeting_path(
    points: list[PolicyPathFundamentalPoint],
) -> list[dict[str, Any]]:
    meetings: dict[date, list[PolicyPathFundamentalPoint]] = {}
    for point in points:
        meetings.setdefault(point.meeting_date, []).append(point)
    path: list[dict[str, Any]] = []
    for meeting_date, outcomes in sorted(meetings.items()):
        probability_sum = sum(outcome.probability for outcome in outcomes)
        if abs(probability_sum - 1.0) > 0.01:
            continue
        expected_rate = (
            sum(
                outcome.probability
                * (
                    outcome.expected_rate
                    if outcome.expected_rate is not None
                    else outcome.outcome_basis_points / 100
                )
                for outcome in outcomes
            )
            / probability_sum
        )
        path.append(
            {
                "meeting_date": meeting_date.isoformat(),
                "expected_rate": round(expected_rate, 6),
                "probability_sum": round(probability_sum, 8),
                "outcomes": [
                    {
                        "outcome_key_basis_points": outcome.outcome_basis_points,
                        "expected_rate": (
                            outcome.expected_rate
                            if outcome.expected_rate is not None
                            else outcome.outcome_basis_points / 100
                        ),
                        "probability": outcome.probability,
                    }
                    for outcome in sorted(
                        outcomes,
                        key=lambda item: item.outcome_basis_points,
                    )
                ],
                "source_record_keys": [outcome.source_record_key for outcome in outcomes],
            }
        )
    return path


def _quarterly_fed_path_component(
    *,
    current_rate: float,
    points: list[QuarterlyPolicyExpectationPoint],
    as_of: datetime,
) -> FundamentalComponent:
    code = "FED_PATH"
    eligible = [
        point
        for point in points
        if point.available_at <= as_of
        and point.snapshot_as_of <= as_of
        and point.reference_end >= as_of.date()
    ]
    snapshots: dict[
        tuple[str, datetime, datetime],
        list[QuarterlyPolicyExpectationPoint],
    ] = {}
    for point in eligible:
        snapshots.setdefault(
            (
                point.provider_code,
                point.snapshot_as_of,
                point.available_at,
            ),
            [],
        ).append(point)
    if not snapshots:
        return _missing_component(
            code,
            layer=2,
            explanation="The point-in-time expected Fed path is unavailable.",
        )

    ordered_snapshots = sorted(
        snapshots.items(),
        key=lambda item: (item[0][2], item[0][1]),
    )
    latest_key, latest_points = ordered_snapshots[-1]
    latest_path = _quarterly_expected_path(latest_points)
    probability_windows = [
        item
        for item in latest_path
        if item["probability_bins"]
        or item["probability_cut"] is not None
        or item["probability_hike"] is not None
    ]
    latest_path = (probability_windows or latest_path)[:4]
    if not latest_path:
        return _missing_component(
            code,
            layer=2,
            explanation="No complete quarterly SOFR expectation path is available.",
        )

    destination_rate = latest_path[-1]["expected_average_sofr"]
    destination_signal = clamp(
        (current_rate - destination_rate) / 1.0,
        -1,
        1,
    )
    previous_path: list[dict[str, Any]] = []
    for previous_key, previous_points in reversed(ordered_snapshots[:-1]):
        if previous_key[0] != latest_key[0]:
            continue
        previous_all = _quarterly_expected_path(previous_points)
        previous_probability_windows = [
            item
            for item in previous_all
            if item["probability_bins"]
            or item["probability_cut"] is not None
            or item["probability_hike"] is not None
        ]
        previous_path = (previous_probability_windows or previous_all)[:4]
        if previous_path:
            break

    repricing_change: float | None = None
    repricing_signal = 0.0
    if previous_path:
        latest_by_window = {
            item["reference_start"]: item["expected_average_sofr"] for item in latest_path
        }
        prior_by_window = {
            item["reference_start"]: item["expected_average_sofr"] for item in previous_path
        }
        common = sorted(set(latest_by_window) & set(prior_by_window))
        if common:
            repricing_change = sum(
                latest_by_window[window] - prior_by_window[window] for window in common
            ) / len(common)
            repricing_signal = clamp(-repricing_change / 0.25, -1, 1)

    direction = (
        0.65 * repricing_signal + 0.35 * destination_signal
        if repricing_change is not None
        else destination_signal
    )
    direction = clamp(direction, -1, 1)
    freshness = _freshness(
        latest_key[2],
        as_of,
        half_life_days=1,
        expiry_days=7,
    )
    confidence = 84.0 if repricing_change is not None else 68.0
    quality = 86.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    first_expected_reference_window = next(
        (
            item
            for item in latest_path
            if abs(item["expected_average_sofr"] - current_rate) >= 0.125
        ),
        None,
    )
    stance = (
        "DOVISH_REPRICING"
        if direction > 0.15
        else "HAWKISH_REPRICING"
        if direction < -0.15
        else "LITTLE_NET_REPRICING"
    )
    return FundamentalComponent(
        code=code,
        layer=2,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            "The real quarterly SOFR-options-implied path indicates "
            f"{stance.lower().replace('_', ' ')}; the fourth liquid reference "
            f"window averages {destination_rate:.3f}% versus the current "
            f"effective fed funds rate of {current_rate:.3f}%."
        ),
        evidence={
            "provider_code": latest_key[0],
            "snapshot_as_of": latest_key[1].isoformat(),
            "available_at": latest_key[2].isoformat(),
            "availability_quality": latest_points[0].availability_quality,
            "current_effective_rate": current_rate,
            "expected_destination_rate": round(destination_rate, 6),
            "total_expected_change_basis_points": round(
                (destination_rate - current_rate) * 100,
                3,
            ),
            "average_path_repricing_basis_points": (
                round(repricing_change * 100, 3) if repricing_change is not None else None
            ),
            "first_expected_reference_window": first_expected_reference_window,
            "expected_path": latest_path,
            "stance": stance,
            "source_semantics": "QUARTERLY_AVERAGE_SOFR_OPTIONS_DISTRIBUTION",
            "exact_fomc_meeting_probability": False,
            "interpretation_warning": (
                "This is a real market-implied quarterly average SOFR distribution, "
                "not an exact meeting-date FedWatch probability. SOFR and effective "
                "fed funds can also differ by a basis spread. It cannot identify "
                "the exact timing of the first FOMC move."
            ),
        },
    )


def _quarterly_expected_path(
    points: list[QuarterlyPolicyExpectationPoint],
) -> list[dict[str, Any]]:
    return [
        {
            "reference_start": point.reference_start.isoformat(),
            "reference_end": point.reference_end.isoformat(),
            "expected_average_sofr": round(point.rate_mean_basis_points / 100, 6),
            "p25_rate": round(point.rate_p25_basis_points / 100, 6),
            "mode_rate": round(point.rate_mode_basis_points / 100, 6),
            "p75_rate": round(point.rate_p75_basis_points / 100, 6),
            "probability_cut": point.probability_cut,
            "probability_hike": point.probability_hike,
            "probability_bins": list(point.probability_bins),
            "source_record_key": point.source_record_key,
        }
        for point in sorted(points, key=lambda item: item.reference_start)
    ]


def _growth_regime_component(
    series: dict[str, list[FundamentalObservation]],
    as_of: datetime,
) -> FundamentalComponent:
    code = "GROWTH_REGIME"
    directional_parts: list[tuple[str, float, float, datetime]] = []
    evidence: dict[str, Any] = {}
    gdp = series.get("US_REAL_GDP", [])
    if len(gdp) >= 3 and gdp[-2].value > 0 and gdp[-3].value > 0:
        latest = ((gdp[-1].value / gdp[-2].value) ** 4 - 1) * 100
        previous = ((gdp[-2].value / gdp[-3].value) ** 4 - 1) * 100
        change = latest - previous
        gdp_direction = clamp(-change / 2.0 - min(latest, 0) / 2.0, -1, 1)
        directional_parts.append(("US_REAL_GDP", 0.60, gdp_direction, gdp[-1].available_at))
        evidence["real_gdp"] = {
            "latest_qoq_annualized_pct": round(latest, 4),
            "prior_qoq_annualized_pct": round(previous, 4),
            "change_pp": round(change, 4),
            "latest_available_at": gdp[-1].available_at.isoformat(),
        }
    retail = series.get("US_RETAIL_SALES", [])
    retail_metrics = _year_over_year_metrics(retail)
    if retail_metrics is not None:
        latest, prior = retail_metrics
        change = latest - prior
        retail_direction = clamp(-change / 2.0 - min(latest, 0) / 2.0, -1, 1)
        directional_parts.append(
            (
                "US_RETAIL_SALES",
                0.40,
                retail_direction,
                retail[-1].available_at,
            )
        )
        evidence["retail_sales"] = {
            "latest_yoy_pct": round(latest, 4),
            "three_month_yoy_change_pp": round(change, 4),
            "latest_available_at": retail[-1].available_at.isoformat(),
        }
    if not directional_parts:
        return _missing_component(
            code,
            layer=1,
            explanation="Vintage-aware real GDP or retail-sales history is unavailable.",
        )
    total_weight = sum(part[1] for part in directional_parts)
    direction = sum(weight * value for _, weight, value, _ in directional_parts) / total_weight
    freshness = sum(
        _freshness(
            available_at,
            as_of,
            half_life_days=45,
            expiry_days=150,
        )
        for _, _, _, available_at in directional_parts
    ) / len(directional_parts)
    confidence = 82.0 if len(directional_parts) == 2 else 66.0
    quality = 90.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    state = "WEAKENING" if direction > 0.20 else "STRENGTHENING" if direction < -0.20 else "STABLE"
    evidence["state"] = state
    return FundamentalComponent(
        code=code,
        layer=1,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            f"Growth is {state.lower()}; weakening activity is interpreted as "
            "gold-supportive through easing and defensive-demand channels."
        ),
        evidence=evidence,
    )


def _labour_regime_component(
    series: dict[str, list[FundamentalObservation]],
    as_of: datetime,
) -> FundamentalComponent:
    code = "LABOUR_REGIME"
    parts: list[tuple[str, float, float, datetime]] = []
    evidence: dict[str, Any] = {}
    payrolls = series.get("US_NONFARM_PAYROLLS", [])
    if len(payrolls) >= 5:
        latest_change = payrolls[-1].value - payrolls[-2].value
        prior_changes = [
            payrolls[index].value - payrolls[index - 1].value
            for index in range(len(payrolls) - 4, len(payrolls) - 1)
        ]
        prior_average = sum(prior_changes) / len(prior_changes)
        direction = clamp(-(latest_change - prior_average) / 100.0, -1, 1)
        parts.append(("US_NONFARM_PAYROLLS", 0.35, direction, payrolls[-1].available_at))
        evidence["payrolls"] = {
            "latest_change_thousands": round(latest_change, 3),
            "prior_three_month_average_thousands": round(prior_average, 3),
        }
    unemployment = series.get("US_UNEMPLOYMENT_RATE", [])
    if len(unemployment) >= 4:
        change = unemployment[-1].value - unemployment[-4].value
        direction = clamp(change / 0.30, -1, 1)
        parts.append(
            (
                "US_UNEMPLOYMENT_RATE",
                0.25,
                direction,
                unemployment[-1].available_at,
            )
        )
        evidence["unemployment"] = {
            "latest_pct": unemployment[-1].value,
            "three_month_change_pp": round(change, 4),
        }
    wages = series.get("US_AVERAGE_HOURLY_EARNINGS", [])
    wage_metrics = _year_over_year_metrics(wages)
    if wage_metrics is not None:
        latest, prior = wage_metrics
        change = latest - prior
        direction = clamp(-change / 0.40, -1, 1)
        parts.append(
            (
                "US_AVERAGE_HOURLY_EARNINGS",
                0.20,
                direction,
                wages[-1].available_at,
            )
        )
        evidence["wages"] = {
            "latest_yoy_pct": round(latest, 4),
            "three_month_yoy_change_pp": round(change, 4),
        }
    claims = series.get("US_INITIAL_JOBLESS_CLAIMS", [])
    if len(claims) >= 8:
        latest_average = sum(point.value for point in claims[-4:]) / 4
        prior_average = sum(point.value for point in claims[-8:-4]) / 4
        change = latest_average - prior_average
        direction = clamp(change / 20_000.0, -1, 1)
        parts.append(
            (
                "US_INITIAL_JOBLESS_CLAIMS",
                0.20,
                direction,
                claims[-1].available_at,
            )
        )
        evidence["initial_claims"] = {
            "latest_four_week_average": round(latest_average, 3),
            "prior_four_week_average": round(prior_average, 3),
            "change": round(change, 3),
        }
    if len(parts) < 2:
        return _missing_component(
            code,
            layer=1,
            explanation=(
                "At least two vintage-aware payroll, unemployment, wage, or "
                "claims histories are required."
            ),
        )
    total_weight = sum(part[1] for part in parts)
    direction = sum(weight * value for _, weight, value, _ in parts) / total_weight
    freshness = sum(
        _freshness(
            available_at,
            as_of,
            half_life_days=21,
            expiry_days=60,
        )
        for _, _, _, available_at in parts
    ) / len(parts)
    confidence = 84.0 if len(parts) == 4 else 74.0
    quality = 91.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    state = "WEAKENING" if direction > 0.20 else "TIGHTENING" if direction < -0.20 else "BALANCED"
    evidence["state"] = state
    evidence["series_count"] = len(parts)
    return FundamentalComponent(
        code=code,
        layer=1,
        direction=round(direction, 6),
        strength=round(abs(direction) * 100, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            f"Labour conditions are {state.lower()}; the sign represents the "
            "configured gold impact through Fed repricing and defensive demand."
        ),
        evidence=evidence,
    )


def _cot_component(eligible: list[CotFundamentalPoint], as_of: datetime) -> FundamentalComponent:
    code = "POSITIONING_FLOW"
    if len(eligible) < 2:
        return _missing_component(
            code,
            layer=3,
            explanation="At least two published COT reports are required.",
        )
    current = eligible[-1]
    previous = eligible[-2]
    net_change = current.managed_money_net - previous.managed_money_net
    normalization = max(current.open_interest * 0.05, 1)
    direction = clamp(net_change / normalization, -1, 1)
    freshness = _freshness(current.publication_at, as_of, half_life_days=7, expiry_days=14)
    quality = 96.0 if current.availability_quality == "EXACT_OFFICIAL_SCHEDULE" else 78.0
    confidence = 82.0
    strength = abs(direction) * 100
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * direction * certainty_fraction
    return FundamentalComponent(
        code=code,
        layer=3,
        direction=round(direction, 6),
        strength=round(strength, 3),
        confidence=confidence,
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="CALCULATED",
        explanation=(
            "Published managed-money net positioning increased, indicating fresh bullish positioning pressure."
            if direction > 0
            else "Published managed-money net positioning decreased, indicating bearish positioning pressure or long reduction."
            if direction < 0
            else "Published managed-money net positioning was unchanged."
        ),
        evidence={
            "observation_date": current.observation_date.isoformat(),
            "publication_at": current.publication_at.isoformat(),
            "availability_quality": current.availability_quality,
            "managed_money_long": current.managed_money_long,
            "managed_money_short": current.managed_money_short,
            "managed_money_net": current.managed_money_net,
            "prior_managed_money_net": previous.managed_money_net,
            "net_change": net_change,
            "open_interest": current.open_interest,
            "classification_warning": "Position motive is inferred; CFTC categories do not reveal individual intent.",
        },
    )


def _event_surprise_component(
    eligible: list[EventSurprisePoint],
    as_of: datetime,
) -> FundamentalComponent:
    code = "CATALYST_SURPRISE"
    fresh = [point for point in eligible if as_of - point.released_at <= timedelta(days=3)]
    if not fresh:
        return _missing_component(
            code,
            layer=4,
            explanation="No fresh point-in-time forecast/actual event surprise is available.",
        )
    latest = fresh[-1]
    freshness = _freshness(
        latest.available_at,
        as_of,
        half_life_days=0.75,
        expiry_days=3,
    )
    importance_multiplier = 0.60 + 0.08 * latest.importance
    confidence = clamp(
        latest.confidence * importance_multiplier,
        0,
        100,
    )
    quality = 90.0
    certainty_fraction = confidence * freshness * quality / 1_000_000
    contribution = DRIVER_WEIGHTS[code] * clamp(latest.gold_direction, -1, 1) * certainty_fraction
    return FundamentalComponent(
        code=code,
        layer=4,
        direction=round(clamp(latest.gold_direction, -1, 1), 6),
        strength=round(clamp(latest.strength, 0, 100), 3),
        confidence=round(confidence, 3),
        freshness=round(freshness, 3),
        data_quality=quality,
        weight=DRIVER_WEIGHTS[code],
        contribution=round(contribution, 3),
        epistemic_status="INFERRED",
        explanation=latest.event_name
        + " surprise: the configured macro interpretation is "
        + (
            "gold-supportive."
            if latest.gold_direction > 0
            else "gold-negative."
            if latest.gold_direction < 0
            else "directionally neutral."
        ),
        evidence={
            "event_id": latest.event_id,
            "event_code": latest.event_code,
            "component_code": latest.component_code,
            "released_at": latest.released_at.isoformat(),
            "available_at": latest.available_at.isoformat(),
            "importance": latest.importance,
            "surprise_strength": latest.strength,
            "surprise_confidence": latest.confidence,
            "surprise_data_hash": latest.data_hash,
            "classification_warning": (
                "This direction is inferred from the point-in-time surprise and "
                "must be confirmed by yields, USD, and price acceptance."
            ),
        },
    )


def _upcoming_catalyst(
    events: list[FundamentalEventPoint],
    as_of: datetime,
) -> tuple[dict[str, Any] | None, str]:
    canonical: dict[str, FundamentalEventPoint] = {}
    for event in sorted(events, key=lambda item: item.available_at):
        if event.available_at <= as_of:
            canonical[event.source_record_key] = event
    upcoming = sorted(
        (
            event
            for event in canonical.values()
            if event.scheduled_at > as_of
            and event.status not in {"CANCELLED", "RELEASED", "REVISED"}
        ),
        key=lambda item: (item.scheduled_at, -item.importance),
    )
    if not upcoming:
        return None, "UNKNOWN"
    event = upcoming[0]
    seconds = (event.scheduled_at - as_of).total_seconds()
    risk = (
        "EXTREME"
        if event.importance >= 4 and seconds <= 3600
        else "HIGH"
        if event.importance >= 4 and seconds <= 4 * 3600
        else "ELEVATED"
        if event.importance >= 3 and seconds <= 24 * 3600
        else "LOW"
    )
    return (
        {
            "event_id": event.event_id,
            "event_code": event.event_code,
            "name": event.event_name,
            "scheduled_at": event.scheduled_at.isoformat(),
            "importance": event.importance,
            "minutes_until": round(seconds / 60, 1),
            "status": event.status,
        },
        risk,
    )


def _missing_component(code: str, *, layer: int, explanation: str) -> FundamentalComponent:
    return FundamentalComponent(
        code=code,
        layer=layer,
        direction=0.0,
        strength=0.0,
        confidence=0.0,
        freshness=0.0,
        data_quality=0.0,
        weight=DRIVER_WEIGHTS[code],
        contribution=0.0,
        epistemic_status="UNKNOWN",
        explanation=explanation,
        evidence={},
    )


def _freshness(
    available_at: datetime,
    as_of: datetime,
    *,
    half_life_days: float,
    expiry_days: float,
) -> float:
    age_days = max(0.0, (as_of - available_at).total_seconds() / 86_400)
    if age_days > expiry_days:
        return 0.0
    return 100 * math.pow(0.5, age_days / half_life_days)


def _crowding_state(eligible: list[CotFundamentalPoint]) -> dict[str, Any]:
    if not eligible:
        return {"state": "UNKNOWN", "percentile": None}
    current = eligible[-1].managed_money_net
    historical = sorted(point.managed_money_net for point in eligible)
    below_or_equal = sum(value <= current for value in historical)
    percentile = below_or_equal / len(historical) * 100
    state = (
        "CROWDED_LONGS"
        if percentile >= 90
        else "CROWDED_SHORTS"
        if percentile <= 10
        else "BALANCED"
    )
    return {
        "state": state,
        "percentile": round(percentile, 3),
        "managed_money_net": current,
        "history_count": len(historical),
        "publication_at": eligible[-1].publication_at.isoformat(),
    }


def _bias_label(score: float) -> str:
    if score >= 25:
        return "STRONGLY_BULLISH"
    if score >= 12:
        return "MODERATELY_BULLISH"
    if score >= 5:
        return "SLIGHTLY_BULLISH"
    if score <= -25:
        return "STRONGLY_BEARISH"
    if score <= -12:
        return "MODERATELY_BEARISH"
    if score <= -5:
        return "SLIGHTLY_BEARISH"
    return "NEUTRAL_OR_CONFLICTED"


def _regime_label(score: float, components: list[FundamentalComponent]) -> str:
    financial_stress = next(
        component for component in components if component.code == "FINANCIAL_STRESS"
    )
    if (
        financial_stress.epistemic_status != "UNKNOWN"
        and financial_stress.evidence.get("crisis_classification_eligible") is True
    ):
        return "FINANCIAL_CRISIS_OR_LIQUIDITY_STRESS"
    required = {"INFLATION_REGIME", "GROWTH_REGIME", "LABOUR_REGIME"}
    missing = {
        component.code
        for component in components
        if component.code in required and component.epistemic_status == "UNKNOWN"
    }
    if missing:
        return (
            "PARTIAL_RATES_USD_SUPPORTIVE"
            if score >= 5
            else "PARTIAL_RATES_USD_PRESSURE"
            if score <= -5
            else "PARTIAL_RATES_USD_MIXED"
        )
    inflation = next(component for component in components if component.code == "INFLATION_REGIME")
    growth = next(component for component in components if component.code == "GROWTH_REGIME")
    labour = next(component for component in components if component.code == "LABOUR_REGIME")
    inflation_level = float(inflation.evidence.get("weighted_yoy_pct", 2.0))
    inflation_change = float(inflation.evidence.get("three_month_yoy_change_pp", 0.0))
    weakness = (growth.direction + labour.direction) / 2
    if inflation_level < 1.0 and weakness > 0.45:
        return "DEFLATIONARY_STRESS"
    if inflation_level >= 3.0 and inflation_change > 0.10 and weakness > 0.25:
        return "STAGFLATION"
    if inflation_level >= 3.0 and inflation_change > 0.10:
        return "OVERHEATING"
    if weakness > 0.60 and inflation_change < -0.10:
        return "RECESSION_DISINFLATION"
    if weakness > 0.25:
        return "SLOWDOWN"
    if 1.5 <= inflation_level <= 2.6 and abs(inflation_change) <= 0.15:
        return "GOLDILOCKS"
    if inflation_change < -0.10:
        return "SOFT_LANDING"
    return "GOLDILOCKS"


def _reaction_function(components: list[FundamentalComponent]) -> str:
    financial_stress = next(
        component for component in components if component.code == "FINANCIAL_STRESS"
    )
    if financial_stress.epistemic_status != "UNKNOWN" and financial_stress.direction > 0.50:
        return "FINANCIAL_STRESS_FOCUS"
    regime = {
        component.code: component
        for component in components
        if component.code in {"INFLATION_REGIME", "GROWTH_REGIME", "LABOUR_REGIME"}
        and component.epistemic_status != "UNKNOWN"
    }
    catalyst_known = any(
        component.code == "CATALYST_SURPRISE" and component.epistemic_status != "UNKNOWN"
        for component in components
    )
    if not regime:
        return (
            "EVENT_SURPRISE_WITH_PARTIAL_MACRO"
            if catalyst_known
            else "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE"
        )
    inflation_component = regime.get("INFLATION_REGIME")
    inflation_strength = inflation_component.strength if inflation_component is not None else 0.0
    growth_labour_strength = max(
        (
            component.strength
            for code, component in regime.items()
            if code in {"GROWTH_REGIME", "LABOUR_REGIME"}
        ),
        default=0.0,
    )
    if inflation_strength >= growth_labour_strength + 10:
        return "INFLATION_FOCUS"
    if growth_labour_strength >= inflation_strength + 10:
        return "GROWTH_LABOUR_FOCUS"
    return "MIXED_MACRO_REACTION_FUNCTION"


def _year_over_year_metrics(
    values: list[FundamentalObservation],
) -> tuple[float, float] | None:
    if len(values) < 16:
        return None
    if values[-13].value <= 0 or values[-16].value <= 0:
        return None
    latest = (values[-1].value / values[-13].value - 1) * 100
    three_month_prior = (values[-4].value / values[-16].value - 1) * 100
    return latest, three_month_prior


def _layer_statuses(
    components: list[FundamentalComponent],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for layer in range(1, 8):
        members = [component for component in components if component.layer == layer]
        known = [component for component in members if component.epistemic_status != "UNKNOWN"]
        status = (
            "ACTIVE"
            if members and len(known) == len(members)
            else "PARTIAL"
            if known
            else "UNKNOWN"
        )
        rows.append(
            {
                "layer": layer,
                "status": status,
                "known_components": [component.code for component in known],
                "unknown_components": [
                    component.code
                    for component in members
                    if component.epistemic_status == "UNKNOWN"
                ],
            }
        )
    return rows


def _data_hash(
    series: dict[str, list[FundamentalObservation]],
    cot: list[CotFundamentalPoint],
    event_surprises: list[EventSurprisePoint],
    events: list[FundamentalEventPoint],
    policy_path_points: list[PolicyPathFundamentalPoint],
    quarterly_policy_expectations: list[QuarterlyPolicyExpectationPoint],
    as_of: datetime,
) -> str:
    payload = {
        "as_of": as_of.isoformat(),
        "series": {
            code: [
                {
                    "observation_time": point.observation_time.isoformat(),
                    "available_at": point.available_at.isoformat(),
                    "value": point.value,
                    "source_record_key": point.source_record_key,
                }
                for point in values
            ]
            for code, values in sorted(series.items())
        },
        "cot": [asdict(point) for point in cot],
        "event_surprises": [asdict(point) for point in event_surprises],
        "events": [asdict(point) for point in events if point.available_at <= as_of],
        "policy_path_points": [
            asdict(point)
            for point in policy_path_points
            if point.available_at <= as_of and point.snapshot_as_of <= as_of
        ],
        "quarterly_policy_expectations": [
            asdict(point)
            for point in quarterly_policy_expectations
            if point.available_at <= as_of and point.snapshot_as_of <= as_of
        ],
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
