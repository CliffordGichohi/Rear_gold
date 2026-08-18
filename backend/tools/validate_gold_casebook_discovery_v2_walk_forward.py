from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Mapping, Sequence
from datetime import date
from pathlib import Path
from typing import Any

import run_gold_casebook_discovery_v2_walk_forward as runner
import run_gold_casebook_relationship_discovery as utility

from gold_intel.analytics.casebook import canonical_hash, json_ready
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


def main() -> None:
    args = _parser().parse_args()
    bundle_root = Path(args.bundle)
    output = Path(args.output) if args.output else bundle_root / "semantic_validation.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite semantic validation: {output}")

    research = runner._load_json(Path(args.research_manifest))
    research_hash = runner._verify_manifest(
        research,
        label="V2 M4 manifest",
    )
    runner._verify_research_freeze(research)
    contract = runner._load_json(Path(args.contract_manifest))
    contract_hash = runner._verify_manifest(
        contract,
        label="V2 contract manifest",
    )
    runner._verify_candidate_identity(
        research,
        contract=contract,
        contract_hash=contract_hash,
    )
    source = runner._verify_sources(
        research,
        m3_root=Path(args.milestone_3_bundle),
        outcome_root=Path(args.outcome_bundle),
    )

    manifest = runner._load_json(bundle_root / "manifest.json")
    manifest_hash = runner._verify_manifest(
        manifest,
        label="V2 M4 bundle manifest",
    )
    _verify_bundle_chain(
        manifest,
        research_hash=research_hash,
        contract_hash=contract_hash,
        source=source,
    )
    for artifact in manifest["artifacts"]:
        utility._verify_file_hash(
            bundle_root / str(artifact["path"]),
            str(artifact["sha256"]),
        )
    results = runner._load_json(bundle_root / "walk_forward_results.json")
    results_hash = runner._verify_document_hash(
        results,
        hash_field="results_hash",
        label="V2 M4 results",
    )
    _progress(
        "V2_M4_VALIDATION_ARTIFACTS_VERIFIED",
        bundle_manifest_hash=manifest_hash,
        results_hash=results_hash,
    )

    features = runner._load_london_features(
        Path(args.milestone_3_bundle) / "development_features.jsonl.gz",
        expected_research_hash=str(research["source"]["milestone_3_research_manifest_hash"]),
    )
    outcomes = runner._load_london_outcomes(
        Path(args.outcome_bundle) / "outcomes.jsonl.gz",
        expected_execution_hash=str(research["execution"]["execution_manifest_hash"]),
    )
    cases = runner._join_cases(features, outcomes=outcomes)
    decisions = _load_and_verify_decisions(
        bundle_root / "fold_decisions.jsonl.gz",
        cases=cases,
        research=research,
        research_hash=research_hash,
        expected_count=int(
            utility._artifact(
                manifest,
                "fold_decisions.jsonl.gz",
            )["record_count"]
        ),
    )
    expected_results = _recompute_results(
        cases,
        research=research,
        research_hash=research_hash,
    )
    if json_ready(expected_results) != results:
        raise ValueError("V2 M4 results do not independently reconstruct")

    validation: dict[str, Any] = {
        "validation_version": ("GOLD_CASEBOOK_DISCOVERY_V2_WALK_FORWARD_VALIDATION_V0_1"),
        "walk_forward_version": WALK_FORWARD_VERSION,
        "research_manifest_hash": research_hash,
        "bundle_manifest_hash": manifest_hash,
        "results_hash": results_hash,
        "verified": {
            "bundle_artifact_hashes": len(manifest["artifacts"]),
            "london_development_cases": len(cases),
            "decision_records": decisions,
            "training_windows": len(results["folds"]),
            "forward_test_folds": len(results["folds"]),
            "evaluated_candidates": 1,
            "evaluated_sessions": 1,
        },
        "semantic_assertions": {
            "all_source_artifact_and_record_hashes_match": True,
            "all_decisions_join_to_immutable_feature_and_outcome_cases": True,
            "candidate_rule_table_recomputed_for_every_case": True,
            "expanding_training_boundaries_recomputed": True,
            "non_overlapping_forward_folds_recomputed": True,
            "matched_controls_recomputed_on_directional_cases": True,
            "base_and_1_5x_cost_identities_recomputed": True,
            "all_state_fold_and_aggregate_metrics_recomputed": True,
            "all_cluster_bootstrap_intervals_recomputed": True,
            "all_cluster_sign_flip_p_values_recomputed": True,
            "one_candidate_bh_q_value_recomputed": True,
            "all_frozen_gates_and_verdict_recomputed": True,
            "new_milestone_3_relationships_absent": True,
            "new_york_absent": True,
            "calendar_2025_absent": True,
            "calendar_2026_absent": True,
            "execution_optimization_absent": True,
        },
        "result": "PASS_SEMANTIC_VALIDATION",
    }
    validation["validation_hash"] = canonical_hash(validation)
    output.write_text(
        json.dumps(json_ready(validation), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _progress(
        "V2_M4_SEMANTIC_VALIDATION_COMPLETE",
        output=str(output),
        validation_hash=validation["validation_hash"],
        verdict=results["gate_evaluation"]["verdict"],
        calendar_2025_loaded=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reconstruct the V2 Milestone 4 London-only "
            "expanding walk-forward decisions, metrics, uncertainty, and gates."
        )
    )
    parser.add_argument(
        "--bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_walk_forward_v01"),
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
    parser.add_argument("--output")
    return parser


def _verify_bundle_chain(
    manifest: Mapping[str, Any],
    *,
    research_hash: str,
    contract_hash: str,
    source: Mapping[str, str],
) -> None:
    if manifest["walk_forward_version"] != WALK_FORWARD_VERSION:
        raise ValueError("V2 M4 bundle version changed")
    if manifest["schema_version"] != WALK_FORWARD_SCHEMA_VERSION:
        raise ValueError("V2 M4 bundle schema changed")
    if manifest["candidate_code"] != runner.CANDIDATE_CODE:
        raise ValueError("V2 M4 bundle candidate changed")
    lineage = manifest["source"]
    if lineage["research_manifest_hash"] != research_hash:
        raise ValueError("V2 M4 bundle research lineage changed")
    if lineage["contract_manifest_hash"] != contract_hash:
        raise ValueError("V2 M4 bundle contract lineage changed")
    for key, value in source.items():
        if lineage[key] != value:
            raise ValueError(f"V2 M4 bundle source changed: {key}")
    integrity = manifest["integrity"]
    required_false = (
        "candidate_changed",
        "execution_optimized",
        "new_candidate_evaluated",
        "new_york_evaluated",
        "calendar_2025_loaded",
        "calendar_2026_loaded",
    )
    if any(integrity[key] is not False for key in required_false):
        raise ValueError("V2 M4 bundle integrity guardrail changed")


def _load_and_verify_decisions(
    path: Path,
    *,
    cases: Sequence[WalkForwardCase],
    research: Mapping[str, Any],
    research_hash: str,
    expected_count: int,
) -> int:
    by_id = {case.case_id: case for case in cases}
    actual: set[str] = set()
    stress = float(research["cost_stress"]["stress_cost_multiplier"])
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("V2 M4 decision enters a locked calendar")
            record = json.loads(line)
            runner._verify_record_hash(record)
            if record["record_type"] != "V2_WALK_FORWARD_DECISION":
                raise ValueError("Unexpected V2 M4 decision record type")
            if record["research_manifest_hash"] != research_hash:
                raise ValueError("V2 M4 decision research lineage changed")
            if record["session_code"] != "LONDON":
                raise ValueError("New York entered V2 M4 decisions")
            case_id = str(record["case_id"])
            if case_id in actual:
                raise ValueError(f"Duplicate V2 M4 decision: {case_id}")
            case = by_id[case_id]
            base = selected_observation(case)
            stressed = selected_observation(case, cost_multiplier=stress)
            expected = {
                "case_record_hash": case.case_record_hash,
                "session_date": case.session_date.isoformat(),
                "decision_at": case.decision_at.isoformat(),
                "feature_id": runner.FEATURE_ID,
                "feature_state": case.feature_state,
                "raw_percent_change": case.raw_percent_change,
                "feature_source_key": case.feature_source_key,
                "bias": case.bias,
                "fold_memberships": _fold_memberships(
                    case,
                    definitions=research["fold_design"]["folds"],
                ),
                "selected_base_outcome": (
                    {
                        "side": base.side,
                        "net_pnl_usd_per_ounce": base.net_pnl_usd_per_ounce,
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
            }
            for key, value in expected.items():
                if record[key] != json_ready(value):
                    raise ValueError(f"V2 M4 decision does not reconstruct: {case_id}/{key}")
            actual.add(case_id)
    if len(actual) != expected_count or len(actual) != len(cases) or actual != set(by_id):
        raise ValueError("V2 M4 decision case set or count changed")
    return len(actual)


def _recompute_results(
    cases: Sequence[WalkForwardCase],
    *,
    research: Mapping[str, Any],
    research_hash: str,
) -> dict[str, Any]:
    uncertainty = research["uncertainty"]
    thresholds = research["gate_evaluation"]["thresholds"]
    stress = float(research["cost_stress"]["stress_cost_multiplier"])

    def report(
        selected: Sequence[WalkForwardCase],
        *,
        window_id: str,
    ) -> dict[str, Any]:
        return build_window_report(
            selected,
            manifest_hash=research_hash,
            candidate_code=runner.CANDIDATE_CODE,
            window_id=window_id,
            bootstrap_replications=int(uncertainty["cluster_bootstrap"]["replications"]),
            sign_flip_replications=int(uncertainty["cluster_sign_flip_test"]["replications"]),
            stress_multiplier=stress,
        )

    fold_results: list[dict[str, Any]] = []
    forward: list[WalkForwardCase] = []
    seen: set[str] = set()
    for definition in research["fold_design"]["folds"]:
        fold_id = str(definition["fold_id"])
        training = _slice(
            cases,
            start=date.fromisoformat(definition["training_start_inclusive"]),
            end=date.fromisoformat(definition["training_end_exclusive"]),
        )
        test = _slice(
            cases,
            start=date.fromisoformat(definition["test_start_inclusive"]),
            end=date.fromisoformat(definition["test_end_exclusive"]),
        )
        if seen.intersection(case.case_id for case in test):
            raise ValueError("V2 M4 validation found overlapping test folds")
        seen.update(case.case_id for case in test)
        forward.extend(test)
        training_report = report(training, window_id=f"{fold_id}_TRAIN")
        test_report = report(test, window_id=f"{fold_id}_TEST")
        fold_results.append(
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
    aggregate = report(
        sorted(forward, key=lambda item: (item.decision_at, item.case_id)),
        window_id="AGGREGATE_FORWARD_2022_2024",
    )
    aggregate["benjamini_hochberg_q_value"] = aggregate["cluster_sign_flip_p_value"]
    gates = evaluate_aggregate_gates(
        fold_results,
        aggregate_report=aggregate,
        q_threshold=float(thresholds["aggregate_maximum_bh_q_value"]),
        integrity_passed=True,
    )
    output: dict[str, Any] = {
        "walk_forward_version": WALK_FORWARD_VERSION,
        "schema_version": WALK_FORWARD_SCHEMA_VERSION,
        "milestone": "V2_M4_INTERNAL_EXPANDING_WALK_FORWARD",
        "research_manifest_hash": research_hash,
        "candidate": research["candidate"],
        "folds": fold_results,
        "aggregate_forward": aggregate,
        "gate_evaluation": gates,
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
    output["results_hash"] = canonical_hash(output)
    return output


def _fold_memberships(
    case: WalkForwardCase,
    *,
    definitions: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    output: list[dict[str, str]] = []
    for fold in definitions:
        if (
            date.fromisoformat(str(fold["training_start_inclusive"]))
            <= case.session_date
            < date.fromisoformat(str(fold["training_end_exclusive"]))
        ):
            output.append({"fold_id": str(fold["fold_id"]), "role": "TRAIN"})
        if (
            date.fromisoformat(str(fold["test_start_inclusive"]))
            <= case.session_date
            < date.fromisoformat(str(fold["test_end_exclusive"]))
        ):
            output.append({"fold_id": str(fold["fold_id"]), "role": "TEST"})
    return output


def _slice(
    cases: Sequence[WalkForwardCase],
    *,
    start: date,
    end: date,
) -> list[WalkForwardCase]:
    return [case for case in cases if start <= case.session_date < end]


def _progress(stage: str, **values: Any) -> None:
    print(
        json.dumps(json_ready({"stage": stage, **values}), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
