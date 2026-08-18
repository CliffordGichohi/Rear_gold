from __future__ import annotations

import bisect
import hashlib
import importlib.util
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np


ROOT = Path(__file__).resolve().parents[1]
LEGACY_PATH = ROOT / "tools/run_multi_asset_macro_session_portfolio_v1_m3.py"
UTC = timezone.utc
THRESHOLDS = (0.25, 0.50, 1.00, 1.50, 2.00, 3.00)
TIMEFRAMES = {"M15": 15, "H1": 60, "H4": 240}
MONTHS = 41

INSTRUMENTS: dict[str, dict[str, Any]] = {
    "XAGUSD": {"research_id": "XAGUSD", "cluster": "PRECIOUS_METALS", "point": 0.001, "contract": 1000.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "USD", "round_increment": 0.50},
    "EURUSD": {"research_id": "EURUSD", "cluster": "USD_FX", "point": 0.00001, "contract": 100000.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "USD", "round_increment": 0.005},
    "USDJPY": {"research_id": "USDJPY", "cluster": "USD_FX", "point": 0.001, "contract": 100000.0, "volume_min": 0.01, "volume_step": 0.01, "quote": "JPY", "round_increment": 0.50},
    "USTEC": {"research_id": "NAS100", "cluster": "US_EQUITY_INDICES", "point": 0.01, "contract": 1.0, "volume_min": 0.1, "volume_step": 0.1, "quote": "USD", "round_increment": 100.0},
    "US500": {"research_id": "US500", "cluster": "US_EQUITY_INDICES", "point": 0.01, "contract": 1.0, "volume_min": 0.1, "volume_step": 0.1, "quote": "USD", "round_increment": 25.0},
    "XTIUSD": {"research_id": "WTI", "cluster": "ENERGY", "point": 0.01, "contract": 100.0, "volume_min": 0.5, "volume_step": 0.5, "quote": "USD", "round_increment": 1.0},
}


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def minute_of(raw: str | datetime) -> int:
    value = raw if isinstance(raw, datetime) else datetime.fromisoformat(raw.replace("Z", "+00:00"))
    return int(value.astimezone(UTC).timestamp() // 60)


def iso_minute(value: int) -> str:
    return datetime.fromtimestamp(value * 60, UTC).isoformat().replace("+00:00", "Z")


def rounded(value: float | int | None) -> float | int | None:
    if value is None:
        return None
    if isinstance(value, int):
        return value
    if not math.isfinite(float(value)):
        return None
    result = round(float(value), 10)
    return 0.0 if result == 0 else result


def normalize_payload(value: Any) -> Any:
    """Canonicalize floating-point leaves before independent checksumming."""
    if isinstance(value, dict):
        return {str(key): normalize_payload(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [normalize_payload(item) for item in value]
    if isinstance(value, (np.floating, float)):
        return rounded(float(value))
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def load_legacy() -> Any:
    spec = importlib.util.spec_from_file_location("msbam_legacy_m3", LEGACY_PATH)
    if not spec or not spec.loader:
        raise RuntimeError("Cannot import sealed legacy utilities")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def patch_sources(legacy: Any, inventory: Mapping[str, Sequence[Path]]) -> None:
    def exact_sources(symbol: str) -> list[Path]:
        if symbol not in inventory:
            raise KeyError(symbol)
        return list(inventory[symbol])
    legacy.mt5_source_files = exact_sources


def pressure_payload(legacy: Any, series: Any, decision: int) -> dict[str, Any]:
    state = legacy.pressure_state(series, decision)
    return {key: rounded(value) if isinstance(value, float) else value for key, value in state.items()}


def structure_payload(bundle: Any, size: int, decision: int) -> dict[str, Any]:
    highs = [row for row in bundle.swings[size]["HIGH"] if int(row[0]) <= decision]
    lows = [row for row in bundle.swings[size]["LOW"] if int(row[0]) <= decision]
    state = "UNKNOWN"
    if len(highs) >= 2 and len(lows) >= 2:
        higher_high = highs[-1][2] > highs[-2][2]
        higher_low = lows[-1][2] > lows[-2][2]
        lower_high = highs[-1][2] < highs[-2][2]
        lower_low = lows[-1][2] < lows[-2][2]
        state = "UPTREND" if higher_high and higher_low else "DOWNTREND" if lower_high and lower_low else "RANGE_OR_TRANSITION"
    series = {15: bundle.m15, 60: bundle.h1, 240: bundle.h4}[size]
    index = series.latest_index(decision)
    bos = "NONE"
    if index >= 0 and highs and float(series.close[index]) > float(highs[-1][2]):
        bos = "BULLISH_BREAK"
    elif index >= 0 and lows and float(series.close[index]) < float(lows[-1][2]):
        bos = "BEARISH_BREAK"
    return {
        "state": state, "bos_mss": bos,
        "latest_high": rounded(highs[-1][2]) if highs else None,
        "latest_high_known_minute": int(highs[-1][0]) if highs else None,
        "latest_low": rounded(lows[-1][2]) if lows else None,
        "latest_low_known_minute": int(lows[-1][0]) if lows else None,
    }


def raw_slice(series: Any, start: int, end: int) -> tuple[int, int]:
    return int(np.searchsorted(series.minute, start, side="left")), int(np.searchsorted(series.minute, end, side="left"))


def level(level_id: str, family: str, side: str, price: float, known: int) -> dict[str, Any]:
    return {"level_id": level_id, "family": family, "side": side, "price": rounded(price), "known_minute": known}


def known_levels(bundle: Any, case: Mapping[str, Any], prior_case: Mapping[str, Any] | None) -> list[dict[str, Any]]:
    decision = minute_of(str(case["decision_at_utc"]))
    reference_minute = minute_of(str(case["observation_start_utc"]))
    reference_index = bundle.m1.exact_index(reference_minute)
    if reference_index is None:
        return []
    reference = float(bundle.m1.open[reference_index])
    output: list[dict[str, Any]] = []
    for family, series in (("PRIOR_DAY", bundle.d1), ("PRIOR_WEEK", bundle.w1)):
        index = series.latest_index(decision)
        if index >= 0:
            output.extend([
                level(f"{family}_HIGH::{int(series.end[index])}", family, "UPPER", float(series.high[index]), int(series.end[index])),
                level(f"{family}_LOW::{int(series.end[index])}", family, "LOWER", float(series.low[index]), int(series.end[index])),
            ])
    if prior_case is not None:
        start = minute_of(str(prior_case["observation_start_utc"]))
        end = minute_of(str(prior_case["observation_end_utc"]))
        left, right = raw_slice(bundle.m1, start, end)
        if right > left:
            output.extend([
                level(f"PRIOR_SAME_SESSION_HIGH::{end}", "PRIOR_SAME_SESSION", "UPPER", float(np.max(bundle.m1.high[left:right])), end),
                level(f"PRIOR_SAME_SESSION_LOW::{end}", "PRIOR_SAME_SESSION", "LOWER", float(np.min(bundle.m1.low[left:right])), end),
            ])
    for size, family in ((15, "M15_SWING"), (60, "H1_SWING"), (240, "H4_SWING")):
        for kind, side in (("HIGH", "UPPER"), ("LOW", "LOWER")):
            values = [row for row in bundle.swings[size][kind] if int(row[0]) <= decision]
            for known, _, price in values[-2:]:
                output.append(level(f"{family}_{kind}::{known}::{price:.10g}", family, side, float(price), int(known)))
    increment = float(INSTRUMENTS[str(case["instrument"])]["round_increment"])
    lower = math.floor(reference / increment) * increment
    upper = lower + increment
    output.extend([
        level(f"ROUND_LOWER::{lower:.10g}", "ROUND_NUMBER", "LOWER", lower, decision),
        level(f"ROUND_UPPER::{upper:.10g}", "ROUND_NUMBER", "UPPER", upper, decision),
    ])
    unique: dict[tuple[str, str, float], dict[str, Any]] = {}
    for item in output:
        if int(item["known_minute"]) <= decision:
            unique.setdefault((str(item["family"]), str(item["side"]), round(float(item["price"]), 10)), item)
    return sorted(unique.values(), key=lambda item: (item["side"], item["price"], item["level_id"]))


def relative_bars(series: Any, start: int, end: int, size: int) -> list[dict[str, Any]]:
    left, right = raw_slice(series, start, end)
    groups: dict[int, list[int]] = defaultdict(list)
    for index in range(left, right):
        bucket = (int(series.minute[index]) - start) // size
        if bucket >= 0:
            groups[bucket].append(index)
    output: list[dict[str, Any]] = []
    for bucket in sorted(groups):
        bucket_start = start + bucket * size
        bucket_end = min(bucket_start + size, end)
        if bucket_end - bucket_start < size:
            continue
        indexes = groups[bucket]
        output.append({
            "start": bucket_start, "end": bucket_end, "open": float(series.open[indexes[0]]),
            "high": float(np.max(series.high[indexes])), "low": float(np.min(series.low[indexes])),
            "close": float(series.close[indexes[-1]]), "observed_minutes": len(indexes),
        })
    return output


def path_efficiency(m5: Sequence[Mapping[str, Any]]) -> float:
    if len(m5) < 2:
        return 0.0
    closes = np.asarray([float(item["close"]) for item in m5])
    denominator = float(np.sum(np.abs(np.diff(closes))))
    return abs(float(closes[-1] - closes[0])) / denominator if denominator > 0 else 0.0


def turn_count(m5: Sequence[Mapping[str, Any]]) -> int:
    if len(m5) < 5:
        return 0
    highs = [float(item["high"]) for item in m5]
    lows = [float(item["low"]) for item in m5]
    turns = 0
    for index in range(2, len(m5) - 2):
        neighbours = [index - 2, index - 1, index + 1, index + 2]
        turns += int(all(highs[index] > highs[item] for item in neighbours))
        turns += int(all(lows[index] < lows[item] for item in neighbours))
    return turns


def level_interactions(levels: Sequence[Mapping[str, Any]], series: Any, left: int, right: int, m5: Sequence[Mapping[str, Any]], atr: float, session_close: float) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for item in levels:
        price = float(item["price"])
        side = str(item["side"])
        touched = bool(np.any(series.high[left:right] >= price) and np.any(series.low[left:right] <= price))
        if not touched:
            continue
        if side == "UPPER":
            swept = bool(np.max(series.high[left:right]) >= price + 0.05 * atr)
            broken = bool(np.max(series.high[left:right]) >= price + 0.10 * atr)
            beyond = [float(bar["close"]) > price for bar in m5]
            inside = lambda value: value < price
            close_beyond = session_close > price
            direction = 1
        else:
            swept = bool(np.min(series.low[left:right]) <= price - 0.05 * atr)
            broken = bool(np.min(series.low[left:right]) <= price - 0.10 * atr)
            beyond = [float(bar["close"]) < price for bar in m5]
            inside = lambda value: value > price
            close_beyond = session_close < price
            direction = -1
        acceptance_index = next((index for index in range(2, len(beyond)) if all(beyond[index - offset] for offset in (0, 1, 2))), None)
        breach_index = next((index for index, bar in enumerate(m5) if (float(bar["high"]) >= price + 0.10 * atr if side == "UPPER" else float(bar["low"]) <= price - 0.10 * atr)), None)
        reclaim = False
        if breach_index is not None:
            reclaim = any(inside(float(m5[index]["close"])) for index in range(breach_index, min(len(m5), breach_index + 4)))
        kind = "TOUCH"
        if swept and reclaim:
            kind = "SWEEP_REVERSAL"
        elif broken and acceptance_index is not None and close_beyond:
            kind = "BREAKOUT_HOLD"
        elif broken and not close_beyond:
            kind = "FAILED_BREAK"
        elif broken:
            kind = "BREACH_UNRESOLVED"
        output.append({
            "level_id": item["level_id"], "family": item["family"], "side": side,
            "interaction": kind, "direction": direction, "swept": swept, "broken": broken,
            "accepted": acceptance_index is not None, "reclaimed": reclaim,
        })
    return sorted(output, key=lambda item: (item["interaction"], item["level_id"]))


def archetype(interactions: Sequence[Mapping[str, Any]], up_r: float, down_r: float, close_r: float, range_r: float, close_location: float, efficiency: float) -> tuple[str, int]:
    for kind in ("SWEEP_REVERSAL", "FAILED_BREAK", "BREAKOUT_HOLD"):
        matches = [item for item in interactions if item["interaction"] == kind]
        if matches:
            source = matches[0]
            direction = int(source["direction"])
            if kind in {"SWEEP_REVERSAL", "FAILED_BREAK"}:
                direction *= -1
            return kind, direction
    if up_r >= 1.0 and down_r <= 0.25:
        return "ONE_SIDED", 1
    if down_r >= 1.0 and up_r <= 0.25:
        return "ONE_SIDED", -1
    if up_r >= 0.75 and down_r >= 0.75:
        return "TWO_SIDED_EXPANSION", 0
    if abs(close_r) >= 0.50 and efficiency >= 0.35:
        return "TREND", 1 if close_r > 0 else -1
    if range_r <= 0.75 and abs(close_r) <= 0.25:
        return "BALANCED_COMPRESSION", 0
    if efficiency <= 0.20:
        return "ROTATIONAL", 0
    return "MIXED_UNCLASSIFIED", 1 if close_r > 0 else -1 if close_r < 0 else 0


def first_passages(series: Any, left: int, right: int, reference: float, atr: float, start: int) -> dict[str, Any]:
    output: dict[str, Any] = {}
    for threshold in THRESHOLDS:
        up_hits = np.flatnonzero(series.high[left:right] >= reference + threshold * atr)
        down_hits = np.flatnonzero(series.low[left:right] <= reference - threshold * atr)
        up_index = int(up_hits[0]) + left if len(up_hits) else None
        down_index = int(down_hits[0]) + left if len(down_hits) else None
        up_minute = int(series.minute[up_index]) if up_index is not None else None
        down_minute = int(series.minute[down_index]) if down_index is not None else None
        order = "NEITHER"
        if up_minute is not None and down_minute is not None:
            order = "AMBIGUOUS_SAME_BAR" if up_minute == down_minute else "UP_FIRST" if up_minute < down_minute else "DOWN_FIRST"
        elif up_minute is not None:
            order = "UP_ONLY"
        elif down_minute is not None:
            order = "DOWN_ONLY"
        key = str(threshold).replace(".", "P")
        output[key] = {
            "up_elapsed_minutes": up_minute - start if up_minute is not None else None,
            "down_elapsed_minutes": down_minute - start if down_minute is not None else None,
            "order": order,
        }
    return output


def prior_case_map(cases: Sequence[Mapping[str, Any]]) -> dict[str, Mapping[str, Any] | None]:
    output: dict[str, Mapping[str, Any] | None] = {}
    latest: dict[str, Mapping[str, Any]] = {}
    for case in sorted(cases, key=lambda item: (item["session_date_local"], item["instrument"], item["session_code"])):
        unit = f"{case['instrument']}|{case['session_code']}"
        output[str(case["case_id"])] = latest.get(unit)
        latest[unit] = case
    return output


def event_context(macro_book: Any, decision: int) -> dict[str, Any]:
    eligible = [item for item in macro_book.events if int(item["available_minute"]) <= decision and int(item["minute"]) >= decision]
    if not eligible:
        return {"next_event": None, "minutes_to_event": None, "state": "UNKNOWN_OR_NONE"}
    event = min(eligible, key=lambda item: (item["minute"], item["event_code"], item["event_id"]))
    delta = int(event["minute"]) - decision
    return {"next_event": event["family"], "minutes_to_event": delta, "state": "HIGH" if delta <= 240 else "SCHEDULED"}


def materialize_case(legacy: Any, bundle: Any, macro_book: Any, case: Mapping[str, Any], prior_case: Mapping[str, Any] | None) -> dict[str, Any]:
    decision = minute_of(str(case["decision_at_utc"]))
    start = minute_of(str(case["observation_start_utc"]))
    end = minute_of(str(case["observation_end_utc"]))
    reference_index = bundle.m1.exact_index(start)
    left, right = raw_slice(bundle.m1, start, end)
    base = {
        "case_id": case["case_id"], "instrument": case["instrument"], "research_id": case["research_id"],
        "cluster": INSTRUMENTS[str(case["instrument"])]["cluster"], "unit": f"{case['instrument']}|{case['session_code']}",
        "session_code": case["session_code"], "session_date_local": case["session_date_local"],
        "decision_minute": decision, "observation_start_minute": start, "observation_end_minute": end,
        "path_disposition": case["path_disposition"],
    }
    if reference_index is None or right <= left:
        return {**base, "materialization_status": "DATA_UNAVAILABLE", "archetype": "DATA_UNAVAILABLE", "archetype_direction": 0, "reason": "REFERENCE_OR_PATH_MISSING"}
    atr = legacy.atr_at(bundle.m15, decision, length=14)
    if atr is None or atr <= 0:
        return {**base, "materialization_status": "DATA_UNAVAILABLE", "archetype": "DATA_UNAVAILABLE", "archetype_direction": 0, "reason": "PREDECISION_ATR_UNAVAILABLE"}
    reference = float(bundle.m1.open[reference_index])
    high_index = left + int(np.argmax(bundle.m1.high[left:right]))
    low_index = left + int(np.argmin(bundle.m1.low[left:right]))
    maximum = float(bundle.m1.high[high_index])
    minimum = float(bundle.m1.low[low_index])
    close = float(bundle.m1.close[right - 1])
    up = max(0.0, maximum - reference)
    down = max(0.0, reference - minimum)
    session_range = maximum - minimum
    close_r = (close - reference) / atr
    m5 = relative_bars(bundle.m1, start, end, 5)
    efficiency = path_efficiency(m5)
    location = (close - minimum) / session_range if session_range > 0 else 0.5
    levels = known_levels(bundle, case, prior_case)
    interactions = level_interactions(levels, bundle.m1, left, right, m5, atr, close)
    archetype_name, archetype_direction = archetype(interactions, up / atr, down / atr, close_r, session_range / atr, location, efficiency)
    horizons: dict[str, Any] = {}
    for horizon in (5, 15, 30, 60, 120):
        bound = min(end, start + horizon)
        _, horizon_right = raw_slice(bundle.m1, start, bound)
        value = float(bundle.m1.close[horizon_right - 1] - reference) if horizon_right > left else None
        horizons[str(horizon)] = {"signed": rounded(value), "absolute": rounded(abs(value)) if value is not None else None, "signed_r": rounded(value / atr) if value is not None else None}
    closes = bundle.m1.close[left:right]
    realized = float(math.sqrt(float(np.sum(np.diff(np.log(closes)) ** 2)))) if len(closes) > 1 and np.all(closes > 0) else None
    macro = macro_book.context(str(case["instrument"]), decision, 1)
    macro_payload = {
        "score": macro.get("score"), "confidence": macro.get("confidence"), "direction": macro.get("macro_direction"),
        "bias": "BULLISH" if macro.get("macro_direction") == 1 else "BEARISH" if macro.get("macro_direction") == -1 else "NEUTRAL_OR_UNKNOWN",
        "components": macro.get("components"), "cot_metals_context": macro.get("cot_metals_context"),
    }
    pre_index = bundle.m1.exact_index(decision)
    mechanics = {
        "spread_points": rounded(float(bundle.m1.spread[pre_index])) if pre_index is not None else None,
        "tick_volume": rounded(float(bundle.m1.volume[pre_index])) if pre_index is not None else None,
        "timestamp_quality": case["path_disposition"],
    }
    htf = {
        "W1": pressure_payload(legacy, bundle.w1, decision), "D1": pressure_payload(legacy, bundle.d1, decision),
        "H4": pressure_payload(legacy, bundle.h4, decision), "H1": pressure_payload(legacy, bundle.h1, decision),
        "M15": pressure_payload(legacy, bundle.m15, decision), "M5": pressure_payload(legacy, bundle.m5, decision),
    }
    structures = {"M15": structure_payload(bundle, 15, decision), "H1": structure_payload(bundle, 60, decision), "H4": structure_payload(bundle, 240, decision)}
    row = {
        **base, "materialization_status": "VALID", "reason": None,
        "atr15": rounded(atr), "reference_open": rounded(reference), "session_high": rounded(maximum),
        "session_low": rounded(minimum), "session_close": rounded(close), "session_range": rounded(session_range),
        "range_r": rounded(session_range / atr), "up_excursion": rounded(up), "down_excursion": rounded(down),
        "up_excursion_r": rounded(up / atr), "down_excursion_r": rounded(down / atr),
        "long_mfe_r": rounded(up / atr), "long_mae_r": rounded(down / atr),
        "short_mfe_r": rounded(down / atr), "short_mae_r": rounded(up / atr),
        "session_close_displacement": rounded(close - reference), "session_close_r": rounded(close_r),
        "fixed_horizons": horizons, "session_high_minute": int(bundle.m1.minute[high_index]),
        "session_low_minute": int(bundle.m1.minute[low_index]),
        "high_low_order": "SAME_M1_AMBIGUOUS" if high_index == low_index else "HIGH_FIRST" if high_index < low_index else "LOW_FIRST",
        "close_location": rounded(location), "path_efficiency": rounded(efficiency),
        "realized_path_volatility": rounded(realized), "turning_point_count": turn_count(m5),
        "observed_m1_count": right - left, "expected_wall_clock_minutes": end - start,
        "first_passages": first_passages(bundle.m1, left, right, reference, atr, start),
        "higher_timeframe_states": htf, "structures": structures, "known_levels": levels,
        "level_interactions": interactions, "macro_context": macro_payload, "event_context": event_context(macro_book, decision),
        "mechanics": mechanics, "unknown_contexts": [
            "EXACT_MEETING_PROBABILITIES", "OPTIONS_IV_STRIKES_GAMMA", "ETF_CENTRAL_BANK_FLOWS",
            "CENTRALIZED_FUTURES_ORDER_FLOW_FOR_NON_GOLD_ASSETS", "LICENSED_UNSCHEDULED_NEWS",
        ],
        "archetype": archetype_name, "archetype_direction": archetype_direction,
    }
    row = normalize_payload(row)
    row["lineage_hash"] = canonical_hash(row)
    return row


def atlas(cases: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    valid = [row for row in cases if row["materialization_status"] == "VALID"]
    groups: dict[tuple[str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in valid:
        groups[(str(row["instrument"]), str(row["session_code"]), str(row["archetype"]))].append(row)
    strata: list[dict[str, Any]] = []
    for key, rows in sorted(groups.items()):
        strata.append({
            "instrument": key[0], "session": key[1], "archetype": key[2], "support": len(rows),
            "cases_per_month": rounded(len(rows) / MONTHS),
            "bullish_close_fraction": rounded(sum(float(row["session_close_r"]) > 0 for row in rows) / len(rows)),
            "median_range_r": rounded(float(np.median([row["range_r"] for row in rows]))),
            "median_up_excursion_r": rounded(float(np.median([row["up_excursion_r"] for row in rows]))),
            "median_down_excursion_r": rounded(float(np.median([row["down_excursion_r"] for row in rows]))),
            "median_path_efficiency": rounded(float(np.median([row["path_efficiency"] for row in rows]))),
            "up_1r_first_passage_fraction": rounded(sum(row["first_passages"]["1P0"]["up_elapsed_minutes"] is not None for row in rows) / len(rows)),
            "down_1r_first_passage_fraction": rounded(sum(row["first_passages"]["1P0"]["down_elapsed_minutes"] is not None for row in rows) / len(rows)),
        })
    return {
        "valid_case_count": len(valid), "unavailable_case_count": len(cases) - len(valid),
        "archetype_counts": dict(sorted(Counter(str(row["archetype"]) for row in cases).items())),
        "strata": strata, "atlas_hash": canonical_hash(strata),
    }


def trigger_for_track(series: Any, case: Mapping[str, Any], timeframe: str) -> dict[str, Any] | None:
    start, end = int(case["observation_start_minute"]), int(case["observation_end_minute"])
    reference, atr = float(case["reference_open"]), float(case["atr15"])
    bars = relative_bars(series, start, end, TIMEFRAMES[timeframe])
    for bar in bars:
        width = float(bar["high"] - bar["low"])
        if width <= 0:
            continue
        location = float((bar["close"] - bar["low"]) / width)
        direction = 1 if float(bar["close"]) >= reference + 0.25 * atr and location >= 0.75 else -1 if float(bar["close"]) <= reference - 0.25 * atr and location <= 0.25 else 0
        if direction == 0:
            continue
        available = int(bar["end"])
        desired_entry = available + 1
        index = int(np.searchsorted(series.minute, desired_entry, side="left"))
        if index >= len(series.minute) or int(series.minute[index]) >= end or int(series.minute[index]) > desired_entry + 2:
            return None
        return {"direction": direction, "trigger_available_minute": available, "entry_index": index, "entry_minute": int(series.minute[index]), "entry": float(series.open[index])}
    return None


def position_size(symbol: str, entry: float, atr: float, planned_usd: float = 100.0) -> tuple[float, float]:
    spec = INSTRUMENTS[symbol]
    risk_per_lot = atr * float(spec["contract"])
    if spec["quote"] == "JPY":
        risk_per_lot /= entry
    step = float(spec["volume_step"])
    volume = math.floor((planned_usd / risk_per_lot + 1e-12) / step) * step if risk_per_lot > 0 else 0.0
    if volume < float(spec["volume_min"]):
        return 0.0, 0.0
    return rounded(volume), rounded(volume * risk_per_lot)


def feasibility_row(series: Any, case: Mapping[str, Any], timeframe: str) -> dict[str, Any]:
    symbol = str(case["instrument"])
    atr = float(case["atr15"])
    stage1 = max(float(case["up_excursion_r"]), float(case["down_excursion_r"]))
    trigger = trigger_for_track(series, case, timeframe)
    base = {
        "case_id": case["case_id"], "instrument": symbol, "research_id": case["research_id"],
        "cluster": case["cluster"], "session": case["session_code"], "session_date": case["session_date_local"],
        "archetype": case["archetype"], "timeframe": timeframe, "stage1_full_path_ceiling_r": rounded(stage1),
        "session_close_direction": 1 if float(case["session_close_r"]) > 0 else -1 if float(case["session_close_r"]) < 0 else 0,
        "up_excursion_r": case["up_excursion_r"], "down_excursion_r": case["down_excursion_r"],
        "long_mfe_r": case["long_mfe_r"], "long_mae_r": case["long_mae_r"],
        "short_mfe_r": case["short_mfe_r"], "short_mae_r": case["short_mae_r"],
        "up_1r_reached": case["first_passages"]["1P0"]["up_elapsed_minutes"] is not None,
        "down_1r_reached": case["first_passages"]["1P0"]["down_elapsed_minutes"] is not None,
        "one_r_first_passage_order": case["first_passages"]["1P0"]["order"],
    }
    if trigger is None:
        return {**base, "triggered": False, "stage2_observable_ceiling_r": 0.0, "stage3_stop_feasible_gross_r": 0.0, "cost_r": 0.0, "stage3_net_r": 0.0, "portfolio_accepted": False, "stage4_portfolio_net_r": 0.0, "net_pnl_usd": 0.0}
    direction = int(trigger["direction"])
    entry_index = int(trigger["entry_index"])
    entry = float(trigger["entry"])
    end = int(case["observation_end_minute"])
    _, right = raw_slice(series, int(trigger["entry_minute"]), end)
    if right <= entry_index:
        return {**base, "triggered": False, "stage2_observable_ceiling_r": 0.0, "stage3_stop_feasible_gross_r": 0.0, "cost_r": 0.0, "stage3_net_r": 0.0, "portfolio_accepted": False, "stage4_portfolio_net_r": 0.0, "net_pnl_usd": 0.0}
    future_mfe = float(np.max(series.high[entry_index:right]) - entry) if direction == 1 else float(entry - np.min(series.low[entry_index:right]))
    stage2 = max(0.0, future_mfe / atr)
    stop, target = (entry - atr, entry + atr) if direction == 1 else (entry + atr, entry - atr)
    exit_index = right - 1
    gross = max(-1.0, min(1.0, direction * (float(series.close[exit_index]) - entry) / atr))
    reason = "TIME_EXIT"
    for index in range(entry_index, right):
        opened, high, low = float(series.open[index]), float(series.high[index]), float(series.low[index])
        if direction == 1:
            if opened <= stop:
                gross, reason, exit_index = (opened - entry) / atr, "STOP_GAP", index
                break
            if opened >= target:
                gross, reason, exit_index = 1.0, "TARGET_GAP", index
                break
            stop_hit, target_hit = low <= stop, high >= target
        else:
            if opened >= stop:
                gross, reason, exit_index = (entry - opened) / atr, "STOP_GAP", index
                break
            if opened <= target:
                gross, reason, exit_index = 1.0, "TARGET_GAP", index
                break
            stop_hit, target_hit = high >= stop, low <= target
        if stop_hit:
            gross, reason, exit_index = -1.0, "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP", index
            break
        if target_hit:
            gross, reason, exit_index = 1.0, "TARGET", index
            break
    point = float(INSTRUMENTS[symbol]["point"])
    entry_spread = float(series.spread[entry_index]) * point
    exit_spread = float(series.spread[exit_index]) * point
    cost = max(max(entry_spread, exit_spread) / atr + 0.03, 0.05)
    volume, actual_risk = position_size(symbol, entry, atr)
    executable = bool(volume and actual_risk)
    net = gross - cost if executable else 0.0
    return {
        **base, "triggered": True, "direction": direction,
        "trigger_available_minute": trigger["trigger_available_minute"], "entry_minute": trigger["entry_minute"],
        "entry": rounded(entry), "stop": rounded(stop), "target": rounded(target),
        "exit_minute": int(series.minute[exit_index]), "exit_reason": reason,
        "stage2_observable_ceiling_r": rounded(stage2), "stage3_stop_feasible_gross_r": rounded(gross),
        "cost_r": rounded(cost), "stage3_net_r": rounded(net), "planned_risk_usd": 100.0,
        "volume": volume, "actual_risk_usd": actual_risk, "size_executable": executable,
        "portfolio_accepted": False, "stage4_portfolio_net_r": 0.0,
        "net_pnl_usd": rounded(net * float(actual_risk)) if executable else 0.0,
    }


def apply_portfolio(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    output = [dict(row) for row in rows]
    candidates = [(index, row) for index, row in enumerate(output) if row.get("triggered") and row.get("size_executable")]
    candidates.sort(key=lambda item: (int(item[1]["entry_minute"]), str(item[1]["instrument"]), str(item[1]["case_id"]), str(item[1]["timeframe"])))
    active_until: dict[str, int] = {}
    for index, row in candidates:
        cluster = str(row["cluster"])
        if int(row["entry_minute"]) < active_until.get(cluster, -1):
            output[index]["portfolio_rejection"] = "CONCURRENT_CLUSTER_RISK_CAP"
            continue
        output[index]["portfolio_accepted"] = True
        output[index]["stage4_portfolio_net_r"] = row["stage3_net_r"]
        active_until[cluster] = int(row["exit_minute"]) + 1
    return output


def earliest_track_per_case(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[str(row["case_id"])].append(row)
    output: list[dict[str, Any]] = []
    priority = {"M15": 0, "H1": 1, "H4": 2}
    for case_id, values in groups.items():
        triggered = [row for row in values if row.get("triggered")]
        if triggered:
            chosen = min(triggered, key=lambda row: (int(row["entry_minute"]), priority[str(row["timeframe"])]))
        else:
            chosen = min(values, key=lambda row: priority[str(row["timeframe"])] )
        item = dict(chosen)
        item["timeframe"] = "COMBINED_EARLIEST"
        output.append(item)
    return sorted(output, key=lambda row: (row["session_date"], row["instrument"], row["session"], row["case_id"]))


def max_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def summarize_feasibility(rows: Sequence[Mapping[str, Any]], label: str) -> dict[str, Any]:
    accepted = [row for row in rows if row.get("portfolio_accepted")]
    ordered = sorted(accepted, key=lambda row: (row["entry_minute"], row["instrument"], row["case_id"]))
    stage1 = sum(float(row["stage1_full_path_ceiling_r"]) for row in rows)
    stage2 = sum(float(row["stage2_observable_ceiling_r"]) for row in rows)
    stage3 = sum(float(row["stage3_stop_feasible_gross_r"]) for row in rows)
    stage4 = sum(float(row["stage4_portfolio_net_r"]) for row in rows)
    dollars = sum(float(row["net_pnl_usd"]) for row in accepted)
    return {
        "label": label, "case_count": len(rows), "trigger_count": sum(bool(row.get("triggered")) for row in rows),
        "accepted_trade_count": len(accepted), "accepted_trades_per_month": rounded(len(accepted) / MONTHS),
        "stage1_full_path_ceiling_total_r": rounded(stage1), "stage1_r_per_month": rounded(stage1 / MONTHS),
        "stage2_observable_ceiling_total_r": rounded(stage2), "stage2_r_per_month": rounded(stage2 / MONTHS),
        "stage3_stop_feasible_gross_total_r": rounded(stage3), "stage3_r_per_month": rounded(stage3 / MONTHS),
        "stage4_portfolio_net_total_r": rounded(stage4), "stage4_net_r_per_month": rounded(stage4 / MONTHS),
        "stage4_dollars_per_month": rounded(dollars / MONTHS),
        "stage1_to_stage2_loss_r_per_month": rounded((stage1 - stage2) / MONTHS),
        "stage2_to_stage3_loss_r_per_month": rounded((stage2 - stage3) / MONTHS),
        "stage3_to_stage4_loss_r_per_month": rounded((stage3 - stage4) / MONTHS),
        "stage1_to_stage2_retention_pct": rounded(100.0 * stage2 / stage1) if stage1 else None,
        "stage2_to_stage3_retention_pct": rounded(100.0 * stage3 / stage2) if stage2 else None,
        "stage3_to_stage4_retention_pct": rounded(100.0 * stage4 / stage3) if stage3 else None,
        "max_drawdown_r": rounded(max_drawdown([float(row["stage4_portfolio_net_r"]) for row in ordered])),
        "win_rate": rounded(sum(float(row["stage4_portfolio_net_r"]) > 0 for row in accepted) / len(accepted)) if accepted else None,
    }


def strata_feasibility(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str, str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(str(row["instrument"]), str(row["session"]), str(row["timeframe"]), str(row["archetype"]))].append(row)
    output: list[dict[str, Any]] = []
    for key, values in sorted(groups.items()):
        accepted = [row for row in values if row.get("portfolio_accepted")]
        output.append({
            "instrument": key[0], "session": key[1], "timeframe": key[2], "archetype": key[3],
            "support": len(values), "occurrences_per_month": rounded(len(values) / MONTHS),
            "bullish_close_fraction": rounded(sum(int(row["session_close_direction"]) > 0 for row in values) / len(values)),
            "bearish_close_fraction": rounded(sum(int(row["session_close_direction"]) < 0 for row in values) / len(values)),
            "neutral_close_fraction": rounded(sum(int(row["session_close_direction"]) == 0 for row in values) / len(values)),
            "median_long_mfe_r": rounded(float(np.median([row["long_mfe_r"] for row in values]))),
            "median_long_mae_r": rounded(float(np.median([row["long_mae_r"] for row in values]))),
            "median_short_mfe_r": rounded(float(np.median([row["short_mfe_r"] for row in values]))),
            "median_short_mae_r": rounded(float(np.median([row["short_mae_r"] for row in values]))),
            "up_1r_first_passage_fraction": rounded(sum(bool(row["up_1r_reached"]) for row in values) / len(values)),
            "down_1r_first_passage_fraction": rounded(sum(bool(row["down_1r_reached"]) for row in values) / len(values)),
            "trigger_count": sum(bool(row.get("triggered")) for row in values),
            "accepted_count": len(accepted), "stage1_r_per_month": rounded(sum(float(row["stage1_full_path_ceiling_r"]) for row in values) / MONTHS),
            "stage2_r_per_month": rounded(sum(float(row["stage2_observable_ceiling_r"]) for row in values) / MONTHS),
            "stage3_r_per_month": rounded(sum(float(row["stage3_stop_feasible_gross_r"]) for row in values) / MONTHS),
            "stage4_net_r_per_month": rounded(sum(float(row["stage4_portfolio_net_r"]) for row in values) / MONTHS),
            "stage4_dollars_per_month": rounded(sum(float(row["net_pnl_usd"]) for row in accepted) / MONTHS),
            "stage1_to_stage2_loss_r_per_month": rounded(sum(float(row["stage1_full_path_ceiling_r"]) - float(row["stage2_observable_ceiling_r"]) for row in values) / MONTHS),
            "stage2_to_stage3_loss_r_per_month": rounded(sum(float(row["stage2_observable_ceiling_r"]) - float(row["stage3_stop_feasible_gross_r"]) for row in values) / MONTHS),
            "stage3_to_stage4_loss_r_per_month": rounded(sum(float(row["stage3_stop_feasible_gross_r"]) - float(row["stage4_portfolio_net_r"]) for row in values) / MONTHS),
        })
    return output
