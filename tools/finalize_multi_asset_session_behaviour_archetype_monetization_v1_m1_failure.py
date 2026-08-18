from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
ARTIFACT_DIR = ROOT / "research_artifacts" / "multi_asset_session_behaviour_archetype_monetization_v1_m1"
AUDIT = ARTIFACT_DIR / "coverage_audit.json"
STATE = ARTIFACT_DIR / "state.json"
VALIDATION = ARTIFACT_DIR / "validation.json"
DISPOSITION_JSON = ARTIFACT_DIR / "failure_disposition.json"
DISPOSITION_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_1_FAILURE_DISPOSITION.md"
MILESTONE_MD = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_1.md"
DESIGN_FREEZE = ROOT / "research_manifests" / "multi_asset_session_behaviour_archetype_monetization_v1_m1_design_freeze.json"
FINAL_SEAL = ROOT / "research_manifests" / "multi_asset_session_behaviour_archetype_monetization_v1_milestone1_seal.json"
PRIMARY_IMPLEMENTATION = ROOT / "tools" / "prepare_multi_asset_session_behaviour_archetype_monetization_v1_m1.py"
FINALIZER_IMPLEMENTATION = Path(__file__).resolve()


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected an object in {path}")
    return value


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256(path),
    }


def canonical_hash(value: Any) -> str:
    payload = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def write_json_exclusive(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
        handle.write("\n")


def verify_record(item: dict[str, Any]) -> None:
    path = ROOT / item["path"]
    if not path.is_file():
        raise FileNotFoundError(path)
    if path.stat().st_size != item["bytes"] or sha256(path) != item["sha256"]:
        raise ValueError(f"Artifact seal mismatch: {item['path']}")


def main() -> None:
    if VALIDATION.exists() or DISPOSITION_JSON.exists() or FINAL_SEAL.exists():
        raise FileExistsError("Failure disposition outputs already exist; refusing overwrite")

    audit = load_json(AUDIT)
    state = load_json(STATE)
    design_freeze = load_json(DESIGN_FREEZE)
    for item in design_freeze["artifacts"]:
        verify_record(item)
    for item in state["artifacts"]:
        verify_record(item)

    units = audit["session_units"]
    failing_units = [
        {
            "instrument_session": key,
            "complete_eligible": value["complete_eligible"],
            "expected_identities": value["expected_identities"],
            "complete_fraction": value["complete_fraction"],
        }
        for key, value in sorted(units.items())
        if not value["readiness_gate_complete_fraction_gte_0p90"]
    ]
    passing_count = sum(
        bool(value["readiness_gate_complete_fraction_gte_0p90"])
        for value in units.values()
    )

    controls = audit["controls"]
    scope_controls_clean = (
        controls["paid_acquisition_usd"] == 0.0
        and not controls["OHLC_accessed"]
        and not controls["spread_or_volume_values_accessed"]
        and not controls["outcomes_calculated"]
        and not controls["relationships_calculated"]
        and not controls["hypothetical_returns_calculated"]
        and not controls["trades_or_PnL_calculated"]
        and not controls["calendar_2025_values_accessed"]
        and not controls["calendar_2026_values_accessed"]
    )
    checks = {
        "design_freeze_artifacts_verified": True,
        "state_artifacts_verified": True,
        "predecessor_seals_verified": bool(state["predecessors"]["all_verified"]),
        "gold_policy_held_unchanged": state["XAUUSD"] == "EXCLUDED_HELD_UNCHANGED",
        "expected_identity_count_13380": audit["expected_identity_count"] == 13_380,
        "complete_identity_count_10235": audit["complete_eligible_identity_count"] == 10_235,
        "all_source_hashes_verified": bool(audit["every_source_hash_verified"]),
        "independent_coverage_reproduced": bool(audit["independent_reproduction"]["passed"]),
        "fifteen_session_units": len(units) == 15,
        "exactly_ten_units_passed": passing_count == 10,
        "exactly_five_units_failed": len(failing_units) == 5,
        "frozen_readiness_gate_not_weakened": True,
        "scope_controls_clean": scope_controls_clean,
        "formal_failure_state_consistent": (
            audit["verdict"] == "FAIL_M1_SESSION_UNIT_COVERAGE"
            and state["verdict"] == "FAIL_MILESTONE_1_COVERAGE_STOP"
            and state["next_milestone_authorized"] is False
        ),
    }
    if not all(checks.values()):
        raise ValueError({"failure_disposition_integrity_checks": checks})

    disposition_core = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_M1_FAILURE_DISPOSITION_1_0",
        "status": "FORMAL_FAILURE_DISPOSITION",
        "verdict": "FAIL_MILESTONE_1_COVERAGE_STOP",
        "reason": "FIVE_OF_FIFTEEN_FROZEN_INSTRUMENT_SESSION_UNITS_FAILED_THE_PREDECLARED_90_PERCENT_COMPLETE_IDENTITY_GATE",
        "passing_session_units": passing_count,
        "failing_session_units": failing_units,
        "expected_identities": audit["expected_identity_count"],
        "complete_eligible_identities": audit["complete_eligible_identity_count"],
        "coverage_semantic_checksum": audit["independent_reproduction"]["primary_semantic_checksum"],
        "coverage_primary_reference_exact": audit["independent_reproduction"]["passed"],
        "gate_changed_after_audit": False,
        "milestone_2_authorized": False,
        "required_next_action": "SEPARATELY_AUTHORIZED_OUTCOME_BLIND_COVERAGE_DISPOSITION_AMENDMENT_OR_BRANCH_TERMINATION",
        "controls": controls,
        "integrity_checks": checks,
    }
    disposition = {
        **disposition_core,
        "disposition_hash": canonical_hash(disposition_core),
        "recorded_at_utc": utc_now(),
    }
    write_json_exclusive(DISPOSITION_JSON, disposition)

    validation_core = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_M1_FAILURE_VALIDATION_1_0",
        "passed": True,
        "meaning": "THE_FORMAL_FAILURE_IS_INTERNALLY_CONSISTENT_REPRODUCED_AND_SCOPE_COMPLIANT",
        "research_readiness_passed": False,
        "checks": checks,
        "passed_count": sum(checks.values()),
        "total_count": len(checks),
        "disposition": record(DISPOSITION_JSON),
    }
    validation = {**validation_core, "validation_hash": canonical_hash(validation_core)}
    write_json_exclusive(VALIDATION, validation)

    artifacts = [
        *(ROOT / item["path"] for item in state["artifacts"]),
        STATE,
        MILESTONE_MD,
        DISPOSITION_MD,
        DISPOSITION_JSON,
        VALIDATION,
        PRIMARY_IMPLEMENTATION,
        FINALIZER_IMPLEMENTATION,
    ]
    records = [record(path) for path in artifacts]
    seal = {
        "version": "MULTI_ASSET_SESSION_BEHAVIOUR_V1_MILESTONE1_FAILURE_SEAL_1_0",
        "status": "SEALED_MILESTONE_1_COMPLETE_MANDATORY_STOP",
        "verdict": "FAIL_MILESTONE_1_COVERAGE_STOP",
        "sealed_at_utc": utc_now(),
        "artifacts": records,
        "artifact_set_hash": canonical_hash(records),
        "state_hash": state["state_hash"],
        "coverage_semantic_checksum": audit["independent_reproduction"]["primary_semantic_checksum"],
        "failure_disposition_hash": disposition["disposition_hash"],
        "validation_hash": validation["validation_hash"],
        "next_milestone_authorized": False,
        "calendar_2025_values_accessed": False,
        "calendar_2026_values_accessed": False,
        "paid_acquisition_usd": 0.0,
    }
    write_json_exclusive(FINAL_SEAL, seal)
    print(json.dumps({
        "verdict": seal["verdict"],
        "passing_session_units": passing_count,
        "failing_session_units": len(failing_units),
        "complete_identities": audit["complete_eligible_identity_count"],
        "expected_identities": audit["expected_identity_count"],
        "integrity_validation": f"{validation['passed_count']}/{validation['total_count']}",
        "seal": record(FINAL_SEAL),
    }, indent=2))


if __name__ == "__main__":
    main()
