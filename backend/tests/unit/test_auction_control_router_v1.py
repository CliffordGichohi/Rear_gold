from datetime import UTC, datetime, timedelta

from gold_intel.analytics.auction_control_router_v1 import (
    accepted_state_sequence,
    active_control_event,
    earliest_candidate,
    first_bearish_retest,
    raw_control_label,
    short_classification,
    spread_price,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import simulate_track


def bar(
    opened: datetime,
    *,
    minutes: int = 5,
    open_: float = 100.0,
    high: float = 101.0,
    low: float = 99.0,
    close: float = 100.0,
) -> dict:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": opened.isoformat().replace("+00:00", "Z"),
        "close_at": closed.isoformat().replace("+00:00", "Z"),
        "available_at": closed.isoformat().replace("+00:00", "Z"),
        "open": open_,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "source_record_hash": f"row-{opened.timestamp()}",
    }


def event(direction: str, break_at: str, invalidated_at: str | None = None) -> dict:
    return {
        "identity": f"{direction}-{break_at}",
        "direction": direction,
        "break_at": break_at,
        "invalidated_at": invalidated_at,
    }


def test_control_labels_are_mutually_exclusive() -> None:
    long = event("LONG", "2022-01-03T08:00:00Z")
    short = event("SHORT", "2022-01-03T08:00:00Z")

    assert raw_control_label(long, long) == "BUYER_CONTROL"
    assert raw_control_label(short, short) == "SELLER_CONTROL"
    assert raw_control_label(long, short) == "CONFLICTED"
    assert raw_control_label(None, short) == "UNRESOLVED"


def test_acceptance_requires_two_consecutive_closes_and_resets() -> None:
    raw = [
        "BUYER_CONTROL",
        "BUYER_CONTROL",
        "CONFLICTED",
        "SELLER_CONTROL",
        "SELLER_CONTROL",
        "UNRESOLVED",
        "BUYER_CONTROL",
    ]
    assert accepted_state_sequence(raw) == [
        "UNRESOLVED",
        "BUYER_CONTROL",
        "CONFLICTED",
        "UNRESOLVED",
        "SELLER_CONTROL",
        "UNRESOLVED",
        "UNRESOLVED",
    ]


def test_active_event_excludes_the_invalidation_boundary() -> None:
    events = [
        event(
            "LONG",
            "2022-01-03T08:00:00Z",
            invalidated_at="2022-01-03T09:00:00Z",
        )
    ]
    assert active_control_event(events, "2022-01-03T08:59:59Z") is events[0]
    assert active_control_event(events, "2022-01-03T09:00:00Z") is None


def test_bearish_retest_is_first_qualifier_and_expires_after_six_bars() -> None:
    start = datetime(2022, 1, 3, 7, tzinfo=UTC)
    warmup = [bar(start + timedelta(minutes=5 * index)) for index in range(15)]
    accepted = warmup[-1]["available_at"]
    first = bar(
        start + timedelta(minutes=75),
        open_=100.8,
        high=101.0,
        low=99.0,
        close=99.5,
    )
    later = bar(
        start + timedelta(minutes=80),
        open_=100.6,
        high=101.2,
        low=98.8,
        close=99.2,
    )
    result = first_bearish_retest(
        warmup + [first, later],
        accepted_at=accepted,
        session_end=start + timedelta(hours=3),
        broken_level=100.0,
    )
    assert result is not None
    assert result["bar_open_at"] == first["open_at"]

    six_misses = [
        bar(
            start + timedelta(minutes=75 + 5 * index),
            open_=98.8,
            high=99.0,
            low=98.0,
            close=98.5,
        )
        for index in range(6)
    ]
    seventh_hit = bar(
        start + timedelta(minutes=105),
        open_=100.8,
        high=101.0,
        low=99.0,
        close=99.5,
    )
    assert (
        first_bearish_retest(
            warmup + six_misses + [seventh_hit],
            accepted_at=accepted,
            session_end=start + timedelta(hours=3),
            broken_level=100.0,
        )
        is None
    )


def test_spread_and_earliest_candidate_are_adverse_and_deterministic() -> None:
    assert spread_price({"spread_price": 0.2}) == 0.2
    assert spread_price({"spread_price": None}) == 0.2
    long = {
        "direction": "LONG",
        "fill_at": "2022-01-03T14:01:00Z",
    }
    short = {
        "direction": "SHORT",
        "fill_at": "2022-01-03T13:01:00Z",
    }
    assert earliest_candidate(long, short) is short
    short["fill_at"] = long["fill_at"]
    assert earliest_candidate(long, short) is long


def test_short_execution_preserves_stop_first_ambiguity() -> None:
    point = datetime(2022, 1, 3, 8, tzinfo=UTC)
    plan = {
        "admitted": True,
        "confirmation": {"confirmation_at": point.isoformat().replace("+00:00", "Z")},
        "macro": {"state": "NEUTRAL_OR_CONFLICTED"},
        "h4": {"swing_sequence": "BEARISH_SWING_SEQUENCE"},
        "fill": 100.0,
        "stop": 101.0,
        "target": 99.0,
        "structural_price_risk_per_ounce": 1.0,
        "cost_per_ounce": 0.1,
        "quantity_ounces": 45,
    }
    classification = short_classification(plan)
    ambiguous = bar(
        point + timedelta(minutes=1),
        minutes=1,
        open_=100.0,
        high=101.5,
        low=98.5,
        close=99.5,
    )
    stream = {
        "end_exclusive": (point + timedelta(minutes=3)).isoformat().replace(
            "+00:00", "Z"
        ),
        "timeframes": {"1m": [ambiguous], "15m": []},
    }
    result = simulate_track(
        classification=classification,
        stream=stream,
        fill_at=ambiguous["open_at"],
        track="FAITHFUL_FIXED_GEOMETRY",
    )
    assert result["executed"] is True
    assert result["resolution"] == "STRUCTURAL_STOP"
    assert result["net_r50"] < 0
