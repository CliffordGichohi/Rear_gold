from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Literal

Bias = Literal["LONG", "SHORT", "NO_BIAS"]
SessionCode = Literal["LONDON", "NEW_YORK"]

CASE_SPECIFICATION_VERSION = "GOLD_CASEBOOK_CASE_SPECIFICATION_V0_1"
SELECTOR_CODE = "UNIVERSAL_ZN_4H_SIGN_V0_1"
FEATURE_ID = "cross_zn_v_0_4_hours"
FEATURE_FAMILY = "INTRADAY_CROSS_MARKET"
FEATURE_TRANSFORM = "SIGN_3"
ALLOWED_SESSIONS = frozenset({"LONDON", "NEW_YORK"})
ALLOWED_STATES = frozenset({"POSITIVE", "NEGATIVE", "FLAT", "UNKNOWN"})


@dataclass(frozen=True, slots=True)
class SelectorFeature:
    feature_id: str
    family_code: str
    transform: str
    state: str
    raw_value: float | None
    source_key: str | None
    point_in_time_eligible: bool = True


@dataclass(frozen=True, slots=True)
class BiasDecision:
    bias: Bias
    reason_code: str
    feature_state: str
    raw_percent_change: float | None
    source_key: str | None
    epistemic_status: Literal["INFERRED"] = "INFERRED"
    selector_code: str = SELECTOR_CODE


def select_universal_zn_4h_bias(
    feature: SelectorFeature,
    *,
    session_code: str,
) -> BiasDecision:
    """Apply the frozen universal ZN four-hour sign rule.

    There is deliberately no configurable threshold and no session-specific
    branch. Metadata or sign inconsistencies raise instead of silently changing
    the frozen rule.
    """

    _validate_contract_identity(feature, session_code=session_code)
    if not feature.point_in_time_eligible:
        return _no_bias(feature, reason_code="NOT_POINT_IN_TIME_ELIGIBLE")

    if feature.state == "UNKNOWN":
        if feature.raw_value is not None:
            raise ValueError("UNKNOWN ZN state cannot carry a raw value")
        return _no_bias(feature, reason_code="ZN_4H_UNKNOWN")

    raw_value = feature.raw_value
    if raw_value is None or not math.isfinite(raw_value):
        return _no_bias(feature, reason_code="ZN_4H_VALUE_UNAVAILABLE")

    if feature.state == "FLAT":
        if raw_value != 0:
            raise ValueError("FLAT ZN state must have an exact zero change")
        return _no_bias(feature, reason_code="ZN_4H_FLAT")

    if not feature.source_key:
        return _no_bias(feature, reason_code="ZN_4H_SOURCE_UNAVAILABLE")

    if feature.state == "POSITIVE":
        if raw_value <= 0:
            raise ValueError("POSITIVE ZN state must have a positive raw change")
        return BiasDecision(
            bias="LONG",
            reason_code="ZN_4H_POSITIVE",
            feature_state=feature.state,
            raw_percent_change=raw_value,
            source_key=feature.source_key,
        )

    if raw_value >= 0:
        raise ValueError("NEGATIVE ZN state must have a negative raw change")
    return BiasDecision(
        bias="SHORT",
        reason_code="ZN_4H_NEGATIVE",
        feature_state=feature.state,
        raw_percent_change=raw_value,
        source_key=feature.source_key,
    )


def _validate_contract_identity(
    feature: SelectorFeature,
    *,
    session_code: str,
) -> None:
    if session_code not in ALLOWED_SESSIONS:
        raise ValueError(f"Unsupported session for frozen selector: {session_code}")
    if feature.feature_id != FEATURE_ID:
        raise ValueError(f"Frozen selector requires feature {FEATURE_ID}")
    if feature.family_code != FEATURE_FAMILY:
        raise ValueError(f"Frozen selector requires family {FEATURE_FAMILY}")
    if feature.transform != FEATURE_TRANSFORM:
        raise ValueError(f"Frozen selector requires transform {FEATURE_TRANSFORM}")
    if feature.state not in ALLOWED_STATES:
        raise ValueError(f"Unsupported frozen feature state: {feature.state}")


def _no_bias(
    feature: SelectorFeature,
    *,
    reason_code: str,
) -> BiasDecision:
    return BiasDecision(
        bias="NO_BIAS",
        reason_code=reason_code,
        feature_state=feature.state,
        raw_percent_change=feature.raw_value,
        source_key=feature.source_key,
    )
