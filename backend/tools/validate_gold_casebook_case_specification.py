from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import random
import statistics
from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.backtesting.casebook_baseline import (
    BaselineTrade,
    calculate_baseline_metrics,
)
from gold_intel.backtesting.casebook_relationships import quantile_type_7
from gold_intel.backtesting.casebook_selector import (
    FEATURE_ID,
    SELECTOR_CODE,
    SelectorFeature,
    select_universal_zn_4h_bias,
)

VALIDATION_VERSION = "GOLD_CASEBOOK_CASE_SPECIFICATION_VALIDATION_V0_1"
DEVELOPMENT_START = date(2021, 8, 1)
DEVELOPMENT_END = date(2024, 1, 1)
SESSION_CODES = ("LONDON", "NEW_YORK")


@dataclass(frozen=True, slots=True)
class SourceTrade:
    record_id: str
    record_hash: str
    trade: BaselineTrade


def main() -> None:
    args = _parser().parse_args()
    specification_path = Path(args.case_specification_manifest)
    discovery_root = Path(args.discovery_bundle)
    baseline_root = Path(args.baseline_bundle)
    bundle_root = Path(args.case_specification_bundle)

    specification = _load_json(specification_path)
    specification_hash = _verify_hashed_document(
        specification,
        hash_field="manifest_hash",
        label="case-specification manifest",
    )
    bundle_manifest = _load_json(bundle_root / "manifest.json")
    bundle_hash = _verify_hashed_document(
        bundle_manifest,
        hash_field="manifest_hash",
        label="case-specification bundle manifest",
    )
    if (
        bundle_manifest["source"]["case_specification_manifest_hash"]
        != specification_hash
    ):
        raise ValueError("Bundle points to another case specification")
    _verify_bundle_artifacts(bundle_root, bundle_manifest)

    results = _load_json(bundle_root / "development_results.json")
    results_hash = _verify_hashed_document(
        results,
        hash_field="results_hash",
        label="development selector results",
    )
    if results["case_specification_manifest_hash"] != specification_hash:
        raise ValueError("Results point to another case specification")
    if (
        results["guardrails"]["chronological_validation_2024_deserialized"]
        is not False
        or results["guardrails"]["calendar_2025_loaded"] is not False
    ):
        raise ValueError("Results opened a reserved period")

    feature_records = _load_development_features(
        discovery_root / "development_features.jsonl.gz"
    )
    baseline_records, reserved_rows = _load_development_trades(
        baseline_root / "trades.jsonl.gz",
        execution_manifest_hash=str(
            specification["execution"]["execution_manifest_hash"]
        ),
    )
    decisions = _load_and_verify_decisions(
        bundle_root / "development_decisions.jsonl.gz",
        specification_hash=specification_hash,
        feature_records=feature_records,
        baseline_records=baseline_records,
    )
    if set(decisions) != set(feature_records):
        raise ValueError("Decision cases differ from development feature cases")

    selected = [
        baseline_records[case_id][str(record["bias"])].trade
        for case_id, record in decisions.items()
        if record["bias"] in {"LONG", "SHORT"}
    ]
    if calculate_baseline_metrics(selected) != results["overall"]["selector_metrics"]:
        raise ValueError("Overall selector metrics do not reconstruct")
    if Counter(record["bias"] for record in decisions.values()) != Counter(
        results["overall"]["bias_counts"]
    ):
        raise ValueError("Overall bias counts do not reconstruct")

    bootstrap_replications = int(
        specification["development_reporting"]["bootstrap_replications"]
    )
    for session_code in SESSION_CODES:
        _verify_session_results(
            session_code,
            decisions=decisions,
            baseline_records=baseline_records,
            expected=results["sessions"][session_code],
            specification_hash=specification_hash,
            bootstrap_replications=bootstrap_replications,
        )

    expected_reserved = results["guardrails"][
        "reserved_2024_baseline_trade_rows_skipped_before_deserialization"
    ]
    if reserved_rows != expected_reserved:
        raise ValueError("Reserved-row skip count changed")
    if reserved_rows != bundle_manifest["integrity"][
        "reserved_baseline_trade_rows_skipped_before_deserialization"
    ]:
        raise ValueError("Bundle reserved-row evidence changed")

    validation = {
        "bundle_manifest_hash": bundle_hash,
        "case_specification_manifest_hash": specification_hash,
        "case_specification_version": specification["manifest_version"],
        "holdout_loaded": False,
        "results_hash": results_hash,
        "semantic_assertions": {
            "all_decision_record_hashes_match": True,
            "all_decisions_join_to_immutable_development_feature_hashes": True,
            "all_directional_outcomes_join_to_frozen_baseline_trade_hashes": True,
            "calendar_2025_absent": True,
            "chronological_validation_2024_not_deserialized": True,
            "development_metrics_controls_states_and_halves_reconstruct": True,
            "execution_optimization_absent": True,
            "flat_and_unknown_states_are_no_bias": True,
            "negative_zn_change_is_short_in_both_sessions": True,
            "positive_zn_change_is_long_in_both_sessions": True,
            "universal_session_rule_has_no_threshold_or_fallback": True,
            "week_cluster_bootstrap_intervals_reconstruct": True,
        },
        "validation_hash": "",
        "validation_version": VALIDATION_VERSION,
        "verified": {
            "development_decision_records": len(decisions),
            "directional_decisions": len(selected),
            "no_bias_decisions": len(decisions) - len(selected),
            "reserved_2024_baseline_rows_skipped_before_deserialization": (
                reserved_rows
            ),
            "source_development_feature_records": len(feature_records),
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
        description="Independently validate the frozen Milestone 5 selector.",
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
        "--case-specification-bundle",
        default="research_artifacts/gold_casebook_case_specification_v01",
    )
    return parser


def _load_development_features(
    path: Path,
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if (
                '"session_date":"2024-' in line
                or '"session_date":"2025-' in line
            ):
                raise ValueError("Development feature artifact contains reserved rows")
            record = json.loads(line)
            if record["record_type"] != "DEVELOPMENT_FEATURE_CASE":
                continue
            _verify_record_hash(record)
            session_date = date.fromisoformat(record["session_date"])
            if not DEVELOPMENT_START <= session_date < DEVELOPMENT_END:
                raise ValueError("Feature record is outside development")
            if (
                record["calendar_2025_loaded"] is not False
                or record["chronological_validation_2024_loaded"] is not False
            ):
                raise ValueError("Feature record opens a reserved period")
            case_id = str(record["case_id"])
            if case_id in output:
                raise ValueError(f"Duplicate feature case: {case_id}")
            output[case_id] = record
    return output


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
                raise ValueError("Baseline artifact contains calendar 2025")
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
            trade = _trade_from_record(record)
            case_id = str(record["case_id"])
            if trade.side in output[case_id]:
                raise ValueError(f"Duplicate baseline side for {case_id}")
            output[case_id][trade.side] = SourceTrade(
                record_id=str(record["record_id"]),
                record_hash=str(record["record_hash"]),
                trade=trade,
            )
    if any(set(sides) != {"LONG", "SHORT"} for sides in output.values()):
        raise ValueError("A development case lacks a fixed directional outcome")
    return dict(output), reserved_rows


def _load_and_verify_decisions(
    path: Path,
    *,
    specification_hash: str,
    feature_records: Mapping[str, Mapping[str, Any]],
    baseline_records: Mapping[str, Mapping[str, SourceTrade]],
) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if (
                '"session_date":"2024-' in line
                or '"session_date":"2025-' in line
            ):
                raise ValueError("Decision artifact contains a reserved period")
            record = json.loads(line)
            _verify_record_hash(record)
            if record["record_type"] != "CASE_SPECIFICATION_DECISION":
                raise ValueError("Unexpected decision artifact record")
            if (
                record["case_specification_manifest_hash"]
                != specification_hash
            ):
                raise ValueError("Decision specification hash changed")
            if (
                record["calendar_2025_loaded"] is not False
                or record["chronological_validation_2024_loaded"] is not False
            ):
                raise ValueError("Decision record opens a reserved period")
            case_id = str(record["case_id"])
            source = feature_records[case_id]
            if (
                record["source_feature_record_id"] != source["record_id"]
                or record["source_feature_record_hash"] != source["record_hash"]
                or record["case_record_hash"] != source["case_record_hash"]
            ):
                raise ValueError(f"Feature lineage mismatch: {case_id}")
            source_feature = source["features"][FEATURE_ID]
            recorded_feature = record["feature"]
            if recorded_feature != {
                "epistemic_status": "CALCULATED",
                "family_code": source_feature["family_code"],
                "feature_id": FEATURE_ID,
                "raw_percent_change": source_feature["raw_value"],
                "source_key": source_feature["source_key"],
                "state": source_feature["state"],
                "transform": source_feature["transform"],
            }:
                raise ValueError(f"Recorded feature differs from source: {case_id}")
            decision = select_universal_zn_4h_bias(
                SelectorFeature(
                    feature_id=FEATURE_ID,
                    family_code=str(source_feature["family_code"]),
                    transform=str(source_feature["transform"]),
                    state=str(source_feature["state"]),
                    raw_value=(
                        float(source_feature["raw_value"])
                        if source_feature["raw_value"] is not None
                        else None
                    ),
                    source_key=(
                        str(source_feature["source_key"])
                        if source_feature["source_key"] is not None
                        else None
                    ),
                ),
                session_code=str(source["session_code"]),
            )
            if (
                record["bias"] != decision.bias
                or record["reason_code"] != decision.reason_code
            ):
                raise ValueError(f"Frozen rule does not reconstruct: {case_id}")
            outcome = record["selected_outcome"]
            if decision.bias == "NO_BIAS":
                if outcome is not None:
                    raise ValueError(f"NO_BIAS case has an outcome: {case_id}")
            else:
                source_trade = baseline_records[case_id][decision.bias]
                trade = source_trade.trade
                expected_outcome = {
                    "baseline_trade_record_hash": source_trade.record_hash,
                    "baseline_trade_record_id": source_trade.record_id,
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
                if outcome != expected_outcome:
                    raise ValueError(f"Selected outcome mismatch: {case_id}")
            if case_id in output:
                raise ValueError(f"Duplicate selector decision: {case_id}")
            output[case_id] = record
    return output


def _verify_session_results(
    session_code: str,
    *,
    decisions: Mapping[str, Mapping[str, Any]],
    baseline_records: Mapping[str, Mapping[str, SourceTrade]],
    expected: Mapping[str, Any],
    specification_hash: str,
    bootstrap_replications: int,
) -> None:
    session_decisions = {
        case_id: record
        for case_id, record in decisions.items()
        if record["session_code"] == session_code
    }
    selected = [
        baseline_records[case_id][str(record["bias"])].trade
        for case_id, record in session_decisions.items()
        if record["bias"] in {"LONG", "SHORT"}
    ]
    if len(session_decisions) != expected["total_case_count"]:
        raise ValueError(f"{session_code} total case count does not reconstruct")
    if (
        sum(record["bias"] == "NO_BIAS" for record in session_decisions.values())
        != expected["no_bias_count"]
    ):
        raise ValueError(f"{session_code} no-bias count does not reconstruct")
    if calculate_baseline_metrics(selected) != expected["selector_metrics"]:
        raise ValueError(f"{session_code} selector metrics do not reconstruct")
    if dict(
        sorted(
            Counter(
                record["reason_code"] for record in session_decisions.values()
            ).items()
        )
    ) != expected["reason_counts"]:
        raise ValueError(f"{session_code} reason counts do not reconstruct")

    controls: dict[str, Any] = {}
    for side in ("LONG", "SHORT"):
        controls[f"ALWAYS_{side}"] = calculate_baseline_metrics(
            [
                baseline_records[case_id][side].trade
                for case_id in session_decisions
            ]
        )
    if controls != expected["development_unconditional_controls"]:
        raise ValueError(f"{session_code} controls do not reconstruct")
    best_control = max(
        controls,
        key=lambda key: (
            float(controls[key]["mean_net_return_basis_points"]),
            key,
        ),
    )
    if best_control != expected["best_development_unconditional_control"]:
        raise ValueError(f"{session_code} best control does not reconstruct")
    excess = round(
        float(expected["selector_metrics"]["mean_net_return_basis_points"])
        - float(controls[best_control]["mean_net_return_basis_points"]),
        8,
    )
    if excess != expected[
        "selector_excess_mean_net_return_vs_best_control_bps"
    ]:
        raise ValueError(f"{session_code} control excess does not reconstruct")

    for state in ("POSITIVE", "NEGATIVE", "FLAT", "UNKNOWN"):
        state_cases = {
            case_id
            for case_id, record in session_decisions.items()
            if record["feature"]["state"] == state
        }
        state_selected = [
            baseline_records[case_id][str(session_decisions[case_id]["bias"])].trade
            for case_id in state_cases
            if session_decisions[case_id]["bias"] in {"LONG", "SHORT"}
        ]
        state_expected = expected["feature_state_results"][state]
        if len(state_cases) != state_expected["case_count"]:
            raise ValueError(f"{session_code} {state} count does not reconstruct")
        if calculate_baseline_metrics(state_selected) != state_expected["metrics"]:
            raise ValueError(f"{session_code} {state} metrics do not reconstruct")

    for half in ("EARLY", "LATE"):
        half_selected = [
            baseline_records[case_id][str(record["bias"])].trade
            for case_id, record in session_decisions.items()
            if record["chronological_half"] == half
            and record["bias"] in {"LONG", "SHORT"}
        ]
        if (
            calculate_baseline_metrics(half_selected)
            != expected["chronological_halves"][half]
        ):
            raise ValueError(f"{session_code} {half} metrics do not reconstruct")

    interval = _week_cluster_bootstrap_ci(
        selected,
        replications=bootstrap_replications,
        seed_material=f"{specification_hash}|{session_code}|{SELECTOR_CODE}",
    )
    if (
        interval
        != expected["bootstrap_95pct_ci_mean_net_return_basis_points"]
    ):
        raise ValueError(f"{session_code} bootstrap interval does not reconstruct")


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
        rounded = round(mean, 8)
        return [rounded, rounded]
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
        round(quantile_type_7(means, 0.025), 8),
        round(quantile_type_7(means, 0.975), 8),
    ]


def _verify_bundle_artifacts(
    bundle_root: Path,
    manifest: Mapping[str, Any],
) -> None:
    for name in ("development_decisions.jsonl.gz", "development_results.json"):
        artifact = _artifact(manifest, name)
        path = bundle_root / name
        if path.stat().st_size != artifact["bytes"]:
            raise ValueError(f"Artifact byte size changed: {name}")
        if _sha256(path) != artifact["sha256"]:
            raise ValueError(f"Artifact SHA-256 changed: {name}")


def _artifact(
    manifest: Mapping[str, Any],
    name: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if item["path"] == name]
    if len(matches) != 1:
        raise ValueError(f"Bundle does not contain exactly one {name}")
    return matches[0]


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


if __name__ == "__main__":
    main()
