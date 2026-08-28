from __future__ import annotations

from copy import deepcopy

from gold_intel.analytics.all_transition_auction_scanner_v1 import (
    _assert_outcome_blind,
    _sanitized_break,
    enumerate_transition_observations,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash


def _break(identity: str, direction: str, at: str, timeframe: str) -> dict:
    return {
        "identity": identity,
        "timeframe": timeframe,
        "direction": direction,
        "break_at": at,
        "broken_level": 101.0,
        "broken_identity": f"{identity}-broken",
        "protected_level": 99.0,
        "protected_identity": f"{identity}-protected",
        "origin_at": at,
        "origin_adverse": 98.5,
        "atr": 1.0,
        "range_atr": 1.2,
        "body_ratio": 0.7,
        "buffer": 0.05,
        "invalidated_at": "2099-01-01T00:00:00Z",
    }


def _observation(
    minute: int,
    state: str,
    m5: dict | None,
    m15: dict | None,
) -> dict:
    at = f"2022-01-03T13:{minute:02d}:00Z"
    row = {
        "at": at,
        "raw_state": state,
        "state": state,
        "transition": False,
        "m5_event": m5,
        "m15_event": m15,
    }
    row["observation_sha256"] = canonical_hash(row)
    return row


def _fixture() -> list[dict]:
    long_m5_a = _break("LM5-A", "LONG", "2022-01-03T13:05:00Z", "M5")
    long_m15_a = _break("LM15-A", "LONG", "2022-01-03T13:05:00Z", "M15")
    long_m5_b = _break("LM5-B", "LONG", "2022-01-03T13:15:00Z", "M5")
    short_m5_a = _break("SM5-A", "SHORT", "2022-01-03T13:35:00Z", "M5")
    short_m15_a = _break("SM15-A", "SHORT", "2022-01-03T13:35:00Z", "M15")
    short_m5_b = _break("SM5-B", "SHORT", "2022-01-03T13:45:00Z", "M5")
    return [
        _observation(0, "UNRESOLVED", None, None),
        _observation(5, "BUYER_CONTROL", long_m5_a, long_m15_a),
        _observation(10, "BUYER_CONTROL", long_m5_a, long_m15_a),
        _observation(15, "BUYER_CONTROL", long_m5_b, long_m15_a),
        _observation(20, "CONFLICTED", long_m5_b, short_m15_a),
        _observation(25, "BUYER_CONTROL", long_m5_b, long_m15_a),
        _observation(30, "UNRESOLVED", short_m5_a, long_m15_a),
        _observation(35, "SELLER_CONTROL", short_m5_a, short_m15_a),
        _observation(40, "SELLER_CONTROL", short_m5_a, short_m15_a),
        _observation(45, "SELLER_CONTROL", short_m5_b, short_m15_a),
    ]


def test_emits_initial_continuation_reassertion_and_reversal_without_daily_cap() -> None:
    rows = enumerate_transition_observations(_fixture())
    assert [item["event_class"] for item in rows] == [
        "INITIAL_CONTROL",
        "CONTINUATION_REFRESH",
        "CONTROL_REASSERTION",
        "REVERSAL_TRANSFER",
        "CONTINUATION_REFRESH",
    ]
    assert [item["direction"] for item in rows] == [
        "LONG",
        "LONG",
        "LONG",
        "SHORT",
        "SHORT",
    ]
    assert rows[1]["new_break_timeframes"] == ["M5"]
    assert rows[-1]["new_break_timeframes"] == ["M5"]


def test_fallback_to_an_older_event_is_not_a_fresh_continuation() -> None:
    rows = _fixture()
    old = deepcopy(rows[-3]["m5_event"])
    rows.append(_observation(50, "SELLER_CONTROL", old, rows[-1]["m15_event"]))
    events = enumerate_transition_observations(rows)
    assert len(events) == 5
    assert all(item["decision_at"] != "2022-01-03T13:50:00Z" for item in events)


def test_direction_mirror_preserves_classes_and_flips_every_direction() -> None:
    source = _fixture()
    state_map = {
        "BUYER_CONTROL": "SELLER_CONTROL",
        "SELLER_CONTROL": "BUYER_CONTROL",
        "CONFLICTED": "CONFLICTED",
        "UNRESOLVED": "UNRESOLVED",
    }
    direction_map = {"LONG": "SHORT", "SHORT": "LONG"}
    mirrored = deepcopy(source)
    for row in mirrored:
        row["state"] = state_map[row["state"]]
        row["raw_state"] = state_map[row["raw_state"]]
        for key in ("m5_event", "m15_event"):
            if row[key] is not None:
                row[key]["direction"] = direction_map[row[key]["direction"]]
        row["observation_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "observation_sha256"}
        )
    original_events = enumerate_transition_observations(source)
    mirror_events = enumerate_transition_observations(mirrored)
    assert [item["event_class"] for item in original_events] == [
        item["event_class"] for item in mirror_events
    ]
    assert [direction_map[item["direction"]] for item in original_events] == [
        item["direction"] for item in mirror_events
    ]


def test_sanitized_break_drops_future_invalidation_metadata() -> None:
    sanitized = _sanitized_break(
        _break("A", "LONG", "2022-01-03T13:05:00Z", "M5")
    )
    assert sanitized is not None
    assert "invalidated_at" not in sanitized
    _assert_outcome_blind(sanitized)


def test_outcome_blind_guard_rejects_nested_performance_fields() -> None:
    try:
        _assert_outcome_blind({"safe": {"net_r": 2.0}})
    except RuntimeError as exc:
        assert "Forbidden outcome field" in str(exc)
    else:
        raise AssertionError("Outcome-blind guard accepted a performance field")
