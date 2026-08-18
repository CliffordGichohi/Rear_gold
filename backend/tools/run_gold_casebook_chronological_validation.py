from __future__ import annotations

import argparse
import gzip
import hashlib
import io
import json
import math
import random
import shutil
import statistics
import tempfile
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gold_intel.analytics.casebook import (
    CASEBOOK_VERSION,
    canonical_hash,
    finalize_record,
    json_ready,
)
from gold_intel.backtesting.casebook_baseline import (
    BaselineTrade,
    calculate_baseline_metrics,
)
from gold_intel.backtesting.casebook_relationships import quantile_type_7
from gold_intel.backtesting.casebook_selector import (
    CASE_SPECIFICATION_VERSION,
    FEATURE_FAMILY,
    FEATURE_ID,
    FEATURE_TRANSFORM,
    SELECTOR_CODE,
    BiasDecision,
    SelectorFeature,
    select_universal_zn_4h_bias,
)
from gold_intel.backtesting.casebook_validation import (
    VALIDATION_SCHEMA_VERSION,
    VALIDATION_VERSION,
    apply_cost_multiplier,
    evaluate_validation_gates,
)

SESSION_CODES = ("LONDON", "NEW_YORK")
VALIDATION_START = date(2024, 1, 1)
VALIDATION_END = date(2025, 1, 1)
SESSION_TIMEZONES = {
    "LONDON": ZoneInfo("Europe/London"),
    "NEW_YORK": ZoneInfo("America/New_York"),
}


@dataclass(frozen=True, slots=True)
class ValidationCase:
    case_id: str
    case_record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    observation_end: datetime
    cross_market_snapshot_id: str
    chronological_half: str
    source_record: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MaterializedFeature:
    feature: SelectorFeature
    decision: BiasDecision
    cross_record_id: str
    cross_record_hash: str
    evidence: Mapping[str, Any]
    integrity_issues: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class SourceTrade:
    source_record: Mapping[str, Any]
    trade: BaselineTrade


def main() -> None:
    args = _parser().parse_args()
    validation_manifest_path = Path(args.validation_manifest)
    case_specification_path = Path(args.case_specification_manifest)
    casebook_root = Path(args.casebook_bundle)
    baseline_root = Path(args.baseline_bundle)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite immutable validation bundle: {output}"
        )

    validation_manifest = _load_json(validation_manifest_path)
    validation_manifest_hash = _verify_hashed_document(
        validation_manifest,
        hash_field="manifest_hash",
        label="chronological-validation manifest",
    )
    case_specification = _load_json(case_specification_path)
    case_specification_hash = _verify_hashed_document(
        case_specification,
        hash_field="manifest_hash",
        label="case-specification manifest",
    )
    _verify_validation_definition(
        validation_manifest,
        case_specification=case_specification,
        case_specification_hash=case_specification_hash,
    )
    source_manifests = _verify_sources(
        validation_manifest,
        casebook_root=casebook_root,
        baseline_root=baseline_root,
    )

    cases = _load_validation_cases(casebook_root / "sessions.jsonl.gz")
    cross_records = _load_cross_market_records(
        casebook_root / "cross_market_snapshots.jsonl.gz",
        wanted={case.cross_market_snapshot_id for case in cases.values()},
    )
    features = _materialize_features(cases, cross_records=cross_records)
    trades = _load_validation_trades(
        baseline_root / "trades.jsonl.gz",
        execution_manifest_hash=str(
            validation_manifest["execution"]["execution_manifest_hash"]
        ),
        cases=cases,
    )
    if set(trades) != set(cases):
        missing = sorted(cases.keys() - trades.keys())
        extra = sorted(trades.keys() - cases.keys())
        raise ValueError(
            f"Validation trade join mismatch; missing={missing[:3]}, extra={extra[:3]}"
        )

    decisions, selected_trades = _materialize_decisions(
        cases,
        features=features,
        trades=trades,
        validation_manifest_hash=validation_manifest_hash,
        case_specification_hash=case_specification_hash,
    )
    integrity_issues = [
        {
            "case_id": case_id,
            "issues": list(feature.integrity_issues),
        }
        for case_id, feature in sorted(features.items())
        if feature.integrity_issues
    ]
    results = _build_results(
        cases,
        features=features,
        source_trades=trades,
        selected_trades=selected_trades,
        validation_manifest=validation_manifest,
        validation_manifest_hash=validation_manifest_hash,
        case_specification_hash=case_specification_hash,
        integrity_issues=integrity_issues,
    )
    results["results_hash"] = canonical_hash(
        {
            key: value
            for key, value in results.items()
            if key != "results_hash"
        }
    )

    output.parent.mkdir(parents=True, exist_ok=True)
    staging = Path(
        tempfile.mkdtemp(
            prefix=f".{output.name}-",
            dir=output.parent,
        )
    )
    try:
        decisions_path = staging / "validation_decisions.jsonl.gz"
        decision_count = _write_jsonl_gzip(decisions_path, decisions)
        results_path = staging / "validation_results.json"
        _write_json(results_path, results)
        bundle_manifest = {
            "artifacts": [
                _artifact_summary(
                    decisions_path,
                    record_count=decision_count,
                    record_type="CHRONOLOGICAL_VALIDATION_DECISION",
                ),
                {
                    **_file_summary(results_path),
                    "document_hash": results["results_hash"],
                },
            ],
            "case_specification_version": CASE_SPECIFICATION_VERSION,
            "governing_contract": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
            "integrity": {
                "calendar_2024_conditional_data_loaded": True,
                "calendar_2025_loaded": False,
                "case_specification_changed": False,
                "execution_optimized": False,
                "feature_or_threshold_retuned": False,
                "source_artifact_hashes_verified": 5,
                "validation_decision_records_written": decision_count,
            },
            "manifest_hash": "",
            "milestone": "6_CHRONOLOGICAL_VALIDATION",
            "schema_version": VALIDATION_SCHEMA_VERSION,
            "selector_code": SELECTOR_CODE,
            "source": {
                "baseline_bundle_manifest_hash": source_manifests[
                    "baseline_manifest_hash"
                ],
                "case_specification_manifest_hash": case_specification_hash,
                "casebook_manifest_hash": source_manifests[
                    "casebook_manifest_hash"
                ],
                "chronological_validation_manifest_hash": (
                    validation_manifest_hash
                ),
            },
            "validation_version": VALIDATION_VERSION,
            "verdict": results["gate_evaluation"]["verdict"],
        }
        bundle_manifest["manifest_hash"] = canonical_hash(
            {
                key: value
                for key, value in bundle_manifest.items()
                if key != "manifest_hash"
            }
        )
        _write_json(staging / "manifest.json", bundle_manifest)
        staging.replace(output)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    print(
        json.dumps(
            {
                "bundle": str(output),
                "bundle_manifest_hash": bundle_manifest["manifest_hash"],
                "case_specification_manifest_hash": case_specification_hash,
                "failed_gate_ids": results["gate_evaluation"][
                    "failed_gate_ids"
                ],
                "results_hash": results["results_hash"],
                "validation_cases": len(cases),
                "validation_manifest_hash": validation_manifest_hash,
                "verdict": results["gate_evaluation"]["verdict"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Run the one-time frozen calendar-2024 validation.",
    )
    parser.add_argument(
        "--validation-manifest",
        default="research_manifests/gold_casebook_chronological_validation_v01.json",
    )
    parser.add_argument(
        "--case-specification-manifest",
        default="research_manifests/gold_casebook_case_specification_v01.json",
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
        default="research_artifacts/gold_casebook_chronological_validation_v01",
    )
    return parser


def _verify_validation_definition(
    validation: Mapping[str, Any],
    *,
    case_specification: Mapping[str, Any],
    case_specification_hash: str,
) -> None:
    if validation["manifest_version"] != VALIDATION_VERSION:
        raise ValueError("Chronological-validation version changed")
    if validation["status"] != "FROZEN_BEFORE_2024_CONDITIONAL_ACCESS":
        raise ValueError("Validation mechanics were not frozen before 2024 access")
    if (
        validation["source"]["case_specification_manifest_hash"]
        != case_specification_hash
    ):
        raise ValueError("Validation manifest points to another case specification")
    if case_specification["manifest_version"] != CASE_SPECIFICATION_VERSION:
        raise ValueError("Case-specification version changed")
    selector = validation["case_materialization"]["selector"]
    if selector != {
        "feature_id": FEATURE_ID,
        "rule_table": {
            "FLAT": "NO_BIAS",
            "NEGATIVE": "SHORT",
            "POSITIVE": "LONG",
            "UNKNOWN": "NO_BIAS",
        },
        "selector_code": SELECTOR_CODE,
        "sessions": list(SESSION_CODES),
        "universal_session_rule": True,
    }:
        raise ValueError("Frozen validation selector changed")
    if (
        validation["execution"]["execution_manifest_hash"]
        != case_specification["execution"]["execution_manifest_hash"]
    ):
        raise ValueError("Validation execution differs from case specification")
    gate_ids = [
        str(item["gate_id"])
        for item in validation["gate_evaluation"]["gates"]
    ]
    if gate_ids != [
        "G01_POINT_IN_TIME_INTEGRITY",
        "G02_DIRECTIONAL_SESSION_SUPPORT",
        "G03_DIRECTIONAL_STATE_SUPPORT",
        "G04_STATE_WEEK_SUPPORT",
        "G05_SESSION_MEAN_POSITIVE",
        "G06_SESSION_PROFIT_FACTOR",
        "G07_BEATS_BEST_UNCONDITIONAL_CONTROL",
        "G08_DIRECTION_MAPPING_CONSISTENCY",
        "G09_CHRONOLOGICAL_HALF_STABILITY",
        "G10_COST_STRESS",
    ]:
        raise ValueError("Frozen validation gate set changed")
    if validation["gate_evaluation"]["all_gates_required"] is not True:
        raise ValueError("Validation no longer requires every gate")
    if not all(bool(value) for value in validation["prohibited"].values()):
        raise ValueError("A prohibited validation action was enabled")
    if validation["time_partitions"]["locked_holdout"]["data_loaded"] is not False:
        raise ValueError("Calendar 2025 was opened")


def _verify_sources(
    validation: Mapping[str, Any],
    *,
    casebook_root: Path,
    baseline_root: Path,
) -> dict[str, str]:
    source = validation["source"]
    casebook_manifest = _load_json(casebook_root / "manifest.json")
    casebook_hash = _verify_hashed_document(
        casebook_manifest,
        hash_field="manifest_hash",
        label="casebook manifest",
    )
    if casebook_hash != source["casebook_manifest_hash"]:
        raise ValueError("Casebook manifest hash changed")
    sessions = _artifact(casebook_manifest, "sessions.jsonl.gz")
    cross = _artifact(casebook_manifest, "cross_market_snapshots.jsonl.gz")
    _verify_file_hash(casebook_root / "sessions.jsonl.gz", str(sessions["sha256"]))
    _verify_file_hash(
        casebook_root / "cross_market_snapshots.jsonl.gz",
        str(cross["sha256"]),
    )
    if sessions["sha256"] != source["casebook_sessions_sha256"]:
        raise ValueError("Session artifact hash changed")
    if cross["sha256"] != source["casebook_cross_market_sha256"]:
        raise ValueError("Cross-market artifact hash changed")

    baseline_manifest = _load_json(baseline_root / "manifest.json")
    baseline_hash = _verify_hashed_document(
        baseline_manifest,
        hash_field="manifest_hash",
        label="baseline manifest",
    )
    if baseline_hash != source["baseline_bundle_manifest_hash"]:
        raise ValueError("Baseline bundle manifest hash changed")
    trades = _artifact(baseline_manifest, "trades.jsonl.gz")
    _verify_file_hash(baseline_root / "trades.jsonl.gz", str(trades["sha256"]))
    if trades["sha256"] != source["baseline_trades_sha256"]:
        raise ValueError("Baseline trade artifact hash changed")
    return {
        "baseline_manifest_hash": baseline_hash,
        "casebook_manifest_hash": casebook_hash,
    }


def _load_validation_cases(path: Path) -> dict[str, ValidationCase]:
    raw_cases: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line:
                raise ValueError("Session artifact contains the locked holdout")
            if '"session_date":"2024-' not in line:
                continue
            record = json.loads(line)
            if record["record_type"] != "SESSION_CASE":
                continue
            _verify_casebook_record(record)
            session_date = date.fromisoformat(record["session_date"])
            if not VALIDATION_START <= session_date < VALIDATION_END:
                continue
            if record["holdout_loaded"] is not False:
                raise ValueError("Validation session opens calendar 2025")
            case_id = str(record["record_id"])
            if case_id in raw_cases:
                raise ValueError(f"Duplicate validation session: {case_id}")
            raw_cases[case_id] = record

    halves: dict[str, str] = {}
    for session_code in SESSION_CODES:
        ordered = sorted(
            (
                record
                for record in raw_cases.values()
                if record["session_code"] == session_code
            ),
            key=lambda item: (item["decision_at"], item["record_id"]),
        )
        split = len(ordered) // 2
        for index, record in enumerate(ordered):
            halves[str(record["record_id"])] = (
                "EARLY" if index < split else "LATE"
            )

    output: dict[str, ValidationCase] = {}
    for case_id, record in raw_cases.items():
        session_code = str(record["session_code"])
        if session_code not in SESSION_CODES:
            raise ValueError(f"Unexpected validation session: {session_code}")
        decision_at = _timestamp(record["decision_at"])
        observation_end = _timestamp(record["observation_end"])
        output[case_id] = ValidationCase(
            case_id=case_id,
            case_record_hash=str(record["record_hash"]),
            session_code=session_code,
            session_date=date.fromisoformat(record["session_date"]),
            decision_at=decision_at,
            observation_end=observation_end,
            cross_market_snapshot_id=str(
                record["decision_state"]["cross_market_snapshot_id"]
            ),
            chronological_half=halves[case_id],
            source_record=record,
        )
    if not output:
        raise ValueError("No calendar-2024 validation cases found")
    if {case.session_code for case in output.values()} != set(SESSION_CODES):
        raise ValueError("Validation cases do not cover both sessions")
    return output


def _load_cross_market_records(
    path: Path,
    *,
    wanted: set[str],
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            record_id = _extract_json_string(line, "record_id")
            if record_id not in wanted:
                continue
            record = json.loads(line)
            _verify_casebook_record(record)
            if record["record_type"] != "CROSS_MARKET_SNAPSHOT":
                raise ValueError(f"Unexpected joined record: {record_id}")
            as_of = _timestamp(record["as_of"])
            if as_of >= datetime(2025, 1, 1, tzinfo=UTC):
                raise ValueError("Cross-market join enters calendar 2025")
            if record_id in output:
                raise ValueError(f"Duplicate cross-market record: {record_id}")
            output[str(record_id)] = record
            if len(output) == len(wanted):
                break
    missing = wanted - output.keys()
    if missing:
        raise ValueError(f"Missing cross-market records: {sorted(missing)[:3]}")
    return output


def _materialize_features(
    cases: Mapping[str, ValidationCase],
    *,
    cross_records: Mapping[str, Mapping[str, Any]],
) -> dict[str, MaterializedFeature]:
    output: dict[str, MaterializedFeature] = {}
    for case_id, case in cases.items():
        cross = cross_records[case.cross_market_snapshot_id]
        issues: list[str] = []
        if _timestamp(cross["as_of"]) != case.decision_at:
            issues.append("CROSS_AS_OF_MISMATCH")
        if _timestamp(cross["available_at"]) > case.decision_at:
            issues.append("CROSS_NOT_AVAILABLE_AT_DECISION")
        timezone = SESSION_TIMEZONES[case.session_code]
        if case.decision_at.astimezone(timezone).strftime("%H:%M") != "08:00":
            issues.append("DECISION_CLOCK_MISMATCH")
        if case.observation_end.astimezone(timezone).strftime("%H:%M") != "12:00":
            issues.append("OBSERVATION_END_CLOCK_MISMATCH")

        state = cross["instruments"].get("ZN.v.0")
        raw_value: float | None = None
        source_key: str | None = None
        feature_state = "UNKNOWN"
        evidence: dict[str, Any] = {
            "change_reason": None,
            "change_status": "UNKNOWN",
            "current_instrument_id": None,
            "instrument_status": "UNKNOWN",
            "reference_instrument_id": None,
        }
        if state is not None:
            evidence["instrument_status"] = state["status"]
            evidence["current_instrument_id"] = state.get("instrument_id")
            if _timestamp(state["available_at"]) > case.decision_at:
                issues.append("ZN_NOT_AVAILABLE_AT_DECISION")
            if _timestamp(state["observed_at"]) > case.decision_at:
                issues.append("ZN_OBSERVED_AFTER_DECISION")
            change = state["changes"].get("4_HOURS")
            if change is not None:
                evidence["change_status"] = change["status"]
                evidence["change_reason"] = change.get("reason")
                evidence["reference_instrument_id"] = change.get(
                    "reference_instrument_id"
                )
                if change["status"] == "READY":
                    if _timestamp(change["reference_available_at"]) > case.decision_at:
                        issues.append("ZN_REFERENCE_NOT_AVAILABLE_AT_DECISION")
                    if _timestamp(change["reference_at"]) > case.decision_at:
                        issues.append("ZN_REFERENCE_AFTER_DECISION")
            if (
                state["status"] == "READY"
                and change is not None
                and change["status"] == "READY"
                and not issues
            ):
                raw = change.get("percent_change")
                if raw is not None:
                    raw_value = float(raw)
                    feature_state = (
                        "POSITIVE"
                        if raw_value > 0
                        else "NEGATIVE"
                        if raw_value < 0
                        else "FLAT"
                    )
                    source_key = (
                        f"{cross['record_id']}|ZN.v.0|4_HOURS|"
                        f"{state['source_record_key']}"
                    )

        feature = SelectorFeature(
            feature_id=FEATURE_ID,
            family_code=FEATURE_FAMILY,
            transform=FEATURE_TRANSFORM,
            state=feature_state,
            raw_value=raw_value,
            source_key=source_key,
            point_in_time_eligible=not issues,
        )
        decision = select_universal_zn_4h_bias(
            feature,
            session_code=case.session_code,
        )
        output[case_id] = MaterializedFeature(
            feature=feature,
            decision=decision,
            cross_record_id=str(cross["record_id"]),
            cross_record_hash=str(cross["record_hash"]),
            evidence=evidence,
            integrity_issues=tuple(issues),
        )
    return output


def _load_validation_trades(
    path: Path,
    *,
    execution_manifest_hash: str,
    cases: Mapping[str, ValidationCase],
) -> dict[str, dict[str, SourceTrade]]:
    output: dict[str, dict[str, SourceTrade]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line:
                raise ValueError("Baseline artifact contains the locked holdout")
            if '"session_date":"2024-' not in line:
                continue
            if (
                '"control_code":"ALWAYS_LONG"' not in line
                and '"control_code":"ALWAYS_SHORT"' not in line
            ):
                continue
            record = json.loads(line)
            _verify_record_hash(record)
            if record["holdout_loaded"] is not False:
                raise ValueError("Validation trade opens calendar 2025")
            if record["execution_manifest_hash"] != execution_manifest_hash:
                raise ValueError("Validation trade execution hash changed")
            case_id = str(record["case_id"])
            if case_id not in cases:
                raise ValueError(f"Unexpected validation trade case: {case_id}")
            trade = _trade_from_record(record)
            _verify_trade_lineage(trade, case=cases[case_id])
            if trade.side in output[case_id]:
                raise ValueError(f"Duplicate validation {trade.side}: {case_id}")
            output[case_id][trade.side] = SourceTrade(
                source_record=record,
                trade=trade,
            )
    for case_id, sides in output.items():
        if set(sides) != {"LONG", "SHORT"}:
            raise ValueError(f"Incomplete validation outcomes: {case_id}")
    return dict(output)


def _verify_trade_lineage(
    trade: BaselineTrade,
    *,
    case: ValidationCase,
) -> None:
    if trade.case_record_hash != case.case_record_hash:
        raise ValueError(f"Trade case hash mismatch: {case.case_id}")
    if trade.session_code != case.session_code:
        raise ValueError(f"Trade session mismatch: {case.case_id}")
    if trade.session_date != case.session_date:
        raise ValueError(f"Trade date mismatch: {case.case_id}")
    if trade.decision_at != case.decision_at:
        raise ValueError(f"Trade decision mismatch: {case.case_id}")
    if trade.entry_time != case.decision_at + timedelta(minutes=1):
        raise ValueError(f"Trade entry mismatch: {case.case_id}")
    if trade.exit_time != case.observation_end:
        raise ValueError(f"Trade exit mismatch: {case.case_id}")


def _materialize_decisions(
    cases: Mapping[str, ValidationCase],
    *,
    features: Mapping[str, MaterializedFeature],
    trades: Mapping[str, Mapping[str, SourceTrade]],
    validation_manifest_hash: str,
    case_specification_hash: str,
) -> tuple[list[dict[str, Any]], list[BaselineTrade]]:
    records: list[dict[str, Any]] = []
    selected_trades: list[BaselineTrade] = []
    ordered_cases = sorted(
        cases.values(),
        key=lambda item: (item.decision_at, item.case_id),
    )
    for case in ordered_cases:
        materialized = features[case.case_id]
        selected = (
            trades[case.case_id][materialized.decision.bias]
            if materialized.decision.bias in {"LONG", "SHORT"}
            else None
        )
        if selected is not None:
            selected_trades.append(selected.trade)
        records.append(
            finalize_record(
                {
                    "bias": materialized.decision.bias,
                    "calendar_2025_loaded": False,
                    "case_id": case.case_id,
                    "case_record_hash": case.case_record_hash,
                    "case_specification_manifest_hash": case_specification_hash,
                    "chronological_half": case.chronological_half,
                    "chronological_validation_2024_loaded": True,
                    "decision_at": case.decision_at,
                    "epistemic_status": "INFERRED",
                    "execution_manifest_hash": (
                        trades[case.case_id]["LONG"].trade.execution_manifest_hash
                    ),
                    "feature": {
                        "epistemic_status": "CALCULATED",
                        "evidence": dict(materialized.evidence),
                        "family_code": materialized.feature.family_code,
                        "feature_id": materialized.feature.feature_id,
                        "raw_percent_change": materialized.feature.raw_value,
                        "source_key": materialized.feature.source_key,
                        "state": materialized.feature.state,
                        "transform": materialized.feature.transform,
                    },
                    "integrity_issues": list(materialized.integrity_issues),
                    "reason_code": materialized.decision.reason_code,
                    "record_id": f"VALIDATION-{case.case_id}",
                    "record_type": "CHRONOLOGICAL_VALIDATION_DECISION",
                    "schema_version": VALIDATION_SCHEMA_VERSION,
                    "selected_outcome": (
                        _selected_outcome(selected)
                        if selected is not None
                        else None
                    ),
                    "selector_code": SELECTOR_CODE,
                    "session_code": case.session_code,
                    "session_date": case.session_date,
                    "source_cross_record_hash": materialized.cross_record_hash,
                    "source_cross_record_id": materialized.cross_record_id,
                    "source_session_record_hash": case.case_record_hash,
                    "source_session_record_id": case.case_id,
                    "validation_manifest_hash": validation_manifest_hash,
                    "validation_version": VALIDATION_VERSION,
                }
            )
        )
    return records, selected_trades


def _selected_outcome(source: SourceTrade) -> dict[str, Any]:
    trade = source.trade
    return {
        "baseline_trade_record_hash": source.source_record["record_hash"],
        "baseline_trade_record_id": source.source_record["record_id"],
        "commission_usd": trade.commission_usd,
        "entry_time": trade.entry_time,
        "exit_time": trade.exit_time,
        "gross_pnl_usd": trade.gross_pnl_usd,
        "gross_return_basis_points": trade.gross_return_basis_points,
        "holding_minutes": trade.holding_minutes,
        "net_pnl_usd": trade.net_pnl_usd,
        "net_return_basis_points": trade.net_return_basis_points,
        "reference_entry_price": trade.reference_entry_price,
        "side": trade.side,
        "slippage_cost_usd": trade.slippage_cost_usd,
        "spread_cost_usd": trade.spread_cost_usd,
        "total_cost_usd": trade.total_cost_usd,
    }


def _build_results(
    cases: Mapping[str, ValidationCase],
    *,
    features: Mapping[str, MaterializedFeature],
    source_trades: Mapping[str, Mapping[str, SourceTrade]],
    selected_trades: Sequence[BaselineTrade],
    validation_manifest: Mapping[str, Any],
    validation_manifest_hash: str,
    case_specification_hash: str,
    integrity_issues: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    by_case = {trade.case_id: trade for trade in selected_trades}
    bootstrap_replications = int(validation_manifest["bootstrap"]["replications"])
    sessions: dict[str, Any] = {}
    for session_code in SESSION_CODES:
        session_cases = [
            case for case in cases.values() if case.session_code == session_code
        ]
        session_selected = [
            by_case[case.case_id]
            for case in session_cases
            if case.case_id in by_case
        ]
        directional_states: dict[str, Any] = {}
        for state in ("POSITIVE", "NEGATIVE"):
            state_cases = [
                case
                for case in session_cases
                if features[case.case_id].feature.state == state
            ]
            state_selected = [
                by_case[case.case_id]
                for case in state_cases
                if case.case_id in by_case
            ]
            directional_states[state] = {
                "bias": (
                    "LONG" if state == "POSITIVE" else "SHORT"
                ),
                "case_count": len(state_cases),
                "iso_week_cluster_count": len(
                    {_iso_week_key(case.session_date) for case in state_cases}
                ),
                "metrics": calculate_baseline_metrics(state_selected),
            }
        controls: dict[str, Any] = {}
        for side in ("LONG", "SHORT"):
            controls[f"ALWAYS_{side}"] = calculate_baseline_metrics(
                [
                    source_trades[case.case_id][side].trade
                    for case in session_cases
                ]
            )
        best_control = max(
            controls,
            key=lambda key: (
                float(controls[key]["mean_net_return_basis_points"]),
                key,
            ),
        )
        selector_metrics = calculate_baseline_metrics(session_selected)
        sessions[session_code] = {
            "best_validation_unconditional_control": best_control,
            "bootstrap_95pct_ci_mean_net_return_basis_points": (
                _week_cluster_bootstrap_ci(
                    session_selected,
                    replications=bootstrap_replications,
                    seed_material=(
                        f"{validation_manifest_hash}|{session_code}|"
                        f"{SELECTOR_CODE}"
                    ),
                )
            ),
            "chronological_halves": {
                half: calculate_baseline_metrics(
                    [
                        trade
                        for trade in session_selected
                        if cases[trade.case_id].chronological_half == half
                    ]
                )
                for half in ("EARLY", "LATE")
            },
            "cost_stress_1_5x": calculate_baseline_metrics(
                [
                    apply_cost_multiplier(trade, multiplier=1.5)
                    for trade in session_selected
                ]
            ),
            "directional_state_results": directional_states,
            "no_bias_count": sum(
                features[case.case_id].decision.bias == "NO_BIAS"
                for case in session_cases
            ),
            "reason_counts": dict(
                sorted(
                    Counter(
                        features[case.case_id].decision.reason_code
                        for case in session_cases
                    ).items()
                )
            ),
            "selector_excess_mean_net_return_vs_best_control_bps": _rounded(
                float(selector_metrics["mean_net_return_basis_points"])
                - float(controls[best_control]["mean_net_return_basis_points"])
            ),
            "selector_metrics": selector_metrics,
            "total_case_count": len(session_cases),
            "validation_unconditional_controls": controls,
        }

    thresholds = validation_manifest["gate_evaluation"]["thresholds"]
    frozen_support = {
        "minimum_directional_cases": int(
            thresholds["minimum_directional_cases_per_session"]
        ),
        "minimum_state_cases": int(
            thresholds["minimum_directional_cases_per_session_and_state"]
        ),
        "minimum_state_week_clusters": int(
            thresholds["minimum_iso_week_clusters_per_session_and_state"]
        ),
    }
    gate_evaluation = evaluate_validation_gates(
        sessions,
        integrity_passed=not integrity_issues,
        **frozen_support,
    )
    return {
        "case_specification_manifest_hash": case_specification_hash,
        "gate_evaluation": gate_evaluation,
        "integrity": {
            "calendar_2024_conditional_data_loaded": True,
            "calendar_2025_loaded": False,
            "case_specification_changed": False,
            "execution_optimized": False,
            "feature_or_threshold_retuned": False,
            "issue_count": len(integrity_issues),
            "issues": list(integrity_issues),
            "point_in_time_integrity_passed": not integrity_issues,
        },
        "milestone": "6_CHRONOLOGICAL_VALIDATION",
        "overall": {
            "bias_counts": dict(
                sorted(
                    Counter(
                        feature.decision.bias for feature in features.values()
                    ).items()
                )
            ),
            "selector_metrics": calculate_baseline_metrics(selected_trades),
            "total_case_count": len(cases),
        },
        "results_hash": "",
        "schema_version": VALIDATION_SCHEMA_VERSION,
        "selector": {
            "feature_id": FEATURE_ID,
            "selector_code": SELECTOR_CODE,
            "universal_session_rule": True,
        },
        "sessions": sessions,
        "validation_interval": {
            "end_exclusive": "2025-01-01",
            "start_inclusive": "2024-01-01",
        },
        "validation_manifest_hash": validation_manifest_hash,
        "validation_version": VALIDATION_VERSION,
    }


def _week_cluster_bootstrap_ci(
    trades: Sequence[BaselineTrade],
    *,
    replications: int,
    seed_material: str,
) -> list[float | None]:
    if not trades:
        return [None, None]
    clusters: dict[str, list[float]] = defaultdict(list)
    for trade in trades:
        clusters[_iso_week_key(trade.session_date)].append(
            trade.net_return_basis_points
        )
    summaries = [
        (math.fsum(values), len(values))
        for _, values in sorted(clusters.items())
    ]
    if len(summaries) == 1 or replications <= 0:
        mean = statistics.fmean(
            trade.net_return_basis_points for trade in trades
        )
        return [_rounded(mean), _rounded(mean)]
    seed = int.from_bytes(
        hashlib.sha256(seed_material.encode("utf-8")).digest()[:8],
        "big",
    )
    generator = random.Random(seed)
    means: list[float] = []
    for _ in range(replications):
        total = 0.0
        observations = 0
        for _ in range(len(summaries)):
            cluster_total, cluster_observations = summaries[
                generator.randrange(len(summaries))
            ]
            total += cluster_total
            observations += cluster_observations
        means.append(total / observations)
    return [
        _rounded(quantile_type_7(means, 0.025)),
        _rounded(quantile_type_7(means, 0.975)),
    ]


def _trade_from_record(record: Mapping[str, Any]) -> BaselineTrade:
    return BaselineTrade(
        case_id=str(record["case_id"]),
        case_record_hash=str(record["case_record_hash"]),
        session_code=str(record["session_code"]),
        session_date=date.fromisoformat(record["session_date"]),
        control_code=str(record["control_code"]),  # type: ignore[arg-type]
        side=str(record["side"]),  # type: ignore[arg-type]
        decision_at=_timestamp(record["decision_at"]),
        entry_time=_timestamp(record["entry_time"]),
        exit_time=_timestamp(record["exit_time"]),
        holding_minutes=int(record["holding_minutes"]),
        entry_bar_id=str(record["entry_bar_id"]),
        entry_bar_hash=str(record["entry_bar_hash"]),
        exit_bar_id=str(record["exit_bar_id"]),
        exit_bar_hash=str(record["exit_bar_hash"]),
        reference_entry_price=float(record["reference_entry_price"]),
        reference_exit_price=float(record["reference_exit_price"]),
        executed_entry_price=float(record["executed_entry_price"]),
        executed_exit_price=float(record["executed_exit_price"]),
        entry_spread_price=float(record["entry_spread_price"]),
        exit_spread_price=float(record["exit_spread_price"]),
        quantity_ounces=float(record["quantity_ounces"]),
        quantity_lots=float(record["quantity_lots"]),
        gross_pnl_usd=float(record["gross_pnl_usd"]),
        spread_cost_usd=float(record["spread_cost_usd"]),
        slippage_cost_usd=float(record["slippage_cost_usd"]),
        commission_usd=float(record["commission_usd"]),
        total_cost_usd=float(record["total_cost_usd"]),
        net_pnl_usd=float(record["net_pnl_usd"]),
        gross_return_basis_points=float(record["gross_return_basis_points"]),
        net_return_basis_points=float(record["net_return_basis_points"]),
        execution_manifest_hash=str(record["execution_manifest_hash"]),
    )


def _verify_casebook_record(record: Mapping[str, Any]) -> None:
    if record["casebook_version"] != CASEBOOK_VERSION:
        raise ValueError(f"Casebook version mismatch: {record['record_id']}")
    _verify_record_hash(record)


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record["record_hash"])
    unhashed = {key: value for key, value in record.items() if key != "record_hash"}
    if canonical_hash(unhashed) != supplied:
        raise ValueError(f"Record hash mismatch: {record['record_id']}")


def _verify_hashed_document(
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


def _artifact(
    manifest: Mapping[str, Any],
    path: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == path]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not contain exactly one {path}")
    return matches[0]


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


def _artifact_summary(
    path: Path,
    *,
    record_count: int,
    record_type: str,
) -> dict[str, Any]:
    return {
        **_file_summary(path),
        "record_count": record_count,
        "record_type_counts": {record_type: record_count},
    }


def _file_summary(path: Path) -> dict[str, Any]:
    return {
        "bytes": path.stat().st_size,
        "path": path.name,
        "sha256": _sha256(path),
    }


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


def _verify_file_hash(path: Path, expected: str) -> None:
    if _sha256(path) != expected:
        raise ValueError(f"Artifact SHA-256 mismatch: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _timestamp(value: Any) -> datetime:
    parsed = datetime.fromisoformat(str(value))
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamp")
    return parsed.astimezone(UTC)


def _extract_json_string(line: str, key: str) -> str | None:
    marker = f'"{key}":"'
    start = line.find(marker)
    if start < 0:
        return None
    value_start = start + len(marker)
    value_end = line.find('"', value_start)
    return line[value_start:value_end] if value_end >= 0 else None


def _iso_week_key(value: date) -> str:
    iso = value.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def _rounded(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None


if __name__ == "__main__":
    main()
