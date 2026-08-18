from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import text

from gold_intel.infrastructure.database import session_factory

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class Bar:
    open_time: datetime
    close_time: datetime
    open: float
    high: float
    low: float
    close: float
    volume: float
    spread: float


@dataclass(frozen=True, slots=True)
class Day:
    session_date: date
    asia: tuple[Bar, ...]
    london: tuple[Bar, ...]
    new_york: tuple[Bar, ...]


FIVE_MINUTE_SQL = text(
    """
    WITH canonical AS (
        SELECT DISTINCT ON (open_time)
            open_time,
            close_time,
            open,
            high,
            low,
            close,
            volume,
            spread_price,
            available_at
        FROM market.price_bars
        WHERE instrument_code = 'XAUUSD'
          AND provider_code = 'IC_MARKETS_MT5'
          AND timeframe = '1m'
          AND is_complete
          AND NOT is_synthetic
          AND open_time >= :load_start
          AND open_time < :load_end
          AND available_at <= close_time
        ORDER BY open_time, available_at
    )
    SELECT
        time_bucket('5 minutes', open_time) AS open_time,
        time_bucket('5 minutes', open_time) + interval '5 minutes' AS close_time,
        first(open, open_time) AS open,
        max(high) AS high,
        min(low) AS low,
        last(close, open_time) AS close,
        sum(volume) AS volume,
        max(spread_price) AS spread_price,
        count(*) AS minute_count
    FROM canonical
    GROUP BY 1
    HAVING count(*) = 5
    ORDER BY 1
    """
)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--start", default="2021-08-01")
    parser.add_argument("--end", default="2025-01-01")
    args = parser.parse_args()
    start = datetime.fromisoformat(args.start).replace(tzinfo=UTC)
    end = datetime.fromisoformat(args.end).replace(tzinfo=UTC)
    if start >= end:
        raise ValueError("start must precede end")

    async with session_factory() as session:
        rows = (
            await session.execute(
                FIVE_MINUTE_SQL,
                {
                    "load_start": start - timedelta(days=2),
                    "load_end": end,
                },
            )
        ).mappings()
        bars = [
            Bar(
                open_time=row["open_time"],
                close_time=row["close_time"],
                open=float(row["open"]),
                high=float(row["high"]),
                low=float(row["low"]),
                close=float(row["close"]),
                volume=float(row["volume"]),
                spread=float(row["spread_price"]),
            )
            for row in rows
        ]
    days = _build_days(bars, start=start, end=end)
    print(json.dumps(_summarize(days), indent=2, sort_keys=True))


def _build_days(
    bars: list[Bar],
    *,
    start: datetime,
    end: datetime,
) -> list[Day]:
    bars_by_open = {item.open_time: item for item in bars}
    first_date = start.astimezone(LONDON).date()
    last_date = (end - timedelta(microseconds=1)).astimezone(LONDON).date()
    output: list[Day] = []
    current = first_date
    while current <= last_date:
        if current.weekday() < 5:
            asia_start = datetime.combine(current, time(10, 5), tzinfo=TOKYO).astimezone(UTC)
            asia_end = datetime.combine(current, time(16, 0), tzinfo=TOKYO).astimezone(UTC)
            london_start = datetime.combine(current, time(8, 0), tzinfo=LONDON).astimezone(
                UTC
            )
            london_end = datetime.combine(current, time(12, 0), tzinfo=LONDON).astimezone(
                UTC
            )
            ny_start = datetime.combine(current, time(8, 0), tzinfo=NEW_YORK).astimezone(
                UTC
            )
            ny_end = datetime.combine(current, time(12, 0), tzinfo=NEW_YORK).astimezone(
                UTC
            )
            asia = _window(bars_by_open, asia_start, asia_end)
            london = _window(bars_by_open, london_start, london_end)
            new_york = _window(bars_by_open, ny_start, ny_end)
            if (
                _complete(asian := asia, asia_start, asia_end)
                and _complete(london, london_start, london_end)
                and _complete(new_york, ny_start, ny_end)
            ):
                output.append(
                    Day(
                        session_date=current,
                        asia=asian,
                        london=london,
                        new_york=new_york,
                    )
                )
        current += timedelta(days=1)
    return output


def _window(
    bars_by_open: dict[datetime, Bar],
    start: datetime,
    end: datetime,
) -> tuple[Bar, ...]:
    expected = int((end - start).total_seconds() // 300)
    return tuple(
        bars_by_open[open_time]
        for offset in range(expected)
        if (open_time := start + timedelta(minutes=offset * 5)) in bars_by_open
    )


def _complete(
    bars: tuple[Bar, ...],
    start: datetime,
    end: datetime,
) -> bool:
    expected = int((end - start).total_seconds() // 300)
    return (
        len(bars) == expected
        and bool(bars)
        and bars[0].open_time == start
        and bars[-1].close_time == end
        and all(
            current.open_time == prior.close_time
            for prior, current in zip(bars, bars[1:], strict=False)
        )
    )


def _summarize(days: list[Day]) -> dict[str, Any]:
    by_year: dict[int, Counter[str]] = {}
    total: Counter[str] = Counter()
    asia_ranges: list[float] = []
    london_ranges: list[float] = []
    for day in days:
        bucket = by_year.setdefault(day.session_date.year, Counter())
        facts = _day_facts(day, asia_ranges=asia_ranges, london_ranges=london_ranges)
        for key, value in facts.items():
            if value:
                total[key] += 1
                bucket[key] += 1
        asia_ranges.append(max(item.high for item in day.asia) - min(item.low for item in day.asia))
        london_ranges.append(
            max(item.high for item in day.london) - min(item.low for item in day.london)
        )

    return {
        "period": {
            "first_complete_session": days[0].session_date.isoformat() if days else None,
            "last_complete_session": days[-1].session_date.isoformat() if days else None,
            "complete_sessions": len(days),
        },
        "totals": _counter_payload(total, denominator=len(days)),
        "by_year": {
            str(year): _counter_payload(counter, denominator=counter["sessions"])
            for year, counter in sorted(by_year.items())
        },
        "interpretation": {
            "london_close_outside": (
                "London closed beyond the Asian boundary it broke; this is an "
                "acceptance/continuation research state, not an entry."
            ),
            "ny_confirms_london_outside": (
                "New York noon remained beyond the same Asian boundary after a "
                "London outside close."
            ),
            "ny_rejects_london_outside": (
                "New York noon returned inside the Asian range after a London "
                "outside close."
            ),
        },
    }


def _day_facts(
    day: Day,
    *,
    asia_ranges: list[float],
    london_ranges: list[float],
) -> dict[str, bool]:
    asia_high = max(item.high for item in day.asia)
    asia_low = min(item.low for item in day.asia)
    london_high = max(item.high for item in day.london)
    london_low = min(item.low for item in day.london)
    high_breach_index = next(
        (index for index, item in enumerate(day.london) if item.high > asia_high),
        None,
    )
    low_breach_index = next(
        (index for index, item in enumerate(day.london) if item.low < asia_low),
        None,
    )
    first_side = (
        "HIGH"
        if high_breach_index is not None
        and (low_breach_index is None or high_breach_index < low_breach_index)
        else "LOW"
        if low_breach_index is not None
        else "NONE"
    )
    london_close = day.london[-1].close
    ny_close = day.new_york[-1].close
    london_outside = (
        "HIGH"
        if london_close > asia_high
        else "LOW"
        if london_close < asia_low
        else "INSIDE"
    )
    prior_asia_median = _median(asia_ranges[-20:])
    prior_london_median = _median(london_ranges[-20:])
    asia_range = asia_high - asia_low
    london_range = london_high - london_low
    ny_confirms = (
        (london_outside == "HIGH" and ny_close > asia_high)
        or (london_outside == "LOW" and ny_close < asia_low)
    )
    ny_rejects = london_outside in {"HIGH", "LOW"} and asia_low <= ny_close <= asia_high
    ny_reverses = (
        (london_outside == "HIGH" and ny_close < asia_low)
        or (london_outside == "LOW" and ny_close > asia_high)
    )
    return {
        "sessions": True,
        "london_breaks_asia": first_side != "NONE",
        "london_breaks_high": high_breach_index is not None,
        "london_breaks_low": low_breach_index is not None,
        "london_breaks_both": high_breach_index is not None and low_breach_index is not None,
        "london_first_break_high": first_side == "HIGH",
        "london_first_break_low": first_side == "LOW",
        "london_close_outside": london_outside in {"HIGH", "LOW"},
        "london_close_outside_high": london_outside == "HIGH",
        "london_close_outside_low": london_outside == "LOW",
        "london_break_rejected_by_noon": first_side != "NONE" and london_outside == "INSIDE",
        "ny_confirms_london_outside": ny_confirms,
        "ny_rejects_london_outside": ny_rejects,
        "ny_reverses_london_outside": ny_reverses,
        "asia_compressed_vs_prior_median": (
            prior_asia_median is not None and asia_range <= prior_asia_median
        ),
        "london_expanded_vs_prior_median": (
            prior_london_median is not None and london_range >= prior_london_median
        ),
        "london_extreme_expansion_1_5x": (
            prior_london_median is not None
            and london_range >= 1.5 * prior_london_median
        ),
    }


def _counter_payload(counter: Counter[str], *, denominator: int) -> dict[str, Any]:
    return {
        key: {
            "count": value,
            "pct_of_complete_sessions": round(value / denominator * 100, 4)
            if denominator
            else None,
        }
        for key, value in sorted(counter.items())
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    midpoint = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[midpoint]
    return (ordered[midpoint - 1] + ordered[midpoint]) / 2


if __name__ == "__main__":
    asyncio.run(main())
