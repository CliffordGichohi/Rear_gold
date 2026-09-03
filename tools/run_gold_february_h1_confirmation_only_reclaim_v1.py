#!/usr/bin/env python3
"""Apply the sealed confirmation-only H1 policy to calendar February 2022."""

from __future__ import annotations

import csv
import gzip
import json
import math
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

import materialize_gold_blind_discretionary_replay_v1 as replay_source  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    confirmed_swings,
    iso,
    parse_dt,
)
from run_gold_january_h1_confirmation_only_reclaim_v2 import (  # noqa: E402
    V1_NET_R,
    confirmation_precedes_h1_breach,
    execution_metrics,
    first_confirmation,
    h1_breached,
    latest_control,
    valid_geometry,
)
from run_gold_january_h1_probe_confirm_reclaim_v1 import (  # noqa: E402
    CONTROL_NET_R,
    RECOVERY_BUFFER,
    signed_move,
    target_multiple,
)

SPEC = ROOT / "GOLD_FEBRUARY_2022_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1.md"
CASEBOOK = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"
CASEBOOK_MANIFEST = ROOT / "research_artifacts/gold_casebook_v01/manifest.json"
JAN_V2_RESULT = ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2/result.json"
JAN_V2_MANIFEST = ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2/manifest.json"
JAN_V2_SPEC = ROOT / "GOLD_JANUARY_H1_CONFIRMATION_ONLY_RECLAIM_MILESTONE_V2.md"
OUT = ROOT / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1"
COVERAGE = OUT / "source_coverage_and_january_equivalence.json"
RESULT = OUT / "result.json"
LEDGER = OUT / "february_case_ledger.csv"
CHART_DATA = OUT / "february_chart_data.json"
REPORT = OUT / "report.md"
MANIFEST = OUT / "manifest.json"

HISTORY_START = parse_dt("2021-07-23T00:00:00Z")
JAN_START = parse_dt("2022-01-01T00:00:00Z")
FEB_START = parse_dt("2022-02-01T00:00:00Z")
EXPOSURE_SPLIT = parse_dt("2022-02-17T00:00:00Z")
FEB_END = parse_dt("2022-03-01T00:00:00Z")
CONFIRM_CUTOFF = parse_dt("2022-03-03T00:00:00Z")
DISPLAY_TIMEFRAMES = ("1h", "15m", "5m")
REQUIRED_TIMEFRAMES = ("1m", *DISPLAY_TIMEFRAMES)


def verify_file_in_manifest(manifest_path: Path, required: Path) -> str:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    matches = [
        row for row in manifest["files"]
        if (ROOT / str(row["path"])).resolve() == required.resolve()
    ]
    require(len(matches) == 1, f"Manifest binding absent or ambiguous: {required}")
    actual = sha256_file(required)
    require(actual == str(matches[0]["sha256"]), f"Manifest hash differs: {required}")
    return actual


def verify_sources() -> dict[str, str]:
    for path in (SPEC, CASEBOOK, CASEBOOK_MANIFEST, JAN_V2_RESULT, JAN_V2_MANIFEST, JAN_V2_SPEC):
        require(path.is_file(), f"Required source absent: {path}")
    casebook_manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    source_rows = [row for row in casebook_manifest["artifacts"] if row["name"] == CASEBOOK.name]
    require(len(source_rows) == 1, "Casebook price source binding is ambiguous")
    casebook_sha = sha256_file(CASEBOOK)
    require(casebook_sha == str(source_rows[0]["sha256"]), "Casebook price source seal mismatch")
    require(casebook_manifest["contract"]["case_end_exclusive"] == "2025-01-01T00:00:00+00:00", "Casebook end changed")
    jan_v2_sha = verify_file_in_manifest(JAN_V2_MANIFEST, JAN_V2_RESULT)
    jan_v2_spec_sha = verify_file_in_manifest(JAN_V2_MANIFEST, JAN_V2_SPEC)
    jan_v2 = json.loads(JAN_V2_RESULT.read_text(encoding="utf-8"))
    require(jan_v2["primary_reference_exact"] is True, "January V2 did not reproduce")
    return {
        "casebook_sha256": casebook_sha,
        "casebook_manifest_sha256": sha256_file(CASEBOOK_MANIFEST),
        "january_v2_result_sha256": jan_v2_sha,
        "january_v2_spec_sha256": jan_v2_spec_sha,
    }


def canonical_bar(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "open_at": iso(str(row["open_time"])),
        "close_at": iso(str(row["close_time"])),
        "available_at": iso(str(row["available_at"])),
        "open": float(row["open"]),
        "high": float(row["high"]),
        "low": float(row["low"]),
        "close": float(row["close"]),
        "volume": None if row.get("volume") is None else float(row["volume"]),
        "spread_price": None if row.get("spread_price") is None else float(row["spread_price"]),
        "complete": bool(row["complete"]),
        "timeframe": str(row["timeframe"]),
    }


def load_casebook(parser: Callable[[str], dict[str, Any]]) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in REQUIRED_TIMEFRAMES}
    source_counts = Counter()
    with gzip.open(CASEBOOK, "rt", encoding="utf-8") as handle:
        for line in handle:
            parsed = parser(line)
            timeframe = str(parsed["timeframe"])
            if timeframe not in rows or not bool(parsed["complete"]):
                continue
            opened = parse_dt(str(parsed["open_time"]))
            available = parse_dt(str(parsed["available_at"]))
            include = False
            if timeframe in {"5m", "1h"}:
                include = opened >= HISTORY_START and available <= CONFIRM_CUTOFF
            elif timeframe == "1m":
                include = opened >= JAN_START and available <= FEB_END
            elif timeframe == "15m":
                include = opened >= FEB_START and available <= FEB_END
            if not include:
                continue
            rows[timeframe].append(canonical_bar(parsed))
            source_counts[timeframe] += 1
    diagnostics: dict[str, Any] = {}
    for timeframe, values in rows.items():
        values.sort(key=lambda row: (parse_dt(str(row["open_at"])), parse_dt(str(row["available_at"]))))
        require(values, f"No selected casebook rows for {timeframe}")
        identities = [(str(row["open_at"]), str(row["available_at"])) for row in values]
        require(len(identities) == len(set(identities)), f"Duplicate selected {timeframe} bars")
        diagnostics[timeframe] = {
            "rows": len(values),
            "first_open_at": str(values[0]["open_at"]),
            "last_available_at": str(values[-1]["available_at"]),
            "rows_sha256": canonical_hash(values),
        }
    feb_m1 = [row for row in rows["1m"] if FEB_START <= parse_dt(str(row["open_at"])) and parse_dt(str(row["available_at"])) <= FEB_END]
    expected_first = parse_dt("2022-02-01T01:02:00Z")
    expected_last_open = parse_dt("2022-02-28T23:58:00Z")
    require(feb_m1 and parse_dt(str(feb_m1[0]["open_at"])) == expected_first, "February M1 opening coverage differs")
    require(parse_dt(str(feb_m1[-1]["open_at"])) == expected_last_open, "February M1 terminal coverage differs")
    observed_dates = sorted({parse_dt(str(row["open_at"])).date() for row in feb_m1})
    require(len(observed_dates) == 20, "February trading-date count differs")
    for observed_date in observed_dates:
        daily = [row for row in feb_m1 if parse_dt(str(row["open_at"])).date() == observed_date]
        require(
            parse_dt(str(daily[0]["open_at"])).strftime("%H:%M") == "01:02",
            f"February daily observed-quote reopening differs: {observed_date}",
        )
    diagnostics["february_m1"] = {
        "rows": len(feb_m1),
        "first_open_at": str(feb_m1[0]["open_at"]),
        "last_available_at": str(feb_m1[-1]["available_at"]),
        "trading_dates": len(observed_dates),
        "daily_reopen_utc": "01:02",
        "closed_intervals_imputed": False,
        "rows_sha256": canonical_hash(feb_m1),
    }
    return rows, diagnostics


def resolve_control(
    future: Sequence[Mapping[str, Any]], *, entry: float, stop: float, target: float, direction: str
) -> dict[str, Any]:
    for row in future:
        stop_hit = float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if stop_hit:
            return {
                "outcome": "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP",
                "resolution_at": iso(str(row["open_at"])),
                "realized_r": -1.0,
            }
        if target_hit:
            return {
                "outcome": "TARGET",
                "resolution_at": iso(str(row["open_at"])),
                "realized_r": abs(target - entry) / abs(entry - stop),
            }
    final = future[-1]
    move = float(final["close"]) - entry if direction == "LONG" else entry - float(final["close"])
    return {
        "outcome": "TIME_EXIT",
        "resolution_at": iso(str(final["open_at"])),
        "realized_r": move / abs(entry - stop),
    }


def first_m1_at_or_after(
    rows: Sequence[Mapping[str, Any]], point: datetime, *, end: datetime
) -> Mapping[str, Any] | None:
    """Month-parameterized equivalent of the sealed January helper."""
    for row in rows:
        if (
            row.get("complete") is True
            and parse_dt(str(row["open_at"])) >= point
            and parse_dt(str(row["available_at"])) <= end
        ):
            return row
    return None


def first_target_after(
    rows: Sequence[Mapping[str, Any]],
    *,
    after: datetime,
    direction: str,
    target: float,
    end: datetime,
) -> datetime | None:
    """Month-parameterized equivalent of the sealed January helper."""
    for row in rows:
        opened = parse_dt(str(row["open_at"]))
        if opened <= after or parse_dt(str(row["available_at"])) > end:
            continue
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if target_hit:
            return opened
    return None


def first_h1_after(
    rows: Sequence[Mapping[str, Any]], point: datetime, *, end: datetime
) -> Mapping[str, Any] | None:
    """Month-parameterized equivalent of the sealed January helper."""
    eligible = [
        row
        for row in rows
        if (
            row.get("complete") is True
            and parse_dt(str(row["available_at"])) > point
            and parse_dt(str(row["available_at"])) <= end
        )
    ]
    return min(eligible, key=lambda row: parse_dt(str(row["available_at"]))) if eligible else None


def first_h1_breach_after(
    rows: Sequence[Mapping[str, Any]],
    *,
    after: datetime,
    swing: float,
    direction: str,
    end: datetime,
) -> datetime | None:
    """Month-parameterized equivalent of the sealed January helper."""
    for row in rows:
        available = parse_dt(str(row["available_at"]))
        if row.get("complete") is not True or available <= after or available > end:
            continue
        if h1_breached(float(row["close"]), swing, direction):
            return available
    return None


def resolve_path(
    rows: Sequence[Mapping[str, Any]],
    *,
    entry_at: datetime,
    entry: float,
    stop: float,
    target: float,
    direction: str,
    end: datetime,
) -> dict[str, Any]:
    """Month-parameterized equivalent of the sealed January helper."""
    eligible = [
        row
        for row in rows
        if (
            row.get("complete") is True
            and parse_dt(str(row["open_at"])) >= entry_at
            and parse_dt(str(row["available_at"])) <= end
        )
    ]
    require(eligible, f"No M1 recovery path at {iso(entry_at)}")
    for row in eligible:
        stop_hit = float(row["low"]) <= stop if direction == "LONG" else float(row["high"]) >= stop
        target_hit = float(row["high"]) >= target if direction == "LONG" else float(row["low"]) <= target
        if stop_hit:
            return {
                "outcome": "STOP_FIRST_AMBIGUOUS" if target_hit else "STOP",
                "at": iso(str(row["open_at"])),
                "raw_r": -1.0,
            }
        if target_hit:
            return {
                "outcome": "TARGET",
                "at": iso(str(row["open_at"])),
                "raw_r": target_multiple(entry, stop, target),
            }
    final = eligible[-1]
    return {
        "outcome": "TIME_EXIT",
        "at": iso(str(final["available_at"])),
        "raw_r": signed_move(entry, float(final["close"]), direction) / abs(entry - stop),
    }


def build_population(
    rows: Mapping[str, Sequence[Mapping[str, Any]]], *, start: datetime, end: datetime, cutoff: datetime
) -> dict[str, Any]:
    h1_rows = list(rows["1h"])
    m1_rows = list(rows["1m"])
    _, h1_swings = confirmed_swings(
        [row for row in h1_rows if parse_dt(str(row["open_at"])) < cutoff], cutoff, "H1"
    )
    monthly = [row for row in h1_swings if start <= parse_dt(str(row["pivot_at"])) < end]
    construction = Counter()
    outcomes = Counter()
    trades: list[dict[str, Any]] = []
    for swing in sorted(monthly, key=lambda row: (parse_dt(str(row["pivot_at"])), str(row["kind"]), str(row["identity"]))):
        decision = parse_dt(str(swing["detected_at"]))
        direction = "LONG" if str(swing["kind"]) == "LOW" else "SHORT"
        if decision >= end:
            construction["CONFIRMED_AFTER_MONTH"] += 1
            continue
        prior_opposite = [
            row for row in h1_swings
            if row["kind"] != swing["kind"]
            and parse_dt(str(row["pivot_at"])) < parse_dt(str(swing["pivot_at"]))
            and parse_dt(str(row["detected_at"])) <= decision
        ]
        if not prior_opposite:
            construction["NO_CAUSAL_TARGET"] += 1
            continue
        target_swing = max(prior_opposite, key=lambda row: parse_dt(str(row["pivot_at"])))
        future = [
            row for row in m1_rows
            if row.get("complete") is True
            and parse_dt(str(row["open_at"])) >= decision
            and parse_dt(str(row["available_at"])) <= end
        ]
        if not future:
            construction["NO_M1_PATH"] += 1
            continue
        entry = float(future[0]["open"])
        stop = float(swing["level"])
        target = float(target_swing["level"])
        if not valid_geometry(entry, stop, target, direction):
            construction["NON_EXECUTABLE_GEOMETRY"] += 1
            continue
        resolved = resolve_control(future, entry=entry, stop=stop, target=target, direction=direction)
        target_r = abs(target - entry) / abs(entry - stop)
        trade_id = canonical_hash(["H1_SWING_ROTATION", swing["identity"], iso(decision), entry, stop, target])
        trades.append({
            "trade_identity": trade_id,
            "source_swing_identity": str(swing["identity"]),
            "target_swing_identity": str(target_swing["identity"]),
            "pivot_at": iso(str(swing["pivot_at"])),
            "decision_at": iso(decision),
            "direction": direction,
            "entry": entry,
            "stop": stop,
            "target": target,
            "target_r": target_r,
            "outcome": str(resolved["outcome"]),
            "resolution_at": str(resolved["resolution_at"]),
            "realized_r": float(resolved["realized_r"]),
        })
        outcomes[str(resolved["outcome"])] += 1
    return {
        "local_h1_pivots": len(monthly),
        "construction_dispositions": dict(sorted(construction.items())),
        "control_outcome_counts": dict(sorted(outcomes.items())),
        "trades": trades,
    }


def apply_policy(
    trades: Sequence[Mapping[str, Any]], rows: Mapping[str, Sequence[Mapping[str, Any]]], *, end: datetime
) -> list[dict[str, Any]]:
    require(end == FEB_END or end == FEB_START, "Unexpected policy end")
    m1_rows = list(rows["1m"])
    h1_rows = list(rows["1h"])
    m5_rows = list(rows["5m"])
    cutoff = FEB_START if end == FEB_START else CONFIRM_CUTOFF
    _, m5_swings = confirmed_swings(
        [row for row in m5_rows if parse_dt(str(row["open_at"])) < cutoff], cutoff, "M5"
    )
    ledger: list[dict[str, Any]] = []
    for trade in sorted(trades, key=lambda row: (parse_dt(str(row["decision_at"])), str(row["trade_identity"]))):
        direction = str(trade["direction"])
        decision = parse_dt(str(trade["decision_at"]))
        boundary_at = parse_dt(str(trade["resolution_at"]))
        swing = float(trade["stop"])
        target = float(trade["target"])
        control = latest_control(m5_swings, decision, direction)
        confirmation = (
            first_confirmation(m5_rows, after=decision, through=boundary_at, direction=direction, control_level=float(control["level"]))
            if control is not None else None
        )
        entry_row = (
            first_m1_at_or_after(m1_rows, parse_dt(str(confirmation["available_at"])), end=end)
            if confirmation is not None else None
        )
        initial_valid = bool(
            entry_row is not None
            and parse_dt(str(entry_row["open_at"])) <= boundary_at
            and valid_geometry(float(entry_row["open"]), swing, target, direction)
        )
        executed = False
        route = ""
        entry_at: str | None = None
        entry_price: float | None = None
        filled_stop: float | None = None
        resolution_at: str | None = None
        outcome: str | None = None
        net_r = 0.0
        if initial_valid:
            executed = True
            entry_time = parse_dt(str(entry_row["open_at"]))
            entry_price = float(entry_row["open"])
            entry_at = iso(entry_time)
            filled_stop = swing
            resolved = resolve_path(
                m1_rows, entry_at=entry_time, entry=entry_price, stop=swing,
                target=target, direction=direction, end=end,
            )
            outcome, resolution_at, net_r = str(resolved["outcome"]), str(resolved["at"]), float(resolved["raw_r"])
            route = f"INITIAL_CONFIRMATION_{outcome}"
        elif str(trade["outcome"]) == "TARGET":
            route = "NO_TRADE_TARGET_BEFORE_CONFIRMATION" if confirmation is None else "NO_TRADE_INITIAL_GEOMETRY_INVALID"
        elif str(trade["outcome"]).startswith("STOP"):
            later_target_at = first_target_after(
                m1_rows, after=boundary_at, direction=direction, target=target, end=end
            )
            h1_review = first_h1_after(h1_rows, boundary_at, end=end)
            if h1_review is None:
                route = "NO_TRADE_NO_H1_REVIEW"
            else:
                review_time = parse_dt(str(h1_review["available_at"]))
                if later_target_at is not None and later_target_at < review_time:
                    route = "NO_TRADE_TARGET_BEFORE_H1_REVIEW"
                elif h1_breached(float(h1_review["close"]), swing, direction):
                    route = "NO_TRADE_H1_CLOSE_INVALIDATED"
                else:
                    recovery_control = latest_control(m5_swings, review_time, direction)
                    next_breach_at = first_h1_breach_after(
                        h1_rows, after=review_time, swing=swing, direction=direction, end=end
                    )
                    cancellation_points = [end]
                    if later_target_at is not None:
                        cancellation_points.append(later_target_at)
                    if next_breach_at is not None:
                        cancellation_points.append(next_breach_at)
                    deadline = min(cancellation_points)
                    recovery_confirmation = (
                        first_confirmation(
                            m5_rows, after=review_time, through=deadline, direction=direction,
                            control_level=float(recovery_control["level"]), required_valid_side=swing,
                        ) if recovery_control is not None else None
                    )
                    if recovery_confirmation is not None and not confirmation_precedes_h1_breach(
                        parse_dt(str(recovery_confirmation["available_at"])), next_breach_at
                    ):
                        recovery_confirmation = None
                    if recovery_control is None:
                        route = "NO_TRADE_NO_RECLAIM_CONTROL"
                    elif recovery_confirmation is None:
                        if later_target_at is not None and later_target_at <= deadline:
                            route = "NO_TRADE_TARGET_BEFORE_RECLAIM"
                        elif next_breach_at is not None and next_breach_at <= deadline:
                            route = "NO_TRADE_LATER_H1_INVALIDATED"
                        else:
                            route = "NO_TRADE_NO_RECLAIM_CONFIRMATION"
                    else:
                        confirmation_time = parse_dt(str(recovery_confirmation["available_at"]))
                        reclaim_entry_row = first_m1_at_or_after(m1_rows, confirmation_time, end=end)
                        require(reclaim_entry_row is not None, f"No reclaim M1 entry: {trade['trade_identity']}")
                        excursion = [
                            row for row in m1_rows
                            if row.get("complete") is True
                            and parse_dt(str(row["open_at"])) >= boundary_at
                            and parse_dt(str(row["available_at"])) <= confirmation_time
                        ]
                        require(excursion, f"No reclaim excursion: {trade['trade_identity']}")
                        reclaim_stop = (
                            min(float(row["low"]) for row in excursion) - RECOVERY_BUFFER
                            if direction == "LONG" else max(float(row["high"]) for row in excursion) + RECOVERY_BUFFER
                        )
                        reclaim_entry = float(reclaim_entry_row["open"])
                        if not valid_geometry(reclaim_entry, reclaim_stop, target, direction):
                            route = "NO_TRADE_RECLAIM_GEOMETRY_INVALID"
                        else:
                            executed = True
                            entry_time = parse_dt(str(reclaim_entry_row["open_at"]))
                            entry_at, entry_price, filled_stop = iso(entry_time), reclaim_entry, reclaim_stop
                            resolved = resolve_path(
                                m1_rows, entry_at=entry_time, entry=reclaim_entry, stop=reclaim_stop,
                                target=target, direction=direction, end=end,
                            )
                            outcome, resolution_at, net_r = str(resolved["outcome"]), str(resolved["at"]), float(resolved["raw_r"])
                            route = f"RECLAIM_CONFIRMATION_{outcome}"
        else:
            route = "NO_TRADE_MONTH_END_WITHOUT_CONFIRMATION" if confirmation is None else "NO_TRADE_INITIAL_GEOMETRY_INVALID"
        require(not executed or net_r >= -1.0000000001, f"Risk cap breached: {trade['trade_identity']}")
        ledger.append({
            "trade_identity": str(trade["trade_identity"]),
            "pivot_at": str(trade["pivot_at"]),
            "decision_at": str(trade["decision_at"]),
            "direction": direction,
            "control_outcome": str(trade["outcome"]),
            "control_r": float(trade["realized_r"]),
            "executed": executed,
            "route": route,
            "entry_at": entry_at,
            "entry_price": entry_price,
            "stop": filled_stop,
            "target": target,
            "outcome": outcome,
            "resolution_at": resolution_at,
            "net_r": net_r,
            "exposure_segment": "PREVIOUSLY_EXPOSED_FEB_01_16" if decision < EXPOSURE_SPLIT else "NEWLY_OPENED_FEB_17_28",
        })
    return ledger


def jan_equivalence(generated_population: Mapping[str, Any], generated_ledger: Sequence[Mapping[str, Any]], sealed: Mapping[str, Any]) -> dict[str, Any]:
    sealed_by_id = {str(row["trade_identity"]): row for row in sealed["case_ledger"]}
    require(len(generated_population["trades"]) == 88, "Casebook January population is not 88")
    require(set(sealed_by_id) == {str(row["trade_identity"]) for row in generated_ledger}, "January identities differ")
    fields = ("route", "executed", "entry_at", "filled_stop", "outcome", "resolution_at", "net_r")
    failures = []
    for row in generated_ledger:
        reference = sealed_by_id[str(row["trade_identity"])]
        mapped = {
            "route": row["route"], "executed": row["executed"], "entry_at": row["entry_at"],
            "filled_stop": row["stop"], "outcome": row["outcome"], "resolution_at": row["resolution_at"], "net_r": row["net_r"],
        }
        if any(mapped[field] != reference[field] for field in fields):
            failures.append(str(row["trade_identity"]))
    require(not failures, f"January V2 semantic equivalence failed for {len(failures)} cases")
    return {"population": 88, "fields": list(fields), "mismatches": 0, "exact": True}


def compact_bars(rows: Sequence[Mapping[str, Any]], timeframe: str) -> list[list[float | int]]:
    return [
        [
            int(parse_dt(str(row["open_at"])).timestamp()),
            round(float(row["open"]), 4), round(float(row["high"]), 4),
            round(float(row["low"]), 4), round(float(row["close"]), 4),
        ]
        for row in rows
        if str(row["timeframe"]) == timeframe and FEB_START <= parse_dt(str(row["open_at"])) and parse_dt(str(row["available_at"])) <= FEB_END
    ]


def run_side(parser: Callable[[str], dict[str, Any]], sealed_jan: Mapping[str, Any]) -> dict[str, Any]:
    rows, diagnostics = load_casebook(parser)
    jan_population = build_population(rows, start=JAN_START, end=FEB_START, cutoff=FEB_START)
    jan_ledger = apply_policy(jan_population["trades"], rows, end=FEB_START)
    equivalence = jan_equivalence(jan_population, jan_ledger, sealed_jan)
    feb_population = build_population(rows, start=FEB_START, end=FEB_END, cutoff=CONFIRM_CUTOFF)
    feb_ledger = apply_policy(feb_population["trades"], rows, end=FEB_END)
    segments = {}
    for name in ("PREVIOUSLY_EXPOSED_FEB_01_16", "NEWLY_OPENED_FEB_17_28"):
        subset = [row for row in feb_ledger if row["exposure_segment"] == name]
        segments[name] = execution_metrics(subset)
    return {
        "source_diagnostics": diagnostics,
        "january_equivalence": equivalence,
        "february_population": {key: value for key, value in feb_population.items() if key != "trades"},
        "february_control_metrics": execution_metrics([
            {"executed": True, "net_r": row["realized_r"]} for row in feb_population["trades"]
        ]),
        "february_v2_metrics": execution_metrics(feb_ledger),
        "february_segments": segments,
        "february_route_counts": dict(sorted(Counter(str(row["route"]) for row in feb_ledger).items())),
        "february_ledger": feb_ledger,
        "chart_bars": {"H1": compact_bars(rows["1h"], "1h"), "M15": compact_bars(rows["15m"], "15m"), "M5": compact_bars(rows["5m"], "5m")},
    }


def main() -> None:
    bindings = verify_sources()
    sealed_jan = json.loads(JAN_V2_RESULT.read_text(encoding="utf-8"))
    OUT.mkdir(parents=True, exist_ok=True)
    primary = run_side(replay_source.parse_price_primary, sealed_jan)
    reference = run_side(replay_source.parse_price_reference, sealed_jan)
    require(primary == reference, "Primary/reference February application differs")
    coverage = {
        "version": "GOLD_FEBRUARY_H1_CONFIRMATION_ONLY_SOURCE_CERTIFICATION_V1",
        "verdict": "PASS_CASEBOOK_READER_AND_JANUARY_V2_EQUIVALENCE",
        "bindings": bindings,
        "primary_reference_exact": True,
        "source_diagnostics": primary["source_diagnostics"],
        "january_v2_equivalence": primary["january_equivalence"],
    }
    coverage["coverage_sha256"] = canonical_hash(coverage)
    COVERAGE.write_text(json.dumps(coverage, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")

    result = {
        "version": "GOLD_FEBRUARY_2022_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1",
        "verdict": "COMPLETED_UNCHANGED_FEBRUARY_APPLICATION",
        "evidence_status": "EXPOSED_HISTORICAL_ROBUSTNESS_NOT_INDEPENDENT_VALIDATION",
        "period": {"start": iso(FEB_START), "end_exclusive": iso(FEB_END)},
        "exposure_split": iso(EXPOSURE_SPLIT),
        "population": primary["february_population"],
        "control_metrics": primary["february_control_metrics"],
        "v2_metrics": primary["february_v2_metrics"],
        "segments": primary["february_segments"],
        "route_counts": primary["february_route_counts"],
        "case_ledger": primary["february_ledger"],
        "primary_reference_exact": True,
        "january_semantic_equivalence_exact": True,
        "policy_retuned": False,
    }
    result["result_sha256"] = canonical_hash(result)
    RESULT.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    with LEDGER.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(result["case_ledger"][0].keys()), lineterminator="\n")
        writer.writeheader(); writer.writerows(result["case_ledger"])

    chart_trades = []
    for index, row in enumerate((row for row in result["case_ledger"] if row["executed"]), start=1):
        chart_trades.append({
            "number": index,
            "tradeIdentity": row["trade_identity"],
            "decision": int(parse_dt(str(row["decision_at"])).timestamp()),
            "entryTime": int(parse_dt(str(row["entry_at"])).timestamp()),
            "resolution": int(parse_dt(str(row["resolution_at"])).timestamp()),
            "direction": row["direction"], "route": row["route"], "outcome": row["outcome"],
            "entry": round(float(row["entry_price"]), 4), "stop": round(float(row["stop"]), 4),
            "target": round(float(row["target"]), 4), "netR": round(float(row["net_r"]), 6),
            "exposureSegment": row["exposure_segment"],
        })
    chart = {
        "version": "GOLD_FEBRUARY_H1_CONFIRMATION_ONLY_CONTINUOUS_CHART_V1",
        "period": result["period"], "bars": primary["chart_bars"], "trades": chart_trades,
        "summary": result["v2_metrics"], "dataSha256": None,
    }
    chart["dataSha256"] = canonical_hash({key: value for key, value in chart.items() if key != "dataSha256"})
    CHART_DATA.write_text(json.dumps(chart, separators=(",", ":"), allow_nan=False) + "\n", encoding="utf-8", newline="\n")

    c, v = result["control_metrics"], result["v2_metrics"]
    old, fresh = result["segments"]["PREVIOUSLY_EXPOSED_FEB_01_16"], result["segments"]["NEWLY_OPENED_FEB_17_28"]
    report = [
        "# February 2022 confirmation-only V2 application",
        "",
        f"**Verdict:** `{result['verdict']}`",
        "",
        "| View | Setups | Trades | Win rate | Net R | PF | Expectancy/trade | Max DD | $50/R | $100/R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| February original control | {c['setups']} | {c['executed_trades']} | {100*c['trade_win_rate']:.1f}% | {c['net_r']:+.2f} | {c['profit_factor']:.3f} | {c['expectancy_per_trade_r']:+.3f} | {c['maximum_drawdown_r']:.2f} | {c['net_r']*50:+.2f} | {c['net_r']*100:+.2f} |",
        f"| February V2 | {v['setups']} | {v['executed_trades']} | {100*v['trade_win_rate']:.1f}% | {v['net_r']:+.2f} | {v['profit_factor']:.3f} | {v['expectancy_per_trade_r']:+.3f} | {v['maximum_drawdown_r']:.2f} | {v['net_r']*50:+.2f} | {v['net_r']*100:+.2f} |",
        f"| Feb 1-16 previously exposed | {old['setups']} | {old['executed_trades']} | {100*old['trade_win_rate']:.1f}% | {old['net_r']:+.2f} | {old['profit_factor']:.3f} | {old['expectancy_per_trade_r']:+.3f} | {old['maximum_drawdown_r']:.2f} | {old['net_r']*50:+.2f} | {old['net_r']*100:+.2f} |",
        f"| Feb 17-28 newly opened | {fresh['setups']} | {fresh['executed_trades']} | {100*fresh['trade_win_rate']:.1f}% | {fresh['net_r']:+.2f} | {fresh['profit_factor']:.3f} | {fresh['expectancy_per_trade_r']:+.3f} | {fresh['maximum_drawdown_r']:.2f} | {fresh['net_r']*50:+.2f} | {fresh['net_r']*100:+.2f} |",
        "",
        "The V2 policy was unchanged. Results are gross before costs and overlap controls.",
    ]
    REPORT.write_text("\n".join(report) + "\n", encoding="utf-8", newline="\n")
    sealed = (SPEC, Path(__file__).resolve(), CASEBOOK_MANIFEST, JAN_V2_RESULT, COVERAGE, RESULT, LEDGER, CHART_DATA, REPORT)
    manifest = {
        "version": "GOLD_FEBRUARY_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1_MANIFEST",
        "verdict": result["verdict"], "result_sha256": result["result_sha256"],
        "primary_reference_exact": True, "january_semantic_equivalence_exact": True,
        "files": [
            {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}
            for path in sealed
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    MANIFEST.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({
        "verdict": result["verdict"], "population": result["population"], "control": c,
        "v2": v, "segments": result["segments"], "routes": result["route_counts"],
    }, indent=2))


if __name__ == "__main__":
    main()
