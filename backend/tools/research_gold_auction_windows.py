from __future__ import annotations

import argparse
import asyncio
import json
import statistics
from collections import defaultdict
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from explore_session_playbooks import (
    FIVE_MINUTE_SQL,
    LONDON,
    NEW_YORK,
    Bar,
    _complete,
    _window,
)

from gold_intel.infrastructure.database import session_factory


@dataclass(frozen=True, slots=True)
class WindowSpec:
    name: str
    timezone: ZoneInfo
    pre_start: time
    pre_end: time
    post_start: time
    post_end: time
    interpretation: str


@dataclass(frozen=True, slots=True)
class WindowRecord:
    name: str
    session_date: date
    pre_range: float
    pre_return: float
    post_range: float
    post_return: float
    post_mfe_up: float
    post_mfe_down: float
    post_break: str
    post_close_state: str
    entry_spread: float
    exit_spread: float


SPECS = (
    WindowSpec(
        "LONDON_OPEN_0800",
        LONDON,
        time(7, 0),
        time(8, 0),
        time(8, 0),
        time(9, 0),
        "London opening auction after the overnight range.",
    ),
    WindowSpec(
        "LBMA_AM_1030",
        LONDON,
        time(9, 30),
        time(10, 30),
        time(10, 30),
        time(11, 30),
        "Official LBMA AM gold-price auction at 10:30 London time.",
    ),
    WindowSpec(
        "COMEX_OPEN_0820",
        NEW_YORK,
        time(7, 20),
        time(8, 20),
        time(8, 20),
        time(9, 20),
        "COMEX floor-session opening and US-data handover.",
    ),
    WindowSpec(
        "US_DATA_0830",
        NEW_YORK,
        time(7, 30),
        time(8, 30),
        time(8, 30),
        time(9, 30),
        "Common timestamp for major US macro releases.",
    ),
    WindowSpec(
        "LBMA_PM_1500",
        LONDON,
        time(14, 0),
        time(15, 0),
        time(15, 0),
        time(16, 0),
        "Official LBMA PM gold-price auction at 15:00 London time.",
    ),
    WindowSpec(
        "COMEX_SETTLEMENT_1330",
        NEW_YORK,
        time(12, 30),
        time(13, 30),
        time(13, 30),
        time(14, 30),
        "Five-minute proxy around the official 13:29-13:30 ET settlement.",
    ),
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
    if end > datetime(2025, 1, 1, tzinfo=UTC):
        raise ValueError("The locked 2025 holdout must not be loaded")

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

    records = _records(bars, start=start, end=end)
    print(
        json.dumps(
            {
                "contract": {
                    "version": "GOLD_AUCTION_WINDOWS_V0_1",
                    "start": start.isoformat(),
                    "end": end.isoformat(),
                    "locked_holdout": "calendar year 2025 (not loaded)",
                    "bar_resolution": "complete point-in-time 5-minute bars",
                    "purpose": (
                        "Descriptive auction-state audit. These are not trading "
                        "signals and no direction is selected with future data."
                    ),
                },
                "windows": {
                    spec.name: {
                        "interpretation": spec.interpretation,
                        "all": _summary(
                            [
                                record
                                for record in records
                                if record.name == spec.name
                            ]
                        ),
                        "by_year": {
                            str(year): _summary(
                                [
                                    record
                                    for record in records
                                    if record.name == spec.name
                                    and record.session_date.year == year
                                ]
                            )
                            for year in range(2021, 2025)
                        },
                    }
                    for spec in SPECS
                },
            },
            indent=2,
            sort_keys=True,
        )
    )


def _records(
    bars: Sequence[Bar],
    *,
    start: datetime,
    end: datetime,
) -> list[WindowRecord]:
    bars_by_open = {bar.open_time: bar for bar in bars}
    first_date = start.astimezone(LONDON).date()
    last_date = (end - timedelta(microseconds=1)).astimezone(LONDON).date()
    output: list[WindowRecord] = []
    current = first_date
    while current <= last_date:
        if current.weekday() < 5:
            for spec in SPECS:
                record = _record_for_spec(
                    current,
                    spec=spec,
                    bars_by_open=bars_by_open,
                )
                if record is not None:
                    output.append(record)
        current += timedelta(days=1)
    return output


def _record_for_spec(
    session_date: date,
    *,
    spec: WindowSpec,
    bars_by_open: dict[datetime, Bar],
) -> WindowRecord | None:
    pre_start = datetime.combine(
        session_date,
        spec.pre_start,
        tzinfo=spec.timezone,
    ).astimezone(UTC)
    pre_end = datetime.combine(
        session_date,
        spec.pre_end,
        tzinfo=spec.timezone,
    ).astimezone(UTC)
    post_start = datetime.combine(
        session_date,
        spec.post_start,
        tzinfo=spec.timezone,
    ).astimezone(UTC)
    post_end = datetime.combine(
        session_date,
        spec.post_end,
        tzinfo=spec.timezone,
    ).astimezone(UTC)
    pre = _window(bars_by_open, pre_start, pre_end)
    post = _window(bars_by_open, post_start, post_end)
    if not _complete(pre, pre_start, pre_end) or not _complete(
        post,
        post_start,
        post_end,
    ):
        return None
    pre_high = max(bar.high for bar in pre)
    pre_low = min(bar.low for bar in pre)
    post_high = max(bar.high for bar in post)
    post_low = min(bar.low for bar in post)
    broke_high = post_high > pre_high
    broke_low = post_low < pre_low
    post_break = (
        "BOTH"
        if broke_high and broke_low
        else "HIGH"
        if broke_high
        else "LOW"
        if broke_low
        else "NONE"
    )
    post_close_state = (
        "ABOVE"
        if post[-1].close > pre_high
        else "BELOW"
        if post[-1].close < pre_low
        else "INSIDE"
    )
    return WindowRecord(
        name=spec.name,
        session_date=session_date,
        pre_range=pre_high - pre_low,
        pre_return=pre[-1].close - pre[0].open,
        post_range=post_high - post_low,
        post_return=post[-1].close - post[0].open,
        post_mfe_up=post_high - post[0].open,
        post_mfe_down=post[0].open - post_low,
        post_break=post_break,
        post_close_state=post_close_state,
        entry_spread=post[0].spread,
        exit_spread=post[-1].spread,
    )


def _summary(records: Sequence[WindowRecord]) -> dict[str, Any]:
    if not records:
        return {"observations": 0}
    nonzero = [
        record
        for record in records
        if record.pre_return != 0 and record.post_return != 0
    ]
    continuation = [
        record
        for record in nonzero
        if record.pre_return * record.post_return > 0
    ]
    rejection = [
        record
        for record in records
        if record.post_break in {"HIGH", "LOW", "BOTH"}
        and record.post_close_state == "INSIDE"
    ]
    outside = [
        record
        for record in records
        if record.post_close_state in {"ABOVE", "BELOW"}
    ]
    return {
        "observations": len(records),
        "median_pre_range_usd": round(
            statistics.median(record.pre_range for record in records),
            4,
        ),
        "median_post_range_usd": round(
            statistics.median(record.post_range for record in records),
            4,
        ),
        "median_post_absolute_return_usd": round(
            statistics.median(abs(record.post_return) for record in records),
            4,
        ),
        "median_post_best_excursion_usd": round(
            statistics.median(
                max(record.post_mfe_up, record.post_mfe_down)
                for record in records
            ),
            4,
        ),
        "pre_direction_continues_pct": round(
            len(continuation) / len(nonzero) * 100,
            3,
        ),
        "post_breaks_pre_range_pct": round(
            sum(record.post_break != "NONE" for record in records)
            / len(records)
            * 100,
            3,
        ),
        "post_closes_outside_pre_range_pct": round(
            len(outside) / len(records) * 100,
            3,
        ),
        "broken_range_rejected_pct": round(
            len(rejection)
            / max(
                1,
                sum(record.post_break != "NONE" for record in records),
            )
            * 100,
            3,
        ),
        "median_round_trip_spread_usd": round(
            statistics.median(
                record.entry_spread / 2 + record.exit_spread / 2
                for record in records
            ),
            4,
        ),
        "post_break_states": dict(
            sorted(
                _counts(record.post_break for record in records).items()
            )
        ),
        "post_close_states": dict(
            sorted(
                _counts(record.post_close_state for record in records).items()
            )
        ),
    }


def _counts(values: Sequence[str] | Any) -> dict[str, int]:
    output: dict[str, int] = defaultdict(int)
    for value in values:
        output[str(value)] += 1
    return dict(output)


if __name__ == "__main__":
    asyncio.run(main())
