from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
ARTIFACTS = ROOT / "research_artifacts"
MANIFESTS = ROOT / "research_manifests"
OUTPUT = ARTIFACTS / "gold_trend_pullback_movement_anatomy_edge_v1_v01"
EDGE = ARTIFACTS / "gold_trend_pullback_continuation_edge_v1_v01"
CENSUS = ARTIFACTS / "gold_multitimeframe_trend_continuation_census_v1_v02"
CASEBOOK = ARTIFACTS / "gold_casebook_v01"

CONTRACT = ROOT / "GOLD_TREND_PULLBACK_MOVEMENT_ANATOMY_EDGE_DISCOVERY_CONTRACT_V1.md"
PROTOCOL = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_protocol.json"
FREEZE = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_design_freeze.json"

PRIMARY_ANATOMY = OUTPUT / "primary_movement_anatomy.parquet"
REFERENCE_ANATOMY = OUTPUT / "reference_movement_anatomy.parquet"
PRIMARY_TRIGGERS = OUTPUT / "primary_trigger_facts.parquet"
REFERENCE_TRIGGERS = OUTPUT / "reference_trigger_facts.parquet"
CERTIFICATION = OUTPUT / "movement_anatomy_certification.json"
PRETEST_SEAL = MANIFESTS / "gold_trend_pullback_movement_anatomy_edge_v1_pretest_seal.json"
STATE = OUTPUT / "state_m2.json"

SCALE = 100_000_000
END_NS = int(datetime(2025, 1, 1, tzinfo=UTC).timestamp() * 1_000_000_000)
TF_SOURCE = {"15m": "M15", "1h": "H1", "4h": "H4"}
TF_MINUTES = {"M15": 15, "H1": 60, "H4": 240}
MINUTE_HORIZONS = [1, 5, 15, 30, 60]
PARENT_HORIZONS = [1, 2, 4, 8, 16]
BARRIERS = [0.25, 0.5, 0.75, 1.0, 1.5, 2.0, 3.0]
TRIGGERS = ["IMMEDIATE", "CONFIRMATION_EXTREME_BREAK", "RESPONSE_HALF_RETRACE_LIMIT", "REFERENCE_LEVEL_RETEST_LIMIT", "BREAK_RETEST_CONFIRM"]


@dataclass(frozen=True, slots=True)
class ParentBars:
    close_ns: np.ndarray
    open_e8: np.ndarray
    high_e8: np.ndarray
    low_e8: np.ndarray
    close_e8: np.ndarray


@dataclass(frozen=True, slots=True)
class PriceData:
    open_ns: np.ndarray
    open_e8: np.ndarray
    high_e8: np.ndarray
    low_e8: np.ndarray
    close_e8: np.ndarray
    spread: np.ndarray
    parents: Mapping[str, ParentBars]
    diagnostics: Mapping[str, Any]


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def dt_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def scaled(value: Any) -> int:
    return int((Decimal(str(value)) * SCALE).to_integral_value(rounding=ROUND_HALF_UP))


def finite(value: Any) -> float | None:
    try:
        output = float(value)
    except (TypeError, ValueError):
        return None
    return output if math.isfinite(output) else None


def rounded(value: float | None) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    output = round(float(value), 12)
    return 0.0 if output == 0 else output


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while payload := handle.read(1 << 20):
            digest.update(payload)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
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


def verify_freeze() -> dict[str, Any]:
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if freeze["status"] != "FROZEN_BEFORE_NEW_MOVEMENT_ANATOMY_ACCESS":
        raise ValueError("Design freeze is invalid")
    for item in freeze["source_records"].values():
        path = ROOT / item["path"]
        if not path.is_file() or path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise ValueError(f"Frozen source changed: {item['path']}")
    if freeze["source_records"]["contract"]["sha256"] != sha256_file(CONTRACT) or freeze["source_records"]["protocol"]["sha256"] != sha256_file(PROTOCOL):
        raise ValueError("Frozen controls changed")
    return freeze


def load_price() -> PriceData:
    path = CASEBOOK / "price_bars.jsonl.gz"
    m1: list[list[Any]] = [[] for _ in range(6)]
    parent: dict[str, list[list[int]]] = {key: [[] for _ in range(5)] for key in TF_MINUTES}
    scanned = selected_m1 = selected_parent = malformed = forward_skipped = 0
    with gzip.open(path, "rb") as handle:
        for raw in handle:
            scanned += 1
            if b'"instrument_code":"XAUUSD"' not in raw:
                continue
            if b'"open_time":"2025' in raw or b'"open_time":"2026' in raw:
                forward_skipped += 1
                continue
            row = json.loads(raw)
            timeframe = str(row.get("timeframe"))
            if timeframe != "1m" and timeframe not in TF_SOURCE:
                continue
            opened = dt_ns(parse_dt(str(row["open_time"])))
            if opened >= END_NS:
                forward_skipped += 1
                continue
            ohlc = row.get("ohlc") if isinstance(row.get("ohlc"), Mapping) else {}
            if any(ohlc.get(key) is None for key in ("open", "high", "low", "close")):
                malformed += 1
                continue
            o, high, low, close = (scaled(ohlc[key]) for key in ("open", "high", "low", "close"))
            if not (low <= min(o, close) <= max(o, close) <= high):
                malformed += 1
                continue
            if timeframe == "1m":
                spread = finite(row.get("spread_price"))
                m1[0].append(opened); m1[1].append(o); m1[2].append(high); m1[3].append(low); m1[4].append(close); m1[5].append(float("nan") if spread is None else spread)
                selected_m1 += 1
            else:
                key = TF_SOURCE[timeframe]
                closed = dt_ns(parse_dt(str(row["close_time"])))
                parent[key][0].append(closed); parent[key][1].append(o); parent[key][2].append(high); parent[key][3].append(low); parent[key][4].append(close)
                selected_parent += 1
    arrays = [np.asarray(value, dtype=np.int64) for value in m1[:5]]
    spreads = np.asarray(m1[5], dtype=np.float64)
    if not len(arrays[0]) or np.any(np.diff(arrays[0]) <= 0):
        raise ValueError("M1 timestamps invalid")
    parents: dict[str, ParentBars] = {}
    for timeframe, values in parent.items():
        converted = [np.asarray(value, dtype=np.int64) for value in values]
        if not len(converted[0]) or np.any(np.diff(converted[0]) <= 0):
            raise ValueError(f"Parent timestamps invalid: {timeframe}")
        parents[timeframe] = ParentBars(*converted)
    return PriceData(
        arrays[0], arrays[1], arrays[2], arrays[3], arrays[4], spreads, parents,
        {
            "source": file_record(path), "source_rows_scanned": scanned, "selected_m1_rows": selected_m1,
            "selected_parent_rows": selected_parent, "malformed_rows": malformed, "forward_rows_not_deserialized": forward_skipped,
            "first_m1_open": ns_iso(int(arrays[0][0])), "last_m1_open": ns_iso(int(arrays[0][-1])),
            "parent_counts": {key: len(value.close_ns) for key, value in parents.items()},
        },
    )


def eligible_cases() -> list[dict[str, Any]]:
    features = pq.read_table(EDGE / "primary_features.parquet").to_pylist()
    cases = {str(row["pullback_id"]): row for row in pq.read_table(CENSUS / "primary_pullback_cases.parquet").to_pylist()}
    output = []
    for feature in features:
        if not (
            feature["timeframe"] in TF_MINUTES and feature["scale"] == "STANDARD" and feature["feature_available"]
            and feature["actionable_at_known"] and feature["research_eligible"] and str(feature["known_at_utc"]) < "2025-01-01T00:00:00Z"
        ):
            continue
        case = cases.get(str(feature["pullback_id"]))
        if case is None or case["resolution"] not in {"CONTINUED", "FAILED_STRUCTURE_SWITCH"}:
            continue
        row = dict(feature)
        row.update({
            "pivot_price_e8": int(case["pivot_price_e8"]), "reference_level_e8": int(case["reference_level_e8"]),
            "resolution": str(case["resolution"]), "resolution_hash": str(case["resolution_hash"]),
            "decision_facts_hash": str(case["decision_facts_hash"]),
        })
        output.append(row)
    output.sort(key=lambda row: (row["known_at_utc"], row["timeframe"], row["pullback_id"]))
    counts = {timeframe: sum(row["timeframe"] == timeframe for row in output) for timeframe in TF_MINUTES}
    expected = {"M15": 6633, "H1": 1576, "H4": 444}
    if counts != expected or len({row["pullback_id"] for row in output}) != len(output):
        raise ValueError(f"Eligible population changed: {counts}")
    return output


def parent_index(parent: ParentBars, known_ns: int) -> int | None:
    index = int(np.searchsorted(parent.close_ns, known_ns, side="left"))
    return index if index < len(parent.close_ns) and int(parent.close_ns[index]) == known_ns else None


def complete_slice(prices: PriceData, start_index: int, deadline_ns: int) -> tuple[slice | None, str | None]:
    end_index = int(np.searchsorted(prices.open_ns, deadline_ns, side="left"))
    if end_index <= start_index:
        return None, "EMPTY_PATH"
    if int(prices.open_ns[end_index - 1]) + 60_000_000_000 != deadline_ns:
        return None, "INCOMPLETE_TERMINAL_MINUTE"
    return slice(start_index, end_index), None


def excursion(prices: PriceData, path_slice: slice, entry: int, sign: int) -> tuple[float, float, float, int, int]:
    highs = prices.high_e8[path_slice]; lows = prices.low_e8[path_slice]; closes = prices.close_e8[path_slice]
    if sign > 0:
        favourable_values = highs - entry; adverse_values = entry - lows
    else:
        favourable_values = entry - lows; adverse_values = highs - entry
    favourable_index = int(np.argmax(favourable_values)); adverse_index = int(np.argmax(adverse_values))
    return float(favourable_values[favourable_index]), float(adverse_values[adverse_index]), float(sign * (int(closes[-1]) - entry)), favourable_index, adverse_index


def first_passage(highs: np.ndarray, lows: np.ndarray, entry: int, atr: float, sign: int, barrier: float, implementation: str) -> tuple[int | None, int | None, str]:
    distance = barrier * atr
    if implementation == "primary":
        favourable = np.flatnonzero((highs - entry >= distance) if sign > 0 else (entry - lows >= distance))
        adverse = np.flatnonzero((entry - lows >= distance) if sign > 0 else (highs - entry >= distance))
        f = int(favourable[0]) if len(favourable) else None; a = int(adverse[0]) if len(adverse) else None
    else:
        f = a = None
        for index, (high, low) in enumerate(zip(highs, lows)):
            if f is None and ((high - entry >= distance) if sign > 0 else (entry - low >= distance)): f = index
            if a is None and ((entry - low >= distance) if sign > 0 else (high - entry >= distance)): a = index
            if f is not None and a is not None: break
    order = "NEITHER" if f is None and a is None else "FAVOURABLE_FIRST" if f is not None and (a is None or f < a) else "ADVERSE_FIRST" if a is not None and (f is None or a < f) else "BOTH_SAME_BAR"
    return f, a, order


def trigger_rows(case: Mapping[str, Any], prices: PriceData, confirmation_index: int, anchor_index: int) -> list[dict[str, Any]]:
    timeframe = str(case["timeframe"]); parent = prices.parents[timeframe]; sign = 1 if case["direction"] == "UP" else -1
    known_ns = dt_ns(parse_dt(str(case["known_at_utc"])))
    confirmation_high = int(parent.high_e8[confirmation_index]); confirmation_low = int(parent.low_e8[confirmation_index]); decision_close = int(parent.close_e8[confirmation_index])
    trigger_parent_index = confirmation_index + 4
    wait_deadline = int(parent.close_ns[trigger_parent_index]) if trigger_parent_index < len(parent.close_ns) else END_NS
    wait_end = int(np.searchsorted(prices.open_ns, wait_deadline, side="left"))
    wait_end = min(wait_end, len(prices.open_ns))
    break_level = confirmation_high if sign > 0 else confirmation_low
    pivot = int(case["pivot_price_e8"]); atr = float(case["atr14_e8"]); reference = int(case["reference_level_e8"])

    def unavailable(name: str, reason: str) -> dict[str, Any]:
        return {
            "pullback_id": case["pullback_id"], "timeframe": timeframe, "direction": case["direction"], "known_at_utc": case["known_at_utc"],
            "trigger": name, "status": "NO_TRIGGER", "reason": reason, "entry_index": None, "entry_at_utc": None, "entry_e8": None,
            "entry_delay_minutes": None, "entry_spread_usd_oz": None, "confirmation_high_e8": confirmation_high,
            "confirmation_low_e8": confirmation_low, "decision_close_e8": decision_close, "pivot_price_e8": pivot,
            "reference_level_e8": reference, "atr14_e8": atr, "trigger_lineage_hash": canonical_hash([case["feature_lineage_hash"], name, reason]),
        }

    def formed(name: str, index: int, price: int, lineage: Any) -> dict[str, Any]:
        spread = float(prices.spread[index]); spread_value = None if not math.isfinite(spread) or spread < 0 else spread
        return {
            "pullback_id": case["pullback_id"], "timeframe": timeframe, "direction": case["direction"], "known_at_utc": case["known_at_utc"],
            "trigger": name, "status": "FORMED", "reason": "", "entry_index": index, "entry_at_utc": ns_iso(int(prices.open_ns[index])),
            "entry_e8": price, "entry_delay_minutes": rounded((int(prices.open_ns[index]) - known_ns) / 60_000_000_000),
            "entry_spread_usd_oz": spread_value, "confirmation_high_e8": confirmation_high, "confirmation_low_e8": confirmation_low,
            "decision_close_e8": decision_close, "pivot_price_e8": pivot, "reference_level_e8": reference, "atr14_e8": atr,
            "trigger_lineage_hash": canonical_hash([case["feature_lineage_hash"], name, index, price, lineage]),
        }

    rows = [formed("IMMEDIATE", anchor_index, int(prices.open_e8[anchor_index]), "FIRST_AVAILABLE_OPEN")]
    highs = prices.high_e8[anchor_index:wait_end]; lows = prices.low_e8[anchor_index:wait_end]
    breaks = np.flatnonzero(highs >= break_level if sign > 0 else lows <= break_level)
    break_index = anchor_index + int(breaks[0]) if len(breaks) else None
    if break_index is None:
        rows.append(unavailable("CONFIRMATION_EXTREME_BREAK", "BREAK_NOT_REACHED_WITHIN_4_PARENT_BARS"))
    else:
        break_fill = max(int(prices.open_e8[break_index]), break_level) if sign > 0 else min(int(prices.open_e8[break_index]), break_level)
        rows.append(formed("CONFIRMATION_EXTREME_BREAK", break_index, break_fill, break_level))

    half_level = int(round((decision_close + pivot) / 2))
    half_hits = np.flatnonzero(lows <= half_level if sign > 0 else highs >= half_level)
    if len(half_hits):
        index = anchor_index + int(half_hits[0]); rows.append(formed("RESPONSE_HALF_RETRACE_LIMIT", index, half_level, half_level))
    else:
        rows.append(unavailable("RESPONSE_HALF_RETRACE_LIMIT", "HALF_RETRACE_NOT_REACHED_WITHIN_4_PARENT_BARS"))

    invalidation = pivot - int(round(0.15 * atr)) if sign > 0 else pivot + int(round(0.15 * atr))
    reference_valid = invalidation < reference < decision_close if sign > 0 else decision_close < reference < invalidation
    if not reference_valid:
        rows.append(unavailable("REFERENCE_LEVEL_RETEST_LIMIT", "REFERENCE_NOT_BETWEEN_DECISION_AND_INVALIDATION"))
    else:
        ref_hits = np.flatnonzero(lows <= reference if sign > 0 else highs >= reference)
        if len(ref_hits):
            index = anchor_index + int(ref_hits[0]); rows.append(formed("REFERENCE_LEVEL_RETEST_LIMIT", index, reference, reference))
        else:
            rows.append(unavailable("REFERENCE_LEVEL_RETEST_LIMIT", "REFERENCE_NOT_RETESTED_WITHIN_4_PARENT_BARS"))

    retest_entry = None
    if break_index is not None:
        for index in range(break_index + 1, wait_end):
            touched = int(prices.low_e8[index]) <= break_level if sign > 0 else int(prices.high_e8[index]) >= break_level
            closed_trend_side = int(prices.close_e8[index]) > break_level if sign > 0 else int(prices.close_e8[index]) < break_level
            if touched and closed_trend_side:
                next_index = index + 1
                if next_index < len(prices.open_ns) and int(prices.open_ns[next_index]) - int(prices.open_ns[index]) <= 60_000_000_000:
                    retest_entry = next_index
                break
    if retest_entry is None:
        rows.append(unavailable("BREAK_RETEST_CONFIRM", "NO_COMPLETED_BREAK_RETEST_ENTRY_WITHIN_4_PARENT_BARS"))
    else:
        rows.append(formed("BREAK_RETEST_CONFIRM", retest_entry, int(prices.open_e8[retest_entry]), [break_index, retest_entry]))
    if [row["trigger"] for row in rows] != TRIGGERS:
        raise ValueError("Trigger order changed")
    return rows


def anatomy_row(case: Mapping[str, Any], prices: PriceData, implementation: str) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    timeframe = str(case["timeframe"]); parent = prices.parents[timeframe]; known_ns = dt_ns(parse_dt(str(case["known_at_utc"])))
    confirmation_index = parent_index(parent, known_ns)
    base = {
        "pullback_id": case["pullback_id"], "timeframe": timeframe, "scale": case["scale"], "direction": case["direction"],
        "known_at_utc": case["known_at_utc"], "resolution": case["resolution"], "atr14_e8": float(case["atr14_e8"]),
        "feature_lineage_hash": case["feature_lineage_hash"], "resolution_hash": case["resolution_hash"],
    }
    if confirmation_index is None:
        return {**base, "anatomy_available": False, "unavailable_reason": "MISSING_CONFIRMATION_PARENT_BAR", "anatomy_lineage_hash": canonical_hash([case["feature_lineage_hash"], "MISSING_CONFIRMATION_PARENT_BAR"])}, []
    anchor_index = int(np.searchsorted(prices.open_ns, known_ns, side="left"))
    if anchor_index >= len(prices.open_ns) or int(prices.open_ns[anchor_index]) - known_ns > 300_000_000_000:
        return {**base, "anatomy_available": False, "unavailable_reason": "MISSING_M1_ANCHOR", "anatomy_lineage_hash": canonical_hash([case["feature_lineage_hash"], "MISSING_M1_ANCHOR"])}, []
    entry = int(prices.open_e8[anchor_index]); atr = float(case["atr14_e8"]); sign = 1 if case["direction"] == "UP" else -1
    row: dict[str, Any] = {
        **base, "anatomy_available": True, "unavailable_reason": "", "anchor_index": anchor_index,
        "anchor_at_utc": ns_iso(int(prices.open_ns[anchor_index])), "anchor_delay_minutes": rounded((int(prices.open_ns[anchor_index]) - known_ns) / 60_000_000_000),
        "anchor_open_e8": entry, "confirmation_parent_index": confirmation_index,
    }
    for horizon in MINUTE_HORIZONS:
        expected_last = int(prices.open_ns[anchor_index]) + (horizon - 1) * 60_000_000_000
        end = anchor_index + horizon
        complete = end <= len(prices.open_ns) and int(prices.open_ns[end - 1]) == expected_last
        prefix = f"m{horizon}"
        if not complete:
            row.update({f"{prefix}_complete": False, f"{prefix}_displacement_atr": None, f"{prefix}_mfe_atr": None, f"{prefix}_mae_atr": None})
            continue
        path = slice(anchor_index, end); favourable, adverse, terminal, _, _ = excursion(prices, path, entry, sign)
        row.update({f"{prefix}_complete": True, f"{prefix}_displacement_atr": rounded(terminal / atr), f"{prefix}_mfe_atr": rounded(favourable / atr), f"{prefix}_mae_atr": rounded(adverse / atr)})
    full_slice = None
    for horizon in PARENT_HORIZONS:
        deadline_index = confirmation_index + horizon
        prefix = f"p{horizon}"
        if deadline_index >= len(parent.close_ns):
            row.update({f"{prefix}_complete": False, f"{prefix}_displacement_atr": None, f"{prefix}_mfe_atr": None, f"{prefix}_mae_atr": None})
            continue
        path, _ = complete_slice(prices, anchor_index, int(parent.close_ns[deadline_index]))
        if path is None:
            row.update({f"{prefix}_complete": False, f"{prefix}_displacement_atr": None, f"{prefix}_mfe_atr": None, f"{prefix}_mae_atr": None})
            continue
        favourable, adverse, terminal, favourable_index, adverse_index = excursion(prices, path, entry, sign)
        row.update({f"{prefix}_complete": True, f"{prefix}_displacement_atr": rounded(terminal / atr), f"{prefix}_mfe_atr": rounded(favourable / atr), f"{prefix}_mae_atr": rounded(adverse / atr)})
        if horizon == 16:
            full_slice = path
            row.update({
                "complete_mfe_atr": rounded(favourable / atr), "complete_mae_atr": rounded(adverse / atr),
                "terminal_displacement_atr": rounded(terminal / atr), "m1_bars_in_complete_path": int(path.stop - path.start),
                "bars_to_max_favourable": favourable_index, "bars_to_max_adverse": adverse_index,
                "minutes_to_max_favourable": int((int(prices.open_ns[path.start + favourable_index]) - int(prices.open_ns[path.start])) / 60_000_000_000),
                "minutes_to_max_adverse": int((int(prices.open_ns[path.start + adverse_index]) - int(prices.open_ns[path.start])) / 60_000_000_000),
            })
    if full_slice is None:
        row.update({"complete_path_available": False, "path_classification": "INCOMPLETE_16_PARENT_BAR_PATH"})
    else:
        row["complete_path_available"] = True
        highs = prices.high_e8[full_slice]; lows = prices.low_e8[full_slice]
        for barrier in BARRIERS:
            code = str(barrier).replace(".", "p")
            favourable, adverse, order = first_passage(highs, lows, entry, atr, sign, barrier, implementation)
            row[f"barrier_{code}_favourable_bar"] = favourable
            row[f"barrier_{code}_adverse_bar"] = adverse
            row[f"barrier_{code}_order"] = order
            row[f"barrier_{code}_favourable_minutes"] = None if favourable is None else int((int(prices.open_ns[full_slice.start + favourable]) - int(prices.open_ns[full_slice.start])) / 60_000_000_000)
            row[f"barrier_{code}_adverse_minutes"] = None if adverse is None else int((int(prices.open_ns[full_slice.start + adverse]) - int(prices.open_ns[full_slice.start])) / 60_000_000_000)
        order_05 = row["barrier_0p5_order"]
        row["path_classification"] = "CONTINUATION_FIRST" if order_05 == "FAVOURABLE_FIRST" else "REVERSAL_FIRST" if order_05 == "ADVERSE_FIRST" else "AMBIGUOUS_SAME_BAR" if order_05 == "BOTH_SAME_BAR" else "COMPRESSION_NEITHER"
    trigger_values = trigger_rows(case, prices, confirmation_index, anchor_index)
    row["anatomy_lineage_hash"] = canonical_hash([case["feature_lineage_hash"], case["resolution_hash"], anchor_index, row.get("path_classification"), [item["trigger_lineage_hash"] for item in trigger_values]])
    return row, trigger_values


def materialize(cases: Sequence[Mapping[str, Any]], prices: PriceData, implementation: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    anatomy: list[dict[str, Any]] = []; triggers: list[dict[str, Any]] = []
    for case in cases:
        row, trigger_rows_value = anatomy_row(case, prices, implementation)
        anatomy.append(row); triggers.extend(trigger_rows_value)
    anatomy.sort(key=lambda row: (row["known_at_utc"], row["timeframe"], row["pullback_id"]))
    triggers.sort(key=lambda row: (row["known_at_utc"], row["timeframe"], row["pullback_id"], TRIGGERS.index(str(row["trigger"]))))
    return anatomy, triggers


def selftest() -> None:
    highs = np.asarray([105, 104, 110], dtype=np.int64); lows = np.asarray([95, 96, 98], dtype=np.int64)
    primary = first_passage(highs, lows, 100, 10.0, 1, 0.5, "primary")
    reference = first_passage(highs, lows, 100, 10.0, 1, 0.5, "reference")
    if primary != reference or primary != (0, 0, "BOTH_SAME_BAR"):
        raise ValueError("First-passage selftest failed")


def main() -> None:
    selftest()
    outputs = (PRIMARY_ANATOMY, REFERENCE_ANATOMY, PRIMARY_TRIGGERS, REFERENCE_TRIGGERS, CERTIFICATION, PRETEST_SEAL, STATE)
    if any(path.exists() for path in outputs):
        raise FileExistsError("Movement-anatomy artifact already exists")
    freeze = verify_freeze(); cases = eligible_cases(); prices = load_price()
    primary_anatomy, primary_triggers = materialize(cases, prices, "primary")
    reference_anatomy, reference_triggers = materialize(cases, prices, "reference")
    if primary_anatomy != reference_anatomy or primary_triggers != reference_triggers:
        raise ValueError("Primary/reference movement anatomy differs")
    write_parquet_exclusive(PRIMARY_ANATOMY, primary_anatomy); write_parquet_exclusive(REFERENCE_ANATOMY, reference_anatomy)
    write_parquet_exclusive(PRIMARY_TRIGGERS, primary_triggers); write_parquet_exclusive(REFERENCE_TRIGGERS, reference_triggers)
    if sha256_file(PRIMARY_ANATOMY) != sha256_file(REFERENCE_ANATOMY) or sha256_file(PRIMARY_TRIGGERS) != sha256_file(REFERENCE_TRIGGERS):
        raise ValueError("Primary/reference Parquet bytes differ")
    available = [row for row in primary_anatomy if row["anatomy_available"]]
    complete = [row for row in available if row.get("complete_path_available")]
    certification = {
        "version": "GOLD_TPMA_EDGE_V1_MOVEMENT_ANATOMY_CERTIFICATION_1_0", "status": "PASS_MOVEMENT_ANATOMY_MATERIALIZATION",
        "certified_at_utc": utc_now(), "eligible_cases": len(cases), "anatomy_available": len(available), "complete_16_parent_paths": len(complete),
        "timeframe_counts": {timeframe: sum(row["timeframe"] == timeframe for row in primary_anatomy) for timeframe in TF_MINUTES},
        "path_classifications": dict(sorted({key: sum(row.get("path_classification") == key for row in primary_anatomy) for key in sorted({str(row.get("path_classification")) for row in primary_anatomy})}.items())),
        "trigger_rows": len(primary_triggers), "trigger_status_counts": dict(sorted({trigger: {status: sum(row["trigger"] == trigger and row["status"] == status for row in primary_triggers) for status in ("FORMED", "NO_TRIGGER")} for trigger in TRIGGERS}.items())),
        "price_diagnostics": prices.diagnostics, "primary_anatomy": file_record(PRIMARY_ANATOMY), "reference_anatomy": file_record(REFERENCE_ANATOMY),
        "primary_triggers": file_record(PRIMARY_TRIGGERS), "reference_triggers": file_record(REFERENCE_TRIGGERS),
        "primary_reference_exact": True, "forward_values_accessed": False, "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(CERTIFICATION, certification)
    pretest = {
        "version": "GOLD_TPMA_EDGE_V1_PRETEST_SEAL_1_0", "status": "SEALED_MOVEMENT_ANATOMY_AND_TRIGGER_POPULATION_BEFORE_GRID_TEST",
        "sealed_at_utc": utc_now(), "design_freeze": file_record(FREEZE), "implementation": file_record(Path(__file__).resolve()),
        "certification": file_record(CERTIFICATION), "primary_anatomy": file_record(PRIMARY_ANATOMY), "reference_anatomy": file_record(REFERENCE_ANATOMY),
        "primary_triggers": file_record(PRIMARY_TRIGGERS), "reference_triggers": file_record(REFERENCE_TRIGGERS), "forward_values_accessed": False,
    }
    write_json_exclusive(PRETEST_SEAL, pretest)
    write_json_exclusive(STATE, {"version": "GOLD_TPMA_EDGE_V1_STATE_M2_1_0", "status": certification["status"], "recorded_at_utc": utc_now(), "pretest_seal": file_record(PRETEST_SEAL), "next_step": "RUN_FROZEN_EXECUTION_GRID_WALK_FORWARD"})
    print(json.dumps({"status": certification["status"], "cases": len(cases), "complete_paths": len(complete), "triggers": certification["trigger_status_counts"], "pretest_seal": file_record(PRETEST_SEAL)}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
