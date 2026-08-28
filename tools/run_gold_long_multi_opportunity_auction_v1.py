#!/usr/bin/env python3
"""Checkpointed exposed LONG multi-opportunity and management regression."""

from __future__ import annotations

import argparse
import copy
import json
import math
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_family_router_exposed_regression_v1 as router  # noqa: E402
import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    materialize_case,
    predict_class,
    predict_class_probability,
    predict_regression,
    prepare_features,
    require,
    sha256_file,
    transform_rows,
)
from gold_intel.analytics.auction_family_router_v1_r1 import (  # noqa: E402
    corrected_router_lifecycle,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    iso,
    parse_dt,
    structural_breaks,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    simulate_track,
)
from gold_intel.analytics.long_multi_opportunity_auction_v1 import (  # noqa: E402
    LONG_SIGNAL_THRESHOLD,
    REARM_BELOW_MINUTES,
    build_structural_cache,
    non_overlapping,
    signal_episodes,
    simulate_structural_long,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    classify_autonomous,
    first_m1_after,
    latest_m1_at,
    spread,
)


CONTRACT = ROOT / "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_LIFECYCLE_AND_STRUCTURAL_PROFIT_PROTECTION_RESEARCH_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "long_multi_opportunity_auction_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_long_multi_opportunity_auction_v1.py"
RUNNER = Path(__file__).resolve()
TRANSLATOR = ROOT / "research_artifacts" / "gold_coherent_auction_end_to_end_same_month_v1" / "translator.json"
ROUTER_RESULT = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1" / "final_result.json"
ROUTER_SEAL = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1" / "final_seal.json"
CONTROL_RESULT = ROOT / "research_artifacts" / "gold_auction_family_router_v1_r1_mechanical_correction" / "final_result.json"
CONTROL_SEAL = ROOT / "research_artifacts" / "gold_auction_family_router_v1_r1_mechanical_correction" / "final_seal.json"

OUT = ROOT / "research_artifacts" / "gold_long_multi_opportunity_auction_v1"
FREEZE = OUT / "precalculation_freeze.json"
STATUS_FILE = OUT / "status.json"
CHECKPOINT_ROOT = OUT / "checkpoints"
FINAL = OUT / "final_result.json"
SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_LIFECYCLE_AND_STRUCTURAL_PROFIT_PROTECTION_RESEARCH_V1_REPORT.md"

SIDES = ("primary", "reference")
TRACKS = (
    "FROZEN_LONG_CONTROL",
    "MULTI_OPPORTUNITY_CONTROL_MANAGEMENT",
    "FIRST_OPPORTUNITY_STRUCTURAL_MANAGEMENT",
    "MULTI_OPPORTUNITY_STRUCTURAL_MANAGEMENT",
)
EPSILON = 1e-12


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    require(not path.exists(), f"Append-only output appeared concurrently: {path}")
    os.replace(temporary, path)


def write_new_text(path: Path, value: str) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    require(not path.exists(), f"Append-only output appeared concurrently: {path}")
    os.replace(temporary, path)


def write_status(payload: dict[str, Any]) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    enriched = {**payload, "updated_at": now()}
    temporary = STATUS_FILE.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(enriched, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, STATUS_FILE)


def source_rows() -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    controls = baseline.control_rows()
    router_rows = load_json(ROUTER_RESULT)["rows"]
    corrected_rows = load_json(CONTROL_RESULT)["rows"]
    router_by_alias = {str(row["case_alias"]): row for row in router_rows}
    corrected_by_alias = {str(row["case_alias"]): row for row in corrected_rows}
    aliases = [str(row["case_alias"]) for row in controls]
    require(len(aliases) == 95 and len(set(aliases)) == 95, "Control population differs")
    require(set(aliases) == set(router_by_alias) == set(corrected_by_alias), "Predecessor identities differ")
    return controls, router_by_alias, corrected_by_alias


def synthetic_proof() -> dict[str, Any]:
    rows = [
        {"checkpoint_at": f"2022-01-03T13:{minute:02d}:00Z", "session": "NEW_YORK"}
        for minute in range(32)
    ]
    probabilities = [0.95] + [0.10] * 15 + [0.95] * 16
    identities = ["A"] * 20 + ["B"] * 12
    emitted = signal_episodes(rows, probabilities, structure_identities=identities)
    checks = {
        "threshold_episode_count": len(emitted) == 3,
        "first_rearmed_at_16": emitted[1]["checkpoint_at"].endswith("13:16:00Z"),
        "new_structure_at_20": emitted[2]["checkpoint_at"].endswith("13:20:00Z"),
    }
    accepted, audited = non_overlapping(
        [
            {"signal_at": "2022-01-03T13:00:00Z", "result": {"executed": True, "final_at": "2022-01-03T13:10:00Z"}},
            {"signal_at": "2022-01-03T13:05:00Z", "result": {"executed": True, "final_at": "2022-01-03T13:15:00Z"}},
            {"signal_at": "2022-01-03T13:11:00Z", "result": {"executed": True, "final_at": "2022-01-03T13:20:00Z"}},
        ]
    )
    checks["overlap_policy"] = len(accepted) == 2 and audited[1]["portfolio_disposition"] == "OVERLAP_EXISTING_POSITION"
    require(all(checks.values()), f"Synthetic proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    baseline.verify_static_inputs()
    controls, router_by_alias, corrected_by_alias = source_rows()
    files = [CONTRACT, IMPLEMENTATION, TESTS, RUNNER, TRANSLATOR, ROUTER_RESULT, ROUTER_SEAL, CONTROL_RESULT, CONTROL_SEAL]
    require(all(path.is_file() for path in files), "A required predecessor is absent")
    identities = [
        {
            "ordinal": index,
            "case_alias": str(row["case_alias"]),
            "trading_date_utc": str(row["trading_date_utc"]),
            "control_row_sha256": str(corrected_by_alias[str(row["case_alias"])]["row_sha256"]),
            "router_row_sha256": str(router_by_alias[str(row["case_alias"])]["row_sha256"]),
        }
        for index, row in enumerate(controls, start=1)
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_EXPOSED_MULTI_OPPORTUNITY_PATH_CALCULATION",
        "files": [file_record(path) for path in files],
        "population": identities,
        "population_sha256": canonical_hash(identities),
        "translator_threshold": LONG_SIGNAL_THRESHOLD,
        "rearm_below_minutes": REARM_BELOW_MINUTES,
        "additional_opportunity_session": "NEW_YORK",
        "directions": ["LONG"],
        "tracks": list(TRACKS),
        "synthetic_proof": synthetic_proof(),
        "checkpoint_policy": {
            "immutable_record_per_day_and_pass": True,
            "hash_chained": True,
            "resumable": True,
            "primary_then_reference": True,
            "progress_after_every_day": True,
        },
        "random_50_cases_opened": False,
        "february_17_28_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "short_branch_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    write_status(
        {
            "phase": "FROZEN_READY",
            "active_pass": None,
            "completed_primary": 0,
            "completed_reference": 0,
            "remaining_total": 190,
            "last_checkpoint": None,
        }
    )
    print(json.dumps({"status": payload["status"], "days": 95, "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Freeze is absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Freeze payload differs")
    payload["freeze_sha256"] = submitted
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen file size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen file hash differs: {path}")
    controls, _, corrected = source_rows()
    observed = [
        {
            "ordinal": index,
            "case_alias": str(row["case_alias"]),
            "trading_date_utc": str(row["trading_date_utc"]),
            "control_row_sha256": str(corrected[str(row["case_alias"])]["row_sha256"]),
            "router_row_sha256": next(
                item["router_row_sha256"]
                for item in payload["population"]
                if item["case_alias"] == str(row["case_alias"])
            ),
        }
        for index, row in enumerate(controls, start=1)
    ]
    require(observed == payload["population"], "Frozen population differs")
    return payload


def checkpoint_path(side: str, ordinal: int, alias: str) -> Path:
    return CHECKPOINT_ROOT / side / f"{ordinal:03d}_{alias}.json"


def verify_checkpoint_chain(side: str, frozen: dict[str, Any]) -> list[dict[str, Any]]:
    require(side in SIDES, f"Unknown side: {side}")
    records: list[dict[str, Any]] = []
    prior = str(frozen["freeze_sha256"])
    for identity in frozen["population"]:
        path = checkpoint_path(side, int(identity["ordinal"]), str(identity["case_alias"]))
        if not path.exists():
            break
        record = load_json(path)
        submitted = record.pop("checkpoint_sha256")
        require(canonical_hash(record) == submitted, f"Checkpoint differs: {path}")
        record["checkpoint_sha256"] = submitted
        require(record["side"] == side, f"Checkpoint side differs: {path}")
        require(int(record["ordinal"]) == int(identity["ordinal"]), f"Checkpoint ordinal differs: {path}")
        require(record["case_alias"] == identity["case_alias"], f"Checkpoint identity differs: {path}")
        require(record["previous_checkpoint_sha256"] == prior, f"Checkpoint chain differs: {path}")
        require(record["row_sha256"] == canonical_hash(record["row"]), f"Checkpoint row differs: {path}")
        prior = submitted
        records.append(record)
    directory = CHECKPOINT_ROOT / side
    if directory.exists():
        require(len(list(directory.glob("*.json"))) == len(records), f"Noncontiguous checkpoint files: {side}")
    return records


def status_payload(frozen: dict[str, Any]) -> dict[str, Any]:
    primary = verify_checkpoint_chain("primary", frozen)
    reference = verify_checkpoint_chain("reference", frozen)
    completed = len(primary) + len(reference)
    if FINAL.exists() and SEAL.exists():
        phase = "COMPLETE"
        active = None
    elif FINAL.exists():
        phase = "FINALIZATION_INCOMPLETE"
        active = None
    elif len(primary) < 95:
        phase = "PRIMARY_PENDING_OR_RUNNING"
        active = "primary"
    elif len(reference) < 95:
        phase = "REFERENCE_PENDING_OR_RUNNING"
        active = "reference"
    else:
        phase = "READY_TO_FINALIZE"
        active = None
    last = None
    pool = [("primary", row) for row in primary] + [("reference", row) for row in reference]
    if pool:
        side, row = pool[-1]
        last = {
            "side": side,
            "ordinal": row["ordinal"],
            "case_alias": row["case_alias"],
            "trading_date_utc": row["trading_date_utc"],
            "checkpoint_sha256": row["checkpoint_sha256"],
        }
    return {
        "phase": phase,
        "active_pass": active,
        "completed_primary": len(primary),
        "completed_reference": len(reference),
        "remaining_total": 190 - completed,
        "last_checkpoint": last,
        "final_exists": FINAL.exists(),
        "sealed": SEAL.exists(),
    }


def print_status() -> None:
    frozen = verify_freeze()
    payload = status_payload(frozen)
    if STATUS_FILE.exists():
        payload["runtime_status"] = load_json(STATUS_FILE)
    print(json.dumps(payload, indent=2, sort_keys=True))


def m15_structure_identities(stream: dict[str, Any], checkpoints: list[dict[str, Any]]) -> list[str | None]:
    events = structural_breaks(
        stream["timeframes"]["15m"], stream["end_exclusive"], "M15", "LONG"
    )
    bars = complete_rows(stream["timeframes"]["15m"], stream["end_exclusive"])
    intervals: list[tuple[dict[str, Any], datetime | None]] = []
    for event in events:
        invalidated_at = next(
            (
                parse_dt(bar["available_at"])
                for bar in bars
                if parse_dt(bar["available_at"]) > parse_dt(event["break_at"])
                and float(bar["close"])
                < float(event["protected_level"]) - float(event["buffer"])
            ),
            None,
        )
        intervals.append((event, invalidated_at))
    identities: list[str | None] = []
    for checkpoint in checkpoints:
        point = parse_dt(checkpoint["checkpoint_at"])
        active = [
            event
            for event, invalidated_at in intervals
            if parse_dt(event["break_at"]) <= point
            and (invalidated_at is None or point < invalidated_at)
        ]
        identities.append(None if not active else str(active[-1]["identity"]))
    return identities


def candidate_from_episode(
    *,
    episode: dict[str, Any],
    stream: dict[str, Any],
    translator: dict[str, Any],
    structural_cache: dict[str, Any],
) -> dict[str, Any]:
    signal_row = episode["checkpoint"]
    matrix = transform_rows([signal_row], translator["preprocessing"])
    geometry_model = translator["geometry"]
    stop_distance = float(predict_regression(geometry_model["stop_distance_tree"], matrix)[0])
    target_distance = float(predict_regression(geometry_model["target_distance_tree"], matrix)[0])
    family = str(predict_class(geometry_model["family_tree"], matrix)[0])
    reference = float(signal_row["m1_reference_close"])
    atr = float(signal_row["m15_atr_scale"])
    stop = reference - stop_distance * atr
    target = reference + target_distance * atr
    signal_at = str(signal_row["checkpoint_at"])
    fill_bar = first_m1_after(stream, signal_at)
    decision_bar = latest_m1_at(stream, signal_at)
    require(fill_bar is not None and decision_bar is not None, "Candidate execution bars absent")
    fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + 0.05
    cost = spread(decision_bar) + 0.10
    classification = classify_autonomous(
        stream=stream,
        signal_at=signal_at,
        family=family,
        fill=fill,
        stop=stop,
        target=target,
        cost_per_ounce=cost,
    )
    raw = simulate_track(
        classification=classification,
        stream=stream,
        fill_at=iso(fill_bar["open_at"]),
        track="COMPLETE_V2_POLICY",
    )
    control = {
        "case_alias": str(stream["case_alias"]),
        "trading_date_utc": str(stream["trading_date_utc"]),
        "signal_at": signal_at,
        "signal_probability": float(episode["probability"]),
        "geometry": {
            "reference_close": reference,
            "m15_atr": atr,
            "stop_distance_atr": stop_distance,
            "target_distance_atr": target_distance,
            "family": family,
            "fill_at": iso(fill_bar["open_at"]),
            "fill": fill,
            "stop": stop,
            "target": target,
            "cost_per_ounce": cost,
        },
        "classification": classification,
        "result": raw,
    }
    lifecycle = router.family_lifecycle(control=control, stream=stream)
    corrected = corrected_router_lifecycle(lifecycle)
    structural = None
    if corrected.get("effective_result") is not None and corrected["effective_result"].get("executed"):
        structural = simulate_structural_long(
            classification=lifecycle["classification"],
            stream=stream,
            fill_at=str(lifecycle["geometry"]["fill_at"]),
            structure_cache=structural_cache,
        )
    payload = {
        "episode": int(episode["episode"]),
        "episode_identity": str(episode["episode_identity"]),
        "emission_reason": str(episode["emission_reason"]),
        "m15_structure_identity": episode["m15_structure_identity"],
        "signal_at": signal_at,
        "signal_probability": float(episode["probability"]),
        "family": family,
        "classification": classification,
        "geometry": control["geometry"],
        "router": lifecycle,
        "corrected": corrected,
        "result": corrected.get("effective_result"),
        "structural_result": structural,
    }
    payload["opportunity_sha256"] = canonical_hash(payload)
    return payload


def _track_payload(trades: list[dict[str, Any]]) -> dict[str, Any]:
    values = [float(row["net_r50"]) for row in trades]
    return {
        "trades": trades,
        "trade_count": len(trades),
        "net_r": sum(values),
        "net_usd": sum(float(row["net_usd"]) for row in trades),
        "stressed_net_r": sum(float(row["stressed_1_5x_cost_r50"]) for row in trades),
    }


def process_day(
    *,
    stream: dict[str, Any],
    prepared: dict[str, Any],
    translator: dict[str, Any],
    source_router: dict[str, Any],
    source_corrected: dict[str, Any],
) -> dict[str, Any]:
    checkpoints = materialize_case(
        alias=str(stream["case_alias"]), stream=stream, prepared=prepared, end_at=None
    )
    matrix = transform_rows(checkpoints, translator["preprocessing"])
    probabilities = predict_class_probability(
        translator["semantic"]["tree"], matrix, positive_class=1
    ).astype(float).tolist()
    structure_ids = m15_structure_identities(stream, checkpoints)
    structural_cache = build_structural_cache(stream)
    episodes = signal_episodes(
        checkpoints,
        probabilities,
        structure_identities=structure_ids,
        session="NEW_YORK",
        threshold=LONG_SIGNAL_THRESHOLD,
        rearm_below_minutes=REARM_BELOW_MINUTES,
    )
    candidates = [
        candidate_from_episode(
            episode=episode,
            stream=stream,
            translator=translator,
            structural_cache=structural_cache,
        )
        for episode in episodes
    ]

    original_signal = source_router["control"].get("signal_at")
    if original_signal is not None and baseline.signal_session(str(original_signal)) == "NEW_YORK":
        exact = [row for row in candidates if row["signal_at"] == original_signal]
        require(len(exact) == 1, f"Original New York signal did not reproduce: {stream['case_alias']}")
        require(
            exact[0]["corrected"] == source_corrected["corrected"],
            f"Original corrected lifecycle differs: {stream['case_alias']}",
        )

    original = source_corrected["corrected"].get("effective_result")
    original_trades = [copy.deepcopy(original)] if original is not None and original.get("executed") else []
    original_until = None if not original_trades else str(original_trades[0]["final_at"])
    additional_baseline_pool = [
        {**row, "result": row.get("result")}
        for row in candidates
        if row["signal_at"] != original_signal
    ]
    accepted_baseline, audited_baseline = non_overlapping(
        additional_baseline_pool, occupied_until=original_until
    )
    multi_trades = original_trades + [copy.deepcopy(row["result"]) for row in accepted_baseline]

    original_structural: list[dict[str, Any]] = []
    if original_trades:
        lifecycle = source_router["family_router"]
        original_structural = [
            simulate_structural_long(
                classification=lifecycle["classification"],
                stream=stream,
                fill_at=str(lifecycle["geometry"]["fill_at"]),
                structure_cache=structural_cache,
            )
        ]
    structural_until = None if not original_structural else str(original_structural[0]["final_at"])
    additional_structural_pool = [
        {**row, "result": row.get("structural_result")}
        for row in candidates
        if row["signal_at"] != original_signal
    ]
    accepted_structural, audited_structural = non_overlapping(
        additional_structural_pool, occupied_until=structural_until
    )
    combined_trades = original_structural + [copy.deepcopy(row["result"]) for row in accepted_structural]

    tracks = {
        "FROZEN_LONG_CONTROL": _track_payload(original_trades),
        "MULTI_OPPORTUNITY_CONTROL_MANAGEMENT": _track_payload(multi_trades),
        "FIRST_OPPORTUNITY_STRUCTURAL_MANAGEMENT": _track_payload(original_structural),
        "MULTI_OPPORTUNITY_STRUCTURAL_MANAGEMENT": _track_payload(combined_trades),
    }
    payload: dict[str, Any] = {
        "case_alias": str(stream["case_alias"]),
        "trading_date_utc": str(stream["trading_date_utc"]),
        "original_signal_at": original_signal,
        "original_session": None if original_signal is None else baseline.signal_session(str(original_signal)),
        "emitted_opportunities": candidates,
        "baseline_opportunity_audit": audited_baseline,
        "structural_opportunity_audit": audited_structural,
        "tracks": tracks,
        "shorts_evaluated": False,
    }
    payload["row_sha256"] = canonical_hash(payload)
    return payload


def append_checkpoint(
    *,
    side: str,
    identity: dict[str, Any],
    row: dict[str, Any],
    prior_sha256: str,
    frozen: dict[str, Any],
) -> dict[str, Any]:
    record: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_DAY_CHECKPOINT_1_0",
        "created_at": now(),
        "side": side,
        "ordinal": int(identity["ordinal"]),
        "case_alias": str(identity["case_alias"]),
        "trading_date_utc": str(identity["trading_date_utc"]),
        "freeze_sha256": str(frozen["freeze_sha256"]),
        "previous_checkpoint_sha256": prior_sha256,
        "row": row,
        "row_sha256": canonical_hash(row),
        "cumulative_completed": int(identity["ordinal"]),
    }
    record["checkpoint_sha256"] = canonical_hash(record)
    write_new_json(
        checkpoint_path(side, int(identity["ordinal"]), str(identity["case_alias"])),
        record,
    )
    return record


def run(max_days: int | None) -> None:
    frozen = verify_freeze()
    if FINAL.exists():
        finalize()
        return
    controls, router_by_alias, corrected_by_alias = source_rows()
    translator = load_json(TRANSLATOR)
    require(float(translator["semantic"]["threshold"]) == LONG_SIGNAL_THRESHOLD, "Translator threshold differs")
    processed_this_run = 0
    for side in SIDES:
        completed = verify_checkpoint_chain(side, frozen)
        if len(completed) == 95:
            continue
        write_status(
            {
                **status_payload(frozen),
                "phase": "LOADING_SEALED_STREAMS",
                "active_pass": side,
                "pid": os.getpid(),
                "next_ordinal": len(completed) + 1,
            }
        )
        print(f"[{now()}] {side}: loading sealed streams", flush=True)
        streams = baseline.load_all_streams(side)
        write_status(
            {
                **status_payload(frozen),
                "phase": "PREPARING_POINT_IN_TIME_FEATURES",
                "active_pass": side,
                "pid": os.getpid(),
                "next_ordinal": len(completed) + 1,
            }
        )
        print(f"[{now()}] {side}: preparing shared point-in-time features", flush=True)
        prepared = prepare_features(streams.values())
        prior = str(frozen["freeze_sha256"]) if not completed else str(completed[-1]["checkpoint_sha256"])
        for identity, control in zip(frozen["population"], controls, strict=True):
            ordinal = int(identity["ordinal"])
            if ordinal <= len(completed):
                continue
            if max_days is not None and processed_this_run >= max_days:
                write_status({**status_payload(frozen), "phase": "PAUSED_AT_REQUESTED_CHECKPOINT_LIMIT", "active_pass": None})
                print_status()
                return
            alias = str(identity["case_alias"])
            require(alias == str(control["case_alias"]), "Population order differs")
            write_status(
                {
                    **status_payload(frozen),
                    "phase": "PROCESSING_DAY",
                    "active_pass": side,
                    "pid": os.getpid(),
                    "next_ordinal": ordinal,
                    "next_case_alias": alias,
                    "next_trading_date_utc": identity["trading_date_utc"],
                }
            )
            row = process_day(
                stream=streams[alias],
                prepared=prepared,
                translator=translator,
                source_router=router_by_alias[alias],
                source_corrected=corrected_by_alias[alias],
            )
            if side == "reference":
                primary_record = load_json(checkpoint_path("primary", ordinal, alias))
                require(row == primary_record["row"], f"Primary/reference day differs: {alias}")
            record = append_checkpoint(
                side=side,
                identity=identity,
                row=row,
                prior_sha256=prior,
                frozen=frozen,
            )
            prior = str(record["checkpoint_sha256"])
            processed_this_run += 1
            current = status_payload(frozen)
            write_status({**current, "phase": "DAY_CHECKPOINT_SEALED", "active_pass": side})
            print(
                f"[{now()}] checkpoint {side} {ordinal:03d}/095 "
                f"{identity['trading_date_utc']} {alias} | remaining total={current['remaining_total']}",
                flush=True,
            )
        del streams, prepared
    finalize()


def _all_trades(rows: list[dict[str, Any]], track: str) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    for row in rows:
        for index, result in enumerate(row["tracks"][track]["trades"], start=1):
            output.append(
                {
                    "trading_date_utc": row["trading_date_utc"],
                    "case_alias": row["case_alias"],
                    "trade_index": index,
                    **result,
                }
            )
    return sorted(output, key=lambda item: (item["trading_date_utc"], item["final_at"], item["case_alias"], item["trade_index"]))


def metrics(rows: list[dict[str, Any]], track: str) -> dict[str, Any]:
    trades = _all_trades(rows, track)
    values = [float(row["net_r50"]) for row in trades]
    wins = [value for value in values if value > EPSILON]
    losses = [value for value in values if value < -EPSILON]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    monthly = {
        month: sum(float(row["net_r50"]) for row in trades if row["trading_date_utc"].startswith(month))
        for month in sorted({row["trading_date_utc"][:7] for row in rows})
    }
    positive_month_gross = {
        month: sum(max(float(row["net_r50"]), 0.0) for row in trades if row["trading_date_utc"].startswith(month))
        for month in monthly
    }
    positive_total = sum(positive_month_gross.values())
    return {
        "days": len(rows),
        "trades": len(trades),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "net_r": sum(values),
        "net_usd": sum(float(row["net_usd"]) for row in trades),
        "expectancy_r": sum(values) / len(values) if values else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else (math.inf if wins else None),
        "maximum_drawdown_r": drawdown,
        "stressed_1p5x_cost_net_r": sum(float(row["stressed_1_5x_cost_r50"]) for row in trades),
        "monthly_net_r": monthly,
        "positive_months": sum(value > 0 for value in monthly.values()),
        "maximum_positive_gross_month_share": max(positive_month_gross.values()) / positive_total if positive_total else 1.0,
        "trades_per_represented_month": len(trades) / len(monthly) if monthly else 0.0,
    }


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold LONG Multi-Opportunity Auction Lifecycle and Structural Profit-Protection Research V1 Report",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "SHORT was quarantined. This is exposed 2022 regression evidence with zero validation credit.",
        "",
        "| Track | Trades | Win rate | Net R | PF | Max DD R | 1.5x-cost R | Positive months |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for track in TRACKS:
        row = result["metrics"][track]
        pf = "NA" if row["profit_factor"] is None else ("INF" if math.isinf(row["profit_factor"]) else f"{row['profit_factor']:.3f}")
        lines.append(
            f"| {track} | {row['trades']} | {(row['win_rate'] or 0.0)*100:.2f}% | "
            f"{row['net_r']:+.4f} | {pf} | {row['maximum_drawdown_r']:.4f} | "
            f"{row['stressed_1p5x_cost_net_r']:+.4f} | {row['positive_months']} |"
        )
    lines.extend(["", "## Incremental attribution", ""])
    for key, value in result["attribution"].items():
        lines.append(f"- {key}: `{value:+.6f}R`")
    lines.extend(["", "## Gate results", ""])
    for key, value in result["pass_gates"].items():
        lines.append(f"- {key}: `{value}`")
    lines.extend(
        [
            "",
            "The complete primary/reference day records remain in the immutable checkpoint chain. No unopened date was accessed.",
            "",
        ]
    )
    return "\n".join(lines)


def finalize() -> None:
    frozen = verify_freeze()
    primary = verify_checkpoint_chain("primary", frozen)
    reference = verify_checkpoint_chain("reference", frozen)
    require(len(primary) == len(reference) == 95, "Both checkpoint passes must be complete")
    primary_rows = [record["row"] for record in primary]
    reference_rows = [record["row"] for record in reference]
    require(primary_rows == reference_rows, "Primary/reference rows differ")
    computed = {track: metrics(primary_rows, track) for track in TRACKS}
    control = computed["FROZEN_LONG_CONTROL"]
    multi = computed["MULTI_OPPORTUNITY_CONTROL_MANAGEMENT"]
    structural = computed["FIRST_OPPORTUNITY_STRUCTURAL_MANAGEMENT"]
    combined = computed["MULTI_OPPORTUNITY_STRUCTURAL_MANAGEMENT"]
    attribution = {
        "additional_opportunities_existing_management": multi["net_r"] - control["net_r"],
        "structural_management_original_trades": structural["net_r"] - control["net_r"],
        "structural_management_later_trades": combined["net_r"] - structural["net_r"],
        "combined_delta_vs_control": combined["net_r"] - control["net_r"],
    }
    pass_gates = {
        "net_r_improves_control": combined["net_r"] > control["net_r"],
        "expectancy_positive": combined["expectancy_r"] > 0,
        "profit_factor_gte_1p10": combined["profit_factor"] is not None and combined["profit_factor"] >= 1.10,
        "stressed_cost_net_positive": combined["stressed_1p5x_cost_net_r"] > 0,
        "drawdown_not_worse_than_1p25x_control": combined["maximum_drawdown_r"] <= 1.25 * control["maximum_drawdown_r"],
        "at_least_three_positive_months": combined["positive_months"] >= 3,
        "max_positive_month_share_lte_0p70": combined["maximum_positive_gross_month_share"] <= 0.70,
        "primary_reference_exact": True,
    }
    verdict = "PASS_EXPOSED_LONG_POLICY_READY_FOR_FRESH_MONTH_FREEZE" if all(pass_gates.values()) else "REJECT_ADDITIONS_PRESERVE_FROZEN_LONG_CONTROL"
    emitted = sum(len(row["emitted_opportunities"]) for row in primary_rows)
    accepted_baseline = sum(
        item["portfolio_disposition"] == "ACCEPTED"
        for row in primary_rows
        for item in row["baseline_opportunity_audit"]
    )
    result: dict[str, Any] = {
        "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_RESULT_1_0",
        "completed_at": max(str(primary[-1]["created_at"]), str(reference[-1]["created_at"])),
        "verdict": verdict,
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "primary_reference_exact": True,
        "primary_checkpoint_tip": primary[-1]["checkpoint_sha256"],
        "reference_checkpoint_tip": reference[-1]["checkpoint_sha256"],
        "emitted_new_york_opportunities": emitted,
        "accepted_additional_baseline_opportunities": accepted_baseline,
        "metrics": computed,
        "attribution": attribution,
        "pass_gates": pass_gates,
        "rows_sha256": canonical_hash(primary_rows),
        "rows": primary_rows,
        "short_branch_opened": False,
        "february_17_28_opened": False,
        "random_50_cases_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    result["result_sha256"] = canonical_hash(result)
    if FINAL.exists():
        require(load_json(FINAL) == result, "Existing resumable final result differs")
    else:
        write_new_json(FINAL, result)
    report_text = markdown(result)
    if REPORT.exists():
        require(REPORT.read_text(encoding="utf-8") == report_text, "Existing resumable report differs")
    else:
        write_new_text(REPORT, report_text)
    if not SEAL.exists():
        seal: dict[str, Any] = {
            "version": "GOLD_LONG_MULTI_OPPORTUNITY_AUCTION_V1_FINAL_SEAL_1_0",
            "sealed_at": now(),
            "verdict": verdict,
            "files": [file_record(path) for path in (CONTRACT, IMPLEMENTATION, TESTS, RUNNER, FREEZE, FINAL, REPORT)],
            "primary_reference_exact": True,
            "checkpoint_counts": {"primary": 95, "reference": 95},
            "short_branch_opened": False,
            "fresh_dates_opened": False,
            "paid_acquisition": False,
        }
        seal["seal_sha256"] = canonical_hash(seal)
        write_new_json(SEAL, seal)
    write_status({**status_payload(frozen), "phase": "COMPLETE", "active_pass": None, "verdict": verdict})
    print(json.dumps({"verdict": verdict, "metrics": computed, "attribution": attribution, "pass_gates": pass_gates}, indent=2, sort_keys=True))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "status", "finalize"))
    parser.add_argument("--max-days", type=int, default=None)
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        require(args.max_days is None or args.max_days >= 1, "--max-days must be positive")
        run(args.max_days)
    elif args.phase == "status":
        print_status()
    else:
        finalize()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
