from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import (
    CASEBOOK_VERSION,
    canonical_hash,
    finalize_record,
    json_ready,
)
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
    feature_coverage,
    fit_tertile_thresholds,
    materialize_feature,
    relationship_rank_key,
)

DISCOVERY_VERSION = "GOLD_CASEBOOK_RELATIONSHIP_DISCOVERY_V0_1"
DISCOVERY_SCHEMA_VERSION = "gold-casebook-relationship-schema-0.1.0"
SESSION_CODES = ("LONDON", "NEW_YORK")
DEVELOPMENT_START = datetime(2021, 8, 1, tzinfo=UTC)
DEVELOPMENT_END = datetime(2024, 1, 1, tzinfo=UTC)
ACTIONABLE_STRUCTURE_KINDS = {
    "BREAK_OF_STRUCTURE_BULLISH",
    "BREAK_OF_STRUCTURE_BEARISH",
    "MARKET_STRUCTURE_SHIFT_BULLISH",
    "MARKET_STRUCTURE_SHIFT_BEARISH",
    "ACCEPTANCE_ABOVE_RESISTANCE",
    "ACCEPTANCE_BELOW_SUPPORT",
    "REJECTION_BELOW_SUPPORT",
    "REJECTION_ABOVE_RESISTANCE",
    "TRAPPED_BREAKOUT_SHORTS",
    "TRAPPED_BREAKOUT_LONGS",
    "RETEST_HELD_ABOVE_RESISTANCE",
    "RETEST_HELD_BELOW_SUPPORT",
}
TIMEFRAME_MINUTES = {
    "15m": 15,
    "1h": 60,
    "4h": 240,
}


@dataclass(frozen=True, slots=True)
class FeatureSpec:
    feature_id: str
    family_code: str
    transform: str
    sessions: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SessionSource:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    decision_state: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class RawDevelopmentCase:
    source: SessionSource
    raw_features: Mapping[str, RawFeature]
    outcome: CaseOutcome
    chronological_half: str


def main() -> None:
    args = _parser().parse_args()
    research_manifest_path = Path(args.research_manifest)
    casebook_root = Path(args.casebook_bundle)
    baseline_root = Path(args.baseline_bundle)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite immutable discovery bundle: {output}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    research_manifest = _load_json(research_manifest_path)
    research_hash = _verify_hashed_document(
        research_manifest,
        hash_field="manifest_hash",
        label="relationship research manifest",
    )
    _verify_research_manifest(research_manifest)
    feature_registry = _declared_feature_registry(research_manifest)
    if len(feature_registry) != 88:
        raise ValueError(
            f"Frozen feature universe changed: {len(feature_registry)} != 88"
        )

    casebook_manifest = _load_json(casebook_root / "manifest.json")
    casebook_hash = _verify_hashed_document(
        casebook_manifest,
        hash_field="manifest_hash",
        label="casebook manifest",
    )
    baseline_manifest = _load_json(baseline_root / "manifest.json")
    baseline_hash = _verify_hashed_document(
        baseline_manifest,
        hash_field="manifest_hash",
        label="baseline manifest",
    )
    baseline_results = _load_json(baseline_root / "results.json")
    baseline_results_hash = _verify_hashed_document(
        baseline_results,
        hash_field="results_hash",
        label="baseline results",
    )
    _verify_source_chain(
        research_manifest=research_manifest,
        casebook_hash=casebook_hash,
        baseline_hash=baseline_hash,
        baseline_results_hash=baseline_results_hash,
        baseline_manifest=baseline_manifest,
    )

    source_artifacts = {
        name: _artifact(casebook_manifest, name)
        for name in (
            "sessions.jsonl.gz",
            "fundamentals.jsonl.gz",
            "positioning.jsonl.gz",
            "structure_snapshots.jsonl.gz",
            "cross_market_snapshots.jsonl.gz",
        )
    }
    for name, artifact in source_artifacts.items():
        _verify_file_hash(casebook_root / name, artifact["sha256"])
    baseline_ledger = _artifact(baseline_manifest, "trades.jsonl.gz")
    _verify_file_hash(
        baseline_root / baseline_ledger["path"],
        baseline_ledger["sha256"],
    )
    _progress(
        "FROZEN_SOURCES_VERIFIED",
        research_manifest_hash=research_hash,
        casebook_manifest_hash=casebook_hash,
        baseline_manifest_hash=baseline_hash,
        source_artifact_hashes=6,
    )

    session_sources = _load_development_sessions(
        casebook_root / "sessions.jsonl.gz"
    )
    outcomes = _load_development_outcomes(
        baseline_root / baseline_ledger["path"],
        execution_manifest_hash=research_manifest["source"][
            "execution_manifest_hash"
        ],
    )
    if set(session_sources) != set(outcomes):
        raise ValueError("Development cases and baseline outcomes do not match")
    joins = {
        "fundamental": {
            str(item.decision_state["fundamental_snapshot_id"])
            for item in session_sources.values()
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
    fundamentals = _load_records_by_ids(
        casebook_root / "fundamentals.jsonl.gz",
        wanted=joins["fundamental"],
        expected_type="FUNDAMENTAL_SNAPSHOT",
    )
    positioning = _load_records_by_ids(
        casebook_root / "positioning.jsonl.gz",
        wanted=joins["positioning"],
        expected_type="POSITIONING_REPORT",
    )
    structures = _load_records_by_ids(
        casebook_root / "structure_snapshots.jsonl.gz",
        wanted=joins["structure"],
        expected_type="STRUCTURE_SNAPSHOT",
    )
    cross_market = _load_records_by_ids(
        casebook_root / "cross_market_snapshots.jsonl.gz",
        wanted=joins["cross"],
        expected_type="CROSS_MARKET_SNAPSHOT",
    )

    raw_cases = _extract_raw_cases(
        session_sources,
        outcomes=outcomes,
        feature_registry=feature_registry,
        research_manifest=research_manifest,
        fundamentals=fundamentals,
        positioning=positioning,
        structures=structures,
        cross_market=cross_market,
    )
    development_cases, thresholds = _materialize_cases(
        raw_cases,
        feature_registry=feature_registry,
        research_manifest=research_manifest,
    )
    _progress(
        "DEVELOPMENT_FEATURES_MATERIALIZED",
        cases=len(development_cases),
        features=len(feature_registry),
        tertile_threshold_sets=sum(len(value) for value in thresholds.values()),
        latest_case=max(
            item.session_date.isoformat() for item in development_cases
        ),
    )

    relationships, development_baselines = _discover_relationships(
        development_cases,
        feature_registry=feature_registry,
        research_manifest=research_manifest,
        research_hash=research_hash,
    )
    _progress(
        "BOUNDED_RELATIONSHIPS_EVALUATED",
        candidates=len(relationships),
        support_eligible=sum(
            bool(item["support_eligible"]) for item in relationships
        ),
        discovery_leads=sum(
            bool(item["discovery_lead"]) for item in relationships
        ),
    )

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        features_path = staging / "development_features.jsonl.gz"
        feature_records = _write_feature_records(
            features_path,
            development_cases,
            research_hash=research_hash,
        )
        relationships_path = staging / "relationships.jsonl.gz"
        relationship_records = _write_relationship_records(
            relationships_path,
            relationships,
            research_hash=research_hash,
        )
        rankings = _build_rankings(
            development_cases,
            relationships=relationships,
            development_baselines=development_baselines,
            feature_registry=feature_registry,
            research_manifest=research_manifest,
            thresholds=thresholds,
            research_hash=research_hash,
            casebook_hash=casebook_hash,
            baseline_hash=baseline_hash,
            feature_artifact_sha=_sha256(features_path),
            relationship_artifact_sha=_sha256(relationships_path),
        )
        rankings["rankings_hash"] = canonical_hash(rankings)
        rankings_path = staging / "rankings.json"
        _write_json(rankings_path, rankings)

        artifacts = [
            _artifact_summary(
                features_path,
                record_count=feature_records,
                record_type="DEVELOPMENT_FEATURE_CASE",
            ),
            _artifact_summary(
                relationships_path,
                record_count=relationship_records,
                record_type="RELATIONSHIP_CANDIDATE",
            ),
            {
                "path": "rankings.json",
                "sha256": _sha256(rankings_path),
                "bytes": rankings_path.stat().st_size,
                "document_hash": rankings["rankings_hash"],
            },
        ]
        manifest: dict[str, Any] = {
            "discovery_version": DISCOVERY_VERSION,
            "schema_version": DISCOVERY_SCHEMA_VERSION,
            "governing_contract": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
            "milestone": "4_RELATIONSHIP_DISCOVERY",
            "source": {
                "research_manifest_hash": research_hash,
                "casebook_manifest_hash": casebook_hash,
                "baseline_manifest_hash": baseline_hash,
            },
            "artifacts": artifacts,
            "integrity": {
                "source_artifact_hashes_verified": 6,
                "development_feature_record_hashes_written": feature_records,
                "relationship_record_hashes_written": relationship_records,
                "chronological_validation_2024_loaded": False,
                "calendar_2025_loaded": False,
                "execution_optimized": False,
                "undeclared_relationships_evaluated": False,
            },
        }
        manifest["manifest_hash"] = canonical_hash(manifest)
        _write_json(staging / "manifest.json", manifest)
        staging.rename(output)

    _progress(
        "RELATIONSHIP_DISCOVERY_BUNDLE_COMPLETE",
        output=str(output),
        manifest_hash=manifest["manifest_hash"],
        rankings_hash=rankings["rankings_hash"],
        relationship_candidates=relationship_records,
        discovery_leads=rankings["summary"]["discovery_leads"],
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate only the frozen Milestone 4 point-in-time Gold casebook "
            "relationships on 2021-2023 development data."
        )
    )
    parser.add_argument(
        "--research-manifest",
        default=(
            "research_manifests/"
            "gold_casebook_relationship_discovery_v01.json"
        ),
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
        "--output",
        default="research_artifacts/gold_casebook_relationships_v01",
    )
    return parser


def _verify_research_manifest(manifest: Mapping[str, Any]) -> None:
    if manifest["manifest_version"] != DISCOVERY_VERSION:
        raise ValueError("Unexpected discovery manifest version")
    if manifest["status"] != "FROZEN_BEFORE_FIRST_CONDITIONAL_RESULT":
        raise ValueError("Discovery manifest was not frozen before results")
    partitions = manifest["time_partitions"]
    if partitions["development"]["start_inclusive"] != DEVELOPMENT_START.isoformat():
        raise ValueError("Development start changed")
    if partitions["development"]["end_exclusive"] != DEVELOPMENT_END.isoformat():
        raise ValueError("Development end changed")
    if (
        partitions["chronological_validation_reserve"][
            "conditional_features_or_returns_loaded_in_milestone_4"
        ]
        is not False
    ):
        raise ValueError("2024 reserve is not locked")
    if partitions["locked_holdout"]["loaded"] is not False:
        raise ValueError("2025 holdout is not locked")
    if not all(bool(value) for value in manifest["prohibited"].values()):
        raise ValueError("A prohibited Milestone 4 action is not locked")


def _verify_source_chain(
    *,
    research_manifest: Mapping[str, Any],
    casebook_hash: str,
    baseline_hash: str,
    baseline_results_hash: str,
    baseline_manifest: Mapping[str, Any],
) -> None:
    source = research_manifest["source"]
    if source["casebook_manifest_hash"] != casebook_hash:
        raise ValueError("Research manifest points to another casebook")
    if source["baseline_manifest_hash"] != baseline_hash:
        raise ValueError("Research manifest points to another baseline")
    if source["baseline_results_hash"] != baseline_results_hash:
        raise ValueError("Research manifest points to other baseline results")
    ledger = _artifact(baseline_manifest, "trades.jsonl.gz")
    if source["baseline_trade_ledger_sha256"] != ledger["sha256"]:
        raise ValueError("Research manifest points to another trade ledger")


def _declared_feature_registry(
    manifest: Mapping[str, Any],
) -> dict[str, FeatureSpec]:
    output: dict[str, FeatureSpec] = {}
    families = {
        item["family_code"]: item for item in manifest["feature_universe"]
    }
    engine = families["FUNDAMENTAL_ENGINE"]
    for item in engine["features"]:
        _add_spec(
            output,
            FeatureSpec(
                feature_id=item["feature_id"],
                family_code=engine["family_code"],
                transform=item["transform"],
                sessions=SESSION_CODES,
            ),
        )
    for code in engine["component_direction_features"]:
        _add_spec(
            output,
            FeatureSpec(
                feature_id=f"component_{code.lower()}",
                family_code=engine["family_code"],
                transform=engine["component_transform"],
                sessions=SESSION_CODES,
            ),
        )

    series = families["FUNDAMENTAL_SERIES_CHANGE"]
    for item in series["features"]:
        _add_spec(
            output,
            FeatureSpec(
                feature_id=item["feature_id"],
                family_code=series["family_code"],
                transform=series["transform"],
                sessions=SESSION_CODES,
            ),
        )
    positioning = families["POSITIONING"]
    for item in positioning["features"]:
        _add_spec(
            output,
            FeatureSpec(
                feature_id=item["feature_id"],
                family_code=positioning["family_code"],
                transform=item["transform"],
                sessions=SESSION_CODES,
            ),
        )
    structure = families["MARKET_STRUCTURE"]
    for timeframe in structure["timeframes"]:
        for item in structure["features_per_timeframe"]:
            _add_spec(
                output,
                FeatureSpec(
                    feature_id=f"structure_{timeframe}_{item['suffix']}",
                    family_code=structure["family_code"],
                    transform=item["transform"],
                    sessions=SESSION_CODES,
                ),
            )
    tertiles = structure["tertile_features_for_timeframes"]
    for timeframe in tertiles["timeframes"]:
        for item in tertiles["features"]:
            _add_spec(
                output,
                FeatureSpec(
                    feature_id=f"structure_{timeframe}_{item['suffix']}",
                    family_code=structure["family_code"],
                    transform="TERTILE",
                    sessions=SESSION_CODES,
                ),
            )
    for timeframe in structure["recent_action_feature"]["timeframes"]:
        _add_spec(
            output,
            FeatureSpec(
                feature_id=f"structure_{timeframe}_recent_action",
                family_code=structure["family_code"],
                transform="CATEGORY",
                sessions=SESSION_CODES,
            ),
        )
    sessions = families["SESSION_AND_LIQUIDITY"]
    for item in sessions["features"]:
        _add_spec(
            output,
            FeatureSpec(
                feature_id=item["feature_id"],
                family_code=sessions["family_code"],
                transform=item["transform"],
                sessions=tuple(item["sessions"]),
            ),
        )
    cross = families["INTRADAY_CROSS_MARKET"]
    for instrument in cross["instruments"]:
        for horizon in cross["horizons"]:
            _add_spec(
                output,
                FeatureSpec(
                    feature_id=_cross_feature_id(instrument, horizon),
                    family_code=cross["family_code"],
                    transform=cross["transform"],
                    sessions=SESSION_CODES,
                ),
            )
    return output


def _add_spec(
    output: dict[str, FeatureSpec],
    spec: FeatureSpec,
) -> None:
    if spec.feature_id in output:
        raise ValueError(f"Duplicate declared feature: {spec.feature_id}")
    output[spec.feature_id] = spec


def _load_development_sessions(path: Path) -> dict[str, SessionSource]:
    output: dict[str, SessionSource] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2024-' in line:
                continue
            record = json.loads(line)
            if record["record_type"] != "SESSION_CASE":
                continue
            decision_at = _timestamp(record["decision_at"])
            if not DEVELOPMENT_START <= decision_at < DEVELOPMENT_END:
                continue
            _verify_source_record(record)
            if record["holdout_loaded"] is not False:
                raise ValueError(f"Session loads holdout: {record['record_id']}")
            case_id = str(record["record_id"])
            if case_id in output:
                raise ValueError(f"Duplicate development case: {case_id}")
            output[case_id] = SessionSource(
                case_id=case_id,
                case_record_hash=str(record["record_hash"]),
                session_code=str(record["session_code"]),
                session_date=date.fromisoformat(record["session_date"]),
                decision_at=decision_at,
                decision_state=record["decision_state"],
            )
    return output


def _load_development_outcomes(
    path: Path,
    *,
    execution_manifest_hash: str,
) -> dict[str, CaseOutcome]:
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
            session_date = date.fromisoformat(record["session_date"])
            if not date(2021, 8, 1) <= session_date < date(2024, 1, 1):
                continue
            _verify_source_record(record, require_casebook_version=False)
            if record["execution_manifest_hash"] != execution_manifest_hash:
                raise ValueError(
                    f"Baseline execution hash changed: {record['record_id']}"
                )
            control = str(record["control_code"])
            side = "LONG" if control == "ALWAYS_LONG" else "SHORT"
            case_id = str(record["case_id"])
            if side in trades[case_id]:
                raise ValueError(f"Duplicate {side} outcome: {case_id}")
            trades[case_id][side] = OutcomeTrade(
                side=side,
                net_pnl_usd=float(record["net_pnl_usd"]),
                net_return_basis_points=float(
                    record["net_return_basis_points"]
                ),
            )
    output: dict[str, CaseOutcome] = {}
    for case_id, values in trades.items():
        if set(values) != {"LONG", "SHORT"}:
            raise ValueError(f"Incomplete fixed outcomes: {case_id}")
        output[case_id] = CaseOutcome(
            long=values["LONG"],
            short=values["SHORT"],
        )
    return output


def _load_records_by_ids(
    path: Path,
    *,
    wanted: set[str],
    expected_type: str,
) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    if not wanted:
        return output
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            record_id = _extract_json_string(line, "record_id")
            if record_id not in wanted:
                continue
            record = json.loads(line)
            _verify_source_record(record)
            if record["record_type"] != expected_type:
                raise ValueError(
                    f"Unexpected joined record type: {record['record_id']}"
                )
            output[record_id] = record
            if len(output) == len(wanted):
                break
    missing = wanted - output.keys()
    if missing:
        raise ValueError(f"Missing joined {expected_type} records: {sorted(missing)[:5]}")
    return output


def _extract_raw_cases(
    session_sources: Mapping[str, SessionSource],
    *,
    outcomes: Mapping[str, CaseOutcome],
    feature_registry: Mapping[str, FeatureSpec],
    research_manifest: Mapping[str, Any],
    fundamentals: Mapping[str, Mapping[str, Any]],
    positioning: Mapping[str, Mapping[str, Any]],
    structures: Mapping[str, Mapping[str, Any]],
    cross_market: Mapping[str, Mapping[str, Any]],
) -> list[RawDevelopmentCase]:
    session_order: dict[str, list[SessionSource]] = {
        code: sorted(
            (
                source
                for source in session_sources.values()
                if source.session_code == code
            ),
            key=lambda item: (item.decision_at, item.case_id),
        )
        for code in SESSION_CODES
    }
    halves: dict[str, str] = {}
    for _code, sources in session_order.items():
        split = len(sources) // 2
        for index, source in enumerate(sources):
            halves[source.case_id] = "EARLY" if index < split else "LATE"

    output: list[RawDevelopmentCase] = []
    for source in sorted(
        session_sources.values(),
        key=lambda item: (item.decision_at, item.case_id),
    ):
        decision = source.decision_state
        fundamental = fundamentals[str(decision["fundamental_snapshot_id"])]
        structure = structures[str(decision["market_structure_snapshot_id"])]
        cross = cross_market[str(decision["cross_market_snapshot_id"])]
        positioning_id = decision["positioning_record_id"]
        position = (
            positioning[str(positioning_id)]
            if positioning_id is not None
            else None
        )
        _verify_join_clocks(
            source,
            fundamental=fundamental,
            structure=structure,
            cross=cross,
            positioning=position,
        )
        raw: dict[str, RawFeature] = {}
        _extract_fundamental_features(
            raw,
            record=fundamental,
            registry=feature_registry,
            research_manifest=research_manifest,
        )
        _extract_positioning_features(
            raw,
            record=position,
            registry=feature_registry,
        )
        _extract_structure_features(
            raw,
            record=structure,
            registry=feature_registry,
            decision_at=source.decision_at,
        )
        _extract_session_features(
            raw,
            source=source,
            registry=feature_registry,
        )
        _extract_cross_market_features(
            raw,
            record=cross,
            registry=feature_registry,
            research_manifest=research_manifest,
        )
        for feature_id, spec in feature_registry.items():
            if feature_id not in raw:
                raw[feature_id] = RawFeature(
                    feature_id=feature_id,
                    family_code=spec.family_code,
                    transform=spec.transform,
                    raw_value=None,
                    source_key=None,
                )
        if set(raw) != set(feature_registry):
            raise AssertionError("Extracted feature universe differs from manifest")
        output.append(
            RawDevelopmentCase(
                source=source,
                raw_features=raw,
                outcome=outcomes[source.case_id],
                chronological_half=halves[source.case_id],
            )
        )
    return output


def _extract_fundamental_features(
    output: dict[str, RawFeature],
    *,
    record: Mapping[str, Any],
    registry: Mapping[str, FeatureSpec],
    research_manifest: Mapping[str, Any],
) -> None:
    engine = record["engine_state"]
    base = {
        "macro_bias_label": engine["bias_label"],
        "macro_regime": engine["regime_label"],
        "reaction_function": engine["reaction_function"],
        "macro_score": engine["directional_score"],
        "macro_confidence": engine["confidence"],
    }
    for feature_id, value in base.items():
        _put_feature(
            output,
            registry=registry,
            feature_id=feature_id,
            value=value,
            source_key=str(record["record_id"]),
        )
    components = {item["code"]: item for item in engine["components"]}
    for code, component in components.items():
        feature_id = f"component_{code.lower()}"
        if feature_id not in registry:
            continue
        value = (
            component["direction"]
            if component["epistemic_status"] != "UNKNOWN"
            else None
        )
        _put_feature(
            output,
            registry=registry,
            feature_id=feature_id,
            value=value,
            source_key=canonical_hash(
                {
                    "code": code,
                    "epistemic_status": component["epistemic_status"],
                    "evidence": component["evidence"],
                }
            ),
        )
    series_family = next(
        item
        for item in research_manifest["feature_universe"]
        if item["family_code"] == "FUNDAMENTAL_SERIES_CHANGE"
    )
    for item in series_family["features"]:
        state = record["series_state"].get(item["series_code"])
        value = None
        source_key = None
        if state is not None and state["status"] == "READY":
            value = state.get(item["field"])
            source_key = state.get("record_id")
        _put_feature(
            output,
            registry=registry,
            feature_id=item["feature_id"],
            value=value,
            source_key=source_key,
        )


def _extract_positioning_features(
    output: dict[str, RawFeature],
    *,
    record: Mapping[str, Any] | None,
    registry: Mapping[str, FeatureSpec],
) -> None:
    values: dict[str, float | str | None] = {
        feature_id: None
        for feature_id, spec in registry.items()
        if spec.family_code == "POSITIONING"
    }
    report_id: str | None = None
    if record is not None:
        report_id = str(record["record_id"])
        calculated = record["calculated"]
        inferred = record["inferred"]
        denominator = float(record["open_interest"])
        values.update(
            {
                "cot_net_percentile": calculated[
                    "managed_money_net_percentile"
                ],
                "cot_net_change": _scaled(
                    calculated["managed_money_net_change"],
                    denominator,
                ),
                "cot_net_change_acceleration": _scaled(
                    calculated["managed_money_net_change_acceleration"],
                    denominator,
                ),
                "cot_open_interest_change": _scaled(
                    calculated["open_interest_change"],
                    denominator,
                ),
                "cot_producer_net": _scaled(
                    calculated["producer_net"],
                    denominator,
                ),
                "cot_crowding_state": inferred["crowding_state"],
                "cot_participation_state": inferred["participation_state"],
                "cot_long_liquidation_risk": inferred[
                    "long_liquidation_risk"
                ],
                "cot_short_covering_risk": inferred[
                    "short_covering_risk"
                ],
            }
        )
    for feature_id, value in values.items():
        _put_feature(
            output,
            registry=registry,
            feature_id=feature_id,
            value=value,
            source_key=report_id,
            cot_report_id=report_id,
        )


def _extract_structure_features(
    output: dict[str, RawFeature],
    *,
    record: Mapping[str, Any],
    registry: Mapping[str, FeatureSpec],
    decision_at: datetime,
) -> None:
    timeframes = {
        item["timeframe"]: item for item in record["timeframes"]
    }
    for timeframe in ("5m", "15m", "1h", "4h", "1d"):
        state = timeframes[timeframe]
        for suffix, field in (
            ("trend", "trend"),
            ("momentum", "momentum_atr"),
        ):
            feature_id = f"structure_{timeframe}_{suffix}"
            _put_feature(
                output,
                registry=registry,
                feature_id=feature_id,
                value=state.get(field),
                source_key=str(record["record_id"]),
            )
    for timeframe in ("15m", "1h", "4h"):
        state = timeframes[timeframe]
        _put_feature(
            output,
            registry=registry,
            feature_id=f"structure_{timeframe}_compression",
            value=state.get("compression_ratio"),
            source_key=str(record["record_id"]),
        )
        range_high = state.get("range_high")
        range_low = state.get("range_low")
        last_close = state.get("last_close")
        location = _range_location(last_close, range_low, range_high)
        _put_feature(
            output,
            registry=registry,
            feature_id=f"structure_{timeframe}_range_location",
            value=location,
            source_key=str(record["record_id"]),
        )
        action = _recent_structure_action(
            state["detections"],
            decision_at=decision_at,
            timeframe=timeframe,
        )
        _put_feature(
            output,
            registry=registry,
            feature_id=f"structure_{timeframe}_recent_action",
            value=action,
            source_key=str(record["record_id"]),
        )


def _extract_session_features(
    output: dict[str, RawFeature],
    *,
    source: SessionSource,
    registry: Mapping[str, FeatureSpec],
) -> None:
    windows = source.decision_state["windows"]
    asia = windows["asia"]
    prior = source.decision_state["prior_same_session"]
    prior_window = prior["window"] if prior is not None else None
    common = {
        "asia_return": _return(asia),
        "asia_range": asia.get("range"),
        "asia_close_location": _range_location(
            asia.get("close"),
            asia.get("low"),
            asia.get("high"),
        ),
        "prior_same_session_return": _return(prior_window),
        "prior_same_session_range": (
            prior_window.get("range") if prior_window is not None else None
        ),
    }
    for feature_id, value in common.items():
        source_key = (
            str(prior["case_id"])
            if feature_id.startswith("prior_") and prior is not None
            else None
            if feature_id.startswith("prior_")
            else str(asia.get("source_hash"))
        )
        _put_feature(
            output,
            registry=registry,
            feature_id=feature_id,
            value=value,
            source_key=source_key,
        )
    london = windows["london"]
    if source.session_code == "NEW_YORK" and london is not None:
        new_york_values = {
            "london_return_before_new_york": _return(london),
            "london_range_before_new_york": london.get("range"),
            "london_close_location": _range_location(
                london.get("close"),
                london.get("low"),
                london.get("high"),
            ),
            "london_range_vs_asia_range": _ratio(
                london.get("range"),
                asia.get("range"),
            ),
            "new_york_price_vs_asia_range": _range_relation(
                london.get("close"),
                asia.get("low"),
                asia.get("high"),
            ),
        }
        for feature_id, value in new_york_values.items():
            _put_feature(
                output,
                registry=registry,
                feature_id=feature_id,
                value=value,
                source_key=str(london.get("source_hash")),
            )


def _extract_cross_market_features(
    output: dict[str, RawFeature],
    *,
    record: Mapping[str, Any],
    registry: Mapping[str, FeatureSpec],
    research_manifest: Mapping[str, Any],
) -> None:
    cross_family = next(
        item
        for item in research_manifest["feature_universe"]
        if item["family_code"] == "INTRADAY_CROSS_MARKET"
    )
    for instrument in cross_family["instruments"]:
        state = record["instruments"].get(instrument)
        for horizon in cross_family["horizons"]:
            feature_id = _cross_feature_id(instrument, horizon)
            value = None
            source_key = None
            if state is not None and state["status"] == "READY":
                change = state["changes"].get(horizon)
                if change is not None and change["status"] == "READY":
                    value = change.get("percent_change")
                    source_key = (
                        f"{record['record_id']}|{instrument}|{horizon}|"
                        f"{state['source_record_key']}"
                    )
            _put_feature(
                output,
                registry=registry,
                feature_id=feature_id,
                value=value,
                source_key=source_key,
            )


def _put_feature(
    output: dict[str, RawFeature],
    *,
    registry: Mapping[str, FeatureSpec],
    feature_id: str,
    value: float | str | None,
    source_key: str | None,
    cot_report_id: str | None = None,
) -> None:
    if feature_id in output:
        raise ValueError(f"Feature extracted twice: {feature_id}")
    spec = registry[feature_id]
    output[feature_id] = RawFeature(
        feature_id=feature_id,
        family_code=spec.family_code,
        transform=spec.transform,
        raw_value=value,
        source_key=source_key,
        cot_report_id=cot_report_id,
    )


def _materialize_cases(
    raw_cases: Sequence[RawDevelopmentCase],
    *,
    feature_registry: Mapping[str, FeatureSpec],
    research_manifest: Mapping[str, Any],
) -> tuple[
    list[DevelopmentCase],
    dict[str, dict[str, dict[str, float | int]]],
]:
    tertile_ids = [
        feature_id
        for feature_id, spec in feature_registry.items()
        if spec.transform == "TERTILE"
    ]
    thresholds: dict[str, dict[str, dict[str, float | int]]] = {}
    for session_code in SESSION_CODES:
        session_raw = [
            item.raw_features
            for item in raw_cases
            if item.source.session_code == session_code
        ]
        thresholds[session_code] = fit_tertile_thresholds(
            session_raw,
            feature_ids=tertile_ids,
        )
    direction = research_manifest["transforms"]["DIRECTION_3"]
    sign = research_manifest["transforms"]["SIGN_3"]
    output: list[DevelopmentCase] = []
    for item in raw_cases:
        observations: dict[str, FeatureObservation] = {}
        for feature_id, raw in item.raw_features.items():
            spec = feature_registry[feature_id]
            eligible_session = item.source.session_code in spec.sessions
            effective = (
                raw
                if eligible_session
                else RawFeature(
                    feature_id=raw.feature_id,
                    family_code=raw.family_code,
                    transform=raw.transform,
                    raw_value=None,
                    source_key=None,
                    cot_report_id=raw.cot_report_id,
                )
            )
            observations[feature_id] = materialize_feature(
                effective,
                tertile_thresholds=thresholds[item.source.session_code],
                direction_bearish_max=float(
                    direction["bearish_max_inclusive"]
                ),
                direction_bullish_min=float(
                    direction["bullish_min_inclusive"]
                ),
                sign_epsilon=float(sign["epsilon"]),
            )
        output.append(
            DevelopmentCase(
                case_id=item.source.case_id,
                case_record_hash=item.source.case_record_hash,
                session_code=item.source.session_code,
                session_date=item.source.session_date,
                decision_at=item.source.decision_at,
                chronological_half=item.chronological_half,
                features=observations,
                outcome=item.outcome,
            )
        )
    return output, thresholds


def _discover_relationships(
    cases: Sequence[DevelopmentCase],
    *,
    feature_registry: Mapping[str, FeatureSpec],
    research_manifest: Mapping[str, Any],
    research_hash: str,
) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
    support = research_manifest["support_and_stability"]
    uncertainty = research_manifest["uncertainty_and_multiplicity"]
    replications = int(uncertainty["confidence_interval"]["replications"])
    q_threshold = float(
        uncertainty["multiple_testing"]["reported_q_threshold"]
    )
    baselines: dict[str, dict[str, Any]] = {}
    relationships: list[dict[str, Any]] = []
    for session_code in SESSION_CODES:
        session_cases = sorted(
            (
                case
                for case in cases
                if case.session_code == session_code
            ),
            key=lambda item: (item.decision_at, item.case_id),
        )
        session_baselines = {
            side: direction_metrics(session_cases, side=side)
            for side in ("LONG", "SHORT")
        }
        baselines[session_code] = session_baselines
        session_records: list[dict[str, Any]] = []
        for feature_id, spec in sorted(feature_registry.items()):
            if session_code not in spec.sessions:
                continue
            grouped: dict[str, list[DevelopmentCase]] = defaultdict(list)
            for case in session_cases:
                state = case.features[feature_id].state
                if state != "UNKNOWN":
                    grouped[state].append(case)
            for state, selected in sorted(grouped.items()):
                session_records.append(
                    evaluate_relationship_state(
                        selected,
                        relationship_type="SINGLE",
                        relationship_id=feature_id,
                        state=state,
                        feature_ids=[feature_id],
                        total_session_cases=len(session_cases),
                        same_session_baselines=session_baselines,
                        manifest_hash=research_hash,
                        bootstrap_replications=replications,
                        minimum_cases=int(
                            support["single_state_min_cases"]
                        ),
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
                            support[
                                "cot_feature_or_interaction_min_distinct_reports"
                            ]
                        ),
                        development_years=support[
                            "development_year_buckets"
                        ],
                    )
                )
        for interaction in research_manifest["interactions"]:
            if session_code not in interaction["sessions"]:
                continue
            left = str(interaction["left"])
            right = str(interaction["right"])
            grouped_interactions: dict[
                str,
                list[DevelopmentCase],
            ] = defaultdict(list)
            for case in session_cases:
                left_state = case.features[left].state
                right_state = case.features[right].state
                if "UNKNOWN" in {left_state, right_state}:
                    continue
                state = f"{left}={left_state}|{right}={right_state}"
                grouped_interactions[state].append(case)
            for state, selected in sorted(grouped_interactions.items()):
                session_records.append(
                    evaluate_relationship_state(
                        selected,
                        relationship_type="INTERACTION",
                        relationship_id=interaction["interaction_id"],
                        state=state,
                        feature_ids=[left, right],
                        total_session_cases=len(session_cases),
                        same_session_baselines=session_baselines,
                        manifest_hash=research_hash,
                        bootstrap_replications=replications,
                        minimum_cases=int(
                            support["interaction_state_min_cases"]
                        ),
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
                            support[
                                "cot_feature_or_interaction_min_distinct_reports"
                            ]
                        ),
                        development_years=support[
                            "development_year_buckets"
                        ],
                    )
                )
        apply_benjamini_hochberg(session_records)
        apply_discovery_lead_flags(
            session_records,
            q_threshold=q_threshold,
        )
        ordered = sorted(session_records, key=relationship_rank_key)
        for rank, record in enumerate(ordered, start=1):
            record["session_rank"] = rank
        relationships.extend(ordered)
    return relationships, baselines


def _write_feature_records(
    path: Path,
    cases: Sequence[DevelopmentCase],
    *,
    research_hash: str,
) -> int:
    records = (
        finalize_record(
            {
                "record_type": "DEVELOPMENT_FEATURE_CASE",
                "record_id": f"FEATURES-{case.case_id}",
                "discovery_version": DISCOVERY_VERSION,
                "schema_version": DISCOVERY_SCHEMA_VERSION,
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
                    for feature_id, observation in sorted(
                        case.features.items()
                    )
                },
                "chronological_validation_2024_loaded": False,
                "calendar_2025_loaded": False,
            }
        )
        for case in sorted(
            cases,
            key=lambda item: (item.decision_at, item.case_id),
        )
    )
    return _write_jsonl_gzip(path, records)


def _write_relationship_records(
    path: Path,
    relationships: Sequence[Mapping[str, Any]],
    *,
    research_hash: str,
) -> int:
    records = (
        finalize_record(
            {
                "record_type": "RELATIONSHIP_CANDIDATE",
                "record_id": (
                    "REL-"
                    + canonical_hash(
                        {
                            "session": record["session_code"],
                            "type": record["relationship_type"],
                            "relationship": record["relationship_id"],
                            "state": record["state"],
                        }
                    )[:24]
                ),
                "discovery_version": DISCOVERY_VERSION,
                "schema_version": DISCOVERY_SCHEMA_VERSION,
                "epistemic_status": "CALCULATED",
                "research_manifest_hash": research_hash,
                **record,
                "chronological_validation_2024_loaded": False,
                "calendar_2025_loaded": False,
            }
        )
        for record in sorted(
            relationships,
            key=lambda item: (
                item["session_code"],
                int(item["session_rank"]),
            ),
        )
    )
    return _write_jsonl_gzip(path, records)


def _build_rankings(
    cases: Sequence[DevelopmentCase],
    *,
    relationships: Sequence[Mapping[str, Any]],
    development_baselines: Mapping[str, Any],
    feature_registry: Mapping[str, FeatureSpec],
    research_manifest: Mapping[str, Any],
    thresholds: Mapping[str, Any],
    research_hash: str,
    casebook_hash: str,
    baseline_hash: str,
    feature_artifact_sha: str,
    relationship_artifact_sha: str,
) -> dict[str, Any]:
    case_counts = Counter(case.session_code for case in cases)
    coverage = {
        session: feature_coverage(
            [
                case
                for case in cases
                if case.session_code == session
            ],
            feature_ids=[
                feature_id
                for feature_id, spec in feature_registry.items()
                if session in spec.sessions
            ],
        )
        for session in SESSION_CODES
    }
    summary_by_session: dict[str, dict[str, Any]] = {}
    top_ranked: dict[str, list[dict[str, Any]]] = {}
    leads: list[dict[str, Any]] = []
    for session in SESSION_CODES:
        selected = [
            item
            for item in relationships
            if item["session_code"] == session
        ]
        eligible = [
            item for item in selected if item["support_eligible"]
        ]
        session_leads = [
            item for item in selected if item["discovery_lead"]
        ]
        summary_by_session[session] = {
            "development_cases": case_counts[session],
            "candidate_states": len(selected),
            "support_eligible_states": len(eligible),
            "q_at_or_below_0_10": sum(
                item["benjamini_hochberg_q_value"] is not None
                and float(item["benjamini_hochberg_q_value"]) <= 0.1
                for item in eligible
            ),
            "stable_positive_after_cost_states": sum(
                item["stability_flag"]
                and float(
                    item["selected_metrics"][
                        "mean_net_return_basis_points"
                    ]
                )
                > 0
                for item in eligible
            ),
            "discovery_leads": len(session_leads),
        }
        top_ranked[session] = [
            _compact_relationship(item)
            for item in sorted(eligible, key=relationship_rank_key)[:25]
        ]
        leads.extend(_compact_relationship(item) for item in session_leads)
    return {
        "discovery_version": DISCOVERY_VERSION,
        "schema_version": DISCOVERY_SCHEMA_VERSION,
        "milestone": "4_RELATIONSHIP_DISCOVERY",
        "source": {
            "research_manifest_hash": research_hash,
            "casebook_manifest_hash": casebook_hash,
            "baseline_manifest_hash": baseline_hash,
        },
        "development_interval": {
            "start_inclusive": DEVELOPMENT_START,
            "end_exclusive": DEVELOPMENT_END,
        },
        "reserved_intervals": {
            "chronological_validation": "2024-01-01/2025-01-01",
            "locked_holdout": "calendar 2025",
            "conditional_features_or_returns_loaded": False,
        },
        "summary": {
            "declared_features": len(feature_registry),
            "declared_interactions": len(research_manifest["interactions"]),
            "development_cases": len(cases),
            "relationship_candidate_states": len(relationships),
            "support_eligible_states": sum(
                bool(item["support_eligible"]) for item in relationships
            ),
            "discovery_leads": sum(
                bool(item["discovery_lead"]) for item in relationships
            ),
            "by_session": summary_by_session,
        },
        "development_unconditional_baselines": development_baselines,
        "tertile_thresholds": thresholds,
        "feature_coverage": coverage,
        "top_ranked_support_eligible": top_ranked,
        "discovery_leads": sorted(
            leads,
            key=lambda item: (
                item["session_code"],
                item["session_rank"],
            ),
        ),
        "artifacts": {
            "development_features": {
                "path": "development_features.jsonl.gz",
                "sha256": feature_artifact_sha,
            },
            "relationships": {
                "path": "relationships.jsonl.gz",
                "sha256": relationship_artifact_sha,
            },
        },
        "research_guardrails": {
            "only_predeclared_features_and_interactions_evaluated": True,
            "fixed_milestone_3_execution_used": True,
            "entry_exit_stop_target_or_rr_optimized": False,
            "chronological_validation_2024_loaded": False,
            "calendar_2025_loaded": False,
            "machine_learning_used": False,
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
        "mean_net_return_basis_points": selected[
            "mean_net_return_basis_points"
        ],
        "mean_net_pnl_usd_per_ounce": selected[
            "mean_net_pnl_usd_per_ounce"
        ],
        "net_win_rate_pct": selected["net_win_rate_pct"],
        "profit_factor": selected["profit_factor"],
        "cluster_bootstrap_95pct_ci_basis_points": record[
            "cluster_bootstrap_95pct_ci_basis_points"
        ],
        "excess_mean_net_return_vs_baseline_bps": record[
            "excess_mean_net_return_vs_baseline_bps"
        ],
        "benjamini_hochberg_q_value": record[
            "benjamini_hochberg_q_value"
        ],
        "positive_development_year_count": record[
            "positive_development_year_count"
        ],
        "positive_chronological_half_count": record[
            "positive_chronological_half_count"
        ],
        "stability_flag": record["stability_flag"],
        "discovery_lead": record["discovery_lead"],
    }


def _verify_join_clocks(
    source: SessionSource,
    *,
    fundamental: Mapping[str, Any],
    structure: Mapping[str, Any],
    cross: Mapping[str, Any],
    positioning: Mapping[str, Any] | None,
) -> None:
    for record in (fundamental, structure, cross):
        available_at = _timestamp(record["available_at"])
        if available_at > source.decision_at:
            raise ValueError(
                f"Joined feature unavailable at decision: {source.case_id}"
            )
    if _timestamp(fundamental["as_of"]) != source.decision_at:
        raise ValueError(f"Fundamental as-of mismatch: {source.case_id}")
    if _timestamp(structure["as_of"]) != source.decision_at:
        raise ValueError(f"Structure as-of mismatch: {source.case_id}")
    if _timestamp(cross["as_of"]) != source.decision_at:
        raise ValueError(f"Cross-market as-of mismatch: {source.case_id}")
    if positioning is not None:
        if _timestamp(positioning["available_at"]) > source.decision_at:
            raise ValueError(f"COT availability mismatch: {source.case_id}")
        if _timestamp(positioning["publication_at"]) > source.decision_at:
            raise ValueError(f"COT publication mismatch: {source.case_id}")


def _recent_structure_action(
    detections: Sequence[Mapping[str, Any]],
    *,
    decision_at: datetime,
    timeframe: str,
) -> str:
    cutoff = decision_at - timedelta(
        minutes=TIMEFRAME_MINUTES[timeframe] * 12
    )
    eligible: list[tuple[datetime, str, str]] = []
    for detection in detections:
        if detection["kind"] not in ACTIONABLE_STRUCTURE_KINDS:
            continue
        direction = detection.get("direction")
        if direction not in {"BULLISH", "BEARISH"}:
            continue
        detected_at = _timestamp(detection["detected_at"])
        if cutoff <= detected_at <= decision_at:
            eligible.append(
                (detected_at, str(detection["kind"]), str(direction))
            )
    if not eligible:
        return "NONE"
    return max(eligible)[2]


def _return(window: Mapping[str, Any] | None) -> float | None:
    if window is None:
        return None
    open_price = window.get("open")
    close_price = window.get("close")
    if open_price is None or close_price is None or float(open_price) == 0:
        return None
    return (float(close_price) - float(open_price)) / float(open_price)


def _range_location(
    value: Any,
    low: Any,
    high: Any,
) -> float | None:
    if value is None or low is None or high is None:
        return None
    span = float(high) - float(low)
    if span <= 0:
        return None
    return (float(value) - float(low)) / span


def _range_relation(
    value: Any,
    low: Any,
    high: Any,
) -> str | None:
    if value is None or low is None or high is None:
        return None
    number = float(value)
    if number < float(low):
        return "BELOW"
    if number > float(high):
        return "ABOVE"
    return "INSIDE"


def _ratio(numerator: Any, denominator: Any) -> float | None:
    if numerator is None or denominator is None or float(denominator) == 0:
        return None
    return float(numerator) / float(denominator)


def _scaled(value: Any, denominator: float) -> float | None:
    if value is None or denominator == 0:
        return None
    return float(value) / denominator


def _cross_feature_id(instrument: str, horizon: str) -> str:
    normalized_instrument = (
        instrument.lower().replace(".", "_").replace("-", "_")
    )
    return f"cross_{normalized_instrument}_{horizon.lower()}"


def _extract_json_string(line: str, key: str) -> str | None:
    marker = f'"{key}":"'
    start = line.find(marker)
    if start < 0:
        return None
    value_start = start + len(marker)
    value_end = line.find('"', value_start)
    return line[value_start:value_end] if value_end >= 0 else None


def _verify_source_record(
    record: Mapping[str, Any],
    *,
    require_casebook_version: bool = True,
) -> None:
    if require_casebook_version and record["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError(f"Casebook version mismatch: {record['record_id']}")
    if record.get("holdout_loaded") is not False:
        raise ValueError(f"Source record loads holdout: {record['record_id']}")
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Source record hash mismatch: {record['record_id']}")


def _artifact(
    manifest: Mapping[str, Any],
    path: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == path]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not contain exactly one {path}")
    return matches[0]


def _artifact_summary(
    path: Path,
    *,
    record_count: int,
    record_type: str,
) -> dict[str, Any]:
    return {
        "path": path.name,
        "sha256": _sha256(path),
        "bytes": path.stat().st_size,
        "record_count": record_count,
        "record_type_counts": {record_type: record_count},
    }


def _write_jsonl_gzip(
    path: Path,
    records: Iterable[Mapping[str, Any]],
) -> int:
    count = 0
    with (
        path.open("wb") as raw,
        gzip.GzipFile(
            filename="",
            mode="wb",
            compresslevel=6,
            fileobj=raw,
            mtime=0,
        ) as compressed,
        io.TextIOWrapper(
            compressed,
            encoding="utf-8",
            newline="\n",
        ) as text,
    ):
        for record in records:
            text.write(
                json.dumps(
                    json_ready(record),
                    sort_keys=True,
                    separators=(",", ":"),
                )
                + "\n"
            )
            count += 1
    return count


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _verify_hashed_document(
    value: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    supplied = str(value[hash_field])
    unhashed = {key: item for key, item in value.items() if key != hash_field}
    calculated = canonical_hash(unhashed)
    if supplied != calculated:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _verify_file_hash(path: Path, expected: str) -> None:
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def _progress(stage: str, **values: Any) -> None:
    print(
        json.dumps(json_ready({"stage": stage, **values}), sort_keys=True),
        flush=True,
    )


if __name__ == "__main__":
    main()
