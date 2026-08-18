from __future__ import annotations

import hashlib
import json
import math
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
FEATURE_DIR = ROOT / "research_artifacts" / "gold_trend_pullback_continuation_edge_v1_v01"
ANATOMY_DIR = ROOT / "research_artifacts" / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
OUTPUT_DIR = ROOT / "research_artifacts" / "gold_pullback_behavior_atlas_v1"
REPORT_PATH = ROOT / "GOLD_PULLBACK_BEHAVIOR_ATLAS_V1.md"

FEATURES_PATH = FEATURE_DIR / "primary_features.parquet"
OUTCOMES_PATH = FEATURE_DIR / "primary_outcomes.parquet"
ANATOMY_PATH = ANATOMY_DIR / "primary_movement_anatomy.parquet"
TRIGGERS_PATH = ANATOMY_DIR / "primary_trigger_facts.parquet"
CENSUS_PATH = (
    ROOT
    / "research_artifacts"
    / "gold_multitimeframe_trend_continuation_census_v1_v02"
    / "primary_pullback_cases.parquet"
)

TIMEFRAMES = ("M15", "H1", "H4")
RESOLUTIONS = ("CONTINUED", "FAILED_STRUCTURE_SWITCH")
TF_ORDER = {name: index for index, name in enumerate(TIMEFRAMES)}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def finite(value: Any) -> float | None:
    if value is None or pd.isna(value):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def rounded(value: Any, places: int = 6) -> float | None:
    number = finite(value)
    return None if number is None else round(number, places)


def pct(numerator: int | float, denominator: int | float) -> float | None:
    if not denominator:
        return None
    return round(100.0 * float(numerator) / float(denominator), 6)


def json_clean(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): json_clean(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_clean(item) for item in value]
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return finite(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    if pd.isna(value):
        return None
    return value


def rate_rows(frame: pd.DataFrame, group_columns: Iterable[str]) -> list[dict[str, Any]]:
    group_columns = list(group_columns)
    rows: list[dict[str, Any]] = []
    baseline = frame.groupby("timeframe")["continued"].mean().to_dict()
    for key, group in frame.groupby(group_columns, dropna=False, observed=True):
        keys = key if isinstance(key, tuple) else (key,)
        row = dict(zip(group_columns, keys))
        continued = int(group["continued"].sum())
        count = int(len(group))
        timeframe = str(row["timeframe"])
        rate = 100.0 * continued / count
        row.update(
            cases=count,
            continued=continued,
            failed=count - continued,
            continuation_rate_pct=round(rate, 6),
            lift_vs_timeframe_pp=round(rate - 100.0 * float(baseline[timeframe]), 6),
        )
        rows.append(json_clean(row))
    return rows


def fixed_bin_rows(
    frame: pd.DataFrame,
    column: str,
    edges: list[float],
    labels: list[str],
) -> list[dict[str, Any]]:
    working = frame[["timeframe", "continued", column]].dropna().copy()
    working["bin"] = pd.cut(
        working[column].astype(float), bins=edges, labels=labels, right=False, include_lowest=True
    )
    working = working.dropna(subset=["bin"])
    return rate_rows(working, ["timeframe", "bin"])


def boolean_condition_rows(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        tf = frame[frame["timeframe"] == timeframe]
        baseline = 100.0 * float(tf["continued"].mean())
        for column in columns:
            eligible = tf.dropna(subset=[column])
            positive = eligible[eligible[column].astype(bool)]
            negative = eligible[~eligible[column].astype(bool)]
            positive_rate = 100.0 * float(positive["continued"].mean()) if len(positive) else None
            negative_rate = 100.0 * float(negative["continued"].mean()) if len(negative) else None
            output.append(
                {
                    "timeframe": timeframe,
                    "condition": column,
                    "condition_cases": int(len(positive)),
                    "condition_continuation_rate_pct": rounded(positive_rate),
                    "complement_cases": int(len(negative)),
                    "complement_continuation_rate_pct": rounded(negative_rate),
                    "condition_vs_complement_lift_pp": rounded(
                        None if positive_rate is None or negative_rate is None else positive_rate - negative_rate
                    ),
                    "condition_vs_baseline_lift_pp": rounded(
                        None if positive_rate is None else positive_rate - baseline
                    ),
                }
            )
    return output


def numeric_outcome_summary(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for (timeframe, resolution), group in frame.groupby(["timeframe", "resolution"], observed=True):
        for column in columns:
            values = pd.to_numeric(group[column], errors="coerce").dropna()
            rows.append(
                {
                    "timeframe": timeframe,
                    "resolution": resolution,
                    "field": column,
                    "n": int(len(values)),
                    "q25": rounded(values.quantile(0.25) if len(values) else None),
                    "median": rounded(values.median() if len(values) else None),
                    "q75": rounded(values.quantile(0.75) if len(values) else None),
                    "mean": rounded(values.mean() if len(values) else None),
                }
            )
    return rows


def first_passage_rows(anatomy: pd.DataFrame) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        for resolution in RESOLUTIONS:
            group = anatomy[
                (anatomy["timeframe"] == timeframe)
                & (anatomy["resolution"] == resolution)
                & anatomy["complete_path_available"]
            ]
            for barrier, column in (
                ("0.25_ATR", "barrier_0p25_order"),
                ("0.50_ATR", "barrier_0p5_order"),
                ("0.75_ATR", "barrier_0p75_order"),
                ("1.00_ATR", "barrier_1p0_order"),
                ("1.50_ATR", "barrier_1p5_order"),
                ("2.00_ATR", "barrier_2p0_order"),
            ):
                counts = group[column].fillna("UNKNOWN").value_counts().to_dict()
                output.append(
                    {
                        "timeframe": timeframe,
                        "resolution": resolution,
                        "barrier": barrier,
                        "cases": int(len(group)),
                        "favourable_first": int(counts.get("FAVOURABLE_FIRST", 0)),
                        "adverse_first": int(counts.get("ADVERSE_FIRST", 0)),
                        "same_bar": int(counts.get("BOTH_SAME_BAR", 0)),
                        "neither": int(counts.get("NEITHER", 0)),
                        "favourable_first_pct_all": pct(counts.get("FAVOURABLE_FIRST", 0), len(group)),
                    }
                )
    return output


def trigger_rows(triggers: pd.DataFrame, labels: pd.DataFrame) -> list[dict[str, Any]]:
    joined = triggers.merge(labels[["pullback_id", "continued"]], on="pullback_id", how="left", validate="many_to_one")
    if joined["continued"].isna().any():
        raise ValueError("Trigger facts contain a pullback outside the frozen primary population")
    output: list[dict[str, Any]] = []
    for (timeframe, trigger), group in joined.groupby(["timeframe", "trigger"], observed=True):
        formed = group[group["status"] == "FORMED"]
        absent = group[group["status"] != "FORMED"]
        output.append(
            {
                "timeframe": timeframe,
                "trigger": trigger,
                "eligible_cases": int(len(group)),
                "formed": int(len(formed)),
                "formed_pct": pct(len(formed), len(group)),
                "median_delay_minutes": rounded(formed["entry_delay_minutes"].median() if len(formed) else None),
                "formed_continuation_rate_pct": rounded(100.0 * formed["continued"].mean() if len(formed) else None),
                "not_formed": int(len(absent)),
                "not_formed_continuation_rate_pct": rounded(100.0 * absent["continued"].mean() if len(absent) else None),
            }
        )
    return output


def md_table(headers: list[str], rows: list[list[Any]]) -> list[str]:
    def display(value: Any) -> str:
        if value is None:
            return "NA"
        if isinstance(value, float):
            return f"{value:.2f}"
        return str(value)

    return [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
        *("| " + " | ".join(display(value) for value in row) + " |" for row in rows),
    ]


def main() -> None:
    for path in (FEATURES_PATH, OUTCOMES_PATH, ANATOMY_PATH, TRIGGERS_PATH, CENSUS_PATH):
        if not path.exists():
            raise FileNotFoundError(path)

    features = pd.read_parquet(FEATURES_PATH)
    outcomes = pd.read_parquet(OUTCOMES_PATH)
    joined = features.merge(
        outcomes[["pullback_id", "resolution", "bars_to_resolution", "resolved_at_utc", "resolution_hash"]],
        on="pullback_id",
        how="inner",
        validate="one_to_one",
    )
    population = joined[
        (joined["scale"] == "STANDARD")
        & joined["actionable_at_known"]
        & joined["research_eligible"]
        & joined["feature_available"]
        & joined["resolution"].isin(RESOLUTIONS)
    ].copy()
    population["continued"] = population["resolution"].eq("CONTINUED")
    population["known_timestamp"] = pd.to_datetime(population["known_at_utc"], utc=True)
    population["year"] = population["known_timestamp"].dt.year
    if len(population) != 8_653:
        raise ValueError(f"Frozen STANDARD population changed: {len(population)} != 8653")
    if population["known_timestamp"].max() >= pd.Timestamp("2025-01-01", tz="UTC"):
        raise ValueError("Forward-period row detected")

    anatomy = pd.read_parquet(ANATOMY_PATH)
    anatomy = anatomy[anatomy["pullback_id"].isin(population["pullback_id"])].copy()
    census_pivots = pd.read_parquet(CENSUS_PATH, columns=["pullback_id", "pivot_price_e8"])
    triggers = pd.read_parquet(TRIGGERS_PATH)
    triggers = triggers[triggers["pullback_id"].isin(population["pullback_id"])].copy()

    population_summary: list[dict[str, Any]] = []
    common_trading_dates = int(
        population.loc[population["timeframe"] == "M15", "known_timestamp"].dt.date.nunique()
    )
    common_calendar_weeks = int(
        population.loc[population["timeframe"] == "M15", "known_timestamp"]
        .dt.tz_convert(None)
        .dt.to_period("W")
        .nunique()
    )
    common_calendar_months = int(
        population.loc[population["timeframe"] == "M15", "known_timestamp"]
        .dt.tz_convert(None)
        .dt.to_period("M")
        .nunique()
    )
    recurrence_summary: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        group = population[population["timeframe"] == timeframe]
        continued = int(group["continued"].sum())
        population_summary.append(
            {
                "timeframe": timeframe,
                "cases": int(len(group)),
                "continued": continued,
                "failed_structure_switch": int(len(group) - continued),
                "continuation_rate_pct": pct(continued, len(group)),
                "distinct_decision_dates": int(group["known_timestamp"].dt.date.nunique()),
                "median_bars_to_resolution": rounded(group["bars_to_resolution"].median()),
                "known_from": group["known_at_utc"].min(),
                "known_through": group["known_at_utc"].max(),
            }
        )
        recurrence_summary.append(
            {
                "timeframe": timeframe,
                "setup_cases": int(len(group)),
                "unique_trend_segments": int(group["segment_id"].nunique()),
                "setups_per_common_trading_day": rounded(len(group) / common_trading_dates),
                "setups_per_calendar_week": rounded(len(group) / common_calendar_weeks),
                "setups_per_calendar_month": rounded(len(group) / common_calendar_months),
                "continued_cases": continued,
                "continued_cases_per_common_trading_day": rounded(continued / common_trading_dates),
                "continued_cases_per_calendar_week": rounded(continued / common_calendar_weeks),
                "continued_cases_per_calendar_month": rounded(continued / common_calendar_months),
            }
        )

    annual = rate_rows(population, ["timeframe", "year"])
    by_direction = rate_rows(population, ["timeframe", "direction"])
    by_session = rate_rows(population, ["timeframe", "session_state"])
    by_fundamental_alignment = rate_rows(population, ["timeframe", "fundamental_alignment_state"])
    by_prior_continuations = rate_rows(
        population.assign(
            prior_continuation_band=pd.cut(
                population["prior_continuation_count"],
                bins=[-np.inf, 0.5, 1.5, 2.5, np.inf],
                labels=["0", "1", "2", "3+"],
            )
        ),
        ["timeframe", "prior_continuation_band"],
    )

    fixed_bins = {
        "trend_age_bars": fixed_bin_rows(
            population,
            "trend_age_bars",
            [-np.inf, 5, 9, 17, 33, np.inf],
            ["<=4", "5-8", "9-16", "17-32", "33+"],
        ),
        "event_to_pivot_bars": fixed_bin_rows(
            population,
            "event_to_pivot_bars",
            [-np.inf, 3, 5, 9, 17, np.inf],
            ["<=2", "3-4", "5-8", "9-16", "17+"],
        ),
        "retracement_depth_atr": fixed_bin_rows(
            population,
            "retracement_depth_atr",
            [-np.inf, 0.5, 1.0, 1.5, 2.0, np.inf],
            ["<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", "2.0+"],
        ),
        "pullback_efficiency": fixed_bin_rows(
            population,
            "pullback_efficiency",
            [-np.inf, 0.25, 0.50, 0.75, np.inf],
            ["<0.25", "0.25-0.50", "0.50-0.75", "0.75+"],
        ),
        "compression_ratio": fixed_bin_rows(
            population,
            "compression_ratio",
            [-np.inf, 0.75, 1.0, 1.25, np.inf],
            ["<0.75", "0.75-1.00", "1.00-1.25", "1.25+"],
        ),
        "response_displacement_atr": fixed_bin_rows(
            population,
            "response_displacement_atr",
            [-np.inf, 0.0, 0.25, 0.50, 0.80, np.inf],
            ["<0", "0-0.25", "0.25-0.50", "0.50-0.80", "0.80+"],
        ),
        "confirmation_close_location_trend": fixed_bin_rows(
            population,
            "confirmation_close_location_trend",
            [-np.inf, 1 / 3, 0.50, 2 / 3, 0.80, np.inf],
            ["<0.33", "0.33-0.50", "0.50-0.67", "0.67-0.80", "0.80+"],
        ),
        "pivot_close_location_trend": fixed_bin_rows(
            population,
            "pivot_close_location_trend",
            [-np.inf, 1 / 3, 0.50, 2 / 3, 0.80, np.inf],
            ["<0.33", "0.33-0.50", "0.50-0.67", "0.67-0.80", "0.80+"],
        ),
    }

    retracement_zones = rate_rows(population, ["timeframe", "retracement_zone"])
    candle_states = {
        "pivot_body_state": rate_rows(population, ["timeframe", "pivot_body_state"]),
        "confirmation_body_state": rate_rows(population, ["timeframe", "confirmation_body_state"]),
        "pivot_confirmation_sequence": rate_rows(
            population.assign(
                pivot_confirmation_sequence=(
                    population["pivot_body_state"].astype(str)
                    + " -> "
                    + population["confirmation_body_state"].astype(str)
                )
            ),
            ["timeframe", "pivot_confirmation_sequence"],
        ),
    }

    bool_columns = [
        "pivot_rejection_strong",
        "pivot_engulfing_aligned",
        "pivot_inside_bar",
        "pivot_outside_bar",
        "pivot_close_through_prior_extreme",
        "confirmation_displacement",
        "confirmation_engulfing_aligned",
        "confirmation_inside_bar",
        "confirmation_outside_bar",
        "confirmation_close_through_prior_extreme",
        "reference_touch",
        "reference_sweep_reclaim",
        "prior_day_sweep_reclaim",
        "asia_sweep_reclaim",
        "h1_structure_alignment",
        "h4_structure_alignment",
        "daily_3bar_alignment",
        "weekly_2bar_alignment",
    ]
    boolean_conditions = boolean_condition_rows(population, bool_columns)

    numeric_fields = [
        "bars_to_resolution",
        "trend_age_bars",
        "event_to_pivot_bars",
        "prior_continuation_count",
        "impulse_extension_atr",
        "impulse_efficiency",
        "pullback_efficiency",
        "retracement_fraction",
        "retracement_depth_atr",
        "compression_ratio",
        "pivot_range_atr",
        "pivot_body_fraction",
        "pivot_close_location_trend",
        "pivot_rejection_wick_fraction",
        "confirmation_range_atr",
        "confirmation_body_fraction",
        "confirmation_close_location_trend",
        "confirmation_rejection_wick_fraction",
        "response_displacement_atr",
        "response_efficiency",
        "response_aligned_close_count",
    ]
    numeric_summary = numeric_outcome_summary(population, numeric_fields)

    anatomy_numeric = numeric_outcome_summary(
        anatomy[anatomy["complete_path_available"].fillna(False).astype(bool)],
        [
            "complete_mfe_atr",
            "complete_mae_atr",
            "terminal_displacement_atr",
            "minutes_to_max_favourable",
            "minutes_to_max_adverse",
        ],
    )
    complete_anatomy = anatomy[anatomy["complete_path_available"].fillna(False).astype(bool)].copy()
    complete_anatomy["mfe_usd_oz"] = complete_anatomy["complete_mfe_atr"] * complete_anatomy["atr14_e8"] / 1e8
    complete_anatomy["mae_usd_oz"] = complete_anatomy["complete_mae_atr"] * complete_anatomy["atr14_e8"] / 1e8
    dollar_path_summary = numeric_outcome_summary(
        complete_anatomy,
        ["mfe_usd_oz", "mae_usd_oz"],
    )
    pivot_paths = complete_anatomy.merge(census_pivots, on="pullback_id", how="left", validate="one_to_one")
    if pivot_paths["pivot_price_e8"].isna().any():
        raise ValueError("A complete path is missing its frozen visual pivot price")
    pivot_paths["direction_sign"] = np.where(pivot_paths["direction"].eq("UP"), 1.0, -1.0)
    pivot_paths["pivot_to_anchor_atr"] = (
        pivot_paths["direction_sign"]
        * (pivot_paths["anchor_open_e8"] - pivot_paths["pivot_price_e8"])
        / pivot_paths["atr14_e8"]
    )
    pivot_paths["pivot_to_max_atr"] = pivot_paths["pivot_to_anchor_atr"] + pivot_paths["complete_mfe_atr"]
    pivot_paths["pivot_to_terminal_atr"] = (
        pivot_paths["pivot_to_anchor_atr"] + pivot_paths["terminal_displacement_atr"]
    )
    pivot_paths["opposite_beyond_pivot_atr"] = (
        -(pivot_paths["pivot_to_anchor_atr"] - pivot_paths["complete_mae_atr"])
    ).clip(lower=0)
    for atr_field, dollar_field in (
        ("pivot_to_max_atr", "pivot_to_max_usd_oz"),
        ("pivot_to_terminal_atr", "pivot_to_terminal_usd_oz"),
        ("opposite_beyond_pivot_atr", "opposite_beyond_pivot_usd_oz"),
    ):
        pivot_paths[dollar_field] = pivot_paths[atr_field] * pivot_paths["atr14_e8"] / 1e8
    pivot_path_summary = numeric_outcome_summary(
        pivot_paths,
        [
            "pivot_to_max_atr",
            "pivot_to_max_usd_oz",
            "pivot_to_terminal_atr",
            "pivot_to_terminal_usd_oz",
            "opposite_beyond_pivot_atr",
            "opposite_beyond_pivot_usd_oz",
        ],
    )
    pivot_paths["known_timestamp"] = pd.to_datetime(pivot_paths["known_at_utc"], utc=True)
    oracle_capture_ceiling: list[dict[str, Any]] = []
    for timeframe in TIMEFRAMES:
        group = pivot_paths[pivot_paths["timeframe"] == timeframe].sort_values("known_timestamp").copy()
        continued = group[group["resolution"] == "CONTINUED"]
        failures = int((group["resolution"] == "FAILED_STRUCTURE_SWITCH").sum())
        group["oracle_r"] = np.where(
            group["resolution"].eq("CONTINUED"), group["pivot_to_max_atr"], -1.0
        )
        cumulative = group["oracle_r"].cumsum()
        peak = cumulative.cummax().clip(lower=0)
        winner_r_total = float(continued["pivot_to_max_atr"].sum())
        net_r = float(group["oracle_r"].sum())
        oracle_capture_ceiling.append(
            {
                "timeframe": timeframe,
                "complete_cases": int(len(group)),
                "successful_continuations": int(len(continued)),
                "failures_charged_one_sl": failures,
                "success_rate_pct": pct(len(continued), len(group)),
                "average_winner_r": rounded(continued["pivot_to_max_atr"].mean()),
                "median_winner_r": rounded(continued["pivot_to_max_atr"].median()),
                "winner_r_total": rounded(winner_r_total),
                "loss_r_total": -failures,
                "net_r": rounded(net_r),
                "expectancy_r_per_case": rounded(group["oracle_r"].mean()),
                "profit_factor": rounded(winner_r_total / failures),
                "max_drawdown_r": rounded((peak - cumulative).max()),
                "fixed_0p5pct_risk": {
                    "risk_usd": 50.0,
                    "winner_profit_usd": rounded(winner_r_total * 50.0),
                    "failure_loss_usd": rounded(-failures * 50.0),
                    "net_pnl_usd": rounded(net_r * 50.0),
                    "average_monthly_pnl_usd": rounded(net_r * 50.0 / common_calendar_months),
                    "ending_balance_usd": rounded(10_000.0 + net_r * 50.0),
                },
                "fixed_1pct_risk": {
                    "risk_usd": 100.0,
                    "net_pnl_usd": rounded(net_r * 100.0),
                    "average_monthly_pnl_usd": rounded(net_r * 100.0 / common_calendar_months),
                    "ending_balance_usd": rounded(10_000.0 + net_r * 100.0),
                },
            }
        )
    passage = first_passage_rows(anatomy)
    triggers_summary = trigger_rows(triggers, population)

    atlas = {
        "version": "GOLD_PULLBACK_BEHAVIOR_ATLAS_V1_1_0",
        "classification": "POST_HOC_DEVELOPMENT_DESCRIPTION_ONLY",
        "development_period": ["2021-08-01", "2024-12-31"],
        "forward_values_accessed": False,
        "primary_scale": "STANDARD_SPAN_2",
        "input_lineage": {
            str(path.relative_to(ROOT)): {"sha256": sha256_file(path), "bytes": path.stat().st_size}
            for path in (FEATURES_PATH, OUTCOMES_PATH, ANATOMY_PATH, TRIGGERS_PATH, CENSUS_PATH)
        },
        "population": population_summary,
        "recurrence": {
            "common_trading_dates": common_trading_dates,
            "calendar_weeks": common_calendar_weeks,
            "calendar_months": common_calendar_months,
            "rows": recurrence_summary,
            "overlap_warning": "Cases can overlap within the same structural segment and are not independent trades.",
        },
        "annual": annual,
        "direction": by_direction,
        "session": by_session,
        "fundamental_alignment": by_fundamental_alignment,
        "prior_continuation_count": by_prior_continuations,
        "fixed_bins": fixed_bins,
        "retracement_zones": retracement_zones,
        "candle_states": candle_states,
        "boolean_conditions": boolean_conditions,
        "numeric_outcome_summary": numeric_summary,
        "path_numeric_summary": anatomy_numeric,
        "dollar_path_summary": dollar_path_summary,
        "visual_pivot_path_summary": pivot_path_summary,
        "oracle_capture_ceiling": {
            "assumptions": [
                "Every CONTINUED case captures its complete visual-pivot-to-maximum move.",
                "Every FAILED_STRUCTURE_SWITCH case loses exactly 1R.",
                "One ATR is treated as the constant stop distance and 1R.",
                "The fixed-risk ledgers use $50 (0.5% initial equity) or $100 (1% initial equity) with no compounding.",
                "Costs, overlap, fill feasibility, confirmation delay and imperfect exits are intentionally excluded.",
            ],
            "rows": oracle_capture_ceiling,
        },
        "first_passage": passage,
        "trigger_availability": triggers_summary,
        "limitations": [
            "All tables are post-hoc descriptions of 2021-2024 development data.",
            "A pullback case is not a winning continuation trade; FAILED_STRUCTURE_SWITCH cases remain in the denominator.",
            "Candle labels are deterministic geometry, not evidence of institutional intent.",
            "The report does not define or validate a new entry, exit, stop, target, or economic edge.",
            "Calendar 2025 and 2026 values were not read by this analysis.",
        ],
    }

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    atlas_path = OUTPUT_DIR / "atlas.json"
    atlas_bytes = (json.dumps(json_clean(atlas), indent=2, sort_keys=True) + "\n").encode("utf-8")
    atlas_path.write_bytes(atlas_bytes)

    lines = [
        "# Gold Pullback Behaviour Atlas V1",
        "",
        "Status: **COMPLETE_POST_HOC_DEVELOPMENT_DESCRIPTION**",
        "",
        "This report describes the sealed 2021-2024 STANDARD span-two pullback population. It does not define a new rule or claim an economic edge. Calendar 2025 and 2026 were not accessed.",
        "",
        "## What was actually validated",
        "",
        "A trend/pullback setup is common. Successful continuation is not automatic: every setup remains in the denominator until either the next same-direction structure break or an opposite structure switch.",
        "",
        "## Point-in-time clocks",
        "",
        "- Trend direction becomes observable only when a completed candle closes through a previously confirmed swing. The first such break is a structure switch; later same-direction breaks are continuation breaks.",
        "- On the STANDARD scale, a swing uses two bars on each side. The pivot is therefore not knowable until the second right-hand bar closes: 30 minutes after an M15 pivot, 2 hours after an H1 pivot, and 8 hours after an H4 pivot.",
        "- A pullback decision is timestamped at that confirmation close, never at the visually obvious pivot candle. Anything formed later belongs to trigger/execution research.",
        "",
        "## Primary denominator",
        "",
    ]
    lines += md_table(
        ["TF", "Cases", "Continued", "Failed", "Continue %", "Decision dates", "Median bars to resolution"],
        [
            [
                row["timeframe"],
                row["cases"],
                row["continued"],
                row["failed_structure_switch"],
                row["continuation_rate_pct"],
                row["distinct_decision_dates"],
                row["median_bars_to_resolution"],
            ]
            for row in population_summary
        ],
    )

    lines += [
        "",
        "## Recurrence",
        "",
        "The common denominator contains 887 XAUUSD trading dates, 179 calendar weeks and 41 calendar months. Multiple pullbacks can occur inside one structural trend, so these are recurring observations rather than independent trades.",
        "",
    ]
    lines += md_table(
        ["TF", "Setups/day", "Setups/week", "Setups/month", "Continued/day", "Continued/week", "Unique trend segments"],
        [
            [
                row["timeframe"],
                row["setups_per_common_trading_day"],
                row["setups_per_calendar_week"],
                row["setups_per_calendar_month"],
                row["continued_cases_per_common_trading_day"],
                row["continued_cases_per_calendar_week"],
                row["unique_trend_segments"],
            ]
            for row in recurrence_summary
        ],
    )

    direction_lookup = {(row["timeframe"], row["direction"]): row for row in by_direction}
    lines += ["", "## Direction asymmetry", ""]
    lines += md_table(
        ["TF", "Up cases", "Up continue %", "Down cases", "Down continue %"],
        [
            [
                timeframe,
                direction_lookup[(timeframe, "UP")]["cases"],
                direction_lookup[(timeframe, "UP")]["continuation_rate_pct"],
                direction_lookup[(timeframe, "DOWN")]["cases"],
                direction_lookup[(timeframe, "DOWN")]["continuation_rate_pct"],
            ]
            for timeframe in TIMEFRAMES
        ],
    )

    lines += ["", "## Session and point-in-time fundamental context", ""]
    lines += md_table(
        ["TF", "Context", "State", "N", "Continue %", "Lift vs TF pp"],
        [
            [
                row["timeframe"],
                "SESSION",
                row["session_state"],
                row["cases"],
                row["continuation_rate_pct"],
                row["lift_vs_timeframe_pp"],
            ]
            for row in by_session
        ]
        + [
            [
                row["timeframe"],
                "FUNDAMENTAL",
                row["fundamental_alignment_state"],
                row["cases"],
                row["continuation_rate_pct"],
                row["lift_vs_timeframe_pp"],
            ]
            for row in by_fundamental_alignment
        ],
    )

    chosen_conditions = {
        "pivot_rejection_strong",
        "pivot_engulfing_aligned",
        "confirmation_displacement",
        "confirmation_engulfing_aligned",
        "reference_sweep_reclaim",
        "asia_sweep_reclaim",
    }
    condition_rows = [row for row in boolean_conditions if row["condition"] in chosen_conditions]
    condition_rows.sort(key=lambda row: (TF_ORDER[row["timeframe"]], -float(row["condition_vs_complement_lift_pp"] or -999)))
    lines += [
        "",
        "## Completed-candle and level clues",
        "",
        "Positive lift here is descriptive. The earlier sealed relationship study supplied formal clustered uncertainty and multiplicity controls; these rows do not create a new candidate.",
        "",
    ]
    lines += md_table(
        ["TF", "Condition", "N", "Continue %", "Complement %", "Lift pp"],
        [
            [
                row["timeframe"],
                row["condition"],
                row["condition_cases"],
                row["condition_continuation_rate_pct"],
                row["complement_continuation_rate_pct"],
                row["condition_vs_complement_lift_pp"],
            ]
            for row in condition_rows
        ],
    )

    response_rows = fixed_bins["response_displacement_atr"]
    lines += ["", "## Response displacement known at pullback confirmation", ""]
    lines += md_table(
        ["TF", "Trend-normalized displacement", "N", "Continue %", "Lift vs TF pp"],
        [
            [row["timeframe"], row["bin"], row["cases"], row["continuation_rate_pct"], row["lift_vs_timeframe_pp"]]
            for row in response_rows
        ],
    )

    retrace_rows = retracement_zones
    lines += ["", "## Retracement location", ""]
    lines += md_table(
        ["TF", "Zone", "N", "Continue %", "Lift vs TF pp"],
        [
            [
                row["timeframe"],
                row["retracement_zone"],
                row["cases"],
                row["continuation_rate_pct"],
                row["lift_vs_timeframe_pp"],
            ]
            for row in retrace_rows
        ],
    )

    numeric_index = {
        (row["timeframe"], row["resolution"], row["field"]): row for row in numeric_summary
    }
    lines += ["", "## Candle geometry: continuation versus later structure reversal", ""]
    lines += md_table(
        ["TF", "Field", "Continued median", "Failed median"],
        [
            [
                timeframe,
                field,
                numeric_index[(timeframe, "CONTINUED", field)]["median"],
                numeric_index[(timeframe, "FAILED_STRUCTURE_SWITCH", field)]["median"],
            ]
            for timeframe in TIMEFRAMES
            for field in (
                "pivot_range_atr",
                "pivot_body_fraction",
                "pivot_close_location_trend",
                "pivot_rejection_wick_fraction",
                "confirmation_range_atr",
                "confirmation_body_fraction",
                "confirmation_close_location_trend",
                "response_displacement_atr",
                "response_efficiency",
            )
        ],
    )

    sequence_rows = [
        row
        for row in candle_states["pivot_confirmation_sequence"]
        if row["pivot_confirmation_sequence"]
        in {"ALIGNED -> ALIGNED", "ALIGNED -> OPPOSED", "OPPOSED -> ALIGNED", "OPPOSED -> OPPOSED"}
    ]
    sequence_rows.sort(key=lambda row: (TF_ORDER[row["timeframe"]], row["pivot_confirmation_sequence"]))
    lines += [
        "",
        "The pivot candle alone separates outcomes poorly. The completed pivot-to-confirmation sequence is more informative:",
        "",
    ]
    lines += md_table(
        ["TF", "Pivot -> confirmation body", "N", "Continue %", "Failure %"],
        [
            [
                row["timeframe"],
                row["pivot_confirmation_sequence"],
                row["cases"],
                row["continuation_rate_pct"],
                round(100.0 - row["continuation_rate_pct"], 6),
            ]
            for row in sequence_rows
        ],
    )

    path_index = {
        (row["timeframe"], row["resolution"], row["field"]): row for row in anatomy_numeric
    }
    dollar_index = {
        (row["timeframe"], row["resolution"], row["field"]): row for row in dollar_path_summary
    }
    pivot_path_index = {
        (row["timeframe"], row["resolution"], row["field"]): row for row in pivot_path_summary
    }
    lines += [
        "",
        "## Entry-independent movement from the visual pullback pivot",
        "",
        "This is pure market anatomy: distance from the actual visual swing pivot to the furthest trend-side price before structural resolution. It includes movement that occurred before the pivot became point-in-time confirmable and therefore is not a claim that the whole distance was tradable.",
        "",
    ]
    lines += md_table(
        ["TF", "Resolution", "Max ATR Q25", "Max ATR median", "Max ATR Q75", "Max $/oz Q25", "Max $/oz median", "Max $/oz Q75", "Net $/oz at resolution"],
        [
            [
                timeframe,
                resolution,
                pivot_path_index[(timeframe, resolution, "pivot_to_max_atr")]["q25"],
                pivot_path_index[(timeframe, resolution, "pivot_to_max_atr")]["median"],
                pivot_path_index[(timeframe, resolution, "pivot_to_max_atr")]["q75"],
                pivot_path_index[(timeframe, resolution, "pivot_to_max_usd_oz")]["q25"],
                pivot_path_index[(timeframe, resolution, "pivot_to_max_usd_oz")]["median"],
                pivot_path_index[(timeframe, resolution, "pivot_to_max_usd_oz")]["q75"],
                pivot_path_index[(timeframe, resolution, "pivot_to_terminal_usd_oz")]["median"],
            ]
            for timeframe in TIMEFRAMES
            for resolution in RESOLUTIONS
        ],
    )
    lines += [
        "",
        "## Oracle full-capture account ceiling",
        "",
        "This answers the hypothetical question: capture every successful move from its visual pivot to its maximum, and charge every failed structure case exactly one 1-ATR stop. It excludes costs, overlap, confirmation delay and execution feasibility and is not a backtest.",
        "",
    ]
    lines += md_table(
        ["TF", "Cases", "Successes", "SL failures", "Avg winner R", "Net R", "PF", "Net at $50 risk", "Avg/month at $50", "Net at $100 risk", "Avg/month at $100"],
        [
            [
                row["timeframe"],
                row["complete_cases"],
                row["successful_continuations"],
                row["failures_charged_one_sl"],
                row["average_winner_r"],
                row["net_r"],
                row["profit_factor"],
                row["fixed_0p5pct_risk"]["net_pnl_usd"],
                row["fixed_0p5pct_risk"]["average_monthly_pnl_usd"],
                row["fixed_1pct_risk"]["net_pnl_usd"],
                row["fixed_1pct_risk"]["average_monthly_pnl_usd"],
            ]
            for row in oracle_capture_ceiling
        ],
    )
    lines += ["", "## Post-decision path anatomy", ""]
    lines += md_table(
        ["TF", "Resolution", "N", "Median MFE ATR", "Median MAE ATR", "Median terminal ATR", "Median min to MFE", "Median min to MAE"],
        [
            [
                timeframe,
                resolution,
                path_index[(timeframe, resolution, "complete_mfe_atr")]["n"],
                path_index[(timeframe, resolution, "complete_mfe_atr")]["median"],
                path_index[(timeframe, resolution, "complete_mae_atr")]["median"],
                path_index[(timeframe, resolution, "terminal_displacement_atr")]["median"],
                path_index[(timeframe, resolution, "minutes_to_max_favourable")]["median"],
                path_index[(timeframe, resolution, "minutes_to_max_adverse")]["median"],
            ]
            for timeframe in TIMEFRAMES
            for resolution in RESOLUTIONS
        ],
    )
    lines += [
        "",
        "Dollar distances use the case-specific ATR and are dollars per troy ounce, not account PnL:",
        "",
    ]
    lines += md_table(
        ["TF", "Resolution", "MFE $/oz Q25", "MFE $/oz median", "MFE $/oz Q75", "MAE $/oz median"],
        [
            [
                timeframe,
                resolution,
                dollar_index[(timeframe, resolution, "mfe_usd_oz")]["q25"],
                dollar_index[(timeframe, resolution, "mfe_usd_oz")]["median"],
                dollar_index[(timeframe, resolution, "mfe_usd_oz")]["q75"],
                dollar_index[(timeframe, resolution, "mae_usd_oz")]["median"],
            ]
            for timeframe in TIMEFRAMES
            for resolution in RESOLUTIONS
        ],
    )

    trigger_order = {
        "IMMEDIATE": 0,
        "CONFIRMATION_EXTREME_BREAK": 1,
        "RESPONSE_HALF_RETRACE_LIMIT": 2,
        "REFERENCE_LEVEL_RETEST_LIMIT": 3,
        "BREAK_RETEST_CONFIRM": 4,
    }
    triggers_summary.sort(key=lambda row: (TF_ORDER[row["timeframe"]], trigger_order[row["trigger"]]))
    lines += ["", "## Trigger opportunity frequency (not profitability)", ""]
    lines += md_table(
        ["TF", "Trigger", "Eligible", "Formed", "Formed %", "Median delay min", "Formed continue %", "Absent continue %"],
        [
            [
                row["timeframe"],
                row["trigger"],
                row["eligible_cases"],
                row["formed"],
                row["formed_pct"],
                row["median_delay_minutes"],
                row["formed_continuation_rate_pct"],
                row["not_formed_continuation_rate_pct"],
            ]
            for row in triggers_summary
        ],
    )

    lines += [
        "",
        "## Direct reading of the evidence",
        "",
        "1. The setup is frequent, but its unconditional continuation probability at the point-in-time pullback decision is near 50%; frequency alone is not the edge.",
        "2. Retracement depth and a generic rejection wick do not provide a stable standalone discriminator. The response after the pivot is more informative than the pivot shape by itself.",
        "3. A large trend-aligned confirmation candle, trend-aligned response displacement, and an objective sweep/reclaim were the clearest development relationships. They describe acceptance after the pullback, not an institution that was directly observed.",
        "4. A later structure reversal is not represented by one universal candle name. In aggregate it is characterized more by weak/opposed confirmation and inferior trend-normalized response than by the pivot candle alone.",
        "5. The rejected economic tests do not prove monetization is impossible. They prove that the specific frozen entry/structural-stop/nearby-target families tested so far did not convert the relationship into positive net expectancy.",
        "",
        "## Research boundary",
        "",
        "This atlas may be used to write one explicit rule before any forward path is opened. That rule must state the timeframe, structural trend clock, pullback/location condition, completed-candle trigger, entry clock, invalidation, target/exit, and no-trade conditions. Testing it on 2025 and 2026 will be an exposed historical robustness test, not pristine independent validation.",
    ]
    REPORT_PATH.write_text("\n".join(lines) + "\n", encoding="utf-8")

    final = {
        "status": "PASS_COMPLETE_POST_HOC_DEVELOPMENT_DESCRIPTION",
        "forward_values_accessed": False,
        "population_rows": int(len(population)),
        "anatomy_rows": int(len(anatomy)),
        "trigger_rows": int(len(triggers)),
        "atlas_sha256": sha256_file(atlas_path),
        "report_sha256": sha256_file(REPORT_PATH),
        "input_hashes": atlas["input_lineage"],
    }
    final_path = OUTPUT_DIR / "final_seal.json"
    final_path.write_text(json.dumps(final, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps(final, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
