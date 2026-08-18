from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from gold_intel.analytics.session_behaviour_v3 import (
    HORIZONS,
    REQUIRED_TIMEFRAMES,
    RESEARCH_POLICY,
    _build_subsequent_behaviour,
    case_record_hash,
    fact,
    validate_case_semantics,
    validate_json_schema,
)


def test_unknown_fact_payload_must_be_null() -> None:
    with pytest.raises(ValueError, match="UNKNOWN facts must have null value"):
        fact(
            {"invented": True},
            epistemic_status="UNKNOWN",
            as_of=None,
            available_at=None,
            quality="MISSING",
            method=None,
            explanation="Unavailable.",
        )


def test_neutral_subsequent_behaviour_uses_0801_and_fixed_horizon_closes() -> None:
    decision = datetime(2024, 6, 3, 7, 0, tzinfo=UTC)
    observation_end = decision + timedelta(hours=4)
    bars = [_measurement_bar(decision + timedelta(minutes=index + 1), index) for index in range(239)]
    session = _source_session(decision, observation_end)

    outcome = _build_subsequent_behaviour(
        session=session,
        measurement_bars=bars,
    )

    assert outcome["decision_eligible"] is False
    assert outcome["neutral_reference"]["timestamp"] == (
        decision + timedelta(minutes=1)
    ).isoformat()
    assert outcome["neutral_reference"]["trade_entry_assumed"] is False
    assert outcome["path"]["one_minute_source_count"] == 239
    assert outcome["path"]["missing_one_minute_bars"] == 0
    assert len(outcome["path"]["five_minute_points"]) == 48
    assert [item["horizon"] for item in outcome["fixed_horizons"]] == [
        item[0] for item in HORIZONS
    ]
    assert outcome["fixed_horizons"][0]["signed_displacement"]["value"] == 0.05
    assert outcome["neutral_excursions"]["maximum_upward_displacement"]["value"] == 2.58
    assert outcome["neutral_excursions"]["maximum_downward_displacement"]["value"] == -0.1
    assert outcome["extremes"]["extreme_order"]["value"] == "LOW_FIRST"
    assert outcome["path_classification"]["value"]["net_state"] == "UP"


def test_semantic_validator_rejects_future_decision_fact() -> None:
    case = _minimal_semantic_case()
    future_fact = _known_fact(
        "future",
        available_at="2024-01-02T08:01:00+00:00",
    )
    case["decision_state"]["synthesis"]["supporting_evidence"].append(future_fact)
    case["case_metadata"]["record_hash"] = case_record_hash(case)

    errors = validate_case_semantics(case)

    assert any(error.startswith("FUTURE_DECISION_FACT") for error in errors)


def test_semantic_validator_accepts_minimal_valid_boundary() -> None:
    case = _minimal_semantic_case()

    assert validate_case_semantics(case) == []


def test_json_schema_subset_enforces_conditional_unknown_null() -> None:
    schema = {
        "type": "object",
        "properties": {
            "epistemic_status": {"enum": ["OBSERVED", "UNKNOWN"]},
            "value": {},
        },
        "required": ["epistemic_status", "value"],
        "allOf": [
            {
                "if": {
                    "properties": {"epistemic_status": {"const": "UNKNOWN"}},
                    "required": ["epistemic_status"],
                },
                "then": {"properties": {"value": {"type": "null"}}},
            }
        ],
        "additionalProperties": False,
    }

    assert validate_json_schema(
        {"epistemic_status": "UNKNOWN", "value": None},
        schema,
    ) == []
    assert validate_json_schema(
        {"epistemic_status": "UNKNOWN", "value": 0},
        schema,
    ) == ["$.value:TYPE_null"]


def _measurement_bar(open_time: datetime, index: int) -> dict[str, object]:
    open_price = round(1800 + index * 0.01, 2)
    close_price = round(open_price + 0.01, 2)
    return {
        "available_at": (open_time + timedelta(minutes=1)).isoformat(),
        "close_time": (open_time + timedelta(minutes=1)).isoformat(),
        "complete": True,
        "epistemic_status": "OBSERVED",
        "ohlc": {
            "open": open_price,
            "high": round(open_price + 0.2, 2),
            "low": round(open_price - 0.1, 2),
            "close": close_price,
        },
        "open_time": open_time.isoformat(),
        "provider_code": "IC_MARKETS_MT5",
        "record_hash": f"{index + 1:064x}",
        "record_id": f"BAR-{index:03d}",
        "source_record_key": f"BAR-{index:03d}",
        "spread_points": 10,
        "spread_price": 0.1,
        "volume": 100.0,
        "volume_type": "TICK",
        "casebook_version": "GOLD_CASEBOOK_V0_1",
    }


def _source_session(
    decision: datetime,
    observation_end: datetime,
) -> dict[str, object]:
    path: list[dict[str, object]] = []
    for index in range(48):
        open_time = decision + timedelta(minutes=index * 5)
        path.append(
            {
                "open_time": open_time.isoformat(),
                "close_time": (open_time + timedelta(minutes=5)).isoformat(),
                "ohlc": {
                    "open": 1800.0,
                    "high": 1800.2,
                    "low": 1799.9,
                    "close": 1800.1,
                },
                "record_hash": f"{index + 1000:064x}",
                "record_id": f"BAR-5M-{index:02d}",
                "spread_price": 0.1,
                "volume": 500.0,
            }
        )
    return {
        "availability_at": decision.isoformat(),
        "casebook_version": "GOLD_CASEBOOK_V0_1",
        "decision_at": decision.isoformat(),
        "observation_end": observation_end.isoformat(),
        "record_hash": "a" * 64,
        "record_id": "CASE-LONDON-2024-06-03-TEST",
        "session_code": "LONDON",
        "session_date": "2024-06-03",
        "session_timezone": "Europe/London",
        "decision_state": {"known_levels": []},
        "subsequent_observation": {
            "five_minute_path": path,
            "level_interactions": [],
        },
    }


def _minimal_semantic_case() -> dict[str, object]:
    decision_at = "2024-01-02T08:00:00+00:00"
    timeframes = [
        {
            "timeframe": timeframe,
        }
        for timeframe in REQUIRED_TIMEFRAMES
    ]
    case: dict[str, object] = {
        "case_metadata": {
            "case_id": "V3-TEST",
            "decision_at": decision_at,
            "observation_end": "2024-01-02T12:00:00+00:00",
            "data_partition": "DEVELOPMENT_2021_2024",
            "access_class": "DEVELOPMENT",
        },
        "decision_state": {
            "decision_eligible": True,
            "market_structure": {"timeframes": timeframes},
            "synthesis": {
                "supporting_evidence": [_known_fact("known")],
            },
        },
        "subsequent_behaviour": {
            "decision_eligible": False,
            "path": {
                "one_minute_source_count": 239,
                "five_minute_points": [{} for _ in range(48)],
            },
            "fixed_horizons": [
                {"horizon": horizon}
                for horizon, _minutes in HORIZONS
            ],
        },
        "research_policy": dict(RESEARCH_POLICY),
    }
    case["case_metadata"]["record_hash"] = case_record_hash(case)
    return case


def _known_fact(
    value: object,
    *,
    available_at: str = "2024-01-02T08:00:00+00:00",
) -> dict[str, object]:
    return {
        "value": value,
        "unit": None,
        "epistemic_status": "CALCULATED",
        "as_of": available_at,
        "available_at": available_at,
        "quality": "VALID",
        "method": "TEST",
        "explanation": "Test fact.",
        "evidence": [],
        "source_refs": [],
        "invalidation": None,
    }
