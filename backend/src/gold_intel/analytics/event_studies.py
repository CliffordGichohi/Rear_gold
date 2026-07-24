from __future__ import annotations

import hashlib
import json
import statistics
from collections import defaultdict
from dataclasses import asdict, dataclass
from datetime import datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from gold_intel.analytics.events import SurpriseCalculation

NEW_YORK = ZoneInfo("America/New_York")
EVENT_REACTION_VERSION = "event-reaction-1"
FIXED_HORIZONS: dict[str, timedelta] = {
    "1M": timedelta(minutes=1),
    "5M": timedelta(minutes=5),
    "15M": timedelta(minutes=15),
    "1H": timedelta(hours=1),
    "4H": timedelta(hours=4),
}


@dataclass(frozen=True, slots=True)
class ReactionBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    available_at: datetime
    source_record_key: str
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class ReactionResult:
    event_id: Any
    release_id: Any
    surprise_id: Any | None
    component_code: str
    horizon_code: str
    reference_time: datetime
    reference_price: float
    horizon_time: datetime
    horizon_price: float
    price_change: float
    return_pct: float
    mfe_price: float
    mae_price: float
    first_move_direction: str
    first_move_held: bool | None
    available_at: datetime
    expected_gold_direction: float
    data_hash: str
    evidence: dict[str, Any]
    is_synthetic: bool


@dataclass(frozen=True, slots=True)
class ReactionBatch:
    reactions: tuple[ReactionResult, ...]
    exclusion: str | None


def calculate_event_reactions(
    surprise: SurpriseCalculation,
    bars: list[ReactionBar],
    *,
    study_as_of: datetime,
    surprise_id: Any | None = None,
) -> ReactionBatch:
    if study_as_of.tzinfo is None:
        raise ValueError("study_as_of must include a timezone")
    canonical: dict[datetime, ReactionBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_time, item.available_at)):
        if bar.close_time <= study_as_of and bar.available_at <= study_as_of:
            canonical.setdefault(bar.open_time, bar)
    ordered = sorted(canonical.values(), key=lambda item: item.open_time)
    references = [bar for bar in ordered if bar.close_time <= surprise.released_at]
    if not references:
        return ReactionBatch((), "NO_REFERENCE_PRICE")
    reference = references[-1]
    if surprise.released_at - reference.close_time > timedelta(minutes=5):
        return ReactionBatch((), "REFERENCE_PRICE_TOO_STALE")

    endpoints: list[tuple[str, datetime]] = [
        (code, surprise.released_at + delta) for code, delta in FIXED_HORIZONS.items()
    ]
    endpoints.append(("DAILY_CLOSE", _daily_close_target(surprise.released_at)))
    raw_rows: list[dict[str, Any]] = []
    for horizon_code, target in endpoints:
        if target > study_as_of:
            continue
        endpoint = _endpoint_bar(ordered, target, horizon_code)
        if endpoint is None:
            continue
        path = [
            bar for bar in ordered if reference.close_time < bar.close_time <= endpoint.close_time
        ]
        if not path:
            continue
        change = endpoint.close - reference.close
        return_pct = change / reference.close * 100 if reference.close else 0.0
        direction = surprise.gold_direction
        if direction == 0:
            direction = 1 if change >= 0 else -1
        if direction > 0:
            mfe = max(max(bar.high for bar in path) - reference.close, 0.0)
            mae = max(reference.close - min(bar.low for bar in path), 0.0)
        else:
            mfe = max(reference.close - min(bar.low for bar in path), 0.0)
            mae = max(max(bar.high for bar in path) - reference.close, 0.0)
        raw_rows.append(
            {
                "horizon_code": horizon_code,
                "endpoint": endpoint,
                "path": path,
                "change": change,
                "return_pct": return_pct,
                "mfe": mfe,
                "mae": mae,
            }
        )
    if not raw_rows:
        return ReactionBatch((), "NO_COMPLETE_REACTION_HORIZON")

    one_minute = next(
        (row for row in raw_rows if row["horizon_code"] == "1M"),
        raw_rows[0],
    )
    first_change = float(one_minute["change"])
    first_direction = "UP" if first_change > 0 else "DOWN" if first_change < 0 else "FLAT"
    output: list[ReactionResult] = []
    for row in raw_rows:
        endpoint = row["endpoint"]
        change = float(row["change"])
        held = None
        if row["horizon_code"] != "1M" and first_direction != "FLAT":
            held = (change > 0) == (first_direction == "UP")
        evidence = {
            "release_time": surprise.released_at.isoformat(),
            "reference_source_record_key": reference.source_record_key,
            "endpoint_source_record_key": endpoint.source_record_key,
            "path_bar_count": len(row["path"]),
            "expected_gold_direction": surprise.gold_direction,
            "surprise_data_hash": surprise.data_hash,
            "endpoint_target_policy": (
                "FIRST_COMPLETE_MINUTE_AT_OR_AFTER_TARGET"
                if row["horizon_code"] != "DAILY_CLOSE"
                else "LAST_COMPLETE_MINUTE_AT_OR_BEFORE_17_ET"
            ),
        }
        data_hash = _reaction_hash(
            surprise,
            reference,
            endpoint,
            row["path"],
            str(row["horizon_code"]),
        )
        output.append(
            ReactionResult(
                event_id=surprise.event_id,
                release_id=surprise.release_id,
                surprise_id=surprise_id,
                component_code=surprise.component_code,
                horizon_code=str(row["horizon_code"]),
                reference_time=reference.close_time,
                reference_price=round(reference.close, 6),
                horizon_time=endpoint.close_time,
                horizon_price=round(endpoint.close, 6),
                price_change=round(change, 6),
                return_pct=round(float(row["return_pct"]), 8),
                mfe_price=round(float(row["mfe"]), 6),
                mae_price=round(float(row["mae"]), 6),
                first_move_direction=first_direction,
                first_move_held=held,
                available_at=endpoint.available_at,
                expected_gold_direction=surprise.gold_direction,
                data_hash=data_hash,
                evidence=evidence,
                is_synthetic=surprise.is_synthetic or any(bar.is_synthetic for bar in row["path"]),
            )
        )
    return ReactionBatch(tuple(output), None)


def summarize_event_reactions(
    reactions: list[ReactionResult],
) -> dict[str, Any]:
    grouped: dict[tuple[str, str], list[ReactionResult]] = defaultdict(list)
    for reaction in reactions:
        grouped[(reaction.component_code, reaction.horizon_code)].append(reaction)
    rows: list[dict[str, Any]] = []
    for (component_code, horizon_code), members in sorted(grouped.items()):
        returns = [member.return_pct for member in members]
        aligned = [
            (member.return_pct > 0) == (member.expected_gold_direction > 0)
            for member in members
            if member.expected_gold_direction != 0 and member.return_pct != 0
        ]
        held = [member.first_move_held for member in members if member.first_move_held is not None]
        ci_low, ci_high = _mean_confidence_interval(returns)
        rows.append(
            {
                "component_code": component_code,
                "horizon_code": horizon_code,
                "observations": len(members),
                "average_return_pct": _rounded(statistics.mean(returns)),
                "median_return_pct": _rounded(statistics.median(returns)),
                "positive_return_pct": _percentage(
                    sum(value > 0 for value in returns),
                    len(returns),
                ),
                "expected_direction_alignment_pct": _percentage(
                    sum(aligned),
                    len(aligned),
                ),
                "first_move_hold_pct": _percentage(
                    sum(bool(value) for value in held),
                    len(held),
                ),
                "average_mfe_price": _rounded(
                    statistics.mean(member.mfe_price for member in members)
                ),
                "average_mae_price": _rounded(
                    statistics.mean(member.mae_price for member in members)
                ),
                "mean_return_95ci": [_rounded(ci_low), _rounded(ci_high)],
            }
        )
    return {"groups": rows}


def _endpoint_bar(
    bars: list[ReactionBar],
    target: datetime,
    horizon_code: str,
) -> ReactionBar | None:
    if horizon_code == "DAILY_CLOSE":
        candidates = [bar for bar in bars if bar.close_time <= target]
        if not candidates:
            return None
        endpoint = candidates[-1]
        return endpoint if target - endpoint.close_time <= timedelta(minutes=2) else None
    candidates = [bar for bar in bars if bar.close_time >= target]
    if not candidates:
        return None
    endpoint = candidates[0]
    return endpoint if endpoint.close_time - target <= timedelta(minutes=2) else None


def _daily_close_target(released_at: datetime) -> datetime:
    local = released_at.astimezone(NEW_YORK)
    target_date = local.date()
    if local.time() >= time(17, 0):
        target_date += timedelta(days=1)
    return datetime.combine(target_date, time(17, 0), tzinfo=NEW_YORK).astimezone(
        released_at.tzinfo
    )


def _reaction_hash(
    surprise: SurpriseCalculation,
    reference: ReactionBar,
    endpoint: ReactionBar,
    path: list[ReactionBar],
    horizon_code: str,
) -> str:
    payload = {
        "version": EVENT_REACTION_VERSION,
        "surprise_hash": surprise.data_hash,
        "horizon_code": horizon_code,
        "reference": asdict(reference),
        "endpoint": asdict(endpoint),
        "path_source_keys": [bar.source_record_key for bar in path],
    }
    canonical = json.dumps(payload, sort_keys=True, default=str, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


def _mean_confidence_interval(values: list[float]) -> tuple[float | None, float | None]:
    if len(values) < 2:
        return None, None
    margin = 1.96 * statistics.stdev(values) / len(values) ** 0.5
    mean = statistics.mean(values)
    return mean - margin, mean + margin


def _percentage(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 3) if denominator else None


def _rounded(value: float | None) -> float | None:
    return round(value, 6) if value is not None else None
