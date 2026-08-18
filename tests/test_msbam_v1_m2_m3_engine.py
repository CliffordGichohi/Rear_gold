from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from tools import msbam_v1_m2_m3_engine as engine


@dataclass
class SyntheticSeries:
    minute: np.ndarray
    open: np.ndarray
    high: np.ndarray
    low: np.ndarray
    close: np.ndarray
    spread: np.ndarray

    def exact_index(self, minute: int) -> int | None:
        index = int(np.searchsorted(self.minute, minute, side="left"))
        return index if index < len(self.minute) and int(self.minute[index]) == minute else None


def synthetic_series() -> SyntheticSeries:
    minutes = np.arange(100, 131, dtype=np.int64)
    opened = np.full(len(minutes), 25.0)
    high = np.full(len(minutes), 25.10)
    low = np.full(len(minutes), 24.90)
    close = np.full(len(minutes), 25.0)
    # The first completed M15 bar is an observable bullish state.
    high[:15] = 25.50
    low[:15] = 24.90
    close[14] = 25.40
    # Entry is at minute 116 after the frozen one-minute latency. Both
    # stop and target occur in that bar, so the stop-first rule must win.
    opened[16] = 25.40
    high[16] = 26.60
    low[16] = 23.80
    close[16] = 25.50
    return SyntheticSeries(minutes, opened, high, low, close, np.full(len(minutes), 10.0))


def test_legacy_utility_module_loads() -> None:
    legacy = engine.load_legacy()
    assert callable(legacy.load_price_series)
    assert callable(legacy.build_technical_bundle)


def test_same_bar_first_passage_is_explicitly_ambiguous() -> None:
    series = synthetic_series()
    result = engine.first_passages(series, 0, len(series.minute), 25.0, 1.0, 100)
    assert result["1P0"]["order"] == "AMBIGUOUS_SAME_BAR"


def test_completed_bar_trigger_respects_latency_and_stop_first() -> None:
    case = {
        "case_id": "synthetic", "instrument": "XAGUSD", "research_id": "XAGUSD",
        "cluster": "PRECIOUS_METALS", "session_code": "LONDON_SESSION",
        "session_date_local": "2024-01-02", "observation_start_minute": 100,
        "observation_end_minute": 131, "reference_open": 25.0, "atr15": 1.0,
        "up_excursion_r": 1.6, "down_excursion_r": 0.8, "long_mfe_r": 1.6,
        "long_mae_r": 0.8, "short_mfe_r": 0.8, "short_mae_r": 1.6,
        "session_close_r": 0.4, "first_passages": {"1P0": {
            "up_elapsed_minutes": 16, "down_elapsed_minutes": 16,
            "order": "AMBIGUOUS_SAME_BAR",
        }}, "archetype": "MIXED_UNCLASSIFIED",
    }
    row = engine.feasibility_row(synthetic_series(), case, "M15")
    assert row["trigger_available_minute"] == 115
    assert row["entry_minute"] == 116
    assert row["exit_reason"] == "STOP_FIRST_AMBIGUOUS"
    assert row["stage3_stop_feasible_gross_r"] == -1.0


def test_cluster_cap_rejects_only_overlapping_same_cluster() -> None:
    base = {
        "triggered": True, "size_executable": True, "entry_minute": 100,
        "exit_minute": 120, "stage3_net_r": 0.8, "timeframe": "M15",
        "portfolio_accepted": False, "stage4_portfolio_net_r": 0.0,
    }
    rows = [
        {**base, "case_id": "a", "instrument": "EURUSD", "cluster": "USD_FX"},
        {**base, "case_id": "b", "instrument": "USDJPY", "cluster": "USD_FX", "entry_minute": 110},
        {**base, "case_id": "c", "instrument": "XAGUSD", "cluster": "PRECIOUS_METALS", "entry_minute": 110},
    ]
    result = {row["case_id"]: row for row in engine.apply_portfolio(rows)}
    assert result["a"]["portfolio_accepted"] is True
    assert result["b"]["portfolio_accepted"] is False
    assert result["b"]["portfolio_rejection"] == "CONCURRENT_CLUSTER_RISK_CAP"
    assert result["c"]["portfolio_accepted"] is True
