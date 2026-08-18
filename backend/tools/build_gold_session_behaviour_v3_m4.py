from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_discovery_validation import (
    VALIDATION_RULESET_VERSION,
    validate_discovery_semantics,
)
from gold_intel.analytics.session_behaviour_v3_relationships import (
    RELATIONSHIP_ENGINE_VERSION,
    DiscoveryCase,
    build_discovery_results,
    materialize_discovery_case,
)

M4_PRE_RESULT_MANIFEST_HASH = (
    "e024ceba35a6d3af1c384f8c66eec299aab8cdcd23b666eb9f33ac672a24fbf4"
)
M4_PRE_RESULT_MANIFEST_FILE_HASH = (
    "e11b86385c1d7594a48ef1d11fc04b65ac979c952251078528ed727f0fd91127"
)
M3_STATE_HASH = "c569bd67aae862c4e86de49aa99d4d33ee6d820cf970251603a74f73619045a7"
M3_STATE_FILE_HASH = (
    "f56a8732fe466f2f5574c80b9421eb5b3f2f7e1435fd177bcae4c57cb9efc980"
)
CONTRACT_HASH = "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
TRACEABILITY_HASH = (
    "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4"
)
CASE_MANIFEST_HASH = (
    "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
)
CASE_ARTIFACT_HASH = (
    "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
)
BOOK_HASH = "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a"
FEATURE_MODULE_HASH = (
    "921a6d02c71514438e46a81d22f0ea788b2bdfca88172e564d10b510f14e96dc"
)
FEATURE_TEST_HASH = (
    "bc2e40acbdd1cdbcd8e8dfd3be675518c25a991f7e7d49a6966946e5217f74c8"
)
RELATIONSHIP_MODULE_HASH = (
    "8ad9c8adfc94ea433e185ce1b17b7f9f1d8981f29b7b967b338d351b8f51ee97"
)
VALIDATION_MODULE_HASH = (
    "a8584de3c2fcb8e11d0b0e6fd16a85f7bcf7887eef2e7e6c0309cb9d48925a4c"
)
RELATIONSHIP_TEST_HASH = (
    "3f32083c0da1f75937cfaf0948e46bcdb2e9654eff2b6e709497088199949733"
)
RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M4_RESULT_V0_1"
BUILD_VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M4_BUILD_VALIDATION_V0_1"
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    if root not in output_dir.parents:
        raise ValueError("Output directory must remain inside the repository root")
    result = build(root=root, output_dir=output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


def build(*, root: Path, output_dir: Path) -> dict[str, Any]:
    paths = _paths(root)
    frozen_manifest = _verify_pre_read_seals(paths)
    cases, readback = _read_cases(
        paths["cases"],
        features=list(frozen_manifest["feature_registry"]),
    )

    discovery = build_discovery_results(
        cases,
        frozen_manifest=frozen_manifest,
    )
    semantic_errors = validate_discovery_semantics(
        discovery,
        frozen_manifest=frozen_manifest,
    )
    if semantic_errors:
        raise ValueError(
            "Discovery semantic validation failed before sealing: "
            f"{semantic_errors}"
        )

    output_dir.mkdir(parents=True, exist_ok=True)
    relationships_path = output_dir / "relationships.json"
    validation_path = output_dir / "semantic_validation.json"
    manifest_path = output_dir / "manifest.json"
    _write_json(relationships_path, discovery)

    validation = _build_validation(
        discovery=discovery,
        discovery_path=relationships_path,
        frozen_manifest=frozen_manifest,
        readback=readback,
        semantic_errors=semantic_errors,
    )
    _write_hashed_json(
        validation_path,
        validation,
        hash_field="validation_hash",
    )
    saved_validation = _load_json(validation_path)

    recorded_at = str(frozen_manifest["recorded_at"])
    manifest: dict[str, Any] = {
        "manifest_version": RESULT_VERSION,
        "milestone": "V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY",
        "created_at": recorded_at,
        "sealed_at": recorded_at,
        "pre_result_manifest": {
            "path": (
                "research_manifests/"
                "gold_session_behaviour_v3_m4_discovery_v01.json"
            ),
            "manifest_hash": M4_PRE_RESULT_MANIFEST_HASH,
            "file_sha256": M4_PRE_RESULT_MANIFEST_FILE_HASH,
            "sealed_before_relationship_calculation": True,
        },
        "source": {
            "case_artifact_path": (
                "research_artifacts/"
                "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
            ),
            "case_artifact_sha256": CASE_ARTIFACT_HASH,
            "case_matrix_manifest_hash": CASE_MANIFEST_HASH,
            "predecessor_state_hash": M3_STATE_HASH,
            "contract_hash": CONTRACT_HASH,
            "traceability_catalog_hash": TRACEABILITY_HASH,
            "all_seals_verified_before_case_read": True,
            "source_record_hash_chain": readback["record_hash_chain"],
        },
        "implementation_seals": {
            "feature_module_sha256": FEATURE_MODULE_HASH,
            "feature_test_sha256": FEATURE_TEST_HASH,
            "relationship_engine_version": RELATIONSHIP_ENGINE_VERSION,
            "relationship_module_sha256": RELATIONSHIP_MODULE_HASH,
            "relationship_test_sha256": RELATIONSHIP_TEST_HASH,
            "semantic_validation_ruleset_version": (
                VALIDATION_RULESET_VERSION
            ),
            "semantic_validation_module_sha256": VALIDATION_MODULE_HASH,
            "implementation_frozen_before_relationship_calculation": True,
        },
        "artifacts": [
            {
                "name": "relationships.json",
                "path": "relationships.json",
                "bytes": relationships_path.stat().st_size,
                "sha256": sha256_file(relationships_path),
                "discovery_hash": discovery["discovery_hash"],
            },
            {
                "name": "semantic_validation.json",
                "path": "semantic_validation.json",
                "bytes": validation_path.stat().st_size,
                "sha256": sha256_file(validation_path),
                "validation_hash": saved_validation["validation_hash"],
            },
        ],
        "case_counts": discovery["case_counts"],
        "integrity": {
            "source_records_read": readback["records_read"],
            "source_record_hash_mismatches": readback[
                "record_hash_mismatches"
            ],
            "unique_case_ids": readback["unique_case_ids"],
            "unique_session_dates": readback["unique_session_dates"],
            "row_order_violations": readback["row_order_violations"],
            "undeclared_feature_states": readback[
                "undeclared_feature_states"
            ],
            "discovery_semantic_errors": len(semantic_errors),
            "build_validation_checks_failed": saved_validation["summary"][
                "failed"
            ],
            "build_validation_checks_passed": saved_validation["summary"][
                "passed"
            ],
        },
        "relationship_inventory": _relationship_inventory(discovery),
        "provisional_candidates": {
            session_code: list(
                discovery["sessions"][session_code]["provisional_candidates"]
            )
            for session_code in ("LONDON", "NEW_YORK")
        },
        "research_boundary": dict(discovery["interpretation_boundary"]),
        "verdict": "PASS_V3_MILESTONE_4_DISCOVERY_SEALED",
        "mandatory_stop": True,
        "next_milestone": {
            "code": "V3_M5_CANDIDATE_STABILITY_AND_FREEZE",
            "authorized": False,
            "started": False,
        },
    }
    _write_hashed_json(manifest_path, manifest, hash_field="manifest_hash")
    saved_manifest = _load_json(manifest_path)
    return {
        "candidate_counts": {
            session_code: len(
                discovery["sessions"][session_code][
                    "provisional_candidates"
                ]
            )
            for session_code in ("LONDON", "NEW_YORK")
        },
        "cases": discovery["case_counts"]["total"],
        "discovery_file_sha256": sha256_file(relationships_path),
        "discovery_hash": discovery["discovery_hash"],
        "manifest": str(manifest_path),
        "manifest_hash": saved_manifest["manifest_hash"],
        "relationships": str(relationships_path),
        "semantic_validation": str(validation_path),
        "semantic_validation_hash": saved_validation["validation_hash"],
        "verdict": saved_manifest["verdict"],
    }


def _read_cases(
    path: Path,
    *,
    features: list[Mapping[str, Any]],
) -> tuple[list[DiscoveryCase], dict[str, Any]]:
    cases: list[DiscoveryCase] = []
    case_ids: set[str] = set()
    session_dates: set[tuple[str, str]] = set()
    session_counts: Counter[str] = Counter()
    record_hashes: list[str] = []
    row_order_violations = 0
    record_hash_mismatches = 0
    undeclared_feature_states: Counter[str] = Counter()
    prior_key: tuple[str, int] | None = None
    order = {"LONDON": 0, "NEW_YORK": 1}
    definitions = {
        str(item["feature_id"]): item
        for item in features
    }

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            if not isinstance(record, dict):
                raise ValueError(f"Case is not an object on line {line_number}")
            metadata = record["case_metadata"]
            supplied_hash = str(metadata.pop("record_hash"))
            calculated_hash = canonical_hash(record)
            metadata["record_hash"] = supplied_hash
            if calculated_hash != supplied_hash:
                record_hash_mismatches += 1
                raise ValueError(
                    f"Case record hash mismatch on line {line_number}"
                )
            case = materialize_discovery_case(record, features=features)
            if case.case_id in case_ids:
                raise ValueError(f"Duplicate case ID: {case.case_id}")
            case_ids.add(case.case_id)
            date_key = (case.session_code, case.session_date.isoformat())
            if date_key in session_dates:
                raise ValueError(f"Duplicate session date: {date_key}")
            session_dates.add(date_key)
            key = (case.session_date.isoformat(), order[case.session_code])
            if prior_key is not None and key <= prior_key:
                row_order_violations += 1
            prior_key = key

            expected_feature_ids = {
                feature_id
                for feature_id, definition in definitions.items()
                if case.session_code in definition["sessions"]
            }
            if set(case.features) != expected_feature_ids:
                raise ValueError(
                    f"Feature extraction mismatch: {case.case_id}"
                )
            for feature_id, observation in case.features.items():
                allowed = set(definitions[feature_id]["states"])
                if observation.state not in allowed:
                    undeclared_feature_states[
                        f"{feature_id}={observation.state}"
                    ] += 1
                    continue
                if not observation.source_signature:
                    raise ValueError(
                        f"Empty source signature for {feature_id} "
                        f"in {case.case_id}"
                    )
            session_counts[case.session_code] += 1
            record_hashes.append(supplied_hash)
            cases.append(case)

    if undeclared_feature_states:
        raise ValueError(
            "Undeclared extracted feature states across the sealed matrix: "
            f"{dict(sorted(undeclared_feature_states.items()))}"
        )
    return cases, {
        "records_read": len(cases),
        "record_hash_mismatches": record_hash_mismatches,
        "record_hash_chain": canonical_hash(record_hashes),
        "row_order_violations": row_order_violations,
        "session_counts": dict(sorted(session_counts.items())),
        "undeclared_feature_states": sum(
            undeclared_feature_states.values()
        ),
        "unique_case_ids": len(case_ids),
        "unique_session_dates": len(session_dates),
    }


def _build_validation(
    *,
    discovery: Mapping[str, Any],
    discovery_path: Path,
    frozen_manifest: Mapping[str, Any],
    readback: Mapping[str, Any],
    semantic_errors: list[str],
) -> dict[str, Any]:
    sessions = discovery["sessions"]
    inventory = _relationship_inventory(discovery)
    checks = [
        _check(
            "PRE_READ_SEALS",
            True,
            {
                "m4_pre_result_manifest_hash": (
                    M4_PRE_RESULT_MANIFEST_HASH
                ),
                "m3_state_hash": M3_STATE_HASH,
                "contract_hash": CONTRACT_HASH,
                "traceability_hash": TRACEABILITY_HASH,
                "case_manifest_hash": CASE_MANIFEST_HASH,
                "case_artifact_hash": CASE_ARTIFACT_HASH,
                "reference_book_hash": BOOK_HASH,
            },
        ),
        _check(
            "IMPLEMENTATION_SEALED_BEFORE_CALCULATION",
            True,
            {
                "feature_module_sha256": FEATURE_MODULE_HASH,
                "relationship_module_sha256": RELATIONSHIP_MODULE_HASH,
                "semantic_validation_module_sha256": (
                    VALIDATION_MODULE_HASH
                ),
            },
        ),
        _check(
            "EXACT_SOURCE_COUNTS",
            readback["records_read"] == 1659
            and readback["session_counts"]
            == {"LONDON": 833, "NEW_YORK": 826},
            dict(readback),
        ),
        _check(
            "SOURCE_RECORD_HASHES_IDENTITIES_AND_ORDER",
            readback["record_hash_mismatches"] == 0
            and readback["unique_case_ids"] == 1659
            and readback["unique_session_dates"] == 1659
            and readback["row_order_violations"] == 0,
            {
                "record_hash_mismatches": readback[
                    "record_hash_mismatches"
                ],
                "unique_case_ids": readback["unique_case_ids"],
                "unique_session_dates": readback["unique_session_dates"],
                "row_order_violations": readback[
                    "row_order_violations"
                ],
            },
        ),
        _check(
            "FEATURE_STATES_DECLARED",
            readback["undeclared_feature_states"] == 0,
            {
                "undeclared_feature_states": readback[
                    "undeclared_feature_states"
                ]
            },
        ),
        _check(
            "DISCOVERY_HASH",
            discovery["discovery_hash"]
            == canonical_hash(
                {
                    key: value
                    for key, value in discovery.items()
                    if key != "discovery_hash"
                }
            ),
            {"discovery_hash": discovery["discovery_hash"]},
        ),
        _check(
            "DISCOVERY_SEMANTICS",
            not semantic_errors,
            {"errors": semantic_errors},
        ),
        _check(
            "SESSION_SEPARATION",
            set(sessions) == {"LONDON", "NEW_YORK"}
            and discovery["interpretation_boundary"][
                "combined_session_result"
            ]
            is False,
            {"session_keys": sorted(sessions)},
        ),
        _check(
            "SINGLES_BEFORE_FROZEN_INTERACTIONS",
            inventory["LONDON"]["single_registered"]
            == inventory["LONDON"]["single_recorded"]
            and inventory["NEW_YORK"]["single_registered"]
            == inventory["NEW_YORK"]["single_recorded"]
            and inventory["LONDON"]["interaction_registered"]
            == inventory["LONDON"]["interaction_recorded"]
            and inventory["NEW_YORK"]["interaction_registered"]
            == inventory["NEW_YORK"]["interaction_recorded"],
            inventory,
        ),
        _check(
            "ALL_RESULTS_AND_NEGATIVE_RESULTS_RETAINED",
            all(
                item["relationships_recorded"]
                == item["relationships_registered"]
                and item["did_not_pass_candidate_gate"]
                + item["candidate_gate_pass"]
                == item["relationships_recorded"]
                for item in inventory.values()
            ),
            inventory,
        ),
        _check(
            "PROVISIONAL_CANDIDATE_CAP",
            all(
                len(sessions[code]["provisional_candidates"]) <= 2
                for code in ("LONDON", "NEW_YORK")
            ),
            {
                code: len(sessions[code]["provisional_candidates"])
                for code in ("LONDON", "NEW_YORK")
            },
        ),
        _check(
            "NO_HOLDOUT_EXECUTION_OR_REJECTED_ZN_RESEARCH",
            discovery["interpretation_boundary"]
            == {
                "calendar_2025_values_opened": False,
                "calendar_2026_values_opened": False,
                "causal_claims": False,
                "combined_session_result": False,
                "development_only": True,
                "execution_variants": 0,
                "provisional_candidates_have_validation_credit": False,
                "rejected_zn_rules_reopened": False,
                "trades_or_returns": 0,
            }
            and not _registered_condition_mentions_zn(discovery),
            discovery["interpretation_boundary"],
        ),
        _check(
            "DETERMINISTIC_DISCOVERY_ARTIFACT",
            sha256_file(discovery_path)
            == hashlib.sha256(discovery_path.read_bytes()).hexdigest(),
            {
                "bytes": discovery_path.stat().st_size,
                "sha256": sha256_file(discovery_path),
            },
        ),
    ]
    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "validation_version": BUILD_VALIDATION_VERSION,
        "semantic_ruleset_version": VALIDATION_RULESET_VERSION,
        "generated_at": str(frozen_manifest["recorded_at"]),
        "milestone": "V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY",
        "pre_result_manifest_hash": M4_PRE_RESULT_MANIFEST_HASH,
        "discovery_hash": discovery["discovery_hash"],
        "discovery_file_sha256": sha256_file(discovery_path),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_4_BUILD_VALIDATION"
            if failed == 0
            else "FAIL_V3_MILESTONE_4_BUILD_VALIDATION"
        ),
    }


def _relationship_inventory(
    discovery: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    output: dict[str, dict[str, int]] = {}
    for session_code in ("LONDON", "NEW_YORK"):
        session = discovery["sessions"][session_code]
        singles = list(session["single_condition_results"])
        interactions = list(session["interaction_results"])
        records = [*singles, *interactions]
        summary = session["summary"]
        output[session_code] = {
            "single_registered": int(
                summary["single_conditions_registered"]
            ),
            "single_recorded": len(singles),
            "single_support_eligible": sum(
                bool(item["support_eligible"]) for item in singles
            ),
            "interaction_registered": int(
                summary["interaction_conditions_registered"]
            ),
            "interaction_recorded": len(interactions),
            "interaction_support_eligible": sum(
                bool(item["support_eligible"]) for item in interactions
            ),
            "relationships_registered": int(
                summary["single_conditions_registered"]
            )
            + int(summary["interaction_conditions_registered"]),
            "relationships_recorded": len(records),
            "candidate_gate_pass": sum(
                bool(item["candidate_gate_pass"]) for item in records
            ),
            "did_not_pass_candidate_gate": sum(
                not bool(item["candidate_gate_pass"]) for item in records
            ),
            "provisional_candidates_advanced": len(
                session["provisional_candidates"]
            ),
        }
    return output


def _registered_condition_mentions_zn(
    discovery: Mapping[str, Any],
) -> bool:
    for session_code in ("LONDON", "NEW_YORK"):
        session = discovery["sessions"][session_code]
        for record in [
            *session["single_condition_results"],
            *session["interaction_results"],
        ]:
            if "ZN" in str(record["condition_id"]).upper().split("__"):
                return True
            for condition in record["conditions"]:
                if str(condition["feature_id"]).upper().startswith("ZN"):
                    return True
    return False


def _verify_pre_read_seals(paths: Mapping[str, Path]) -> dict[str, Any]:
    frozen_manifest = _load_json(paths["pre_manifest"])
    _verify_embedded_hash(
        frozen_manifest,
        hash_field="manifest_hash",
        expected=M4_PRE_RESULT_MANIFEST_HASH,
    )
    if sha256_file(paths["pre_manifest"]) != M4_PRE_RESULT_MANIFEST_FILE_HASH:
        raise ValueError("M4 pre-result manifest file hash mismatch")

    contract = _load_json(paths["contract"])
    _verify_embedded_hash(
        contract,
        hash_field="manifest_hash",
        expected=CONTRACT_HASH,
    )
    traceability = _load_json(paths["traceability"])
    _verify_embedded_hash(
        traceability,
        hash_field="catalog_hash",
        expected=TRACEABILITY_HASH,
    )
    case_manifest = _load_json(paths["case_manifest"])
    _verify_embedded_hash(
        case_manifest,
        hash_field="manifest_hash",
        expected=CASE_MANIFEST_HASH,
    )
    if sha256_file(paths["cases"]) != CASE_ARTIFACT_HASH:
        raise ValueError("Development case artifact hash mismatch")
    if paths["cases"].stat().st_size != 103_763_781:
        raise ValueError("Development case artifact byte size mismatch")

    state = _load_json(paths["m3_state"])
    calculated_state_hash = canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    if (
        calculated_state_hash != M3_STATE_HASH
        or state.get("state_hash") != M3_STATE_HASH
        or sha256_file(paths["m3_state"]) != M3_STATE_FILE_HASH
    ):
        raise ValueError("M3 predecessor-state seal mismatch")
    expected_files = {
        "book": BOOK_HASH,
        "feature_module": FEATURE_MODULE_HASH,
        "feature_test": FEATURE_TEST_HASH,
        "relationship_module": RELATIONSHIP_MODULE_HASH,
        "relationship_test": RELATIONSHIP_TEST_HASH,
        "validation_module": VALIDATION_MODULE_HASH,
    }
    for name, expected in expected_files.items():
        actual = sha256_file(paths[name])
        if actual != expected:
            raise ValueError(
                f"{name} implementation/input seal mismatch: "
                f"expected={expected} actual={actual}"
            )
    return frozen_manifest


def _verify_embedded_hash(
    document: Mapping[str, Any],
    *,
    hash_field: str,
    expected: str,
) -> None:
    supplied = str(document.get(hash_field, ""))
    calculated = canonical_hash(
        {
            key: value
            for key, value in document.items()
            if key != hash_field
        }
    )
    if supplied != expected or calculated != supplied:
        raise ValueError(
            f"Embedded {hash_field} mismatch: expected={expected} "
            f"supplied={supplied} calculated={calculated}"
        )


def _check(code: str, passed: bool, evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "status": "PASS" if passed else "FAIL",
        "evidence": json_ready(evidence),
    }


def _write_json(path: Path, document: Mapping[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(json_ready(document), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _write_hashed_json(
    path: Path,
    document: Mapping[str, Any],
    *,
    hash_field: str,
) -> None:
    payload = dict(document)
    if hash_field in payload:
        raise ValueError(f"{hash_field} already supplied")
    payload[hash_field] = canonical_hash(payload)
    _write_json(path, payload)


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _paths(root: Path) -> dict[str, Path]:
    return {
        "pre_manifest": (
            root
            / "research_manifests"
            / "gold_session_behaviour_v3_m4_discovery_v01.json"
        ),
        "contract": (
            root
            / "research_manifests"
            / "gold_session_behaviour_discovery_contract_v03.json"
        ),
        "traceability": (
            root
            / "research_manifests"
            / "gold_session_behaviour_v3_traceability_v01.json"
        ),
        "case_manifest": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_case_matrix_v01"
            / "manifest.json"
        ),
        "cases": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_case_matrix_v01"
            / "cases.jsonl.gz"
        ),
        "m3_state": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_state_v03.json"
        ),
        "book": root / "Gold_USD_Market_Intelligence_Reference_Book.pdf",
        "feature_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_discovery.py"
        ),
        "feature_test": (
            root
            / "backend"
            / "tests"
            / "unit"
            / "test_session_behaviour_v3_discovery.py"
        ),
        "relationship_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_relationships.py"
        ),
        "relationship_test": (
            root
            / "backend"
            / "tests"
            / "unit"
            / "test_session_behaviour_v3_relationships.py"
        ),
        "validation_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_discovery_validation.py"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the preregistered, development-only Gold Session "
            "Behaviour V3 Milestone 4 conditional-bias discovery."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output-dir",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m4_discovery_v01"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
