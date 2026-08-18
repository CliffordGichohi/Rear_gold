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
from gold_intel.analytics.session_behaviour_v3_atlas import (
    CREATED_AND_SEALED_AT,
    M2_CASE_ARTIFACT_HASH,
    M2_RESULT_MANIFEST_HASH,
    M3_PRE_RESULT_MANIFEST_HASH,
    TRANSFORM_VERSION,
    AtlasCase,
    build_atlas_document,
    extract_atlas_case,
    validate_atlas_semantics,
)

M2_STATE_HASH = "26bc72f56c868a542b4cafce57b177f59df94fd26a4db39b342cd0b35244d46c"
M2_STATE_FILE_HASH = (
    "3ef1b663e7267f1fe9979aaba4e57d34e1e0c69adaf7f9585205b57e5d5cb421"
)
M2_VALIDATION_HASH = (
    "2394ad0ff3dd71abe25757689b1655df78788dd9b76f86c2278e5f905b4e3893"
)
M2_VALIDATION_FILE_HASH = (
    "31b5ec7ff90ad92db933aeefec11855c6466ebbf98cc8e72e18a4d26a45343e0"
)
M2_RESULT_MANIFEST_FILE_HASH = (
    "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5"
)
RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M3_RESULT_V0_1"
SEMANTIC_VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M3_BUILD_VALIDATION_V0_1"
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output_dir = (root / args.output_dir).resolve()
    result = build(root=root, output_dir=output_dir)
    print(json.dumps(result, indent=2, sort_keys=True))


def build(*, root: Path, output_dir: Path) -> dict[str, Any]:
    paths = _paths(root)
    _verify_pre_read_seals(paths)

    cases, readback = _read_cases(paths["cases"])
    atlas = build_atlas_document(cases)
    semantic_errors = validate_atlas_semantics(atlas)
    if semantic_errors:
        raise ValueError(f"Atlas semantic validation failed: {semantic_errors}")

    output_dir.mkdir(parents=True, exist_ok=True)
    atlas_path = output_dir / "atlas.json"
    validation_path = output_dir / "semantic_validation.json"
    manifest_path = output_dir / "manifest.json"
    _write_json(atlas_path, atlas)

    validation = _build_validation(
        atlas=atlas,
        atlas_path=atlas_path,
        readback=readback,
        semantic_errors=semantic_errors,
    )
    _write_hashed_json(
        validation_path,
        validation,
        hash_field="validation_hash",
    )
    saved_validation = _load_json(validation_path)

    manifest: dict[str, Any] = {
        "manifest_version": RESULT_VERSION,
        "milestone": "V3_M3_DEVELOPMENT_BEHAVIOUR_ATLAS",
        "created_at": CREATED_AND_SEALED_AT,
        "sealed_at": CREATED_AND_SEALED_AT,
        "pre_result_manifest": {
            "path": (
                "research_manifests/"
                "gold_session_behaviour_v3_m3_atlas_v01.json"
            ),
            "manifest_hash": M3_PRE_RESULT_MANIFEST_HASH,
        },
        "source": {
            "case_artifact_path": (
                "research_artifacts/"
                "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
            ),
            "case_artifact_sha256": M2_CASE_ARTIFACT_HASH,
            "case_matrix_manifest_hash": M2_RESULT_MANIFEST_HASH,
            "predecessor_state_hash": M2_STATE_HASH,
            "m2_independent_validation_hash": M2_VALIDATION_HASH,
            "all_seals_verified_before_case_read": True,
        },
        "artifacts": [
            {
                "name": "atlas.json",
                "path": "atlas.json",
                "bytes": atlas_path.stat().st_size,
                "sha256": sha256_file(atlas_path),
                "atlas_hash": atlas["atlas_hash"],
            },
            {
                "name": "semantic_validation.json",
                "path": "semantic_validation.json",
                "bytes": validation_path.stat().st_size,
                "sha256": sha256_file(validation_path),
                "validation_hash": saved_validation["validation_hash"],
            },
        ],
        "case_counts": atlas["case_counts"],
        "integrity": {
            "source_records_read": readback["records_read"],
            "source_record_hash_mismatches": readback["record_hash_mismatches"],
            "unique_case_ids": readback["unique_case_ids"],
            "row_order_violations": readback["row_order_violations"],
            "atlas_semantic_errors": len(semantic_errors),
            "build_validation_checks_failed": saved_validation["summary"]["failed"],
            "build_validation_checks_passed": saved_validation["summary"]["passed"],
        },
        "research_boundary": dict(atlas["interpretation_boundary"]),
        "transform_version": TRANSFORM_VERSION,
        "verdict": "PASS_V3_MILESTONE_3_ATLAS_SEALED",
        "mandatory_stop": True,
        "next_milestone": {
            "code": "V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY",
            "authorized": False,
            "started": False,
        },
    }
    _write_hashed_json(manifest_path, manifest, hash_field="manifest_hash")
    saved_manifest = _load_json(manifest_path)
    return {
        "atlas": str(atlas_path),
        "atlas_bytes": atlas_path.stat().st_size,
        "atlas_file_sha256": sha256_file(atlas_path),
        "atlas_hash": atlas["atlas_hash"],
        "cases": atlas["case_counts"]["total"],
        "london": atlas["case_counts"]["london"],
        "new_york": atlas["case_counts"]["new_york"],
        "manifest": str(manifest_path),
        "manifest_hash": saved_manifest["manifest_hash"],
        "semantic_validation": str(validation_path),
        "semantic_validation_hash": saved_validation["validation_hash"],
        "verdict": saved_manifest["verdict"],
    }


def _read_cases(path: Path) -> tuple[list[AtlasCase], dict[str, Any]]:
    cases: list[AtlasCase] = []
    case_ids: set[str] = set()
    session_counts: Counter[str] = Counter()
    row_order_violations = 0
    record_hash_mismatches = 0
    prior_key: tuple[str, int] | None = None
    order = {"LONDON": 0, "NEW_YORK": 1}

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            metadata = record["case_metadata"]
            supplied_hash = str(metadata.pop("record_hash"))
            calculated_hash = canonical_hash(record)
            metadata["record_hash"] = supplied_hash
            if calculated_hash != supplied_hash:
                record_hash_mismatches += 1
                raise ValueError(f"Case record hash mismatch on line {line_number}")

            case = extract_atlas_case(record)
            if case.case_id in case_ids:
                raise ValueError(f"Duplicate case ID: {case.case_id}")
            case_ids.add(case.case_id)
            key = (case.session_date.isoformat(), order[case.session_code])
            if prior_key is not None and key <= prior_key:
                row_order_violations += 1
            prior_key = key
            session_counts[case.session_code] += 1
            cases.append(case)

    return cases, {
        "records_read": len(cases),
        "record_hash_mismatches": record_hash_mismatches,
        "unique_case_ids": len(case_ids),
        "row_order_violations": row_order_violations,
        "session_counts": dict(sorted(session_counts.items())),
    }


def _build_validation(
    *,
    atlas: Mapping[str, Any],
    atlas_path: Path,
    readback: Mapping[str, Any],
    semantic_errors: list[str],
) -> dict[str, Any]:
    checks = [
        _check(
            "PRE_READ_SEALS",
            True,
            {
                "m3_pre_result_manifest_hash": M3_PRE_RESULT_MANIFEST_HASH,
                "m2_result_manifest_hash": M2_RESULT_MANIFEST_HASH,
                "m2_case_artifact_hash": M2_CASE_ARTIFACT_HASH,
                "m2_state_hash": M2_STATE_HASH,
                "m2_validation_hash": M2_VALIDATION_HASH,
            },
        ),
        _check(
            "EXACT_SOURCE_COUNTS",
            readback["records_read"] == 1659
            and readback["session_counts"] == {
                "LONDON": 833,
                "NEW_YORK": 826,
            },
            dict(readback),
        ),
        _check(
            "SOURCE_RECORD_HASHES",
            readback["record_hash_mismatches"] == 0,
            {"mismatches": readback["record_hash_mismatches"]},
        ),
        _check(
            "SOURCE_IDENTITY_AND_ORDER",
            readback["unique_case_ids"] == 1659
            and readback["row_order_violations"] == 0,
            {
                "unique_case_ids": readback["unique_case_ids"],
                "row_order_violations": readback["row_order_violations"],
            },
        ),
        _check(
            "ATLAS_HASH",
            atlas["atlas_hash"]
            == canonical_hash(
                {key: value for key, value in atlas.items() if key != "atlas_hash"}
            ),
            {"atlas_hash": atlas["atlas_hash"]},
        ),
        _check(
            "ATLAS_SEMANTICS",
            not semantic_errors,
            {"errors": semantic_errors},
        ),
        _check(
            "SESSION_SEPARATION",
            set(atlas["sessions"]) == {"LONDON", "NEW_YORK"}
            and atlas["interpretation_boundary"]["combined_session_result"] is False,
            {"session_keys": sorted(atlas["sessions"])},
        ),
        _check(
            "DESCRIPTIVE_SCOPE_ONLY",
            atlas["interpretation_boundary"]["descriptive_only"] is True
            and atlas["interpretation_boundary"]["causal_attribution"] is False
            and atlas["interpretation_boundary"]["conditional_relationships_tested"]
            == 0
            and atlas["interpretation_boundary"]["candidates_created_or_ranked"]
            == 0
            and atlas["interpretation_boundary"]["predictive_metrics_calculated"]
            == 0
            and atlas["interpretation_boundary"]["hypothesis_tests_calculated"]
            == 0,
            atlas["interpretation_boundary"],
        ),
        _check(
            "NO_EXECUTION_RESEARCH",
            atlas["interpretation_boundary"]["execution_variants_tested"] == 0
            and atlas["interpretation_boundary"]["trades_or_returns_calculated"]
            == 0,
            {
                "execution_variants": 0,
                "trades_or_returns": 0,
            },
        ),
        _check(
            "HOLDOUT_LOCK",
            atlas["interpretation_boundary"]["calendar_2025_values_opened"] is False
            and atlas["interpretation_boundary"]["calendar_2026_values_opened"]
            is False,
            {
                "calendar_2025_values_opened": False,
                "calendar_2026_values_opened": False,
            },
        ),
        _check(
            "DETERMINISTIC_ARTIFACT",
            sha256_file(atlas_path)
            == hashlib.sha256(atlas_path.read_bytes()).hexdigest(),
            {
                "bytes": atlas_path.stat().st_size,
                "sha256": sha256_file(atlas_path),
            },
        ),
    ]
    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "validation_version": SEMANTIC_VALIDATION_VERSION,
        "generated_at": CREATED_AND_SEALED_AT,
        "milestone": "V3_M3_DEVELOPMENT_BEHAVIOUR_ATLAS",
        "atlas_hash": atlas["atlas_hash"],
        "atlas_file_sha256": sha256_file(atlas_path),
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_3_BUILD_VALIDATION"
            if failed == 0
            else "FAIL_V3_MILESTONE_3_BUILD_VALIDATION"
        ),
    }


def _verify_pre_read_seals(paths: Mapping[str, Path]) -> None:
    pre_manifest = _load_json(paths["pre_manifest"])
    _verify_embedded_hash(
        pre_manifest,
        hash_field="manifest_hash",
        expected=M3_PRE_RESULT_MANIFEST_HASH,
    )
    result_manifest = _load_json(paths["m2_manifest"])
    _verify_embedded_hash(
        result_manifest,
        hash_field="manifest_hash",
        expected=M2_RESULT_MANIFEST_HASH,
    )
    if sha256_file(paths["m2_manifest"]) != M2_RESULT_MANIFEST_FILE_HASH:
        raise ValueError("M2 result-manifest file hash mismatch")
    if sha256_file(paths["cases"]) != M2_CASE_ARTIFACT_HASH:
        raise ValueError("M2 case artifact hash mismatch")

    state = _load_json(paths["m2_state"])
    calculated_state_hash = canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    if (
        calculated_state_hash != M2_STATE_HASH
        or state.get("state_hash") != M2_STATE_HASH
        or sha256_file(paths["m2_state"]) != M2_STATE_FILE_HASH
    ):
        raise ValueError("M2 predecessor-state seal mismatch")

    validation = _load_json(paths["m2_validation"])
    _verify_embedded_hash(
        validation,
        hash_field="validation_hash",
        expected=M2_VALIDATION_HASH,
    )
    if (
        sha256_file(paths["m2_validation"]) != M2_VALIDATION_FILE_HASH
        or validation["summary"]["failed"] != 0
    ):
        raise ValueError("M2 independent-validation seal mismatch")


def _verify_embedded_hash(
    document: Mapping[str, Any],
    *,
    hash_field: str,
    expected: str,
) -> None:
    supplied = str(document.get(hash_field, ""))
    calculated = canonical_hash(
        {key: value for key, value in document.items() if key != hash_field}
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
            / "gold_session_behaviour_v3_m3_atlas_v01.json"
        ),
        "m2_manifest": (
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
        "m2_state": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_state_v02.json"
        ),
        "m2_validation": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_m2_validation_v01.json"
        ),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Build the frozen, descriptive-only Gold Session Behaviour V3 "
            "Milestone 3 atlas from the sealed development case matrix."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output-dir",
        default="research_artifacts/gold_session_behaviour_v3_atlas_v01",
    )
    return parser


if __name__ == "__main__":
    main()
