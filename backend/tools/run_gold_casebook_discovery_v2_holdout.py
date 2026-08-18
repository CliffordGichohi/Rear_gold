from __future__ import annotations

import argparse
import asyncio
import csv
import gzip
import hashlib
import io
import json
import math
import tempfile
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import bindparam, text

from gold_intel.analytics.casebook import (
    canonical_hash,
    finalize_record,
    json_ready,
)
from gold_intel.backtesting.casebook_baseline import (
    BaselineCase,
    BaselineExecutionConfig,
    BaselinePriceBar,
    BaselineTrade,
    simulate_baseline_case,
    trade_to_dict,
)
from gold_intel.backtesting.casebook_discovery_v2_holdout import (
    CANDIDATE_CODE,
    EXPECTED_EVALUATION_GATE_IDS,
    EXPECTED_READINESS_GATE_IDS,
    M6_HOLDOUT_SCHEMA_VERSION,
    M6_HOLDOUT_VERSION,
    HoldoutCase,
    ZnHoldoutFeature,
    ZnHoldoutSample,
    ZnHoldoutSeries,
    build_holdout_report,
    evaluate_holdout_gates,
    validate_holdout_manifest,
)
from gold_intel.infrastructure.database import session_factory

LONDON = ZoneInfo("Europe/London")
FEATURE_ID = "cross_zn_v_0_4_hours"
OPEN_INTENT_VERSION = "GOLD_CASEBOOK_DISCOVERY_V2_M6_OPEN_INTENT_V0_1"

XAU_EXECUTION_VALUE_SQL = """
SELECT
    CAST(p.id AS TEXT) AS record_id,
    p.open_time,
    p.close_time,
    p.available_at,
    p.provider_code,
    p.instrument_code,
    p.timeframe,
    p.open AS reference_open,
    p.close AS reference_close,
    p.spread_price,
    p.is_complete,
    p.is_synthetic,
    CAST(p.batch_id AS TEXT) AS batch_id,
    p.source_record_key,
    b.provider_code AS batch_provider_code,
    b.dataset_code,
    b.content_hash AS batch_content_hash,
    b.raw_object_path,
    b.is_synthetic AS batch_is_synthetic
FROM market.price_bars AS p
JOIN raw.ingestion_batches AS b ON b.id = p.batch_id
WHERE p.provider_code = 'IC_MARKETS_MT5'
  AND p.instrument_code = 'XAUUSD'
  AND p.timeframe = '1m'
  AND p.open_time IN :required_times
ORDER BY p.open_time
"""

EXPECTED_ZN_VALUE_COLUMNS = {
    "source_record_id",
    "source_file_sha256",
    "source_row_ordinal",
    "open_time",
    "available_at",
    "continuous_symbol",
    "instrument_id",
    "underlying_raw_symbol",
    "open",
    "high",
    "low",
    "close",
    "volume",
}


@dataclass(frozen=True, slots=True)
class SealedXauExecutionBar:
    bar: BaselinePriceBar
    identity: Mapping[str, Any]


@dataclass(frozen=True, slots=True)
class MaterializedHoldout:
    case: HoldoutCase
    feature: ZnHoldoutFeature
    entry_bar: BaselinePriceBar
    exit_bar: BaselinePriceBar
    entry_identity: Mapping[str, Any]
    exit_identity: Mapping[str, Any]
    long_trade: BaselineTrade
    short_trade: BaselineTrade


async def main() -> None:
    args = _parser().parse_args()
    research_path = Path(args.research_manifest)
    readiness_root = Path(args.readiness_bundle)
    acquisition_root = Path(args.acquisition_root)
    execution_path = Path(args.execution_manifest)
    output = Path(args.output)
    open_intent_path = Path(args.open_intent)
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite holdout bundle: {output}")
    if open_intent_path.exists():
        raise FileExistsError(
            "The one-time calendar-2025 holdout authorization has already "
            f"been consumed: {open_intent_path}"
        )
    output.parent.mkdir(parents=True, exist_ok=True)

    research = _load_json(research_path)
    research_hash = validate_holdout_manifest(research)
    execution = _load_json(execution_path)
    execution_hash = _verify_hashed_document(
        execution,
        hash_field="manifest_hash",
        label="constant execution manifest",
    )
    if execution_hash != research["source"]["execution_manifest_hash"]:
        raise ValueError("Frozen execution lineage changed")
    readiness = _verify_readiness_bundle(
        readiness_root,
        research_hash=research_hash,
    )
    acquisition, normalization, normalized_dir = _verify_sealed_sources(
        acquisition_root,
        readiness=readiness,
        research_hash=research_hash,
    )
    session_dates = _read_session_dates(readiness)
    _progress(
        "V2_M6_PREOPEN_GATES_REVERIFIED",
        research_manifest_hash=research_hash,
        readiness_hash=readiness["readiness_hash"],
        readiness_gate_count=len(readiness["gates"]),
        timestamp_complete_cases=len(session_dates),
        calendar_2025_values_accessed=False,
    )

    open_intent = _write_open_intent(
        open_intent_path,
        research_hash=research_hash,
        readiness=readiness,
        acquisition=acquisition,
        normalization=normalization,
    )

    # This is the sole transition across the frozen holdout boundary.
    required_times = _required_xau_value_times(session_dates)
    xau_bars = await _load_xau_execution_values(required_times)
    zn_series, zn_value_source = _load_zn_value_series(
        normalized_dir,
        normalization=normalization,
        expected_payload_sha256=str(readiness["source_seals"]["zn_payload_sha256"]),
    )
    _progress(
        "V2_M6_HOLDOUT_OPENED_ONCE",
        open_intent_hash=open_intent["open_intent_hash"],
        xau_execution_bars_loaded=len(xau_bars),
        zn_value_rows_loaded=len(zn_series.samples),
        calendar_2025_values_accessed=True,
        calendar_2026_values_accessed=False,
    )

    config = _execution_config(research, execution_hash=execution_hash)
    materialized = _materialize_cases(
        session_dates,
        xau_bars=xau_bars,
        zn_series=zn_series,
        config=config,
        research_hash=research_hash,
        readiness_hash=str(readiness["readiness_hash"]),
    )
    cases = [item.case for item in materialized]
    uncertainty = research["evaluation"]["uncertainty"]
    report = build_holdout_report(
        cases,
        manifest_hash=research_hash,
        bootstrap_replications=int(uncertainty["bootstrap_replications"]),
        sign_flip_replications=int(uncertainty["sign_flip_replications"]),
        stress_multiplier=float(research["execution"]["cost_stress_multiplier"]),
    )
    thresholds = research["evaluation"]["thresholds"]
    gates = evaluate_holdout_gates(
        report,
        integrity_passed=True,
        minimum_directional_cases=int(thresholds["minimum_directional_cases"]),
        minimum_state_cases=int(thresholds["minimum_state_cases"]),
        minimum_state_week_clusters=int(thresholds["minimum_state_iso_week_clusters"]),
        minimum_half_directional_cases=int(thresholds["minimum_directional_cases_per_half"]),
        maximum_q_value=float(thresholds["maximum_q_value"]),
    )
    if tuple(item["gate_id"] for item in gates["gates"]) != (EXPECTED_EVALUATION_GATE_IDS):
        raise AssertionError("Frozen holdout gate order changed")

    decisions = [
        _decision_record(
            item,
            research_hash=research_hash,
            readiness_hash=str(readiness["readiness_hash"]),
            stress_multiplier=float(research["execution"]["cost_stress_multiplier"]),
        )
        for item in materialized
    ]
    results = _build_results(
        research=research,
        research_hash=research_hash,
        readiness=readiness,
        acquisition=acquisition,
        normalization=normalization,
        open_intent=open_intent,
        zn_value_source=zn_value_source,
        materialized=materialized,
        report=report,
        gates=gates,
    )
    results["results_hash"] = canonical_hash(results)

    with tempfile.TemporaryDirectory(
        dir=output.parent,
        prefix=f".{output.name}.staging-",
    ) as temporary:
        staging = Path(temporary)
        decisions_path = staging / "decisions.jsonl.gz"
        decision_count = _write_jsonl_gzip(decisions_path, decisions)
        results_path = staging / "holdout_results.json"
        _write_json(results_path, results)
        bundle: dict[str, Any] = {
            "holdout_version": M6_HOLDOUT_VERSION,
            "schema_version": M6_HOLDOUT_SCHEMA_VERSION,
            "governing_contract": "GOLD_CASEBOOK_DISCOVERY_CONTRACT_V2.md",
            "milestone": "V2_M6_CALENDAR_2025_HOLDOUT",
            "candidate_code": CANDIDATE_CODE,
            "verdict": gates["verdict"],
            "source": {
                "research_manifest_hash": research_hash,
                "readiness_hash": readiness["readiness_hash"],
                "readiness_bundle_manifest_hash": readiness["_bundle_manifest_hash"],
                "execution_manifest_hash": execution_hash,
                "acquisition_manifest_sha256": readiness["source_seals"][
                    "zn_acquisition_manifest_sha256"
                ],
                "normalization_hash": normalization["normalization_hash"],
                "zn_payload_sha256": zn_value_source["sha256"],
                "open_intent_hash": open_intent["open_intent_hash"],
            },
            "artifacts": [
                {
                    "path": decisions_path.name,
                    "sha256": _sha256(decisions_path),
                    "bytes": decisions_path.stat().st_size,
                    "record_count": decision_count,
                    "record_type_counts": {"V2_M6_HOLDOUT_DECISION": decision_count},
                },
                {
                    "path": results_path.name,
                    "sha256": _sha256(results_path),
                    "bytes": results_path.stat().st_size,
                    "document_hash": results["results_hash"],
                },
            ],
            "integrity": {
                "all_five_readiness_gates_reverified": True,
                "holdout_open_count": 1,
                "candidate_changed": False,
                "execution_changed": False,
                "candidate_added_or_replaced": False,
                "new_york_evaluated": False,
                "calendar_2026_loaded": False,
                "parameter_search_performed": False,
                "semantic_validation_required": True,
            },
        }
        bundle["manifest_hash"] = canonical_hash(bundle)
        _write_json(staging / "manifest.json", bundle)
        staging.rename(output)

    _progress(
        "V2_M6_HOLDOUT_COMPLETE",
        output=str(output),
        bundle_manifest_hash=bundle["manifest_hash"],
        results_hash=results["results_hash"],
        verdict=gates["verdict"],
        passed_gate_count=gates["passed_gate_count"],
        failed_gate_ids=gates["failed_gate_ids"],
        total_timestamp_complete_cases=report["total_timestamp_complete_case_count"],
        directional_cases=report["directional_case_count"],
        calendar_2025_open_count=1,
        calendar_2026_loaded=False,
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Open calendar 2025 exactly once and evaluate the frozen "
            "London ZN four-hour sign candidate."
        )
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
        "--output",
        default=("research_artifacts/gold_casebook_discovery_v2_holdout_v01"),
    )
    parser.add_argument(
        "--open-intent",
        default=("research_artifacts/gold_casebook_discovery_v2_holdout_v01_open_intent.json"),
    )
    return parser


def _verify_readiness_bundle(
    root: Path,
    *,
    research_hash: str,
) -> dict[str, Any]:
    bundle = _load_json(root / "manifest.json")
    bundle_hash = _verify_hashed_document(
        bundle,
        hash_field="manifest_hash",
        label="M6 readiness bundle manifest",
    )
    artifact = _artifact(bundle, "readiness.json")
    readiness_path = root / str(artifact["path"])
    _verify_file(
        readiness_path,
        sha256=str(artifact["sha256"]),
        size=int(artifact["bytes"]),
    )
    readiness = _load_json(readiness_path)
    readiness_hash = _verify_hashed_document(
        readiness,
        hash_field="readiness_hash",
        label="M6 readiness document",
    )
    if artifact["document_hash"] != readiness_hash:
        raise ValueError("Readiness artifact document hash changed")
    if readiness["research_manifest_hash"] != research_hash:
        raise ValueError("Readiness belongs to another research manifest")
    if readiness["status"] != "READY_FOR_ONE_TIME_HOLDOUT_OPEN":
        raise ValueError("Readiness status does not authorize holdout access")
    if readiness["passed"] is not True or readiness["failed_gate_ids"]:
        raise ValueError("Not every readiness gate passed")
    if tuple(item["gate_id"] for item in readiness["gates"]) != (EXPECTED_READINESS_GATE_IDS):
        raise ValueError("Readiness gate identities changed")
    if any(item["passed"] is not True for item in readiness["gates"]):
        raise ValueError("A readiness gate is not passed")
    boundary = readiness["audit_boundary"]
    if any(
        boundary[key] is not False
        for key in (
            "xau_ohlc_values_read",
            "zn_ohlc_values_read",
            "feature_values_calculated",
            "feature_directions_calculated",
            "holdout_outcomes_calculated",
            "holdout_charts_inspected",
        )
    ):
        raise ValueError("Readiness boundary shows premature holdout access")
    if (
        readiness["next_action"]["authorized"] is not True
        or readiness["next_action"]["action"] != "OPEN_CALENDAR_2025_HOLDOUT_ONCE"
    ):
        raise ValueError("Readiness next action changed")
    readiness["_bundle_manifest_hash"] = bundle_hash
    readiness["_readiness_artifact_sha256"] = artifact["sha256"]
    return readiness


def _verify_sealed_sources(
    root: Path,
    *,
    readiness: Mapping[str, Any],
    research_hash: str,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    acquisition_path = root / "acquisition_manifest.json"
    if _sha256(acquisition_path) != readiness["source_seals"]["zn_acquisition_manifest_sha256"]:
        raise ValueError("Acquisition manifest changed after readiness")
    acquisition = _load_json(acquisition_path)
    if (
        acquisition["research_manifest_hash"] != research_hash
        or acquisition["status"] != "NORMALIZED_HASHED_AND_SEALED"
        or acquisition["job_details"]["state"] != "done"
    ):
        raise ValueError("Acquisition seal is not valid")
    normalized_dir = root / str(acquisition["job_id"]) / "normalized"
    normalization_path = normalized_dir / "normalization.json"
    if _sha256(normalization_path) != readiness["source_seals"]["zn_normalization_sha256"]:
        raise ValueError("Normalization file changed after readiness")
    normalization = _load_json(normalization_path)
    if normalization["normalization_hash"] != readiness["source_seals"]["zn_normalization_hash"]:
        raise ValueError("Normalization document changed after readiness")
    _verify_hashed_document(
        normalization,
        hash_field="normalization_hash",
        label="ZN normalization",
    )
    if (
        normalization["market_values_human_or_model_inspected"] is not False
        or normalization["features_calculated"] is not False
        or normalization["outcomes_accessed"] is not False
    ):
        raise ValueError("Sealed source indicates premature value access")
    return acquisition, normalization, normalized_dir


def _read_session_dates(readiness: Mapping[str, Any]) -> list[date]:
    dates = [date.fromisoformat(value) for value in readiness["case_population"]["session_dates"]]
    if (
        not dates
        or dates != sorted(set(dates))
        or any(value.year != 2025 or value.weekday() >= 5 for value in dates)
        or len(dates) != int(readiness["case_population"]["timestamp_complete_case_count"])
    ):
        raise ValueError("Readiness case population is invalid")
    return dates


def _write_open_intent(
    path: Path,
    *,
    research_hash: str,
    readiness: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    normalization: Mapping[str, Any],
) -> dict[str, Any]:
    intent: dict[str, Any] = {
        "open_intent_version": OPEN_INTENT_VERSION,
        "milestone": "V2_M6_CALENDAR_2025_HOLDOUT",
        "research_manifest_hash": research_hash,
        "readiness_hash": readiness["readiness_hash"],
        "readiness_bundle_manifest_hash": readiness["_bundle_manifest_hash"],
        "all_five_readiness_gates_passed": True,
        "job_id": acquisition["job_id"],
        "normalization_hash": normalization["normalization_hash"],
        "zn_payload_sha256": readiness["source_seals"]["zn_payload_sha256"],
        "authorization_consumed_at": datetime.now(UTC),
        "authorized_open_count": 1,
        "candidate_code": CANDIDATE_CODE,
        "candidate_changed": False,
        "execution_changed": False,
        "calendar_2026_access_authorized": False,
    }
    intent["open_intent_hash"] = canonical_hash(intent)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(json_ready(intent), indent=2, sort_keys=True) + "\n")
    return intent


def _required_xau_value_times(session_dates: Sequence[date]) -> set[datetime]:
    required: set[datetime] = set()
    for session_date in session_dates:
        required.add(
            datetime.combine(
                session_date,
                time(8, 1),
                tzinfo=LONDON,
            ).astimezone(UTC)
        )
        required.add(
            datetime.combine(
                session_date,
                time(11, 59),
                tzinfo=LONDON,
            ).astimezone(UTC)
        )
    return required


async def _load_xau_execution_values(
    required_times: set[datetime],
) -> dict[datetime, SealedXauExecutionBar]:
    statement = text(XAU_EXECUTION_VALUE_SQL).bindparams(
        bindparam("required_times", expanding=True)
    )
    async with session_factory() as session:
        rows = (
            (
                await session.execute(
                    statement,
                    {"required_times": sorted(required_times)},
                )
            )
            .mappings()
            .all()
        )
    bars: dict[datetime, SealedXauExecutionBar] = {}
    for row in rows:
        open_time = row["open_time"].astimezone(UTC)
        close_time = row["close_time"].astimezone(UTC)
        available_at = row["available_at"].astimezone(UTC)
        if open_time in bars:
            raise ValueError(f"Duplicate XAU value bar: {open_time}")
        if (
            open_time not in required_times
            or close_time != open_time + timedelta(minutes=1)
            or available_at > close_time
            or row["provider_code"] != "IC_MARKETS_MT5"
            or row["instrument_code"] != "XAUUSD"
            or row["timeframe"] != "1m"
            or row["is_complete"] is not True
            or row["is_synthetic"] is not False
            or row["batch_provider_code"] != "IC_MARKETS_MT5"
            or row["batch_is_synthetic"] is not False
            or row["spread_price"] is None
            or not row["source_record_key"]
            or not row["batch_content_hash"]
        ):
            raise ValueError(f"XAU execution bar failed: {open_time}")
        reference_open = float(row["reference_open"])
        reference_close = float(row["reference_close"])
        spread = float(row["spread_price"])
        if (
            not math.isfinite(reference_open)
            or not math.isfinite(reference_close)
            or not math.isfinite(spread)
            or reference_open <= 0
            or reference_close <= 0
            or spread < 0
        ):
            raise ValueError(f"XAU execution values invalid: {open_time}")
        identity = _xau_identity(
            record_id=str(row["record_id"]),
            open_time=open_time,
            close_time=close_time,
            available_at=available_at,
            reference_open=reference_open,
            reference_close=reference_close,
            spread_price=spread,
            batch_id=str(row["batch_id"]),
            source_record_key=str(row["source_record_key"]),
            batch_content_hash=str(row["batch_content_hash"]),
            dataset_code=str(row["dataset_code"]),
            raw_object_path=str(row["raw_object_path"]),
        )
        bars[open_time] = SealedXauExecutionBar(
            bar=BaselinePriceBar(
                record_id=str(row["record_id"]),
                record_hash=canonical_hash(identity),
                open_time=open_time,
                close_time=close_time,
                open=reference_open,
                close=reference_close,
                spread_price=spread,
                available_at=available_at,
            ),
            identity=identity,
        )
    missing = sorted(required_times - bars.keys())
    if missing:
        raise ValueError(
            f"Missing {len(missing)} required XAU value bars; first={missing[0].isoformat()}"
        )
    return bars


def _xau_identity(
    *,
    record_id: str,
    open_time: datetime,
    close_time: datetime,
    available_at: datetime,
    reference_open: float,
    reference_close: float,
    spread_price: float,
    batch_id: str,
    source_record_key: str,
    batch_content_hash: str,
    dataset_code: str,
    raw_object_path: str,
) -> dict[str, Any]:
    return {
        "record_type": "FROZEN_XAU_EXECUTION_BAR",
        "record_id": record_id,
        "provider_code": "IC_MARKETS_MT5",
        "instrument_code": "XAUUSD",
        "timeframe": "1m",
        "open_time": open_time,
        "close_time": close_time,
        "available_at": available_at,
        "reference_open": reference_open,
        "reference_close": reference_close,
        "spread_price": spread_price,
        "batch_id": batch_id,
        "source_record_key": source_record_key,
        "batch_content_hash": batch_content_hash,
        "dataset_code": dataset_code,
        "raw_object_path": raw_object_path,
    }


def _load_zn_value_series(
    normalized_dir: Path,
    *,
    normalization: Mapping[str, Any],
    expected_payload_sha256: str,
) -> tuple[ZnHoldoutSeries, dict[str, Any]]:
    definition = normalization["normalized_payload"]
    payload = normalized_dir / str(definition["path"])
    _verify_file(
        payload,
        sha256=expected_payload_sha256,
        size=int(definition["bytes"]),
    )
    if definition["sha256"] != expected_payload_sha256:
        raise ValueError("ZN payload hash lineage changed")
    samples: list[ZnHoldoutSample] = []
    identifiers: set[str] = set()
    with gzip.open(payload, "rt", encoding="utf-8", newline="") as handle:
        reader = csv.DictReader(handle)
        if set(reader.fieldnames or ()) != EXPECTED_ZN_VALUE_COLUMNS:
            raise ValueError("ZN value payload columns changed")
        for raw in reader:
            open_time = datetime.fromisoformat(raw["open_time"]).astimezone(UTC)
            available_at = datetime.fromisoformat(raw["available_at"]).astimezone(UTC)
            close = float(raw["close"])
            source_record_id = raw["source_record_id"]
            if (
                available_at != open_time + timedelta(minutes=1)
                or raw["continuous_symbol"] != "ZN.v.0"
                or not raw["underlying_raw_symbol"]
                or not source_record_id
                or source_record_id in identifiers
                or not math.isfinite(close)
                or close <= 0
            ):
                raise ValueError(
                    f"ZN value payload row failed at ordinal {raw['source_row_ordinal']}"
                )
            identifiers.add(source_record_id)
            samples.append(
                ZnHoldoutSample(
                    source_record_id=source_record_id,
                    source_file_sha256=raw["source_file_sha256"],
                    source_row_ordinal=int(raw["source_row_ordinal"]),
                    open_time=open_time,
                    available_at=available_at,
                    continuous_symbol=raw["continuous_symbol"],
                    instrument_id=int(raw["instrument_id"]),
                    underlying_raw_symbol=raw["underlying_raw_symbol"],
                    close=close,
                )
            )
    if len(samples) != int(normalization["total_rows"]):
        raise ValueError("ZN value payload row count changed")
    series = ZnHoldoutSeries.from_samples(samples)
    return series, {
        "path": str(payload),
        "sha256": expected_payload_sha256,
        "bytes": payload.stat().st_size,
        "rows": len(samples),
    }


def _execution_config(
    research: Mapping[str, Any],
    *,
    execution_hash: str,
) -> BaselineExecutionConfig:
    execution = research["execution"]
    return BaselineExecutionConfig(
        execution_manifest_hash=execution_hash,
        quantity_ounces=float(execution["notional_ounces"]),
        contract_size_ounces_per_lot=float(execution["contract_size_ounces_per_lot"]),
        commission_usd_per_lot_round_turn=float(execution["commission_usd_per_lot_round_turn"]),
        slippage_price_per_side=float(execution["slippage_usd_per_ounce_per_side"]),
        cost_multiplier=1.0,
        entry_latency_minutes=1,
    )


def _materialize_cases(
    session_dates: Sequence[date],
    *,
    xau_bars: Mapping[datetime, SealedXauExecutionBar],
    zn_series: ZnHoldoutSeries,
    config: BaselineExecutionConfig,
    research_hash: str,
    readiness_hash: str,
) -> list[MaterializedHoldout]:
    output: list[MaterializedHoldout] = []
    early_count = len(session_dates) // 2
    for index, session_date in enumerate(session_dates):
        decision_at = datetime.combine(
            session_date,
            time(8),
            tzinfo=LONDON,
        ).astimezone(UTC)
        observation_end = datetime.combine(
            session_date,
            time(12),
            tzinfo=LONDON,
        ).astimezone(UTC)
        entry_source = xau_bars[decision_at + timedelta(minutes=1)]
        exit_source = xau_bars[observation_end - timedelta(minutes=1)]
        entry_bar = entry_source.bar
        exit_bar = exit_source.bar
        feature = zn_series.feature_at(decision_at)
        case_id = f"M6-LONDON-{session_date:%Y%m%d}"
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
                "entry_bar_hash": entry_bar.record_hash,
                "exit_bar_hash": exit_bar.record_hash,
            }
        )
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
            entry_bar=entry_bar,
            exit_bar=exit_bar,
            config=config,
        )
        short_trade = simulate_baseline_case(
            baseline_case,
            control_code="ALWAYS_SHORT",
            entry_bar=entry_bar,
            exit_bar=exit_bar,
            config=config,
        )
        if not math.isclose(
            long_trade.gross_pnl_usd,
            -short_trade.gross_pnl_usd,
            abs_tol=1e-9,
        ) or not math.isclose(
            long_trade.total_cost_usd,
            short_trade.total_cost_usd,
            abs_tol=1e-9,
        ):
            raise AssertionError(f"Long/short execution identity failed: {case_id}")
        case = HoldoutCase(
            case_id=case_id,
            case_record_hash=case_record_hash,
            session_date=session_date,
            decision_at=decision_at,
            chronological_half="EARLY" if index < early_count else "LATE",
            feature_state=feature.state,
            raw_percent_change=feature.raw_percent_change,
            feature_source_key=feature.source_key,
            reference_entry_price=entry_bar.open,
            gross_move_usd_per_ounce=(long_trade.gross_pnl_usd / config.quantity_ounces),
            cost_usd_per_ounce=(long_trade.total_cost_usd / config.quantity_ounces),
            long_net_pnl_usd_per_ounce=(long_trade.net_pnl_usd / config.quantity_ounces),
            long_net_return_basis_points=(long_trade.net_return_basis_points),
            short_net_pnl_usd_per_ounce=(short_trade.net_pnl_usd / config.quantity_ounces),
            short_net_return_basis_points=(short_trade.net_return_basis_points),
        )
        output.append(
            MaterializedHoldout(
                case=case,
                feature=feature,
                entry_bar=entry_bar,
                exit_bar=exit_bar,
                entry_identity=entry_source.identity,
                exit_identity=exit_source.identity,
                long_trade=long_trade,
                short_trade=short_trade,
            )
        )
    if len(output) != len(session_dates):
        raise AssertionError("Holdout case count changed")
    return output


def _decision_record(
    item: MaterializedHoldout,
    *,
    research_hash: str,
    readiness_hash: str,
    stress_multiplier: float,
) -> dict[str, Any]:
    case = item.case
    selected = (
        item.long_trade
        if item.feature.bias == "LONG"
        else item.short_trade
        if item.feature.bias == "SHORT"
        else None
    )
    stressed = None
    if selected is not None:
        direction = 1 if selected.side == "LONG" else -1
        gross = direction * case.gross_move_usd_per_ounce
        stressed_pnl = gross - stress_multiplier * case.cost_usd_per_ounce
        stressed = {
            "cost_multiplier": stress_multiplier,
            "side": selected.side,
            "net_pnl_usd_per_ounce": round(stressed_pnl, 8),
            "net_return_basis_points": round(
                10_000 * stressed_pnl / case.reference_entry_price,
                8,
            ),
        }
    return finalize_record(
        {
            "record_type": "V2_M6_HOLDOUT_DECISION",
            "record_id": f"V2-M6-{case.case_id}",
            "holdout_version": M6_HOLDOUT_VERSION,
            "schema_version": M6_HOLDOUT_SCHEMA_VERSION,
            "epistemic_status": "INFERRED",
            "research_manifest_hash": research_hash,
            "readiness_hash": readiness_hash,
            "candidate_code": CANDIDATE_CODE,
            "case_id": case.case_id,
            "case_record_hash": case.case_record_hash,
            "session_code": "LONDON",
            "session_date": case.session_date,
            "decision_at": case.decision_at,
            "observation_end": item.exit_bar.close_time,
            "chronological_half": case.chronological_half,
            "feature": {
                "feature_id": FEATURE_ID,
                "state": item.feature.state,
                "reason_code": item.feature.reason_code,
                "raw_absolute_change": item.feature.raw_absolute_change,
                "raw_percent_change": item.feature.raw_percent_change,
                "source_key": item.feature.source_key,
                "current": _zn_sample_dict(item.feature.current),
                "reference": _zn_sample_dict(item.feature.reference),
            },
            "bias": item.feature.bias,
            "execution": {
                "entry_bar": _price_bar_dict(
                    item.entry_bar,
                    identity=item.entry_identity,
                ),
                "exit_bar": _price_bar_dict(
                    item.exit_bar,
                    identity=item.exit_identity,
                ),
                "always_long": trade_to_dict(item.long_trade),
                "always_short": trade_to_dict(item.short_trade),
                "selected_base_outcome": (
                    {
                        "side": selected.side,
                        "net_pnl_usd_per_ounce": round(selected.net_pnl_usd, 8),
                        "net_return_basis_points": round(
                            selected.net_return_basis_points,
                            8,
                        ),
                    }
                    if selected is not None
                    else None
                ),
                "selected_cost_stress_outcome": stressed,
            },
            "guardrails": {
                "candidate_changed": False,
                "execution_changed": False,
                "new_york_evaluated": False,
                "calendar_2026_loaded": False,
                "parameter_search_performed": False,
            },
        }
    )


def _zn_sample_dict(sample: ZnHoldoutSample | None) -> dict[str, Any] | None:
    if sample is None:
        return None
    return {
        "source_record_id": sample.source_record_id,
        "source_file_sha256": sample.source_file_sha256,
        "source_row_ordinal": sample.source_row_ordinal,
        "open_time": sample.open_time,
        "available_at": sample.available_at,
        "continuous_symbol": sample.continuous_symbol,
        "instrument_id": sample.instrument_id,
        "underlying_raw_symbol": sample.underlying_raw_symbol,
        "close": sample.close,
    }


def _price_bar_dict(
    bar: BaselinePriceBar,
    *,
    identity: Mapping[str, Any],
) -> dict[str, Any]:
    if canonical_hash(identity) != bar.record_hash:
        raise AssertionError("XAU source identity hash changed")
    return {
        "record_id": bar.record_id,
        "record_hash": bar.record_hash,
        "open_time": bar.open_time,
        "close_time": bar.close_time,
        "available_at": bar.available_at,
        "reference_open": bar.open,
        "reference_close": bar.close,
        "spread_price": bar.spread_price,
        "source_identity": dict(identity),
    }


def _build_results(
    *,
    research: Mapping[str, Any],
    research_hash: str,
    readiness: Mapping[str, Any],
    acquisition: Mapping[str, Any],
    normalization: Mapping[str, Any],
    open_intent: Mapping[str, Any],
    zn_value_source: Mapping[str, Any],
    materialized: Sequence[MaterializedHoldout],
    report: Mapping[str, Any],
    gates: Mapping[str, Any],
) -> dict[str, Any]:
    reasons = Counter(item.feature.reason_code for item in materialized)
    states = Counter(item.feature.state for item in materialized)
    return {
        "holdout_version": M6_HOLDOUT_VERSION,
        "schema_version": M6_HOLDOUT_SCHEMA_VERSION,
        "milestone": "V2_M6_CALENDAR_2025_HOLDOUT",
        "research_manifest_hash": research_hash,
        "readiness_hash": readiness["readiness_hash"],
        "candidate": research["candidate"],
        "execution": research["execution"],
        "holdout": research["holdout"],
        "source": {
            "databento_job_id": acquisition["job_id"],
            "fresh_estimated_cost_usd": acquisition["fresh_estimated_cost_usd"],
            "actual_cost_usd": acquisition["actual_cost_usd"],
            "maximum_cost_usd": acquisition["maximum_cost_usd"],
            "normalization_hash": normalization["normalization_hash"],
            "zn_payload": dict(zn_value_source),
            "open_intent_hash": open_intent["open_intent_hash"],
        },
        "population": {
            "timestamp_complete_cases": len(materialized),
            "first_session_date": materialized[0].case.session_date,
            "last_session_date": materialized[-1].case.session_date,
            "feature_state_counts": dict(sorted(states.items())),
            "feature_reason_counts": dict(sorted(reasons.items())),
        },
        "report": dict(report),
        "gate_evaluation": dict(gates),
        "verdict": gates["verdict"],
        "integrity": {
            "point_in_time_and_lineage_integrity_passed": True,
            "all_five_readiness_gates_reverified": True,
            "holdout_open_count": 1,
            "candidate_changed": False,
            "candidate_added_or_replaced": False,
            "execution_changed": False,
            "parameter_search_performed": False,
            "new_york_evaluated": False,
            "calendar_2026_loaded": False,
            "human_chart_inspection_performed": False,
            "issue_count": 0,
            "issues": [],
        },
        "interpretation": {
            "independent_calendar_2025_validation_credit": bool(gates["passed"]),
            "edge_claim_permitted": bool(gates["passed"]),
            "result_meaning": (
                "The frozen candidate passed every predeclared calendar-2025 holdout gate."
                if gates["passed"]
                else "The frozen candidate failed one or more predeclared "
                "calendar-2025 holdout gates and is rejected."
            ),
            "account_return_or_10r_claim_permitted": False,
            "next_milestone_authorized": False,
            "stop_after_milestone_6": True,
        },
    }


def _artifact(
    manifest: Mapping[str, Any],
    name: str,
) -> Mapping[str, Any]:
    matches = [item for item in manifest["artifacts"] if str(item["path"]) == name]
    if len(matches) != 1:
        raise ValueError(f"Expected one artifact named {name}")
    return matches[0]


def _verify_hashed_document(
    document: Mapping[str, Any],
    *,
    hash_field: str,
    label: str,
) -> str:
    supplied = str(document.get(hash_field, ""))
    content = {key: value for key, value in document.items() if key != hash_field}
    if not supplied or canonical_hash(content) != supplied:
        raise ValueError(f"{label} hash mismatch")
    return supplied


def _verify_file(path: Path, *, sha256: str, size: int) -> None:
    if not path.is_file() or path.stat().st_size != size or _sha256(path) != sha256:
        raise ValueError(f"File seal failed: {path}")


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    path.write_text(
        json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _write_jsonl_gzip(
    path: Path,
    records: Sequence[Mapping[str, Any]],
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
        ) as handle,
    ):
        for record in records:
            handle.write(
                json.dumps(
                    json_ready(record),
                    sort_keys=True,
                    separators=(",", ":"),
                )
            )
            handle.write("\n")
            count += 1
    return count


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _progress(stage: str, **values: Any) -> None:
    print(json.dumps({"stage": stage, **json_ready(values)}, sort_keys=True))


if __name__ == "__main__":
    asyncio.run(main())
