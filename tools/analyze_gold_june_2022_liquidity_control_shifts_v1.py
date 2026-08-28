#!/usr/bin/env python3
"""Describe point-in-time auction-control transfers in exposed June 2022.

This is a post-result diagnostic.  It does not modify the frozen LONG control,
fit thresholds, construct a SHORT strategy, or receive validation credit.
"""

from __future__ import annotations

import csv
import gzip
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Literal, Sequence
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    BREAK_BUFFER_ATR as ACTIVE_INVALIDATION_BUFFER_ATR,
    TICK_FLOOR,
    canonical_hash,
    complete_rows,
    confirmed_swings,
    event_is_active,
    iso,
    parse_dt,
    structural_breaks,
    true_ranges_and_atr,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    macro_state,
)


Direction = Literal["LONG", "SHORT"]
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")

SOURCE_DIR = ROOT / "research_artifacts" / "gold_frozen_long_control_june_2022_v1"
PRIMARY_STREAMS = SOURCE_DIR / "june_streams.primary.jsonl.gz"
REFERENCE_STREAMS = SOURCE_DIR / "june_streams.reference.jsonl.gz"
SOURCE_RESULT = SOURCE_DIR / "final_result.json"
SOURCE_SEAL = SOURCE_DIR / "final_seal.json"

OUT = ROOT / "research_artifacts" / "gold_june_2022_liquidity_control_shift_diagnostic_v1_r2"
RESULT = OUT / "result.json"
TRADE_CSV = OUT / "trade_diagnostic.csv"
SESSION_CSV = OUT / "session_shift_atlas.csv"
REPORT = ROOT / "GOLD_JUNE_2022_LIQUIDITY_CONTROL_SHIFT_DIAGNOSTIC_V1_R2_REPORT.md"

# These are inherited, non-fitted definitions from the already documented
# liquidity-shift work.  They are not selected from June outcomes.
BREAK_BUFFER_ATR = 0.05
M5_MINIMUM_RANGE_ATR = 0.80
M15_MINIMUM_RANGE_ATR = 0.90
MINIMUM_BODY_RATIO = 0.55
ACCEPTANCE_M5_CLOSES = 2
TICK_SIZE = 0.01


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def verify_source_chain() -> dict[str, Any]:
    seal = load_json(SOURCE_SEAL)
    require(
        seal.get("verdict") == "FAIL_JUNE_2022_EXPOSED_ROBUSTNESS",
        "Frozen June verdict differs",
    )
    for record in seal.get("files", []):
        path = ROOT / str(record["path"])
        require(path.is_file(), f"Sealed source missing: {path}")
        require(path.stat().st_size == int(record["bytes"]), f"Size differs: {path}")
        require(sha256_file(path) == str(record["sha256"]), f"Hash differs: {path}")
    return seal


def load_streams(path: Path) -> dict[str, dict[str, Any]]:
    streams: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            stream = json.loads(line)
            submitted = str(stream.pop("stream_sha256"))
            require(canonical_hash(stream) == submitted, "Stream payload hash differs")
            stream["stream_sha256"] = submitted
            alias = str(stream["case_alias"])
            require(alias not in streams, f"Duplicate stream: {alias}")
            streams[alias] = stream
    require(len(streams) == 22, "Expected 22 June streams")
    return streams


def strong_breaks(
    rows: Sequence[dict[str, Any]], cutoff: str, timeframe: Literal["M5", "M15"]
) -> list[dict[str, Any]]:
    minimum_range = M5_MINIMUM_RANGE_ATR if timeframe == "M5" else M15_MINIMUM_RANGE_ATR
    output: list[dict[str, Any]] = []
    for direction in ("LONG", "SHORT"):
        output.extend(
            structural_breaks(
                rows,
                cutoff,
                timeframe,
                direction,
                buffer_atr=BREAK_BUFFER_ATR,
                minimum_range_atr=minimum_range,
                minimum_body_ratio=MINIMUM_BODY_RATIO,
            )
        )
    ordered = sorted(
        output,
        key=lambda row: (
            parse_dt(row["break_at"]),
            str(row["direction"]),
            str(row["identity"]),
        ),
    )
    completed = complete_rows(rows, cutoff)
    for event in ordered:
        buffer = max(ACTIVE_INVALIDATION_BUFFER_ATR * float(event["atr"]), TICK_FLOOR)
        invalidated_at: str | None = None
        for bar in completed:
            if parse_dt(bar["available_at"]) <= parse_dt(event["break_at"]):
                continue
            invalid = (
                float(bar["close"]) < float(event["protected_level"]) - buffer
                if event["direction"] == "LONG"
                else float(bar["close"]) > float(event["protected_level"]) + buffer
            )
            if invalid:
                invalidated_at = iso(bar["available_at"])
                break
        event["invalidated_at"] = invalidated_at
    return ordered


def active_control(
    events: Sequence[dict[str, Any]], cutoff: datetime
) -> dict[str, Any] | None:
    active = [
        event
        for event in events
        if parse_dt(event["break_at"]) <= cutoff
        and (
            event["invalidated_at"] is None
            or cutoff < parse_dt(event["invalidated_at"])
        )
    ]
    return active[-1] if active else None


def control_label(event: dict[str, Any] | None) -> str:
    return str(event["direction"]) if event is not None else "UNRESOLVED"


def first_event(
    events: Sequence[dict[str, Any]],
    *,
    direction: Direction,
    after: datetime,
    before_or_at: datetime,
) -> dict[str, Any] | None:
    return next(
        (
            event
            for event in events
            if str(event["direction"]) == direction
            and after < parse_dt(event["break_at"]) <= before_or_at
        ),
        None,
    )


def session_bounds(calendar_day: date, session: str) -> tuple[datetime, datetime]:
    zone = LONDON if session == "LONDON" else NEW_YORK
    opened = datetime.combine(calendar_day, time(8, 0), tzinfo=zone)
    return opened.astimezone(UTC), (opened + timedelta(hours=4)).astimezone(UTC)


def sweep_reclaims(
    rows: Sequence[dict[str, Any]], cutoff: str, timeframe: Literal["M5", "M15"]
) -> list[dict[str, Any]]:
    bars, swings = confirmed_swings(rows, cutoff, timeframe)
    output: list[dict[str, Any]] = []
    for bar in bars:
        at = parse_dt(bar["available_at"])
        known = [swing for swing in swings if parse_dt(swing["detected_at"]) <= parse_dt(bar["open_at"])]
        highs = [swing for swing in known if swing["kind"] == "HIGH"]
        lows = [swing for swing in known if swing["kind"] == "LOW"]
        if highs:
            level = float(highs[-1]["level"])
            if float(bar["high"]) > level + TICK_SIZE and float(bar["close"]) < level:
                output.append(
                    {
                        "at": iso(at),
                        "direction": "SHORT",
                        "kind": "BUY_SIDE_SWEEP_RECLAIM",
                        "level": level,
                    }
                )
        if lows:
            level = float(lows[-1]["level"])
            if float(bar["low"]) < level - TICK_SIZE and float(bar["close"]) > level:
                output.append(
                    {
                        "at": iso(at),
                        "direction": "LONG",
                        "kind": "SELL_SIDE_SWEEP_RECLAIM",
                        "level": level,
                    }
                )
    return sorted(output, key=lambda row: (parse_dt(row["at"]), row["direction"]))


def latest_between(
    events: Sequence[dict[str, Any]], start: datetime, end: datetime
) -> dict[str, Any] | None:
    eligible = [event for event in events if start <= parse_dt(event["at"]) <= end]
    return eligible[-1] if eligible else None


def atr_at(rows: Sequence[dict[str, Any]], at: datetime) -> float | None:
    eligible = complete_rows(rows, at)
    if not eligible:
        return None
    _, atrs = true_ranges_and_atr(eligible)
    value = atrs[-1]
    return float(value) if value is not None and value > 0 else None


def next_m1_open(
    rows: Sequence[dict[str, Any]], after: datetime, end: datetime
) -> tuple[datetime, float] | None:
    for row in complete_rows(rows, end):
        opened = parse_dt(row["open_at"])
        if opened >= after and opened < end:
            return opened, float(row["open"])
    return None


def move_after_event(
    m1_rows: Sequence[dict[str, Any]],
    event: dict[str, Any] | None,
    *,
    end: datetime,
    scale: float,
) -> dict[str, Any] | None:
    if event is None or not math.isfinite(scale) or scale <= 0:
        return None
    event_at = parse_dt(event["break_at"])
    entry = next_m1_open(m1_rows, event_at, end)
    if entry is None:
        return None
    entry_at, entry_price = entry
    path = [
        row
        for row in complete_rows(m1_rows, end)
        if entry_at <= parse_dt(row["open_at"]) < end
    ]
    if not path:
        return None
    direction: Direction = str(event["direction"])  # type: ignore[assignment]
    if direction == "SHORT":
        favourable = entry_price - min(float(row["low"]) for row in path)
        adverse = max(float(row["high"]) for row in path) - entry_price
    else:
        favourable = max(float(row["high"]) for row in path) - entry_price
        adverse = entry_price - min(float(row["low"]) for row in path)
    first_passage = "NEITHER"
    for row in path:
        if direction == "SHORT":
            favourable_touch = float(row["low"]) <= entry_price - scale
            adverse_touch = float(row["high"]) >= entry_price + scale
        else:
            favourable_touch = float(row["high"]) >= entry_price + scale
            adverse_touch = float(row["low"]) <= entry_price - scale
        if favourable_touch and adverse_touch:
            first_passage = "AMBIGUOUS_STOP_FIRST"
            break
        if adverse_touch:
            first_passage = "ADVERSE_1R_FIRST"
            break
        if favourable_touch:
            first_passage = "FAVOURABLE_1R_FIRST"
            break
    return {
        "entry_at": iso(entry_at),
        "entry_price": entry_price,
        "favourable_r": favourable / scale,
        "adverse_r": adverse / scale,
        "first_passage_1r": first_passage,
    }


def context_at(
    m5_events: Sequence[dict[str, Any]],
    m15_events: Sequence[dict[str, Any]],
    at: datetime,
) -> dict[str, Any]:
    m5 = active_control(m5_events, at)
    m15 = active_control(m15_events, at)
    return {
        "m5": m5,
        "m15": m15,
        "m5_control": control_label(m5),
        "m15_control": control_label(m15),
        "confluent_control": (
            control_label(m5)
            if m5 is not None and m15 is not None and m5["direction"] == m15["direction"]
            else "CONFLICTED_OR_UNRESOLVED"
        ),
    }


def prepare_stream(stream: dict[str, Any]) -> dict[str, Any]:
    return {
        "m5_events": strong_breaks(
            stream["timeframes"]["5m"], stream["end_exclusive"], "M5"
        ),
        "m15_events": strong_breaks(
            stream["timeframes"]["15m"], stream["end_exclusive"], "M15"
        ),
        "m5_sweeps": sweep_reclaims(
            stream["timeframes"]["5m"], stream["end_exclusive"], "M5"
        ),
    }


def trade_analysis(
    row: dict[str, Any], stream: dict[str, Any], prepared: dict[str, Any]
) -> dict[str, Any]:
    signal_at = parse_dt(row["signal_at"])
    result = row["corrected"]["effective_result"]
    geometry = row["family_router"]["geometry"]
    fill_at = parse_dt(geometry["fill_at"])
    exit_at = parse_dt(result["final_at"])
    day_end = parse_dt(stream["end_exclusive"])
    session = str(row["family_router"]["session"])
    opened, _ = session_bounds(date.fromisoformat(row["trading_date_utc"]), session)
    risk = float(geometry["structural_risk_per_ounce"])

    m5_events = prepared["m5_events"]
    m15_events = prepared["m15_events"]
    m5_sweeps = prepared["m5_sweeps"]
    pre = context_at(m5_events, m15_events, signal_at)
    last_sweep = latest_between(m5_sweeps, opened, signal_at)

    seller_m5 = first_event(m5_events, direction="SHORT", after=signal_at, before_or_at=day_end)
    seller_m15 = first_event(m15_events, direction="SHORT", after=signal_at, before_or_at=day_end)
    buyer_m5 = first_event(m5_events, direction="LONG", after=signal_at, before_or_at=day_end)
    buyer_m15 = first_event(m15_events, direction="LONG", after=signal_at, before_or_at=day_end)
    first_seller = min(
        (event for event in (seller_m5, seller_m15) if event is not None),
        key=lambda event: parse_dt(event["break_at"]),
        default=None,
    )
    seller_move = move_after_event(
        stream["timeframes"]["1m"], first_seller, end=day_end, scale=risk
    )

    first_seller_at = parse_dt(first_seller["break_at"]) if first_seller else None
    if pre["confluent_control"] == "SHORT":
        attribution = "SELLER_CONTROL_VISIBLE_BEFORE_LONG"
    elif first_seller_at is not None and first_seller_at <= exit_at:
        attribution = "SELLER_CONTROL_TRANSFER_BEFORE_LONG_EXIT"
    elif float(result["net_r50"]) < 0:
        attribution = "LONG_FAILED_WITHOUT_STRONG_SELLER_TRANSFER_BEFORE_EXIT"
    else:
        attribution = "LONG_SURVIVED_WITHOUT_STRONG_SELLER_TRANSFER"

    macro_long = row["base_classification"]["macro"]
    macro_short = macro_state(stream, iso(signal_at), "SHORT")
    return {
        "date": row["trading_date_utc"],
        "case_alias": row["case_alias"],
        "session": session,
        "signal_at": iso(signal_at),
        "fill_at": iso(fill_at),
        "exit_at": iso(exit_at),
        "net_r": float(result["net_r50"]),
        "resolution": result["resolution"],
        "h4_swing_sequence": row["base_classification"]["h4"]["swing_sequence"],
        "macro_long_state": macro_long["state"],
        "macro_short_state": macro_short["state"],
        "m5_control_at_signal": pre["m5_control"],
        "m15_control_at_signal": pre["m15_control"],
        "confluent_control_at_signal": pre["confluent_control"],
        "last_session_sweep_direction": last_sweep and last_sweep["direction"],
        "last_session_sweep_kind": last_sweep and last_sweep["kind"],
        "last_session_sweep_at": last_sweep and last_sweep["at"],
        "first_seller_m5_at": seller_m5 and seller_m5["break_at"],
        "first_seller_m15_at": seller_m15 and seller_m15["break_at"],
        "first_buyer_m5_at": buyer_m5 and buyer_m5["break_at"],
        "first_buyer_m15_at": buyer_m15 and buyer_m15["break_at"],
        "seller_transfer_before_exit": bool(first_seller_at and first_seller_at <= exit_at),
        "seller_move_after_first_transfer_r": seller_move and seller_move["favourable_r"],
        "seller_adverse_after_first_transfer_r": seller_move and seller_move["adverse_r"],
        "seller_first_passage_1r": seller_move and seller_move["first_passage_1r"],
        "attribution": attribution,
    }


def accepted_session_shifts(
    stream: dict[str, Any], prepared: dict[str, Any], session: str
) -> list[dict[str, Any]]:
    calendar_day = date.fromisoformat(str(stream["trading_date_utc"]))
    opened, closed = session_bounds(calendar_day, session)
    m5_rows = stream["timeframes"]["5m"]
    m15_rows = stream["timeframes"]["15m"]
    m1_rows = stream["timeframes"]["1m"]
    m5_events = prepared["m5_events"]
    m15_events = prepared["m15_events"]
    checkpoints = [
        parse_dt(row["available_at"])
        for row in complete_rows(m5_rows, closed)
        if opened < parse_dt(row["available_at"]) <= closed
    ]
    candidate: str | None = None
    consecutive = 0
    accepted: str | None = None
    output: list[dict[str, Any]] = []
    for checkpoint in checkpoints:
        context = context_at(m5_events, m15_events, checkpoint)
        state = str(context["confluent_control"])
        if state not in {"LONG", "SHORT"}:
            candidate = None
            consecutive = 0
            continue
        if state == candidate:
            consecutive += 1
        else:
            candidate = state
            consecutive = 1
        if consecutive < ACCEPTANCE_M5_CLOSES or state == accepted:
            continue
        m5_event = context["m5"]
        m15_event = context["m15"]
        latest_break_at = max(parse_dt(m5_event["break_at"]), parse_dt(m15_event["break_at"]))
        if latest_break_at < opened:
            accepted = state
            continue
        accepted = state
        scale = atr_at(m15_rows, checkpoint)
        move = (
            move_after_event(
                m1_rows,
                {
                    "break_at": iso(checkpoint),
                    "direction": state,
                },
                end=closed,
                scale=scale,
            )
            if scale is not None
            else None
        )
        output.append(
            {
                "date": stream["trading_date_utc"],
                "case_alias": stream["case_alias"],
                "session": session,
                "accepted_at": iso(checkpoint),
                "direction": state,
                "m5_break_at": m5_event["break_at"],
                "m15_break_at": m15_event["break_at"],
                "m15_atr": scale,
                "session_end_favourable_atr": move and move["favourable_r"],
                "session_end_adverse_atr": move and move["adverse_r"],
                "first_passage_1atr": move and move["first_passage_1r"],
                "macro_state_for_direction": macro_state(stream, iso(checkpoint), state)["state"],
            }
        )
    return output


def synthetic_proof() -> dict[str, Any]:
    # The state acceptance mechanism must require two consecutive observations
    # and must reset on unresolved input.  This proof is deliberately price-free.
    sequence = ["LONG", "LONG", "UNRESOLVED", "SHORT", "SHORT", "SHORT"]
    accepted: list[str] = []
    candidate: str | None = None
    count = 0
    current: str | None = None
    for state in sequence:
        if state == "UNRESOLVED":
            candidate = None
            count = 0
            continue
        if state == candidate:
            count += 1
        else:
            candidate = state
            count = 1
        if count >= ACCEPTANCE_M5_CLOSES and state != current:
            current = state
            accepted.append(state)
    require(accepted == ["LONG", "SHORT"], "Acceptance proof failed")
    return {"input": sequence, "accepted": accepted, "passed": True}


def lifecycle_equivalence_proof(
    streams: dict[str, dict[str, Any]], prepared: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    checks = 0
    # First and last dates cover different stream lengths. Every event is tested
    # at creation, at its inferred terminal when present, and at stream end.
    for alias in (sorted(streams)[0], sorted(streams)[-1]):
        stream = streams[alias]
        for event_key, timeframe in (("m5_events", "5m"), ("m15_events", "15m")):
            rows = stream["timeframes"][timeframe]
            for event in prepared[alias][event_key]:
                points = [parse_dt(event["break_at"]), parse_dt(stream["end_exclusive"])]
                if event["invalidated_at"] is not None:
                    points.append(parse_dt(event["invalidated_at"]))
                for point in points:
                    expected = event_is_active(event, rows, point)
                    actual = parse_dt(event["break_at"]) <= point and (
                        event["invalidated_at"] is None
                        or point < parse_dt(event["invalidated_at"])
                    )
                    require(
                        expected == actual,
                        f"Lifecycle equivalence failed: {alias} {event['identity']} {iso(point)}",
                    )
                    checks += 1
    return {"checks": checks, "passed": True}


def analyse_side(streams: dict[str, dict[str, Any]], source: dict[str, Any]) -> dict[str, Any]:
    rows = [
        row
        for row in source["rows"]
        if row["corrected"].get("effective_result") is not None
        and row["corrected"]["effective_result"].get("executed")
    ]
    prepared = {alias: prepare_stream(stream) for alias, stream in streams.items()}
    lifecycle_proof = lifecycle_equivalence_proof(streams, prepared)
    trades = [
        trade_analysis(
            row,
            streams[str(row["case_alias"])],
            prepared[str(row["case_alias"])],
        )
        for row in rows
    ]
    shifts: list[dict[str, Any]] = []
    for alias in sorted(streams):
        for session in ("LONDON", "NEW_YORK"):
            shifts.extend(accepted_session_shifts(streams[alias], prepared[alias], session))
    return {
        "trades": trades,
        "trade_sha256": canonical_hash(trades),
        "session_shifts": shifts,
        "session_shift_sha256": canonical_hash(shifts),
        "lifecycle_equivalence_proof": lifecycle_proof,
    }


def finite(values: Iterable[Any]) -> list[float]:
    output: list[float] = []
    for value in values:
        if value is None:
            continue
        number = float(value)
        if math.isfinite(number):
            output.append(number)
    return output


def median(values: Iterable[Any]) -> float | None:
    observed = sorted(finite(values))
    if not observed:
        return None
    middle = len(observed) // 2
    return observed[middle] if len(observed) % 2 else (observed[middle - 1] + observed[middle]) / 2


def summarize(trades: list[dict[str, Any]], shifts: list[dict[str, Any]]) -> dict[str, Any]:
    by_direction: dict[str, Any] = {}
    for direction in ("LONG", "SHORT"):
        selected = [row for row in shifts if row["direction"] == direction]
        by_direction[direction] = {
            "accepted_shifts": len(selected),
            "favourable_1atr_first": sum(
                row["first_passage_1atr"] == "FAVOURABLE_1R_FIRST" for row in selected
            ),
            "adverse_1atr_first": sum(
                row["first_passage_1atr"] in {"ADVERSE_1R_FIRST", "AMBIGUOUS_STOP_FIRST"}
                for row in selected
            ),
            "neither_1atr": sum(row["first_passage_1atr"] == "NEITHER" for row in selected),
            "median_session_end_favourable_atr": median(
                row["session_end_favourable_atr"] for row in selected
            ),
            "median_session_end_adverse_atr": median(
                row["session_end_adverse_atr"] for row in selected
            ),
            "macro_aligned": sum(row["macro_state_for_direction"] == "ALIGNED" for row in selected),
            "macro_opposed": sum(row["macro_state_for_direction"] == "OPPOSED" for row in selected),
            "macro_neutral_or_conflicted": sum(
                row["macro_state_for_direction"] == "NEUTRAL_OR_CONFLICTED" for row in selected
            ),
        }
    return {
        "executed_long_trades": len(trades),
        "attribution_counts": dict(sorted(Counter(row["attribution"] for row in trades).items())),
        "confluent_control_at_signal": dict(
            sorted(Counter(row["confluent_control_at_signal"] for row in trades).items())
        ),
        "seller_transfer_before_exit": sum(row["seller_transfer_before_exit"] for row in trades),
        "seller_transfer_favourable_1r_first": sum(
            row["seller_first_passage_1r"] == "FAVOURABLE_1R_FIRST" for row in trades
        ),
        "session_shift_atlas": by_direction,
    }


def write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    require(rows, f"No rows for {path}")
    with path.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def markdown(result: dict[str, Any]) -> str:
    summary = result["summary"]
    lines = [
        "# Gold June 2022 Liquidity-Control Shift Diagnostic V1-R2",
        "",
        "Verdict: `COMPLETE_EXPOSED_POST_RESULT_DIAGNOSTIC_ZERO_VALIDATION_CREDIT`",
        "",
        "The frozen LONG control remains unchanged. This diagnostic separates H4 swing backdrop from completed-candle M5/M15 control transfer.",
        "",
        "## Frozen descriptive semantics",
        "",
        f"- Causal 2-left/2-right pivots with 0.25 ATR prominence.",
        f"- M5 control break: close through a known pivot by 0.05 ATR, range >= {M5_MINIMUM_RANGE_ATR:.2f} ATR and body/range >= {MINIMUM_BODY_RATIO:.2f}.",
        f"- M15 control break: the same rule with range >= {M15_MINIMUM_RANGE_ATR:.2f} ATR.",
        f"- Accepted session shift: M5 and M15 agree for {ACCEPTANCE_M5_CLOSES} completed M5 closes.",
        "- All events are INFERRED price-auction states, not observed institutional orders.",
        "",
        "## Existing LONG trades",
        "",
        "| Date | Net R | H4 | M5 at signal | M15 at signal | Confluent | First seller M5 | First seller M15 | Before exit? | Attribution |",
        "|---|---:|---|---|---|---|---|---|---|---|",
    ]
    for row in result["trades"]:
        lines.append(
            "| {date} | {net_r:+.4f} | {h4_swing_sequence} | {m5_control_at_signal} | "
            "{m15_control_at_signal} | {confluent_control_at_signal} | {first_seller_m5_at} | "
            "{first_seller_m15_at} | {seller_transfer_before_exit} | {attribution} |".format(
                **{key: ("-" if value is None else value) for key, value in row.items()}
            )
        )
    lines.extend(
        [
            "",
            "## Summary",
            "",
            f"- Pre-entry confluent control: `{summary['confluent_control_at_signal']}`.",
            f"- Attribution: `{summary['attribution_counts']}`.",
            f"- Seller transfer before the frozen LONG exit: {summary['seller_transfer_before_exit']}/{summary['executed_long_trades']}.",
            f"- Seller transfers subsequently reaching +1 original LONG-risk unit before -1: {summary['seller_transfer_favourable_1r_first']}.",
            "",
            "## Session shift atlas",
            "",
            "| Direction | Accepted shifts | +1 ATR first | -1 ATR/ambiguous first | Neither | Median favourable ATR | Median adverse ATR | Macro aligned | Macro opposed | Macro neutral/conflicted |",
            "|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for direction, row in summary["session_shift_atlas"].items():
        lines.append(
            f"| {direction} | {row['accepted_shifts']} | {row['favourable_1atr_first']} | "
            f"{row['adverse_1atr_first']} | {row['neither_1atr']} | "
            f"{row['median_session_end_favourable_atr']} | {row['median_session_end_adverse_atr']} | "
            f"{row['macro_aligned']} | {row['macro_opposed']} | {row['macro_neutral_or_conflicted']} |"
        )
    lines.extend(
        [
            "",
            "## Scope",
            "",
            "No policy was changed, no SHORT strategy was simulated, no new period was opened, and no edge is claimed.",
        ]
    )
    return "\n".join(lines) + "\n"


def main() -> None:
    require(not OUT.exists(), f"Append-only diagnostic exists: {OUT}")
    require(not REPORT.exists(), f"Append-only report exists: {REPORT}")
    seal = verify_source_chain()
    proof = synthetic_proof()
    source = load_json(SOURCE_RESULT)
    primary = analyse_side(load_streams(PRIMARY_STREAMS), source)
    reference = analyse_side(load_streams(REFERENCE_STREAMS), source)
    require(primary == reference, "Primary/reference liquidity diagnostics differ")
    summary = summarize(primary["trades"], primary["session_shifts"])
    payload: dict[str, Any] = {
        "version": "GOLD_JUNE_2022_LIQUIDITY_CONTROL_SHIFT_DIAGNOSTIC_V1_R2_1_0",
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "verdict": "COMPLETE_EXPOSED_POST_RESULT_DIAGNOSTIC_ZERO_VALIDATION_CREDIT",
        "source_verdict": source["verdict"],
        "source_seal_sha256": sha256_file(SOURCE_SEAL),
        "source_result_sha256": sha256_file(SOURCE_RESULT),
        "preserved_failed_predecessors": [
            "FAIL_SESSION_CALENDAR_CONSTRUCTION_ZERO_RESEARCH_CREDIT",
            "FAIL_CONTROL_LIFECYCLE_EQUIVALENCE_ZERO_RESEARCH_CREDIT",
        ],
        "definitions": {
            "break_buffer_atr": BREAK_BUFFER_ATR,
            "m5_minimum_range_atr": M5_MINIMUM_RANGE_ATR,
            "m15_minimum_range_atr": M15_MINIMUM_RANGE_ATR,
            "minimum_body_ratio": MINIMUM_BODY_RATIO,
            "acceptance_m5_closes": ACCEPTANCE_M5_CLOSES,
            "epistemic_status": "INFERRED",
        },
        "synthetic_proof": proof,
        "primary_reference_exact": True,
        "lifecycle_equivalence_proof": primary["lifecycle_equivalence_proof"],
        "trades": primary["trades"],
        "session_shifts": primary["session_shifts"],
        "summary": summary,
        "frozen_long_policy_changed": False,
        "short_strategy_simulated": False,
        "new_period_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "source_seal_verdict": seal["verdict"],
    }
    payload["result_sha256"] = canonical_hash(payload)
    OUT.mkdir(parents=True, exist_ok=False)
    RESULT.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    write_csv(TRADE_CSV, payload["trades"])
    write_csv(SESSION_CSV, payload["session_shifts"])
    REPORT.write_text(markdown(payload), encoding="utf-8", newline="\n")
    print(json.dumps({"verdict": payload["verdict"], "summary": summary}, indent=2))


if __name__ == "__main__":
    main()
