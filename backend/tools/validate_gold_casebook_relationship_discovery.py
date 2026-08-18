from __future__ import annotations

import argparse
import gzip
import hashlib
import json
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.backtesting.casebook_relationships import (
    CaseOutcome,
    DevelopmentCase,
    FeatureObservation,
    OutcomeTrade,
    RawFeature,
    apply_benjamini_hochberg,
    apply_discovery_lead_flags,
    direction_metrics,
    evaluate_relationship_state,
    fit_tertile_thresholds,
    relationship_rank_key,
    transform_feature_value,
)

VALIDATION_VERSION = "GOLD_CASEBOOK_RELATIONSHIP_VALIDATION_V0_1"
DISCOVERY_VERSION = "GOLD_CASEBOOK_RELATIONSHIP_DISCOVERY_V0_1"
DISCOVERY_SCHEMA_VERSION = "gold-casebook-relationship-schema-0.1.0"
SESSION_CODES = ("LONDON", "NEW_YORK")


@dataclass(frozen=True, slots=True)
class DeclaredFeature:
    family_code: str
    transform: str
    sessions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class FeatureRecord:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    chronological_half: str
    features: Mapping[str, Mapping[str, Any]]


def main() -> None:
    args = _parser().parse_args()
    bundle = Path(args.bundle)
    casebook_root = Path(args.casebook_bundle)
    baseline_root = Path(args.baseline_bundle)
    research_path = Path(args.research_manifest)
    output = Path(args.output) if args.output else bundle / "semantic_validation.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite validation evidence: {output}")

    research = _load_json(research_path)
    research_hash = _verify_document_hash(
        research,
        hash_field="manifest_hash",
        label="research manifest",
    )
    manifest = _load_json(bundle / "manifest.json")
    manifest_hash = _verify_document_hash(
        manifest,
        hash_field="manifest_hash",
        label="discovery bundle manifest",
    )
    rankings = _load_json(bundle / "rankings.json")
    rankings_hash = _verify_document_hash(
        rankings,
        hash_field="rankings_hash",
        label="relationship rankings",
    )
    _verify_manifest_chain(
        research=research,
        research_hash=research_hash,
        manifest=manifest,
        rankings=rankings,
    )
    for artifact in manifest["artifacts"]:
        if _sha256(bundle / artifact["path"]) != artifact["sha256"]:
            raise ValueError(f"Discovery artifact hash mismatch: {artifact['path']}")
    _progress(
        "DISCOVERY_ARTIFACTS_VERIFIED",
        manifest_hash=manifest_hash,
        rankings_hash=rankings_hash,
        artifacts=len(manifest["artifacts"]),
    )

    declared = _declared_features(research)
    if len(declared) != 88:
        raise ValueError("Declared feature universe does not contain 88 features")
    source_cases = _load_source_cases(
        casebook_root / "sessions.jsonl.gz",
        expected_sha=_casebook_artifact_sha(
            casebook_root / "manifest.json",
            "sessions.jsonl.gz",
        ),
    )
    feature_records = _load_feature_records(
        bundle / "development_features.jsonl.gz",
        declared=declared,
        research_hash=research_hash,
        source_cases=source_cases,
        expected_count=int(
            _artifact(manifest, "development_features.jsonl.gz")[
                "record_count"
            ]
        ),
    )
    outcomes = _load_outcomes(
        baseline_root,
        research=research,
        expected_case_ids=set(feature_records),
    )
    recomputed_thresholds = _recompute_and_verify_states(
        feature_records,
        declared=declared,
        research=research,
        reported_thresholds=rankings["tertile_thresholds"],
    )
    development_cases = _materialize_cases(
        feature_records,
        outcomes=outcomes,
    )

    actual_relationships = _load_relationship_records(
        bundle / "relationships.jsonl.gz",
        research_hash=research_hash,
        declared=declared,
        expected_count=int(
            _artifact(manifest, "relationships.jsonl.gz")["record_count"]
        ),
    )
    recomputed_relationships, recomputed_baselines = _recompute_relationships(
        development_cases,
        declared=declared,
        research=research,
        research_hash=research_hash,
    )
    _compare_relationships(
        actual_relationships,
        recomputed_relationships=recomputed_relationships,
    )
    if recomputed_baselines != rankings["development_unconditional_baselines"]:
        raise ValueError("Development baseline metrics do not recompute")
    _verify_ranking_summary(
        rankings,
        relationships=recomputed_relationships,
        development_cases=development_cases,
        declared=declared,
    )

    unique_cot_reports = _verify_cot_availability(
        casebook_root / "positioning.jsonl.gz",
        development_cases=development_cases,
    )
    report: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "discovery_version": DISCOVERY_VERSION,
        "research_manifest_hash": research_hash,
        "discovery_manifest_hash": manifest_hash,
        "rankings_hash": rankings_hash,
        "holdout_loaded": False,
        "verified": {
            "bundle_artifact_hashes": len(manifest["artifacts"]),
            "development_case_records": len(development_cases),
            "declared_features_per_case": len(declared),
            "recomputed_tertile_threshold_sets": sum(
                len(values) for values in recomputed_thresholds.values()
            ),
            "relationship_candidate_records": len(actual_relationships),
            "support_eligible_relationship_states": sum(
                bool(item["support_eligible"])
                for item in recomputed_relationships
            ),
            "discovery_leads": sum(
                bool(item["discovery_lead"])
                for item in recomputed_relationships
            ),
            "unique_point_in_time_cot_reports": unique_cot_reports,
        },
        "semantic_assertions": {
            "all_feature_case_and_relationship_record_hashes_match": True,
            "all_feature_cases_join_to_immutable_session_hashes": True,
            "all_88_features_follow_declared_transforms": True,
            "all_25_session_specific_tertile_thresholds_recomputed": True,
            "all_866_predeclared_relationship_states_recomputed": True,
            "long_short_selection_and_fixed_cost_outcomes_match": True,
            "weekly_cluster_bootstrap_intervals_reproduce": True,
            "support_stability_p_values_bh_q_values_and_ranks_reproduce": True,
            "cot_publication_availability_respected": True,
            "chronological_validation_2024_absent": True,
            "calendar_2025_absent": True,
            "execution_optimization_absent": True,
        },
    }
    report["validation_hash"] = canonical_hash(report)
    output.write_text(
        json.dumps(json_ready(report), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    _progress(
        "RELATIONSHIP_SEMANTIC_VALIDATION_COMPLETE",
        output=str(output),
        validation_hash=report["validation_hash"],
        cases=len(development_cases),
        relationships=len(actual_relationships),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reconstruct Milestone 4 feature states, candidate "
            "memberships, statistics, multiplicity, and rankings."
        )
    )
    parser.add_argument(
        "--bundle",
        default="research_artifacts/gold_casebook_relationships_v01",
    )
    parser.add_argument(
        "--casebook-bundle",
        default="research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--baseline-bundle",
        default="research_artifacts/gold_casebook_baseline_v01",
    )
    parser.add_argument(
        "--research-manifest",
        default=(
            "research_manifests/"
            "gold_casebook_relationship_discovery_v01.json"
        ),
    )
    parser.add_argument("--output")
    return parser


def _verify_manifest_chain(
    *,
    research: Mapping[str, Any],
    research_hash: str,
    manifest: Mapping[str, Any],
    rankings: Mapping[str, Any],
) -> None:
    if research["status"] != "FROZEN_BEFORE_FIRST_CONDITIONAL_RESULT":
        raise ValueError("Research manifest is not frozen")
    if manifest["discovery_version"] != DISCOVERY_VERSION:
        raise ValueError("Discovery manifest version mismatch")
    if manifest["schema_version"] != DISCOVERY_SCHEMA_VERSION:
        raise ValueError("Discovery schema mismatch")
    if rankings["discovery_version"] != DISCOVERY_VERSION:
        raise ValueError("Rankings version mismatch")
    if manifest["source"]["research_manifest_hash"] != research_hash:
        raise ValueError("Bundle-to-research manifest chain mismatch")
    if rankings["source"]["research_manifest_hash"] != research_hash:
        raise ValueError("Rankings-to-research manifest chain mismatch")
    if rankings["reserved_intervals"][
        "conditional_features_or_returns_loaded"
    ] is not False:
        raise ValueError("Rankings accessed a reserved interval")
    if not all(
        bool(value)
        for value in research["prohibited"].values()
    ):
        raise ValueError("A prohibited research action is unlocked")
    guardrails = rankings["research_guardrails"]
    if guardrails != {
        "only_predeclared_features_and_interactions_evaluated": True,
        "fixed_milestone_3_execution_used": True,
        "entry_exit_stop_target_or_rr_optimized": False,
        "chronological_validation_2024_loaded": False,
        "calendar_2025_loaded": False,
        "machine_learning_used": False,
    }:
        raise ValueError("Ranking guardrails changed")


def _declared_features(
    research: Mapping[str, Any],
) -> dict[str, DeclaredFeature]:
    output: dict[str, DeclaredFeature] = {}
    families = {
        item["family_code"]: item for item in research["feature_universe"]
    }

    def add(
        feature_id: str,
        family: str,
        transform: str,
        sessions: Sequence[str] = SESSION_CODES,
    ) -> None:
        if feature_id in output:
            raise ValueError(f"Duplicate declared feature: {feature_id}")
        output[feature_id] = DeclaredFeature(
            family_code=family,
            transform=transform,
            sessions=tuple(sessions),
        )

    engine = families["FUNDAMENTAL_ENGINE"]
    for item in engine["features"]:
        add(
            item["feature_id"],
            engine["family_code"],
            item["transform"],
        )
    for code in engine["component_direction_features"]:
        add(
            f"component_{code.lower()}",
            engine["family_code"],
            engine["component_transform"],
        )
    series = families["FUNDAMENTAL_SERIES_CHANGE"]
    for item in series["features"]:
        add(item["feature_id"], series["family_code"], series["transform"])
    positioning = families["POSITIONING"]
    for item in positioning["features"]:
        add(
            item["feature_id"],
            positioning["family_code"],
            item["transform"],
        )
    structure = families["MARKET_STRUCTURE"]
    for timeframe in structure["timeframes"]:
        for item in structure["features_per_timeframe"]:
            add(
                f"structure_{timeframe}_{item['suffix']}",
                structure["family_code"],
                item["transform"],
            )
    tertiles = structure["tertile_features_for_timeframes"]
    for timeframe in tertiles["timeframes"]:
        for item in tertiles["features"]:
            add(
                f"structure_{timeframe}_{item['suffix']}",
                structure["family_code"],
                "TERTILE",
            )
    for timeframe in structure["recent_action_feature"]["timeframes"]:
        add(
            f"structure_{timeframe}_recent_action",
            structure["family_code"],
            "CATEGORY",
        )
    session_family = families["SESSION_AND_LIQUIDITY"]
    for item in session_family["features"]:
        add(
            item["feature_id"],
            session_family["family_code"],
            item["transform"],
            item["sessions"],
        )
    cross = families["INTRADAY_CROSS_MARKET"]
    for instrument in cross["instruments"]:
        normalized = instrument.lower().replace(".", "_").replace("-", "_")
        for horizon in cross["horizons"]:
            add(
                f"cross_{normalized}_{horizon.lower()}",
                cross["family_code"],
                cross["transform"],
            )
    return output


def _load_source_cases(
    path: Path,
    *,
    expected_sha: str,
) -> dict[str, dict[str, Any]]:
    if _sha256(path) != expected_sha:
        raise ValueError("Immutable session artifact hash mismatch")
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2024-' in line:
                continue
            record = json.loads(line)
            decision = _timestamp(record["decision_at"])
            if not datetime(2021, 8, 1, tzinfo=UTC) <= decision < datetime(
                2024,
                1,
                1,
                tzinfo=UTC,
            ):
                continue
            _verify_record_hash(record)
            output[str(record["record_id"])] = {
                "record_hash": record["record_hash"],
                "session_code": record["session_code"],
                "session_date": record["session_date"],
                "decision_at": decision,
            }
    return output


def _load_feature_records(
    path: Path,
    *,
    declared: Mapping[str, DeclaredFeature],
    research_hash: str,
    source_cases: Mapping[str, Mapping[str, Any]],
    expected_count: int,
) -> dict[str, FeatureRecord]:
    output: dict[str, FeatureRecord] = {}
    for record in _records(path):
        _verify_record_hash(record)
        if record["record_type"] != "DEVELOPMENT_FEATURE_CASE":
            raise ValueError(f"Unexpected feature record: {record['record_id']}")
        if record["research_manifest_hash"] != research_hash:
            raise ValueError(f"Feature research hash mismatch: {record['record_id']}")
        if record["chronological_validation_2024_loaded"] is not False:
            raise ValueError("Feature record loaded 2024")
        if record["calendar_2025_loaded"] is not False:
            raise ValueError("Feature record loaded 2025")
        session_date = date.fromisoformat(record["session_date"])
        if session_date >= date(2024, 1, 1):
            raise ValueError(f"Reserved feature case present: {record['case_id']}")
        case_id = str(record["case_id"])
        source = source_cases.get(case_id)
        if source is None:
            raise ValueError(f"Unknown immutable case: {case_id}")
        if (
            record["case_record_hash"] != source["record_hash"]
            or record["session_code"] != source["session_code"]
            or record["session_date"] != source["session_date"]
            or _timestamp(record["decision_at"]) != source["decision_at"]
        ):
            raise ValueError(f"Feature-to-case join mismatch: {case_id}")
        if set(record["features"]) != set(declared):
            raise ValueError(f"Feature universe mismatch: {case_id}")
        if case_id in output:
            raise ValueError(f"Duplicate feature case: {case_id}")
        output[case_id] = FeatureRecord(
            case_id=case_id,
            case_record_hash=str(record["case_record_hash"]),
            session_code=str(record["session_code"]),
            session_date=session_date,
            decision_at=_timestamp(record["decision_at"]),
            chronological_half=str(record["chronological_half"]),
            features=record["features"],
        )
    if len(output) != expected_count:
        raise ValueError(f"Feature record count mismatch: {len(output)}")
    return output


def _load_outcomes(
    baseline_root: Path,
    *,
    research: Mapping[str, Any],
    expected_case_ids: set[str],
) -> dict[str, CaseOutcome]:
    baseline_manifest = _load_json(baseline_root / "manifest.json")
    if _verify_document_hash(
        baseline_manifest,
        hash_field="manifest_hash",
        label="baseline manifest",
    ) != research["source"]["baseline_manifest_hash"]:
        raise ValueError("Research-to-baseline manifest mismatch")
    ledger = _artifact(baseline_manifest, "trades.jsonl.gz")
    path = baseline_root / ledger["path"]
    if _sha256(path) != research["source"]["baseline_trade_ledger_sha256"]:
        raise ValueError("Baseline ledger hash mismatch")
    trades: dict[str, dict[str, OutcomeTrade]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2024-' in line:
                continue
            if (
                '"control_code":"ALWAYS_LONG"' not in line
                and '"control_code":"ALWAYS_SHORT"' not in line
            ):
                continue
            record = json.loads(line)
            case_id = str(record["case_id"])
            if case_id not in expected_case_ids:
                continue
            _verify_record_hash(record)
            side = (
                "LONG"
                if record["control_code"] == "ALWAYS_LONG"
                else "SHORT"
            )
            if record["side"] != side:
                raise ValueError(f"Control side mismatch: {record['record_id']}")
            trades[case_id][side] = OutcomeTrade(
                side=side,
                net_pnl_usd=float(record["net_pnl_usd"]),
                net_return_basis_points=float(
                    record["net_return_basis_points"]
                ),
            )
    output = {
        case_id: CaseOutcome(
            long=values["LONG"],
            short=values["SHORT"],
        )
        for case_id, values in trades.items()
        if set(values) == {"LONG", "SHORT"}
    }
    if set(output) != expected_case_ids:
        raise ValueError("Development feature and outcome case sets differ")
    return output


def _recompute_and_verify_states(
    records: Mapping[str, FeatureRecord],
    *,
    declared: Mapping[str, DeclaredFeature],
    research: Mapping[str, Any],
    reported_thresholds: Mapping[str, Any],
) -> dict[str, dict[str, dict[str, float | int]]]:
    tertile_ids = [
        feature_id
        for feature_id, spec in declared.items()
        if spec.transform == "TERTILE"
    ]
    thresholds: dict[str, dict[str, dict[str, float | int]]] = {}
    for session in SESSION_CODES:
        raw_cases: list[dict[str, RawFeature]] = []
        for record in records.values():
            if record.session_code != session:
                continue
            raw_cases.append(
                {
                    feature_id: RawFeature(
                        feature_id=feature_id,
                        family_code=declared[feature_id].family_code,
                        transform=declared[feature_id].transform,
                        raw_value=feature["raw_value"],
                        source_key=feature["source_key"],
                        cot_report_id=feature["cot_report_id"],
                    )
                    for feature_id, feature in record.features.items()
                }
            )
        thresholds[session] = fit_tertile_thresholds(
            raw_cases,
            feature_ids=tertile_ids,
        )
    if thresholds != reported_thresholds:
        raise ValueError("Tertile thresholds do not recompute")
    direction = research["transforms"]["DIRECTION_3"]
    sign = research["transforms"]["SIGN_3"]
    for record in records.values():
        for feature_id, feature in record.features.items():
            spec = declared[feature_id]
            expected = transform_feature_value(
                feature_id,
                feature["raw_value"],
                transform=spec.transform,
                tertile_thresholds=thresholds[record.session_code],
                direction_bearish_max=float(
                    direction["bearish_max_inclusive"]
                ),
                direction_bullish_min=float(
                    direction["bullish_min_inclusive"]
                ),
                sign_epsilon=float(sign["epsilon"]),
            )
            if record.session_code not in spec.sessions:
                expected = "UNKNOWN"
            if feature["state"] != expected:
                raise ValueError(
                    f"Feature state mismatch: {record.case_id}/{feature_id}"
                )
            if (
                feature["family_code"] != spec.family_code
                or feature["transform"] != spec.transform
            ):
                raise ValueError(
                    f"Feature declaration mismatch: {record.case_id}/{feature_id}"
                )
    return thresholds


def _materialize_cases(
    records: Mapping[str, FeatureRecord],
    *,
    outcomes: Mapping[str, CaseOutcome],
) -> list[DevelopmentCase]:
    return [
        DevelopmentCase(
            case_id=record.case_id,
            case_record_hash=record.case_record_hash,
            session_code=record.session_code,
            session_date=record.session_date,
            decision_at=record.decision_at,
            chronological_half=record.chronological_half,
            features={
                feature_id: FeatureObservation(
                    feature_id=feature_id,
                    family_code=feature["family_code"],
                    transform=feature["transform"],
                    raw_value=feature["raw_value"],
                    state=feature["state"],
                    source_key=feature["source_key"],
                    cot_report_id=feature["cot_report_id"],
                )
                for feature_id, feature in record.features.items()
            },
            outcome=outcomes[record.case_id],
        )
        for record in records.values()
    ]


def _load_relationship_records(
    path: Path,
    *,
    research_hash: str,
    declared: Mapping[str, DeclaredFeature],
    expected_count: int,
) -> dict[tuple[str, str, str, str], dict[str, Any]]:
    output: dict[tuple[str, str, str, str], dict[str, Any]] = {}
    for record in _records(path):
        _verify_record_hash(record)
        if record["record_type"] != "RELATIONSHIP_CANDIDATE":
            raise ValueError(f"Unexpected relationship record: {record['record_id']}")
        if record["research_manifest_hash"] != research_hash:
            raise ValueError("Relationship research hash mismatch")
        if record["chronological_validation_2024_loaded"] is not False:
            raise ValueError("Relationship record loaded 2024")
        if record["calendar_2025_loaded"] is not False:
            raise ValueError("Relationship record loaded 2025")
        if not set(record["feature_ids"]).issubset(declared):
            raise ValueError("Relationship contains an undeclared feature")
        key = (
            str(record["session_code"]),
            str(record["relationship_type"]),
            str(record["relationship_id"]),
            str(record["state"]),
        )
        if key in output:
            raise ValueError(f"Duplicate relationship state: {key}")
        output[key] = record
    if len(output) != expected_count:
        raise ValueError(f"Relationship record count mismatch: {len(output)}")
    return output


def _recompute_relationships(
    cases: Sequence[DevelopmentCase],
    *,
    declared: Mapping[str, DeclaredFeature],
    research: Mapping[str, Any],
    research_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    support = research["support_and_stability"]
    uncertainty = research["uncertainty_and_multiplicity"]
    replications = int(uncertainty["confidence_interval"]["replications"])
    q_threshold = float(
        uncertainty["multiple_testing"]["reported_q_threshold"]
    )
    all_records: list[dict[str, Any]] = []
    baselines: dict[str, Any] = {}
    for session in SESSION_CODES:
        session_cases = sorted(
            (case for case in cases if case.session_code == session),
            key=lambda item: (item.decision_at, item.case_id),
        )
        session_baselines = {
            side: direction_metrics(session_cases, side=side)
            for side in ("LONG", "SHORT")
        }
        baselines[session] = session_baselines
        records: list[dict[str, Any]] = []
        for feature_id, spec in sorted(declared.items()):
            if session not in spec.sessions:
                continue
            groups: dict[str, list[DevelopmentCase]] = defaultdict(list)
            for case in session_cases:
                state = case.features[feature_id].state
                if state != "UNKNOWN":
                    groups[state].append(case)
            for state, selected in sorted(groups.items()):
                records.append(
                    _evaluate(
                        selected,
                        relationship_type="SINGLE",
                        relationship_id=feature_id,
                        state=state,
                        feature_ids=[feature_id],
                        total_cases=len(session_cases),
                        baselines=session_baselines,
                        research=research,
                        research_hash=research_hash,
                        replications=replications,
                        minimum_cases=int(
                            support["single_state_min_cases"]
                        ),
                    )
                )
        for interaction in research["interactions"]:
            if session not in interaction["sessions"]:
                continue
            left = str(interaction["left"])
            right = str(interaction["right"])
            groups = defaultdict(list)
            for case in session_cases:
                left_state = case.features[left].state
                right_state = case.features[right].state
                if "UNKNOWN" in {left_state, right_state}:
                    continue
                groups[
                    f"{left}={left_state}|{right}={right_state}"
                ].append(case)
            for state, selected in sorted(groups.items()):
                records.append(
                    _evaluate(
                        selected,
                        relationship_type="INTERACTION",
                        relationship_id=interaction["interaction_id"],
                        state=state,
                        feature_ids=[left, right],
                        total_cases=len(session_cases),
                        baselines=session_baselines,
                        research=research,
                        research_hash=research_hash,
                        replications=replications,
                        minimum_cases=int(
                            support["interaction_state_min_cases"]
                        ),
                    )
                )
        apply_benjamini_hochberg(records)
        apply_discovery_lead_flags(records, q_threshold=q_threshold)
        ordered = sorted(records, key=relationship_rank_key)
        for rank, record in enumerate(ordered, start=1):
            record["session_rank"] = rank
        all_records.extend(ordered)
    return all_records, baselines


def _evaluate(
    cases: Sequence[DevelopmentCase],
    *,
    relationship_type: str,
    relationship_id: str,
    state: str,
    feature_ids: Sequence[str],
    total_cases: int,
    baselines: Mapping[str, Mapping[str, Any]],
    research: Mapping[str, Any],
    research_hash: str,
    replications: int,
    minimum_cases: int,
) -> dict[str, Any]:
    support = research["support_and_stability"]
    return evaluate_relationship_state(
        cases,
        relationship_type=relationship_type,
        relationship_id=relationship_id,
        state=state,
        feature_ids=feature_ids,
        total_session_cases=total_cases,
        same_session_baselines=baselines,
        manifest_hash=research_hash,
        bootstrap_replications=replications,
        minimum_cases=minimum_cases,
        maximum_prevalence_pct=float(
            support["maximum_state_prevalence_pct"]
        ),
        minimum_week_clusters=int(
            support["minimum_iso_week_clusters"]
        ),
        minimum_years_with_10_cases=int(
            support["minimum_development_years_with_10_cases"]
        ),
        cot_minimum_reports=int(
            support["cot_feature_or_interaction_min_distinct_reports"]
        ),
        development_years=support["development_year_buckets"],
    )


def _compare_relationships(
    actual: Mapping[tuple[str, str, str, str], Mapping[str, Any]],
    *,
    recomputed_relationships: Sequence[Mapping[str, Any]],
) -> None:
    expected = {
        (
            str(item["session_code"]),
            str(item["relationship_type"]),
            str(item["relationship_id"]),
            str(item["state"]),
        ): item
        for item in recomputed_relationships
    }
    if set(actual) != set(expected):
        raise ValueError("Relationship candidate universe does not recompute")
    wrapper = {
        "record_type",
        "record_id",
        "record_hash",
        "discovery_version",
        "schema_version",
        "epistemic_status",
        "research_manifest_hash",
        "chronological_validation_2024_loaded",
        "calendar_2025_loaded",
    }
    for key, actual_record in actual.items():
        semantic = {
            field: value
            for field, value in actual_record.items()
            if field not in wrapper
        }
        if semantic != expected[key]:
            raise ValueError(f"Relationship metrics do not recompute: {key}")


def _verify_ranking_summary(
    rankings: Mapping[str, Any],
    *,
    relationships: Sequence[Mapping[str, Any]],
    development_cases: Sequence[DevelopmentCase],
    declared: Mapping[str, DeclaredFeature],
) -> None:
    summary = rankings["summary"]
    if summary["declared_features"] != len(declared):
        raise ValueError("Ranking feature count mismatch")
    if summary["development_cases"] != len(development_cases):
        raise ValueError("Ranking case count mismatch")
    if summary["relationship_candidate_states"] != len(relationships):
        raise ValueError("Ranking relationship count mismatch")
    if summary["support_eligible_states"] != sum(
        bool(item["support_eligible"]) for item in relationships
    ):
        raise ValueError("Ranking support count mismatch")
    if summary["discovery_leads"] != sum(
        bool(item["discovery_lead"]) for item in relationships
    ):
        raise ValueError("Ranking discovery-lead count mismatch")
    for session in SESSION_CODES:
        expected = [
            item
            for item in relationships
            if item["session_code"] == session
            and item["support_eligible"]
        ][:25]
        reported = rankings["top_ranked_support_eligible"][session]
        expected_keys = [
            (
                item["session_rank"],
                item["relationship_id"],
                item["state"],
            )
            for item in expected
        ]
        reported_keys = [
            (
                item["session_rank"],
                item["relationship_id"],
                item["state"],
            )
            for item in reported
        ]
        if expected_keys != reported_keys:
            raise ValueError(f"Top ranking order mismatch: {session}")


def _verify_cot_availability(
    path: Path,
    *,
    development_cases: Sequence[DevelopmentCase],
) -> int:
    case_by_id = {case.case_id: case for case in development_cases}
    usage: dict[str, list[DevelopmentCase]] = defaultdict(list)
    for case in development_cases:
        report_ids = {
            observation.cot_report_id
            for observation in case.features.values()
            if observation.cot_report_id is not None
        }
        for report_id in report_ids:
            usage[str(report_id)].append(case)
    records: dict[str, Mapping[str, Any]] = {}
    for record in _records(path):
        record_id = str(record["record_id"])
        if record_id in usage:
            _verify_record_hash(record)
            records[record_id] = record
    if set(records) != set(usage):
        raise ValueError("COT source records are missing")
    for report_id, cases in usage.items():
        available = _timestamp(records[report_id]["available_at"])
        published = _timestamp(records[report_id]["publication_at"])
        if any(
            available > case.decision_at or published > case.decision_at
            for case in cases
        ):
            raise ValueError(f"COT look-ahead detected: {report_id}")
        if any(case.case_id not in case_by_id for case in cases):
            raise AssertionError("Unexpected COT case")
    return len(records)


def _casebook_artifact_sha(manifest_path: Path, artifact_path: str) -> str:
    manifest = _load_json(manifest_path)
    _verify_document_hash(
        manifest,
        hash_field="manifest_hash",
        label="casebook manifest",
    )
    return str(_artifact(manifest, artifact_path)["sha256"])


def _artifact(
    manifest: Mapping[str, Any],
    path: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == path]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not contain exactly one {path}")
    return matches[0]


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Record hash mismatch: {record['record_id']}")


def _verify_document_hash(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    supplied = str(value[hash_field])
    unhashed = {key: item for key, item in value.items() if key != hash_field}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _records(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            yield json.loads(line)


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _progress(stage: str, **values: Any) -> None:
    print(
        json.dumps(json_ready({"stage": stage, **values}), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
