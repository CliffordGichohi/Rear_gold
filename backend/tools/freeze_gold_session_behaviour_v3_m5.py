from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m5 import (
    M5_ENGINE_VERSION,
    M5_REGISTRY_VERSION,
    candidate_registry,
    registry_fingerprint,
    stability_protocol,
)

FROZEN_AT = "2026-07-30T11:52:00Z"
CONTRACT_HASH = "79a74f81bce0b80ca6c5da6b420400479013484a4bb759684402546672fa140b"
M4_STATE_HASH = "72c1956d7276d8c3987936104212468fe7411bf432b402feeb222a0cfd928977"
M4_STATE_FILE_HASH = (
    "cf059d9a0e37d0d5f6273171d7059776782eab4046b9fce01a43d342c00c30b2"
)
M4_PRE_RESULT_MANIFEST_HASH = (
    "e024ceba35a6d3af1c384f8c66eec299aab8cdcd23b666eb9f33ac672a24fbf4"
)
M4_PRE_RESULT_MANIFEST_FILE_HASH = (
    "e11b86385c1d7594a48ef1d11fc04b65ac979c952251078528ed727f0fd91127"
)
M4_RESULT_MANIFEST_HASH = (
    "c12a71ac9decf0d2cd3f6866528809c937edab8cd6fc3e42072a5bbf8187c40c"
)
M4_RESULT_MANIFEST_FILE_HASH = (
    "3fedd5013481ea3b0f8b30063f56b3eb2c44e2280efe456ca29f7f5de436b3c8"
)
M4_DISCOVERY_HASH = (
    "c8d011c69446df3f287dae9e77a4d0e78057c8850e811299302b689ff09d6b70"
)
M4_RELATIONSHIPS_FILE_HASH = (
    "f8a4e55da149ec22f29f3455251f7c69bcf9e316b2fbad75f7a7580d8a04412b"
)
M4_VALIDATION_HASH = (
    "f34f1910fc4d18a5a41d00928c8baf1954f62404abe90e5939834677f280014a"
)
M4_VALIDATION_FILE_HASH = (
    "7b4fd3916abb55160801fdaf8463272855ea5798aa7406fc4bf2228aee7ccfa5"
)
CASE_MANIFEST_HASH = (
    "d6aad4b861d98899d6fdcc92ea53a20221434af5038a3bcb86a8b9faa1d8e7b7"
)
CASE_ARTIFACT_HASH = (
    "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
)
AMENDMENT_FILE_HASH = (
    "cb8e33fb4c0bfa383fe74ea53a923d82806ea2261f86c0f5e0e77c8adcc125c0"
)
M5_MODULE_HASH = (
    "85068a4cf67116846f9461842a680a5d2fab3199c49719c8b7aaf75d767648a1"
)
M5_TEST_HASH = (
    "9c5f76f691868012b8ed7b1dfda6c32e77406c16e8b7f078285d4d8d9a2b1b05"
)
AUTHORIZATION = (
    "Proceed to V3 Milestone 5 under Amendment A. Preserve Milestone 4’s "
    "zero-candidate verdict. Permit exactly four post-hoc hypothesis families "
    "with no development-validation credit: "
    "LONDON_ASIA_DIRECTION_REVERSAL_V0_1, "
    "LONDON_VOLATILITY_DIRECTION_V0_1, "
    "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1, and "
    "NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1. Before calculating chronology-aware "
    "results, freeze and seal their exact definitions, complementary states, "
    "support floors, annual and rolling-block stability gates, multiplicity "
    "method, ranking order, and rejection rules. Use only 2021-08-01 through "
    "2024-12-31. Do not add candidates, repair failed candidates, optimize "
    "execution, use COT as a pass gate, inspect 2025 or 2026, or reopen "
    "rejected ZN rules. Freeze zero to two internally stable candidates per "
    "session, record all negative results, complete only Milestone 5, and stop."
)


def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    if root not in output.parents:
        raise ValueError("Output path must remain inside the repository root")
    manifest = build_manifest(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, manifest)
    print(
        json.dumps(
            {
                "candidate_count": len(manifest["candidate_registry"]),
                "manifest_hash": manifest["manifest_hash"],
                "output": str(output),
                "registry_fingerprint": manifest["registry_fingerprint"],
                "verdict": manifest["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def build_manifest(root: Path) -> dict[str, Any]:
    paths = _paths(root)
    _verify_inputs(paths)
    registry = candidate_registry()
    protocol = stability_protocol()
    _validate_registry(registry, protocol)
    manifest: dict[str, Any] = {
        "manifest_version": M5_REGISTRY_VERSION,
        "milestone": "V3_M5_INTERNAL_STABILITY_AND_SHORTLIST_FREEZE",
        "recorded_at": FROZEN_AT,
        "authorization": {
            "authorized_on": "2026-07-30",
            "verbatim": AUTHORIZATION,
            "scope": "Complete only V3 Milestone 5 and stop.",
        },
        "amendment_a": {
            "path": "GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_A.md",
            "file_sha256": AMENDMENT_FILE_HASH,
            "preserves_m4_zero_candidate_verdict": True,
            "post_hoc_development_validation_credit": False,
        },
        "frozen_inputs": {
            "contract_manifest_hash": CONTRACT_HASH,
            "m4_state": {
                "path": (
                    "research_artifacts/"
                    "gold_session_behaviour_v3_state_v04.json"
                ),
                "state_hash": M4_STATE_HASH,
                "file_sha256": M4_STATE_FILE_HASH,
            },
            "m4_pre_result_manifest_hash": M4_PRE_RESULT_MANIFEST_HASH,
            "m4_result_manifest_hash": M4_RESULT_MANIFEST_HASH,
            "m4_discovery_hash": M4_DISCOVERY_HASH,
            "m4_independent_validation_hash": M4_VALIDATION_HASH,
            "case_matrix": {
                "manifest_hash": CASE_MANIFEST_HASH,
                "artifact_path": (
                    "research_artifacts/"
                    "gold_session_behaviour_v3_case_matrix_v01/cases.jsonl.gz"
                ),
                "artifact_sha256": CASE_ARTIFACT_HASH,
                "artifact_bytes": 103_763_781,
                "case_counts": {
                    "LONDON": 833,
                    "NEW_YORK": 826,
                    "total": 1659,
                },
            },
        },
        "candidate_registry": registry,
        "stability_protocol": protocol,
        "registry_fingerprint": registry_fingerprint(),
        "implementation_freeze": {
            "engine_version": M5_ENGINE_VERSION,
            "module_path": (
                "backend/src/gold_intel/analytics/"
                "session_behaviour_v3_m5.py"
            ),
            "module_sha256": M5_MODULE_HASH,
            "test_path": "backend/tests/unit/test_session_behaviour_v3_m5.py",
            "test_sha256": M5_TEST_HASH,
            "preresult_tests": {
                "passed": 4,
                "failed": 0,
            },
        },
        "research_boundary_at_freeze": {
            "calendar_2025_values_opened": False,
            "calendar_2026_values_opened": False,
            "cot_used_as_pass_gate": False,
            "development_validation_credit": False,
            "execution_variants": 0,
            "rejected_zn_rules_reopened": False,
            "trades_or_returns": 0,
        },
        "validation_gates": [
            "M4 state and all M4 result seals match before chronology access.",
            "Exactly four authorized candidate families are present.",
            "Exactly two candidates are assigned to each session.",
            "Every candidate links only to its exact M4 relationship IDs.",
            "No COT feature, ZN feature, execution field, 2025 value, or 2026 value is present.",
            "The Holm family size is fixed at four even when support fails.",
            "Calendar and rolling blocks, support floors, gates, ranking, and rejection rules are frozen.",
            "The engine and tests pass and their hashes are sealed.",
            "No development case chronology or outcome is deserialized by this freeze operation.",
        ],
        "verdict": "PASS_V3_MILESTONE_5_PRE_RESULT_FREEZE",
        "mandatory_stop_after_m5": True,
        "next_milestone": {
            "code": "V3_M6_FORWARD_EVALUATION",
            "authorized": False,
            "started": False,
        },
        "manifest_hash": "",
    }
    manifest["manifest_hash"] = _embedded_hash(manifest, "manifest_hash")
    return manifest


def _verify_inputs(paths: dict[str, Path]) -> None:
    contract = _load_json(paths["contract"])
    _verify_embedded_hash(contract, "manifest_hash", CONTRACT_HASH)
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
        raise ValueError("M4 state seal mismatch")
    m4_pre = _load_json(paths["m4_pre"])
    _verify_embedded_hash(
        m4_pre,
        "manifest_hash",
        M4_PRE_RESULT_MANIFEST_HASH,
    )
    if sha256_file(paths["m4_pre"]) != M4_PRE_RESULT_MANIFEST_FILE_HASH:
        raise ValueError("M4 pre-result manifest file seal mismatch")
    result_manifest = _load_json(paths["m4_result_manifest"])
    _verify_embedded_hash(
        result_manifest,
        "manifest_hash",
        M4_RESULT_MANIFEST_HASH,
    )
    if (
        sha256_file(paths["m4_result_manifest"])
        != M4_RESULT_MANIFEST_FILE_HASH
    ):
        raise ValueError("M4 result manifest file seal mismatch")
    relationships = _load_json(paths["m4_relationships"])
    _verify_embedded_hash(relationships, "discovery_hash", M4_DISCOVERY_HASH)
    if sha256_file(paths["m4_relationships"]) != M4_RELATIONSHIPS_FILE_HASH:
        raise ValueError("M4 relationship file seal mismatch")
    validation = _load_json(paths["m4_validation"])
    _verify_embedded_hash(validation, "validation_hash", M4_VALIDATION_HASH)
    if (
        sha256_file(paths["m4_validation"]) != M4_VALIDATION_FILE_HASH
        or validation["summary"]["failed"] != 0
    ):
        raise ValueError("M4 independent-validation seal mismatch")
    case_manifest = _load_json(paths["case_manifest"])
    _verify_embedded_hash(case_manifest, "manifest_hash", CASE_MANIFEST_HASH)
    if (
        sha256_file(paths["cases"]) != CASE_ARTIFACT_HASH
        or paths["cases"].stat().st_size != 103_763_781
    ):
        raise ValueError("Development case matrix seal mismatch")
    expected_files = {
        "amendment": AMENDMENT_FILE_HASH,
        "m5_module": M5_MODULE_HASH,
        "m5_test": M5_TEST_HASH,
    }
    for name, expected in expected_files.items():
        actual = sha256_file(paths[name])
        if actual != expected:
            raise ValueError(
                f"{name} seal mismatch: expected={expected} actual={actual}"
            )


def _validate_registry(
    registry: list[dict[str, Any]],
    protocol: dict[str, Any],
) -> None:
    expected_codes = [
        "LONDON_ASIA_DIRECTION_REVERSAL_V0_1",
        "LONDON_VOLATILITY_DIRECTION_V0_1",
        "NEW_YORK_FINANCIAL_STRESS_DIRECTION_V0_1",
        "NEW_YORK_SOFR_CUT_2Y_FALLING_V0_1",
    ]
    if [item["candidate_code"] for item in registry] != expected_codes:
        raise ValueError("Authorized M5 candidate IDs differ")
    counts = {
        session: sum(item["session_code"] == session for item in registry)
        for session in ("LONDON", "NEW_YORK")
    }
    if counts != {"LONDON": 2, "NEW_YORK": 2}:
        raise ValueError("M5 must have exactly two candidates per session")
    serialized = json.dumps(json_ready(registry), sort_keys=True).upper()
    if "POSITION_" in serialized or "COT_" in serialized or "ZN_" in serialized:
        raise ValueError("COT/positioning or ZN entered the M5 candidate registry")
    if protocol["multiplicity"]["family_size_fixed"] != 4:
        raise ValueError("M5 multiplicity family size must remain four")
    if protocol["shortlist"]["maximum_per_session"] != 2:
        raise ValueError("M5 shortlist cap must remain two per session")


def _verify_embedded_hash(
    document: dict[str, Any],
    field: str,
    expected: str,
) -> None:
    supplied = str(document.get(field, ""))
    calculated = _embedded_hash(document, field)
    if supplied != expected or calculated != supplied:
        raise ValueError(
            f"Embedded {field} mismatch: expected={expected} "
            f"supplied={supplied} calculated={calculated}"
        )


def _embedded_hash(document: dict[str, Any], field: str) -> str:
    return canonical_hash(
        {key: value for key, value in document.items() if key != field}
    )


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, document: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(json_ready(document), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _paths(root: Path) -> dict[str, Path]:
    m4_dir = (
        root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m4_discovery_v01"
    )
    return {
        "contract": (
            root
            / "research_manifests"
            / "gold_session_behaviour_discovery_contract_v03.json"
        ),
        "m4_state": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_state_v04.json"
        ),
        "m4_pre": (
            root
            / "research_manifests"
            / "gold_session_behaviour_v3_m4_discovery_v01.json"
        ),
        "m4_result_manifest": m4_dir / "manifest.json",
        "m4_relationships": m4_dir / "relationships.json",
        "m4_validation": (
            root
            / "research_artifacts"
            / "gold_session_behaviour_v3_m4_validation_v01.json"
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
        "amendment": root / "GOLD_SESSION_BEHAVIOUR_V3_AMENDMENT_A.md",
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
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze Amendment A and the exact V3 Milestone 5 post-hoc "
            "candidate stability protocol without reading case chronology."
        )
    )
    parser.add_argument("--root", required=True)
    parser.add_argument(
        "--output",
        default=(
            "research_manifests/"
            "gold_session_behaviour_v3_m5_amendment_a_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    main()
