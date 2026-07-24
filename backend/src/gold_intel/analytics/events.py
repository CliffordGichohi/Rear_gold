from __future__ import annotations

import hashlib
import json
import statistics
from dataclasses import asdict, dataclass
from datetime import UTC, date, datetime
from typing import Any
from uuid import UUID

from gold_intel.domain.signals import clamp

SURPRISE_RULESET_VERSION = "economic-surprise-2"


@dataclass(frozen=True, slots=True)
class SurpriseSpecification:
    component_code: str
    gold_sign: float
    fallback_scale: float
    family: str
    higher_description: str
    lower_description: str


SURPRISE_SPECIFICATIONS: tuple[SurpriseSpecification, ...] = (
    SurpriseSpecification(
        "CPI_HEADLINE_MOM",
        -1,
        0.10,
        "INFLATION",
        "hotter headline CPI",
        "cooler headline CPI",
    ),
    SurpriseSpecification(
        "CPI_CORE_MOM",
        -1,
        0.10,
        "INFLATION",
        "hotter core CPI",
        "cooler core CPI",
    ),
    SurpriseSpecification(
        "CPI_HEADLINE_YOY",
        -1,
        0.20,
        "INFLATION",
        "hotter headline CPI",
        "cooler headline CPI",
    ),
    SurpriseSpecification(
        "CPI_CORE_YOY",
        -1,
        0.20,
        "INFLATION",
        "hotter core CPI",
        "cooler core CPI",
    ),
    SurpriseSpecification(
        "PCE_HEADLINE_MOM",
        -1,
        0.10,
        "INFLATION",
        "hotter headline PCE",
        "cooler headline PCE",
    ),
    SurpriseSpecification(
        "PCE_CORE_MOM",
        -1,
        0.10,
        "INFLATION",
        "hotter core PCE",
        "cooler core PCE",
    ),
    SurpriseSpecification(
        "PCE_HEADLINE_YOY",
        -1,
        0.20,
        "INFLATION",
        "hotter headline PCE",
        "cooler headline PCE",
    ),
    SurpriseSpecification(
        "PCE_CORE_YOY",
        -1,
        0.20,
        "INFLATION",
        "hotter core PCE",
        "cooler core PCE",
    ),
    SurpriseSpecification(
        "NFP_CHANGE",
        -1,
        75.0,
        "LABOUR",
        "stronger payroll growth",
        "weaker payroll growth",
    ),
    SurpriseSpecification(
        "UNEMPLOYMENT_RATE",
        1,
        0.10,
        "LABOUR",
        "higher unemployment",
        "lower unemployment",
    ),
    SurpriseSpecification(
        "AVERAGE_HOURLY_EARNINGS_MOM",
        -1,
        0.10,
        "LABOUR",
        "stronger wage growth",
        "weaker wage growth",
    ),
    SurpriseSpecification(
        "AVERAGE_HOURLY_EARNINGS_YOY",
        -1,
        0.20,
        "LABOUR",
        "stronger wage growth",
        "weaker wage growth",
    ),
    SurpriseSpecification(
        "INITIAL_JOBLESS_CLAIMS",
        1,
        20.0,
        "LABOUR",
        "higher jobless claims",
        "lower jobless claims",
    ),
    SurpriseSpecification(
        "GDP_QOQ_ANNUALIZED",
        -1,
        0.50,
        "GROWTH",
        "stronger GDP growth",
        "weaker GDP growth",
    ),
    SurpriseSpecification(
        "RETAIL_SALES_MOM",
        -1,
        0.30,
        "GROWTH",
        "stronger retail sales",
        "weaker retail sales",
    ),
    SurpriseSpecification(
        "FED_TARGET_RATE",
        -1,
        0.25,
        "FED",
        "a more hawkish rate outcome",
        "a more dovish rate outcome",
    ),
)
SURPRISE_SPEC_BY_CODE = {
    specification.component_code: specification for specification in SURPRISE_SPECIFICATIONS
}


@dataclass(frozen=True, slots=True)
class EventReleaseFact:
    event_id: UUID
    release_id: UUID
    event_code: str
    event_name: str
    scheduled_at: datetime
    importance: int
    component_code: str
    observation_period: date
    actual_value: float
    previous_value: float | None
    revised_previous_value: float | None
    unit: str
    released_at: datetime
    available_at: datetime
    is_revision: bool
    vintage: str
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class ForecastFact:
    forecast_id: UUID
    event_code: str
    scheduled_at: datetime
    component_code: str
    forecast_value: float
    unit: str
    forecast_as_of: datetime
    available_at: datetime
    provider_code: str
    vintage: str
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class SurpriseCalculation:
    event_id: UUID
    release_id: UUID
    forecast_id: UUID
    event_code: str
    event_name: str
    component_code: str
    released_at: datetime
    available_at: datetime
    actual_value: float
    forecast_value: float
    previous_value: float | None
    revised_previous_value: float | None
    unit: str
    raw_surprise: float
    standardized_surprise: float
    gold_direction: float
    strength: float
    confidence: float
    history_count: int
    method: str
    epistemic_status: str
    explanation: str
    evidence: dict[str, Any]
    data_hash: str
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class SurpriseBatch:
    calculations: tuple[SurpriseCalculation, ...]
    exclusions: tuple[dict[str, Any], ...]


def calculate_economic_surprises(
    releases: list[EventReleaseFact],
    forecasts: list[ForecastFact],
    *,
    as_of: datetime,
    include_synthetic: bool = False,
) -> SurpriseBatch:
    """Calculate surprises using only pre-release forecasts and eligible releases."""

    if as_of.tzinfo is None:
        raise ValueError("as_of must include a timezone")
    cutoff = as_of.astimezone(UTC)
    eligible_releases = sorted(
        (
            release
            for release in releases
            if release.available_at <= cutoff
            and release.released_at <= cutoff
            and not release.is_revision
            and (include_synthetic or not release.is_synthetic)
        ),
        key=lambda release: (release.released_at, release.available_at),
    )
    forecasts_by_key: dict[tuple[str, datetime, str], list[ForecastFact]] = {}
    for forecast in forecasts:
        if forecast.available_at > cutoff:
            continue
        if forecast.is_synthetic and not include_synthetic:
            continue
        key = (
            forecast.event_code,
            forecast.scheduled_at,
            forecast.component_code,
        )
        forecasts_by_key.setdefault(key, []).append(forecast)

    prior_surprises: dict[str, list[float]] = {}
    calculations: list[SurpriseCalculation] = []
    exclusions: list[dict[str, Any]] = []
    for release in eligible_releases:
        specification = SURPRISE_SPEC_BY_CODE.get(release.component_code)
        if specification is None:
            exclusions.append(
                {
                    "release_id": str(release.release_id),
                    "component_code": release.component_code,
                    "reason": "UNSUPPORTED_COMPONENT",
                }
            )
            continue
        key = (
            release.event_code,
            release.scheduled_at,
            release.component_code,
        )
        candidate_forecasts = [
            forecast
            for forecast in forecasts_by_key.get(key, [])
            if forecast.available_at <= release.released_at
            and forecast.forecast_as_of <= release.released_at
            and forecast.unit == release.unit
        ]
        if not candidate_forecasts:
            exclusions.append(
                {
                    "release_id": str(release.release_id),
                    "component_code": release.component_code,
                    "reason": "NO_ELIGIBLE_PRE_RELEASE_FORECAST",
                }
            )
            continue
        forecast = max(
            candidate_forecasts,
            key=lambda item: (item.available_at, item.forecast_as_of),
        )
        raw_surprise = release.actual_value - forecast.forecast_value
        history = prior_surprises.setdefault(release.component_code, [])
        scale, method = _surprise_scale(history, specification.fallback_scale)
        standardized = clamp(raw_surprise / scale, -4, 4)
        gold_direction = clamp(
            specification.gold_sign * standardized,
            -1,
            1,
        )
        strength = abs(gold_direction) * 100
        confidence = 90.0 if method == "EXPANDING_PRIOR_STD" else 78.0
        if forecast.provider_code.startswith("MANUAL"):
            confidence -= 5.0
        available_at = max(release.available_at, forecast.available_at)
        evidence = {
            "event_code": release.event_code,
            "event_name": release.event_name,
            "scheduled_at": release.scheduled_at.isoformat(),
            "released_at": release.released_at.isoformat(),
            "release_available_at": release.available_at.isoformat(),
            "forecast_as_of": forecast.forecast_as_of.isoformat(),
            "forecast_available_at": forecast.available_at.isoformat(),
            "actual": release.actual_value,
            "forecast": forecast.forecast_value,
            "previous": release.previous_value,
            "revised_previous": release.revised_previous_value,
            "unit": release.unit,
            "raw_surprise": raw_surprise,
            "scale": scale,
            "standardized_surprise": standardized,
            "importance": release.importance,
            "forecast_provider": forecast.provider_code,
            "forecast_vintage": forecast.vintage,
            "release_vintage": release.vintage,
            "gold_sign_policy": specification.gold_sign,
            "interpretation_warning": (
                "The gold direction is inferred from the configured reaction template "
                "and requires yield, USD, and price confirmation."
            ),
        }
        data_hash = _surprise_hash(release, forecast, history, evidence)
        explanation = _explanation(
            specification,
            raw_surprise=raw_surprise,
            actual=release.actual_value,
            forecast=forecast.forecast_value,
            unit=release.unit,
            gold_direction=gold_direction,
        )
        calculations.append(
            SurpriseCalculation(
                event_id=release.event_id,
                release_id=release.release_id,
                forecast_id=forecast.forecast_id,
                event_code=release.event_code,
                event_name=release.event_name,
                component_code=release.component_code,
                released_at=release.released_at,
                available_at=available_at,
                actual_value=release.actual_value,
                forecast_value=forecast.forecast_value,
                previous_value=release.previous_value,
                revised_previous_value=release.revised_previous_value,
                unit=release.unit,
                raw_surprise=round(raw_surprise, 10),
                standardized_surprise=round(standardized, 8),
                gold_direction=round(gold_direction, 6),
                strength=round(strength, 3),
                confidence=round(confidence, 3),
                history_count=len(history),
                method=method,
                epistemic_status="INFERRED",
                explanation=explanation,
                evidence=evidence,
                data_hash=data_hash,
                is_synthetic=release.is_synthetic or forecast.is_synthetic,
            )
        )
        history.append(raw_surprise)
    return SurpriseBatch(
        calculations=tuple(calculations),
        exclusions=tuple(exclusions),
    )


def _surprise_scale(history: list[float], fallback: float) -> tuple[float, str]:
    if len(history) >= 5:
        deviation = statistics.stdev(history)
        if deviation > 1e-12:
            return deviation, "EXPANDING_PRIOR_STD"
    return fallback, "CONFIGURED_FALLBACK_SCALE"


def _explanation(
    specification: SurpriseSpecification,
    *,
    raw_surprise: float,
    actual: float,
    forecast: float,
    unit: str,
    gold_direction: float,
) -> str:
    if abs(raw_surprise) < 1e-12:
        return (
            f"{specification.component_code} matched the eligible pre-release "
            f"consensus at {actual:g} {unit}."
        )
    outcome = (
        specification.higher_description if raw_surprise > 0 else specification.lower_description
    )
    gold_effect = (
        "gold-supportive"
        if gold_direction > 0
        else "gold-negative"
        if gold_direction < 0
        else "directionally neutral"
    )
    return (
        f"Actual {actual:g} versus forecast {forecast:g} {unit} indicates "
        f"{outcome}; the configured macro template is {gold_effect}."
    )


def _surprise_hash(
    release: EventReleaseFact,
    forecast: ForecastFact,
    history: list[float],
    evidence: dict[str, Any],
) -> str:
    payload = {
        "ruleset_version": SURPRISE_RULESET_VERSION,
        "release": asdict(release),
        "forecast": asdict(forecast),
        "prior_surprises": history,
        "evidence": evidence,
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()
