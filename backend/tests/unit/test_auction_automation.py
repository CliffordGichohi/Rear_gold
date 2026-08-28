from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from gold_intel.analytics.auction_automation import (
    _entry_session,
    auction_automation_to_dict,
    build_auction_automation_snapshot,
)
from gold_intel.analytics.structure import MinuteBar
from gold_intel.api.schemas import AuctionAutomationResponse


def _minute(
    open_time: datetime,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> MinuteBar:
    return MinuteBar(
        id=uuid5(NAMESPACE_URL, open_time.isoformat()),
        open_time=open_time,
        close_time=open_time + timedelta(minutes=1),
        open=open_price,
        high=max(high, open_price, close),
        low=min(low, open_price, close),
        close=close,
        volume=10,
        available_at=open_time + timedelta(minutes=1),
    )


def _m15_block(
    start: datetime,
    index: int,
    *,
    open_price: float,
    high: float,
    low: float,
    close: float,
) -> list[MinuteBar]:
    output: list[MinuteBar] = []
    block_start = start + timedelta(minutes=15 * index)
    for minute_index in range(15):
        fraction = minute_index / 15
        next_fraction = (minute_index + 1) / 15
        minute_open = open_price + (close - open_price) * fraction
        minute_close = open_price + (close - open_price) * next_fraction
        output.append(
            _minute(
                block_start + timedelta(minutes=minute_index),
                open_price=minute_open,
                high=high if minute_index == 0 else max(minute_open, minute_close),
                low=low if minute_index == 0 else min(minute_open, minute_close),
                close=minute_close,
            )
        )
    return output


def _retest_block(start: datetime, index: int) -> list[MinuteBar]:
    block_start = start + timedelta(minutes=15 * index)
    prices = [100.50, 101.10, 101.70, 102.30, 102.90, 103.30]
    output: list[MinuteBar] = []
    for minute_index in range(5):
        output.append(
            _minute(
                block_start + timedelta(minutes=minute_index),
                open_price=prices[minute_index],
                high=103.50 if minute_index == 4 else prices[minute_index + 1],
                low=99.80 if minute_index == 0 else prices[minute_index],
                close=prices[minute_index + 1],
            )
        )
    for minute_index in range(5, 15):
        minute_open = 103.30 + (minute_index - 5) * 0.02
        minute_close = minute_open + 0.02
        output.append(
            _minute(
                block_start + timedelta(minutes=minute_index),
                open_price=minute_open,
                high=104.00 if minute_index == 14 else minute_close,
                low=minute_open,
                close=minute_close,
            )
        )
    return output


def _scenario() -> tuple[datetime, list[MinuteBar]]:
    start = datetime(2024, 1, 8, 0, 0, tzinfo=UTC)
    bars: list[MinuteBar] = []
    for index in range(40):
        if index == 10:
            specification = (100.0, 105.0, 99.0, 100.2)
        elif index == 17:
            specification = (101.0, 101.5, 99.0, 100.0)
        elif index == 18:
            specification = (100.0, 108.0, 99.5, 107.0)
        elif index == 32:
            bars.extend(_retest_block(start, index))
            continue
        elif 19 <= index < 32:
            specification = (106.0, 107.0, 104.0, 105.5)
        else:
            close = 100.2 if index % 2 == 0 else 99.8
            specification = (100.0, 101.0, 99.0, close)
        bars.extend(
            _m15_block(
                start,
                index,
                open_price=specification[0],
                high=specification[1],
                low=specification[2],
                close=specification[3],
            )
        )
    return start, bars


def test_zone_is_not_available_before_displacement_close() -> None:
    start, bars = _scenario()
    before = build_auction_automation_snapshot(
        bars,
        as_of=start + timedelta(minutes=15 * 19 - 1),
    )
    after = build_auction_automation_snapshot(
        bars,
        as_of=start + timedelta(minutes=15 * 19),
    )

    assert before.zones == ()
    assert len(after.zones) == 1
    zone = after.zones[0]
    assert zone.direction == "BULLISH"
    assert zone.created_at == start + timedelta(minutes=15 * 19)
    assert zone.detected_at == zone.created_at
    assert zone.origin_at == start + timedelta(minutes=15 * 17)
    assert zone.lower_bound == 99.0
    assert zone.upper_bound == 101.0
    assert zone.epistemic_status == "INFERRED"


def test_limit_proposal_uses_actual_geometry_and_point_in_time_macro() -> None:
    start, bars = _scenario()
    as_of = start + timedelta(hours=8, minutes=15)
    snapshot = build_auction_automation_snapshot(
        bars,
        as_of=as_of,
        macro_bias_label="MODERATELY_BULLISH",
        macro_available_at=start + timedelta(hours=7, minutes=30),
        liquidity_status="NORMAL",
    )

    zone = snapshot.zones[0]
    assert zone.first_touch_at is not None
    assert zone.retest_confirmed_at is not None
    limit = next(item for item in snapshot.proposals if item.family == "RETEST_LIMIT_V0_1")
    assert limit.triggered_at is not None
    assert limit.entry_reference == 100.0
    assert limit.quantity_ounces is not None
    assert limit.planned_risk_usd is not None
    assert 0 < limit.planned_risk_usd <= 50
    assert limit.target == 105.0
    assert limit.reward_to_risk is not None and limit.reward_to_risk >= 1.25
    assert limit.macro_relationship == "ALIGNED"
    assert limit.disposition == "PAPER_READY"
    assert limit.evidence["live_order_permitted"] is False


def test_later_macro_snapshot_is_not_backfilled_into_prior_trigger() -> None:
    start, bars = _scenario()
    as_of = start + timedelta(hours=8, minutes=15)
    snapshot = build_auction_automation_snapshot(
        bars,
        as_of=as_of,
        macro_bias_label="MODERATELY_BULLISH",
        macro_available_at=as_of,
        liquidity_status="NORMAL",
    )
    limit = next(item for item in snapshot.proposals if item.family == "RETEST_LIMIT_V0_1")

    assert limit.triggered_at is not None and limit.triggered_at < as_of
    assert limit.macro_direction == "UNKNOWN"
    assert limit.macro_relationship == "UNKNOWN"
    assert limit.disposition == "WAITING_MACRO"


def test_automation_is_byte_stable_for_identical_inputs() -> None:
    start, bars = _scenario()
    kwargs = {
        "as_of": start + timedelta(hours=8, minutes=15),
        "macro_bias_label": "MODERATELY_BULLISH",
        "macro_available_at": start + timedelta(hours=7, minutes=30),
        "liquidity_status": "NORMAL",
    }
    primary = auction_automation_to_dict(build_auction_automation_snapshot(bars, **kwargs))
    reference = auction_automation_to_dict(build_auction_automation_snapshot(bars, **kwargs))

    primary_bytes = json.dumps(primary, sort_keys=True, default=str).encode()
    reference_bytes = json.dumps(reference, sort_keys=True, default=str).encode()
    assert primary_bytes == reference_bytes
    assert primary["data_hash"] == reference["data_hash"]


def test_automation_payload_satisfies_the_public_api_contract() -> None:
    start, bars = _scenario()
    payload = auction_automation_to_dict(
        build_auction_automation_snapshot(
            bars,
            as_of=start + timedelta(hours=8, minutes=15),
            macro_bias_label="MODERATELY_BULLISH",
            macro_available_at=start + timedelta(hours=7, minutes=30),
            liquidity_status="NORMAL",
        )
    )

    validated = AuctionAutomationResponse.model_validate(payload)

    assert validated.ruleset_version == "gold-auction-automation-1"
    assert validated.proposals
    assert all(
        proposal.planned_risk_usd is None or proposal.planned_risk_usd <= 50
        for proposal in validated.proposals
    )


def test_entry_session_is_dst_aware() -> None:
    assert _entry_session(datetime(2024, 1, 8, 8, 0, tzinfo=UTC)) is True
    assert _entry_session(datetime(2024, 7, 8, 7, 0, tzinfo=UTC)) is True
    assert _entry_session(datetime(2024, 1, 8, 6, 0, tzinfo=UTC)) is False
