from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import run_gold_casebook_relationship_discovery as utility

from gold_intel.analytics.casebook import (
    canonical_hash,
    finalize_record,
    json_ready,
)
from gold_intel.backtesting.casebook_discovery_v2_relationships import (
    embedded_manifest_hash,
)
from gold_intel.backtesting.casebook_discovery_v2_walk_forward import (
    WALK_FORWARD_SCHEMA_VERSION,
    WALK_FORWARD_VERSION,
    WalkForwardCase,
    build_window_report,
    evaluate_aggregate_gates,
    evaluate_test_gates,
    evaluate_training_gates,
    selected_observation,
)

DEVELOPMENT_START = date(2021, 8, 1)
DEVELOPMENT_END = date(2025, 1, 1)
FEATURE_ID = "cross_zn_v_0_4_hours"
CANDIDATE_CODE = "LONDON_ZN_4H_POSTHOC_V0_1"


def main() -> None:
    args = _parser().parse_args()
    research_path = Path(args.research_manifest)
    m3_root = Path(args.milestone_3_bundle)
    outcome_root = Path(args.outcome_bundle)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite immutable V2 M4 bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    research = _load_json(research_path)
    research_hash = _verify_manifest(research, label="V2 M4 manifest")
    _verify_research_freeze(research)
    contract = _load_json(Path(args.contract_manifest))
    contract_hash = _verify_manifest(contract, label="V2 contract manifest")
    _verify_candidate_identity(
        research,
        contract=contract,
        contract_hash=contract_hash,
    )
    source = _verify_sources(
        research,
        m3_root=m3_root,
        outcome_root=outcome_root,
    )
    _progress(
        "V2_M4_FROZEN_SOURCES_VERIFIED",
        research_manifest_hash=research_hash,
        contract_manifest_hash=contract_hash,
        milestone_3_bundle_hash=source["m3_bundle_hash"],
        outcome_bundle_hash=source["outcome_bundle_hash"],
    )

    features = _load_london_features(
        m3_root / "development_features.jsonl.gz",
        expected_research_hash=str(research["source"]["milestone_3_research_manifest_hash"]),
    )
    outcomes = _load_london_outcomes(
        outcome_root / "outcomes.jsonl.gz",
        expected_execution_hash=str(research["execution"]["execution_manifest_hash"]),
    )
    cases = _join_cases(features, outcomes=outcomes)
    _progress(
        "V2_M4_LONDON_CASES_MATERIALIZED",
        cases=len(cases),
        first_case=cases[0].session_date.isoformat(),
        last_case=cases[-1].session_date.isoformat(),
        calendar_2025_loaded=False,
    )

    fold_results = _build_folds(
        cases,
        research=research,
        research_hash=research_hash,
    )
    test_case_ids = {
        case.case_id
        for fold in research["fold_design"]["folds"]
        for case in _slice_cases(
            cases,
            start=date.fromisoformat(fold["test_start_inclusive"]),
            end=date.fromisoformat(fold["test_end_exclusive"]),
        )
    }
    forward_cases = [case for case in cases if case.case_id in test_case_ids]
    aggregate = _window_report(
        forward_cases,
        research=research,
        research_hash=research_hash,
        window_id="AGGREGATE_FORWARD_2022_2024",
    )
    aggregate["benjamini_hochberg_q_value"] = aggregate["cluster_sign_flip_p_value"]
    thresholds = research["gate_evaluation"]["thresholds"]
    gate_evaluation = evaluate_aggregate_gates(
        fold_results,
        aggregate_report=aggregate,
        q_threshold=float(thresholds["aggregate_maximum_bh_q_value"]),
        integrity_passed=True,
    )
    results: dict[str, Any] = {
        "walk_forward_version": WALK_FORWARD_VERSION,
        "schema_version": WALK_FORWARD_SCHEMA_VERSION,
        "milestone": "V2_M4_INTERNAL_EXPANDING_WALK_FORWARD",
        "research_manifest_hash": research_hash,
        "candidate": research["candidate"],
        "folds": fold_results,
        "aggregate_forward": aggregate,
        "gate_evaluation": gate_evaluation,
        "integrity": {
            "point_in_time_integrity_passed": True,
            "issue_count": 0,
            "issues": [],
            "candidate_changed": False,
            "execution_changed": False,
            "new_candidate_evaluated": False,
            "new_york_evaluated": False,
            "milestone_3_q_failed_relationship_evaluated": False,
            "calendar_2025_loaded": False,
            "calendar_2026_loaded": False,
        },
        "interpretation": {
            "independent_validation_credit": False,
            "edge_claim_permitted": False,
            "pass_meaning": (
                "Eligibility for Milestone 5 shortlist consideration only; "
                "not independent validation."
            ),
            "next_milestone": "V2_M5_SHORTLIST_FREEZE",
            "next_milestone_authorized": False,
        },
    }
    results["results_hash"] = canonical_hash(results)
    decisions = _decision_records(
        cases,
        research=research,
        research_hash=research_hash,
    )

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        decisions_path = staging / "fold_decisions.jsonl.gz"
        decision_count = utility._write_jsonl_gzip(
            decisions_path,
            decisions,
        )
        results_path = staging / "walk_forward_results.json"
        utility._write_json(results_path, results)
        artifacts = [
            utility._artifact_summary(
                decisions_path,
                record_count=decision_count,
                record_type="V2_WALK_FORWARD_DECISION",
            ),
            {
                "path": results_path.name,
                "sha256": utility._sha256(results_path),
                "bytes": results_path.stat().st_size,
                "document_hash": results["results_hash"],
            },
        ]
        bundle: dict[str, Any] = {
            "walk_forward_version": WALK_FORWARD_VERSION,
            "schema_version": WALK_FORWARD_SCHEMA_VERSION,
            "governing_contract": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
            "milestone": "V2_M4_INTERNAL_EXPANDING_WALK_FORWARD",
            "candidate_code": CANDIDATE_CODE,
            "verdict": gate_evaluation["verdict"],
            "source": {
                "research_manifest_hash": research_hash,
                "contract_manifest_hash": contract_hash,
                **source,
            },
            "artifacts": artifacts,
            "integrity": {
                "source_artifact_hashes_verified": 5,
                "decision_records_written": decision_count,
                "candidate_changed": False,
                "execution_optimized": False,
                "new_candidate_evaluated": False,
                "new_york_evaluated": False,
                "calendar_2025_loaded": False,
                "calendar_2026_loaded": False,
            },
        }
        bundle["manifest_hash"] = canonical_hash(bundle)
        utility._write_json(staging / "manifest.json", bundle)
        staging.rename(output)

    _progress(
        "V2_M4_WALK_FORWARD_COMPLETE",
        output=str(output),
        bundle_manifest_hash=bundle["manifest_hash"],
        results_hash=results["results_hash"],
        verdict=gate_evaluation["verdict"],
        failed_gate_ids=gate_evaluation["failed_gate_ids"],
        calendar_2025_loaded=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run the frozen V2 Milestone 4 London-only expanding walk-forward stability test."
        )
    )
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_walk_forward_v01.json"),
    )
    parser.add_argument(
        "--contract-manifest",
        default="research_manifests/gold_casebook_discovery_contract_v02.json",
    )
    parser.add_argument(
        "--milestone-3-bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_relationships_v01"),
    )
    parser.add_argument(
        "--outcome-bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_outcome_atlas_v01"),
    )
    parser.add_argument(
        "--output",
        default=("research_artifacts/gold_casebook_discovery_v2_walk_forward_v01"),
    )
    return parser


def _verify_research_freeze(research: Mapping[str, Any]) -> None:
    if research["manifest_version"] != "GOLD_CASEBOOK_DISCOVERY_V2_WALK_FORWARD_MANIFEST_V0_1":
        raise ValueError("Unexpected V2 M4 manifest version")
    if research["status"] != "FROZEN_BEFORE_WALK_FORWARD_CALCULATION":
        raise ValueError("V2 M4 manifest is not pre-result frozen")
    if research["milestone"] != "V2_M4_INTERNAL_EXPANDING_WALK_FORWARD":
        raise ValueError("Unexpected V2 milestone")
    if not all(bool(value) for value in research["prohibited"].values()):
        raise ValueError("One or more V2 M4 prohibitions is unlocked")
    if len(research["fold_design"]["folds"]) != 3:
        raise ValueError("Frozen walk-forward fold count changed")
    if research["multiplicity"]["number_of_candidates"] != 1:
        raise ValueError("Frozen candidate family changed")
    if research["gate_evaluation"]["all_gates_required"] is not True:
        raise ValueError("V2 M4 no longer requires every gate")


def _verify_candidate_identity(
    research: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    contract_hash: str,
) -> None:
    if research["contract"]["manifest_hash"] != contract_hash:
        raise ValueError("V2 M4 points to another contract")
    expected = contract["post_hoc_candidate"]
    candidate = research["candidate"]
    for key in (
        "candidate_code",
        "feature_id",
        "rule_table",
        "session",
        "threshold",
        "tuning_permitted",
    ):
        if candidate[key] != expected[key]:
            raise ValueError(f"Post-hoc candidate identity changed: {key}")
    if candidate["candidate_code"] != CANDIDATE_CODE:
        raise ValueError("Unexpected V2 M4 candidate")
    if candidate["session"] != "LONDON":
        raise ValueError("V2 M4 candidate is not London-only")


def _verify_sources(
    research: Mapping[str, Any],
    *,
    m3_root: Path,
    outcome_root: Path,
) -> dict[str, str]:
    m3 = _load_json(m3_root / "manifest.json")
    m3_hash = _verify_manifest(m3, label="V2 M3 bundle manifest")
    if m3_hash != research["source"]["milestone_3_bundle_hash"]:
        raise ValueError("V2 M4 points to another M3 bundle")
    feature_artifact = utility._artifact(
        m3,
        "development_features.jsonl.gz",
    )
    utility._verify_file_hash(
        m3_root / "development_features.jsonl.gz",
        str(feature_artifact["sha256"]),
    )
    if feature_artifact["sha256"] != research["source"]["development_feature_ledger_sha256"]:
        raise ValueError("V2 M4 points to another feature ledger")
    rankings = _load_json(m3_root / "rankings.json")
    _verify_document_hash(
        rankings,
        hash_field="rankings_hash",
        label="V2 M3 rankings",
    )
    if int(rankings["summary"]["discovery_leads"]) != 0:
        raise ValueError("Unexpected new M3 lead entered V2 M4")
    validation = _load_json(m3_root / "semantic_validation.json")
    validation_hash = _verify_document_hash(
        validation,
        hash_field="validation_hash",
        label="V2 M3 semantic validation",
    )
    if validation_hash != research["source"]["milestone_3_semantic_validation_hash"]:
        raise ValueError("V2 M4 points to another M3 validation")
    if validation["result"] != "PASS_SEMANTIC_VALIDATION":
        raise ValueError("V2 M3 source did not pass semantic validation")

    outcome = _load_json(outcome_root / "manifest.json")
    outcome_hash = _verify_manifest(
        outcome,
        label="V2 outcome bundle manifest",
    )
    if outcome_hash != research["outcome"]["source_bundle_hash"]:
        raise ValueError("V2 M4 points to another outcome bundle")
    outcome_artifact = utility._artifact(outcome, "outcomes.jsonl.gz")
    utility._verify_file_hash(
        outcome_root / "outcomes.jsonl.gz",
        str(outcome_artifact["sha256"]),
    )
    if outcome_artifact["sha256"] != research["outcome"]["source_ledger_sha256"]:
        raise ValueError("V2 M4 points to another outcome ledger")
    return {
        "m3_bundle_hash": m3_hash,
        "m3_feature_ledger_sha256": str(feature_artifact["sha256"]),
        "outcome_bundle_hash": outcome_hash,
        "outcome_ledger_sha256": str(outcome_artifact["sha256"]),
    }


def _load_london_features(
    path: Path,
    *,
    expected_research_hash: str,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Feature source enters a locked calendar")
            if '"session_code":"LONDON"' not in line:
                continue
            record = json.loads(line)
            _verify_record_hash(record)
            if record["record_type"] != "V2_DEVELOPMENT_FEATURE_CASE":
                raise ValueError("Unexpected M3 feature record type")
            if record["research_manifest_hash"] != expected_research_hash:
                raise ValueError("M3 feature research lineage changed")
            feature = record["features"][FEATURE_ID]
            _verify_feature(feature, case_id=str(record["case_id"]))
            case_id = str(record["case_id"])
            if case_id in output:
                raise ValueError(f"Duplicate London feature case: {case_id}")
            output[case_id] = {
                "case_id": case_id,
                "case_record_hash": str(record["case_record_hash"]),
                "session_date": date.fromisoformat(str(record["session_date"])),
                "decision_at": utility._timestamp(str(record["decision_at"])),
                "feature": feature,
                "feature_record_hash": str(record["record_hash"]),
            }
    return output


def _load_london_outcomes(
    path: Path,
    *,
    expected_execution_hash: str,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Outcome source enters a locked calendar")
            if '"session_code":"LONDON"' not in line:
                continue
            record = json.loads(line)
            _verify_record_hash(record)
            if record["record_type"] != "V2_OUTCOME_CASE":
                raise ValueError("Unexpected V2 outcome record type")
            if record["execution_manifest_hash"] != expected_execution_hash:
                raise ValueError("Outcome execution lineage changed")
            case_id = str(record["case_id"])
            if case_id in output:
                raise ValueError(f"Duplicate London outcome: {case_id}")
            output[case_id] = record
    return output


def _join_cases(
    features: Mapping[str, Mapping[str, Any]],
    *,
    outcomes: Mapping[str, Mapping[str, Any]],
) -> list[WalkForwardCase]:
    if set(features) != set(outcomes):
        raise ValueError("London feature and outcome case sets differ")
    output: list[WalkForwardCase] = []
    for case_id, source in features.items():
        outcome = outcomes[case_id]
        if source["case_record_hash"] != outcome["case_record_hash"]:
            raise ValueError(f"London case hash mismatch: {case_id}")
        if source["session_date"] != date.fromisoformat(str(outcome["session_date"])):
            raise ValueError(f"London case date mismatch: {case_id}")
        feature = source["feature"]
        output.append(
            WalkForwardCase(
                case_id=case_id,
                case_record_hash=str(source["case_record_hash"]),
                session_date=source["session_date"],
                decision_at=source["decision_at"],
                feature_state=str(feature["state"]),
                raw_percent_change=(
                    float(feature["raw_value"]) if feature["raw_value"] is not None else None
                ),
                feature_source_key=feature["source_key"],
                reference_entry_price=float(outcome["reference_entry_price"]),
                gross_move_usd_per_ounce=float(outcome["gross_move_usd_per_ounce"]),
                cost_usd_per_ounce=float(outcome["cost_usd_per_ounce"]),
                long_net_pnl_usd_per_ounce=float(outcome["long_net_pnl_usd"]),
                long_net_return_basis_points=float(outcome["long_net_return_basis_points"]),
                short_net_pnl_usd_per_ounce=float(outcome["short_net_pnl_usd"]),
                short_net_return_basis_points=float(outcome["short_net_return_basis_points"]),
            )
        )
    ordered = sorted(output, key=lambda item: (item.decision_at, item.case_id))
    if not ordered:
        raise ValueError("No London cases were materialized")
    if ordered[0].session_date < DEVELOPMENT_START or ordered[-1].session_date >= DEVELOPMENT_END:
        raise ValueError("London development boundary changed")
    for case in ordered:
        selected_observation(case)
    return ordered


def _build_folds(
    cases: Sequence[WalkForwardCase],
    *,
    research: Mapping[str, Any],
    research_hash: str,
) -> list[dict[str, Any]]:
    thresholds = research["gate_evaluation"]["thresholds"]
    output: list[dict[str, Any]] = []
    seen_test_cases: set[str] = set()
    for definition in research["fold_design"]["folds"]:
        fold_id = str(definition["fold_id"])
        training = _slice_cases(
            cases,
            start=date.fromisoformat(definition["training_start_inclusive"]),
            end=date.fromisoformat(definition["training_end_exclusive"]),
        )
        test = _slice_cases(
            cases,
            start=date.fromisoformat(definition["test_start_inclusive"]),
            end=date.fromisoformat(definition["test_end_exclusive"]),
        )
        if seen_test_cases.intersection(case.case_id for case in test):
            raise ValueError("Walk-forward test folds overlap")
        seen_test_cases.update(case.case_id for case in test)
        training_report = _window_report(
            training,
            research=research,
            research_hash=research_hash,
            window_id=f"{fold_id}_TRAIN",
        )
        test_report = _window_report(
            test,
            research=research,
            research_hash=research_hash,
            window_id=f"{fold_id}_TEST",
        )
        output.append(
            {
                **definition,
                "training_report": training_report,
                "training_gates": evaluate_training_gates(
                    training_report,
                    minimum_directional_cases=int(thresholds["training_minimum_directional_cases"]),
                    minimum_state_cases=int(thresholds["training_minimum_state_cases"]),
                    minimum_state_week_clusters=int(
                        thresholds["training_minimum_state_week_clusters"]
                    ),
                ),
                "test_report": test_report,
                "test_gates": evaluate_test_gates(
                    test_report,
                    minimum_directional_cases=int(thresholds["test_minimum_directional_cases"]),
                    minimum_state_cases=int(thresholds["test_minimum_state_cases"]),
                    minimum_state_week_clusters=int(thresholds["test_minimum_state_week_clusters"]),
                ),
            }
        )
    return output


def _window_report(
    cases: Sequence[WalkForwardCase],
    *,
    research: Mapping[str, Any],
    research_hash: str,
    window_id: str,
) -> dict[str, Any]:
    uncertainty = research["uncertainty"]
    return build_window_report(
        cases,
        manifest_hash=research_hash,
        candidate_code=CANDIDATE_CODE,
        window_id=window_id,
        bootstrap_replications=int(uncertainty["cluster_bootstrap"]["replications"]),
        sign_flip_replications=int(uncertainty["cluster_sign_flip_test"]["replications"]),
        stress_multiplier=float(research["cost_stress"]["stress_cost_multiplier"]),
    )


def _decision_records(
    cases: Sequence[WalkForwardCase],
    *,
    research: Mapping[str, Any],
    research_hash: str,
) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    folds = research["fold_design"]["folds"]
    stress = float(research["cost_stress"]["stress_cost_multiplier"])
    for case in cases:
        base = selected_observation(case)
        stressed = selected_observation(case, cost_multiplier=stress)
        memberships: list[dict[str, str]] = []
        for fold in folds:
            if (
                date.fromisoformat(fold["training_start_inclusive"])
                <= case.session_date
                < date.fromisoformat(fold["training_end_exclusive"])
            ):
                memberships.append({"fold_id": str(fold["fold_id"]), "role": "TRAIN"})
            if (
                date.fromisoformat(fold["test_start_inclusive"])
                <= case.session_date
                < date.fromisoformat(fold["test_end_exclusive"])
            ):
                memberships.append({"fold_id": str(fold["fold_id"]), "role": "TEST"})
        output.append(
            finalize_record(
                {
                    "record_type": "V2_WALK_FORWARD_DECISION",
                    "record_id": f"V2-M4-{case.case_id}",
                    "walk_forward_version": WALK_FORWARD_VERSION,
                    "schema_version": WALK_FORWARD_SCHEMA_VERSION,
                    "epistemic_status": "INFERRED",
                    "research_manifest_hash": research_hash,
                    "candidate_code": CANDIDATE_CODE,
                    "case_id": case.case_id,
                    "case_record_hash": case.case_record_hash,
                    "session_code": "LONDON",
                    "session_date": case.session_date,
                    "decision_at": case.decision_at,
                    "feature_id": FEATURE_ID,
                    "feature_state": case.feature_state,
                    "raw_percent_change": case.raw_percent_change,
                    "feature_source_key": case.feature_source_key,
                    "bias": case.bias,
                    "fold_memberships": memberships,
                    "selected_base_outcome": (
                        {
                            "side": base.side,
                            "net_pnl_usd_per_ounce": (base.net_pnl_usd_per_ounce),
                            "net_return_basis_points": (base.net_return_basis_points),
                        }
                        if base is not None
                        else None
                    ),
                    "selected_cost_stress_outcome": (
                        {
                            "cost_multiplier": stress,
                            "side": stressed.side,
                            "net_pnl_usd_per_ounce": (stressed.net_pnl_usd_per_ounce),
                            "net_return_basis_points": (stressed.net_return_basis_points),
                        }
                        if stressed is not None
                        else None
                    ),
                    "candidate_changed": False,
                    "new_york_evaluated": False,
                    "calendar_2025_loaded": False,
                }
            )
        )
    return output


def _slice_cases(
    cases: Sequence[WalkForwardCase],
    *,
    start: date,
    end: date,
) -> list[WalkForwardCase]:
    return [case for case in cases if start <= case.session_date < end]


def _verify_feature(
    feature: Mapping[str, Any],
    *,
    case_id: str,
) -> None:
    if feature["family_code"] != "INTRADAY_CROSS_MARKET":
        raise ValueError(f"ZN feature family changed: {case_id}")
    if feature["transform"] != "SIGN_3":
        raise ValueError(f"ZN feature transform changed: {case_id}")
    state = str(feature["state"])
    value = feature["raw_value"]
    if state == "POSITIVE" and (value is None or float(value) <= 0 or not feature["source_key"]):
        raise ValueError(f"Invalid positive ZN feature: {case_id}")
    if state == "NEGATIVE" and (value is None or float(value) >= 0 or not feature["source_key"]):
        raise ValueError(f"Invalid negative ZN feature: {case_id}")
    if state == "FLAT" and (value is None or float(value) != 0):
        raise ValueError(f"Invalid flat ZN feature: {case_id}")
    if state == "UNKNOWN" and value is not None:
        raise ValueError(f"Invalid unknown ZN feature: {case_id}")
    if state not in {"POSITIVE", "NEGATIVE", "FLAT", "UNKNOWN"}:
        raise ValueError(f"Unexpected ZN feature state: {case_id}")


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Record hash mismatch: {record['record_id']}")


def _verify_manifest(document: Mapping[str, Any], *, label: str) -> str:
    supplied = str(document["manifest_hash"])
    if embedded_manifest_hash(document) != supplied:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _verify_document_hash(
    document: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    supplied = str(document[hash_field])
    unhashed = {key: value for key, value in document.items() if key != hash_field}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _progress(stage: str, **values: Any) -> None:
    print(
        json.dumps(json_ready({"stage": stage, **values}), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
