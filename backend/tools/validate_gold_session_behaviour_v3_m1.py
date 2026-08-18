from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType
from typing import Any

from gold_intel.analytics.casebook import json_ready
from gold_intel.analytics.casebook_discovery_v3 import (
    add_deterministic_hash,
    assert_metadata_only_sql,
    sha256_file,
    verify_embedded_hash,
)

CONTRACT_HASH = "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
TRACEABILITY_HASH = "8707c39eb75bf3c74ce33908b0a3f4b0a1f679ee68848f1d10dce25e4bdf6bb4"
REFERENCE_BOOK_HASH = "3e7ddc561932a859a4c9043a38ff71b7003907963fb52247e41edaeefc8ac42a"
CASEBOOK_HASH = "d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f"
ORIGINAL_RESULT_HASH = (
    "e508b049961c622d09b8474815e0a4d3c8e3c814f03ce1f72b0154116594d3c4"
)
V2_RESULT_HASH = "110018f6997b7b96c55398696f68a70b1935f9a488dfe39bcc204e9ea5bb6d68"


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    result = validate(root)
    output = Path(args.output)
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(json_ready(result), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(
        json.dumps(
            {
                "checks_failed": result["summary"]["failed"],
                "checks_passed": result["summary"]["passed"],
                "output": str(output),
                "state_hash": result["state_hash"],
                "validation_hash": result["validation_hash"],
                "verdict": result["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )
    if result["summary"]["failed"]:
        raise SystemExit(1)


def validate(root: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    contract_path = (
        root
        / "research_manifests"
        / "gold_session_behaviour_discovery_contract_v03.json"
    )
    traceability_path = (
        root
        / "research_manifests"
        / "gold_session_behaviour_v3_traceability_v01.json"
    )
    coverage_path = (
        root
        / "research_artifacts"
        / "gold_session_behaviour_v3_coverage_v01.json"
    )
    state_path = (
        root
        / "research_artifacts"
        / "gold_session_behaviour_v3_state_v01.json"
    )
    schema_path = (
        root
        / "research_schemas"
        / "gold_session_behaviour_v3_case_matrix.schema.json"
    )
    reference_book_path = root / "Gold_USD_Market_Intelligence_Reference_Book.pdf"
    original_path = (
        root
        / "research_artifacts"
        / "gold_casebook_chronological_validation_v01"
        / "manifest.json"
    )
    v2_path = (
        root
        / "research_artifacts"
        / "gold_casebook_discovery_v2_holdout_v01"
        / "manifest.json"
    )

    contract = _load_json(contract_path)
    traceability = _load_json(traceability_path)
    coverage = _load_json(coverage_path)
    state = _load_json(state_path)
    schema = _load_json(schema_path)
    original = _load_json(original_path)
    v2 = _load_json(v2_path)

    _check(
        checks,
        "CONTRACT_HASH",
        verify_embedded_hash(contract, hash_field="manifest_hash") == CONTRACT_HASH,
        {"expected": CONTRACT_HASH},
    )
    _check(
        checks,
        "TRACEABILITY_HASH",
        verify_embedded_hash(traceability, hash_field="catalog_hash")
        == TRACEABILITY_HASH,
        {"expected": TRACEABILITY_HASH},
    )
    _check(
        checks,
        "REFERENCE_BOOK_HASH",
        sha256_file(reference_book_path) == REFERENCE_BOOK_HASH,
        {"expected": REFERENCE_BOOK_HASH},
    )
    _check(
        checks,
        "TIME_PARTITIONS",
        _time_partitions_are_exact(contract),
        contract["time_partitions"],
    )
    _check(
        checks,
        "MILESTONE_1_ONLY",
        contract["v3_milestone_1"]["authorized"] is True
        and contract["v3_milestone_1"]["stop_after_completion"] is True
        and all(
            item["authorized"] is False
            for item in contract["milestones"]
            if item["code"] != "V3_M1_CONTRACT_TRACEABILITY_METADATA_SCHEMA_STATE"
        ),
        {
            "current": contract["v3_milestone_1"]["code"],
            "stop_after_completion": contract["v3_milestone_1"][
                "stop_after_completion"
            ],
        },
    )

    _check(
        checks,
        "ORIGINAL_REJECTION_PRESERVED",
        original["manifest_hash"] == ORIGINAL_RESULT_HASH
        and original["selector_code"] == "UNIVERSAL_ZN_4H_SIGN_V0_1"
        and original["verdict"] == "REJECT_CHRONOLOGICAL_VALIDATION",
        {
            "manifest_hash": original["manifest_hash"],
            "selector_code": original["selector_code"],
            "verdict": original["verdict"],
        },
    )
    _check(
        checks,
        "V2_REJECTION_PRESERVED",
        v2["manifest_hash"] == V2_RESULT_HASH
        and v2["candidate_code"] == "LONDON_ZN_4H_POSTHOC_V0_1"
        and v2["verdict"] == "REJECT_CALENDAR_2025_HOLDOUT",
        {
            "manifest_hash": v2["manifest_hash"],
            "candidate_code": v2["candidate_code"],
            "verdict": v2["verdict"],
        },
    )

    requirements = traceability["field_requirements"]
    status_counts = Counter(item["development_coverage"] for item in requirements)
    _check(
        checks,
        "TRACEABILITY_REQUIREMENTS_UNIQUE",
        len(requirements) == 75
        and len({item["factor_id"] for item in requirements}) == 75,
        {"requirements": len(requirements)},
    )
    _check(
        checks,
        "TRACEABILITY_STATUS_COUNTS",
        status_counts
        == {
            "PRESENT": 34,
            "PARTIAL": 18,
            "DERIVABLE": 14,
            "UNAVAILABLE": 6,
            "OUT_OF_SCOPE": 3,
        },
        dict(sorted(status_counts.items())),
    )
    _check(
        checks,
        "TRACEABILITY_PRE_RESULT",
        traceability["generated_from_results"] is False
        and traceability["relationship_or_candidate_fields_included"] is False,
        {
            "generated_from_results": traceability["generated_from_results"],
            "relationship_or_candidate_fields_included": traceability[
                "relationship_or_candidate_fields_included"
            ],
        },
    )
    _check(
        checks,
        "TRACEABILITY_PATH_ROOTS",
        _traceability_roots_are_valid(requirements),
        {"valid_roots": _valid_traceability_roots()},
    )

    missing_refs = _missing_internal_schema_refs(schema)
    _check(
        checks,
        "CASE_MATRIX_SCHEMA_INTERNAL_REFS",
        not missing_refs,
        {"missing_refs": missing_refs, "definition_count": len(schema["$defs"])},
    )
    _check(
        checks,
        "CASE_MATRIX_DECISION_OUTCOME_SEPARATION",
        schema["$defs"]["subsequent_behaviour"]["properties"][
            "decision_eligible"
        ]["const"]
        is False
        and schema["$defs"]["decision_state"]["properties"]["decision_eligible"][
            "const"
        ]
        is True,
        {
            "decision_state": True,
            "subsequent_behaviour": False,
        },
    )
    policy = schema["$defs"]["research_policy"]["properties"]
    _check(
        checks,
        "CASE_MATRIX_NO_EXECUTION",
        all(
            policy[key]["const"] is False
            for key in (
                "trade_direction_assigned",
                "candidate_or_relationship_label_present",
                "entry_or_exit_assumed",
                "stop_or_target_assigned",
                "position_size_assigned",
                "execution_optimized",
                "mfe_or_mae_calculated",
                "pnl_or_r_multiple_calculated",
                "account_return_calculated",
            )
        ),
        {"execution_flags_fixed_false": 9},
    )

    coverage_hash = _deterministic_document_hash(
        coverage,
        hash_field="data_hash",
    )
    _check(
        checks,
        "COVERAGE_HASH",
        coverage_hash == coverage["data_hash"],
        {
            "supplied": coverage["data_hash"],
            "calculated": coverage_hash,
        },
    )
    boundary = coverage["audit_boundary"]
    _check(
        checks,
        "METADATA_ONLY_BOUNDARY",
        boundary["database_transaction_read_only"] is True
        and boundary["sql_guard_passed"] is True
        and boundary["exposed_2025_market_or_macro_values_read"] is False
        and boundary["locked_2026_market_or_macro_values_read"] is False
        and boundary["exposed_2025_outcomes_calculated"] is False
        and boundary["locked_2026_outcomes_calculated"] is False
        and boundary["feature_values_calculated"] is False
        and boundary["feature_outcome_joins_calculated"] is False
        and boundary["relationship_statistics_calculated"] is False
        and boundary["candidate_discovery_started"] is False,
        boundary,
    )

    audit_module = _load_audit_module(
        root / "backend" / "tools" / "audit_gold_session_behaviour_v3_coverage.py"
    )
    sql_statements = audit_module.SQL_STATEMENTS
    sql_guard_passed = True
    try:
        assert_metadata_only_sql(sql_statements)
    except ValueError:
        sql_guard_passed = False
    expected_sql_hashes = {
        name: hashlib.sha256(statement.encode()).hexdigest()
        for name, statement in sorted(sql_statements.items())
    }
    _check(
        checks,
        "AUDIT_SQL_RECHECK",
        sql_guard_passed
        and boundary["sql_statement_count"] == len(sql_statements)
        and boundary["sql_statement_sha256"] == expected_sql_hashes,
        {
            "statement_count": len(sql_statements),
            "guard_passed": sql_guard_passed,
        },
    )

    milestone = coverage["milestone_decision"]
    _check(
        checks,
        "NO_RESEARCH_STARTED",
        milestone["case_matrix_rows_built"] == 0
        and milestone["relationship_calculations"] == 0
        and milestone["candidates_created"] == 0
        and milestone["2025_values_inspected"] is False
        and milestone["2026_values_inspected"] is False
        and milestone["next_milestone_authorized"] is False
        and milestone["mandatory_stop"] is True,
        milestone,
    )
    _check(
        checks,
        "LOCKED_2026_STATE",
        coverage["locked_2026_ytd"]["value_access_state"] == "LOCKED"
        and coverage["locked_2026_ytd"]["values_or_outcomes_read_by_v3_m1"]
        is False
        and coverage["locked_2026_ytd"]["classification"]
        == "LOCKED_INDEPENDENT_HOLDOUT",
        {
            "classification": coverage["locked_2026_ytd"]["classification"],
            "value_access_state": coverage["locked_2026_ytd"][
                "value_access_state"
            ],
        },
    )
    _check(
        checks,
        "EXPOSED_2025_STATE",
        coverage["exposed_2025"]["classification"]
        == "EXPOSED_HISTORICAL_FORWARD_TEST_NO_INDEPENDENT_CREDIT"
        and coverage["exposed_2025"]["values_or_outcomes_read_by_v3_m1"]
        is False,
        {"classification": coverage["exposed_2025"]["classification"]},
    )

    state_hash = _deterministic_document_hash(state, hash_field="state_hash")
    _check(
        checks,
        "STATE_HASH",
        state_hash == state["state_hash"],
        {
            "supplied": state["state_hash"],
            "calculated": state_hash,
        },
    )
    output_mismatches = _state_output_mismatches(root, state)
    _check(
        checks,
        "STATE_OUTPUT_HASHES",
        not output_mismatches,
        {"mismatches": output_mismatches},
    )
    _check(
        checks,
        "STATE_MANDATORY_STOP",
        state["current_milestone"]["status"] == "COMPLETE_MANDATORY_STOP"
        and state["current_milestone"]["next_milestone_authorized"] is False
        and state["next_action"]["authorized"] is False,
        {
            "status": state["current_milestone"]["status"],
            "next_authorized": state["next_action"]["authorized"],
        },
    )

    m2_paths = _unexpected_post_m1_paths(root)
    _check(
        checks,
        "NO_V3_M2_OR_CASE_ARTIFACTS",
        not m2_paths,
        {"unexpected_paths": m2_paths},
    )

    failed = sum(item["status"] == "FAIL" for item in checks)
    result: dict[str, Any] = {
        "validation_version": "GOLD_SESSION_BEHAVIOUR_V3_M1_VALIDATION_V0_1",
        "generated_at": datetime.now(UTC).isoformat(),
        "milestone": "V3_M1_CONTRACT_TRACEABILITY_METADATA_SCHEMA_STATE",
        "state_hash": state["state_hash"],
        "contract_manifest_hash": CONTRACT_HASH,
        "traceability_catalog_hash": TRACEABILITY_HASH,
        "coverage_data_hash": coverage["data_hash"],
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_1_MANDATORY_STOP"
            if failed == 0
            else "FAIL_V3_MILESTONE_1_VALIDATION"
        ),
    }
    add_deterministic_hash(result, hash_field="validation_hash")
    return result


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


def _time_partitions_are_exact(contract: dict[str, Any]) -> bool:
    partitions = contract["time_partitions"]
    return (
        partitions["development"]["session_date_start_inclusive"] == "2021-08-01"
        and partitions["development"]["session_date_end_inclusive"] == "2024-12-31"
        and partitions["exposed_historical_forward_test"][
            "session_date_start_inclusive"
        ]
        == "2025-01-01"
        and partitions["exposed_historical_forward_test"][
            "session_date_end_inclusive"
        ]
        == "2025-12-31"
        and partitions["exposed_historical_forward_test"][
            "independent_validation_credit"
        ]
        is False
        and partitions["independent_2026_ytd_holdout"][
            "session_date_start_inclusive"
        ]
        == "2026-01-01"
        and partitions["independent_2026_ytd_holdout"][
            "session_date_end_inclusive"
        ]
        == "2026-07-29"
        and partitions["independent_2026_ytd_holdout"]["values_loaded_for_v3"]
        is False
        and partitions["prospective_2026"]["earliest_session_date"] == "2026-07-30"
    )


def _valid_traceability_roots() -> set[str]:
    return {
        "case_metadata",
        "lineage",
        "quality",
        "decision_state",
        "subsequent_behaviour",
    }


def _traceability_roots_are_valid(requirements: list[dict[str, Any]]) -> bool:
    valid = _valid_traceability_roots()
    return all(
        not path or path.split(".", maxsplit=1)[0].replace("[]", "") in valid
        for item in requirements
        for path in item["case_matrix_fields"]
    )


def _missing_internal_schema_refs(schema: dict[str, Any]) -> list[str]:
    definitions = set(schema["$defs"])
    missing: set[str] = set()

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            ref = value.get("$ref")
            if isinstance(ref, str) and ref.startswith("#/$defs/"):
                name = ref.removeprefix("#/$defs/")
                if name not in definitions:
                    missing.add(ref)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(schema)
    return sorted(missing)


def _deterministic_document_hash(
    document: dict[str, Any],
    *,
    hash_field: str,
) -> str:
    content = {
        key: value
        for key, value in document.items()
        if key not in {"generated_at", hash_field}
    }
    return hashlib.sha256(
        json.dumps(
            json_ready(content),
            sort_keys=True,
            separators=(",", ":"),
        ).encode()
    ).hexdigest()


def _state_output_mismatches(root: Path, state: dict[str, Any]) -> list[dict[str, Any]]:
    mismatches: list[dict[str, Any]] = []
    for item in state["milestone_1_outputs"]:
        path = root / item["path"]
        if not path.exists():
            mismatches.append({"path": item["path"], "reason": "MISSING"})
            continue
        actual_bytes = path.stat().st_size
        actual_hash = sha256_file(path)
        if actual_bytes != item["bytes"] or actual_hash != item["sha256"]:
            mismatches.append(
                {
                    "path": item["path"],
                    "declared_bytes": item["bytes"],
                    "actual_bytes": actual_bytes,
                    "declared_sha256": item["sha256"],
                    "actual_sha256": actual_hash,
                }
            )
    return mismatches


def _unexpected_post_m1_paths(root: Path) -> list[str]:
    candidates: list[Path] = []
    for pattern in (
        "GOLD_SESSION_BEHAVIOUR_V3_M2*",
        "GOLD_SESSION_BEHAVIOUR_V3_CASES*",
    ):
        candidates.extend(root.glob(pattern))
    for directory in (
        root / "research_artifacts",
        root / "research_manifests",
        root / "research_schemas",
    ):
        if not directory.exists():
            continue
        for pattern in (
            "gold_session_behaviour_v3_m2*",
            "gold_session_behaviour_v3_cases*",
        ):
            candidates.extend(directory.glob(pattern))
    return sorted(
        {
            str(path.relative_to(root)).replace("\\", "/")
            for path in candidates
            if path.is_file()
        }
    )


def _load_audit_module(path: Path) -> ModuleType:
    spec = importlib.util.spec_from_file_location("v3_coverage_audit", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Could not load audit module: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Validate Gold Session Behaviour V3 Milestone 1."
    )
    parser.add_argument("--root", required=True)
    parser.add_argument("--output", required=True)
    return parser


if __name__ == "__main__":
    main()
