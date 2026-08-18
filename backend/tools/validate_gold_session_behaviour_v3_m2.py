from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import (
    CASEBOOK_MANIFEST_HASH,
    DEVELOPMENT_END,
    DEVELOPMENT_START,
    FIVE_MINUTE_POINT_COUNT,
    M2_PRE_RESULT_MANIFEST_HASH,
    MEASUREMENT_BAR_COUNT,
    REQUIRED_TIMEFRAMES,
    case_record_hash,
    parse_timestamp,
    sha256_file,
    validate_case_semantics,
    validate_json_schema,
)

VALIDATION_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M2_INDEPENDENT_VALIDATION_V0_1"
EXPECTED_RESULT_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M2_RESULT_V0_1"
EXPECTED_INPUT_HASHES = {
    "cross_market_snapshots.jsonl.gz": (
        "470a2e1c020cd2f97f2ad5b0d7f9c5220aff4f644689c4d680c24373964eb285"
    ),
    "events.jsonl.gz": (
        "c7875e09d9ed831ece0f223b8be5efb75550af5bf1996a2dfea9d6119b24e35f"
    ),
    "fundamentals.jsonl.gz": (
        "d2b776f60c4535978bbfb28706b4700e6d054a10f8d57cfee171c83b212b7235"
    ),
    "positioning.jsonl.gz": (
        "e6d1aabf0d4401f3af4e54dc8ef4c0e4074772ec3f2199cfe9009b5a0b267228"
    ),
    "price_bars.jsonl.gz": (
        "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"
    ),
    "sessions.jsonl.gz": (
        "2695a2c0b9e8f41fcbf64c9f388e8883ebf7e1f0b3b09b90fb3a60ba7e64966a"
    ),
    "structure_snapshots.jsonl.gz": (
        "31eea2decc8ed3f8d3e498a9339e7f59ee101e7c787da47a831e63bfb97c1064"
    ),
}


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
    bundle = root / "research_artifacts" / "gold_session_behaviour_v3_case_matrix_v01"
    cases_path = bundle / "cases.jsonl.gz"
    manifest_path = bundle / "manifest.json"
    semantic_path = bundle / "semantic_validation.json"
    schema_path = (
        root
        / "research_schemas"
        / "gold_session_behaviour_v3_case_matrix.schema.json"
    )
    pre_manifest_path = (
        root
        / "research_manifests"
        / "gold_session_behaviour_v3_m2_case_matrix_v01.json"
    )
    source_dir = root / "research_artifacts" / "gold_casebook_v01"

    schema = _load_json(schema_path)
    pre_manifest = _load_json(pre_manifest_path)
    manifest = _load_json(manifest_path)
    semantic = _load_json(semantic_path)
    checks: list[dict[str, Any]] = []

    _check(
        checks,
        "PRE_RESULT_MANIFEST_HASH",
        _embedded_hash(pre_manifest, "manifest_hash") == M2_PRE_RESULT_MANIFEST_HASH,
        {
            "expected": M2_PRE_RESULT_MANIFEST_HASH,
            "supplied": pre_manifest.get("manifest_hash"),
        },
    )
    result_manifest_hash = _embedded_hash(manifest, "manifest_hash")
    _check(
        checks,
        "RESULT_MANIFEST_HASH",
        result_manifest_hash == manifest.get("manifest_hash")
        and manifest.get("manifest_version") == EXPECTED_RESULT_VERSION,
        {
            "calculated": result_manifest_hash,
            "supplied": manifest.get("manifest_hash"),
            "version": manifest.get("manifest_version"),
        },
    )
    _check(
        checks,
        "SOURCE_BUNDLE_PIN",
        manifest["source_bundle"]["manifest_hash"] == CASEBOOK_MANIFEST_HASH,
        manifest["source_bundle"],
    )
    actual_inputs = {
        name: sha256_file(source_dir / name)
        for name in EXPECTED_INPUT_HASHES
    }
    _check(
        checks,
        "FROZEN_INPUT_ARTIFACT_HASHES",
        actual_inputs == EXPECTED_INPUT_HASHES
        and manifest["source_bundle"][
            "artifact_hashes_verified_before_deserialization"
        ]
        == EXPECTED_INPUT_HASHES,
        actual_inputs,
    )
    _check(
        checks,
        "FROZEN_SCHEMA_HASH",
        sha256_file(schema_path)
        == pre_manifest["frozen_inputs"]["case_matrix_schema"]["sha256"]
        == manifest["schema"]["sha256"],
        {
            "actual": sha256_file(schema_path),
            "declared": manifest["schema"]["sha256"],
        },
    )
    artifact_decl = next(
        item for item in manifest["artifacts"] if item["name"] == "cases.jsonl.gz"
    )
    cases_sha = sha256_file(cases_path)
    _check(
        checks,
        "CASE_ARTIFACT_HASH_AND_SIZE",
        cases_sha == artifact_decl["sha256"]
        and cases_path.stat().st_size == artifact_decl["bytes"],
        {
            "actual_sha256": cases_sha,
            "declared_sha256": artifact_decl["sha256"],
            "actual_bytes": cases_path.stat().st_size,
            "declared_bytes": artifact_decl["bytes"],
        },
    )
    semantic_decl = next(
        item
        for item in manifest["artifacts"]
        if item["name"] == "semantic_validation.json"
    )
    _check(
        checks,
        "BUILD_SEMANTIC_VALIDATION_HASH",
        _embedded_hash(semantic, "validation_hash")
        == semantic["validation_hash"]
        == semantic_decl["validation_hash"]
        and sha256_file(semantic_path) == semantic_decl["sha256"]
        and semantic["summary"]["failed"] == 0,
        {
            "validation_hash": semantic["validation_hash"],
            "file_sha256": sha256_file(semantic_path),
            "verdict": semantic["verdict"],
        },
    )

    readback = _readback_cases(cases_path, schema)
    _check(
        checks,
        "EXACT_CASE_COUNTS",
        readback["record_count"] == 1659
        and readback["session_counts"] == {"LONDON": 833, "NEW_YORK": 826},
        {
            "total": readback["record_count"],
            "session_counts": readback["session_counts"],
        },
    )
    _check(
        checks,
        "UNIQUE_CASE_IDS_AND_SESSION_KEYS",
        readback["unique_case_ids"] == 1659
        and readback["unique_session_keys"] == 1659,
        {
            "case_ids": readback["unique_case_ids"],
            "session_keys": readback["unique_session_keys"],
        },
    )
    _check(
        checks,
        "DETERMINISTIC_ROW_ORDER",
        readback["row_order_violations"] == 0,
        {"violations": readback["row_order_violations"]},
    )
    _check(
        checks,
        "CASE_RECORD_HASHES",
        readback["record_hash_mismatches"] == 0,
        {"mismatches": readback["record_hash_mismatches"]},
    )
    _check(
        checks,
        "FROZEN_JSON_SCHEMA_ALL_ROWS",
        readback["schema_error_records"] == 0,
        {
            "error_records": readback["schema_error_records"],
            "examples": readback["schema_error_examples"],
        },
    )
    _check(
        checks,
        "SEMANTIC_INVARIANTS_ALL_ROWS",
        readback["semantic_error_records"] == 0,
        {
            "error_records": readback["semantic_error_records"],
            "examples": readback["semantic_error_examples"],
        },
    )
    _check(
        checks,
        "POINT_IN_TIME_AND_UNKNOWN_POLICY",
        readback["future_decision_facts"] == 0
        and readback["unknown_non_null"] == 0,
        {
            "future_decision_facts": readback["future_decision_facts"],
            "unknown_non_null": readback["unknown_non_null"],
        },
    )
    _check(
        checks,
        "STRUCTURE_AND_PATH_COMPLETENESS",
        readback["structure_violations"] == 0
        and readback["path_violations"] == 0,
        {
            "required_timeframes": list(REQUIRED_TIMEFRAMES),
            "one_minute_source_count": MEASUREMENT_BAR_COUNT,
            "five_minute_points": FIVE_MINUTE_POINT_COUNT,
            "structure_violations": readback["structure_violations"],
            "path_violations": readback["path_violations"],
        },
    )
    _check(
        checks,
        "DEVELOPMENT_ONLY_AND_OUTCOME_SEPARATION",
        readback["partition_violations"] == 0
        and readback["outcome_separation_violations"] == 0,
        {
            "partition_violations": readback["partition_violations"],
            "outcome_separation_violations": readback[
                "outcome_separation_violations"
            ],
        },
    )
    boundary = manifest["research_boundary"]
    _check(
        checks,
        "NO_RELATIONSHIP_CANDIDATE_OR_EXECUTION_RESEARCH",
        boundary
        == {
            "development_values_opened": True,
            "exposed_2025_values_opened": False,
            "locked_2026_values_opened": False,
            "feature_outcome_joins_calculated": 0,
            "relationship_statistics_calculated": 0,
            "descriptive_distributions_calculated": 0,
            "candidates_created": 0,
            "execution_variants_tested": 0,
            "trades_or_returns_calculated": 0,
            "mfe_or_mae_calculated": 0,
        }
        and readback["forbidden_execution_key_records"] == 0,
        {
            "manifest_boundary": boundary,
            "forbidden_execution_key_records": readback[
                "forbidden_execution_key_records"
            ],
        },
    )
    _check(
        checks,
        "MANDATORY_MILESTONE_STOP",
        manifest["mandatory_stop"] is True
        and manifest["next_milestone"]["authorized"] is False
        and manifest["next_milestone"]["started"] is False,
        {
            "mandatory_stop": manifest["mandatory_stop"],
            "next_milestone": manifest["next_milestone"],
        },
    )

    failed = sum(item["status"] == "FAIL" for item in checks)
    return {
        "validation_version": VALIDATION_VERSION,
        "milestone": "V3_M2_DEVELOPMENT_CASE_MATRIX",
        "result_manifest_hash": manifest["manifest_hash"],
        "case_artifact_sha256": cases_sha,
        "case_artifact_bytes": cases_path.stat().st_size,
        "records_read_back": readback["record_count"],
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_2_INDEPENDENT_VALIDATION_MANDATORY_STOP"
            if failed == 0
            else "FAIL_V3_MILESTONE_2_INDEPENDENT_VALIDATION"
        ),
    }


def _readback_cases(path: Path, schema: dict[str, Any]) -> dict[str, Any]:
    case_ids: set[str] = set()
    session_keys: set[tuple[str, str]] = set()
    session_counts: Counter[str] = Counter()
    prior_key: tuple[str, int] | None = None
    record_count = 0
    row_order_violations = 0
    record_hash_mismatches = 0
    schema_error_records = 0
    semantic_error_records = 0
    schema_error_examples: list[dict[str, Any]] = []
    semantic_error_examples: list[dict[str, Any]] = []
    future_decision_facts = 0
    unknown_non_null = 0
    structure_violations = 0
    path_violations = 0
    partition_violations = 0
    outcome_separation_violations = 0
    forbidden_execution_key_records = 0

    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            case = json.loads(line)
            record_count += 1
            metadata = case["case_metadata"]
            case_id = str(metadata["case_id"])
            session_code = str(metadata["session_code"])
            session_date = str(metadata["session_date"])
            key = (session_date, session_code)
            order_key = (
                session_date,
                {"LONDON": 0, "NEW_YORK": 1}.get(session_code, 99),
            )
            if prior_key is not None and order_key <= prior_key:
                row_order_violations += 1
            prior_key = order_key
            case_ids.add(case_id)
            session_keys.add(key)
            session_counts[session_code] += 1

            if case_record_hash(case) != metadata["record_hash"]:
                record_hash_mismatches += 1
            schema_errors = validate_json_schema(case, schema)
            if schema_errors:
                schema_error_records += 1
                if len(schema_error_examples) < 3:
                    schema_error_examples.append(
                        {"case_id": case_id, "errors": schema_errors[:10]}
                    )
            semantic_errors = validate_case_semantics(case)
            if semantic_errors:
                semantic_error_records += 1
                if len(semantic_error_examples) < 3:
                    semantic_error_examples.append(
                        {"case_id": case_id, "errors": semantic_errors[:10]}
                    )
            future_decision_facts += sum(
                item.startswith("FUTURE_") for item in semantic_errors
            )
            unknown_non_null += sum(
                item.startswith("UNKNOWN_NON_NULL") for item in semantic_errors
            )
            forbidden_execution_key_records += int(
                "FORBIDDEN_EXECUTION_KEY" in semantic_errors
            )

            decision = parse_timestamp(str(metadata["decision_at"]))
            observation_end = parse_timestamp(str(metadata["observation_end"]))
            if (
                not DEVELOPMENT_START <= decision < DEVELOPMENT_END
                or not DEVELOPMENT_START <= observation_end <= DEVELOPMENT_END
                or metadata["data_partition"] != "DEVELOPMENT_2021_2024"
                or metadata["access_class"] != "DEVELOPMENT"
            ):
                partition_violations += 1

            timeframes = case["decision_state"]["market_structure"]["timeframes"]
            if len(timeframes) != 6 or {
                item["timeframe"] for item in timeframes
            } != set(REQUIRED_TIMEFRAMES):
                structure_violations += 1
            outcome = case["subsequent_behaviour"]
            if (
                outcome["path"]["one_minute_source_count"]
                != MEASUREMENT_BAR_COUNT
                or outcome["path"]["missing_one_minute_bars"] != 0
                or len(outcome["path"]["five_minute_points"])
                != FIVE_MINUTE_POINT_COUNT
                or len(outcome["fixed_horizons"]) != 5
            ):
                path_violations += 1
            if (
                outcome["decision_eligible"] is not False
                or case["decision_state"]["decision_eligible"] is not True
                or case["research_policy"]["decision_outcome_separated"] is not True
            ):
                outcome_separation_violations += 1

    return {
        "record_count": record_count,
        "unique_case_ids": len(case_ids),
        "unique_session_keys": len(session_keys),
        "session_counts": dict(sorted(session_counts.items())),
        "row_order_violations": row_order_violations,
        "record_hash_mismatches": record_hash_mismatches,
        "schema_error_records": schema_error_records,
        "schema_error_examples": schema_error_examples,
        "semantic_error_records": semantic_error_records,
        "semantic_error_examples": semantic_error_examples,
        "future_decision_facts": future_decision_facts,
        "unknown_non_null": unknown_non_null,
        "structure_violations": structure_violations,
        "path_violations": path_violations,
        "partition_violations": partition_violations,
        "outcome_separation_violations": outcome_separation_violations,
        "forbidden_execution_key_records": forbidden_execution_key_records,
    }


def _embedded_hash(document: dict[str, Any], hash_field: str) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != hash_field}
    )


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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently read back and validate the sealed Gold Session Behaviour "
            "V3 Milestone 2 development case matrix."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m2_validation_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
