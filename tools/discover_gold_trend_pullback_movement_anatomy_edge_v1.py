from __future__ import annotations

import hashlib
import bisect
import json
import math
import os
import statistics
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
import materialize_gold_trend_pullback_movement_anatomy_edge_v1 as anatomy_impl  # noqa: E402

ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
EDGE = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_MOVEMENT_ANATOMY_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_protocol.json"
FREEZE = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_design_freeze.json"
PRETEST = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_pretest_seal.json"
ANATOMY = OUTPUT / "primary_movement_anatomy.parquet"
REFERENCE_ANATOMY = OUTPUT / "reference_movement_anatomy.parquet"
TRIGGER_FACTS = OUTPUT / "primary_trigger_facts.parquet"
REFERENCE_TRIGGER_FACTS = OUTPUT / "reference_trigger_facts.parquet"

GRID_PRIMARY = OUTPUT / "primary_complete_execution_grid.parquet"
GRID_REFERENCE = OUTPUT / "reference_complete_execution_grid.parquet"
SELECTIONS = OUTPUT / "walk_forward_training_selections.json"
OOF_TRADES_PRIMARY = OUTPUT / "primary_oof_trades.parquet"
OOF_TRADES_REFERENCE = OUTPUT / "reference_oof_trades.parquet"
OOF_RESULTS_PRIMARY = OUTPUT / "primary_oof_candidate_results.json"
OOF_RESULTS_REFERENCE = OUTPUT / "reference_oof_candidate_results.json"
ATLAS = OUTPUT / "movement_anatomy_atlas.json"
FROZEN_CANDIDATES = OUTPUT / "frozen_development_candidates.json"
REPORT = ROOT / "GOLD_TREND_PULLBACK_MOVEMENT_ANATOMY_EDGE_V1_DEVELOPMENT.md"
DEVELOPMENT_SEAL = OUTPUT / "development_discovery_seal.json"
STATE = OUTPUT / "state_m3.json"
MATRIX_CHECKPOINTS = {timeframe: OUTPUT / f"trade_matrix_checkpoint_{timeframe.lower()}.npz" for timeframe in ("M15", "H1", "H4")}

SCALE = anatomy_impl.SCALE
NY = ZoneInfo("America/New_York")
TRIGGERS = anatomy_impl.TRIGGERS
STOPS = ["PIVOT_BUFFER_0P05_ATR", "PIVOT_BUFFER_0P15_ATR", "CONFIRMATION_EXTREME_BUFFER_0P05_ATR"]
TARGETS = ["FIXED_1P0_R", "FIXED_1P5_R", "FIXED_2P0_R", "NEAREST_KNOWN_SWING"]
TIMES = [4, 8, 16]
TIMEFRAMES = ["M15", "H1", "H4"]
SWING_PRICE_INDEX: dict[str, list[int]] = {}
SWING_TARGET_CACHE: dict[tuple[str, str], tuple[int | None, str | None]] = {}
FOLDS = [
    (1, "2021-08-01", "2022-06-30", "2022-07-01", "2023-03-31"),
    (2, "2021-08-01", "2023-03-31", "2023-04-01", "2023-12-31"),
    (3, "2021-08-01", "2023-12-31", "2024-01-01", "2024-12-31"),
]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while block := handle.read(1 << 20):
            digest.update(block)
    return digest.hexdigest()


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    output = round(float(value), 12)
    return 0.0 if output == 0 else output


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
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
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows))
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=16_384)
    temporary.replace(path)


def save_matrix_checkpoint(path: Path, timeframe: str, cases: Sequence[Mapping[str, Any]], matrices: Sequence[np.ndarray]) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("wb") as handle:
        np.savez(
            handle,
            timeframe=np.asarray([timeframe]),
            case_ids=np.asarray([str(case["pullback_id"]) for case in cases]),
            pretest_sha256=np.asarray([sha256_file(PRETEST)]),
            net=matrices[0], stress=matrices[1], pnl=matrices[2], gross=matrices[3],
        )
    temporary.replace(path)


def load_matrix_checkpoint(path: Path, timeframe: str, cases: Sequence[Mapping[str, Any]]) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    with np.load(path, allow_pickle=False) as payload:
        if str(payload["timeframe"][0]) != timeframe or str(payload["pretest_sha256"][0]) != sha256_file(PRETEST):
            raise ValueError(f"Matrix checkpoint lineage changed: {timeframe}")
        case_ids = [str(value) for value in payload["case_ids"].tolist()]
        if case_ids != [str(case["pullback_id"]) for case in cases]:
            raise ValueError(f"Matrix checkpoint cases changed: {timeframe}")
        matrices = tuple(np.array(payload[name], copy=True) for name in ("net", "stress", "pnl", "gross"))
    expected_shape = (len(cases), len(full_specs()))
    if any(matrix.shape != expected_shape for matrix in matrices):
        raise ValueError(f"Matrix checkpoint shape changed: {timeframe}")
    return matrices  # type: ignore[return-value]


def verify_pretest() -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8")); pretest = json.loads(PRETEST.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_BEFORE_NEW_MOVEMENT_ANATOMY_ACCESS" or pretest["status"] != "SEALED_MOVEMENT_ANATOMY_AND_TRIGGER_POPULATION_BEFORE_GRID_TEST":
        raise ValueError("Predecessor state invalid")
    for item in pretest.values():
        if isinstance(item, Mapping) and {"path", "bytes", "sha256"}.issubset(item):
            path = ROOT / str(item["path"])
            if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
                raise ValueError(f"Pretest artifact changed: {item['path']}")
    if sha256_file(ANATOMY) != sha256_file(REFERENCE_ANATOMY) or sha256_file(TRIGGER_FACTS) != sha256_file(REFERENCE_TRIGGER_FACTS):
        raise ValueError("Primary/reference anatomy sources differ")
    return freeze, pretest


def condition_state(candidate_id: str, row: Mapping[str, Any]) -> bool:
    condition = candidate_id.split("|", 2)[2]
    if condition == "RESPONSE_DISPLACEMENT_HALF_ATR":
        return row.get("response_displacement_atr") is not None and float(row["response_displacement_atr"]) >= 0.5
    if condition == "CONFIRMATION_DISPLACEMENT":
        return row.get("confirmation_displacement") is True
    if condition == "REFERENCE_SWEEP_RECLAIM":
        return row.get("reference_sweep_reclaim") is True
    if condition == "REFERENCE_SWEEP_RECLAIM__CONFIRMATION_DISPLACEMENT":
        return row.get("reference_sweep_reclaim") is True and row.get("confirmation_displacement") is True
    if condition == "HTF_FULL_ALIGNMENT":
        known = int(row.get("higher_timeframe_known_count") or 0)
        return known >= 2 and int(row["higher_timeframe_alignment_count"]) == known
    raise ValueError(f"Unknown frozen condition: {condition}")


def load_cases(freeze: Mapping[str, Any]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, dict[str, Any]], dict[str, set[str]]]:
    anatomy = {str(row["pullback_id"]): row for row in pq.read_table(ANATOMY).to_pylist()}
    features = pq.read_table(EDGE / "primary_features.parquet").to_pylist()
    census = {str(row["pullback_id"]): row for row in pq.read_table(CENSUS / "primary_pullback_cases.parquet").to_pylist()}
    by_tf: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in TIMEFRAMES}
    feature_map: dict[str, dict[str, Any]] = {}
    for feature in features:
        pullback_id = str(feature["pullback_id"])
        if pullback_id not in anatomy:
            continue
        case = census[pullback_id]
        row = dict(feature)
        row.update({"pivot_price_e8": int(case["pivot_price_e8"]), "reference_level_e8": int(case["reference_level_e8"]), "resolution": case["resolution"]})
        feature_map[pullback_id] = row; by_tf[str(row["timeframe"])].append(row)
    for values in by_tf.values():
        values.sort(key=lambda row: (row["known_at_utc"], row["pullback_id"]))
    expected = {"M15": 6633, "H1": 1576, "H4": 444}
    if {key: len(value) for key, value in by_tf.items()} != expected:
        raise ValueError("Case universe changed")
    memberships: dict[str, set[str]] = {}
    expected_counts = {
        "M15|S1|RESPONSE_DISPLACEMENT_HALF_ATR": 2530,
        "M15|S1|CONFIRMATION_DISPLACEMENT": 743,
        "M15|S2|REFERENCE_SWEEP_RECLAIM__CONFIRMATION_DISPLACEMENT": 432,
        "H1|S1|RESPONSE_DISPLACEMENT_HALF_ATR": 548,
        "H1|S1|CONFIRMATION_DISPLACEMENT": 149,
        "H1|S1|REFERENCE_SWEEP_RECLAIM": 464,
        "H4|S1|RESPONSE_DISPLACEMENT_HALF_ATR": 151,
        "H4|S1|REFERENCE_SWEEP_RECLAIM": 123,
        "H4|S1|HTF_FULL_ALIGNMENT": 187,
    }
    for candidate_id in freeze["predecessor_candidate_ids"]:
        timeframe = candidate_id.split("|", 1)[0]
        memberships[candidate_id] = {str(row["pullback_id"]) for row in by_tf[timeframe] if condition_state(candidate_id, row)}
        if len(memberships[candidate_id]) != expected_counts[candidate_id]:
            raise ValueError(f"Candidate membership changed: {candidate_id}")
    return by_tf, feature_map, memberships


def load_trigger_map() -> dict[tuple[str, str], dict[str, Any]]:
    rows = pq.read_table(TRIGGER_FACTS).to_pylist()
    output = {(str(row["pullback_id"]), str(row["trigger"])): row for row in rows}
    if len(output) != len(rows):
        raise ValueError("Duplicate trigger identity")
    return output


def load_target_registry() -> tuple[dict[str, list[dict[str, Any]]], dict[str, datetime]]:
    swing_columns = ["swing_id", "timeframe", "scale", "side", "known_at_utc", "price_e8", "evidence_hash"]
    event_columns = ["event_at_utc", "broken_swing_ids_json"]
    swings = pq.read_table(CENSUS / "primary_swings.parquet", columns=swing_columns).to_pylist()
    events = pq.read_table(CENSUS / "primary_structure_events.parquet", columns=event_columns).to_pylist()
    broken_at: dict[str, datetime] = {}
    for event in sorted(events, key=lambda row: row["event_at_utc"]):
        when = parse_dt(str(event["event_at_utc"]))
        for swing_id in json.loads(str(event["broken_swing_ids_json"])):
            broken_at.setdefault(str(swing_id), when)
    by_tf: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for swing in swings:
        if swing["scale"] != "STANDARD" or swing["timeframe"] not in TIMEFRAMES:
            continue
        item = dict(swing); item["known_dt"] = parse_dt(str(item["known_at_utc"])); by_tf[str(item["timeframe"])].append(item)
    for timeframe, values in by_tf.items():
        values.sort(key=lambda row: (row["price_e8"], row["known_at_utc"], row["swing_id"]))
        SWING_PRICE_INDEX[timeframe] = [int(row["price_e8"]) for row in values]
    return dict(by_tf), broken_at


def nearest_swing_target(trigger: Mapping[str, Any], direction: str, timeframe: str, swings: Mapping[str, Sequence[Mapping[str, Any]]], broken_at: Mapping[str, datetime]) -> tuple[int | None, str | None]:
    if trigger["status"] != "FORMED":
        return None, None
    entry = int(trigger["entry_e8"]); entry_time = parse_dt(str(trigger["entry_at_utc"])); side = "UPPER" if direction == "UP" else "LOWER"
    items = swings[timeframe]; prices = SWING_PRICE_INDEX[timeframe]
    index = bisect.bisect_right(prices, entry) if direction == "UP" else bisect.bisect_left(prices, entry) - 1
    step = 1 if direction == "UP" else -1
    while 0 <= index < len(items):
        price = prices[index]
        left = bisect.bisect_left(prices, price); right = bisect.bisect_right(prices, price)
        eligible = []
        for swing in items[left:right]:
            if swing["side"] != side or swing["known_dt"] > entry_time:
                continue
            broken = broken_at.get(str(swing["swing_id"]))
            if broken is not None and broken <= entry_time:
                continue
            eligible.append((str(swing["known_at_utc"]), str(swing["swing_id"])))
        if eligible:
            chosen = min(eligible)
            return price, chosen[1]
        index = right if step > 0 else left - 1
    return None, None


def core_specs() -> list[tuple[str, str, str]]:
    return [(trigger, stop, target) for trigger in TRIGGERS for stop in STOPS for target in TARGETS]


def full_specs() -> list[tuple[str, str, str, int]]:
    return [(trigger, stop, target, time_bars) for trigger, stop, target in core_specs() for time_bars in TIMES]


def spec_code(trigger: str, stop: str, target: str, time_bars: int) -> str:
    return f"{trigger}::{stop}::{target}::TIME_{time_bars}_PARENT_BARS"


def trading_date(value: str) -> str:
    return (parse_dt(value).astimezone(NY) - timedelta(hours=17)).date().isoformat()


def no_trade(case: Mapping[str, Any], specification: str, reason: str) -> dict[str, Any]:
    return {
        "pullback_id": case["pullback_id"], "known_at_utc": case["known_at_utc"], "cluster_date": trading_date(str(case["known_at_utc"])),
        "timeframe": case["timeframe"], "direction": case["direction"], "specification": specification, "status": "NO_TRADE", "no_trade_reason": reason,
        "entry_at_utc": None, "exit_at_utc": None, "entry_e8": None, "stop_e8": None, "target_e8": None, "exit_e8": None,
        "exit_reason": None, "gross_r": None, "net_r": None, "net_r_cost_1p5x": None, "net_r_cost_2x": None,
        "cost_r": None, "net_pnl_usd": None, "mfe_r": None, "mae_r": None, "holding_minutes": None, "target_r": None,
        "ounces": None, "outcome_hash": canonical_hash([case["pullback_id"], specification, reason]),
    }


def simulate_core(
    case: Mapping[str, Any], trigger: Mapping[str, Any] | None, stop_name: str, target_name: str,
    prices: anatomy_impl.PriceData, swings: Mapping[str, Sequence[Mapping[str, Any]]], broken_at: Mapping[str, datetime], implementation: str,
) -> dict[int, dict[str, Any]]:
    prefix = f"{trigger['trigger'] if trigger else 'MISSING'}::{stop_name}::{target_name}"
    if trigger is None or trigger["status"] != "FORMED":
        reason = "NO_TRIGGER_FACT" if trigger is None else str(trigger["reason"])
        return {time_bars: no_trade(case, spec_code(str(trigger["trigger"]) if trigger else "MISSING", stop_name, target_name, time_bars), reason) for time_bars in TIMES}
    direction = str(case["direction"]); sign = 1 if direction == "UP" else -1; atr = float(trigger["atr14_e8"]); entry = int(trigger["entry_e8"]); entry_index = int(trigger["entry_index"])
    buffer_005 = int(round(0.05 * atr))
    if stop_name == "PIVOT_BUFFER_0P05_ATR":
        stop = int(trigger["pivot_price_e8"]) - buffer_005 if sign > 0 else int(trigger["pivot_price_e8"]) + buffer_005
    elif stop_name == "PIVOT_BUFFER_0P15_ATR":
        buffer_015 = int(round(0.15 * atr)); stop = int(trigger["pivot_price_e8"]) - buffer_015 if sign > 0 else int(trigger["pivot_price_e8"]) + buffer_015
    elif stop_name == "CONFIRMATION_EXTREME_BUFFER_0P05_ATR":
        stop = int(trigger["confirmation_low_e8"]) - buffer_005 if sign > 0 else int(trigger["confirmation_high_e8"]) + buffer_005
    else:
        raise ValueError(stop_name)
    risk = entry - stop if sign > 0 else stop - entry
    if risk <= 0:
        return {time_bars: no_trade(case, spec_code(str(trigger["trigger"]), stop_name, target_name, time_bars), "STOP_NOT_ADVERSE_TO_ENTRY") for time_bars in TIMES}
    target_id = None
    if target_name.startswith("FIXED_"):
        multiple = {"FIXED_1P0_R": 1.0, "FIXED_1P5_R": 1.5, "FIXED_2P0_R": 2.0}[target_name]
        target = entry + sign * int(round(multiple * risk))
    else:
        target_cache_key = (str(case["pullback_id"]), str(trigger["trigger"]))
        if target_cache_key not in SWING_TARGET_CACHE:
            SWING_TARGET_CACHE[target_cache_key] = nearest_swing_target(trigger, direction, str(case["timeframe"]), swings, broken_at)
        target, target_id = SWING_TARGET_CACHE[target_cache_key]
        if target is None:
            return {time_bars: no_trade(case, spec_code(str(trigger["trigger"]), stop_name, target_name, time_bars), "NO_KNOWN_LIQUIDITY_TARGET") for time_bars in TIMES}
    parent = prices.parents[str(case["timeframe"])]
    entry_ns = int(prices.open_ns[entry_index]); first_parent = int(np.searchsorted(parent.close_ns, entry_ns, side="right"))
    deadlines: dict[int, tuple[int, int] | None] = {}
    for time_bars in TIMES:
        deadline_parent = first_parent + time_bars - 1
        if deadline_parent >= len(parent.close_ns):
            deadlines[time_bars] = None; continue
        deadline_ns = int(parent.close_ns[deadline_parent]); end_index = int(np.searchsorted(prices.open_ns, deadline_ns, side="left"))
        deadlines[time_bars] = None if end_index <= entry_index or int(prices.open_ns[end_index - 1]) + 60_000_000_000 != deadline_ns else (deadline_ns, end_index)
    valid = [value for value in deadlines.values() if value is not None]
    if not valid:
        return {time_bars: no_trade(case, spec_code(str(trigger["trigger"]), stop_name, target_name, time_bars), "NO_COMPLETE_TIME_PATH") for time_bars in TIMES}
    max_end = max(value[1] for value in valid); path_open = prices.open_e8[entry_index:max_end]; path_high = prices.high_e8[entry_index:max_end]; path_low = prices.low_e8[entry_index:max_end]; path_close = prices.close_e8[entry_index:max_end]
    if implementation == "primary":
        stop_hits = np.flatnonzero(path_low <= stop if sign > 0 else path_high >= stop); target_hits = np.flatnonzero(path_high >= target if sign > 0 else path_low <= target)
        first_stop = int(stop_hits[0]) if len(stop_hits) else None; first_target = int(target_hits[0]) if len(target_hits) else None
    else:
        stop_states = (path_low <= stop) if sign > 0 else (path_high >= stop)
        target_states = (path_high >= target) if sign > 0 else (path_low <= target)
        first_stop = int(np.argmax(stop_states)) if bool(np.any(stop_states)) else None
        first_target = int(np.argmax(target_states)) if bool(np.any(target_states)) else None
    spread_raw = trigger["entry_spread_usd_oz"]; spread = 0.30 if spread_raw is None or float(spread_raw) < 0 else float(spread_raw); total_cost = spread + 0.07 + 0.10; risk_usd_oz = risk / SCALE
    ounces = math.floor((50.0 / (risk_usd_oz + total_cost)) + 1e-12)
    if ounces < 1:
        return {time_bars: no_trade(case, spec_code(str(trigger["trigger"]), stop_name, target_name, time_bars), "MINIMUM_SIZE_EXCEEDS_RISK") for time_bars in TIMES}
    output: dict[int, dict[str, Any]] = {}
    for time_bars in TIMES:
        specification = spec_code(str(trigger["trigger"]), stop_name, target_name, time_bars); deadline = deadlines[time_bars]
        if deadline is None:
            output[time_bars] = no_trade(case, specification, "INCOMPLETE_TIME_PATH"); continue
        path_length = deadline[1] - entry_index
        if first_stop is not None and first_stop < path_length and (first_target is None or first_stop <= first_target):
            exit_offset = first_stop; exit_price = min(stop, int(path_open[exit_offset])) if sign > 0 else max(stop, int(path_open[exit_offset])); exit_reason = "STOP"
        elif first_target is not None and first_target < path_length:
            exit_offset = first_target; exit_price = int(target); exit_reason = "TARGET"
        else:
            exit_offset = path_length - 1; exit_price = int(path_close[exit_offset]); exit_reason = "TIME"
        used_high = path_high[:exit_offset + 1]; used_low = path_low[:exit_offset + 1]
        gross_r = sign * (exit_price - entry) / risk; cost_r = total_cost / risk_usd_oz; net_r = gross_r - cost_r
        favourable = int(np.max(used_high)) - entry if sign > 0 else entry - int(np.min(used_low)); adverse = entry - int(np.min(used_low)) if sign > 0 else int(np.max(used_high)) - entry
        exit_index = entry_index + exit_offset; net_pnl = (sign * ((exit_price - entry) / SCALE) - total_cost) * ounces
        output[time_bars] = {
            "pullback_id": case["pullback_id"], "known_at_utc": case["known_at_utc"], "cluster_date": trading_date(str(case["known_at_utc"])),
            "timeframe": case["timeframe"], "direction": direction, "specification": specification, "status": "EXECUTED", "no_trade_reason": "",
            "entry_at_utc": trigger["entry_at_utc"], "exit_at_utc": ns_iso(int(prices.open_ns[exit_index]) + 60_000_000_000), "entry_e8": entry, "stop_e8": stop,
            "target_e8": int(target), "target_swing_id": target_id, "exit_e8": exit_price, "exit_reason": exit_reason,
            "gross_r": rounded(gross_r), "net_r": rounded(net_r), "net_r_cost_1p5x": rounded(gross_r - 1.5 * cost_r), "net_r_cost_2x": rounded(gross_r - 2.0 * cost_r),
            "cost_r": rounded(cost_r), "net_pnl_usd": rounded(net_pnl), "mfe_r": rounded(max(0, favourable) / risk), "mae_r": rounded(max(0, adverse) / risk),
            "holding_minutes": int((int(prices.open_ns[exit_index]) - entry_ns) / 60_000_000_000) + 1, "target_r": rounded(abs(int(target) - entry) / risk), "ounces": ounces,
            "outcome_hash": canonical_hash([case["feature_lineage_hash"], trigger["trigger_lineage_hash"], specification, stop, target, exit_index, exit_price, exit_reason]),
        }
    return output


def build_trade_matrices(
    cases: Sequence[Mapping[str, Any]], trigger_map: Mapping[tuple[str, str], Mapping[str, Any]], prices: anatomy_impl.PriceData,
    swings: Mapping[str, Sequence[Mapping[str, Any]]], broken_at: Mapping[str, datetime], implementation: str,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    specs = full_specs(); index_map = {spec: index for index, spec in enumerate(specs)}
    shape = (len(cases), len(specs)); net = np.full(shape, np.nan); stress = np.full(shape, np.nan); pnl = np.full(shape, np.nan); gross = np.full(shape, np.nan)
    for trigger_name, stop_name, target_name in core_specs():
        columns = {time_bars: index_map[(trigger_name, stop_name, target_name, time_bars)] for time_bars in TIMES}
        for case_index, case in enumerate(cases):
            trigger = trigger_map.get((str(case["pullback_id"]), trigger_name))
            results = simulate_core(case, trigger, stop_name, target_name, prices, swings, broken_at, implementation)
            for time_bars, row in results.items():
                if row["status"] == "EXECUTED":
                    column = columns[time_bars]; net[case_index, column] = float(row["net_r"]); stress[case_index, column] = float(row["net_r_cost_1p5x"]); pnl[case_index, column] = float(row["net_pnl_usd"]); gross[case_index, column] = float(row["gross_r"])
    return net, stress, pnl, gross


def matrix_stats(values: np.ndarray, dates: Sequence[str], seed: int) -> dict[str, np.ndarray]:
    finite_mask = np.isfinite(values); counts = finite_mask.sum(axis=0); sums = np.nansum(values, axis=0); expectancy = np.divide(sums, counts, out=np.full(values.shape[1], np.nan), where=counts > 0)
    positive_sum = np.nansum(np.where(values > 0, values, 0), axis=0); negative_sum = np.abs(np.nansum(np.where(values < 0, values, 0), axis=0)); pf = np.divide(positive_sum, negative_sum, out=np.full(values.shape[1], np.inf), where=negative_sum > 0)
    winners = np.sum(values > 0, axis=0); losers = np.sum(values < 0, axis=0)
    unique_dates = sorted(set(dates)); date_index = {value: index for index, value in enumerate(unique_dates)}; date_sums = np.zeros((len(unique_dates), values.shape[1])); date_counts = np.zeros((len(unique_dates), values.shape[1]), dtype=np.int32)
    for row_index, day in enumerate(dates):
        index = date_index[day]; row_finite = finite_mask[row_index]; date_sums[index, row_finite] += values[row_index, row_finite]; date_counts[index, row_finite] += 1
    trade_dates = np.sum(date_counts > 0, axis=0); ci_low = np.full(values.shape[1], np.nan); ci_high = np.full(values.shape[1], np.nan); p_value = np.full(values.shape[1], np.nan)
    eligible_columns = np.flatnonzero((counts >= 2) & (trade_dates >= 2) & (winners > 0) & (losers > 0) & (expectancy > 0))
    if len(eligible_columns):
        rng = np.random.default_rng(seed); weights = rng.multinomial(len(unique_dates), np.full(len(unique_dates), 1 / len(unique_dates)), size=5000)
        for left in range(0, len(eligible_columns), 24):
            columns = eligible_columns[left:left + 24]; numerators = weights @ date_sums[:, columns]; denominators = weights @ date_counts[:, columns]
            samples = np.divide(numerators, denominators, out=np.full(numerators.shape, np.nan), where=denominators > 0)
            ci_low[columns] = np.nanquantile(samples, 0.025, axis=0); ci_high[columns] = np.nanquantile(samples, 0.975, axis=0); p_value[columns] = (1 + np.sum(samples <= 0, axis=0)) / (1 + np.sum(np.isfinite(samples), axis=0))
    max_dd = np.zeros(values.shape[1])
    for column in range(values.shape[1]):
        sequence = values[:, column]; sequence = sequence[np.isfinite(sequence)]; cumulative = peak = drawdown = 0.0
        for value in sequence:
            cumulative += float(value); peak = max(peak, cumulative); drawdown = max(drawdown, peak - cumulative)
        max_dd[column] = drawdown
    return {"trades": counts, "dates": trade_dates, "winners": winners, "losers": losers, "expectancy": expectancy, "profit_factor": pf, "ci_low": ci_low, "ci_high": ci_high, "p": p_value, "max_drawdown_r": max_dd}


def rank_fold(candidate_id: str, fold: tuple[int, str, str, str, str], cases: Sequence[Mapping[str, Any]], net: np.ndarray, memberships: set[str], seed: int) -> tuple[list[dict[str, Any]], list[int]]:
    fold_id, train_start, train_end, _, _ = fold; mask = np.array([str(case["pullback_id"]) in memberships and train_start <= str(case["known_at_utc"])[:10] <= train_end for case in cases], dtype=bool)
    selected_cases = [case for case, keep in zip(cases, mask) if keep]; values = net[mask]; dates = [trading_date(str(case["known_at_utc"])) for case in selected_cases]
    stats = matrix_stats(values, dates, seed); specs = full_specs(); rows = []
    for index, spec in enumerate(specs):
        row = {
            "candidate_id": candidate_id, "fold": fold_id, "specification": spec_code(*spec), "trigger": spec[0], "stop": spec[1], "target": spec[2], "time_exit_parent_bars": spec[3],
            "training_cases": len(selected_cases), "trades": int(stats["trades"][index]), "dates": int(stats["dates"][index]), "winners": int(stats["winners"][index]), "losers": int(stats["losers"][index]),
            "expectancy_r": rounded(float(stats["expectancy"][index])) if math.isfinite(float(stats["expectancy"][index])) else None,
            "profit_factor": None if math.isinf(float(stats["profit_factor"][index])) else rounded(float(stats["profit_factor"][index])),
            "profit_factor_infinite": math.isinf(float(stats["profit_factor"][index])),
            "bootstrap_ci95_low": rounded(float(stats["ci_low"][index])) if math.isfinite(float(stats["ci_low"][index])) else None,
            "bootstrap_ci95_high": rounded(float(stats["ci_high"][index])) if math.isfinite(float(stats["ci_high"][index])) else None,
            "bootstrap_p_one_sided": rounded(float(stats["p"][index])) if math.isfinite(float(stats["p"][index])) else None,
            "max_drawdown_r": rounded(float(stats["max_drawdown_r"][index])), "selected_for_validation": False,
        }
        row["training_eligible"] = row["bootstrap_ci95_low"] is not None and float(row["bootstrap_ci95_low"]) > 0
        rows.append(row)
    eligible = [index for index, row in enumerate(rows) if row["training_eligible"]]
    eligible.sort(key=lambda index: (-float(rows[index]["bootstrap_ci95_low"]), -float(rows[index]["expectancy_r"]), -(float("inf") if rows[index]["profit_factor_infinite"] else float(rows[index]["profit_factor"])), -int(rows[index]["trades"]), float(rows[index]["max_drawdown_r"]), rows[index]["specification"]))
    selected = eligible[:3]
    for index in selected: rows[index]["selected_for_validation"] = True
    return rows, selected


def cluster_bootstrap(rows: Sequence[Mapping[str, Any]], field: str, seed: int) -> dict[str, Any]:
    by_date: dict[str, list[float]] = defaultdict(list)
    for row in rows: by_date[str(row["cluster_date"])].append(float(row[field]))
    dates = sorted(by_date)
    if not dates: return {"ci90": [None, None], "ci95": [None, None], "p_one_sided": None}
    sums = np.asarray([sum(by_date[day]) for day in dates]); counts = np.asarray([len(by_date[day]) for day in dates]); rng = np.random.default_rng(seed); values = []
    for left in range(0, 5000, 250):
        sample = rng.integers(0, len(dates), size=(min(250, 5000-left), len(dates))); values.extend((sums[sample].sum(axis=1) / counts[sample].sum(axis=1)).tolist())
    array = np.asarray(values)
    return {"ci90": [rounded(float(np.quantile(array, 0.05))), rounded(float(np.quantile(array, 0.95)))], "ci95": [rounded(float(np.quantile(array, 0.025))), rounded(float(np.quantile(array, 0.975)))], "p_one_sided": rounded(float((1 + np.sum(array <= 0)) / (len(array) + 1)))}


def profit_factor(rows: Sequence[Mapping[str, Any]], field: str) -> float | str | None:
    values = [float(row[field]) for row in rows]; positive = sum(value for value in values if value > 0); negative = abs(sum(value for value in values if value < 0))
    return rounded(positive / negative) if negative else ("INF" if positive else None)


def full_metrics(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r"]) for row in rows]; wins = [value for value in values if value > 0]; losses = [value for value in values if value < 0]
    cumulative = peak = dd_r = 0.0; equity = equity_peak = 10000.0; dd_pct = 0.0
    for row, value in zip(rows, values):
        cumulative += value; peak = max(peak, cumulative); dd_r = max(dd_r, peak - cumulative); equity += float(row["net_pnl_usd"]); equity_peak = max(equity_peak, equity); dd_pct = max(dd_pct, 100 * (equity_peak - equity) / equity_peak)
    positive_total = sum(wins); concentration = max(wins) / positive_total if wins else None
    return {
        "trades": len(rows), "dates": len({row["cluster_date"] for row in rows}), "winners": len(wins), "losers": len(losses), "win_rate_pct": rounded(100*len(wins)/len(rows)) if rows else None,
        "expectancy_r": rounded(statistics.fmean(values)) if values else None, "net_r": rounded(sum(values)), "profit_factor": profit_factor(rows, "net_r"),
        "average_win_r": rounded(statistics.fmean(wins)) if wins else None, "average_loss_r": rounded(statistics.fmean(losses)) if losses else None,
        "net_pnl_usd": rounded(sum(float(row["net_pnl_usd"]) for row in rows)), "max_drawdown_r": rounded(dd_r), "max_drawdown_pct": rounded(dd_pct),
        "average_mfe_r": rounded(statistics.fmean(float(row["mfe_r"]) for row in rows)) if rows else None, "average_mae_r": rounded(statistics.fmean(float(row["mae_r"]) for row in rows)) if rows else None,
        "median_holding_minutes": rounded(statistics.median(float(row["holding_minutes"]) for row in rows)) if rows else None, "profit_concentration": rounded(concentration),
        "exit_reasons": dict(sorted(Counter(str(row["exit_reason"]) for row in rows).items())),
    }


def holm_adjust(items: Sequence[tuple[int, float]]) -> dict[int, float]:
    ordered = sorted(items, key=lambda item: (item[1], item[0])); count = len(ordered); output = {}; running = 0.0
    for rank, (index, p) in enumerate(ordered, 1): running = max(running, (count-rank+1)*p); output[index] = min(1.0, running)
    return output


def movement_atlas() -> dict[str, Any]:
    rows = pq.read_table(ANATOMY).to_pylist(); output = {}
    for timeframe in TIMEFRAMES:
        selected = [row for row in rows if row["timeframe"] == timeframe and row.get("complete_path_available")]
        result = {"cases": len(selected), "resolution": dict(sorted(Counter(str(row["resolution"]) for row in selected).items())), "path_classification": dict(sorted(Counter(str(row["path_classification"]) for row in selected).items()))}
        for barrier in (0.5, 1.0, 1.5, 2.0):
            field = f"barrier_{str(barrier).replace('.', 'p')}_order"; counts = Counter(str(row[field]) for row in selected); result[f"barrier_{barrier}_order"] = dict(sorted(counts.items()))
            result[f"barrier_{barrier}_favourable_first_pct"] = rounded(100 * counts["FAVOURABLE_FIRST"] / len(selected)) if selected else None
        result["median_complete_mfe_atr"] = rounded(statistics.median(float(row["complete_mfe_atr"]) for row in selected)) if selected else None
        result["median_complete_mae_atr"] = rounded(statistics.median(float(row["complete_mae_atr"]) for row in selected)) if selected else None
        output[timeframe] = result
    return {"version": "GOLD_TPMA_EDGE_V1_MOVEMENT_ATLAS_1_0", "development_only": True, "timeframes": output, "forward_values_accessed": False}


def report_text(results: Mapping[str, Any], atlas: Mapping[str, Any]) -> str:
    lines = ["# Gold Trend-Pullback Movement Anatomy Edge V1 — Development", "", f"Verdict: **{results['verdict']}**", "", "## Movement anatomy", ""]
    for timeframe in TIMEFRAMES:
        item = atlas["timeframes"][timeframe]; lines.append(f"- {timeframe}: {item['cases']} complete cases; 0.5 ATR favourable-first {item['barrier_0.5_favourable_first_pct']}%; median MFE {item['median_complete_mfe_atr']} ATR; median MAE {item['median_complete_mae_atr']} ATR.")
    lines.extend(["", "## Walk-forward candidates", ""])
    if not results["candidates"]: lines.append("No exact entry/stop/target/time specification passed the frozen OOF economic gates.")
    for item in results["candidates"]:
        metrics = item["metrics"]; lines.append(f"- `{item['candidate_id']}::{item['specification']}` — {metrics['trades']} OOF trades, {metrics['win_rate_pct']}% wins, {metrics['expectancy_r']}R expectancy, PF {metrics['profit_factor']}, PnL ${metrics['net_pnl_usd']}, verdict {item['verdict']}.")
    lines.extend(["", "Calendar 2025 and 2026 remained locked during development. Complete grid and negative results are sealed in the research artifacts.", ""])
    return "\n".join(lines)


def selftest() -> None:
    if len(full_specs()) != 180 or len({spec_code(*spec) for spec in full_specs()}) != 180:
        raise ValueError("Execution specification registry invalid")
    adjusted = holm_adjust([(0, .01), (1, .04), (2, .03)])
    if not math.isclose(adjusted[0], .03) or not math.isclose(adjusted[1], .06):
        raise ValueError("Holm selftest failed")


def main() -> None:
    selftest()
    outputs = (GRID_PRIMARY, GRID_REFERENCE, SELECTIONS, OOF_TRADES_PRIMARY, OOF_TRADES_REFERENCE, OOF_RESULTS_PRIMARY, OOF_RESULTS_REFERENCE, ATLAS, FROZEN_CANDIDATES, REPORT, DEVELOPMENT_SEAL, STATE)
    if any(path.exists() for path in outputs): raise FileExistsError("Discovery artifact already exists")
    freeze, pretest = verify_pretest(); by_tf, feature_map, memberships = load_cases(freeze); trigger_map = load_trigger_map(); prices = anatomy_impl.load_price(); swings, broken_at = load_target_registry()
    candidate_order = list(freeze["predecessor_candidate_ids"]); grid_rows: list[dict[str, Any]] = []; selected_registry: dict[str, dict[str, list[int]]] = defaultdict(dict); matrices: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = {}
    for timeframe in TIMEFRAMES:
        cases = by_tf[timeframe]
        checkpoint = MATRIX_CHECKPOINTS[timeframe]
        if checkpoint.exists():
            primary_matrices = load_matrix_checkpoint(checkpoint, timeframe, cases)
        else:
            primary_matrices = build_trade_matrices(cases, trigger_map, prices, swings, broken_at, "primary")
            reference_matrices = build_trade_matrices(cases, trigger_map, prices, swings, broken_at, "reference")
            for primary, reference in zip(primary_matrices, reference_matrices):
                if not np.array_equal(primary, reference, equal_nan=True): raise ValueError(f"Primary/reference trade matrix differs: {timeframe}")
            save_matrix_checkpoint(checkpoint, timeframe, cases, primary_matrices)
        matrices[timeframe] = primary_matrices
        for candidate_index, candidate_id in enumerate(candidate_order):
            if not candidate_id.startswith(timeframe + "|"): continue
            for fold in FOLDS:
                seed = 410817 + candidate_index * 100 + fold[0]
                rows, selected_columns = rank_fold(candidate_id, fold, cases, primary_matrices[0], memberships[candidate_id], seed)
                grid_rows.extend(rows)
                for column in selected_columns:
                    specification = spec_code(*full_specs()[column]); selected_registry[candidate_id].setdefault(specification, []).append(fold[0])
    grid_rows.sort(key=lambda row: (candidate_order.index(row["candidate_id"]), row["fold"], row["specification"]))
    write_parquet_exclusive(GRID_PRIMARY, grid_rows); write_parquet_exclusive(GRID_REFERENCE, grid_rows)
    if sha256_file(GRID_PRIMARY) != sha256_file(GRID_REFERENCE): raise ValueError("Grid outputs differ")
    shortlist = []
    for candidate_id, specs in selected_registry.items():
        for specification, folds in specs.items():
            if len(folds) >= 2: shortlist.append((candidate_id, specification, sorted(folds)))
    shortlist.sort(key=lambda item: (candidate_order.index(item[0]), item[1]))
    selections_payload = {"version": "GOLD_TPMA_EDGE_V1_WALK_FORWARD_SELECTIONS_1_0", "grid_tests": len(grid_rows), "training_selections": {candidate: specs for candidate, specs in selected_registry.items()}, "shortlist": [{"candidate_id": item[0], "specification": item[1], "selected_folds": item[2]} for item in shortlist], "forward_values_accessed": False}
    write_json_exclusive(SELECTIONS, selections_payload)
    oof_rows: list[dict[str, Any]] = []; reference_oof_rows: list[dict[str, Any]] = []; candidate_results = []
    spec_lookup = {spec_code(*spec): spec for spec in full_specs()}
    for shortlist_index, (candidate_id, specification, selected_folds) in enumerate(shortlist):
        timeframe = candidate_id.split("|", 1)[0]; cases = by_tf[timeframe]; spec = spec_lookup[specification]; column = full_specs().index(spec); net, stress, pnl, gross = matrices[timeframe]
        rows = []; reference_rows = []
        for fold in FOLDS:
            if fold[0] not in selected_folds: continue
            _, _, _, validation_start, validation_end = fold
            for case_index, case in enumerate(cases):
                if str(case["pullback_id"]) not in memberships[candidate_id] or not validation_start <= str(case["known_at_utc"])[:10] <= validation_end or not math.isfinite(float(net[case_index, column])): continue
                trigger = trigger_map.get((str(case["pullback_id"]), spec[0])); row = simulate_core(case, trigger, spec[1], spec[2], prices, swings, broken_at, "primary")[spec[3]]
                reference_row = simulate_core(case, trigger, spec[1], spec[2], prices, swings, broken_at, "reference")[spec[3]]
                if row["status"] != "EXECUTED" or row != reference_row: raise ValueError("OOF primary/reference trade mismatch")
                row["candidate_id"] = candidate_id; row["selected_training_folds"] = canonical_json(selected_folds); row["validation_fold"] = fold[0]; rows.append(row)
                reference_row = dict(reference_row); reference_row["candidate_id"] = candidate_id; reference_row["selected_training_folds"] = canonical_json(selected_folds); reference_row["validation_fold"] = fold[0]; reference_rows.append(reference_row)
        rows.sort(key=lambda row: (row["entry_at_utc"], row["pullback_id"])); reference_rows.sort(key=lambda row: (row["entry_at_utc"], row["pullback_id"]))
        if rows != reference_rows: raise ValueError("OOF primary/reference rows differ")
        oof_rows.extend(rows); reference_oof_rows.extend(reference_rows); metrics = full_metrics(rows); bootstrap = cluster_bootstrap(rows, "net_r", 510817 + shortlist_index)
        fold_stats = []
        for fold_id in selected_folds:
            selected = [row for row in rows if row["validation_fold"] == fold_id]; fold_stats.append({"fold": fold_id, "trades": len(selected), "expectancy_r": rounded(statistics.fmean(float(row["net_r"]) for row in selected)) if selected else None})
        stress_expectancy = rounded(statistics.fmean(float(row["net_r_cost_1p5x"]) for row in rows)) if rows else None; stress_pf = profit_factor(rows, "net_r_cost_1p5x")
        result = {"candidate_id": candidate_id, "specification": specification, "selected_folds": selected_folds, "metrics": metrics, "bootstrap": bootstrap, "holm_p": None, "folds": fold_stats, "cost_1p5x_expectancy_r": stress_expectancy, "cost_1p5x_profit_factor": stress_pf, "failed_gates": [], "verdict": "PENDING_MULTIPLICITY"}
        candidate_results.append(result)
    adjusted = holm_adjust([(index, float(item["bootstrap"]["p_one_sided"])) for index, item in enumerate(candidate_results) if item["bootstrap"]["p_one_sided"] is not None])
    support_floors = {"M15": (120, 75), "H1": (60, 40), "H4": (30, 25)}
    for index, item in enumerate(candidate_results):
        item["holm_p"] = rounded(adjusted.get(index)) if index in adjusted else None; metrics = item["metrics"]; timeframe = item["candidate_id"].split("|", 1)[0]; failures = []
        if metrics["trades"] < support_floors[timeframe][0]: failures.append(f"TRADES_LT_{support_floors[timeframe][0]}")
        if metrics["dates"] < support_floors[timeframe][1]: failures.append(f"DATES_LT_{support_floors[timeframe][1]}")
        if metrics["winners"] < 15: failures.append("WINNERS_LT_15")
        if metrics["losers"] < 15: failures.append("LOSERS_LT_15")
        if metrics["expectancy_r"] is None or metrics["expectancy_r"] <= 0: failures.append("EXPECTANCY_NOT_POSITIVE")
        if item["bootstrap"]["ci95"][0] is None or item["bootstrap"]["ci95"][0] <= 0: failures.append("CI95_LOWER_NOT_POSITIVE")
        if item["holm_p"] is None or item["holm_p"] > .05: failures.append("HOLM_P_GT_0P05")
        if metrics["profit_factor"] != "INF" and (metrics["profit_factor"] is None or float(metrics["profit_factor"]) < 1.2): failures.append("PROFIT_FACTOR_LT_1P20")
        supported_folds = [fold for fold in item["folds"] if fold["trades"] >= 10 and fold["expectancy_r"] is not None]
        if sum(float(fold["expectancy_r"]) > 0 for fold in supported_folds) < 2: failures.append("POSITIVE_VALIDATION_FOLDS_LT_2")
        if any(float(fold["expectancy_r"]) < -.10 for fold in supported_folds): failures.append("VALIDATION_FOLD_BELOW_MINUS_0P10R")
        if item["cost_1p5x_expectancy_r"] is None or item["cost_1p5x_expectancy_r"] <= 0: failures.append("COST_1P5X_EXPECTANCY_NOT_POSITIVE")
        if item["cost_1p5x_profit_factor"] != "INF" and (item["cost_1p5x_profit_factor"] is None or float(item["cost_1p5x_profit_factor"]) < 1.05): failures.append("COST_1P5X_PF_LT_1P05")
        if metrics["max_drawdown_pct"] > 15: failures.append("MAX_DRAWDOWN_GT_15PCT")
        if metrics["profit_concentration"] is None or metrics["profit_concentration"] > .25: failures.append("PROFIT_CONCENTRATION_GT_25PCT")
        item["failed_gates"] = failures; item["verdict"] = "PASS_DEVELOPMENT_EXECUTION_CANDIDATE" if not failures else "REJECT_OOF_ECONOMICS"
    passing = [item for item in candidate_results if item["verdict"] == "PASS_DEVELOPMENT_EXECUTION_CANDIDATE"]
    final_passing = []
    for timeframe in TIMEFRAMES:
        values = [item for item in passing if item["candidate_id"].startswith(timeframe + "|")]
        values.sort(key=lambda item: (-float(item["bootstrap"]["ci95"][0]), -float(item["metrics"]["expectancy_r"]), -float(item["metrics"]["profit_factor"] if item["metrics"]["profit_factor"] != "INF" else 1e9), item["specification"])); final_passing.extend(values[:3])
    oof_rows.sort(key=lambda row: (candidate_order.index(row["candidate_id"]), row["specification"], row["entry_at_utc"], row["pullback_id"]))
    reference_oof_rows.sort(key=lambda row: (candidate_order.index(row["candidate_id"]), row["specification"], row["entry_at_utc"], row["pullback_id"]))
    if oof_rows != reference_oof_rows: raise ValueError("Complete OOF primary/reference payload differs")
    write_parquet_exclusive(OOF_TRADES_PRIMARY, oof_rows); write_parquet_exclusive(OOF_TRADES_REFERENCE, reference_oof_rows)
    if sha256_file(OOF_TRADES_PRIMARY) != sha256_file(OOF_TRADES_REFERENCE): raise ValueError("OOF Parquet bytes differ")
    atlas = movement_atlas(); write_json_exclusive(ATLAS, atlas)
    verdict = "PASS_DEVELOPMENT_EXECUTION_CANDIDATES_FROZEN" if final_passing else "REJECT_NO_OOF_ECONOMIC_EDGE"
    results = {"version": "GOLD_TPMA_EDGE_V1_OOF_RESULTS_1_0", "verdict": verdict, "grid_tests": len(grid_rows), "shortlisted_exact_specifications": len(shortlist), "candidate_results": candidate_results, "passing_candidates": [{"candidate_id": item["candidate_id"], "specification": item["specification"]} for item in final_passing], "candidates": candidate_results, "forward_values_accessed": False, "primary_reference_exact": True}
    write_json_exclusive(OOF_RESULTS_PRIMARY, results); write_json_exclusive(OOF_RESULTS_REFERENCE, results)
    frozen = {"version": "GOLD_TPMA_EDGE_V1_FROZEN_DEVELOPMENT_CANDIDATES_1_0", "status": "FROZEN_BEFORE_FORWARD_VALUES", "candidate_count": len(final_passing), "candidates": final_passing, "forward_values_accessed": False, "retuning_permitted": False}
    write_json_exclusive(FROZEN_CANDIDATES, frozen); write_text_exclusive(REPORT, report_text(results, atlas))
    artifacts = [*MATRIX_CHECKPOINTS.values(), GRID_PRIMARY, GRID_REFERENCE, SELECTIONS, OOF_TRADES_PRIMARY, OOF_TRADES_REFERENCE, OOF_RESULTS_PRIMARY, OOF_RESULTS_REFERENCE, ATLAS, FROZEN_CANDIDATES, REPORT]
    seal = {"version": "GOLD_TPMA_EDGE_V1_DEVELOPMENT_SEAL_1_0", "status": verdict, "sealed_at_utc": utc_now(), "artifacts": {path.name: file_record(path) for path in artifacts}, "artifact_set_hash": canonical_hash({path.name: sha256_file(path) for path in artifacts}), "passing_candidates": frozen["candidates"], "forward_values_accessed": False, "primary_reference_exact": True}
    write_json_exclusive(DEVELOPMENT_SEAL, seal); write_json_exclusive(STATE, {"version": "GOLD_TPMA_EDGE_V1_STATE_M3_1_0", "status": verdict, "recorded_at_utc": utc_now(), "development_seal": file_record(DEVELOPMENT_SEAL), "next_step": "OPEN_FORWARD_ONCE" if final_passing else "FINALIZE_ZERO_CANDIDATE"})
    print(json.dumps({"status": verdict, "grid_tests": len(grid_rows), "shortlist": len(shortlist), "passing": frozen["candidates"], "candidate_summaries": [{"candidate_id": item["candidate_id"], "specification": item["specification"], "trades": item["metrics"]["trades"], "expectancy_r": item["metrics"]["expectancy_r"], "pf": item["metrics"]["profit_factor"], "verdict": item["verdict"], "failed_gates": item["failed_gates"]} for item in candidate_results], "development_seal": file_record(DEVELOPMENT_SEAL)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
