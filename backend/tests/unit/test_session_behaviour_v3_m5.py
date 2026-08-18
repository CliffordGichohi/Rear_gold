from __future__ import annotations

from datetime import date, timedelta

from gold_intel.analytics.session_behaviour_v3_discovery import FeatureObservation
from gold_intel.analytics.session_behaviour_v3_m5 import (
    apply_holm_bonferroni,
    build_m5_results,
    candidate_membership,
    candidate_registry,
    registry_fingerprint,
    stability_protocol,
    validate_m5_semantics,
)
from gold_intel.analytics.session_behaviour_v3_relationships import (
    DiscoveryCase,
    NeutralOutcome,
)


def _observation(state: str, signature: str) -> FeatureObservation:
    return FeatureObservation(
        state=state,
        source_signature=signature,
        epistemic_status="CALCULATED",
        quality="VALID",
    )


def _case(
    *,
    index: int,
    session_code: str,
    session_date: date,
    condition: bool,
) -> DiscoveryCase:
    direction = "UP" if condition else "DOWN"
    signed = 2.0 if condition else -2.0
    return DiscoveryCase(
        case_id=f"{session_code}-{index:04d}",
        record_hash=f"{index:064x}",
        session_code=session_code,
        session_date=session_date,
        features={
            "SESSION_ASIA_DIRECTION": _observation(
                "DOWN" if condition else "UP",
                f"ASIA-{index:04d}",
            ),
            "MACRO_VOLATILITY_CHANGE": _observation(
                "FALLING" if condition else "RISING",
                f"VOL-{index:04d}",
            ),
            "MACRO_FINANCIAL_STRESS_CHANGE": _observation(
                "FALLING" if condition else "RISING",
                f"STRESS-{index:04d}",
            ),
            "EXPECT_SOFR_WINDOW_CUT_HIKE_BALANCE": _observation(
                "CUT_DOMINANT" if condition else "HIKE_DOMINANT",
                f"SOFR-{index:04d}",
            ),
            "MACRO_TREASURY_2Y_CHANGE": _observation(
                "FALLING" if condition else "RISING",
                f"TWOY-{index:04d}",
            ),
        },
        outcome=NeutralOutcome(
            close_direction=direction,
            signed_close_displacement=signed,
            absolute_close_displacement=2.0,
            sixty_minute_direction=direction,
            maximum_upward_displacement=3.0 if condition else 1.0,
            maximum_downward_displacement_magnitude=1.0 if condition else 3.0,
            session_range=4.0,
            extreme_order="LOW_FIRST" if condition else "HIGH_FIRST",
        ),
    )


def _dates(count: int) -> list[date]:
    start = date(2021, 8, 1)
    span = (date(2024, 12, 31) - start).days
    return [
        start + timedelta(days=round(index * span / (count - 1)))
        for index in range(count)
    ]


def _frozen_manifest() -> dict[str, object]:
    return {
        "candidate_registry": candidate_registry(),
        "stability_protocol": stability_protocol(),
        "manifest_hash": "manifest",
        "recorded_at": "2026-07-30T00:00:00Z",
        "registry_fingerprint": registry_fingerprint(),
    }


def test_registry_is_exactly_the_four_authorized_post_hoc_families() -> None:
    registry = candidate_registry()

    assert [item["candidate_code"] for item in registry] == [
        "LONDON_ASIA_DIRECTION_REVERSAL_V0_1",
        "LONDON_VOLATILITY_DIRECTION_V0_1",
        "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
        "NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1",
    ]
    assert all(
        item["post_hoc_status"]
        == "POST_HOC_NO_DEVELOPMENT_VALIDATION_CREDIT"
        for item in registry
    )
    assert stability_protocol()["multiplicity"]["family_size_fixed"] == 4


def test_membership_respects_exact_complement_and_joint_known_rules() -> None:
    case = _case(
        index=1,
        session_code="LONDON",
        session_date=date(2022, 1, 3),
        condition=True,
    )
    asia = candidate_registry()[0]
    sofr = candidate_registry()[3]

    assert candidate_membership(case, asia) == "CONDITION"
    assert candidate_membership(case, sofr) == "CONDITION"

    altered_features = dict(case.features)
    altered_features["SESSION_ASIA_DIRECTION"] = _observation("FLAT", "flat")
    altered = DiscoveryCase(
        case_id=case.case_id,
        record_hash=case.record_hash,
        session_code=case.session_code,
        session_date=case.session_date,
        features=altered_features,
        outcome=case.outcome,
    )
    assert candidate_membership(altered, asia) == "EXCLUDED_KNOWN"

    altered_features["SESSION_ASIA_DIRECTION"] = _observation(
        "UNKNOWN",
        "UNKNOWN",
    )
    unknown = DiscoveryCase(
        case_id=case.case_id,
        record_hash=case.record_hash,
        session_code=case.session_code,
        session_date=case.session_date,
        features=altered_features,
        outcome=case.outcome,
    )
    assert candidate_membership(unknown, asia) == "JOINT_UNKNOWN"


def test_holm_family_size_remains_four_including_unsupported_candidates() -> None:
    records = []
    for code, p_value in (
        ("A", 0.01),
        ("B", 0.02),
        ("C", 0.04),
        ("D", None),
    ):
        records.append(
            {
                "candidate_code": code,
                "full_development": {
                    "fisher_exact_two_sided_p_value": p_value,
                },
                "holm_adjusted_p_value": None,
            }
        )

    apply_holm_bonferroni(records, family_size=4)

    assert [item["holm_adjusted_p_value"] for item in records] == [
        0.04,
        0.06,
        0.08,
        1.0,
    ]


def test_full_m5_document_preserves_sessions_and_shortlist_cap() -> None:
    london_dates = _dates(833)
    new_york_dates = _dates(826)
    cases = [
        *[
            _case(
                index=index,
                session_code="LONDON",
                session_date=session_date,
                condition=index % 2 == 0,
            )
            for index, session_date in enumerate(london_dates)
        ],
        *[
            _case(
                index=10_000 + index,
                session_code="NEW_YORK",
                session_date=session_date,
                condition=index % 2 == 0,
            )
            for index, session_date in enumerate(new_york_dates)
        ],
    ]
    manifest = _frozen_manifest()

    result = build_m5_results(cases, frozen_manifest=manifest)

    assert result["total_passing_all_gates"] == 4
    assert result["total_shortlisted"] == 4
    assert len(result["sessions"]["LONDON"]["shortlist"]) == 2
    assert len(result["sessions"]["NEW_YORK"]["shortlist"]) == 2
    assert not validate_m5_semantics(result, frozen_manifest=manifest)
    assert result["interpretation_boundary"]["calendar_2025_values_opened"] is False
    assert result["interpretation_boundary"]["calendar_2026_values_opened"] is False
