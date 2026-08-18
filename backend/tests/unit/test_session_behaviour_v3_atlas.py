from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from gold_intel.analytics.session_behaviour_v3_atlas import (
    AtlasCase,
    LevelInteraction,
    PathPoint,
    build_atlas_document,
    direction_frequency,
    extract_atlas_case,
    summarize_numeric,
    validate_atlas_semantics,
    verify_atlas_hash,
)


def test_numeric_summary_uses_frozen_type_7_percentiles_and_sample_std() -> None:
    summary = summarize_numeric(
        [Decimal("1"), Decimal("2"), Decimal("3"), Decimal("4"), None]
    )

    assert summary == {
        "count": 4,
        "missing_count": 1,
        "mean": 2.5,
        "standard_deviation": 1.29099445,
        "minimum": 1.0,
        "p05": 1.15,
        "p10": 1.3,
        "p25": 1.75,
        "median": 2.5,
        "p75": 3.25,
        "p90": 3.7,
        "p95": 3.85,
        "maximum": 4.0,
    }


def test_direction_frequency_honours_flat_epsilon() -> None:
    frequency = direction_frequency(
        [
            Decimal("-0.02"),
            Decimal("-0.01"),
            Decimal("0"),
            Decimal("0.01"),
            Decimal("0.02"),
        ]
    )

    assert frequency["denominator"] == 5
    assert frequency["states"]["UP"] == {"count": 1, "percentage": 20.0}
    assert frequency["states"]["DOWN"] == {"count": 1, "percentage": 20.0}
    assert frequency["states"]["FLAT"] == {"count": 3, "percentage": 60.0}


def test_extract_atlas_case_maps_level_identity_without_other_decision_values() -> None:
    record = _source_record()

    case = extract_atlas_case(record)

    assert case.case_id == "V3-TEST"
    assert case.session_code == "LONDON"
    assert case.fixed_horizons["SESSION_CLOSE"] == Decimal("1.5")
    assert len(case.path) == 48
    assert case.level_interactions == (
        LevelInteraction(
            level_id="LEVEL-1",
            level_type="ASIA_HIGH",
            first_interaction_at=datetime(2024, 1, 2, 8, 30, tzinfo=UTC),
            touched=True,
            breached=True,
            accepted=False,
            rejected=True,
            failed_break=False,
            retested=False,
        ),
    )


def test_full_atlas_keeps_sessions_separate_and_reconciles() -> None:
    london = [_atlas_case("LONDON", index) for index in range(833)]
    new_york = [_atlas_case("NEW_YORK", index) for index in range(826)]

    atlas = build_atlas_document([*london, *new_york])

    assert verify_atlas_hash(atlas)
    assert validate_atlas_semantics(atlas) == []
    assert atlas["case_counts"] == {
        "total": 1659,
        "london": 833,
        "new_york": 826,
    }
    assert set(atlas["sessions"]) == {"LONDON", "NEW_YORK"}
    assert atlas["interpretation_boundary"]["combined_session_result"] is False
    assert (
        atlas["sessions"]["LONDON"]["direction_frequencies"]["SESSION_CLOSE"][
            "denominator"
        ]
        == 833
    )
    assert (
        atlas["sessions"]["NEW_YORK"]["direction_frequencies"]["SESSION_CLOSE"][
            "denominator"
        ]
        == 826
    )
    serialized = json.loads(json.dumps(atlas, sort_keys=True))
    assert validate_atlas_semantics(serialized) == []


def test_atlas_hash_detects_tampering() -> None:
    atlas = build_atlas_document(
        [
            *[_atlas_case("LONDON", index) for index in range(833)],
            *[_atlas_case("NEW_YORK", index) for index in range(826)],
        ]
    )
    atlas["sessions"]["LONDON"]["case_count"] = 832

    assert not verify_atlas_hash(atlas)
    assert "ATLAS_HASH_MISMATCH" in validate_atlas_semantics(atlas)


def _atlas_case(session_code: str, index: int) -> AtlasCase:
    year = 2021 + index % 4
    month = 1 + index % 12
    day = 1 + index % 20
    session_date = date(year, month, day)
    while session_date.weekday() >= 5:
        session_date += timedelta(days=1)
    decision_at = datetime(year, month, day, 8, tzinfo=UTC)
    sign = Decimal("1") if index % 2 == 0 else Decimal("-1")
    path = tuple(
        PathPoint(
            offset_minutes=offset,
            close=Decimal("1800") + sign * Decimal(offset + 5) / Decimal(10),
        )
        for offset in range(0, 240, 5)
    )
    close = sign * Decimal("2")
    return AtlasCase(
        case_id=f"V3-{session_code}-{index:04d}",
        session_code=session_code,
        session_date=session_date,
        decision_at=decision_at,
        neutral_price=Decimal("1800"),
        fixed_horizons={
            "5m": sign * Decimal("0.5"),
            "15m": sign * Decimal("0.75"),
            "30m": sign,
            "60m": sign * Decimal("1.25"),
            "SESSION_CLOSE": close,
        },
        signed_close_displacement=close,
        absolute_close_displacement=abs(close),
        maximum_upward_displacement=Decimal("4"),
        maximum_downward_displacement=Decimal("-3"),
        session_range=Decimal("7"),
        path_efficiency=Decimal("0.28571429"),
        close_location_fraction=Decimal("0.6"),
        session_high_at=decision_at + timedelta(minutes=60),
        session_low_at=decision_at + timedelta(minutes=180),
        extreme_order="HIGH_FIRST",
        path=path,
        level_interactions=(),
    )


def _source_record() -> dict[str, object]:
    decision_at = datetime(2024, 1, 2, 8, tzinfo=UTC)
    path = [
        {
            "offset_minutes": offset,
            "xauusd": {"value": {"ohlc": {"close": 1800 + offset / 100}}},
        }
        for offset in range(0, 240, 5)
    ]
    fixed = [
        {
            "horizon": horizon,
            "signed_displacement": {"value": value},
        }
        for horizon, value in (
            ("5m", 0.2),
            ("15m", 0.4),
            ("30m", 0.7),
            ("60m", 1.0),
            ("SESSION_CLOSE", 1.5),
        )
    ]
    return {
        "case_metadata": {
            "case_id": "V3-TEST",
            "session_code": "LONDON",
            "session_date": "2024-01-02",
            "decision_at": decision_at.isoformat(),
            "data_partition": "DEVELOPMENT_2021_2024",
            "access_class": "DEVELOPMENT",
        },
        "decision_state": {
            "levels": [{"level_id": "LEVEL-1", "level_type": "ASIA_HIGH"}],
            "unused_macro_value": {"must_not_be_read": 123},
        },
        "subsequent_behaviour": {
            "decision_eligible": False,
            "neutral_reference": {"price": {"value": 1800}},
            "fixed_horizons": fixed,
            "neutral_excursions": {
                "signed_close_displacement": {"value": 1.5},
                "absolute_close_displacement": {"value": 1.5},
                "maximum_upward_displacement": {"value": 3.0},
                "maximum_downward_displacement": {"value": -1.5},
                "session_range": {"value": 4.5},
            },
            "extremes": {
                "session_high_at": {
                    "value": (decision_at + timedelta(minutes=60)).isoformat()
                },
                "session_low_at": {
                    "value": (decision_at + timedelta(minutes=180)).isoformat()
                },
                "extreme_order": {"value": "HIGH_FIRST"},
            },
            "level_interactions": [
                {
                    "level_id": "LEVEL-1",
                    "first_interaction_at": (
                        decision_at + timedelta(minutes=30)
                    ).isoformat(),
                    "touched": {"value": True},
                    "breached": {"value": True},
                    "accepted": {"value": False},
                    "rejected": {"value": True},
                    "failed_break": {"value": False},
                    "retested": {"value": False},
                }
            ],
            "path": {
                "complete": True,
                "one_minute_source_count": 239,
                "missing_one_minute_bars": 0,
                "five_minute_points": path,
            },
            "path_classification": {
                "value": {"net_state": "UP", "path_efficiency": 0.33333333}
            },
            "close_location": {"value": {"fraction": 0.66666667}},
        },
    }
