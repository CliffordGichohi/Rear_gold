from __future__ import annotations

import importlib.util
from datetime import datetime, timedelta, timezone
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "tools/diagnose_multi_asset_session_behaviour_archetype_monetization_v1_m1_r1.py"
SPEC = importlib.util.spec_from_file_location("msbam_m1_r1", MODULE_PATH)
assert SPEC and SPEC.loader
module = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(module)


def test_maximal_run_implementations_match() -> None:
    present = {100, 101, 104, 108, 109}
    missing = [minute for minute in range(100, 110) if minute not in present]
    assert module.maximal_runs(missing) == [(102, 104), (105, 108)]
    assert module.maximal_runs_reference(100, 110, present) == [(102, 104), (105, 108)]


def test_current_schedule_shape_uses_server_clock() -> None:
    evidence = module.load(module.SCHEDULE_EVIDENCE) if module.SCHEDULE_EVIDENCE.exists() else {
        "current_documented_closed_minute_ranges_server_time": {
            "XAGUSD": [{"start": "23:59", "end_exclusive": "01:02", "crosses_midnight": True}],
        }
    }
    closed = int(datetime(2024, 1, 2, 22, 0, tzinfo=timezone.utc).timestamp() // 60)
    open_minute = int(datetime(2024, 1, 2, 12, 0, tzinfo=timezone.utc).timestamp() // 60)
    assert module.current_schedule_shape("XAGUSD", closed, closed + 1, evidence) == "ENTIRELY_CURRENT_DOCUMENTED_CLOSURE"
    assert module.current_schedule_shape("XAGUSD", open_minute, open_minute + 1, evidence) == "CURRENT_DOCUMENTED_TRADING_TIME"


def make_identity(index: int, start: datetime, instrument: str = "EURUSD", session: str = "ASIA_SESSION") -> dict[str, object]:
    observation_start = start
    observation_end = start + timedelta(minutes=5)
    return {
        "case_id": f"synthetic-{instrument}-{index}",
        "instrument": instrument,
        "research_id": instrument,
        "session_code": session,
        "session_date_local": start.date().isoformat(),
        "timezone": "UTC",
        "observation_start_utc": observation_start.isoformat().replace("+00:00", "Z"),
        "observation_end_utc": observation_end.isoformat().replace("+00:00", "Z"),
    }


def test_isolated_low_recurrence_gap_is_no_tick_disposition() -> None:
    evidence = module.load(module.SCHEDULE_EVIDENCE) if module.SCHEDULE_EVIDENCE.exists() else {
        "current_documented_closed_minute_ranges_server_time": {
            "EURUSD": [{"start": "23:59", "end_exclusive": "00:01", "crosses_midnight": True}],
        }
    }
    identities = [make_identity(index, datetime(2024, 1, 2 + index, 12, 0, tzinfo=timezone.utc)) for index in range(20)]
    all_minutes: set[int] = set()
    for identity in identities:
        start = module.timestamp_from_raw(str(identity["observation_start_utc"]))
        end = module.timestamp_from_raw(str(identity["observation_end_utc"]))
        all_minutes.update(range(start - 1, end + 1))
    timestamps = {symbol: set(all_minutes) for symbol in module.SYMBOLS}
    first_start = module.timestamp_from_raw(str(identities[0]["observation_start_utc"]))
    timestamps["EURUSD"].remove(first_start + 2)
    base = module.extract_primary(identities, timestamps, evidence)
    rows = module.enrich_and_classify(base, identities, {symbol: [] for symbol in module.SYMBOLS})
    assert len(rows) == 1
    assert rows[0]["classification"] == "NORMAL_NO_TICK_BAR_EMISSION"


def test_frozen_unit_sets_cover_all_fifteen_units() -> None:
    assert len(module.TARGET_UNITS) == 5
    assert len(module.CONTROL_UNITS) == 10
    assert not (module.TARGET_UNITS & module.CONTROL_UNITS)
    assert len(module.TARGET_UNITS | module.CONTROL_UNITS) == 15


if __name__ == "__main__":
    test_maximal_run_implementations_match()
    test_current_schedule_shape_uses_server_clock()
    test_isolated_low_recurrence_gap_is_no_tick_disposition()
    test_frozen_unit_sets_cover_all_fifteen_units()
    print("4 Multi-Asset Session Behaviour Milestone 1-R1 preaccess tests passed")
