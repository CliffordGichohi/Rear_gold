from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, is_dataclass
from datetime import UTC, date, datetime, time, timedelta
from decimal import Decimal
from typing import Any, Literal
from uuid import UUID
from zoneinfo import ZoneInfo

CASEBOOK_VERSION = "GOLD_CASEBOOK_V0_1"
CASEBOOK_SCHEMA_VERSION = "gold-casebook-schema-0.1.0"
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

SessionCode = Literal["LONDON", "NEW_YORK"]
LevelSide = Literal["UPPER", "LOWER"]


@dataclass(frozen=True, slots=True)
class CaseBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float | None
    spread: float | None
    source_count: int
    source_hash: str


@dataclass(frozen=True, slots=True)
class Window:
    code: str
    start: datetime
    end: datetime
    bars: tuple[CaseBar, ...]


@dataclass(frozen=True, slots=True)
class SessionCaseSpec:
    case_id: str
    session_date: date
    session_code: SessionCode
    timezone: str
    decision_at: datetime
    observation_end: datetime
    asia: Window
    london: Window
    new_york: Window | None


@dataclass(frozen=True, slots=True)
class KnownLevel:
    code: str
    price: float
    side: LevelSide
    known_at: datetime
    source_hash: str


def validate_casebook_period(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError("start must precede end")
    if end > HOLDOUT_START:
        raise ValueError("The locked 2025 holdout must not be loaded")


def build_session_case_specs(
    bars: Sequence[CaseBar],
    *,
    start: datetime,
    end: datetime,
) -> list[SessionCaseSpec]:
    validate_casebook_period(start, end)
    bars_by_open = {bar.open_time.astimezone(UTC): bar for bar in bars}
    first_date = start.astimezone(LONDON).date()
    last_date = end.astimezone(LONDON).date()
    output: list[SessionCaseSpec] = []
    current = first_date
    while current <= last_date:
        london_start = _local(current, time(8), LONDON).astimezone(UTC)
        if current.weekday() < 5 and start <= london_start < end:
            asia = _window(
                bars_by_open,
                code="ASIA",
                start=_local(current, time(10, 5), TOKYO).astimezone(UTC),
                end=_local(current, time(16), TOKYO).astimezone(UTC),
            )
            london = _window(
                bars_by_open,
                code="LONDON",
                start=london_start,
                end=_local(current, time(12), LONDON).astimezone(UTC),
            )
            new_york = _window(
                bars_by_open,
                code="NEW_YORK",
                start=_local(current, time(8), NEW_YORK).astimezone(UTC),
                end=_local(current, time(12), NEW_YORK).astimezone(UTC),
            )
            if _complete(asia) and _complete(london):
                output.append(
                    SessionCaseSpec(
                        case_id=_case_id(current, "LONDON", london.start),
                        session_date=current,
                        session_code="LONDON",
                        timezone=LONDON.key,
                        decision_at=london.start,
                        observation_end=london.end,
                        asia=asia,
                        london=london,
                        new_york=None,
                    )
                )
            if _complete(asia) and _complete(london) and _complete(new_york):
                output.append(
                    SessionCaseSpec(
                        case_id=_case_id(current, "NEW_YORK", new_york.start),
                        session_date=current,
                        session_code="NEW_YORK",
                        timezone=NEW_YORK.key,
                        decision_at=new_york.start,
                        observation_end=new_york.end,
                        asia=asia,
                        london=london,
                        new_york=new_york,
                    )
                )
        current += timedelta(days=1)
    return output


def summarize_window(
    window: Window,
    *,
    as_of: datetime,
) -> dict[str, Any]:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(UTC)
    eligible = [
        bar
        for bar in window.bars
        if bar.close_time.astimezone(UTC) <= cutoff
    ]
    expected = int(
        (min(window.end, cutoff) - window.start).total_seconds() // 300
    )
    expected = max(expected, 0)
    complete = cutoff >= window.end and len(eligible) == len(window.bars)
    status = "COMPLETE" if complete else "PARTIAL" if eligible else "NOT_STARTED"
    if not eligible:
        return {
            "code": window.code,
            "status": status,
            "start": window.start,
            "end": window.end,
            "as_of": cutoff,
            "bar_count": 0,
            "expected_bar_count_as_of": expected,
            "open": None,
            "high": None,
            "low": None,
            "close": None,
            "range": None,
            "tick_volume": None,
            "average_spread": None,
            "maximum_spread": None,
            "source_hash": None,
            "epistemic_status": "UNKNOWN",
        }
    spreads = [bar.spread for bar in eligible if bar.spread is not None]
    return {
        "code": window.code,
        "status": status,
        "start": window.start,
        "end": window.end,
        "as_of": cutoff,
        "bar_count": len(eligible),
        "expected_bar_count_as_of": expected,
        "open": eligible[0].open,
        "high": max(bar.high for bar in eligible),
        "low": min(bar.low for bar in eligible),
        "close": eligible[-1].close,
        "range": max(bar.high for bar in eligible) - min(bar.low for bar in eligible),
        "tick_volume": (
            sum(bar.volume or 0 for bar in eligible)
            if all(bar.volume is not None for bar in eligible)
            else None
        ),
        "average_spread": (
            round(sum(spreads) / len(spreads), 8) if spreads else None
        ),
        "maximum_spread": max(spreads) if spreads else None,
        "source_hash": canonical_hash(
            [
                {
                    "open_time": bar.open_time,
                    "close_time": bar.close_time,
                    "source_hash": bar.source_hash,
                    "source_count": bar.source_count,
                }
                for bar in eligible
            ]
        ),
        "epistemic_status": "OBSERVED",
    }


def window_at_or_before(
    window: Window,
    *,
    cutoff: datetime,
) -> tuple[CaseBar, ...]:
    return tuple(
        bar
        for bar in window.bars
        if bar.close_time.astimezone(UTC) <= cutoff.astimezone(UTC)
    )


def level_interactions(
    bars: Sequence[CaseBar],
    levels: Sequence[KnownLevel],
    *,
    decision_at: datetime,
    observation_end: datetime,
    acceptance_bars: int = 2,
) -> list[dict[str, Any]]:
    if acceptance_bars < 1:
        raise ValueError("acceptance_bars must be positive")
    eligible = [
        bar
        for bar in bars
        if bar.open_time >= decision_at
        and bar.close_time <= observation_end
    ]
    output: list[dict[str, Any]] = []
    for level in levels:
        if level.known_at > decision_at:
            raise ValueError(f"Level {level.code} was not known at the decision")
        first_breach: datetime | None = None
        first_close_beyond: datetime | None = None
        accepted_at: datetime | None = None
        returned_inside_at: datetime | None = None
        consecutive = 0
        accepted = False
        for bar in eligible:
            breached = (
                bar.high > level.price
                if level.side == "UPPER"
                else bar.low < level.price
            )
            close_beyond = (
                bar.close > level.price
                if level.side == "UPPER"
                else bar.close < level.price
            )
            if breached and first_breach is None:
                first_breach = bar.close_time
            if close_beyond:
                if first_close_beyond is None:
                    first_close_beyond = bar.close_time
                consecutive += 1
                if consecutive >= acceptance_bars and accepted_at is None:
                    accepted_at = bar.close_time
                    accepted = True
            else:
                if accepted and returned_inside_at is None:
                    returned_inside_at = bar.close_time
                consecutive = 0
        close_relation = None
        if eligible:
            close_relation = (
                "ABOVE"
                if eligible[-1].close > level.price
                else "BELOW"
                if eligible[-1].close < level.price
                else "AT_LEVEL"
            )
        classification = (
            "FAILED_ACCEPTED_BREAK"
            if accepted_at is not None and returned_inside_at is not None
            else "ACCEPTED_BREAK"
            if accepted_at is not None
            else "REJECTED_BREACH"
            if first_breach is not None
            else "UNTOUCHED"
        )
        output.append(
            {
                "level_code": level.code,
                "level_price": level.price,
                "level_side": level.side,
                "level_known_at": level.known_at,
                "level_source_hash": level.source_hash,
                "first_breach_at": first_breach,
                "first_close_beyond_at": first_close_beyond,
                "accepted_at": accepted_at,
                "returned_inside_at": returned_inside_at,
                "session_close_relation": close_relation,
                "classification": classification,
                "detection_method": (
                    f"FIVE_MINUTE_BREACH_AND_{acceptance_bars}_CLOSE_ACCEPTANCE"
                ),
                "epistemic_status": "CALCULATED",
            }
        )
    return output


def cot_state_at(
    points: Sequence[Any],
    *,
    as_of: datetime,
) -> dict[str, Any]:
    eligible = sorted(
        [point for point in points if point.publication_at <= as_of],
        key=lambda point: (point.publication_at, point.observation_date),
    )
    if not eligible:
        return {
            "status": "UNKNOWN",
            "epistemic_status": "UNKNOWN",
            "explanation": "No published COT report was eligible.",
        }
    current = eligible[-1]
    previous = eligible[-2] if len(eligible) >= 2 else None
    historical = sorted(point.managed_money_net for point in eligible)
    below_or_equal = sum(value <= current.managed_money_net for value in historical)
    percentile = 100 * below_or_equal / len(historical)
    crowding = (
        "CROWDED_LONGS"
        if percentile >= 90
        else "CROWDED_SHORTS"
        if percentile <= 10
        else "BALANCED"
    )
    return {
        "status": "READY",
        "observation_date": current.observation_date,
        "publication_at": current.publication_at,
        "availability_quality": current.availability_quality,
        "managed_money_long": current.managed_money_long,
        "managed_money_short": current.managed_money_short,
        "managed_money_net": current.managed_money_net,
        "managed_money_net_change": (
            current.managed_money_net - previous.managed_money_net
            if previous is not None
            else None
        ),
        "producer_long": current.producer_long,
        "producer_short": current.producer_short,
        "producer_net": current.producer_long - current.producer_short,
        "open_interest": current.open_interest,
        "managed_money_net_percentile": round(percentile, 4),
        "history_count": len(historical),
        "crowding_state": crowding,
        "source_record_key": current.source_record_key,
        "epistemic_status": "CALCULATED",
        "classification_warning": (
            "Positions are observed by CFTC category; crowding and motive are "
            "calculated or inferred, not directly observed institutional intent."
        ),
    }


def compact_structure_evidence(value: Any) -> Any:
    if isinstance(value, Mapping):
        output: dict[str, Any] = {}
        for key, item in value.items():
            if key == "source_bar_ids" and isinstance(item, Sequence):
                identifiers = [str(identifier) for identifier in item]
                output["source_bar_count"] = len(identifiers)
                output["source_bar_ids_hash"] = canonical_hash(identifiers)
                output["source_bar_first"] = identifiers[0] if identifiers else None
                output["source_bar_last"] = identifiers[-1] if identifiers else None
            else:
                output[str(key)] = compact_structure_evidence(item)
        return output
    if isinstance(value, list | tuple):
        return [compact_structure_evidence(item) for item in value]
    return value


def finalize_record(record: Mapping[str, Any]) -> dict[str, Any]:
    if "record_hash" in record:
        raise ValueError("record_hash must not be supplied by the caller")
    output = dict(record)
    output["record_hash"] = canonical_hash(output)
    return output


def canonical_hash(value: Any) -> str:
    encoded = json.dumps(
        json_ready(value),
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return hashlib.sha256(encoded).hexdigest()


def json_ready(value: Any) -> Any:
    if is_dataclass(value) and not isinstance(value, type):
        return json_ready(asdict(value))
    if isinstance(value, Mapping):
        return {str(key): json_ready(item) for key, item in value.items()}
    if isinstance(value, list | tuple | set):
        return [json_ready(item) for item in value]
    if isinstance(value, datetime):
        if value.tzinfo is None:
            raise ValueError("Naive datetime cannot enter the casebook")
        return value.astimezone(UTC).isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, Decimal):
        return float(value)
    if isinstance(value, UUID):
        return str(value)
    return value


def _window(
    bars_by_open: Mapping[datetime, CaseBar],
    *,
    code: str,
    start: datetime,
    end: datetime,
) -> Window:
    expected = int((end - start).total_seconds() // 300)
    bars = tuple(
        bars_by_open[open_time]
        for offset in range(expected)
        if (open_time := start + timedelta(minutes=offset * 5)) in bars_by_open
    )
    return Window(code=code, start=start, end=end, bars=bars)


def _complete(window: Window) -> bool:
    expected = int((window.end - window.start).total_seconds() // 300)
    return (
        len(window.bars) == expected
        and bool(window.bars)
        and window.bars[0].open_time == window.start
        and window.bars[-1].close_time == window.end
        and all(
            current.open_time == previous.close_time
            for previous, current in zip(window.bars, window.bars[1:], strict=False)
        )
    )


def _case_id(
    session_date: date,
    session_code: SessionCode,
    decision_at: datetime,
) -> str:
    digest = canonical_hash(
        {
            "version": CASEBOOK_VERSION,
            "session_date": session_date,
            "session_code": session_code,
            "decision_at": decision_at,
        }
    )
    return f"CASE-{session_code}-{session_date.isoformat()}-{digest[:16]}"


def _local(value_date: date, value_time: time, timezone: ZoneInfo) -> datetime:
    return datetime.combine(value_date, value_time, tzinfo=timezone)
