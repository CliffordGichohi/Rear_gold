#!/usr/bin/env python3
"""Materialize GC Session Trigger Edge Discovery V1 Milestone 2.

The program is deliberately outcome blind.  It certifies the existing sealed
development sources, builds the frozen 85-column one-second feature grid,
materializes point-in-time state/context rows, detects the six preregistered
event families, and reports support counts only.  It never constructs or joins
a forward market outcome.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import json
import math
import os
import re
import sys
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.dataset as ds
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
LOCAL_ARTIFACTS = ROOT / "research_artifacts"
PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2_protocol_v01.json"
ROW_REGISTRY_PATH = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2_freeze_v01.json"
M1_FINAL_SEAL = LOCAL_ARTIFACTS / "gc_session_trigger_edge_m1_v01" / "final_seal.json"
M1_CONTRACT = MANIFESTS / "gc_session_trigger_edge_contract_v01.json"
M1_TAXONOMY = MANIFESTS / "gc_session_trigger_edge_taxonomy_v01.json"
M1_FEATURES = MANIFESTS / "gc_session_trigger_edge_feature_traceability_v01.json"
M1_STATISTICS = MANIFESTS / "gc_session_trigger_edge_statistics_v01.json"
STEP5C_ROW_REGISTRY = MANIFESTS / "gc_microstructure_step_5c_row_registry_v01.json"
STEP5C_ENGINE_PATH = ROOT / "tools" / "materialize_gc_microstructure_step5c.py"
BASE_ENGINE_PATH = ROOT / "tools" / "build_gc_microstructure_features_step4a.py"

DEFAULT_REMOTE_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_ACQUISITION = DEFAULT_REMOTE_ROOT / "data/databento_gc_microstructure_budget_c_v01/acquisition_manifest.json"
DEFAULT_STEP5B2 = DEFAULT_REMOTE_ROOT / "artifacts/step5b2_final"
DEFAULT_CONTEXT = DEFAULT_REMOTE_ROOT / "artifacts/step5c_context_input"
DEFAULT_XAU = DEFAULT_REMOTE_ROOT / "data/gold_casebook_v01/price_bars.jsonl.gz"
DEFAULT_OUTPUT = DEFAULT_REMOTE_ROOT / "artifacts/gc_session_trigger_edge_m2_v01"

EXPECTED_M1_FINAL_SEAL_SHA256 = "d2df2418ca06ef3e28ecbbe531459df659840853579ef82a9a99e26785862957"
EXPECTED_M1_STATUS = "PASS_MILESTONE_1_CONTRACT_FROZEN_CONDITIONAL_M2_READINESS"
EXPECTED_SOURCE_REQUESTS = 80
EXPECTED_SESSION_ROWS = 376
EXPECTED_AVAILABLE_SESSIONS = 374
EXPECTED_FEATURE_BUCKETS_PER_SESSION = 18_900
EXPECTED_FEATURE_ROWS = 7_068_600
EXPECTED_DECISIONS_PER_SESSION = 240
EXPECTED_DECISION_ROWS = 89_760
EXPECTED_XAU_BARS_PER_SESSION = 300
EXPECTED_XAU_TIMESTAMPS = 112_200
EXPECTED_ALLOWED_XAU_MISSING = 57
BUCKET_NS = 1_000_000_000
MINUTE_NS = 60 * BUCKET_NS

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
EVENT_FAMILIES = (
    "LEVEL_SWEEP_RECLAIM",
    "LEVEL_BREAK_ACCEPT",
    "LEVEL_FAILED_ACCEPTANCE",
    "FLOW_DEPTH_ALIGNMENT_ONSET",
    "ABSORPTION_ONSET",
    "FRAGILITY_FLOW_ONSET",
)
LEVEL_EVENT_FAMILIES = EVENT_FAMILIES[:3]

DECISION_ID_COLUMNS = (
    "decision_id",
    "session_row_id",
    "session_date",
    "session_code",
    "selected_month_week_id",
    "decision_at_utc",
    "decision_minute",
    "session_phase",
    "xau_bar_quality",
    "gc_state_quality",
)
DECISION_COLUMNS = (
    *DECISION_ID_COLUMNS,
    *(f"{name}__{field}" for name in OBSERVATION_IDS for field in OBSERVATION_FIELDS),
)
DECISION_SCHEMA = pa.schema([pa.field(name, pa.int64() if name == "decision_minute" else pa.string(), nullable=False) for name in DECISION_COLUMNS])

EVENT_COLUMNS = (
    "event_id",
    "session_date",
    "session_code",
    "selected_month_week_id",
    "event_family",
    "source_domain",
    "directional_prior",
    "decision_at_utc",
    "decision_id",
    "confirmation_evidence",
    "level_families",
    "feature_available_at_max",
    "epistemic_class",
    "quality_state",
    "lineage_hash",
    "context_states_json",
    "context_signatures_json",
)
EVENT_SCHEMA = pa.schema([pa.field(name, pa.string(), nullable=False) for name in EVENT_COLUMNS])


@dataclass(frozen=True, slots=True)
class Paths:
    acquisition: Path
    step5b2: Path
    context: Path
    xau: Path
    output: Path


@dataclass(frozen=True, slots=True)
class Bar:
    open_at: datetime
    close_at: datetime
    available_at: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    record_id: str
    record_hash: str


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def _read(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def _write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value)
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _file(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _load_module(path: Path, name: str) -> Any:
    spec = importlib.util.spec_from_file_location(name, path)
    if spec is None or spec.loader is None:
        raise ImportError(path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def _verified_control(paths: Paths, *, verify_payload_hashes: bool) -> tuple[Any, Any, dict[str, Any], dict[str, Any]]:
    for path in (PROTOCOL_PATH, ROW_REGISTRY_PATH, FREEZE_PATH, M1_FINAL_SEAL, M1_CONTRACT, M1_TAXONOMY, M1_FEATURES, M1_STATISTICS, STEP5C_ROW_REGISTRY, STEP5C_ENGINE_PATH, BASE_ENGINE_PATH):
        if not path.is_file():
            raise FileNotFoundError(path)
    freeze = _read(FREEZE_PATH)
    protocol = _read(PROTOCOL_PATH)
    registry = _read(ROW_REGISTRY_PATH)
    if _sha256(M1_FINAL_SEAL) != EXPECTED_M1_FINAL_SEAL_SHA256 or _read(M1_FINAL_SEAL).get("status") != EXPECTED_M1_STATUS:
        raise ValueError("Milestone 1 final seal failed")
    for key, path in (("protocol", PROTOCOL_PATH), ("row_registry", ROW_REGISTRY_PATH), ("implementation", Path(__file__))):
        if freeze[key]["sha256"] != _sha256(path):
            raise ValueError(f"Milestone 2 freeze binding failed: {key}")
    if protocol.get("status") != "FROZEN_BEFORE_M2_DEVELOPMENT_MARKET_VALUE_ACCESS" or freeze.get("status") != "SEALED_BEFORE_M2_DEVELOPMENT_MARKET_VALUE_ACCESS":
        raise ValueError("Milestone 2 protocol is not frozen")
    if len(registry.get("rows", [])) != EXPECTED_SESSION_ROWS:
        raise ValueError("Milestone 2 row registry changed")
    if not paths.acquisition.is_file() or not paths.xau.is_file():
        raise FileNotFoundError("Existing sealed remote source is missing")
    acquisition = _read(paths.acquisition)
    if len(acquisition.get("requests", [])) != EXPECTED_SOURCE_REQUESTS:
        raise ValueError("Expected 80 existing Databento requests")
    s5c = _load_module(STEP5C_ENGINE_PATH, "gc_trigger_m2_step5c_engine")
    base = s5c._load_base_engine()
    if tuple(protocol["feature_materialization"]["columns"]) != tuple(base.FEATURE_COLUMNS):
        raise ValueError("Frozen 85-column registry changed")
    _verify_source_inventory(acquisition, verify_payload_hashes=verify_payload_hashes)
    return s5c, base, registry, acquisition


def _verify_source_inventory(acquisition: Mapping[str, Any], *, verify_payload_hashes: bool) -> None:
    for request in acquisition["requests"]:
        normalization = _mapping(request.get("normalization"))
        for name in ("normalized_payload", "data_quality", "lineage", "seal"):
            record = _mapping(normalization.get(name))
            path = Path(str(record.get("path")))
            if not path.is_file() or path.stat().st_size != int(record.get("bytes", -1)):
                raise ValueError(f"Sealed source file missing or changed: {path}")
            if verify_payload_hashes and _sha256(path) != str(record.get("sha256")):
                raise ValueError(f"Sealed source hash failed: {path}")


def _load_contexts(paths: Paths) -> tuple[dict[str, dict[str, Any]], dict[str, Any], dict[str, Any]]:
    projection = paths.context / "decision_context_projection.jsonl.gz"
    history = paths.context / "asia_range_history.json"
    summary = paths.context / "summary.json"
    if not projection.is_file() or not history.is_file() or not summary.is_file():
        raise FileNotFoundError("Sealed Step 5C context projection is incomplete")
    contexts: dict[str, dict[str, Any]] = {}
    with gzip.open(projection, "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            contexts[str(record["row_id"])] = record
    if len(contexts) != EXPECTED_SESSION_ROWS:
        raise ValueError("Context projection row count changed")
    return contexts, _read(history), _read(summary)


def _request_map(acquisition: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for request in acquisition["requests"]:
        output[str(request["request_id"])] = request
    if len(output) != EXPECTED_SOURCE_REQUESTS:
        raise ValueError("Duplicate request identity")
    return output


def _preflight(paths: Paths) -> None:
    if paths.output.exists():
        raise FileExistsError(f"Refusing to overwrite Milestone 2 output: {paths.output}")
    s5c, base, registry, acquisition = _verified_control(paths, verify_payload_hashes=True)
    contexts, _history, context_summary = _load_contexts(paths)
    if context_summary.get("status") != "PASS_OUTCOME_BLIND_CONTEXT_PROJECTION":
        raise ValueError("Step 5C context projection did not pass")
    request_ids = {str(request["request_id"]) for request in acquisition["requests"]}
    missing_requests = sorted({str(row[key]) for row in registry["rows"] for key in ("mbo_request_id", "mbp10_request_id")} - request_ids)
    if missing_requests:
        raise ValueError(f"M2 registry source requests missing: {missing_requests}")
    counts = registry["counts"]
    gates = {
        "m1_and_m2_seals_verified": True,
        "all_80_existing_sources_hash_verified": True,
        "exact_376_session_rows": len(registry["rows"]) == EXPECTED_SESSION_ROWS,
        "exact_374_available_sessions": counts["available_session_rows"] == EXPECTED_AVAILABLE_SESSIONS,
        "exact_7068600_expected_feature_rows": counts["expected_feature_rows"] == EXPECTED_FEATURE_ROWS,
        "exact_89760_expected_decision_rows": counts["expected_minute_decision_rows"] == EXPECTED_DECISION_ROWS,
        "exact_112200_expected_xau_timestamps": counts["expected_xau_timestamps"] == EXPECTED_XAU_TIMESTAMPS,
        "all_context_rows_present": len(contexts) == EXPECTED_SESSION_ROWS,
        "xau_source_is_bound_existing_casebook_copy": paths.xau.stat().st_size == int(_mapping(_mapping(_read(FREEZE_PATH)["predecessors"]).get("casebook_price_bars")).get("bytes")),
        "no_2025_or_2026_registry_rows": all(str(row["session_date"]) < "2025-01-01" for row in registry["rows"]),
        "no_acquisition_or_charge": True,
    }
    if not all(gates.values()):
        raise ValueError(gates)
    paths.output.mkdir(parents=True, exist_ok=False)
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_PREFLIGHT_V1_0",
        "status": "PASS_M2_PRE_MATERIALIZATION_READINESS",
        "completed_at_utc": _utc_now(),
        "protocol": _file(PROTOCOL_PATH),
        "row_registry": _file(ROW_REGISTRY_PATH),
        "freeze": _file(FREEZE_PATH),
        "tool": _file(Path(__file__)),
        "base_engine": _file(BASE_ENGINE_PATH),
        "step5c_engine": _file(STEP5C_ENGINE_PATH),
        "acquisition_manifest": _file(paths.acquisition),
        "xau_source": _file(paths.xau),
        "formal_gates": gates,
        "market_values_accessed": False,
        "development_outcomes_opened_or_joined": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "feature_columns": len(base.FEATURE_COLUMNS),
        "sealed_request_count": len(acquisition["requests"]),
    }
    _write_json_exclusive(paths.output / "preflight.json", record)
    print(json.dumps({"status": record["status"], "source_requests": EXPECTED_SOURCE_REQUESTS}, sort_keys=True))


@dataclass(slots=True)
class XauSession:
    value_bars: dict[datetime, Bar]
    coverage_opens: set[datetime]
    duplicate_opens: set[datetime]
    malformed_rows: int = 0


def _allowed_xau_missing() -> set[tuple[str, str, datetime]]:
    values: list[tuple[str, str, str]] = [
        ("2021-12-13", "NEW_YORK", "2021-12-13T16:32:00Z"),
        ("2021-12-13", "NEW_YORK", "2021-12-13T16:33:00Z"),
    ]
    for minute in range(19, 28):
        values.append(("2023-03-15", "NEW_YORK", f"2023-03-15T13:{minute:02d}:00Z"))
    for minute in range(5, 41):
        values.append(("2023-08-15", "LONDON", f"2023-08-15T08:{minute:02d}:00Z"))
    for minute in range(37, 40):
        values.append(("2023-08-15", "LONDON", f"2023-08-15T09:{minute:02d}:00Z"))
    for minute in range(5, 9):
        values.append(("2023-08-15", "LONDON", f"2023-08-15T10:{minute:02d}:00Z"))
    for minute in range(48, 51):
        values.append(("2023-09-13", "NEW_YORK", f"2023-09-13T14:{minute:02d}:00Z"))
    output = {(date, session, _parse(stamp)) for date, session, stamp in values}
    if len(output) != EXPECTED_ALLOWED_XAU_MISSING:
        raise AssertionError("Frozen XAU missing-timestamp registry is not 57")
    return output


def _history_start(row: Mapping[str, Any]) -> datetime:
    opened = _parse(str(row["session_open_utc"]))
    if row["session_code"] == "LONDON":
        return opened
    local_date = datetime.fromisoformat(str(row["session_date"])).date()
    london_open = datetime.combine(local_date, time(8, 0), tzinfo=ZoneInfo("Europe/London")).astimezone(UTC)
    return min(opened, london_open)


def _load_xau(paths: Paths, rows: Sequence[Mapping[str, Any]]) -> tuple[dict[str, XauSession], dict[str, Any]]:
    intervals: list[tuple[datetime, datetime, str, datetime]] = []
    sessions: dict[str, XauSession] = {}
    session_open_by_id: dict[str, datetime] = {}
    for row in rows:
        if int(row["expected_bucket_rows"]) == 0:
            continue
        row_id = str(row["row_id"])
        start = _history_start(row)
        end = _parse(str(row["coverage_end_exclusive_utc"]))
        scan_end = _parse(str(row["trigger_scan_end_exclusive_utc"]))
        intervals.append((start, end, row_id, scan_end))
        sessions[row_id] = XauSession({}, set(), set())
        session_open_by_id[row_id] = _parse(str(row["session_open_utc"]))
    intervals.sort(key=lambda item: (item[0], item[2]))
    active: list[tuple[datetime, datetime, str, datetime]] = []
    index = 0
    source_rows = selected_metadata = selected_value_rows = 0
    first_2025_or_2026_line_deserialized = False
    saw_one_minute = False
    holdout_pattern = re.compile(r'"open_time"\s*:\s*"202(?:5|6)-')
    with gzip.open(paths.xau, "rt", encoding="utf-8") as handle:
        for line in handle:
            if holdout_pattern.search(line):
                break
            record = json.loads(line)
            timeframe = record.get("timeframe")
            if timeframe != "1m":
                if saw_one_minute:
                    break
                continue
            saw_one_minute = True
            if record.get("instrument_code") != "XAUUSD":
                continue
            source_rows += 1
            opened = _parse(str(record["open_time"]))
            closed = _parse(str(record["close_time"]))
            while index < len(intervals) and intervals[index][0] <= opened:
                active.append(intervals[index])
                index += 1
            active = [item for item in active if item[1] > opened]
            if not active:
                if index >= len(intervals):
                    break
                continue
            for start, end, row_id, scan_end in active:
                if not (start <= opened < end):
                    continue
                selected_metadata += 1
                target = sessions[row_id]
                if opened in target.coverage_opens:
                    target.duplicate_opens.add(opened)
                target.coverage_opens.add(opened)
                if closed > scan_end and opened >= session_open_by_id[row_id]:
                    continue
                timely = bool(record.get("complete")) and closed - opened == timedelta(minutes=1) and _parse(str(record["available_at"])) <= closed
                ohlc = _mapping(record.get("ohlc"))
                if not timely or any(ohlc.get(name) is None for name in ("open", "high", "low", "close")):
                    target.malformed_rows += 1
                    continue
                bar = Bar(
                    open_at=opened,
                    close_at=closed,
                    available_at=_parse(str(record["available_at"])),
                    open=Decimal(str(ohlc["open"])),
                    high=Decimal(str(ohlc["high"])),
                    low=Decimal(str(ohlc["low"])),
                    close=Decimal(str(ohlc["close"])),
                    record_id=str(record["record_id"]),
                    record_hash=str(record["record_hash"]),
                )
                target.value_bars[opened] = bar
                selected_value_rows += 1
    allowed = _allowed_xau_missing()
    missing: list[tuple[str, str, datetime]] = []
    unexpected_missing: list[tuple[str, str, datetime]] = []
    allowed_observed: list[tuple[str, str, datetime]] = []
    duplicate_count = 0
    malformed = 0
    history_missing = 0
    by_session = Counter()
    for row in rows:
        if int(row["expected_bucket_rows"]) == 0:
            continue
        row_id = str(row["row_id"])
        target = sessions[row_id]
        opened = _parse(str(row["session_open_utc"]))
        expected = {opened + timedelta(minutes=minute) for minute in range(EXPECTED_XAU_BARS_PER_SESSION)}
        absent = sorted(expected - target.coverage_opens)
        for stamp in absent:
            item = (str(row["session_date"]), str(row["session_code"]), stamp)
            missing.append(item)
            if item in allowed:
                allowed_observed.append(item)
            else:
                unexpected_missing.append(item)
        history_expected = {
            _history_start(row) + timedelta(minutes=minute)
            for minute in range(int((opened - _history_start(row)).total_seconds() // 60))
        }
        history_missing += len(history_expected - target.coverage_opens)
        duplicate_count += len(target.duplicate_opens)
        malformed += target.malformed_rows
        by_session[str(row["session_code"])] += len(expected & target.coverage_opens)
    diagnostics = {
        "source_one_minute_rows_deserialized_before_2025": source_rows,
        "selected_session_interval_metadata_emissions": selected_metadata,
        "selected_predecision_value_emissions": selected_value_rows,
        "expected_full_session_plus_60_timestamps": EXPECTED_XAU_TIMESTAMPS,
        "observed_full_session_plus_60_timestamps": EXPECTED_XAU_TIMESTAMPS - len(missing),
        "missing_full_session_plus_60_timestamps": len(missing),
        "allowed_missing_timestamps_observed": len(allowed_observed),
        "unexpected_missing_timestamps": len(unexpected_missing),
        "duplicate_timestamps": duplicate_count,
        "malformed_or_late_predecision_rows": malformed,
        "pre_new_york_history_missing_timestamps": history_missing,
        "observed_by_session": dict(sorted(by_session.items())),
        "first_2025_or_2026_line_deserialized": first_2025_or_2026_line_deserialized,
        "market_values_reported": False,
        "outcomes_constructed_or_joined": False,
    }
    return sessions, diagnostics


class FeatureWriters:
    def __init__(self, output: Path, implementation: str, schema: pa.Schema) -> None:
        self.final = {session: output / f"{implementation}_{session.lower()}_one_second_features.parquet" for session in ("LONDON", "NEW_YORK")}
        self.temp = {session: path.with_suffix(path.suffix + ".tmp") for session, path in self.final.items()}
        for path in (*self.final.values(), *self.temp.values()):
            if path.exists():
                raise FileExistsError(path)
        self.writers = {
            session: pq.ParquetWriter(path, schema, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")
            for session, path in self.temp.items()
        }

    def write(self, session: str, columns: Mapping[str, Sequence[Any]], schema: pa.Schema) -> None:
        table = pa.Table.from_pydict(dict(columns), schema=schema)
        if table.num_rows != EXPECTED_FEATURE_BUCKETS_PER_SESSION:
            raise ValueError("Feature row group is not 18,900 buckets")
        self.writers[session].write_table(table, row_group_size=EXPECTED_FEATURE_BUCKETS_PER_SESSION)

    def close(self) -> None:
        for writer in self.writers.values():
            writer.close()
        for session in self.final:
            os.replace(self.temp[session], self.final[session])


def _observation_record(observations: Mapping[str, Any], base: Mapping[str, Any]) -> dict[str, Any]:
    record = dict(base)
    if set(observations) != set(OBSERVATION_IDS):
        raise ValueError(f"Observation registry mismatch: {sorted(set(OBSERVATION_IDS) ^ set(observations))}")
    for name in OBSERVATION_IDS:
        observation = observations[name]
        record[f"{name}__state"] = str(observation.state)
        record[f"{name}__epistemic_status"] = str(observation.epistemic_status)
        record[f"{name}__quality"] = str(observation.quality)
        record[f"{name}__source_signature"] = str(observation.source_signature)
    if tuple(record) != DECISION_COLUMNS:
        raise ValueError("Decision schema/order changed")
    return record


def _slice_feature_columns(columns: Mapping[str, Sequence[Any]], end: int) -> dict[str, Sequence[Any]]:
    if end < 900 or end > EXPECTED_FEATURE_BUCKETS_PER_SESSION:
        raise ValueError("Invalid rolling-state boundary")
    return {name: values[end - 900 : end] for name, values in columns.items()}


def _minute_micro_states(s5c: Any, base: Any, columns: Mapping[str, Sequence[Any]], implementation: str) -> dict[datetime, dict[str, Any]]:
    start = datetime.fromtimestamp(int(columns["bucket_start_ns"][0]) / 1_000_000_000, UTC)
    session_open = start + timedelta(minutes=15)
    output: dict[datetime, dict[str, Any]] = {}
    s5c.WINDOW_BUCKETS = 900
    for minute in range(0, EXPECTED_DECISIONS_PER_SESSION + 1):
        decision = session_open + timedelta(minutes=minute)
        end = 900 + minute * 60
        window = _slice_feature_columns(columns, end)
        states = s5c._primary_micro_states(window, base) if implementation == "primary" else s5c._reference_micro_states(window, base)
        output[decision] = states
    s5c.WINDOW_BUCKETS = EXPECTED_FEATURE_BUCKETS_PER_SESSION
    return output


def _session_phase(decision: datetime, row: Mapping[str, Any]) -> str:
    local = decision.astimezone(ZoneInfo(str(row["session_timezone"]))).time()
    if local < time(9, 0):
        return "OPENING"
    if local < time(10, 30):
        return "MID"
    return "LATE"


def _bar_sequence(session: XauSession, start: datetime, end: datetime) -> list[Bar] | None:
    expected = [start + timedelta(minutes=index) for index in range(int((end - start).total_seconds() // 60))]
    bars = [session.value_bars.get(stamp) for stamp in expected]
    if any(bar is None for bar in bars):
        return None
    selected = [bar for bar in bars if bar is not None]
    if any(bar.open_at != stamp or bar.close_at != stamp + timedelta(minutes=1) or bar.available_at > bar.close_at for bar, stamp in zip(selected, expected, strict=True)):
        return None
    return selected


def _five_minute_bars(bars: Sequence[Bar]) -> list[dict[str, Any]]:
    grouped: dict[datetime, list[Bar]] = defaultdict(list)
    for bar in bars:
        aligned = bar.open_at.replace(minute=(bar.open_at.minute // 5) * 5, second=0, microsecond=0)
        grouped[aligned].append(bar)
    output: list[dict[str, Any]] = []
    for aligned in sorted(grouped):
        group = sorted(grouped[aligned], key=lambda item: item.open_at)
        if len(group) != 5 or group[0].open_at != aligned or group[-1].close_at != aligned + timedelta(minutes=5):
            continue
        if any(left.close_at != right.open_at for left, right in zip(group, group[1:])):
            continue
        output.append(
            {
                "close_time": group[-1].close_at,
                "high": float(max(item.high for item in group)),
                "low": float(min(item.low for item in group)),
                "close": float(group[-1].close),
                "source_hashes": [item.record_hash for item in group],
            }
        )
    return output


def _fixed_level_facts(s5c: Any, state: Mapping[str, Any], decision: datetime) -> dict[str, Mapping[str, Any]]:
    output: dict[str, Mapping[str, Any]] = {}
    for name in ("ASIA_HIGH", "ASIA_LOW", "PRIOR_DAY_HIGH", "PRIOR_DAY_LOW"):
        output[name] = s5c._level_fact(state, name, decision)
    return output


def _decimal_fact(s5c: Any, fact: Mapping[str, Any]) -> Decimal | None:
    value = s5c._fact_number(fact)
    return None if value is None else Decimal(str(value))


def _dynamic_levels(
    s5c: Any,
    row: Mapping[str, Any],
    projection: Mapping[str, Any],
    session: XauSession,
    decision: datetime,
) -> dict[str, dict[str, Any]]:
    state = _mapping(projection.get("decision_state"))
    facts = _fixed_level_facts(s5c, state, decision)
    levels: dict[str, dict[str, Any]] = {}
    asia_high, asia_low = _decimal_fact(s5c, facts["ASIA_HIGH"]), _decimal_fact(s5c, facts["ASIA_LOW"])
    prior_high, prior_low = _decimal_fact(s5c, facts["PRIOR_DAY_HIGH"]), _decimal_fact(s5c, facts["PRIOR_DAY_LOW"])
    if asia_high is not None and asia_low is not None and asia_high > asia_low:
        levels["ASIA_RANGE"] = {"upper": asia_high, "lower": asia_low, "signature": _canonical([facts["ASIA_HIGH"], facts["ASIA_LOW"]])}
    if prior_high is not None and prior_low is not None and prior_high > prior_low:
        levels["PRIOR_DAY_RANGE"] = {"upper": prior_high, "lower": prior_low, "signature": _canonical([facts["PRIOR_DAY_HIGH"], facts["PRIOR_DAY_LOW"]])}
    opened = _parse(str(row["session_open_utc"]))
    if row["session_code"] == "NEW_YORK":
        london_start = _history_start(row)
        london_bars = _bar_sequence(session, london_start, opened)
        if london_bars:
            levels["LONDON_PRE_NEW_YORK_RANGE"] = {
                "upper": max(item.high for item in london_bars),
                "lower": min(item.low for item in london_bars),
                "signature": _canonical([item.record_hash for item in london_bars]),
            }
    or_end = opened + timedelta(minutes=15)
    if decision >= or_end:
        opening = _bar_sequence(session, opened, or_end)
        if opening:
            levels["SESSION_OPENING_RANGE_15"] = {
                "upper": max(item.high for item in opening),
                "lower": min(item.low for item in opening),
                "signature": _canonical([item.record_hash for item in opening]),
            }
    return levels


def _location_observation(s5c: Any, price: Decimal | None, level: Mapping[str, Any] | None, labels: tuple[str, str, str]) -> Any:
    if price is None or level is None:
        return s5c._unknown()
    upper, lower = level.get("upper"), level.get("lower")
    if not isinstance(upper, Decimal) or not isinstance(lower, Decimal) or upper <= lower:
        return s5c._unknown()
    state = labels[0] if price > upper else labels[2] if price < lower else labels[1]
    return s5c._calculated(state, {"price_source": "DECISION_BAR_CLOSE", "level_signature": level["signature"]})


def _london_direction_observation(s5c: Any, row: Mapping[str, Any], session: XauSession) -> Any:
    if row["session_code"] != "NEW_YORK":
        return s5c._unknown()
    opened = _parse(str(row["session_open_utc"]))
    bars = _bar_sequence(session, _history_start(row), opened)
    if not bars:
        return s5c._unknown()
    displacement = bars[-1].close - bars[0].open
    state = "UP" if displacement > Decimal("0.01") else "DOWN" if displacement < Decimal("-0.01") else "FLAT"
    return s5c._calculated(state, {"first": bars[0].record_hash, "last": bars[-1].record_hash, "count": len(bars)})


def _interaction_observation(
    s5c: Any,
    implementation: str,
    bars: Sequence[Bar] | None,
    level: Mapping[str, Any] | None,
    no_interaction: str,
) -> Any:
    if not bars or level is None:
        return s5c._unknown()
    five = _five_minute_bars(bars)
    if not five:
        return s5c._unknown()
    upper, lower = float(level["upper"]), float(level["lower"])
    if implementation == "primary":
        return s5c._primary_interaction_state(five, upper, lower, no_interaction)
    return s5c._reference_interaction_state(five, upper, lower, no_interaction)


def _level_contexts(
    s5c: Any,
    implementation: str,
    row: Mapping[str, Any],
    projection: Mapping[str, Any],
    history: Mapping[str, Any],
    session: XauSession,
    decision: datetime,
) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    opened = _parse(str(row["session_open_utc"]))
    current = session.value_bars.get(decision - timedelta(minutes=1))
    price = current.close if current is not None and current.close_at == decision else None
    levels = _dynamic_levels(s5c, row, projection, session, decision)
    state = _mapping(projection.get("decision_state"))
    asia_location = _location_observation(s5c, price, levels.get("ASIA_RANGE"), ("ABOVE_ASIA_HIGH", "INSIDE_ASIA_RANGE", "BELOW_ASIA_LOW"))
    prior_location = _location_observation(s5c, price, levels.get("PRIOR_DAY_RANGE"), ("ABOVE_PRIOR_HIGH", "INSIDE_PRIOR_RANGE", "BELOW_PRIOR_LOW"))
    history_bars = _bar_sequence(session, _history_start(row), decision)
    asia_break = _interaction_observation(s5c, implementation, history_bars, levels.get("ASIA_RANGE"), "NO_BREAK")
    structure = s5c._primary_structure_alignment(state, decision) if implementation == "primary" else s5c._reference_structure_alignment(state, decision)
    compression = s5c._primary_asia_compression(row, state, history, decision) if implementation == "primary" else s5c._reference_asia_compression(row, state, history, decision)
    london_direction = _london_direction_observation(s5c, row, session)
    if row["session_code"] == "NEW_YORK":
        london_bars = _bar_sequence(session, _history_start(row), opened)
        london_interaction = _interaction_observation(s5c, implementation, london_bars, levels.get("ASIA_RANGE"), "NO_COMPLETED_INTERACTION")
    else:
        london_interaction = s5c._unknown()
    observations = {
        "ASIA_RANGE_LOCATION": asia_location,
        "ASIA_PREDECISION_BREAK_STATE": asia_break,
        "PRIOR_DAY_RANGE_LOCATION": prior_location,
        "STRUCTURE_15M_1H_ALIGNMENT": structure,
        "ASIA_RANGE_COMPRESSION": compression,
        "LONDON_PRE_NEW_YORK_DIRECTION": london_direction,
        "LONDON_ASIA_INTERACTION_PRE_NEW_YORK": london_interaction,
    }
    return observations, levels


def _decision_rows(
    s5c: Any,
    base_engine: Any,
    row: Mapping[str, Any],
    columns: Mapping[str, Sequence[Any]],
    micro: Mapping[datetime, Mapping[str, Any]],
    projection: Mapping[str, Any],
    history: Mapping[str, Any],
    session: XauSession,
    implementation: str,
) -> tuple[list[dict[str, Any]], dict[datetime, dict[str, dict[str, Any]]]]:
    opened = _parse(str(row["session_open_utc"]))
    output: list[dict[str, Any]] = []
    levels_at: dict[datetime, dict[str, dict[str, Any]]] = {}
    for minute in range(1, EXPECTED_DECISIONS_PER_SESSION + 1):
        decision = opened + timedelta(minutes=minute)
        bar = session.value_bars.get(decision - timedelta(minutes=1))
        xau_quality = "VALID" if bar is not None and bar.close_at == decision else "UNKNOWN_MISSING_OR_INVALID_BAR"
        index = 900 + minute * 60 - 1
        gc_valid = bool(columns["state_available"][index]) and bool(columns["book_two_sided"][index]) and not bool(columns["book_locked"][index]) and not bool(columns["book_crossed"][index])
        gc_quality = "VALID_CONTINUOUS_TWO_SIDED_UNCROSSED" if gc_valid else "UNKNOWN_INELIGIBLE_BUCKET_CLOSE"
        decision_projection = dict(projection)
        decision_projection["observation_end"] = row["coverage_end_exclusive_utc"]
        state = _mapping(projection.get("decision_state"))
        fundamental = s5c._primary_fundamental_contexts(state, decision_projection, decision) if implementation == "primary" else s5c._reference_fundamental_contexts(state, decision_projection, decision)
        level_observations, levels = _level_contexts(s5c, implementation, row, projection, history, session, decision)
        levels_at[decision] = levels
        observations = {**micro[decision], **fundamental, **level_observations}
        base = {
            "decision_id": f"{row['row_id']}:{minute:03d}",
            "session_row_id": str(row["row_id"]),
            "session_date": str(row["session_date"]),
            "session_code": str(row["session_code"]),
            "selected_month_week_id": str(row["selected_month_week_id"]),
            "decision_at_utc": _iso(decision),
            "decision_minute": minute,
            "session_phase": _session_phase(decision, row),
            "xau_bar_quality": xau_quality,
            "gc_state_quality": gc_quality,
        }
        output.append(_observation_record(observations, base))
    return output, levels_at


def _context_payload(decision_row: Mapping[str, Any]) -> tuple[str, str]:
    states = {name: decision_row[f"{name}__state"] for name in OBSERVATION_IDS}
    states["SESSION_PHASE"] = decision_row["session_phase"]
    signatures = {name: decision_row[f"{name}__source_signature"] for name in OBSERVATION_IDS}
    return (
        json.dumps(states, sort_keys=True, separators=(",", ":")),
        json.dumps(signatures, sort_keys=True, separators=(",", ":")),
    )


def _future_timestamp_quality(row: Mapping[str, Any], session: XauSession, decision: datetime) -> str:
    opened = _parse(str(row["session_open_utc"]))
    anchor_open = decision - timedelta(minutes=1)
    expected = {anchor_open + timedelta(minutes=index) for index in range(0, 61)}
    expected = {stamp for stamp in expected if opened <= stamp < _parse(str(row["coverage_end_exclusive_utc"]))}
    return "ELIGIBLE" if expected <= session.coverage_opens else "UNKNOWN_FORWARD_COVERAGE"


def _event_record(
    row: Mapping[str, Any],
    decision_row: Mapping[str, Any],
    family: str,
    direction: str,
    source_domain: str,
    epistemic: str,
    level_families: Sequence[str],
    evidence: Mapping[str, Any],
    quality: str,
) -> dict[str, str]:
    levels_json = json.dumps(sorted(level_families), separators=(",", ":"))
    evidence_hash = _canonical(evidence)
    event_id = _canonical([row["row_id"], family, direction, decision_row["decision_at_utc"], levels_json, evidence_hash])
    states, signatures = _context_payload(decision_row)
    record = {
        "event_id": event_id,
        "session_date": str(row["session_date"]),
        "session_code": str(row["session_code"]),
        "selected_month_week_id": str(row["selected_month_week_id"]),
        "event_family": family,
        "source_domain": source_domain,
        "directional_prior": direction,
        "decision_at_utc": str(decision_row["decision_at_utc"]),
        "decision_id": str(decision_row["decision_id"]),
        "confirmation_evidence": evidence_hash,
        "level_families": levels_json,
        "feature_available_at_max": str(decision_row["decision_at_utc"]),
        "epistemic_class": epistemic,
        "quality_state": quality,
        "lineage_hash": "",
        "context_states_json": states,
        "context_signatures_json": signatures,
    }
    record["lineage_hash"] = _canonical({**record, "lineage_hash": ""})
    return record


def _merge_and_cap_level_events(
    row: Mapping[str, Any],
    session: XauSession,
    decision_by_time: Mapping[datetime, Mapping[str, Any]],
    raw: Sequence[Mapping[str, Any]],
) -> list[dict[str, str]]:
    grouped: dict[tuple[str, str, datetime], list[Mapping[str, Any]]] = defaultdict(list)
    for item in raw:
        grouped[(str(item["family"]), str(item["direction"]), item["decision"])].append(item)
    merged: list[dict[str, str]] = []
    for (family, direction, decision), items in grouped.items():
        level_families = sorted({str(item["level_family"]) for item in items})
        evidence = {
            "family": family,
            "direction": direction,
            "decision": _iso(decision),
            "level_evidence": sorted(str(item["evidence"]) for item in items),
        }
        quality = _future_timestamp_quality(row, session, decision)
        merged.append(
            _event_record(
                row,
                decision_by_time[decision],
                family,
                direction,
                "XAUUSD_PRICE_LEVEL",
                "CALCULATED",
                level_families,
                evidence,
                quality,
            )
        )
    retained: list[dict[str, str]] = []
    for family in LEVEL_EVENT_FAMILIES:
        selected = sorted(
            (item for item in merged if item["event_family"] == family),
            key=lambda item: (item["decision_at_utc"], item["directional_prior"], item["level_families"], item["event_id"]),
        )[:3]
        retained.extend(selected)
    return sorted(retained, key=lambda item: (item["decision_at_utc"], item["event_family"], item["directional_prior"], item["event_id"]))


def _detect_level_events_primary(
    row: Mapping[str, Any],
    session: XauSession,
    decisions: Sequence[Mapping[str, Any]],
    levels_at: Mapping[datetime, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, str]]:
    decision_by_time = {_parse(str(item["decision_at_utc"])): item for item in decisions}
    emitted: set[tuple[str, str, str]] = set()
    previous: dict[str, Bar | None] = {}
    pending_accept: dict[tuple[str, str], tuple[int, str]] = {}
    raw: list[dict[str, Any]] = []
    for minute, decision_row in enumerate(decisions, start=1):
        decision = _parse(str(decision_row["decision_at_utc"]))
        bar = session.value_bars.get(decision - timedelta(minutes=1))
        current_levels = levels_at[decision]
        for level_family, level in sorted(current_levels.items()):
            prior = previous.get(level_family)
            if bar is None:
                previous[level_family] = None
                pending_accept.pop((level_family, "UPPER"), None)
                pending_accept.pop((level_family, "LOWER"), None)
                continue
            adjacent = prior is not None and prior.close_at == bar.open_at
            upper, lower = level["upper"], level["lower"]
            level_signature = str(level["signature"])
            same_upper_reclaim = bar.high > upper and bar.close <= upper
            next_upper_reclaim = adjacent and prior.high > upper and prior.close > upper and bar.close <= upper
            if (same_upper_reclaim or next_upper_reclaim) and ("LEVEL_SWEEP_RECLAIM", "DOWN", level_family) not in emitted:
                raw.append({"family": "LEVEL_SWEEP_RECLAIM", "direction": "DOWN", "level_family": level_family, "decision": decision, "evidence": _canonical([level_signature, bar.record_hash, "UPPER_RECLAIM"])})
                emitted.add(("LEVEL_SWEEP_RECLAIM", "DOWN", level_family))
            same_lower_reclaim = bar.low < lower and bar.close >= lower
            next_lower_reclaim = adjacent and prior.low < lower and prior.close < lower and bar.close >= lower
            if (same_lower_reclaim or next_lower_reclaim) and ("LEVEL_SWEEP_RECLAIM", "UP", level_family) not in emitted:
                raw.append({"family": "LEVEL_SWEEP_RECLAIM", "direction": "UP", "level_family": level_family, "decision": decision, "evidence": _canonical([level_signature, bar.record_hash, "LOWER_RECLAIM"])})
                emitted.add(("LEVEL_SWEEP_RECLAIM", "UP", level_family))

            accept_upper = adjacent and prior.close > upper and bar.close > upper
            accept_lower = adjacent and prior.close < lower and bar.close < lower
            if accept_upper:
                if ("LEVEL_BREAK_ACCEPT", "UP", level_family) not in emitted:
                    raw.append({"family": "LEVEL_BREAK_ACCEPT", "direction": "UP", "level_family": level_family, "decision": decision, "evidence": _canonical([level_signature, prior.record_hash, bar.record_hash])})
                    emitted.add(("LEVEL_BREAK_ACCEPT", "UP", level_family))
                pending_accept[(level_family, "UPPER")] = (minute, level_signature)
            if accept_lower:
                if ("LEVEL_BREAK_ACCEPT", "DOWN", level_family) not in emitted:
                    raw.append({"family": "LEVEL_BREAK_ACCEPT", "direction": "DOWN", "level_family": level_family, "decision": decision, "evidence": _canonical([level_signature, prior.record_hash, bar.record_hash])})
                    emitted.add(("LEVEL_BREAK_ACCEPT", "DOWN", level_family))
                pending_accept[(level_family, "LOWER")] = (minute, level_signature)

            upper_pending = pending_accept.get((level_family, "UPPER"))
            if upper_pending and minute > upper_pending[0]:
                elapsed = minute - upper_pending[0]
                if elapsed <= 5 and bar.close <= upper and ("LEVEL_FAILED_ACCEPTANCE", "DOWN", level_family) not in emitted:
                    raw.append({"family": "LEVEL_FAILED_ACCEPTANCE", "direction": "DOWN", "level_family": level_family, "decision": decision, "evidence": _canonical([upper_pending[1], bar.record_hash, "UPPER_FAILED"])})
                    emitted.add(("LEVEL_FAILED_ACCEPTANCE", "DOWN", level_family))
                    pending_accept.pop((level_family, "UPPER"), None)
                elif elapsed >= 5:
                    pending_accept.pop((level_family, "UPPER"), None)
            lower_pending = pending_accept.get((level_family, "LOWER"))
            if lower_pending and minute > lower_pending[0]:
                elapsed = minute - lower_pending[0]
                if elapsed <= 5 and bar.close >= lower and ("LEVEL_FAILED_ACCEPTANCE", "UP", level_family) not in emitted:
                    raw.append({"family": "LEVEL_FAILED_ACCEPTANCE", "direction": "UP", "level_family": level_family, "decision": decision, "evidence": _canonical([lower_pending[1], bar.record_hash, "LOWER_FAILED"])})
                    emitted.add(("LEVEL_FAILED_ACCEPTANCE", "UP", level_family))
                    pending_accept.pop((level_family, "LOWER"), None)
                elif elapsed >= 5:
                    pending_accept.pop((level_family, "LOWER"), None)
            previous[level_family] = bar
    return _merge_and_cap_level_events(row, session, decision_by_time, raw)


def _detect_level_events_reference(
    row: Mapping[str, Any],
    session: XauSession,
    decisions: Sequence[Mapping[str, Any]],
    levels_at: Mapping[datetime, Mapping[str, Mapping[str, Any]]],
) -> list[dict[str, str]]:
    times = [_parse(str(item["decision_at_utc"])) for item in decisions]
    decision_by_time = dict(zip(times, decisions, strict=True))
    raw: list[dict[str, Any]] = []
    level_names = sorted({name for values in levels_at.values() for name in values})
    for level_family in level_names:
        candidates: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
        accepted: dict[str, list[tuple[int, str]]] = {"UPPER": [], "LOWER": []}
        for index, decision in enumerate(times):
            level = levels_at[decision].get(level_family)
            bar = session.value_bars.get(decision - timedelta(minutes=1))
            if level is None or bar is None:
                continue
            prior_time = times[index - 1] if index else None
            prior = None if prior_time is None else session.value_bars.get(prior_time - timedelta(minutes=1))
            adjacent = prior is not None and prior.close_at == bar.open_at and level_family in levels_at[prior_time]
            upper, lower = level["upper"], level["lower"]
            signature = str(level["signature"])
            if bar.high > upper and bar.close <= upper or adjacent and prior.high > upper and prior.close > upper and bar.close <= upper:
                candidates[("LEVEL_SWEEP_RECLAIM", "DOWN")].append({"family": "LEVEL_SWEEP_RECLAIM", "direction": "DOWN", "level_family": level_family, "decision": decision, "evidence": _canonical([signature, bar.record_hash, "UPPER_RECLAIM"])})
            if bar.low < lower and bar.close >= lower or adjacent and prior.low < lower and prior.close < lower and bar.close >= lower:
                candidates[("LEVEL_SWEEP_RECLAIM", "UP")].append({"family": "LEVEL_SWEEP_RECLAIM", "direction": "UP", "level_family": level_family, "decision": decision, "evidence": _canonical([signature, bar.record_hash, "LOWER_RECLAIM"])})
            if adjacent and prior.close > upper and bar.close > upper:
                evidence = _canonical([signature, prior.record_hash, bar.record_hash])
                candidates[("LEVEL_BREAK_ACCEPT", "UP")].append({"family": "LEVEL_BREAK_ACCEPT", "direction": "UP", "level_family": level_family, "decision": decision, "evidence": evidence})
                accepted["UPPER"].append((index, evidence))
            if adjacent and prior.close < lower and bar.close < lower:
                evidence = _canonical([signature, prior.record_hash, bar.record_hash])
                candidates[("LEVEL_BREAK_ACCEPT", "DOWN")].append({"family": "LEVEL_BREAK_ACCEPT", "direction": "DOWN", "level_family": level_family, "decision": decision, "evidence": evidence})
                accepted["LOWER"].append((index, evidence))
        for side, accepts in accepted.items():
            family_direction = "DOWN" if side == "UPPER" else "UP"
            for accepted_index, accepted_evidence in accepts:
                for return_index in range(accepted_index + 1, min(accepted_index + 6, len(times))):
                    decision = times[return_index]
                    level = levels_at[decision].get(level_family)
                    bar = session.value_bars.get(decision - timedelta(minutes=1))
                    if level is None or bar is None:
                        break
                    returned = bar.close <= level["upper"] if side == "UPPER" else bar.close >= level["lower"]
                    if returned:
                        candidates[("LEVEL_FAILED_ACCEPTANCE", family_direction)].append({"family": "LEVEL_FAILED_ACCEPTANCE", "direction": family_direction, "level_family": level_family, "decision": decision, "evidence": _canonical([str(level["signature"]), bar.record_hash, "UPPER_FAILED" if side == "UPPER" else "LOWER_FAILED"])})
                        break
        for items in candidates.values():
            if items:
                raw.append(min(items, key=lambda item: (item["decision"], item["evidence"])))
    return _merge_and_cap_level_events(row, session, decision_by_time, raw)


def _detect_micro_events(
    row: Mapping[str, Any],
    session: XauSession,
    decisions: Sequence[Mapping[str, Any]],
    micro: Mapping[datetime, Mapping[str, Any]],
    implementation: str,
) -> list[dict[str, str]]:
    opened = _parse(str(row["session_open_utc"]))
    decision_by_time = {_parse(str(item["decision_at_utc"])): item for item in decisions}
    events: list[dict[str, str]] = []
    seen: set[tuple[str, str]] = set()
    minutes = range(2, EXPECTED_DECISIONS_PER_SESSION + 1) if implementation == "primary" else list(range(2, EXPECTED_DECISIONS_PER_SESSION + 1))
    for minute in minutes:
        now = opened + timedelta(minutes=minute)
        prior = opened + timedelta(minutes=minute - 1)
        antecedent = opened + timedelta(minutes=minute - 2)
        current_states, prior_states, antecedent_states = micro[now], micro[prior], micro[antecedent]
        candidates: list[tuple[str, str, Mapping[str, Any]]] = []
        for state in ("BULLISH", "BEARISH"):
            if current_states["FLOW_DEPTH_ALIGNMENT"].state == prior_states["FLOW_DEPTH_ALIGNMENT"].state == state and antecedent_states["FLOW_DEPTH_ALIGNMENT"].state != state:
                candidates.append(("FLOW_DEPTH_ALIGNMENT_ONSET", "UP" if state == "BULLISH" else "DOWN", {"states": state, "at": [_iso(antecedent), _iso(prior), _iso(now)]}))
        for state in ("BULLISH_ABSORPTION", "BEARISH_ABSORPTION"):
            if current_states["ABSORPTION_STATE_W60"].state == prior_states["ABSORPTION_STATE_W60"].state == state and antecedent_states["ABSORPTION_STATE_W60"].state != state:
                candidates.append(("ABSORPTION_ONSET", "UP" if state == "BULLISH_ABSORPTION" else "DOWN", {"states": state, "at": [_iso(antecedent), _iso(prior), _iso(now)]}))
        for flow in ("BULLISH", "BEARISH"):
            current_pair = current_states["LIQUIDITY_FRAGILITY"].state == "FRAGILE" and current_states["FLOW_PRESSURE_W60"].state == flow
            prior_pair = prior_states["LIQUIDITY_FRAGILITY"].state == "FRAGILE" and prior_states["FLOW_PRESSURE_W60"].state == flow
            antecedent_pair = antecedent_states["LIQUIDITY_FRAGILITY"].state == "FRAGILE" and antecedent_states["FLOW_PRESSURE_W60"].state == flow
            if current_pair and prior_pair and not antecedent_pair:
                candidates.append(("FRAGILITY_FLOW_ONSET", "UP" if flow == "BULLISH" else "DOWN", {"flow": flow, "fragility": "FRAGILE", "at": [_iso(antecedent), _iso(prior), _iso(now)]}))
        for family, direction, evidence in sorted(candidates):
            if (family, direction) in seen:
                continue
            decision_row = decision_by_time[now]
            if decision_row["gc_state_quality"] != "VALID_CONTINUOUS_TWO_SIDED_UNCROSSED":
                continue
            quality = _future_timestamp_quality(row, session, now)
            events.append(_event_record(row, decision_row, family, direction, "GC_MICROSTRUCTURE", "INFERRED", (), evidence, quality))
            seen.add((family, direction))
    return sorted(events, key=lambda item: (item["decision_at_utc"], item["event_family"], item["directional_prior"], item["event_id"]))


def _detect_events(
    row: Mapping[str, Any],
    session: XauSession,
    decisions: Sequence[Mapping[str, Any]],
    levels_at: Mapping[datetime, Mapping[str, Mapping[str, Any]]],
    micro: Mapping[datetime, Mapping[str, Any]],
    implementation: str,
) -> list[dict[str, str]]:
    level = _detect_level_events_primary(row, session, decisions, levels_at) if implementation == "primary" else _detect_level_events_reference(row, session, decisions, levels_at)
    micro_events = _detect_micro_events(row, session, decisions, micro, implementation)
    output = sorted([*level, *micro_events], key=lambda item: (item["decision_at_utc"], item["event_family"], item["directional_prior"], item["event_id"]))
    if any(event["event_family"] not in EVENT_FAMILIES for event in output):
        raise ValueError("Unregistered event family emitted")
    return output


def _count_group(events: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    dates = {str(item["session_date"]) for item in events}
    blocks = {str(item["selected_month_week_id"]) for item in events}
    up = [item for item in events if item["directional_prior"] == "UP"]
    down = [item for item in events if item["directional_prior"] == "DOWN"]
    years = Counter(str(item["session_date"])[:4] for item in events)
    return {
        "event_instances": len(events),
        "distinct_session_dates": len(dates),
        "distinct_month_week_blocks": len(blocks),
        "bullish_event_instances": len(up),
        "bearish_event_instances": len(down),
        "bullish_distinct_dates": len({str(item["session_date"]) for item in up}),
        "bearish_distinct_dates": len({str(item["session_date"]) for item in down}),
        "events_by_year": dict(sorted(years.items())),
    }


def _stage1_pass(counts: Mapping[str, Any]) -> bool:
    floors = _read(M1_STATISTICS)["stage_1"]["support_floors"]
    numeric = (
        "event_instances",
        "distinct_session_dates",
        "distinct_month_week_blocks",
        "bullish_event_instances",
        "bearish_event_instances",
        "bullish_distinct_dates",
        "bearish_distinct_dates",
    )
    if any(int(counts[name]) < int(floors[name]) for name in numeric):
        return False
    eligible = sum(int(counts["events_by_year"].get(year, 0)) >= int(floors["minimum_total_events_in_each_eligible_year"]) for year in ("2022", "2023", "2024"))
    return eligible >= int(floors["calendar_years"])


def _alignment_state(event: Mapping[str, Any], context: str) -> str:
    states = json.loads(str(event["context_states_json"]))
    direction = str(event["directional_prior"])
    if context == "MACRO_ENGINE_ALIGNMENT":
        value = states["MACRO_ENGINE_BIAS_STATE"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "REAL_YIELD_USD_ALIGNMENT":
        value = states["REAL_YIELD_USD_CONFIRMATION"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("GOLD_BULLISH" if direction == "UP" else "GOLD_BEARISH") else "COMPARISON"
    if context == "RECENT_RELEASE_ALIGNMENT":
        value = states["RECENT_RELEASE_SURPRISE_DIRECTION"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "STRUCTURE_15M_1H_ALIGNMENT":
        value = states["STRUCTURE_15M_1H_ALIGNMENT"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "FLOW_DEPTH_CONFIRMATION_FOR_LEVEL_EVENTS_ONLY":
        value = states["FLOW_DEPTH_ALIGNMENT"]
        if value in {"UNKNOWN", "NEUTRAL_OR_UNKNOWN"}:
            return "UNKNOWN"
        return "CONDITION" if value == ("BULLISH" if direction == "UP" else "BEARISH") else "COMPARISON"
    if context == "LIQUIDITY_FRAGILITY_FOR_LEVEL_EVENTS_ONLY":
        value = states["LIQUIDITY_FRAGILITY"]
        if value == "UNKNOWN":
            return "UNKNOWN"
        return "CONDITION" if value == "FRAGILE" else "COMPARISON"
    raise KeyError(context)


def _stage2_pass(condition: Mapping[str, Any], comparison: Mapping[str, Any]) -> bool:
    floors = _read(M1_STATISTICS)["stage_2"]["support_floors"]
    checks = {
        "condition_event_instances": condition["event_instances"],
        "condition_distinct_dates": condition["distinct_session_dates"],
        "condition_distinct_month_week_blocks": condition["distinct_month_week_blocks"],
        "comparison_event_instances": comparison["event_instances"],
        "comparison_distinct_dates": comparison["distinct_session_dates"],
        "comparison_distinct_month_week_blocks": comparison["distinct_month_week_blocks"],
        "condition_bullish_distinct_dates": condition["bullish_distinct_dates"],
        "condition_bearish_distinct_dates": condition["bearish_distinct_dates"],
        "comparison_bullish_distinct_dates": comparison["bullish_distinct_dates"],
        "comparison_bearish_distinct_dates": comparison["bearish_distinct_dates"],
    }
    if any(int(value) < int(floors[name]) for name, value in checks.items()):
        return False
    eligible = sum(int(condition["events_by_year"].get(year, 0)) >= int(floors["minimum_condition_dates_per_eligible_year"]) for year in ("2022", "2023", "2024"))
    return eligible >= int(floors["calendar_years"])


def _support_report(events: Sequence[Mapping[str, Any]], implementation: str) -> dict[str, Any]:
    report: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_SUPPORT_V1_0",
        "implementation": implementation,
        "classification": "OUTCOME_BLIND_SUPPORT_COUNTS_ONLY",
        "stage1": [],
        "stage2": [],
        "quality_counts": dict(sorted(Counter(str(item["quality_state"]) for item in events).items())),
        "event_rows_total": len(events),
        "eligible_event_rows": sum(item["quality_state"] == "ELIGIBLE" for item in events),
    }
    eligible = [item for item in events if item["quality_state"] == "ELIGIBLE"]
    for session in ("LONDON", "NEW_YORK"):
        for family in EVENT_FAMILIES:
            selected = [item for item in eligible if item["session_code"] == session and item["event_family"] == family]
            counts = _count_group(selected)
            report["stage1"].append({"test_id": f"S1:{session}:{family}", "session": session, "event_family": family, "counts": counts, "support_status": "SUPPORT_ELIGIBLE" if _stage1_pass(counts) else "SUPPORT_FAIL"})
        contexts_all = ("MACRO_ENGINE_ALIGNMENT", "REAL_YIELD_USD_ALIGNMENT", "RECENT_RELEASE_ALIGNMENT", "STRUCTURE_15M_1H_ALIGNMENT")
        contexts_level = ("FLOW_DEPTH_CONFIRMATION_FOR_LEVEL_EVENTS_ONLY", "LIQUIDITY_FRAGILITY_FOR_LEVEL_EVENTS_ONLY")
        for family in EVENT_FAMILIES:
            contexts = (*contexts_all, *(contexts_level if family in LEVEL_EVENT_FAMILIES else ()))
            base = [item for item in eligible if item["session_code"] == session and item["event_family"] == family]
            for context in contexts:
                classified = [(item, _alignment_state(item, context)) for item in base]
                condition_events = [item for item, state in classified if state == "CONDITION"]
                comparison_events = [item for item, state in classified if state == "COMPARISON"]
                condition, comparison = _count_group(condition_events), _count_group(comparison_events)
                report["stage2"].append(
                    {
                        "test_id": f"S2:{session}:{family}:{context}",
                        "session": session,
                        "event_family": family,
                        "context": context,
                        "condition_counts": condition,
                        "comparison_counts": comparison,
                        "unknown_context_events": sum(state == "UNKNOWN" for _, state in classified),
                        "support_status": "SUPPORT_ELIGIBLE" if _stage2_pass(condition, comparison) else "SUPPORT_FAIL",
                    }
                )
    report["stage1_support_eligible"] = sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in report["stage1"])
    report["stage2_support_eligible"] = sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in report["stage2"])
    report["stage1_tests"] = len(report["stage1"])
    report["stage2_tests"] = len(report["stage2"])
    report["relationships_hit_rates_effects_candidates_or_outcomes_calculated"] = False
    report["year_2025_or_2026_values_accessed"] = False
    report["support_receipt"] = _canonical({**report, "support_receipt": None})
    return report


class RowWriter:
    def __init__(self, path: Path, schema: pa.Schema, row_group_size: int) -> None:
        self.final = path
        self.temp = path.with_suffix(path.suffix + ".tmp")
        if self.final.exists() or self.temp.exists():
            raise FileExistsError(path)
        self.writer = pq.ParquetWriter(self.temp, schema, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6")
        self.schema = schema
        self.row_group_size = row_group_size
        self.rows = 0

    def write(self, rows: Sequence[Mapping[str, Any]]) -> None:
        if not rows:
            return
        table = pa.Table.from_pylist(list(rows), schema=self.schema)
        self.writer.write_table(table, row_group_size=self.row_group_size)
        self.rows += table.num_rows

    def close(self) -> None:
        self.writer.close()
        os.replace(self.temp, self.final)


def _source_table(path: Path, columns: Sequence[str], start_ns: int, end_ns: int, s5c: Any) -> pa.Table:
    return s5c._read_exact_ranges(path, columns, [(start_ns, end_ns)])


def _materialize(paths: Paths) -> None:
    preflight_path = paths.output / "preflight.json"
    if not preflight_path.is_file() or _read(preflight_path).get("status") != "PASS_M2_PRE_MATERIALIZATION_READINESS":
        raise ValueError("Matching M2 preflight required")
    s5c, base, registry, acquisition = _verified_control(paths, verify_payload_hashes=False)
    contexts, history, _context_summary = _load_contexts(paths)
    rows = list(registry["rows"])
    xau_sessions, xau_diagnostics = _load_xau(paths, rows)
    request_by_id = _request_map(acquisition)
    feature_writers = {name: FeatureWriters(paths.output, name, base.FEATURE_SCHEMA) for name in ("primary", "reference")}
    decision_writers = {name: RowWriter(paths.output / f"{name}_minute_contexts.parquet", DECISION_SCHEMA, EXPECTED_DECISIONS_PER_SESSION) for name in ("primary", "reference")}
    all_events: dict[str, list[dict[str, str]]] = {"primary": [], "reference": []}
    aggregate: dict[str, Counter[str]] = {"primary": Counter(), "reference": Counter()}
    per_session_diagnostics: list[dict[str, Any]] = []
    decision_mismatch_rows = event_mismatch_sessions = 0
    available_index = 0
    for row in rows:
        if int(row["expected_bucket_rows"]) == 0:
            aggregate["primary"]["documented_unavailable_sessions"] += 1
            aggregate["reference"]["documented_unavailable_sessions"] += 1
            continue
        available_index += 1
        mbo_request = request_by_id[str(row["mbo_request_id"])]
        mbp_request = request_by_id[str(row["mbp10_request_id"])]
        mbo_path = Path(str(mbo_request["normalization"]["normalized_payload"]["path"]))
        mbp_path = Path(str(mbp_request["normalization"]["normalized_payload"]["path"]))
        start_ns, end_ns = int(row["window_start_inclusive_ns"]), int(row["window_end_exclusive_ns"])
        mbo_table = _source_table(mbo_path, base.MBO_COLUMNS, start_ns, end_ns, s5c)
        mbp_table = _source_table(mbp_path, base.MBP_COLUMNS, start_ns, end_ns, s5c)
        mbo_arrays = s5c._table_arrays(mbo_table, base.MBO_COLUMNS)
        mbp_arrays = s5c._table_arrays(mbp_table, base.MBP_COLUMNS)
        s5c._assert_source_order(mbo_arrays, "MBO", str(row["row_id"]))
        s5c._assert_source_order(mbp_arrays, "MBP-10", str(row["row_id"]))
        anchor = s5c._read_exact_anchor(mbp_path, base.MBP_COLUMNS, start_ns, int(row["utc_day_start_ns"]))
        s5c.WINDOW_BUCKETS = EXPECTED_FEATURE_BUCKETS_PER_SESSION
        primary_columns, primary_technical = s5c._primary_window_features(row, mbo_arrays, mbp_arrays, anchor, base)
        reference_columns, reference_technical = s5c._reference_window_features(row, mbo_arrays, mbp_arrays, anchor, base)
        feature_writers["primary"].write(str(row["session_code"]), primary_columns, base.FEATURE_SCHEMA)
        feature_writers["reference"].write(str(row["session_code"]), reference_columns, base.FEATURE_SCHEMA)
        primary_micro = _minute_micro_states(s5c, base, primary_columns, "primary")
        reference_micro = _minute_micro_states(s5c, base, reference_columns, "reference")
        context = contexts[str(row["source_step5c_row_id"])]
        session = xau_sessions[str(row["row_id"])]
        primary_decisions, primary_levels = _decision_rows(s5c, base, row, primary_columns, primary_micro, context, history, session, "primary")
        reference_decisions, reference_levels = _decision_rows(s5c, base, row, reference_columns, reference_micro, context, history, session, "reference")
        decision_writers["primary"].write(primary_decisions)
        decision_writers["reference"].write(reference_decisions)
        if _canonical(primary_decisions) != _canonical(reference_decisions):
            decision_mismatch_rows += 1
        primary_events = _detect_events(row, session, primary_decisions, primary_levels, primary_micro, "primary")
        reference_events = _detect_events(row, session, reference_decisions, reference_levels, reference_micro, "reference")
        all_events["primary"].extend(primary_events)
        all_events["reference"].extend(reference_events)
        if _canonical(primary_events) != _canonical(reference_events):
            event_mismatch_sessions += 1
        aggregate["primary"].update(primary_technical)
        aggregate["reference"].update(reference_technical)
        per_session_diagnostics.append(
            {
                "row_id": row["row_id"],
                "mbo_rows": mbo_table.num_rows,
                "mbp10_rows": mbp_table.num_rows,
                "anchor_rows": anchor.num_rows,
                "primary_event_rows": len(primary_events),
                "reference_event_rows": len(reference_events),
                "decision_reproduction": _canonical(primary_decisions) == _canonical(reference_decisions),
                "event_reproduction": _canonical(primary_events) == _canonical(reference_events),
                "market_values_reported": False,
            }
        )
        print(json.dumps({"stage": "GC_TRIGGER_M2_SESSION_COMPLETE", "completed": available_index, "total": EXPECTED_AVAILABLE_SESSIONS, "row_id": row["row_id"], "events": len(primary_events), "outcomes": False}, sort_keys=True), flush=True)
    for writer in feature_writers.values():
        writer.close()
    for writer in decision_writers.values():
        writer.close()
    if any(writer.rows != EXPECTED_DECISION_ROWS for writer in decision_writers.values()):
        raise ValueError("Minute context output is not 89,760 rows")
    event_files: dict[str, Path] = {}
    support_files: dict[str, Path] = {}
    for implementation in ("primary", "reference"):
        events = sorted(all_events[implementation], key=lambda item: (item["session_date"], item["session_code"], item["decision_at_utc"], item["event_family"], item["directional_prior"], item["event_id"]))
        event_path = paths.output / f"{implementation}_events.parquet"
        table = pa.Table.from_pylist(events, schema=EVENT_SCHEMA)
        pq.write_table(table, event_path, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=max(1, len(events)))
        event_files[implementation] = event_path
        support = _support_report(events, implementation)
        support_path = paths.output / f"{implementation}_support_counts.json"
        _write_json_exclusive(support_path, support)
        support_files[implementation] = support_path
    diagnostics = {
        "xau": xau_diagnostics,
        "available_sessions": available_index,
        "documented_unavailable_sessions": EXPECTED_SESSION_ROWS - available_index,
        "decision_reproduction_mismatch_sessions": decision_mismatch_rows,
        "event_reproduction_mismatch_sessions": event_mismatch_sessions,
        "primary_technical": dict(sorted(aggregate["primary"].items())),
        "reference_technical": dict(sorted(aggregate["reference"].items())),
        "session_diagnostics_receipt": _canonical(per_session_diagnostics),
        "session_diagnostic_rows": len(per_session_diagnostics),
    }
    _write_json_exclusive(paths.output / "technical_diagnostics.json", diagnostics)
    for implementation in ("primary", "reference"):
        summary = {
            "version": "GC_SESSION_TRIGGER_EDGE_M2_RUN_V1_0",
            "implementation": implementation,
            "status": "PASS_IMPLEMENTATION" if not (decision_mismatch_rows or event_mismatch_sessions) else "FAIL_REPRODUCTION_DURING_RUN",
            "completed_at_utc": _utc_now(),
            "feature_files": {session: _file(feature_writers[implementation].final[session]) for session in ("LONDON", "NEW_YORK")},
            "decision_file": _file(decision_writers[implementation].final),
            "event_file": _file(event_files[implementation]),
            "support_file": _file(support_files[implementation]),
            "technical_diagnostics": _file(paths.output / "technical_diagnostics.json"),
            "feature_rows": EXPECTED_FEATURE_ROWS,
            "decision_rows": EXPECTED_DECISION_ROWS,
            "event_rows": len(all_events[implementation]),
            "development_outcomes_opened_or_joined": False,
            "relationships_hit_rates_effects_candidates_execution_trades_pnl_r_or_returns_calculated": False,
            "year_2025_or_2026_values_accessed": False,
            "data_acquired": False,
            "charge_incurred_usd": 0.0,
            "market_or_feature_values_reported": False,
        }
        _write_json_exclusive(paths.output / f"{implementation}_summary.json", summary)
    print(json.dumps({"status": "M2_MATERIALIZATION_COMPLETE_PENDING_SEAL", "sessions": available_index, "feature_rows": EXPECTED_FEATURE_ROWS, "decision_rows": EXPECTED_DECISION_ROWS, "events": len(all_events["primary"]), "outcomes": False}, sort_keys=True))


def _normalized_support(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output.pop("implementation", None)
    output.pop("support_receipt", None)
    return output


def _parquet_fingerprint(s5c: Any, path: Path, schema: pa.Schema, expected_rows: int) -> dict[str, Any]:
    return s5c._parquet_hashes(path, schema, expected_rows, s5c._schema_hash(schema))


def _event_count_table(support: Mapping[str, Any]) -> list[dict[str, Any]]:
    output = []
    for item in support["stage1"]:
        counts = item["counts"]
        output.append(
            {
                "session": item["session"],
                "event_family": item["event_family"],
                "events": counts["event_instances"],
                "up": counts["bullish_event_instances"],
                "down": counts["bearish_event_instances"],
                "dates": counts["distinct_session_dates"],
                "blocks": counts["distinct_month_week_blocks"],
                "support_status": item["support_status"],
            }
        )
    return output


def _render_report(verdict: Mapping[str, Any], support: Mapping[str, Any]) -> str:
    lines = [
        "# GC Session Trigger Edge Discovery V1 — Milestone 2",
        "",
        f"Formal status: `{verdict['status']}`",
        "",
        "## Scope completed",
        "",
        "- Existing sealed 2021-11-08 through 2024-12-13 development sources only.",
        "- Full London and New York trigger sessions plus a sixty-minute timestamp tail were certified.",
        "- The unchanged 85 one-second features, eight derived states, point-in-time contexts, and six frozen event families were independently materialized.",
        "- Forward outcomes remained unopened and unjoined. No relationship, hit rate, effect, candidate, execution, trade, PnL, R multiple, or return was calculated.",
        "",
        "## Technical coverage",
        "",
        f"- Available session rows: {verdict['technical_counts']['available_sessions']:,}",
        f"- One-second feature rows: {verdict['technical_counts']['feature_rows']:,}",
        f"- Minute context rows: {verdict['technical_counts']['decision_rows']:,}",
        f"- Expected XAUUSD full-session/+60 timestamps: {verdict['technical_counts']['xau_expected_timestamps']:,}",
        f"- Documented missing XAUUSD timestamps: {verdict['technical_counts']['xau_allowed_missing_timestamps']:,}",
        f"- Unexpected missing XAUUSD timestamps: {verdict['technical_counts']['xau_unexpected_missing_timestamps']:,}",
        "",
        "## Outcome-blind event support",
        "",
        "| Session | Event family | Events | Up | Down | Dates | Blocks | Support |",
        "|---|---|---:|---:|---:|---:|---:|---|",
    ]
    for item in _event_count_table(support):
        lines.append(f"| {item['session']} | {item['event_family']} | {item['events']} | {item['up']} | {item['down']} | {item['dates']} | {item['blocks']} | {item['support_status']} |")
    lines.extend(
        [
            "",
            f"Stage-1 support-eligible tests: {support['stage1_support_eligible']} of {support['stage1_tests']}.",
            f"Stage-2 support-eligible tests: {support['stage2_support_eligible']} of {support['stage2_tests']}.",
            "",
            "These are incidence and coverage counts only. They say whether a later test is feasible; they do not say whether any event predicts gold.",
            "",
            "## Disposition",
            "",
            verdict["completion_policy"],
            "",
        ]
    )
    return "\n".join(lines)


def _seal(paths: Paths) -> None:
    s5c, base, registry, acquisition = _verified_control(paths, verify_payload_hashes=False)
    preflight = _read(paths.output / "preflight.json")
    primary = _read(paths.output / "primary_summary.json")
    reference = _read(paths.output / "reference_summary.json")
    diagnostics = _read(paths.output / "technical_diagnostics.json")
    primary_support = _read(paths.output / "primary_support_counts.json")
    reference_support = _read(paths.output / "reference_support_counts.json")
    feature_rows_per_session = EXPECTED_FEATURE_ROWS // 2
    feature_fingerprints: dict[str, dict[str, Any]] = {"primary": {}, "reference": {}}
    for implementation, summary in (("primary", primary), ("reference", reference)):
        for session in ("LONDON", "NEW_YORK"):
            path = Path(summary["feature_files"][session]["path"])
            if pq.ParquetFile(path).metadata.num_rows != feature_rows_per_session or pq.ParquetFile(path).schema_arrow != base.FEATURE_SCHEMA:
                raise ValueError(f"Feature output schema/count failed: {implementation}/{session}")
            feature_fingerprints[implementation][session] = _parquet_fingerprint(s5c, path, base.FEATURE_SCHEMA, feature_rows_per_session)
    decision_fingerprints = {
        implementation: _parquet_fingerprint(s5c, Path(summary["decision_file"]["path"]), DECISION_SCHEMA, EXPECTED_DECISION_ROWS)
        for implementation, summary in (("primary", primary), ("reference", reference))
    }
    event_rows = primary["event_rows"]
    if reference["event_rows"] != event_rows:
        event_count_match = False
    else:
        event_count_match = True
    event_fingerprints = {
        implementation: _parquet_fingerprint(s5c, Path(summary["event_file"]["path"]), EVENT_SCHEMA, int(summary["event_rows"]))
        for implementation, summary in (("primary", primary), ("reference", reference))
    }
    primary_technical = diagnostics["primary_technical"]
    reference_technical = diagnostics["reference_technical"]
    xau = diagnostics["xau"]
    feature_integrity = (
        primary_technical == reference_technical
        and int(primary_technical.get("bucket_rows", 0)) == EXPECTED_FEATURE_ROWS
        and int(primary_technical.get("continuous_crossed_bucket_closes", 0)) == 0
        and int(primary_technical.get("mbo_timestamp_or_ordinal_regressions", 0)) == 0
        and int(primary_technical.get("mbp10_timestamp_or_ordinal_regressions", 0)) == 0
        and int(primary_technical.get("mbo_publisher_mismatches", 0)) == 0
        and int(primary_technical.get("mbp10_publisher_mismatches", 0)) == 0
        and int(primary_technical.get("mbo_instrument_mismatches", 0)) == 0
        and int(primary_technical.get("mbp10_instrument_mismatches", 0)) == 0
        and int(primary_technical.get("mbo_unknown_action_rows", 0)) == 0
        and int(primary_technical.get("mbp10_unknown_action_rows", 0)) == 0
        and int(primary_technical.get("mbo_maybe_bad_book_rows", 0)) == 0
        and int(primary_technical.get("mbp10_maybe_bad_book_rows", 0)) == 0
        and int(primary_technical.get("anchor_not_before_window", 0)) == 0
    )
    timestamp_coverage = (
        xau["expected_full_session_plus_60_timestamps"] == EXPECTED_XAU_TIMESTAMPS
        and xau["missing_full_session_plus_60_timestamps"] == EXPECTED_ALLOWED_XAU_MISSING
        and xau["allowed_missing_timestamps_observed"] == EXPECTED_ALLOWED_XAU_MISSING
        and xau["unexpected_missing_timestamps"] == 0
        and xau["duplicate_timestamps"] == 0
        and xau["malformed_or_late_predecision_rows"] == 0
        and not xau["first_2025_or_2026_line_deserialized"]
    )
    feature_reproduction = all(
        feature_fingerprints["primary"][session] == feature_fingerprints["reference"][session]
        and primary["feature_files"][session]["sha256"] == reference["feature_files"][session]["sha256"]
        for session in ("LONDON", "NEW_YORK")
    )
    decision_reproduction = decision_fingerprints["primary"] == decision_fingerprints["reference"] and primary["decision_file"]["sha256"] == reference["decision_file"]["sha256"]
    event_reproduction = event_count_match and event_fingerprints["primary"] == event_fingerprints["reference"] and primary["event_file"]["sha256"] == reference["event_file"]["sha256"]
    support_reproduction = _normalized_support(primary_support) == _normalized_support(reference_support)
    reproduction = feature_reproduction and decision_reproduction and event_reproduction and support_reproduction and diagnostics["decision_reproduction_mismatch_sessions"] == 0 and diagnostics["event_reproduction_mismatch_sessions"] == 0
    predecessor_pass = preflight.get("status") == "PASS_M2_PRE_MATERIALIZATION_READINESS" and all(preflight["formal_gates"].values())
    event_family_values = set(
        pq.read_table(Path(primary["event_file"]["path"]), columns=["event_family"])
        .column("event_family")
        .to_pylist()
    )
    event_context_integrity = (
        primary_support["stage1_tests"] == 12
        and primary_support["stage2_tests"] == 60
        and event_family_values <= set(EVENT_FAMILIES)
        and int(primary["decision_rows"]) == EXPECTED_DECISION_ROWS
    )
    if not predecessor_pass:
        status = "FAIL_PREDECESSOR_OR_SOURCE_SEAL"
    elif not timestamp_coverage:
        status = "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE"
    elif not feature_integrity:
        status = "FAIL_FEATURE_INTEGRITY"
    elif not event_context_integrity:
        status = "FAIL_EVENT_OR_CONTEXT_INTEGRITY"
    elif not reproduction:
        status = "FAIL_REPRODUCTION"
    else:
        status = "PASS_MILESTONE_2_OUTCOME_BLIND_SUPPORT_MATERIALIZATION"
    gates = {
        "predecessor_and_source_seals_pass": predecessor_pass,
        "full_session_plus_60_timestamp_coverage_pass": timestamp_coverage,
        "feature_integrity_pass": feature_integrity,
        "event_and_context_integrity_pass": event_context_integrity,
        "primary_reference_feature_reproduction": feature_reproduction,
        "primary_reference_decision_reproduction": decision_reproduction,
        "primary_reference_event_reproduction": event_reproduction,
        "primary_reference_support_reproduction": support_reproduction,
        "no_outcome_relationship_candidate_execution_or_performance_work": True,
        "no_2025_or_2026_value_access": True,
        "no_acquisition_or_charge": True,
    }
    verdict: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_VERDICT_V1_0",
        "status": status,
        "formal_pass": status == "PASS_MILESTONE_2_OUTCOME_BLIND_SUPPORT_MATERIALIZATION",
        "completed_at_utc": _utc_now(),
        "classification": "OUTCOME_BLIND_TRIGGER_SUPPORT_AND_TECHNICAL_MATERIALIZATION",
        "formal_gates": gates,
        "technical_counts": {
            "available_sessions": EXPECTED_AVAILABLE_SESSIONS,
            "feature_rows": EXPECTED_FEATURE_ROWS,
            "decision_rows": EXPECTED_DECISION_ROWS,
            "event_rows": event_rows,
            "xau_expected_timestamps": EXPECTED_XAU_TIMESTAMPS,
            "xau_allowed_missing_timestamps": xau["allowed_missing_timestamps_observed"],
            "xau_unexpected_missing_timestamps": xau["unexpected_missing_timestamps"],
            "stage1_tests": primary_support["stage1_tests"],
            "stage1_support_eligible": primary_support["stage1_support_eligible"],
            "stage2_tests": primary_support["stage2_tests"],
            "stage2_support_eligible": primary_support["stage2_support_eligible"],
        },
        "reproduction": {
            "feature_fingerprints": feature_reproduction,
            "decision_fingerprints": decision_reproduction,
            "event_fingerprints": event_reproduction,
            "support_counts": support_reproduction,
        },
        "development_outcomes_opened_or_joined": False,
        "relationships_hit_rates_effects_pvalues_candidates_or_rankings_calculated": False,
        "execution_trades_pnl_r_multiples_or_returns_calculated": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "market_or_feature_values_reported": False,
        "completion_policy": "Milestone 2 complete. Stop before opening development outcomes or beginning Milestone 3; a new explicit authorization and an exact support-qualified test freeze are required.",
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = _canonical({**verdict, "verdict_receipt": None})
    verdict_path = paths.output / "verdict.json"
    _write_json_exclusive(verdict_path, verdict)
    report_path = paths.output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_2.md"
    _write_text_exclusive(report_path, _render_report(verdict, primary_support))
    artifact_paths = [
        paths.output / "preflight.json",
        paths.output / "technical_diagnostics.json",
        paths.output / "primary_summary.json",
        paths.output / "reference_summary.json",
        paths.output / "primary_support_counts.json",
        paths.output / "reference_support_counts.json",
        Path(primary["feature_files"]["LONDON"]["path"]),
        Path(primary["feature_files"]["NEW_YORK"]["path"]),
        Path(reference["feature_files"]["LONDON"]["path"]),
        Path(reference["feature_files"]["NEW_YORK"]["path"]),
        Path(primary["decision_file"]["path"]),
        Path(reference["decision_file"]["path"]),
        Path(primary["event_file"]["path"]),
        Path(reference["event_file"]["path"]),
        verdict_path,
        report_path,
    ]
    manifest: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_MANIFEST_V1_0",
        "status": status,
        "sealed_at_utc": _utc_now(),
        "protocol": _file(PROTOCOL_PATH),
        "row_registry": _file(ROW_REGISTRY_PATH),
        "freeze": _file(FREEZE_PATH),
        "m1_final_seal": _file(M1_FINAL_SEAL),
        "acquisition_manifest": _file(paths.acquisition),
        "xau_source": _file(paths.xau),
        "artifacts": [_file(path) for path in artifact_paths],
        "feature_fingerprints": feature_fingerprints,
        "decision_fingerprints": decision_fingerprints,
        "event_fingerprints": event_fingerprints,
        "verdict_receipt": verdict["verdict_receipt"],
        "development_outcomes_accessed": False,
        "holdout_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = _canonical({**manifest, "manifest_receipt": None})
    manifest_path = paths.output / "manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    final: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_FINAL_SEAL_V1_0",
        "status": status,
        "sealed_at_utc": _utc_now(),
        "freeze_sha256": _sha256(FREEZE_PATH),
        "verdict_sha256": _sha256(verdict_path),
        "manifest_sha256": _sha256(manifest_path),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = _canonical({**final, "final_seal_receipt": None})
    _write_json_exclusive(paths.output / "final_seal.json", final)
    print(json.dumps({"status": status, "event_rows": event_rows, "stage1_support_eligible": primary_support["stage1_support_eligible"], "stage2_support_eligible": primary_support["stage2_support_eligible"], "outcomes": False}, sort_keys=True))


def _verify_final(paths: Paths) -> None:
    _verified_control(paths, verify_payload_hashes=False)
    verdict = _read(paths.output / "verdict.json")
    manifest = _read(paths.output / "manifest.json")
    final = _read(paths.output / "final_seal.json")
    if final["freeze_sha256"] != _sha256(FREEZE_PATH) or final["verdict_sha256"] != _sha256(paths.output / "verdict.json") or final["manifest_sha256"] != _sha256(paths.output / "manifest.json"):
        raise ValueError("M2 final-seal binding failed")
    if verdict["verdict_receipt"] != _canonical({**verdict, "verdict_receipt": None}):
        raise ValueError("M2 verdict receipt failed")
    if manifest["manifest_receipt"] != _canonical({**manifest, "manifest_receipt": None}):
        raise ValueError("M2 manifest receipt failed")
    if final["final_seal_receipt"] != _canonical({**final, "final_seal_receipt": None}):
        raise ValueError("M2 final receipt failed")
    if not all(path["bytes"] == Path(path["path"]).stat().st_size and path["sha256"] == _sha256(Path(path["path"])) for path in manifest["artifacts"]):
        raise ValueError("M2 artifact verification failed")
    if any((verdict["development_outcomes_opened_or_joined"], verdict["relationships_hit_rates_effects_pvalues_candidates_or_rankings_calculated"], verdict["execution_trades_pnl_r_multiples_or_returns_calculated"], verdict["year_2025_or_2026_values_accessed"], verdict["data_acquired"], bool(verdict["charge_incurred_usd"]))):
        raise ValueError("Prohibited Milestone 2 work recorded")
    print(json.dumps({"status": final["status"], "final_seal_receipt": final["final_seal_receipt"], "verified_artifacts": len(manifest["artifacts"])}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "materialize", "seal", "verify"))
    parser.add_argument("--acquisition", default=str(DEFAULT_ACQUISITION))
    parser.add_argument("--step5b2", default=str(DEFAULT_STEP5B2))
    parser.add_argument("--context", default=str(DEFAULT_CONTEXT))
    parser.add_argument("--xau", default=str(DEFAULT_XAU))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    paths = Paths(Path(args.acquisition), Path(args.step5b2), Path(args.context), Path(args.xau), Path(args.output))
    if args.action == "preflight":
        _preflight(paths)
    elif args.action == "materialize":
        _materialize(paths)
    elif args.action == "seal":
        _seal(paths)
    else:
        _verify_final(paths)


if __name__ == "__main__":
    main()
