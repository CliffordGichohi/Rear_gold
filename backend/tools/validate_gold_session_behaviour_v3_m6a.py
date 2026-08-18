from __future__ import annotations

import argparse
import asyncio
import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from audit_gold_session_behaviour_v3_m6a import (
    SQL_STATEMENTS,
    build_audit_report,
    collect_metadata_snapshot,
    validate_audit_report,
)

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.analytics.casebook_discovery_v3 import assert_metadata_only_sql
from gold_intel.analytics.session_behaviour_v3 import sha256_file
from gold_intel.analytics.session_behaviour_v3_m6a import (
    M5_SHORTLIST_CODES,
    protocol_fingerprint,
    validate_forward_protocol,
)

VALIDATION_VERSION = (
    "GOLD_SESSION_BEHAVIOUR_V3_M6A_INDEPENDENT_VALIDATION_V0_1"
)
PRE_MANIFEST_HASH = (
    "218564c0459f711f08c32529b095e06bfd47a092dbd1d5bfa3f6d483afae133d"
)
PRE_MANIFEST_FILE_HASH = (
    "6665c5ef61df449fde035e9b6404908a00141640d52f9fa526e226f5bfe14a4c"
)
READINESS_AUDIT_HASH = (
    "38fff196a4ef6ca45c8d545506531dbddfdf0b7b17113248a4227e6be736cd4d"
)
READINESS_AUDIT_FILE_HASH = (
    "11b2030b47188d2faba1f16d519a62b5dbd143e6d1fffc7676622047e61bfaed"
)
RESULT_MANIFEST_HASH = (
    "567087285b78edc79dab9e7f1ff83fb5dd998c2c6f74f27c5068ff8132e42c2c"
)
RESULT_MANIFEST_FILE_HASH = (
    "f3e9b48e7a5535e5f6aed854358a5b2ddaa5b863c29d9a48f992ea8aaf394da5"
)
SEMANTIC_VALIDATION_HASH = (
    "b58a5a22ff64fb3d41a72c75f1f8fe18566ac647479ba3256f10b9947eedf2b0"
)
SEMANTIC_VALIDATION_FILE_HASH = (
    "c6d39b8739c606e3f195865f7dafe12d35b402137a8b8a14aaf141c9017a3ecb"
)


async def main() -> None:
    args = _parser().parse_args()
    root = Path(args.root).resolve()
    output = (root / args.output).resolve()
    _assert_within(root, output)
    if output.exists():
        raise FileExistsError(
            "M6A independent validation already exists; refusing to overwrite"
        )
    validation = await validate(root)
    output.parent.mkdir(parents=True, exist_ok=True)
    _write_json(output, validation)
    print(
        json.dumps(
            {
                "failed": validation["summary"]["failed"],
                "output": str(output),
                "passed": validation["summary"]["passed"],
                "validation_hash": validation["validation_hash"],
                "verdict": validation["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


async def validate(root: Path) -> dict[str, Any]:
    paths = _paths(root)
    pre_manifest = _load_json(paths["pre_manifest"])
    result = _load_json(paths["readiness_audit"])
    result_manifest = _load_json(paths["result_manifest"])
    semantic = _load_json(paths["semantic_validation"])
    checks: list[dict[str, Any]] = []

    checks.append(
        _check(
            "PRE_RESULT_MANIFEST_EMBEDDED_AND_FILE_SEALS",
            _embedded_hash(pre_manifest, "manifest_hash")
            == PRE_MANIFEST_HASH
            == pre_manifest["manifest_hash"]
            and sha256_file(paths["pre_manifest"])
            == PRE_MANIFEST_FILE_HASH,
        )
    )
    checks.append(
        _check(
            "READINESS_AUDIT_EMBEDDED_AND_FILE_SEALS",
            _embedded_hash(
                result,
                "readiness_audit_hash",
                excluded=("generated_at",),
            )
            == READINESS_AUDIT_HASH
            == result["readiness_audit_hash"]
            and sha256_file(paths["readiness_audit"])
            == READINESS_AUDIT_FILE_HASH,
        )
    )
    checks.append(
        _check(
            "RESULT_MANIFEST_EMBEDDED_AND_FILE_SEALS",
            _embedded_hash(result_manifest, "manifest_hash")
            == RESULT_MANIFEST_HASH
            == result_manifest["manifest_hash"]
            and sha256_file(paths["result_manifest"])
            == RESULT_MANIFEST_FILE_HASH,
        )
    )
    checks.append(
        _check(
            "BUILD_SEMANTIC_VALIDATION_EMBEDDED_AND_FILE_SEALS",
            _embedded_hash(semantic, "validation_hash")
            == SEMANTIC_VALIDATION_HASH
            == semantic["validation_hash"]
            and sha256_file(paths["semantic_validation"])
            == SEMANTIC_VALIDATION_FILE_HASH
            and int(semantic["summary"]["failed"]) == 0,
        )
    )
    checks.append(
        _check(
            "PROTOCOL_FINGERPRINT_AND_IMPLEMENTATION_VALID",
            pre_manifest["protocol_fingerprint"] == protocol_fingerprint()
            and validate_forward_protocol() == [],
        )
    )
    checks.append(
        _check(
            "EXACT_M5_SHORTLIST_PRESERVED",
            tuple(
                item["candidate_code"]
                for item in pre_manifest["candidate_registry"]
            )
            == M5_SHORTLIST_CODES,
        )
    )
    assert_metadata_only_sql(SQL_STATEMENTS)
    checks.append(
        _check(
            "INDEPENDENT_SQL_METADATA_GUARD_PASS",
            True,
            sql_statement_count=len(SQL_STATEMENTS),
        )
    )

    boundary = result["audit_boundary"]
    checks.extend(
        [
            _check(
                "NO_2025_VALUE_STATE_OR_OUTCOME_ACCESS",
                not boundary["calendar_2025_market_or_macro_values_read"]
                and not boundary[
                    "calendar_2025_candidate_states_or_outcomes_calculated"
                ],
            ),
            _check(
                "NO_2026_VALUE_STATE_OR_OUTCOME_ACCESS",
                not boundary["calendar_2026_market_or_macro_values_read"]
                and not boundary[
                    "calendar_2026_candidate_states_or_outcomes_calculated"
                ],
            ),
            _check(
                "NO_FORWARD_INFERENCE_OR_EXECUTION",
                not boundary[
                    "forward_relationships_effects_p_values_or_verdicts_calculated"
                ]
                and int(boundary["execution_variants"]) == 0
                and int(boundary["trades_or_returns"]) == 0,
            ),
            _check(
                "NO_COT_GATE_OR_REJECTED_RULE_REOPEN",
                not boundary["cot_used_as_pass_gate"]
                and not boundary[
                    "rejected_candidates_or_zn_rules_reopened"
                ],
            ),
        ]
    )

    metadata_snapshot = await collect_metadata_snapshot()
    rebuilt = build_audit_report(
        metadata_snapshot=metadata_snapshot,
        pre_manifest=pre_manifest,
        pre_manifest_path=paths["pre_manifest"],
        generated_at=str(result["generated_at"]),
    )
    checks.append(
        _check(
            "INDEPENDENT_EXACT_READINESS_AUDIT_REPRODUCTION",
            rebuilt == result,
            rebuilt_hash=rebuilt["readiness_audit_hash"],
            sealed_hash=result["readiness_audit_hash"],
        )
    )
    independent_semantic = validate_audit_report(
        rebuilt,
        pre_manifest=pre_manifest,
    )
    checks.append(
        _check(
            "INDEPENDENT_SEMANTIC_VALIDATION_PASS",
            all(item["status"] == "PASS" for item in independent_semantic),
            checks=len(independent_semantic),
        )
    )

    assessments = [
        item
        for code in ("EXPOSED_CALENDAR_2025", "LOCKED_2026_YTD")
        for item in rebuilt["partitions"][code]["candidate_assessments"]
    ]
    checks.extend(
        [
            _check(
                "FOUR_CANDIDATE_PARTITION_ASSESSMENTS_RECORDED",
                len(assessments) == 4,
            ),
            _check(
                "ALL_HISTORICAL_METADATA_GATES_PASS",
                all(item["metadata_ready"] for item in assessments),
            ),
            _check(
                "NO_FORWARD_STATE_OR_OUTCOME_SUPPORT_OBSERVED",
                all(
                    not item["exact_condition_cases_known"]
                    and not item["exact_complement_cases_known"]
                    and not item["candidate_states_calculated"]
                    and not item["outcomes_calculated"]
                    for item in assessments
                ),
            ),
            _check(
                "POWER_USES_ONLY_FROZEN_PLANNING_ASSUMPTIONS",
                all(
                    not item["power_audit"][
                        "forward_values_or_candidate_states_used"
                    ]
                    and item["power_audit"]["planned_effect_pp"] == 7.5
                    for item in assessments
                ),
            ),
            _check(
                "PROSPECTIVE_LEDGER_REMAINS_EMPTY",
                rebuilt["prospective_tracking"][
                    "decision_records_created_by_m6a"
                ]
                == 0
                and not rebuilt["prospective_tracking"][
                    "market_values_or_outcomes_read"
                ],
            ),
            _check(
                "M6B_UNAUTHORIZED_AND_MANDATORY_STOP",
                not rebuilt["readiness_decision"]["m6b_authorized"]
                and rebuilt["mandatory_stop"]["stop_after_m6a"]
                and not rebuilt["mandatory_stop"][
                    "next_milestone_authorized"
                ],
            ),
        ]
    )

    failed = [item for item in checks if item["status"] != "PASS"]
    validation: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "milestone": "V3_M6A_FORWARD_PROTOCOL_AND_METADATA_READINESS",
        "generated_at": result["generated_at"],
        "pre_result_manifest_hash": PRE_MANIFEST_HASH,
        "readiness_audit_hash": READINESS_AUDIT_HASH,
        "result_manifest_hash": RESULT_MANIFEST_HASH,
        "records_read_back": {
            "candidate_partition_assessments": len(assessments),
            "metadata_only_sql_statements": len(SQL_STATEMENTS),
            "forward_market_or_macro_values": 0,
            "candidate_states": 0,
            "session_outcomes": 0,
            "relationships": 0,
        },
        "checks": checks,
        "summary": {
            "total": len(checks),
            "passed": len(checks) - len(failed),
            "failed": len(failed),
        },
        "verdict": (
            "PASS_V3_MILESTONE_6A_INDEPENDENT_VALIDATION_MANDATORY_STOP"
            if not failed
            else "FAIL_V3_MILESTONE_6A_INDEPENDENT_VALIDATION"
        ),
        "validation_hash": "",
    }
    validation["validation_hash"] = _embedded_hash(
        validation,
        "validation_hash",
        excluded=("generated_at",),
    )
    if failed:
        raise ValueError(f"M6A independent validation failed: {failed}")
    return validation


def _check(code: str, passed: bool, **evidence: Any) -> dict[str, Any]:
    return {
        "code": code,
        "status": "PASS" if passed else "FAIL",
        "evidence": evidence,
    }


def _embedded_hash(
    document: Mapping[str, Any],
    field: str,
    *,
    excluded: Sequence[str] = (),
) -> str:
    excluded_keys = set(excluded)
    return canonical_hash(
        {
            key: value
            for key, value in document.items()
            if key != field and key not in excluded_keys
        }
    )


def _paths(root: Path) -> dict[str, Path]:
    return {
        "pre_manifest": root
        / "research_manifests"
        / "gold_session_behaviour_v3_m6a_amendment_b_v01.json",
        "readiness_audit": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m6a_readiness_v01"
        / "readiness_audit.json",
        "result_manifest": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m6a_readiness_v01"
        / "manifest.json",
        "semantic_validation": root
        / "research_artifacts"
        / "gold_session_behaviour_v3_m6a_readiness_v01"
        / "semantic_validation.json",
    }


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
            "Independently reproduce the V3 M6A candidate-specific "
            "metadata-only readiness audit."
        )
    )
    parser.add_argument("--root", default=".")
    parser.add_argument(
        "--output",
        default=(
            "research_artifacts/"
            "gold_session_behaviour_v3_m6a_validation_v01.json"
        ),
    )
    return parser


if __name__ == "__main__":
    asyncio.run(main())
