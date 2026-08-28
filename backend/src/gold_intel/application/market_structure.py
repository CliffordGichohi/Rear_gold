from __future__ import annotations

from dataclasses import asdict
from datetime import UTC, datetime, time
from typing import Any, Literal
from zoneinfo import ZoneInfo

from sqlalchemy import Select, select
from sqlalchemy.ext.asyncio import AsyncSession

from gold_intel.analytics.auction_automation import (
    auction_automation_to_dict,
    build_auction_automation_snapshot,
)
from gold_intel.analytics.liquidity import LiquidityBar, calculate_liquidity_snapshot
from gold_intel.analytics.sessions import (
    SessionPause,
    SessionPriceBar,
    calculate_session_ranges,
    session_at,
)
from gold_intel.analytics.structure import (
    MinuteBar,
    StructureConfig,
    build_market_structure_snapshot,
    market_structure_to_dict,
)
from gold_intel.infrastructure.models import FundamentalSnapshot, PriceBar

StructureDataMode = Literal["AUTO", "REAL_ONLY", "SYNTHETIC_ONLY"]
IC_MARKETS_MT5_CONFIG = StructureConfig(
    monday_session_start_hour_new_york=21,
    daily_pause_start_minute_new_york=19 * 60 + 59,
    daily_pause_end_minute_new_york=21 * 60,
)
IC_MARKETS_MT5_PAUSES = (
    SessionPause(
        name="IC_MARKETS_DAILY_MAINTENANCE",
        timezone=ZoneInfo("America/New_York"),
        start=time(19, 59),
        end=time(21, 0),
    ),
)


async def calculate_market_structure(
    session: AsyncSession,
    *,
    instrument: str,
    provider_code: str | None,
    as_of: datetime | None,
    data_mode: StructureDataMode,
    chart_timeframe: str,
    max_source_bars: int,
) -> dict[str, Any] | None:
    requested_cutoff = as_of.astimezone(UTC) if as_of is not None else datetime.now(UTC)
    selected = await _resolve_latest_bar(
        session,
        instrument=instrument,
        provider_code=provider_code,
        cutoff=requested_cutoff,
        data_mode=data_mode,
    )
    if selected is None:
        return None

    selected_provider = selected.provider_code
    selected_synthetic = selected.is_synthetic
    calculation_cutoff = (
        requested_cutoff if as_of is not None else min(requested_cutoff, selected.close_time)
    )
    query = (
        select(PriceBar)
        .where(
            PriceBar.instrument_code == instrument,
            PriceBar.provider_code == selected_provider,
            PriceBar.timeframe == "1m",
            PriceBar.is_complete.is_(True),
            PriceBar.is_synthetic.is_(selected_synthetic),
            PriceBar.close_time <= calculation_cutoff,
            PriceBar.available_at <= calculation_cutoff,
        )
        .order_by(PriceBar.open_time.desc(), PriceBar.available_at.desc())
        .limit(max_source_bars)
    )
    rows = list((await session.scalars(query)).all())
    canonical: dict[datetime, PriceBar] = {}
    for row in rows:
        canonical.setdefault(row.open_time, row)
    ordered = sorted(canonical.values(), key=lambda item: item.open_time)
    minute_bars = [
        MinuteBar(
            id=row.id,
            open_time=row.open_time,
            close_time=row.close_time,
            open=float(row.open),
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            volume=float(row.volume) if row.volume is not None else None,
            available_at=row.available_at,
        )
        for row in ordered
    ]
    if not minute_bars:
        return None
    liquidity_bars = [
        LiquidityBar(
            open_time=row.open_time,
            close_time=row.close_time,
            high=float(row.high),
            low=float(row.low),
            close=float(row.close),
            tick_volume=(
                float(row.volume) if row.volume is not None and row.volume_type == "TICK" else None
            ),
            spread_points=row.spread_points,
            spread_price=(float(row.spread_price) if row.spread_price is not None else None),
            available_at=row.available_at,
        )
        for row in ordered
    ]

    session_pauses: tuple[SessionPause, ...]
    if selected_provider == "IC_MARKETS_MT5":
        structure_config = IC_MARKETS_MT5_CONFIG
        session_template = "IC_MARKETS_MT5_XAUUSD_V1"
        session_pauses = IC_MARKETS_MT5_PAUSES
    else:
        structure_config = StructureConfig()
        session_template = "GENERIC_NEW_YORK_18_TO_17_V1"
        session_pauses = ()
    snapshot = build_market_structure_snapshot(
        minute_bars,
        as_of=calculation_cutoff,
        config=structure_config,
        chart_timeframe=chart_timeframe,
    )
    context = session_at(calculation_cutoff)
    session_bars = [
        SessionPriceBar(
            open_time=bar.open_time,
            close_time=bar.close_time,
            open=bar.open,
            high=bar.high,
            low=bar.low,
            close=bar.close,
            available_at=bar.available_at,
        )
        for bar in minute_bars
    ]
    ranges = calculate_session_ranges(
        session_bars,
        calculation_cutoff,
        scheduled_pauses=session_pauses,
    )
    latest_bar = minute_bars[-1]
    liquidity = calculate_liquidity_snapshot(
        liquidity_bars,
        calculation_cutoff,
        provider_code=selected_provider,
    )
    fundamental = await session.scalar(
        select(FundamentalSnapshot)
        .where(
            FundamentalSnapshot.instrument_code == instrument,
            FundamentalSnapshot.as_of <= calculation_cutoff,
        )
        .order_by(
            FundamentalSnapshot.as_of.desc(),
            FundamentalSnapshot.created_at.desc(),
        )
        .limit(1)
    )
    automation = build_auction_automation_snapshot(
        minute_bars,
        as_of=calculation_cutoff,
        macro_bias_label=fundamental.bias_label if fundamental is not None else "UNKNOWN",
        macro_available_at=fundamental.as_of if fundamental is not None else None,
        liquidity_status=liquidity.status,
    )
    response = market_structure_to_dict(snapshot)
    response.update(
        {
            "instrument": instrument,
            "provider_code": selected_provider,
            "provider_session_template": session_template,
            "data_mode": "SYNTHETIC_ONLY" if selected_synthetic else "REAL_ONLY",
            "is_synthetic": selected_synthetic,
            "latest_bar_at": latest_bar.close_time,
            "generated_at": datetime.now(UTC),
            "source_staleness_seconds": max(
                0,
                int((requested_cutoff - latest_bar.available_at).total_seconds()),
            ),
            "session": {
                "primary": context.primary,
                "active": list(context.active),
                "special_windows": list(context.special_windows),
                "calculated_at": context.calculated_at,
                "evidence": context.evidence,
                "ranges": [asdict(item) for item in ranges],
            },
            "liquidity": asdict(liquidity),
            "auction_automation": auction_automation_to_dict(automation),
        }
    )
    return response


async def _resolve_latest_bar(
    session: AsyncSession,
    *,
    instrument: str,
    provider_code: str | None,
    cutoff: datetime,
    data_mode: StructureDataMode,
) -> PriceBar | None:
    modes: tuple[bool, ...]
    if data_mode == "REAL_ONLY":
        modes = (False,)
    elif data_mode == "SYNTHETIC_ONLY":
        modes = (True,)
    else:
        modes = (False, True)

    for synthetic in modes:
        query: Select[tuple[PriceBar]] = select(PriceBar).where(
            PriceBar.instrument_code == instrument,
            PriceBar.timeframe == "1m",
            PriceBar.is_complete.is_(True),
            PriceBar.is_synthetic.is_(synthetic),
            PriceBar.close_time <= cutoff,
            PriceBar.available_at <= cutoff,
        )
        if provider_code is not None:
            query = query.where(PriceBar.provider_code == provider_code)
        row = await session.scalar(
            query.order_by(
                PriceBar.open_time.desc(),
                PriceBar.available_at.desc(),
            ).limit(1)
        )
        if row is not None:
            return row
    return None
