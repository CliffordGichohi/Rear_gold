from __future__ import annotations

from copy import deepcopy

from gold_intel.analytics.session_behaviour_v3_discovery import (
    extract_feature,
    feature_registry,
    interaction_registry,
    registry_fingerprint,
)


def _fact(
    value: object,
    *,
    epistemic_status: str = "CALCULATED",
    quality: str = "VALID",
) -> dict[str, object]:
    return {
        "as_of": "2024-01-02T08:00:00+00:00",
        "available_at": "2024-01-02T08:00:00+00:00",
        "epistemic_status": epistemic_status,
        "evidence": ["SOURCE-1"],
        "explanation": "Synthetic decision-known fact.",
        "invalidation": None,
        "method": "SYNTHETIC",
        "quality": quality,
        "source_refs": [],
        "unit": None,
        "value": value,
    }


def _definition(feature_id: str) -> dict[str, object]:
    return next(
        item for item in feature_registry() if item["feature_id"] == feature_id
    )


def test_registry_is_complete_deterministic_and_contains_no_zn_reopen() -> None:
    features = feature_registry()
    interactions = interaction_registry()

    assert len(features) == 102
    assert len(interactions) == 40
    assert len({item["feature_id"] for item in features}) == 102
    assert len({item["interaction_id"] for item in interactions}) == 40
    assert registry_fingerprint(features, interactions) == (
        "f5702111b9e40024bed20d5aa85173147da6cc772279aa9b142a3b63a9a8c929"
    )
    serialized = repr((features, interactions)).upper()
    assert "ZN.V.0" not in serialized
    assert "UNIVERSAL_ZN_4H_SIGN_V0_1" not in serialized
    assert "LONDON_ZN_4H_POSTHOC_V0_1" not in serialized


def test_series_change_uses_point_in_time_change_and_unknown_policy() -> None:
    decision = {
        "layers": {
            "market_regime": {
                "rates": {
                    "real_yield_10y": _fact(
                        {
                            "absolute_change": -0.11,
                            "change_epistemic_status": "CALCULATED",
                            "previous_record_id": "REAL-0",
                            "record_id": "REAL-1",
                        },
                        epistemic_status="OBSERVED",
                    )
                }
            }
        }
    }
    definition = _definition("MACRO_REAL_YIELD_10Y_CHANGE")

    observed = extract_feature(decision, definition)

    assert observed.state == "FALLING"
    assert observed.epistemic_status == "OBSERVED"
    assert observed.source_signature != "UNKNOWN"

    missing = deepcopy(decision)
    missing["layers"]["market_regime"]["rates"]["real_yield_10y"] = _fact(
        None,
        epistemic_status="UNKNOWN",
        quality="MISSING",
    )
    assert extract_feature(missing, definition).state == "UNKNOWN"


def test_structure_transforms_are_fixed_and_directional() -> None:
    common = {
        "timeframe": "15m",
        "trend_state": _fact("BULLISH"),
        "break_of_structure": _fact(
            {
                "detected": True,
                "detections": [
                    {
                        "detected_at": "2024-01-02T07:30:00+00:00",
                        "kind": "BREAK_OF_STRUCTURE_BEARISH",
                        "timestamp": "2024-01-02T07:15:00+00:00",
                    },
                    {
                        "detected_at": "2024-01-02T07:55:00+00:00",
                        "kind": "BREAK_OF_STRUCTURE_BULLISH",
                        "timestamp": "2024-01-02T07:45:00+00:00",
                    },
                ],
            }
        ),
        "market_structure_shift": _fact({"detected": False, "detections": []}),
        "momentum": _fact({"detected": True, "momentum_atr": -0.42}),
        "compression": _fact({"detected": True, "compression_ratio": 0.70}),
        "range_state": _fact(
            {
                "atr14": 3.0,
                "last_close": 2028.0,
                "range_high": 2030.0,
                "range_low": 2020.0,
            }
        ),
    }
    decision = {"market_structure": {"timeframes": [common]}}

    assert extract_feature(
        decision,
        _definition("STRUCT_15M_TREND"),
    ).state == "BULLISH"
    assert extract_feature(
        decision,
        _definition("STRUCT_15M_LATEST_BOS"),
    ).state == "BULLISH"
    assert extract_feature(
        decision,
        _definition("STRUCT_15M_MOMENTUM"),
    ).state == "NEGATIVE"
    assert extract_feature(
        decision,
        _definition("STRUCT_15M_COMPRESSION"),
    ).state == "DETECTED"
    assert extract_feature(
        decision,
        _definition("STRUCT_15M_RANGE_LOCATION"),
    ).state == "UPPER_THIRD"


def test_session_positioning_and_policy_transforms_preserve_semantics() -> None:
    decision = {
        "layers": {
            "expectations": {
                "policy_path": {
                    "repricing": _fact(
                        {
                            "observation_date": "2024-01-01",
                            "windows": [
                                {
                                    "probability_cut": 0.60,
                                    "probability_hike": 0.20,
                                    "record_id": "WINDOW-1",
                                },
                                {
                                    "probability_cut": 0.40,
                                    "probability_hike": 0.30,
                                    "record_id": "WINDOW-2",
                                },
                            ],
                        },
                        epistemic_status="OBSERVED",
                    )
                }
            },
            "positioning": {
                "inferred_states": [
                    _fact(
                        {"code": "crowding_state", "state": "CROWDED_LONGS"},
                        epistemic_status="INFERRED",
                        quality="UNVERIFIED_AVAILABILITY",
                    )
                ],
                "managed_money": _fact(
                    {"net_contracts": 125_000},
                    epistemic_status="OBSERVED",
                    quality="UNVERIFIED_AVAILABILITY",
                ),
            },
            "sessions_and_liquidity": {
                "asia_state": _fact(
                    {
                        "average_spread": 0.10,
                        "close": 2027.0,
                        "high": 2028.0,
                        "low": 2020.0,
                        "maximum_spread": 0.20,
                        "open": 2022.0,
                        "range": 8.0,
                        "source_hash": "ASIA-HASH",
                    },
                    epistemic_status="OBSERVED",
                )
            },
        }
    }

    assert extract_feature(
        decision,
        _definition("SESSION_ASIA_DIRECTION"),
    ).state == "UP"
    assert extract_feature(
        decision,
        _definition("SESSION_ASIA_SPREAD_EXPANSION"),
    ).state == "WIDE"
    assert extract_feature(
        decision,
        _definition("POSITION_MANAGED_MONEY_NET"),
    ).state == "NET_LONG"
    assert extract_feature(
        decision,
        _definition("POSITION_CROWDING_STATE"),
    ).state == "CROWDED_LONGS"
    assert extract_feature(
        decision,
        _definition("EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE"),
    ).state == "CUT_DOMINANT"


def test_interactions_are_exact_two_condition_preregistrations() -> None:
    features = {item["feature_id"]: item for item in feature_registry()}
    for interaction in interaction_registry():
        assert len(interaction["conditions"]) == 2
        left, right = interaction["conditions"]
        assert left["feature_id"] != right["feature_id"]
        assert left["state"] in features[left["feature_id"]]["tested_states"]
        assert right["state"] in features[right["feature_id"]]["tested_states"]
        assert set(interaction["sessions"]).issubset(
            set(features[left["feature_id"]]["sessions"])
            & set(features[right["feature_id"]]["sessions"])
        )
