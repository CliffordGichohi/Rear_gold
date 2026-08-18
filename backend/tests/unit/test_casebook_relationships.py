from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest

from gold_intel.backtesting.casebook_relationships import (
    CaseOutcome,
    DevelopmentCase,
    FeatureObservation,
    OutcomeTrade,
    RawFeature,
    apply_benjamini_hochberg,
    apply_discovery_lead_flags,
    cluster_bootstrap_mean_ci,
    evaluate_relationship_state,
    fit_tertile_thresholds,
    materialize_feature,
    quantile_type_7,
    transform_feature_value,
)


def _case(
    index: int,
    *,
    long_bps: float,
    short_bps: float,
    half: str,
) -> DevelopmentCase:
    session_date = date(2022, 1, 3) + timedelta(days=index * 10)
    feature = FeatureObservation(
        feature_id="test_feature",
        family_code="TEST",
        transform="CATEGORY",
        raw_value="STATE",
        state="STATE",
        source_key=f"SOURCE-{index}",
    )
    return DevelopmentCase(
        case_id=f"CASE-{index}",
        case_record_hash="a" * 64,
        session_code="LONDON",
        session_date=session_date,
        decision_at=datetime.combine(
            session_date,
            datetime.min.time(),
            tzinfo=UTC,
        ),
        chronological_half=half,
        features={"test_feature": feature},
        outcome=CaseOutcome(
            long=OutcomeTrade(
                side="LONG",
                net_pnl_usd=long_bps / 10,
                net_return_basis_points=long_bps,
            ),
            short=OutcomeTrade(
                side="SHORT",
                net_pnl_usd=short_bps / 10,
                net_return_basis_points=short_bps,
            ),
        ),
    )


def test_type_7_quantiles_and_tertile_boundaries_are_deterministic() -> None:
    assert quantile_type_7([0, 10, 20, 30], 1 / 3) == pytest.approx(10)
    assert quantile_type_7([0, 10, 20, 30], 2 / 3) == pytest.approx(20)

    raw_cases = [
        {
            "feature": RawFeature(
                feature_id="feature",
                family_code="TEST",
                transform="TERTILE",
                raw_value=value,
                source_key=str(value),
            )
        }
        for value in (0.0, 10.0, 20.0, 30.0)
    ]
    thresholds = fit_tertile_thresholds(
        raw_cases,
        feature_ids=["feature"],
    )

    assert thresholds["feature"]["low_max"] == pytest.approx(10)
    assert thresholds["feature"]["high_min"] == pytest.approx(20)
    low = materialize_feature(
        raw_cases[1]["feature"],
        tertile_thresholds=thresholds,
    )
    high = materialize_feature(
        raw_cases[2]["feature"],
        tertile_thresholds=thresholds,
    )
    assert low.state == "LOW"
    assert high.state == "HIGH"


def test_declared_direction_and_sign_transforms_preserve_unknowns() -> None:
    assert (
        transform_feature_value(
            "direction",
            -0.1,
            transform="DIRECTION_3",
            tertile_thresholds={},
        )
        == "BEARISH"
    )
    assert (
        transform_feature_value(
            "direction",
            0.05,
            transform="DIRECTION_3",
            tertile_thresholds={},
        )
        == "NEUTRAL"
    )
    assert (
        transform_feature_value(
            "change",
            0.0,
            transform="SIGN_3",
            tertile_thresholds={},
        )
        == "FLAT"
    )
    assert (
        transform_feature_value(
            "missing",
            None,
            transform="CATEGORY",
            tertile_thresholds={},
        )
        == "UNKNOWN"
    )


def test_relationship_selection_bootstrap_and_stability_are_reproducible() -> None:
    cases = [
        _case(
            index,
            long_bps=2.0 + (index % 3),
            short_bps=-3.0 - (index % 2),
            half="EARLY" if index < 30 else "LATE",
        )
        for index in range(60)
    ]
    baselines = {
        "LONG": {"mean_net_return_basis_points": -1.0},
        "SHORT": {"mean_net_return_basis_points": -1.0},
    }

    first = evaluate_relationship_state(
        cases,
        relationship_type="SINGLE",
        relationship_id="test_feature",
        state="STATE",
        feature_ids=["test_feature"],
        total_session_cases=100,
        same_session_baselines=baselines,
        manifest_hash="b" * 64,
        bootstrap_replications=200,
        minimum_cases=50,
        maximum_prevalence_pct=80,
        minimum_week_clusters=5,
        minimum_years_with_10_cases=1,
        cot_minimum_reports=12,
        development_years=[2022, 2023],
    )
    second_ci = cluster_bootstrap_mean_ci(
        cases,
        side="LONG",
        replications=200,
        seed_material=f"{'b' * 64}|LONDON|test_feature|STATE",
    )

    assert first["selected_direction"] == "LONG"
    assert first["support_eligible"] is True
    assert first["stability_flag"] is True
    assert first["cluster_bootstrap_95pct_ci_basis_points"] == second_ci
    assert first["excess_mean_net_return_vs_baseline_bps"] > 0


def test_benjamini_hochberg_and_lead_flag_are_bounded() -> None:
    records = [
        {
            "support_eligible": True,
            "selection_adjusted_p_value": value,
            "relationship_id": f"R{index}",
            "state": "S",
            "benjamini_hochberg_q_value": None,
            "selected_metrics": {
                "mean_net_return_basis_points": 2.0,
                "profit_factor": 1.2,
            },
            "excess_mean_net_return_vs_baseline_bps": 1.0,
            "stability_flag": True,
            "discovery_lead": False,
        }
        for index, value in enumerate((0.01, 0.02, 0.2), start=1)
    ]

    apply_benjamini_hochberg(records)
    apply_discovery_lead_flags(records, q_threshold=0.1)

    assert [record["benjamini_hochberg_q_value"] for record in records] == [
        0.03,
        0.03,
        0.2,
    ]
    assert [record["discovery_lead"] for record in records] == [
        True,
        True,
        False,
    ]
