from __future__ import annotations

from copy import deepcopy
from datetime import UTC, date, datetime, time, timedelta

import pytest

from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    CANDIDATE_CODE,
    EXPECTED_EVALUATION_GATE_IDS,
    EXPECTED_READINESS_GATE_IDS,
    EXPECTED_ZN_BATCH_REQUEST,
    EXPECTED_ZN_QUOTE_REQUEST,
    HoldoutCase,
    ZnHoldoutSample,
    build_holdout_report,
    embedded_manifest_hash,
    evaluate_holdout_gates,
    materialize_zn_4h_feature,
    quote_request_fingerprint,
    validate_holdout_manifest,
    validate_quote_manifest,
)


def _manifest() -> dict[str, object]:
    document: dict[str, object] = {
        "manifest_version": "GOLD_CASEBOOK_DISCOVERY_V2_M6_ZN_QUOTE_MANIFEST_V0_1",
        "milestone": "V2_M6_PREOPEN_ZN_COST_ESTIMATE",
        "request": deepcopy(EXPECTED_ZN_QUOTE_REQUEST),
        "authorization_boundary": {
            "current_authorization": "METADATA_COST_ESTIMATE_ONLY",
            "paid_submission_authorized": False,
            "market_value_access_authorized": False,
            "holdout_outcome_access_authorized": False,
        },
        "prohibited": {
            "batch_job_submission": True,
            "market_value_access": True,
            "holdout_outcome_access": True,
        },
    }
    document["manifest_hash"] = embedded_manifest_hash(document)
    return document


def test_quote_manifest_freezes_exact_request_and_authorization_boundary() -> None:
    document = _manifest()

    assert validate_quote_manifest(document) == document["manifest_hash"]
    assert quote_request_fingerprint() == (
        "24d8efeea286b2fb6748669f04ed6c3c559ff3786e35923bf58bd48aa7892096"
    )


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("request", "symbols"), ["ZT.v.0"]),
        (("request", "end"), "2025-12-31T00:00:00Z"),
        (("authorization_boundary", "paid_submission_authorized"), True),
        (("prohibited", "market_value_access"), False),
    ],
)
def test_quote_manifest_rejects_scope_expansion(
    path: tuple[str, str],
    value: object,
) -> None:
    document = _manifest()
    section = document[path[0]]
    assert isinstance(section, dict)
    section[path[1]] = value
    document["manifest_hash"] = embedded_manifest_hash(document)

    with pytest.raises(ValueError):
        validate_quote_manifest(document)


def _holdout_manifest() -> dict[str, object]:
    document: dict[str, object] = {
        "manifest_version": "GOLD_CASEBOOK_DISCOVERY_V2_M6_HOLDOUT_MANIFEST_V0_1",
        "milestone": "V2_M6_CALENDAR_2025_HOLDOUT",
        "acquisition": {
            "request": deepcopy(EXPECTED_ZN_BATCH_REQUEST),
            "maximum_cost_usd": 1.25,
            "paid_submission_authorized": True,
        },
        "candidate": {
            "candidate_code": CANDIDATE_CODE,
            "rule_table": {
                "FLAT": "NO_BIAS",
                "NEGATIVE": "SHORT",
                "POSITIVE": "LONG",
                "UNKNOWN": "NO_BIAS",
            },
            "tuning_permitted": False,
        },
        "evaluation": {
            "candidate_family_size": 1,
            "all_gates_required": True,
            "gate_ids": list(EXPECTED_EVALUATION_GATE_IDS),
            "thresholds": {
                "maximum_q_value": 0.1,
                "minimum_directional_cases": 180,
                "minimum_directional_cases_per_half": 70,
                "minimum_state_cases": 80,
                "minimum_state_iso_week_clusters": 35,
            },
            "uncertainty": {
                "bootstrap_replications": 5000,
                "sign_flip_replications": 20000,
            },
        },
        "readiness": {
            "all_gates_required": True,
            "gate_ids": list(EXPECTED_READINESS_GATE_IDS),
            "minimum_case_coverage_pct": 95.0,
        },
        "execution": {
            "commission_usd_per_lot_round_turn": 7.0,
            "contract_size_ounces_per_lot": 100.0,
            "cost_stress_multiplier": 1.5,
            "decision_clock_local": "08:00",
            "entry_clock_local": "08:01",
            "exit_clock_local": "12:00",
            "notional_ounces": 1.0,
            "provider": "IC_MARKETS_MT5",
            "slippage_usd_per_ounce_per_side": 0.05,
            "symbol": "XAUUSD",
            "timeframe": "1m",
            "timezone": "Europe/London",
        },
        "holdout": {
            "start_inclusive": "2025-01-01T00:00:00Z",
            "end_exclusive": "2026-01-01T00:00:00Z",
        },
        "prohibited": {
            "candidate_retuning": True,
            "early_holdout_access": True,
        },
    }
    document["manifest_hash"] = embedded_manifest_hash(document)
    return document


def test_holdout_manifest_freezes_paid_request_candidate_and_family() -> None:
    document = _holdout_manifest()

    assert validate_holdout_manifest(document) == document["manifest_hash"]


@pytest.mark.parametrize(
    ("section_name", "field", "value"),
    [
        ("acquisition", "maximum_cost_usd", 2.00),
        ("acquisition", "paid_submission_authorized", False),
        ("candidate", "tuning_permitted", True),
        ("evaluation", "candidate_family_size", 2),
    ],
)
def test_holdout_manifest_rejects_frozen_scope_changes(
    section_name: str,
    field: str,
    value: object,
) -> None:
    document = _holdout_manifest()
    section = document[section_name]
    assert isinstance(section, dict)
    section[field] = value
    document["manifest_hash"] = embedded_manifest_hash(document)

    with pytest.raises(ValueError):
        validate_holdout_manifest(document)


def _passing_cases() -> list[HoldoutCase]:
    cases: list[HoldoutCase] = []
    start = date(2025, 1, 1)
    entry_price = 2_000.0
    cost = 0.2
    for index in range(240):
        session_date = start + timedelta(days=index * 3 // 2)
        positive = index % 2 == 0
        gross = 2.0 if positive else -2.0
        if index % 10 == 0:
            gross = -1.0 if positive else 1.0
        long_net = gross - cost
        short_net = -gross - cost
        decision_at = datetime.combine(
            session_date,
            time(8),
            tzinfo=UTC,
        )
        cases.append(
            HoldoutCase(
                case_id=f"M6-LONDON-{session_date:%Y%m%d}-{index:03d}",
                case_record_hash=f"hash-{index}",
                session_date=session_date,
                decision_at=decision_at,
                chronological_half="EARLY" if index < 120 else "LATE",
                feature_state="POSITIVE" if positive else "NEGATIVE",
                raw_percent_change=0.1 if positive else -0.1,
                feature_source_key=f"zn-{index}",
                reference_entry_price=entry_price,
                gross_move_usd_per_ounce=gross,
                cost_usd_per_ounce=cost,
                long_net_pnl_usd_per_ounce=long_net,
                long_net_return_basis_points=10_000 * long_net / entry_price,
                short_net_pnl_usd_per_ounce=short_net,
                short_net_return_basis_points=10_000 * short_net / entry_price,
            )
        )
    return cases


def test_frozen_holdout_report_and_all_twelve_gates_pass() -> None:
    report = build_holdout_report(
        _passing_cases(),
        manifest_hash="m6-manifest",
        bootstrap_replications=500,
        sign_flip_replications=2_000,
        stress_multiplier=1.5,
    )
    gates = evaluate_holdout_gates(report, integrity_passed=True)

    assert report["directional_case_count"] == 240
    assert report["best_matched_control"] in {"ALWAYS_LONG", "ALWAYS_SHORT"}
    assert gates["passed"] is True
    assert gates["passed_gate_count"] == 12
    assert gates["verdict"] == "PASS_CALENDAR_2025_HOLDOUT"


def test_holdout_integrity_failure_forces_rejection() -> None:
    report = build_holdout_report(
        _passing_cases(),
        manifest_hash="m6-manifest",
        bootstrap_replications=100,
        sign_flip_replications=100,
        stress_multiplier=1.5,
    )
    gates = evaluate_holdout_gates(report, integrity_passed=False)

    assert gates["passed"] is False
    assert gates["failed_gate_ids"] == ["G01_POINT_IN_TIME_AND_LINEAGE_INTEGRITY"]
    assert gates["verdict"] == "REJECT_CALENDAR_2025_HOLDOUT"


def _zn_sample(
    *,
    available_at: datetime,
    close: float,
    instrument_id: int = 42,
    ordinal: int,
) -> ZnHoldoutSample:
    return ZnHoldoutSample(
        source_record_id=f"source-{ordinal}",
        source_file_sha256="a" * 64,
        source_row_ordinal=ordinal,
        open_time=available_at - timedelta(minutes=1),
        available_at=available_at,
        continuous_symbol="ZN.v.0",
        instrument_id=instrument_id,
        underlying_raw_symbol="ZNH5",
        close=close,
    )


def test_zn_feature_uses_latest_point_in_time_endpoints_and_percent_sign() -> None:
    decision = datetime(2025, 1, 6, 8, tzinfo=UTC)
    samples = [
        _zn_sample(
            available_at=decision - timedelta(hours=4, minutes=1),
            close=110.0,
            ordinal=1,
        ),
        _zn_sample(
            available_at=decision - timedelta(hours=4),
            close=112.0,
            ordinal=2,
        ),
        _zn_sample(
            available_at=decision,
            close=113.0,
            ordinal=3,
        ),
    ]

    feature = materialize_zn_4h_feature(samples, decision_at=decision)

    assert feature.state == "POSITIVE"
    assert feature.bias == "LONG"
    assert feature.raw_absolute_change == 1.0
    assert feature.raw_percent_change == 0.89285714
    assert feature.reference == samples[1]
    assert feature.current == samples[2]


def test_zn_feature_roll_crossing_is_unknown_and_no_bias() -> None:
    decision = datetime(2025, 2, 28, 8, tzinfo=UTC)
    samples = [
        _zn_sample(
            available_at=decision - timedelta(hours=4),
            close=110.0,
            instrument_id=41,
            ordinal=1,
        ),
        _zn_sample(
            available_at=decision,
            close=111.0,
            instrument_id=42,
            ordinal=2,
        ),
    ]

    feature = materialize_zn_4h_feature(samples, decision_at=decision)

    assert feature.state == "UNKNOWN"
    assert feature.bias == "NO_BIAS"
    assert feature.reason_code == "CONTINUOUS_CONTRACT_ROLL"
    assert feature.raw_percent_change is None


def test_zn_feature_rejects_stale_current_sample() -> None:
    decision = datetime(2025, 1, 6, 8, tzinfo=UTC)
    samples = [
        _zn_sample(
            available_at=decision - timedelta(hours=12),
            close=110.0,
            ordinal=1,
        )
    ]

    feature = materialize_zn_4h_feature(samples, decision_at=decision)

    assert feature.state == "UNKNOWN"
    assert feature.bias == "NO_BIAS"
    assert feature.reason_code == "CURRENT_STALE"
