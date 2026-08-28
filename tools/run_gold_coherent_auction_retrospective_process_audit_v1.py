#!/usr/bin/env python3
"""Outcome-isolated process audit for the frozen 50-case coherent-auction block.

The command is deliberately split into three lifecycle stages:

1. ``freeze`` hashes the protocol and inputs without reading row values;
2. ``materialize`` constructs and seals predecision-only process packets;
3. ``join`` opens the already-exposed result only after the process registry is sealed.

This is retrospective audit evidence with zero validation credit.
"""

from __future__ import annotations

import argparse
import gzip
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

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
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    classify_predecision as reconstruct_complete_rulebook,
    iso,
    latest_atr,
)
from run_gold_coherent_auction_end_to_end_v1_inference import (  # noqa: E402
    classify_autonomous,
    first_m1_after,
    latest_m1_at,
    spread,
)


CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_RETROSPECTIVE_PROCESS_AUDIT_V1.md"
REFERENCE_BOOK = ROOT / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
RULEBOOK = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_RULEBOOK_V1_DRAFT.md"
RULEBOOK_APPROVAL = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_RULEBOOK_V1_APPROVAL.md"
IMPLEMENTATION_MAPPING = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_IMPLEMENTATION_MAPPING.md"
HUMAN_POLICY_V2 = ROOT / "GOLD_COHERENT_AUCTION_HUMAN_POLICY_RECONSTRUCTION_V2.md"
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
VALIDATION_ROOT = ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"
VALIDATION_CERTIFICATION = VALIDATION_ROOT / "stream_materialization_certification.json"
VALIDATION_REGISTRY = VALIDATION_ROOT / "population_registry.private.json"
PRIMARY_STREAM = VALIDATION_ROOT / "validation_streams.primary.jsonl.gz"
REFERENCE_STREAM = VALIDATION_ROOT / "validation_streams.reference.jsonl.gz"
EXPOSED_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_frozen_translator_unseen_block_v1"
    / "unseen_result.json"
)
SOURCE_RESULT_SEAL = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_frozen_translator_unseen_block_v1"
    / "final_seal.json"
)
OUT = ROOT / "research_artifacts" / "gold_coherent_auction_retrospective_process_audit_v1"
FREEZE = OUT / "predecision_freeze.json"
PRIMARY_PACKET = OUT / "predecision_primary.json"
REFERENCE_PACKET = OUT / "predecision_reference.json"
REGISTRY = OUT / "sealed_process_classification_registry.json"
JOIN_PRIMARY = OUT / "outcome_join_primary.json"
JOIN_REFERENCE = OUT / "outcome_join_reference.json"
FINAL_RESULT = OUT / "final_result.json"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_COHERENT_AUCTION_RETROSPECTIVE_PROCESS_AUDIT_V1_REPORT.md"

EXPECTED_TRANSLATOR_SHA256 = "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841"
EXPECTED_STREAM_SHA256 = "b3f1628e30f1549253478fb45d628bd09eab3abf95fed492c715e030a9b819ef"
EXPECTED_CASES = [f"GAV-2022-{index:03d}" for index in range(1, 51)]
RISK_BUDGET_USD = 50.0
STOP_EXCESS_ATR = 0.50
TICK_FLOOR = 0.02
EPSILON = 1e-9

BANNED_PREDECISION_KEYS = {
    "result",
    "results",
    "resolution",
    "outcome",
    "outcomes",
    "mfe",
    "mae",
    "net_r50",
    "net_usd",
    "pnl",
    "profit",
    "exit_at",
    "exit_price",
    "win",
    "loss",
    "label",
    "human_action",
    "human_decision_at",
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only artifact already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_new_text(path: Path, payload: str) -> None:
    require(not path.exists(), f"Append-only artifact already exists: {path}")
    path.write_text(payload.rstrip() + "\n", encoding="utf-8", newline="\n")


def file_record(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"Required file is absent: {path}")
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def seal_payload(payload: dict[str, Any], key: str) -> dict[str, Any]:
    require(key not in payload, f"Seal key already present: {key}")
    payload[key] = canonical_hash(payload)
    return payload


def validate_sealed_payload(path: Path, key: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    submitted = payload.pop(key)
    require(canonical_hash(payload) == submitted, f"Seal differs: {path}")
    payload[key] = submitted
    return payload


def assert_no_banned_keys(value: Any, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            require(
                normalized not in BANNED_PREDECISION_KEYS,
                f"Forbidden predecision field at {'.'.join((*trail, str(key)))}",
            )
            assert_no_banned_keys(item, (*trail, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_banned_keys(item, (*trail, str(index)))


def freeze() -> None:
    require(not OUT.exists(), f"Audit output directory already exists: {OUT}")
    sources = {
        "contract": file_record(CONTRACT),
        "reference_book": file_record(REFERENCE_BOOK),
        "approved_rulebook": file_record(RULEBOOK),
        "rulebook_approval": file_record(RULEBOOK_APPROVAL),
        "implementation_mapping": file_record(IMPLEMENTATION_MAPPING),
        "corrected_human_policy_v2": file_record(HUMAN_POLICY_V2),
        "translator": file_record(TRANSLATOR),
        "validation_certification": file_record(VALIDATION_CERTIFICATION),
        "validation_registry": file_record(VALIDATION_REGISTRY),
        "primary_stream": file_record(PRIMARY_STREAM),
        "reference_stream": file_record(REFERENCE_STREAM),
        "exposed_result": file_record(EXPOSED_RESULT),
        "source_result_seal": file_record(SOURCE_RESULT_SEAL),
        "audit_implementation": file_record(Path(__file__).resolve()),
        "complete_rulebook_engine": file_record(
            ROOT / "backend" / "src" / "gold_intel" / "analytics" / "coherent_auction_correction_v1.py"
        ),
        "human_policy_engine": file_record(
            ROOT / "backend" / "src" / "gold_intel" / "analytics" / "coherent_auction_human_policy_v2.py"
        ),
        "translator_inference_engine": file_record(
            ROOT / "tools" / "run_gold_coherent_auction_end_to_end_v1_inference.py"
        ),
        "translator_common_engine": file_record(
            ROOT / "tools" / "gold_coherent_auction_end_to_end_v1_common.py"
        ),
    }
    require(
        sources["translator"]["sha256"] == EXPECTED_TRANSLATOR_SHA256,
        "Frozen translator differs",
    )
    require(
        sources["primary_stream"]["sha256"] == EXPECTED_STREAM_SHA256
        and sources["reference_stream"]["sha256"] == EXPECTED_STREAM_SHA256,
        "Validation stream differs",
    )
    payload = {
        "version": "GOLD_COHERENT_AUCTION_RETROSPECTIVE_PROCESS_AUDIT_V1_0",
        "status": "SEALED_BEFORE_PREDECISION_PACKET_MATERIALIZATION",
        "created_at": now(),
        "evidentiary_status": "RETROSPECTIVE_ZERO_VALIDATION_CREDIT",
        "population": {
            "source_cases": EXPECTED_CASES,
            "audit_scope": "ALL_FROZEN_TRANSLATOR_SIGNAL_CASES",
            "expected_source_cases": 50,
            "expected_signal_cases": 20,
            "direction": "LONG_UNCHANGED",
        },
        "parameters": {
            "risk_budget_usd": RISK_BUDGET_USD,
            "stop_excess_width_atr": STOP_EXCESS_ATR,
            "target_balance_buffer_atr": 0.10,
            "target_tick_floor_usd": TICK_FLOOR,
            "classification_order": [
                "OBJECTIVE_PROCESS_VIOLATION",
                "UNVERIFIABLE_IMPLEMENTATION",
                "PROCESS_COMPLIANT_WITH_QUALITY_CONCERN",
                "PROCESS_COMPLIANT",
            ],
            "outcome_fields_prohibited_until_join": sorted(BANNED_PREDECISION_KEYS),
        },
        "lifecycle": ["freeze", "materialize", "join"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "sources": sources,
    }
    write_new_json(FREEZE, seal_payload(payload, "freeze_sha256"))
    print(json.dumps({"status": payload["status"], "freeze": str(FREEZE)}, indent=2))


def verify_freeze() -> dict[str, Any]:
    freeze_payload = validate_sealed_payload(FREEZE, "freeze_sha256")
    require(
        freeze_payload["status"] == "SEALED_BEFORE_PREDECISION_PACKET_MATERIALIZATION",
        "Freeze status differs",
    )
    for record in freeze_payload["sources"].values():
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen source is absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen source size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen source hash differs: {path}")
    return freeze_payload


def load_bundle(path: Path) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    require(sha256_file(path) == EXPECTED_STREAM_SHA256, f"Stream bundle differs: {path}")
    streams: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for source_row, line in enumerate(handle, start=1):
            payload = json.loads(line)
            submitted = payload.pop("stream_sha256")
            require(canonical_hash(payload) == submitted, f"Stream row differs: {source_row}")
            payload["stream_sha256"] = submitted
            alias = str(payload["case_alias"])
            require(alias not in streams, f"Duplicate case alias: {alias}")
            streams[alias] = payload
            lineage.append(
                {
                    "source_row": source_row,
                    "case_alias": alias,
                    "stream_sha256": submitted,
                    "population_sha256": payload["source_lineage"]["population_sha256"],
                }
            )
    require(list(streams) == EXPECTED_CASES, "Validation case order differs")
    return streams, lineage


def load_translator() -> dict[str, Any]:
    require(sha256_file(TRANSLATOR) == EXPECTED_TRANSLATOR_SHA256, "Translator differs")
    return json.loads(TRANSLATOR.read_text(encoding="utf-8"))


def finding(code: str, evidence: Any) -> dict[str, Any]:
    return {"code": code, "evidence": evidence}


def target_identity(full: dict[str, Any]) -> dict[str, Any] | None:
    zone = full.get("target_zone")
    if zone is not None:
        return {
            "kind": "ACTIVE_HTF_ZONE",
            "identity": zone.get("identity"),
            "source": zone.get("source"),
            "state": zone.get("state"),
            "level": zone.get("level"),
            "buffer": zone.get("buffer"),
            "known_at": zone.get("known_at"),
        }
    if full.get("thesis") == "RANGE_ROTATION" and full.get("controlling_balance") is not None:
        balance = full["controlling_balance"]
        return {
            "kind": "CONTROLLING_BALANCE_BOUNDARY",
            "identity": balance.get("identity"),
            "source": balance.get("source"),
            "state": "ACTIVE_BALANCE",
            "level": full.get("target"),
            "buffer": None,
            "known_at": balance.get("known_at"),
        }
    if full.get("thesis") == "STRUCTURAL_REPAIR" and full.get("damage") is not None:
        damage = full["damage"]
        return {
            "kind": "BROKEN_H4_REFERENCE",
            "identity": canonical_hash(
                {
                    "damage_at": damage.get("damage_at"),
                    "broken_reference": damage.get("broken_reference"),
                }
            ),
            "source": "H4",
            "state": "BROKEN_REFERENCE",
            "level": full.get("target"),
            "buffer": None,
            "known_at": damage.get("damage_at"),
        }
    return None


def process_assessment(
    *,
    alias: str,
    signal_at: str,
    geometry: dict[str, Any],
    original: dict[str, Any],
    full: dict[str, Any],
    m15_atr: float,
) -> dict[str, Any]:
    violations: list[dict[str, Any]] = []
    unverifiable: list[dict[str, Any]] = []
    concerns: list[dict[str, Any]] = []

    fill = float(geometry["fill"])
    stop = float(geometry["stop"])
    target = float(geometry["target"])
    cost = float(geometry["cost_per_ounce"])
    quantity = int(original["quantity_ounces"])
    planned_risk = quantity * float(original["planned_loss_per_ounce"])
    if not all(math.isfinite(value) for value in (fill, stop, target, cost)):
        violations.append(finding("NONFINITE_FROZEN_GEOMETRY", None))
    if not stop < fill < target:
        violations.append(finding("INVALID_LONG_GEOMETRY_ORDER", {"stop": stop, "fill": fill, "target": target}))
    if quantity < 1:
        violations.append(finding("ZERO_WHOLE_OUNCE_POSITION", {"quantity_ounces": quantity}))
    if planned_risk > RISK_BUDGET_USD + EPSILON:
        violations.append(finding("PLANNED_RISK_EXCEEDS_50_USD", {"planned_risk_usd": planned_risk}))

    if not original["h4"].get("available"):
        unverifiable.append(finding("CRITICAL_HTF_CONTEXT_UNAVAILABLE", original["h4"]))
    if original["macro"].get("state") == "UNKNOWN":
        unverifiable.append(finding("CRITICAL_MACRO_CONTEXT_UNKNOWN", original["macro"]))
    if not original["m15_structure"].get("available"):
        violations.append(finding("NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE", original["m15_structure"]))
    if original["event"].get("locked"):
        violations.append(finding("UNRESOLVED_TIER1_EVENT_AUCTION", original["event"]))
    for blocker in original.get("blockers", []):
        code = str(blocker["code"])
        if code not in {"NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE", "UNRESOLVED_TIER1_EVENT_AUCTION"}:
            violations.append(finding(code, blocker.get("evidence")))

    thesis = full.get("thesis")
    if thesis is None:
        unverifiable.append(finding("GOVERNING_AUCTION_NOT_RECONSTRUCTIBLE", full.get("blockers")))
    elif str(geometry["family"]) != str(thesis):
        concerns.append(
            finding(
                "THESIS_FAMILY_DISAGREEMENT",
                {"translator_family": geometry["family"], "reconstructed_thesis": thesis},
            )
        )

    trigger = full.get("trigger")
    if trigger is None:
        violations.append(finding("NO_RECONSTRUCTIBLE_LIVE_APPROVED_TRIGGER", full.get("blockers")))
    else:
        required_stop = full.get("stop")
        if required_stop is None:
            unverifiable.append(finding("STRUCTURAL_INVALIDATION_NOT_RECONSTRUCTIBLE", trigger))
        else:
            required_stop = float(required_stop)
            if stop > required_stop + EPSILON:
                violations.append(
                    finding(
                        "INVALIDATION_INSIDE_CONTROLLING_STRUCTURE",
                        {
                            "frozen_stop": stop,
                            "required_maximum_stop": required_stop,
                            "inside_by_price": stop - required_stop,
                            "trigger_identity": trigger.get("identity"),
                            "stop_reference": trigger.get("stop_reference"),
                        },
                    )
                )
            elif required_stop - stop > STOP_EXCESS_ATR * m15_atr + EPSILON:
                concerns.append(
                    finding(
                        "EXCESS_INVALIDATION_WIDTH",
                        {
                            "frozen_stop": stop,
                            "minimum_structural_stop": required_stop,
                            "excess_atr": (required_stop - stop) / m15_atr,
                        },
                    )
                )

    expected_target = full.get("target")
    destination = target_identity(full)
    if expected_target is None or destination is None or destination.get("identity") is None:
        if expected_target is None:
            violations.append(finding("NO_ACTIVE_FORWARD_LIQUIDITY_DESTINATION", full.get("blockers")))
        else:
            unverifiable.append(finding("DESTINATION_IDENTITY_NOT_RECONSTRUCTIBLE", {"target": expected_target}))
    else:
        expected_target = float(expected_target)
        target_buffer = destination.get("buffer")
        if target_buffer is None:
            target_buffer = max(0.10 * m15_atr, TICK_FLOOR)
        target_buffer = float(target_buffer)
        if target < expected_target - target_buffer - EPSILON:
            concerns.append(
                finding(
                    "TARGET_TRUNCATED_BEFORE_NAMED_LIQUIDITY",
                    {
                        "frozen_target": target,
                        "named_destination": expected_target,
                        "buffer": target_buffer,
                        "destination_identity": destination["identity"],
                    },
                )
            )
        elif target > expected_target + target_buffer + EPSILON:
            violations.append(
                finding(
                    "TARGET_BEYOND_FIRST_UNRESOLVED_LIQUIDITY",
                    {
                        "frozen_target": target,
                        "named_destination": expected_target,
                        "buffer": target_buffer,
                        "destination_identity": destination["identity"],
                    },
                )
            )

    if original["macro"].get("state") == "OPPOSED" and str(geometry["family"]) == "CONTINUATION_WITH_ROOM":
        concerns.append(finding("COUNTER_MACRO_CONTINUATION", original["macro"]))

    def unique(rows: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
        seen: set[str] = set()
        output: list[dict[str, Any]] = []
        for row in rows:
            key = canonical_hash(row)
            if key not in seen:
                seen.add(key)
                output.append(row)
        return sorted(output, key=lambda row: (str(row["code"]), canonical_hash(row.get("evidence"))))

    violations = unique(violations)
    unverifiable = unique(unverifiable)
    concerns = unique(concerns)
    if violations:
        primary_class = "OBJECTIVE_PROCESS_VIOLATION"
    elif unverifiable:
        primary_class = "UNVERIFIABLE_IMPLEMENTATION"
    elif concerns:
        primary_class = "PROCESS_COMPLIANT_WITH_QUALITY_CONCERN"
    else:
        primary_class = "PROCESS_COMPLIANT"
    result = {
        "case_alias": alias,
        "signal_at": signal_at,
        "original_admitted": bool(original["admitted"]),
        "original_disposition": original["primary_disposition"],
        "primary_process_class": primary_class,
        "objective_violations": violations,
        "unverifiable_requirements": unverifiable,
        "quality_concerns": concerns,
        "reconstruction": {
            "thesis": thesis,
            "thesis_evidence": full.get("thesis_evidence"),
            "controlling_balance_identity": (
                full["controlling_balance"].get("identity") if full.get("controlling_balance") else None
            ),
            "trigger": trigger,
            "minimum_structural_stop": full.get("stop"),
            "destination": destination,
            "expected_target": expected_target,
            "macro": full.get("macro"),
            "event": full.get("event"),
            "full_rulebook_disposition_for_diagnostic_only": full.get("primary_disposition"),
        },
        "frozen_geometry": geometry,
        "process_assessment_sha256": None,
    }
    result["process_assessment_sha256"] = canonical_hash(
        {key: value for key, value in result.items() if key != "process_assessment_sha256"}
    )
    return result


def materialize_side(
    *, side: str, stream_path: Path, translator: dict[str, Any]
) -> dict[str, Any]:
    streams, lineage = load_bundle(stream_path)
    prepared = prepare_features(streams.values())
    semantic = translator["semantic"]
    geometry_model = translator["geometry"]
    schema = translator["preprocessing"]
    rows: list[dict[str, Any]] = []
    no_signal: list[str] = []
    for alias in EXPECTED_CASES:
        stream = streams[alias]
        checkpoints = materialize_case(alias=alias, stream=stream, prepared=prepared, end_at=None)
        signal_row: dict[str, Any] | None = None
        probability: float | None = None
        for checkpoint in checkpoints:
            matrix = transform_rows([checkpoint], schema)
            candidate_probability = float(
                predict_class_probability(semantic["tree"], matrix, positive_class=1)[0]
            )
            if candidate_probability >= float(semantic["threshold"]):
                signal_row = checkpoint
                probability = candidate_probability
                break
        if signal_row is None:
            no_signal.append(alias)
            continue
        safe_signal_snapshot = {
            key: value
            for key, value in signal_row.items()
            if str(key).casefold() not in BANNED_PREDECISION_KEYS
        }
        assert_no_banned_keys(safe_signal_snapshot)
        matrix = transform_rows([signal_row], schema)
        stop_distance = float(predict_regression(geometry_model["stop_distance_tree"], matrix)[0])
        target_distance = float(predict_regression(geometry_model["target_distance_tree"], matrix)[0])
        family = str(predict_class(geometry_model["family_tree"], matrix)[0])
        signal_at = str(signal_row["checkpoint_at"])
        reference_close = float(signal_row["m1_reference_close"])
        m15_atr = float(signal_row["m15_atr_scale"])
        stop = reference_close - stop_distance * m15_atr
        target = reference_close + target_distance * m15_atr
        fill_bar = first_m1_after(stream, signal_at)
        decision_bar = latest_m1_at(stream, signal_at)
        require(fill_bar is not None and decision_bar is not None, f"Execution metadata unavailable: {alias}")
        fill = float(fill_bar["open"]) + spread(fill_bar) / 2.0 + 0.05
        cost_per_ounce = spread(decision_bar) + 2.0 * 0.05
        geometry = {
            "reference_close": reference_close,
            "m15_atr": m15_atr,
            "stop_distance_atr": stop_distance,
            "target_distance_atr": target_distance,
            "family": family,
            "fill_at": iso(fill_bar["open_at"]),
            "fill": fill,
            "stop": stop,
            "target": target,
            "cost_per_ounce": cost_per_ounce,
        }
        original = classify_autonomous(
            stream=stream,
            signal_at=signal_at,
            family=family,
            fill=fill,
            stop=stop,
            target=target,
            cost_per_ounce=cost_per_ounce,
        )
        audit_quantity = max(1, int(original["quantity_ounces"]))
        full = reconstruct_complete_rulebook(
            decision={
                "direction": "LONG",
                "submitted_at": signal_at,
                "fill_price": fill,
                "estimated_base_cost_usd": cost_per_ounce * audit_quantity,
                "quantity_ounces": audit_quantity,
            },
            stream=stream,
        )
        assessment = process_assessment(
            alias=alias,
            signal_at=signal_at,
            geometry=geometry,
            original=original,
            full=full,
            m15_atr=m15_atr,
        )
        packet = {
            "case_alias": alias,
            "session_code": stream["session_code"],
            "trading_date_utc": stream["trading_date_utc"],
            "signal_at": signal_at,
            "signal_probability": probability,
            "source_stream_sha256": stream["stream_sha256"],
            "feature_snapshot_sha256": canonical_hash(safe_signal_snapshot),
            "original_context_classification": original,
            "process_assessment": assessment,
            "packet_sha256": None,
        }
        assert_no_banned_keys(packet)
        packet["packet_sha256"] = canonical_hash(
            {key: value for key, value in packet.items() if key != "packet_sha256"}
        )
        rows.append(packet)
    require(len(rows) == 20, f"Expected 20 signal packets, found {len(rows)}")
    require(len(no_signal) == 30, f"Expected 30 no-signal cases, found {len(no_signal)}")
    payload = {
        "version": "GOLD_COHERENT_AUCTION_PREDECISION_PROCESS_PACKETS_V1_0",
        "side": side,
        "created_at": now(),
        "source_lineage_sha256": canonical_hash(lineage),
        "translator_sha256": sha256_file(TRANSLATOR),
        "signal_cases": len(rows),
        "no_signal_cases": no_signal,
        "rows": rows,
        "outcome_fields_accessed": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
    }
    assert_no_banned_keys(payload)
    return seal_payload(payload, "payload_sha256")


def materialize() -> None:
    freeze_payload = verify_freeze()
    require(not PRIMARY_PACKET.exists() and not REFERENCE_PACKET.exists() and not REGISTRY.exists(), "Materialization already exists")
    translator = load_translator()
    primary = materialize_side(side="primary", stream_path=PRIMARY_STREAM, translator=translator)
    write_new_json(PRIMARY_PACKET, primary)
    reference = materialize_side(side="reference", stream_path=REFERENCE_STREAM, translator=translator)
    write_new_json(REFERENCE_PACKET, reference)
    primary_rows = primary["rows"]
    reference_rows = reference["rows"]
    require(
        [row["case_alias"] for row in primary_rows] == [row["case_alias"] for row in reference_rows],
        "Primary/reference signal identities differ",
    )
    primary_core = [
        {key: value for key, value in row.items() if key != "packet_sha256"} for row in primary_rows
    ]
    reference_core = [
        {key: value for key, value in row.items() if key != "packet_sha256"} for row in reference_rows
    ]
    require(primary_core == reference_core, "Primary/reference predecision packets differ")
    registry_rows = [
        {
            "case_alias": row["case_alias"],
            "session_code": row["session_code"],
            "trading_date_utc": row["trading_date_utc"],
            "signal_at": row["signal_at"],
            "packet_sha256": row["packet_sha256"],
            "process_assessment": row["process_assessment"],
        }
        for row in primary_rows
    ]
    registry = {
        "version": "GOLD_COHERENT_AUCTION_SEALED_PROCESS_CLASSIFICATION_REGISTRY_V1_0",
        "status": "SEALED_BEFORE_OUTCOME_JOIN",
        "created_at": now(),
        "freeze_sha256": freeze_payload["freeze_sha256"],
        "primary_packet_file_sha256": sha256_file(PRIMARY_PACKET),
        "reference_packet_file_sha256": sha256_file(REFERENCE_PACKET),
        "primary_reference_exact": True,
        "rows": registry_rows,
        "classification_counts": dict(
            sorted(Counter(row["process_assessment"]["primary_process_class"] for row in registry_rows).items())
        ),
        "outcomes_opened": False,
    }
    assert_no_banned_keys(registry)
    write_new_json(REGISTRY, seal_payload(registry, "registry_sha256"))
    print(
        json.dumps(
            {
                "status": registry["status"],
                "signals": len(registry_rows),
                "classification_counts": registry["classification_counts"],
                "registry": str(REGISTRY),
            },
            indent=2,
        )
    )


def outcome_label(result: dict[str, Any]) -> str:
    if not result["executed"]:
        return "ORIGINAL_CONTEXTUAL_REJECTION"
    value = float(result["net_r50"])
    if value > EPSILON:
        return "WIN"
    if value < -EPSILON:
        return "LOSS"
    return "SCRATCH"


def join_rows_loop(
    registry_rows: list[dict[str, Any]], exposed_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    exposed_by_alias = {row["case_alias"]: row for row in exposed_rows}
    output: list[dict[str, Any]] = []
    for audit in registry_rows:
        source = exposed_by_alias[audit["case_alias"]]
        require(source["signal_at"] == audit["signal_at"], f"Signal time differs: {audit['case_alias']}")
        result = source["result"]
        assessment = audit["process_assessment"]
        output.append(
            {
                "case_alias": audit["case_alias"],
                "session_code": audit["session_code"],
                "signal_at": audit["signal_at"],
                "original_admitted": assessment["original_admitted"],
                "original_disposition": assessment["original_disposition"],
                "process_class": assessment["primary_process_class"],
                "objective_violation_codes": [row["code"] for row in assessment["objective_violations"]],
                "unverifiable_codes": [row["code"] for row in assessment["unverifiable_requirements"]],
                "quality_concern_codes": [row["code"] for row in assessment["quality_concerns"]],
                "outcome_label": outcome_label(result),
                "resolution": result["resolution"],
                "net_r50": float(result["net_r50"]),
                "net_usd": float(result["net_usd"]),
                "joined_row_sha256": None,
            }
        )
        output[-1]["joined_row_sha256"] = canonical_hash(
            {key: value for key, value in output[-1].items() if key != "joined_row_sha256"}
        )
    return output


def join_rows_comprehension(
    registry_rows: list[dict[str, Any]], exposed_rows: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    audit_by_alias = {row["case_alias"]: row for row in registry_rows}
    selected = [row for row in exposed_rows if row["case_alias"] in audit_by_alias]
    output: list[dict[str, Any]] = []
    for source in selected:
        audit = audit_by_alias[source["case_alias"]]
        assessment = audit["process_assessment"]
        result = source["result"]
        row = {
            "case_alias": source["case_alias"],
            "session_code": audit["session_code"],
            "signal_at": source["signal_at"],
            "original_admitted": assessment["original_admitted"],
            "original_disposition": assessment["original_disposition"],
            "process_class": assessment["primary_process_class"],
            "objective_violation_codes": list(map(lambda item: item["code"], assessment["objective_violations"])),
            "unverifiable_codes": list(map(lambda item: item["code"], assessment["unverifiable_requirements"])),
            "quality_concern_codes": list(map(lambda item: item["code"], assessment["quality_concerns"])),
            "outcome_label": outcome_label(result),
            "resolution": result["resolution"],
            "net_r50": float(result["net_r50"]),
            "net_usd": float(result["net_usd"]),
            "joined_row_sha256": None,
        }
        row["joined_row_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "joined_row_sha256"}
        )
        output.append(row)
    output.sort(key=lambda row: row["case_alias"])
    return output


def aggregate(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [row for row in rows if row["original_admitted"]]

    def metrics(group: list[dict[str, Any]]) -> dict[str, Any]:
        traded = [row for row in group if row["original_admitted"]]
        wins = [row for row in traded if row["net_r50"] > EPSILON]
        losses = [row for row in traded if row["net_r50"] < -EPSILON]
        positive = sum(row["net_r50"] for row in wins)
        negative = sum(row["net_r50"] for row in losses)
        return {
            "signals": len(group),
            "executed": len(traded),
            "wins": len(wins),
            "losses": len(losses),
            "win_rate": len(wins) / len(traded) if traded else None,
            "net_r50": sum(row["net_r50"] for row in traded),
            "net_usd": sum(row["net_usd"] for row in traded),
            "profit_factor": positive / abs(negative) if negative < -EPSILON else None,
        }

    by_class: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_class[row["process_class"]].append(row)
    violation_code_metrics: dict[str, dict[str, Any]] = {}
    all_codes = sorted({code for row in rows for code in row["objective_violation_codes"]})
    for code in all_codes:
        matched = [row for row in rows if code in row["objective_violation_codes"]]
        violation_code_metrics[code] = metrics(matched)
    return {
        "all_signals": metrics(rows),
        "executed_only": metrics(executed),
        "by_process_class": {key: metrics(by_class[key]) for key in sorted(by_class)},
        "by_objective_violation_code": violation_code_metrics,
        "classification_counts": dict(sorted(Counter(row["process_class"] for row in rows).items())),
        "joined_label_counts": dict(sorted(Counter(row["outcome_label"] for row in rows).items())),
    }


def report_markdown(result: dict[str, Any]) -> str:
    rows = result["rows"]
    summary = result["summary"]
    lines = [
        "# Gold Coherent-Auction Retrospective Process Audit V1 — Result",
        "",
        f"Status: `{result['verdict']}`",
        "",
        "## What this audit can and cannot establish",
        "",
        "This is a retrospective, outcome-isolated process audit with zero validation credit. Process classifications were sealed from predecision-only packets before the already-exposed outcomes were joined. A loss is not called bad practice unless an objective predecision rule was violated; a winning violation remains a violation.",
        "",
        "## Headline",
        "",
        f"- Signals audited: **{len(rows)}**",
        f"- Executed by the frozen policy: **{summary['executed_only']['executed']}**",
        f"- Original performance: **{summary['executed_only']['net_r50']:.6f}R** / **${summary['executed_only']['net_usd']:.2f}**",
        f"- Process-class counts: `{json.dumps(summary['classification_counts'], sort_keys=True)}`",
        "",
        "## Process-class decomposition",
        "",
        "| Process class | Signals | Executed | W | L | Win rate | Net R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for name, row in summary["by_process_class"].items():
        win_rate = "—" if row["win_rate"] is None else f"{100 * row['win_rate']:.1f}%"
        lines.append(
            f"| {name} | {row['signals']} | {row['executed']} | {row['wins']} | {row['losses']} | {win_rate} | {row['net_r50']:.6f} |"
        )
    lines.extend(
        [
            "",
            "## Every emitted signal",
            "",
            "| Case | Session | Original | Process class | Violations | Unverifiable | Concerns | Outcome | R |",
            "|---|---|---|---|---|---|---|---|---:|",
        ]
    )
    for row in rows:
        lines.append(
            "| {case_alias} | {session_code} | {original} | {process_class} | {violations} | {unverifiable} | {concerns} | {outcome_label} | {net_r50:.6f} |".format(
                case_alias=row["case_alias"],
                session_code=row["session_code"],
                original="ADMIT" if row["original_admitted"] else row["original_disposition"],
                process_class=row["process_class"],
                violations=", ".join(row["objective_violation_codes"]) or "—",
                unverifiable=", ".join(row["unverifiable_codes"]) or "—",
                concerns=", ".join(row["quality_concern_codes"]) or "—",
                outcome_label=row["outcome_label"],
                net_r50=row["net_r50"],
            )
        )
    lines.extend(
        [
            "",
            "## Interpretation rule",
            "",
            "The table is a diagnosis of implementation fidelity, not a proposal to delete losing rows. No violation or concern becomes a trading filter from this exposed sample. Corrections are limited to making the autonomous engine explicitly identify its governing auction, live trigger, controlling invalidation structure, and named liquidity destination before it is allowed to trade.",
            "",
            "## Integrity",
            "",
            f"- Predecision registry SHA-256: `{result['process_registry_sha256']}`",
            f"- Joined row-set SHA-256: `{result['joined_rows_sha256']}`",
            "- Primary/reference predecision packets: exact",
            "- Two outcome-join implementations: exact",
            "- 2025/2026 opened: no",
            "- Paid acquisition: no",
        ]
    )
    return "\n".join(lines)


def join() -> None:
    freeze_payload = verify_freeze()
    registry = validate_sealed_payload(REGISTRY, "registry_sha256")
    require(registry["status"] == "SEALED_BEFORE_OUTCOME_JOIN", "Registry was not sealed before join")
    require(sha256_file(PRIMARY_PACKET) == registry["primary_packet_file_sha256"], "Primary packet differs")
    require(sha256_file(REFERENCE_PACKET) == registry["reference_packet_file_sha256"], "Reference packet differs")
    require(not any(path.exists() for path in (JOIN_PRIMARY, JOIN_REFERENCE, FINAL_RESULT, FINAL_SEAL, REPORT)), "Join output already exists")

    # This is the first lifecycle stage in this script allowed to read result fields.
    exposed = json.loads(EXPOSED_RESULT.read_text(encoding="utf-8"))
    require(exposed["evaluation"]["combined"]["net_r50"] == 3.6907126075569305, "Exposed result summary differs")
    exposed_rows = exposed["rows"]
    primary_rows = join_rows_loop(registry["rows"], exposed_rows)
    reference_rows = join_rows_comprehension(registry["rows"], exposed_rows)
    require(primary_rows == reference_rows, "Independent outcome joins differ")
    join_primary = seal_payload(
        {
            "version": "GOLD_COHERENT_AUCTION_PROCESS_OUTCOME_JOIN_V1_0",
            "implementation": "PRIMARY_LOOP",
            "created_at": now(),
            "process_registry_sha256": registry["registry_sha256"],
            "rows": primary_rows,
        },
        "join_sha256",
    )
    join_reference = seal_payload(
        {
            "version": "GOLD_COHERENT_AUCTION_PROCESS_OUTCOME_JOIN_V1_0",
            "implementation": "REFERENCE_ALIAS_MAP",
            "created_at": now(),
            "process_registry_sha256": registry["registry_sha256"],
            "rows": reference_rows,
        },
        "join_sha256",
    )
    write_new_json(JOIN_PRIMARY, join_primary)
    write_new_json(JOIN_REFERENCE, join_reference)
    summary = aggregate(primary_rows)
    verdict = "PASS_RETROSPECTIVE_PROCESS_AUDIT_REPRODUCED"
    final = {
        "version": "GOLD_COHERENT_AUCTION_RETROSPECTIVE_PROCESS_AUDIT_RESULT_V1_0",
        "verdict": verdict,
        "completed_at": now(),
        "evidentiary_status": "RETROSPECTIVE_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": freeze_payload["freeze_sha256"],
        "process_registry_sha256": registry["registry_sha256"],
        "joined_rows_sha256": canonical_hash(primary_rows),
        "independent_join_exact": True,
        "summary": summary,
        "rows": primary_rows,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    write_new_json(FINAL_RESULT, seal_payload(final, "result_sha256"))
    write_new_text(REPORT, report_markdown(final))
    final_seal = {
        "version": "GOLD_COHERENT_AUCTION_RETROSPECTIVE_PROCESS_AUDIT_FINAL_SEAL_V1_0",
        "status": verdict,
        "sealed_at": now(),
        "files": {
            path.name: file_record(path)
            for path in (
                FREEZE,
                PRIMARY_PACKET,
                REFERENCE_PACKET,
                REGISTRY,
                JOIN_PRIMARY,
                JOIN_REFERENCE,
                FINAL_RESULT,
                REPORT,
            )
        },
    }
    write_new_json(FINAL_SEAL, seal_payload(final_seal, "seal_sha256"))
    print(
        json.dumps(
            {
                "verdict": verdict,
                "summary": summary,
                "report": str(REPORT),
                "final_seal": str(FINAL_SEAL),
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "materialize", "join"))
    args = parser.parse_args()
    if args.stage == "freeze":
        freeze()
    elif args.stage == "materialize":
        materialize()
    else:
        join()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

