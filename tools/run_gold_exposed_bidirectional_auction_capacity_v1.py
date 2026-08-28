#!/usr/bin/env python3
"""Exposed-only bidirectional M15 auction-capacity scan.

The protocol is frozen in GOLD_EXPOSED_BIDIRECTIONAL_AUCTION_CAPACITY_PROTOCOL_V1.md.
This script must never be used to claim validation.
"""

from __future__ import annotations

import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as sources  # noqa: E402
from gold_intel.analytics.auction_family_router_v2_r1 import destination_hierarchy  # noqa: E402
from gold_intel.analytics.auction_plan_compiler_v1_semantic_amendment_a import (  # noqa: E402
    compile_auction_plan_v1_semantic_amendment_a,
    plan_integrity_violations,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
    structural_breaks,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    RISK_BUDGET_USD,
    simulate_track,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    SLIPPAGE_USD_PER_OUNCE,
    first_m1_after,
    latest_m1_at,
    spread,
)


Direction = Literal["LONG", "SHORT"]
PROTOCOL = ROOT / "GOLD_EXPOSED_BIDIRECTIONAL_AUCTION_CAPACITY_PROTOCOL_V1.md"
PROTOCOL_SHA256 = "109b103901cae70889a3c3fdbf3f6d44b5f9fa75a1310b3451a97b1bb1b999c2"
OUTPUT = ROOT / "research_artifacts" / "gold_exposed_bidirectional_auction_capacity_v1"
CHECKPOINTS = OUTPUT / "checkpoints"
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
MIN_FINAL_ROOM_R = 1.50
TARGET_CAP_R = 2.00


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def session_bounds(day: date, session: str) -> tuple[datetime, datetime]:
    zone = LONDON if session == "LONDON" else NEW_YORK
    start = datetime.combine(day, time(8), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(day, time(12), tzinfo=zone).astimezone(UTC)
    return start, end


def candidate_events(
    stream: dict[str, Any], start: datetime, end: datetime
) -> list[tuple[str, Direction, dict[str, Any]]]:
    grouped: dict[str, list[tuple[Direction, dict[str, Any]]]] = defaultdict(list)
    for direction in ("LONG", "SHORT"):
        events = structural_breaks(
            stream["timeframes"]["15m"], iso(end), "M15", direction
        )
        for event in events:
            point = parse_dt(event["break_at"])
            if start <= point < end:
                grouped[iso(point)].append((direction, event))
    output: list[tuple[str, Direction, dict[str, Any]]] = []
    for timestamp in sorted(grouped, key=parse_dt):
        directions = {direction for direction, _ in grouped[timestamp]}
        if len(directions) != 1:
            continue
        direction, event = sorted(
            grouped[timestamp], key=lambda item: str(item[1]["identity"])
        )[0]
        output.append((timestamp, direction, event))
    return output


def classify_candidate(
    *,
    stream: dict[str, Any],
    signal_at: str,
    direction: Direction,
    event: dict[str, Any],
    session_end: datetime,
) -> tuple[dict[str, Any] | None, dict[str, Any]]:
    decision_bar = latest_m1_at(stream, signal_at)
    fill_bar = first_m1_after(stream, signal_at)
    if decision_bar is None or fill_bar is None:
        return None, {"disposition": "M1_EXECUTION_REFERENCE_UNAVAILABLE"}
    if parse_dt(fill_bar["open_at"]) >= session_end:
        return None, {"disposition": "FILL_NOT_BEFORE_SESSION_CLOSE"}

    entry_reference = float(decision_bar["close"])
    plan = compile_auction_plan_v1_semantic_amendment_a(
        stream=stream,
        decision_at=signal_at,
        direction=direction,
        entry_reference=entry_reference,
    )
    violations = plan_integrity_violations(plan)
    if plan["disposition"] != "EXECUTABLE_PLAN" or violations:
        return None, {
            "disposition": "PLAN_UNRESOLVED_OR_INVALID",
            "missing_components": plan.get("missing_components"),
            "integrity_violations": violations,
            "plan_sha256": plan["plan_sha256"],
        }
    local = plan["components"]["local_trigger"]
    setup = local.get("setup_transition") if isinstance(local, dict) else None
    if (
        not isinstance(setup, dict)
        or setup.get("timeframe") != "M15"
        or str(setup.get("event_identity")) != str(event["identity"])
        or iso(setup.get("break_at")) != iso(signal_at)
    ):
        return None, {
            "disposition": "STALE_OR_DIFFERENT_M15_TRANSITION",
            "plan_sha256": plan["plan_sha256"],
        }

    fill_at = iso(fill_bar["open_at"])
    sign = 1.0 if direction == "LONG" else -1.0
    fill = float(fill_bar["open"]) + sign * (
        spread(fill_bar) / 2.0 + SLIPPAGE_USD_PER_OUNCE
    )
    stop = float(plan["components"]["structural_invalidation"]["price"])
    structural_risk = sign * (fill - stop)
    cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE_USD_PER_OUNCE
    if not math.isfinite(structural_risk) or structural_risk <= 0:
        return None, {"disposition": "INVALID_ACTUAL_FILL_STOP_GEOMETRY"}

    hierarchy = destination_hierarchy(
        stream=stream,
        cutoff=fill_at,
        entry=fill,
        direction=direction,
        plan=plan,
    )
    if hierarchy is None:
        return None, {"disposition": "ACTIVE_FINAL_DESTINATION_UNAVAILABLE"}
    final_target = float(hierarchy["final"]["level"])
    final_room_r = sign * (final_target - fill) / structural_risk
    if final_room_r < MIN_FINAL_ROOM_R:
        return None, {
            "disposition": "ACTUAL_FILL_FINAL_DESTINATION_ROOM_LT_1P5R",
            "final_room_r": final_room_r,
        }
    target_distance = min(sign * (final_target - fill), TARGET_CAP_R * structural_risk)
    target = fill + sign * target_distance
    planned_loss_per_ounce = structural_risk + cost_per_ounce
    quantity = math.floor(RISK_BUDGET_USD / planned_loss_per_ounce)
    if quantity < 1:
        return None, {"disposition": "WHOLE_OUNCE_RISK_CAP_UNAVAILABLE"}

    family = str(plan["components"]["governing_auction"]["family"])
    classification: dict[str, Any] = {
        "ruleset": "EXPOSED_BIDIRECTIONAL_M15_AUCTION_CAPACITY_V1",
        "decision_at": iso(signal_at),
        "direction": direction,
        "family": family,
        "admitted": True,
        "primary_disposition": "ADMIT",
        "fill": fill,
        "stop": stop,
        "target": target,
        "final_liquidity_target": final_target,
        "final_destination_room_r": final_room_r,
        "structural_price_risk_per_ounce": structural_risk,
        "cost_per_ounce": cost_per_ounce,
        "planned_loss_per_ounce": planned_loss_per_ounce,
        "quantity_ounces": quantity,
        "plan_sha256": plan["plan_sha256"],
        "destination_hierarchy_sha256": hierarchy["hierarchy_hash"],
        "macro_state": plan["components"]["macro_context"]["state"],
        "classification_hash": None,
    }
    classification["classification_hash"] = canonical_hash(
        {key: value for key, value in classification.items() if key != "classification_hash"}
    )
    return classification, {
        "disposition": "ADMIT",
        "fill_at": fill_at,
        "plan_sha256": plan["plan_sha256"],
        "destination_hierarchy_sha256": hierarchy["hierarchy_hash"],
    }


def scan_side(side: str) -> dict[str, Any]:
    streams = sources.load_all_streams(side)
    session_rows: list[dict[str, Any]] = []
    ordered_aliases = sorted(streams, key=lambda key: streams[key]["trading_date_utc"])
    for alias_index, alias in enumerate(ordered_aliases, start=1):
        stream = streams[alias]
        checkpoint_path = CHECKPOINTS / side / f"{alias}.json"
        if checkpoint_path.exists():
            checkpoint = json.loads(checkpoint_path.read_text(encoding="utf-8"))
            submitted = checkpoint.pop("checkpoint_sha256")
            require(canonical_hash(checkpoint) == submitted, f"Checkpoint differs: {checkpoint_path}")
            require(checkpoint["protocol_sha256"] == PROTOCOL_SHA256, "Checkpoint protocol differs")
            require(checkpoint["side"] == side and checkpoint["case_alias"] == alias, "Checkpoint identity differs")
            require(checkpoint["stream_sha256"] == stream["stream_sha256"], "Checkpoint source differs")
            session_rows.extend(checkpoint["rows"])
            if alias_index % 10 == 0 or alias_index == len(ordered_aliases):
                print(f"{side}: {alias_index}/{len(ordered_aliases)} session dates certified", flush=True)
            continue
        day = date.fromisoformat(str(stream["trading_date_utc"]))
        alias_rows: list[dict[str, Any]] = []
        for session in ("LONDON", "NEW_YORK"):
            start, end = session_bounds(day, session)
            attempts: list[dict[str, Any]] = []
            selected: dict[str, Any] | None = None
            for signal_at, direction, event in candidate_events(stream, start, end):
                classification, diagnostic = classify_candidate(
                    stream=stream,
                    signal_at=signal_at,
                    direction=direction,
                    event=event,
                    session_end=end,
                )
                attempt = {
                    "signal_at": signal_at,
                    "direction": direction,
                    "event_identity": str(event["identity"]),
                    **diagnostic,
                }
                attempt["attempt_sha256"] = canonical_hash(attempt)
                attempts.append(attempt)
                if classification is None:
                    continue
                selected = {
                    "signal_at": signal_at,
                    "fill_at": diagnostic["fill_at"],
                    "classification": classification,
                }
                break

            decision = {
                "case_alias": alias,
                "trading_date_utc": day.isoformat(),
                "session": session,
                "session_start": iso(start),
                "session_end": iso(end),
                "attempts": attempts,
                "selected": selected,
            }
            decision["decision_sha256"] = canonical_hash(decision)
            result = None
            if selected is not None:
                truncated_stream = dict(stream)
                truncated_stream["end_exclusive"] = iso(end)
                result = simulate_track(
                    classification=selected["classification"],
                    stream=truncated_stream,
                    fill_at=selected["fill_at"],
                    track="FAITHFUL_FIXED_GEOMETRY",
                )
            row = {"decision": decision, "result": result}
            row["row_sha256"] = canonical_hash(row)
            alias_rows.append(row)
        checkpoint = {
            "protocol_sha256": PROTOCOL_SHA256,
            "side": side,
            "case_alias": alias,
            "stream_sha256": stream["stream_sha256"],
            "rows": alias_rows,
        }
        checkpoint["checkpoint_sha256"] = canonical_hash(checkpoint)
        checkpoint_path.parent.mkdir(parents=True, exist_ok=True)
        checkpoint_path.write_text(
            json.dumps(checkpoint, indent=2, sort_keys=True) + "\n", encoding="utf-8"
        )
        session_rows.extend(alias_rows)
        if alias_index % 10 == 0 or alias_index == len(ordered_aliases):
            print(f"{side}: {alias_index}/{len(ordered_aliases)} session dates certified", flush=True)
    return {
        "side": side,
        "rows": session_rows,
        "row_set_sha256": canonical_hash(
            [
                {
                    "decision": row["decision"],
                    "result": row["result"],
                }
                for row in session_rows
            ]
        ),
    }


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    trades = [row for row in rows if row["result"] is not None]
    values = [float(row["result"]["net_r50"]) for row in trades]
    stressed = [float(row["result"]["stressed_1_5x_cost_r50"]) for row in trades]
    wins = [value for value in values if value > 1e-12]
    losses = [value for value in values if value < -1e-12]
    equity = peak = maximum_drawdown = 0.0
    monthly: dict[str, float] = defaultdict(float)
    contributions: dict[str, float] = defaultdict(float)
    for row, value in zip(trades, values, strict=True):
        equity += value
        peak = max(peak, equity)
        maximum_drawdown = max(maximum_drawdown, peak - equity)
        decision = row["decision"]
        selected = decision["selected"]
        month = decision["trading_date_utc"][:7]
        monthly[month] += value
        contributions[f"{decision['session']}::{selected['classification']['direction']}"] += value
    positive = sum(wins)
    negative = abs(sum(losses))
    return {
        "session_units": len(rows),
        "trades": len(trades),
        "trades_per_month": len(trades) / 5.0,
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "net_r": sum(values),
        "net_usd_at_50_risk": sum(values) * RISK_BUDGET_USD,
        "r_per_month": sum(values) / 5.0,
        "expectancy_r": sum(values) / len(values) if values else None,
        "profit_factor": positive / negative if negative else None,
        "maximum_drawdown_r": maximum_drawdown,
        "stressed_1_5x_cost_net_r": sum(stressed),
        "monthly": dict(sorted(monthly.items())),
        "positive_months": sum(value > 0 for value in monthly.values()),
        "directions": dict(Counter(row["decision"]["selected"]["classification"]["direction"] for row in trades)),
        "sessions": dict(Counter(row["decision"]["session"] for row in trades)),
        "families": dict(Counter(row["decision"]["selected"]["classification"]["family"] for row in trades)),
        "contribution_r": dict(sorted(contributions.items())),
    }


def main() -> int:
    require(sha256_file(PROTOCOL) == PROTOCOL_SHA256, "Frozen protocol changed")
    OUTPUT.mkdir(parents=True, exist_ok=True)
    primary = scan_side("primary")
    reference = scan_side("reference")
    require(len(primary["rows"]) == 190, "Expected 95 days x two sessions")
    require(len(reference["rows"]) == 190, "Reference session population differs")
    primary_comparable = [
        {"decision": row["decision"], "result": row["result"]}
        for row in primary["rows"]
    ]
    reference_comparable = [
        {"decision": row["decision"], "result": row["result"]}
        for row in reference["rows"]
    ]
    reproduced = canonical_hash(primary_comparable) == canonical_hash(reference_comparable)
    require(reproduced, "Primary/reference bidirectional scan differs")
    summary = summarize(primary["rows"])
    payload = {
        "version": "GOLD_EXPOSED_BIDIRECTIONAL_AUCTION_CAPACITY_V1_1_0",
        "completed_at": datetime.now(UTC).isoformat().replace("+00:00", "Z"),
        "protocol_sha256": PROTOCOL_SHA256,
        "scope": "EXPOSED_HYPOTHESIS_GENERATION_ONLY",
        "primary_reference_exact": reproduced,
        "summary": summary,
        "fresh_data_opened": False,
        "validation_credit": 0,
        "primary_row_set_sha256": primary["row_set_sha256"],
        "reference_row_set_sha256": reference["row_set_sha256"],
        "rows": primary["rows"],
    }
    payload["result_sha256"] = canonical_hash(payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    (OUTPUT / "final_result.json").write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTPUT / "primary.json").write_text(
        json.dumps(primary, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    (OUTPUT / "reference.json").write_text(
        json.dumps(reference, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({
        "output": str(OUTPUT / "final_result.json"),
        "result_sha256": payload["result_sha256"],
        "primary_reference_exact": reproduced,
        "summary": summary,
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
