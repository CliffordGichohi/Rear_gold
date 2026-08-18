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
from gold_intel.analytics.session_behaviour_v3_discovery_validation import (
    validate_discovery_semantics,
)
from gold_intel.analytics.session_behaviour_v3_relationships import (
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
CASE_MANIFEST_HASH = (
    "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
)
CASE_ARTIFACT_HASH = (
    "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
)
FEATURE_MODULE_HASH = (
    "921a6d02c71514438e46a81d22f0ea788b2bdfca88172e564d10b510f14e96dc"
)
RELATIONSHIP_MODULE_HASH = (
    "8ad9c8adfc94ea433e185ce1b17b7f9f1d8981f29b7b967b338d351b8f51ee97"
)
VALIDATION_MODULE_HASH = (
    "a8584de3c2fcb8e11d0b0e6fd16a85f7bcf7887eef2e7e6c0309cb9d48925a4c"
)
EXPECTED_RESULT_MANIFEST_HASH = (
    "c12a71ac9decf0d2cd3f6866528809c937edab8cd6fc3e42072a5bbf8187c40c"
)
EXPECTED_DISCOVERY_HASH = (
    "c8d011c69446df3f287dae9e77a4d0e78057c8850e811299302b689ff09d6b70"
)
EXPECTED_DISCOVERY_FILE_HASH = (
    "f8a4e55da149ec22f29f3455251f7c69bcf9e316b2fbad75f7a7580d8a04412b"
)
EXPECTED_BUILD_VALIDATION_HASH = (
    "bebca06e34f9fcf1233613c0986663750a47dfa38ac3a5ae9c4f37d4aa0bafb4"
)
VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M4_INDEPENDENT_VALIDATION_V0_1"
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
    m3_state = _load_json(paths["m3_state"])
    case_manifest = _load_json(paths["case_manifest"])
    result_manifest = _load_json(paths["result_manifest"])
    discovery = _load_json(paths["discovery"])
    build_validation = _load_json(paths["build_validation"])
    checks: list[dict[str, Any]] = []

    _check(
        checks,
        "M4_PRE_RESULT_MANIFEST_SEAL",
        _embedded_hash(pre_manifest, "manifest_hash")
        == pre_manifest["manifest_hash"]
        == M4_PRE_RESULT_MANIFEST_HASH
        and sha256_file(paths["pre_manifest"])
        == M4_PRE_RESULT_MANIFEST_FILE_HASH,
        {
            "manifest_hash": pre_manifest["manifest_hash"],
            "file_sha256": sha256_file(paths["pre_manifest"]),
        },
    )
    calculated_state_hash = canonical_hash(
        {
            key: value
            for key, value in m3_state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    _check(
        checks,
        "M3_PREDECESSOR_STATE_SEAL",
        calculated_state_hash == m3_state["state_hash"] == M3_STATE_HASH
        and sha256_file(paths["m3_state"]) == M3_STATE_FILE_HASH,
        {
            "state_hash": m3_state["state_hash"],
            "file_sha256": sha256_file(paths["m3_state"]),
        },
    )
    _check(
        checks,
        "DEVELOPMENT_CASE_MATRIX_SEAL",
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
        "FROZEN_IMPLEMENTATION_SEALS",
        sha256_file(paths["feature_module"]) == FEATURE_MODULE_HASH
        and sha256_file(paths["relationship_module"])
        == RELATIONSHIP_MODULE_HASH
        and sha256_file(paths["validation_module"])
        == VALIDATION_MODULE_HASH,
        {
            "feature_module_sha256": sha256_file(paths["feature_module"]),
            "relationship_module_sha256": sha256_file(
                paths["relationship_module"]
            ),
            "validation_module_sha256": sha256_file(
                paths["validation_module"]
            ),
        },
    )

    supplied_result_manifest_hash = _embedded_hash(
        result_manifest,
        "manifest_hash",
    )
    _check(
        checks,
        "M4_RESULT_MANIFEST_SEAL",
        supplied_result_manifest_hash == result_manifest["manifest_hash"]
        and (
            not EXPECTED_RESULT_MANIFEST_HASH
            or result_manifest["manifest_hash"]
            == EXPECTED_RESULT_MANIFEST_HASH
        ),
        {
            "manifest_hash": result_manifest["manifest_hash"],
            "expected_frozen_hash": EXPECTED_RESULT_MANIFEST_HASH,
        },
    )
    discovery_declaration = next(
        item
        for item in result_manifest["artifacts"]
        if item["name"] == "relationships.json"
    )
    _check(
        checks,
        "DISCOVERY_ARTIFACT_SEAL",
        sha256_file(paths["discovery"])
        == discovery_declaration["sha256"]
        and paths["discovery"].stat().st_size
        == discovery_declaration["bytes"]
        and discovery["discovery_hash"]
        == discovery_declaration["discovery_hash"]
        and (
            not EXPECTED_DISCOVERY_HASH
            or discovery["discovery_hash"] == EXPECTED_DISCOVERY_HASH
        )
        and (
            not EXPECTED_DISCOVERY_FILE_HASH
            or sha256_file(paths["discovery"])
            == EXPECTED_DISCOVERY_FILE_HASH
        ),
        {
            "discovery_hash": discovery["discovery_hash"],
            "file_sha256": sha256_file(paths["discovery"]),
            "bytes": paths["discovery"].stat().st_size,
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
        features=list(pre_manifest["feature_registry"]),
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
            "row_order_violations": readback["row_order_violations"],
            "record_hash_chain": readback["record_hash_chain"],
        },
    )
    _check(
        checks,
        "SOURCE_HASH_CHAIN_MATCHES_BUILD",
        readback["record_hash_chain"]
        == result_manifest["source"]["source_record_hash_chain"],
        {
            "recomputed": readback["record_hash_chain"],
            "sealed": result_manifest["source"]["source_record_hash_chain"],
        },
    )

    recomputed = build_discovery_results(
        cases,
        frozen_manifest=pre_manifest,
    )
    _check(
        checks,
        "INDEPENDENT_DISCOVERY_REPRODUCTION",
        recomputed == discovery
        and canonical_hash(recomputed) == canonical_hash(discovery),
        {
            "documents_equal": recomputed == discovery,
            "recomputed_discovery_hash": recomputed["discovery_hash"],
            "sealed_discovery_hash": discovery["discovery_hash"],
        },
    )
    semantic_errors = validate_discovery_semantics(
        discovery,
        frozen_manifest=pre_manifest,
    )
    _check(
        checks,
        "DISCOVERY_SEMANTIC_INVARIANTS",
        not semantic_errors,
        {"errors": semantic_errors},
    )
    _check(
        checks,
        "ALL_REGISTERED_RESULTS_RETAINED",
        all(
            session["summary"]["single_conditions_registered"]
            == len(session["single_condition_results"])
            and session["summary"]["interaction_conditions_registered"]
            == len(session["interaction_results"])
            for session in discovery["sessions"].values()
        ),
        {
            session_code: session["summary"]
            for session_code, session in discovery["sessions"].items()
        },
    )
    _check(
        checks,
        "SESSION_SEPARATION_AND_CANDIDATE_CAP",
        set(discovery["sessions"]) == {"LONDON", "NEW_YORK"}
        and discovery["interpretation_boundary"]["combined_session_result"]
        is False
        and all(
            len(discovery["sessions"][code]["provisional_candidates"]) <= 2
            for code in ("LONDON", "NEW_YORK")
        ),
        {
            code: len(
                discovery["sessions"][code]["provisional_candidates"]
            )
            for code in ("LONDON", "NEW_YORK")
        },
    )
    boundary = discovery["interpretation_boundary"]
    _check(
        checks,
        "NO_HOLDOUT_EXECUTION_RETUNING_OR_REJECTED_ZN",
        boundary["calendar_2025_values_opened"] is False
        and boundary["calendar_2026_values_opened"] is False
        and boundary["development_only"] is True
        and boundary["execution_variants"] == 0
        and boundary["trades_or_returns"] == 0
        and boundary["rejected_zn_rules_reopened"] is False
        and boundary["provisional_candidates_have_validation_credit"]
        is False,
        boundary,
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
        "generated_at": str(pre_manifest["recorded_at"]),
        "milestone": "V3_M4_BOUNDED_CONDITIONAL_BIAS_DISCOVERY",
        "result_manifest_hash": result_manifest["manifest_hash"],
        "discovery_hash": discovery["discovery_hash"],
        "discovery_file_sha256": sha256_file(paths["discovery"]),
        "records_read_back": readback["records"],
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - failed,
            "failed": failed,
        },
        "verdict": (
            "PASS_V3_MILESTONE_4_INDEPENDENT_VALIDATION_MANDATORY_STOP"
            if failed == 0
            else "FAIL_V3_MILESTONE_4_INDEPENDENT_VALIDATION"
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
    discovery_dir = (
        root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m4_discovery_v01"
    )
    return {
        "pre_manifest": (
            root
            / "research_manifests"
            / "gold_session_behaviour_v3_m4_discovery_v01.json"
        ),
        "m3_state": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_state_v03.json"
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
        "validation_module": (
            root
            / "backend"
            / "src"
            / "gold_intel"
            / "analytics"
            / "session_behaviour_v3_discovery_validation.py"
        ),
        "result_manifest": discovery_dir / "manifest.json",
        "discovery": discovery_dir / "relationships.json",
        "build_validation": discovery_dir / "semantic_validation.json",
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reproduce and validate the Gold Session Behaviour "
            "V3 Milestone 4 bounded conditional-bias discovery."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m4_validation_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
