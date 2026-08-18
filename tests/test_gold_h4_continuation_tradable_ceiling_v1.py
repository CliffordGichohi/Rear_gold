from __future__ import annotations

import sys
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_h4_continuation_tradable_ceiling_v1 as subject  # noqa: E402


def test_synthetic_stop_first_and_preinvalidation_proof() -> None:
    proof = subject.synthetic_proof()
    assert proof["status"] == "PASS_SYNTHETIC_STOP_FIRST_AND_PREINVALIDATION_CEILING_PROOF"
    assert proof["event_comparisons"] == 4


def test_r_month_and_one_percent_scaling_are_frozen() -> None:
    item = subject.stage("TEST", [50.0] * 39, 3900.0)
    assert item["total_r"] == 39.0
    assert item["r_per_month"] == 1.0
    assert item["usd_per_month_at_50_risk"] == 50.0
    assert item["usd_per_month_at_1pct_risk_linear"] == 100.0


def test_distribution_is_deterministic() -> None:
    result = subject.distribution([1.0, 2.0, 3.0, 4.0])
    assert result == {
        "count": 4,
        "mean": 2.5,
        "median": 2.5,
        "p25": 1.75,
        "p75": 3.25,
        "minimum": 1.0,
        "maximum": 4.0,
    }
