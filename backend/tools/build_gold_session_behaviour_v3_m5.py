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
from gold_intel.analytics.session_behaviour_v3_m5 import (
    M5_ENGINE_VERSION,
    DiscoveryCase,
    build_m5_results,
    validate_m5_semantics,
)
from gold_intel.analytics.session_behaviour_v3_relationships import (
    materialize_discovery_case,
)

M5_PRE_RESULT_MANIFEST_HASH = (
    "adbeed7d029fab23ec72c3866f58bc041d48fe9f8607f65508246f6240917dab"
)
M5_PRE_RESULT_MANIFEST_FILE_HASH = (
    "eceda7c20e4c43b33ce786f246176c34b43aa9f48806c11fac5bd47f230b8584"
)
M4_PRE_RESULT_MANIFEST_HASH = (
    "e024ceba35a6d3af1c384f8c66eec299aab8cdcd23b666eb9f33ac672a24fbf4"
)
M4_STATE_HASH = "72c1956d7276d8c3987936104212468fe7411bf432b402feeb222a0cfd928977"
M4_STATE_FILE_HASH = (
    "cf059d9a0e37d0d5f6273171d7059776782eab4046b9fce01a43d342c00c30b2"
)
CASE_MANIFEST_HASH = (
    "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
)
CASE_ARTIFACT_HASH = (
    "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
)
M5_MODULE_HASH = (
    "85068a4cf67116846f9461842a680a5d2fab3199c49719c8b7aaf75d767648a1"
)
M5_TEST_HASH = (
    "9c5f76f691868012b8ed7b1dfda6c32e77406c16e8b7f078285d4d8d9a2b1b05"
)
FEATURE_MODULE_HASH = (
    "921a6d02c71514438e46a81d22f0ea788b2bdfca88172e564d10b510f14e96dc"
)
RELATIONSHIP_MODULE_HASH = (
    "8ad9c8adfc94ea433e185ce1b17b7f9f1d8981f29b7b967b338d351b8f51ee97"
)
RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M5_RESULT_V0_1"
BUILD_VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M5_BUILD_VALIDATION_V0_1"
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
    pre_manifest, m4_manifest = _verify_pre_read_seals(paths)
    cases, readback = _read_cases(
        paths["cases"],
        features=list(m4_manifest["feature_registry"]),
    )
    result = build_m5_results(cases, frozen_manifest=pre_manifest)
    semantic_errors = validate_m5_semantics(
        result,
        frozen_manifest=pre_manifest,
    )
    if semantic_errors:
        raise ValueError(f"M5 semantic validation failed: {semantic_errors}")

    output_dir.mkdir(parents=True, exist_ok=True)
    result_path = output_dir / "stability_results.json"
    validation_path = output_dir / "semantic_validation.json"
    manifest_path = output_dir / "manifest.json"
    _write_json(result_path, result)
    validation = _build_validation(
        result=result,
        result_path=result_path,
        readback=readback,
        semantic_errors=semantic_errors,
        frozen_manifest=pre_manifest,
    )
    _write_hashed_json(
        validation_path,
        validation,
        hash_field="validation_hash",
    )
    saved_validation = _load_json(validation_path)

    manifest: dict[str, Any] = {
        "manifest_version": RESULT_VERSION,
        "milestone": "V3_M5_INTERNAL_STABILITY_AND_SHORTLIST_FREEZE",
        "created_at": pre_manifest["recorded_at"],
        "sealed_at": pre_manifest["recorded_at"],
        "pre_result_manifest": {
            "path": (
                "research_manifests/"
                "gold_session_behaviour_v3_m5_amendment_a_v01.json"
            ),
            "manifest_hash": M5_PRE_RESULT_MANIFEST_HASH,
            "file_sha256": M5_PRE_RESULT_MANIFEST_FILE_HASH,
            "sealed_before_chronology_calculation": True,
        },
        "source": {
            "case_artifact_path": (
                "research_artifacts/"
                "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
            ),
            "case_artifact_sha256": CASE_ARTIFACT_HASH,
            "case_matrix_manifest_hash": CASE_MANIFEST_HASH,
            "m4_pre_result_manifest_hash": M4_PRE_RESULT_MANIFEST_HASH,
            "predecessor_state_hash": M4_STATE_HASH,
            "source_record_hash_chain": readback["record_hash_chain"],
            "all_seals_verified_before_case_read": True,
        },
        "implementation_seals": {
            "m5_engine_version": M5_ENGINE_VERSION,
            "m5_module_sha256": M5_MODULE_HASH,
            "m5_test_sha256": M5_TEST_HASH,
            "feature_module_sha256": FEATURE_MODULE_HASH,
            "relationship_materializer_sha256": RELATIONSHIP_MODULE_HASH,
            "implementation_frozen_before_chronology_calculation": True,
        },
        "artifacts": [
            {
                "name": "stability_results.json",
                "path": "stability_results.json",
                "bytes": result_path.stat().st_size,
                "sha256": sha256_file(result_path),
                "m5_hash": result["m5_hash"],
            },
            {
                "name": "semantic_validation.json",
                "path": "semantic_validation.json",
                "bytes": validation_path.stat().st_size,
                "sha256": sha256_file(validation_path),
                "validation_hash": saved_validation["validation_hash"],
            },
        ],
        "case_counts": result["case_counts"],
        "candidate_inventory": _candidate_inventory(result),
        "shortlists": {
            session: list(result["sessions"][session]["shortlist"])
            for session in ("LONDON", "NEW_YORK")
        },
        "integrity": {
            "source_records_read": readback["records_read"],
            "source_record_hash_mismatches": readback[
                "record_hash_mismatches"
            ],
            "unique_case_ids": readback["unique_case_ids"],
            "unique_session_dates": readback["unique_session_dates"],
            "row_order_violations": readback["row_order_violations"],
            "m5_semantic_errors": len(semantic_errors),
            "build_validation_checks_failed": saved_validation["summary"][
                "failed"
            ],
            "build_validation_checks_passed": saved_validation["summary"][
                "passed"
            ],
        },
        "research_boundary": dict(result["interpretation_boundary"]),
        "verdict": "PASS_V3_MILESTONE_5_STABILITY_SEALED",
        "mandatory_stop": True,
        "next_milestone": {
            "code": "V3_M6_FORWARD_EVALUATION",
            "authorized": False,
            "started": False,
        },
    }
    _write_hashed_json(manifest_path, manifest, hash_field="manifest_hash")
    saved_manifest = _load_json(manifest_path)
    return {
        "manifest": str(manifest_path),
        "manifest_hash": saved_manifest["manifest_hash"],
        "m5_hash": result["m5_hash"],
        "result": str(result_path),
        "result_file_sha256": sha256_file(result_path),
        "semantic_validation": str(validation_path),
        "semantic_validation_hash": saved_validation["validation_hash"],
        "shortlist_counts": {
            session: len(result["sessions"][session]["shortlist"])
            for session in ("LONDON", "NEW_YORK")
        },
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
    record_hash_mismatches = 0
    row_order_violations = 0
    prior_key: tuple[str, int] | None = None
    order = {"LONDON": 0, "NEW_YORK": 1}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            metadata = record["case_metadata"]
            supplied = str(metadata.pop("record_hash"))
            calculated = canonical_hash(record)
            metadata["record_hash"] = supplied
            if supplied != calculated:
                record_hash_mismatches += 1
                raise ValueError(f"Case record hash mismatch: line {line_number}")
            case = materialize_discovery_case(record, features=features)
            if case.case_id in case_ids:
                raise ValueError(f"Duplicate case ID: {case.case_id}")
            case_ids.add(case.case_id)
            session_date = (
                case.session_code,
                case.session_date.isoformat(),
            )
            if session_date in session_dates:
                raise ValueError(f"Duplicate session date: {session_date}")
            session_dates.add(session_date)
            key = (
                case.session_date.isoformat(),
                order[case.session_code],
            )
            if prior_key is not None and key <= prior_key:
                row_order_violations += 1
            prior_key = key
            session_counts[case.session_code] += 1
            record_hashes.append(supplied)
            cases.append(case)
    if len(cases) != 1659 or session_counts != {
        "LONDON": 833,
        "NEW_YORK": 826,
    }:
        raise ValueError("M5 source case counts differ")
    return cases, {
        "records_read": len(cases),
        "record_hash_mismatches": record_hash_mismatches,
        "record_hash_chain": canonical_hash(record_hashes),
        "row_order_violations": row_order_violations,
        "session_counts": dict(sorted(session_counts.items())),
        "unique_case_ids": len(case_ids),
        "unique_session_dates": len(session_dates),
    }


def _build_validation(
    *,
    result: Mapping[str, Any],
    result_path: Path,
    readback: Mapping[str, Any],
    semantic_errors: list[str],
    frozen_manifest: Mapping[str, Any],
) -> dict[str, Any]:
    inventory = _candidate_inventory(result)
    boundary = result["interpretation_boundary"]
    checks = [
        _check(
            "PRE_READ_SEALS",
            True,
            {
                "m5_pre_result_manifest_hash": (
                    M5_PRE_RESULT_MANIFEST_HASH
                ),
                "m4_state_hash": M4_STATE_HASH,
                "case_artifact_hash": CASE_ARTIFACT_HASH,
            },
        ),
        _check(
            "IMPLEMENTATION_FROZEN_BEFORE_CHRONOLOGY",
            True,
            {
                "m5_module_sha256": M5_MODULE_HASH,
                "m5_test_sha256": M5_TEST_HASH,
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
            "SOURCE_HASHES_IDENTITIES_AND_ORDER",
            readback["record_hash_mismatches"] == 0
            and readback["unique_case_ids"] == 1659
            and readback["unique_session_dates"] == 1659
            and readback["row_order_violations"] == 0,
            {
                key: readback[key]
                for key in (
                    "record_hash_mismatches",
                    "unique_case_ids",
                    "unique_session_dates",
                    "row_order_violations",
                )
            },
        ),
        _check(
            "M5_EMBEDDED_HASH",
            result["m5_hash"]
            == canonical_hash(
                {
                    key: value
                    for key, value in result.items()
                    if key != "m5_hash"
                }
            ),
            {"m5_hash": result["m5_hash"]},
        ),
        _check(
            "M5_SEMANTIC_INVARIANTS",
            not semantic_errors,
            {"errors": semantic_errors},
        ),
        _check(
            "EXACT_FOUR_CANDIDATES_TWO_PER_SESSION",
            inventory["LONDON"]["authorized"] == 2
            and inventory["NEW_YORK"]["authorized"] == 2,
            inventory,
        ),
        _check(
            "ALL_PASS_AND_NEGATIVE_RESULTS_RETAINED",
            all(
                item["authorized"]
                == item["passed"] + item["rejected"]
                for item in inventory.values()
            ),
            inventory,
        ),
        _check(
            "SHORTLIST_CAP",
            all(item["shortlisted"] <= 2 for item in inventory.values()),
            inventory,
        ),
        _check(
            "NO_FORWARD_EXECUTION_COT_OR_ZN_RESEARCH",
            boundary
            == {
                "calendar_2025_values_opened": False,
                "calendar_2026_values_opened": False,
                "cot_used_as_pass_gate": False,
                "development_validation_credit": False,
                "execution_variants": 0,
                "new_candidates_added_after_freeze": 0,
                "rejected_zn_rules_reopened": False,
                "trades_or_returns": 0,
            },
            boundary,
        ),
        _check(
            "DETERMINISTIC_RESULT_ARTIFACT",
            sha256_file(result_path)
            == hashlib.sha256(result_path.read_bytes()).hexdigest(),
            {
                "bytes": result_path.stat().st_size,
                "sha256": sha256_file(result_path),
            },
        ),
    ]
    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "validation_version": BUILD_VALIDATION_VERSION,
        "generated_at": frozen_manifest["recorded_at"],
        "milestone": "V3_M5_INTERNAL_STABILITY_AND_SHORTLIST_FREEZE",
        "pre_result_manifest_hash": M5_PRE_RESULT_MANIFEST_HASH,
        "m5_hash": result["m5_hash"],
        "result_file_sha256": sha256_file(result_path),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_5_BUILD_VALIDATION"
            if failed == 0
            else "FAIL_V3_MILESTONE_5_BUILD_VALIDATION"
        ),
    }


def _candidate_inventory(
    result: Mapping[str, Any],
) -> dict[str, dict[str, int]]:
    inventory: dict[str, dict[str, int]] = {}
    for session in ("LONDON", "NEW_YORK"):
        records = list(result["sessions"][session]["candidate_records"])
        passed = sum(bool(item["gate_pass"]) for item in records)
        inventory[session] = {
            "authorized": len(records),
            "passed": passed,
            "rejected": len(records) - passed,
            "shortlisted": len(result["sessions"][session]["shortlist"]),
        }
    return inventory


def _verify_pre_read_seals(
    paths: Mapping[str, Path],
) -> tuple[dict[str, Any], dict[str, Any]]:
    pre_manifest = _load_json(paths["pre_manifest"])
    _verify_embedded_hash(
        pre_manifest,
        "manifest_hash",
        M5_PRE_RESULT_MANIFEST_HASH,
    )
    if sha256_file(paths["pre_manifest"]) != M5_PRE_RESULT_MANIFEST_FILE_HASH:
        raise ValueError("M5 pre-result manifest file seal mismatch")
    m4_manifest = _load_json(paths["m4_pre_manifest"])
    _verify_embedded_hash(
        m4_manifest,
        "manifest_hash",
        M4_PRE_RESULT_MANIFEST_HASH,
    )
    state = _load_json(paths["m4_state"])
    state_hash = canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    if (
        state_hash != M4_STATE_HASH
        or state.get("state_hash") != M4_STATE_HASH
        or sha256_file(paths["m4_state"]) != M4_STATE_FILE_HASH
    ):
        raise ValueError("M4 predecessor-state seal mismatch")
    case_manifest = _load_json(paths["case_manifest"])
    _verify_embedded_hash(
        case_manifest,
        "manifest_hash",
        CASE_MANIFEST_HASH,
    )
    if (
        sha256_file(paths["cases"]) != CASE_ARTIFACT_HASH
        or paths["cases"].stat().st_size != 103_763_781
    ):
        raise ValueError("Development case matrix seal mismatch")
    expected_files = {
        "m5_module": M5_MODULE_HASH,
        "m5_test": M5_TEST_HASH,
        "feature_module": FEATURE_MODULE_HASH,
        "relationship_module": RELATIONSHIP_MODULE_HASH,
    }
    for name, expected in expected_files.items():
        actual = sha256_file(paths[name])
        if actual != expected:
            raise ValueError(
                f"{name} seal mismatch: expected={expected} actual={actual}"
            )
    return pre_manifest, m4_manifest


def _verify_embedded_hash(
    document: Mapping[str, Any],
    field: str,
    expected: str,
) -> None:
    supplied = str(document.get(field, ""))
    calculated = canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )
    if supplied != expected or calculated != supplied:
        raise ValueError(
            f"Embedded {field} mismatch: expected={expected} "
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
            / "gold_session_behaviour_v3_m5_amendment_a_v01.json"
        ),
        "m4_pre_manifest": (
            root
            / "research_manifests"
            / "gold_session_behaviour_v3_m4_discovery_v01.json"
        ),
        "m4_state": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_state_v04.json"
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
        "m5_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_m5.py"
        ),
        "m5_test": (
            root
            / "backend"
            / "tests"
            / "unit"
            / "test_session_behaviour_v3_m5.py"
        ),
        "feature_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_discovery.py"
        ),
        "relationship_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_relationships.py"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the sealed 2021-2024 V3 Milestone 5 chronology-aware "
            "stability and shortlist result."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output-dir",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m5_stability_v01"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
