from __future__ import annotations

import argparse
import json
import tempfile
from collections.abc import Mapping
from pathlib import Path
from typing import Any

import run_gold_casebook_relationship_discovery as utility

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.backtesting.casebook_discovery_v2_relationships import (
    embedded_manifest_hash,
)
from gold_intel.backtesting.casebook_discovery_v2_shortlist import (
    CANDIDATE_CODE,
    SHORTLIST_SCHEMA_VERSION,
    SHORTLIST_VERSION,
    metadata_readiness,
    validate_shortlist_definition,
)


def main() -> None:
    args = _parser().parse_args()
    research_path = Path(args.research_manifest)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite immutable V2 M5 bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    research = _load_json(research_path)
    research_hash = _verify_manifest(research, label="V2 M5 manifest")
    validate_shortlist_definition(research)
    contract = _load_json(Path(args.contract_manifest))
    contract_hash = _verify_manifest(contract, label="V2 contract manifest")
    execution = _load_json(Path(args.execution_manifest))
    execution_hash = _verify_manifest(
        execution,
        label="execution manifest",
    )
    _verify_contract_and_execution(
        research,
        contract=contract,
        contract_hash=contract_hash,
        execution_hash=execution_hash,
    )
    sources = _verify_research_sources(
        research,
        milestone_3_root=Path(args.milestone_3_bundle),
        milestone_4_root=Path(args.milestone_4_bundle),
    )
    coverage = _load_json(Path(args.coverage))
    coverage_hash = _verify_coverage_hash(coverage)
    if coverage_hash != research["holdout_source_readiness"]["coverage_data_hash"]:
        raise ValueError("V2 M5 points to another coverage audit")
    _verify_metadata_only_coverage(coverage)
    readiness = metadata_readiness(coverage)
    if readiness["all_readiness_gates_passed"]:
        raise ValueError("Frozen M5 source unexpectedly reports holdout ready")
    _progress(
        "V2_M5_SOURCES_AND_METADATA_VERIFIED",
        research_manifest_hash=research_hash,
        contract_manifest_hash=contract_hash,
        milestone_4_verdict=sources["milestone_4_verdict"],
        readiness_status=readiness["status"],
        calendar_2025_values_accessed=False,
    )

    m4_results = sources["milestone_4_results"]
    aggregate = m4_results["aggregate_forward"]
    shortlist: dict[str, Any] = {
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
    shortlist["shortlist_hash"] = canonical_hash(shortlist)

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        shortlist_path = staging / "shortlist.json"
        utility._write_json(shortlist_path, shortlist)
        artifacts = [
            {
                "path": "shortlist.json",
                "sha256": utility._sha256(shortlist_path),
                "bytes": shortlist_path.stat().st_size,
                "document_hash": shortlist["shortlist_hash"],
            }
        ]
        bundle: dict[str, Any] = {
            "shortlist_version": SHORTLIST_VERSION,
            "schema_version": SHORTLIST_SCHEMA_VERSION,
            "governing_contract": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
            "milestone": "V2_M5_SHORTLIST_FREEZE",
            "status": shortlist["status"],
            "source": {
                "research_manifest_hash": research_hash,
                "contract_manifest_hash": contract_hash,
                "execution_manifest_hash": execution_hash,
                "coverage_data_hash": coverage_hash,
                "milestone_3_bundle_hash": sources["milestone_3_bundle_hash"],
                "milestone_4_bundle_hash": sources["milestone_4_bundle_hash"],
                "milestone_4_results_hash": sources["milestone_4_results_hash"],
            },
            "artifacts": artifacts,
            "integrity": {
                "source_documents_verified": 8,
                "frozen_candidates": 1,
                "new_york_candidates": 0,
                "calendar_2025_values_accessed": False,
                "calendar_2025_outcomes_calculated": False,
                "calendar_2026_accessed": False,
                "execution_changed": False,
                "candidate_retuned": False,
            },
        }
        bundle["manifest_hash"] = canonical_hash(bundle)
        utility._write_json(staging / "manifest.json", bundle)
        staging.rename(output)

    _progress(
        "V2_M5_SHORTLIST_FROZEN",
        output=str(output),
        bundle_manifest_hash=bundle["manifest_hash"],
        shortlist_hash=shortlist["shortlist_hash"],
        candidate_codes=[CANDIDATE_CODE],
        readiness_status=readiness["status"],
        calendar_2025_values_accessed=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Freeze the V2 Milestone 5 candidate shortlist and exact "
            "calendar-2025 gates without accessing holdout values."
        )
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
    parser.add_argument(
        "--output",
        default=("research_artifacts/gold_casebook_discovery_v2_shortlist_v01"),
    )
    return parser


def _verify_contract_and_execution(
    research: Mapping[str, Any],
    *,
    contract: Mapping[str, Any],
    contract_hash: str,
    execution_hash: str,
) -> None:
    if research["contract"]["manifest_hash"] != contract_hash:
        raise ValueError("V2 M5 points to another contract")
    if research["source"]["execution_manifest_hash"] != execution_hash:
        raise ValueError("V2 M5 points to another execution manifest")
    candidate = research["candidates"][0]
    expected = contract["post_hoc_candidate"]
    for key in (
        "candidate_code",
        "rule_table",
        "session",
        "threshold",
        "tuning_permitted",
    ):
        if candidate[key] != expected[key]:
            raise ValueError(f"V2 M5 candidate changed: {key}")
    if contract["candidate_budget"]["post_hoc_london_zn_may_consume_one_london_slot"] is not True:
        raise ValueError("Contract no longer permits the London candidate")


def _verify_research_sources(
    research: Mapping[str, Any],
    *,
    milestone_3_root: Path,
    milestone_4_root: Path,
) -> dict[str, Any]:
    m3 = _load_json(milestone_3_root / "manifest.json")
    m3_hash = _verify_manifest(m3, label="V2 M3 bundle manifest")
    if m3_hash != research["source"]["milestone_3_bundle_hash"]:
        raise ValueError("V2 M5 points to another M3 bundle")
    rankings = _load_json(milestone_3_root / "rankings.json")
    _verify_document_hash(
        rankings,
        hash_field="rankings_hash",
        label="V2 M3 rankings",
    )
    if int(rankings["summary"]["discovery_leads"]) != int(
        research["source"]["milestone_3_discovery_leads"]
    ):
        raise ValueError("V2 M5 M3 lead count changed")

    m4 = _load_json(milestone_4_root / "manifest.json")
    m4_hash = _verify_manifest(m4, label="V2 M4 bundle manifest")
    if m4_hash != research["source"]["milestone_4_bundle_hash"]:
        raise ValueError("V2 M5 points to another M4 bundle")
    results = _load_json(milestone_4_root / "walk_forward_results.json")
    results_hash = _verify_document_hash(
        results,
        hash_field="results_hash",
        label="V2 M4 results",
    )
    if results_hash != research["source"]["milestone_4_results_hash"]:
        raise ValueError("V2 M5 points to another M4 result")
    if results["gate_evaluation"]["verdict"] != research["source"]["milestone_4_verdict"]:
        raise ValueError("V2 M5 M4 verdict changed")
    if not results["gate_evaluation"]["passed"]:
        raise ValueError("V2 M5 candidate did not pass M4")
    validation = _load_json(milestone_4_root / "semantic_validation.json")
    validation_hash = _verify_document_hash(
        validation,
        hash_field="validation_hash",
        label="V2 M4 semantic validation",
    )
    if validation_hash != research["source"]["milestone_4_semantic_validation_hash"]:
        raise ValueError("V2 M5 points to another M4 validation")
    if validation["result"] != "PASS_SEMANTIC_VALIDATION":
        raise ValueError("V2 M4 semantic validation did not pass")
    return {
        "milestone_3_bundle_hash": m3_hash,
        "milestone_4_bundle_hash": m4_hash,
        "milestone_4_results_hash": results_hash,
        "milestone_4_verdict": results["gate_evaluation"]["verdict"],
        "milestone_4_results": results,
    }


def _verify_metadata_only_coverage(coverage: Mapping[str, Any]) -> None:
    audit = coverage["audit_boundary"]
    if audit["access_class"] != "METADATA_ONLY":
        raise ValueError("Coverage source is not metadata-only")
    forbidden = (
        "holdout_ohlc_or_market_values_read",
        "holdout_feature_values_calculated",
        "holdout_outcomes_calculated",
        "holdout_feature_outcome_joins_calculated",
        "holdout_charts_inspected",
    )
    if any(audit[key] is not False for key in forbidden):
        raise ValueError("Coverage source accessed a forbidden holdout value")


def _verify_coverage_hash(coverage: Mapping[str, Any]) -> str:
    supplied = str(coverage["data_hash"])
    content = {
        key: value for key, value in coverage.items() if key not in {"generated_at", "data_hash"}
    }
    if canonical_hash(content) != supplied:
        raise ValueError("V2 coverage data hash mismatch")
    return supplied


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
    content = {key: value for key, value in document.items() if key != hash_field}
    if canonical_hash(content) != supplied:
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
