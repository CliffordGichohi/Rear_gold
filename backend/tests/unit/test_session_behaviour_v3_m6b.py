from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

from gold_intel.analytics.session_behaviour_v3_m6b import (
    evaluate_segment,
    forward_case_hash,
    materialize_forward_case,
    new_forward_case,
    overall_candidate_verdicts,
    validate_m6b_freeze,
)


def _case(
    *,
    segment: str,
    session: str,
    session_date: date,
    state: str,
    up: bool,
    signature_number: int,
) -> dict:
    feature = (
        "MACRO_VOLATILITY_CHANGE"
        if session == "LONDON"
        else "MACRO_FINANCIAL_STRESS_CHANGE"
    )
    timezone_hour = 8
    decision = datetime.combine(
        session_date,
        datetime.min.time(),
        tzinfo=UTC,
    ) + timedelta(hours=timezone_hour)
    reference = 2000.0
    close = 2001.0 if up else 1999.0
    return new_forward_case(
        segment_code=segment,
        session_code=session,
        session_date=session_date,
        decision_at=decision,
        observation_end=decision + timedelta(hours=4),
        feature_id=feature,
        feature_state=state,
        feature_source_signature=f"signature-{signature_number}",
        feature_source_records=[
            {
                "record_id": f"prior-{signature_number}",
                "source_record_key": f"prior-{signature_number}",
                "available_at": (decision - timedelta(days=2)).isoformat(),
                "vintage": "TEST",
            },
            {
                "record_id": f"latest-{signature_number}",
                "source_record_key": f"latest-{signature_number}",
                "available_at": (decision - timedelta(days=1)).isoformat(),
                "vintage": "TEST",
            },
        ],
        neutral_reference_open=reference,
        sixty_minute_close=close,
        session_close=close,
        session_high=max(reference, close) + 0.5,
        session_high_at=decision + timedelta(hours=1),
        session_low=min(reference, close) - 0.5,
        session_low_at=decision + timedelta(hours=2),
        measurement_bar_count=239,
        measurement_bar_ids_hash=f"ids-{session_date}",
        measurement_bar_payload_hash=f"payload-{session_date}",
        price_batch_content_hashes=["batch"],
    )


def _segment_cases(
    *,
    segment: str,
    reverse: bool = False,
    per_session: int = 100,
) -> list[dict]:
    start = date(2025, 1, 1) if "2025" in segment else date(2026, 1, 1)
    cases: list[dict] = []
    for session in ("LONDON", "NEW_YORK"):
        for index in range(per_session):
            state = "FALLING" if index % 2 == 0 else "RISING"
            expected_up = state == "FALLING"
            cases.append(
                _case(
                    segment=segment,
                    session=session,
                    session_date=start + timedelta(days=index),
                    state=state,
                    up=(not expected_up if reverse else expected_up),
                    signature_number=index % 8,
                )
            )
    return cases


def test_m6b_freeze_and_case_hash_are_valid() -> None:
    assert validate_m6b_freeze() == []
    document = _segment_cases(
        segment="EXPOSED_CALENDAR_2025",
        per_session=1,
    )[0]
    assert forward_case_hash(document) == document["case_hash"]
    case = materialize_forward_case(document)
    assert case.outcome.close_direction == "UP"
    assert case.outcome.signed_close_displacement == 1.0


def test_m6b_strict_positive_and_reverse_verdicts() -> None:
    integrity = {
        "duplicate_price_natural_keys": 0,
        "duplicate_observation_natural_keys": 0,
    }
    positive = evaluate_segment(
        _segment_cases(segment="EXPOSED_CALENDAR_2025"),
        segment_code="EXPOSED_CALENDAR_2025",
        source_integrity=integrity,
    )
    reverse = evaluate_segment(
        _segment_cases(segment="LOCKED_2026_YTD", reverse=True),
        segment_code="LOCKED_2026_YTD",
        source_integrity=integrity,
    )
    assert {
        item["segment_verdict"] for item in positive["candidate_results"]
    } == {"PASS_MATERIAL_POSITIVE_REPLICATION"}
    assert {
        item["segment_verdict"] for item in reverse["candidate_results"]
    } == {"REJECT_MATERIAL_REVERSE_REPLICATION"}
    overall = overall_candidate_verdicts([positive, reverse])
    assert {
        item["overall_verdict"] for item in overall
    } == {"REJECTED_MATERIAL_REVERSE_IN_HISTORICAL_FORWARD_SEGMENT"}


def test_m6b_support_failure_is_inconclusive_and_still_in_holm_family() -> None:
    result = evaluate_segment(
        _segment_cases(
            segment="EXPOSED_CALENDAR_2025",
            per_session=20,
        ),
        segment_code="EXPOSED_CALENDAR_2025",
        source_integrity={
            "duplicate_price_natural_keys": 0,
            "duplicate_observation_natural_keys": 0,
        },
    )
    assert len(result["candidate_results"]) == 2
    for candidate in result["candidate_results"]:
        assert candidate["segment_verdict"] == "INCONCLUSIVE_INSUFFICIENT_SUPPORT"
        assert candidate["holm_adjusted_p_value"] == 1.0
