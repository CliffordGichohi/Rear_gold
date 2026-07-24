from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo


@dataclass(frozen=True, slots=True)
class SessionContext:
    primary: str
    active: tuple[str, ...]
    special_windows: tuple[str, ...]
    calculated_at: datetime
    evidence: dict[str, str]


@dataclass(frozen=True, slots=True)
class SessionRange:
    name: str
    timezone: str
    start_at: datetime
    end_at: datetime
    status: str
    bar_count: int
    expected_bar_count: int
    completeness_pct: float
    open: float | None
    high: float | None
    low: float | None
    close: float | None
    range_size: float | None
    breakout_state: str


@dataclass(frozen=True, slots=True)
class SessionPause:
    name: str
    timezone: ZoneInfo
    start: time
    end: time


@dataclass(frozen=True, slots=True)
class SessionPriceBar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    available_at: datetime


SESSION_ZONES = {
    "ASIA": ZoneInfo("Asia/Tokyo"),
    "LONDON": ZoneInfo("Europe/London"),
    "NEW_YORK": ZoneInfo("America/New_York"),
}
SESSION_HOURS = {
    "ASIA": (time(8, 0), time(17, 0)),
    "LONDON": (time(8, 0), time(17, 0)),
    "NEW_YORK": (time(8, 0), time(17, 0)),
}
SPECIAL_WINDOWS = (
    ("LBMA_AM_WINDOW", ZoneInfo("Europe/London"), time(10, 15), time(10, 45)),
    ("LBMA_PM_WINDOW", ZoneInfo("Europe/London"), time(14, 45), time(15, 15)),
    ("DAILY_ROLLOVER", ZoneInfo("America/New_York"), time(16, 55), time(17, 10)),
    (
        "NEW_YORK_CLOSE_SQUARING",
        ZoneInfo("America/New_York"),
        time(16, 0),
        time(17, 0),
    ),
)


def session_at(as_of: datetime) -> SessionContext:
    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")

    active: list[str] = []
    evidence: dict[str, str] = {}
    for name, zone in SESSION_ZONES.items():
        local = as_of.astimezone(zone)
        evidence[f"{name.lower()}_local"] = local.isoformat()
        start, end = SESSION_HOURS[name]
        if start <= local.timetz().replace(tzinfo=None) < end:
            active.append(name)

    if "LONDON" in active and "NEW_YORK" in active:
        primary = "LONDON_NEW_YORK_OVERLAP"
    elif active:
        primary = active[-1]
    else:
        primary = "OUT_OF_PRIMARY_SESSIONS"

    special = tuple(
        name
        for name, zone, start, end in SPECIAL_WINDOWS
        if _time_in_window(as_of.astimezone(zone).timetz().replace(tzinfo=None), start, end)
    )
    evidence["special_windows"] = ",".join(special)
    return SessionContext(
        primary=primary,
        active=tuple(active),
        special_windows=special,
        calculated_at=as_of,
        evidence=evidence,
    )


def calculate_session_ranges(
    bars: Sequence[SessionPriceBar],
    as_of: datetime,
    *,
    scheduled_pauses: Sequence[SessionPause] = (),
) -> tuple[SessionRange, ...]:
    """Calculate the latest eligible Asia, London, and New York ranges.

    Every range is anchored in its local IANA timezone and converted to UTC. Only
    bars closed and available by ``as_of`` are eligible. This keeps replay and DST
    behaviour deterministic.
    """

    if as_of.tzinfo is None:
        raise ValueError("as_of must be timezone-aware")
    cutoff = as_of.astimezone(UTC)
    eligible = sorted(
        (bar for bar in bars if bar.close_time <= cutoff and bar.available_at <= cutoff),
        key=lambda bar: bar.open_time,
    )
    output: list[SessionRange] = []
    for name, zone in SESSION_ZONES.items():
        local_start, local_end = SESSION_HOURS[name]
        start_at, end_at = _latest_session_window(
            cutoff,
            zone=zone,
            local_start=local_start,
            local_end=local_end,
        )
        range_cutoff = min(cutoff, end_at)
        members = [
            bar for bar in eligible if bar.open_time >= start_at and bar.close_time <= range_cutoff
        ]
        elapsed_minutes = max(
            0,
            int((range_cutoff - start_at).total_seconds() // 60),
        )
        candidate_opens = (start_at + timedelta(minutes=index) for index in range(elapsed_minutes))
        expected_opens = {
            candidate
            for candidate in candidate_opens
            if not _in_scheduled_pause(candidate, scheduled_pauses)
        }
        expected = len(expected_opens)
        unique_opens = {bar.open_time.astimezone(UTC) for bar in members}
        completeness = (
            min(100.0, len(unique_opens & expected_opens) / expected * 100) if expected else 0.0
        )
        active = start_at <= cutoff < end_at
        if active:
            status = "ACTIVE"
        elif not members:
            status = "NO_DATA"
        elif completeness >= 99.5:
            status = "COMPLETE"
        else:
            status = "INCOMPLETE"

        session_high = max((bar.high for bar in members), default=None)
        session_low = min((bar.low for bar in members), default=None)
        session_open = members[0].open if members else None
        session_close = members[-1].close if members else None
        post_session = [bar for bar in eligible if end_at < bar.close_time <= cutoff]
        breakout_state = "FORMING" if active else "NOT_EVALUABLE"
        if not active and post_session and session_high is not None and session_low is not None:
            latest_close = post_session[-1].close
            if latest_close > session_high:
                breakout_state = "ACCEPTED_ABOVE"
            elif latest_close < session_low:
                breakout_state = "ACCEPTED_BELOW"
            else:
                traded_above = max(bar.high for bar in post_session) > session_high
                traded_below = min(bar.low for bar in post_session) < session_low
                if traded_above and traded_below:
                    breakout_state = "BOTH_SIDES_REJECTED"
                elif traded_above:
                    breakout_state = "ABOVE_REJECTED"
                elif traded_below:
                    breakout_state = "BELOW_REJECTED"
                else:
                    breakout_state = "INSIDE_RANGE"

        output.append(
            SessionRange(
                name=name,
                timezone=zone.key,
                start_at=start_at,
                end_at=end_at,
                status=status,
                bar_count=len(members),
                expected_bar_count=expected,
                completeness_pct=round(completeness, 2),
                open=session_open,
                high=session_high,
                low=session_low,
                close=session_close,
                range_size=(
                    round(session_high - session_low, 6)
                    if session_high is not None and session_low is not None
                    else None
                ),
                breakout_state=breakout_state,
            )
        )
    return tuple(output)


def _latest_session_window(
    as_of: datetime,
    *,
    zone: ZoneInfo,
    local_start: time,
    local_end: time,
) -> tuple[datetime, datetime]:
    local_now = as_of.astimezone(zone)
    session_date = local_now.date()
    candidate_start = _local_datetime(session_date, local_start, zone)
    if as_of < candidate_start.astimezone(UTC):
        session_date -= timedelta(days=1)
    session_date = _previous_weekday(session_date)
    start_at = _local_datetime(session_date, local_start, zone).astimezone(UTC)
    end_date = session_date + (timedelta(days=1) if local_end <= local_start else timedelta())
    end_at = _local_datetime(end_date, local_end, zone).astimezone(UTC)
    return start_at, end_at


def _local_datetime(value: date, clock: time, zone: ZoneInfo) -> datetime:
    return datetime.combine(value, clock, tzinfo=zone)


def _previous_weekday(value: date) -> date:
    while value.weekday() >= 5:
        value -= timedelta(days=1)
    return value


def _time_in_window(value: time, start: time, end: time) -> bool:
    if start < end:
        return start <= value < end
    return value >= start or value < end


def _in_scheduled_pause(
    timestamp: datetime,
    pauses: Sequence[SessionPause],
) -> bool:
    return any(
        _time_in_window(
            timestamp.astimezone(pause.timezone).timetz().replace(tzinfo=None),
            pause.start,
            pause.end,
        )
        for pause in pauses
    )
