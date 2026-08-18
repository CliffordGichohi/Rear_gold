from __future__ import annotations

import hashlib
import json
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from gold_intel.analytics.casebook_discovery_v3 import (
    add_deterministic_hash,
    assert_metadata_only_sql,
    audit_timestamp_only_session_coverage,
    mt5_xau_files_overlapping,
    overlapping_filename_pairs,
    verify_embedded_hash,
)

ROOT = Path(__file__).resolve().parents[3]


def test_metadata_sql_guard_rejects_value_and_outcome_columns() -> None:
    with pytest.raises(ValueError, match="forbidden column 'close'"):
        assert_metadata_only_sql(
            {"bad": "SELECT close, open_time FROM market.price_bars"}
        )
    with pytest.raises(ValueError, match="forbidden column 'actual_value'"):
        assert_metadata_only_sql(
            {"bad": "SELECT actual_value FROM market.economic_releases"}
        )
    with pytest.raises(ValueError, match="forbidden column 'return'"):
        assert_metadata_only_sql({"bad": "SELECT return FROM analytics.results"})


def test_metadata_sql_guard_allows_identifiers_timestamps_and_counts() -> None:
    assert_metadata_only_sql(
        {
            "good": """
                SELECT provider_code, count(*), min(open_time), max(open_time),
                       count(*) FILTER (WHERE spread_price IS NOT NULL)
                FROM market.price_bars
                GROUP BY provider_code
            """
        }
    )


def test_timestamp_only_session_coverage_is_dst_aware() -> None:
    session_date = date(2026, 3, 30)
    available: set[datetime] = set()
    for timezone_name, start, end in (
        ("Asia/Tokyo", time(10, 5), time(16, 0)),
        ("Europe/London", time(8, 0), time(12, 0)),
        ("America/New_York", time(8, 0), time(12, 0)),
    ):
        timezone = ZoneInfo(timezone_name)
        window_start = datetime.combine(session_date, start, tzinfo=timezone)
        window_end = datetime.combine(session_date, end, tzinfo=timezone)
        count = int((window_end - window_start).total_seconds() // 300)
        available.update(
            (window_start + timedelta(minutes=5 * index)).astimezone(UTC)
            for index in range(count)
        )

    result = audit_timestamp_only_session_coverage(
        available,
        session_date_start=session_date,
        session_date_end_inclusive=session_date,
    )

    assert result["counts"]["requested_weekdays"] == 1
    assert result["counts"]["asia_complete"] == 1
    assert result["counts"]["london_case_complete"] == 1
    assert result["counts"]["new_york_case_complete"] == 1
    assert result["missing_dates"] == {}


def test_timestamp_only_session_coverage_does_not_synthesize_missing_bar() -> None:
    session_date = date(2026, 6, 15)
    london = ZoneInfo("Europe/London")
    start = datetime.combine(session_date, time(8, 0), tzinfo=london)
    available = {
        (start + timedelta(minutes=5 * index)).astimezone(UTC)
        for index in range(48)
        if index != 7
    }

    result = audit_timestamp_only_session_coverage(
        available,
        session_date_start=session_date,
        session_date_end_inclusive=session_date,
    )

    assert result["counts"]["london_complete"] == 0
    assert result["counts"]["london_case_complete"] == 0
    assert result["missing_dates"]["LONDON"] == ["2026-06-15"]


def test_filename_coverage_and_overlap_use_names_only(tmp_path: Path) -> None:
    names = (
        "xauusd_1m_ic_markets_mt5_20251215T0100_20260113T1404.csv",
        "xauusd_1m_ic_markets_mt5_20260113T1405_20260212T1404.csv",
        "xauusd_1m_ic_markets_mt5_20260120T0100_20260121T0100.csv",
    )
    for name in names:
        (tmp_path / name).touch()

    files = mt5_xau_files_overlapping(
        tmp_path,
        start=datetime(2026, 1, 1, tzinfo=UTC),
        end=datetime(2026, 2, 1, tzinfo=UTC),
    )
    pairs = overlapping_filename_pairs(files)

    assert [path.name for path in files] == list(names)
    assert pairs == [
        [
            "xauusd_1m_ic_markets_mt5_20260113T1405_20260212T1404.csv",
            "xauusd_1m_ic_markets_mt5_20260120T0100_20260121T0100.csv",
        ]
    ]


def test_v3_contract_and_traceability_hashes_are_canonical() -> None:
    contract = json.loads(
        (
            ROOT
            / "research_manifests"
            / "gold_session_behaviour_discovery_contract_v03.json"
        ).read_text(encoding="utf-8")
    )
    catalog = json.loads(
        (
            ROOT
            / "research_manifests"
            / "gold_session_behaviour_v3_traceability_v01.json"
        ).read_text(encoding="utf-8")
    )

    assert (
        verify_embedded_hash(contract, hash_field="manifest_hash")
        == "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
    )
    assert (
        verify_embedded_hash(catalog, hash_field="catalog_hash")
        == "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4"
    )


def test_traceability_is_comprehensive_and_pre_result() -> None:
    catalog = json.loads(
        (
            ROOT
            / "research_manifests"
            / "gold_session_behaviour_v3_traceability_v01.json"
        ).read_text(encoding="utf-8")
    )
    requirements = catalog["field_requirements"]
    counts = Counter(item["development_coverage"] for item in requirements)

    assert len(requirements) == 75
    assert len({item["factor_id"] for item in requirements}) == 75
    assert counts == {
        "PRESENT": 34,
        "PARTIAL": 18,
        "DERIVABLE": 14,
        "UNAVAILABLE": 6,
        "OUT_OF_SCOPE": 3,
    }
    assert catalog["generated_from_results"] is False
    assert catalog["relationship_or_candidate_fields_included"] is False


def test_case_matrix_schema_keeps_outcomes_and_execution_separate() -> None:
    schema_path = (
        ROOT
        / "research_schemas"
        / "gold_session_behaviour_v3_case_matrix.schema.json"
    )
    schema = json.loads(schema_path.read_text(encoding="utf-8"))
    policy = schema["$defs"]["research_policy"]["properties"]
    outcome = schema["$defs"]["subsequent_behaviour"]

    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert outcome["properties"]["decision_eligible"]["const"] is False
    assert policy["trade_direction_assigned"]["const"] is False
    assert policy["execution_optimized"]["const"] is False
    assert policy["mfe_or_mae_calculated"]["const"] is False
    assert policy["pnl_or_r_multiple_calculated"]["const"] is False
    assert policy["account_return_calculated"]["const"] is False


def test_coverage_artifact_proves_metadata_only_boundary() -> None:
    path = (
        ROOT
        / "research_artifacts"
        / "gold_session_behaviour_v3_coverage_v01.json"
    )
    report = json.loads(path.read_text(encoding="utf-8"))
    boundary = report["audit_boundary"]
    supplied = report["data_hash"]
    content = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "data_hash"}
    }
    actual = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()

    assert supplied == actual
    assert boundary["database_transaction_read_only"] is True
    assert boundary["sql_guard_passed"] is True
    assert boundary["exposed_2025_market_or_macro_values_read"] is False
    assert boundary["locked_2026_market_or_macro_values_read"] is False
    assert boundary["feature_outcome_joins_calculated"] is False
    assert boundary["relationship_statistics_calculated"] is False
    assert report["milestone_decision"]["case_matrix_rows_built"] == 0
    assert report["milestone_decision"]["candidates_created"] == 0


def test_deterministic_hash_excludes_generation_clock() -> None:
    left = {"generated_at": "2026-01-01T00:00:00Z", "value": "metadata"}
    right = {"generated_at": "2026-07-30T00:00:00Z", "value": "metadata"}
    assert add_deterministic_hash(left) == add_deterministic_hash(right)
