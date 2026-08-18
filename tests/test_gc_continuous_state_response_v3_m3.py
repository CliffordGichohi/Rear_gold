from __future__ import annotations

import importlib.util
import sys
from datetime import UTC, datetime
from pathlib import Path

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools" / "run_gc_continuous_state_response_v3_m3.py"
SPEC = importlib.util.spec_from_file_location("gc_csr_v3_m3", MODULE_PATH)
assert SPEC and SPEC.loader
M = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = M
SPEC.loader.exec_module(M)


def test_protocol_preserves_locks_and_exact_families() -> None:
    protocol = M.load_json(M.PROTOCOL)
    assert protocol["status"] == "READY_TO_FREEZE_PRE_OUTCOME"
    assert protocol["population"]["stage1_eligible_per_session"] == 9
    assert protocol["population"]["stage2_eligible_per_session"] == 5
    assert all(protocol["locked"].values())
    assert protocol["outcomes"]["source_sha256"] == M.EXPECTED_XAU_SHA


def test_seed_derivation_is_stable_and_scoped() -> None:
    first = M.seed_for("LONDON", 1, "CSR_FLOW_QUOTE_OFI_W60", "BLOCK_BOOTSTRAP")
    second = M.seed_for("LONDON", 1, "CSR_FLOW_QUOTE_OFI_W60", "BLOCK_BOOTSTRAP")
    different = M.seed_for("NEW_YORK", 1, "CSR_FLOW_QUOTE_OFI_W60", "BLOCK_BOOTSTRAP")
    assert first == second
    assert first != different
    assert 0 <= first < 2**64
    assert M.horizon_seed(first, 5) == M.horizon_seed(first, 5)
    assert M.horizon_seed(first, 5) != M.horizon_seed(first, 15)


def test_rank_spearman_and_transform_are_deterministic() -> None:
    assert np.array_equal(M.rankdata_average(np.asarray([3.0, 1.0, 1.0, 2.0])), np.asarray([4.0, 1.5, 1.5, 3.0]))
    assert M.spearman([1, 2, 3], [10, 20, 30]) == 1.0
    parameters = M.transform_parameters(list(range(-50, 51)))
    assert parameters is not None
    assert parameters["winsor_lower"] < parameters["winsor_upper"]
    assert np.array_equal(M.apply_transform([1.0, 2.0], parameters), M.apply_transform([1.0, 2.0], parameters))


def test_huber_and_ridge_have_registered_positive_solution() -> None:
    x = np.linspace(-3, 3, 301)
    y = 0.3 + 1.5 * x
    y[::41] += 20
    huber = M.fit_huber_irls(x, y)
    assert huber["converged"]
    assert huber["coefficient"] > 1
    ridge = M.fit_ridge(np.column_stack((x, x * x)), y, 1.0)
    assert ridge["converged"]
    assert len(ridge["coefficients"]) == 2


def test_outcome_windows_are_exact_start_end_and_missing_safe() -> None:
    decision = M.dt_ns(datetime(2024, 1, 2, 10, 0, tzinfo=UTC))
    opens = (decision - M.ONE_MINUTE_NS, *tuple(decision + minute * M.ONE_MINUTE_NS for minute in range(61)))
    bars = {
        stamp: {
            "close_scaled": 100 * M.XAU_SCALE + ordinal * M.XAU_SCALE,
            "available_at_ns": stamp + M.ONE_MINUTE_NS,
            "lineage": str(stamp),
        }
        for ordinal, stamp in enumerate(opens)
    }
    outcomes = M.outcome_fields(decision, bars, "0" * 64)
    assert outcomes["outcome_5m_displacement_fixed_1e9"] == 5 * M.XAU_SCALE
    assert outcomes["outcome_15m_displacement_fixed_1e9"] == 15 * M.XAU_SCALE
    assert outcomes["outcome_60m_displacement_fixed_1e9"] == 60 * M.XAU_SCALE
    bars.pop(decision + 14 * M.ONE_MINUTE_NS)
    outcomes = M.outcome_fields(decision, bars, "0" * 64)
    assert outcomes["outcome_15m_quality"] == "UNKNOWN_MISSING_INVALID_OR_NONUNIQUE_PATH"
    bars[decision + 14 * M.ONE_MINUTE_NS] = {
        "close_scaled": 115 * M.XAU_SCALE,
        "available_at_ns": decision + 15 * M.ONE_MINUTE_NS,
        "lineage": "restored",
    }
    bars[decision - M.ONE_MINUTE_NS]["available_at_ns"] = decision + 1
    outcomes = M.outcome_fields(decision, bars, "0" * 64)
    assert outcomes["outcome_15m_quality"] == "UNKNOWN_MISSING_INVALID_OR_NONUNIQUE_PATH"


def _synthetic_samples() -> list[dict[str, object]]:
    samples: list[dict[str, object]] = []
    for date_index in range(18):
        fold = 1 if date_index < 6 else 2 if date_index < 12 else 3
        block = 11 + date_index
        for offset in (0, 15):
            score = float(date_index - 8.5 + offset / 30)
            samples.append(
                {
                    "anchor_id": f"S:{date_index}:{offset}",
                    "session_date": f"2024-01-{date_index + 1:02d}",
                    "selected_month_week_id": f"B{block:02d}",
                    "chronological_block": block,
                    "anchor_offset_minutes": offset,
                    "fold": fold,
                    "score": score,
                    "outcome_5m": score + 0.1,
                    "outcome_15m": score + 0.2,
                    "outcome_30m": score + 0.3,
                    "outcome_60m": score + 0.4,
                }
            )
    return samples


def test_bootstrap_and_permutation_reproduce_exactly() -> None:
    samples = _synthetic_samples()
    assert M.block_bootstrap(samples, 7, repetitions=200) == M.block_bootstrap(samples, 7, repetitions=200)
    samples[0]["outcome_5m"] = None
    first = M.date_cluster_permutations(samples, 11, repetitions=200)
    second = M.date_cluster_permutations(samples, 11, repetitions=200)
    assert first == second
    assert first["horizons"]["5"]["anchors"] == len(samples) - 1
    assert first["horizons"]["15"]["anchors"] == len(samples)


def test_outcome_coverage_uses_frozen_test_specific_floors() -> None:
    rows: list[dict[str, object]] = []
    for block in range(1, 39):
        year = 2021 if block <= 10 else 2022 if block <= 19 else 2023 if block <= 28 else 2024
        for date_index in range(5):
            session_date = f"{year}-B{block:02d}-D{date_index:02d}"
            for offset in range(16):
                rows.append(
                    {
                        "session_date": session_date,
                        "chronological_block": block,
                        "outcome_15m_quality": "VALID_EXACT_CONTIGUOUS_PATH",
                        "outcome_15m_displacement_fixed_1e9": offset,
                    }
                )
    passed = M.test_specific_outcome_coverage(rows, stage=1)
    assert passed["pass"]
    assert passed["available_primary_outcome_anchors"] == len(rows)

    failed_rows = [dict(row) for row in rows]
    unavailable_2024_dates = {
        str(row["session_date"])
        for row in failed_rows
        if str(row["session_date"]).startswith("2024-")
    }
    unavailable_2024_dates = set(sorted(unavailable_2024_dates)[:11])
    for row in failed_rows:
        if row["session_date"] in unavailable_2024_dates:
            row["outcome_15m_quality"] = "UNKNOWN_MISSING_INVALID_OR_NONUNIQUE_PATH"
            row["outcome_15m_displacement_fixed_1e9"] = None
    failed = M.test_specific_outcome_coverage(failed_rows, stage=1)
    assert not failed["pass"]
    assert not failed["required_years"]["2024"]["pass"]


def test_multiplicity_adjustments_are_order_stable() -> None:
    results = [
        {"test_id": "A", "metrics": {"permutation": {"horizons": {"15": {"two_sided_p_value": 0.01}}}}},
        {"test_id": "B", "metrics": {"permutation": {"horizons": {"15": {"two_sided_p_value": 0.04}}}}},
    ]
    assert M.benjamini_hochberg(results) == {"A": 0.02, "B": 0.04}
    assert M.holm_adjust({5: 0.01, 30: 0.03, 60: 0.2}) == {"5": 0.03, "30": 0.06, "60": 0.2}
