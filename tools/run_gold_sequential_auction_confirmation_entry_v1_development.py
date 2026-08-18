from __future__ import annotations

import argparse
import bisect
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

import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402
import run_gold_structural_stop_geometry_v1_stage1 as stop_impl  # noqa: E402


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
MATERIALIZATION = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_materialization"
OUTPUT = ARTIFACTS / "gold_sequential_auction_confirmation_entry_v1_development"
REPORT = ROOT / "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_RESEARCH_V1_DEVELOPMENT.md"
PROTOCOL = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_protocol.json"
MATERIALIZATION_SEAL = MATERIALIZATION / "materialization_seal.json"
ECONOMIC_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_pre_economic_freeze.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_sequential_auction_confirmation_entry_v1_economic_implementation_freeze.json"

SCALE = 100_000_000
MINUTE_NS = 60_000_000_000
TF_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
BOOTSTRAPS = 5000
BASE_SEED = 970331
OOF_RANGES = (
    (1, "2022-07-01", "2023-03-31"),
    (2, "2023-04-01", "2023-12-31"),
    (3, "2024-01-01", "2024-12-31"),
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


def iso_week(value: str) -> str:
    year, week, _ = datetime.fromisoformat(value).date().isocalendar()
    return f"{year:04d}-W{week:02d}"


def oof_fold(value: str) -> int | None:
    day = value[:10]
    for fold, start, end in OOF_RANGES:
        if start <= day <= end:
            return fold
    return None


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    result = round(float(value), 12)
    return 0.0 if result == 0 else result


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
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
        pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=16_384)
        temporary.replace(path)
    except Exception:
        temporary.unlink(missing_ok=True)
        raise


def verify_controls() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    materialization_seal = json.loads(MATERIALIZATION_SEAL.read_text(encoding="utf-8"))
    freeze = json.loads(ECONOMIC_FREEZE.read_text(encoding="utf-8"))
    implementation = json.loads(IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    if materialization_seal.get("status") != "PASS_OUTCOME_BLIND_SEQUENCE_MATERIALIZATION":
        raise ValueError("Materialization did not pass")
    if freeze.get("status") != "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_PATHS":
        raise ValueError("Pre-economic freeze changed")
    if implementation.get("status") != "FROZEN_BEFORE_DEVELOPMENT_OUTCOME_PATHS":
        raise ValueError("Economic implementation freeze changed")
    for item in [*materialization_seal["controls"].values(), *materialization_seal["artifacts"].values(), *freeze["controls"].values()]:
        path = ROOT / item["path"]
        if not path.is_file() or record(path) != item:
            raise ValueError(f"Frozen input changed: {item['path']}")
    if record(ROOT / implementation["implementation"]["path"]) != implementation["implementation"]:
        raise ValueError("Economic implementation changed")
    if freeze.get("calendar_2025_values_accessed") or freeze.get("calendar_2026_values_accessed"):
        raise ValueError("Forward lock changed")
    return protocol, freeze, implementation


def path_indices(row: Mapping[str, Any], prices: anatomy_impl.PriceData, implementation: str) -> tuple[int | None, int | None, str | None]:
    entry_ns = parse_ns(str(row["delayed_entry_at_utc"])); deadline_ns = parse_ns(str(row["original_deadline_at_utc"]))
    if implementation == "primary":
        start = int(np.searchsorted(prices.open_ns, entry_ns, side="left")); end = int(np.searchsorted(prices.open_ns, deadline_ns, side="left"))
    else:
        start = bisect.bisect_left(prices.open_ns, entry_ns); end = bisect.bisect_left(prices.open_ns, deadline_ns)
    if start >= len(prices.open_ns) or int(prices.open_ns[start]) != entry_ns:
        return None, None, "MISSING_EXACT_DELAYED_ENTRY_M1"
    if end <= start:
        return None, None, "EMPTY_POST_ENTRY_PATH"
    timestamps = prices.open_ns[start:end]
    if len(timestamps) != (deadline_ns - entry_ns) // MINUTE_NS or int(timestamps[-1]) + MINUTE_NS != deadline_ns:
        return None, None, "INCOMPLETE_POST_ENTRY_M1_PATH"
    if len(timestamps) > 1 and np.any(np.diff(timestamps) != MINUTE_NS):
        return None, None, "INCOMPLETE_POST_ENTRY_M1_PATH"
    return start, end, None


def economic_values(entry: int, stop: int, target: int, exit_e8: int, direction: str, total_cost: float, planned_ounces: int) -> dict[str, Any]:
    sign = 1 if direction == "UP" else -1
    risk_e8 = abs(entry - stop); risk_usd_oz = risk_e8 / SCALE
    gross_r = sign * (exit_e8 - entry) / risk_e8; cost_r = total_cost / risk_usd_oz
    net_r = gross_r - cost_r; signed_change = sign * (exit_e8 - entry) / SCALE
    return {
        "gross_r": rounded(gross_r), "cost_r": rounded(cost_r), "net_r": rounded(net_r),
        "net_r_cost_1p5x": rounded(gross_r - 1.5 * cost_r), "net_r_cost_2x": rounded(gross_r - 2.0 * cost_r),
        "normalized_pnl_usd": rounded(50.0 * net_r), "whole_ounce_pnl_usd": rounded((signed_change - total_cost) * planned_ounces),
        "target_r": rounded(abs(target - entry) / risk_e8),
    }


def simulate(rows: Sequence[Mapping[str, Any]], prices: anatomy_impl.PriceData, implementation: str) -> list[dict[str, Any]]:
    scanner = stop_impl.scan_primary if implementation == "primary" else stop_impl.scan_reference
    output: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row.update({
            "economic_status": "NOT_ENTRY_ELIGIBLE", "outcome_unavailable_reason": "", "exit_at_utc": None,
            "exit_e8": None, "exit_reason": None, "holding_minutes": None, "first_stop_offset": None,
            "first_target_offset": None, "stopped_then_later_target": None, "target_first": None,
            "exit_mfe_r": None, "exit_mae_r": None, "full_horizon_mfe_r": None, "full_horizon_mae_r": None,
            "gross_r": None, "cost_r": None, "net_r": None, "net_r_cost_1p5x": None,
            "net_r_cost_2x": None, "normalized_pnl_usd": None, "whole_ounce_pnl_usd": None,
            "full_portfolio_status": "UNAVAILABLE", "oof_portfolio_status": "UNAVAILABLE",
            "oof_fold": oof_fold(str(row["known_at_utc"])), "is_oof_validation": oof_fold(str(row["known_at_utc"])) is not None,
            "iso_week": iso_week(str(row["cluster_date"])),
        })
        if row["status"] != "ENTRY_ELIGIBLE":
            output.append(row); continue
        start, end, failure = path_indices(row, prices, implementation)
        if failure is not None or start is None or end is None:
            row["economic_status"] = "OUTCOME_UNAVAILABLE"; row["outcome_unavailable_reason"] = failure or "UNKNOWN_PATH_FAILURE"; output.append(row); continue
        entry = int(row["entry_e8"]); stop = int(row["stop_e8"]); target = int(row["target_e8"])
        sign = 1 if row["trade_direction"] == "UP" else -1
        result = scanner(prices, start, end, entry, stop, target, sign)
        exit_index = start + int(result["exit_offset"]); risk_e8 = abs(entry - stop)
        row.update({
            "economic_status": "EXECUTABLE", "exit_at_utc": ns_iso(int(prices.open_ns[exit_index]) + MINUTE_NS),
            "exit_e8": int(result["exit_e8"]), "exit_reason": str(result["exit_reason"]),
            "holding_minutes": int(result["exit_offset"]) + 1, "first_stop_offset": result["first_stop_offset"],
            "first_target_offset": result["first_target_offset"],
            "stopped_then_later_target": bool(result["exit_reason"] == "STOP" and result["first_target_offset"] is not None and int(result["first_target_offset"]) > int(result["first_stop_offset"])),
            "target_first": bool(result["exit_reason"] == "TARGET"),
            "exit_mfe_r": rounded(int(result["exit_mfe_e8"]) / risk_e8), "exit_mae_r": rounded(int(result["exit_mae_e8"]) / risk_e8),
            "full_horizon_mfe_r": rounded(int(result["full_mfe_e8"]) / risk_e8), "full_horizon_mae_r": rounded(int(result["full_mae_e8"]) / risk_e8),
        })
        row.update(economic_values(entry, stop, target, int(result["exit_e8"]), str(row["trade_direction"]), float(row["total_cost_usd_oz"]), int(row["planned_ounces"])))
        output.append(row)
    output.sort(key=lambda row: (TF_PRIORITY[str(row["timeframe"])], str(row["model_id"]), str(row["track_id"]), str(row["variant"]), str(row["delayed_entry_at_utc"] or ""), str(row["trade_id"])))
    return output


def apply_overlap(group: list[dict[str, Any]], field: str, formal_oof: bool) -> None:
    for row in group:
        row[field] = "NOT_OOF" if formal_oof and not row["is_oof_validation"] else "UNAVAILABLE"
    eligible = [row for row in group if row["economic_status"] == "EXECUTABLE" and (not formal_oof or row["is_oof_validation"])]
    eligible.sort(key=lambda row: (str(row["delayed_entry_at_utc"]), str(row["trade_id"])))
    open_until: str | None = None
    for row in eligible:
        if open_until is not None and str(row["delayed_entry_at_utc"]) < open_until:
            row[field] = "SKIPPED_OVERLAPPING_POSITION"
        else:
            row[field] = "ACCEPTED"; open_until = str(row["exit_at_utc"])


def attach_overlap(rows: list[dict[str, Any]]) -> None:
    grouped: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["variant"]), str(row["candidate_id"]))].append(row)
    for group in grouped.values():
        apply_overlap(group, "full_portfolio_status", False); apply_overlap(group, "oof_portfolio_status", True)


def profit_factor(values: Sequence[float]) -> float | str | None:
    positive = sum(value for value in values if value > 0); negative = abs(sum(value for value in values if value < 0))
    if negative == 0:
        return "INF" if positive > 0 else None
    return rounded(positive / negative)


def max_drawdown(values: Sequence[float]) -> float:
    cumulative = peak = drawdown = 0.0
    for value in values:
        cumulative += float(value); peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
    return rounded(drawdown) or 0.0


def daily_risk_ratios(rows: Sequence[Mapping[str, Any]]) -> tuple[float | None, float | None]:
    grouped: dict[str, float] = defaultdict(float)
    for row in rows:
        grouped[str(row["cluster_date"])] += float(row["normalized_pnl_usd"]) / 10_000.0
    values = list(grouped.values())
    if len(values) < 2:
        return None, None
    mean = statistics.fmean(values); standard = statistics.stdev(values)
    downside = [min(value, 0.0) for value in values]
    downside_dev = math.sqrt(statistics.fmean(value * value for value in downside))
    sharpe = mean / standard * math.sqrt(252) if standard > 0 else None
    sortino = mean / downside_dev * math.sqrt(252) if downside_dev > 0 else None
    return rounded(sharpe), rounded(sortino)


def performance(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (str(row["delayed_entry_at_utc"]), str(row["trade_id"])))
    net = [float(row["net_r"]) for row in ordered]; gross = [float(row["gross_r"]) for row in ordered]
    stress15 = [float(row["net_r_cost_1p5x"]) for row in ordered]; stress20 = [float(row["net_r_cost_2x"]) for row in ordered]
    wins = [value for value in net if value > 0]; losses = [value for value in net if value < 0]
    sharpe, sortino = daily_risk_ratios(ordered)
    return {
        "trades": len(ordered), "trading_dates": len({str(row["cluster_date"]) for row in ordered}), "iso_weeks": len({str(row["iso_week"]) for row in ordered}),
        "wins": len(wins), "losses": len(losses), "win_rate": rounded(len(wins) / len(net)) if net else None,
        "average_win_r": rounded(statistics.fmean(wins)) if wins else None, "average_loss_r": rounded(statistics.fmean(losses)) if losses else None,
        "gross_expectancy_r": rounded(statistics.fmean(gross)) if gross else None, "net_expectancy_r": rounded(statistics.fmean(net)) if net else None,
        "net_expectancy_r_cost_1p5x": rounded(statistics.fmean(stress15)) if stress15 else None,
        "net_expectancy_r_cost_2x": rounded(statistics.fmean(stress20)) if stress20 else None,
        "profit_factor": profit_factor(net), "total_net_r": rounded(sum(net)),
        "normalized_pnl_usd": rounded(sum(float(row["normalized_pnl_usd"]) for row in ordered)),
        "whole_ounce_pnl_usd": rounded(sum(float(row["whole_ounce_pnl_usd"]) for row in ordered)),
        "max_drawdown_r": max_drawdown(net), "normalized_max_drawdown_usd": rounded(50.0 * max_drawdown(net)),
        "whole_ounce_max_drawdown_usd": max_drawdown([float(row["whole_ounce_pnl_usd"]) for row in ordered]),
        "stop_rate": rounded(sum(row["exit_reason"] == "STOP" for row in ordered) / len(ordered)) if ordered else None,
        "stopped_then_later_target_rate": rounded(sum(bool(row["stopped_then_later_target"]) for row in ordered) / sum(row["exit_reason"] == "STOP" for row in ordered)) if any(row["exit_reason"] == "STOP" for row in ordered) else None,
        "target_first_rate": rounded(sum(bool(row["target_first"]) for row in ordered) / len(ordered)) if ordered else None,
        "mfe_r_mean": rounded(statistics.fmean(float(row["exit_mfe_r"]) for row in ordered)) if ordered else None,
        "mae_r_mean": rounded(statistics.fmean(float(row["exit_mae_r"]) for row in ordered)) if ordered else None,
        "holding_minutes_mean": rounded(statistics.fmean(float(row["holding_minutes"]) for row in ordered)) if ordered else None,
        "entry_delay_minutes_mean": rounded(statistics.fmean(float(row["entry_delay_minutes"]) for row in ordered)) if ordered else None,
        "entry_improvement_usd_oz_mean": rounded(statistics.fmean(float(row["entry_improvement_usd_oz"]) for row in ordered)) if ordered else None,
        "daily_sharpe": sharpe, "daily_sortino": sortino,
    }


def group_metrics(rows: Sequence[Mapping[str, Any]], field: str) -> list[dict[str, Any]]:
    grouped: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[str(row[field])].append(row)
    output = []
    for name in sorted(grouped):
        values = grouped[name]; net = [float(row["net_r"]) for row in values]
        output.append({field: name, "trades": len(values), "net_expectancy_r": rounded(statistics.fmean(net)), "total_net_r": rounded(sum(net)), "profit_factor": profit_factor(net)})
    return output


def positive_share(rows: Sequence[Mapping[str, Any]], field: str) -> tuple[int, float | None]:
    grouped: dict[str, float] = defaultdict(float)
    for row in rows:
        grouped[str(row[field])] += float(row["net_r"])
    positives = [value for value in grouped.values() if value > 0]
    return len(positives), rounded(max(positives) / sum(positives)) if positives else None


def clustered_bootstrap(rows: Sequence[Mapping[str, Any]], candidate_id: str) -> dict[str, Any]:
    grouped: dict[str, list[float]] = defaultdict(list)
    for row in rows:
        grouped[str(row["cluster_date"])].append(float(row["net_r"]))
    dates = sorted(grouped)
    if len(dates) < 2:
        return {"seed": None, "clusters": len(dates), "ci95_low": None, "ci95_high": None, "p_one_sided": 1.0}
    sums = np.asarray([sum(grouped[day]) for day in dates]); counts = np.asarray([len(grouped[day]) for day in dates])
    seed = (BASE_SEED + int(hashlib.sha256(candidate_id.encode()).hexdigest()[:8], 16)) % (2**31 - 1)
    rng = np.random.default_rng(seed); samples = []
    for left in range(0, BOOTSTRAPS, 250):
        indices = rng.integers(0, len(dates), size=(min(250, BOOTSTRAPS - left), len(dates)))
        samples.extend((sums[indices].sum(axis=1) / counts[indices].sum(axis=1)).tolist())
    values = np.asarray(samples)
    return {"seed": seed, "clusters": len(dates), "ci95_low": rounded(float(np.quantile(values, 0.025))), "ci95_high": rounded(float(np.quantile(values, 0.975))), "p_one_sided": rounded((1 + int(np.sum(values <= 0))) / (BOOTSTRAPS + 1))}


def bh_adjust(results: list[dict[str, Any]]) -> None:
    grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in results:
        grouped[str(row["timeframe"])].append(row)
    for values in grouped.values():
        ordered = sorted(values, key=lambda row: (float(row["bootstrap"]["p_one_sided"]), str(row["candidate_id"])))
        running = 1.0; count = len(ordered)
        for rank in range(count, 0, -1):
            row = ordered[rank - 1]; running = min(running, float(row["bootstrap"]["p_one_sided"]) * count / rank); row["bh_q"] = rounded(min(running, 1.0))


def summarize(rows: Sequence[Mapping[str, Any]], protocol: Mapping[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["variant"]), str(row["candidate_id"]))].append(row)
    candidates = [f"{tf}::{model}::{track}" for tf in ("M15", "H1", "H4") for model in sorted({key[1].split("::")[1] for key in grouped if key[0] == "PRIMARY" and key[1].startswith(tf + "::")}) for track in ("TRACK_A_ORIGINAL_STOP", "TRACK_B_CONFIRMED_RETEST_STOP")]
    results: list[dict[str, Any]] = []
    for candidate_id in candidates:
        source = grouped[("PRIMARY", candidate_id)]
        full = [row for row in source if row["full_portfolio_status"] == "ACCEPTED"]
        oof = [row for row in source if row["oof_portfolio_status"] == "ACCEPTED"]
        timeframe, model_id, track = candidate_id.split("::")
        fold_results = group_metrics(oof, "oof_fold"); annual_results = group_metrics(oof, "calendar_year"); session_results = group_metrics(oof, "session_state")
        positive_years, year_share = positive_share(oof, "calendar_year"); positive_sessions, session_share = positive_share(oof, "session_state")
        neighbours = []
        for variant in ("LENIENT", "STRICT"):
            neighbour_rows = grouped[(variant, candidate_id)]
            accepted = [row for row in neighbour_rows if row["oof_portfolio_status"] == "ACCEPTED"]
            neighbours.append({"variant": variant, "formation_rows": sum(row["status"] == "ENTRY_ELIGIBLE" for row in neighbour_rows), "oof_validation_union": performance(accepted)})
        result = {
            "candidate_id": candidate_id, "timeframe": timeframe, "model_id": model_id, "track_id": track,
            "setup_rows": len(source), "sequence_or_post_sequence_gate_rows": sum(row["status"] == "ENTRY_ELIGIBLE" or row["reason"] in {"ORIGINAL_TARGET_TOUCHED_BEFORE_DELAYED_ENTRY", "STOP_NOT_ADVERSE_TO_DELAYED_ENTRY", "TARGET_NOT_FAVOURABLE_TO_DELAYED_ENTRY", "GROSS_TARGET_ROOM_BELOW_1R", "WHOLE_OUNCE_RISK_INFEASIBLE"} for row in source),
            "entry_eligible_rows": sum(row["status"] == "ENTRY_ELIGIBLE" for row in source),
            "outcome_unavailable_rows": sum(row["economic_status"] == "OUTCOME_UNAVAILABLE" for row in source),
            "skip_reasons": dict(sorted(Counter(str(row["reason"] or row["outcome_unavailable_reason"]) for row in source if row["economic_status"] != "EXECUTABLE").items())),
            "full_development": performance(full), "oof_validation_union": performance(oof),
            "fold_results": fold_results, "annual_results": annual_results, "session_results": session_results,
            "positive_validation_folds": sum(float(item["net_expectancy_r"]) > 0 for item in fold_results),
            "positive_calendar_years": positive_years, "maximum_positive_year_share": year_share,
            "positive_sessions": positive_sessions, "maximum_positive_session_share": session_share,
            "bootstrap": clustered_bootstrap(oof, candidate_id), "bh_q": None,
            "sensitivity_bundles": neighbours, "checks": {}, "failed_gates": [], "disposition": None,
        }
        results.append(result)
    if len(results) != 36:
        raise ValueError(f"Candidate registry changed: {len(results)}")
    bh_adjust(results)
    for row in results:
        metrics = row["oof_validation_union"]; floors = protocol["support_floors"][row["timeframe"]]; gates = protocol["pass_gates"]
        pf = metrics["profit_factor"]; pf_value = float("inf") if pf == "INF" else float(pf) if pf is not None else float("-inf")
        checks = {
            "trade_support": metrics["trades"] >= floors["trades"], "date_support": metrics["trading_dates"] >= floors["dates"], "week_support": metrics["iso_weeks"] >= floors["weeks"],
            "positive_net_expectancy": metrics["net_expectancy_r"] is not None and metrics["net_expectancy_r"] > gates["net_expectancy_gt"],
            "profit_factor": pf_value >= gates["profit_factor_gte"],
            "positive_cluster_ci95_low": row["bootstrap"]["ci95_low"] is not None and row["bootstrap"]["ci95_low"] > gates["cluster_ci95_low_gt"],
            "bh_q": row["bh_q"] is not None and row["bh_q"] <= gates["bh_q_lte"],
            "positive_cost_1p5x": metrics["net_expectancy_r_cost_1p5x"] is not None and metrics["net_expectancy_r_cost_1p5x"] > gates["cost_1p5x_expectancy_gt"],
            "positive_validation_folds": row["positive_validation_folds"] >= gates["positive_validation_folds_gte"],
            "positive_calendar_years": row["positive_calendar_years"] >= gates["positive_calendar_years_gte"],
            "maximum_positive_year_share": row["maximum_positive_year_share"] is not None and row["maximum_positive_year_share"] <= gates["maximum_positive_year_share_lte"],
            "positive_sessions": row["positive_sessions"] >= gates["positive_sessions_gte"],
            "maximum_positive_session_share": row["maximum_positive_session_share"] is not None and row["maximum_positive_session_share"] <= gates["maximum_positive_session_share_lte"],
            "both_sensitivity_bundles_positive": all(item["oof_validation_union"]["net_expectancy_r"] is not None and item["oof_validation_union"]["net_expectancy_r"] > 0 for item in row["sensitivity_bundles"]),
        }
        row["checks"] = checks; row["failed_gates"] = [name for name, passed in checks.items() if not passed]
        if not checks["trade_support"] or not checks["date_support"] or not checks["week_support"]:
            row["disposition"] = "SUPPORT_FAIL"
        elif all(checks.values()):
            row["disposition"] = "PASS_PROVISIONAL_UNVALIDATED"
        else:
            row["disposition"] = "REJECT"
    shortlist: dict[str, list[str]] = {}
    for timeframe in ("M15", "H1", "H4"):
        passing = [row for row in results if row["timeframe"] == timeframe and row["disposition"] == "PASS_PROVISIONAL_UNVALIDATED"]
        passing.sort(key=lambda row: (-float(row["bootstrap"]["ci95_low"]), -float(row["oof_validation_union"]["net_expectancy_r_cost_1p5x"]), -(float("inf") if row["oof_validation_union"]["profit_factor"] == "INF" else float(row["oof_validation_union"]["profit_factor"])), -int(row["oof_validation_union"]["trades"]), float(row["oof_validation_union"]["max_drawdown_r"]), str(row["candidate_id"])))
        shortlist[timeframe] = [row["candidate_id"] for row in passing[: int(protocol["maximum_candidates_per_timeframe"])]]
    selected = [candidate for values in shortlist.values() for candidate in values]
    return {
        "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_DEVELOPMENT_RESULTS_1_0",
        "status": "PASS_DEVELOPMENT_PROVISIONAL_CANDIDATES" if selected else "REJECT_NO_DEVELOPMENT_ECONOMIC_CANDIDATE",
        "generated_at_utc": utc_now(), "candidate_results": results, "shortlist_by_timeframe": shortlist,
        "shortlisted_candidates": selected, "candidate_counts": dict(Counter(row["disposition"] for row in results)),
        "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
    }


def report_markdown(summary: Mapping[str, Any]) -> str:
    lines = ["# Gold Sequential Auction-Confirmation Entry Research V1 — Development", "", f"Status: **{summary['status']}**", "", "## Candidate results", "", "| Candidate | Confirmed/eligible | OOF trades | Win rate | Exp R | PF | CI low | 1.5x exp | PnL $50 | Whole-oz PnL | Verdict |", "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---|"]
    for row in summary["candidate_results"]:
        metric = row["oof_validation_union"]
        lines.append(f"| {row['candidate_id']} | {row['sequence_or_post_sequence_gate_rows']}/{row['entry_eligible_rows']} | {metric['trades']} | {metric['win_rate']} | {metric['net_expectancy_r']} | {metric['profit_factor']} | {row['bootstrap']['ci95_low']} | {metric['net_expectancy_r_cost_1p5x']} | {metric['normalized_pnl_usd']} | {metric['whole_ounce_pnl_usd']} | {row['disposition']} |")
    lines.extend(["", "## Frozen shortlist", "", canonical_json(summary["shortlist_by_timeframe"]), "", "2025 and 2026 remained locked during this development evaluation. GC order flow cannot rescue a rejected base candidate and is evaluated only if this shortlist is non-empty.", ""])
    return "\n".join(lines)


def run_self_test() -> None:
    entry = 2000 * SCALE; stop = 1999 * SCALE; target = 2002 * SCALE
    values = economic_values(entry, stop, target, target, "UP", 0.20, 10)
    if values["gross_r"] != 2.0 or values["net_r"] != 1.8 or values["whole_ounce_pnl_usd"] != 18.0:
        raise ValueError(values)
    sample = [{"cluster_date": "2024-01-01", "net_r": 1.0}, {"cluster_date": "2024-01-02", "net_r": -0.5}]
    first = clustered_bootstrap(sample, "SYNTHETIC"); second = clustered_bootstrap(sample, "SYNTHETIC")
    if first != second:
        raise ValueError("Bootstrap is not deterministic")
    count = 4; timestamps = np.arange(count, dtype=np.int64) * MINUTE_NS
    opens = np.asarray([entry, entry, entry + SCALE, target], dtype=np.int64)
    highs = np.asarray([entry + SCALE // 2, entry + SCALE, target, target], dtype=np.int64)
    lows = np.asarray([entry - SCALE // 2, stop + SCALE // 2, entry, target - SCALE // 2], dtype=np.int64)
    closes = np.asarray([entry, entry + SCALE // 2, target, target], dtype=np.int64)
    prices = anatomy_impl.PriceData(timestamps, opens, highs, lows, closes, np.full(count, 0.2), {}, {})
    primary = stop_impl.scan_primary(prices, 0, count, entry, stop, target, 1)
    reference = stop_impl.scan_reference(prices, 0, count, entry, stop, target, 1)
    if primary != reference or primary["exit_reason"] != "TARGET":
        raise ValueError("Synthetic outcome scanners differ")
    print(json.dumps({"status": "PASS_SYNTHETIC_ECONOMIC_PROOF", "economic": values, "bootstrap_hash": canonical_hash(first), "path_hash": canonical_hash(primary)}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser(); parser.add_argument("--self-test", action="store_true"); args = parser.parse_args()
    if args.self_test:
        run_self_test(); return
    protocol, freeze, implementation = verify_controls()
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError(OUTPUT if OUTPUT.exists() else REPORT)
    OUTPUT.mkdir(parents=True)
    try:
        prices = anatomy_impl.load_price()
        primary_source = pq.read_table(MATERIALIZATION / "primary_sequences.parquet").to_pylist()
        reference_source = pq.read_table(MATERIALIZATION / "reference_sequences.parquet").to_pylist()
        primary_rows = simulate(primary_source, prices, "primary"); reference_rows = simulate(reference_source, prices, "reference")
        attach_overlap(primary_rows); attach_overlap(reference_rows)
        if primary_rows != reference_rows:
            raise ValueError("Independent economic paths differ")
        primary_path = OUTPUT / "primary_economic_rows.parquet"; reference_path = OUTPUT / "reference_economic_rows.parquet"
        write_parquet_exclusive(primary_path, primary_rows); write_parquet_exclusive(reference_path, reference_rows)
        if sha256_file(primary_path) != sha256_file(reference_path):
            raise ValueError("Independent economic Parquet outputs differ")
        summary = summarize(primary_rows, protocol); summary_path = OUTPUT / "development_results.json"
        write_json_exclusive(summary_path, summary)
        report = report_markdown(summary); write_text_exclusive(REPORT, report)
        seal = {
            "version": "GOLD_SEQUENTIAL_AUCTION_CONFIRMATION_ENTRY_V1_DEVELOPMENT_SEAL_1_0", "status": summary["status"], "sealed_at_utc": utc_now(),
            "controls": {"protocol": record(PROTOCOL), "materialization_seal": record(MATERIALIZATION_SEAL), "pre_economic_freeze": record(ECONOMIC_FREEZE), "implementation_freeze": record(IMPLEMENTATION_FREEZE)},
            "artifacts": {"primary_economic_rows": record(primary_path), "reference_economic_rows": record(reference_path), "development_results": record(summary_path), "report": record(REPORT)},
            "result_hash": canonical_hash(summary), "independent_reproduction": True,
            "calendar_2025_values_accessed": False, "calendar_2026_values_accessed": False, "paid_acquisition_usd": 0.0,
        }
        write_json_exclusive(OUTPUT / "development_seal.json", seal)
        print(json.dumps({"status": summary["status"], "candidate_counts": summary["candidate_counts"], "shortlist": summary["shortlisted_candidates"], "seal": record(OUTPUT / "development_seal.json")}, sort_keys=True))
    except Exception:
        if OUTPUT.exists() and not any(OUTPUT.iterdir()):
            OUTPUT.rmdir()
        raise


if __name__ == "__main__":
    main()
