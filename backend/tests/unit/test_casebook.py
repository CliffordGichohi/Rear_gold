from __future__ import annotations

from dataclasses import replace
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import pytest

from gold_intel.analytics.casebook import (
    CaseBar,
    KnownLevel,
    build_session_case_specs,
    compact_structure_evidence,
    finalize_record,
    level_interactions,
    summarize_window,
    validate_casebook_period,
)


def _bars(start: datetime, count: int, *, base: float = 2000.0) -> list[CaseBar]:
    return [
        CaseBar(
            open_time=start + timedelta(minutes=5 * index),
            close_time=start + timedelta(minutes=5 * (index + 1)),
            open=base,
            high=base + 1,
            low=base - 1,
            close=base,
            volume=10,
            spread=0.2,
            source_count=5,
            source_hash=f"source-{index}",
        )
        for index in range(count)
    ]


def test_casebook_rejects_loading_after_holdout_boundary() -> None:
    with pytest.raises(ValueError, match="locked 2025 holdout"):
        validate_casebook_period(
            datetime(2024, 1, 1, tzinfo=UTC),
            datetime(2025, 1, 2, tzinfo=UTC),
        )


def test_session_specs_use_session_open_as_decision_clock() -> None:
    session_date = date(2024, 7, 1)
    tokyo = ZoneInfo("Asia/Tokyo")
    london = ZoneInfo("Europe/London")
    new_york = ZoneInfo("America/New_York")
    bars = (
        _bars(
            datetime.combine(session_date, time(10, 5), tzinfo=tokyo).astimezone(UTC),
            71,
        )
        + _bars(
            datetime.combine(session_date, time(8), tzinfo=london).astimezone(UTC),
            48,
        )
        + _bars(
            datetime.combine(session_date, time(8), tzinfo=new_york).astimezone(UTC),
            48,
        )
    )

    specs = build_session_case_specs(
        bars,
        start=datetime(2024, 7, 1, tzinfo=UTC),
        end=datetime(2024, 7, 2, tzinfo=UTC),
    )

    assert [spec.session_code for spec in specs] == ["LONDON", "NEW_YORK"]
    assert specs[0].decision_at == datetime.combine(
        session_date, time(8), tzinfo=london
    ).astimezone(UTC)
    assert specs[1].decision_at == datetime.combine(
        session_date, time(8), tzinfo=new_york
    ).astimezone(UTC)


def test_window_summary_excludes_bars_not_known_by_cutoff() -> None:
    session_date = date(2024, 7, 1)
    london = ZoneInfo("Europe/London")
    start = datetime.combine(session_date, time(8), tzinfo=london).astimezone(UTC)
    specs = build_session_case_specs(
        _bars(
            datetime.combine(
                session_date,
                time(10, 5),
                tzinfo=ZoneInfo("Asia/Tokyo"),
            ).astimezone(UTC),
            71,
        )
        + _bars(start, 48)
        + _bars(
            datetime.combine(
                session_date,
                time(8),
                tzinfo=ZoneInfo("America/New_York"),
            ).astimezone(UTC),
            48,
        ),
        start=datetime(2024, 7, 1, tzinfo=UTC),
        end=datetime(2024, 7, 2, tzinfo=UTC),
    )
    london_window = specs[0].london

    summary = summarize_window(
        london_window,
        as_of=start + timedelta(minutes=15),
    )

    assert summary["status"] == "PARTIAL"
    assert summary["bar_count"] == 3
    assert summary["expected_bar_count_as_of"] == 3


def test_level_interaction_distinguishes_acceptance_and_failed_break() -> None:
    start = datetime(2024, 7, 1, 8, tzinfo=UTC)
    bars = _bars(start, 4)
    bars[0] = replace(bars[0], high=2002.0, close=2001.0)
    bars[1] = replace(bars[1], high=2002.0, close=2001.5)
    bars[2] = replace(bars[2], close=1999.5)
    level = KnownLevel(
        code="ASIA_HIGH",
        price=2000.5,
        side="UPPER",
        known_at=start,
        source_hash="asia",
    )

    result = level_interactions(
        bars,
        [level],
        decision_at=start,
        observation_end=start + timedelta(minutes=20),
    )

    assert result[0]["classification"] == "FAILED_ACCEPTED_BREAK"
    assert result[0]["accepted_at"] == start + timedelta(minutes=10)
    assert result[0]["returned_inside_at"] == start + timedelta(minutes=15)


def test_structure_evidence_compacts_source_identifiers_without_losing_trace() -> None:
    compacted = compact_structure_evidence(
        {"evidence": {"source_bar_ids": ["a", "b", "c"]}}
    )
    evidence = compacted["evidence"]
    assert evidence["source_bar_count"] == 3
    assert evidence["source_bar_first"] == "a"
    assert evidence["source_bar_last"] == "c"
    assert len(evidence["source_bar_ids_hash"]) == 64


def test_finalized_record_hash_is_stable_and_content_sensitive() -> None:
    first = finalize_record({"record_id": "A", "value": 1})
    second = finalize_record({"value": 1, "record_id": "A"})
    changed = finalize_record({"record_id": "A", "value": 2})
    assert first["record_hash"] == second["record_hash"]
    assert first["record_hash"] != changed["record_hash"]
