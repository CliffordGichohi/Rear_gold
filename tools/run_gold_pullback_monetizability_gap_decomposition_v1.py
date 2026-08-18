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
from typing import Any, Iterable, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_pullback_monetizability_gap_decomposition_v1"
REPORT = ROOT / "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_V1_REPORT.md"
CONTRACT = ROOT / "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_pullback_monetizability_gap_decomposition_v1_protocol.json"
FREEZE = MANIFESTS / "gold_pullback_monetizability_gap_decomposition_v1_pre_result_freeze.json"
ATTEMPT_FAILURE = OUTPUT / "attempt_1_failure.json"
RECOVERY = MANIFESTS / "gold_pullback_monetizability_gap_decomposition_v1_recovery_a.json"

ATLAS_DIR = ARTIFACTS / "gold_pullback_behavioural_archetypes_v1"
ROUTING_DIR = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"

STAGES_FIXED = (
    "stage1_visual_pivot_oracle_r",
    "stage2_checkpoint_mfe_ceiling_r",
    "stage3_stop_feasible_mfe_ceiling_r",
    "stage4_frozen_exit_gross_r",
    "stage5_frozen_exit_net_r",
    "stage6_nonoverlap_fixed_risk_r",
)
STAGE7 = "stage7_router_50usd_equivalent_r"
STAGE_LABELS = {
    STAGES_FIXED[0]: "VISUAL_PIVOT_ORACLE",
    STAGES_FIXED[1]: "CHECKPOINT_MFE_CEILING",
    STAGES_FIXED[2]: "STOP_FEASIBLE_MFE_CEILING",
    STAGES_FIXED[3]: "FROZEN_EXIT_GROSS",
    STAGES_FIXED[4]: "FROZEN_EXIT_NET_COSTS",
    STAGES_FIXED[5]: "NON_OVERLAPPING_FIXED_RISK",
    STAGE7: "FROZEN_VARIABLE_RISK_ROUTER",
}
ACTIVE_FIELDS = {
    STAGES_FIXED[0]: "stage1_active",
    STAGES_FIXED[1]: "stage2_active",
    STAGES_FIXED[2]: "stage3_active",
    STAGES_FIXED[3]: "stage4_active",
    STAGES_FIXED[4]: "stage5_active",
    STAGES_FIXED[5]: "stage6_active",
    STAGE7: "stage7_active",
}
TF_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
MINUTE_NS = 60_000_000_000
SCALE = 100_000_000
MONTHS = 41


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
    output = round(float(value), 12)
    return 0.0 if output == 0 else output


def write_json_exclusive(path: Path, value: Any) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
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
    temporary = path.with_suffix(path.suffix + ".tmp")
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


def verify_freeze() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_AND_READY_FOR_DECOMPOSITION":
        raise ValueError("Decomposition freeze is invalid")
    if protocol["status"] != "FROZEN_BEFORE_DECOMPOSITION_RESULTS":
        raise ValueError("Protocol is not frozen")
    for item in [*freeze["controls"].values(), *freeze["predecessor_seals"].values(), freeze["development_price"]]:
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Frozen input changed: {item['path']}")
    for pair in freeze["source_pairs"].values():
        for side in ("primary", "reference"):
            item = pair[side]
            path = ROOT / item["path"]
            if not path.is_file() or record(path) != item:
                raise ValueError(f"Frozen source changed: {item['path']}")
        if pair["primary"]["sha256"] != pair["reference"]["sha256"]:
            raise ValueError("Frozen primary/reference source pair differs")
    if freeze["value_rows_accessed_before_freeze"]:
        raise ValueError("Freeze claims prior value access")
    if ATTEMPT_FAILURE.exists() or RECOVERY.exists():
        if not ATTEMPT_FAILURE.is_file() or not RECOVERY.is_file():
            raise ValueError("Incomplete recovery controls")
        failure = json.loads(ATTEMPT_FAILURE.read_text(encoding="utf-8"))
        recovery = json.loads(RECOVERY.read_text(encoding="utf-8"))
        if failure.get("status") != "FAIL_POST_REPLAY_AGGREGATION_NAMESPACE_COLLISION_NO_RESULT":
            raise ValueError("Preserved failed attempt is invalid")
        if recovery.get("status") != "FROZEN_BEFORE_RECOVERY_RERUN" or recovery.get("additional_complete_attempts_permitted") != 1:
            raise ValueError("Recovery amendment is invalid")
    return protocol, freeze


def load_rows(side: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    atlas = pq.read_table(ATLAS_DIR / f"{side}_archetypes.parquet").to_pylist()
    trades = pq.read_table(ROUTING_DIR / f"{side}_model_trades.parquet").to_pylist()
    predictions = pq.read_table(ROUTING_DIR / f"{side}_oof_predictions.parquet").to_pylist()
    equal = pq.read_table(ROUTING_DIR / f"{side}_equal_risk_oof_decisions.parquet").to_pylist()
    variable = pq.read_table(ROUTING_DIR / f"{side}_variable_risk_oof_decisions.parquet").to_pylist()
    if (len(atlas), len(trades), len(predictions), len(equal), len(variable)) != (8653, 51918, 16240, 16240, 497):
        raise ValueError(f"Frozen row population changed for {side}")
    for collection in (atlas, trades, predictions, equal, variable):
        for row in collection:
            for field in ("known_at_utc", "entry_at_utc", "exit_at_utc"):
                value = row.get(field)
                if value is not None and str(value) >= "2025-01-01T00:00:00Z":
                    raise ValueError(f"Forward timestamp encountered in {side}: {field}={value}")
    return atlas, trades, predictions, equal, variable


def first_true_primary(values: np.ndarray) -> int | None:
    found = np.flatnonzero(values)
    return int(found[0]) if len(found) else None


def path_values_primary(
    trade: Mapping[str, Any],
    prices: anatomy_impl.PriceData,
    time_bars: int,
) -> tuple[float, float, float, int, int | None, int]:
    entry_ns = int(datetime.fromisoformat(str(trade["entry_at_utc"]).replace("Z", "+00:00")).timestamp() * 1_000_000_000)
    entry_index = int(np.searchsorted(prices.open_ns, entry_ns, side="left"))
    if entry_index >= len(prices.open_ns) or int(prices.open_ns[entry_index]) != entry_ns:
        raise ValueError(f"Missing entry minute: {trade['trade_id']}")
    parent = prices.parents[str(trade["timeframe"])]
    first_parent = int(np.searchsorted(parent.close_ns, entry_ns, side="right"))
    deadline_parent = first_parent + time_bars - 1
    if deadline_parent >= len(parent.close_ns):
        raise ValueError(f"Missing parent deadline: {trade['trade_id']}")
    deadline_ns = int(parent.close_ns[deadline_parent])
    end_index = int(np.searchsorted(prices.open_ns, deadline_ns, side="left"))
    if end_index <= entry_index or int(prices.open_ns[end_index - 1]) + MINUTE_NS != deadline_ns:
        raise ValueError(f"Incomplete frozen path: {trade['trade_id']}")
    entry = int(trade["entry_e8"])
    stop = int(trade["stop_e8"])
    sign = 1 if str(trade["trade_direction"]) == "UP" else -1
    risk = abs(entry - stop)
    if risk <= 0:
        raise ValueError(f"Invalid structural risk: {trade['trade_id']}")
    highs = prices.high_e8[entry_index:end_index]
    lows = prices.low_e8[entry_index:end_index]
    opens = prices.open_e8[entry_index:end_index]
    favourable = highs - entry if sign > 0 else entry - lows
    adverse = entry - lows if sign > 0 else highs - entry
    maximum = max(0, int(np.max(favourable)))
    mfe_index = int(np.argmax(favourable)) if len(favourable) else 0
    stop_index = first_true_primary(lows <= stop if sign > 0 else highs >= stop)
    if stop_index is not None and stop_index <= mfe_index:
        stop_exit = min(stop, int(opens[stop_index])) if sign > 0 else max(stop, int(opens[stop_index]))
        stop_feasible = sign * (stop_exit - entry) / risk
    else:
        stop_feasible = maximum / risk
    return maximum / risk, max(0, int(np.max(adverse))) / risk, stop_feasible, end_index - entry_index, stop_index, mfe_index


def path_values_reference(
    trade: Mapping[str, Any],
    prices: anatomy_impl.PriceData,
    time_bars: int,
) -> tuple[float, float, float, int, int | None, int]:
    entry_ns = int(datetime.fromisoformat(str(trade["entry_at_utc"]).replace("Z", "+00:00")).timestamp() * 1_000_000_000)
    entry_index = 0
    left, right = 0, len(prices.open_ns)
    while left < right:
        middle = (left + right) // 2
        if int(prices.open_ns[middle]) < entry_ns:
            left = middle + 1
        else:
            right = middle
    entry_index = left
    if entry_index >= len(prices.open_ns) or int(prices.open_ns[entry_index]) != entry_ns:
        raise ValueError(f"Reference missing entry minute: {trade['trade_id']}")
    parent_closes = prices.parents[str(trade["timeframe"])].close_ns
    left, right = 0, len(parent_closes)
    while left < right:
        middle = (left + right) // 2
        if int(parent_closes[middle]) <= entry_ns:
            left = middle + 1
        else:
            right = middle
    first_parent = left
    deadline_parent = first_parent + time_bars - 1
    if deadline_parent >= len(parent_closes):
        raise ValueError(f"Reference missing parent deadline: {trade['trade_id']}")
    deadline_ns = int(parent_closes[deadline_parent])
    end_index = entry_index
    while end_index < len(prices.open_ns) and int(prices.open_ns[end_index]) < deadline_ns:
        end_index += 1
    if end_index <= entry_index or int(prices.open_ns[end_index - 1]) + MINUTE_NS != deadline_ns:
        raise ValueError(f"Reference incomplete path: {trade['trade_id']}")
    entry = int(trade["entry_e8"])
    stop = int(trade["stop_e8"])
    sign = 1 if str(trade["trade_direction"]) == "UP" else -1
    risk = abs(entry - stop)
    maximum = 0
    maximum_index = 0
    maximum_adverse = 0
    first_stop = None
    for offset, index in enumerate(range(entry_index, end_index)):
        favourable = int(prices.high_e8[index]) - entry if sign > 0 else entry - int(prices.low_e8[index])
        adverse = entry - int(prices.low_e8[index]) if sign > 0 else int(prices.high_e8[index]) - entry
        if favourable > maximum:
            maximum = favourable
            maximum_index = offset
        maximum_adverse = max(maximum_adverse, adverse)
        hit = int(prices.low_e8[index]) <= stop if sign > 0 else int(prices.high_e8[index]) >= stop
        if first_stop is None and hit:
            first_stop = offset
    if first_stop is not None and first_stop <= maximum_index:
        open_price = int(prices.open_e8[entry_index + first_stop])
        stop_exit = min(stop, open_price) if sign > 0 else max(stop, open_price)
        stop_feasible = sign * (stop_exit - entry) / risk
    else:
        stop_feasible = maximum / risk
    return maximum / risk, max(0, maximum_adverse) / risk, stop_feasible, end_index - entry_index, first_stop, maximum_index


def route_statuses(candidates: Sequence[Mapping[str, Any]], variable: bool) -> dict[str, str]:
    if variable:
        ordered = sorted(
            candidates,
            key=lambda row: (
                str(row["entry_at_utc"]),
                -float(row["conservative_score_r"]),
                int(row["model_rank"]),
                TF_PRIORITY[str(row["timeframe"])],
                str(row["pullback_id"]),
            ),
        )
    else:
        ordered = sorted(
            candidates,
            key=lambda row: (
                str(row["entry_at_utc"]),
                int(row["model_rank"]),
                TF_PRIORITY[str(row["timeframe"])],
                str(row["pullback_id"]),
            ),
        )
    output: dict[str, str] = {}
    open_until: str | None = None
    current_timestamp: str | None = None
    timestamp_winner = False
    for row in ordered:
        entry_at = str(row["entry_at_utc"])
        if entry_at != current_timestamp:
            current_timestamp = entry_at
            timestamp_winner = False
        if open_until is not None and entry_at < open_until:
            status = "SKIPPED_OVERLAPPING_POSITION"
        elif timestamp_winner:
            status = "SKIPPED_SAME_TIMESTAMP_LOWER_PRIORITY"
        else:
            status = "ACCEPTED"
            timestamp_winner = True
            open_until = str(row["exit_at_utc"])
        output[str(row["trade_id"])] = status
    return output


def variable_candidate(prediction: Mapping[str, Any], trade: Mapping[str, Any], eligible: Mapping[str, bool]) -> dict[str, Any] | None:
    key = f"{prediction['timeframe']}|{prediction['model_id']}"
    risk_usd = float(prediction["assigned_risk_usd"])
    if not eligible.get(key, False) or risk_usd <= 0:
        return None
    entry = int(trade["entry_e8"])
    stop = int(trade["stop_e8"])
    risk_per_ounce = abs(entry - stop) / SCALE
    cost_per_ounce = float(trade["cost_r"]) * risk_per_ounce
    ounces = math.floor((risk_usd / (risk_per_ounce + cost_per_ounce)) + 1e-12)
    if ounces < 1:
        return None
    output = dict(trade)
    output.update({
        "conservative_score_r": float(prediction["conservative_score_r"]),
        "assigned_risk_usd": risk_usd,
    })
    return output


def materialize(side: str, implementation: str, protocol: Mapping[str, Any], prices: anatomy_impl.PriceData) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    atlas, trades, predictions, equal_decisions, variable_decisions = load_rows(side)
    atlas_map = {str(row["pullback_id"]): row for row in atlas}
    time_bars = {str(row["model_id"]): int(row["time_exit_parent_bars"]) for row in protocol["models"]}
    trade_map = {str(row["trade_id"]): row for row in trades}
    if len(trade_map) != len(trades):
        raise ValueError("Duplicate model-trade identity")

    executed = [row for row in trades if row["status"] == "EXECUTED"]
    full_statuses = route_statuses(executed, False)
    output: list[dict[str, Any]] = []
    scanner = path_values_primary if implementation == "primary" else path_values_reference
    for trade in trades:
        atlas_row = atlas_map[str(trade["pullback_id"])]
        archetype = str(atlas_row["archetype"]) if bool(atlas_row["technical_available"]) else "UNAVAILABLE_TECHNICAL"
        oracle_raw = atlas_row.get("oracle_r")
        oracle = float(oracle_raw) if oracle_raw is not None and math.isfinite(float(oracle_raw)) else None
        is_executed = trade["status"] == "EXECUTED"
        row = {
            "trade_id": str(trade["trade_id"]),
            "pullback_id": str(trade["pullback_id"]),
            "timeframe": str(trade["timeframe"]),
            "model_id": str(trade["model_id"]),
            "archetype": archetype,
            "technical_available": bool(atlas_row["technical_available"]),
            "known_at_utc": str(trade["known_at_utc"]),
            "cluster_date": str(trade["cluster_date"]),
            "entry_at_utc": trade.get("entry_at_utc"),
            "exit_at_utc": trade.get("exit_at_utc"),
            "trade_status": str(trade["status"]),
            "no_trade_reason": str(trade.get("no_trade_reason") or ""),
            "stage1_visual_pivot_oracle_r": rounded(oracle),
            "stage1_active": oracle is not None,
            "stage2_checkpoint_mfe_ceiling_r": 0.0,
            "stage2_active": is_executed,
            "stage3_stop_feasible_mfe_ceiling_r": 0.0,
            "stage3_active": is_executed,
            "stage4_frozen_exit_gross_r": rounded(float(trade["gross_r"])) if is_executed else 0.0,
            "stage4_active": is_executed,
            "stage5_frozen_exit_net_r": rounded(float(trade["net_r"])) if is_executed else 0.0,
            "stage5_active": is_executed,
            "stage5_cost_1p5x_r": rounded(float(trade["net_r_cost_1p5x"])) if is_executed else 0.0,
            "stage5_cost_2x_r": rounded(float(trade["net_r_cost_2x"])) if is_executed else 0.0,
            "stage6_nonoverlap_fixed_risk_r": 0.0,
            "stage6_active": False,
            "stage6_portfolio_status": full_statuses.get(str(trade["trade_id"]), "NO_TRADE"),
            "stage6_oof_fixed_risk_r": None,
            "stage6_oof_active": False,
            "stage7_router_50usd_equivalent_r": None,
            "stage7_actual_pnl_usd": None,
            "stage7_assigned_risk_usd": None,
            "stage7_active": False,
            "stage7_portfolio_status": "NOT_IN_OOF_ROUTER_POPULATION",
            "checkpoint_path_mfe_r": None,
            "checkpoint_path_mae_r": None,
            "checkpoint_path_minutes": None,
            "stop_first_or_same_as_global_mfe": None,
            "entry_model_mfe_until_actual_exit_r": rounded(float(trade["mfe_r"])) if is_executed else None,
            "entry_model_mae_until_actual_exit_r": rounded(float(trade["mae_r"])) if is_executed else None,
            "frozen_cost_r": rounded(float(trade["cost_r"])) if is_executed else None,
            "frozen_whole_ounce_net_pnl_usd": rounded(float(trade["net_pnl_usd"])) if is_executed else None,
            "model_rank": int(trade["model_rank"]),
        }
        if is_executed:
            mfe, mae, stop_feasible, path_minutes, stop_index, mfe_index = scanner(trade, prices, time_bars[str(trade["model_id"])])
            row["stage2_checkpoint_mfe_ceiling_r"] = rounded(mfe)
            row["stage3_stop_feasible_mfe_ceiling_r"] = rounded(stop_feasible)
            row["checkpoint_path_mfe_r"] = rounded(mfe)
            row["checkpoint_path_mae_r"] = rounded(mae)
            row["checkpoint_path_minutes"] = path_minutes
            row["stop_first_or_same_as_global_mfe"] = stop_index is not None and stop_index <= mfe_index
            if full_statuses[str(trade["trade_id"])] == "ACCEPTED":
                row["stage6_nonoverlap_fixed_risk_r"] = row["stage5_frozen_exit_net_r"]
                row["stage6_active"] = True
        output.append(row)

    output_map = {str(row["trade_id"]): row for row in output}
    prediction_map = {str(row["trade_id"]): row for row in predictions}
    equal_expected = {str(row["trade_id"]): str(row["portfolio_status"]) for row in equal_decisions}
    equal_candidates = [trade_map[identity] for identity in prediction_map]
    equal_observed = route_statuses(equal_candidates, False)
    if equal_observed != equal_expected:
        raise ValueError(f"{side} OOF equal-risk overlap reproduction differs")
    for identity, status in equal_expected.items():
        row = output_map[identity]
        row["stage6_oof_fixed_risk_r"] = row["stage5_frozen_exit_net_r"] if status == "ACCEPTED" else 0.0
        row["stage6_oof_active"] = status == "ACCEPTED"

    frozen_system = json.loads((ROUTING_DIR / "frozen_system_pre_forward.json").read_text(encoding="utf-8"))
    eligible = {f"{row['timeframe']}|{row['model_id']}": bool(row["calibration_eligible"]) for row in frozen_system["models"]}
    variable_candidates = []
    for identity, prediction in prediction_map.items():
        candidate = variable_candidate(prediction, trade_map[identity], eligible)
        if candidate is not None:
            variable_candidates.append(candidate)
    variable_observed = route_statuses(variable_candidates, True)
    variable_expected = {str(row["trade_id"]): str(row["portfolio_status"]) for row in variable_decisions}
    if variable_observed != variable_expected:
        raise ValueError(f"{side} variable-router overlap reproduction differs")
    variable_map = {str(row["trade_id"]): row for row in variable_decisions}
    for identity in prediction_map:
        row = output_map[identity]
        row["stage7_router_50usd_equivalent_r"] = 0.0
        row["stage7_actual_pnl_usd"] = 0.0
        row["stage7_assigned_risk_usd"] = 0.0
        row["stage7_portfolio_status"] = variable_expected.get(identity, "ROUTER_NO_TRADE")
        decision = variable_map.get(identity)
        if decision is not None and decision["portfolio_status"] == "ACCEPTED":
            pnl = float(decision["net_pnl_usd"])
            row["stage7_router_50usd_equivalent_r"] = rounded(pnl / 50.0)
            row["stage7_actual_pnl_usd"] = rounded(pnl)
            row["stage7_assigned_risk_usd"] = float(decision["planned_risk_usd"])
            row["stage7_active"] = True

    output.sort(key=lambda row: (row["known_at_utc"], TF_PRIORITY[row["timeframe"]], row["model_rank"], row["pullback_id"]))
    diagnostics = {
        "model_case_rows": len(output),
        "executed_rows": len(executed),
        "no_trade_rows": len(output) - len(executed),
        "technical_available_model_rows": sum(row["technical_available"] for row in output),
        "technical_unavailable_model_rows": sum(not row["technical_available"] for row in output),
        "full_nonoverlap_accepted": sum(row["stage6_active"] for row in output),
        "oof_rows": len(predictions),
        "oof_equal_risk_accepted": sum(row["stage6_oof_active"] for row in output),
        "oof_variable_candidates": len(variable_candidates),
        "oof_variable_accepted": sum(row["stage7_active"] for row in output),
        "no_trade_reasons": dict(sorted(Counter(row["no_trade_reason"] for row in output if row["trade_status"] != "EXECUTED").items())),
        "full_overlap_status": dict(sorted(Counter(row["stage6_portfolio_status"] for row in output if row["trade_status"] == "EXECUTED").items())),
        "oof_router_status": dict(sorted(Counter(row["stage7_portfolio_status"] for row in output if row[STAGE7] is not None).items())),
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
    }
    return output, diagnostics


def profit_factor(values: Sequence[float]) -> float | str | None:
    positive = sum(value for value in values if value > 0)
    negative = abs(sum(value for value in values if value < 0))
    if negative == 0:
        return "INF" if positive > 0 else None
    return rounded(positive / negative)


def stage_metrics(rows: Sequence[Mapping[str, Any]], stages: Sequence[str]) -> list[dict[str, Any]]:
    baseline_values = [float(row[STAGES_FIXED[0]]) for row in rows if row[STAGES_FIXED[0]] is not None]
    baseline_total = sum(baseline_values)
    baseline_positive = sum(max(0.0, value) for value in baseline_values)
    output = []
    previous_total = None
    for stage in stages:
        values = [float(row[stage]) for row in rows if row[stage] is not None]
        active = [row for row in rows if row[stage] is not None and bool(row[ACTIVE_FIELDS[stage]])]
        active_values = [float(row[stage]) for row in active]
        total = sum(values)
        if stage == STAGE7:
            actual_pnl = sum(float(row["stage7_actual_pnl_usd"] or 0.0) for row in rows if row[STAGE7] is not None)
        else:
            actual_pnl = total * 50.0
        positives = sum(value > 0 for value in active_values)
        negatives = sum(value < 0 for value in active_values)
        zeroes = sum(value == 0 for value in active_values)
        path_rows = [row for row in active if row.get("checkpoint_path_mfe_r") is not None]
        result = {
            "stage": STAGE_LABELS[stage],
            "stage_field": stage,
            "opportunity_rows": len(rows),
            "value_rows": len(values),
            "active_rows": len(active),
            "positive_active_rows": positives,
            "negative_active_rows": negatives,
            "zero_active_rows": zeroes,
            "win_rate_active_pct": rounded(100 * positives / len(active_values)) if active_values else None,
            "total_r": rounded(total),
            "mean_r_per_opportunity": rounded(total / len(rows)) if rows else None,
            "mean_r_per_active": rounded(statistics.fmean(active_values)) if active_values else None,
            "profit_factor": profit_factor(active_values),
            "normalized_or_actual_pnl_usd": rounded(actual_pnl),
            "average_monthly_pnl_usd": rounded(actual_pnl / MONTHS),
            "gross_positive_capture_vs_stage1_pct": rounded(100 * sum(max(0.0, value) for value in values) / baseline_positive) if baseline_positive else None,
            "net_value_retention_vs_stage1_pct": rounded(100 * total / baseline_total) if baseline_total else None,
            "average_checkpoint_path_mfe_r": rounded(statistics.fmean(float(row["checkpoint_path_mfe_r"]) for row in path_rows)) if path_rows else None,
            "average_checkpoint_path_mae_r": rounded(statistics.fmean(float(row["checkpoint_path_mae_r"]) for row in path_rows)) if path_rows else None,
            "incremental_r_from_prior_stage": rounded(total - previous_total) if previous_total is not None else None,
            "incremental_usd_from_prior_stage": rounded((total - previous_total) * 50.0) if previous_total is not None else None,
        }
        output.append(result)
        previous_total = total
    if output:
        expected = float(output[0]["total_r"]) + sum(float(row["incremental_r_from_prior_stage"]) for row in output[1:])
        output[-1]["waterfall_residual_r"] = rounded(float(output[-1]["total_r"]) - expected)
    return output


def group_rows(rows: Sequence[Mapping[str, Any]], fields: Sequence[str]) -> Iterable[tuple[tuple[str, ...], list[Mapping[str, Any]]]]:
    grouped: dict[tuple[str, ...], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[tuple(str(row[field]) for field in fields)].append(row)
    for key in sorted(grouped):
        yield key, grouped[key]


def summarize(rows: list[dict[str, Any]], diagnostics: Mapping[str, Any]) -> dict[str, Any]:
    formation = rows
    executed = [row for row in rows if row["trade_status"] == "EXECUTED"]
    oof = [row for row in rows if row[STAGE7] is not None]
    fixed = list(STAGES_FIXED)
    oof_stages = [*STAGES_FIXED[:5], "stage6_oof_fixed_risk_r", STAGE7]
    # Re-map OOF-specific Stage 6 into the common Stage 6 slot for generic metrics.
    oof_copy = []
    for row in oof:
        item = dict(row)
        item[STAGES_FIXED[5]] = row["stage6_oof_fixed_risk_r"]
        item["stage6_active"] = row["stage6_oof_active"]
        oof_copy.append(item)
    oof_stages = [*STAGES_FIXED, STAGE7]

    timeframe = {"formation_aware": {}, "executed_only": {}, "oof_router_matched": {}}
    for key, values in group_rows(formation, ["timeframe"]):
        timeframe["formation_aware"][key[0]] = stage_metrics(values, fixed)
    for key, values in group_rows(executed, ["timeframe"]):
        timeframe["executed_only"][key[0]] = stage_metrics(values, fixed)
    for key, values in group_rows(oof_copy, ["timeframe"]):
        timeframe["oof_router_matched"][key[0]] = stage_metrics(values, oof_stages)

    cells = []
    for key, values in group_rows(formation, ["timeframe", "model_id", "archetype"]):
        cell_executed = [row for row in values if row["trade_status"] == "EXECUTED"]
        cells.append({
            "timeframe": key[0],
            "model_id": key[1],
            "archetype": key[2],
            "formation_aware": stage_metrics(values, fixed),
            "executed_only": stage_metrics(cell_executed, fixed) if cell_executed else [],
        })

    atlas_unique = {}
    unique: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        unique.setdefault(str(row["pullback_id"]), row)
    for timeframe_name in ("M15", "H1", "H4"):
        values = [float(row[STAGES_FIXED[0]]) for row in unique.values() if row["timeframe"] == timeframe_name and row[STAGES_FIXED[0]] is not None]
        atlas_unique[timeframe_name] = {
            "cases_with_oracle": len(values),
            "total_r": rounded(sum(values)),
            "pnl_usd_at_50_risk": rounded(sum(values) * 50.0),
            "average_monthly_pnl_usd_at_50_risk": rounded(sum(values) * 50.0 / MONTHS),
            "pnl_usd_at_100_risk": rounded(sum(values) * 100.0),
            "average_monthly_pnl_usd_at_100_risk": rounded(sum(values) * 100.0 / MONTHS),
        }

    def bottlenecks(view: str) -> dict[str, Any]:
        output: dict[str, Any] = {}
        for timeframe_name, stages in timeframe[view].items():
            transitions = [
                {
                    "transition": f"{stages[index - 1]['stage']}->{stages[index]['stage']}",
                    "incremental_r": stages[index]["incremental_r_from_prior_stage"],
                    "incremental_usd": stages[index]["incremental_usd_from_prior_stage"],
                }
                for index in range(1, len(stages))
            ]
            dominant = min(transitions, key=lambda row: float(row["incremental_usd"]))
            output[timeframe_name] = {"transitions": transitions, "dominant": dominant}
        return output

    executed_total = stage_metrics(executed, fixed)
    transitions = [
        (index, float(executed_total[index]["incremental_usd_from_prior_stage"]))
        for index in range(1, len(executed_total))
    ]
    dominant_index, _ = min(transitions, key=lambda item: item[1])
    mapping = {
        1: "EARLIER_POINT_IN_TIME_CHECKPOINT_AND_ENTRY_LOCATION_RESEARCH",
        2: "STRUCTURAL_STOP_GEOMETRY_RESEARCH",
        3: "TRANSPARENT_STRUCTURAL_OR_TRAILING_EXIT_CAPTURE_RESEARCH",
        4: "TRANSACTION_COST_AND_TURNOVER_REDUCTION_RESEARCH",
        5: "SIGNAL_PRIORITY_AND_CONCURRENCY_RESEARCH",
    }
    recommendation = mapping[dominant_index]
    return {
        "version": "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_V1_RESULTS_1_0",
        "status": "COMPLETE_DIAGNOSTIC_NO_EDGE_CREDIT",
        "development_period": ["2021-08-01", "2024-12-31"],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "diagnostics": diagnostics,
        "unique_case_oracle_reconciliation": atlas_unique,
        "total": {
            "formation_aware": stage_metrics(formation, fixed),
            "executed_only": executed_total,
            "oof_router_matched": stage_metrics(oof_copy, oof_stages),
        },
        "timeframe": timeframe,
        "cells": cells,
        "bottlenecks": {
            "formation_aware": bottlenecks("formation_aware"),
            "executed_only": bottlenecks("executed_only"),
        },
        "dominant_executed_only_transition_all_timeframes": {
            "transition": f"{executed_total[dominant_index - 1]['stage']}->{executed_total[dominant_index]['stage']}",
            "incremental_r": executed_total[dominant_index]["incremental_r_from_prior_stage"],
            "incremental_usd": executed_total[dominant_index]["incremental_usd_from_prior_stage"],
        },
        "single_bounded_recommendation": recommendation,
        "recommendation_not_implemented": True,
        "attribution_limitations": [
            "The bridge is exact for the frozen order but is not a causal or order-invariant Shapley attribution.",
            "Stage 1 uses the original one-ATR oracle unit while Stages 2-6 use each entry model's structural-stop risk unit.",
            "Stage 1-to-Stage 2 therefore combines confirmation timing, entry location, trade direction, and risk-denominator effects.",
            "Stage 7 jointly changes selection, overlap priority, and dollar risk and is restricted to the corrected OOF population.",
            "Model-opportunity totals repeat each unique pullback across six models and are not unique-case account returns.",
        ],
        "fixed_order_residual_r": {
            "formation_aware": stage_metrics(formation, fixed)[-1].get("waterfall_residual_r"),
            "executed_only": executed_total[-1].get("waterfall_residual_r"),
            "oof_router_matched": stage_metrics(oof_copy, oof_stages)[-1].get("waterfall_residual_r"),
        },
        "paid_acquisition_usd": 0.0,
        "live_trading_authorized": False,
    }


def report(results: Mapping[str, Any]) -> str:
    lines = [
        "# Gold Pullback Monetizability Gap Decomposition V1",
        "",
        f"Status: **{results['status']}**",
        "",
        "This is an accounting diagnosis of the previously observed movement opportunity. It creates no candidate and grants no edge or validation credit.",
        "",
        "## Unique-case oracle reconciliation",
        "",
        "| TF | Cases | Oracle R | $50/month | $100/month |",
        "|---|---:|---:|---:|---:|",
    ]
    for timeframe in ("M15", "H1", "H4"):
        row = results["unique_case_oracle_reconciliation"][timeframe]
        lines.append(f"| {timeframe} | {row['cases_with_oracle']} | {row['total_r']} | ${row['average_monthly_pnl_usd_at_50_risk']} | ${row['average_monthly_pnl_usd_at_100_risk']} |")
    for view, title in (("formation_aware", "Formation-aware all-model waterfall"), ("executed_only", "Executed-only waterfall"), ("oof_router_matched", "OOF router-matched waterfall")):
        lines += ["", f"## {title}", "", "| Stage | Active | Total R | PnL | Avg/month | Incremental $ | Net retention |", "|---|---:|---:|---:|---:|---:|---:|"]
        for row in results["total"][view]:
            lines.append(
                f"| {row['stage']} | {row['active_rows']} | {row['total_r']} | ${row['normalized_or_actual_pnl_usd']} | "
                f"${row['average_monthly_pnl_usd']} | ${row['incremental_usd_from_prior_stage']} | {row['net_value_retention_vs_stage1_pct']}% |"
            )
    lines += ["", "## Dominant bottlenecks by timeframe", "", "| View | TF | Transition | Incremental $ |", "|---|---|---|---:|"]
    for view in ("formation_aware", "executed_only"):
        for timeframe in ("M15", "H1", "H4"):
            row = results["bottlenecks"][view][timeframe]["dominant"]
            lines.append(f"| {view} | {timeframe} | {row['transition']} | ${row['incremental_usd']} |")
    dominant = results["dominant_executed_only_transition_all_timeframes"]
    lines += [
        "",
        "## Verdict",
        "",
        f"The dominant executed-only loss transition is **{dominant['transition']}**, contributing ${dominant['incremental_usd']} in the fixed $50 model-opportunity accounting bridge.",
        "",
        f"Exactly one bounded next direction is recommended: **{results['single_bounded_recommendation']}**.",
        "",
        "The recommendation is not implemented here. The model-opportunity totals repeat a pullback across six models and must not be interpreted as account returns. Stage 1 also uses the original ATR oracle unit, while later stages use structural-stop R; therefore the first transition is a combined timing/location/direction/risk-unit loss, not a pure causal estimate.",
        "",
        "No 2025 or 2026 values were accessed, no data was acquired, and no charge was incurred.",
        "",
    ]
    return "\n".join(lines)


def main() -> None:
    if REPORT.exists() or (OUTPUT / "final_seal.json").exists():
        raise FileExistsError("Completed decomposition output already exists")
    if OUTPUT.exists():
        observed = {path.name for path in OUTPUT.iterdir()}
        if observed != {"attempt_1_failure.json"}:
            raise FileExistsError(f"Unexpected incomplete decomposition artifacts: {sorted(observed)}")
    else:
        OUTPUT.mkdir(parents=True, exist_ok=False)
    protocol, freeze = verify_freeze()
    prices = anatomy_impl.load_price()
    if prices.diagnostics["last_m1_open"] >= "2025-01-01T00:00:00Z":
        raise ValueError("Development price loader exposed a forward minute")

    primary_rows, primary_diagnostics = materialize("primary", "primary", protocol, prices)
    reference_rows, reference_diagnostics = materialize("reference", "reference", protocol, prices)
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise ValueError("Independent waterfall rows differ")
    if primary_diagnostics != reference_diagnostics:
        raise ValueError("Independent waterfall diagnostics differ")
    primary_results = summarize(primary_rows, primary_diagnostics)
    reference_results = summarize(reference_rows, reference_diagnostics)
    if canonical_hash(primary_results) != canonical_hash(reference_results):
        raise ValueError("Independent aggregate results differ")

    primary_path = OUTPUT / "primary_waterfall_rows.parquet"
    reference_path = OUTPUT / "reference_waterfall_rows.parquet"
    write_parquet_exclusive(primary_path, primary_rows)
    write_parquet_exclusive(reference_path, reference_rows)
    if sha256_file(primary_path) != sha256_file(reference_path):
        raise ValueError("Paired Parquet payloads are not byte-identical")
    primary_results_path = OUTPUT / "primary_results.json"
    reference_results_path = OUTPUT / "reference_results.json"
    write_json_exclusive(primary_results_path, primary_results)
    write_json_exclusive(reference_results_path, reference_results)
    if sha256_file(primary_results_path) != sha256_file(reference_results_path):
        raise ValueError("Paired result payloads are not byte-identical")
    report_text = report(primary_results)
    write_text_exclusive(REPORT, report_text)

    artifacts = {
        str(path.relative_to(ROOT)).replace("\\", "/"): record(path)
        for path in (primary_path, reference_path, primary_results_path, reference_results_path, REPORT, CONTRACT, PROTOCOL, FREEZE, ATTEMPT_FAILURE, RECOVERY)
    }
    seal = {
        "version": "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_V1_FINAL_SEAL_1_0",
        "status": "PASS_COMPLETE_INDEPENDENT_DECOMPOSITION",
        "sealed_at_utc": utc_now(),
        "pre_result_freeze": record(FREEZE),
        "predecessor_seals": freeze["predecessor_seals"],
        "primary_reference_exact": True,
        "paired_parquet_byte_identical": True,
        "paired_results_byte_identical": True,
        "fixed_order_residual_r": primary_results["fixed_order_residual_r"],
        "single_bounded_recommendation": primary_results["single_bounded_recommendation"],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
        "artifacts": artifacts,
        "artifact_set_hash": canonical_hash([artifacts[key]["sha256"] for key in sorted(artifacts)]),
    }
    write_json_exclusive(OUTPUT / "final_seal.json", seal)
    state = {
        "version": "GOLD_PULLBACK_MONETIZABILITY_GAP_DECOMPOSITION_V1_STATE_1_0",
        "status": "COMPLETE_DIAGNOSTIC_STOPPED",
        "final_seal": record(OUTPUT / "final_seal.json"),
        "next_step": primary_results["single_bounded_recommendation"],
        "recommendation_implemented": False,
    }
    write_json_exclusive(OUTPUT / "state.json", state)
    print(canonical_json({
        "status": seal["status"],
        "diagnostics": primary_diagnostics,
        "dominant": primary_results["dominant_executed_only_transition_all_timeframes"],
        "recommendation": primary_results["single_bounded_recommendation"],
        "seal": record(OUTPUT / "final_seal.json"),
    }))


if __name__ == "__main__":
    main()
