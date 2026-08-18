from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_RESULT_HASH,
    M5_SHORTLIST_CODES,
    M6A_AUDIT_VERSION,
    M6A_PROTOCOL_VERSION,
    forward_candidate_registry,
    forward_protocol,
    protocol_fingerprint,
    validate_forward_protocol,
)

FROZEN_AT = "2026-07-30T12:27:56Z"
MANIFEST_VERSION = "GOLD_SESSION_BEHAVIOUR_V3_M6A_PRERESULT_V0_1"

CONTRACT_HASH = "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
CONTRACT_FILE_HASH = (
    "993e91610992c62fd97c3c9aeb81b8a46ed422f025fac441b629ce35985ca591"
)
V05_STATE_HASH = "9ad36a1c24b9c421b70a523c93170cef2e00f2f62804be8368ec7614d5cf621b"
V05_STATE_FILE_HASH = (
    "982847ec9824c0f0feb9b86513f90301787179499f69ab7b29384e7a77761c44"
)
M5_PRE_RESULT_MANIFEST_HASH = (
    "adbeed7d029fab23ec72c3866f58bc041d48fe9f8607f65508246f6240917dab"
)
M5_PRE_RESULT_MANIFEST_FILE_HASH = (
    "eceda7c20e4c43b33ce786f246176c34b43aa9f48806c11fac5bd47f230b8584"
)
M5_RESULT_FILE_HASH = (
    "f1bcf4c8f84e2aa44e7a6bb77e30bda36e478bd8d89b4f12761cbfe5422a5743"
)
M5_RESULT_MANIFEST_HASH = (
    "3fc550f8c18279742b82c3176246e862f571cbbc759966ac9bf441d7e3c38fdb"
)
M5_RESULT_MANIFEST_FILE_HASH = (
    "374dfcc2f5928a60c16a362dbf034da8fa8ac3a99014ad6f1c37ee230eb24b34"
)
M5_VALIDATION_HASH = (
    "9b6f9da28c67cf13f90f13e062f6d1106059777d0baa89d64dd590184f191c11"
)
M5_VALIDATION_FILE_HASH = (
    "44c27747940af171d85e47ae6aa2f83572103872ee30b95ac8029906edc60f82"
)
AMENDMENT_B_HASH = (
    "8213fcdb3d7f5571c7688a70ebcbddd8d6ce85b7613dae185c4324b551314799"
)
M6A_MODULE_HASH = (
    "ec94b95299713584b6a687b62f3e774d355eb06431779ed23d474aa891a88ba7"
)
M6A_AUDIT_TOOL_HASH = (
    "90a52dbc68357d3bf699f7ed24bdc5f740f54c2a30e6d7f2aeae671698243f7b"
)
M6A_TEST_HASH = (
    "b39f7c6335d760e2f2670a8d49b4fac46bda98e4046019673cc68b11e71b2b97"
)

AUTHORIZATION = (
    "Proceed to V3 Milestone 6A under the existing contract. Preserve the "
    "frozen Milestone 5 shortlist unchanged: "
    "LONDON_VOLATILITY_DIRECTION_V0_1 and "
    "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1. Perform only a "
    "candidate-specific metadata-only readiness and power audit for calendar "
    "2025, locked 2026 YTD through 29 July, and prospective tracking. Create "
    "Amendment B and freeze the exact support floors, multiplicity method, "
    "effect and uncertainty requirements, PASS/REJECT/INCONCLUSIVE rules, "
    "segment reporting order, and missing-data policy before inspecting any "
    "values or outcomes. Do not retune candidates, add variables, optimize "
    "execution, use COT as a pass gate, reopen rejected candidates or ZN "
    "rules, or inspect 2025/2026 market values or outcomes. Complete only the "
    "pre-result protocol and readiness audit, seal them, and stop before "
    "opening the holdouts."
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    _assert_within(root, output)
    if output.exists():
        raise FileExistsError(
            "M6A pre-result manifest already exists; refusing to overwrite"
        )
    manifest = build_manifest(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, manifest)
    print(
        json.dumps(
            {
                "candidate_count": len(manifest["candidate_registry"]),
                "manifest_hash": manifest["manifest_hash"],
                "output": str(output),
                "protocol_fingerprint": manifest["protocol_fingerprint"],
                "verdict": manifest["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_manifest(root: Path) -> dict[str, Any]:
    paths = _paths(root)
    _verify_inputs(paths)
    protocol_failures = validate_forward_protocol()
    if protocol_failures:
        raise ValueError(f"M6A forward protocol invalid: {protocol_failures}")
    candidates = forward_candidate_registry()
    protocol = forward_protocol()
    manifest: dict[str, Any] = {
        "manifest_version": MANIFEST_VERSION,
        "milestone": "V3_M6A_FORWARD_PROTOCOL_AND_METADATA_READINESS",
        "recorded_at": FROZEN_AT,
        "authorization": {
            "authorized_on": "2026-07-30",
            "verbatim": AUTHORIZATION,
            "scope": (
                "Complete only the pre-result protocol and metadata-only "
                "readiness and power audit; stop before holdout opening."
            ),
        },
        "amendment_b": {
            "path": "GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_B.md",
            "file_sha256": AMENDMENT_B_HASH,
            "completes_forward_gate_freeze_before_value_access": True,
            "changes_m5_candidate_definition": False,
        },
        "frozen_inputs": {
            "contract": {
                "path": "research_manifests/gold_session_behaviour_discovery_contract_v03.json",
                "manifest_hash": CONTRACT_HASH,
                "file_sha256": CONTRACT_FILE_HASH,
            },
            "v05_state": {
                "path": (
                    "research_artifacts/"
                    "gold_session_behaviour_v3_state_v05.json"
                ),
                "state_hash": V05_STATE_HASH,
                "file_sha256": V05_STATE_FILE_HASH,
            },
            "m5_pre_result": {
                "path": (
                    "research_manifests/"
                    "gold_session_behaviour_v3_m5_amendment_a_v01.json"
                ),
                "manifest_hash": M5_PRE_RESULT_MANIFEST_HASH,
                "file_sha256": M5_PRE_RESULT_MANIFEST_FILE_HASH,
            },
            "m5_result": {
                "path": (
                    "research_artifacts/"
                    "gold_session_behaviour_v3_m5_stability_v01/"
                    "stability_results.json"
                ),
                "m5_hash": M5_RESULT_HASH,
                "file_sha256": M5_RESULT_FILE_HASH,
            },
            "m5_result_manifest": {
                "path": (
                    "research_artifacts/"
                    "gold_session_behaviour_v3_m5_stability_v01/"
                    "manifest.json"
                ),
                "manifest_hash": M5_RESULT_MANIFEST_HASH,
                "file_sha256": M5_RESULT_MANIFEST_FILE_HASH,
            },
            "m5_independent_validation": {
                "path": (
                    "research_artifacts/"
                    "gold_session_behaviour_v3_m5_validation_v01.json"
                ),
                "validation_hash": M5_VALIDATION_HASH,
                "file_sha256": M5_VALIDATION_FILE_HASH,
            },
        },
        "candidate_registry": candidates,
        "forward_protocol": protocol,
        "protocol_fingerprint": protocol_fingerprint(),
        "implementation_freeze": {
            "m6a_protocol_version": M6A_PROTOCOL_VERSION,
            "m6a_audit_version": M6A_AUDIT_VERSION,
            "m6a_module_path": (
                "backend/src/gold_intel/analytics/"
                "session_behaviour_v3_m6a.py"
            ),
            "m6a_module_sha256": M6A_MODULE_HASH,
            "m6a_audit_tool_path": (
                "backend/tools/audit_gold_session_behaviour_v3_m6a.py"
            ),
            "m6a_audit_tool_sha256": M6A_AUDIT_TOOL_HASH,
            "m6a_test_path": (
                "backend/tests/unit/test_session_behaviour_v3_m6a.py"
            ),
            "m6a_test_sha256": M6A_TEST_HASH,
            "amendment_b_path": "GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_B.md",
            "amendment_b_sha256": AMENDMENT_B_HASH,
            "preresult_tests": {
                "passed": 5,
                "failed": 0,
            },
            "preresult_ruff": "PASS",
        },
        "metadata_audit_boundary": {
            "database_transaction_read_only_required": True,
            "metadata_sql_guard_required": True,
            "market_or_macro_value_columns_permitted": False,
            "candidate_state_calculation_permitted": False,
            "session_outcome_calculation_permitted": False,
            "relationship_or_verdict_calculation_permitted": False,
            "permitted_forward_information": [
                "source identifiers",
                "timestamps",
                "counts",
                "quality flag counts",
                "file sizes and hashes",
                "sealed manifest metadata",
            ],
        },
        "research_boundary_at_freeze": {
            "calendar_2025_values_opened_by_v3_m6": False,
            "calendar_2026_values_opened_by_v3_m6": False,
            "candidate_states_or_outcomes_calculated": False,
            "cot_used_as_pass_gate": False,
            "execution_variants": 0,
            "new_or_repaired_candidates": 0,
            "rejected_candidates_or_zn_rules_reopened": False,
            "trades_or_returns": 0,
        },
        "validation_gates": [
            "V05 state and every M5 predecessor seal match.",
            "Exactly the two M5-shortlisted candidates are present.",
            "Candidate sessions, fields, source series, transforms, conditions, complements, exclusions, and directions are unchanged.",
            "Forward segments and their reporting order are fixed.",
            "Support, effect, interval, median, multiplicity, and symmetric verdict gates are fixed.",
            "Missing-data and prospective anti-backfill policies are fixed.",
            "The implementation, audit SQL surface, Amendment B, and tests are hash-sealed before metadata access.",
            "The freeze operation reads no forward metadata, market values, feature states, or outcomes.",
        ],
        "verdict": "PASS_V3_MILESTONE_6A_PRE_RESULT_PROTOCOL_FREEZE",
        "mandatory_stop_after_m6a": True,
        "next_milestone": {
            "code": "V3_M6B_ONE_TIME_FORWARD_VALUE_EVALUATION",
            "authorized": False,
            "started": False,
        },
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _embedded_hash(manifest, "manifest_hash")
    return manifest


def _verify_inputs(paths: Mapping[str, Path]) -> None:
    contract = _load_json(paths["contract"])
    _verify_embedded_hash(contract, "manifest_hash", CONTRACT_HASH)
    if sha256_file(paths["contract"]) != CONTRACT_FILE_HASH:
        raise ValueError("V3 contract file seal mismatch")

    state = _load_json(paths["v05_state"])
    state_hash = canonical_hash(
        {
            key: value
            for key, value in state.items()
            if key not in {"generated_at", "state_hash"}
        }
    )
    if (
        state_hash != V05_STATE_HASH
        or state.get("state_hash") != V05_STATE_HASH
        or sha256_file(paths["v05_state"]) != V05_STATE_FILE_HASH
    ):
        raise ValueError("V05 state seal mismatch")
    if state["stability_result"]["m5_hash"] != M5_RESULT_HASH:
        raise ValueError("V05 does not preserve expected M5 result")

    m5_pre = _load_json(paths["m5_pre"])
    _verify_embedded_hash(
        m5_pre,
        "manifest_hash",
        M5_PRE_RESULT_MANIFEST_HASH,
    )
    if sha256_file(paths["m5_pre"]) != M5_PRE_RESULT_MANIFEST_FILE_HASH:
        raise ValueError("M5 pre-result manifest file seal mismatch")

    m5_result = _load_json(paths["m5_result"])
    _verify_embedded_hash(m5_result, "m5_hash", M5_RESULT_HASH)
    if sha256_file(paths["m5_result"]) != M5_RESULT_FILE_HASH:
        raise ValueError("M5 result file seal mismatch")
    shortlists = [
        item["candidate_code"]
        for session in ("LONDON", "NEW_YORK")
        for item in m5_result["sessions"][session]["shortlist"]
    ]
    if tuple(shortlists) != M5_SHORTLIST_CODES:
        raise ValueError("M5 shortlist differs from Amendment B")

    m5_manifest = _load_json(paths["m5_manifest"])
    _verify_embedded_hash(
        m5_manifest,
        "manifest_hash",
        M5_RESULT_MANIFEST_HASH,
    )
    if sha256_file(paths["m5_manifest"]) != M5_RESULT_MANIFEST_FILE_HASH:
        raise ValueError("M5 result manifest file seal mismatch")

    m5_validation = _load_json(paths["m5_validation"])
    _verify_embedded_hash(
        m5_validation,
        "validation_hash",
        M5_VALIDATION_HASH,
    )
    if (
        sha256_file(paths["m5_validation"]) != M5_VALIDATION_FILE_HASH
        or int(m5_validation["summary"]["failed"]) != 0
    ):
        raise ValueError("M5 independent validation seal mismatch")

    expected_files = {
        "amendment_b": AMENDMENT_B_HASH,
        "m6a_module": M6A_MODULE_HASH,
        "m6a_audit_tool": M6A_AUDIT_TOOL_HASH,
        "m6a_test": M6A_TEST_HASH,
    }
    for key, expected_hash in expected_files.items():
        actual_hash = sha256_file(paths[key])
        if actual_hash != expected_hash:
            raise ValueError(
                f"{key} seal mismatch: expected={expected_hash} "
                f"actual={actual_hash}"
            )


def _paths(root: Path) -> dict[str, Path]:
    return {
        "contract": root
        / "research_manifests"
        / "gold_session_behaviour_discovery_contract_v03.json",
        "v05_state": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_state_v05.json",
        "m5_pre": root
        / "research_manifests"
        / "gold_session_behaviour_v3_m5_amendment_a_v01.json",
        "m5_result": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m5_stability_v01"
        / "stability_results.json",
        "m5_manifest": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m5_stability_v01"
        / "manifest.json",
        "m5_validation": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m5_validation_v01.json",
        "amendment_b": root / "GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_B.md",
        "m6a_module": root
        / "backend"
        / "src"
        / "gold_intel"
        / "analytics"
        / "session_behaviour_v3_m6a.py",
        "m6a_audit_tool": root
        / "backend"
        / "tools"
        / "audit_gold_session_behaviour_v3_m6a.py",
        "m6a_test": root
        / "backend"
        / "tests"
        / "unit"
        / "test_session_behaviour_v3_m6a.py",
    }


def _verify_embedded_hash(
    document: Mapping[str, Any],
    field: str,
    expected: str,
) -> None:
    actual = _embedded_hash(document, field)
    if actual != expected or document.get(field) != expected:
        raise ValueError(
            f"Embedded hash mismatch for {field}: "
            f"expected={expected} actual={actual}"
        )


def _embedded_hash(document: Mapping[str, Any], field: str) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(payload), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _assert_within(root: Path, path: Path) -> None:
    if path != root and root not in path.parents:
        raise ValueError(f"Path must remain inside repository root: {path}")


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the Gold Session Behaviour V3 Milestone 6A "
            "Amendment-B forward protocol before metadata access."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--output",
        default=(
            "research_manifests/"
            "gold_session_behaviour_v3_m6a_amendment_b_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
