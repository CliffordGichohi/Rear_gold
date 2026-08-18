#!/usr/bin/env python3
"""Freeze the bounded Step 5D-R3 amendment before outcome-value access."""

from __future__ import annotations

from collections import Counter
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
import platform
from typing import Any, Mapping

import numpy as np
import pyarrow as pa


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
AMENDMENT_PATH = MANIFESTS / "gc_microstructure_step_5dr3_amendment_v01.json"
POPULATION_PATH = MANIFESTS / "gc_microstructure_step_5dr3_population_v01.json"
FREEZE_PATH = MANIFESTS / "gc_microstructure_step_5dr3_freeze_v01.json"
IMPLEMENTATION_PATH = ROOT / "tools" / "run_gc_microstructure_step5dr3.py"
ROW_REGISTRY_PATH = MANIFESTS / "gc_microstructure_step_5c_row_registry_v01.json"
R1_PRIMARY_PATH = ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "primary_corrected_diagnostic.json"
R1_REFERENCE_PATH = ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "reference_corrected_diagnostic.json"


BOUND: dict[str, tuple[Path, str]] = {
    "discovery_contract": (
        MANIFESTS / "gc_microstructure_conditional_edge_discovery_contract_v01.json",
        "da9048f497c853ef3b1f2a4debe6c80f8c650217004bfe6df05e045751554fcb",
    ),
    "feature_hypothesis_registry": (
        MANIFESTS / "gc_microstructure_step_5a_feature_hypothesis_registry_v01.json",
        "4b207a1dec5aa78a904c86cf8c6a14bf0a517dd918f24c5270c254400c865f01",
    ),
    "step5b2_amendment": (
        MANIFESTS / "gc_microstructure_step_5b2_amendment_v01.json",
        "1a6dd3372f40b52d219b38e35504b9a96046ffc284117ed1ac6cc703d009f9d7",
    ),
    "step5b2_freeze": (
        MANIFESTS / "gc_microstructure_step_5b2_freeze_v01.json",
        "0c1e7b8db099ea4489c201dda9893da184a55f8159f89a4ce946e78a1485f918",
    ),
    "step5b2_manifest": (
        ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "manifest.json",
        "3fedb586ce4f9621721575b748b82043f47a4f6630488c29e0b2f8e73b4c86f1",
    ),
    "step5b2_verdict": (
        ARTIFACTS / "gc_microstructure_step_5b2_v01" / "step5b2_final" / "verdict.json",
        "5f3bd13cc2336a50c09ecfcc44c7d63b226a4d212f9d08666d6a50e93e09a6cb",
    ),
    "step5c_protocol": (
        MANIFESTS / "gc_microstructure_step_5c_protocol_v01.json",
        "25e087ae505bd2b304b5d9533c9fb8dd8042b47e8e498ed82242ad48365e272d",
    ),
    "step5c_freeze": (
        MANIFESTS / "gc_microstructure_step_5c_freeze_v01.json",
        "5ad5d57af1fdab6a80e90cb872408f1f6df99d2d7a4a892a5f380c49aee9f82d",
    ),
    "step5c_row_registry": (
        ROW_REGISTRY_PATH,
        "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225",
    ),
    "step5c_manifest": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "manifest.json",
        "f7150f861f4883e3f7c100822af527ba497b8343225c24ebe16ffe11107e31fb",
    ),
    "step5c_verdict": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "verdict.json",
        "f98702e5260f60fa258a8f5ed43adc944724075bf442f958677fdf8fe3dee2ad",
    ),
    "step5d_protocol": (
        MANIFESTS / "gc_microstructure_step_5d_protocol_v01.json",
        "835361070b3955912938b5519ec0b7b32542d6774c895f43bde11a93fb268b64",
    ),
    "step5d_test_registry": (
        MANIFESTS / "gc_microstructure_step_5d_test_registry_v01.json",
        "e3b7a132f03cebaff4c05cc646e00f0b1867881d0109c65b71f1076e74ab2d4a",
    ),
    "step5d_freeze": (
        MANIFESTS / "gc_microstructure_step_5d_freeze_v01.json",
        "982464e185fabaab57b5871506fc3f75b9f577267eb3bcd52ebd83a4fbf2725d",
    ),
    "step5d_implementation_amendment_a": (
        MANIFESTS / "gc_microstructure_step_5d_implementation_amendment_a_v01.json",
        "436300bc285914a9151c3fe74ec25a8b6c7651716a2e94c0e0c86f39537332fe",
    ),
    "step5d_implementation_v02": (
        MANIFESTS / "gc_microstructure_step_5d_implementation_v02.json",
        "ffebe445bb2732a2e29105c148b702bf800fb211a9d47a545722597ae2fa38c3",
    ),
    "step5d_frozen_runner": (
        ROOT / "tools" / "run_gc_microstructure_step5d.py",
        "b129b18d6f62ba8338c81b05163b9ee8e4cff0fd79d8f3fd89a50b7ecef6e44a",
    ),
    "step5d_outcome_join_failure": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "outcome_opening_failure.json",
        "44f32d8da4e58d19f1f4e2d2a9fccace63457f75fa58370e119d0b5273090805",
    ),
    "step5d_verdict": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "verdict.json",
        "3ec082a95bd48cb412b9771eaae8cffd1641593c7ad60b033da3c9a95a6994ef",
    ),
    "step5d_final_seal": (
        ARTIFACTS / "gc_microstructure_step5d_v01" / "final_seal.json",
        "17f2a97487c72cf447eed34b6dabda558af7f88671fc845316139c2a1c71c2db",
    ),
    "step5dr1_protocol": (
        MANIFESTS / "gc_microstructure_step_5dr1_protocol_v01.json",
        "18c4637970505d6b2f58e74e7cc4f8bb862bf50e1336aa6fd62057eaac3536ac",
    ),
    "step5dr1_freeze": (
        MANIFESTS / "gc_microstructure_step_5dr1_freeze_v01.json",
        "3d2602f6c2efb8c2146835c8b877727d7a0a4bc82aa66d5617e08be18fc5b34d",
    ),
    "step5dr1_primary_corrected": (
        R1_PRIMARY_PATH,
        "f7e3460e32df145a15b24696bd5db8d78c15069b85e002310c6685c47b37421c",
    ),
    "step5dr1_reference_corrected": (
        R1_REFERENCE_PATH,
        "3e81ae8e8d925f266c2a98c18061368ef534055ea0f52bfe5bd806776cbf7cb9",
    ),
    "step5dr1_corrected_final_seal": (
        ARTIFACTS / "gc_microstructure_step5dr1_corrected_v01" / "final_seal.json",
        "885d292f604669011a76b28bb649baf8389d7a2ecd59ff43d42abce08e9ae578",
    ),
    "step5dr2_protocol": (
        MANIFESTS / "gc_microstructure_step_5dr2_recovery_protocol_v01.json",
        "fdd48b9bf9c70070cbc876612956dd9cc4dcb6097cddf3229febea2e64ef9590",
    ),
    "step5dr2_freeze": (
        MANIFESTS / "gc_microstructure_step_5dr2_recovery_freeze_v01.json",
        "6cc8d3c91351068d303e1e4e49804fb5ef5fc32e1b2002adfde8bb1059414334",
    ),
    "step5dr2_certification": (
        ARTIFACTS / "gc_microstructure_step5dr2_v01" / "certification.json",
        "454638ff5b011c75f94ba690114c0552bb333902986b7fa24dbaf4b707292e67",
    ),
    "step5dr2_verdict": (
        ARTIFACTS / "gc_microstructure_step5dr2_v01" / "verdict.json",
        "af596de71061eca5f18706bd62dea2f90b81b5799642bc03ba4f5f9b87592533",
    ),
    "step5dr2_final_seal": (
        ARTIFACTS / "gc_microstructure_step5dr2_v01" / "final_seal.json",
        "65a7b19971eae1d434720f79d0dcd39d4c05d4fbb41ab995ac4632f49d80ad24",
    ),
    "step5c_primary_features": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "primary_decision_features.parquet",
        "277993e0cd2d5bff2e8f49c6aaf519ac024a1f7ac1ed8bbd0808f5d3213b5d98",
    ),
    "step5c_reference_features": (
        ARTIFACTS / "gc_microstructure_step5c_v01" / "reference_decision_features.parquet",
        "277993e0cd2d5bff2e8f49c6aaf519ac024a1f7ac1ed8bbd0808f5d3213b5d98",
    ),
    "v3_case_payload": (
        ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01" / "cases.jsonl.gz",
        "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9",
    ),
    "casebook_price_bars": (
        ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz",
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
    ),
}

GOOD_FRIDAY_KEYS = {
    ("2022-04-15", "LONDON"),
    ("2022-04-15", "NEW_YORK"),
}
SOURCE_UNAVAILABLE_KEYS = {
    ("2021-12-13", "NEW_YORK"),
    ("2023-03-15", "NEW_YORK"),
    ("2023-08-15", "LONDON"),
    ("2023-09-13", "NEW_YORK"),
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
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
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite frozen artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def public_key(key: tuple[str, str]) -> dict[str, str]:
    return {"session_date": key[0], "session_code": key[1]}


def main() -> None:
    if AMENDMENT_PATH.exists() or POPULATION_PATH.exists() or FREEZE_PATH.exists():
        raise FileExistsError("Step 5D-R3 is already frozen")
    for name, (path, expected) in BOUND.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Predecessor seal failed: {name} {actual}")
    if not IMPLEMENTATION_PATH.is_file():
        raise FileNotFoundError(IMPLEMENTATION_PATH)

    original_failure = load_json(BOUND["step5d_outcome_join_failure"][0])
    if original_failure.get("status") != "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE":
        raise ValueError("Original Step 5D failure changed")
    if (
        original_failure.get("source_stream_open_count") != 1
        or original_failure.get("relationship_tests_executed") != 0
    ):
        raise ValueError("Original Step 5D access history changed")
    r2_verdict = load_json(BOUND["step5dr2_verdict"][0])
    if r2_verdict.get("status") != "FAIL_STEP_5D_R2_RECOVERY_OR_METADATA_CERTIFICATION":
        raise ValueError("Step 5D-R2 formal failure changed")

    registry = load_json(ROW_REGISTRY_PATH)
    rows = registry.get("rows")
    if not isinstance(rows, list) or len(rows) != 376:
        raise ValueError("Step 5C feature-row population changed")
    all_keys_list = [
        (str(row["session_date"]), str(row["session_code"]))
        for row in rows
    ]
    if len(set(all_keys_list)) != 376:
        raise ValueError("Feature-row keys are not unique")
    all_keys = set(all_keys_list)
    if Counter(code for _, code in all_keys) != {"LONDON": 188, "NEW_YORK": 188}:
        raise ValueError("Feature-row session counts changed")
    if not GOOD_FRIDAY_KEYS.issubset(all_keys) or not SOURCE_UNAVAILABLE_KEYS.issubset(all_keys):
        raise ValueError("Frozen UNKNOWN key is absent from the feature rows")

    primary = load_json(R1_PRIMARY_PATH)
    reference = load_json(R1_REFERENCE_PATH)
    if primary.get("result_checksum") != reference.get("result_checksum"):
        raise ValueError("Corrected R1 independent reproductions disagree")
    primary_keys = primary.get("result", {}).get("keys", [])
    reference_keys = reference.get("result", {}).get("keys", [])
    primary_projection = sorted(
        (str(item["session_date"]), str(item["session_code"]), str(item["classification"]))
        for item in primary_keys
    )
    reference_projection = sorted(
        (str(item["session_date"]), str(item["session_code"]), str(item["classification"]))
        for item in reference_keys
    )
    if primary_projection != reference_projection or len(primary_projection) != 16:
        raise ValueError("Corrected R1 missing-key registry changed")
    existing_recovery_keys = {
        (session_date, session_code)
        for session_date, session_code, classification in primary_projection
        if classification == "RECOVERABLE_EXISTING_SEALED_SOURCE"
    }
    refresh_keys = {
        (session_date, session_code)
        for session_date, session_code, classification in primary_projection
        if classification == "RECOVERABLE_TARGETED_MT5_REFRESH"
    }
    if len(existing_recovery_keys) != 12 or refresh_keys != SOURCE_UNAVAILABLE_KEYS:
        raise ValueError("R3 source-unavailability disposition differs from corrected R1")

    unknown_keys = GOOD_FRIDAY_KEYS | SOURCE_UNAVAILABLE_KEYS
    outcome_bearing_keys = all_keys - unknown_keys
    v3_payload_keys = outcome_bearing_keys - existing_recovery_keys
    if len(outcome_bearing_keys) != 370 or len(v3_payload_keys) != 358:
        raise ValueError("R3 effective-population arithmetic failed")
    if v3_payload_keys & existing_recovery_keys or unknown_keys & outcome_bearing_keys:
        raise ValueError("R3 source allocations overlap")

    session_counts = {
        session: {
            "feature_rows": sum(code == session for _, code in all_keys),
            "known_outcomes": sum(code == session for _, code in outcome_bearing_keys),
            "v3_payload_outcomes": sum(code == session for _, code in v3_payload_keys),
            "recovered_price_bar_outcomes": sum(code == session for _, code in existing_recovery_keys),
            "unknown_rows": sum(code == session for _, code in unknown_keys),
        }
        for session in ("LONDON", "NEW_YORK")
    }
    expected_session_counts = {
        "LONDON": {
            "feature_rows": 188,
            "known_outcomes": 186,
            "v3_payload_outcomes": 180,
            "recovered_price_bar_outcomes": 6,
            "unknown_rows": 2,
        },
        "NEW_YORK": {
            "feature_rows": 188,
            "known_outcomes": 184,
            "v3_payload_outcomes": 178,
            "recovered_price_bar_outcomes": 6,
            "unknown_rows": 4,
        },
    }
    if session_counts != expected_session_counts:
        raise ValueError(f"R3 per-session population changed: {session_counts}")

    frozen_at = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    predecessor_bindings = {
        name: {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": expected,
        }
        for name, (path, expected) in BOUND.items()
    }
    amendment: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_SOURCE_UNAVAILABILITY_AMENDMENT_V0_1",
        "status": "SEALED_BEFORE_R3_OUTCOME_VALUE_ACCESS",
        "classification": "BOUNDED_SOURCE_UNAVAILABILITY_AND_OUTCOME_POPULATION_AMENDMENT",
        "frozen_at_utc": frozen_at,
        "authority": {
            "authorized_step": "STEP_5D_R3",
            "authorized_operations": [
                "exactly one controlled recovery outcome construction and join",
                "unchanged Stage 1 followed by unchanged registered Stage 2",
                "independent complete reproduction, documentation, and sealing",
            ],
            "mandatory_stop": "Stop after the Step 5D-R3 result is independently reproduced, documented, and sealed.",
        },
        "permanent_dispositions": [
            {**public_key(key), "disposition": "DOCUMENTED_SOURCE_UNAVAILABLE_FOR_THIS_STUDY"}
            for key in sorted(SOURCE_UNAVAILABLE_KEYS)
        ],
        "disposition_rules": {
            "imputation": False,
            "provider_substitution": False,
            "holiday_reclassification": False,
            "selective_filtering": False,
            "four_keys_are_explicit_unknown_rows": True,
        },
        "effective_population": {
            "known_outcomes": 370,
            "previously_available_v3_outcomes": 358,
            "recoverable_from_existing_sealed_price_source": 12,
            "documented_unknown_rows": 6,
            "feature_rows_retained": 376,
            "session_counts": session_counts,
        },
        "unchanged_analysis": {
            "neutral_outcome_definition": "Open of first complete one-minute bar at 08:01 local through close of the 11:59 local bar; UP above +0.01, DOWN below -0.01, otherwise FLAT.",
            "test_registry_sha256": BOUND["step5d_test_registry"][1],
            "registered_tests": 148,
            "stage_order": "Seal complete Stage 1 before evaluating Stage 2.",
            "sessions_separate": True,
            "maximum_provisional_candidates_per_session": 2,
            "zero_candidates_acceptable": True,
            "all_test_definitions_seeds_multiplicity_support_stability_ranking_and_verdict_gates": "UNCHANGED",
        },
        "preserved_history": {
            "step5d_original_status": "FAIL_STEP_5D_OUTCOME_JOIN_COVERAGE",
            "step5d_original_source_open_count": 1,
            "step5d_original_tests_executed": 0,
            "step5dr1_corrected_status": "PASS_STEP_5D_R1_DIAGNOSTIC_REPRODUCTION_AFTER_IMPLEMENTATION_CORRECTION",
            "step5dr2_status": "FAIL_STEP_5D_R2_RECOVERY_OR_METADATA_CERTIFICATION",
            "all_prior_verdicts_artifacts_and_seals_immutable": True,
        },
        "predecessor_bindings": predecessor_bindings,
        "implementation": {
            "path": str(IMPLEMENTATION_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(IMPLEMENTATION_PATH),
            "original_frozen_step5d_runner_sha256": BOUND["step5d_frozen_runner"][1],
            "modification_after_freeze_prohibited": True,
        },
        "prohibited": [
            "adding retuning inverting repairing or selectively filtering tests or candidates",
            "changing seeds multiplicity support stability ranking or verdict rules",
            "2025 or 2026 value access",
            "execution optimization or calculation of trades PnL R multiples or account returns",
            "new acquisition charge or provider substitution",
        ],
        "outcome_values_accessed_before_amendment_seal": False,
        "year_2025_or_2026_values_accessed": False,
    }
    amendment["amendment_receipt"] = canonical_hash(amendment)
    write_json_exclusive(AMENDMENT_PATH, amendment)

    population: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_EXACT_POPULATION_V0_1",
        "status": "SEALED_EXACT_370_OUTCOME_KEY_POPULATION",
        "sealed_at_utc": frozen_at,
        "all_feature_keys": [public_key(key) for key in sorted(all_keys)],
        "outcome_bearing_keys": [public_key(key) for key in sorted(outcome_bearing_keys)],
        "v3_payload_keys": [public_key(key) for key in sorted(v3_payload_keys)],
        "recovered_price_bar_keys": [public_key(key) for key in sorted(existing_recovery_keys)],
        "unknown_keys": [
            {
                **public_key(key),
                "disposition": (
                    "UNAVAILABLE_DOCUMENTED_CME_GOOD_FRIDAY"
                    if key in GOOD_FRIDAY_KEYS
                    else "DOCUMENTED_SOURCE_UNAVAILABLE_FOR_THIS_STUDY"
                ),
            }
            for key in sorted(unknown_keys)
        ],
        "counts": {
            "feature_rows": 376,
            "outcome_bearing": 370,
            "v3_payload": 358,
            "recovered_price_bars": 12,
            "unknown": 6,
            "per_session": session_counts,
        },
        "source_allocation_is_disjoint_and_exhaustive": True,
        "outcome_values_accessed_to_construct_registry": False,
        "population_hash": canonical_hash({
            "outcome_bearing_keys": [public_key(key) for key in sorted(outcome_bearing_keys)],
            "v3_payload_keys": [public_key(key) for key in sorted(v3_payload_keys)],
            "recovered_price_bar_keys": [public_key(key) for key in sorted(existing_recovery_keys)],
            "unknown_keys": [public_key(key) for key in sorted(unknown_keys)],
        }),
    }
    population["population_receipt"] = canonical_hash(population)
    write_json_exclusive(POPULATION_PATH, population)

    freeze: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_FREEZE_V0_1",
        "status": "SEALED_BEFORE_R3_OUTCOME_VALUE_ACCESS",
        "frozen_at_utc": frozen_at,
        "amendment": {
            "path": str(AMENDMENT_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(AMENDMENT_PATH),
            "receipt": amendment["amendment_receipt"],
        },
        "population": {
            "path": str(POPULATION_PATH.relative_to(ROOT)).replace("\\", "/"),
            "sha256": sha256_file(POPULATION_PATH),
            "receipt": population["population_receipt"],
            "population_hash": population["population_hash"],
        },
        "implementation": amendment["implementation"],
        "runtime": {
            "python": platform.python_version(),
            "numpy": np.__version__,
            "pyarrow": pa.__version__,
        },
        "predecessor_hashes": {name: expected for name, (_, expected) in BOUND.items()},
        "outcome_values_accessed_before_freeze": False,
        "development_outcome_sources_opened_by_r3_before_freeze": 0,
        "year_2025_or_2026_values_accessed": False,
        "next_action": "Run preflight, then exactly one controlled R3 recovery construction and join, Stage 1, Stage 2, independent reproduction, final seal, and stop.",
    }
    freeze["freeze_receipt"] = canonical_hash(freeze)
    write_json_exclusive(FREEZE_PATH, freeze)
    print(json.dumps({
        "status": freeze["status"],
        "amendment_sha256": sha256_file(AMENDMENT_PATH),
        "population_sha256": sha256_file(POPULATION_PATH),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "freeze_receipt": freeze["freeze_receipt"],
        "implementation_sha256": amendment["implementation"]["sha256"],
        "feature_rows": 376,
        "known_outcomes": 370,
        "v3_payload_outcomes": 358,
        "recovered_price_bar_outcomes": 12,
        "unknown_rows": 6,
        "outcome_values_accessed": False,
    }, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
