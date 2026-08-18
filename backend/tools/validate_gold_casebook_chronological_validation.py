from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from gold_intel.analytics.casebook import (
    CASEBOOK_VERSION,
    canonical_hash,
    json_ready,
)
from gold_intel.backtesting.casebook_baseline import (
    BaselineTrade,
    calculate_baseline_metrics,
)
from gold_intel.backtesting.casebook_relationships import quantile_type_7
from gold_intel.backtesting.casebook_selector import (
    FEATURE_FAMILY,
    FEATURE_ID,
    FEATURE_TRANSFORM,
    SELECTOR_CODE,
    SelectorFeature,
    select_universal_zn_4h_bias,
)
from gold_intel.backtesting.casebook_validation import (
    apply_cost_multiplier,
    evaluate_validation_gates,
)

SEMANTIC_VALIDATION_VERSION = (
    "GOLD_CASEBOOK_CHRONOLOGICAL_SEMANTIC_VALIDATION_V0_1"
)
SESSION_CODES = ("LONDON", "NEW_YORK")
SESSION_TIMEZONES = {
    "LONDON": ZoneInfo("Europe/London"),
    "NEW_YORK": ZoneInfo("America/New_York"),
}


@dataclass(frozen=True, slots=True)
class SourceCase:
    case_id: str
    record_hash: str
    session_code: str
    session_date: date
    decision_at: datetime
    observation_end: datetime
    cross_record_id: str
    chronological_half: str


@dataclass(frozen=True, slots=True)
class SourceTrade:
    record_id: str
    record_hash: str
    trade: BaselineTrade


@dataclass(frozen=True, slots=True)
class ExpectedFeature:
    feature: SelectorFeature
    bias: str
    reason_code: str
    evidence: Mapping[str, Any]
    cross_record_hash: str


def main() -> None:
    args = _parser().parse_args()
    validation_manifest_path = Path(args.validation_manifest)
    case_specification_path = Path(args.case_specification_manifest)
    casebook_root = Path(args.casebook_bundle)
    baseline_root = Path(args.baseline_bundle)
    bundle_root = Path(args.validation_bundle)

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
    bundle_manifest = _load_json(bundle_root / "manifest.json")
    bundle_manifest_hash = _verify_hashed_document(
        bundle_manifest,
        hash_field="manifest_hash",
        label="chronological-validation bundle",
    )
    _verify_bundle_artifacts(bundle_root, bundle_manifest)
    if bundle_manifest["source"] != {
        "baseline_bundle_manifest_hash": validation_manifest["source"][
            "baseline_bundle_manifest_hash"
        ],
        "case_specification_manifest_hash": case_specification_hash,
        "casebook_manifest_hash": validation_manifest["source"][
            "casebook_manifest_hash"
        ],
        "chronological_validation_manifest_hash": validation_manifest_hash,
    }:
        raise ValueError("Validation bundle source lineage changed")

    results = _load_json(bundle_root / "validation_results.json")
    results_hash = _verify_hashed_document(
        results,
        hash_field="results_hash",
        label="chronological-validation results",
    )
    if (
        results["validation_manifest_hash"] != validation_manifest_hash
        or results["case_specification_manifest_hash"]
        != case_specification_hash
    ):
        raise ValueError("Validation results source lineage changed")

    _verify_source_artifact_hashes(
        validation_manifest,
        casebook_root=casebook_root,
        baseline_root=baseline_root,
    )
    cases = _load_source_cases(casebook_root / "sessions.jsonl.gz")
    crosses = _load_source_crosses(
        casebook_root / "cross_market_snapshots.jsonl.gz",
        wanted={case.cross_record_id for case in cases.values()},
    )
    expected_features = {
        case_id: _expected_feature(case, cross=crosses[case.cross_record_id])
        for case_id, case in cases.items()
    }
    trades = _load_source_trades(
        baseline_root / "trades.jsonl.gz",
        execution_manifest_hash=str(
            validation_manifest["execution"]["execution_manifest_hash"]
        ),
        cases=cases,
    )
    decisions = _load_and_verify_decisions(
        bundle_root / "validation_decisions.jsonl.gz",
        validation_manifest_hash=validation_manifest_hash,
        case_specification_hash=case_specification_hash,
        cases=cases,
        expected_features=expected_features,
        trades=trades,
    )
    if set(decisions) != set(cases):
        raise ValueError("Validation decision cases differ from source cases")

    selected = [
        trades[case_id][str(record["bias"])].trade
        for case_id, record in decisions.items()
        if record["bias"] in {"LONG", "SHORT"}
    ]
    if calculate_baseline_metrics(selected) != results["overall"]["selector_metrics"]:
        raise ValueError("Overall validation metrics do not reconstruct")
    if dict(
        sorted(Counter(record["bias"] for record in decisions.values()).items())
    ) != results["overall"]["bias_counts"]:
        raise ValueError("Overall validation bias counts do not reconstruct")

    reconstructed_sessions: dict[str, Mapping[str, Any]] = {}
    for session_code in SESSION_CODES:
        reconstructed_sessions[session_code] = _verify_session(
            session_code,
            decisions=decisions,
            cases=cases,
            trades=trades,
            expected=results["sessions"][session_code],
            validation_manifest_hash=validation_manifest_hash,
            bootstrap_replications=int(
                validation_manifest["bootstrap"]["replications"]
            ),
        )
    thresholds = validation_manifest["gate_evaluation"]["thresholds"]
    gate_evaluation = evaluate_validation_gates(
        reconstructed_sessions,
        integrity_passed=True,
        minimum_directional_cases=int(
            thresholds["minimum_directional_cases_per_session"]
        ),
        minimum_state_cases=int(
            thresholds["minimum_directional_cases_per_session_and_state"]
        ),
        minimum_state_week_clusters=int(
            thresholds["minimum_iso_week_clusters_per_session_and_state"]
        ),
    )
    if gate_evaluation != results["gate_evaluation"]:
        raise ValueError("Frozen gate verdict does not reconstruct")
    if results["integrity"]["issue_count"] != 0:
        raise ValueError("Validation results contain unresolved integrity issues")
    if bundle_manifest["verdict"] != gate_evaluation["verdict"]:
        raise ValueError("Bundle verdict differs from reconstructed verdict")

    validation = {
        "bundle_manifest_hash": bundle_manifest_hash,
        "calendar_2025_loaded": False,
        "case_specification_manifest_hash": case_specification_hash,
        "results_hash": results_hash,
        "semantic_assertions": {
            "all_2024_decisions_reconstructed_from_raw_casebook_records": True,
            "all_decision_and_source_record_hashes_match": True,
            "all_directional_outcomes_match_frozen_baseline_trade_hashes": True,
            "all_ten_predeclared_gates_reconstructed": True,
            "calendar_2025_absent": True,
            "cost_stress_1_5x_reconstructed": True,
            "decision_clocks_and_cross_market_availability_are_point_in_time": True,
            "execution_rule_unchanged": True,
            "selector_rule_and_threshold_unchanged": True,
            "session_state_half_control_and_bootstrap_metrics_reconstructed": True,
        },
        "validation_hash": "",
        "validation_manifest_hash": validation_manifest_hash,
        "validation_version": SEMANTIC_VALIDATION_VERSION,
        "verdict": gate_evaluation["verdict"],
        "verified": {
            "decision_records": len(decisions),
            "directional_decisions": len(selected),
            "failed_gate_ids": gate_evaluation["failed_gate_ids"],
            "no_bias_decisions": len(decisions) - len(selected),
            "passed_gates": gate_evaluation["passed_gate_count"],
            "source_cross_market_records": len(crosses),
            "source_session_records": len(cases),
            "total_gates": gate_evaluation["total_gate_count"],
        },
    }
    validation["validation_hash"] = canonical_hash(
        {
            key: value
            for key, value in validation.items()
            if key != "validation_hash"
        }
    )
    output = bundle_root / "semantic_validation.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite validation evidence: {output}")
    _write_json(output, validation)
    print(json.dumps(validation, indent=2, sort_keys=True))


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Independently validate the one-time calendar-2024 result.",
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
        "--validation-bundle",
        default="research_artifacts/gold_casebook_chronological_validation_v01",
    )
    return parser


def _verify_source_artifact_hashes(
    manifest: Mapping[str, Any],
    *,
    casebook_root: Path,
    baseline_root: Path,
) -> None:
    casebook_manifest = _load_json(casebook_root / "manifest.json")
    if (
        _verify_hashed_document(
            casebook_manifest,
            hash_field="manifest_hash",
            label="casebook manifest",
        )
        != manifest["source"]["casebook_manifest_hash"]
    ):
        raise ValueError("Casebook manifest hash changed")
    for name, expected_key in (
        ("sessions.jsonl.gz", "casebook_sessions_sha256"),
        ("cross_market_snapshots.jsonl.gz", "casebook_cross_market_sha256"),
    ):
        artifact = _artifact(casebook_manifest, name)
        if artifact["sha256"] != manifest["source"][expected_key]:
            raise ValueError(f"Frozen source hash changed: {name}")
        _verify_file_hash(casebook_root / name, str(artifact["sha256"]))

    baseline_manifest = _load_json(baseline_root / "manifest.json")
    if (
        _verify_hashed_document(
            baseline_manifest,
            hash_field="manifest_hash",
            label="baseline manifest",
        )
        != manifest["source"]["baseline_bundle_manifest_hash"]
    ):
        raise ValueError("Baseline manifest hash changed")
    trades = _artifact(baseline_manifest, "trades.jsonl.gz")
    if trades["sha256"] != manifest["source"]["baseline_trades_sha256"]:
        raise ValueError("Baseline trade source hash changed")
    _verify_file_hash(baseline_root / "trades.jsonl.gz", str(trades["sha256"]))


def _load_source_cases(path: Path) -> dict[str, SourceCase]:
    records: list[Mapping[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line:
                raise ValueError("Session source contains calendar 2025")
            if '"session_date":"2024-' not in line:
                continue
            record = json.loads(line)
            if record["record_type"] != "SESSION_CASE":
                continue
            _verify_casebook_record(record)
            records.append(record)
    halves: dict[str, str] = {}
    for session_code in SESSION_CODES:
        ordered = sorted(
            (
                record
                for record in records
                if record["session_code"] == session_code
            ),
            key=lambda item: (item["decision_at"], item["record_id"]),
        )
        split = len(ordered) // 2
        for index, record in enumerate(ordered):
            halves[str(record["record_id"])] = (
                "EARLY" if index < split else "LATE"
            )
    output: dict[str, SourceCase] = {}
    for record in records:
        case_id = str(record["record_id"])
        session_date = date.fromisoformat(record["session_date"])
        if not date(2024, 1, 1) <= session_date < date(2025, 1, 1):
            raise ValueError("Source session is outside validation")
        output[case_id] = SourceCase(
            case_id=case_id,
            record_hash=str(record["record_hash"]),
            session_code=str(record["session_code"]),
            session_date=session_date,
            decision_at=_timestamp(record["decision_at"]),
            observation_end=_timestamp(record["observation_end"]),
            cross_record_id=str(
                record["decision_state"]["cross_market_snapshot_id"]
            ),
            chronological_half=halves[case_id],
        )
    return output


def _load_source_crosses(
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
                raise ValueError("Unexpected cross-market record type")
            if _timestamp(record["as_of"]) >= datetime(2025, 1, 1, tzinfo=UTC):
                raise ValueError("Cross-market source enters calendar 2025")
            output[str(record_id)] = record
            if len(output) == len(wanted):
                break
    if output.keys() != wanted:
        raise ValueError("Cross-market source join is incomplete")
    return output


def _expected_feature(
    case: SourceCase,
    *,
    cross: Mapping[str, Any],
) -> ExpectedFeature:
    if _timestamp(cross["as_of"]) != case.decision_at:
        raise ValueError(f"Cross as-of mismatch: {case.case_id}")
    if _timestamp(cross["available_at"]) > case.decision_at:
        raise ValueError(f"Cross unavailable at decision: {case.case_id}")
    timezone = SESSION_TIMEZONES[case.session_code]
    if case.decision_at.astimezone(timezone).strftime("%H:%M") != "08:00":
        raise ValueError(f"Decision clock mismatch: {case.case_id}")
    if case.observation_end.astimezone(timezone).strftime("%H:%M") != "12:00":
        raise ValueError(f"Exit clock mismatch: {case.case_id}")

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
        if _timestamp(state["available_at"]) > case.decision_at:
            raise ValueError(f"ZN unavailable at decision: {case.case_id}")
        if _timestamp(state["observed_at"]) > case.decision_at:
            raise ValueError(f"ZN observed after decision: {case.case_id}")
        evidence["instrument_status"] = state["status"]
        evidence["current_instrument_id"] = state.get("instrument_id")
        change = state["changes"].get("4_HOURS")
        if change is not None:
            evidence["change_status"] = change["status"]
            evidence["change_reason"] = change.get("reason")
            evidence["reference_instrument_id"] = change.get(
                "reference_instrument_id"
            )
            if change["status"] == "READY":
                if _timestamp(change["reference_available_at"]) > case.decision_at:
                    raise ValueError(f"ZN reference unavailable: {case.case_id}")
                if _timestamp(change["reference_at"]) > case.decision_at:
                    raise ValueError(f"ZN reference is future: {case.case_id}")
        if (
            state["status"] == "READY"
            and change is not None
            and change["status"] == "READY"
            and change.get("percent_change") is not None
        ):
            raw_value = float(change["percent_change"])
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
    )
    decision = select_universal_zn_4h_bias(
        feature,
        session_code=case.session_code,
    )
    return ExpectedFeature(
        feature=feature,
        bias=decision.bias,
        reason_code=decision.reason_code,
        evidence=evidence,
        cross_record_hash=str(cross["record_hash"]),
    )


def _load_source_trades(
    path: Path,
    *,
    execution_manifest_hash: str,
    cases: Mapping[str, SourceCase],
) -> dict[str, dict[str, SourceTrade]]:
    output: dict[str, dict[str, SourceTrade]] = defaultdict(dict)
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line:
                raise ValueError("Baseline source contains calendar 2025")
            if '"session_date":"2024-' not in line:
                continue
            if (
                '"control_code":"ALWAYS_LONG"' not in line
                and '"control_code":"ALWAYS_SHORT"' not in line
            ):
                continue
            record = json.loads(line)
            _verify_record_hash(record)
            if record["execution_manifest_hash"] != execution_manifest_hash:
                raise ValueError("Execution manifest hash changed")
            case_id = str(record["case_id"])
            trade = _trade_from_record(record)
            case = cases[case_id]
            if (
                trade.case_record_hash != case.record_hash
                or trade.session_code != case.session_code
                or trade.session_date != case.session_date
                or trade.decision_at != case.decision_at
                or trade.entry_time != case.decision_at + timedelta(minutes=1)
                or trade.exit_time != case.observation_end
            ):
                raise ValueError(f"Baseline trade lineage mismatch: {case_id}")
            output[case_id][trade.side] = SourceTrade(
                record_id=str(record["record_id"]),
                record_hash=str(record["record_hash"]),
                trade=trade,
            )
    if set(output) != set(cases):
        raise ValueError("Baseline validation case set differs from sessions")
    if any(set(sides) != {"LONG", "SHORT"} for sides in output.values()):
        raise ValueError("A validation case lacks both fixed outcomes")
    return dict(output)


def _load_and_verify_decisions(
    path: Path,
    *,
    validation_manifest_hash: str,
    case_specification_hash: str,
    cases: Mapping[str, SourceCase],
    expected_features: Mapping[str, ExpectedFeature],
    trades: Mapping[str, Mapping[str, SourceTrade]],
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if '"session_date":"2025-' in line:
                raise ValueError("Decision artifact contains calendar 2025")
            record = json.loads(line)
            _verify_record_hash(record)
            case_id = str(record["case_id"])
            case = cases[case_id]
            expected = expected_features[case_id]
            if record["validation_manifest_hash"] != validation_manifest_hash:
                raise ValueError("Decision validation manifest hash changed")
            if (
                record["case_specification_manifest_hash"]
                != case_specification_hash
            ):
                raise ValueError("Decision case specification hash changed")
            if (
                record["source_session_record_id"] != case_id
                or record["source_session_record_hash"] != case.record_hash
                or record["source_cross_record_hash"]
                != expected.cross_record_hash
            ):
                raise ValueError(f"Decision source lineage mismatch: {case_id}")
            if (
                record["bias"] != expected.bias
                or record["reason_code"] != expected.reason_code
                or record["chronological_half"] != case.chronological_half
                or record["integrity_issues"] != []
            ):
                raise ValueError(f"Decision rule does not reconstruct: {case_id}")
            feature = record["feature"]
            if feature != {
                "epistemic_status": "CALCULATED",
                "evidence": expected.evidence,
                "family_code": FEATURE_FAMILY,
                "feature_id": FEATURE_ID,
                "raw_percent_change": expected.feature.raw_value,
                "source_key": expected.feature.source_key,
                "state": expected.feature.state,
                "transform": FEATURE_TRANSFORM,
            }:
                raise ValueError(f"Decision feature does not reconstruct: {case_id}")
            if expected.bias == "NO_BIAS":
                if record["selected_outcome"] is not None:
                    raise ValueError(f"NO_BIAS case has outcome: {case_id}")
            else:
                source_trade = trades[case_id][expected.bias]
                if record["selected_outcome"] != _expected_outcome(source_trade):
                    raise ValueError(f"Selected outcome mismatch: {case_id}")
            output[case_id] = record
    return output


def _expected_outcome(source: SourceTrade) -> dict[str, Any]:
    trade = source.trade
    return {
        "baseline_trade_record_hash": source.record_hash,
        "baseline_trade_record_id": source.record_id,
        "commission_usd": trade.commission_usd,
        "entry_time": trade.entry_time.isoformat(),
        "exit_time": trade.exit_time.isoformat(),
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


def _verify_session(
    session_code: str,
    *,
    decisions: Mapping[str, Mapping[str, Any]],
    cases: Mapping[str, SourceCase],
    trades: Mapping[str, Mapping[str, SourceTrade]],
    expected: Mapping[str, Any],
    validation_manifest_hash: str,
    bootstrap_replications: int,
) -> Mapping[str, Any]:
    session_decisions = {
        case_id: record
        for case_id, record in decisions.items()
        if record["session_code"] == session_code
    }
    selected = [
        trades[case_id][str(record["bias"])].trade
        for case_id, record in session_decisions.items()
        if record["bias"] in {"LONG", "SHORT"}
    ]
    selector_metrics = calculate_baseline_metrics(selected)
    if selector_metrics != expected["selector_metrics"]:
        raise ValueError(f"{session_code} selector metrics differ")
    controls = {
        f"ALWAYS_{side}": calculate_baseline_metrics(
            [trades[case_id][side].trade for case_id in session_decisions]
        )
        for side in ("LONG", "SHORT")
    }
    if controls != expected["validation_unconditional_controls"]:
        raise ValueError(f"{session_code} controls differ")
    best_control = max(
        controls,
        key=lambda key: (
            float(controls[key]["mean_net_return_basis_points"]),
            key,
        ),
    )
    if best_control != expected["best_validation_unconditional_control"]:
        raise ValueError(f"{session_code} best control differs")
    excess = round(
        float(selector_metrics["mean_net_return_basis_points"])
        - float(controls[best_control]["mean_net_return_basis_points"]),
        8,
    )
    if excess != expected[
        "selector_excess_mean_net_return_vs_best_control_bps"
    ]:
        raise ValueError(f"{session_code} control excess differs")

    state_results: dict[str, Any] = {}
    for state in ("POSITIVE", "NEGATIVE"):
        state_cases = [
            case_id
            for case_id, record in session_decisions.items()
            if record["feature"]["state"] == state
        ]
        state_selected = [
            trades[case_id][str(session_decisions[case_id]["bias"])].trade
            for case_id in state_cases
        ]
        state_results[state] = {
            "bias": "LONG" if state == "POSITIVE" else "SHORT",
            "case_count": len(state_cases),
            "iso_week_cluster_count": len(
                {_iso_week_key(cases[case_id].session_date) for case_id in state_cases}
            ),
            "metrics": calculate_baseline_metrics(state_selected),
        }
    if state_results != expected["directional_state_results"]:
        raise ValueError(f"{session_code} state results differ")

    halves = {
        half: calculate_baseline_metrics(
            [
                trades[case_id][str(record["bias"])].trade
                for case_id, record in session_decisions.items()
                if record["chronological_half"] == half
                and record["bias"] in {"LONG", "SHORT"}
            ]
        )
        for half in ("EARLY", "LATE")
    }
    if halves != expected["chronological_halves"]:
        raise ValueError(f"{session_code} half results differ")
    stress = calculate_baseline_metrics(
        [apply_cost_multiplier(trade, multiplier=1.5) for trade in selected]
    )
    if stress != expected["cost_stress_1_5x"]:
        raise ValueError(f"{session_code} cost stress differs")
    interval = _week_cluster_bootstrap_ci(
        selected,
        replications=bootstrap_replications,
        seed_material=f"{validation_manifest_hash}|{session_code}|{SELECTOR_CODE}",
    )
    if interval != expected[
        "bootstrap_95pct_ci_mean_net_return_basis_points"
    ]:
        raise ValueError(f"{session_code} bootstrap differs")
    reason_counts = dict(
        sorted(Counter(record["reason_code"] for record in session_decisions.values()).items())
    )
    if reason_counts != expected["reason_counts"]:
        raise ValueError(f"{session_code} reason counts differ")
    if (
        len(session_decisions) != expected["total_case_count"]
        or sum(
            record["bias"] == "NO_BIAS"
            for record in session_decisions.values()
        )
        != expected["no_bias_count"]
    ):
        raise ValueError(f"{session_code} coverage differs")
    return {
        **expected,
        "best_validation_unconditional_control": best_control,
        "chronological_halves": halves,
        "cost_stress_1_5x": stress,
        "directional_state_results": state_results,
        "selector_excess_mean_net_return_vs_best_control_bps": excess,
        "selector_metrics": selector_metrics,
        "validation_unconditional_controls": controls,
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
        round(quantile_type_7(means, 0.025), 8),
        round(quantile_type_7(means, 0.975), 8),
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


def _verify_bundle_artifacts(
    root: Path,
    manifest: Mapping[str, Any],
) -> None:
    for name in ("validation_decisions.jsonl.gz", "validation_results.json"):
        artifact = _artifact(manifest, name)
        path = root / name
        if path.stat().st_size != artifact["bytes"]:
            raise ValueError(f"Bundle artifact size changed: {name}")
        _verify_file_hash(path, str(artifact["sha256"]))


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
    name: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == name]
    if len(matches) != 1:
        raise ValueError(f"Manifest does not contain exactly one {name}")
    return matches[0]


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


if __name__ == "__main__":
    main()
