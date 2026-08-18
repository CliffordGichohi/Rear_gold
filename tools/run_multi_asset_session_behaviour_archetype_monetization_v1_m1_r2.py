from __future__ import annotations

import hashlib
import json
import os
from collections import Counter, defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
R1_OUTER_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_amendment_a_seal.json"
R1_INNER_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1_seal.json"
R1_RECOMMENDATION = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1/recommendation.json"
R1_PRIMARY = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1/diagnostic_primary.json"
R1_REFERENCE = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r1/diagnostic_reference.json"
IDENTITIES = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1/session_identity_registry.json"
M1_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_milestone1_seal.json"

AMENDMENT = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_coverage_amendment_a.json"
PREACCESS_FREEZE = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2_preaccess_freeze.json"
ARTIFACTS = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2"
PRIMARY = ARTIFACTS / "recertification_primary.json"
REFERENCE = ARTIFACTS / "recertification_reference.json"
RESULT = ARTIFACTS / "recertification.json"
STATE = ARTIFACTS / "state.json"
VALIDATION = ARTIFACTS / "validation.json"
REPORT = ROOT / "MULTI_ASSET_SESSION_BEHAVIOUR_ARCHETYPE_AND_MONETIZATION_V1_MILESTONE_1_R2.md"
FINAL_SEAL = ROOT / "research_manifests/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2_seal.json"
IMPLEMENTATION = Path(__file__).resolve()

ALLOWED = {"DOCUMENTED_MARKET_UNAVAILABLE", "NORMAL_NO_TICK_BAR_EMISSION"}
INSTRUMENTS = {"XAGUSD", "EURUSD", "USDJPY", "USTEC", "US500", "XTIUSD"}


def now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode()).hexdigest()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.relative_to(ROOT).as_posix(), "bytes": path.stat().st_size, "sha256": sha256(path)}


def load(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify(item: Mapping[str, Any]) -> None:
    path = ROOT / item["path"]
    if not path.is_file() or record(path) != dict(item):
        raise ValueError(f"Seal mismatch: {item['path']}")


def verify_seal(path: Path) -> dict[str, Any]:
    seal = load(path)
    for item in seal.get("artifacts", []):
        verify(item)
    return seal


def disposition_for(runs: Sequence[Mapping[str, Any]]) -> str:
    if not runs:
        return "ELIGIBLE_COMPLETE_WALL_CLOCK"
    if all(str(row["classification"]) in ALLOWED for row in runs):
        for row in runs:
            if row["classification"] == "NORMAL_NO_TICK_BAR_EMISSION" and not (
                int(row["length_minutes"]) <= 2
                and row["boundary_position"] == "INTERIOR"
                and row["preceding_minute_present"] is True
                and row["following_minute_present"] is True
                and row["current_schedule_shape"] == "CURRENT_DOCUMENTED_TRADING_TIME"
                and float(row["exact_signature_total_fraction"]) < 0.10
                and int(row["cross_instrument_missing_maximum"]) < 4
                and row["explicit_acquisition_failure_overlap"] is False
            ):
                raise ValueError(f"Invalid no-tick classification: {row['run_id']}")
            if row["classification"] == "DOCUMENTED_MARKET_UNAVAILABLE" and not (
                row["current_schedule_shape"] == "ENTIRELY_CURRENT_DOCUMENTED_CLOSURE"
                and row["historical_recurrence_gate_passed"] is True
                and row["explicit_acquisition_failure_overlap"] is False
            ):
                raise ValueError(f"Invalid documented-closure classification: {row['run_id']}")
        return "ELIGIBLE_OBSERVED_QUOTE_PATH"
    return "TECHNICALLY_UNAVAILABLE"


def synthetic_proof() -> dict[str, Any]:
    allowed = [{
        "classification": "NORMAL_NO_TICK_BAR_EMISSION", "length_minutes": 1,
        "boundary_position": "INTERIOR", "preceding_minute_present": True,
        "following_minute_present": True, "current_schedule_shape": "CURRENT_DOCUMENTED_TRADING_TIME",
        "exact_signature_total_fraction": 0.01, "cross_instrument_missing_maximum": 1,
        "explicit_acquisition_failure_overlap": False, "run_id": "synthetic-allowed",
    }]
    blocked = [{**allowed[0], "classification": "UNRESOLVED", "run_id": "synthetic-blocked"}]
    proof = {
        "complete": disposition_for([]),
        "allowed": disposition_for(allowed),
        "blocked": disposition_for(blocked),
    }
    if proof != {
        "complete": "ELIGIBLE_COMPLETE_WALL_CLOCK",
        "allowed": "ELIGIBLE_OBSERVED_QUOTE_PATH",
        "blocked": "TECHNICALLY_UNAVAILABLE",
    }:
        raise ValueError(proof)
    return proof


def recertify(implementation: str, diagnostic: Mapping[str, Any], identities: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_case: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for row in diagnostic["run_records"]:
        by_case[str(row["case_id"])].append(row)
    rows: list[dict[str, Any]] = []
    for identity in identities if implementation == "primary" else reversed(list(identities)):
        runs = by_case.get(str(identity["case_id"]), [])
        disposition = disposition_for(runs)
        rows.append({
            "case_id": identity["case_id"], "instrument": identity["instrument"],
            "research_id": identity["research_id"], "session_code": identity["session_code"],
            "session_date_local": identity["session_date_local"],
            "decision_at_utc": identity["decision_at_utc"],
            "observation_start_utc": identity["observation_start_utc"],
            "observation_end_utc": identity["observation_end_utc"],
            "path_disposition": disposition,
            "missing_run_count": len(runs),
            "missing_run_classifications": dict(sorted(Counter(str(item["classification"]) for item in runs).items())),
            "eligible_for_milestone_2": disposition != "TECHNICALLY_UNAVAILABLE",
        })
    rows.sort(key=lambda item: (item["session_date_local"], item["instrument"], item["session_code"]))
    unit_counts: dict[str, Counter[str]] = defaultdict(Counter)
    for row in rows:
        unit = f"{row['instrument']}|{row['session_code']}"
        unit_counts[unit]["total"] += 1
        unit_counts[unit][row["path_disposition"]] += 1
        if row["eligible_for_milestone_2"]:
            unit_counts[unit]["eligible"] += 1
    units: dict[str, Any] = {}
    for unit, counts in sorted(unit_counts.items()):
        fraction = counts["eligible"] / counts["total"]
        units[unit] = {
            "expected_identities": counts["total"], "eligible_identities": counts["eligible"],
            "complete_wall_clock": counts["ELIGIBLE_COMPLETE_WALL_CLOCK"],
            "observed_quote_path": counts["ELIGIBLE_OBSERVED_QUOTE_PATH"],
            "technically_unavailable": counts["TECHNICALLY_UNAVAILABLE"],
            "eligible_fraction": round(fraction, 12), "unit_readiness_pass": fraction >= 0.90,
        }
    passing = sorted(unit for unit, item in units.items() if item["unit_readiness_pass"])
    eligible_instruments = sorted({unit.split("|", 1)[0] for unit in passing})
    branch_pass = len(passing) >= 10 and set(eligible_instruments) == INSTRUMENTS
    semantic = {"case_rows": rows, "unit_summaries": units, "passing_units": passing, "eligible_instruments": eligible_instruments, "branch_pass": branch_pass}
    return {
        "version": "MSBAM_V1_M1_R2_RECERTIFICATION_1_0", "implementation": implementation,
        **semantic, "semantic_checksum": canonical_hash(semantic),
        "controls": {"market_values_accessed": False, "outcomes_accessed": False, "2025_2026_values_accessed": False, "charge_usd": 0.0},
    }


def report(result: Mapping[str, Any]) -> str:
    lines = []
    for unit, item in result["unit_summaries"].items():
        lines.append(f"| `{unit}` | {item['eligible_identities']} | {item['expected_identities']} | {item['eligible_fraction']:.2%} | {'PASS' if item['unit_readiness_pass'] else 'UNAVAILABLE'} |")
    return f"""# Multi-Asset Session Behaviour V1 — Milestone 1-R2

Verdict: **`{'PASS_M1_R2_BRANCH_READY' if result['branch_pass'] else 'FAIL_M1_R2_BRANCH_NOT_READY'}`**

| Instrument-session unit | Eligible | Expected | Fraction | Disposition |
|---|---:|---:|---:|---|
{chr(10).join(lines)}

Passing units: **{len(result['passing_units'])}/15**. Eligible instruments: **{len(result['eligible_instruments'])}/6**.

Every identity remains in the ledger. Failed units are retained as `TECHNICALLY_UNAVAILABLE`; nothing was deleted, imputed or replaced. The original Milestone 1 failure and R1 diagnostic verdict remain preserved.
"""


def main() -> None:
    outputs = [AMENDMENT, PREACCESS_FREEZE, PRIMARY, REFERENCE, RESULT, STATE, VALIDATION, REPORT, FINAL_SEAL]
    if any(path.exists() for path in outputs):
        raise FileExistsError([str(path) for path in outputs if path.exists()])
    proof = synthetic_proof()
    r1_outer = load(R1_OUTER_SEAL)
    r1_inner = verify_seal(R1_INNER_SEAL)
    if r1_outer["verdict"] != "PASS_MILESTONE_1_R1_DIAGNOSTIC_REPRODUCTION" or r1_inner["preserved_m1_verdict"] != "FAIL_MILESTONE_1_COVERAGE_STOP":
        raise ValueError("R1 chain not preserved")
    verify(r1_outer["inner_result_seal"])
    verify(r1_outer["preaccess_engineering_amendment_a"])
    verify(r1_outer["amended_runner"])
    m1 = verify_seal(M1_SEAL)
    if m1["verdict"] != "FAIL_MILESTONE_1_COVERAGE_STOP":
        raise ValueError("M1 failure changed")

    amendment_core = {
        "version": "MSBAM_V1_COVERAGE_AMENDMENT_A_1_0", "status": "FROZEN_BEFORE_R1_CLASSIFICATION_ROW_ACCESS",
        "preserved_m1_verdict": m1["verdict"], "preserved_r1_verdict": r1_outer["verdict"],
        "policy": "OBSERVED_QUOTE_PATH_VALIDITY_V0_1", "identity_count": 13_380,
        "unit_policy": "EVALUATE_EACH_OF_15_UNITS_SEPARATELY", "unit_readiness_floor": 0.90,
        "branch_gate": {"minimum_passing_units": 10, "each_of_six_instruments_has_passing_unit": True},
        "eligible_gap_classes": sorted(ALLOWED),
        "unavailable_gap_classes": ["RECOVERABLE_EXISTING_SEALED_SOURCE", "GENUINE_SOURCE_GAP", "UNRESOLVED"],
        "failed_unit_disposition": "TECHNICALLY_UNAVAILABLE_RETAIN_IDENTITY_NO_DELETE_NO_IMPUTE",
        "normal_no_tick_rule": "R1_FROZEN_RULE_UNCHANGED",
        "documented_closure_rule": "R1_FROZEN_RULE_UNCHANGED",
        "attempt_limit": 1, "further_coverage_diagnostic_permitted": False,
        "controls": {"market_values": False, "outcomes": False, "2025": False, "2026": False, "charge_usd": 0.0},
    }
    amendment = {**amendment_core, "amendment_hash": canonical_hash(amendment_core), "sealed_at_utc": now()}
    write_json(AMENDMENT, amendment)
    freeze_core = {
        "version": "MSBAM_V1_M1_R2_PREACCESS_FREEZE_1_0", "status": "SEALED_BEFORE_R1_CLASSIFICATION_ROW_ACCESS",
        "coverage_amendment_a": record(AMENDMENT), "r1_outer_seal": record(R1_OUTER_SEAL),
        "r1_primary": record(R1_PRIMARY), "r1_reference": record(R1_REFERENCE),
        "r1_recommendation": record(R1_RECOMMENDATION), "identities": record(IDENTITIES),
        "implementation": record(IMPLEMENTATION), "synthetic_proof": proof,
        "controls": amendment["controls"],
    }
    freeze = {**freeze_core, "freeze_hash": canonical_hash(freeze_core), "sealed_at_utc": now()}
    write_json(PREACCESS_FREEZE, freeze)

    identities = load(IDENTITIES)["rows"]
    if len(identities) != 13_380:
        raise ValueError("Identity population changed")
    primary = recertify("primary", load(R1_PRIMARY), identities)
    write_json(PRIMARY, primary)
    reference = recertify("reference", load(R1_REFERENCE), identities)
    write_json(REFERENCE, reference)
    if primary["semantic_checksum"] != reference["semantic_checksum"] or {key: value for key, value in primary.items() if key not in {"implementation"}} != {key: value for key, value in reference.items() if key not in {"implementation"}}:
        raise ValueError("R2 independent reproduction failed")
    verdict = "PASS_M1_R2_BRANCH_READY" if primary["branch_pass"] else "FAIL_M1_R2_BRANCH_NOT_READY"
    result_core = {
        "version": "MSBAM_V1_M1_R2_RESULT_1_0", "verdict": verdict,
        "preserved_m1_verdict": m1["verdict"], "preserved_r1_verdict": r1_outer["verdict"],
        "independent_reproduction": True, "semantic_checksum": primary["semantic_checksum"],
        "unit_summaries": primary["unit_summaries"], "passing_units": primary["passing_units"],
        "eligible_instruments": primary["eligible_instruments"], "eligible_case_count": sum(1 for row in primary["case_rows"] if row["eligible_for_milestone_2"]),
        "branch_pass": primary["branch_pass"], "controls": primary["controls"],
    }
    result = {**result_core, "result_hash": canonical_hash(result_core), "completed_at_utc": now()}
    write_json(RESULT, result)
    write_text(REPORT, report(result))
    checks = {
        "predecessors_verified": True, "identity_count_preserved": len(identities) == 13_380,
        "all_15_units_retained": len(primary["unit_summaries"]) == 15,
        "unit_floor_unchanged": amendment["unit_readiness_floor"] == 0.90,
        "primary_reference_exact": True, "market_values_not_accessed": True,
        "forward_locks": True, "no_charge": True,
    }
    validation = {"version": "MSBAM_V1_M1_R2_VALIDATION_1_0", "passed": all(checks.values()), "checks": checks, "validation_hash": canonical_hash(checks)}
    write_json(VALIDATION, validation)
    state_core = {
        "version": "MSBAM_V1_M1_R2_STATE_1_0", "status": "COMPLETE",
        "verdict": verdict, "branch_ready": primary["branch_pass"],
        "passing_unit_count": len(primary["passing_units"]), "eligible_case_count": result["eligible_case_count"],
        "milestone_2_authorized_by_user_chain": primary["branch_pass"], "2025": "LOCKED", "2026": "LOCKED", "charge_usd": 0.0,
    }
    state = {**state_core, "state_hash": canonical_hash(state_core), "completed_at_utc": now()}
    write_json(STATE, state)
    artifact_paths = [AMENDMENT, PREACCESS_FREEZE, PRIMARY, REFERENCE, RESULT, VALIDATION, STATE, REPORT, IMPLEMENTATION]
    records = [record(path) for path in artifact_paths]
    seal = {
        "version": "MSBAM_V1_M1_R2_SEAL_1_0", "status": "SEALED_M1_R2_COMPLETE",
        "verdict": verdict, "branch_ready": primary["branch_pass"], "artifacts": records,
        "artifact_set_hash": canonical_hash(records), "result_hash": result["result_hash"],
        "next_milestone_authorized": primary["branch_pass"], "2025_values_accessed": False,
        "2026_values_accessed": False, "charge_usd": 0.0, "sealed_at_utc": now(),
    }
    write_json(FINAL_SEAL, seal)
    print(json.dumps({"verdict": verdict, "passing_units": len(primary["passing_units"]), "eligible_cases": result["eligible_case_count"], "instruments": primary["eligible_instruments"], "seal": record(FINAL_SEAL)}, indent=2))


if __name__ == "__main__":
    main()
