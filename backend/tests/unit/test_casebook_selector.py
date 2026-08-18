from __future__ import annotations

import math

import pytest

from gold_intel.backtesting.casebook_selector import (
    FEATURE_FAMILY,
    FEATURE_ID,
    FEATURE_TRANSFORM,
    SelectorFeature,
    select_universal_zn_4h_bias,
)


def _feature(
    *,
    state: str,
    raw_value: float | None,
    source_key: str | None = "CROSS-1|ZN.v.0|4_HOURS|ROW-1",
    point_in_time_eligible: bool = True,
) -> SelectorFeature:
    return SelectorFeature(
        feature_id=FEATURE_ID,
        family_code=FEATURE_FAMILY,
        transform=FEATURE_TRANSFORM,
        state=state,
        raw_value=raw_value,
        source_key=source_key,
        point_in_time_eligible=point_in_time_eligible,
    )


@pytest.mark.parametrize("session_code", ["LONDON", "NEW_YORK"])
def test_universal_rule_maps_positive_to_long_in_both_sessions(
    session_code: str,
) -> None:
    decision = select_universal_zn_4h_bias(
        _feature(state="POSITIVE", raw_value=0.00000001),
        session_code=session_code,
    )

    assert decision.bias == "LONG"
    assert decision.reason_code == "ZN_4H_POSITIVE"


@pytest.mark.parametrize("session_code", ["LONDON", "NEW_YORK"])
def test_universal_rule_maps_negative_to_short_in_both_sessions(
    session_code: str,
) -> None:
    decision = select_universal_zn_4h_bias(
        _feature(state="NEGATIVE", raw_value=-0.00000001),
        session_code=session_code,
    )

    assert decision.bias == "SHORT"
    assert decision.reason_code == "ZN_4H_NEGATIVE"


@pytest.mark.parametrize(
    ("feature", "reason"),
    [
        (_feature(state="FLAT", raw_value=0.0), "ZN_4H_FLAT"),
        (
            _feature(state="UNKNOWN", raw_value=None, source_key=None),
            "ZN_4H_UNKNOWN",
        ),
        (
            _feature(state="POSITIVE", raw_value=None),
            "ZN_4H_VALUE_UNAVAILABLE",
        ),
        (
            _feature(state="NEGATIVE", raw_value=-1.0, source_key=None),
            "ZN_4H_SOURCE_UNAVAILABLE",
        ),
        (
            _feature(
                state="POSITIVE",
                raw_value=1.0,
                point_in_time_eligible=False,
            ),
            "NOT_POINT_IN_TIME_ELIGIBLE",
        ),
        (
            _feature(state="POSITIVE", raw_value=math.nan),
            "ZN_4H_VALUE_UNAVAILABLE",
        ),
    ],
)
def test_unavailable_or_flat_inputs_remain_no_bias(
    feature: SelectorFeature,
    reason: str,
) -> None:
    decision = select_universal_zn_4h_bias(
        feature,
        session_code="LONDON",
    )

    assert decision.bias == "NO_BIAS"
    assert decision.reason_code == reason


@pytest.mark.parametrize(
    "feature",
    [
        _feature(state="POSITIVE", raw_value=0.0),
        _feature(state="NEGATIVE", raw_value=0.0),
        _feature(state="FLAT", raw_value=0.1),
        _feature(state="UNKNOWN", raw_value=0.1),
    ],
)
def test_state_and_raw_sign_mismatches_are_rejected(
    feature: SelectorFeature,
) -> None:
    with pytest.raises(ValueError):
        select_universal_zn_4h_bias(feature, session_code="LONDON")


def test_metadata_or_session_substitution_is_rejected() -> None:
    wrong_feature = SelectorFeature(
        feature_id="cross_zt_v_0_4_hours",
        family_code=FEATURE_FAMILY,
        transform=FEATURE_TRANSFORM,
        state="POSITIVE",
        raw_value=0.1,
        source_key="SOURCE",
    )

    with pytest.raises(ValueError, match="requires feature"):
        select_universal_zn_4h_bias(
            wrong_feature,
            session_code="LONDON",
        )
    with pytest.raises(ValueError, match="Unsupported session"):
        select_universal_zn_4h_bias(
            _feature(state="POSITIVE", raw_value=0.1),
            session_code="ASIA",
        )
