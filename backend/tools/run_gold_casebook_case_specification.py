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
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, finalize_record, json_ready
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

SCHEMA_VERSION = "gold-casebook-case-specification-schema-0.1.0"
DEVELOPMENT_START = date(2021, 8, 1)
DEVELOPMENT_END = date(2024, 1, 1)
SESSION_CODES = ("LONDON", "NEW_YORK")


@dataclass(frozen=True, slots=True)
class FrozenCase:
    source_record: Mapping[str, Any]
    feature: SelectorFeature
    decision: BiasDecision


@dataclass(frozen=True, slots=True)
class SourceTrade:
    source_record: Mapping[str, Any]
    trade: BaselineTrade


def main() -> None:
    args = _parser().parse_args()
    specification_path = Path(args.case_specification_manifest)
    discovery_root = Path(args.discovery_bundle)
    baseline_root = Path(args.baseline_bundle)
    casebook_root = Path(args.casebook_bundle)
    output = Path(args.output)
    if output.exists():
        raise FileExistsError(
            f"Refusing to overwrite immutable case-specification bundle: {output}"
        )

    specification = _load_json(specification_path)
    specification_hash = _verify_hashed_document(
        specification,
        hash_field="manifest_hash",
        label="case-specification manifest",
    )
    _verify_specification(specification)
    _verify_sources(
        specification,
        discovery_root=discovery_root,
        baseline_root=baseline_root,
        casebook_root=casebook_root,
    )

    discovery_manifest = _load_json(discovery_root / "manifest.json")
    feature_artifact = _artifact(discovery_manifest, "development_features.jsonl.gz")
    feature_path = discovery_root / "development_features.jsonl.gz"
    feature_cases, feature_reserved_rows = _load_development_features(
        feature_path,
        discovery_research_manifest_hash=str(
            specification["source"]["discovery_research_manifest_hash"]
        ),
    )
    if feature_reserved_rows:
        raise ValueError("Development feature artifact contains reserved-period rows")

    baseline_manifest = _load_json(baseline_root / "manifest.json")
    trades_path = baseline_root / "trades.jsonl.gz"
    trades, reserved_trade_rows = _load_development_trades(
        trades_path,
        execution_manifest_hash=str(
            specification["execution"]["execution_manifest_hash"]
        ),
    )
    expected_trade_cases = set(feature_cases)
    if set(trades) != expected_trade_cases:
        missing = sorted(expected_trade_cases - trades.keys())
        extra = sorted(trades.keys() - expected_trade_cases)
        raise ValueError(
            f"Development trade join mismatch; missing={missing[:3]}, extra={extra[:3]}"
        )

    decisions, selector_trades = _materialize_decisions(
        feature_cases,
        trades=trades,
        specification_hash=specification_hash,
    )
    bootstrap_replications = int(
        specification["development_reporting"]["bootstrap_replications"]
    )
    results = _build_results(
        feature_cases,
        source_trades=trades,
        selector_trades=selector_trades,
        specification=specification,
        specification_hash=specification_hash,
        bootstrap_replications=bootstrap_replications,
        reserved_trade_rows=reserved_trade_rows,
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
        decisions_path = staging / "development_decisions.jsonl.gz"
        decision_count = _write_jsonl_gzip(decisions_path, decisions)
        results_path = staging / "development_results.json"
        _write_json(results_path, results)
        bundle_manifest = {
            "artifacts": [
                _artifact_summary(
                    decisions_path,
                    record_count=decision_count,
                    record_type="CASE_SPECIFICATION_DECISION",
                ),
                {
                    **_file_summary(results_path),
                    "document_hash": results["results_hash"],
                },
            ],
            "case_specification_version": CASE_SPECIFICATION_VERSION,
            "governing_contract": "GOLD_CASEBOOK_RESEARCH_CONTRACT.md",
            "integrity": {
                "calendar_2025_loaded": False,
                "chronological_validation_2024_deserialized": False,
                "development_decision_records_written": decision_count,
                "execution_optimized": False,
                "feature_or_threshold_retuned": False,
                "reserved_baseline_trade_rows_skipped_before_deserialization": (
                    reserved_trade_rows
                ),
                "source_artifact_hashes_verified": 7,
                "universal_session_rule": True,
            },
            "manifest_hash": "",
            "milestone": "5_CASE_SPECIFICATION",
            "schema_version": SCHEMA_VERSION,
            "selector_code": SELECTOR_CODE,
            "source": {
                "baseline_bundle_manifest_hash": baseline_manifest["manifest_hash"],
                "case_specification_manifest_hash": specification_hash,
                "casebook_manifest_hash": specification["source"][
                    "casebook_manifest_hash"
                ],
                "development_features_sha256": feature_artifact["sha256"],
                "discovery_bundle_manifest_hash": discovery_manifest["manifest_hash"],
            },
            "status": "EXPLORATORY_NOT_VALIDATED_EDGE",
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
                "case_specification_manifest_hash": specification_hash,
                "development_cases": len(feature_cases),
                "directional_cases": len(selector_trades),
                "no_bias_cases": len(feature_cases) - len(selector_trades),
                "results_hash": results["results_hash"],
                "reserved_2024_trade_rows_skipped_before_deserialization": (
                    reserved_trade_rows
                ),
            },
            indent=2,
            sort_keys=True,
        )
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Materialize the frozen universal-ZN Milestone 5 selector.",
    )
    parser.add_argument(
        "--case-specification-manifest",
        default="research_manifests/gold_casebook_case_specification_v01.json",
    )
    parser.add_argument(
        "--discovery-bundle",
        default="research_artifacts/gold_casebook_relationships_v01",
    )
    parser.add_argument(
        "--baseline-bundle",
        default="research_artifacts/gold_casebook_baseline_v01",
    )
    parser.add_argument(
        "--casebook-bundle",
        default="research_artifacts/gold_casebook_v01",
    )
    parser.add_argument(
        "--output",
        default="research_artifacts/gold_casebook_case_specification_v01",
    )
    return parser


def _verify_specification(specification: Mapping[str, Any]) -> None:
    if specification["manifest_version"] != CASE_SPECIFICATION_VERSION:
        raise ValueError("Case-specification version changed")
    if specification["status"] != "FROZEN_BEFORE_COMBINED_SELECTOR_RESULT":
        raise ValueError("Case specification was not frozen before its result")
    candidate = specification["candidate"]
    if candidate["candidate_code"] != SELECTOR_CODE:
        raise ValueError("Selector code changed")
    if candidate["sessions"] != list(SESSION_CODES):
        raise ValueError("Frozen selector sessions changed")
    if candidate["universal_session_rule"] is not True:
        raise ValueError("Frozen selector is not universal")
    feature = candidate["feature"]
    expected = {
        "feature_id": FEATURE_ID,
        "family_code": FEATURE_FAMILY,
        "transform": FEATURE_TRANSFORM,
    }
    for key, value in expected.items():
        if feature[key] != value:
            raise ValueError(f"Frozen selector {key} changed")
    if candidate["rule_table"] != {
        "FLAT": "NO_BIAS",
        "NEGATIVE": "SHORT",
        "POSITIVE": "LONG",
        "UNKNOWN": "NO_BIAS",
    }:
        raise ValueError("Frozen selector mapping changed")
    partitions = specification["time_partitions"]
    if partitions["development"] != {
        "start_inclusive": "2021-08-01T00:00:00+00:00",
        "end_exclusive": "2024-01-01T00:00:00+00:00",
    }:
        raise ValueError("Development interval changed")
    if (
        partitions["chronological_validation_reserve"]["conditional_data_loaded"]
        is not False
    ):
        raise ValueError("Chronological validation reserve was opened")
    if partitions["locked_holdout"]["data_loaded"] is not False:
        raise ValueError("Locked holdout was opened")
    if not all(bool(value) for value in specification["prohibited"].values()):
        raise ValueError("A prohibited Milestone 5 action was enabled")


def _verify_sources(
    specification: Mapping[str, Any],
    *,
    discovery_root: Path,
    baseline_root: Path,
    casebook_root: Path,
) -> None:
    source = specification["source"]
    casebook_manifest = _load_json(casebook_root / "manifest.json")
    casebook_hash = _verify_hashed_document(
        casebook_manifest,
        hash_field="manifest_hash",
        label="casebook manifest",
    )
    if casebook_hash != source["casebook_manifest_hash"]:
        raise ValueError("Casebook source hash changed")

    discovery_manifest = _load_json(discovery_root / "manifest.json")
    discovery_hash = _verify_hashed_document(
        discovery_manifest,
        hash_field="manifest_hash",
        label="discovery bundle manifest",
    )
    if discovery_hash != source["discovery_bundle_manifest_hash"]:
        raise ValueError("Discovery bundle source hash changed")
    features = _artifact(discovery_manifest, "development_features.jsonl.gz")
    _verify_file_hash(
        discovery_root / "development_features.jsonl.gz",
        str(features["sha256"]),
    )
    if features["sha256"] != source["development_features_sha256"]:
        raise ValueError("Development feature source hash changed")
    rankings = _artifact(discovery_manifest, "rankings.json")
    _verify_file_hash(discovery_root / "rankings.json", str(rankings["sha256"]))
    rankings_document = _load_json(discovery_root / "rankings.json")
    rankings_hash = _verify_hashed_document(
        rankings_document,
        hash_field="rankings_hash",
        label="discovery rankings",
    )
    if rankings_hash != source["discovery_rankings_hash"]:
        raise ValueError("Discovery rankings hash changed")

    baseline_manifest = _load_json(baseline_root / "manifest.json")
    baseline_hash = _verify_hashed_document(
        baseline_manifest,
        hash_field="manifest_hash",
        label="baseline bundle manifest",
    )
    if baseline_hash != source["baseline_bundle_manifest_hash"]:
        raise ValueError("Baseline bundle source hash changed")
    baseline_trades = _artifact(baseline_manifest, "trades.jsonl.gz")
    _verify_file_hash(
        baseline_root / "trades.jsonl.gz",
        str(baseline_trades["sha256"]),
    )
    if baseline_trades["sha256"] != source["baseline_trades_sha256"]:
        raise ValueError("Baseline trades source hash changed")


def _load_development_features(
    path: Path,
    *,
    discovery_research_manifest_hash: str,
) -> tuple[dict[str, FrozenCase], int]:
    output: dict[str, FrozenCase] = {}
    reserved_rows = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if (
                '"session_date":"2024-' in line
                or '"session_date":"2025-' in line
            ):
                reserved_rows += 1
                continue
            record = json.loads(line)
            if record["record_type"] != "DEVELOPMENT_FEATURE_CASE":
                continue
            _verify_record_hash(record)
            session_date = date.fromisoformat(record["session_date"])
            if not DEVELOPMENT_START <= session_date < DEVELOPMENT_END:
                raise ValueError(
                    f"Feature case outside development: {record['record_id']}"
                )
            if record["research_manifest_hash"] != discovery_research_manifest_hash:
                raise ValueError("Feature case discovery manifest hash changed")
            if (
                record["calendar_2025_loaded"] is not False
                or record["chronological_validation_2024_loaded"] is not False
            ):
                raise ValueError("Feature case opens a reserved period")
            session_code = str(record["session_code"])
            if session_code not in SESSION_CODES:
                raise ValueError(f"Unexpected session: {session_code}")
            source = record["features"][FEATURE_ID]
            feature = SelectorFeature(
                feature_id=FEATURE_ID,
                family_code=str(source["family_code"]),
                transform=str(source["transform"]),
                state=str(source["state"]),
                raw_value=(
                    float(source["raw_value"])
                    if source["raw_value"] is not None
                    else None
                ),
                source_key=(
                    str(source["source_key"])
                    if source["source_key"] is not None
                    else None
                ),
                point_in_time_eligible=True,
            )
            decision = select_universal_zn_4h_bias(
                feature,
                session_code=session_code,
            )
            case_id = str(record["case_id"])
            if case_id in output:
                raise ValueError(f"Duplicate feature case: {case_id}")
            output[case_id] = FrozenCase(
                source_record=record,
                feature=feature,
                decision=decision,
            )
    return output, reserved_rows


def _load_development_trades(
    path: Path,
    *,
    execution_manifest_hash: str,
) -> tuple[dict[str, dict[str, SourceTrade]], int]:
    output: dict[str, dict[str, SourceTrade]] = defaultdict(dict)
    reserved_rows = 0
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2024-' in line:
                reserved_rows += 1
                continue
            if '"session_date":"2025-' in line:
                raise ValueError("Baseline trade artifact contains the locked holdout")
            if (
                '"control_code":"ALWAYS_LONG"' not in line
                and '"control_code":"ALWAYS_SHORT"' not in line
            ):
                continue
            record = json.loads(line)
            _verify_record_hash(record)
            session_date = date.fromisoformat(record["session_date"])
            if not DEVELOPMENT_START <= session_date < DEVELOPMENT_END:
                continue
            if record["execution_manifest_hash"] != execution_manifest_hash:
                raise ValueError("Baseline execution manifest hash changed")
            if record["holdout_loaded"] is not False:
                raise ValueError("Baseline trade opens the locked holdout")
            trade = _trade_from_record(record)
            case_id = str(record["case_id"])
            if trade.side in output[case_id]:
                raise ValueError(f"Duplicate {trade.side} trade for {case_id}")
            output[case_id][trade.side] = SourceTrade(
                source_record=record,
                trade=trade,
            )
    for case_id, sides in output.items():
        if set(sides) != {"LONG", "SHORT"}:
            raise ValueError(f"Incomplete fixed outcomes for {case_id}")
    return dict(output), reserved_rows


def _materialize_decisions(
    cases: Mapping[str, FrozenCase],
    *,
    trades: Mapping[str, Mapping[str, SourceTrade]],
    specification_hash: str,
) -> tuple[list[dict[str, Any]], list[BaselineTrade]]:
    records: list[dict[str, Any]] = []
    selected_trades: list[BaselineTrade] = []
    for case_id, case in sorted(
        cases.items(),
        key=lambda item: (
            item[1].source_record["decision_at"],
            item[0],
        ),
    ):
        selected = (
            trades[case_id][case.decision.bias]
            if case.decision.bias in {"LONG", "SHORT"}
            else None
        )
        if selected is not None:
            selected_trades.append(selected.trade)
        source = case.source_record
        outcome = (
            {
                "baseline_trade_record_hash": selected.source_record["record_hash"],
                "baseline_trade_record_id": selected.source_record["record_id"],
                "commission_usd": selected.trade.commission_usd,
                "entry_time": selected.trade.entry_time,
                "exit_time": selected.trade.exit_time,
                "gross_pnl_usd": selected.trade.gross_pnl_usd,
                "gross_return_basis_points": (
                    selected.trade.gross_return_basis_points
                ),
                "holding_minutes": selected.trade.holding_minutes,
                "net_pnl_usd": selected.trade.net_pnl_usd,
                "net_return_basis_points": selected.trade.net_return_basis_points,
                "reference_entry_price": selected.trade.reference_entry_price,
                "side": selected.trade.side,
                "slippage_cost_usd": selected.trade.slippage_cost_usd,
                "spread_cost_usd": selected.trade.spread_cost_usd,
                "total_cost_usd": selected.trade.total_cost_usd,
            }
            if selected is not None
            else None
        )
        records.append(
            finalize_record(
                {
                    "bias": case.decision.bias,
                    "calendar_2025_loaded": False,
                    "case_id": case_id,
                    "case_record_hash": source["case_record_hash"],
                    "case_specification_manifest_hash": specification_hash,
                    "case_specification_version": CASE_SPECIFICATION_VERSION,
                    "chronological_half": source["chronological_half"],
                    "chronological_validation_2024_loaded": False,
                    "decision_at": source["decision_at"],
                    "epistemic_status": "INFERRED",
                    "execution_manifest_hash": (
                        trades[case_id]["LONG"].trade.execution_manifest_hash
                    ),
                    "feature": {
                        "epistemic_status": "CALCULATED",
                        "family_code": case.feature.family_code,
                        "feature_id": case.feature.feature_id,
                        "raw_percent_change": case.feature.raw_value,
                        "source_key": case.feature.source_key,
                        "state": case.feature.state,
                        "transform": case.feature.transform,
                    },
                    "record_id": f"SELECTOR-{case_id}",
                    "record_type": "CASE_SPECIFICATION_DECISION",
                    "reason_code": case.decision.reason_code,
                    "schema_version": SCHEMA_VERSION,
                    "selected_outcome": outcome,
                    "selector_code": SELECTOR_CODE,
                    "session_code": source["session_code"],
                    "session_date": source["session_date"],
                    "source_feature_record_hash": source["record_hash"],
                    "source_feature_record_id": source["record_id"],
                }
            )
        )
    return records, selected_trades


def _build_results(
    cases: Mapping[str, FrozenCase],
    *,
    source_trades: Mapping[str, Mapping[str, SourceTrade]],
    selector_trades: Sequence[BaselineTrade],
    specification: Mapping[str, Any],
    specification_hash: str,
    bootstrap_replications: int,
    reserved_trade_rows: int,
) -> dict[str, Any]:
    by_case = {trade.case_id: trade for trade in selector_trades}
    sessions: dict[str, Any] = {}
    for session_code in SESSION_CODES:
        session_cases = [
            case
            for case in cases.values()
            if case.source_record["session_code"] == session_code
        ]
        session_selected = [
            by_case[str(case.source_record["case_id"])]
            for case in session_cases
            if str(case.source_record["case_id"]) in by_case
        ]
        state_results: dict[str, Any] = {}
        for state in ("POSITIVE", "NEGATIVE", "FLAT", "UNKNOWN"):
            state_case_ids = {
                str(case.source_record["case_id"])
                for case in session_cases
                if case.feature.state == state
            }
            state_selected = [
                trade
                for trade in session_selected
                if trade.case_id in state_case_ids
            ]
            state_results[state] = {
                "bias": specification["candidate"]["rule_table"][state],
                "case_count": len(state_case_ids),
                "metrics": calculate_baseline_metrics(state_selected),
            }
        controls: dict[str, Any] = {}
        for side in ("LONG", "SHORT"):
            control_trades = [
                source_trades[str(case.source_record["case_id"])][side].trade
                for case in session_cases
            ]
            controls[f"ALWAYS_{side}"] = calculate_baseline_metrics(control_trades)
        best_control = max(
            controls,
            key=lambda key: (
                float(controls[key]["mean_net_return_basis_points"]),
                key,
            ),
        )
        selector_metrics = calculate_baseline_metrics(session_selected)
        half_results = {
            half: calculate_baseline_metrics(
                [
                    trade
                    for trade in session_selected
                    if cases[trade.case_id].source_record["chronological_half"]
                    == half
                ]
            )
            for half in ("EARLY", "LATE")
        }
        sessions[session_code] = {
            "bootstrap_95pct_ci_mean_net_return_basis_points": (
                _week_cluster_bootstrap_ci(
                    session_selected,
                    replications=bootstrap_replications,
                    seed_material=(
                        f"{specification_hash}|{session_code}|{SELECTOR_CODE}"
                    ),
                )
            ),
            "chronological_halves": half_results,
            "development_unconditional_controls": controls,
            "feature_state_results": state_results,
            "no_bias_count": sum(
                case.decision.bias == "NO_BIAS" for case in session_cases
            ),
            "reason_counts": dict(
                sorted(Counter(case.decision.reason_code for case in session_cases).items())
            ),
            "selector_excess_mean_net_return_vs_best_control_bps": _rounded(
                float(selector_metrics["mean_net_return_basis_points"])
                - float(controls[best_control]["mean_net_return_basis_points"])
            ),
            "selector_metrics": selector_metrics,
            "best_development_unconditional_control": best_control,
            "total_case_count": len(session_cases),
        }
    return {
        "case_specification_manifest_hash": specification_hash,
        "case_specification_version": CASE_SPECIFICATION_VERSION,
        "development_interval": {
            "end_exclusive": "2024-01-01T00:00:00+00:00",
            "start_inclusive": "2021-08-01T00:00:00+00:00",
        },
        "guardrails": {
            "calendar_2025_loaded": False,
            "chronological_validation_2024_deserialized": False,
            "execution_optimized": False,
            "feature_or_threshold_retuned": False,
            "reserved_2024_baseline_trade_rows_skipped_before_deserialization": (
                reserved_trade_rows
            ),
            "status": "EXPLORATORY_NOT_VALIDATED_EDGE",
        },
        "milestone": "5_CASE_SPECIFICATION",
        "overall": {
            "bias_counts": dict(
                sorted(Counter(case.decision.bias for case in cases.values()).items())
            ),
            "selector_metrics": calculate_baseline_metrics(selector_trades),
            "total_case_count": len(cases),
        },
        "results_hash": "",
        "schema_version": SCHEMA_VERSION,
        "selector": {
            "feature_id": FEATURE_ID,
            "rule_table": specification["candidate"]["rule_table"],
            "selector_code": SELECTOR_CODE,
            "universal_session_rule": True,
        },
        "sessions": sessions,
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
        iso = trade.session_date.isocalendar()
        clusters[f"{iso.year}-W{iso.week:02d}"].append(
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
    cluster_count = len(summaries)
    means: list[float] = []
    for _ in range(replications):
        total = 0.0
        observations = 0
        for _ in range(cluster_count):
            cluster_total, cluster_observations = summaries[
                generator.randrange(cluster_count)
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
    parsed = datetime.fromisoformat(str(value)).astimezone(UTC)
    if parsed.tzinfo is None:
        raise ValueError("Naive timestamp")
    return parsed


def _rounded(value: float | None) -> float | None:
    return round(value, 8) if value is not None else None


if __name__ == "__main__":
    main()
