from __future__ import annotations

import argparse
import gzip
import json
from collections import Counter
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m5 import (
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
EXPECTED_RESULT_MANIFEST_HASH = (
    "3fc550f8c18279742b82c3176246e862f571cbbc759966ac9bf441d7e3c38fdb"
)
EXPECTED_M5_HASH = (
    "e399534950756933905d2cbfb69bc03e69c5fba60910830b879da08db138f508"
)
EXPECTED_RESULT_FILE_HASH = (
    "f1bcf4c8f84e2aa44e7a6bb77e30bda36e478bd8d89b4f12761cbfe5422a5743"
)
EXPECTED_BUILD_VALIDATION_HASH = (
    "f79bfa1897beba0804c66624cf6b7b7348e6f529f5d128ae7d5682b684cd40dd"
)
VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M5_INDEPENDENT_VALIDATION_V0_1"
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    if root not in output.parents:
        raise ValueError("Output path must remain inside the repository root")
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
    m4_manifest = _load_json(paths["m4_pre_manifest"])
    m4_state = _load_json(paths["m4_state"])
    case_manifest = _load_json(paths["case_manifest"])
    result_manifest = _load_json(paths["result_manifest"])
    result = _load_json(paths["result"])
    build_validation = _load_json(paths["build_validation"])
    checks: list[dict[str, Any]] = []

    _check(
        checks,
        "M5_PRE_RESULT_MANIFEST_SEAL",
        _embedded_hash(pre_manifest, "manifest_hash")
        == pre_manifest["manifest_hash"]
        == M5_PRE_RESULT_MANIFEST_HASH
        and sha256_file(paths["pre_manifest"])
        == M5_PRE_RESULT_MANIFEST_FILE_HASH,
        {
            "manifest_hash": pre_manifest["manifest_hash"],
            "file_sha256": sha256_file(paths["pre_manifest"]),
        },
    )
    _check(
        checks,
        "M4_FEATURE_REGISTRY_SEAL",
        _embedded_hash(m4_manifest, "manifest_hash")
        == m4_manifest["manifest_hash"]
        == M4_PRE_RESULT_MANIFEST_HASH,
        {"manifest_hash": m4_manifest["manifest_hash"]},
    )
    state_hash = canonical_hash(
        {
            key: value
            for key, value in m4_state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    _check(
        checks,
        "M4_STATE_SEAL",
        state_hash == m4_state["state_hash"] == M4_STATE_HASH
        and sha256_file(paths["m4_state"]) == M4_STATE_FILE_HASH,
        {
            "state_hash": state_hash,
            "file_sha256": sha256_file(paths["m4_state"]),
        },
    )
    _check(
        checks,
        "CASE_MATRIX_SEAL",
        _embedded_hash(case_manifest, "manifest_hash")
        == case_manifest["manifest_hash"]
        == CASE_MANIFEST_HASH
        and sha256_file(paths["cases"]) == CASE_ARTIFACT_HASH,
        {
            "manifest_hash": case_manifest["manifest_hash"],
            "artifact_sha256": sha256_file(paths["cases"]),
        },
    )
    _check(
        checks,
        "M5_IMPLEMENTATION_SEAL",
        sha256_file(paths["m5_module"]) == M5_MODULE_HASH,
        {"module_sha256": sha256_file(paths["m5_module"])},
    )
    _check(
        checks,
        "M5_RESULT_MANIFEST_SEAL",
        _embedded_hash(result_manifest, "manifest_hash")
        == result_manifest["manifest_hash"]
        and (
            not EXPECTED_RESULT_MANIFEST_HASH
            or result_manifest["manifest_hash"]
            == EXPECTED_RESULT_MANIFEST_HASH
        ),
        {
            "manifest_hash": result_manifest["manifest_hash"],
            "expected": EXPECTED_RESULT_MANIFEST_HASH,
        },
    )
    result_declaration = next(
        item
        for item in result_manifest["artifacts"]
        if item["name"] == "stability_results.json"
    )
    _check(
        checks,
        "M5_RESULT_ARTIFACT_SEAL",
        sha256_file(paths["result"]) == result_declaration["sha256"]
        and paths["result"].stat().st_size == result_declaration["bytes"]
        and result["m5_hash"] == result_declaration["m5_hash"]
        and (
            not EXPECTED_M5_HASH or result["m5_hash"] == EXPECTED_M5_HASH
        )
        and (
            not EXPECTED_RESULT_FILE_HASH
            or sha256_file(paths["result"]) == EXPECTED_RESULT_FILE_HASH
        ),
        {
            "m5_hash": result["m5_hash"],
            "file_sha256": sha256_file(paths["result"]),
            "bytes": paths["result"].stat().st_size,
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
        and sha256_file(paths["build_validation"])
        == validation_declaration["sha256"]
        and build_validation["summary"]["failed"] == 0
        and (
            not EXPECTED_BUILD_VALIDATION_HASH
            or build_validation["validation_hash"]
            == EXPECTED_BUILD_VALIDATION_HASH
        ),
        {
            "validation_hash": build_validation["validation_hash"],
            "file_sha256": sha256_file(paths["build_validation"]),
        },
    )

    cases, readback = _independent_case_readback(
        paths["cases"],
        features=list(m4_manifest["feature_registry"]),
    )
    _check(
        checks,
        "EXACT_SOURCE_COUNTS",
        readback["records"] == 1659
        and readback["session_counts"]
        == {"LONDON": 833, "NEW_YORK": 826},
        readback,
    )
    _check(
        checks,
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
    )
    _check(
        checks,
        "SOURCE_HASH_CHAIN_MATCH",
        readback["record_hash_chain"]
        == result_manifest["source"]["source_record_hash_chain"],
        {
            "recomputed": readback["record_hash_chain"],
            "sealed": result_manifest["source"]["source_record_hash_chain"],
        },
    )
    recomputed = build_m5_results(cases, frozen_manifest=pre_manifest)
    _check(
        checks,
        "INDEPENDENT_EXACT_RESULT_REPRODUCTION",
        recomputed == result
        and canonical_hash(recomputed) == canonical_hash(result),
        {
            "documents_equal": recomputed == result,
            "recomputed_m5_hash": recomputed["m5_hash"],
            "sealed_m5_hash": result["m5_hash"],
        },
    )
    semantic_errors = validate_m5_semantics(
        result,
        frozen_manifest=pre_manifest,
    )
    _check(
        checks,
        "M5_SEMANTIC_INVARIANTS",
        not semantic_errors,
        {"errors": semantic_errors},
    )
    records = [
        *result["sessions"]["LONDON"]["candidate_records"],
        *result["sessions"]["NEW_YORK"]["candidate_records"],
    ]
    _check(
        checks,
        "EXACT_AUTHORIZED_CANDIDATE_SET",
        [item["candidate_code"] for item in records]
        == [
            item["candidate_code"]
            for item in pre_manifest["candidate_registry"]
        ],
        {"candidate_codes": [item["candidate_code"] for item in records]},
    )
    _check(
        checks,
        "ALL_PASS_AND_REJECTION_RESULTS_RETAINED",
        len(records) == 4
        and all("gate_failures" in item for item in records),
        {
            "records": len(records),
            "passed": sum(item["gate_pass"] for item in records),
            "rejected": sum(not item["gate_pass"] for item in records),
        },
    )
    boundary = result["interpretation_boundary"]
    _check(
        checks,
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
    )
    _check(
        checks,
        "SHORTLIST_CAP_AND_NO_VALIDATION_CREDIT",
        all(
            len(result["sessions"][session]["shortlist"]) <= 2
            and all(
                item["forward_validation_credit"] is False
                for item in result["sessions"][session]["shortlist"]
            )
            for session in ("LONDON", "NEW_YORK")
        ),
        {
            session: result["sessions"][session]["shortlist"]
            for session in ("LONDON", "NEW_YORK")
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
        "generated_at": pre_manifest["recorded_at"],
        "milestone": "V3_M5_INTERNAL_STABILITY_AND_SHORTLIST_FREEZE",
        "result_manifest_hash": result_manifest["manifest_hash"],
        "m5_hash": result["m5_hash"],
        "result_file_sha256": sha256_file(paths["result"]),
        "records_read_back": readback["records"],
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_5_INDEPENDENT_VALIDATION_MANDATORY_STOP"
            if failed == 0
            else "FAIL_V3_MILESTONE_5_INDEPENDENT_VALIDATION"
        ),
    }


def _independent_case_readback(
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
                raise ValueError(
                    f"Source record hash mismatch: line {line_number}"
                )
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
                session_order[case.session_code],
            )
            if prior_key is not None and key <= prior_key:
                row_order_violations += 1
            prior_key = key
            session_counts[case.session_code] += 1
            record_hashes.append(supplied)
            cases.append(case)
    return cases, {
        "records": len(cases),
        "unique_case_ids": len(case_ids),
        "unique_session_dates": len(session_dates),
        "session_counts": dict(sorted(session_counts.items())),
        "record_hash_chain": canonical_hash(record_hashes),
        "record_hash_mismatches": record_hash_mismatches,
        "row_order_violations": row_order_violations,
    }


def _embedded_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != field}
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


def _paths(root: Path) -> dict[str, Path]:
    result_dir = (
        root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m5_stability_v01"
    )
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
        "result_manifest": result_dir / "manifest.json",
        "result": result_dir / "stability_results.json",
        "build_validation": result_dir / "semantic_validation.json",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reproduce and validate V3 Milestone 5 internal "
            "stability and shortlist results."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m5_validation_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
