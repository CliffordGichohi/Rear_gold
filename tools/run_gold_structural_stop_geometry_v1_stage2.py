from __future__ import annotations

import hashlib
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_structural_stop_geometry_v1_stage1 as stage1  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_structural_stop_geometry_v1_economic"
DEVELOPMENT_REPORT = ROOT / "GOLD_STRUCTURAL_STOP_GEOMETRY_ECONOMIC_RESEARCH_V1_DEVELOPMENT.md"
FINAL_REPORT = ROOT / "GOLD_STRUCTURAL_STOP_GEOMETRY_ECONOMIC_RESEARCH_V1_FINAL.md"
PROTOCOL = MANIFESTS / "gold_structural_stop_geometry_v1_protocol.json"
STAGE2_FREEZE = MANIFESTS / "gold_structural_stop_geometry_v1_stage2_pre_economic_freeze.json"
STAGE1_DIR = ARTIFACTS / "gold_structural_stop_geometry_v1_stage1"
STAGE1_SEAL = STAGE1_DIR / "stage1_seal.json"
ROUTING = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"

SCALE = 100_000_000
TF_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
BOOTSTRAPS = 5000
BASE_SEED = 861301


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.relative_to(ROOT)).replace("\\", "/"),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def write_json_exclusive(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    try:
        table = pa.Table.from_pylist(list(rows))
        pq.write_table(
            table,
            temporary,
            compression="zstd",
            use_dictionary=False,
            write_statistics=True,
            data_page_version="1.0",
            version="2.6",
            row_group_size=16_384,
        )
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = json.loads(STAGE2_FREEZE.read_text(encoding="utf-8"))
    stage1_seal = json.loads(STAGE1_SEAL.read_text(encoding="utf-8"))
    if freeze.get("status") != "FROZEN_BEFORE_STAGE_2_ECONOMIC_VALUES":
        raise ValueError("Stage-2 freeze status changed")
    if stage1_seal.get("status") != "PASS_STAGE1_INDEPENDENT_REPRODUCTION":
        raise ValueError("Stage-1 seal status changed")
    for item in freeze["predecessors"].values():
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Frozen predecessor changed: {item['path']}")
    for item in stage1_seal["artifacts"].values():
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Stage-1 artifact changed: {item['path']}")
    if len(freeze["evaluated_candidate_ids"]) != 53:
        raise ValueError("Evaluated registry changed")
    if freeze.get("calendar_2025_values_accessed") or freeze.get("calendar_2026_values_accessed"):
        raise ValueError("Forward lock is not intact")
    return protocol, freeze, stage1_seal


def model_registry() -> dict[str, dict[str, Any]]:
    payload = json.loads((MANIFESTS / "gold_pullback_archetype_setup_routing_v1_protocol.json").read_text(encoding="utf-8"))
    result = {str(row["model_id"]): dict(row) for row in payload["entry_models"]}
    if len(result) != 6:
        raise ValueError("Frozen model registry changed")
    return result


def candidate_parts(candidate_id: str) -> tuple[str, str, str]:
    values = candidate_id.split("|")
    if len(values) != 3:
        raise ValueError(candidate_id)
    return values[0], values[1], values[2]


def neighbour_registry(candidate_id: str, models: Mapping[str, Mapping[str, Any]]) -> list[dict[str, Any]]:
    _, model_id, stop_id = candidate_parts(candidate_id)
    if stop_id == "STOP_CONFIRMATION_EXTREME_0P25_ATR":
        family, buffers = "CONFIRMATION_EXTREME", (0.15, 0.35)
    elif stop_id == "STOP_PIVOT_0P25_ATR":
        family, buffers = "PIVOT", (0.15, 0.35)
    elif stop_id == "STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR":
        family, buffers = "LATEST_KNOWN_OPPOSING_SWING", (0.00, 0.20)
    elif stop_id == "STOP_BASELINE_FROZEN":
        source = str(models[model_id]["stop"])
        if source == "CONFIRMATION_EXTREME_BUFFER_0P05_ATR":
            family, buffers = "CONFIRMATION_EXTREME", (0.00, 0.15)
        elif source == "PIVOT_BUFFER_0P15_ATR":
            family, buffers = "PIVOT", (0.05, 0.25)
        else:
            raise ValueError(f"Unknown frozen baseline stop: {source}")
    else:
        raise ValueError(stop_id)
    return [
        {
            "candidate_id": candidate_id,
            "neighbour_id": f"{family}::{buffer:.2f}_ATR",
            "family": family,
            "buffer_atr": buffer,
        }
        for buffer in buffers
    ]


def buffered_stop(
    trade: Mapping[str, Any],
    fact: Mapping[str, Any],
    swings: stage1.SwingIndex,
    family: str,
    buffer_atr: float,
) -> tuple[int | None, str | None, str | None]:
    entry = int(trade["entry_e8"])
    direction = str(trade["trade_direction"])
    sign = 1 if direction == "UP" else -1
    atr = float(fact["atr14_e8"])
    buffer_e8 = int(round(buffer_atr * atr))
    level_id: str | None
    if family == "CONFIRMATION_EXTREME":
        stop = int(fact["confirmation_low_e8"]) - buffer_e8 if sign > 0 else int(fact["confirmation_high_e8"]) + buffer_e8
        level_id = "CONFIRMATION_EXTREME"
    elif family == "PIVOT":
        stop = int(fact["pivot_price_e8"]) - buffer_e8 if sign > 0 else int(fact["pivot_price_e8"]) + buffer_e8
        level_id = "PULLBACK_PIVOT"
    elif family == "LATEST_KNOWN_OPPOSING_SWING":
        selected = swings.latest_adverse(
            str(trade["timeframe"]), direction, stage1.parse_ns(str(trade["entry_at_utc"])), entry
        )
        if selected is None:
            return None, None, "NO_KNOWN_ADVERSE_STANDARD_SWING"
        stop = int(selected["price_e8"]) - buffer_e8 if sign > 0 else int(selected["price_e8"]) + buffer_e8
        level_id = str(selected["swing_id"])
    else:
        raise ValueError(family)
    if (sign > 0 and stop >= entry) or (sign < 0 and stop <= entry):
        return None, level_id, "STOP_NOT_ADVERSE_TO_ENTRY"
    return stop, level_id, None


def economic_values(
    entry: int,
    stop: int,
    target: int,
    exit_e8: int,
    direction: str,
    total_cost: float,
    planned_ounces: int,
) -> dict[str, Any]:
    sign = 1 if direction == "UP" else -1
    risk_e8 = abs(entry - stop)
    risk_usd = risk_e8 / SCALE
    gross_r = sign * (exit_e8 - entry) / risk_e8
    cost_r = total_cost / risk_usd
    signed_change_usd = sign * (exit_e8 - entry) / SCALE
    net_r = gross_r - cost_r
    return {
        "gross_r": rounded(gross_r),
        "cost_r": rounded(cost_r),
        "net_r": rounded(net_r),
        "net_r_cost_1p5x": rounded(gross_r - 1.5 * cost_r),
        "net_r_cost_2x": rounded(gross_r - 2.0 * cost_r),
        "normalized_pnl_usd": rounded(50.0 * net_r),
        "whole_ounce_pnl_usd": rounded((signed_change_usd - total_cost) * planned_ounces),
        "target_r": rounded(abs(target - entry) / risk_e8),
    }


def apply_overlap(rows: list[dict[str, Any]], field: str, formal_oof: bool) -> None:
    eligible = [
        row
        for row in rows
        if row["economic_status"] == "EXECUTABLE" and (not formal_oof or bool(row["is_oof_validation"]))
    ]
    eligible.sort(key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])))
    open_until: str | None = None
    for row in rows:
        row[field] = "NOT_OOF" if formal_oof and not bool(row["is_oof_validation"]) else "UNAVAILABLE"
    for row in eligible:
        if open_until is not None and str(row["entry_at_utc"]) < open_until:
            row[field] = "SKIPPED_OVERLAPPING_POSITION"
        else:
            row[field] = "ACCEPTED"
            open_until = str(row["exit_at_utc"])


def base_economic_rows(side: str, candidate_ids: Sequence[str]) -> list[dict[str, Any]]:
    source = pq.read_table(STAGE1_DIR / f"{side}_survival_rows.parquet").to_pylist()
    candidate_set = set(candidate_ids)
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for raw in source:
        candidate_id = f"{raw['timeframe']}|{raw['model_id']}|{raw['stop_id']}"
        if candidate_id not in candidate_set:
            continue
        row = {
            "candidate_id": candidate_id,
            "trade_id": str(raw["trade_id"]),
            "pullback_id": str(raw["pullback_id"]),
            "timeframe": str(raw["timeframe"]),
            "model_id": str(raw["model_id"]),
            "stop_id": str(raw["stop_id"]),
            "archetype": str(raw["archetype"]),
            "trade_direction": str(raw["trade_direction"]),
            "session_state": str(raw["session_state"]),
            "known_at_utc": str(raw["known_at_utc"]),
            "entry_at_utc": str(raw["entry_at_utc"]),
            "exit_at_utc": raw["exit_at_utc"],
            "cluster_date": str(raw["cluster_date"]),
            "iso_week": str(raw["iso_week"]),
            "calendar_year": int(raw["calendar_year"]),
            "oof_fold": raw["oof_fold"],
            "is_oof_validation": bool(raw["is_oof_validation"]),
            "entry_e8": int(raw["entry_e8"]),
            "stop_e8": raw["stop_e8"],
            "target_e8": int(raw["target_e8"]),
            "exit_e8": raw["exit_e8"],
            "exit_reason": raw["exit_reason"],
            "total_cost_usd_oz": float(raw["total_cost_usd_oz"]),
            "planned_ounces": raw["planned_ounces"],
            "stop_distance_usd_oz": raw["stop_distance_usd_oz"],
            "stop_distance_atr": raw["stop_distance_atr"],
            "stop_hit_full_horizon": raw["stop_hit_full_horizon"],
            "stop_before_or_same_as_global_mfe": raw["stop_before_or_same_as_global_mfe"],
            "full_horizon_mfe_r": raw["full_horizon_mfe_r"],
            "full_horizon_mae_r": raw["full_horizon_mae_r"],
            "exit_mfe_r": raw["exit_mfe_r"],
            "exit_mae_r": raw["exit_mae_r"],
            "holding_minutes": None,
            "economic_status": "EXECUTABLE",
            "unavailable_reason": "",
            "full_portfolio_status": None,
            "oof_portfolio_status": None,
            "gross_r": None,
            "cost_r": None,
            "net_r": None,
            "net_r_cost_1p5x": None,
            "net_r_cost_2x": None,
            "normalized_pnl_usd": None,
            "whole_ounce_pnl_usd": None,
            "target_r": None,
        }
        if raw["stop_status"] != "AVAILABLE":
            row["economic_status"] = "UNAVAILABLE"
            row["unavailable_reason"] = str(raw["unavailable_reason"])
        elif not bool(raw["one_ounce_feasible"]):
            row["economic_status"] = "UNAVAILABLE"
            row["unavailable_reason"] = "MINIMUM_SIZE_EXCEEDS_RISK"
        else:
            row.update(
                economic_values(
                    int(row["entry_e8"]),
                    int(row["stop_e8"]),
                    int(row["target_e8"]),
                    int(row["exit_e8"]),
                    str(row["trade_direction"]),
                    float(row["total_cost_usd_oz"]),
                    int(row["planned_ounces"]),
                )
            )
            row["holding_minutes"] = int(
                (stage1.parse_ns(str(row["exit_at_utc"])) - stage1.parse_ns(str(row["entry_at_utc"])))
                / stage1.MINUTE_NS
            )
        grouped[candidate_id].append(row)
    output: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        values = grouped[candidate_id]
        if not values:
            raise ValueError(f"No Stage-1 rows for {candidate_id}")
        apply_overlap(values, "full_portfolio_status", False)
        apply_overlap(values, "oof_portfolio_status", True)
        output.extend(values)
    output.sort(
        key=lambda row: (
            TF_PRIORITY[str(row["timeframe"])],
            str(row["model_id"]),
            str(row["stop_id"]),
            str(row["entry_at_utc"]),
            str(row["trade_id"]),
        )
    )
    return output


def neighbour_economic_rows(
    side: str,
    implementation: str,
    candidate_ids: Sequence[str],
    prices: stage1.anatomy_impl.PriceData,
    models: Mapping[str, Mapping[str, Any]],
) -> list[dict[str, Any]]:
    trades, facts, swings = stage1.load_inputs(side)
    trade_groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for trade in trades:
        trade_groups[(str(trade["timeframe"]), str(trade["model_id"]))].append(trade)
    scanner = stage1.scan_primary if implementation == "primary" else stage1.scan_reference
    output: list[dict[str, Any]] = []
    for candidate_id in candidate_ids:
        timeframe, model_id, _ = candidate_parts(candidate_id)
        for spec in neighbour_registry(candidate_id, models):
            values: list[dict[str, Any]] = []
            for trade in trade_groups[(timeframe, model_id)]:
                fact = facts[str(trade["pullback_id"])]
                stop, level_id, unavailable = buffered_stop(
                    trade, fact, swings, str(spec["family"]), float(spec["buffer_atr"])
                )
                known_date = str(trade["known_at_utc"])[:10]
                fold = stage1.oof_fold(known_date)
                row = {
                    "candidate_id": candidate_id,
                    "neighbour_id": str(spec["neighbour_id"]),
                    "buffer_atr": float(spec["buffer_atr"]),
                    "trade_id": str(trade["trade_id"]),
                    "pullback_id": str(trade["pullback_id"]),
                    "timeframe": timeframe,
                    "model_id": model_id,
                    "archetype": str(trade["archetype"]),
                    "trade_direction": str(trade["trade_direction"]),
                    "session_state": str(trade["session_state"]),
                    "known_at_utc": str(trade["known_at_utc"]),
                    "entry_at_utc": str(trade["entry_at_utc"]),
                    "exit_at_utc": None,
                    "cluster_date": str(trade["cluster_date"]),
                    "iso_week": stage1.iso_week(str(trade["cluster_date"])),
                    "calendar_year": int(trade["calendar_year"]),
                    "oof_fold": fold,
                    "is_oof_validation": fold is not None,
                    "stop_level_id": level_id,
                    "entry_e8": int(trade["entry_e8"]),
                    "stop_e8": stop,
                    "target_e8": int(trade["target_e8"]),
                    "exit_e8": None,
                    "exit_reason": None,
                    "total_cost_usd_oz": None,
                    "planned_ounces": None,
                    "stop_distance_usd_oz": None,
                    "stop_distance_atr": None,
                    "holding_minutes": None,
                    "economic_status": "UNAVAILABLE" if unavailable else "EXECUTABLE",
                    "unavailable_reason": unavailable or "",
                    "full_portfolio_status": None,
                    "oof_portfolio_status": None,
                    "gross_r": None,
                    "cost_r": None,
                    "net_r": None,
                    "net_r_cost_1p5x": None,
                    "net_r_cost_2x": None,
                    "normalized_pnl_usd": None,
                    "whole_ounce_pnl_usd": None,
                    "target_r": None,
                }
                if unavailable is not None or stop is None:
                    values.append(row)
                    continue
                entry_index, end_index, _ = stage1.path_bounds(
                    trade, prices, int(models[model_id]["time_exit_parent_bars"]), implementation
                )
                entry = int(trade["entry_e8"])
                target = int(trade["target_e8"])
                sign = 1 if str(trade["trade_direction"]) == "UP" else -1
                result = scanner(prices, entry_index, end_index, entry, stop, target, sign)
                baseline_risk = abs(entry - int(trade["stop_e8"])) / SCALE
                total_cost = round(float(trade["cost_r"]) * baseline_risk, 8)
                risk_usd = abs(entry - stop) / SCALE
                ounces = math.floor((50.0 / (risk_usd + total_cost)) + 1e-12)
                exit_index = entry_index + int(result["exit_offset"])
                row.update(
                    {
                        "exit_at_utc": stage1.ns_iso(int(prices.open_ns[exit_index]) + stage1.MINUTE_NS),
                        "exit_e8": int(result["exit_e8"]),
                        "exit_reason": str(result["exit_reason"]),
                        "total_cost_usd_oz": rounded(total_cost),
                        "planned_ounces": ounces,
                        "stop_distance_usd_oz": rounded(risk_usd),
                        "stop_distance_atr": rounded(abs(entry - stop) / float(fact["atr14_e8"])),
                        "holding_minutes": int(result["exit_offset"]) + 1,
                    }
                )
                if ounces < 1:
                    row["economic_status"] = "UNAVAILABLE"
                    row["unavailable_reason"] = "MINIMUM_SIZE_EXCEEDS_RISK"
                else:
                    row.update(
                        economic_values(entry, stop, target, int(result["exit_e8"]), str(trade["trade_direction"]), total_cost, ounces)
                    )
                values.append(row)
            apply_overlap(values, "full_portfolio_status", False)
            apply_overlap(values, "oof_portfolio_status", True)
            output.extend(values)
    output.sort(
        key=lambda row: (
            TF_PRIORITY[str(row["timeframe"])],
            str(row["model_id"]),
            str(row["candidate_id"]),
            str(row["neighbour_id"]),
            str(row["entry_at_utc"]),
            str(row["trade_id"]),
        )
    )
    return output


def profit_factor(values: Sequence[float]) -> float | str | None:
    positive = sum(value for value in values if value > 0)
    negative = abs(sum(value for value in values if value < 0))
    if negative == 0:
        return "INF" if positive > 0 else None
    return rounded(positive / negative)


def max_drawdown(values: Sequence[float]) -> float:
    cumulative = peak = drawdown = 0.0
    for value in values:
        cumulative += float(value)
        peak = max(peak, cumulative)
        drawdown = max(drawdown, peak - cumulative)
    return rounded(drawdown) or 0.0


def performance(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row["entry_at_utc"]), str(row["trade_id"])))
    net = [float(row["net_r"]) for row in ordered]
    gross = [float(row["gross_r"]) for row in ordered]
    stress15 = [float(row["net_r_cost_1p5x"]) for row in ordered]
    stress20 = [float(row["net_r_cost_2x"]) for row in ordered]
    whole = [float(row["whole_ounce_pnl_usd"]) for row in ordered]
    winners = [value for value in net if value > 0]
    losers = [value for value in net if value < 0]
    return {
        "trades": len(ordered),
        "trading_dates": len({str(row["cluster_date"]) for row in ordered}),
        "iso_weeks": len({str(row["iso_week"]) for row in ordered}),
        "wins": len(winners),
        "losses": len(losers),
        "zero_net": len(net) - len(winners) - len(losers),
        "win_rate": rounded(len(winners) / len(net)) if net else None,
        "average_win_r": rounded(statistics.fmean(winners)) if winners else None,
        "average_loss_r": rounded(statistics.fmean(losers)) if losers else None,
        "gross_expectancy_r": rounded(statistics.fmean(gross)) if gross else None,
        "net_expectancy_r": rounded(statistics.fmean(net)) if net else None,
        "net_expectancy_r_cost_1p5x": rounded(statistics.fmean(stress15)) if stress15 else None,
        "net_expectancy_r_cost_2x": rounded(statistics.fmean(stress20)) if stress20 else None,
        "profit_factor": profit_factor(net),
        "total_net_r": rounded(sum(net)),
        "normalized_pnl_usd": rounded(sum(float(row["normalized_pnl_usd"]) for row in ordered)),
        "whole_ounce_pnl_usd": rounded(sum(whole)),
        "max_drawdown_r": max_drawdown(net),
        "normalized_max_drawdown_usd": rounded(50.0 * max_drawdown(net)),
        "whole_ounce_max_drawdown_usd": max_drawdown(whole),
        "stop_exit_rate": rounded(sum(row["exit_reason"] == "STOP" for row in ordered) / len(ordered)) if ordered else None,
        "stop_hit_full_horizon_rate": rounded(sum(bool(row["stop_hit_full_horizon"]) for row in ordered) / len(ordered)) if ordered and "stop_hit_full_horizon" in ordered[0] else None,
        "stop_before_global_mfe_rate": rounded(sum(bool(row["stop_before_or_same_as_global_mfe"]) for row in ordered) / len(ordered)) if ordered and "stop_before_or_same_as_global_mfe" in ordered[0] else None,
        "mfe_r_mean": rounded(statistics.fmean(float(row["exit_mfe_r"]) for row in ordered)) if ordered and "exit_mfe_r" in ordered[0] else None,
        "mae_r_mean": rounded(statistics.fmean(float(row["exit_mae_r"]) for row in ordered)) if ordered and "exit_mae_r" in ordered[0] else None,
        "holding_minutes_mean": rounded(statistics.fmean(float(row["holding_minutes"]) for row in ordered)) if ordered else None,
    }


def simple_group_metrics(rows: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[field])].append(row)
    output = []
    for key in sorted(grouped):
        values = grouped[key]
        net = [float(row["net_r"]) for row in values]
        output.append(
            {
                field: key,
                "trades": len(values),
                "dates": len({str(row["cluster_date"]) for row in values}),
                "net_expectancy_r": rounded(statistics.fmean(net)),
                "total_net_r": rounded(sum(net)),
                "profit_factor": profit_factor(net),
                "normalized_pnl_usd": rounded(50.0 * sum(net)),
                "whole_ounce_pnl_usd": rounded(sum(float(row["whole_ounce_pnl_usd"]) for row in values)),
            }
        )
    return output


def clustered_bootstrap(rows: Sequence[Mapping[str, Any]], candidate_id: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row["cluster_date"])].append(float(row["net_r"]))
    dates = sorted(grouped)
    if len(dates) < 2:
        return {"seed": None, "clusters": len(dates), "ci95_low": None, "ci95_high": None, "p_one_sided": None}
    sums = np.asarray([sum(grouped[day]) for day in dates], dtype=np.float64)
    counts = np.asarray([len(grouped[day]) for day in dates], dtype=np.float64)
    seed = (BASE_SEED + int(hashlib.sha256(candidate_id.encode("utf-8")).hexdigest()[:8], 16)) % (2**31 - 1)
    rng = np.random.default_rng(seed)
    samples: list[float] = []
    for left in range(0, BOOTSTRAPS, 250):
        indices = rng.integers(0, len(dates), size=(min(250, BOOTSTRAPS - left), len(dates)))
        values = sums[indices].sum(axis=1) / counts[indices].sum(axis=1)
        samples.extend(values.tolist())
    array = np.asarray(samples, dtype=np.float64)
    return {
        "seed": seed,
        "clusters": len(dates),
        "ci95_low": rounded(float(np.quantile(array, 0.025, method="linear"))),
        "ci95_high": rounded(float(np.quantile(array, 0.975, method="linear"))),
        "p_one_sided": rounded((1 + int(np.sum(array <= 0))) / (BOOTSTRAPS + 1)),
    }


def positive_share(rows: Sequence[Mapping[str, Any]], field: str) -> tuple[int, float | None]:
    grouped: dict[str, float] = defaultdict(float)
    for row in rows:
        grouped[str(row[field])] += float(row["net_r"])
    positives = [value for value in grouped.values() if value > 0]
    return len(positives), rounded(max(positives) / sum(positives)) if positives else None


def bh_adjust(rows: list[dict[str, Any]]) -> None:
    by_tf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_tf[str(row["timeframe"])].append(row)
    for values in by_tf.values():
        ordered = sorted(values, key=lambda row: (float(row["bootstrap"]["p_one_sided"] or 1.0), str(row["candidate_id"])))
        count = len(ordered)
        running = 1.0
        for rank in range(count, 0, -1):
            row = ordered[rank - 1]
            p_value = float(row["bootstrap"]["p_one_sided"] or 1.0)
            running = min(running, p_value * count / rank)
            row["bh_q"] = rounded(min(1.0, running))


def summarize(
    economic_rows: Sequence[Mapping[str, Any]],
    neighbour_rows: Sequence[Mapping[str, Any]],
    freeze: Mapping[str, Any],
    protocol: Mapping[str, Any],
) -> dict[str, Any]:
    base_groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in economic_rows:
        base_groups[str(row["candidate_id"])].append(row)
    neighbour_groups: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in neighbour_rows:
        neighbour_groups[(str(row["candidate_id"]), str(row["neighbour_id"]))].append(row)
    neighbour_summaries: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for (candidate_id, neighbour_id), values in sorted(neighbour_groups.items()):
        full = [row for row in values if row["full_portfolio_status"] == "ACCEPTED"]
        oof = [row for row in values if row["oof_portfolio_status"] == "ACCEPTED"]
        neighbour_summaries[candidate_id].append(
            {
                "neighbour_id": neighbour_id,
                "buffer_atr": float(values[0]["buffer_atr"]),
                "formation_rows": len(values),
                "unavailable_rows": sum(row["economic_status"] != "EXECUTABLE" for row in values),
                "full_development": performance(full),
                "oof_validation_union": performance(oof),
            }
        )

    results: list[dict[str, Any]] = []
    baseline_set = set(freeze["baseline_control_ids"])
    alternatives = set(freeze["stage1_eligible_alternative_ids"])
    for candidate_id in freeze["evaluated_candidate_ids"]:
        values = base_groups[candidate_id]
        full = [row for row in values if row["full_portfolio_status"] == "ACCEPTED"]
        oof = [row for row in values if row["oof_portfolio_status"] == "ACCEPTED"]
        timeframe, model_id, stop_id = candidate_parts(candidate_id)
        folds = simple_group_metrics(oof, "oof_fold")
        years = simple_group_metrics(oof, "calendar_year")
        sessions = simple_group_metrics(oof, "session_state")
        positive_folds = sum(float(row["net_expectancy_r"]) > 0 for row in folds)
        positive_years, max_year_share = positive_share(oof, "calendar_year")
        positive_sessions, max_session_share = positive_share(oof, "session_state")
        result = {
            "candidate_id": candidate_id,
            "timeframe": timeframe,
            "model_id": model_id,
            "stop_id": stop_id,
            "control": candidate_id in baseline_set,
            "stage1_eligible": candidate_id in alternatives,
            "formation_rows": len(values),
            "unavailable_rows": sum(row["economic_status"] != "EXECUTABLE" for row in values),
            "full_development": performance(full),
            "oof_validation_union": performance(oof),
            "fold_results": folds,
            "annual_results": years,
            "session_results": sessions,
            "positive_validation_folds": positive_folds,
            "positive_calendar_years": positive_years,
            "maximum_positive_year_share": max_year_share,
            "positive_sessions": positive_sessions,
            "maximum_positive_session_share": max_session_share,
            "bootstrap": clustered_bootstrap(oof, candidate_id),
            "bh_q": None,
            "parameter_neighbours": neighbour_summaries[candidate_id],
            "economic_checks": {},
            "failed_gates": [],
            "disposition": None,
            "economic_pass": False,
        }
        results.append(result)
    bh_adjust(results)

    floors = protocol["support_floors"]
    gates = protocol["economic_gates"]
    for row in results:
        tf = str(row["timeframe"])
        metrics = row["oof_validation_union"]
        pf = metrics["profit_factor"]
        pf_value = float("inf") if pf == "INF" else float(pf) if pf is not None else float("-inf")
        neighbours = row["parameter_neighbours"]
        neighbour_positive = len(neighbours) == 2 and all(
            item["oof_validation_union"]["net_expectancy_r"] is not None
            and float(item["oof_validation_union"]["net_expectancy_r"]) > 0
            for item in neighbours
        )
        checks = {
            "stage1_survival": bool(row["stage1_eligible"]),
            "trade_support": int(metrics["trades"]) >= int(floors[tf]["trades"]),
            "date_support": int(metrics["trading_dates"]) >= int(floors[tf]["dates"]),
            "week_support": int(metrics["iso_weeks"]) >= int(floors[tf]["weeks"]),
            "positive_net_expectancy": metrics["net_expectancy_r"] is not None and float(metrics["net_expectancy_r"]) > float(gates["net_expectancy_gt"]),
            "profit_factor": pf_value >= float(gates["profit_factor_gte"]),
            "positive_cluster_ci95_low": row["bootstrap"]["ci95_low"] is not None and float(row["bootstrap"]["ci95_low"]) > float(gates["cluster_ci95_low_gt"]),
            "bh_q": row["bh_q"] is not None and float(row["bh_q"]) <= float(gates["bh_q_lte"]),
            "positive_cost_1p5x": metrics["net_expectancy_r_cost_1p5x"] is not None and float(metrics["net_expectancy_r_cost_1p5x"]) > float(gates["cost_1p5x_expectancy_gt"]),
            "positive_validation_folds": int(row["positive_validation_folds"]) >= int(gates["positive_validation_folds_gte"]),
            "positive_calendar_years": int(row["positive_calendar_years"]) >= int(gates["positive_calendar_years_gte"]),
            "maximum_positive_year_share": row["maximum_positive_year_share"] is not None and float(row["maximum_positive_year_share"]) <= float(gates["maximum_positive_year_share_lte"]),
            "positive_sessions": int(row["positive_sessions"]) >= int(gates["positive_sessions_gte"]),
            "maximum_positive_session_share": row["maximum_positive_session_share"] is not None and float(row["maximum_positive_session_share"]) <= float(gates["maximum_positive_session_share_lte"]),
            "both_parameter_neighbours_positive": neighbour_positive,
        }
        row["economic_checks"] = checks
        if row["control"]:
            row["failed_gates"] = ["BASELINE_CONTROL_NO_CANDIDATE_CREDIT", *[name for name, passed in checks.items() if name != "stage1_survival" and not passed]]
            row["disposition"] = "CONTROL_ONLY"
        else:
            row["failed_gates"] = [name for name, passed in checks.items() if not passed]
            row["economic_pass"] = all(checks.values())
            row["disposition"] = "PASS_ECONOMIC" if row["economic_pass"] else "REJECT_ECONOMIC"

    passing = [row for row in results if row["economic_pass"]]
    passing.sort(
        key=lambda row: (
            TF_PRIORITY[str(row["timeframe"])],
            -float(row["bootstrap"]["ci95_low"]),
            -float(row["oof_validation_union"]["net_expectancy_r_cost_1p5x"]),
            -(float("inf") if row["oof_validation_union"]["profit_factor"] == "INF" else float(row["oof_validation_union"]["profit_factor"])),
            -int(row["oof_validation_union"]["trades"]),
            float(row["oof_validation_union"]["max_drawdown_r"]),
            str(row["candidate_id"]),
        )
    )
    shortlist: list[str] = []
    counts: Counter[str] = Counter()
    for row in passing:
        tf = str(row["timeframe"])
        if counts[tf] < int(protocol["maximum_candidates_per_timeframe"]):
            shortlist.append(str(row["candidate_id"]))
            counts[tf] += 1

    archetype_matrix: list[dict[str, Any]] = []
    for candidate_id in freeze["evaluated_candidate_ids"]:
        values = base_groups[candidate_id]
        archetypes = sorted({str(row["archetype"]) for row in values})
        for archetype in archetypes:
            subset = [
                row
                for row in values
                if str(row["archetype"]) == archetype and row["oof_portfolio_status"] == "ACCEPTED"
            ]
            timeframe, model_id, stop_id = candidate_parts(candidate_id)
            archetype_matrix.append(
                {
                    "candidate_id": candidate_id,
                    "timeframe": timeframe,
                    "model_id": model_id,
                    "stop_id": stop_id,
                    "realised_archetype": archetype,
                    "accepted_oof": performance(subset),
                }
            )
    return {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_STAGE2_RESULT_1_0",
        "status": "PASS_DEVELOPMENT_CANDIDATES_FROZEN_FORWARD_REQUIRED" if shortlist else "REJECT_NO_DEVELOPMENT_ECONOMIC_STOP_CANDIDATE",
        "evaluated_tests": len(results),
        "baseline_controls": len(baseline_set),
        "stage1_eligible_alternatives": len(alternatives),
        "economic_pass_count": len(passing),
        "shortlist": shortlist,
        "candidate_results": results,
        "timeframe_model_stop_archetype_matrix": archetype_matrix,
        "stage1_rejected_alternatives": 19,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }


def report_text(summary: Mapping[str, Any]) -> str:
    candidates = summary["candidate_results"]
    alternatives = [row for row in candidates if not row["control"]]
    near = sorted(
        alternatives,
        key=lambda row: (
            -(float(row["oof_validation_union"]["net_expectancy_r"]) if row["oof_validation_union"]["net_expectancy_r"] is not None else -999),
            str(row["candidate_id"]),
        ),
    )[:12]
    lines = [
        "# Gold Structural Stop Geometry Economic Research V1 — Development",
        "",
        f"Status: **{summary['status']}**",
        "",
        "## Verdict",
        "",
        f"- Economically evaluated tests: **{summary['evaluated_tests']}** (18 controls + 35 Stage-1 alternatives).",
        f"- Alternatives passing every frozen economic gate: **{summary['economic_pass_count']}**.",
        f"- Frozen shortlist: **{len(summary['shortlist'])}**.",
        "- 2025 and 2026 remained locked during development evaluation.",
        "- No data was acquired; charge: $0.00.",
        "",
        "## Strongest alternatives by out-of-fold net expectancy",
        "",
        "| Candidate | Trades | Exp R | PF | CI95 low | 1.5x-cost Exp R | DD R | Verdict | Failed gates |",
        "|---|---:|---:|---:|---:|---:|---:|---|---|",
    ]
    for row in near:
        metric = row["oof_validation_union"]
        lines.append(
            f"| {row['candidate_id']} | {metric['trades']:,} | {float(metric['net_expectancy_r']):.4f} | "
            f"{metric['profit_factor']} | {row['bootstrap']['ci95_low']} | {float(metric['net_expectancy_r_cost_1p5x']):.4f} | "
            f"{float(metric['max_drawdown_r']):.2f} | {row['disposition']} | {', '.join(row['failed_gates']) or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Forward disposition",
            "",
            "The forward years may be opened only for the frozen shortlist above. If the shortlist is empty, the contract requires stopping without inspecting 2025/2026 values.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if OUTPUT.exists() or DEVELOPMENT_REPORT.exists() or FINAL_REPORT.exists():
        raise FileExistsError("Stage-2 output already exists")
    protocol, freeze, stage1_seal = verify_freeze()
    models = model_registry()
    candidate_ids = list(freeze["evaluated_candidate_ids"])
    OUTPUT.mkdir(parents=True)
    prices = stage1.anatomy_impl.load_price()
    if prices.diagnostics["last_m1_open"] >= "2025-01-01T00:00:00Z":
        raise ValueError("Forward value exposed by development price loader")

    primary_economic = base_economic_rows("primary", candidate_ids)
    primary_neighbours = neighbour_economic_rows("primary", "primary", candidate_ids, prices, models)
    primary_summary = summarize(primary_economic, primary_neighbours, freeze, protocol)
    primary_economic_path = OUTPUT / "primary_economic_rows.parquet"
    primary_neighbour_path = OUTPUT / "primary_neighbour_rows.parquet"
    primary_summary_path = OUTPUT / "primary_development_summary.json"
    write_parquet_exclusive(primary_economic_path, primary_economic)
    write_parquet_exclusive(primary_neighbour_path, primary_neighbours)
    write_json_exclusive(primary_summary_path, primary_summary)
    del primary_economic, primary_neighbours

    reference_economic = base_economic_rows("reference", candidate_ids)
    reference_neighbours = neighbour_economic_rows("reference", "reference", candidate_ids, prices, models)
    reference_summary = summarize(reference_economic, reference_neighbours, freeze, protocol)
    reference_economic_path = OUTPUT / "reference_economic_rows.parquet"
    reference_neighbour_path = OUTPUT / "reference_neighbour_rows.parquet"
    reference_summary_path = OUTPUT / "reference_development_summary.json"
    write_parquet_exclusive(reference_economic_path, reference_economic)
    write_parquet_exclusive(reference_neighbour_path, reference_neighbours)
    write_json_exclusive(reference_summary_path, reference_summary)
    del reference_economic, reference_neighbours

    checks = {
        "economic_rows_byte_identical": sha256_file(primary_economic_path) == sha256_file(reference_economic_path),
        "neighbour_rows_byte_identical": sha256_file(primary_neighbour_path) == sha256_file(reference_neighbour_path),
        "summary_byte_identical": sha256_file(primary_summary_path) == sha256_file(reference_summary_path),
    }
    if not all(checks.values()):
        raise ValueError(f"Independent Stage-2 reproduction failed: {checks}")

    report = report_text(primary_summary)
    write_text_exclusive(DEVELOPMENT_REPORT, report)
    shortlist_path = OUTPUT / "frozen_development_shortlist.json"
    shortlist = {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_FROZEN_DEVELOPMENT_SHORTLIST_1_0",
        "status": "FROZEN_FORWARD_APPLICATION_REQUIRED" if primary_summary["shortlist"] else "FROZEN_EMPTY_SHORTLIST",
        "frozen_at_utc": utc_now(),
        "candidate_ids": primary_summary["shortlist"],
        "development_result_hash": canonical_hash(primary_summary),
        "no_retuning_after_freeze": True,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
    }
    write_json_exclusive(shortlist_path, shortlist)
    development_seal_path = OUTPUT / "development_seal.json"
    development_seal = {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_DEVELOPMENT_SEAL_1_0",
        "status": primary_summary["status"],
        "sealed_at_utc": utc_now(),
        "predecessors": {
            "stage1_seal": record(STAGE1_SEAL),
            "stage2_freeze": record(STAGE2_FREEZE),
        },
        "artifacts": {
            "primary_economic_rows": record(primary_economic_path),
            "reference_economic_rows": record(reference_economic_path),
            "primary_neighbour_rows": record(primary_neighbour_path),
            "reference_neighbour_rows": record(reference_neighbour_path),
            "primary_summary": record(primary_summary_path),
            "reference_summary": record(reference_summary_path),
            "shortlist": record(shortlist_path),
            "development_report": record(DEVELOPMENT_REPORT),
        },
        "reproduction": checks,
        "result_hash": canonical_hash(primary_summary),
        "evaluated_tests": primary_summary["evaluated_tests"],
        "economic_pass_count": primary_summary["economic_pass_count"],
        "shortlist": primary_summary["shortlist"],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(development_seal_path, development_seal)

    if not primary_summary["shortlist"]:
        final = report.replace("— Development", "— Final").replace(
            "The forward years may be opened only for the frozen shortlist above. If the shortlist is empty, the contract requires stopping without inspecting 2025/2026 values.",
            "The shortlist is empty. In accordance with the frozen contract, 2025 and 2026 were not opened and this branch stops with a development rejection.",
        )
        write_text_exclusive(FINAL_REPORT, final)
        final_seal_path = OUTPUT / "final_seal.json"
        final_seal = {
            "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_FINAL_SEAL_1_0",
            "status": "REJECT_NO_DEVELOPMENT_ECONOMIC_STOP_CANDIDATE",
            "sealed_at_utc": utc_now(),
            "development_seal": record(development_seal_path),
            "final_report": record(FINAL_REPORT),
            "result_hash": canonical_hash(primary_summary),
            "calendar_2025_values_accessed": False,
            "calendar_2026_values_accessed": False,
            "prospective_ledger_initialized": False,
            "exit_research_recommended": False,
            "paid_acquisition_usd": 0.0,
        }
        write_json_exclusive(final_seal_path, final_seal)
    print(
        json.dumps(
            {
                "status": primary_summary["status"],
                "evaluated_tests": primary_summary["evaluated_tests"],
                "economic_pass_count": primary_summary["economic_pass_count"],
                "shortlist": primary_summary["shortlist"],
                "development_seal": record(development_seal_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
