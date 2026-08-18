from __future__ import annotations

import hashlib
import json
from bisect import bisect_right
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo

AUDIT_VERSION = "GOLD_CASEBOOK_COVERAGE_V0_1"
HOLDOUT_START = datetime(2025, 1, 1, tzinfo=UTC)

TOKYO = ZoneInfo("Asia/Tokyo")
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")


@dataclass(frozen=True, slots=True)
class SessionWindow:
    code: str
    timezone: ZoneInfo
    start: time
    end: time


WINDOWS = (
    SessionWindow("ASIA", TOKYO, time(10, 5), time(16, 0)),
    SessionWindow("LONDON", LONDON, time(8, 0), time(12, 0)),
    SessionWindow("NEW_YORK", NEW_YORK, time(8, 0), time(12, 0)),
)


def validate_development_period(start: datetime, end: datetime) -> None:
    if start.tzinfo is None or end.tzinfo is None:
        raise ValueError("start and end must be timezone-aware")
    if start >= end:
        raise ValueError("start must precede end")
    if end > HOLDOUT_START:
        raise ValueError("The locked 2025 holdout must not be loaded")


def audit_session_windows(
    five_minute_open_times: Iterable[datetime],
    *,
    start: datetime,
    end: datetime,
) -> tuple[dict[str, Any], dict[str, tuple[datetime, ...]]]:
    validate_development_period(start, end)
    available = {item.astimezone(UTC) for item in five_minute_open_times}
    first_date = start.astimezone(LONDON).date()
    last_date = end.astimezone(LONDON).date()
    counters: dict[str, dict[str, int]] = defaultdict(_empty_session_counts)
    missing: dict[str, list[str]] = defaultdict(list)
    decisions: dict[str, list[datetime]] = {"LONDON": [], "NEW_YORK": []}

    current = first_date
    while current <= last_date:
        london_anchor = _local_datetime(current, time(8, 0), LONDON).astimezone(UTC)
        if current.weekday() < 5 and start <= london_anchor < end:
            year = str(current.year)
            _increment(counters["all"], "requested_weekdays")
            _increment(counters[year], "requested_weekdays")
            complete = {
                spec.code: _window_complete(available, session_date=current, spec=spec)
                for spec in WINDOWS
            }
            for code, is_complete in complete.items():
                if is_complete:
                    _increment(counters["all"], f"{code.lower()}_complete")
                    _increment(counters[year], f"{code.lower()}_complete")
                else:
                    missing[code].append(current.isoformat())

            london_case_complete = complete["ASIA"] and complete["LONDON"]
            new_york_case_complete = london_case_complete and complete["NEW_YORK"]
            if london_case_complete:
                _increment(counters["all"], "london_case_complete")
                _increment(counters[year], "london_case_complete")
                decisions["LONDON"].append(
                    _local_datetime(current, time(7, 55), LONDON).astimezone(UTC)
                )
            else:
                missing["LONDON_CASE"].append(current.isoformat())
            if new_york_case_complete:
                _increment(counters["all"], "new_york_case_complete")
                _increment(counters[year], "new_york_case_complete")
                decisions["NEW_YORK"].append(
                    _local_datetime(current, time(7, 55), NEW_YORK).astimezone(UTC)
                )
            else:
                missing["NEW_YORK_CASE"].append(current.isoformat())
        current += timedelta(days=1)

    for bucket in counters.values():
        requested = bucket["requested_weekdays"]
        for key in (
            "asia_complete",
            "london_complete",
            "new_york_complete",
            "london_case_complete",
            "new_york_case_complete",
        ):
            bucket[f"{key}_pct"] = _percentage(bucket[key], requested)

    return (
        {
            "definition": {
                "source_resolution": "complete point-in-time 5-minute buckets",
                "asia": "10:05-16:00 Asia/Tokyo",
                "london": "08:00-12:00 Europe/London",
                "new_york": "08:00-12:00 America/New_York",
                "london_coverage_probe": "07:55 Europe/London",
                "new_york_coverage_probe": "07:55 America/New_York",
                "coverage_probes_are_execution_manifest": False,
                "weekday_note": (
                    "Requested weekdays include exchange holidays; an incomplete "
                    "holiday is recorded, not silently synthesized."
                ),
            },
            "counts": {
                key: dict(value)
                for key, value in sorted(
                    counters.items(),
                    key=lambda item: (item[0] != "all", item[0]),
                )
            },
            "missing_dates": dict(sorted(missing.items())),
        },
        {key: tuple(value) for key, value in decisions.items()},
    )


def eligible_record_coverage(
    decision_times: Sequence[datetime],
    records: Sequence[tuple[datetime, str]],
) -> dict[str, Any]:
    ordered_records = sorted(
        (available_at.astimezone(UTC), key) for available_at, key in records
    )
    available_times = [item[0] for item in ordered_records]
    eligible_sessions = 0
    used_keys: set[str] = set()
    for decision_at in sorted(item.astimezone(UTC) for item in decision_times):
        index = bisect_right(available_times, decision_at) - 1
        if index >= 0:
            eligible_sessions += 1
            used_keys.add(ordered_records[index][1])
    return {
        "session_count": len(decision_times),
        "eligible_sessions": eligible_sessions,
        "eligible_pct": _percentage(eligible_sessions, len(decision_times)),
        "effective_distinct_records": len(used_keys),
    }


def build_field_registry(
    *,
    session_coverage: Mapping[str, Any],
    series_eligibility: Mapping[str, Mapping[str, Mapping[str, Any]]],
    price_sources: Sequence[Mapping[str, Any]],
    cot_reports: Sequence[Mapping[str, Any]],
    event_summary: Mapping[str, Any],
    policy_summary: Mapping[str, Any],
    cme_summary: Mapping[str, Any],
) -> list[dict[str, Any]]:
    all_sessions = session_coverage["counts"]["all"]
    price_by_instrument = {
        str(item["instrument_code"]): item for item in price_sources
    }

    fields: list[dict[str, Any]] = []

    def add(
        code: str,
        group: str,
        status: str,
        source: str,
        evidence: str,
    ) -> None:
        fields.append(
            {
                "code": code,
                "group": group,
                "status": status,
                "source": source,
                "evidence": evidence,
            }
        )

    xau = price_by_instrument.get("XAUUSD")
    add(
        "xauusd_ohlc_1m",
        "PRICE_SESSION",
        "AVAILABLE" if xau else "MISSING",
        "IC_MARKETS_MT5",
        f"{xau['rows']} complete rows" if xau else "No observed rows",
    )
    add(
        "observed_broker_spread",
        "PRICE_SESSION",
        "AVAILABLE" if xau and xau["spread_rows"] == xau["rows"] else "PARTIAL",
        "IC_MARKETS_MT5",
        f"{xau['spread_rows'] if xau else 0} rows with spread",
    )
    add(
        "broker_tick_activity",
        "PRICE_SESSION",
        "AVAILABLE" if xau and xau["volume_rows"] == xau["rows"] else "PARTIAL",
        "IC_MARKETS_MT5",
        "Broker tick activity; not centralized COMEX volume",
    )
    add(
        "complete_asia_london_new_york_sessions",
        "PRICE_SESSION",
        "AVAILABLE" if all_sessions["new_york_case_complete"] else "MISSING",
        "IC_MARKETS_MT5",
        (
            f"{all_sessions['new_york_case_complete']} of "
            f"{all_sessions['requested_weekdays']} requested weekdays"
        ),
    )

    structure_fields = (
        "swings_hh_hl_lh_ll",
        "support_resistance",
        "break_of_structure",
        "market_structure_shift",
        "compression_expansion",
        "displacement_momentum",
        "acceptance_rejection",
        "failed_trapped_breakout",
        "retests",
        "session_and_prior_day_week_levels",
    )
    for code in structure_fields:
        add(
            code,
            "MARKET_STRUCTURE",
            "DERIVABLE_PENDING_CASEBOOK",
            "XAUUSD bars + deterministic structure engine",
            "Source bars are present; immutable case fields are milestone 2",
        )

    for series_code in sorted(series_eligibility):
        london = series_eligibility[series_code]["LONDON"]
        new_york = series_eligibility[series_code]["NEW_YORK"]
        minimum = min(london["eligible_pct"], new_york["eligible_pct"])
        status = "AVAILABLE" if minimum >= 95 else "PARTIAL" if minimum > 0 else "MISSING"
        add(
            series_code.lower(),
            "FUNDAMENTALS",
            status,
            "FRED_PUBLIC / ALFRED_OFFICIAL",
            (
                f"eligible at {london['eligible_pct']}% London and "
                f"{new_york['eligible_pct']}% New York coverage probes"
            ),
        )

    cot_count = sum(int(item["effective_observations"]) for item in cot_reports)
    add(
        "cot_raw_positioning",
        "POSITIONING",
        "AVAILABLE" if cot_count else "MISSING",
        "CFTC_PUBLIC",
        f"{cot_count} unique pre-2025 observation dates",
    )
    for code in (
        "cot_net_and_weekly_change",
        "cot_historical_percentile",
        "cot_crowding_and_divergence",
    ):
        add(
            code,
            "POSITIONING",
            "DERIVABLE_PENDING_CASEBOOK",
            "CFTC_PUBLIC",
            "Raw reports are available; derived point-in-time fields are milestone 2",
        )

    add(
        "historical_event_actuals",
        "EVENTS",
        "AVAILABLE" if event_summary["release_components"] else "MISSING",
        "METAQUOTES_MT5_CALENDAR",
        f"{event_summary['release_components']} release components",
    )
    add(
        "historical_pre_event_schedule",
        "EVENTS",
        "MISSING",
        "METAQUOTES_MT5_CALENDAR",
        "Historical schedule first-publication times are not verified",
    )
    add(
        "historical_pre_event_consensus",
        "EVENTS",
        (
            "AVAILABLE"
            if event_summary["pre_event_allowed_forecasts"]
            else "POST_RELEASE_ONLY"
        ),
        "METAQUOTES_MT5_CONSENSUS",
        (
            f"{event_summary['pre_event_allowed_forecasts']} of "
            f"{event_summary['forecast_rows']} rows allow pre-event use"
        ),
    )
    add(
        "post_release_surprise",
        "EVENTS",
        "DERIVABLE_PENDING_CASEBOOK",
        "METAQUOTES_MT5_CALENDAR",
        "Actual and release-boundary consensus can be joined after release",
    )
    add(
        "unscheduled_event_metadata",
        "EVENTS",
        "MISSING",
        "No licensed historical news source",
        "Must remain UNKNOWN in the initial casebook",
    )

    for instrument in ("EURUSD", "XAGUSD", "US500"):
        item = price_by_instrument.get(instrument)
        status = "AVAILABLE"
        if not item:
            status = "MISSING"
        elif str(item["last_open"]) < "2024-12-01":
            status = "PARTIAL"
        add(
            f"{instrument.lower()}_intraday",
            "CROSS_MARKET",
            status,
            "IC_MARKETS_MT5",
            (
                f"{item['rows']} rows, {item['first_open']} to {item['last_open']}"
                if item
                else "No observed rows"
            ),
        )
    for symbol in ("ZT.v.0", "ZN.v.0", "ZQ.v.0", "SR3.v.0"):
        symbol_summary = cme_summary.get("symbols", {}).get(symbol)
        add(
            f"{symbol.split('.')[0].lower()}_intraday",
            "CROSS_MARKET",
            "AVAILABLE" if symbol_summary else "MISSING",
            "DATABENTO_GLBX_MDP3",
            (
                f"{symbol_summary['rows']} rows, "
                f"{symbol_summary['first_open']} to {symbol_summary['last_open']}"
                if symbol_summary
                else "No normalized rows"
            ),
        )
    add(
        "fed_expectation_windows",
        "EXPECTATIONS",
        "PARTIAL" if policy_summary.get("rows") else "MISSING",
        "ATLANTA_FED_MPT",
        (
            f"{policy_summary.get('effective_observations', 0)} observation dates; "
            "quarterly windows, not exact meeting-level FedWatch"
        ),
    )
    add(
        "centralized_comex_gold_volume_open_interest",
        "POSITIONING",
        "PARTIAL",
        "CFTC weekly open interest only",
        "No centralized intraday GC volume/open-interest series",
    )
    return fields


def add_deterministic_hash(report: dict[str, Any]) -> str:
    content = {
        key: value
        for key, value in report.items()
        if key not in {"generated_at", "data_hash"}
    }
    digest = hashlib.sha256(
        json.dumps(content, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    report["data_hash"] = digest
    return digest


def _window_complete(
    available: set[datetime],
    *,
    session_date: date,
    spec: SessionWindow,
) -> bool:
    start = _local_datetime(session_date, spec.start, spec.timezone).astimezone(UTC)
    end_date = session_date + timedelta(days=1) if spec.end <= spec.start else session_date
    end = _local_datetime(end_date, spec.end, spec.timezone).astimezone(UTC)
    expected = int((end - start).total_seconds() // 300)
    return all(
        start + timedelta(minutes=offset * 5) in available
        for offset in range(expected)
    )


def _local_datetime(
    session_date: date,
    local_time: time,
    timezone: ZoneInfo,
) -> datetime:
    return datetime.combine(session_date, local_time, tzinfo=timezone)


def _empty_session_counts() -> dict[str, int]:
    return {
        "requested_weekdays": 0,
        "asia_complete": 0,
        "london_complete": 0,
        "new_york_complete": 0,
        "london_case_complete": 0,
        "new_york_case_complete": 0,
    }


def _increment(bucket: dict[str, int], key: str) -> None:
    bucket[key] += 1


def _percentage(numerator: int, denominator: int) -> float:
    return round(100 * numerator / denominator, 4) if denominator else 0.0
