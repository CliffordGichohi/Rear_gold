"""Point-in-time entry and structural-stop geometry audit for H1 confirmation V2."""

from __future__ import annotations

from bisect import bisect_left
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import timedelta
from statistics import median
from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import (
    TICK_FLOOR,
    canonical_hash,
    confirmed_swings,
    iso,
    parse_dt,
    true_ranges_and_atr,
)


Direction = Literal["LONG", "SHORT"]

RULESET = "GOLD_H1_CONFIRMATION_ENTRY_STOP_GEOMETRY_AUDIT_V1"
CONTROL_STOP = "CONTROL_V2_FILLED_STOP"
M5_STOP = "M5_LATEST_CONFIRMED_OPPOSING_SWING_ELSE_CONTROL"
M15_STOP = "M15_LATEST_CONFIRMED_OPPOSING_SWING_ELSE_CONTROL"
H1_STOP = "H1_SOURCE_SWING_BUFFERED_ELSE_CONTROL"
STOP_POLICIES = (CONTROL_STOP, M5_STOP, M15_STOP, H1_STOP)

CONTROL_ENTRY = "CONTROL_NEXT_M1_OPEN"
RETEST_ENTRY = "M5_BROKEN_CONTROL_FIRST_RETEST"
SPLIT_ENTRY = "CONFIRMED_25_75_RETEST_SPLIT"
ENTRY_POLICIES = (CONTROL_ENTRY, RETEST_ENTRY, SPLIT_ENTRY)

BUFFER_ATR_FRACTION = 0.05
RETEST_EXPIRY_MINUTES = 15
SPLIT_CONTROL_FRACTION = 0.25
SPLIT_RETEST_FRACTION = 0.75


def valid_geometry(entry: float, stop: float, target: float, direction: Direction) -> bool:
    return stop < entry < target if direction == "LONG" else target < entry < stop


def outward_stop(direction: Direction, level: float, buffer: float) -> float:
    return level - buffer if direction == "LONG" else level + buffer


def stop_buffer(atr: float) -> float:
    if atr <= 0:
        raise ValueError("ATR must be positive")
    return max(BUFFER_ATR_FRACTION * atr, TICK_FLOOR)


def build_structure_registry(
    rows_by_timeframe: Mapping[str, Sequence[Mapping[str, Any]]],
    *,
    cutoff: Any,
) -> dict[str, Any]:
    """Precompute only completed, point-in-time swings and ATR timelines."""

    registry: dict[str, Any] = {}
    for key, label in (("5m", "M5"), ("15m", "M15"), ("1h", "H1")):
        source = [dict(row) for row in rows_by_timeframe[key]]
        bars, swings = confirmed_swings(source, cutoff, label)
        _, atrs = true_ranges_and_atr(bars)
        registry[key] = {
            "bars": bars,
            "swings": swings,
            "atr_timeline": [
                (parse_dt(str(row["available_at"])), float(atr))
                for row, atr in zip(bars, atrs, strict=True)
                if atr is not None and float(atr) > 0
            ],
        }
    registry["registry_sha256"] = canonical_hash(
        {
            key: {
                "swings": value["swings"],
                "atr_timeline": [(iso(point), atr) for point, atr in value["atr_timeline"]],
            }
            for key, value in registry.items()
            if key != "registry_sha256"
        }
    )
    return registry


def _latest_atr(registry: Mapping[str, Any], timeframe: str, cutoff: Any) -> float | None:
    point = parse_dt(cutoff)
    eligible = [value for available, value in registry[timeframe]["atr_timeline"] if available <= point]
    return eligible[-1] if eligible else None


def _latest_opposing_swing(
    registry: Mapping[str, Any], timeframe: str, cutoff: Any, direction: Direction
) -> Mapping[str, Any] | None:
    kind = "LOW" if direction == "LONG" else "HIGH"
    point = parse_dt(cutoff)
    eligible = [
        row
        for row in registry[timeframe]["swings"]
        if str(row["kind"]) == kind and parse_dt(str(row["detected_at"])) <= point
    ]
    return (
        max(
            eligible,
            key=lambda row: (
                parse_dt(str(row["detected_at"])),
                parse_dt(str(row["pivot_at"])),
                str(row["identity"]),
            ),
        )
        if eligible
        else None
    )


def stop_geometry(
    case: Mapping[str, Any], registry: Mapping[str, Any], policy: str
) -> dict[str, Any]:
    """Return the requested structural stop or an explicit unchanged-control fallback."""

    if policy not in STOP_POLICIES:
        raise ValueError(f"Unknown stop policy: {policy}")
    direction = str(case["direction"])
    if direction not in {"LONG", "SHORT"}:
        raise ValueError(f"Invalid direction: {direction}")
    typed_direction: Direction = direction  # type: ignore[assignment]
    entry = float(case["control_entry_price"])
    target = float(case["target"])
    control = float(case["control_stop"])
    requested_stop = control
    source_timeframe = "V2"
    source_identity: str | None = None
    source_known_at: str | None = str(case["control_entry_at"])
    source_level: float | None = control
    atr: float | None = None
    buffer: float | None = None
    fallback_reason: str | None = None

    if policy != CONTROL_STOP:
        if policy == H1_STOP:
            source_timeframe = "H1"
            source_identity = str(case["source_h1_swing_identity"])
            source_known_at = str(case["source_h1_detected_at"])
            source_level = float(case["source_h1_level"])
            atr = _latest_atr(registry, "1h", case["control_entry_at"])
        else:
            timeframe = "5m" if policy == M5_STOP else "15m"
            source_timeframe = "M5" if timeframe == "5m" else "M15"
            swing = _latest_opposing_swing(
                registry, timeframe, case["control_entry_at"], typed_direction
            )
            atr = _latest_atr(registry, timeframe, case["control_entry_at"])
            if swing is None:
                fallback_reason = "NO_CONFIRMED_OPPOSING_SWING_AVAILABLE"
                source_level = None
                source_known_at = None
            else:
                source_identity = str(swing["identity"])
                source_known_at = iso(swing["detected_at"])
                source_level = float(swing["level"])
        if fallback_reason is None and atr is None:
            fallback_reason = "ATR14_UNAVAILABLE"
        if fallback_reason is None:
            buffer = stop_buffer(float(atr))
            requested_stop = outward_stop(typed_direction, float(source_level), buffer)
            if not valid_geometry(entry, requested_stop, target, typed_direction):
                fallback_reason = "INVALID_STOP_ENTRY_TARGET_ORDER"
            elif abs(entry - requested_stop) >= abs(entry - control):
                fallback_reason = "NOT_STRICTLY_CLOSER_THAN_CONTROL"

    replaced = policy != CONTROL_STOP and fallback_reason is None
    effective_stop = requested_stop if replaced else control
    payload = {
        "requested_policy": policy,
        "effective_policy": policy if replaced or policy == CONTROL_STOP else CONTROL_STOP,
        "replaced_control": replaced,
        "fallback_reason": fallback_reason,
        "source_timeframe": source_timeframe,
        "source_identity": source_identity,
        "source_known_at": source_known_at,
        "source_level": source_level,
        "atr14": atr,
        "buffer": buffer,
        "requested_stop": requested_stop,
        "stop": effective_stop,
        "control_stop": control,
        "stop_distance": abs(entry - effective_stop),
        "control_distance": abs(entry - control),
        "distance_ratio_to_control": abs(entry - effective_stop) / abs(entry - control),
        "classification": "CALCULATED_STRUCTURAL_INVALIDATION",
    }
    payload["geometry_sha256"] = canonical_hash(payload)
    return payload


class M1Path:
    def __init__(self, rows: Sequence[Mapping[str, Any]]) -> None:
        self.rows = sorted(
            [dict(row) for row in rows if row.get("complete") is True],
            key=lambda row: (parse_dt(str(row["open_at"])), parse_dt(str(row["available_at"]))),
        )
        self.times = [parse_dt(str(row["open_at"])) for row in self.rows]

    def range(self, start: Any, end: Any) -> list[dict[str, Any]]:
        left = bisect_left(self.times, parse_dt(start))
        endpoint = parse_dt(end)
        right = bisect_left(self.times, endpoint)
        return [
            row
            for row in self.rows[left:right]
            if parse_dt(str(row["available_at"])) <= endpoint
        ]


def _touches(row: Mapping[str, Any], level: float) -> bool:
    return float(row["low"]) <= level <= float(row["high"])


def _stop_hit(row: Mapping[str, Any], stop: float, direction: Direction) -> bool:
    return float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop


def _target_hit(row: Mapping[str, Any], target: float, direction: Direction) -> bool:
    return float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target


def resolve_leg(
    path: M1Path,
    *,
    entry_at: Any,
    entry_price: float,
    stop: float,
    target: float,
    direction: Direction,
    deadline: Any,
) -> dict[str, Any]:
    if not valid_geometry(entry_price, stop, target, direction):
        raise ValueError("Invalid executable geometry")
    rows = path.range(entry_at, deadline)
    if not rows:
        raise RuntimeError("No complete M1 path after entry")
    risk = abs(entry_price - stop)
    max_adverse = 0.0
    max_favourable = 0.0
    for row in rows:
        adverse = (
            entry_price - float(row["low"])
            if direction == "LONG"
            else float(row["high"]) - entry_price
        )
        favourable = (
            float(row["high"]) - entry_price
            if direction == "LONG"
            else entry_price - float(row["low"])
        )
        max_adverse = max(max_adverse, adverse)
        max_favourable = max(max_favourable, favourable)
        stop_hit = _stop_hit(row, stop, direction)
        target_hit = _target_hit(row, target, direction)
        if stop_hit:
            outcome = "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP"
            result = {
                "outcome": outcome,
                "resolution_at": iso(row["open_at"]),
                "net_r": -1.0,
                "mfe_r": max_favourable / risk,
                "mae_r": max_adverse / risk,
            }
            result["lifecycle_sha256"] = canonical_hash(result)
            return result
        if target_hit:
            result = {
                "outcome": "TARGET",
                "resolution_at": iso(row["open_at"]),
                "net_r": abs(target - entry_price) / risk,
                "mfe_r": max_favourable / risk,
                "mae_r": max_adverse / risk,
            }
            result["lifecycle_sha256"] = canonical_hash(result)
            return result
    final = rows[-1]
    signed = (
        float(final["close"]) - entry_price
        if direction == "LONG"
        else entry_price - float(final["close"])
    )
    result = {
        "outcome": "TIME_EXIT",
        "resolution_at": iso(final["available_at"]),
        "net_r": signed / risk,
        "mfe_r": max_favourable / risk,
        "mae_r": max_adverse / risk,
    }
    result["lifecycle_sha256"] = canonical_hash(result)
    return result


def find_retest_fill(
    path: M1Path,
    *,
    order_at: Any,
    limit: float,
    stop: float,
    target: float,
    direction: Direction,
    deadline: Any,
) -> dict[str, Any]:
    expiry = min(parse_dt(deadline), parse_dt(order_at) + timedelta(minutes=RETEST_EXPIRY_MINUTES))
    for row in path.range(order_at, expiry):
        limit_hit = _touches(row, limit)
        stop_hit = _stop_hit(row, stop, direction)
        target_hit = _target_hit(row, target, direction)
        if limit_hit and stop_hit:
            return {
                "filled": True,
                "fill_at": iso(row["open_at"]),
                "fill_price": limit,
                "disposition": "FILL_THEN_STOP_SAME_BAR",
                "expiry_at": iso(expiry),
            }
        if target_hit:
            return {
                "filled": False,
                "fill_at": None,
                "fill_price": None,
                "disposition": (
                    "AMBIGUOUS_TARGET_AND_LIMIT_SAME_BAR_CANCEL"
                    if limit_hit
                    else "TARGET_BEFORE_RETEST"
                ),
                "expiry_at": iso(expiry),
            }
        if stop_hit:
            return {
                "filled": False,
                "fill_at": None,
                "fill_price": None,
                "disposition": "STOP_BEFORE_RETEST",
                "expiry_at": iso(expiry),
            }
        if limit_hit:
            return {
                "filled": True,
                "fill_at": iso(row["open_at"]),
                "fill_price": limit,
                "disposition": "FIRST_RETEST_FILLED",
                "expiry_at": iso(expiry),
            }
    return {
        "filled": False,
        "fill_at": None,
        "fill_price": None,
        "disposition": "RETEST_EXPIRED",
        "expiry_at": iso(expiry),
    }


def evaluate_policy(
    case: Mapping[str, Any],
    geometry: Mapping[str, Any],
    path: M1Path,
    entry_policy: str,
) -> dict[str, Any]:
    if entry_policy not in ENTRY_POLICIES:
        raise ValueError(f"Unknown entry policy: {entry_policy}")
    direction: Direction = str(case["direction"])  # type: ignore[assignment]
    stop = float(geometry["stop"])
    target = float(case["target"])
    control_entry = float(case["control_entry_price"])
    control_at = str(case["control_entry_at"])
    deadline = str(case["deadline"])
    limit = float(case["broken_m5_control_level"])

    control_leg = resolve_leg(
        path,
        entry_at=control_at,
        entry_price=control_entry,
        stop=stop,
        target=target,
        direction=direction,
        deadline=deadline,
    )
    retest_geometry_valid = (
        valid_geometry(limit, stop, target, direction)
        and (limit < control_entry if direction == "LONG" else limit > control_entry)
    )
    retest = (
        find_retest_fill(
            path,
            order_at=control_at,
            limit=limit,
            stop=stop,
            target=target,
            direction=direction,
            deadline=deadline,
        )
        if retest_geometry_valid
        else {
            "filled": False,
            "fill_at": None,
            "fill_price": None,
            "disposition": "INVALID_OR_NONIMPROVING_RETEST_GEOMETRY",
            "expiry_at": iso(
                min(parse_dt(deadline), parse_dt(control_at) + timedelta(minutes=RETEST_EXPIRY_MINUTES))
            ),
        }
    )
    retest_leg = None
    if retest["filled"]:
        retest_leg = resolve_leg(
            path,
            entry_at=str(retest["fill_at"]),
            entry_price=float(retest["fill_price"]),
            stop=stop,
            target=target,
            direction=direction,
            deadline=deadline,
        )

    if entry_policy == CONTROL_ENTRY:
        net_r = float(control_leg["net_r"])
        filled = True
        outcome = str(control_leg["outcome"])
        entry_at = control_at
        entry_price = control_entry
        mfe_r = float(control_leg["mfe_r"])
        mae_r = float(control_leg["mae_r"])
        retest_used = False
        resolution_at = str(control_leg["resolution_at"])
    elif entry_policy == RETEST_ENTRY:
        filled = bool(retest["filled"])
        if filled:
            net_r = float(retest_leg["net_r"])
            outcome = str(retest_leg["outcome"])
            entry_at = str(retest["fill_at"])
            entry_price = float(retest["fill_price"])
            mfe_r = float(retest_leg["mfe_r"])
            mae_r = float(retest_leg["mae_r"])
            resolution_at = str(retest_leg["resolution_at"])
        else:
            net_r = 0.0
            outcome = "NO_FILL"
            entry_at = None
            entry_price = None
            mfe_r = None
            mae_r = None
            resolution_at = None
        retest_used = filled
    else:
        filled = True
        entry_at = control_at
        entry_price = control_entry
        retest_used = bool(retest["filled"])
        net_r = SPLIT_CONTROL_FRACTION * float(control_leg["net_r"])
        outcome = f"SPLIT_CONTROL_{control_leg['outcome']}_NO_RETEST"
        mfe_r = SPLIT_CONTROL_FRACTION * float(control_leg["mfe_r"])
        mae_r = SPLIT_CONTROL_FRACTION * float(control_leg["mae_r"])
        if retest_used:
            net_r += SPLIT_RETEST_FRACTION * float(retest_leg["net_r"])
            mfe_r += SPLIT_RETEST_FRACTION * float(retest_leg["mfe_r"])
            mae_r += SPLIT_RETEST_FRACTION * float(retest_leg["mae_r"])
            outcome = f"SPLIT_{control_leg['outcome']}_{retest_leg['outcome']}"
            resolution_at = max(
                str(control_leg["resolution_at"]), str(retest_leg["resolution_at"])
            )
        else:
            resolution_at = str(control_leg["resolution_at"])

    payload = {
        "entry_policy": entry_policy,
        "stop_policy": str(geometry["requested_policy"]),
        "effective_stop_policy": str(geometry["effective_policy"]),
        "filled": filled,
        "entry_at": entry_at,
        "entry_price": entry_price,
        "stop": stop,
        "target": target,
        "outcome": outcome,
        "resolution_at": resolution_at,
        "net_r": net_r,
        "mfe_r": mfe_r,
        "mae_r": mae_r,
        "retest_level": limit,
        "retest_opportunity": bool(retest["filled"]),
        "retest_used": retest_used,
        "retest_fill_at": retest["fill_at"],
        "retest_disposition": str(retest["disposition"]),
        "retest_expiry_at": str(retest["expiry_at"]),
        "control_leg": control_leg,
        "retest_leg": retest_leg,
        "geometry_sha256": str(geometry["geometry_sha256"]),
    }
    payload["policy_result_sha256"] = canonical_hash(payload)
    return payload


def maximum_drawdown(values: Sequence[float]) -> float:
    equity = 0.0
    peak = 0.0
    worst = 0.0
    for value in values:
        equity += float(value)
        peak = max(peak, equity)
        worst = max(worst, peak - equity)
    return worst


def summarize(
    rows: Sequence[Mapping[str, Any]], original_by_id: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    ordered = sorted(rows, key=lambda row: (parse_dt(str(row["control_entry_at"])), str(row["trade_identity"])))
    returns = [float(row["net_r"]) for row in ordered]
    filled = [row for row in ordered if bool(row["filled"])]
    positive = sum(value for value in returns if value > 0)
    negative = -sum(value for value in returns if value < 0)
    wins = sum(value > 0 for value in returns)
    original_winners = [
        row for row in ordered if float(original_by_id[str(row["trade_identity"])]["net_r"]) > 0
    ]
    distance_ratios = [float(row["distance_ratio_to_control"]) for row in ordered]
    outcomes = Counter(str(row["outcome"]) for row in ordered)
    return {
        "population": len(ordered),
        "filled_cases": len(filled),
        "no_fill_cases": len(ordered) - len(filled),
        "retest_filled_cases": sum(bool(row["retest_used"]) for row in ordered),
        "retest_opportunity_cases": sum(bool(row["retest_opportunity"]) for row in ordered),
        "winning_cases": wins,
        "losing_cases": sum(value < 0 for value in returns),
        "flat_cases": sum(value == 0 for value in returns),
        "target_disposition_cases": sum("TARGET" in str(row["outcome"]) for row in ordered),
        "stop_disposition_cases": sum("STOP" in str(row["outcome"]) for row in ordered),
        "time_exit_disposition_cases": sum("TIME_EXIT" in str(row["outcome"]) for row in ordered),
        "outcome_counts": dict(sorted(outcomes.items())),
        "win_rate_filled": wins / len(filled) if filled else None,
        "gross_positive_r": positive,
        "gross_negative_r": -negative,
        "net_r": sum(returns),
        "expectancy_per_population_case_r": sum(returns) / len(ordered) if ordered else None,
        "expectancy_per_filled_case_r": sum(returns) / len(filled) if filled else None,
        "profit_factor": positive / negative if negative else None,
        "maximum_drawdown_r": maximum_drawdown(returns),
        "dollars_at_50_max_case_risk": 50.0 * sum(returns),
        "stop_replacements": sum(bool(row["stop_replaced_control"]) for row in ordered),
        "stop_fallbacks": sum(bool(row["stop_fallback_reason"]) for row in ordered),
        "median_stop_distance_ratio_to_control": median(distance_ratios) if distance_ratios else None,
        "original_positive_cases": len(original_winners),
        "original_positive_retained": sum(float(row["net_r"]) > 0 for row in original_winners),
        "original_positive_converted_to_loss": sum(float(row["net_r"]) < 0 for row in original_winners),
        "original_positive_unfilled": sum(not bool(row["filled"]) for row in original_winners),
    }


def synthetic_proof() -> dict[str, Any]:
    base = parse_dt("2022-01-03T10:00:00Z")
    m1 = [
        {
            "open_at": iso(base + timedelta(minutes=index)),
            "available_at": iso(base + timedelta(minutes=index + 1)),
            "open": values[0],
            "high": values[1],
            "low": values[2],
            "close": values[3],
            "complete": True,
        }
        for index, values in enumerate(
            (
                (101.0, 101.2, 100.8, 101.1),
                (101.1, 101.3, 100.4, 100.7),
                (100.7, 103.2, 100.6, 103.0),
            )
        )
    ]
    path = M1Path(m1)
    ambiguous_path = M1Path(
        [
            {
                "open_at": iso(base),
                "available_at": iso(base + timedelta(minutes=1)),
                "open": 101.0,
                "high": 103.2,
                "low": 100.4,
                "close": 101.1,
                "complete": True,
            }
        ]
    )
    stop_first = resolve_leg(
        ambiguous_path,
        entry_at=iso(base),
        entry_price=101.0,
        stop=100.5,
        target=103.0,
        direction="LONG",
        deadline=iso(base + timedelta(minutes=3)),
    )
    retest = find_retest_fill(
        path,
        order_at=iso(base),
        limit=100.5,
        stop=99.0,
        target=103.0,
        direction="LONG",
        deadline=iso(base + timedelta(minutes=30)),
    )
    synthetic_registry = {
        "5m": {
            "swings": [
                {
                    "identity": "KNOWN_LOW",
                    "kind": "LOW",
                    "pivot_at": iso(base - timedelta(minutes=15)),
                    "detected_at": iso(base - timedelta(minutes=5)),
                    "level": 99.0,
                },
                {
                    "identity": "FUTURE_LOW",
                    "kind": "LOW",
                    "pivot_at": iso(base),
                    "detected_at": iso(base + timedelta(minutes=5)),
                    "level": 100.0,
                },
            ],
            "atr_timeline": [
                (base - timedelta(minutes=5), 1.0),
                (base + timedelta(minutes=5), 2.0),
            ],
        },
        "15m": {"swings": [], "atr_timeline": [(base - timedelta(minutes=15), 1.0)]},
        "1h": {"swings": [], "atr_timeline": [(base - timedelta(hours=1), 1.0)]},
    }
    synthetic_case = {
        "direction": "LONG",
        "control_entry_at": iso(base),
        "control_entry_price": 101.0,
        "control_stop": 98.0,
        "target": 103.0,
        "source_h1_swing_identity": "H1_LOW",
        "source_h1_detected_at": iso(base - timedelta(hours=1)),
        "source_h1_level": 98.0,
    }
    known_stop = stop_geometry(synthetic_case, synthetic_registry, M5_STOP)
    invalid_registry = {
        **synthetic_registry,
        "5m": {
            "swings": [
                {
                    "identity": "INVALID_LOW",
                    "kind": "LOW",
                    "pivot_at": iso(base - timedelta(minutes=15)),
                    "detected_at": iso(base - timedelta(minutes=5)),
                    "level": 102.0,
                }
            ],
            "atr_timeline": [(base - timedelta(minutes=5), 1.0)],
        },
    }
    invalid_stop = stop_geometry(synthetic_case, invalid_registry, M5_STOP)
    checks = {
        "stop_first_on_ambiguous_path": stop_first["outcome"] == "STOP_FIRST_AMBIGUOUS",
        "first_retest_filled": retest["filled"] is True
        and retest["fill_at"] == iso(base + timedelta(minutes=1)),
        "expiry_is_fifteen_minutes": retest["expiry_at"] == iso(base + timedelta(minutes=15)),
        "future_swing_is_not_visible": known_stop["source_identity"] == "KNOWN_LOW",
        "known_structural_stop_is_closer": known_stop["replaced_control"] is True
        and known_stop["stop"] == 98.95,
        "invalid_structural_stop_falls_back": invalid_stop["replaced_control"] is False
        and invalid_stop["stop"] == synthetic_case["control_stop"],
        "split_fractions_sum_to_one": SPLIT_CONTROL_FRACTION + SPLIT_RETEST_FRACTION == 1.0,
        "long_short_geometry_symmetric": valid_geometry(101, 100, 103, "LONG")
        and valid_geometry(99, 100, 97, "SHORT"),
        "outward_buffer_symmetric": outward_stop("LONG", 100, 0.1) == 99.9
        and outward_stop("SHORT", 100, 0.1) == 100.1,
    }
    payload = {
        "version": f"{RULESET}_SYNTHETIC_PROOF",
        "checks": checks,
        "verdict": "PASS" if all(checks.values()) else "FAIL",
    }
    payload["proof_sha256"] = canonical_hash(payload)
    return payload
