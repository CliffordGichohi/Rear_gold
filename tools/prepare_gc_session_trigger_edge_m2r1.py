#!/usr/bin/env python3
"""Freeze GC Session Trigger Edge Discovery V1 Milestone 2-R1.

This preparation step is strictly pre-row-access.  It binds the sealed
Milestone 2 failure and freezes the metadata-only diagnostic before any
XAUUSD, MBO, MBP-10, or feature row is opened for R1.
"""

from __future__ import annotations

import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"

M2_DIR = ARTIFACTS / "gc_session_trigger_edge_m2_v01"
M2_FINAL = M2_DIR / "final_seal.json"
M2_MANIFEST = M2_DIR / "manifest.json"
M2_VERDICT = M2_DIR / "verdict.json"
M2_DIAGNOSTICS = M2_DIR / "technical_diagnostics.json"
M2_PROTOCOL = MANIFESTS / "gc_session_trigger_edge_m2_protocol_v01.json"
M2_REGISTRY = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"
M2_FREEZE = MANIFESTS / "gc_session_trigger_edge_m2_freeze_v01.json"
M2_ENGINE = ROOT / "tools" / "materialize_gc_session_trigger_edge_m2.py"
STEP5C_ENGINE = ROOT / "tools" / "materialize_gc_microstructure_step5c.py"
BASE_ENGINE = ROOT / "tools" / "build_gc_microstructure_features_step4a.py"
R1_ENGINE = ROOT / "tools" / "diagnose_gc_session_trigger_edge_m2r1.py"

PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2r1_protocol_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2r1_freeze_v01.json"
OUTPUT_DIR = ARTIFACTS / "gc_session_trigger_edge_m2r1_v01"
PREFLIGHT_PATH = OUTPUT_DIR / "protocol_preflight.json"

BOUND = {
    "m2_final_seal": (M2_FINAL, "c6b86602eceb927db71f56e35bce3bd8778f350f7853429cebbbf281d94c7e85"),
    "m2_manifest": (M2_MANIFEST, "adffdc302f103c8eac307d30193ee06f83e5dafd2fa0e597c9601dbf78a67760"),
    "m2_verdict": (M2_VERDICT, "03b1bbae4f56caa9b1586ec381805040d24f8e0764da40ad3a3ceaeb8dc85267"),
    "m2_technical_diagnostics": (M2_DIAGNOSTICS, "d08bf542afd77e09c44830d0a198300513dfeeb74cb94d8b0605e03fd04c223a"),
    "m2_protocol": (M2_PROTOCOL, "d4490ac0311e0a6a6b40595b6c97ee7e8eba357db14f11ccdbbb0c5b32c8d509"),
    "m2_row_registry": (M2_REGISTRY, "a7a36ae82d92ce91a25e36fcb7f1c95807de67c996d01198648246daa345dc5d"),
    "m2_freeze": (M2_FREEZE, "0705d12b25fb79ef5a74ea2ce1842d60265cf45deca177be9f904c0db47c0037"),
    "m2_engine": (M2_ENGINE, "acc7af0c5196cc943ad129560f736b31fda03727979fe43b58a7bcf0188d5479"),
    "step5c_engine": (STEP5C_ENGINE, "81e2aa4c620aa2bf4e151c727af6827d7743a4e8e452a85d3f78dc1ac7188e92"),
    "base_engine": (BASE_ENGINE, "c5589914a1acae6a3a1e9079c302821477866bba3741317392c567bb590c2369"),
}

AUTHORIZATION = """Proceed to GC Session Trigger Edge Discovery V1 Milestone 2-R1 under a narrow metadata-only coverage and feature-integrity diagnostic protocol. Preserve the sealed Milestone 2 FAIL_FULL_SESSION_TIMESTAMP_COVERAGE verdict and every prior artifact, definition, threshold, gate, and seal unchanged. Use only the existing sealed development sources and Milestone 2 technical artifacts. Before row-level metadata access, freeze and seal the exact diagnostic taxonomy, tests, classification rules, and independent-reproduction requirements. Identify and classify the three unexpected missing XAUUSD timestamps by session key, expected timestamp, source coverage, DST conversion, duplicate/order status, lineage, and market-calendar availability. Diagnose all fifteen continuous-matching crossed bucket-close states using only timestamps, market state, snapshot/reset status, action, side, flags, sequence, native-event grouping, F_LAST status, hashed row identities, and crossed/uncrossed classifications. Determine whether each state occurred inside an unfinished native event, persisted at its completed boundary, or resulted from state construction. Do not repair, refresh, filter, relabel, reacquire, or recalculate the feature outputs. Do not inspect or report prices, depths, order-flow values, outcomes, relationships, candidates, execution, trades, PnL, R multiples, or returns. Keep 2025 and 2026 locked and incur no charge. Run two independent reproductions, classify every finding as DOCUMENTED_VALID_SEMANTICS, RECOVERABLE_EXISTING_SOURCE, RECOVERABLE_TARGETED_REFRESH, GENUINE_SOURCE_OR_STATE_FAILURE, or UNRESOLVED, recommend at most one bounded correction, document and seal the result, and stop."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def relative(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def verify_predecessor() -> dict[str, Any]:
    for name, (path, expected) in BOUND.items():
        if not path.is_file():
            raise FileNotFoundError(path)
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Predecessor binding changed: {name} {actual}")
    final = load_json(M2_FINAL)
    manifest = load_json(M2_MANIFEST)
    verdict = load_json(M2_VERDICT)
    diagnostics = load_json(M2_DIAGNOSTICS)
    if final.get("status") != "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE":
        raise ValueError("Milestone 2 formal failure was not preserved")
    if final.get("manifest_sha256") != sha256_file(M2_MANIFEST):
        raise ValueError("Milestone 2 manifest binding failed")
    if final.get("verdict_sha256") != sha256_file(M2_VERDICT):
        raise ValueError("Milestone 2 verdict binding failed")
    if final.get("freeze_sha256") != sha256_file(M2_FREEZE):
        raise ValueError("Milestone 2 freeze binding failed")
    if final.get("final_seal_receipt") != canonical_hash({**final, "final_seal_receipt": None}):
        raise ValueError("Milestone 2 final receipt failed")
    if verdict.get("status") != "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE":
        raise ValueError("Milestone 2 verdict changed")
    if verdict.get("technical_counts", {}).get("xau_unexpected_missing_timestamps") != 3:
        raise ValueError("Expected three unexpected XAUUSD gaps")
    primary = diagnostics.get("primary_technical", {})
    reference = diagnostics.get("reference_technical", {})
    if primary != reference or primary.get("continuous_crossed_bucket_closes") != 15:
        raise ValueError("Expected exactly fifteen independently reproduced crossed closes")
    required_reproduction = (
        "primary_reference_feature_reproduction",
        "primary_reference_decision_reproduction",
        "primary_reference_event_reproduction",
        "primary_reference_support_reproduction",
    )
    if not all(verdict.get("formal_gates", {}).get(name) is True for name in required_reproduction):
        raise ValueError("Milestone 2 independent reproduction was not preserved")
    return {
        "m2_status": final["status"],
        "m2_final_seal_receipt": final["final_seal_receipt"],
        "m2_registered_artifacts": len(manifest.get("artifacts", [])),
        "unexpected_xau_timestamps": 3,
        "continuous_crossed_bucket_closes": 15,
    }


def build_protocol(frozen_at: str) -> dict[str, Any]:
    classes = [
        "DOCUMENTED_VALID_SEMANTICS",
        "RECOVERABLE_EXISTING_SOURCE",
        "RECOVERABLE_TARGETED_REFRESH",
        "GENUINE_SOURCE_OR_STATE_FAILURE",
        "UNRESOLVED",
    ]
    return {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_PROTOCOL_V1_0",
        "status": "FROZEN_BEFORE_ROW_LEVEL_METADATA_ACCESS",
        "frozen_at_utc": frozen_at,
        "authorization_sha256": hashlib.sha256(AUTHORIZATION.encode("utf-8")).hexdigest(),
        "classification": "METADATA_ONLY_COVERAGE_AND_FEATURE_INTEGRITY_DIAGNOSTIC",
        "scope": {
            "expected_xau_findings": 3,
            "expected_crossed_bucket_close_findings": 15,
            "development_start": "2021-11-08",
            "development_end": "2024-12-13",
            "calendar_2025": "LOCKED_NO_ROW_OR_VALUE_ACCESS",
            "calendar_2026": "LOCKED_NO_ROW_OR_VALUE_ACCESS",
            "source_policy": "Only sources and technical outputs already sealed by Milestone 2.",
            "all_prior_artifacts_immutable": True,
        },
        "predecessor_bindings": {
            name: {"path": relative(path), "sha256": expected}
            for name, (path, expected) in BOUND.items()
        },
        "constants": {
            "flag_maybe_bad_book": 4,
            "flag_bad_ts_recv": 8,
            "flag_snapshot": 32,
            "flag_last": 128,
            "undefined_price_fixed_1e9": 9_223_372_036_854_775_807,
            "bucket_width_ns": 1_000_000_000,
            "xau_minutes_per_available_session": 300,
            "expected_available_sessions": 374,
        },
        "allowed_fields": {
            "xau": [
                "record_type", "record_id", "record_hash", "provider_code",
                "instrument_code", "timeframe", "open_time", "close_time",
                "available_at", "ingested_at", "complete", "epistemic_status",
            ],
            "feature": [
                "bucket_index", "bucket_start_ns", "bucket_end_ns", "market_segment",
                "market_state", "state_source_row_ordinal", "state_ts_recv_ns",
                "state_available", "book_two_sided", "book_locked", "book_crossed",
            ],
            "mbp10": [
                "source_row_ordinal", "ts_recv", "ts_event", "publisher_id",
                "instrument_id", "sequence", "action", "side", "flags",
                "level_00_fields_for_automated_state_classification_only",
            ],
            "mbo": [
                "source_row_ordinal", "ts_recv", "ts_event", "publisher_id",
                "instrument_id", "sequence", "action", "side", "flags",
            ],
            "prohibited_output": [
                "OHLC", "price or quote values", "depth sizes or counts", "spread",
                "order-flow values", "directional outcomes", "returns", "signals",
                "execution", "trades", "PnL", "R multiples", "account returns",
            ],
        },
        "xau_timestamp_tests": {
            "population": "Expected 300 one-minute opens from each available session open through session open plus five hours, minus the frozen 57 documented gaps; identify exactly the remaining three absences.",
            "dst": "Recompute 08:00 local with IANA Europe/London or America/New_York and require exact equality to the sealed UTC session open.",
            "coverage": [
                "qualifying XAUUSD one-minute emission count at the exact timestamp",
                "any nonqualifying source emission at the exact timestamp",
                "immediate qualifying predecessor and successor presence",
                "duplicate qualifying timestamp count",
                "source-order monotonicity",
                "complete, close-time, available-at, identity, and hash structure for any exact emission",
                "whole-source hash and sealed lineage binding",
            ],
            "calendar": "Use only the sealed row-registry availability disposition and weekday/IANA metadata; absence of a sealed closure is not proof that an emission existed.",
        },
        "crossed_state_tests": {
            "population": "Exactly the 15 primary feature rows with CONTINUOUS_MATCHING and book_crossed true; the reference feature file must identify the same hashed rows.",
            "state_row": [
                "map state_source_row_ordinal and state_ts_recv_ns exactly to one MBP-10 source row",
                "verify the mapped row is two-sided crossed without emitting any book field",
                "record action, side, snapshot/reset, flags, sequence, F_LAST, and hashed identity",
                "verify the selected row is the latest source-order MBP-10 row with ts_recv strictly before bucket end",
            ],
            "native_event_group": {
                "key": ["publisher_id", "instrument_id", "sequence"],
                "order": "ts_recv then source_row_ordinal; group rows must be contiguous in normalized source order.",
                "completion": "Exactly one F_LAST row and it is the terminal source-order row of the group.",
                "tests": [
                    "selected one-based group position and group row count",
                    "snapshot and reset membership",
                    "F_LAST count and terminal-after-selected boolean",
                    "terminal state classified only as TWO_SIDED_UNCROSSED, CROSSED, or ONE_SIDED",
                    "terminal timing before, at, or after the bucket close",
                    "completion in the same one-second bucket",
                    "whether crossing persists at the completed F_LAST boundary",
                    "same-K3 MBO metadata group presence, contiguity, action/side/flags, and F_LAST structure as non-selector corroboration",
                ],
            },
            "no_value_selector": "Book fields may calculate only two-sided/crossed/uncrossed class after the state row is selected by frozen metadata. They may never choose a row, group, boundary, or repair.",
        },
        "classification_rules": {
            "classes": classes,
            "xau_precedence": ["UNRESOLVED", "GENUINE_SOURCE_OR_STATE_FAILURE", "DOCUMENTED_VALID_SEMANTICS", "RECOVERABLE_EXISTING_SOURCE", "RECOVERABLE_TARGETED_REFRESH"],
            "xau": {
                "DOCUMENTED_VALID_SEMANTICS": "A pre-existing sealed market-calendar disposition marks the timestamp unavailable.",
                "RECOVERABLE_EXISTING_SOURCE": "Exactly one structurally valid qualifying emission exists in the sealed source but the Milestone 2 coverage selector omitted it.",
                "RECOVERABLE_TARGETED_REFRESH": "No qualifying emission exists, the session is sealed EXPECTED_AVAILABLE, DST agrees, adjacent sealed emissions establish local coverage, and no corruption declaration exists.",
                "GENUINE_SOURCE_OR_STATE_FAILURE": "A conflicting duplicate, malformed exact emission, order failure, or lineage failure is present.",
                "UNRESOLVED": "DST/calendar conflict, absent flanking coverage, parser disagreement, or insufficient metadata prevents another class.",
            },
            "crossed_precedence": ["UNRESOLVED", "GENUINE_SOURCE_OR_STATE_FAILURE", "RECOVERABLE_EXISTING_SOURCE", "DOCUMENTED_VALID_SEMANTICS"],
            "crossed": {
                "DOCUMENTED_VALID_SEMANTICS": "The selected crossed row is a non-snapshot, non-F_LAST partial native-event emission; the unique later terminal F_LAST is after the bucket close and is two-sided uncrossed.",
                "RECOVERABLE_EXISTING_SOURCE": "A unique two-sided uncrossed terminal F_LAST was already available strictly before the bucket close but the feature state selected an earlier crossed row.",
                "RECOVERABLE_TARGETED_REFRESH": "Not applicable to crossed-state findings.",
                "GENUINE_SOURCE_OR_STATE_FAILURE": "The selected row is a crossed completed F_LAST, the unique completed boundary remains crossed or one-sided, or a later eligible row other than the unique two-sided-uncrossed terminal boundary makes the selected state non-latest before bucket close.",
                "UNRESOLVED": "The state row cannot be mapped uniquely, the group is noncontiguous or lacks one terminal F_LAST, source metadata conflicts, or independent implementations disagree.",
            },
        },
        "independent_reproduction": {
            "primary": "Regex-only XAU scalar projection; sequential Parquet row-group feature scan; Arrow dataset range extraction and sequential native-group classification.",
            "reference": "Manual top-level JSON scalar scanner that skips nested values; dataset-filtered feature scan; Parquet row-group-statistics range extraction and dictionary native-group classification.",
            "required_exact": [
                "three XAU finding identities and all metadata classifications",
                "fifteen crossed bucket identities and all event-group classifications",
                "MBO corroboration counts and hashes",
                "source ordering, duplicate, lineage, DST, and calendar diagnostics",
                "classification counts, recommendation, and complete-result checksum",
            ],
            "any_difference": "FAIL_DIAGNOSTIC_REPRODUCTION",
        },
        "recommendation_rule": {
            "maximum": 1,
            "blocked": "If any finding is GENUINE_SOURCE_OR_STATE_FAILURE or UNRESOLVED, recommend NONE pending a separately authorized source/state resolution.",
            "bounded": {
                "recommendation_id": "TARGETED_XAU_REFRESH_AND_COMPLETED_MBP_STATE_RECERTIFICATION_V0_1",
                "condition": "Every XAU finding is documented, recoverable from existing source, or recoverable by targeted refresh; every crossed finding is documented valid semantics or recoverable from existing source.",
                "text": "In one future separately authorized amendment only: recover exactly the classified deficient XAU timestamps by the diagnosed source path, and construct authoritative MBP bucket-close state only from a valid snapshot baseline or unique terminal F_LAST native-event boundary. Preserve every other Milestone 2 definition and rerun full independent certification.",
            },
            "implementation_in_r1": False,
        },
        "formal_gates": {
            "predecessor_and_source_seals_valid": True,
            "exact_three_xau_findings": True,
            "exact_fifteen_crossed_bucket_findings": True,
            "every_finding_classified_once": True,
            "primary_reference_exact_reproduction": True,
            "no_market_or_feature_values_reported": True,
            "at_most_one_recommendation": True,
            "no_repair_refresh_filter_relabel_reacquisition_or_recalculation": True,
            "no_outcome_relationship_candidate_execution_or_performance_work": True,
            "no_2025_or_2026_access": True,
            "zero_charge": True,
        },
        "status_precedence": [
            "FAIL_PREDECESSOR_OR_SOURCE_INTEGRITY",
            "FAIL_DIAGNOSTIC_INTEGRITY",
            "FAIL_DIAGNOSTIC_REPRODUCTION",
            "PASS_DIAGNOSTIC_REPRODUCTION",
        ],
        "prohibited": [
            "modifying any Milestone 2 or predecessor artifact",
            "repairing, refreshing, filtering, relabeling, substituting, or reacquiring data",
            "rerunning or changing feature materialization",
            "using book equality or market values as a selector",
            "reporting OHLC, price, depth, order-flow, feature, or outcome values",
            "opening development outcomes or any 2025/2026 row or value",
            "relationships, hit rates, effects, candidates, signals, ranking, execution, trades, PnL, R multiples, or returns",
        ],
        "completion_policy": "Classify all 18 findings, recommend no more than one bounded future correction, independently reproduce, document, seal, and stop without implementation or research.",
    }


def main() -> None:
    if PROTOCOL_PATH.exists() or FREEZE_PATH.exists() or PREFLIGHT_PATH.exists():
        raise FileExistsError("Milestone 2-R1 was already prepared")
    predecessor = verify_predecessor()
    if not R1_ENGINE.is_file():
        raise FileNotFoundError(R1_ENGINE)
    frozen_at = utc_now()
    protocol = build_protocol(frozen_at)
    protocol["protocol_receipt"] = canonical_hash({**protocol, "protocol_receipt": None})
    write_json_exclusive(PROTOCOL_PATH, protocol)
    freeze: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_FREEZE_V1_0",
        "status": "SEALED_BEFORE_ROW_LEVEL_METADATA_ACCESS",
        "frozen_at_utc": frozen_at,
        "protocol": {"path": relative(PROTOCOL_PATH), "bytes": PROTOCOL_PATH.stat().st_size, "sha256": sha256_file(PROTOCOL_PATH)},
        "implementation": {"path": relative(R1_ENGINE), "bytes": R1_ENGINE.stat().st_size, "sha256": sha256_file(R1_ENGINE)},
        "bound_predecessors": {name: expected for name, (_, expected) in BOUND.items()},
        "expected_findings": {"xau_timestamp": 3, "crossed_bucket_close": 15, "total": 18},
        "row_level_metadata_accessed_before_freeze": False,
        "market_book_feature_or_outcome_values_accessed_before_freeze": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = canonical_hash({**freeze, "freeze_receipt": None})
    write_json_exclusive(FREEZE_PATH, freeze)
    preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_PROTOCOL_PREFLIGHT_V1_0",
        "status": "PASS_M2_R1_PROTOCOL_FROZEN_BEFORE_ROW_ACCESS",
        "completed_at_utc": utc_now(),
        "predecessor": predecessor,
        "protocol": {"path": relative(PROTOCOL_PATH), "bytes": PROTOCOL_PATH.stat().st_size, "sha256": sha256_file(PROTOCOL_PATH)},
        "freeze": {"path": relative(FREEZE_PATH), "bytes": FREEZE_PATH.stat().st_size, "sha256": sha256_file(FREEZE_PATH)},
        "implementation": {"path": relative(R1_ENGINE), "bytes": R1_ENGINE.stat().st_size, "sha256": sha256_file(R1_ENGINE)},
        "row_level_metadata_accessed": False,
        "market_book_feature_or_outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "preflight_receipt": None,
    }
    preflight["preflight_receipt"] = canonical_hash({**preflight, "preflight_receipt": None})
    write_json_exclusive(PREFLIGHT_PATH, preflight)
    print(json.dumps({
        "status": preflight["status"],
        "protocol_sha256": preflight["protocol"]["sha256"],
        "freeze_sha256": preflight["freeze"]["sha256"],
        "implementation_sha256": preflight["implementation"]["sha256"],
        "expected_findings": freeze["expected_findings"],
        "row_level_metadata_accessed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
