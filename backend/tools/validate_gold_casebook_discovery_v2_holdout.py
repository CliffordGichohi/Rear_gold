from __future__ import annotations

import argparse
import bisect
import csv
import gzip
import json
import math
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

import run_gold_casebook_discovery_v2_holdout as runner

from gold_intel.analytics.casebook import canonical_hash, json_ready
from gold_intel.backtesting.casebook_baseline import (
    BaselineCase,
    BaselinePriceBar,
    simulate_baseline_case,
    trade_to_dict,
)
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    CANDIDATE_CODE,
    EXPECTED_EVALUATION_GATE_IDS,
    HoldoutCase,
    ZnHoldoutSample,
    ZnHoldoutSeries,
    build_holdout_report,
    evaluate_holdout_gates,
    validate_holdout_manifest,
)

LONDON = ZoneInfo("Europe/London")
VALIDATION_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_M6_HOLDOUT_VALIDATION_V0_1"


def main() -> None:
    args = _parser().parse_args()
    bundle_root = Path(args.bundle)
    output = Path(args.output) if args.output else bundle_root / "semantic_validation.json"
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite semantic validation: {output}")

    research = runner._load_json(Path(args.research_manifest))
    research_hash = validate_holdout_manifest(research)
    execution = runner._load_json(Path(args.execution_manifest))
    execution_hash = runner._verify_hashed_document(
        execution,
        hash_field="manifest_hash",
        label="constant execution manifest",
    )
    if execution_hash != research["source"]["execution_manifest_hash"]:
        raise ValueError("Execution lineage changed")
    readiness = runner._verify_readiness_bundle(
        Path(args.readiness_bundle),
        research_hash=research_hash,
    )
    acquisition, normalization, normalized_dir = runner._verify_sealed_sources(
        Path(args.acquisition_root),
        readiness=readiness,
        research_hash=research_hash,
    )
    open_intent = runner._load_json(Path(args.open_intent))
    open_intent_hash = runner._verify_hashed_document(
        open_intent,
        hash_field="open_intent_hash",
        label="M6 one-time open intent",
    )
    _verify_open_intent(
        open_intent,
        research_hash=research_hash,
        readiness=readiness,
        acquisition=acquisition,
        normalization=normalization,
    )

    bundle = runner._load_json(bundle_root / "manifest.json")
    bundle_hash = runner._verify_hashed_document(
        bundle,
        hash_field="manifest_hash",
        label="M6 holdout bundle manifest",
    )
    _verify_bundle(
        bundle,
        research_hash=research_hash,
        readiness=readiness,
        execution_hash=execution_hash,
        normalization=normalization,
        open_intent_hash=open_intent_hash,
    )
    for artifact in bundle["artifacts"]:
        runner._verify_file(
            bundle_root / str(artifact["path"]),
            sha256=str(artifact["sha256"]),
            size=int(artifact["bytes"]),
        )

    results = runner._load_json(bundle_root / "holdout_results.json")
    results_hash = runner._verify_hashed_document(
        results,
        hash_field="results_hash",
        label="M6 holdout results",
    )
    if runner._artifact(bundle, "holdout_results.json")["document_hash"] != results_hash:
        raise ValueError("Holdout result document hash changed")
    lineage = _load_timestamp_lineage(
        normalized_dir,
        normalization=normalization,
        expected_sha256=str(readiness["source_seals"]["zn_timestamp_lineage_sha256"]),
    )
    decisions = _load_and_reconstruct_decisions(
        bundle_root / "decisions.jsonl.gz",
        expected_count=int(runner._artifact(bundle, "decisions.jsonl.gz")["record_count"]),
        research=research,
        research_hash=research_hash,
        readiness_hash=str(readiness["readiness_hash"]),
        execution_hash=execution_hash,
        timestamp_lineage=lineage,
    )
    cases = [item["case"] for item in decisions]
    _verify_chronological_halves(cases)

    uncertainty = research["evaluation"]["uncertainty"]
    expected_report = build_holdout_report(
        cases,
        manifest_hash=research_hash,
        bootstrap_replications=int(uncertainty["bootstrap_replications"]),
        sign_flip_replications=int(uncertainty["sign_flip_replications"]),
        stress_multiplier=float(research["execution"]["cost_stress_multiplier"]),
    )
    thresholds = research["evaluation"]["thresholds"]
    expected_gates = evaluate_holdout_gates(
        expected_report,
        integrity_passed=True,
        minimum_directional_cases=int(thresholds["minimum_directional_cases"]),
        minimum_state_cases=int(thresholds["minimum_state_cases"]),
        minimum_state_week_clusters=int(thresholds["minimum_state_iso_week_clusters"]),
        minimum_half_directional_cases=int(thresholds["minimum_directional_cases_per_half"]),
        maximum_q_value=float(thresholds["maximum_q_value"]),
    )
    if tuple(item["gate_id"] for item in expected_gates["gates"]) != (EXPECTED_EVALUATION_GATE_IDS):
        raise AssertionError("Reconstructed holdout gates changed")
    if json_ready(expected_report) != results["report"]:
        raise ValueError("Holdout report does not independently reconstruct")
    if json_ready(expected_gates) != results["gate_evaluation"]:
        raise ValueError("Holdout gates do not independently reconstruct")
    if results["verdict"] != expected_gates["verdict"]:
        raise ValueError("Holdout verdict does not independently reconstruct")
    _verify_result_metadata(
        results,
        research=research,
        research_hash=research_hash,
        readiness=readiness,
        acquisition=acquisition,
        normalization=normalization,
        open_intent_hash=open_intent_hash,
        decision_count=len(decisions),
    )

    validation: dict[str, Any] = {
        "validation_version": VALIDATION_VERSION,
        "holdout_version": results["holdout_version"],
        "milestone": "V2_M6_CALENDAR_2025_HOLDOUT",
        "research_manifest_hash": research_hash,
        "readiness_hash": readiness["readiness_hash"],
        "bundle_manifest_hash": bundle_hash,
        "results_hash": results_hash,
        "open_intent_hash": open_intent_hash,
        "verdict": expected_gates["verdict"],
        "verified": {
            "bundle_artifact_hashes": len(bundle["artifacts"]),
            "decision_records": len(decisions),
            "timestamp_lineage_rows": len(lineage["available_times"]),
            "evaluation_gates": len(expected_gates["gates"]),
            "evaluated_candidates": 1,
            "evaluated_sessions": 1,
            "holdout_open_count": 1,
        },
        "semantic_assertions": {
            "all_source_and_bundle_hashes_match": True,
            "all_five_readiness_gates_reverified": True,
            "one_time_open_intent_verified": True,
            "latest_point_in_time_zn_endpoints_verified_from_timestamp_lineage": (True),
            "zn_feature_sign_and_roll_policy_recomputed_for_every_case": True,
            "xau_source_identity_hashes_recomputed_for_every_execution_bar": (True),
            "long_and_short_execution_cost_identities_recomputed": True,
            "chronological_halves_recomputed_before_no_bias_removal": True,
            "matched_controls_recomputed_on_directional_population": True,
            "base_and_1_5x_cost_results_recomputed": True,
            "cluster_bootstrap_interval_recomputed": True,
            "cluster_sign_flip_p_value_recomputed": True,
            "one_candidate_bh_q_value_recomputed": True,
            "all_twelve_frozen_gates_and_verdict_recomputed": True,
            "candidate_changed": False,
            "execution_changed": False,
            "new_york_evaluated": False,
            "calendar_2026_loaded": False,
            "parameter_search_performed": False,
        },
        "result": "PASS_SEMANTIC_VALIDATION",
    }
    validation["validation_hash"] = canonical_hash(validation)
    output.write_text(
        json.dumps(json_ready(validation), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    runner._progress(
        "V2_M6_SEMANTIC_VALIDATION_COMPLETE",
        output=str(output),
        validation_hash=validation["validation_hash"],
        verdict=expected_gates["verdict"],
        failed_gate_ids=expected_gates["failed_gate_ids"],
        decision_records=len(decisions),
        calendar_2025_open_count=1,
        calendar_2026_loaded=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Independently reconstruct the frozen V2 Milestone 6 "
            "calendar-2025 holdout decisions, metrics, gates, and verdict."
        )
    )
    parser.add_argument(
        "--bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_holdout_v01"),
    )
    parser.add_argument(
        "--research-manifest",
        default=("research_manifests/gold_casebook_discovery_v2_m6_holdout_v01.json"),
    )
    parser.add_argument(
        "--readiness-bundle",
        default=("research_artifacts/gold_casebook_discovery_v2_m6_readiness_v01"),
    )
    parser.add_argument(
        "--acquisition-root",
        default="data/raw/databento_cme_2025_zn",
    )
    parser.add_argument(
        "--execution-manifest",
        default=("research_manifests/gold_casebook_constant_execution_v01.json"),
    )
    parser.add_argument(
        "--open-intent",
        default=("research_artifacts/gold_casebook_discovery_v2_holdout_v01_open_intent.json"),
    )
    parser.add_argument("--output")
    return parser


def _verify_open_intent(
    intent: Mapping[str, Any],
    *,
    research_hash: str,
    readiness: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    normalization: Mapping[str, Any],
) -> None:
    if (
        intent["open_intent_version"] != runner.OPEN_INTENT_VERSION
        or intent["milestone"] != "V2_M6_CALENDAR_2025_HOLDOUT"
        or intent["research_manifest_hash"] != research_hash
        or intent["readiness_hash"] != readiness["readiness_hash"]
        or intent["readiness_bundle_manifest_hash"] != readiness["_bundle_manifest_hash"]
        or intent["all_five_readiness_gates_passed"] is not True
        or intent["job_id"] != acquisition["job_id"]
        or intent["normalization_hash"] != normalization["normalization_hash"]
        or int(intent["authorized_open_count"]) != 1
        or intent["candidate_code"] != CANDIDATE_CODE
        or intent["candidate_changed"] is not False
        or intent["execution_changed"] is not False
        or intent["calendar_2026_access_authorized"] is not False
    ):
        raise ValueError("One-time holdout open intent changed")


def _verify_bundle(
    bundle: Mapping[str, Any],
    *,
    research_hash: str,
    readiness: Mapping[str, Any],
    execution_hash: str,
    normalization: Mapping[str, Any],
    open_intent_hash: str,
) -> None:
    if (
        bundle["holdout_version"] != runner.M6_HOLDOUT_VERSION
        or bundle["schema_version"] != runner.M6_HOLDOUT_SCHEMA_VERSION
        or bundle["milestone"] != "V2_M6_CALENDAR_2025_HOLDOUT"
        or bundle["candidate_code"] != CANDIDATE_CODE
    ):
        raise ValueError("Holdout bundle identity changed")
    source = bundle["source"]
    expected = {
        "research_manifest_hash": research_hash,
        "readiness_hash": readiness["readiness_hash"],
        "readiness_bundle_manifest_hash": readiness["_bundle_manifest_hash"],
        "execution_manifest_hash": execution_hash,
        "acquisition_manifest_sha256": readiness["source_seals"]["zn_acquisition_manifest_sha256"],
        "normalization_hash": normalization["normalization_hash"],
        "zn_payload_sha256": readiness["source_seals"]["zn_payload_sha256"],
        "open_intent_hash": open_intent_hash,
    }
    if any(source[key] != value for key, value in expected.items()):
        raise ValueError("Holdout bundle source lineage changed")
    integrity = bundle["integrity"]
    if (
        integrity["all_five_readiness_gates_reverified"] is not True
        or int(integrity["holdout_open_count"]) != 1
        or integrity["semantic_validation_required"] is not True
        or any(
            integrity[key] is not False
            for key in (
                "candidate_changed",
                "execution_changed",
                "candidate_added_or_replaced",
                "new_york_evaluated",
                "calendar_2026_loaded",
                "parameter_search_performed",
            )
        )
    ):
        raise ValueError("Holdout bundle integrity guard changed")


def _load_timestamp_lineage(
    normalized_dir: Path,
    *,
    normalization: Mapping[str, Any],
    expected_sha256: str,
) -> dict[str, Any]:
    definition = normalization["timestamp_lineage"]
    path = normalized_dir / str(definition["path"])
    runner._verify_file(
        path,
        sha256=expected_sha256,
        size=int(definition["bytes"]),
    )
    available_times: list[datetime] = []
    rows: list[dict[str, Any]] = []
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for raw in csv.DictReader(handle):
            open_time = _timestamp(raw["open_time"])
            available_at = _timestamp(raw["available_at"])
            if (
                available_at != open_time + timedelta(minutes=1)
                or raw["continuous_symbol"] != "ZN.v.0"
                or (available_times and available_at <= available_times[-1])
            ):
                raise ValueError("ZN timestamp lineage failed validation")
            available_times.append(available_at)
            rows.append(
                {
                    "source_record_id": raw["source_record_id"],
                    "source_file_sha256": raw["source_file_sha256"],
                    "source_row_ordinal": int(raw["source_row_ordinal"]),
                    "open_time": open_time,
                    "available_at": available_at,
                    "continuous_symbol": raw["continuous_symbol"],
                    "instrument_id": int(raw["instrument_id"]),
                    "underlying_raw_symbol": raw["underlying_raw_symbol"],
                }
            )
    if len(rows) != int(normalization["total_rows"]):
        raise ValueError("ZN timestamp lineage count changed")
    return {"available_times": available_times, "rows": rows}


def _load_and_reconstruct_decisions(
    path: Path,
    *,
    expected_count: int,
    research: Mapping[str, Any],
    research_hash: str,
    readiness_hash: str,
    execution_hash: str,
    timestamp_lineage: Mapping[str, Any],
) -> list[dict[str, Any]]:
    config = runner._execution_config(
        research,
        execution_hash=execution_hash,
    )
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            record = json.loads(line)
            _verify_record_hash(record)
            case_id = str(record["case_id"])
            if case_id in seen:
                raise ValueError(f"Duplicate holdout decision: {case_id}")
            seen.add(case_id)
            if (
                record["record_type"] != "V2_M6_HOLDOUT_DECISION"
                or record["candidate_code"] != CANDIDATE_CODE
                or record["research_manifest_hash"] != research_hash
                or record["readiness_hash"] != readiness_hash
                or record["session_code"] != "LONDON"
                or any(record["guardrails"].values())
            ):
                raise ValueError(f"Holdout decision guard changed: {case_id}")
            session_date = date.fromisoformat(record["session_date"])
            decision_at = _timestamp(record["decision_at"])
            observation_end = _timestamp(record["observation_end"])
            _verify_clocks(
                session_date=session_date,
                decision_at=decision_at,
                observation_end=observation_end,
            )
            feature = _reconstruct_feature(
                record["feature"],
                decision_at=decision_at,
                timestamp_lineage=timestamp_lineage,
            )
            if record["bias"] != feature.bias:
                raise ValueError(f"Candidate bias changed: {case_id}")

            entry = _bar_from_record(record["execution"]["entry_bar"])
            exit_bar = _bar_from_record(record["execution"]["exit_bar"])
            case_record_hash = canonical_hash(
                {
                    "record_type": "V2_M6_HOLDOUT_CASE",
                    "case_id": case_id,
                    "research_manifest_hash": research_hash,
                    "readiness_hash": readiness_hash,
                    "session_code": "LONDON",
                    "session_date": session_date,
                    "decision_at": decision_at,
                    "observation_end": observation_end,
                    "entry_bar_hash": entry.record_hash,
                    "exit_bar_hash": exit_bar.record_hash,
                }
            )
            if record["case_record_hash"] != case_record_hash:
                raise ValueError(f"Holdout case hash changed: {case_id}")
            baseline_case = BaselineCase(
                case_id=case_id,
                case_record_hash=case_record_hash,
                session_code="LONDON",
                session_date=session_date,
                decision_at=decision_at,
                observation_end=observation_end,
            )
            long_trade = simulate_baseline_case(
                baseline_case,
                control_code="ALWAYS_LONG",
                entry_bar=entry,
                exit_bar=exit_bar,
                config=config,
            )
            short_trade = simulate_baseline_case(
                baseline_case,
                control_code="ALWAYS_SHORT",
                entry_bar=entry,
                exit_bar=exit_bar,
                config=config,
            )
            if (
                json_ready(trade_to_dict(long_trade)) != record["execution"]["always_long"]
                or json_ready(trade_to_dict(short_trade)) != record["execution"]["always_short"]
            ):
                raise ValueError(f"Frozen execution does not reconstruct: {case_id}")
            holdout_case = HoldoutCase(
                case_id=case_id,
                case_record_hash=case_record_hash,
                session_date=session_date,
                decision_at=decision_at,
                chronological_half=str(record["chronological_half"]),
                feature_state=feature.state,
                raw_percent_change=feature.raw_percent_change,
                feature_source_key=feature.source_key,
                reference_entry_price=entry.open,
                gross_move_usd_per_ounce=long_trade.gross_pnl_usd,
                cost_usd_per_ounce=long_trade.total_cost_usd,
                long_net_pnl_usd_per_ounce=long_trade.net_pnl_usd,
                long_net_return_basis_points=(long_trade.net_return_basis_points),
                short_net_pnl_usd_per_ounce=short_trade.net_pnl_usd,
                short_net_return_basis_points=(short_trade.net_return_basis_points),
            )
            _verify_selected_outcomes(
                record["execution"],
                case=holdout_case,
                bias=feature.bias,
                stress_multiplier=float(research["execution"]["cost_stress_multiplier"]),
            )
            output.append({"record": record, "case": holdout_case})
    if len(output) != expected_count:
        raise ValueError(f"Holdout decision count changed: {len(output)} != {expected_count}")
    ordered = sorted(
        output,
        key=lambda item: (
            item["case"].decision_at,
            item["case"].case_id,
        ),
    )
    if output != ordered:
        raise ValueError("Holdout decisions are not chronologically ordered")
    return output


def _reconstruct_feature(
    feature_record: Mapping[str, Any],
    *,
    decision_at: datetime,
    timestamp_lineage: Mapping[str, Any],
):
    available_times = timestamp_lineage["available_times"]
    rows = timestamp_lineage["rows"]
    current_index = bisect.bisect_right(available_times, decision_at) - 1
    reference_target = decision_at - timedelta(hours=4)
    reference_index = bisect.bisect_right(available_times, reference_target) - 1
    expected_current = rows[current_index] if current_index >= 0 else None
    expected_reference = rows[reference_index] if reference_index >= 0 else None
    current = _sample_from_record(feature_record.get("current"))
    reference = _sample_from_record(feature_record.get("reference"))
    if not _same_lineage(current, expected_current):
        raise ValueError("ZN current endpoint is not the latest available")
    if reference is not None and not _same_lineage(reference, expected_reference):
        raise ValueError("ZN reference endpoint is not the latest available")

    samples_by_id: dict[str, ZnHoldoutSample] = {}
    for sample in (reference, current):
        if sample is not None:
            samples_by_id[sample.source_record_id] = sample
    series = ZnHoldoutSeries.from_samples(
        sorted(
            samples_by_id.values(),
            key=lambda item: item.available_at,
        )
    )
    expected = series.feature_at(decision_at)
    comparable = {
        "feature_id": runner.FEATURE_ID,
        "state": expected.state,
        "reason_code": expected.reason_code,
        "raw_absolute_change": expected.raw_absolute_change,
        "raw_percent_change": expected.raw_percent_change,
        "source_key": expected.source_key,
        "current": json_ready(runner._zn_sample_dict(expected.current)),
        "reference": json_ready(runner._zn_sample_dict(expected.reference)),
    }
    if comparable != feature_record:
        raise ValueError("ZN feature does not independently reconstruct")
    return expected


def _sample_from_record(
    value: Mapping[str, Any] | None,
) -> ZnHoldoutSample | None:
    if value is None:
        return None
    return ZnHoldoutSample(
        source_record_id=str(value["source_record_id"]),
        source_file_sha256=str(value["source_file_sha256"]),
        source_row_ordinal=int(value["source_row_ordinal"]),
        open_time=_timestamp(value["open_time"]),
        available_at=_timestamp(value["available_at"]),
        continuous_symbol=str(value["continuous_symbol"]),
        instrument_id=int(value["instrument_id"]),
        underlying_raw_symbol=str(value["underlying_raw_symbol"]),
        close=float(value["close"]),
    )


def _same_lineage(
    sample: ZnHoldoutSample | None,
    expected: Mapping[str, Any] | None,
) -> bool:
    if sample is None or expected is None:
        return sample is None and expected is None
    return bool(
        sample.source_record_id == expected["source_record_id"]
        and sample.source_file_sha256 == expected["source_file_sha256"]
        and sample.source_row_ordinal == expected["source_row_ordinal"]
        and sample.open_time == expected["open_time"]
        and sample.available_at == expected["available_at"]
        and sample.continuous_symbol == expected["continuous_symbol"]
        and sample.instrument_id == expected["instrument_id"]
        and sample.underlying_raw_symbol == expected["underlying_raw_symbol"]
    )


def _bar_from_record(value: Mapping[str, Any]) -> BaselinePriceBar:
    identity = value["source_identity"]
    if canonical_hash(identity) != value["record_hash"]:
        raise ValueError("XAU execution bar source identity hash changed")
    if (
        identity["record_id"] != value["record_id"]
        or _timestamp(identity["open_time"]) != _timestamp(value["open_time"])
        or _timestamp(identity["close_time"]) != _timestamp(value["close_time"])
        or _timestamp(identity["available_at"]) != _timestamp(value["available_at"])
        or not math.isclose(
            float(identity["reference_open"]),
            float(value["reference_open"]),
            abs_tol=1e-12,
        )
        or not math.isclose(
            float(identity["reference_close"]),
            float(value["reference_close"]),
            abs_tol=1e-12,
        )
        or not math.isclose(
            float(identity["spread_price"]),
            float(value["spread_price"]),
            abs_tol=1e-12,
        )
    ):
        raise ValueError("XAU execution bar identity content changed")
    return BaselinePriceBar(
        record_id=str(value["record_id"]),
        record_hash=str(value["record_hash"]),
        open_time=_timestamp(value["open_time"]),
        close_time=_timestamp(value["close_time"]),
        open=float(value["reference_open"]),
        close=float(value["reference_close"]),
        spread_price=float(value["spread_price"]),
        available_at=_timestamp(value["available_at"]),
    )


def _verify_selected_outcomes(
    execution: Mapping[str, Any],
    *,
    case: HoldoutCase,
    bias: str,
    stress_multiplier: float,
) -> None:
    if bias == "NO_BIAS":
        if (
            execution["selected_base_outcome"] is not None
            or execution["selected_cost_stress_outcome"] is not None
        ):
            raise ValueError("NO_BIAS case contains a selected outcome")
        return
    pnl = case.long_net_pnl_usd_per_ounce if bias == "LONG" else case.short_net_pnl_usd_per_ounce
    return_bps = (
        case.long_net_return_basis_points if bias == "LONG" else case.short_net_return_basis_points
    )
    expected_base = {
        "side": bias,
        "net_pnl_usd_per_ounce": round(pnl, 8),
        "net_return_basis_points": round(return_bps, 8),
    }
    direction = 1 if bias == "LONG" else -1
    stressed_pnl = (
        direction * case.gross_move_usd_per_ounce - stress_multiplier * case.cost_usd_per_ounce
    )
    expected_stress = {
        "cost_multiplier": stress_multiplier,
        "side": bias,
        "net_pnl_usd_per_ounce": round(stressed_pnl, 8),
        "net_return_basis_points": round(
            10_000 * stressed_pnl / case.reference_entry_price,
            8,
        ),
    }
    if (
        execution["selected_base_outcome"] != expected_base
        or execution["selected_cost_stress_outcome"] != expected_stress
    ):
        raise ValueError(f"Selected outcome changed: {case.case_id}")


def _verify_chronological_halves(cases: Sequence[HoldoutCase]) -> None:
    ordered = sorted(cases, key=lambda item: (item.decision_at, item.case_id))
    early_count = len(ordered) // 2
    for index, case in enumerate(ordered):
        expected = "EARLY" if index < early_count else "LATE"
        if case.chronological_half != expected:
            raise ValueError(f"Chronological half changed: {case.case_id}")


def _verify_result_metadata(
    results: Mapping[str, Any],
    *,
    research: Mapping[str, Any],
    research_hash: str,
    readiness: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    normalization: Mapping[str, Any],
    open_intent_hash: str,
    decision_count: int,
) -> None:
    if (
        results["research_manifest_hash"] != research_hash
        or results["readiness_hash"] != readiness["readiness_hash"]
        or results["candidate"] != research["candidate"]
        or results["execution"] != research["execution"]
        or results["holdout"] != research["holdout"]
        or results["source"]["databento_job_id"] != acquisition["job_id"]
        or results["source"]["normalization_hash"] != normalization["normalization_hash"]
        or results["source"]["open_intent_hash"] != open_intent_hash
        or int(results["population"]["timestamp_complete_cases"]) != decision_count
    ):
        raise ValueError("Holdout result metadata changed")
    integrity = results["integrity"]
    if (
        integrity["point_in_time_and_lineage_integrity_passed"] is not True
        or integrity["all_five_readiness_gates_reverified"] is not True
        or int(integrity["holdout_open_count"]) != 1
        or int(integrity["issue_count"]) != 0
        or integrity["issues"]
        or any(
            integrity[key] is not False
            for key in (
                "candidate_changed",
                "candidate_added_or_replaced",
                "execution_changed",
                "parameter_search_performed",
                "new_york_evaluated",
                "calendar_2026_loaded",
                "human_chart_inspection_performed",
            )
        )
    ):
        raise ValueError("Holdout result integrity guard changed")
    interpretation = results["interpretation"]
    if (
        interpretation["next_milestone_authorized"] is not False
        or interpretation["stop_after_milestone_6"] is not True
        or interpretation["account_return_or_10r_claim_permitted"] is not False
    ):
        raise ValueError("Holdout result interpretation changed")


def _verify_clocks(
    *,
    session_date: date,
    decision_at: datetime,
    observation_end: datetime,
) -> None:
    local_decision = decision_at.astimezone(LONDON)
    local_end = observation_end.astimezone(LONDON)
    if (
        session_date.year != 2025
        or session_date.weekday() >= 5
        or local_decision.date() != session_date
        or local_end.date() != session_date
        or local_decision.time() != time(8)
        or local_end.time() != time(12)
    ):
        raise ValueError("Holdout London clock changed")


def _verify_record_hash(record: Mapping[str, Any]) -> None:
    supplied = str(record.get("record_hash", ""))
    content = {key: value for key, value in record.items() if key != "record_hash"}
    if not supplied or canonical_hash(content) != supplied:
        raise ValueError("Holdout decision record hash mismatch")


def _timestamp(value: Any) -> datetime:
    result = value if isinstance(value, datetime) else datetime.fromisoformat(str(value))
    if result.tzinfo is None:
        raise ValueError("Naive timestamp in holdout artifact")
    return result.astimezone(UTC)


if __name__ == "__main__":
    main()
