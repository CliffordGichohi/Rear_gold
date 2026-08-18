from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, date, datetime
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "m3", ROOT / "tools/run_multi_asset_macro_session_portfolio_v1_m3.py"
)
assert SPEC and SPEC.loader
m3 = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = m3
SPEC.loader.exec_module(m3)


def synthetic_series() -> object:
    minute = np.arange(100, 130, dtype=np.int64)
    opened = np.linspace(10.0, 12.9, len(minute))
    return m3.PriceSeries(
        "XAUUSD", minute, opened, opened + 0.2, opened - 0.2, opened + 0.1,
        np.arange(1, len(minute) + 1, dtype=np.float64), np.ones(len(minute)), "synthetic",
    )


def test_primary_reference_aggregation_is_exact() -> None:
    series = synthetic_series()
    primary = m3.aggregate_primary(series, 5)
    reference = m3.aggregate_reference(series, 5)
    for field in ("start", "end", "open", "high", "low", "close", "volume", "count"):
        assert np.array_equal(getattr(primary, field), getattr(reference, field))


def test_primary_reference_exit_stop_first_is_exact() -> None:
    series = synthetic_series()
    primary = m3._exit_primary(series, 0, 10, 1, 10.15, 10.25)
    reference = m3._exit_reference(series, 0, 10, 1, 10.15, 10.25)
    assert primary == reference
    assert primary[2] in {"STOP", "STOP_GAP"}


def test_session_dst_conversions_are_frozen() -> None:
    winter_london = m3.datetime_of(m3.session_bounds("LONDON_DECISION", date(2024, 1, 15))[0])
    summer_london = m3.datetime_of(m3.session_bounds("LONDON_DECISION", date(2024, 7, 15))[0])
    winter_new_york = m3.datetime_of(m3.session_bounds("NEW_YORK_DECISION", date(2024, 1, 15))[0])
    summer_new_york = m3.datetime_of(m3.session_bounds("NEW_YORK_DECISION", date(2024, 7, 15))[0])
    assert (winter_london.hour, summer_london.hour) == (7, 6)
    assert (winter_new_york.hour, summer_new_york.hour) == (13, 12)


def test_half_open_exact_contiguity() -> None:
    series = synthetic_series()
    assert series.contiguous(100, 130, 1.0) == (0, 30)
    assert series.contiguous(100, 131, 1.0) is None
    assert series.exact_index(100) == 0
    assert series.exact_index(130) is None


def test_fold_boundaries() -> None:
    assert m3.fold_for(date(2021, 12, 31)) is None
    assert m3.fold_for(date(2022, 1, 1)) == 1
    assert m3.fold_for(date(2022, 7, 1)) == 2
    assert m3.fold_for(date(2024, 12, 31)) == 6
    assert m3.fold_for(date(2025, 1, 1)) is None


def test_microsecond_parsed_timestamps_are_normalized_to_nanoseconds() -> None:
    timestamps = pd.to_datetime(pd.Series(["2021-08-02T00:00:00Z", "2021-08-02T00:01:00Z"]), utc=True)
    assert str(timestamps.dtype) == "datetime64[us, UTC]"
    minutes = (timestamps.dt.as_unit("ns").astype("int64") // 60_000_000_000).astype("int64")
    expected = int(datetime(2021, 8, 2, tzinfo=UTC).timestamp() // 60)
    assert minutes.tolist() == [expected, expected + 1]


def test_true_range_cache_is_exact_and_stable() -> None:
    aggregate = m3.aggregate_primary(synthetic_series(), 5)
    expected = aggregate.high - aggregate.low
    expected[1:] = np.maximum(
        expected[1:],
        np.maximum(np.abs(aggregate.high[1:] - aggregate.close[:-1]), np.abs(aggregate.low[1:] - aggregate.close[:-1])),
    )
    first = m3.true_ranges(aggregate)
    second = m3.true_ranges(aggregate)
    assert np.array_equal(first, expected)
    assert second is first


if __name__ == "__main__":
    test_primary_reference_aggregation_is_exact()
    test_primary_reference_exit_stop_first_is_exact()
    test_session_dst_conversions_are_frozen()
    test_half_open_exact_contiguity()
    test_fold_boundaries()
    test_microsecond_parsed_timestamps_are_normalized_to_nanoseconds()
    test_true_range_cache_is_exact_and_stable()
    print("7 synthetic Milestone-3 integrity tests passed")
