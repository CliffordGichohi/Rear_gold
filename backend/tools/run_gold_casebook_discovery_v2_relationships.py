from __future__ import annotations

import argparse
import gzip
import json
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

import run_gold_casebook_relationship_discovery as v1

from gold_intel.analytics.casebook import (
    canonical_hash,
    finalize_record,
    json_ready,
)
from gold_intel.backtesting.casebook_discovery_v2_relationships import (
    V2_RELATIONSHIP_SCHEMA_VERSION,
    V2_RELATIONSHIP_VERSION,
    apply_v2_stability_and_lead_flags,
    embedded_manifest_hash,
    feature_design_fingerprint,
    v2_relationship_rank_key,
)
from gold_intel.backtesting.casebook_relationships import (
    CaseOutcome,
    OutcomeTrade,
    feature_coverage,
)

DEVELOPMENT_START = datetime(2021, 8, 1, tzinfo=UTC)
DEVELOPMENT_END = datetime(2025, 1, 1, tzinfo=UTC)
SESSION_CODES = ("LONDON", "NEW_YORK")


def main() -> None:
    args = _parser().parse_args()
    research_path = Path(args.research_manifest)
    design_path = Path(args.feature_design_manifest)
    casebook_root = Path(args.casebook_bundle)
    outcome_root = Path(args.outcome_bundle)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite immutable V2 discovery bundle: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)

    research = _load_json(research_path)
    research_hash = _verify_manifest(research, label="V2 M3 manifest")
    _verify_research_freeze(research)
    design = _load_json(design_path)
    design_hash = _verify_manifest(design, label="feature-design manifest")
    _verify_design_reference(research, design=design, design_hash=design_hash)
    effective_design = {
        **research,
        "transforms": design["transforms"],
        "feature_universe": design["feature_universe"],
        "interactions": design["interactions"],
    }
    feature_registry = v1._declared_feature_registry(effective_design)
    if len(feature_registry) != int(research["feature_design"]["declared_feature_count"]):
        raise ValueError("Frozen feature count changed")

    casebook = _load_json(casebook_root / "manifest.json")
    casebook_hash = _verify_manifest(casebook, label="casebook manifest")
    outcomes_manifest = _load_json(outcome_root / "manifest.json")
    outcomes_bundle_hash = _verify_manifest(
        outcomes_manifest,
        label="V2 outcome bundle manifest",
    )
    _verify_source_chain(
        research,
        casebook_hash=casebook_hash,
        outcomes_bundle_hash=outcomes_bundle_hash,
        outcomes_manifest=outcomes_manifest,
    )
    source_names = (
        "sessions.jsonl.gz",
        "fundamentals.jsonl.gz",
        "positioning.jsonl.gz",
        "structure_snapshots.jsonl.gz",
        "cross_market_snapshots.jsonl.gz",
    )
    for name in source_names:
        artifact = v1._artifact(casebook, name)
        v1._verify_file_hash(casebook_root / name, str(artifact["sha256"]))
    outcome_artifact = v1._artifact(outcomes_manifest, "outcomes.jsonl.gz")
    outcome_path = outcome_root / str(outcome_artifact["path"])
    v1._verify_file_hash(outcome_path, str(outcome_artifact["sha256"]))
    _progress(
        "V2_M3_FROZEN_SOURCES_VERIFIED",
        research_manifest_hash=research_hash,
        feature_design_hash=design_hash,
        casebook_manifest_hash=casebook_hash,
        outcome_bundle_hash=outcomes_bundle_hash,
    )

    session_sources = _load_development_sessions(casebook_root / "sessions.jsonl.gz")
    outcomes, outcome_case_hashes = _load_development_outcomes(
        outcome_path,
        research=research,
        measurement_manifest_hash=str(outcomes_manifest["measurement_manifest_hash"]),
    )
    if set(session_sources) != set(outcomes):
        raise ValueError("Development case and outcome sets differ")
    for case_id, source in session_sources.items():
        if source.case_record_hash != outcome_case_hashes[case_id]:
            raise ValueError(f"Outcome-to-case hash mismatch: {case_id}")

    joins = {
        "fundamental": {
            str(item.decision_state["fundamental_snapshot_id"]) for item in session_sources.values()
        },
        "positioning": {
            str(item.decision_state["positioning_record_id"])
            for item in session_sources.values()
            if item.decision_state["positioning_record_id"] is not None
        },
        "structure": {
            str(item.decision_state["market_structure_snapshot_id"])
            for item in session_sources.values()
        },
        "cross": {
            str(item.decision_state["cross_market_snapshot_id"])
            for item in session_sources.values()
        },
    }
    fundamentals = v1._load_records_by_ids(
        casebook_root / "fundamentals.jsonl.gz",
        wanted=joins["fundamental"],
        expected_type="FUNDAMENTAL_SNAPSHOT",
    )
    positioning = v1._load_records_by_ids(
        casebook_root / "positioning.jsonl.gz",
        wanted=joins["positioning"],
        expected_type="POSITIONING_REPORT",
    )
    structures = v1._load_records_by_ids(
        casebook_root / "structure_snapshots.jsonl.gz",
        wanted=joins["structure"],
        expected_type="STRUCTURE_SNAPSHOT",
    )
    cross_market = v1._load_records_by_ids(
        casebook_root / "cross_market_snapshots.jsonl.gz",
        wanted=joins["cross"],
        expected_type="CROSS_MARKET_SNAPSHOT",
    )
    raw_cases = v1._extract_raw_cases(
        session_sources,
        outcomes=outcomes,
        feature_registry=feature_registry,
        research_manifest=effective_design,
        fundamentals=fundamentals,
        positioning=positioning,
        structures=structures,
        cross_market=cross_market,
    )
    cases, thresholds = v1._materialize_cases(
        raw_cases,
        feature_registry=feature_registry,
        research_manifest=effective_design,
    )
    _progress(
        "V2_M3_FEATURES_MATERIALIZED",
        cases=len(cases),
        features=len(feature_registry),
        latest_case=max(item.session_date.isoformat() for item in cases),
        tertile_threshold_sets=sum(len(value) for value in thresholds.values()),
    )

    relationships, baselines = v1._discover_relationships(
        cases,
        feature_registry=feature_registry,
        research_manifest=effective_design,
        research_hash=research_hash,
    )
    _apply_v2_policy(
        relationships,
        research=research,
    )
    _progress(
        "V2_M3_BOUNDED_RELATIONSHIPS_EVALUATED",
        candidate_states=len(relationships),
        discovery_leads=sum(bool(item["discovery_lead"]) for item in relationships),
        support_eligible=sum(bool(item["support_eligible"]) for item in relationships),
    )

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        features_path = staging / "development_features.jsonl.gz"
        feature_count = _write_feature_records(
            features_path,
            cases,
            research_hash=research_hash,
        )
        relationships_path = staging / "relationships.jsonl.gz"
        relationship_count = _write_relationship_records(
            relationships_path,
            relationships,
            research_hash=research_hash,
        )
        rankings = _build_rankings(
            cases,
            relationships=relationships,
            baselines=baselines,
            thresholds=thresholds,
            feature_registry=feature_registry,
            research=research,
            research_hash=research_hash,
            casebook_hash=casebook_hash,
            outcome_bundle_hash=outcomes_bundle_hash,
            features_sha=v1._sha256(features_path),
            relationships_sha=v1._sha256(relationships_path),
        )
        rankings["rankings_hash"] = canonical_hash(rankings)
        rankings_path = staging / "rankings.json"
        v1._write_json(rankings_path, rankings)

        artifacts = [
            v1._artifact_summary(
                features_path,
                record_count=feature_count,
                record_type="V2_DEVELOPMENT_FEATURE_CASE",
            ),
            v1._artifact_summary(
                relationships_path,
                record_count=relationship_count,
                record_type="V2_RELATIONSHIP_STATE",
            ),
            {
                "path": "rankings.json",
                "sha256": v1._sha256(rankings_path),
                "bytes": rankings_path.stat().st_size,
                "document_hash": rankings["rankings_hash"],
            },
        ]
        bundle: dict[str, Any] = {
            "discovery_version": V2_RELATIONSHIP_VERSION,
            "schema_version": V2_RELATIONSHIP_SCHEMA_VERSION,
            "governing_contract": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
            "milestone": "V2_M3_BOUNDED_RELATIONSHIP_DISCOVERY",
            "source": {
                "research_manifest_hash": research_hash,
                "feature_design_manifest_hash": design_hash,
                "feature_design_fingerprint": feature_design_fingerprint(design),
                "casebook_manifest_hash": casebook_hash,
                "outcome_bundle_hash": outcomes_bundle_hash,
                "outcome_ledger_sha256": outcome_artifact["sha256"],
            },
            "artifacts": artifacts,
            "integrity": {
                "source_artifact_hashes_verified": len(source_names) + 1,
                "development_feature_record_hashes_written": feature_count,
                "relationship_record_hashes_written": relationship_count,
                "development_2024_loaded": True,
                "calendar_2025_loaded": False,
                "calendar_2026_loaded": False,
                "execution_optimized": False,
                "undeclared_relationships_evaluated": False,
                "session_pairing_performed": False,
            },
        }
        bundle["manifest_hash"] = canonical_hash(bundle)
        v1._write_json(staging / "manifest.json", bundle)
        staging.rename(output)

    _progress(
        "V2_M3_RELATIONSHIP_BUNDLE_COMPLETE",
        output=str(output),
        manifest_hash=bundle["manifest_hash"],
        rankings_hash=rankings["rankings_hash"],
        relationship_states=relationship_count,
        discovery_leads=rankings["summary"]["discovery_leads"],
        calendar_2025_loaded=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run only the frozen V2 Milestone 3 bounded relationship screen "
            "on separate London and New York 2021-2024 development cases."
        )
    )
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_relationship_discovery_v01.json"),
    )
    parser.add_argument(
        "--feature-design-manifest",
        default="research_manifests/gold_casebook_relationship_discovery_v01.json",
    )
    parser.add_argument(
        "--casebook-bundle",
        default="research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--outcome-bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_outcome_atlas_v01"),
    )
    parser.add_argument(
        "--output",
        default=("research_artifacts/gold_casebook_discovery_v2_relationships_v01"),
    )
    return parser


def _verify_research_freeze(research: Mapping[str, Any]) -> None:
    if research["manifest_version"] != "GOLD_CASEBOOK_DISCOVERY_V2_RELATIONSHIP_MANIFEST_V0_1":
        raise ValueError("Unexpected V2 M3 manifest version")
    if research["status"] != "FROZEN_BEFORE_FIRST_CONDITIONAL_RESULT":
        raise ValueError("V2 M3 manifest is not pre-result frozen")
    if research["milestone"] != "V2_M3_BOUNDED_RELATIONSHIP_DISCOVERY":
        raise ValueError("Unexpected V2 milestone")
    if research["development_interval"] != {
        "end_exclusive": DEVELOPMENT_END.isoformat(),
        "independent_validation_credit": False,
        "start_inclusive": DEVELOPMENT_START.isoformat(),
    }:
        raise ValueError("V2 M3 development interval changed")
    if not all(bool(value) for value in research["prohibited"].values()):
        raise ValueError("One or more V2 M3 prohibitions is unlocked")
    if research["evaluation"]["sessions"] != list(SESSION_CODES):
        raise ValueError("Session universe changed")
    if research["evaluation"]["maximum_conditions_per_candidate"] != 2:
        raise ValueError("Candidate condition budget changed")


def _verify_design_reference(
    research: Mapping[str, Any],
    *,
    design: Mapping[str, Any],
    design_hash: str,
) -> None:
    reference = research["feature_design"]
    if design_hash != reference["source_manifest_hash"]:
        raise ValueError("Feature-design manifest hash changed")
    fingerprint = feature_design_fingerprint(design)
    if fingerprint != reference["design_fingerprint"]:
        raise ValueError("Feature-design fingerprint changed")
    if len(design["interactions"]) != int(reference["declared_interaction_count"]):
        raise ValueError("Frozen interaction count changed")


def _verify_source_chain(
    research: Mapping[str, Any],
    *,
    casebook_hash: str,
    outcomes_bundle_hash: str,
    outcomes_manifest: Mapping[str, Any],
) -> None:
    if research["source"]["casebook_manifest_hash"] != casebook_hash:
        raise ValueError("V2 M3 manifest points to another casebook")
    outcome = research["outcome"]
    if outcome["source_bundle_hash"] != outcomes_bundle_hash:
        raise ValueError("V2 M3 manifest points to another outcome bundle")
    artifact = v1._artifact(outcomes_manifest, "outcomes.jsonl.gz")
    if outcome["source_ledger_sha256"] != artifact["sha256"]:
        raise ValueError("V2 M3 manifest points to another outcome ledger")
    if (
        research["source"]["execution_manifest_hash"]
        != outcomes_manifest["source"]["execution_manifest_hash"]
    ):
        raise ValueError("Execution lineage changed")
    if outcomes_manifest["integrity"]["calendar_2025_loaded"] is not False:
        raise ValueError("Outcome source entered the locked holdout")


def _load_development_sessions(path: Path) -> dict[str, v1.SessionSource]:
    output: dict[str, v1.SessionSource] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Session source enters a locked calendar")
            record = json.loads(line)
            if record["record_type"] != "SESSION_CASE":
                continue
            decision_at = v1._timestamp(str(record["decision_at"]))
            if not DEVELOPMENT_START <= decision_at < DEVELOPMENT_END:
                continue
            v1._verify_source_record(record)
            case_id = str(record["record_id"])
            if case_id in output:
                raise ValueError(f"Duplicate development case: {case_id}")
            output[case_id] = v1.SessionSource(
                case_id=case_id,
                case_record_hash=str(record["record_hash"]),
                session_code=str(record["session_code"]),
                session_date=date.fromisoformat(str(record["session_date"])),
                decision_at=decision_at,
                decision_state=record["decision_state"],
            )
    return output


def _load_development_outcomes(
    path: Path,
    *,
    research: Mapping[str, Any],
    measurement_manifest_hash: str,
) -> tuple[dict[str, CaseOutcome], dict[str, str]]:
    outcomes: dict[str, CaseOutcome] = {}
    case_hashes: dict[str, str] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Outcome source enters a locked calendar")
            record = json.loads(line)
            v1._verify_source_record(record, require_casebook_version=False)
            if record["record_type"] != "V2_OUTCOME_CASE":
                raise ValueError("Unexpected V2 outcome record type")
            session_date = date.fromisoformat(str(record["session_date"]))
            if not date(2021, 8, 1) <= session_date < date(2025, 1, 1):
                continue
            if record["measurement_manifest_hash"] != measurement_manifest_hash:
                raise ValueError("Outcome measurement lineage changed")
            if record["execution_manifest_hash"] != research["source"]["execution_manifest_hash"]:
                raise ValueError("Outcome execution lineage changed")
            case_id = str(record["case_id"])
            if case_id in outcomes:
                raise ValueError(f"Duplicate V2 outcome: {case_id}")
            outcomes[case_id] = CaseOutcome(
                long=OutcomeTrade(
                    side="LONG",
                    net_pnl_usd=float(record["long_net_pnl_usd"]),
                    net_return_basis_points=float(record["long_net_return_basis_points"]),
                ),
                short=OutcomeTrade(
                    side="SHORT",
                    net_pnl_usd=float(record["short_net_pnl_usd"]),
                    net_return_basis_points=float(record["short_net_return_basis_points"]),
                ),
            )
            case_hashes[case_id] = str(record["case_record_hash"])
    return outcomes, case_hashes


def _apply_v2_policy(
    relationships: list[dict[str, Any]],
    *,
    research: Mapping[str, Any],
) -> None:
    apply_v2_stability_and_lead_flags(
        relationships,
        q_threshold=float(
            research["uncertainty_and_multiplicity"]["multiple_testing"]["reported_q_threshold"]
        ),
        minimum_positive_years=int(
            research["support_and_stability"]["minimum_development_years_with_10_cases"]
        ),
    )
    for session in SESSION_CODES:
        selected = [record for record in relationships if record["session_code"] == session]
        for rank, record in enumerate(
            sorted(selected, key=v2_relationship_rank_key),
            start=1,
        ):
            record["session_rank"] = rank
    relationships.sort(
        key=lambda item: (
            SESSION_CODES.index(str(item["session_code"])),
            int(item["session_rank"]),
        )
    )


def _write_feature_records(
    path: Path,
    cases: Sequence[Any],
    *,
    research_hash: str,
) -> int:
    records = (
        finalize_record(
            {
                "record_type": "V2_DEVELOPMENT_FEATURE_CASE",
                "record_id": f"V2-FEATURES-{case.case_id}",
                "discovery_version": V2_RELATIONSHIP_VERSION,
                "schema_version": V2_RELATIONSHIP_SCHEMA_VERSION,
                "epistemic_status": "CALCULATED",
                "research_manifest_hash": research_hash,
                "case_id": case.case_id,
                "case_record_hash": case.case_record_hash,
                "session_code": case.session_code,
                "session_date": case.session_date,
                "decision_at": case.decision_at,
                "chronological_half": case.chronological_half,
                "features": {
                    feature_id: {
                        "family_code": observation.family_code,
                        "transform": observation.transform,
                        "raw_value": observation.raw_value,
                        "state": observation.state,
                        "source_key": observation.source_key,
                        "cot_report_id": observation.cot_report_id,
                    }
                    for feature_id, observation in sorted(case.features.items())
                },
                "development_2024_loaded": True,
                "calendar_2025_loaded": False,
            }
        )
        for case in sorted(cases, key=lambda item: (item.decision_at, item.case_id))
    )
    return v1._write_jsonl_gzip(path, records)


def _write_relationship_records(
    path: Path,
    relationships: Sequence[Mapping[str, Any]],
    *,
    research_hash: str,
) -> int:
    records = (
        finalize_record(
            {
                "record_type": "V2_RELATIONSHIP_STATE",
                "record_id": (
                    "V2-REL-"
                    + canonical_hash(
                        {
                            "session": record["session_code"],
                            "type": record["relationship_type"],
                            "relationship": record["relationship_id"],
                            "state": record["state"],
                        }
                    )[:24]
                ),
                "discovery_version": V2_RELATIONSHIP_VERSION,
                "schema_version": V2_RELATIONSHIP_SCHEMA_VERSION,
                "epistemic_status": "CALCULATED",
                "research_manifest_hash": research_hash,
                **record,
                "development_2024_loaded": True,
                "calendar_2025_loaded": False,
            }
        )
        for record in relationships
    )
    return v1._write_jsonl_gzip(path, records)


def _build_rankings(
    cases: Sequence[Any],
    *,
    relationships: Sequence[Mapping[str, Any]],
    baselines: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    feature_registry: Mapping[str, Any],
    research: Mapping[str, Any],
    research_hash: str,
    casebook_hash: str,
    outcome_bundle_hash: str,
    features_sha: str,
    relationships_sha: str,
) -> dict[str, Any]:
    counts = Counter(case.session_code for case in cases)
    coverage = {
        session: feature_coverage(
            [case for case in cases if case.session_code == session],
            feature_ids=[
                feature_id
                for feature_id, spec in feature_registry.items()
                if session in spec.sessions
            ],
        )
        for session in SESSION_CODES
    }
    by_session: dict[str, Any] = {}
    top_ranked: dict[str, Any] = {}
    leads: list[dict[str, Any]] = []
    known: list[dict[str, Any]] = []
    for session in SESSION_CODES:
        selected = [record for record in relationships if record["session_code"] == session]
        eligible = [record for record in selected if record["support_eligible"]]
        session_leads = [record for record in selected if record["discovery_lead"]]
        by_session[session] = {
            "development_cases": counts[session],
            "candidate_states": len(selected),
            "support_eligible_states": len(eligible),
            "q_at_or_below_0_10": sum(
                item["benjamini_hochberg_q_value"] is not None
                and float(item["benjamini_hochberg_q_value"]) <= 0.10
                for item in eligible
            ),
            "bootstrap_lower_bound_above_zero": sum(
                float(item["cluster_bootstrap_95pct_ci_basis_points"][0]) > 0 for item in eligible
            ),
            "stable_positive_after_cost_states": sum(
                item["stability_flag"]
                and float(item["selected_metrics"]["mean_net_return_basis_points"]) > 0
                for item in eligible
            ),
            "discovery_leads": len(session_leads),
        }
        top_ranked[session] = [
            _compact_relationship(item)
            for item in sorted(selected, key=v2_relationship_rank_key)[:25]
        ]
        leads.extend(_compact_relationship(item) for item in session_leads)
        known.extend(
            _compact_relationship(item)
            for item in selected
            if item["known_hypothesis_lead_excluded"]
        )
    return {
        "discovery_version": V2_RELATIONSHIP_VERSION,
        "schema_version": V2_RELATIONSHIP_SCHEMA_VERSION,
        "milestone": "V2_M3_BOUNDED_RELATIONSHIP_DISCOVERY",
        "source": {
            "research_manifest_hash": research_hash,
            "casebook_manifest_hash": casebook_hash,
            "outcome_bundle_hash": outcome_bundle_hash,
        },
        "development_interval": research["development_interval"],
        "locked_intervals": {
            "calendar_2025_loaded": False,
            "calendar_2026_loaded": False,
        },
        "summary": {
            "declared_features": len(feature_registry),
            "declared_interactions": int(research["feature_design"]["declared_interaction_count"]),
            "development_cases": len(cases),
            "relationship_candidate_states": len(relationships),
            "support_eligible_states": sum(
                bool(item["support_eligible"]) for item in relationships
            ),
            "discovery_leads": sum(bool(item["discovery_lead"]) for item in relationships),
            "by_session": by_session,
        },
        "development_unconditional_baselines": baselines,
        "tertile_thresholds": thresholds,
        "feature_coverage": coverage,
        "top_ranked": top_ranked,
        "discovery_leads": sorted(
            leads,
            key=lambda item: (
                SESSION_CODES.index(str(item["session_code"])),
                int(item["session_rank"]),
            ),
        ),
        "known_hypothesis_results": sorted(
            known,
            key=lambda item: (
                SESSION_CODES.index(str(item["session_code"])),
                int(item["session_rank"]),
            ),
        ),
        "artifacts": {
            "development_features": {
                "path": "development_features.jsonl.gz",
                "sha256": features_sha,
            },
            "relationships": {
                "path": "relationships.jsonl.gz",
                "sha256": relationships_sha,
            },
        },
        "research_guardrails": {
            "only_frozen_features_and_interactions_evaluated": True,
            "fixed_execution_used": True,
            "entry_exit_stop_target_or_rr_optimized": False,
            "sessions_paired": False,
            "development_2024_loaded": True,
            "calendar_2025_loaded": False,
            "calendar_2026_loaded": False,
            "machine_learning_used": False,
            "return_target_used_for_ranking": False,
        },
        "verdict_policy": {
            "edge_claim_permitted": False,
            "next_milestone_authorized": False,
            "next_milestone": "V2_M4_INTERNAL_EXPANDING_WALK_FORWARD",
        },
    }


def _compact_relationship(record: Mapping[str, Any]) -> dict[str, Any]:
    selected = record["selected_metrics"]
    return {
        "session_rank": record["session_rank"],
        "session_code": record["session_code"],
        "relationship_type": record["relationship_type"],
        "relationship_id": record["relationship_id"],
        "state": record["state"],
        "feature_ids": record["feature_ids"],
        "selected_direction": record["selected_direction"],
        "case_count": record["case_count"],
        "prevalence_pct": record["prevalence_pct"],
        "iso_week_cluster_count": record["iso_week_cluster_count"],
        "distinct_cot_report_count": record["distinct_cot_report_count"],
        "mean_net_return_basis_points": selected["mean_net_return_basis_points"],
        "mean_net_pnl_usd_per_ounce": selected["mean_net_pnl_usd_per_ounce"],
        "net_win_rate_pct": selected["net_win_rate_pct"],
        "profit_factor": selected["profit_factor"],
        "cluster_bootstrap_95pct_ci_basis_points": record[
            "cluster_bootstrap_95pct_ci_basis_points"
        ],
        "excess_mean_net_return_vs_baseline_bps": record["excess_mean_net_return_vs_baseline_bps"],
        "benjamini_hochberg_q_value": record["benjamini_hochberg_q_value"],
        "positive_development_year_count": record["positive_development_year_count"],
        "positive_chronological_half_count": record["positive_chronological_half_count"],
        "stability_flag": record["stability_flag"],
        "hypothesis_classification": record["hypothesis_classification"],
        "known_hypothesis_lead_excluded": record["known_hypothesis_lead_excluded"],
        "lead_gate_failures": record["lead_gate_failures"],
        "discovery_lead": record["discovery_lead"],
    }


def _verify_manifest(document: Mapping[str, Any], *, label: str) -> str:
    supplied = str(document["manifest_hash"])
    if embedded_manifest_hash(document) != supplied:
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
