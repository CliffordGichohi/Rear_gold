from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_atlas import (
    CREATED_AND_SEALED_AT,
    M2_CASE_ARTIFACT_HASH,
    M2_RESULT_MANIFEST_HASH,
    M3_PRE_RESULT_MANIFEST_HASH,
    build_atlas_document,
    extract_atlas_case,
    validate_atlas_semantics,
    verify_atlas_hash,
)

RESULT_MANIFEST_HASH = (
    "534df4e54a9c137c0d6ef53b6bdb263f03ec51a7751c44c1a3b6ae4dc05e2fc8"
)
ATLAS_HASH = "08bdbe31e559f52623091ea52c79fcff6b9056536a0781ab02a5dc02d9a61fb4"
ATLAS_FILE_HASH = (
    "d23a6be91a87dd577d80594a71cd55ce2862f98653247ac97f894434c114299d"
)
BUILD_VALIDATION_HASH = (
    "181b615551e58cb21f232f3254bff969da87a5bc409ba3ed94def4a4ce93bde0"
)
M2_STATE_HASH = "26bc72f56c868a542b4cafce57b177f59df94fd26a4db39b342cd0b35244d46c"
M2_VALIDATION_HASH = (
    "2394ad0ff3dd71abe25757689b1655df78788dd9b76f86c2278e5f905b4e3893"
)
VALIDATION_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M3_INDEPENDENT_VALIDATION_V0_1"


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    result = validate(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = dict(result)
    payload["validation_hash"] = canonical_hash(payload)
    output.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "checks_failed": payload["summary"]["failed"],
                "checks_passed": payload["summary"]["passed"],
                "output": str(output),
                "validation_hash": payload["validation_hash"],
                "verdict": payload["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if payload["summary"]["failed"]:
        raise SystemExit(1)


def validate(root: Path) -> dict[str, Any]:
    paths = _paths(root)
    pre_manifest = _load_json(paths["pre_manifest"])
    m2_manifest = _load_json(paths["m2_manifest"])
    m2_state = _load_json(paths["m2_state"])
    m2_validation = _load_json(paths["m2_validation"])
    result_manifest = _load_json(paths["result_manifest"])
    atlas = _load_json(paths["atlas"])
    build_validation = _load_json(paths["build_validation"])
    checks: list[dict[str, Any]] = []

    _check(
        checks,
        "M3_PRE_RESULT_MANIFEST_HASH",
        _embedded_hash(pre_manifest, "manifest_hash")
        == pre_manifest["manifest_hash"]
        == M3_PRE_RESULT_MANIFEST_HASH,
        {"manifest_hash": pre_manifest["manifest_hash"]},
    )
    _check(
        checks,
        "M2_CASE_MATRIX_SEAL",
        _embedded_hash(m2_manifest, "manifest_hash")
        == m2_manifest["manifest_hash"]
        == M2_RESULT_MANIFEST_HASH
        and sha256_file(paths["cases"]) == M2_CASE_ARTIFACT_HASH,
        {
            "manifest_hash": m2_manifest["manifest_hash"],
            "artifact_sha256": sha256_file(paths["cases"]),
        },
    )
    calculated_state_hash = canonical_hash(
        {
            key: value
            for key, value in m2_state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    _check(
        checks,
        "M2_STATE_SEAL",
        calculated_state_hash == m2_state["state_hash"] == M2_STATE_HASH,
        {
            "calculated": calculated_state_hash,
            "supplied": m2_state["state_hash"],
        },
    )
    _check(
        checks,
        "M2_INDEPENDENT_VALIDATION_SEAL",
        _embedded_hash(m2_validation, "validation_hash")
        == m2_validation["validation_hash"]
        == M2_VALIDATION_HASH
        and m2_validation["summary"]["failed"] == 0,
        {
            "validation_hash": m2_validation["validation_hash"],
            "failed": m2_validation["summary"]["failed"],
        },
    )
    _check(
        checks,
        "M3_RESULT_MANIFEST_HASH",
        _embedded_hash(result_manifest, "manifest_hash")
        == result_manifest["manifest_hash"]
        == RESULT_MANIFEST_HASH,
        {"manifest_hash": result_manifest["manifest_hash"]},
    )
    atlas_declaration = next(
        item for item in result_manifest["artifacts"] if item["name"] == "atlas.json"
    )
    _check(
        checks,
        "ATLAS_FILE_SEAL",
        sha256_file(paths["atlas"])
        == atlas_declaration["sha256"]
        == ATLAS_FILE_HASH
        and paths["atlas"].stat().st_size == atlas_declaration["bytes"],
        {
            "sha256": sha256_file(paths["atlas"]),
            "bytes": paths["atlas"].stat().st_size,
        },
    )
    validation_declaration = next(
        item
        for item in result_manifest["artifacts"]
        if item["name"] == "semantic_validation.json"
    )
    _check(
        checks,
        "BUILD_VALIDATION_SEAL",
        _embedded_hash(build_validation, "validation_hash")
        == build_validation["validation_hash"]
        == validation_declaration["validation_hash"]
        == BUILD_VALIDATION_HASH
        and sha256_file(paths["build_validation"])
        == validation_declaration["sha256"]
        and build_validation["summary"]["failed"] == 0,
        {
            "validation_hash": build_validation["validation_hash"],
            "file_sha256": sha256_file(paths["build_validation"]),
        },
    )
    _check(
        checks,
        "ATLAS_EMBEDDED_HASH",
        verify_atlas_hash(atlas) and atlas["atlas_hash"] == ATLAS_HASH,
        {"atlas_hash": atlas["atlas_hash"]},
    )

    cases, readback = _independent_case_readback(paths["cases"])
    _check(
        checks,
        "EXACT_SOURCE_COUNTS",
        readback["records"] == 1659
        and readback["session_counts"] == {
            "LONDON": 833,
            "NEW_YORK": 826,
        },
        readback,
    )
    _check(
        checks,
        "SOURCE_RECORD_HASHES_AND_IDENTITIES",
        readback["record_hash_mismatches"] == 0
        and readback["unique_case_ids"] == 1659
        and readback["row_order_violations"] == 0,
        {
            "record_hash_mismatches": readback["record_hash_mismatches"],
            "unique_case_ids": readback["unique_case_ids"],
            "row_order_violations": readback["row_order_violations"],
        },
    )

    recomputed = build_atlas_document(cases)
    _check(
        checks,
        "INDEPENDENT_ATLAS_REPRODUCTION",
        recomputed == atlas
        and recomputed["atlas_hash"] == ATLAS_HASH
        and canonical_hash(recomputed) == canonical_hash(atlas),
        {
            "recomputed_atlas_hash": recomputed["atlas_hash"],
            "sealed_atlas_hash": atlas["atlas_hash"],
            "documents_equal": recomputed == atlas,
        },
    )
    semantic_errors = validate_atlas_semantics(atlas)
    _check(
        checks,
        "ATLAS_SEMANTIC_INVARIANTS",
        not semantic_errors,
        {"errors": semantic_errors},
    )
    _check(
        checks,
        "SESSION_SEPARATION",
        set(atlas["sessions"]) == {"LONDON", "NEW_YORK"}
        and atlas["interpretation_boundary"]["combined_session_result"] is False,
        {
            "sessions": sorted(atlas["sessions"]),
            "combined_session_result": atlas["interpretation_boundary"][
                "combined_session_result"
            ],
        },
    )
    boundary = atlas["interpretation_boundary"]
    _check(
        checks,
        "NO_CAUSAL_OR_CONDITIONAL_RESEARCH",
        boundary["descriptive_only"] is True
        and boundary["causal_attribution"] is False
        and boundary["conditional_relationships_tested"] == 0
        and boundary["candidates_created_or_ranked"] == 0
        and boundary["predictive_metrics_calculated"] == 0
        and boundary["hypothesis_tests_calculated"] == 0,
        boundary,
    )
    _check(
        checks,
        "NO_EXECUTION_OR_TRADE_RESEARCH",
        boundary["execution_variants_tested"] == 0
        and boundary["trades_or_returns_calculated"] == 0,
        {
            "execution_variants_tested": boundary["execution_variants_tested"],
            "trades_or_returns_calculated": boundary[
                "trades_or_returns_calculated"
            ],
        },
    )
    _check(
        checks,
        "HOLDOUT_LOCK",
        boundary["calendar_2025_values_opened"] is False
        and boundary["calendar_2026_values_opened"] is False,
        {
            "calendar_2025_values_opened": boundary[
                "calendar_2025_values_opened"
            ],
            "calendar_2026_values_opened": boundary[
                "calendar_2026_values_opened"
            ],
        },
    )
    _check(
        checks,
        "MANDATORY_STOP",
        result_manifest["mandatory_stop"] is True
        and result_manifest["next_milestone"]["authorized"] is False
        and result_manifest["next_milestone"]["started"] is False,
        result_manifest["next_milestone"],
    )

    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "validation_version": VALIDATION_VERSION,
        "generated_at": CREATED_AND_SEALED_AT,
        "milestone": "V3_M3_DEVELOPMENT_BEHAVIOUR_ATLAS",
        "result_manifest_hash": result_manifest["manifest_hash"],
        "atlas_hash": atlas["atlas_hash"],
        "atlas_file_sha256": sha256_file(paths["atlas"]),
        "records_read_back": readback["records"],
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_3_INDEPENDENT_VALIDATION_MANDATORY_STOP"
            if failed == 0
            else "FAIL_V3_MILESTONE_3_INDEPENDENT_VALIDATION"
        ),
    }


def _independent_case_readback(path: Path) -> tuple[list[Any], dict[str, Any]]:
    cases: list[Any] = []
    case_ids: set[str] = set()
    session_counts: Counter[str] = Counter()
    record_hash_mismatches = 0
    row_order_violations = 0
    prior_key: tuple[str, int] | None = None
    session_order = {"LONDON": 0, "NEW_YORK": 1}

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line_number, line in enumerate(handle, start=1):
            record = json.loads(line)
            metadata = record["case_metadata"]
            supplied = str(metadata.pop("record_hash"))
            calculated = canonical_hash(record)
            metadata["record_hash"] = supplied
            if supplied != calculated:
                record_hash_mismatches += 1
                raise ValueError(f"Source record hash mismatch: line {line_number}")
            case = extract_atlas_case(record)
            if case.case_id in case_ids:
                raise ValueError(f"Duplicate case ID: {case.case_id}")
            case_ids.add(case.case_id)
            key = (case.session_date.isoformat(), session_order[case.session_code])
            if prior_key is not None and key <= prior_key:
                row_order_violations += 1
            prior_key = key
            session_counts[case.session_code] += 1
            cases.append(case)
    return cases, {
        "records": len(cases),
        "unique_case_ids": len(case_ids),
        "session_counts": dict(sorted(session_counts.items())),
        "record_hash_mismatches": record_hash_mismatches,
        "row_order_violations": row_order_violations,
    }


def _embedded_hash(document: dict[str, Any], field: str) -> str:
    return canonical_hash({key: value for key, value in document.items() if key != field})


def _check(
    checks: list[dict[str, Any]],
    code: str,
    passed: bool,
    evidence: Any,
) -> None:
    checks.append(
        {
            "code": code,
            "status": "PASS" if passed else "FAIL",
            "evidence": json_ready(evidence),
        }
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _paths(root: Path) -> dict[str, Path]:
    atlas_dir = (
        root / "research_artifacts" / "gold_session_behaviour_v3_atlas_v01"
    )
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
        "result_manifest": atlas_dir / "manifest.json",
        "atlas": atlas_dir / "atlas.json",
        "build_validation": atlas_dir / "semantic_validation.json",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reproduce and validate the Gold Session Behaviour "
            "V3 Milestone 3 descriptive atlas."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m3_validation_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
