"""Zero-credit exposed regression of the frozen coherent-auction management policy.

The runner has two modes. ``--freeze`` records the immutable protocol,
implementation, and input hashes without opening a case stream. ``--run`` first
verifies that freeze and then evaluates the already exposed matched-human cases.
"""

from __future__ import annotations

import argparse
import csv
import gzip
import hashlib
import json
import math
from collections import Counter
from pathlib import Path
from typing import Any, Callable

from analyze_gold_coherent_auction_management_v1 import (
    ATR_WINDOW,
    PIVOT_PROMINENCE_ATR,
    PIVOT_WIDTH,
    RISK_BUDGET_USD,
    TICK_FLOOR,
    atr_values,
    confirmed_swings,
    latest_atr,
    simulate_fixed,
)
from analyze_gold_same_timeframe_target_v1 import canonical_hash, round_floats


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_PROTOCOL_V1.md"
BLIND_CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_CONTRACT_V1.md"
BASE_RESULT = (
    ROOT
    / "research_artifacts/gold_coherent_auction_management_v1/coherent_auction_management_result.json"
)
COMPARISON = (
    ROOT
    / "research_artifacts/gold_matched_human_replay_v1/comparison/matched_case_comparison.json"
)
OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_exposed_policy_regression_v1"
FREEZE = OUTPUT / "pre_run_freeze.json"
AMENDMENT = ROOT / "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_ENGINEERING_AMENDMENT_A.md"
FAILED_ATTEMPT = OUTPUT / "failed_attempt_001.json"
AMENDED_FREEZE = OUTPUT / "pre_run_freeze_amendment_a.json"
AMENDMENT_B = ROOT / "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_ENGINEERING_AMENDMENT_B.md"
FAILED_ATTEMPT_B = OUTPUT / "failed_attempt_002.json"
AMENDED_FREEZE_B = OUTPUT / "pre_run_freeze_amendment_b.json"
RESULT = OUTPUT / "regression_result.json"
TABLE = OUTPUT / "regression_cases.csv"
REPRODUCTION = OUTPUT / "independent_reproduction.json"
SEAL = OUTPUT / "final_seal.json"

BUFFER_ATR = 0.10
RUNNER_FRACTION = 0.20
PROTECTION_ARM_R = 1.0
CONTROL_USD_TOLERANCE = 1e-6
CORRECT_DIRECTION_ROUND_TRIPS = {
    "CBR-2022-005",
    "CBR-2022-014",
    "CBR-2022-030",
}
LARGE_CONTROL_WINNERS = {
    "CBR-2022-023",
    "CBR-2022-024",
    "CBR-2022-027",
}
KNOWN_DIRECTION_WRONG = {
    "CBR-2022-007",
    "CBR-2022-009",
    "CBR-2022-019",
    "CBR-2022-026",
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        raise RuntimeError(f"Append-only output already exists: {path.relative_to(ROOT)}")
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def freeze() -> dict[str, Any]:
    if FREEZE.exists():
        raise RuntimeError("Pre-run freeze already exists")
    required = [PROTOCOL, BLIND_CONTRACT, BASE_RESULT, COMPARISON, Path(__file__).resolve()]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Required regression inputs are missing: {missing}")
    base = json.loads(BASE_RESULT.read_text(encoding="utf-8"))
    if base.get("population") != 16 or len(base.get("cases", [])) != 16:
        raise RuntimeError("The frozen exposed population is not exactly 16")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_V1_FREEZE_1_0",
        "status": "SEALED_BEFORE_NEW_REGRESSION_CALCULATION",
        "evidence_status": "POST_RESULT_ZERO_CREDIT_CALIBRATION_REGRESSION",
        "population": [row["case_alias"] for row in base["cases"]],
        "population_count": 16,
        "rule_origin": file_record(BLIND_CONTRACT),
        "protocol": file_record(PROTOCOL),
        "implementation": file_record(Path(__file__).resolve()),
        "inputs": [file_record(BASE_RESULT), file_record(COMPARISON)],
        "constants": {
            "protection_arm_r": PROTECTION_ARM_R,
            "runner_fraction": RUNNER_FRACTION,
            "buffer_atr": BUFFER_ATR,
            "atr_window": ATR_WINDOW,
            "pivot_width_each_side": PIVOT_WIDTH,
            "pivot_prominence_atr": PIVOT_PROMINENCE_ATR,
            "tick_floor": TICK_FLOOR,
            "risk_budget_usd": RISK_BUDGET_USD,
            "runner_whole_ounce_rule": "FLOOR_20_PERCENT",
            "same_bar_ambiguity": "STOP_FIRST",
        },
        "calendar_2025": "LOCKED_NOT_ACCESSED",
        "calendar_2026": "LOCKED_NOT_ACCESSED",
    }
    write_new_json(FREEZE, payload)
    return payload


def verify_freeze() -> dict[str, Any]:
    if not AMENDED_FREEZE_B.is_file():
        raise RuntimeError("Run --freeze-amendment-b before the final amended --run")
    payload = json.loads(AMENDED_FREEZE_B.read_text(encoding="utf-8"))
    if payload.get("status") != "SEALED_ENGINEERING_AMENDMENT_B_BEFORE_FINAL_RERUN":
        raise RuntimeError("Regression freeze status differs")
    for record in [
        payload["rule_origin"],
        payload["protocol"],
        payload["engineering_amendment"],
        payload["engineering_amendment_b"],
        payload["implementation"],
        payload["original_freeze"],
        payload["amendment_a_freeze"],
        payload["failed_attempt"],
        payload["failed_attempt_b"],
        *payload["inputs"],
    ]:
        path = ROOT / record["path"]
        if (
            not path.is_file()
            or path.stat().st_size != record["bytes"]
            or sha256_file(path) != record["sha256"]
        ):
            raise RuntimeError(f"Frozen predecessor differs: {record['path']}")
    return payload


def freeze_amendment_a() -> dict[str, Any]:
    if AMENDED_FREEZE.exists():
        raise RuntimeError("Engineering Amendment A freeze already exists")
    required = [
        FREEZE,
        AMENDMENT,
        FAILED_ATTEMPT,
        PROTOCOL,
        BLIND_CONTRACT,
        BASE_RESULT,
        COMPARISON,
        Path(__file__).resolve(),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Amendment A predecessor is missing: {missing}")
    original = json.loads(FREEZE.read_text(encoding="utf-8"))
    failure = json.loads(FAILED_ATTEMPT.read_text(encoding="utf-8"))
    if original.get("status") != "SEALED_BEFORE_NEW_REGRESSION_CALCULATION":
        raise RuntimeError("Original freeze status differs")
    if failure.get("classification") != "FAIL_PRIMARY_REFERENCE_OUTPUT_SHAPE":
        raise RuntimeError("Original failure classification differs")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_V1_AMENDMENT_A_FREEZE_1_0",
        "status": "SEALED_ENGINEERING_AMENDMENT_A_BEFORE_RERUN",
        "permitted_change": "NORMALIZE_OPTIONAL_NULL_TARGET_TOUCH_AT_OUTPUT_SHAPE_ONLY",
        "population": original["population"],
        "population_count": original["population_count"],
        "rule_origin": file_record(BLIND_CONTRACT),
        "protocol": file_record(PROTOCOL),
        "engineering_amendment": file_record(AMENDMENT),
        "implementation": file_record(Path(__file__).resolve()),
        "original_freeze": file_record(FREEZE),
        "failed_attempt": file_record(FAILED_ATTEMPT),
        "inputs": [file_record(BASE_RESULT), file_record(COMPARISON)],
        "constants": original["constants"],
        "calendar_2025": "LOCKED_NOT_ACCESSED",
        "calendar_2026": "LOCKED_NOT_ACCESSED",
    }
    write_new_json(AMENDED_FREEZE, payload)
    return payload


def freeze_amendment_b() -> dict[str, Any]:
    if AMENDED_FREEZE_B.exists():
        raise RuntimeError("Engineering Amendment B freeze already exists")
    required = [
        FREEZE,
        AMENDED_FREEZE,
        AMENDMENT,
        AMENDMENT_B,
        FAILED_ATTEMPT,
        FAILED_ATTEMPT_B,
        PROTOCOL,
        BLIND_CONTRACT,
        BASE_RESULT,
        COMPARISON,
        Path(__file__).resolve(),
    ]
    missing = [str(path) for path in required if not path.is_file()]
    if missing:
        raise RuntimeError(f"Amendment B predecessor is missing: {missing}")
    original = json.loads(FREEZE.read_text(encoding="utf-8"))
    amendment_a = json.loads(AMENDED_FREEZE.read_text(encoding="utf-8"))
    failure_b = json.loads(FAILED_ATTEMPT_B.read_text(encoding="utf-8"))
    if original.get("status") != "SEALED_BEFORE_NEW_REGRESSION_CALCULATION":
        raise RuntimeError("Original freeze status differs")
    if amendment_a.get("status") != "SEALED_ENGINEERING_AMENDMENT_A_BEFORE_RERUN":
        raise RuntimeError("Amendment A freeze status differs")
    if failure_b.get("classification") != "FAIL_CONTROL_SERIALIZATION_PRECISION_GATE":
        raise RuntimeError("Amendment A failure classification differs")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_V1_AMENDMENT_B_FREEZE_1_0",
        "status": "SEALED_ENGINEERING_AMENDMENT_B_BEFORE_FINAL_RERUN",
        "permitted_change": "CONTROL_NET_USD_COMPARISON_TOLERANCE_1E_MINUS_6_ONLY",
        "population": original["population"],
        "population_count": original["population_count"],
        "rule_origin": file_record(BLIND_CONTRACT),
        "protocol": file_record(PROTOCOL),
        "engineering_amendment": file_record(AMENDMENT),
        "engineering_amendment_b": file_record(AMENDMENT_B),
        "implementation": file_record(Path(__file__).resolve()),
        "original_freeze": file_record(FREEZE),
        "amendment_a_freeze": file_record(AMENDED_FREEZE),
        "failed_attempt": file_record(FAILED_ATTEMPT),
        "failed_attempt_b": file_record(FAILED_ATTEMPT_B),
        "inputs": [file_record(BASE_RESULT), file_record(COMPARISON)],
        "constants": {
            **original["constants"],
            "control_r_tolerance": 1e-8,
            "control_usd_tolerance": CONTROL_USD_TOLERANCE,
        },
        "calendar_2025": "LOCKED_NOT_ACCESSED",
        "calendar_2026": "LOCKED_NOT_ACCESSED",
    }
    write_new_json(AMENDED_FREEZE_B, payload)
    return payload


def load_stream(source: str) -> dict[str, Any]:
    path = ROOT / source
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        return json.load(handle)


def m1_path(stream: dict[str, Any], fill_at: str) -> list[dict[str, Any]]:
    return sorted(
        [
            row
            for row in stream["timeframes"]["1m"]
            if row.get("complete") is True and row["open_at"] >= fill_at
        ],
        key=lambda row: (row["open_at"], row["available_at"]),
    )


def latest_primary_swing_low(
    rows: list[dict[str, Any]], cutoff: str, timeframe: str
) -> dict[str, Any] | None:
    _, swings = confirmed_swings(rows, cutoff, timeframe)
    lows = [row for row in swings if row["kind"] == "LOW" and row["detected_at"] <= cutoff]
    return max(lows, key=lambda row: (row["detected_at"], row["pivot_index"])) if lows else None


def primary_completed_metadata(
    rows: list[dict[str, Any]], row: dict[str, Any], timeframe: str
) -> dict[str, Any]:
    return {
        "atr": latest_atr(rows, row["available_at"]),
        "swing": latest_primary_swing_low(rows, row["open_at"], timeframe),
    }


def reference_atr_asof(rows: list[dict[str, Any]], available_at: str) -> float:
    eligible = sorted(
        [row for row in rows if row.get("complete") is True and row["available_at"] <= available_at],
        key=lambda row: (row["open_at"], row["available_at"]),
    )
    tr: list[float] = []
    for index, row in enumerate(eligible):
        high, low = float(row["high"]), float(row["low"])
        prior = float(eligible[index - 1]["close"]) if index else None
        tr.append(high - low if prior is None else max(high - low, abs(high - prior), abs(low - prior)))
    return sum(tr[-ATR_WINDOW:]) / len(tr[-ATR_WINDOW:])


def reference_latest_swing_low(
    rows: list[dict[str, Any]], cutoff: str, timeframe: str
) -> dict[str, Any] | None:
    eligible = sorted(
        [row for row in rows if row.get("complete") is True and row["available_at"] <= cutoff],
        key=lambda row: (row["open_at"], row["available_at"]),
    )
    if len(eligible) < 5:
        return None
    atrs = atr_values(eligible)
    candidates: list[dict[str, Any]] = []
    for index in range(2, len(eligible) - 2):
        center = eligible[index]
        neighbors = eligible[index - 2 : index] + eligible[index + 1 : index + 3]
        low = float(center["low"])
        if not all(low < float(item["low"]) for item in neighbors):
            continue
        prominence = max(float(item["high"]) for item in neighbors) - low
        minimum = max(PIVOT_PROMINENCE_ATR * max(atrs[index], 0.01), TICK_FLOOR)
        if prominence < minimum:
            continue
        candidates.append(
            {
                "kind": "LOW",
                "timeframe": timeframe,
                "pivot_index": index,
                "pivot_at": center["open_at"],
                "detected_at": eligible[index + 2]["available_at"],
                "level": low,
            }
        )
    eligible_candidates = [row for row in candidates if row["detected_at"] <= cutoff]
    return (
        max(eligible_candidates, key=lambda row: (row["detected_at"], row["pivot_index"]))
        if eligible_candidates
        else None
    )


def reference_completed_metadata(
    rows: list[dict[str, Any]], row: dict[str, Any], timeframe: str
) -> dict[str, Any]:
    return {
        "atr": reference_atr_asof(rows, row["available_at"]),
        "swing": reference_latest_swing_low(rows, row["open_at"], timeframe),
    }


def containing_bar(rows: list[dict[str, Any]], timestamp: str) -> dict[str, Any] | None:
    return next(
        (
            row
            for row in rows
            if row.get("complete") is True
            and row["open_at"] <= timestamp < row["close_at"]
        ),
        None,
    )


def economic_payload(
    *,
    fill: float,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
    exits: list[dict[str, Any]],
    resolution: str,
    diagnostics: dict[str, Any],
) -> dict[str, Any]:
    gross = sum(int(item["quantity"]) * (float(item["price"]) - fill) for item in exits)
    cost = quantity * cost_per_ounce
    net = gross - cost
    return {
        "executable": True,
        "resolution": resolution,
        "exits": exits,
        "gross_usd": gross,
        "cost_usd": cost,
        "net_usd": net,
        "net_r50": net / RISK_BUDGET_USD,
        "net_initial_r": net / planned_risk_usd,
        "positive": net > 0,
        **diagnostics,
    }


def invalid_track(reason: str) -> dict[str, Any]:
    return {
        "executable": False,
        "resolution": reason,
        "exits": [],
        "gross_usd": 0.0,
        "cost_usd": 0.0,
        "net_usd": 0.0,
        "net_r50": 0.0,
        "net_initial_r": None,
        "positive": False,
        "protection_armed": False,
        "protection_exit": False,
        "target_core_realized": False,
        "target_accepted": False,
        "runner_activated": False,
    }


def simulate_track_b(
    *,
    stream: dict[str, Any],
    fill_at: str,
    fill: float,
    stop: float,
    target: float,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
    metadata: Callable[[list[dict[str, Any]], dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    path = m1_path(stream, fill_at)
    if not path or not stop < fill < target or quantity < 1:
        return invalid_track("INVALID_GEOMETRY")
    m5 = sorted(
        [row for row in stream["timeframes"]["5m"] if row.get("complete") is True],
        key=lambda row: (row["available_at"], row["open_at"]),
    )
    m15 = sorted(
        [row for row in stream["timeframes"]["15m"] if row.get("complete") is True],
        key=lambda row: (row["available_at"], row["open_at"]),
    )
    risk_price = fill - stop
    arm_price = fill + PROTECTION_ARM_R * risk_price
    armed_at: str | None = None
    target_touch_at: str | None = None
    target_m15: dict[str, Any] | None = None
    target_decided = False
    accepted = False
    runner_stop = stop
    runner_quantity = math.floor(quantity * RUNNER_FRACTION)
    core_quantity = quantity - runner_quantity
    exits: list[dict[str, Any]] = []
    m5_index = 0
    m15_index = 0
    protection_evidence_at: str | None = None
    runner_stop_changes: list[dict[str, Any]] = []
    last_bar = path[-1]

    for bar in path:
        now = bar["open_at"]

        while m5_index < len(m5) and m5[m5_index]["available_at"] <= now:
            completed = m5[m5_index]
            m5_index += 1
            if armed_at is None or target_touch_at is not None or completed["available_at"] < armed_at:
                continue
            state = metadata(m5, completed, "5m")
            swing = state["swing"]
            if swing is None:
                continue
            threshold = float(swing["level"]) - BUFFER_ATR * float(state["atr"])
            if float(completed["close"]) <= threshold:
                protection_evidence_at = completed["available_at"]

        while m15_index < len(m15) and m15[m15_index]["available_at"] <= now:
            completed = m15[m15_index]
            m15_index += 1
            if target_touch_at is None:
                continue
            if target_m15 is not None and completed["open_at"] == target_m15["open_at"]:
                state = metadata(m15, completed, "15m")
                target_decided = True
                accepted = float(completed["close"]) >= target + BUFFER_ATR * float(state["atr"])
                if accepted and runner_quantity:
                    swing = state["swing"]
                    if swing is not None:
                        proposed = float(swing["level"]) - BUFFER_ATR * float(state["atr"])
                        if proposed > runner_stop:
                            runner_stop_changes.append(
                                {"available_at": completed["available_at"], "prior_stop": runner_stop, "new_stop": proposed}
                            )
                            runner_stop = proposed
            elif accepted and runner_quantity and target_m15 is not None and completed["available_at"] > target_m15["available_at"]:
                state = metadata(m15, completed, "15m")
                swing = state["swing"]
                if swing is not None:
                    proposed = float(swing["level"]) - BUFFER_ATR * float(state["atr"])
                    if proposed > runner_stop:
                        runner_stop_changes.append(
                            {"available_at": completed["available_at"], "prior_stop": runner_stop, "new_stop": proposed}
                        )
                        runner_stop = proposed

        if protection_evidence_at is not None and target_touch_at is None:
            exits.append({"quantity": quantity, "price": float(bar["open"]), "at": now, "reason": "M5_PROTECTION_EXIT"})
            return economic_payload(
                fill=fill,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                exits=exits,
                resolution="M5_PROTECTION_EXIT",
                diagnostics={
                    "protection_armed": True,
                    "protection_armed_at": armed_at,
                    "protection_exit": True,
                    "protection_evidence_at": protection_evidence_at,
                    "target_core_realized": False,
                    "target_touch_at": None,
                    "target_accepted": False,
                    "runner_activated": False,
                    "runner_stop_changes": [],
                },
            )

        active_quantity = quantity if target_touch_at is None else runner_quantity
        active_stop = stop if target_touch_at is None or not accepted else runner_stop
        if active_quantity and float(bar["open"]) <= active_stop:
            exits.append({"quantity": active_quantity, "price": float(bar["open"]), "at": now, "reason": "GAP_STOP"})
            return economic_payload(
                fill=fill,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                exits=exits,
                resolution="RUNNER_GAP_STOP" if target_touch_at is not None else "INITIAL_GAP_STOP",
                diagnostics={
                    "protection_armed": armed_at is not None,
                    "protection_armed_at": armed_at,
                    "protection_exit": False,
                    "target_core_realized": target_touch_at is not None,
                    "target_touch_at": target_touch_at,
                    "target_accepted": accepted,
                    "runner_activated": accepted and runner_quantity > 0,
                    "runner_stop_changes": runner_stop_changes,
                },
            )

        if active_quantity and float(bar["low"]) <= active_stop:
            exits.append({"quantity": active_quantity, "price": active_stop, "at": now, "reason": "STOP_FIRST"})
            return economic_payload(
                fill=fill,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                exits=exits,
                resolution="RUNNER_STOP" if target_touch_at is not None else "INITIAL_STOP",
                diagnostics={
                    "protection_armed": armed_at is not None,
                    "protection_armed_at": armed_at,
                    "protection_exit": False,
                    "target_core_realized": target_touch_at is not None,
                    "target_touch_at": target_touch_at,
                    "target_accepted": accepted,
                    "runner_activated": accepted and runner_quantity > 0,
                    "runner_stop_changes": runner_stop_changes,
                },
            )

        if target_touch_at is None and float(bar["high"]) >= target:
            target_touch_at = now
            target_m15 = containing_bar(m15, now)
            exits.append({"quantity": core_quantity, "price": target, "at": now, "reason": "H1_CORE_TARGET"})
            if runner_quantity == 0:
                return economic_payload(
                    fill=fill,
                    quantity=quantity,
                    cost_per_ounce=cost_per_ounce,
                    planned_risk_usd=planned_risk_usd,
                    exits=exits,
                    resolution="H1_TARGET_NO_RUNNER_QUANTITY",
                    diagnostics={
                        "protection_armed": armed_at is not None,
                        "protection_armed_at": armed_at,
                        "protection_exit": False,
                        "target_core_realized": True,
                        "target_touch_at": target_touch_at,
                        "target_accepted": False,
                        "runner_activated": False,
                        "runner_stop_changes": [],
                    },
                )
            if target_m15 is None:
                raise RuntimeError("Target touch did not map to a completed M15 identity")

        if target_touch_at is not None and runner_quantity and target_decided and not accepted:
            exits.append({"quantity": runner_quantity, "price": float(bar["open"]), "at": now, "reason": "TARGET_NO_M15_ACCEPTANCE"})
            return economic_payload(
                fill=fill,
                quantity=quantity,
                cost_per_ounce=cost_per_ounce,
                planned_risk_usd=planned_risk_usd,
                exits=exits,
                resolution="TARGET_NO_M15_ACCEPTANCE",
                diagnostics={
                    "protection_armed": armed_at is not None,
                    "protection_armed_at": armed_at,
                    "protection_exit": False,
                    "target_core_realized": True,
                    "target_touch_at": target_touch_at,
                    "target_accepted": False,
                    "runner_activated": False,
                    "runner_stop_changes": runner_stop_changes,
                },
            )

        if target_touch_at is None and armed_at is None and float(bar["high"]) >= arm_price:
            armed_at = bar["close_at"]

    remaining = quantity if target_touch_at is None else runner_quantity
    if remaining:
        exits.append({"quantity": remaining, "price": float(last_bar["close"]), "at": last_bar["close_at"], "reason": "TIME_EXIT"})
    return economic_payload(
        fill=fill,
        quantity=quantity,
        cost_per_ounce=cost_per_ounce,
        planned_risk_usd=planned_risk_usd,
        exits=exits,
        resolution="RUNNER_TIME_EXIT" if target_touch_at is not None else "TIME_EXIT",
        diagnostics={
            "protection_armed": armed_at is not None,
            "protection_armed_at": armed_at,
            "protection_exit": False,
            "target_core_realized": target_touch_at is not None,
            "target_touch_at": target_touch_at,
            "target_accepted": accepted,
            "runner_activated": accepted and runner_quantity > 0,
            "runner_stop_changes": runner_stop_changes,
        },
    )


def simulate_track_b_reference(
    *,
    stream: dict[str, Any],
    fill_at: str,
    fill: float,
    stop: float,
    target: float,
    quantity: int,
    cost_per_ounce: float,
    planned_risk_usd: float,
    metadata: Callable[[list[dict[str, Any]], dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    """Independent event-table implementation of the same frozen state machine."""

    path = m1_path(stream, fill_at)
    if not path or not stop < fill < target or quantity < 1:
        return invalid_track("INVALID_GEOMETRY")
    m5_rows = sorted(
        [row for row in stream["timeframes"]["5m"] if row.get("complete") is True],
        key=lambda row: (row["available_at"], row["open_at"]),
    )
    m15_rows = sorted(
        [row for row in stream["timeframes"]["15m"] if row.get("complete") is True],
        key=lambda row: (row["available_at"], row["open_at"]),
    )
    m5_events: list[dict[str, Any]] = []
    for row in m5_rows:
        state = metadata(m5_rows, row, "5m")
        swing = state["swing"]
        m5_events.append(
            {
                "available_at": row["available_at"],
                "broken": swing is not None
                and float(row["close"])
                <= float(swing["level"]) - BUFFER_ATR * float(state["atr"]),
            }
        )
    m15_events: list[dict[str, Any]] = []
    for row in m15_rows:
        state = metadata(m15_rows, row, "15m")
        swing = state["swing"]
        m15_events.append(
            {
                "open_at": row["open_at"],
                "available_at": row["available_at"],
                "acceptance_threshold": target + BUFFER_ATR * float(state["atr"]),
                "accepted": float(row["close"])
                >= target + BUFFER_ATR * float(state["atr"]),
                "proposed_stop": None
                if swing is None
                else float(swing["level"]) - BUFFER_ATR * float(state["atr"]),
            }
        )

    arm_price = fill + PROTECTION_ARM_R * (fill - stop)
    runner_quantity = math.floor(quantity * RUNNER_FRACTION)
    core_quantity = quantity - runner_quantity
    armed_at: str | None = None
    target_touch_at: str | None = None
    target_m15_open: str | None = None
    target_m15_available: str | None = None
    target_decided = False
    accepted = False
    runner_stop = stop
    runner_stop_changes: list[dict[str, Any]] = []
    exits: list[dict[str, Any]] = []
    protection_evidence_at: str | None = None
    next_m5 = 0
    next_m15 = 0

    def finish(
        resolution: str,
        *,
        protection_exit: bool = False,
    ) -> dict[str, Any]:
        return economic_payload(
            fill=fill,
            quantity=quantity,
            cost_per_ounce=cost_per_ounce,
            planned_risk_usd=planned_risk_usd,
            exits=exits,
            resolution=resolution,
            diagnostics={
                "protection_armed": armed_at is not None,
                "protection_armed_at": armed_at,
                "protection_exit": protection_exit,
                **(
                    {"protection_evidence_at": protection_evidence_at}
                    if protection_exit
                    else {}
                ),
                "target_core_realized": target_touch_at is not None,
                "target_touch_at": target_touch_at,
                "target_accepted": accepted,
                "runner_activated": accepted and runner_quantity > 0,
                "runner_stop_changes": runner_stop_changes,
            },
        )

    for minute in path:
        now = minute["open_at"]
        while next_m5 < len(m5_events) and m5_events[next_m5]["available_at"] <= now:
            event = m5_events[next_m5]
            next_m5 += 1
            if (
                armed_at is not None
                and target_touch_at is None
                and event["available_at"] >= armed_at
                and event["broken"]
            ):
                protection_evidence_at = event["available_at"]

        while next_m15 < len(m15_events) and m15_events[next_m15]["available_at"] <= now:
            event = m15_events[next_m15]
            next_m15 += 1
            if target_touch_at is None or target_m15_open is None:
                continue
            is_touch_bar = event["open_at"] == target_m15_open
            is_later_bar = (
                accepted
                and target_m15_available is not None
                and event["available_at"] > target_m15_available
            )
            if is_touch_bar:
                target_decided = True
                accepted = bool(event["accepted"])
                target_m15_available = event["available_at"]
            if (is_touch_bar and accepted) or is_later_bar:
                proposed = event["proposed_stop"]
                if proposed is not None and float(proposed) > runner_stop:
                    runner_stop_changes.append(
                        {
                            "available_at": event["available_at"],
                            "prior_stop": runner_stop,
                            "new_stop": float(proposed),
                        }
                    )
                    runner_stop = float(proposed)

        if protection_evidence_at is not None and target_touch_at is None:
            exits.append(
                {
                    "quantity": quantity,
                    "price": float(minute["open"]),
                    "at": now,
                    "reason": "M5_PROTECTION_EXIT",
                }
            )
            return finish("M5_PROTECTION_EXIT", protection_exit=True)

        active_quantity = quantity if target_touch_at is None else runner_quantity
        active_stop = stop if target_touch_at is None or not accepted else runner_stop
        if active_quantity and float(minute["open"]) <= active_stop:
            exits.append(
                {
                    "quantity": active_quantity,
                    "price": float(minute["open"]),
                    "at": now,
                    "reason": "GAP_STOP",
                }
            )
            return finish(
                "RUNNER_GAP_STOP" if target_touch_at is not None else "INITIAL_GAP_STOP"
            )
        if active_quantity and float(minute["low"]) <= active_stop:
            exits.append(
                {
                    "quantity": active_quantity,
                    "price": active_stop,
                    "at": now,
                    "reason": "STOP_FIRST",
                }
            )
            return finish("RUNNER_STOP" if target_touch_at is not None else "INITIAL_STOP")

        if target_touch_at is None and float(minute["high"]) >= target:
            target_touch_at = now
            containing = containing_bar(m15_rows, now)
            if containing is None:
                raise RuntimeError("Reference target touch did not map to M15")
            target_m15_open = containing["open_at"]
            target_m15_available = containing["available_at"]
            exits.append(
                {
                    "quantity": core_quantity,
                    "price": target,
                    "at": now,
                    "reason": "H1_CORE_TARGET",
                }
            )
            if runner_quantity == 0:
                return finish("H1_TARGET_NO_RUNNER_QUANTITY")

        if target_touch_at is not None and runner_quantity and target_decided and not accepted:
            exits.append(
                {
                    "quantity": runner_quantity,
                    "price": float(minute["open"]),
                    "at": now,
                    "reason": "TARGET_NO_M15_ACCEPTANCE",
                }
            )
            return finish("TARGET_NO_M15_ACCEPTANCE")

        if target_touch_at is None and armed_at is None and float(minute["high"]) >= arm_price:
            armed_at = minute["close_at"]

    remaining = quantity if target_touch_at is None else runner_quantity
    final = path[-1]
    if remaining:
        exits.append(
            {
                "quantity": remaining,
                "price": float(final["close"]),
                "at": final["close_at"],
                "reason": "TIME_EXIT",
            }
        )
    return finish("RUNNER_TIME_EXIT" if target_touch_at is not None else "TIME_EXIT")


def summary(cases: list[dict[str, Any]], key: str) -> dict[str, Any]:
    rows = [row[key] for row in cases if row[key]["executable"]]
    gains = [float(row["net_r50"]) for row in rows if float(row["net_r50"]) > 0]
    losses = [-float(row["net_r50"]) for row in rows if float(row["net_r50"]) < 0]
    equity = peak = drawdown = 0.0
    for row in sorted(cases, key=lambda item: item["decision_at"]):
        if not row[key]["executable"]:
            continue
        equity += float(row[key]["net_r50"])
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "population": len(cases),
        "executable": len(rows),
        "wins": len(gains),
        "win_rate": len(gains) / len(rows) if rows else None,
        "net_r50": sum(float(row["net_r50"]) for row in rows),
        "net_usd": sum(float(row["net_usd"]) for row in rows),
        "expectancy_r50": sum(float(row["net_r50"]) for row in rows) / len(rows) if rows else None,
        "profit_factor": sum(gains) / sum(losses) if losses else None,
        "maximum_drawdown_r50": drawdown,
        "resolution_counts": dict(sorted(Counter(row["resolution"] for row in rows).items())),
    }


def recompute_control(
    base_case: dict[str, Any], stream: dict[str, Any], human: dict[str, Any]
) -> dict[str, Any]:
    if not base_case["structural_eligibility"]:
        return base_case["h1_fixed_control"]
    quantity = int(base_case["quantity_ounces"])
    cost = float(base_case["h1_fixed_control"]["cost_usd"]) / quantity
    return simulate_fixed(
        stream=stream,
        fill_at=human["fill_at"],
        fill=float(base_case["actual_fill"]),
        stop=float(base_case["reconstructed_stop"]),
        target=float(base_case["original_h1_target"]),
        quantity=quantity,
        cost_per_ounce=cost,
        planned_risk_usd=float(base_case["planned_risk_usd"]),
        label="H1_CONTROL",
    )


def analyze(
    simulator: Callable[..., dict[str, Any]],
    metadata: Callable[[list[dict[str, Any]], dict[str, Any], str], dict[str, Any]],
) -> dict[str, Any]:
    base = json.loads(BASE_RESULT.read_text(encoding="utf-8"))
    comparison = json.loads(COMPARISON.read_text(encoding="utf-8"))
    human_by_alias = {
        row["case_alias"]: row["human"]
        for row in comparison["cases"]
        if row["human"]["is_trade"]
    }
    cases: list[dict[str, Any]] = []
    control_gate = True
    for base_case in base["cases"]:
        alias = base_case["case_alias"]
        human = human_by_alias[alias]
        stream = load_stream(base_case["source"])
        recomputed = round_floats(recompute_control(base_case, stream, human))
        sealed_control = base_case["h1_fixed_control"]
        comparable = (
            recomputed["resolution"] == sealed_control["resolution"]
            and abs(float(recomputed["net_r50"]) - float(sealed_control["net_r50"])) <= 1e-8
            and abs(float(recomputed["net_usd"]) - float(sealed_control["net_usd"]))
            <= CONTROL_USD_TOLERANCE
        )
        control_gate = control_gate and comparable
        if not base_case["structural_eligibility"]:
            challenger = invalid_track(str(base_case["structural_failure"]))
        else:
            quantity = int(base_case["quantity_ounces"])
            cost = float(sealed_control["cost_usd"]) / quantity
            challenger = simulator(
                stream=stream,
                fill_at=human["fill_at"],
                fill=float(base_case["actual_fill"]),
                stop=float(base_case["reconstructed_stop"]),
                target=float(base_case["original_h1_target"]),
                quantity=quantity,
                cost_per_ounce=cost,
                planned_risk_usd=float(base_case["planned_risk_usd"]),
                metadata=metadata,
            )
        challenger = round_floats(challenger)
        delta = float(challenger["net_r50"]) - float(sealed_control["net_r50"])
        cases.append(
            {
                "case_alias": alias,
                "decision_at": base_case["decision_at"],
                "terminal_direction_correct": base_case["terminal_direction_correct"],
                "structural_eligibility": base_case["structural_eligibility"],
                "structural_failure": base_case["structural_failure"],
                "original_recorded_r50": base_case["original_recorded_r50"],
                "fixed_h1_control": sealed_control,
                "control_reproduction_exact": comparable,
                "frozen_track_b": challenger,
                "incremental_r50": delta,
                "comparison": "IMPROVED" if delta > 1e-8 else "DEGRADED" if delta < -1e-8 else "UNCHANGED",
                "audit_groups": {
                    "correct_direction_round_trip": alias in CORRECT_DIRECTION_ROUND_TRIPS,
                    "large_control_winner": alias in LARGE_CONTROL_WINNERS,
                    "known_direction_wrong": alias in KNOWN_DIRECTION_WRONG,
                },
            }
        )
    return round_floats(
        {
            "version": "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_V1_RESULT_1_0",
            "evidence_status": "POST_RESULT_ZERO_CREDIT_CALIBRATION_REGRESSION",
            "population": len(cases),
            "control_reproduction_exact": control_gate,
            "summaries": {
                "fixed_h1_control": summary(cases, "fixed_h1_control"),
                "frozen_track_b": summary(cases, "frozen_track_b"),
            },
            "cases": cases,
            "calendar_2025": "LOCKED_NOT_ACCESSED",
            "calendar_2026": "LOCKED_NOT_ACCESSED",
        }
    )


def add_attribution(payload: dict[str, Any]) -> dict[str, Any]:
    cases = payload["cases"]
    by_alias = {row["case_alias"]: row for row in cases}
    payload["correction_capture"] = {
        "correct_direction_round_trips": [
            {
                "case_alias": alias,
                "control_r50": by_alias[alias]["fixed_h1_control"]["net_r50"],
                "track_b_r50": by_alias[alias]["frozen_track_b"]["net_r50"],
                "incremental_r50": by_alias[alias]["incremental_r50"],
                "addressed": by_alias[alias]["incremental_r50"] > 0,
            }
            for alias in sorted(CORRECT_DIRECTION_ROUND_TRIPS)
        ],
        "large_control_winners": [
            {
                "case_alias": alias,
                "control_r50": by_alias[alias]["fixed_h1_control"]["net_r50"],
                "track_b_r50": by_alias[alias]["frozen_track_b"]["net_r50"],
                "incremental_r50": by_alias[alias]["incremental_r50"],
                "remained_positive": by_alias[alias]["frozen_track_b"]["net_r50"] > 0,
            }
            for alias in sorted(LARGE_CONTROL_WINNERS)
        ],
        "known_direction_wrong": [
            {
                "case_alias": alias,
                "control_r50": by_alias[alias]["fixed_h1_control"]["net_r50"],
                "track_b_r50": by_alias[alias]["frozen_track_b"]["net_r50"],
                "mechanically_rejected_before_entry": False,
            }
            for alias in sorted(KNOWN_DIRECTION_WRONG)
        ],
        "discretionary_taxonomy_coverage": {
            "CBR-2022-007": ["controlling_h4_state", "location_assessment"],
            "CBR-2022-009": ["auction_family", "controlling_h4_state", "location_assessment"],
            "CBR-2022-019": ["auction_family", "controlling_h4_state", "macro_override_reason"],
            "CBR-2022-026": ["auction_family", "controlling_h4_state", "location_assessment", "macro_override_reason"],
            "automatic_entry_rejection": False,
            "status": "FIELDS_SURFACE_THE_CONFLICTS_BUT_DO_NOT_MECHANICALLY_CATCH_THEM",
        },
    }
    return round_floats(payload)


def write_table(payload: dict[str, Any]) -> None:
    fields = [
        "case_alias",
        "terminal_direction_correct",
        "structural_eligibility",
        "structural_failure",
        "original_recorded_r50",
        "fixed_h1_control_r50",
        "track_b_r50",
        "incremental_r50",
        "comparison",
        "protection_armed",
        "protection_exit",
        "target_core_realized",
        "target_accepted",
        "runner_activated",
        "track_b_resolution",
        "correct_direction_round_trip",
        "large_control_winner",
        "known_direction_wrong",
    ]
    if TABLE.exists():
        raise RuntimeError("Append-only regression table already exists")
    with TABLE.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in payload["cases"]:
            track = row["frozen_track_b"]
            writer.writerow(
                {
                    "case_alias": row["case_alias"],
                    "terminal_direction_correct": row["terminal_direction_correct"],
                    "structural_eligibility": row["structural_eligibility"],
                    "structural_failure": row["structural_failure"],
                    "original_recorded_r50": row["original_recorded_r50"],
                    "fixed_h1_control_r50": row["fixed_h1_control"]["net_r50"],
                    "track_b_r50": track["net_r50"],
                    "incremental_r50": row["incremental_r50"],
                    "comparison": row["comparison"],
                    "protection_armed": track.get("protection_armed", False),
                    "protection_exit": track.get("protection_exit", False),
                    "target_core_realized": track.get("target_core_realized", False),
                    "target_accepted": track.get("target_accepted", False),
                    "runner_activated": track.get("runner_activated", False),
                    "track_b_resolution": track["resolution"],
                    **row["audit_groups"],
                }
            )


def run() -> dict[str, Any]:
    frozen = verify_freeze()
    for path in (RESULT, TABLE, REPRODUCTION, SEAL):
        if path.exists():
            raise RuntimeError(f"Append-only regression output exists: {path.relative_to(ROOT)}")
    primary = add_attribution(analyze(simulate_track_b, primary_completed_metadata))
    reference = add_attribution(
        analyze(simulate_track_b_reference, reference_completed_metadata)
    )
    primary_hash = canonical_hash(primary)
    reference_hash = canonical_hash(reference)
    if primary_hash != reference_hash:
        raise RuntimeError(
            f"Independent exposed regressions differ: {primary_hash} != {reference_hash}"
        )
    if not primary["control_reproduction_exact"]:
        raise RuntimeError("The sealed fixed-H1 control did not reproduce")
    if primary["population"] != 16:
        raise RuntimeError("The complete 16-case population was not retained")
    write_new_json(RESULT, primary)
    write_table(primary)
    reproduction = {
        "version": "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_V1_REPRODUCTION_1_0",
        "status": "PASS_EXACT_PRIMARY_REFERENCE_REPRODUCTION",
        "primary_payload_sha256": primary_hash,
        "reference_payload_sha256": reference_hash,
        "case_count": 16,
        "case_rows_exact": primary["cases"] == reference["cases"],
        "summary_exact": primary["summaries"] == reference["summaries"],
    }
    write_new_json(REPRODUCTION, reproduction)
    seal = {
        "version": "GOLD_COHERENT_AUCTION_EXPOSED_POLICY_REGRESSION_V1_FINAL_SEAL_1_0",
        "verdict": "MECHANICAL_REGRESSION_PASS",
        "evidence_status": "POST_RESULT_ZERO_CREDIT_CALIBRATION_REGRESSION",
        "pre_run_freeze": file_record(AMENDED_FREEZE_B),
        "result": file_record(RESULT),
        "case_table": file_record(TABLE),
        "independent_reproduction": file_record(REPRODUCTION),
        "frozen_input_sha256": canonical_hash(frozen),
        "fresh_50_case_decisions_opened": False,
        "calendar_2025": "LOCKED_NOT_ACCESSED",
        "calendar_2026": "LOCKED_NOT_ACCESSED",
        "charge_usd": 0.0,
    }
    write_new_json(SEAL, seal)
    return primary


def main() -> int:
    parser = argparse.ArgumentParser()
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--freeze", dest="mode", action="store_const", const="--freeze")
    group.add_argument(
        "--freeze-amendment-a",
        dest="mode",
        action="store_const",
        const="--freeze-amendment-a",
    )
    group.add_argument(
        "--freeze-amendment-b",
        dest="mode",
        action="store_const",
        const="--freeze-amendment-b",
    )
    group.add_argument("--run", dest="mode", action="store_const", const="--run")
    args = parser.parse_args()
    if args.mode == "--freeze":
        payload = freeze()
    elif args.mode == "--freeze-amendment-a":
        payload = freeze_amendment_a()
    elif args.mode == "--freeze-amendment-b":
        payload = freeze_amendment_b()
    else:
        payload = run()
    if args.mode in {"--freeze", "--freeze-amendment-a", "--freeze-amendment-b"}:
        print(json.dumps({"status": payload["status"], "population_count": payload["population_count"]}, indent=2))
    else:
        print(json.dumps({"summaries": payload["summaries"], "correction_capture": payload["correction_capture"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
