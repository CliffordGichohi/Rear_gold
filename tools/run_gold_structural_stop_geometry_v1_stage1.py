from __future__ import annotations

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


ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_structural_stop_geometry_v1_stage1"
REPORT = ROOT / "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_STAGE1.md"
PROTOCOL = MANIFESTS / "gold_structural_stop_geometry_v1_protocol.json"
FREEZE = MANIFESTS / "gold_structural_stop_geometry_v1_pre_result_freeze.json"
IMPLEMENTATION_FREEZE = MANIFESTS / "gold_structural_stop_geometry_v1_implementation_freeze.json"

ROUTING = ARTIFACTS / "gold_pullback_archetype_setup_routing_v1_r1"
ANATOMY = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
FEATURES = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"

SCALE = 100_000_000
MINUTE_NS = 60_000_000_000
STOP_IDS = (
    "STOP_BASELINE_FROZEN",
    "STOP_CONFIRMATION_EXTREME_0P25_ATR",
    "STOP_PIVOT_0P25_ATR",
    "STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR",
)
TF_PRIORITY = {"H4": 0, "H1": 1, "M15": 2}
OOF_RANGES = (
    (1, "2022-07-01", "2023-03-31"),
    (2, "2023-04-01", "2023-12-31"),
    (3, "2024-01-01", "2024-12-31"),
)


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


def parse_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp()) * 1_000_000_000 + parsed.microsecond * 1_000


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, UTC).isoformat().replace("+00:00", "Z")


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


def verify_controls() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    protocol = json.loads(PROTOCOL.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    implementation = json.loads(IMPLEMENTATION_FREEZE.read_text(encoding="utf-8"))
    if protocol.get("status") != "FROZEN_BEFORE_STOP_PATH_OR_ECONOMIC_RESULTS":
        raise ValueError("Protocol status changed")
    if freeze.get("status") != "FROZEN_READY_FOR_STAGE_1":
        raise ValueError("Pre-result freeze status changed")
    if implementation.get("status") != "FROZEN_BEFORE_STAGE_1_VALUES":
        raise ValueError("Implementation freeze status changed")
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
            raise ValueError("Primary/reference source pair changed")
    if tuple(row["stop_id"] for row in protocol["stop_registry"]) != STOP_IDS:
        raise ValueError("Stop registry changed")
    if protocol.get("calendar_2025_values_accessed_before_freeze") or protocol.get("calendar_2026_values_accessed_before_freeze"):
        raise ValueError("Forward-value lock is not intact")
    return protocol, freeze, implementation


def oof_fold(known_date: str) -> int | None:
    for fold, start, end in OOF_RANGES:
        if start <= known_date <= end:
            return fold
    return None


def iso_week(value: str) -> str:
    year, week, _ = datetime.fromisoformat(value).date().isocalendar()
    return f"{year:04d}-W{week:02d}"


class SwingIndex:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        grouped: dict[tuple[str, str], dict[int, list[dict[str, Any]]]] = defaultdict(lambda: defaultdict(list))
        for source in rows:
            if str(source["scale"]) != "STANDARD":
                continue
            row = dict(source)
            known_ns = parse_ns(str(row["known_at_utc"]))
            row["_known_ns"] = known_ns
            row["_pivot_ns"] = parse_ns(str(row["pivot_at_utc"]))
            grouped[(str(row["timeframe"]), str(row["side"]))][known_ns].append(row)
        self.keys: dict[tuple[str, str], list[int]] = {}
        self.groups: dict[tuple[str, str], list[list[dict[str, Any]]]] = {}
        for key, values in grouped.items():
            timestamps = sorted(values)
            self.keys[key] = timestamps
            self.groups[key] = [
                sorted(values[timestamp], key=lambda row: (-int(row["_pivot_ns"]), str(row["swing_id"])))
                for timestamp in timestamps
            ]

    def latest_adverse(self, timeframe: str, direction: str, entry_ns: int, entry_e8: int) -> dict[str, Any] | None:
        side = "LOWER" if direction == "UP" else "UPPER"
        key = (timeframe, side)
        timestamps = self.keys.get(key, [])
        groups = self.groups.get(key, [])
        position = bisect.bisect_right(timestamps, entry_ns) - 1
        while position >= 0:
            for row in groups[position]:
                price = int(row["price_e8"])
                if (direction == "UP" and price < entry_e8) or (direction == "DOWN" and price > entry_e8):
                    return row
            position -= 1
        return None


def load_inputs(side: str) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], SwingIndex]:
    trades = pq.read_table(ROUTING / f"{side}_model_trades.parquet").to_pylist()
    trades = [dict(row) for row in trades if row["status"] == "EXECUTED"]
    if len(trades) != 22_193 or len({str(row["trade_id"]) for row in trades}) != len(trades):
        raise ValueError(f"Executed trade population changed for {side}")
    facts = pq.read_table(ANATOMY / f"{side}_trigger_facts.parquet").to_pylist()
    fact_map: dict[str, dict[str, Any]] = {}
    component_fields = ("confirmation_high_e8", "confirmation_low_e8", "pivot_price_e8", "atr14_e8")
    by_pullback: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in facts:
        by_pullback[str(row["pullback_id"])].append(dict(row))
    for identity, rows in by_pullback.items():
        signatures = {tuple(row[field] for field in component_fields) for row in rows}
        if len(signatures) != 1:
            raise ValueError(f"Inconsistent structural components: {identity}")
        chosen = next((row for row in rows if row["trigger"] == "IMMEDIATE"), rows[0])
        fact_map[identity] = chosen
    missing = [row["trade_id"] for row in trades if str(row["pullback_id"]) not in fact_map]
    if missing:
        raise ValueError(f"Missing structural facts: {missing[:3]}")
    swings = pq.read_table(CENSUS / f"{side}_swings.parquet").to_pylist()
    return trades, fact_map, SwingIndex(swings)


def model_time_bars(protocol: Mapping[str, Any]) -> dict[str, int]:
    entry_protocol = json.loads((MANIFESTS / "gold_pullback_archetype_setup_routing_v1_protocol.json").read_text(encoding="utf-8"))
    result = {str(row["model_id"]): int(row["time_exit_parent_bars"]) for row in entry_protocol["entry_models"]}
    if len(result) != 6:
        raise ValueError("Entry-model registry changed")
    return result


def stop_geometry(
    trade: Mapping[str, Any],
    fact: Mapping[str, Any],
    swing_index: SwingIndex,
    stop_id: str,
) -> tuple[int | None, str | None, str | None]:
    entry = int(trade["entry_e8"])
    direction = str(trade["trade_direction"])
    sign = 1 if direction == "UP" else -1
    atr = float(fact["atr14_e8"])
    level_id: str | None = None
    if stop_id == "STOP_BASELINE_FROZEN":
        stop = int(trade["stop_e8"])
        level_id = "FROZEN_BASELINE"
    elif stop_id == "STOP_CONFIRMATION_EXTREME_0P25_ATR":
        buffer_e8 = int(round(0.25 * atr))
        stop = int(fact["confirmation_low_e8"]) - buffer_e8 if sign > 0 else int(fact["confirmation_high_e8"]) + buffer_e8
        level_id = "CONFIRMATION_EXTREME"
    elif stop_id == "STOP_PIVOT_0P25_ATR":
        buffer_e8 = int(round(0.25 * atr))
        stop = int(fact["pivot_price_e8"]) - buffer_e8 if sign > 0 else int(fact["pivot_price_e8"]) + buffer_e8
        level_id = "PULLBACK_PIVOT"
    elif stop_id == "STOP_LATEST_KNOWN_OPPOSING_SWING_0P10_ATR":
        selected = swing_index.latest_adverse(
            str(trade["timeframe"]), direction, parse_ns(str(trade["entry_at_utc"])), entry
        )
        if selected is None:
            return None, None, "NO_KNOWN_ADVERSE_STANDARD_SWING"
        buffer_e8 = int(round(0.10 * atr))
        stop = int(selected["price_e8"]) - buffer_e8 if sign > 0 else int(selected["price_e8"]) + buffer_e8
        level_id = str(selected["swing_id"])
    else:
        raise ValueError(stop_id)
    if (sign > 0 and stop >= entry) or (sign < 0 and stop <= entry):
        return None, level_id, "STOP_NOT_ADVERSE_TO_ENTRY"
    return stop, level_id, None


def path_bounds(
    trade: Mapping[str, Any], prices: anatomy_impl.PriceData, time_bars: int, implementation: str
) -> tuple[int, int, int]:
    entry_ns = parse_ns(str(trade["entry_at_utc"]))
    if implementation == "primary":
        entry_index = int(np.searchsorted(prices.open_ns, entry_ns, side="left"))
        parent = prices.parents[str(trade["timeframe"])]
        first_parent = int(np.searchsorted(parent.close_ns, entry_ns, side="right"))
        deadline_parent = first_parent + time_bars - 1
        if deadline_parent >= len(parent.close_ns):
            raise ValueError(f"Missing parent deadline: {trade['trade_id']}")
        deadline_ns = int(parent.close_ns[deadline_parent])
        end_index = int(np.searchsorted(prices.open_ns, deadline_ns, side="left"))
    else:
        entry_index = bisect.bisect_left(prices.open_ns, entry_ns)
        parent_closes = prices.parents[str(trade["timeframe"])].close_ns
        first_parent = bisect.bisect_right(parent_closes, entry_ns)
        deadline_parent = first_parent + time_bars - 1
        if deadline_parent >= len(parent_closes):
            raise ValueError(f"Reference missing parent deadline: {trade['trade_id']}")
        deadline_ns = int(parent_closes[deadline_parent])
        end_index = bisect.bisect_left(prices.open_ns, deadline_ns)
    if entry_index >= len(prices.open_ns) or int(prices.open_ns[entry_index]) != entry_ns:
        raise ValueError(f"Missing exact entry minute: {trade['trade_id']}")
    if end_index <= entry_index or int(prices.open_ns[end_index - 1]) + MINUTE_NS != deadline_ns:
        raise ValueError(f"Incomplete frozen path: {trade['trade_id']}")
    return entry_index, end_index, deadline_ns


def scan_primary(
    prices: anatomy_impl.PriceData, entry_index: int, end_index: int, entry: int, stop: int, target: int, sign: int
) -> dict[str, Any]:
    opens = prices.open_e8[entry_index:end_index]
    highs = prices.high_e8[entry_index:end_index]
    lows = prices.low_e8[entry_index:end_index]
    closes = prices.close_e8[entry_index:end_index]
    favourable = highs - entry if sign > 0 else entry - lows
    adverse = entry - lows if sign > 0 else highs - entry
    stop_hits = np.flatnonzero(lows <= stop if sign > 0 else highs >= stop)
    target_hits = np.flatnonzero(highs >= target if sign > 0 else lows <= target)
    first_stop = int(stop_hits[0]) if len(stop_hits) else None
    first_target = int(target_hits[0]) if len(target_hits) else None
    full_mfe_e8 = max(0, int(np.max(favourable)))
    full_mae_e8 = max(0, int(np.max(adverse)))
    mfe_offset = int(np.argmax(favourable)) if full_mfe_e8 > 0 else 0
    if first_stop is not None and (first_target is None or first_stop <= first_target):
        exit_offset = first_stop
        exit_reason = "STOP"
        exit_e8 = min(stop, int(opens[exit_offset])) if sign > 0 else max(stop, int(opens[exit_offset]))
    elif first_target is not None:
        exit_offset = first_target
        exit_reason = "TARGET"
        exit_e8 = target
    else:
        exit_offset = len(opens) - 1
        exit_reason = "TIME"
        exit_e8 = int(closes[exit_offset])
    used_favourable = favourable[: exit_offset + 1]
    used_adverse = adverse[: exit_offset + 1]
    return {
        "first_stop_offset": first_stop,
        "first_target_offset": first_target,
        "global_mfe_offset": mfe_offset,
        "full_mfe_e8": full_mfe_e8,
        "full_mae_e8": full_mae_e8,
        "exit_mfe_e8": max(0, int(np.max(used_favourable))),
        "exit_mae_e8": max(0, int(np.max(used_adverse))),
        "exit_offset": exit_offset,
        "exit_reason": exit_reason,
        "exit_e8": exit_e8,
    }


def scan_reference(
    prices: anatomy_impl.PriceData, entry_index: int, end_index: int, entry: int, stop: int, target: int, sign: int
) -> dict[str, Any]:
    first_stop = first_target = None
    full_mfe_e8 = full_mae_e8 = 0
    mfe_offset = 0
    for offset, index in enumerate(range(entry_index, end_index)):
        high = int(prices.high_e8[index])
        low = int(prices.low_e8[index])
        favourable = high - entry if sign > 0 else entry - low
        adverse = entry - low if sign > 0 else high - entry
        if favourable > full_mfe_e8:
            full_mfe_e8 = favourable
            mfe_offset = offset
        full_mae_e8 = max(full_mae_e8, adverse)
        if first_stop is None and (low <= stop if sign > 0 else high >= stop):
            first_stop = offset
        if first_target is None and (high >= target if sign > 0 else low <= target):
            first_target = offset
    if first_stop is not None and (first_target is None or first_stop <= first_target):
        exit_offset = first_stop
        exit_reason = "STOP"
        open_e8 = int(prices.open_e8[entry_index + exit_offset])
        exit_e8 = min(stop, open_e8) if sign > 0 else max(stop, open_e8)
    elif first_target is not None:
        exit_offset = first_target
        exit_reason = "TARGET"
        exit_e8 = target
    else:
        exit_offset = end_index - entry_index - 1
        exit_reason = "TIME"
        exit_e8 = int(prices.close_e8[entry_index + exit_offset])
    exit_mfe_e8 = exit_mae_e8 = 0
    for index in range(entry_index, entry_index + exit_offset + 1):
        high = int(prices.high_e8[index])
        low = int(prices.low_e8[index])
        exit_mfe_e8 = max(exit_mfe_e8, high - entry if sign > 0 else entry - low)
        exit_mae_e8 = max(exit_mae_e8, entry - low if sign > 0 else high - entry)
    return {
        "first_stop_offset": first_stop,
        "first_target_offset": first_target,
        "global_mfe_offset": mfe_offset,
        "full_mfe_e8": max(0, full_mfe_e8),
        "full_mae_e8": max(0, full_mae_e8),
        "exit_mfe_e8": max(0, exit_mfe_e8),
        "exit_mae_e8": max(0, exit_mae_e8),
        "exit_offset": exit_offset,
        "exit_reason": exit_reason,
        "exit_e8": exit_e8,
    }


def materialize(
    side: str, implementation: str, prices: anatomy_impl.PriceData, protocol: Mapping[str, Any]
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    trades, facts, swing_index = load_inputs(side)
    deadlines = model_time_bars(protocol)
    scanner = scan_primary if implementation == "primary" else scan_reference
    output: list[dict[str, Any]] = []
    baseline_mismatches: list[str] = []
    spread_mismatches: list[str] = []
    for trade in sorted(
        trades,
        key=lambda row: (
            str(row["entry_at_utc"]),
            TF_PRIORITY[str(row["timeframe"])],
            int(row["model_rank"]),
            str(row["trade_id"]),
        ),
    ):
        fact = facts[str(trade["pullback_id"])]
        if int(fact["pivot_price_e8"]) <= 0 or float(fact["atr14_e8"]) <= 0:
            raise ValueError(f"Invalid point-in-time structural fact: {trade['trade_id']}")
        entry_index, end_index, deadline_ns = path_bounds(
            trade, prices, deadlines[str(trade["model_id"])], implementation
        )
        baseline_risk_usd_oz = abs(int(trade["entry_e8"]) - int(trade["stop_e8"])) / SCALE
        total_cost = round(float(trade["cost_r"]) * baseline_risk_usd_oz, 8)
        spread = float(prices.spread[entry_index])
        observed_cost = (0.30 if not math.isfinite(spread) or spread < 0 else spread) + 0.07 + 0.10
        if abs(total_cost - observed_cost) > 1e-8:
            spread_mismatches.append(str(trade["trade_id"]))
        for stop_id in STOP_IDS:
            stop, level_id, unavailable = stop_geometry(trade, fact, swing_index, stop_id)
            known_date = str(trade["known_at_utc"])[:10]
            fold = oof_fold(known_date)
            base = {
                "trade_id": str(trade["trade_id"]),
                "stop_row_id": canonical_hash([str(trade["trade_id"]), stop_id]),
                "pullback_id": str(trade["pullback_id"]),
                "timeframe": str(trade["timeframe"]),
                "model_id": str(trade["model_id"]),
                "archetype": str(trade["archetype"]),
                "trade_direction": str(trade["trade_direction"]),
                "session_state": str(trade["session_state"]),
                "known_at_utc": str(trade["known_at_utc"]),
                "entry_at_utc": str(trade["entry_at_utc"]),
                "cluster_date": str(trade["cluster_date"]),
                "calendar_year": int(trade["calendar_year"]),
                "iso_week": iso_week(str(trade["cluster_date"])),
                "oof_fold": fold,
                "is_oof_validation": fold is not None,
                "stop_id": stop_id,
                "stop_level_id": level_id,
                "stop_status": "AVAILABLE" if unavailable is None else "STOP_UNAVAILABLE",
                "unavailable_reason": unavailable or "",
                "entry_e8": int(trade["entry_e8"]),
                "stop_e8": stop,
                "target_e8": int(trade["target_e8"]),
                "deadline_at_utc": ns_iso(deadline_ns),
                "atr14_e8": float(fact["atr14_e8"]),
                "total_cost_usd_oz": rounded(total_cost),
                "stop_distance_usd_oz": None,
                "stop_distance_atr": None,
                "planned_ounces": None,
                "one_ounce_feasible": False,
                "first_stop_offset": None,
                "first_target_offset": None,
                "global_mfe_offset": None,
                "stop_hit_full_horizon": None,
                "stop_before_or_same_as_global_mfe": None,
                "stop_first": None,
                "target_first": None,
                "time_first": None,
                "exit_reason": None,
                "exit_at_utc": None,
                "exit_e8": None,
                "full_horizon_mfe_r": None,
                "full_horizon_mae_r": None,
                "exit_mfe_r": None,
                "exit_mae_r": None,
                "path_minutes": end_index - entry_index,
            }
            if unavailable is not None or stop is None:
                output.append(base)
                continue
            entry = int(trade["entry_e8"])
            target = int(trade["target_e8"])
            sign = 1 if str(trade["trade_direction"]) == "UP" else -1
            risk_e8 = abs(entry - stop)
            result = scanner(prices, entry_index, end_index, entry, stop, target, sign)
            risk_usd_oz = risk_e8 / SCALE
            ounces = math.floor((50.0 / (risk_usd_oz + total_cost)) + 1e-12)
            exit_index = entry_index + int(result["exit_offset"])
            base.update(
                {
                    "stop_distance_usd_oz": rounded(risk_usd_oz),
                    "stop_distance_atr": rounded(risk_e8 / float(fact["atr14_e8"])),
                    "planned_ounces": ounces,
                    "one_ounce_feasible": ounces >= 1,
                    "first_stop_offset": result["first_stop_offset"],
                    "first_target_offset": result["first_target_offset"],
                    "global_mfe_offset": result["global_mfe_offset"],
                    "stop_hit_full_horizon": result["first_stop_offset"] is not None,
                    "stop_before_or_same_as_global_mfe": result["first_stop_offset"] is not None
                    and int(result["first_stop_offset"]) <= int(result["global_mfe_offset"]),
                    "stop_first": result["exit_reason"] == "STOP",
                    "target_first": result["exit_reason"] == "TARGET",
                    "time_first": result["exit_reason"] == "TIME",
                    "exit_reason": result["exit_reason"],
                    "exit_at_utc": ns_iso(int(prices.open_ns[exit_index]) + MINUTE_NS),
                    "exit_e8": int(result["exit_e8"]),
                    "full_horizon_mfe_r": rounded(int(result["full_mfe_e8"]) / risk_e8),
                    "full_horizon_mae_r": rounded(int(result["full_mae_e8"]) / risk_e8),
                    "exit_mfe_r": rounded(int(result["exit_mfe_e8"]) / risk_e8),
                    "exit_mae_r": rounded(int(result["exit_mae_e8"]) / risk_e8),
                }
            )
            if stop_id == "STOP_BASELINE_FROZEN":
                computed_gross = sign * (int(result["exit_e8"]) - entry) / risk_e8
                computed_net = computed_gross - total_cost / risk_usd_oz
                mismatch = (
                    base["exit_reason"] != trade["exit_reason"]
                    or base["exit_at_utc"] != trade["exit_at_utc"]
                    or int(base["exit_e8"]) != int(trade["exit_e8"])
                    or abs(computed_gross - float(trade["gross_r"])) > 5e-12
                    or abs(computed_net - float(trade["net_r"])) > 5e-10
                )
                if mismatch:
                    baseline_mismatches.append(str(trade["trade_id"]))
            output.append(base)
    diagnostics = {
        "implementation": implementation,
        "executed_entry_rows": len(trades),
        "stop_rows": len(output),
        "stop_status_counts": dict(sorted(Counter(str(row["stop_status"]) for row in output).items())),
        "unavailable_reason_counts": dict(
            sorted(Counter(str(row["unavailable_reason"]) for row in output if row["unavailable_reason"]).items())
        ),
        "baseline_replay_mismatches": len(baseline_mismatches),
        "baseline_replay_mismatch_examples": baseline_mismatches[:10],
        "entry_cost_source_mismatches": len(spread_mismatches),
        "entry_cost_source_mismatch_examples": spread_mismatches[:10],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
    }
    if len(output) != 88_772:
        raise ValueError(f"Stop-row population changed: {len(output)}")
    if baseline_mismatches or spread_mismatches:
        raise ValueError(f"Frozen baseline replay failed: exits={len(baseline_mismatches)}, costs={len(spread_mismatches)}")
    return output, diagnostics


def rate(rows: Sequence[Mapping[str, Any]], field: str) -> float | None:
    values = [bool(row[field]) for row in rows if row.get(field) is not None]
    return rounded(sum(values) / len(values)) if values else None


def quantile(values: Sequence[float], probability: float) -> float | None:
    if not values:
        return None
    return rounded(float(np.quantile(np.asarray(values, dtype=float), probability, method="linear")))


def survival_metrics(rows: Sequence[Mapping[str, Any]], population: int) -> dict[str, Any]:
    valid = [row for row in rows if row["stop_status"] == "AVAILABLE"]
    feasible = [row for row in valid if bool(row["one_ounce_feasible"])]
    distances_usd = [float(row["stop_distance_usd_oz"]) for row in feasible]
    distances_atr = [float(row["stop_distance_atr"]) for row in feasible]
    return {
        "population": population,
        "valid_stops": len(valid),
        "valid_stop_coverage": rounded(len(valid) / population) if population else None,
        "one_ounce_feasible": len(feasible),
        "one_ounce_coverage": rounded(len(feasible) / population) if population else None,
        "trading_dates": len({str(row["cluster_date"]) for row in feasible}),
        "iso_weeks": len({str(row["iso_week"]) for row in feasible}),
        "stop_distance_usd_oz_mean": rounded(statistics.fmean(distances_usd)) if distances_usd else None,
        "stop_distance_usd_oz_median": quantile(distances_usd, 0.5),
        "stop_distance_usd_oz_q90": quantile(distances_usd, 0.9),
        "stop_distance_atr_mean": rounded(statistics.fmean(distances_atr)) if distances_atr else None,
        "stop_distance_atr_median": quantile(distances_atr, 0.5),
        "stop_distance_atr_q90": quantile(distances_atr, 0.9),
        "stop_hit_full_horizon_rate": rate(feasible, "stop_hit_full_horizon"),
        "stop_before_global_mfe_rate": rate(feasible, "stop_before_or_same_as_global_mfe"),
        "stop_first_rate": rate(feasible, "stop_first"),
        "target_first_rate": rate(feasible, "target_first"),
        "time_first_rate": rate(feasible, "time_first"),
        "full_horizon_mfe_r_mean": rounded(statistics.fmean(float(row["full_horizon_mfe_r"]) for row in feasible)) if feasible else None,
        "full_horizon_mae_r_mean": rounded(statistics.fmean(float(row["full_horizon_mae_r"]) for row in feasible)) if feasible else None,
        "exit_mfe_r_mean": rounded(statistics.fmean(float(row["exit_mfe_r"]) for row in feasible)) if feasible else None,
        "exit_mae_r_mean": rounded(statistics.fmean(float(row["exit_mae_r"]) for row in feasible)) if feasible else None,
        "unavailable_reasons": dict(
            sorted(Counter(str(row["unavailable_reason"]) for row in rows if row["unavailable_reason"]).items())
        ),
    }


def summarize(rows: Sequence[Mapping[str, Any]], protocol: Mapping[str, Any]) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        grouped[(str(row["timeframe"]), str(row["model_id"]), str(row["stop_id"]))].append(row)
    cells: list[dict[str, Any]] = []
    for key in sorted(grouped, key=lambda item: (TF_PRIORITY[item[0]], item[1], item[2])):
        values = grouped[key]
        full_population = len(values)
        oof_values = [row for row in values if bool(row["is_oof_validation"])]
        full = survival_metrics(values, full_population)
        oof = survival_metrics(oof_values, len(oof_values))
        cells.append({"timeframe": key[0], "model_id": key[1], "stop_id": key[2], "full_development": full, "oof_validation_union": oof})

    by_key = {(row["timeframe"], row["model_id"], row["stop_id"]): row for row in cells}
    gate_rows: list[dict[str, Any]] = []
    floors = protocol["support_floors"]
    gates = protocol["stage1_gates"]
    for cell in cells:
        tf = str(cell["timeframe"])
        model = str(cell["model_id"])
        stop_id = str(cell["stop_id"])
        metric = cell["oof_validation_union"]
        rows_for_stop = grouped[(tf, model, stop_id)]
        paired = [row for row in rows_for_stop if bool(row["is_oof_validation"]) and row["stop_status"] == "AVAILABLE" and bool(row["one_ounce_feasible"])]
        paired_ids = {str(row["trade_id"]) for row in paired}
        baseline_rows = [
            row
            for row in grouped[(tf, model, "STOP_BASELINE_FROZEN")]
            if bool(row["is_oof_validation"]) and str(row["trade_id"]) in paired_ids
        ]
        base_stop_rate = rate(baseline_rows, "stop_before_or_same_as_global_mfe")
        alt_stop_rate = rate(paired, "stop_before_or_same_as_global_mfe")
        base_target_rate = rate(baseline_rows, "target_first")
        alt_target_rate = rate(paired, "target_first")
        improvement_pp = rounded(100 * (float(base_stop_rate) - float(alt_stop_rate))) if base_stop_rate is not None and alt_stop_rate is not None else None
        checks = {
            "valid_stop_coverage": metric["valid_stop_coverage"] is not None and float(metric["valid_stop_coverage"]) >= float(gates["valid_stop_coverage_gte"]),
            "one_ounce_coverage": metric["one_ounce_coverage"] is not None and float(metric["one_ounce_coverage"]) >= float(gates["one_ounce_coverage_gte"]),
            "trade_support": int(metric["one_ounce_feasible"]) >= int(floors[tf]["trades"]),
            "date_support": int(metric["trading_dates"]) >= int(floors[tf]["dates"]),
            "week_support": int(metric["iso_weeks"]) >= int(floors[tf]["weeks"]),
            "stop_before_mfe_improvement": improvement_pp is not None and float(improvement_pp) >= float(gates["stop_before_global_mfe_improvement_pp_gte"]),
            "target_first_not_lower": base_target_rate is not None and alt_target_rate is not None and float(alt_target_rate) >= float(base_target_rate),
            "median_stop_distance_atr": metric["stop_distance_atr_median"] is not None and float(metric["stop_distance_atr_median"]) <= float(gates["median_stop_distance_atr_lte"]),
            "q90_stop_distance_atr": metric["stop_distance_atr_q90"] is not None and float(metric["stop_distance_atr_q90"]) <= float(gates["q90_stop_distance_atr_lte"]),
        }
        is_baseline = stop_id == "STOP_BASELINE_FROZEN"
        eligible = is_baseline or all(checks.values())
        gate_rows.append(
            {
                "candidate_id": f"{tf}|{model}|{stop_id}",
                "timeframe": tf,
                "model_id": model,
                "stop_id": stop_id,
                "control": is_baseline,
                "paired_rows": len(paired),
                "paired_baseline_stop_before_mfe_rate": base_stop_rate,
                "candidate_stop_before_mfe_rate": alt_stop_rate,
                "stop_before_mfe_improvement_pp": improvement_pp,
                "paired_baseline_target_first_rate": base_target_rate,
                "candidate_target_first_rate": alt_target_rate,
                "checks": checks,
                "failed_gates": [] if is_baseline else [name for name, passed in checks.items() if not passed],
                "stage1_disposition": "CONTROL_ADVANCES_TO_ECONOMICS" if is_baseline else "PASS_STAGE1" if eligible else "REJECT_STAGE1",
                "advances_to_economics": eligible,
            }
        )

    archetype_cells: list[dict[str, Any]] = []
    by_archetype: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        by_archetype[(str(row["timeframe"]), str(row["model_id"]), str(row["stop_id"]), str(row["archetype"]))].append(row)
    for key in sorted(by_archetype, key=lambda item: (TF_PRIORITY[item[0]], item[1], item[2], item[3])):
        values = by_archetype[key]
        oof_values = [row for row in values if bool(row["is_oof_validation"])]
        archetype_cells.append(
            {
                "timeframe": key[0],
                "model_id": key[1],
                "stop_id": key[2],
                "archetype": key[3],
                "full_development": survival_metrics(values, len(values)),
                "oof_validation_union": survival_metrics(oof_values, len(oof_values)),
            }
        )
    return {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_STAGE1_RESULT_1_0",
        "status": "PASS_STAGE1_INDEPENDENT_REPRODUCTION",
        "entry_rows": len({str(row["trade_id"]) for row in rows}),
        "stop_rows": len(rows),
        "primary_stop_geometries": len(STOP_IDS),
        "timeframe_model_stop_results": cells,
        "stage1_gate_results": gate_rows,
        "timeframe_model_stop_archetype_results": archetype_cells,
        "advancing_alternatives": [row["candidate_id"] for row in gate_rows if not row["control"] and row["advances_to_economics"]],
        "rejected_alternatives": [row["candidate_id"] for row in gate_rows if not row["control"] and not row["advances_to_economics"]],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }


def report_text(summary: Mapping[str, Any]) -> str:
    gate_rows = summary["stage1_gate_results"]
    advancing = [row for row in gate_rows if not row["control"] and row["advances_to_economics"]]
    rejected = [row for row in gate_rows if not row["control"] and not row["advances_to_economics"]]
    lines = [
        "# Gold Structural Stop Geometry V1 — Stage 1",
        "",
        f"Status: **{summary['status']}**",
        "",
        "## Result",
        "",
        f"- Unchanged executed entries: **{summary['entry_rows']:,}**",
        f"- Trade–stop paths: **{summary['stop_rows']:,}**",
        f"- Alternative model–stop cells passing survival gates: **{len(advancing)} / {len(advancing) + len(rejected)}**",
        f"- Alternative model–stop cells rejected before economics: **{len(rejected)}**",
        "- Frozen baseline exits and entry costs reproduced with zero mismatches in both implementations.",
        "- 2025/2026 values remained locked; acquisition cost was $0.00.",
        "",
        "## Stage-1 dispositions",
        "",
        "| Timeframe | Model | Stop | Paired N | Stop-before-MFE improvement | Target-first Δ | Disposition | Failed gates |",
        "|---|---|---|---:|---:|---:|---|---|",
    ]
    for row in gate_rows:
        if row["control"]:
            continue
        improvement = row["stop_before_mfe_improvement_pp"]
        target_delta = None
        if row["paired_baseline_target_first_rate"] is not None and row["candidate_target_first_rate"] is not None:
            target_delta = 100 * (float(row["candidate_target_first_rate"]) - float(row["paired_baseline_target_first_rate"]))
        lines.append(
            f"| {row['timeframe']} | {row['model_id']} | {row['stop_id']} | {row['paired_rows']:,} | "
            f"{('NA' if improvement is None else f'{float(improvement):.2f} pp')} | "
            f"{('NA' if target_delta is None else f'{target_delta:.2f} pp')} | {row['stage1_disposition']} | "
            f"{', '.join(row['failed_gates']) or '—'} |"
        )
    lines.extend(
        [
            "",
            "## Interpretation",
            "",
            "Stage 1 asks only whether a point-in-time stop survives the unchanged path better without degrading target-first passage or becoming impractically wide. Passing here is not an economic edge; it only authorizes Stage 2 testing under the frozen costs, sizing, overlap, uncertainty and stability gates.",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    if OUTPUT.exists() or REPORT.exists():
        raise FileExistsError("Stage-1 output already exists")
    protocol, freeze, implementation_freeze = verify_controls()
    OUTPUT.mkdir(parents=True)
    prices = anatomy_impl.load_price()
    if prices.diagnostics["last_m1_open"] >= "2025-01-01T00:00:00Z":
        raise ValueError("Development price loader exposed a forward value")

    primary_rows, primary_diagnostics = materialize("primary", "primary", prices, protocol)
    primary_summary = summarize(primary_rows, protocol)
    primary_path = OUTPUT / "primary_survival_rows.parquet"
    primary_summary_path = OUTPUT / "primary_stage1_summary.json"
    write_parquet_exclusive(primary_path, primary_rows)
    write_json_exclusive(primary_summary_path, primary_summary)
    del primary_rows

    reference_rows, reference_diagnostics = materialize("reference", "reference", prices, protocol)
    reference_summary = summarize(reference_rows, protocol)
    reference_path = OUTPUT / "reference_survival_rows.parquet"
    reference_summary_path = OUTPUT / "reference_stage1_summary.json"
    write_parquet_exclusive(reference_path, reference_rows)
    write_json_exclusive(reference_summary_path, reference_summary)
    del reference_rows

    if sha256_file(primary_path) != sha256_file(reference_path):
        raise ValueError("Primary/reference Stage-1 Parquet outputs differ")
    if sha256_file(primary_summary_path) != sha256_file(reference_summary_path):
        raise ValueError("Primary/reference Stage-1 summaries differ")
    if primary_diagnostics["baseline_replay_mismatches"] or reference_diagnostics["baseline_replay_mismatches"]:
        raise ValueError("Baseline replay gate failed")

    report = report_text(primary_summary)
    write_text_exclusive(REPORT, report)
    diagnostics_path = OUTPUT / "technical_diagnostics.json"
    write_json_exclusive(
        diagnostics_path,
        {
            "primary": primary_diagnostics,
            "reference": reference_diagnostics,
            "price": prices.diagnostics,
            "primary_reference_parquet_byte_identical": True,
            "primary_reference_summary_byte_identical": True,
        },
    )
    seal_path = OUTPUT / "stage1_seal.json"
    seal = {
        "version": "GOLD_STRUCTURAL_STOP_GEOMETRY_V1_STAGE1_SEAL_1_0",
        "status": "PASS_STAGE1_INDEPENDENT_REPRODUCTION",
        "sealed_at_utc": utc_now(),
        "predecessor_freeze": record(FREEZE),
        "protocol": record(PROTOCOL),
        "implementation_freeze": record(IMPLEMENTATION_FREEZE),
        "artifacts": {
            "primary_survival_rows": record(primary_path),
            "reference_survival_rows": record(reference_path),
            "primary_summary": record(primary_summary_path),
            "reference_summary": record(reference_summary_path),
            "diagnostics": record(diagnostics_path),
            "report": record(REPORT),
        },
        "result_hash": canonical_hash(primary_summary),
        "entry_rows": primary_summary["entry_rows"],
        "stop_rows": primary_summary["stop_rows"],
        "advancing_alternatives": primary_summary["advancing_alternatives"],
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(seal_path, seal)
    print(
        json.dumps(
            {
                "status": seal["status"],
                "entry_rows": seal["entry_rows"],
                "stop_rows": seal["stop_rows"],
                "advancing_alternatives": len(seal["advancing_alternatives"]),
                "seal": record(seal_path),
            },
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
