from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

from youtube_jpy_public_rule_v1_engine import (  # noqa: E402
    _news_payload,
    _path_result,
    _session_path,
    evaluate_stage1,
)


def test_news_union_and_nfp_week_are_value_blind() -> None:
    payload = _news_payload(
        [
            {"event_id": "840030005", "event_time_eat": pd.Timestamp("2024-01-11T16:30:00+03:00"), "event_name": "CPI m/m"},
            {"event_id": "840030016", "event_time_eat": pd.Timestamp("2024-01-05T16:30:00+03:00"), "event_name": "Nonfarm Payrolls"},
        ]
    )
    assert payload["full_dates"] == ["2024-01-11"]
    assert payload["nfp_weeks"] == ["2024-W01"]


def test_session_path_is_direction_symmetric() -> None:
    bars = pd.DataFrame(
        [
            {"open": 100.0, "high": 100.2, "low": 99.9, "close": 100.1},
            {"open": 100.1, "high": 100.5, "low": 100.0, "close": 100.4},
        ]
    )
    long = _session_path(bars, 1, 100.0)
    short = _session_path(bars, -1, 100.0)
    assert long["signed_displacement_pips"] == 40.0
    assert short["signed_displacement_pips"] == -40.0


def _path_frame(highs: list[float], lows: list[float], closes: list[float]) -> pd.DataFrame:
    start = pd.Timestamp("2024-01-08T09:00:00+03:00")
    rows = []
    for index in range(600):
        pick = min(index, len(highs) - 1)
        eat_time = start + pd.Timedelta(minutes=index)
        rows.append(
            {
                "eat_time": eat_time,
                "open_time": eat_time.tz_convert("UTC"),
                "open": 150.0,
                "high": highs[pick],
                "low": lows[pick],
                "close": closes[pick],
                "spread_points": 8.0,
            }
        )
    return pd.DataFrame(rows)


def test_break_even_activates_and_then_protects_entry() -> None:
    frame = _path_frame([150.21, 150.10], [150.05, 149.99], [150.10, 150.01])
    trigger = {"direction": 1, "entry_price": 150.0, "fill_time": "2024-01-08T09:00:00+03:00", "entry_spread_points": 8.0}
    result = _path_result(trigger, {"m1": frame}, True)
    assert result is not None
    assert result["outcome"] == "BREAK_EVEN"
    assert result["gross_r"] == 0.0


def test_stage1_rejects_negative_premise() -> None:
    rows = []
    dates = pd.date_range("2023-01-02", "2024-12-31", freq="B")[:400]
    for stamp in dates:
        day = stamp.strftime("%Y-%m-%d")
        half = "H1" if stamp.month <= 6 else "H2"
        rows.append(
            {
                "session_date": day,
                "cluster_week": f"{stamp.isocalendar().year}-W{stamp.isocalendar().week:02d}",
                "year": str(stamp.year),
                "fold": f"{stamp.year}_{half}",
                "signed_displacement_pips": -1.0,
                "direction_hit": False,
                "mfe_pips": 5.0,
                "mae_pips": 6.0,
                "session_first_passage": "UNRESOLVED",
            }
        )
    result = evaluate_stage1(rows)
    assert result["verdict"] == "REJECT"
    assert "mean_signed_pips_gt_zero" in result["failed_gates"]
