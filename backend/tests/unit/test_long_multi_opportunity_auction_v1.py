from __future__ import annotations

from gold_intel.analytics.long_multi_opportunity_auction_v1 import (
    non_overlapping,
    signal_episodes,
)


def checkpoint(minute: int, session: str = "NEW_YORK") -> dict[str, object]:
    return {
        "checkpoint_at": f"2022-01-03T13:{minute:02d}:00Z",
        "session": session,
    }


def test_signal_episode_does_not_repeat_while_probability_stays_high() -> None:
    rows = [checkpoint(index) for index in range(20)]
    result = signal_episodes(rows, [0.95] * 20, rearm_below_minutes=15)
    assert len(result) == 1
    assert result[0]["emission_reason"] == "THRESHOLD_REARM"


def test_signal_episode_rearms_only_after_full_fifteen_minutes() -> None:
    rows = [checkpoint(index) for index in range(18)]
    probabilities = [0.95] + [0.10] * 14 + [0.95, 0.10, 0.95]
    assert len(signal_episodes(rows, probabilities, rearm_below_minutes=15)) == 1

    probabilities = [0.95] + [0.10] * 15 + [0.95, 0.95]
    result = signal_episodes(rows, probabilities, rearm_below_minutes=15)
    assert len(result) == 2
    assert result[1]["checkpoint_at"] == "2022-01-03T13:16:00Z"


def test_new_structure_can_emit_without_probability_reset() -> None:
    rows = [checkpoint(index) for index in range(4)]
    result = signal_episodes(
        rows,
        [0.95] * 4,
        structure_identities=["A", "A", "B", "B"],
    )
    assert len(result) == 2
    assert result[1]["emission_reason"] == "NEW_M15_BULLISH_STRUCTURE"


def test_other_session_never_emits() -> None:
    result = signal_episodes(
        [checkpoint(0, "LONDON"), checkpoint(1)],
        [0.99, 0.99],
    )
    assert [row["checkpoint_at"] for row in result] == ["2022-01-03T13:01:00Z"]


def test_non_overlap_accepts_only_after_previous_resolution() -> None:
    opportunities = [
        {
            "signal_at": "2022-01-03T13:00:00Z",
            "result": {"executed": True, "final_at": "2022-01-03T13:30:00Z"},
        },
        {
            "signal_at": "2022-01-03T13:20:00Z",
            "result": {"executed": True, "final_at": "2022-01-03T13:40:00Z"},
        },
        {
            "signal_at": "2022-01-03T13:31:00Z",
            "result": {"executed": True, "final_at": "2022-01-03T14:00:00Z"},
        },
    ]
    accepted, audited = non_overlapping(opportunities)
    assert len(accepted) == 2
    assert [row["portfolio_disposition"] for row in audited] == [
        "ACCEPTED",
        "OVERLAP_EXISTING_POSITION",
        "ACCEPTED",
    ]
