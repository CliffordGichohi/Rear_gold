from __future__ import annotations

import argparse
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import run_gold_casebook_discovery_v2_shortlist as runner
import run_gold_casebook_relationship_discovery as utility

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.backtesting.casebook_discovery_v2_shortlist import (
    CANDIDATE_CODE,
    EVALUATION_GATE_IDS,
    READINESS_GATE_IDS,
    SHORTLIST_SCHEMA_VERSION,
    SHORTLIST_VERSION,
    metadata_readiness,
    validate_shortlist_definition,
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
        label="V2 M5 manifest",
    )
    validate_shortlist_definition(research)
    contract = runner._load_json(Path(args.contract_manifest))
    contract_hash = runner._verify_manifest(
        contract,
        label="V2 contract manifest",
    )
    execution = runner._load_json(Path(args.execution_manifest))
    execution_hash = runner._verify_manifest(
        execution,
        label="execution manifest",
    )
    runner._verify_contract_and_execution(
        research,
        contract=contract,
        contract_hash=contract_hash,
        execution_hash=execution_hash,
    )
    sources = runner._verify_research_sources(
        research,
        milestone_3_root=Path(args.milestone_3_bundle),
        milestone_4_root=Path(args.milestone_4_bundle),
    )
    coverage = runner._load_json(Path(args.coverage))
    coverage_hash = runner._verify_coverage_hash(coverage)
    runner._verify_metadata_only_coverage(coverage)
    readiness = metadata_readiness(coverage)

    manifest = runner._load_json(bundle_root / "manifest.json")
    manifest_hash = runner._verify_manifest(
        manifest,
        label="V2 M5 bundle manifest",
    )
    _verify_bundle_chain(
        manifest,
        research_hash=research_hash,
        contract_hash=contract_hash,
        execution_hash=execution_hash,
        coverage_hash=coverage_hash,
        sources=sources,
    )
    for artifact in manifest["artifacts"]:
        utility._verify_file_hash(
            bundle_root / str(artifact["path"]),
            str(artifact["sha256"]),
        )
    shortlist = runner._load_json(bundle_root / "shortlist.json")
    shortlist_hash = runner._verify_document_hash(
        shortlist,
        hash_field="shortlist_hash",
        label="V2 M5 shortlist",
    )
    expected = _reconstruct_shortlist(
        research,
        research_hash=research_hash,
        coverage_hash=coverage_hash,
        readiness=readiness,
        sources=sources,
    )
    if shortlist != json_ready(expected):
        raise ValueError("V2 M5 shortlist does not independently reconstruct")
    _verify_no_holdout_access(shortlist)

    validation: dict[str, Any] = {
        "validation_version": ("GOLD_CASEBOOK_DISCOVERY_V2_SHORTLIST_VALIDATION_V0_1"),
        "shortlist_version": SHORTLIST_VERSION,
        "research_manifest_hash": research_hash,
        "bundle_manifest_hash": manifest_hash,
        "shortlist_hash": shortlist_hash,
        "verified": {
            "bundle_artifact_hashes": len(manifest["artifacts"]),
            "frozen_candidates": 1,
            "london_candidates": 1,
            "new_york_candidates": 0,
            "evaluation_gates": len(EVALUATION_GATE_IDS),
            "preopen_readiness_gates": len(READINESS_GATE_IDS),
            "failed_preopen_readiness_gates": len(readiness["failed_gate_ids"]),
        },
        "semantic_assertions": {
            "all_source_document_and_artifact_hashes_match": True,
            "candidate_budget_and_session_separation_match_contract": True,
            "only_m4_passing_contract_candidate_is_frozen": True,
            "milestone_3_q_failed_relationships_absent": True,
            "new_york_shortlist_is_empty": True,
            "rule_mapping_threshold_and_missing_policy_are_unchanged": True,
            "execution_costs_and_matched_controls_are_frozen": True,
            "highest_risk_assumption_and_invalidation_evidence_are_present": True,
            "all_12_holdout_evaluation_gates_are_frozen": True,
            "all_5_preopen_readiness_gates_are_frozen": True,
            "one_candidate_multiplicity_family_is_frozen": True,
            "xauusd_metadata_readiness_recomputed": True,
            "missing_2025_zn_blocker_recomputed": True,
            "proxy_substitution_is_prohibited": True,
            "calendar_2025_values_absent": True,
            "calendar_2025_outcomes_absent": True,
            "calendar_2026_absent": True,
        },
        "result": "PASS_SEMANTIC_VALIDATION",
    }
    validation["validation_hash"] = canonical_hash(validation)
    output.write_text(
        json.dumps(json_ready(validation), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _progress(
        "V2_M5_SEMANTIC_VALIDATION_COMPLETE",
        output=str(output),
        validation_hash=validation["validation_hash"],
        shortlist_status=shortlist["status"],
        calendar_2025_values_accessed=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently validate the frozen V2 Milestone 5 shortlist, "
            "holdout gates, and metadata-only readiness."
        )
    )
    parser.add_argument(
        "--bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_shortlist_v01"),
    )
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_shortlist_v01.json"),
    )
    parser.add_argument(
        "--contract-manifest",
        default="research_manifests/gold_casebook_discovery_contract_v02.json",
    )
    parser.add_argument(
        "--execution-manifest",
        default="research_manifests/gold_casebook_constant_execution_v01.json",
    )
    parser.add_argument(
        "--milestone-3-bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_relationships_v01"),
    )
    parser.add_argument(
        "--milestone-4-bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_walk_forward_v01"),
    )
    parser.add_argument(
        "--coverage",
        default="research_artifacts/gold_casebook_discovery_v2_coverage.json",
    )
    parser.add_argument("--output")
    return parser


def _verify_bundle_chain(
    manifest: Mapping[str, Any],
    *,
    research_hash: str,
    contract_hash: str,
    execution_hash: str,
    coverage_hash: str,
    sources: Mapping[str, Any],
) -> None:
    if manifest["shortlist_version"] != SHORTLIST_VERSION:
        raise ValueError("V2 M5 bundle version changed")
    if manifest["schema_version"] != SHORTLIST_SCHEMA_VERSION:
        raise ValueError("V2 M5 bundle schema changed")
    lineage = manifest["source"]
    expected = {
        "research_manifest_hash": research_hash,
        "contract_manifest_hash": contract_hash,
        "execution_manifest_hash": execution_hash,
        "coverage_data_hash": coverage_hash,
        "milestone_3_bundle_hash": sources["milestone_3_bundle_hash"],
        "milestone_4_bundle_hash": sources["milestone_4_bundle_hash"],
        "milestone_4_results_hash": sources["milestone_4_results_hash"],
    }
    for key, value in expected.items():
        if lineage[key] != value:
            raise ValueError(f"V2 M5 bundle source changed: {key}")
    integrity = manifest["integrity"]
    required_false = (
        "calendar_2025_values_accessed",
        "calendar_2025_outcomes_calculated",
        "calendar_2026_accessed",
        "execution_changed",
        "candidate_retuned",
    )
    if any(integrity[key] is not False for key in required_false):
        raise ValueError("V2 M5 bundle integrity guardrail changed")


def _reconstruct_shortlist(
    research: Mapping[str, Any],
    *,
    research_hash: str,
    coverage_hash: str,
    readiness: Mapping[str, Any],
    sources: Mapping[str, Any],
) -> dict[str, Any]:
    aggregate = sources["milestone_4_results"]["aggregate_forward"]
    output: dict[str, Any] = {
        "shortlist_version": SHORTLIST_VERSION,
        "schema_version": SHORTLIST_SCHEMA_VERSION,
        "milestone": "V2_M5_SHORTLIST_FREEZE",
        "research_manifest_hash": research_hash,
        "status": "FROZEN_BLOCKED_PENDING_ZN_2025_ACQUISITION",
        "candidate_budget": research["candidate_budget"],
        "summary": {
            "london_candidates": 1,
            "new_york_candidates": 0,
            "total_candidates": 1,
            "candidate_codes": [CANDIDATE_CODE],
            "milestone_3_new_discovery_leads": 0,
            "holdout_ready": False,
            "holdout_blocker": "MISSING_2025_ZN_INTRADAY",
        },
        "candidates": research["candidates"],
        "development_evidence": {
            "independent_validation_credit": False,
            "milestone_3_bundle_hash": sources["milestone_3_bundle_hash"],
            "milestone_3_discovery_leads": 0,
            "milestone_4_bundle_hash": sources["milestone_4_bundle_hash"],
            "milestone_4_results_hash": sources["milestone_4_results_hash"],
            "milestone_4_verdict": sources["milestone_4_verdict"],
            "forward_2022_2024": {
                "directional_cases": aggregate["directional_case_count"],
                "mean_net_return_basis_points": aggregate["selector_metrics"][
                    "mean_net_return_basis_points"
                ],
                "profit_factor": aggregate["selector_metrics"]["profit_factor"],
                "cluster_bootstrap_95pct_ci_basis_points": aggregate[
                    "cluster_bootstrap_95pct_ci_mean_net_return_basis_points"
                ],
                "cost_stress_1_5x_mean_net_pnl_usd_per_ounce": aggregate["cost_stress"]["metrics"][
                    "mean_net_pnl_usd_per_ounce"
                ],
            },
        },
        "calendar_2025": {
            "evaluation_definition": research["holdout_2025"],
            "metadata_readiness": readiness,
            "coverage_data_hash": coverage_hash,
            "required_next_action": research["holdout_source_readiness"]["required_action"],
            "values_opened": False,
            "outcomes_calculated": False,
        },
        "guardrails": {
            "shortlist_frozen": True,
            "candidate_addition_permitted": False,
            "candidate_replacement_permitted": False,
            "candidate_retuning_permitted": False,
            "new_york_candidate_present": False,
            "milestone_3_q_failed_relationship_present": False,
            "execution_changed": False,
            "proxy_substitution_permitted": False,
            "calendar_2025_values_accessed": False,
            "calendar_2025_outcomes_calculated": False,
            "calendar_2026_accessed": False,
        },
        "next_milestone": {
            "code": "V2_M6_CALENDAR_2025_HOLDOUT",
            "authorized": False,
            "blocked": True,
            "blocker": "BLOCKED_MISSING_ZN_2025",
        },
    }
    output["shortlist_hash"] = canonical_hash(output)
    return output


def _verify_no_holdout_access(shortlist: Mapping[str, Any]) -> None:
    if shortlist["calendar_2025"]["values_opened"] is not False:
        raise ValueError("V2 M5 shortlist opened calendar-2025 values")
    if shortlist["calendar_2025"]["outcomes_calculated"] is not False:
        raise ValueError("V2 M5 shortlist calculated holdout outcomes")
    guardrails = shortlist["guardrails"]
    if guardrails["calendar_2025_values_accessed"] is not False:
        raise ValueError("V2 M5 guardrail says holdout values were accessed")
    if guardrails["calendar_2025_outcomes_calculated"] is not False:
        raise ValueError("V2 M5 guardrail says holdout outcomes were calculated")


def _progress(stage: str, **values: Any) -> None:
    print(
        json.dumps(json_ready({"stage": stage, **values}), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
