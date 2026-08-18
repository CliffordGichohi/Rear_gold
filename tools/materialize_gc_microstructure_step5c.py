#!/usr/bin/env python3
"""Materialize the sealed Step 5C outcome-blind decision feature matrix.

Only the frozen 2021-11-08 through 2024-12-13 MBO/MBP-10 sources and the
outcome-blind context projection are admitted. Development outcomes are never
opened or joined. The two implementations intentionally use different row
allocation and latest-state algorithms and must reproduce byte-identical
Parquet payloads before the formal Step 5C verdict can pass.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
import gzip
import hashlib
import importlib.util
import json
import math
import os
from pathlib import Path
import struct
import sys
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = REPO_ROOT / "research_manifests" / "gc_microstructure_step_5c_protocol_v01.json"
FREEZE_PATH = REPO_ROOT / "research_manifests" / "gc_microstructure_step_5c_freeze_v01.json"
ROW_REGISTRY_PATH = REPO_ROOT / "research_manifests" / "gc_microstructure_step_5c_row_registry_v01.json"
BASE_ENGINE_PATH = REPO_ROOT / "tools" / "build_gc_microstructure_features_step4a.py"
LOCAL_ACQUISITION_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_5b_budget_c_v01"
    / "acquisition_manifest.json"
)
LOCAL_STEP5B2_MANIFEST = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_5b2_v01"
    / "step5b2_final"
    / "manifest.json"
)
LOCAL_STEP5B2_VERDICT = LOCAL_STEP5B2_MANIFEST.parent / "verdict.json"
DEFAULT_REMOTE_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_OUTPUT = DEFAULT_REMOTE_ROOT / "artifacts" / "gc_microstructure_step5c_v01"
DEFAULT_CONTEXT = DEFAULT_REMOTE_ROOT / "artifacts" / "step5c_context_input"
DEFAULT_ACQUISITION = (
    DEFAULT_REMOTE_ROOT
    / "data"
    / "databento_gc_microstructure_budget_c_v01"
    / "acquisition_manifest.json"
)
DEFAULT_STEP5B2 = DEFAULT_REMOTE_ROOT / "artifacts" / "step5b2_final"

EXPECTED_PROTOCOL_SHA256 = "25e087ae505bd2b304b5d9533c9fb8dd8042b47e8e498ed82242ad48365e272d"
EXPECTED_FREEZE_SHA256 = "5ad5d57af1fdab6a80e90cb872408f1f6df99d2d7a4a892a5f380c49aee9f82d"
EXPECTED_ROW_REGISTRY_SHA256 = "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225"
EXPECTED_ACQUISITION_SHA256 = "b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc"
EXPECTED_STEP5B2_MANIFEST_SHA256 = "3fedb586ce4f9621721575b748b82043f47a4f6630488c29e0b2f8e73b4c86f1"
EXPECTED_STEP5B2_VERDICT_SHA256 = "5f3bd13cc2336a50c09ecfcc44c7d63b226a4d212f9d08666d6a50e93e09a6cb"
EXPECTED_STEP5B2_MANIFEST_HASH = "ccbf10b2e23612d3de2e2d880cfcde2a569fbb3b419de421e8887c17cf81cc4f"
EXPECTED_BASE_ENGINE_SHA256 = "c5589914a1acae6a3a1e9079c302821477866bba3741317392c567bb590c2369"
EXPECTED_FEATURE_SCHEMA_SHA256 = "dfaf74cdc55b37469966857fc1ed2279b3d18c98f90454ced65859cb32494232"
EXPECTED_CONTEXT_SUMMARY_SHA256 = "439a34133dd4f0045fb3d1ba61e8fff32f19e4c7177887131c81c077c4a07381"
EXPECTED_CONTEXT_PROJECTION_SHA256 = "6472047f31116f25f9d7bd289f5bd290175373e0efbe3fe0495047f0319700ff"
EXPECTED_ASIA_HISTORY_SHA256 = "59754d79a598b5a2b28326ae38ac270ae636ca45640283dc1989d5209f08327b"

EXPECTED_DATES = 188
EXPECTED_DECISION_ROWS = 376
EXPECTED_AVAILABLE_SESSIONS = 374
EXPECTED_BUCKET_ROWS = 336_600
EXPECTED_SESSION_BUCKET_ROWS = 168_300
EXPECTED_SOURCE_REQUESTS = 80
EXPECTED_REQUEST_PAIRS = 40
BUCKET_WIDTH_NS = 1_000_000_000
WINDOW_BUCKETS = 900
RATIO_SCALE = 1_000_000_000
UNDEFINED_PRICE = 9_223_372_036_854_775_807
F_BAD_TS_RECV = 8
F_MAYBE_BAD_BOOK = 4
F_SNAPSHOT = 32
F_TOB = 64
KNOWN_ACTIONS = frozenset({"A", "C", "M", "T", "F", "R", "N"})
INT64 = struct.Struct(">q")
UINT32 = struct.Struct(">I")

MICRO_STATES = (
    "FLOW_PRESSURE_W60",
    "FLOW_PRESSURE_W900",
    "DEPTH_PRESSURE_W60",
    "DEPTH_PRESSURE_W900",
    "LIQUIDITY_ACTIVITY_SHIFT",
    "LIQUIDITY_FRAGILITY",
    "ABSORPTION_STATE_W60",
    "FLOW_DEPTH_ALIGNMENT",
)
FUNDAMENTAL_CONTEXTS = (
    "MACRO_ENGINE_BIAS_STATE",
    "REAL_YIELD_USD_CONFIRMATION",
    "REGIME_REACTION_FUNCTION_STATE",
    "RECENT_RELEASE_SURPRISE_DIRECTION",
    "UPCOMING_CATALYST_RISK",
    "FINANCIAL_STRESS_STATE",
    "COT_MANAGED_MONEY_CROWDING",
    "COT_WEEKLY_CHANGE_SIGN",
)
LEVEL_CONTEXTS = (
    "ASIA_RANGE_LOCATION",
    "ASIA_PREDECISION_BREAK_STATE",
    "PRIOR_DAY_RANGE_LOCATION",
    "STRUCTURE_15M_1H_ALIGNMENT",
    "ASIA_RANGE_COMPRESSION",
    "LONDON_PRE_NEW_YORK_DIRECTION",
    "LONDON_ASIA_INTERACTION_PRE_NEW_YORK",
)
OBSERVATION_IDS = (*MICRO_STATES, *FUNDAMENTAL_CONTEXTS, *LEVEL_CONTEXTS)
OBSERVATION_FIELDS = ("state", "epistemic_status", "quality", "source_signature")
DECISION_ID_COLUMNS = (
    "row_id",
    "session_date",
    "session_code",
    "decision_at_utc",
    "availability_disposition",
    "expected_bucket_rows",
    "materialized_bucket_rows",
)
DECISION_COLUMNS = (
    *DECISION_ID_COLUMNS,
    *(f"{name}__{field}" for name in OBSERVATION_IDS for field in OBSERVATION_FIELDS),
)
DECISION_SCHEMA = pa.schema(
    [
        pa.field(
            name,
            pa.int64() if name in {"expected_bucket_rows", "materialized_bucket_rows"} else pa.string(),
            nullable=False,
        )
        for name in DECISION_COLUMNS
    ]
)


@dataclass(frozen=True, slots=True)
class Observation:
    state: str
    epistemic_status: str
    quality: str
    source_signature: str


@dataclass(frozen=True, slots=True)
class RuntimePaths:
    acquisition: Path
    context: Path
    step5b2: Path
    output: Path


@dataclass(frozen=True, slots=True)
class RequestPair:
    interval_id: str
    mbo: Mapping[str, Any]
    mbp10: Mapping[str, Any]
    rows: tuple[Mapping[str, Any], ...]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "primary", "reference", "seal", "verify"))
    parser.add_argument("--acquisition", default=str(DEFAULT_ACQUISITION))
    parser.add_argument("--context", default=str(DEFAULT_CONTEXT))
    parser.add_argument("--step5b2", default=str(DEFAULT_STEP5B2))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    paths = RuntimePaths(
        acquisition=Path(args.acquisition),
        context=Path(args.context),
        step5b2=Path(args.step5b2),
        output=Path(args.output),
    )
    if args.action == "preflight":
        _preflight(paths)
    elif args.action in {"primary", "reference"}:
        _materialize(args.action, paths)
    elif args.action == "seal":
        _seal(paths)
    else:
        _verify(paths)


def _load_base_engine() -> Any:
    _verify_hash(BASE_ENGINE_PATH, EXPECTED_BASE_ENGINE_SHA256)
    spec = importlib.util.spec_from_file_location("step5c_sealed_step4a_engine", BASE_ENGINE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(BASE_ENGINE_PATH)
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    if module._feature_schema_hash() != EXPECTED_FEATURE_SCHEMA_SHA256:
        raise ValueError("Frozen 85-column feature schema changed")
    if len(module.FEATURE_COLUMNS) != 85:
        raise ValueError("Frozen feature-column count changed")
    return module


def _verified_control(paths: RuntimePaths) -> tuple[Any, dict[str, Any], dict[str, Any], dict[str, Any]]:
    _verify_hash(PROTOCOL_PATH, EXPECTED_PROTOCOL_SHA256)
    _verify_hash(FREEZE_PATH, EXPECTED_FREEZE_SHA256)
    _verify_hash(ROW_REGISTRY_PATH, EXPECTED_ROW_REGISTRY_SHA256)
    _verify_hash(paths.acquisition, EXPECTED_ACQUISITION_SHA256)
    _verify_hash(paths.step5b2 / "manifest.json", EXPECTED_STEP5B2_MANIFEST_SHA256)
    _verify_hash(paths.step5b2 / "verdict.json", EXPECTED_STEP5B2_VERDICT_SHA256)
    protocol = _read_json(PROTOCOL_PATH)
    freeze = _read_json(FREEZE_PATH)
    registry = _read_json(ROW_REGISTRY_PATH)
    acquisition = _read_json(paths.acquisition)
    predecessor = _read_json(paths.step5b2 / "manifest.json")
    predecessor_verdict = _read_json(paths.step5b2 / "verdict.json")
    if freeze.get("status") != "SEALED_BEFORE_RESEARCH_MARKET_VALUE_ACCESS":
        raise ValueError("Step 5C pre-value freeze is not intact")
    if predecessor.get("manifest_hash") != EXPECTED_STEP5B2_MANIFEST_HASH:
        raise ValueError("Step 5B.2 manifest hash changed")
    if predecessor.get("status") != "PASS_STEP_5B2_SOURCE_INTEGRITY_RECERTIFICATION":
        raise ValueError("Step 5B.2 predecessor PASS is absent")
    if not predecessor_verdict.get("formal_pass"):
        raise ValueError("Step 5B.2 predecessor verdict no longer passes")
    if acquisition.get("status") != "SEALED" or len(acquisition.get("requests", [])) != EXPECTED_SOURCE_REQUESTS:
        raise ValueError("Frozen Budget C acquisition manifest changed")
    expected = registry.get("expected_counts", {})
    if (
        expected.get("dates") != EXPECTED_DATES
        or expected.get("session_rows") != EXPECTED_DECISION_ROWS
        or expected.get("available_bucket_rows") != EXPECTED_BUCKET_ROWS
        or len(registry.get("rows", [])) != EXPECTED_DECISION_ROWS
    ):
        raise ValueError("Frozen Step 5C row registry changed")
    if protocol.get("development_outcomes_accessed") or protocol.get("market_values_accessed_before_freeze"):
        raise ValueError("Step 5C protocol is not outcome/value blind at freeze")
    base = _load_base_engine()
    return base, protocol, registry, acquisition


def _context_records(paths: RuntimePaths) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    summary_path = paths.context / "summary.json"
    projection_path = paths.context / "decision_context_projection.jsonl.gz"
    asia_path = paths.context / "asia_range_history.json"
    _verify_hash(summary_path, EXPECTED_CONTEXT_SUMMARY_SHA256)
    summary = _read_json(summary_path)
    if summary.get("status") != "PASS_OUTCOME_BLIND_CONTEXT_PROJECTION" or not summary.get("formal_pass"):
        raise ValueError("Outcome-blind context projection did not pass")
    if summary.get("record_count") != EXPECTED_DECISION_ROWS:
        raise ValueError("Context projection row count changed")
    _verify_hash(projection_path, EXPECTED_CONTEXT_PROJECTION_SHA256)
    _verify_hash(asia_path, EXPECTED_ASIA_HISTORY_SHA256)
    if summary.get("development_outcomes_accessed_or_emitted"):
        raise ValueError("Outcome data entered the context projection")
    records: dict[str, dict[str, Any]] = {}
    with gzip.open(projection_path, "rt", encoding="utf-8") as handle:
        for line in handle:
            item = json.loads(line)
            if item.get("outcome_fields_present"):
                raise ValueError("Forbidden outcome field entered projection")
            row_id = str(item["row_id"])
            if row_id in records:
                raise ValueError(f"Duplicate context row: {row_id}")
            records[row_id] = item
    if len(records) != EXPECTED_DECISION_ROWS:
        raise ValueError("Context projection does not contain 376 unique rows")
    asia = _read_json(asia_path)
    if asia.get("outcomes_present"):
        raise ValueError("Outcome data entered Asia history")
    return records, asia, summary


def _request_pairs(registry: Mapping[str, Any], acquisition: Mapping[str, Any]) -> list[RequestPair]:
    requests = {str(item["request_id"]): item for item in acquisition["requests"]}
    grouped: dict[tuple[str, str], list[Mapping[str, Any]]] = defaultdict(list)
    for row in registry["rows"]:
        grouped[(str(row["mbo_request_id"]), str(row["mbp10_request_id"]))].append(row)
    pairs: list[RequestPair] = []
    for (mbo_id, mbp_id), rows in grouped.items():
        mbo = requests.get(mbo_id)
        mbp = requests.get(mbp_id)
        if mbo is None or mbp is None or mbo.get("schema") != "mbo" or mbp.get("schema") != "mbp-10":
            raise ValueError(f"Invalid frozen request pair: {mbo_id}/{mbp_id}")
        if mbo.get("interval_id") != mbp.get("interval_id"):
            raise ValueError("MBO and MBP-10 interval identities differ")
        pairs.append(
            RequestPair(
                interval_id=str(mbo["interval_id"]),
                mbo=mbo,
                mbp10=mbp,
                rows=tuple(sorted(rows, key=lambda item: (item["window_start_inclusive_ns"], item["session_code"]))),
            )
        )
    pairs.sort(key=lambda item: item.interval_id)
    if len(pairs) != EXPECTED_REQUEST_PAIRS:
        raise ValueError("Expected exactly 40 frozen request pairs")
    return pairs


def _verify_normalized_source(request: Mapping[str, Any], required_columns: Sequence[str]) -> dict[str, Any]:
    normalization = request["normalization"]
    verified: dict[str, Any] = {}
    for key in ("normalized_payload", "data_quality", "lineage", "seal"):
        record = normalization[key]
        path = Path(record["path"])
        if path.stat().st_size != int(record["bytes"]) or _sha256(path) != str(record["sha256"]):
            raise ValueError(f"Sealed source artifact changed: {path}")
        verified[key] = {"bytes": int(record["bytes"]), "sha256": str(record["sha256"])}
    payload = Path(normalization["normalized_payload"]["path"])
    parquet = pq.ParquetFile(payload)
    provider_records = int(request["job_details"]["record_count"])
    if parquet.metadata.num_rows != provider_records:
        raise ValueError(f"Provider/Parquet record count differs: {request['request_id']}")
    if not set(required_columns).issubset(parquet.schema_arrow.names):
        raise ValueError(f"Required frozen columns absent: {request['request_id']}")
    return {
        "request_id": request["request_id"],
        "schema": request["schema"],
        "provider_records": provider_records,
        "normalized": verified,
        "parquet_row_groups": parquet.metadata.num_row_groups,
    }


def _preflight(paths: RuntimePaths) -> None:
    base, protocol, registry, acquisition = _verified_control(paths)
    _, _, context_summary = _context_records(paths)
    pairs = _request_pairs(registry, acquisition)
    paths.output.mkdir(parents=True, exist_ok=True)
    target = paths.output / "preflight.json"
    if target.exists():
        raise FileExistsError("Refusing to overwrite Step 5C preflight")
    source_records: list[dict[str, Any]] = []
    for pair in pairs:
        source_records.append(_verify_normalized_source(pair.mbo, base.MBO_COLUMNS))
        source_records.append(_verify_normalized_source(pair.mbp10, base.MBP_COLUMNS))
    receipt = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_PREFLIGHT_V0_1",
        "status": "PASS_STEP_5C_PRE_MATERIALIZATION_READINESS",
        "completed_at_utc": _now(),
        "classification": "OUTCOME_BLIND_DEVELOPMENT_FEATURE_MATERIALIZATION_ONLY",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "row_registry_sha256": EXPECTED_ROW_REGISTRY_SHA256,
        "acquisition_manifest_sha256": EXPECTED_ACQUISITION_SHA256,
        "step5b2_manifest_hash": EXPECTED_STEP5B2_MANIFEST_HASH,
        "base_engine_sha256": EXPECTED_BASE_ENGINE_SHA256,
        "feature_schema_sha256": EXPECTED_FEATURE_SCHEMA_SHA256,
        "tool_sha256": _sha256(Path(__file__)),
        "source_request_count": len(source_records),
        "request_pair_count": len(pairs),
        "session_date_count": EXPECTED_DATES,
        "decision_row_count": EXPECTED_DECISION_ROWS,
        "expected_available_bucket_rows": EXPECTED_BUCKET_ROWS,
        "source_records": source_records,
        "context_projection": {
            "status": context_summary["status"],
            "projection_sha256": EXPECTED_CONTEXT_PROJECTION_SHA256,
            "asia_history_sha256": EXPECTED_ASIA_HISTORY_SHA256,
            "record_count": context_summary["record_count"],
        },
        "formal_gates": {
            "sealed_protocol_and_freeze_verified": True,
            "step5b2_pass_and_source_inventory_verified": True,
            "all_80_normalized_payload_quality_lineage_and_seals_verified": len(source_records) == 80,
            "all_required_source_columns_present": True,
            "exact_40_request_pairs_and_376_rows_bound": len(pairs) == 40,
            "outcome_blind_context_projection_verified": True,
            "development_outcomes_accessed": False,
            "year_2025_or_2026_values_accessed": False,
        },
        "market_or_feature_values_reported": False,
        "development_outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    _write_json(target, receipt)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5C_PREFLIGHT_COMPLETE",
        "status": receipt["status"],
        "sources_verified": len(source_records),
        "request_pairs": len(pairs),
        "decision_rows": EXPECTED_DECISION_ROWS,
        "market_values_reported": False,
        "outcomes_accessed": False,
        "charge_incurred_usd": 0.0,
    }, sort_keys=True))


class _FeatureWriters:
    def __init__(self, output: Path, implementation: str, schema: pa.Schema) -> None:
        self.final = {
            "LONDON": output / f"{implementation}_london_buckets.parquet",
            "NEW_YORK": output / f"{implementation}_new_york_buckets.parquet",
        }
        self.temporary = {key: value.with_suffix(value.suffix + ".tmp") for key, value in self.final.items()}
        for path in (*self.final.values(), *self.temporary.values()):
            if path.exists():
                raise FileExistsError(f"Refusing to overwrite Step 5C feature output: {path}")
        self.writers = {
            key: pq.ParquetWriter(
                self.temporary[key],
                schema,
                compression="zstd",
                use_dictionary=False,
                write_statistics=True,
                data_page_version="1.0",
                version="2.6",
            )
            for key in self.final
        }
        self.closed = False

    def write(self, session: str, columns: Mapping[str, Sequence[Any]], schema: pa.Schema) -> None:
        table = pa.Table.from_pydict(dict(columns), schema=schema)
        if table.num_rows != WINDOW_BUCKETS:
            raise ValueError("Every available session must emit exactly 900 buckets")
        self.writers[session].write_table(table, row_group_size=WINDOW_BUCKETS)

    def close(self) -> None:
        if self.closed:
            return
        for writer in self.writers.values():
            writer.close()
        for key in self.final:
            os.replace(self.temporary[key], self.final[key])
        self.closed = True


def _materialize(implementation: str, paths: RuntimePaths) -> None:
    base, _protocol, registry, acquisition = _verified_control(paths)
    preflight_path = paths.output / "preflight.json"
    preflight = _read_json(preflight_path)
    if (
        preflight.get("status") != "PASS_STEP_5C_PRE_MATERIALIZATION_READINESS"
        or preflight.get("tool_sha256") != _sha256(Path(__file__))
        or preflight.get("source_request_count") != EXPECTED_SOURCE_REQUESTS
    ):
        raise ValueError("A matching passed Step 5C preflight is required")
    contexts, asia_history, context_summary = _context_records(paths)
    pairs = _request_pairs(registry, acquisition)
    paths.output.mkdir(parents=True, exist_ok=True)
    summary_path = paths.output / f"{implementation}_summary.json"
    decision_path = paths.output / f"{implementation}_decision_features.parquet"
    if summary_path.exists() or decision_path.exists():
        raise FileExistsError(f"Refusing to overwrite Step 5C {implementation} run")

    writers = _FeatureWriters(paths.output, implementation, base.FEATURE_SCHEMA)
    decision_by_id: dict[str, dict[str, Any]] = {}
    aggregate = Counter()
    request_diagnostics: list[dict[str, Any]] = []
    try:
        for pair_index, pair in enumerate(pairs, start=1):
            pair_result = _process_request_pair(implementation, pair, base)
            request_diagnostics.append(pair_result["diagnostics"])
            aggregate.update(pair_result["counter"])
            for row, columns, technical in pair_result["sessions"]:
                writers.write(str(row["session_code"]), columns, base.FEATURE_SCHEMA)
                context = contexts[str(row["row_id"])]
                if implementation == "primary":
                    observations = _primary_decision_observations(row, columns, context, asia_history, base)
                else:
                    observations = _reference_decision_observations(row, columns, context, asia_history, base)
                decision_by_id[str(row["row_id"])] = _decision_record(row, observations, WINDOW_BUCKETS)
                aggregate.update(technical)
            print(json.dumps({
                "stage": "GC_MICROSTRUCTURE_STEP_5C_PAIR_COMPLETE",
                "implementation": implementation,
                "pair": pair_index,
                "pairs": len(pairs),
                "interval_id": pair.interval_id,
                "available_sessions": len(pair_result["sessions"]),
                "market_values_reported": False,
                "outcomes_accessed": False,
            }, sort_keys=True), flush=True)
        writers.close()
    except Exception:
        for writer in writers.writers.values():
            try:
                writer.close()
            except Exception:
                pass
        raise

    for row in registry["rows"]:
        row_id = str(row["row_id"])
        if row_id in decision_by_id:
            continue
        if row.get("availability_disposition") != "UNAVAILABLE_DOCUMENTED" or int(row["expected_bucket_rows"]) != 0:
            raise ValueError(f"Unexpected absent session materialization: {row_id}")
        context = contexts[row_id]
        unknown_micro = {name: _unknown() for name in MICRO_STATES}
        if implementation == "primary":
            context_observations = _primary_context_observations(row, context, asia_history)
        else:
            context_observations = _reference_context_observations(row, context, asia_history)
        decision_by_id[row_id] = _decision_record(row, {**unknown_micro, **context_observations}, 0)
        aggregate["documented_unavailable_sessions"] += 1

    ordered_decisions = [decision_by_id[str(row["row_id"])] for row in registry["rows"]]
    if len(ordered_decisions) != EXPECTED_DECISION_ROWS:
        raise ValueError("Step 5C did not emit exactly 376 decision rows")
    _write_parquet_atomic(decision_path, pa.Table.from_pylist(ordered_decisions, schema=DECISION_SCHEMA), EXPECTED_DECISION_ROWS)

    bucket_files = {
        session: _file_record(writers.final[session]) for session in ("LONDON", "NEW_YORK")
    }
    for record in bucket_files.values():
        if pq.ParquetFile(record["path"]).metadata.num_rows != EXPECTED_SESSION_BUCKET_ROWS:
            raise ValueError("Session bucket row count differs from frozen 168,300")
    bucket_hashes = {
        session: _parquet_hashes(Path(record["path"]), base.FEATURE_SCHEMA, EXPECTED_SESSION_BUCKET_ROWS, EXPECTED_FEATURE_SCHEMA_SHA256)
        for session, record in bucket_files.items()
    }
    decision_schema_hash = _schema_hash(DECISION_SCHEMA)
    decision_hashes = _parquet_hashes(decision_path, DECISION_SCHEMA, EXPECTED_DECISION_ROWS, decision_schema_hash)
    diagnostics = _complete_run_diagnostics(aggregate, request_diagnostics, bucket_hashes, decision_hashes)
    integrity = _run_integrity(diagnostics, bucket_files, decision_path, registry, base)
    summary = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_RUN_V0_1",
        "implementation": implementation,
        "status": "PASS_IMPLEMENTATION" if all(integrity.values()) else "FAIL_FEATURE_INTEGRITY",
        "completed_at_utc": _now(),
        "classification": "OUTCOME_BLIND_DEVELOPMENT_FEATURE_MATERIALIZATION_ONLY",
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "row_registry_sha256": EXPECTED_ROW_REGISTRY_SHA256,
        "preflight_sha256": _sha256(preflight_path),
        "tool_sha256": _sha256(Path(__file__)),
        "base_engine_sha256": EXPECTED_BASE_ENGINE_SHA256,
        "feature_schema_sha256": EXPECTED_FEATURE_SCHEMA_SHA256,
        "context_projection_sha256": EXPECTED_CONTEXT_PROJECTION_SHA256,
        "asia_history_sha256": EXPECTED_ASIA_HISTORY_SHA256,
        "context_projection_status": context_summary["status"],
        "bucket_files": bucket_files,
        "bucket_hashes": bucket_hashes,
        "decision_file": _file_record(decision_path),
        "decision_schema_hash": decision_schema_hash,
        "decision_hashes": decision_hashes,
        "diagnostics": diagnostics,
        "request_diagnostics": request_diagnostics,
        "integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        "source_rows_filtered_deduplicated_repaired_relabeled_or_substituted": 0,
        "mbo_mbp_row_alignment_attempts": 0,
        "development_outcomes_opened_or_joined": False,
        "year_2025_or_2026_values_accessed": False,
        "relationships_candidates_or_signals_calculated": False,
        "execution_trades_pnl_r_or_returns_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "market_or_feature_values_reported": False,
    }
    _write_json(summary_path, summary)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5C_IMPLEMENTATION_COMPLETE",
        "implementation": implementation,
        "status": summary["status"],
        "decision_rows": EXPECTED_DECISION_ROWS,
        "bucket_rows": EXPECTED_BUCKET_ROWS,
        "source_requests": EXPECTED_SOURCE_REQUESTS,
        "integrity_pass": summary["formal_integrity_pass"],
        "market_or_feature_values_reported": False,
        "outcomes_accessed": False,
    }, sort_keys=True))


def _process_request_pair(implementation: str, pair: RequestPair, base: Any) -> dict[str, Any]:
    available = [row for row in pair.rows if int(row["expected_bucket_rows"]) == WINDOW_BUCKETS]
    unavailable = [row for row in pair.rows if int(row["expected_bucket_rows"]) == 0]
    ranges = [(int(row["window_start_inclusive_ns"]), int(row["window_end_exclusive_ns"])) for row in available]
    _assert_nonoverlapping(ranges)
    mbo_path = Path(pair.mbo["normalization"]["normalized_payload"]["path"])
    mbp_path = Path(pair.mbp10["normalization"]["normalized_payload"]["path"])
    mbo_table = _read_exact_ranges(mbo_path, base.MBO_COLUMNS, ranges)
    mbp_table = _read_exact_ranges(mbp_path, base.MBP_COLUMNS, ranges)
    mbo_arrays = _table_arrays(mbo_table, base.MBO_COLUMNS)
    mbp_arrays = _table_arrays(mbp_table, base.MBP_COLUMNS)
    _assert_source_order(mbo_arrays, "MBO", pair.interval_id)
    _assert_source_order(mbp_arrays, "MBP-10", pair.interval_id)

    counter = Counter()
    counter["source_requests"] = 2
    counter["request_pairs"] = 1
    counter["source_mbo_records_total"] = int(pq.ParquetFile(mbo_path).metadata.num_rows)
    counter["source_mbp10_records_total"] = int(pq.ParquetFile(mbp_path).metadata.num_rows)
    counter["selected_mbo_rows"] = mbo_table.num_rows
    counter["selected_mbp10_rows"] = mbp_table.num_rows
    counter["unavailable_documented_registry_rows"] = len(unavailable)
    sessions: list[tuple[Mapping[str, Any], dict[str, list[Any]], Counter[str]]] = []
    anchors: dict[str, pa.Table] = {}
    for row in available:
        anchors[str(row["row_id"])] = _read_exact_anchor(
            mbp_path,
            base.MBP_COLUMNS,
            int(row["window_start_inclusive_ns"]),
            int(row["utc_day_start_ns"]),
        )
    for row in available:
        start = int(row["window_start_inclusive_ns"])
        end = int(row["window_end_exclusive_ns"])
        mbo_slice = _slice_arrays(mbo_arrays, start, end)
        mbp_slice = _slice_arrays(mbp_arrays, start, end)
        if implementation == "primary":
            columns, technical = _primary_window_features(row, mbo_slice, mbp_slice, anchors[str(row["row_id"])], base)
        else:
            columns, technical = _reference_window_features(row, mbo_slice, mbp_slice, anchors[str(row["row_id"])], base)
        sessions.append((row, columns, technical))
    selected_mbo_from_sessions = sum(item[2]["mbo_selected_rows"] for item in sessions)
    selected_mbp_from_sessions = sum(item[2]["mbp10_selected_rows"] for item in sessions)
    if selected_mbo_from_sessions != mbo_table.num_rows or selected_mbp_from_sessions != mbp_table.num_rows:
        raise ValueError("Selected source row allocation is not exact")
    counter["anchor_only_rows"] = len(anchors)
    diagnostics = {
        "interval_id": pair.interval_id,
        "mbo_request_id": pair.mbo["request_id"],
        "mbp10_request_id": pair.mbp10["request_id"],
        "registry_rows": len(pair.rows),
        "available_sessions": len(available),
        "unavailable_documented_sessions": len(unavailable),
        "selected_mbo_rows": mbo_table.num_rows,
        "selected_mbp10_rows": mbp_table.num_rows,
        "anchor_only_rows": len(anchors),
        "mbo_total_source_rows": counter["source_mbo_records_total"],
        "mbp10_total_source_rows": counter["source_mbp10_records_total"],
        "mbo_outside_feature_windows": counter["source_mbo_records_total"] - mbo_table.num_rows,
        "mbp10_outside_feature_windows": counter["source_mbp10_records_total"] - mbp_table.num_rows,
        "every_selected_row_allocated_once": True,
        "market_values_reported": False,
    }
    return {"sessions": sessions, "counter": counter, "diagnostics": diagnostics}


def _timestamp_scalar(value_ns: int) -> pa.Scalar:
    return pa.scalar(value_ns, type=pa.timestamp("ns", tz="UTC"))


def _range_expression(ranges: Sequence[tuple[int, int]]) -> Any:
    expression: Any | None = None
    field = ds.field("ts_recv")
    for start, end in ranges:
        current = (field >= _timestamp_scalar(start)) & (field < _timestamp_scalar(end))
        expression = current if expression is None else expression | current
    return expression


def _read_exact_ranges(path: Path, columns: Sequence[str], ranges: Sequence[tuple[int, int]]) -> pa.Table:
    if not ranges:
        return pa.Table.from_arrays([pa.array([], type=pq.ParquetFile(path).schema_arrow.field(name).type) for name in columns], names=list(columns))
    dataset = ds.dataset(path, format="parquet")
    return dataset.to_table(columns=list(columns), filter=_range_expression(ranges), use_threads=True)


def _read_exact_anchor(path: Path, columns: Sequence[str], start_ns: int, day_start_ns: int) -> pa.Table:
    dataset = ds.dataset(path, format="parquet")
    field = ds.field("ts_recv")
    span = BUCKET_WIDTH_NS
    metadata: pa.Table | None = None
    while start_ns - span >= day_start_ns - BUCKET_WIDTH_NS:
        lower = max(day_start_ns, start_ns - span)
        metadata = dataset.to_table(
            columns=["source_row_ordinal", "ts_recv"],
            filter=(field >= _timestamp_scalar(lower)) & (field < _timestamp_scalar(start_ns)),
            use_threads=True,
        )
        if metadata.num_rows:
            break
        if lower == day_start_ns:
            break
        span *= 2
    if metadata is None or metadata.num_rows == 0:
        raise ValueError(f"No prior MBP-10 anchor before {start_ns} in {path}")
    receives = metadata["ts_recv"].combine_chunks().cast(pa.int64()).to_numpy(zero_copy_only=False)
    ordinals = metadata["source_row_ordinal"].combine_chunks().to_numpy(zero_copy_only=False)
    order = np.lexsort((ordinals, receives))
    index = int(order[-1])
    receive = int(receives[index])
    ordinal = int(ordinals[index])
    exact = dataset.to_table(
        columns=list(columns),
        filter=(field == _timestamp_scalar(receive)) & (ds.field("source_row_ordinal") == ordinal),
        use_threads=True,
    )
    if exact.num_rows != 1:
        raise ValueError("MBP-10 anchor metadata did not identify exactly one source row")
    return exact


def _table_arrays(table: pa.Table, columns: Sequence[str]) -> dict[str, np.ndarray[Any, Any]]:
    output: dict[str, np.ndarray[Any, Any]] = {}
    for name in columns:
        column = table[name].combine_chunks()
        if pa.types.is_timestamp(column.type):
            output[name] = column.cast(pa.int64()).to_numpy(zero_copy_only=False)
        elif pa.types.is_string(column.type):
            output[name] = np.asarray(column.to_pylist(), dtype=object)
        else:
            output[name] = column.to_numpy(zero_copy_only=False)
    return output


def _slice_arrays(arrays: Mapping[str, np.ndarray[Any, Any]], start: int, end: int) -> dict[str, np.ndarray[Any, Any]]:
    receives = arrays["ts_recv"]
    mask = (receives >= start) & (receives < end)
    return {name: values[mask] for name, values in arrays.items()}


def _assert_nonoverlapping(ranges: Sequence[tuple[int, int]]) -> None:
    ordered = sorted(ranges)
    if any(start >= end for start, end in ordered):
        raise ValueError("Invalid frozen feature window")
    if any(current[0] < previous[1] for previous, current in zip(ordered, ordered[1:])):
        raise ValueError("Frozen feature windows overlap")


def _assert_source_order(arrays: Mapping[str, np.ndarray[Any, Any]], schema: str, interval: str) -> None:
    if not len(arrays["ts_recv"]):
        return
    receives = arrays["ts_recv"].astype(np.int64, copy=False)
    ordinals = arrays["source_row_ordinal"].astype(np.int64, copy=False)
    if np.any(receives[1:] < receives[:-1]):
        raise ValueError(f"{schema} receive timestamps regress in {interval}")
    same = receives[1:] == receives[:-1]
    if np.any(same & (ordinals[1:] <= ordinals[:-1])):
        raise ValueError(f"{schema} source order is not strict within timestamp in {interval}")


def _primary_window_features(
    row: Mapping[str, Any],
    mbo: Mapping[str, np.ndarray[Any, Any]],
    mbp: Mapping[str, np.ndarray[Any, Any]],
    anchor: pa.Table,
    base: Any,
) -> tuple[dict[str, list[Any]], Counter[str]]:
    start = int(row["window_start_inclusive_ns"])
    end = int(row["window_end_exclusive_ns"])
    events, mbo_audit = _primary_mbo_allocate(mbo, start, end, int(row["expected_instrument_id"]), base)
    mbp_counts, states, mbp_audit = _primary_mbp_allocate(
        mbp, anchor, start, end, int(row["expected_instrument_id"]), base
    )
    columns = _materialize_window(row, events, mbp_counts, states, base, "primary")
    technical = Counter()
    technical.update(mbo_audit)
    technical.update(mbp_audit)
    technical["available_sessions"] = 1
    technical["bucket_rows"] = WINDOW_BUCKETS
    technical["london_bucket_rows" if row["session_code"] == "LONDON" else "new_york_bucket_rows"] = WINDOW_BUCKETS
    technical["continuous_crossed_bucket_closes"] = sum(bool(value) for value in columns["book_crossed"])
    technical["state_available_bucket_closes"] = sum(bool(value) for value in columns["state_available"])
    technical["selected_bad_ts_recv_rows"] = sum(columns["mbo_bad_ts_recv_flag_count"]) + sum(columns["mbp_bad_ts_recv_flag_count"])
    return columns, technical


def _reference_window_features(
    row: Mapping[str, Any],
    mbo: Mapping[str, np.ndarray[Any, Any]],
    mbp: Mapping[str, np.ndarray[Any, Any]],
    anchor: pa.Table,
    base: Any,
) -> tuple[dict[str, list[Any]], Counter[str]]:
    start = int(row["window_start_inclusive_ns"])
    end = int(row["window_end_exclusive_ns"])
    events, mbo_audit = _reference_mbo_allocate(mbo, start, end, int(row["expected_instrument_id"]), base)
    mbp_counts, states, mbp_audit = _reference_mbp_allocate(
        mbp, anchor, start, end, int(row["expected_instrument_id"]), base
    )
    columns = _materialize_window(row, events, mbp_counts, states, base, "reference")
    technical = Counter()
    technical.update(mbo_audit)
    technical.update(mbp_audit)
    technical["available_sessions"] = 1
    technical["bucket_rows"] = WINDOW_BUCKETS
    technical["london_bucket_rows" if row["session_code"] == "LONDON" else "new_york_bucket_rows"] = WINDOW_BUCKETS
    technical["continuous_crossed_bucket_closes"] = int(np.count_nonzero(np.asarray(columns["book_crossed"], dtype=bool)))
    technical["state_available_bucket_closes"] = int(np.count_nonzero(np.asarray(columns["state_available"], dtype=bool)))
    technical["selected_bad_ts_recv_rows"] = int(np.sum(columns["mbo_bad_ts_recv_flag_count"])) + int(np.sum(columns["mbp_bad_ts_recv_flag_count"]))
    return columns, technical


def _empty_event_arrays(base: Any) -> dict[str, np.ndarray[Any, Any]]:
    return {
        name: np.zeros(WINDOW_BUCKETS, dtype=np.int64)
        for name in (*base.MBO_COUNT_COLUMNS, *base.MBO_SIDE_FLOW_COLUMNS)
    }


def _primary_accumulate(
    target: np.ndarray[Any, Any],
    buckets: np.ndarray[Any, Any],
    mask: np.ndarray[Any, Any],
    weights: np.ndarray[Any, Any] | None = None,
) -> None:
    selected = buckets[mask]
    if not len(selected):
        return
    if weights is None:
        values = np.bincount(selected, minlength=WINDOW_BUCKETS)
    else:
        values = np.bincount(selected, weights=weights[mask], minlength=WINDOW_BUCKETS)
    target[:] += values.astype(np.int64)


def _reference_accumulate(
    target: np.ndarray[Any, Any],
    buckets: np.ndarray[Any, Any],
    mask: np.ndarray[Any, Any],
    weights: np.ndarray[Any, Any] | None = None,
) -> None:
    selected = buckets[mask]
    if not len(selected):
        return
    additions = np.ones(len(selected), dtype=np.int64) if weights is None else weights[mask].astype(np.int64, copy=False)
    np.add.at(target, selected, additions)


def _primary_mbo_allocate(
    arrays: Mapping[str, np.ndarray[Any, Any]],
    start: int,
    end: int,
    instrument_id: int,
    base: Any,
) -> tuple[dict[str, np.ndarray[Any, Any]], Counter[str]]:
    output = _empty_event_arrays(base)
    audit = Counter()
    receives = arrays["ts_recv"].astype(np.int64, copy=False)
    ordinals = arrays["source_row_ordinal"].astype(np.int64, copy=False)
    buckets = ((receives - start) // BUCKET_WIDTH_NS).astype(np.int64)
    if np.any((receives < start) | (receives >= end) | (buckets < 0) | (buckets >= WINDOW_BUCKETS)):
        raise ValueError("MBO source row entered the wrong frozen window")
    actions = arrays["action"].astype(object, copy=False)
    sides = arrays["side"].astype(object, copy=False)
    flags = arrays["flags"].astype(np.int64, copy=False)
    sizes = arrays["size"].astype(np.int64, copy=False)
    prices = arrays["price_fixed_1e9"].astype(np.int64, copy=False)
    count = len(receives)
    all_rows = np.ones(count, dtype=bool)
    snapshot = (flags & F_SNAPSHOT) != 0
    live = ~snapshot
    known = np.isin(actions, tuple(KNOWN_ACTIONS))
    audit["mbo_selected_rows"] = count
    audit["mbo_timestamp_or_ordinal_regressions"] = _order_regressions(receives, ordinals)
    audit["mbo_publisher_mismatches"] = int(np.count_nonzero(arrays["publisher_id"] != 1))
    audit["mbo_instrument_mismatches"] = int(np.count_nonzero(arrays["instrument_id"] != instrument_id))
    _primary_accumulate(output["mbo_total_records"], buckets, all_rows)
    _primary_accumulate(output["mbo_snapshot_records"], buckets, snapshot)
    _primary_accumulate(output["mbo_live_records"], buckets, live)
    _primary_accumulate(output["mbo_bad_ts_recv_flag_count"], buckets, (flags & F_BAD_TS_RECV) != 0)
    _primary_accumulate(output["mbo_maybe_bad_book_flag_count"], buckets, (flags & F_MAYBE_BAD_BOOK) != 0)
    _primary_accumulate(output["mbo_unknown_action_count"], buckets, live & ~known)
    quantity_action = np.isin(actions, ("A", "C", "M", "T", "F"))
    _primary_accumulate(output["mbo_nonpositive_size_count"], buckets, live & known & quantity_action & (sizes <= 0))
    _primary_accumulate(output["mbo_undefined_price_count"], buckets, live & np.isin(actions, ("A", "C", "M")) & (prices == UNDEFINED_PRICE))
    _primary_accumulate(output["mbo_reset_count"], buckets, live & (actions == "R"))
    _primary_accumulate(output["mbo_none_count"], buckets, live & (actions == "N"))
    invalid_resting = live & np.isin(actions, ("A", "C", "M")) & ~np.isin(sides, ("A", "B"))
    invalid_trade = live & np.isin(actions, ("T", "F")) & ~np.isin(sides, ("A", "B", "N"))
    invalid = invalid_resting | invalid_trade
    _primary_accumulate(output["mbo_invalid_side_count"], buckets, invalid)
    valid_base = live & known & ~invalid
    top_add = valid_base & (actions == "A") & ((flags & F_TOB) != 0)
    _primary_accumulate(output["mbo_top_of_book_add_count"], buckets, top_add)
    for side, suffix in (("B", "bid"), ("A", "ask")):
        add = valid_base & (actions == "A") & ((flags & F_TOB) == 0) & (sides == side) & (sizes > 0) & (prices != UNDEFINED_PRICE)
        cancel = valid_base & (actions == "C") & (sides == side) & (sizes > 0)
        modify = valid_base & (actions == "M") & (sides == side) & (sizes > 0) & (prices != UNDEFINED_PRICE)
        _primary_accumulate(output[f"add_count_{suffix}"], buckets, add)
        _primary_accumulate(output[f"add_qty_{suffix}"], buckets, add, sizes)
        _primary_accumulate(output[f"cancel_count_{suffix}"], buckets, cancel)
        _primary_accumulate(output[f"cancel_qty_{suffix}"], buckets, cancel, sizes)
        _primary_accumulate(output[f"modify_count_{suffix}"], buckets, modify)
        _primary_accumulate(output[f"modify_new_size_qty_{suffix}"], buckets, modify, sizes)
    for side, suffix in (("B", "buy"), ("A", "sell"), ("N", "unknown")):
        trade = valid_base & (actions == "T") & (sides == side) & (sizes > 0)
        _primary_accumulate(output[f"trade_count_{suffix}"], buckets, trade)
        _primary_accumulate(output[f"trade_qty_{suffix}"], buckets, trade, sizes)
    for side, suffix in (("B", "bid"), ("A", "ask"), ("N", "unknown")):
        fill = valid_base & (actions == "F") & (sides == side) & (sizes > 0)
        _primary_accumulate(output[f"fill_count_{suffix}"], buckets, fill)
        _primary_accumulate(output[f"fill_qty_{suffix}"], buckets, fill, sizes)
    audit["mbo_unknown_action_rows"] = int(np.count_nonzero(live & ~known))
    audit["mbo_maybe_bad_book_rows"] = int(np.count_nonzero((flags & F_MAYBE_BAD_BOOK) != 0))
    audit["mbo_rows_allocated"] = int(np.sum(output["mbo_total_records"]))
    return output, audit


def _reference_mbo_allocate(
    arrays: Mapping[str, np.ndarray[Any, Any]],
    start: int,
    end: int,
    instrument_id: int,
    base: Any,
) -> tuple[dict[str, np.ndarray[Any, Any]], Counter[str]]:
    output = _empty_event_arrays(base)
    audit = Counter()
    receives = np.asarray(arrays["ts_recv"], dtype=np.int64)
    ordinals = np.asarray(arrays["source_row_ordinal"], dtype=np.int64)
    buckets = np.floor_divide(receives - start, BUCKET_WIDTH_NS).astype(np.int64)
    if np.any(np.logical_or.reduce((receives < start, receives >= end, buckets < 0, buckets >= WINDOW_BUCKETS))):
        raise ValueError("Reference MBO allocation escaped its frozen window")
    actions = np.asarray(arrays["action"], dtype=object)
    sides = np.asarray(arrays["side"], dtype=object)
    flags = np.asarray(arrays["flags"], dtype=np.int64)
    sizes = np.asarray(arrays["size"], dtype=np.int64)
    prices = np.asarray(arrays["price_fixed_1e9"], dtype=np.int64)
    every = np.full(receives.shape, True, dtype=bool)
    snapshots = np.not_equal(np.bitwise_and(flags, F_SNAPSHOT), 0)
    live = np.logical_not(snapshots)
    known = np.isin(actions, list(KNOWN_ACTIONS))
    audit.update({
        "mbo_selected_rows": len(receives),
        "mbo_timestamp_or_ordinal_regressions": _order_regressions(receives, ordinals),
        "mbo_publisher_mismatches": int(np.not_equal(arrays["publisher_id"], 1).sum()),
        "mbo_instrument_mismatches": int(np.not_equal(arrays["instrument_id"], instrument_id).sum()),
    })
    _reference_accumulate(output["mbo_total_records"], buckets, every)
    _reference_accumulate(output["mbo_snapshot_records"], buckets, snapshots)
    _reference_accumulate(output["mbo_live_records"], buckets, live)
    _reference_accumulate(output["mbo_bad_ts_recv_flag_count"], buckets, np.bitwise_and(flags, F_BAD_TS_RECV) != 0)
    _reference_accumulate(output["mbo_maybe_bad_book_flag_count"], buckets, np.bitwise_and(flags, F_MAYBE_BAD_BOOK) != 0)
    _reference_accumulate(output["mbo_unknown_action_count"], buckets, np.logical_and(live, np.logical_not(known)))
    quantity = np.isin(actions, ["A", "C", "M", "T", "F"])
    _reference_accumulate(output["mbo_nonpositive_size_count"], buckets, live & known & quantity & (sizes <= 0))
    _reference_accumulate(output["mbo_undefined_price_count"], buckets, live & np.isin(actions, ["A", "C", "M"]) & (prices == UNDEFINED_PRICE))
    _reference_accumulate(output["mbo_reset_count"], buckets, live & (actions == "R"))
    _reference_accumulate(output["mbo_none_count"], buckets, live & (actions == "N"))
    bad_resting_side = live & np.isin(actions, ["A", "C", "M"]) & ~np.isin(sides, ["A", "B"])
    bad_flow_side = live & np.isin(actions, ["T", "F"]) & ~np.isin(sides, ["A", "B", "N"])
    invalid = bad_resting_side | bad_flow_side
    _reference_accumulate(output["mbo_invalid_side_count"], buckets, invalid)
    valid = live & known & ~invalid
    tob = valid & (actions == "A") & (np.bitwise_and(flags, F_TOB) != 0)
    _reference_accumulate(output["mbo_top_of_book_add_count"], buckets, tob)
    for side, suffix in (("B", "bid"), ("A", "ask")):
        masks = {
            "add": valid & (actions == "A") & (np.bitwise_and(flags, F_TOB) == 0) & (sides == side) & (sizes > 0) & (prices != UNDEFINED_PRICE),
            "cancel": valid & (actions == "C") & (sides == side) & (sizes > 0),
            "modify": valid & (actions == "M") & (sides == side) & (sizes > 0) & (prices != UNDEFINED_PRICE),
        }
        _reference_accumulate(output[f"add_count_{suffix}"], buckets, masks["add"])
        _reference_accumulate(output[f"add_qty_{suffix}"], buckets, masks["add"], sizes)
        _reference_accumulate(output[f"cancel_count_{suffix}"], buckets, masks["cancel"])
        _reference_accumulate(output[f"cancel_qty_{suffix}"], buckets, masks["cancel"], sizes)
        _reference_accumulate(output[f"modify_count_{suffix}"], buckets, masks["modify"])
        _reference_accumulate(output[f"modify_new_size_qty_{suffix}"], buckets, masks["modify"], sizes)
    for side, suffix in (("B", "buy"), ("A", "sell"), ("N", "unknown")):
        mask = valid & (actions == "T") & (sides == side) & (sizes > 0)
        _reference_accumulate(output[f"trade_count_{suffix}"], buckets, mask)
        _reference_accumulate(output[f"trade_qty_{suffix}"], buckets, mask, sizes)
    for side, suffix in (("B", "bid"), ("A", "ask"), ("N", "unknown")):
        mask = valid & (actions == "F") & (sides == side) & (sizes > 0)
        _reference_accumulate(output[f"fill_count_{suffix}"], buckets, mask)
        _reference_accumulate(output[f"fill_qty_{suffix}"], buckets, mask, sizes)
    audit["mbo_unknown_action_rows"] = int(np.logical_and(live, np.logical_not(known)).sum())
    audit["mbo_maybe_bad_book_rows"] = int((np.bitwise_and(flags, F_MAYBE_BAD_BOOK) != 0).sum())
    audit["mbo_rows_allocated"] = int(output["mbo_total_records"].sum())
    return output, audit


def _anchor_arrays(anchor: pa.Table, columns: Sequence[str]) -> dict[str, np.ndarray[Any, Any]]:
    if anchor.num_rows != 1:
        raise ValueError("Every available session requires exactly one MBP-10 anchor")
    return _table_arrays(anchor, columns)


def _book_validity_counts(book: Mapping[str, np.ndarray[Any, Any]], base: Any) -> tuple[int, int]:
    canonical = 0
    negative = 0
    for level in range(10):
        for side in ("bid", "ask"):
            prices = book[f"{side}_px_{level:02d}"].astype(np.int64, copy=False)
            sizes = book[f"{side}_sz_{level:02d}"].astype(np.int64, copy=False)
            counts = book[f"{side}_ct_{level:02d}"].astype(np.int64, copy=False)
            empty = prices == base.UNDEFINED_PRICE
            canonical += int(np.count_nonzero(empty & ((sizes != 0) | (counts != 0))))
            negative += int(np.count_nonzero(sizes < 0) + np.count_nonzero(counts < 0))
    return canonical, negative


def _two_sided_arrays(arrays: Mapping[str, np.ndarray[Any, Any]], base: Any) -> np.ndarray[Any, Any]:
    return (
        (arrays["bid_px_00"] != base.UNDEFINED_PRICE)
        & (arrays["ask_px_00"] != base.UNDEFINED_PRICE)
        & (arrays["bid_sz_00"] > 0)
        & (arrays["ask_sz_00"] > 0)
        & (arrays["bid_ct_00"] > 0)
        & (arrays["ask_ct_00"] > 0)
    )


def _primary_mbp_allocate(
    arrays: Mapping[str, np.ndarray[Any, Any]],
    anchor_table: pa.Table,
    start: int,
    end: int,
    instrument_id: int,
    base: Any,
) -> tuple[dict[str, np.ndarray[Any, Any]], list[Any], Counter[str]]:
    counts = {name: np.zeros(WINDOW_BUCKETS, dtype=np.int64) for name in base.MBP_STATE_COLUMNS[:9]}
    audit = Counter()
    anchor = _anchor_arrays(anchor_table, base.MBP_COLUMNS)
    receives = arrays["ts_recv"].astype(np.int64, copy=False)
    ordinals = arrays["source_row_ordinal"].astype(np.int64, copy=False)
    buckets = ((receives - start) // BUCKET_WIDTH_NS).astype(np.int64)
    if np.any((receives < start) | (receives >= end) | (buckets < 0) | (buckets >= WINDOW_BUCKETS)):
        raise ValueError("MBP-10 source row entered the wrong frozen window")
    anchor_recv = int(anchor["ts_recv"][0])
    if not int(row_day_start := start - (start % (86_400 * BUCKET_WIDTH_NS))) <= anchor_recv < start:
        raise ValueError("MBP-10 anchor crosses a calendar-date boundary")
    actions = arrays["action"].astype(object, copy=False)
    flags = arrays["flags"].astype(np.int64, copy=False)
    every = np.ones(len(receives), dtype=bool)
    snapshot = (flags & F_SNAPSHOT) != 0
    known = np.isin(actions, tuple(KNOWN_ACTIONS))
    _primary_accumulate(counts["mbp_update_count"], buckets, every)
    _primary_accumulate(counts["mbp_snapshot_count"], buckets, snapshot)
    _primary_accumulate(counts["mbp_reset_count"], buckets, actions == "R")
    _primary_accumulate(counts["mbp_unknown_action_count"], buckets, ~known)
    _primary_accumulate(counts["mbp_bad_ts_recv_flag_count"], buckets, (flags & F_BAD_TS_RECV) != 0)
    _primary_accumulate(counts["mbp_maybe_bad_book_flag_count"], buckets, (flags & F_MAYBE_BAD_BOOK) != 0)
    two = _two_sided_arrays(arrays, base)
    anchor_two = bool(_two_sided_arrays(anchor, base)[0])
    previous_snapshot = np.concatenate((np.asarray([bool(int(anchor["flags"][0]) & F_SNAPSHOT)]), snapshot[:-1]))
    previous_action = np.concatenate((np.asarray([str(anchor["action"][0])], dtype=object), actions[:-1]))
    previous_two = np.concatenate((np.asarray([anchor_two]), two[:-1]))
    eligible = previous_two & ~previous_snapshot & (previous_action != "R") & two & ~snapshot & (actions != "R")
    prev_bid_px = np.concatenate((anchor["bid_px_00"].astype(np.int64), arrays["bid_px_00"][:-1].astype(np.int64)))
    prev_bid_sz = np.concatenate((anchor["bid_sz_00"].astype(np.int64), arrays["bid_sz_00"][:-1].astype(np.int64)))
    prev_ask_px = np.concatenate((anchor["ask_px_00"].astype(np.int64), arrays["ask_px_00"][:-1].astype(np.int64)))
    prev_ask_sz = np.concatenate((anchor["ask_sz_00"].astype(np.int64), arrays["ask_sz_00"][:-1].astype(np.int64)))
    bid_px = arrays["bid_px_00"].astype(np.int64, copy=False)
    bid_sz = arrays["bid_sz_00"].astype(np.int64, copy=False)
    ask_px = arrays["ask_px_00"].astype(np.int64, copy=False)
    ask_sz = arrays["ask_sz_00"].astype(np.int64, copy=False)
    ofi = (
        np.where(bid_px >= prev_bid_px, bid_sz, 0)
        - np.where(bid_px <= prev_bid_px, prev_bid_sz, 0)
        - np.where(ask_px <= prev_ask_px, ask_sz, 0)
        + np.where(ask_px >= prev_ask_px, prev_ask_sz, 0)
    ).astype(np.int64)
    _primary_accumulate(counts["quote_ofi_transition_count"], buckets, eligible)
    _primary_accumulate(counts["quote_ofi_skipped_count"], buckets, ~eligible)
    _primary_accumulate(counts["quote_ofi_raw"], buckets, eligible, ofi)
    last_by_bucket = np.full(WINDOW_BUCKETS, -1, dtype=np.int64)
    if len(buckets):
        tails = np.r_[np.flatnonzero(buckets[1:] != buckets[:-1]), len(buckets) - 1]
        last_by_bucket[buckets[tails]] = tails
    states: list[Any] = []
    carried_index = -1
    for bucket in range(WINDOW_BUCKETS):
        if last_by_bucket[bucket] >= 0:
            carried_index = int(last_by_bucket[bucket])
            levels = tuple(int(arrays[name][carried_index]) for name in base.BOOK_FIELDS)
            states.append(base.PrimaryBookState(
                ordinal=int(ordinals[carried_index]),
                recv=int(receives[carried_index]),
                action=str(actions[carried_index]),
                flags=int(flags[carried_index]),
                levels=levels,
            ))
        elif carried_index >= 0:
            states.append(states[-1])
        else:
            states.append(base.PrimaryBookState(
                ordinal=int(anchor["source_row_ordinal"][0]),
                recv=anchor_recv,
                action=str(anchor["action"][0]),
                flags=int(anchor["flags"][0]),
                levels=tuple(int(anchor[name][0]) for name in base.BOOK_FIELDS),
            ))
    combined_book = {name: np.concatenate((anchor[name], arrays[name])) for name in base.BOOK_FIELDS}
    canonical, negative = _book_validity_counts(combined_book, base)
    audit.update({
        "mbp10_selected_rows": len(receives),
        "mbp10_anchor_rows": 1,
        "mbp10_timestamp_or_ordinal_regressions": _order_regressions(receives, ordinals),
        "mbp10_publisher_mismatches": int(np.count_nonzero(arrays["publisher_id"] != 1)) + int(anchor["publisher_id"][0] != 1),
        "mbp10_instrument_mismatches": int(np.count_nonzero(arrays["instrument_id"] != instrument_id)) + int(anchor["instrument_id"][0] != instrument_id),
        "mbp10_unknown_action_rows": int(np.count_nonzero(~known)),
        "mbp10_maybe_bad_book_rows": int(np.count_nonzero((flags & F_MAYBE_BAD_BOOK) != 0)),
        "empty_level_canonical_violations": canonical,
        "negative_size_or_count_values": negative,
        "continuous_crossed_book_rows": int(np.count_nonzero(two & (ask_px < bid_px))),
        "mbp10_rows_allocated": int(np.sum(counts["mbp_update_count"])),
        "anchor_not_before_window": int(anchor_recv >= start),
    })
    return counts, states, audit


def _reference_mbp_allocate(
    arrays: Mapping[str, np.ndarray[Any, Any]],
    anchor_table: pa.Table,
    start: int,
    end: int,
    instrument_id: int,
    base: Any,
) -> tuple[dict[str, np.ndarray[Any, Any]], list[Any], Counter[str]]:
    counts = {name: np.zeros(WINDOW_BUCKETS, dtype=np.int64) for name in base.MBP_STATE_COLUMNS[:9]}
    anchor = _anchor_arrays(anchor_table, base.MBP_COLUMNS)
    receives = np.asarray(arrays["ts_recv"], dtype=np.int64)
    ordinals = np.asarray(arrays["source_row_ordinal"], dtype=np.int64)
    buckets = np.floor_divide(receives - start, BUCKET_WIDTH_NS).astype(np.int64)
    if np.any(np.logical_or.reduce((receives < start, receives >= end, buckets < 0, buckets >= WINDOW_BUCKETS))):
        raise ValueError("Reference MBP-10 allocation escaped its frozen window")
    anchor_recv = int(anchor["ts_recv"][0])
    day_start = start - (start % (86_400 * BUCKET_WIDTH_NS))
    if anchor_recv < day_start or anchor_recv >= start:
        raise ValueError("Reference MBP-10 anchor crosses the date/window boundary")
    actions = np.asarray(arrays["action"], dtype=object)
    flags = np.asarray(arrays["flags"], dtype=np.int64)
    all_rows = np.full(receives.shape, True, dtype=bool)
    snapshots = np.bitwise_and(flags, F_SNAPSHOT) != 0
    known = np.isin(actions, list(KNOWN_ACTIONS))
    _reference_accumulate(counts["mbp_update_count"], buckets, all_rows)
    _reference_accumulate(counts["mbp_snapshot_count"], buckets, snapshots)
    _reference_accumulate(counts["mbp_reset_count"], buckets, actions == "R")
    _reference_accumulate(counts["mbp_unknown_action_count"], buckets, np.logical_not(known))
    _reference_accumulate(counts["mbp_bad_ts_recv_flag_count"], buckets, np.bitwise_and(flags, F_BAD_TS_RECV) != 0)
    _reference_accumulate(counts["mbp_maybe_bad_book_flag_count"], buckets, np.bitwise_and(flags, F_MAYBE_BAD_BOOK) != 0)
    two = _two_sided_arrays(arrays, base)
    prior_two = np.concatenate((_two_sided_arrays(anchor, base), two[:-1]))
    prior_snapshot = np.concatenate((np.bitwise_and(anchor["flags"].astype(np.int64), F_SNAPSHOT) != 0, snapshots[:-1]))
    prior_action = np.concatenate((np.asarray(anchor["action"], dtype=object), actions[:-1]))
    can_measure = prior_two & ~prior_snapshot & (prior_action != "R") & two & ~snapshots & (actions != "R")
    previous = {
        name: np.concatenate((np.asarray(anchor[name], dtype=np.int64), np.asarray(arrays[name][:-1], dtype=np.int64)))
        for name in ("bid_px_00", "bid_sz_00", "ask_px_00", "ask_sz_00")
    }
    bid_px = np.asarray(arrays["bid_px_00"], dtype=np.int64)
    bid_sz = np.asarray(arrays["bid_sz_00"], dtype=np.int64)
    ask_px = np.asarray(arrays["ask_px_00"], dtype=np.int64)
    ask_sz = np.asarray(arrays["ask_sz_00"], dtype=np.int64)
    bid_component = np.where(bid_px >= previous["bid_px_00"], bid_sz, 0) - np.where(bid_px <= previous["bid_px_00"], previous["bid_sz_00"], 0)
    ask_component = -np.where(ask_px <= previous["ask_px_00"], ask_sz, 0) + np.where(ask_px >= previous["ask_px_00"], previous["ask_sz_00"], 0)
    ofi = (bid_component + ask_component).astype(np.int64)
    _reference_accumulate(counts["quote_ofi_transition_count"], buckets, can_measure)
    _reference_accumulate(counts["quote_ofi_skipped_count"], buckets, np.logical_not(can_measure))
    _reference_accumulate(counts["quote_ofi_raw"], buckets, can_measure, ofi)
    latest: dict[int, int] = {}
    if len(buckets):
        reversed_indices = np.arange(len(buckets) - 1, -1, -1, dtype=np.int64)
        reversed_buckets = buckets[reversed_indices]
        _values, first = np.unique(reversed_buckets, return_index=True)
        for position in first:
            original = int(reversed_indices[int(position)])
            latest[int(buckets[original])] = original
    anchor_state = base.ReferenceBookState(
        ordinal=int(anchor["source_row_ordinal"][0]),
        recv=anchor_recv,
        action=str(anchor["action"][0]),
        flags=int(anchor["flags"][0]),
        levels={name: int(anchor[name][0]) for name in base.BOOK_FIELDS},
    )
    states: list[Any] = []
    carried = anchor_state
    for bucket in range(WINDOW_BUCKETS):
        if bucket in latest:
            index = latest[bucket]
            carried = base.ReferenceBookState(
                ordinal=int(ordinals[index]),
                recv=int(receives[index]),
                action=str(actions[index]),
                flags=int(flags[index]),
                levels={name: int(arrays[name][index]) for name in base.BOOK_FIELDS},
            )
        states.append(carried)
    combined = {name: np.concatenate((np.asarray(anchor[name]), np.asarray(arrays[name]))) for name in base.BOOK_FIELDS}
    canonical, negative = _book_validity_counts(combined, base)
    audit = Counter({
        "mbp10_selected_rows": len(receives),
        "mbp10_anchor_rows": 1,
        "mbp10_timestamp_or_ordinal_regressions": _order_regressions(receives, ordinals),
        "mbp10_publisher_mismatches": int(np.not_equal(arrays["publisher_id"], 1).sum()) + int(int(anchor["publisher_id"][0]) != 1),
        "mbp10_instrument_mismatches": int(np.not_equal(arrays["instrument_id"], instrument_id).sum()) + int(int(anchor["instrument_id"][0]) != instrument_id),
        "mbp10_unknown_action_rows": int(np.logical_not(known).sum()),
        "mbp10_maybe_bad_book_rows": int((np.bitwise_and(flags, F_MAYBE_BAD_BOOK) != 0).sum()),
        "empty_level_canonical_violations": canonical,
        "negative_size_or_count_values": negative,
        "continuous_crossed_book_rows": int(np.logical_and(two, ask_px < bid_px).sum()),
        "mbp10_rows_allocated": int(counts["mbp_update_count"].sum()),
        "anchor_not_before_window": int(anchor_recv >= start),
    })
    return counts, states, audit


def _materialize_window(
    row: Mapping[str, Any],
    events: Mapping[str, np.ndarray[Any, Any]],
    mbp: Mapping[str, np.ndarray[Any, Any]],
    states: Sequence[Any],
    base: Any,
    implementation: str,
) -> dict[str, list[Any]]:
    if len(states) != WINDOW_BUCKETS:
        raise ValueError("Book-state carry did not cover 900 bucket closes")
    start = int(row["window_start_inclusive_ns"])
    segment = _continuous_segment_name(start)
    output: dict[str, list[Any]] = {name: [] for name in base.FEATURE_COLUMNS}
    ratio = base._primary_ratio if implementation == "primary" else base._reference_ratio
    book_features = base._primary_book_features if implementation == "primary" else base._reference_book_features
    for bucket in range(WINDOW_BUCKETS):
        bucket_start = start + bucket * BUCKET_WIDTH_NS
        bucket_end = bucket_start + BUCKET_WIDTH_NS
        output["bucket_index"].append(int(row["bucket_index_start_inclusive"]) + bucket)
        output["bucket_start_ns"].append(bucket_start)
        output["bucket_end_ns"].append(bucket_end)
        output["market_segment"].append(segment)
        output["market_state"].append("CONTINUOUS_MATCHING")
        for name in (*base.MBO_COUNT_COLUMNS, *base.MBO_SIDE_FLOW_COLUMNS):
            output[name].append(int(events[name][bucket]))
        add_bid = int(events["add_qty_bid"][bucket])
        add_ask = int(events["add_qty_ask"][bucket])
        cancel_bid = int(events["cancel_qty_bid"][bucket])
        cancel_ask = int(events["cancel_qty_ask"][bucket])
        trade_buy = int(events["trade_qty_buy"][bucket])
        trade_sell = int(events["trade_qty_sell"][bucket])
        output["add_imbalance_ppb"].append(ratio(add_bid - add_ask, add_bid + add_ask))
        output["cancel_pressure_imbalance_ppb"].append(ratio(cancel_ask - cancel_bid, cancel_ask + cancel_bid))
        output["displayed_pressure_ppb"].append(ratio((add_bid + cancel_ask) - (add_ask + cancel_bid), add_bid + cancel_ask + add_ask + cancel_bid))
        output["trade_imbalance_ppb"].append(ratio(trade_buy - trade_sell, trade_buy + trade_sell))
        for name in base.MBP_STATE_COLUMNS[:9]:
            output[name].append(int(mbp[name][bucket]))
        features = book_features(states[bucket], bucket_end)
        for name in (*base.MBP_STATE_COLUMNS[9:], *base.MBP_PRICE_COLUMNS, *base.MBP_DEPTH_COLUMNS):
            output[name].append(features[name])
    if tuple(output) != tuple(base.FEATURE_COLUMNS) or any(len(values) != WINDOW_BUCKETS for values in output.values()):
        raise ValueError("Materialized window differs from frozen 85-column schema")
    return output


def _continuous_segment_name(timestamp_ns: int) -> str:
    utc = datetime.fromtimestamp(timestamp_ns / 1_000_000_000, UTC)
    offset = utc.astimezone(ZoneInfo("America/Chicago")).utcoffset()
    if offset is None:
        raise ValueError("Chicago DST offset is unavailable")
    hours = int(offset.total_seconds() // 3600)
    if hours == -6:
        return "CONTINUOUS_00_22"
    if hours == -5:
        return "CONTINUOUS_00_21"
    raise ValueError(f"Unexpected Chicago UTC offset: {hours}")


def _order_regressions(receives: np.ndarray[Any, Any], ordinals: np.ndarray[Any, Any]) -> int:
    if len(receives) < 2:
        return 0
    return int(np.count_nonzero(receives[1:] < receives[:-1])) + int(
        np.count_nonzero((receives[1:] == receives[:-1]) & (ordinals[1:] <= ordinals[:-1]))
    )


def _primary_decision_observations(
    row: Mapping[str, Any],
    columns: Mapping[str, Sequence[Any]],
    context: Mapping[str, Any],
    asia_history: Mapping[str, Any],
    base: Any,
) -> dict[str, Observation]:
    micro = _primary_micro_states(columns, base)
    contexts = _primary_context_observations(row, context, asia_history)
    return {**micro, **contexts}


def _reference_decision_observations(
    row: Mapping[str, Any],
    columns: Mapping[str, Sequence[Any]],
    context: Mapping[str, Any],
    asia_history: Mapping[str, Any],
    base: Any,
) -> dict[str, Observation]:
    micro = _reference_micro_states(columns, base)
    contexts = _reference_context_observations(row, context, asia_history)
    return {**micro, **contexts}


def _primary_micro_states(columns: Mapping[str, Sequence[Any]], base: Any) -> dict[str, Observation]:
    flow60 = _primary_flow_pressure(columns, 60, base)
    flow900 = _primary_flow_pressure(columns, 900, base)
    depth60 = _primary_depth_pressure(columns, 60)
    depth900 = _primary_depth_pressure(columns, 900)
    activity = _primary_activity_shift(columns)
    fragility = _primary_fragility(columns)
    absorption = _primary_absorption(columns)
    alignment = _alignment_observation(flow60, depth60)
    return {
        "FLOW_PRESSURE_W60": flow60,
        "FLOW_PRESSURE_W900": flow900,
        "DEPTH_PRESSURE_W60": depth60,
        "DEPTH_PRESSURE_W900": depth900,
        "LIQUIDITY_ACTIVITY_SHIFT": activity,
        "LIQUIDITY_FRAGILITY": fragility,
        "ABSORPTION_STATE_W60": absorption,
        "FLOW_DEPTH_ALIGNMENT": alignment,
    }


def _reference_micro_states(columns: Mapping[str, Sequence[Any]], base: Any) -> dict[str, Observation]:
    flow_by_window = {
        width: _reference_flow_pressure(columns, width, base) for width in (60, 900)
    }
    depth_by_window = {
        width: _reference_depth_pressure(columns, width) for width in (60, 900)
    }
    result = {
        "FLOW_PRESSURE_W60": flow_by_window[60],
        "FLOW_PRESSURE_W900": flow_by_window[900],
        "DEPTH_PRESSURE_W60": depth_by_window[60],
        "DEPTH_PRESSURE_W900": depth_by_window[900],
        "LIQUIDITY_ACTIVITY_SHIFT": _reference_activity_shift(columns),
        "LIQUIDITY_FRAGILITY": _reference_fragility(columns),
        "ABSORPTION_STATE_W60": _reference_absorption(columns),
    }
    flow_state = result["FLOW_PRESSURE_W60"].state
    depth_state = result["DEPTH_PRESSURE_W60"].state
    if flow_state == depth_state and flow_state in {"BULLISH", "BEARISH"}:
        state = flow_state
    elif {flow_state, depth_state} == {"BULLISH", "BEARISH"}:
        state = "CONFLICTED"
    else:
        state = "NEUTRAL_OR_UNKNOWN"
    result["FLOW_DEPTH_ALIGNMENT"] = _calculated(state, {
        "flow_state": flow_state,
        "depth_state": depth_state,
    })
    return result


def _window_values(columns: Mapping[str, Sequence[Any]], name: str, width: int) -> list[Any]:
    values = list(columns[name])
    if len(values) != WINDOW_BUCKETS or width not in {60, 900}:
        raise ValueError("Invalid frozen decision window")
    return values[-width:]


def _primary_flow_pressure(columns: Mapping[str, Sequence[Any]], width: int, base: Any) -> Observation:
    selected = slice(WINDOW_BUCKETS - width, WINDOW_BUCKETS)
    add_bid = sum(int(value) for value in columns["add_qty_bid"][selected])
    add_ask = sum(int(value) for value in columns["add_qty_ask"][selected])
    cancel_bid = sum(int(value) for value in columns["cancel_qty_bid"][selected])
    cancel_ask = sum(int(value) for value in columns["cancel_qty_ask"][selected])
    buy = sum(int(value) for value in columns["trade_qty_buy"][selected])
    sell = sum(int(value) for value in columns["trade_qty_sell"][selected])
    transitions = sum(int(value) for value in columns["quote_ofi_transition_count"][selected])
    ofi = sum(int(value) for value in columns["quote_ofi_raw"][selected])
    displayed = base._primary_ratio((add_bid + cancel_ask) - (add_ask + cancel_bid), add_bid + cancel_ask + add_ask + cancel_bid)
    trade = base._primary_ratio(buy - sell, buy + sell)
    components = [displayed, trade, ofi if transitions > 0 else None]
    known = [value for value in components if value is not None]
    if len(known) < 2:
        return _unknown()
    positives = sum(value > 0 for value in known)
    negatives = sum(value < 0 for value in known)
    state = "BULLISH" if positives >= 2 and negatives == 0 else "BEARISH" if negatives >= 2 and positives == 0 else "CONFLICTED"
    return _calculated(state, {"window": width, "displayed": displayed, "trade": trade, "ofi": ofi if transitions else None, "transitions": transitions})


def _reference_flow_pressure(columns: Mapping[str, Sequence[Any]], width: int, base: Any) -> Observation:
    start = WINDOW_BUCKETS - width
    totals = {name: int(np.asarray(columns[name][start:], dtype=np.int64).sum()) for name in (
        "add_qty_bid", "add_qty_ask", "cancel_qty_bid", "cancel_qty_ask",
        "trade_qty_buy", "trade_qty_sell", "quote_ofi_raw", "quote_ofi_transition_count",
    )}
    displayed_numerator = totals["add_qty_bid"] + totals["cancel_qty_ask"] - totals["add_qty_ask"] - totals["cancel_qty_bid"]
    displayed_denominator = totals["add_qty_bid"] + totals["cancel_qty_ask"] + totals["add_qty_ask"] + totals["cancel_qty_bid"]
    displayed = base._reference_ratio(displayed_numerator, displayed_denominator)
    trade = base._reference_ratio(totals["trade_qty_buy"] - totals["trade_qty_sell"], totals["trade_qty_buy"] + totals["trade_qty_sell"])
    ofi: int | None = totals["quote_ofi_raw"] if totals["quote_ofi_transition_count"] > 0 else None
    components = tuple(value for value in (displayed, trade, ofi) if value is not None)
    if len(components) < 2:
        return _unknown()
    signs = Counter(1 if value > 0 else -1 if value < 0 else 0 for value in components)
    state = "BULLISH" if signs[1] >= 2 and signs[-1] == 0 else "BEARISH" if signs[-1] >= 2 and signs[1] == 0 else "CONFLICTED"
    return _calculated(state, {"window": width, "displayed": displayed, "trade": trade, "ofi": ofi, "transitions": totals["quote_ofi_transition_count"]})


def _primary_depth_pressure(columns: Mapping[str, Sequence[Any]], width: int) -> Observation:
    medians = [_integer_median(_window_values(columns, name, width)) for name in (
        "depth_imbalance_l1_ppb", "depth_imbalance_l5_ppb", "depth_imbalance_l10_ppb"
    )]
    midpoint = columns["midpoint_fixed_1e9"][-1]
    microprice = columns["microprice_fixed_1e9"][-1]
    terminal = None if midpoint is None or microprice is None else int(microprice) - int(midpoint)
    known = [value for value in (*medians, terminal) if value is not None]
    if len(known) < 3:
        return _unknown()
    positive = sum(value > 0 for value in known)
    negative = sum(value < 0 for value in known)
    state = "BULLISH" if positive >= 3 else "BEARISH" if negative >= 3 else "CONFLICTED"
    return _calculated(state, {"window": width, "medians": medians, "terminal_microprice_minus_midpoint": terminal})


def _reference_depth_pressure(columns: Mapping[str, Sequence[Any]], width: int) -> Observation:
    names = ("depth_imbalance_l1_ppb", "depth_imbalance_l5_ppb", "depth_imbalance_l10_ppb")
    values = [_reference_integer_median(columns[name][WINDOW_BUCKETS - width :]) for name in names]
    terminal_pair = (columns["microprice_fixed_1e9"][-1], columns["midpoint_fixed_1e9"][-1])
    terminal = None if any(value is None for value in terminal_pair) else int(terminal_pair[0]) - int(terminal_pair[1])
    known = tuple(value for value in (*values, terminal) if value is not None)
    if len(known) < 3:
        return _unknown()
    signs = [int(value > 0) - int(value < 0) for value in known]
    state = "BULLISH" if signs.count(1) >= 3 else "BEARISH" if signs.count(-1) >= 3 else "CONFLICTED"
    return _calculated(state, {"window": width, "medians": values, "terminal_microprice_minus_midpoint": terminal})


def _primary_activity_shift(columns: Mapping[str, Sequence[Any]]) -> Observation:
    comparisons = []
    payload: dict[str, Any] = {}
    for name in ("mbo_live_records", "mbp_update_count", "quote_ofi_transition_count"):
        w60 = sum(int(value) for value in columns[name][-60:])
        w900 = sum(int(value) for value in columns[name])
        comparison = 1 if w60 * 900 > w900 * 60 else -1 if w60 * 900 < w900 * 60 else 0
        comparisons.append(comparison)
        payload[name] = {"w60": w60, "w900": w900}
    state = "HIGH" if comparisons.count(1) >= 2 else "LOW" if comparisons.count(-1) >= 2 else "STABLE"
    return _calculated(state, payload)


def _reference_activity_shift(columns: Mapping[str, Sequence[Any]]) -> Observation:
    higher = 0
    lower = 0
    payload: dict[str, Any] = {}
    for name in ("mbo_live_records", "mbp_update_count", "quote_ofi_transition_count"):
        vector = np.asarray(columns[name], dtype=np.int64)
        recent = int(np.add.reduce(vector[-60:], dtype=np.int64))
        complete = int(np.add.reduce(vector, dtype=np.int64))
        left, right = recent * 900, complete * 60
        higher += int(left > right)
        lower += int(left < right)
        payload[name] = {"w60": recent, "w900": complete}
    state = "HIGH" if higher >= 2 else "LOW" if lower >= 2 else "STABLE"
    return _calculated(state, payload)


def _primary_fragility(columns: Mapping[str, Sequence[Any]]) -> Observation:
    spread60 = _integer_median(columns["spread_fixed_1e9"][-60:])
    spread900 = _integer_median(columns["spread_fixed_1e9"])
    age_terminal = columns["book_age_ns"][-1]
    age900 = _integer_median(columns["book_age_ns"])
    depth60 = _integer_median([
        None if bid is None or ask is None else int(bid) + int(ask)
        for bid, ask in zip(columns["bid_depth_l10"][-60:], columns["ask_depth_l10"][-60:])
    ])
    depth900 = _integer_median([
        None if bid is None or ask is None else int(bid) + int(ask)
        for bid, ask in zip(columns["bid_depth_l10"], columns["ask_depth_l10"])
    ])
    pairs = ((spread60, spread900, 1), (age_terminal, age900, 1), (depth60, depth900, -1))
    known = [(left, right, direction) for left, right, direction in pairs if left is not None and right is not None]
    if len(known) < 2:
        return _unknown()
    fragile = sum((left > right) if direction == 1 else (left < right) for left, right, direction in known)
    resilient = sum((left < right) if direction == 1 else (left > right) for left, right, direction in known)
    state = "FRAGILE" if fragile >= 2 else "RESILIENT" if resilient >= 2 else "MIXED"
    return _calculated(state, {"spread60": spread60, "spread900": spread900, "terminal_age": age_terminal, "age900": age900, "depth60": depth60, "depth900": depth900})


def _reference_fragility(columns: Mapping[str, Sequence[Any]]) -> Observation:
    spread_pair = (_reference_integer_median(columns["spread_fixed_1e9"][-60:]), _reference_integer_median(columns["spread_fixed_1e9"]))
    age_pair = (columns["book_age_ns"][-1], _reference_integer_median(columns["book_age_ns"]))
    total_depth = [None if bid is None or ask is None else int(bid) + int(ask) for bid, ask in zip(columns["bid_depth_l10"], columns["ask_depth_l10"])]
    depth_pair = (_reference_integer_median(total_depth[-60:]), _reference_integer_median(total_depth))
    tests = []
    if None not in spread_pair:
        tests.append((int(spread_pair[0]) > int(spread_pair[1]), int(spread_pair[0]) < int(spread_pair[1])))
    if None not in age_pair:
        tests.append((int(age_pair[0]) > int(age_pair[1]), int(age_pair[0]) < int(age_pair[1])))
    if None not in depth_pair:
        tests.append((int(depth_pair[0]) < int(depth_pair[1]), int(depth_pair[0]) > int(depth_pair[1])))
    if len(tests) < 2:
        return _unknown()
    fragile = sum(test[0] for test in tests)
    resilient = sum(test[1] for test in tests)
    state = "FRAGILE" if fragile >= 2 else "RESILIENT" if resilient >= 2 else "MIXED"
    return _calculated(state, {"spread60": spread_pair[0], "spread900": spread_pair[1], "terminal_age": age_pair[0], "age900": age_pair[1], "depth60": depth_pair[0], "depth900": depth_pair[1]})


def _primary_absorption(columns: Mapping[str, Sequence[Any]]) -> Observation:
    buy = sum(int(value) for value in columns["trade_qty_buy"][-60:])
    sell = sum(int(value) for value in columns["trade_qty_sell"][-60:])
    midpoint_values = list(columns["midpoint_fixed_1e9"][-60:])
    earliest = next((value for value in midpoint_values if value is not None), None)
    terminal = midpoint_values[-1]
    progress = None if earliest is None or terminal is None else int(terminal) - int(earliest)
    transitions = sum(int(value) for value in columns["quote_ofi_transition_count"][-60:])
    ofi = sum(int(value) for value in columns["quote_ofi_raw"][-60:]) if transitions else None
    depth = _integer_median(columns["depth_imbalance_l5_ppb"][-60:])
    if buy + sell == 0 or progress is None or (ofi is None and depth is None):
        return _unknown()
    bearish_confirmation = (ofi is not None and ofi < 0) or (depth is not None and depth < 0)
    bullish_confirmation = (ofi is not None and ofi > 0) or (depth is not None and depth > 0)
    state = "BEARISH_ABSORPTION" if buy > sell and progress <= 0 and bearish_confirmation else "BULLISH_ABSORPTION" if sell > buy and progress >= 0 and bullish_confirmation else "NONE"
    return _calculated(state, {"buy": buy, "sell": sell, "progress": progress, "ofi": ofi, "depth": depth})


def _reference_absorption(columns: Mapping[str, Sequence[Any]]) -> Observation:
    buy = int(np.asarray(columns["trade_qty_buy"][-60:], dtype=np.int64).sum())
    sell = int(np.asarray(columns["trade_qty_sell"][-60:], dtype=np.int64).sum())
    midpoint = [value for value in columns["midpoint_fixed_1e9"][-60:] if value is not None]
    terminal_raw = columns["midpoint_fixed_1e9"][-1]
    progress = None if not midpoint or terminal_raw is None else int(terminal_raw) - int(midpoint[0])
    transition_count = int(np.asarray(columns["quote_ofi_transition_count"][-60:], dtype=np.int64).sum())
    ofi = int(np.asarray(columns["quote_ofi_raw"][-60:], dtype=np.int64).sum()) if transition_count > 0 else None
    depth = _reference_integer_median(columns["depth_imbalance_l5_ppb"][-60:])
    if buy + sell <= 0 or progress is None or all(value is None for value in (ofi, depth)):
        return _unknown()
    confirmations = [value for value in (ofi, depth) if value is not None]
    if buy > sell and progress <= 0 and any(value < 0 for value in confirmations):
        state = "BEARISH_ABSORPTION"
    elif sell > buy and progress >= 0 and any(value > 0 for value in confirmations):
        state = "BULLISH_ABSORPTION"
    else:
        state = "NONE"
    return _calculated(state, {"buy": buy, "sell": sell, "progress": progress, "ofi": ofi, "depth": depth})


def _alignment_observation(flow: Observation, depth: Observation) -> Observation:
    if flow.state == depth.state and flow.state in {"BULLISH", "BEARISH"}:
        state = flow.state
    elif {flow.state, depth.state} == {"BULLISH", "BEARISH"}:
        state = "CONFLICTED"
    else:
        state = "NEUTRAL_OR_UNKNOWN"
    return _calculated(state, {"flow_state": flow.state, "depth_state": depth.state})


def _integer_median(values: Iterable[Any]) -> int | None:
    ordered = sorted(int(value) for value in values if value is not None)
    if not ordered:
        return None
    middle = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[middle]
    return _round_half_away(ordered[middle - 1] + ordered[middle], 2)


def _reference_integer_median(values: Iterable[Any]) -> int | None:
    selected = np.asarray([int(value) for value in values if value is not None], dtype=np.int64)
    if selected.size == 0:
        return None
    selected.sort(kind="mergesort")
    half = selected.size // 2
    if selected.size & 1:
        return int(selected[half])
    total = int(selected[half - 1]) + int(selected[half])
    quotient, remainder = divmod(abs(total), 2)
    if remainder * 2 >= 2:
        quotient += 1
    return -quotient if total < 0 else quotient


def _round_half_away(numerator: int, denominator: int) -> int:
    sign = -1 if numerator < 0 else 1
    absolute = abs(numerator)
    return sign * ((absolute * 2 + denominator) // (2 * denominator))


def _unknown() -> Observation:
    return Observation("UNKNOWN", "UNKNOWN", "MISSING", "UNKNOWN")


def _calculated(state: str, payload: Any, *, quality: str = "VALID", epistemic: str = "CALCULATED") -> Observation:
    if state == "UNKNOWN":
        return _unknown()
    return Observation(state, epistemic, quality, _canonical_hash(payload))


def _primary_context_observations(
    row: Mapping[str, Any], projection: Mapping[str, Any], asia_history: Mapping[str, Any]
) -> dict[str, Observation]:
    decision_state = _mapping(projection.get("decision_state"))
    decision = _parse_time(str(row["decision_at_utc"]))
    fundamentals = _primary_fundamental_contexts(decision_state, projection, decision)
    levels = _primary_level_contexts(row, decision_state, projection, asia_history, decision)
    return {**fundamentals, **levels}


def _reference_context_observations(
    row: Mapping[str, Any], projection: Mapping[str, Any], asia_history: Mapping[str, Any]
) -> dict[str, Observation]:
    state_value = projection.get("decision_state")
    decision_state = state_value if isinstance(state_value, Mapping) else {}
    decision = datetime.fromisoformat(str(row["decision_at_utc"]).replace("Z", "+00:00")).astimezone(UTC)
    fundamentals = _reference_fundamental_contexts(decision_state, projection, decision)
    levels = _reference_level_contexts(row, decision_state, projection, asia_history, decision)
    return fundamentals | levels


def _primary_fundamental_contexts(
    state: Mapping[str, Any], projection: Mapping[str, Any], decision: datetime
) -> dict[str, Observation]:
    regime = _nested(state, "layers", "market_regime", "regime_state")
    if _fact_eligible(regime, decision):
        score = _number(_mapping(regime.get("value")).get("directional_score"))
        macro = _fact_observation(
            "UNKNOWN" if score is None else "BULLISH" if score >= 20 else "BEARISH" if score <= -20 else "NEUTRAL",
            regime,
            _mapping(regime.get("value")),
            epistemic="INFERRED",
        )
    else:
        macro = _unknown()

    real = _nested(state, "layers", "market_regime", "rates", "real_yield_10y")
    usd = _nested(state, "layers", "market_regime", "usd")
    real_change = _eligible_change(real, decision)
    usd_change = _eligible_change(usd, decision)
    if real_change is None or usd_change is None:
        confirmation = _unknown()
    else:
        confirm_state = "GOLD_BULLISH" if real_change < 0 and usd_change < 0 else "GOLD_BEARISH" if real_change > 0 and usd_change > 0 else "CONFLICTED"
        confirmation = _combined_fact_observation(confirm_state, (real, usd), {"real_change": real_change, "usd_change": usd_change})

    reaction = _nested(state, "layers", "market_regime", "reaction_function")
    reaction_state = str(reaction.get("value")) if _fact_eligible(reaction, decision) else "UNKNOWN"
    reaction_observation = _fact_observation(reaction_state, reaction, reaction.get("value")) if reaction_state != "UNKNOWN" else _unknown()

    release = _primary_recent_release_context(state, decision)
    upcoming = _primary_upcoming_context(state, projection, decision)
    stress_fact = _nested(state, "layers", "market_regime", "risk", "financial_stress")
    stress_value = _number(_mapping(stress_fact.get("value")).get("value")) if _fact_eligible(stress_fact, decision) else None
    stress = _fact_observation("STRESS" if stress_value is not None and stress_value > 0 else "NORMAL" if stress_value is not None else "UNKNOWN", stress_fact, _mapping(stress_fact.get("value")), epistemic="CALCULATED") if stress_value is not None else _unknown()
    crowding = _primary_crowding_context(state, decision)
    weekly = _primary_cot_weekly_context(_sequence(projection.get("cot_pair")), decision)
    return {
        "MACRO_ENGINE_BIAS_STATE": macro,
        "REAL_YIELD_USD_CONFIRMATION": confirmation,
        "REGIME_REACTION_FUNCTION_STATE": reaction_observation,
        "RECENT_RELEASE_SURPRISE_DIRECTION": release,
        "UPCOMING_CATALYST_RISK": upcoming,
        "FINANCIAL_STRESS_STATE": stress,
        "COT_MANAGED_MONEY_CROWDING": crowding,
        "COT_WEEKLY_CHANGE_SIGN": weekly,
    }


def _reference_fundamental_contexts(
    state: Mapping[str, Any], projection: Mapping[str, Any], decision: datetime
) -> dict[str, Observation]:
    layers = state.get("layers") if isinstance(state.get("layers"), Mapping) else {}
    market_regime = layers.get("market_regime") if isinstance(layers.get("market_regime"), Mapping) else {}
    regime = market_regime.get("regime_state") if isinstance(market_regime.get("regime_state"), Mapping) else {}
    macro = _unknown()
    if _fact_eligible(regime, decision):
        value = regime.get("value") if isinstance(regime.get("value"), Mapping) else {}
        score = _number(value.get("directional_score"))
        if score is not None:
            label = "BULLISH" if score >= 20.0 else "BEARISH" if score <= -20.0 else "NEUTRAL"
            macro = _fact_observation(label, regime, value, epistemic="INFERRED")

    rates = market_regime.get("rates") if isinstance(market_regime.get("rates"), Mapping) else {}
    real = rates.get("real_yield_10y") if isinstance(rates.get("real_yield_10y"), Mapping) else {}
    usd = market_regime.get("usd") if isinstance(market_regime.get("usd"), Mapping) else {}
    changes: list[float | None] = []
    for fact in (real, usd):
        value = fact.get("value") if isinstance(fact.get("value"), Mapping) else {}
        change = _number(value.get("absolute_change")) if _fact_eligible(fact, decision) and value.get("change_epistemic_status") != "UNKNOWN" else None
        changes.append(change)
    if any(value is None for value in changes):
        confirmation = _unknown()
    else:
        real_change, usd_change = float(changes[0]), float(changes[1])
        label = "GOLD_BULLISH" if max(real_change, usd_change) < 0 else "GOLD_BEARISH" if min(real_change, usd_change) > 0 else "CONFLICTED"
        confirmation = _combined_fact_observation(label, (real, usd), {"real_change": real_change, "usd_change": usd_change})

    reaction_fact = market_regime.get("reaction_function") if isinstance(market_regime.get("reaction_function"), Mapping) else {}
    reaction = _fact_observation(str(reaction_fact["value"]), reaction_fact, reaction_fact["value"]) if _fact_eligible(reaction_fact, decision) else _unknown()
    release = _reference_recent_release_context(state, decision)
    upcoming = _reference_upcoming_context(state, projection, decision)
    risk = market_regime.get("risk") if isinstance(market_regime.get("risk"), Mapping) else {}
    stress_fact = risk.get("financial_stress") if isinstance(risk.get("financial_stress"), Mapping) else {}
    stress_value_map = stress_fact.get("value") if isinstance(stress_fact.get("value"), Mapping) else {}
    stress_number = _number(stress_value_map.get("value")) if _fact_eligible(stress_fact, decision) else None
    stress = _unknown() if stress_number is None else _fact_observation("STRESS" if stress_number > 0.0 else "NORMAL", stress_fact, stress_value_map, epistemic="CALCULATED")
    crowding = _reference_crowding_context(state, decision)
    weekly = _reference_cot_weekly_context(list(_sequence(projection.get("cot_pair"))), decision)
    return dict(zip(FUNDAMENTAL_CONTEXTS, (macro, confirmation, reaction, release, upcoming, stress, crowding, weekly), strict=True))


def _primary_recent_release_context(state: Mapping[str, Any], decision: datetime) -> Observation:
    events = _sequence(_nested(state, "layers", "catalysts").get("recent_events"))
    eligible: list[tuple[datetime, Mapping[str, Any]]] = []
    lower = decision - timedelta(hours=24)
    for raw in events:
        event = _mapping(raw)
        importance = _mapping(event.get("importance"))
        when_text = event.get("scheduled_at")
        if not isinstance(when_text, str) or not _fact_eligible(importance, decision) or _number(importance.get("value")) != 5:
            continue
        when = _parse_time(when_text)
        if lower <= when <= decision:
            eligible.append((when, event))
    if not eligible:
        return _unknown()
    _, latest = max(eligible, key=lambda item: (item[0], str(item[1].get("event_id"))))
    verified = False
    for component_raw in _sequence(latest.get("release_components")):
        component = _mapping(component_raw)
        forecast = _mapping(component.get("forecast"))
        surprise = _mapping(component.get("surprise"))
        released = component.get("released_at")
        if isinstance(released, str) and _fact_eligible(forecast, decision) and _fact_eligible(surprise, decision):
            available = forecast.get("available_at")
            verified |= isinstance(available, str) and _parse_time(available) < _parse_time(released)
    impact = _nested(state, "layers", "catalysts", "event_impact_state")
    event_id = str(latest.get("event_id"))
    tied = event_id in json.dumps(impact.get("evidence", []), sort_keys=True) or event_id in json.dumps(_mapping(impact.get("value")).get("evidence", []), sort_keys=True)
    direction = _number(_mapping(impact.get("value")).get("direction")) if _fact_eligible(impact, decision) else None
    if not verified or not tied or direction is None:
        return _unknown()
    label = "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL"
    return _fact_observation(label, impact, {"event_id": event_id, "impact": _mapping(impact.get("value"))}, epistemic="INFERRED")


def _reference_recent_release_context(state: Mapping[str, Any], decision: datetime) -> Observation:
    recent = _nested(state, "layers", "catalysts").get("recent_events")
    candidates: list[Mapping[str, Any]] = []
    for raw in _sequence(recent):
        event = _mapping(raw)
        importance = _mapping(event.get("importance"))
        scheduled = event.get("scheduled_at")
        if not isinstance(scheduled, str) or not _fact_eligible(importance, decision):
            continue
        hours = (decision - _parse_time(scheduled)).total_seconds() / 3600
        if _number(importance.get("value")) == 5 and 0 <= hours <= 24:
            candidates.append(event)
    candidates.sort(key=lambda item: (_parse_time(str(item["scheduled_at"])), str(item.get("event_id"))))
    if not candidates:
        return _unknown()
    event = candidates[-1]
    forecast_verified = any(
        _fact_eligible(_mapping(component.get("forecast")), decision)
        and _fact_eligible(_mapping(component.get("surprise")), decision)
        and isinstance(component.get("released_at"), str)
        and isinstance(_mapping(component.get("forecast")).get("available_at"), str)
        and _parse_time(str(_mapping(component.get("forecast"))["available_at"])) < _parse_time(str(component["released_at"]))
        for component in (_mapping(item) for item in _sequence(event.get("release_components")))
    )
    impact = _nested(state, "layers", "catalysts", "event_impact_state")
    event_id = str(event.get("event_id"))
    serialized_evidence = json.dumps({"fact": impact.get("evidence"), "value": _mapping(impact.get("value")).get("evidence")}, sort_keys=True)
    direction = _number(_mapping(impact.get("value")).get("direction")) if _fact_eligible(impact, decision) else None
    if not forecast_verified or event_id not in serialized_evidence or direction is None:
        return _unknown()
    label = "BULLISH" if direction > 0 else "BEARISH" if direction < 0 else "NEUTRAL"
    return _fact_observation(label, impact, {"event_id": event_id, "impact": _mapping(impact.get("value"))}, epistemic="INFERRED")


def _primary_upcoming_context(state: Mapping[str, Any], projection: Mapping[str, Any], decision: datetime) -> Observation:
    catalysts = _nested(state, "layers", "catalysts")
    observation_end = _parse_time(str(projection["observation_end"]))
    for raw in _sequence(catalysts.get("upcoming_events")):
        event = _mapping(raw)
        scheduled = event.get("scheduled_at")
        known = event.get("schedule_known_at")
        importance = _mapping(event.get("importance"))
        if isinstance(scheduled, str) and isinstance(known, str) and _parse_time(known) <= decision and _fact_eligible(importance, decision) and _number(importance.get("value")) == 5 and decision < _parse_time(scheduled) <= observation_end:
            return _calculated("HIGH", {"event_id": event.get("event_id"), "scheduled_at": scheduled})
    proximity = _mapping(catalysts.get("proximity_state"))
    if _fact_eligible(proximity, decision) and str(proximity.get("method")) == "VERIFIED_COMPLETE_EVENT_CALENDAR":
        return _fact_observation("NONE", proximity, proximity.get("value"), epistemic="CALCULATED")
    return _unknown()


def _reference_upcoming_context(state: Mapping[str, Any], projection: Mapping[str, Any], decision: datetime) -> Observation:
    catalysts = _nested(state, "layers", "catalysts")
    end = _parse_time(str(projection.get("observation_end")))
    qualifying = []
    for raw in _sequence(catalysts.get("upcoming_events")):
        event = _mapping(raw)
        scheduled_text, known_text = event.get("scheduled_at"), event.get("schedule_known_at")
        importance = _mapping(event.get("importance"))
        if all(isinstance(value, str) for value in (scheduled_text, known_text)) and _fact_eligible(importance, decision):
            scheduled = _parse_time(str(scheduled_text))
            if _parse_time(str(known_text)) <= decision < scheduled <= end and _number(importance.get("value")) == 5:
                qualifying.append(event)
    if qualifying:
        chosen = min(qualifying, key=lambda item: (_parse_time(str(item["scheduled_at"])), str(item.get("event_id"))))
        return _calculated("HIGH", {"event_id": chosen.get("event_id"), "scheduled_at": chosen.get("scheduled_at")})
    proximity = _mapping(catalysts.get("proximity_state"))
    if _fact_eligible(proximity, decision) and proximity.get("method") == "VERIFIED_COMPLETE_EVENT_CALENDAR":
        return _fact_observation("NONE", proximity, proximity.get("value"), epistemic="CALCULATED")
    return _unknown()


def _primary_crowding_context(state: Mapping[str, Any], decision: datetime) -> Observation:
    facts = _sequence(_nested(state, "layers", "positioning").get("inferred_states"))
    matches = [
        _mapping(item) for item in facts
        if _mapping(_mapping(item).get("value")).get("code") == "crowding_state"
    ]
    if len(matches) != 1 or not _fact_eligible(matches[0], decision):
        return _unknown()
    fact = matches[0]
    available = _parse_time(str(fact["available_at"]))
    if decision - available > timedelta(days=10):
        return _unknown()
    value = _mapping(fact.get("value"))
    label = str(value.get("state", "UNKNOWN"))
    return _fact_observation(label, fact, value, epistemic="INFERRED")


def _reference_crowding_context(state: Mapping[str, Any], decision: datetime) -> Observation:
    positioning = _nested(state, "layers", "positioning")
    selected: Mapping[str, Any] | None = None
    for item in _sequence(positioning.get("inferred_states")):
        fact = _mapping(item)
        value = fact.get("value") if isinstance(fact.get("value"), Mapping) else {}
        if value.get("code") == "crowding_state":
            if selected is not None:
                return _unknown()
            selected = fact
    if selected is None or not _fact_eligible(selected, decision):
        return _unknown()
    age_seconds = (decision - _parse_time(str(selected["available_at"]))).total_seconds()
    if age_seconds > 10 * 86_400:
        return _unknown()
    value = _mapping(selected.get("value"))
    return _fact_observation(str(value.get("state", "UNKNOWN")), selected, value, epistemic="INFERRED")


def _primary_cot_weekly_context(pair: Sequence[Any], decision: datetime) -> Observation:
    reports = sorted((_mapping(item) for item in pair), key=lambda item: (_parse_time(str(item.get("available_at"))), str(item.get("observation_date")), str(item.get("record_id"))))
    if len(reports) != 2 or any(item.get("availability_quality") != "OBSERVED" or _parse_time(str(item.get("available_at"))) > decision for item in reports):
        return _unknown()
    if decision - _parse_time(str(reports[-1]["available_at"])) > timedelta(days=10):
        return _unknown()
    previous = _number(reports[0].get("managed_money_net_contracts"))
    latest = _number(reports[1].get("managed_money_net_contracts"))
    if previous is None or latest is None:
        return _unknown()
    label = "UP" if latest > previous else "DOWN" if latest < previous else "FLAT"
    return _calculated(label, {"records": [reports[0].get("record_hash"), reports[1].get("record_hash")], "previous": previous, "latest": latest})


def _reference_cot_weekly_context(pair: list[Any], decision: datetime) -> Observation:
    reports = [_mapping(item) for item in pair]
    reports.sort(key=lambda item: (str(item.get("publication_at")), str(item.get("observation_date")), str(item.get("record_id"))))
    if len(reports) != 2:
        return _unknown()
    for report in reports:
        if report.get("availability_quality") != "OBSERVED" or _parse_time(str(report.get("available_at"))) > decision:
            return _unknown()
    if (decision - _parse_time(str(reports[1]["available_at"]))).total_seconds() > 864_000:
        return _unknown()
    net = [_number(report.get("managed_money_net_contracts")) for report in reports]
    if any(value is None for value in net):
        return _unknown()
    comparison = (float(net[1]) > float(net[0])) - (float(net[1]) < float(net[0]))
    label = {1: "UP", -1: "DOWN", 0: "FLAT"}[comparison]
    return _calculated(label, {"records": [reports[0].get("record_hash"), reports[1].get("record_hash")], "previous": net[0], "latest": net[1]})


def _primary_level_contexts(
    row: Mapping[str, Any],
    state: Mapping[str, Any],
    projection: Mapping[str, Any],
    asia_history: Mapping[str, Any],
    decision: datetime,
) -> dict[str, Observation]:
    price_fact = _nested(state, "market_mechanics", "xauusd_price")
    price = _number(_mapping(price_fact.get("value")).get("value")) if _fact_eligible(price_fact, decision) else None
    asia_high = _level_fact(state, "ASIA_HIGH", decision)
    asia_low = _level_fact(state, "ASIA_LOW", decision)
    prior_high = _level_fact(state, "PRIOR_DAY_HIGH", decision)
    prior_low = _level_fact(state, "PRIOR_DAY_LOW", decision)
    asia_location = _range_location(
        price_fact,
        price,
        asia_high,
        asia_low,
        ("ABOVE_ASIA_HIGH", "INSIDE_ASIA_RANGE", "BELOW_ASIA_LOW"),
    )
    prior_location = _range_location(
        price_fact,
        price,
        prior_high,
        prior_low,
        ("ABOVE_PRIOR_HIGH", "INSIDE_PRIOR_RANGE", "BELOW_PRIOR_LOW"),
    )
    bars = _sequence(projection.get("pre_new_york_bars"))
    five_minute = _primary_five_minute_bars(bars, decision)
    high_value = _fact_number(asia_high)
    low_value = _fact_number(asia_low)
    if str(row["session_code"]) == "NEW_YORK" and five_minute is not None and high_value is not None and low_value is not None:
        asia_break = _primary_interaction_state(five_minute, high_value, low_value, "NO_BREAK")
        london_interaction = _primary_interaction_state(five_minute, high_value, low_value, "NO_COMPLETED_INTERACTION")
    else:
        asia_break = _unknown()
        london_interaction = _unknown()
    structure = _primary_structure_alignment(state, decision)
    compression = _primary_asia_compression(row, state, asia_history, decision)
    london_direction = _primary_london_direction(row, bars, decision)
    return {
        "ASIA_RANGE_LOCATION": asia_location,
        "ASIA_PREDECISION_BREAK_STATE": asia_break,
        "PRIOR_DAY_RANGE_LOCATION": prior_location,
        "STRUCTURE_15M_1H_ALIGNMENT": structure,
        "ASIA_RANGE_COMPRESSION": compression,
        "LONDON_PRE_NEW_YORK_DIRECTION": london_direction,
        "LONDON_ASIA_INTERACTION_PRE_NEW_YORK": london_interaction,
    }


def _reference_level_contexts(
    row: Mapping[str, Any],
    state: Mapping[str, Any],
    projection: Mapping[str, Any],
    asia_history: Mapping[str, Any],
    decision: datetime,
) -> dict[str, Observation]:
    price_fact = _nested(state, "market_mechanics", "xauusd_price")
    price_map = price_fact.get("value") if isinstance(price_fact.get("value"), Mapping) else {}
    price = _number(price_map.get("value")) if _fact_eligible(price_fact, decision) else None
    levels: dict[str, Mapping[str, Any]] = {}
    for raw in _sequence(state.get("levels")):
        item = _mapping(raw)
        kind = str(item.get("level_type"))
        fact = _mapping(item.get("price"))
        if kind in {"ASIA_HIGH", "ASIA_LOW", "PRIOR_DAY_HIGH", "PRIOR_DAY_LOW"} and _fact_eligible(fact, decision):
            if kind in levels:
                levels[kind] = {}
            else:
                levels[kind] = fact

    def location(high_name: str, low_name: str, labels: tuple[str, str, str]) -> Observation:
        high_fact, low_fact = levels.get(high_name, {}), levels.get(low_name, {})
        high, low = _fact_number(high_fact), _fact_number(low_fact)
        if price is None or high is None or low is None or high <= low:
            return _unknown()
        label = labels[0] if price > high else labels[2] if price < low else labels[1]
        return _combined_fact_observation(label, (price_fact, high_fact, low_fact), {"price": price, "high": high, "low": low})

    asia_location = location("ASIA_HIGH", "ASIA_LOW", ("ABOVE_ASIA_HIGH", "INSIDE_ASIA_RANGE", "BELOW_ASIA_LOW"))
    prior_location = location("PRIOR_DAY_HIGH", "PRIOR_DAY_LOW", ("ABOVE_PRIOR_HIGH", "INSIDE_PRIOR_RANGE", "BELOW_PRIOR_LOW"))
    bars = list(_sequence(projection.get("pre_new_york_bars")))
    five = _reference_five_minute_bars(bars, decision)
    asia_high, asia_low = _fact_number(levels.get("ASIA_HIGH", {})), _fact_number(levels.get("ASIA_LOW", {}))
    if row.get("session_code") == "NEW_YORK" and five is not None and asia_high is not None and asia_low is not None:
        asia_break = _reference_interaction_state(five, asia_high, asia_low, "NO_BREAK")
        london_interaction = _reference_interaction_state(five, asia_high, asia_low, "NO_COMPLETED_INTERACTION")
    else:
        asia_break = _unknown()
        london_interaction = _unknown()
    structure = _reference_structure_alignment(state, decision)
    compression = _reference_asia_compression(row, state, asia_history, decision)
    london_direction = _reference_london_direction(row, bars, decision)
    return dict(zip(LEVEL_CONTEXTS, (asia_location, asia_break, prior_location, structure, compression, london_direction, london_interaction), strict=True))


def _range_location(
    price_fact: Mapping[str, Any],
    price: float | None,
    high_fact: Mapping[str, Any],
    low_fact: Mapping[str, Any],
    labels: tuple[str, str, str],
) -> Observation:
    high, low = _fact_number(high_fact), _fact_number(low_fact)
    if price is None or high is None or low is None or high <= low:
        return _unknown()
    state = labels[0] if price > high else labels[2] if price < low else labels[1]
    return _combined_fact_observation(state, (price_fact, high_fact, low_fact), {"price": price, "high": high, "low": low})


def _level_fact(state: Mapping[str, Any], level_type: str, decision: datetime) -> Mapping[str, Any]:
    matches = []
    for raw in _sequence(state.get("levels")):
        level = _mapping(raw)
        fact = _mapping(level.get("price"))
        if level.get("level_type") == level_type and _fact_eligible(fact, decision):
            matches.append(fact)
    return matches[0] if len(matches) == 1 else {}


def _primary_structure_alignment(state: Mapping[str, Any], decision: datetime) -> Observation:
    facts: dict[str, Mapping[str, Any]] = {}
    for raw in _sequence(_nested(state, "market_structure").get("timeframes")):
        timeframe = _mapping(raw)
        if timeframe.get("timeframe") in {"15m", "1h"}:
            fact = _mapping(timeframe.get("trend_state"))
            if _fact_eligible(fact, decision):
                facts[str(timeframe["timeframe"])] = fact
    if set(facts) != {"15m", "1h"}:
        return _unknown()
    values = [str(facts[key].get("value")) for key in ("15m", "1h")]
    label = "BULLISH" if values == ["BULLISH", "BULLISH"] else "BEARISH" if values == ["BEARISH", "BEARISH"] else "MIXED"
    return _combined_fact_observation(label, (facts["15m"], facts["1h"]), {"15m": values[0], "1h": values[1]})


def _reference_structure_alignment(state: Mapping[str, Any], decision: datetime) -> Observation:
    matches = {
        str(item.get("timeframe")): _mapping(item.get("trend_state"))
        for item in (_mapping(raw) for raw in _sequence(_nested(state, "market_structure").get("timeframes")))
        if item.get("timeframe") in ("15m", "1h")
    }
    if any(name not in matches or not _fact_eligible(matches[name], decision) for name in ("15m", "1h")):
        return _unknown()
    short, long = str(matches["15m"].get("value")), str(matches["1h"].get("value"))
    if short == long == "BULLISH":
        label = "BULLISH"
    elif short == long == "BEARISH":
        label = "BEARISH"
    else:
        label = "MIXED"
    return _combined_fact_observation(label, (matches["15m"], matches["1h"]), {"15m": short, "1h": long})


def _primary_asia_compression(
    row: Mapping[str, Any], state: Mapping[str, Any], history: Mapping[str, Any], decision: datetime
) -> Observation:
    asia = _nested(state, "layers", "sessions_and_liquidity", "asia_state")
    current = _number(_mapping(asia.get("value")).get("range")) if _fact_eligible(asia, decision) else None
    prior = [
        item for item in (_mapping(raw) for raw in _sequence(history.get("rows")))
        if str(item.get("session_date")) < str(row["session_date"]) and item.get("state") == "KNOWN" and _number(item.get("range")) is not None
    ]
    by_date = {str(item["session_date"]): item for item in prior}
    selected = [by_date[key] for key in sorted(by_date)[-20:]]
    if current is None or len(selected) < 20:
        return _unknown()
    values = [float(item["range"]) for item in selected]
    q25 = _type7_quantile(values, Decimal("0.25"))
    q75 = _type7_quantile(values, Decimal("0.75"))
    label = "LOW" if current <= q25 else "HIGH" if current >= q75 else "NORMAL"
    return _calculated(label, {"current": current, "q25": q25, "q75": q75, "sources": [item.get("source_signature") for item in selected]})


def _reference_asia_compression(
    row: Mapping[str, Any], state: Mapping[str, Any], history: Mapping[str, Any], decision: datetime
) -> Observation:
    asia = _nested(state, "layers", "sessions_and_liquidity", "asia_state")
    value = asia.get("value") if isinstance(asia.get("value"), Mapping) else {}
    current = _number(value.get("range")) if _fact_eligible(asia, decision) else None
    dated: dict[str, Mapping[str, Any]] = {}
    for raw in _sequence(history.get("rows")):
        item = _mapping(raw)
        date = str(item.get("session_date"))
        if date < str(row["session_date"]) and item.get("state") == "KNOWN" and _number(item.get("range")) is not None:
            dated[date] = item
    keys = sorted(dated.keys())[-20:]
    if current is None or len(keys) != 20:
        return _unknown()
    values = np.sort(np.asarray([float(dated[key]["range"]) for key in keys], dtype=np.float64))
    q25 = _reference_type7(values, 0.25)
    q75 = _reference_type7(values, 0.75)
    label = "LOW" if current <= q25 else "HIGH" if current >= q75 else "NORMAL"
    return _calculated(label, {"current": current, "q25": q25, "q75": q75, "sources": [dated[key].get("source_signature") for key in keys]})


def _primary_london_direction(row: Mapping[str, Any], bars: Sequence[Any], decision: datetime) -> Observation:
    if row.get("session_code") != "NEW_YORK":
        return _unknown()
    normalized = _validated_minute_bars(row, bars, decision)
    if normalized is None:
        return _unknown()
    first, last = normalized[0], normalized[-1]
    displacement = Decimal(str(last["close"])) - Decimal(str(first["open"]))
    label = "UP" if displacement > Decimal("0.01") else "DOWN" if displacement < Decimal("-0.01") else "FLAT"
    return _calculated(label, {"first_id": first["record_id"], "last_id": last["record_id"], "displacement": str(displacement), "elapsed_minutes": len(normalized)})


def _reference_london_direction(row: Mapping[str, Any], bars: Sequence[Any], decision: datetime) -> Observation:
    if str(row.get("session_code")) != "NEW_YORK":
        return _unknown()
    normalized = _validated_minute_bars(row, bars, decision)
    if not normalized:
        return _unknown()
    start_price = Decimal(str(normalized[0]["open"]))
    finish_price = Decimal(str(normalized[len(normalized) - 1]["close"]))
    difference = finish_price - start_price
    sign = (difference > Decimal("0.01")) - (difference < Decimal("-0.01"))
    label = {1: "UP", -1: "DOWN", 0: "FLAT"}[sign]
    return _calculated(label, {"first_id": normalized[0]["record_id"], "last_id": normalized[-1]["record_id"], "displacement": str(difference), "elapsed_minutes": len(normalized)})


def _validated_minute_bars(
    row: Mapping[str, Any], bars: Sequence[Any], decision: datetime
) -> list[dict[str, Any]] | None:
    if not bars:
        return None
    normalized: list[dict[str, Any]] = []
    for raw in bars:
        bar = _mapping(raw)
        if not bar.get("complete") or not isinstance(bar.get("open_time"), str) or not isinstance(bar.get("close_time"), str):
            return None
        opened = _parse_time(str(bar["open_time"]))
        closed = _parse_time(str(bar["close_time"]))
        available = _parse_time(str(bar.get("available_at")))
        if closed - opened != timedelta(minutes=1) or closed > decision or available > decision:
            return None
        ohlc = _mapping(bar.get("ohlc"))
        if any(_number(ohlc.get(name)) is None for name in ("open", "high", "low", "close")):
            return None
        normalized.append({
            "open_time": opened,
            "close_time": closed,
            "open": float(ohlc["open"]),
            "high": float(ohlc["high"]),
            "low": float(ohlc["low"]),
            "close": float(ohlc["close"]),
            "record_id": str(bar.get("record_id")),
            "record_hash": str(bar.get("record_hash")),
        })
    normalized.sort(key=lambda item: (item["open_time"], item["record_id"]))
    expected_local = datetime.combine(
        datetime.fromisoformat(str(row["session_date"])).date(),
        time(8, 1),
        tzinfo=ZoneInfo("Europe/London"),
    ).astimezone(UTC)
    if normalized[0]["open_time"] != expected_local:
        return None
    if any(left["close_time"] != right["open_time"] for left, right in zip(normalized, normalized[1:])):
        return None
    return normalized


def _primary_five_minute_bars(bars: Sequence[Any], decision: datetime) -> list[dict[str, Any]] | None:
    if not bars:
        return None
    pseudo_row = {"session_date": _parse_time(str(_mapping(bars[0])["open_time"])).astimezone(ZoneInfo("Europe/London")).date().isoformat()}
    normalized = _validated_minute_bars({**pseudo_row, "session_code": "NEW_YORK"}, bars, decision)
    if normalized is None:
        return None
    grouped: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for bar in normalized:
        opened = bar["open_time"]
        aligned = opened.replace(minute=(opened.minute // 5) * 5, second=0, microsecond=0)
        grouped[aligned].append(bar)
    output = []
    for aligned in sorted(grouped):
        group = sorted(grouped[aligned], key=lambda item: item["open_time"])
        if len(group) != 5 or group[0]["open_time"] != aligned or group[-1]["close_time"] != aligned + timedelta(minutes=5):
            continue
        output.append({"close_time": group[-1]["close_time"], "high": max(item["high"] for item in group), "low": min(item["low"] for item in group), "close": group[-1]["close"], "source_hashes": [item["record_hash"] for item in group]})
    return output if output else None


def _reference_five_minute_bars(bars: Sequence[Any], decision: datetime) -> list[dict[str, Any]] | None:
    if not bars:
        return None
    first_open = _parse_time(str(_mapping(bars[0]).get("open_time")))
    row = {"session_date": first_open.astimezone(ZoneInfo("Europe/London")).date().isoformat(), "session_code": "NEW_YORK"}
    minutes = _validated_minute_bars(row, bars, decision)
    if minutes is None:
        return None
    output: list[dict[str, Any]] = []
    for index in range(len(minutes)):
        start = minutes[index]["open_time"]
        if start.minute % 5 or start.second:
            continue
        group = minutes[index : index + 5]
        if len(group) != 5 or any(left["close_time"] != right["open_time"] for left, right in zip(group, group[1:])) or group[-1]["close_time"] != start + timedelta(minutes=5):
            continue
        output.append({"close_time": group[-1]["close_time"], "high": max(item["high"] for item in group), "low": min(item["low"] for item in group), "close": group[-1]["close"], "source_hashes": [item["record_hash"] for item in group]})
    return output or None


def _primary_interaction_state(
    bars: Sequence[Mapping[str, Any]], high: float, low: float, no_interaction: str
) -> Observation:
    side_status: dict[str, tuple[datetime, str] | None] = {"ABOVE": None, "BELOW": None}
    previous_close: float | None = None
    accepted: dict[str, bool] = {"ABOVE": False, "BELOW": False}
    breached: dict[str, bool] = {"ABOVE": False, "BELOW": False}
    for bar in bars:
        close, timestamp = float(bar["close"]), bar["close_time"]
        if float(bar["high"]) > high:
            breached["ABOVE"] = True
        if float(bar["low"]) < low:
            breached["BELOW"] = True
        if previous_close is not None and previous_close > high and close > high:
            accepted["ABOVE"] = True
            side_status["ABOVE"] = (timestamp, "ACCEPTED_ABOVE")
        elif (accepted["ABOVE"] or breached["ABOVE"]) and close <= high:
            accepted["ABOVE"] = False
            side_status["ABOVE"] = (timestamp, "REJECTED_ABOVE")
        if previous_close is not None and previous_close < low and close < low:
            accepted["BELOW"] = True
            side_status["BELOW"] = (timestamp, "ACCEPTED_BELOW")
        elif (accepted["BELOW"] or breached["BELOW"]) and close >= low:
            accepted["BELOW"] = False
            side_status["BELOW"] = (timestamp, "REJECTED_BELOW")
        previous_close = close
    candidates = [item for item in side_status.values() if item is not None]
    if not candidates:
        return _calculated(no_interaction, {"bars": [bar["source_hashes"] for bar in bars], "high": high, "low": low})
    latest = max(item[0] for item in candidates)
    tied = [item for item in candidates if item[0] == latest]
    if len(tied) != 1:
        return _unknown()
    return _calculated(tied[0][1], {"completion": latest.isoformat(), "bars": [bar["source_hashes"] for bar in bars], "high": high, "low": low})


def _reference_interaction_state(
    bars: Sequence[Mapping[str, Any]], high: float, low: float, no_interaction: str
) -> Observation:
    events: list[tuple[datetime, str]] = []
    accepted_above = accepted_below = False
    breached_above = breached_below = False
    closes = [float(item["close"]) for item in bars]
    for index, bar in enumerate(bars):
        timestamp = bar["close_time"]
        breached_above = breached_above or float(bar["high"]) > high
        breached_below = breached_below or float(bar["low"]) < low
        if index > 0 and min(closes[index - 1], closes[index]) > high:
            accepted_above = True
            events.append((timestamp, "ACCEPTED_ABOVE"))
        elif (accepted_above or breached_above) and closes[index] <= high:
            accepted_above = False
            events.append((timestamp, "REJECTED_ABOVE"))
        if index > 0 and max(closes[index - 1], closes[index]) < low:
            accepted_below = True
            events.append((timestamp, "ACCEPTED_BELOW"))
        elif (accepted_below or breached_below) and closes[index] >= low:
            accepted_below = False
            events.append((timestamp, "REJECTED_BELOW"))
    if not events:
        return _calculated(no_interaction, {"bars": [bar["source_hashes"] for bar in bars], "high": high, "low": low})
    latest_time = max(event[0] for event in events)
    latest = [event for event in events if event[0] == latest_time]
    opposing = {event[1].split("_")[-1] for event in latest}
    if len(opposing) != 1:
        return _unknown()
    label = latest[-1][1]
    return _calculated(label, {"completion": latest_time.isoformat(), "bars": [bar["source_hashes"] for bar in bars], "high": high, "low": low})


def _type7_quantile(values: Sequence[float], probability: Decimal) -> float:
    ordered = sorted(Decimal(str(value)) for value in values)
    h = Decimal(len(ordered) - 1) * probability
    lower = int(h)
    fraction = h - Decimal(lower)
    return float(ordered[lower] + fraction * (ordered[min(lower + 1, len(ordered) - 1)] - ordered[lower]))


def _reference_type7(values: np.ndarray[Any, Any], probability: float) -> float:
    position = (len(values) - 1) * probability
    lower = math.floor(position)
    upper = math.ceil(position)
    return float(values[lower] + (position - lower) * (values[upper] - values[lower]))


def _decision_record(
    row: Mapping[str, Any], observations: Mapping[str, Observation], bucket_rows: int
) -> dict[str, Any]:
    if set(observations) != set(OBSERVATION_IDS):
        missing = sorted(set(OBSERVATION_IDS).difference(observations))
        extra = sorted(set(observations).difference(OBSERVATION_IDS))
        raise ValueError(f"Decision observation registry mismatch: missing={missing}, extra={extra}")
    record: dict[str, Any] = {
        "row_id": str(row["row_id"]),
        "session_date": str(row["session_date"]),
        "session_code": str(row["session_code"]),
        "decision_at_utc": str(row["decision_at_utc"]),
        "availability_disposition": str(row["availability_disposition"]),
        "expected_bucket_rows": int(row["expected_bucket_rows"]),
        "materialized_bucket_rows": int(bucket_rows),
    }
    for name in OBSERVATION_IDS:
        observation = observations[name]
        record[f"{name}__state"] = observation.state
        record[f"{name}__epistemic_status"] = observation.epistemic_status
        record[f"{name}__quality"] = observation.quality
        record[f"{name}__source_signature"] = observation.source_signature
    if tuple(record) != DECISION_COLUMNS:
        raise ValueError("Decision output schema/order differs from frozen registry")
    return record


def _complete_run_diagnostics(
    aggregate: Counter[str],
    request_diagnostics: Sequence[Mapping[str, Any]],
    bucket_hashes: Mapping[str, Any],
    decision_hashes: Mapping[str, Any],
) -> dict[str, Any]:
    total_mbo = sum(int(item["mbo_total_source_rows"]) for item in request_diagnostics)
    total_mbp = sum(int(item["mbp10_total_source_rows"]) for item in request_diagnostics)
    selected_mbo = sum(int(item["selected_mbo_rows"]) for item in request_diagnostics)
    selected_mbp = sum(int(item["selected_mbp10_rows"]) for item in request_diagnostics)
    return {
        "source_requests": int(aggregate["source_requests"]),
        "request_pairs": int(aggregate["request_pairs"]),
        "source_mbo_records_total": total_mbo,
        "source_mbp10_records_total": total_mbp,
        "selected_mbo_rows": selected_mbo,
        "selected_mbp10_rows": selected_mbp,
        "mbo_rows_allocated_by_sessions": int(aggregate["mbo_selected_rows"]),
        "mbp10_rows_allocated_by_sessions": int(aggregate["mbp10_selected_rows"]),
        "mbo_bucket_total_records": int(aggregate["mbo_rows_allocated"]),
        "mbp10_bucket_total_updates": int(aggregate["mbp10_rows_allocated"]),
        "mbo_outside_feature_windows": total_mbo - selected_mbo,
        "mbp10_outside_feature_windows": total_mbp - selected_mbp,
        "anchor_only_rows": int(aggregate["mbp10_anchor_rows"]),
        "available_sessions": int(aggregate["available_sessions"]),
        "documented_unavailable_sessions": int(aggregate["documented_unavailable_sessions"]),
        "unavailable_documented_registry_rows": int(aggregate["unavailable_documented_registry_rows"]),
        "bucket_rows": int(aggregate["bucket_rows"]),
        "london_bucket_rows": int(aggregate["london_bucket_rows"]),
        "new_york_bucket_rows": int(aggregate["new_york_bucket_rows"]),
        "timestamp_or_ordinal_regressions": int(aggregate["mbo_timestamp_or_ordinal_regressions"] + aggregate["mbp10_timestamp_or_ordinal_regressions"]),
        "publisher_mismatches": int(aggregate["mbo_publisher_mismatches"] + aggregate["mbp10_publisher_mismatches"]),
        "instrument_mismatches": int(aggregate["mbo_instrument_mismatches"] + aggregate["mbp10_instrument_mismatches"]),
        "unknown_action_rows": int(aggregate["mbo_unknown_action_rows"] + aggregate["mbp10_unknown_action_rows"]),
        "maybe_bad_book_rows": int(aggregate["mbo_maybe_bad_book_rows"] + aggregate["mbp10_maybe_bad_book_rows"]),
        "empty_level_canonical_violations": int(aggregate["empty_level_canonical_violations"]),
        "negative_size_or_count_values": int(aggregate["negative_size_or_count_values"]),
        "continuous_crossed_book_rows_intermediate": int(aggregate["continuous_crossed_book_rows"]),
        "continuous_crossed_bucket_closes": int(aggregate["continuous_crossed_bucket_closes"]),
        "anchor_not_before_window": int(aggregate["anchor_not_before_window"]),
        "selected_bad_ts_recv_rows_under_sealed_step5b2_semantics": int(aggregate["selected_bad_ts_recv_rows"]),
        "state_available_bucket_closes": int(aggregate["state_available_bucket_closes"]),
        "raw_null_classifications": {
            session: hashes["null_counts"] for session, hashes in bucket_hashes.items()
        },
        "decision_null_classifications": decision_hashes["null_counts"],
        "decision_unknown_classifications": decision_hashes.get("unknown_state_counts", {}),
        "source_rows_filtered_deduplicated_repaired_relabeled_or_substituted": 0,
        "mbo_mbp_row_alignment_attempts": 0,
        "development_outcome_columns_or_joins": 0,
        "year_2025_or_2026_value_accesses": 0,
    }


def _run_integrity(
    diagnostics: Mapping[str, Any],
    bucket_files: Mapping[str, Mapping[str, Any]],
    decision_path: Path,
    registry: Mapping[str, Any],
    base: Any,
) -> dict[str, bool]:
    return {
        "all_80_sources_and_40_pairs_processed": diagnostics["source_requests"] == 80 and diagnostics["request_pairs"] == 40,
        "exactly_374_available_and_2_documented_unavailable_sessions": diagnostics["available_sessions"] == 374 and diagnostics["documented_unavailable_sessions"] == 2 and diagnostics["unavailable_documented_registry_rows"] == 2,
        "exactly_336600_bucket_rows": diagnostics["bucket_rows"] == EXPECTED_BUCKET_ROWS,
        "exactly_168300_rows_per_session": diagnostics["london_bucket_rows"] == EXPECTED_SESSION_BUCKET_ROWS and diagnostics["new_york_bucket_rows"] == EXPECTED_SESSION_BUCKET_ROWS,
        "exactly_376_decision_rows": pq.ParquetFile(decision_path).metadata.num_rows == EXPECTED_DECISION_ROWS,
        "exact_85_column_schema_and_order": all(pq.ParquetFile(record["path"]).schema_arrow == base.FEATURE_SCHEMA for record in bucket_files.values()),
        "exact_decision_schema_and_order": pq.ParquetFile(decision_path).schema_arrow == DECISION_SCHEMA,
        "every_selected_mbo_row_allocated_once": diagnostics["selected_mbo_rows"] == diagnostics["mbo_rows_allocated_by_sessions"] == diagnostics["mbo_bucket_total_records"],
        "every_selected_mbp10_row_allocated_once": diagnostics["selected_mbp10_rows"] == diagnostics["mbp10_rows_allocated_by_sessions"] == diagnostics["mbp10_bucket_total_updates"],
        "exactly_one_anchor_per_available_session": diagnostics["anchor_only_rows"] == EXPECTED_AVAILABLE_SESSIONS and diagnostics["anchor_not_before_window"] == 0,
        "timestamp_and_source_ordinal_order_valid": diagnostics["timestamp_or_ordinal_regressions"] == 0,
        "publisher_and_per_date_instrument_mapping_exact": diagnostics["publisher_mismatches"] == 0 and diagnostics["instrument_mismatches"] == 0,
        "unknown_actions_and_maybe_bad_book_rows_zero": diagnostics["unknown_action_rows"] == 0 and diagnostics["maybe_bad_book_rows"] == 0,
        "empty_levels_canonical_and_sizes_counts_nonnegative": diagnostics["empty_level_canonical_violations"] == 0 and diagnostics["negative_size_or_count_values"] == 0,
        "continuous_matching_bucket_close_crossed_states_zero": diagnostics["continuous_crossed_bucket_closes"] == 0,
        "bad_ts_recv_rows_remain_under_sealed_step5b2_semantics": True,
        "no_filter_repair_relabel_deduplication_or_alignment": diagnostics["source_rows_filtered_deduplicated_repaired_relabeled_or_substituted"] == 0 and diagnostics["mbo_mbp_row_alignment_attempts"] == 0,
        "no_outcomes_or_holdout_values": diagnostics["development_outcome_columns_or_joins"] == 0 and diagnostics["year_2025_or_2026_value_accesses"] == 0,
        "registry_identity_count_intact": len(registry["rows"]) == EXPECTED_DECISION_ROWS and len({row["row_id"] for row in registry["rows"]}) == EXPECTED_DECISION_ROWS,
    }


def _seal(paths: RuntimePaths) -> None:
    base, _protocol, registry, _acquisition = _verified_control(paths)
    preflight_path = paths.output / "preflight.json"
    preflight = _read_json(preflight_path)
    current_tool_hash = _sha256(Path(__file__))
    if preflight.get("status") != "PASS_STEP_5C_PRE_MATERIALIZATION_READINESS" or preflight.get("tool_sha256") != current_tool_hash:
        raise ValueError("Step 5C preflight/tool binding failed")
    primary = _read_json(paths.output / "primary_summary.json")
    reference = _read_json(paths.output / "reference_summary.json")
    for run, name in ((primary, "primary"), (reference, "reference")):
        _verify_run_summary(run, name, paths, base)

    comparison_sections = (
        "bucket_hashes",
        "decision_schema_hash",
        "decision_hashes",
        "diagnostics",
        "request_diagnostics",
        "integrity_checks",
        "formal_integrity_pass",
    )
    matching = {name: primary[name] == reference[name] for name in comparison_sections}
    bucket_byte_identical = {
        session: (
            primary["bucket_files"][session]["sha256"] == reference["bucket_files"][session]["sha256"]
            and primary["bucket_files"][session]["bytes"] == reference["bucket_files"][session]["bytes"]
        )
        for session in ("LONDON", "NEW_YORK")
    }
    decision_byte_identical = (
        primary["decision_file"]["sha256"] == reference["decision_file"]["sha256"]
        and primary["decision_file"]["bytes"] == reference["decision_file"]["bytes"]
    )
    reproduction = all(matching.values()) and all(bucket_byte_identical.values()) and decision_byte_identical
    integrity = bool(primary["formal_integrity_pass"] and reference["formal_integrity_pass"])
    if not integrity:
        status = "FAIL_FEATURE_INTEGRITY"
    elif not reproduction:
        status = "FAIL_REPRODUCTION"
    else:
        status = "PASS_STEP_5C_FEATURE_MATERIALIZATION"
    formal_gates = {
        "preflight_and_predecessor_seals_pass": True,
        "primary_integrity_pass": bool(primary["formal_integrity_pass"]),
        "reference_integrity_pass": bool(reference["formal_integrity_pass"]),
        "output_schemas_identical": matching["bucket_hashes"] and matching["decision_schema_hash"],
        "row_identities_identical": primary["decision_hashes"]["column_checksums"]["row_id"] == reference["decision_hashes"]["column_checksums"]["row_id"],
        "null_classifications_identical": primary["diagnostics"]["raw_null_classifications"] == reference["diagnostics"]["raw_null_classifications"] and primary["diagnostics"]["decision_null_classifications"] == reference["diagnostics"]["decision_null_classifications"] and primary["diagnostics"]["decision_unknown_classifications"] == reference["diagnostics"]["decision_unknown_classifications"],
        "per_column_checksums_identical": all(primary["bucket_hashes"][session]["column_checksums"] == reference["bucket_hashes"][session]["column_checksums"] for session in ("LONDON", "NEW_YORK")) and primary["decision_hashes"]["column_checksums"] == reference["decision_hashes"]["column_checksums"],
        "complete_row_checksums_identical": all(primary["bucket_hashes"][session]["complete_row_checksum"] == reference["bucket_hashes"][session]["complete_row_checksum"] for session in ("LONDON", "NEW_YORK")) and primary["decision_hashes"]["complete_row_checksum"] == reference["decision_hashes"]["complete_row_checksum"],
        "technical_diagnostics_identical": matching["diagnostics"] and matching["request_diagnostics"],
        "parquet_outputs_byte_identical": all(bucket_byte_identical.values()) and decision_byte_identical,
        "exact_frozen_coverage": primary["diagnostics"]["bucket_rows"] == EXPECTED_BUCKET_ROWS and pq.ParquetFile(primary["decision_file"]["path"]).metadata.num_rows == EXPECTED_DECISION_ROWS,
        "no_prohibited_work": _no_prohibited_work(primary, reference),
    }
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_STEP_5C_FEATURE_MATERIALIZATION",
        "completed_at_utc": _now(),
        "classification": "OUTCOME_BLIND_DEVELOPMENT_FEATURE_MATERIALIZATION_ONLY",
        "prior_verdicts_and_artifacts_preserved": True,
        "formal_gates": formal_gates,
        "passed_formal_gates": sum(bool(value) for value in formal_gates.values()),
        "total_formal_gates": len(formal_gates),
        "reproduction": {
            "pass": reproduction,
            "matching_sections": matching,
            "bucket_parquet_byte_identical": bucket_byte_identical,
            "decision_parquet_byte_identical": decision_byte_identical,
        },
        "technical_counts": {
            key: value for key, value in primary["diagnostics"].items()
            if key not in {"raw_null_classifications", "decision_null_classifications", "decision_unknown_classifications"}
        },
        "raw_feature_columns": 85,
        "derived_microstructure_states": 8,
        "fundamental_contexts": 8,
        "price_level_session_contexts": 7,
        "decision_rows": EXPECTED_DECISION_ROWS,
        "bucket_rows": EXPECTED_BUCKET_ROWS,
        "development_outcomes_opened_or_joined": False,
        "year_2025_or_2026_values_accessed": False,
        "relationships_candidates_signals_execution_trades_pnl_r_or_returns_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "market_or_feature_values_reported": False,
        "completion_policy": "Step 5C complete; stop before outcome access, relationship discovery, candidate creation, execution, or Step 5D.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = paths.output / "verdict.json"
    if verdict_path.exists():
        raise FileExistsError("Refusing to overwrite Step 5C verdict")
    _write_json(verdict_path, verdict)
    report_path = paths.output / "GC_MICROSTRUCTURE_STEP_5C_REPORT.md"
    _write_text(report_path, _render_report(verdict))
    artifacts = [
        preflight_path,
        paths.output / "primary_summary.json",
        paths.output / "reference_summary.json",
        Path(primary["bucket_files"]["LONDON"]["path"]),
        Path(primary["bucket_files"]["NEW_YORK"]["path"]),
        Path(reference["bucket_files"]["LONDON"]["path"]),
        Path(reference["bucket_files"]["NEW_YORK"]["path"]),
        Path(primary["decision_file"]["path"]),
        Path(reference["decision_file"]["path"]),
        verdict_path,
        report_path,
    ]
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": _now(),
        "classification": "OUTCOME_BLIND_DEVELOPMENT_FEATURE_MATERIALIZATION_ONLY",
        "protocol": _file_record(PROTOCOL_PATH),
        "freeze": _file_record(FREEZE_PATH),
        "row_registry": _file_record(ROW_REGISTRY_PATH),
        "acquisition_manifest": _file_record(paths.acquisition),
        "step5b2_manifest": _file_record(paths.step5b2 / "manifest.json"),
        "step5b2_verdict": _file_record(paths.step5b2 / "verdict.json"),
        "base_feature_engine": _file_record(BASE_ENGINE_PATH),
        "step5c_tool": _file_record(Path(__file__)),
        "context_projection": _file_record(paths.context / "decision_context_projection.jsonl.gz"),
        "asia_history": _file_record(paths.context / "asia_range_history.json"),
        "artifacts": [_file_record(path) for path in artifacts],
        "verdict_hash": verdict["verdict_hash"],
        "source_request_count": EXPECTED_SOURCE_REQUESTS,
        "decision_rows": EXPECTED_DECISION_ROWS,
        "bucket_rows": EXPECTED_BUCKET_ROWS,
        "development_outcomes_accessed": False,
        "holdout_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json(paths.output / "manifest.json", manifest)
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5C_SEALED",
        "status": status,
        "formal_pass": verdict["formal_pass"],
        "reproduction_pass": reproduction,
        "decision_rows": EXPECTED_DECISION_ROWS,
        "bucket_rows": EXPECTED_BUCKET_ROWS,
        "manifest_hash": manifest["manifest_hash"],
        "market_or_feature_values_reported": False,
        "outcomes_accessed": False,
    }, sort_keys=True))


def _verify_run_summary(run: Mapping[str, Any], implementation: str, paths: RuntimePaths, base: Any) -> None:
    if run.get("implementation") != implementation or run.get("tool_sha256") != _sha256(Path(__file__)):
        raise ValueError("Step 5C run identity/tool binding changed")
    if run.get("protocol_sha256") != EXPECTED_PROTOCOL_SHA256 or run.get("freeze_sha256") != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 5C run protocol binding changed")
    for session in ("LONDON", "NEW_YORK"):
        record = run["bucket_files"][session]
        path = Path(record["path"])
        _verify_record(record)
        if pq.ParquetFile(path).metadata.num_rows != EXPECTED_SESSION_BUCKET_ROWS or pq.ParquetFile(path).schema_arrow != base.FEATURE_SCHEMA:
            raise ValueError("Step 5C raw bucket payload changed")
        calculated = _parquet_hashes(path, base.FEATURE_SCHEMA, EXPECTED_SESSION_BUCKET_ROWS, EXPECTED_FEATURE_SCHEMA_SHA256)
        if calculated != run["bucket_hashes"][session]:
            raise ValueError("Step 5C raw bucket checksums changed")
    _verify_record(run["decision_file"])
    decision_path = Path(run["decision_file"]["path"])
    if pq.ParquetFile(decision_path).schema_arrow != DECISION_SCHEMA:
        raise ValueError("Step 5C decision schema changed")
    calculated_decision = _parquet_hashes(decision_path, DECISION_SCHEMA, EXPECTED_DECISION_ROWS, run["decision_schema_hash"])
    if calculated_decision != run["decision_hashes"]:
        raise ValueError("Step 5C decision checksums changed")


def _no_prohibited_work(*runs: Mapping[str, Any]) -> bool:
    return all(
        not bool(run["development_outcomes_opened_or_joined"])
        and not bool(run["year_2025_or_2026_values_accessed"])
        and not bool(run["relationships_candidates_or_signals_calculated"])
        and not bool(run["execution_trades_pnl_r_or_returns_calculated"])
        and not bool(run["data_acquired"])
        and float(run["charge_incurred_usd"]) == 0.0
        and int(run["source_rows_filtered_deduplicated_repaired_relabeled_or_substituted"]) == 0
        and int(run["mbo_mbp_row_alignment_attempts"]) == 0
        for run in runs
    )


def _verify(paths: RuntimePaths) -> None:
    base, _protocol, _registry, _acquisition = _verified_control(paths)
    manifest_path = paths.output / "manifest.json"
    verdict_path = paths.output / "verdict.json"
    manifest = _read_json(manifest_path)
    verdict = _read_json(verdict_path)
    manifest_hash = manifest.get("manifest_hash")
    if manifest_hash != _canonical_hash({key: value for key, value in manifest.items() if key != "manifest_hash"}):
        raise ValueError("Step 5C manifest embedded hash failed")
    if verdict.get("verdict_hash") != _canonical_hash({key: value for key, value in verdict.items() if key != "verdict_hash"}):
        raise ValueError("Step 5C verdict embedded hash failed")
    for record in manifest["artifacts"]:
        _verify_record(record)
    for implementation in ("primary", "reference"):
        _verify_run_summary(_read_json(paths.output / f"{implementation}_summary.json"), implementation, paths, base)
    if manifest.get("status") != verdict.get("status") or manifest.get("verdict_hash") != verdict.get("verdict_hash"):
        raise ValueError("Step 5C manifest/verdict binding failed")
    if verdict.get("formal_pass") != (verdict.get("status") == "PASS_STEP_5C_FEATURE_MATERIALIZATION"):
        raise ValueError("Step 5C formal status is inconsistent")
    print(json.dumps({
        "stage": "GC_MICROSTRUCTURE_STEP_5C_VERIFIED",
        "status": verdict["status"],
        "formal_pass": verdict["formal_pass"],
        "manifest_hash": manifest_hash,
        "decision_rows": EXPECTED_DECISION_ROWS,
        "bucket_rows": EXPECTED_BUCKET_ROWS,
        "market_or_feature_values_reported": False,
        "outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }, sort_keys=True))


def _render_report(verdict: Mapping[str, Any]) -> str:
    counts = verdict["technical_counts"]
    return "\n".join([
        "# GC Microstructure Step 5C — Outcome-Blind Feature Materialization",
        "",
        "## Formal verdict",
        "",
        f"`{verdict['status']}`",
        "",
        "## Frozen coverage",
        "",
        f"- Decision rows: `{verdict['decision_rows']:,}` (`188` London and `188` New York).",
        f"- Available one-second bucket rows: `{verdict['bucket_rows']:,}`.",
        f"- Available sessions: `{counts['available_sessions']:,}`; documented unavailable Good Friday sessions: `{counts['documented_unavailable_sessions']:,}`.",
        "- Raw features: `85`; derived microstructure states: `8`; eligible fundamental contexts: `8`; eligible price/session contexts: `7`.",
        "",
        "## Integrity and reproduction",
        "",
        f"- Formal gates passed: `{verdict['passed_formal_gates']}/{verdict['total_formal_gates']}`.",
        f"- Independent reproduction: `{'PASS' if verdict['reproduction']['pass'] else 'FAIL'}`.",
        f"- Continuous-matching crossed bucket closes: `{counts['continuous_crossed_bucket_closes']:,}`.",
        f"- Source timestamp/order regressions: `{counts['timestamp_or_ordinal_regressions']:,}`.",
        f"- Publisher/instrument mismatches: `{counts['publisher_mismatches'] + counts['instrument_mismatches']:,}`.",
        f"- Unknown-action or maybe-bad-book rows: `{counts['unknown_action_rows'] + counts['maybe_bad_book_rows']:,}`.",
        "",
        "## Scope boundary",
        "",
        "No development outcome was opened or joined. No 2025 or 2026 value was accessed. No relationship, candidate, signal, execution, trade, PnL, R multiple, or return was calculated. No data was acquired and no charge was incurred.",
        "",
        "Step 5C is complete. Work stops before outcome access or conditional-edge discovery.",
        "",
    ])


def _parquet_hashes(
    path: Path, schema: pa.Schema, expected_rows: int, complete_seed: str
) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    if parquet.schema_arrow != schema or parquet.metadata.num_rows != expected_rows:
        raise ValueError(f"Parquet schema/row count changed: {path}")
    column_digests = {field.name: hashlib.sha256() for field in schema}
    null_counts = {field.name: 0 for field in schema}
    for field in schema:
        column_digests[field.name].update(field.name.encode("utf-8"))
        column_digests[field.name].update(str(field.type).encode("ascii"))
    complete = hashlib.sha256()
    complete.update(complete_seed.encode("ascii"))
    unknown_counts = Counter()
    rows = 0
    for batch in parquet.iter_batches(batch_size=900, columns=schema.names):
        pycolumns = {name: batch.column(batch.schema.get_field_index(name)).to_pylist() for name in schema.names}
        for field in schema:
            for value in pycolumns[field.name]:
                if value is None:
                    null_counts[field.name] += 1
                _update_value_hash(column_digests[field.name], value, field.type)
                if field.name.endswith("__state") and value == "UNKNOWN":
                    unknown_counts[field.name.removesuffix("__state")] += 1
        for index in range(batch.num_rows):
            for field in schema:
                _update_value_hash(complete, pycolumns[field.name][index], field.type)
        rows += batch.num_rows
    if rows != expected_rows:
        raise ValueError("Parquet checksum pass did not process expected rows")
    result = {
        "rows": rows,
        "columns": len(schema),
        "null_counts": null_counts,
        "column_checksums": {name: digest.hexdigest() for name, digest in column_digests.items()},
        "complete_row_checksum": complete.hexdigest(),
    }
    if any(name.endswith("__state") for name in schema.names):
        result["unknown_state_counts"] = {name: int(unknown_counts[name]) for name in OBSERVATION_IDS}
    return result


def _update_value_hash(digest: Any, value: Any, data_type: pa.DataType) -> None:
    if value is None:
        digest.update(b"\x00")
        return
    digest.update(b"\x01")
    if pa.types.is_string(data_type):
        encoded = str(value).encode("utf-8")
        digest.update(UINT32.pack(len(encoded)))
        digest.update(encoded)
    elif pa.types.is_boolean(data_type):
        digest.update(b"\x01" if bool(value) else b"\x00")
    else:
        digest.update(INT64.pack(int(value)))


def _schema_hash(schema: pa.Schema) -> str:
    return _canonical_hash([
        {"name": field.name, "type": str(field.type), "nullable": field.nullable}
        for field in schema
    ])


def _write_parquet_atomic(path: Path, table: pa.Table, row_group_size: int) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    if temporary.exists():
        raise FileExistsError(temporary)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=row_group_size,
    )
    os.replace(temporary, path)


def _fact_eligible(fact: Mapping[str, Any], decision: datetime) -> bool:
    if not fact or fact.get("value") is None or fact.get("epistemic_status") == "UNKNOWN" or fact.get("quality") not in {"VALID", "PARTIAL"}:
        return False
    available = fact.get("available_at")
    return isinstance(available, str) and _parse_time(available) <= decision


def _eligible_change(fact: Mapping[str, Any], decision: datetime) -> float | None:
    if not _fact_eligible(fact, decision):
        return None
    value = _mapping(fact.get("value"))
    if value.get("change_epistemic_status") == "UNKNOWN":
        return None
    return _number(value.get("absolute_change"))


def _fact_observation(
    state: str,
    fact: Mapping[str, Any],
    payload: Any,
    *,
    epistemic: str | None = None,
) -> Observation:
    if state == "UNKNOWN" or not fact:
        return _unknown()
    return Observation(
        state=state,
        epistemic_status=epistemic or str(fact.get("epistemic_status")),
        quality=str(fact.get("quality")),
        source_signature=_canonical_hash(payload),
    )


def _combined_fact_observation(
    state: str, facts: Sequence[Mapping[str, Any]], payload: Any
) -> Observation:
    if state == "UNKNOWN" or any(not fact for fact in facts):
        return _unknown()
    quality = "PARTIAL" if any(fact.get("quality") != "VALID" for fact in facts) else "VALID"
    return Observation(state, "CALCULATED", quality, _canonical_hash(payload))


def _fact_number(fact: Mapping[str, Any]) -> float | None:
    return _number(fact.get("value")) if fact else None


def _nested(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        if not isinstance(current, Mapping):
            return {}
        current = current.get(key)
    return _mapping(current)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> list[Any]:
    return list(value) if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else []


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp is prohibited: {value}")
    return parsed.astimezone(UTC)


def _json_ready(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_ready(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_ready(item) for item in value]
    if isinstance(value, datetime):
        return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, np.generic):
        return value.item()
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("Non-finite values are prohibited in sealed JSON")
    return value


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(
        json.dumps(_json_ready(value), sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(_json_ready(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


def _write_text(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")


def _file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path.resolve()), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _verify_record(record: Mapping[str, Any]) -> None:
    path = Path(str(record["path"]))
    if path.stat().st_size != int(record["bytes"]) or _sha256(path) != str(record["sha256"]):
        raise ValueError(f"Sealed artifact changed: {path}")


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
