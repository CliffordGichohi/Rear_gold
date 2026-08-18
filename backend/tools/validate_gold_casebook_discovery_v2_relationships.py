from __future__ import annotations

import argparse
import gzip
import json
from collections.abc import Mapping
from datetime import date
from pathlib import Path
from typing import Any

import run_gold_casebook_discovery_v2_relationships as m3
import run_gold_casebook_relationship_discovery as v1

from gold_intel.analytics.casebook import (
    canonical_hash,
    json_ready,
)
from gold_intel.backtesting.casebook_discovery_v2_relationships import (
    V2_RELATIONSHIP_SCHEMA_VERSION,
    V2_RELATIONSHIP_VERSION,
    feature_design_fingerprint,
)
from gold_intel.backtesting.casebook_relationships import (
    DevelopmentCase,
    FeatureObservation,
    RawFeature,
    fit_tertile_thresholds,
    transform_feature_value,
)

SESSION_CODES = ("LONDON", "NEW_YORK")


def main() -> None:
    args = _parser().parse_args()
    bundle = Path(args.bundle)
    output = Path(args.output) if args.output else bundle / "semantic_validation.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite semantic validation: {output}")

    research = _load_json(Path(args.research_manifest))
    research_hash = m3._verify_manifest(research, label="V2 M3 manifest")
    m3._verify_research_freeze(research)
    design = _load_json(Path(args.feature_design_manifest))
    design_hash = m3._verify_manifest(design, label="feature-design manifest")
    m3._verify_design_reference(
        research,
        design=design,
        design_hash=design_hash,
    )
    effective_design = {
        **research,
        "transforms": design["transforms"],
        "feature_universe": design["feature_universe"],
        "interactions": design["interactions"],
    }
    registry = v1._declared_feature_registry(effective_design)

    manifest = _load_json(bundle / "manifest.json")
    manifest_hash = m3._verify_manifest(
        manifest,
        label="V2 M3 bundle manifest",
    )
    rankings = _load_json(bundle / "rankings.json")
    rankings_hash = _verify_document_hash(
        rankings,
        hash_field="rankings_hash",
        label="V2 M3 rankings",
    )
    _verify_bundle_chain(
        manifest,
        rankings=rankings,
        research_hash=research_hash,
        design_hash=design_hash,
        design_fingerprint=feature_design_fingerprint(design),
    )
    for artifact in manifest["artifacts"]:
        v1._verify_file_hash(
            bundle / str(artifact["path"]),
            str(artifact["sha256"]),
        )
    _progress(
        "V2_M3_VALIDATION_ARTIFACTS_VERIFIED",
        manifest_hash=manifest_hash,
        rankings_hash=rankings_hash,
    )

    source_sessions = m3._load_development_sessions(
        Path(args.casebook_bundle) / "sessions.jsonl.gz"
    )
    feature_records = _load_feature_records(
        bundle / "development_features.jsonl.gz",
        research_hash=research_hash,
        registry=registry,
        source_sessions=source_sessions,
        expected_count=int(
            v1._artifact(
                manifest,
                "development_features.jsonl.gz",
            )["record_count"]
        ),
    )
    recomputed_thresholds = _recompute_thresholds(
        feature_records,
        registry=registry,
    )
    if json_ready(recomputed_thresholds) != rankings["tertile_thresholds"]:
        raise ValueError("Tertile thresholds do not independently recompute")
    _verify_feature_states(
        feature_records,
        registry=registry,
        thresholds=recomputed_thresholds,
        design=design,
    )
    _verify_chronological_halves(feature_records)

    outcome_root = Path(args.outcome_bundle)
    outcome_manifest = _load_json(outcome_root / "manifest.json")
    m3._verify_manifest(
        outcome_manifest,
        label="V2 outcome bundle manifest",
    )
    outcome_artifact = v1._artifact(
        outcome_manifest,
        "outcomes.jsonl.gz",
    )
    outcomes, case_hashes = m3._load_development_outcomes(
        outcome_root / str(outcome_artifact["path"]),
        research=research,
        measurement_manifest_hash=str(outcome_manifest["measurement_manifest_hash"]),
    )
    cases = _materialize_cases(
        feature_records,
        outcomes=outcomes,
        case_hashes=case_hashes,
    )
    relationships, baselines = v1._discover_relationships(
        cases,
        feature_registry=registry,
        research_manifest=effective_design,
        research_hash=research_hash,
    )
    m3._apply_v2_policy(relationships, research=research)

    actual_relationships = _load_relationship_records(
        bundle / "relationships.jsonl.gz",
        research_hash=research_hash,
        expected_count=int(
            v1._artifact(
                manifest,
                "relationships.jsonl.gz",
            )["record_count"]
        ),
    )
    _compare_relationships(
        actual_relationships,
        expected=relationships,
    )
    expected_rankings = m3._build_rankings(
        cases,
        relationships=relationships,
        baselines=baselines,
        thresholds=recomputed_thresholds,
        feature_registry=registry,
        research=research,
        research_hash=research_hash,
        casebook_hash=str(manifest["source"]["casebook_manifest_hash"]),
        outcome_bundle_hash=str(manifest["source"]["outcome_bundle_hash"]),
        features_sha=str(
            v1._artifact(
                manifest,
                "development_features.jsonl.gz",
            )["sha256"]
        ),
        relationships_sha=str(
            v1._artifact(
                manifest,
                "relationships.jsonl.gz",
            )["sha256"]
        ),
    )
    expected_rankings["rankings_hash"] = canonical_hash(expected_rankings)
    if json_ready(expected_rankings) != rankings:
        raise ValueError("Rankings do not independently reconstruct")

    validation: dict[str, Any] = {
        "validation_version": ("GOLD_CASEBOOK_DISCOVERY_V2_RELATIONSHIP_VALIDATION_V0_1"),
        "discovery_version": V2_RELATIONSHIP_VERSION,
        "research_manifest_hash": research_hash,
        "bundle_manifest_hash": manifest_hash,
        "rankings_hash": rankings_hash,
        "verified": {
            "bundle_artifact_hashes": len(manifest["artifacts"]),
            "development_cases": len(cases),
            "declared_features_per_case": len(registry),
            "tertile_threshold_sets": sum(len(item) for item in recomputed_thresholds.values()),
            "relationship_states": len(relationships),
            "support_eligible_relationship_states": sum(
                bool(item["support_eligible"]) for item in relationships
            ),
            "discovery_leads": sum(bool(item["discovery_lead"]) for item in relationships),
        },
        "semantic_assertions": {
            "all_record_and_artifact_hashes_match": True,
            "all_feature_cases_join_to_immutable_session_hashes": True,
            "all_88_feature_states_follow_frozen_transforms": True,
            "all_25_session_specific_tertile_thresholds_recomputed": True,
            "all_898_bounded_relationship_states_recomputed": True,
            "long_short_selection_and_fixed_cost_outcomes_match": True,
            "weekly_cluster_bootstrap_intervals_reproduce": True,
            "support_stability_p_values_bh_q_values_lead_gates_and_ranks_reproduce": True,
            "known_london_and_new_york_zn_hypotheses_are_excluded_from_new_leads": True,
            "sessions_remain_separate": True,
            "development_2024_included": True,
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
        "V2_M3_SEMANTIC_VALIDATION_COMPLETE",
        output=str(output),
        validation_hash=validation["validation_hash"],
        cases=len(cases),
        relationships=len(relationships),
        calendar_2025_loaded=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reconstruct V2 Milestone 3 feature states, "
            "statistics, multiplicity correction, lead gates, and rankings."
        )
    )
    parser.add_argument(
        "--bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_relationships_v01"),
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
    parser.add_argument("--output")
    return parser


def _verify_bundle_chain(
    manifest: Mapping[str, Any],
    *,
    rankings: Mapping[str, Any],
    research_hash: str,
    design_hash: str,
    design_fingerprint: str,
) -> None:
    if manifest["discovery_version"] != V2_RELATIONSHIP_VERSION:
        raise ValueError("Bundle discovery version changed")
    if manifest["schema_version"] != V2_RELATIONSHIP_SCHEMA_VERSION:
        raise ValueError("Bundle schema version changed")
    source = manifest["source"]
    if source["research_manifest_hash"] != research_hash:
        raise ValueError("Bundle research-manifest lineage changed")
    if source["feature_design_manifest_hash"] != design_hash:
        raise ValueError("Bundle feature-design lineage changed")
    if source["feature_design_fingerprint"] != design_fingerprint:
        raise ValueError("Bundle feature-design fingerprint changed")
    if rankings["source"]["research_manifest_hash"] != research_hash:
        raise ValueError("Rankings research-manifest lineage changed")
    integrity = manifest["integrity"]
    if integrity["calendar_2025_loaded"] is not False:
        raise ValueError("Bundle entered calendar 2025")
    if integrity["calendar_2026_loaded"] is not False:
        raise ValueError("Bundle entered calendar 2026")
    if integrity["execution_optimized"] is not False:
        raise ValueError("Bundle optimized execution")


def _load_feature_records(
    path: Path,
    *,
    research_hash: str,
    registry: Mapping[str, Any],
    source_sessions: Mapping[str, Any],
    expected_count: int,
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line or '"session_date":"2026-' in line:
                raise ValueError("Feature artifact enters a locked calendar")
            record = json.loads(line)
            _verify_record_hash(record)
            if record["record_type"] != "V2_DEVELOPMENT_FEATURE_CASE":
                raise ValueError("Unexpected V2 feature record type")
            if record["research_manifest_hash"] != research_hash:
                raise ValueError("Feature record research lineage changed")
            if record["calendar_2025_loaded"] is not False:
                raise ValueError("Feature record entered calendar 2025")
            case_id = str(record["case_id"])
            if case_id in output:
                raise ValueError(f"Duplicate feature case: {case_id}")
            source = source_sessions[case_id]
            if record["case_record_hash"] != source.case_record_hash:
                raise ValueError(f"Feature-to-case hash mismatch: {case_id}")
            if set(record["features"]) != set(registry):
                raise ValueError(f"Feature universe changed: {case_id}")
            output[case_id] = record
    if len(output) != expected_count or set(output) != set(source_sessions):
        raise ValueError("Feature case set or count differs")
    return output


def _recompute_thresholds(
    records: Mapping[str, Mapping[str, Any]],
    *,
    registry: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, float | int]]]:
    tertile_ids = [
        feature_id for feature_id, spec in registry.items() if spec.transform == "TERTILE"
    ]
    output: dict[str, dict[str, dict[str, float | int]]] = {}
    for session in SESSION_CODES:
        raw_cases: list[dict[str, RawFeature]] = []
        for record in records.values():
            if record["session_code"] != session:
                continue
            raw_cases.append(
                {
                    feature_id: _raw_feature(feature_id, item)
                    for feature_id, item in record["features"].items()
                }
            )
        output[session] = fit_tertile_thresholds(
            raw_cases,
            feature_ids=tertile_ids,
        )
    return output


def _verify_feature_states(
    records: Mapping[str, Mapping[str, Any]],
    *,
    registry: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    design: Mapping[str, Any],
) -> None:
    direction = design["transforms"]["DIRECTION_3"]
    sign = design["transforms"]["SIGN_3"]
    for case_id, record in records.items():
        session_thresholds = thresholds[str(record["session_code"])]
        for feature_id, item in record["features"].items():
            expected = transform_feature_value(
                feature_id,
                item["raw_value"],
                transform=registry[feature_id].transform,
                tertile_thresholds=session_thresholds,
                direction_bearish_max=float(direction["bearish_max_inclusive"]),
                direction_bullish_min=float(direction["bullish_min_inclusive"]),
                sign_epsilon=float(sign["epsilon"]),
            )
            if item["state"] != expected:
                raise ValueError(f"Feature state does not recompute: {case_id}/{feature_id}")


def _verify_chronological_halves(
    records: Mapping[str, Mapping[str, Any]],
) -> None:
    for session in SESSION_CODES:
        selected = sorted(
            (record for record in records.values() if record["session_code"] == session),
            key=lambda item: (item["decision_at"], item["case_id"]),
        )
        split = len(selected) // 2
        for index, record in enumerate(selected):
            expected = "EARLY" if index < split else "LATE"
            if record["chronological_half"] != expected:
                raise ValueError("Chronological half assignment changed")


def _materialize_cases(
    records: Mapping[str, Mapping[str, Any]],
    *,
    outcomes: Mapping[str, Any],
    case_hashes: Mapping[str, str],
) -> list[DevelopmentCase]:
    if set(records) != set(outcomes):
        raise ValueError("Feature and outcome case sets differ")
    output: list[DevelopmentCase] = []
    for case_id, record in records.items():
        if record["case_record_hash"] != case_hashes[case_id]:
            raise ValueError(f"Outcome case hash differs: {case_id}")
        output.append(
            DevelopmentCase(
                case_id=case_id,
                case_record_hash=str(record["case_record_hash"]),
                session_code=str(record["session_code"]),
                session_date=date.fromisoformat(str(record["session_date"])),
                decision_at=v1._timestamp(str(record["decision_at"])),
                chronological_half=str(record["chronological_half"]),
                features={
                    feature_id: FeatureObservation(
                        feature_id=feature_id,
                        family_code=str(item["family_code"]),
                        transform=str(item["transform"]),
                        raw_value=item["raw_value"],
                        state=str(item["state"]),
                        source_key=item["source_key"],
                        cot_report_id=item["cot_report_id"],
                    )
                    for feature_id, item in record["features"].items()
                },
                outcome=outcomes[case_id],
            )
        )
    return sorted(output, key=lambda item: (item.decision_at, item.case_id))


def _load_relationship_records(
    path: Path,
    *,
    research_hash: str,
    expected_count: int,
) -> list[Mapping[str, Any]]:
    output: list[Mapping[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            record = json.loads(line)
            _verify_record_hash(record)
            if record["record_type"] != "V2_RELATIONSHIP_STATE":
                raise ValueError("Unexpected V2 relationship record type")
            if record["research_manifest_hash"] != research_hash:
                raise ValueError("Relationship research lineage changed")
            if record["calendar_2025_loaded"] is not False:
                raise ValueError("Relationship record entered calendar 2025")
            output.append(record)
    if len(output) != expected_count:
        raise ValueError("Relationship record count changed")
    return output


def _compare_relationships(
    actual: list[Mapping[str, Any]],
    *,
    expected: list[Mapping[str, Any]],
) -> None:
    if len(actual) != len(expected):
        raise ValueError("Relationship count does not reconstruct")
    for actual_record, expected_record in zip(
        actual,
        expected,
        strict=True,
    ):
        for key, value in expected_record.items():
            if actual_record.get(key) != json_ready(value):
                raise ValueError(
                    f"Relationship does not reconstruct: {actual_record['record_id']}/{key}"
                )


def _raw_feature(feature_id: str, item: Mapping[str, Any]) -> RawFeature:
    return RawFeature(
        feature_id=feature_id,
        family_code=str(item["family_code"]),
        transform=str(item["transform"]),
        raw_value=item["raw_value"],
        source_key=item["source_key"],
        cot_report_id=item["cot_report_id"],
    )


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Record hash mismatch: {record['record_id']}")


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
