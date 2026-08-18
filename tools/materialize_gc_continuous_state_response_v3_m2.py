#!/usr/bin/env python3
"""Outcome-blind V3 Milestone 2 continuous-predictor materialization.

This module is deliberately self-contained.  It never imports or opens an
outcome artifact.  The primary and reference workers consume the same sealed
sources sequentially, calculate one session-date at a time, and write only the
frozen predictor/lineage schema.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict, deque
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
import gzip
import hashlib
import itertools
import json
import math
import os
from pathlib import Path
import re
import statistics
import subprocess
import sys
import time
from typing import Any, Iterable, Iterator, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_CONTRACT_V3.md"
M2_DOCUMENT = ROOT / "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3_MILESTONE_2.md"
PROTOCOL = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_protocol_v01.json"
FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_freeze_v01.json"
FEATURE_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_feature_registry_v01.json"
MODEL_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_model_registry_v01.json"
TRACEABILITY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_traceability_v01.json"
M1_FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m1_freeze_v01.json"
M1_OUTPUT = ROOT / "research_artifacts" / "gc_continuous_state_response_v3_m1_v01"
M1_STATE = ROOT / "research_artifacts" / "gc_continuous_state_response_v3_state_v01.json"
ROW_REGISTRY = ROOT / "research_manifests" / "gc_session_trigger_edge_m2_row_registry_v01.json"
TEST_FILE = ROOT / "tests" / "test_gc_continuous_state_response_v3_m2.py"

DEFAULT_DATA_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_OUTPUT_NAME = "gc_continuous_state_response_v3_m2_v01"

SESSIONS = ("LONDON", "NEW_YORK")
OFFSETS_MINUTES = tuple(range(0, 240, 15))
STAGE1_IDS = (
    "CSR_FLOW_QUOTE_OFI_W60",
    "CSR_FLOW_TRADE_IMBALANCE_W60",
    "CSR_FLOW_DISPLAYED_IMBALANCE_W60",
    "CSR_BOOK_DEPTH_IMBALANCE_L5_W60",
    "CSR_BOOK_MICROPRICE_DISLOCATION_T0",
    "CSR_STRUCTURE_MOMENTUM_15M",
    "CSR_MACRO_ENGINE_SCORE",
    "CSR_MACRO_REAL_YIELD_SUPPORT",
    "CSR_MACRO_USD_SUPPORT",
    "CSR_MACRO_2Y_SUPPORT",
)
MODIFIER_IDS = (
    "CSR_LIQ_SPREAD_FRAGILITY_60_900",
    "CSR_SESSION_LEVEL_TENSION",
)
FEATURE_IDS = (*STAGE1_IDS, *MODIFIER_IDS)

SOURCE_COLUMNS = (
    "bucket_index",
    "bucket_start_ns",
    "bucket_end_ns",
    "market_segment",
    "market_state",
    "add_qty_bid",
    "add_qty_ask",
    "cancel_qty_bid",
    "cancel_qty_ask",
    "trade_qty_buy",
    "trade_qty_sell",
    "quote_ofi_transition_count",
    "quote_ofi_raw",
    "state_available",
    "book_two_sided",
    "book_locked",
    "book_crossed",
    "spread_fixed_1e9",
    "midpoint_fixed_1e9",
    "microprice_fixed_1e9",
    "depth_imbalance_l5_ppb",
)

IDENTITY_COLUMNS = (
    "anchor_id",
    "session_row_id",
    "session_date",
    "session_code",
    "selected_month_week_id",
    "chronological_block",
    "anchor_offset_minutes",
    "session_open_ns",
    "decision_at_ns",
)

EXPECTED_AVAILABLE_SESSIONS = 374
EXPECTED_SESSION_DATES_PER_SESSION = 187
EXPECTED_ANCHORS_PER_DATE = 16
EXPECTED_ANCHORS_PER_SESSION = 2_992
EXPECTED_ANCHORS_TOTAL = 5_984
EXPECTED_SOURCE_ROWS_PER_DATE = 18_900
EXPECTED_SOURCE_ROWS_PER_SESSION = 3_534_300
W60 = 60
W900 = 900
MIN_W60_STATE = 57
MIN_W900_STATE = 855
GC_TICK_FIXED_1E9 = 100_000_000
ONE_SECOND_NS = 1_000_000_000
ONE_MINUTE_NS = 60 * ONE_SECOND_NS
FIFTEEN_MINUTES_NS = 15 * ONE_MINUTE_NS
ONE_HOUR_NS = 60 * ONE_MINUTE_NS
RSS_CAP_BYTES = 4 * 1024**3
RSS_GUARD_BYTES = 3_840 * 1024**2
RSS_POLL_SECONDS = 0.05
PRICE_LOOKBACK = timedelta(days=14)
VALID_FACT_QUALITIES = frozenset({"VALID", "PARTIAL"})

EXPECTED_M1_FINAL_SEAL = "e46dce1b9627d2978c8a13a654b68fd181b3061e9a9ff53658e77057b2bbae7b"
EXPECTED_M1_FREEZE_RECEIPT = "e651648c989720914b23c96d400c0c5d528f87b05358cb692e637e3a35ed7caf"
EXPECTED_FEATURE_REGISTRY_SHA256 = "84d97ec1e26d650f0b9ddd8c216b637db1eafae1b84dcbcddec3270fa3b858b1"
EXPECTED_MODEL_REGISTRY_SHA256 = "98c856fe0ec5363bcc1bdd63ed069534b469398ac1a2972ec5a41b6ff1a5964b"
EXPECTED_TRACEABILITY_SHA256 = "767039935bccefe1922ff898ad5d389ba37effc2f2c3b7a11b103f4377da8ed8"
EXPECTED_ROW_REGISTRY_SHA256 = "a7a36ae82d92ce91a25e36fcb7f1c95807de67c996d01198648246daa345dc5d"

AV_AVAILABLE = "AVAILABLE"
AV_UNKNOWN_CONTEXT = "UNKNOWN_POINT_IN_TIME_CONTEXT"
AV_UNKNOWN_CHANGE = "UNKNOWN_CHANGE_INPUT"
AV_UNKNOWN_NONPOSITIVE = "UNKNOWN_NONPOSITIVE_INPUT"
AV_UNKNOWN_ZERO_DENOM = "UNKNOWN_ZERO_DENOMINATOR"
AV_TECH_STATE = "UNAVAILABLE_TECHNICAL_STATE"
AV_TECH_XAU = "UNAVAILABLE_TECHNICAL_XAU_GAP"
AV_W60 = "UNKNOWN_INSUFFICIENT_W60"
AV_W900 = "UNKNOWN_INSUFFICIENT_W900"
AV_ATR = "UNKNOWN_INSUFFICIENT_ATR_HISTORY"
AV_LEVEL = "UNKNOWN_NO_KNOWN_LEVEL"
AV_SPREAD = "UNKNOWN_NONPOSITIVE_SPREAD"
AV_INVALID = "UNKNOWN_INVALID_NUMERIC_VALUE"
AVAILABILITY_VALUES = frozenset(
    {
        AV_AVAILABLE,
        AV_UNKNOWN_CONTEXT,
        AV_UNKNOWN_CHANGE,
        AV_UNKNOWN_NONPOSITIVE,
        AV_UNKNOWN_ZERO_DENOM,
        AV_TECH_STATE,
        AV_TECH_XAU,
        AV_W60,
        AV_W900,
        AV_ATR,
        AV_LEVEL,
        AV_SPREAD,
        AV_INVALID,
    }
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_hash(value: Any) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"Sealed artifact differs: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    os.replace(temporary, path)


def write_json_once(path: Path, value: Any) -> None:
    write_once(path, json_bytes(value))


def require(value: bool, message: str) -> None:
    if not value:
        raise ValueError(message)


def receipt_valid(record: Mapping[str, Any], field: str) -> bool:
    expected = record.get(field)
    if not isinstance(expected, str):
        return False
    without = dict(record)
    without.pop(field, None)
    return expected in {canonical_hash(without), canonical_hash({**record, field: None})}


def seal_receipt(record: dict[str, Any], field: str) -> dict[str, Any]:
    result = dict(record)
    result[field] = None
    result[field] = canonical_hash(result)
    return result


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def dt_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def ns_iso(value: int) -> str:
    return datetime.fromtimestamp(value / 1_000_000_000, tz=UTC).isoformat().replace("+00:00", "Z")


def output_schema() -> pa.Schema:
    fields: list[pa.Field] = [
        pa.field("anchor_id", pa.string(), nullable=False),
        pa.field("session_row_id", pa.string(), nullable=False),
        pa.field("session_date", pa.string(), nullable=False),
        pa.field("session_code", pa.string(), nullable=False),
        pa.field("selected_month_week_id", pa.string(), nullable=False),
        pa.field("chronological_block", pa.int16(), nullable=False),
        pa.field("anchor_offset_minutes", pa.int16(), nullable=False),
        pa.field("session_open_ns", pa.int64(), nullable=False),
        pa.field("decision_at_ns", pa.int64(), nullable=False),
    ]
    for feature_id in FEATURE_IDS:
        fields.extend(
            (
                pa.field(f"{feature_id}__value", pa.float64(), nullable=True),
                pa.field(f"{feature_id}__availability", pa.string(), nullable=False),
                pa.field(f"{feature_id}__available_at_ns", pa.int64(), nullable=True),
                pa.field(f"{feature_id}__lineage_hash", pa.string(), nullable=False),
            )
        )
    return pa.schema(fields)


OUTPUT_SCHEMA = output_schema()


def schema_fingerprint(schema: pa.Schema) -> str:
    return canonical_hash(
        [
            {"name": field.name, "type": str(field.type), "nullable": field.nullable}
            for field in schema
        ]
    )


@dataclass(frozen=True, slots=True)
class Paths:
    data_root: Path
    output: Path
    gc_dir: Path
    context_projection: Path
    xau_bars: Path

    @classmethod
    def build(cls, data_root: Path, output: Path | None = None) -> "Paths":
        return cls(
            data_root=data_root,
            output=output or data_root / "artifacts" / DEFAULT_OUTPUT_NAME,
            gc_dir=data_root / "artifacts" / "gc_session_trigger_edge_v2r1_v01",
            context_projection=data_root / "artifacts" / "step5c_context_input" / "decision_context_projection.jsonl.gz",
            xau_bars=data_root / "data" / "gold_casebook_v01" / "price_bars.jsonl.gz",
        )

    def gc_file(self, implementation: str, session: str) -> Path:
        return self.gc_dir / f"{implementation}_{session.lower()}_one_second_features.parquet"


@dataclass(frozen=True, slots=True)
class Observation:
    value: float | None
    availability: str
    available_at_ns: int | None
    lineage_hash: str

    def __post_init__(self) -> None:
        if self.availability not in AVAILABILITY_VALUES:
            raise ValueError(self.availability)
        if self.availability == AV_AVAILABLE:
            if self.value is None or not math.isfinite(self.value):
                raise ValueError("Available observation requires a finite value")
        elif self.value is not None:
            raise ValueError("Unavailable observation must be null")


@dataclass(frozen=True, slots=True)
class PriceBar:
    open_ns: int
    close_ns: int
    available_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    record_id: str
    record_hash: str


@dataclass(frozen=True, slots=True)
class AggregateBar:
    start_ns: int
    close_ns: int
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    source_hashes: tuple[str, ...]
    maximum_available_ns: int
    member_count: int
    complete: bool


@dataclass(frozen=True, slots=True)
class PreparedPriceSession:
    canonical: tuple[PriceBar, ...]
    fifteen: Mapping[int, AggregateBar]
    hourly: Mapping[int, AggregateBar]


def expected_source_records(paths: Paths) -> dict[str, dict[str, Any]]:
    protocol = load_json(PROTOCOL)["permitted_sources"]
    return {
        "primary_london_gc": {"path": paths.gc_file("primary", "LONDON"), "sha256": protocol["primary_london_gc_sha256"]},
        "primary_new_york_gc": {"path": paths.gc_file("primary", "NEW_YORK"), "sha256": protocol["primary_new_york_gc_sha256"]},
        "reference_london_gc": {"path": paths.gc_file("reference", "LONDON"), "sha256": protocol["reference_london_gc_sha256"]},
        "reference_new_york_gc": {"path": paths.gc_file("reference", "NEW_YORK"), "sha256": protocol["reference_new_york_gc_sha256"]},
        "decision_context_projection": {"path": paths.context_projection, "sha256": protocol["decision_context_projection_sha256"]},
        "xauusd_price_bars": {"path": paths.xau_bars, "sha256": protocol["xauusd_price_bars_sha256"]},
    }


def verify_m1_boundary() -> dict[str, Any]:
    require(sha256_file(FEATURE_REGISTRY) == EXPECTED_FEATURE_REGISTRY_SHA256, "V3 feature registry changed")
    require(sha256_file(MODEL_REGISTRY) == EXPECTED_MODEL_REGISTRY_SHA256, "V3 model registry changed")
    require(sha256_file(TRACEABILITY) == EXPECTED_TRACEABILITY_SHA256, "V3 traceability changed")
    require(sha256_file(ROW_REGISTRY) == EXPECTED_ROW_REGISTRY_SHA256, "Trigger row registry changed")
    m1_freeze = load_json(M1_FREEZE)
    m1_final = load_json(M1_OUTPUT / "final_seal.json")
    m1_state = load_json(M1_STATE)
    require(receipt_valid(m1_freeze, "freeze_receipt"), "M1 freeze receipt invalid")
    require(receipt_valid(m1_final, "final_seal_receipt"), "M1 final seal receipt invalid")
    require(m1_freeze["freeze_receipt"] == EXPECTED_M1_FREEZE_RECEIPT, "M1 freeze receipt changed")
    require(m1_final["final_seal_receipt"] == EXPECTED_M1_FINAL_SEAL, "M1 final seal changed")
    require(m1_state["development"]["outcomes_locked_until_authorized_m3"], "Development outcomes not locked")
    require(m1_state["forward_locks"] == {"2025": "LOCKED", "2026": "LOCKED"}, "Forward locks changed")
    registry = load_json(FEATURE_REGISTRY)
    models = load_json(MODEL_REGISTRY)
    require(tuple(item["feature_id"] for item in registry["features"]) == FEATURE_IDS, "Feature order/cardinality changed")
    require(tuple(models["stage1"]["features"]) == STAGE1_IDS, "Stage-1 registry changed")
    require(tuple(models["sampling"]["offset_minutes"]) == OFFSETS_MINUTES, "Anchor offsets changed")
    return {
        "m1_freeze_receipt": m1_freeze["freeze_receipt"],
        "m1_final_seal_receipt": m1_final["final_seal_receipt"],
        "m1_state_receipt": m1_state["state_receipt"],
        "outcomes_locked": True,
        "year_2025_locked": True,
        "year_2026_locked": True,
    }


def verify_registry_population() -> tuple[list[dict[str, Any]], dict[str, int]]:
    registry = load_json(ROW_REGISTRY)
    require(receipt_valid(registry, "registry_receipt"), "Row-registry receipt invalid")
    rows = [dict(item) for item in registry["rows"]]
    available = [row for row in rows if int(row["expected_bucket_rows"]) > 0]
    require(len(rows) == 376 and len(available) == EXPECTED_AVAILABLE_SESSIONS, "Session population changed")
    by_session = Counter(str(row["session_code"]) for row in available)
    require(dict(by_session) == {"LONDON": 187, "NEW_YORK": 187}, "Session balance changed")
    require(all(str(row["session_date"]) < "2025-01-01" for row in rows), "Forward row entered registry")
    blocks = sorted({str(row["selected_month_week_id"]) for row in available})
    require(len(blocks) == 38, "Chronological block count changed")
    block_map = {block: index + 1 for index, block in enumerate(blocks)}
    return rows, block_map


def verify_source_metadata(paths: Paths, *, hash_files: bool) -> dict[str, Any]:
    records: dict[str, Any] = {}
    for name, expected in expected_source_records(paths).items():
        path = Path(expected["path"])
        require(path.is_file(), f"Missing sealed source: {path}")
        actual_hash = sha256_file(path) if hash_files else str(expected["sha256"])
        require(actual_hash == expected["sha256"], f"Source hash changed: {name}")
        records[name] = {"path": str(path), "bytes": path.stat().st_size, "sha256": actual_hash}
    expected_schema = pa.schema([field for field in pq.ParquetFile(paths.gc_file("primary", "LONDON")).schema_arrow])
    for implementation in ("primary", "reference"):
        for session in SESSIONS:
            pf = pq.ParquetFile(paths.gc_file(implementation, session))
            require(pf.metadata.num_rows == EXPECTED_SOURCE_ROWS_PER_SESSION, f"GC row count changed: {implementation}/{session}")
            require(all(name in pf.schema_arrow.names for name in SOURCE_COLUMNS), f"GC schema missing fields: {implementation}/{session}")
            require(pf.schema_arrow == expected_schema, f"GC schema differs: {implementation}/{session}")
            records[f"{implementation}_{session.lower()}_gc"]["rows"] = pf.metadata.num_rows
            records[f"{implementation}_{session.lower()}_gc"]["row_groups"] = pf.num_row_groups
    return records


def freeze(paths: Paths) -> None:
    boundary = verify_m1_boundary()
    rows, blocks = verify_registry_population()
    sources = verify_source_metadata(paths, hash_files=True)
    require(not FREEZE.exists(), f"Freeze already exists: {FREEZE}")
    record = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_FREEZE_V1_0",
        "status": "PASS_V3_M2_PRE_VALUE_FREEZE",
        "frozen_at_utc": utc_now(),
        "boundary": boundary,
        "contract_sha256": sha256_file(CONTRACT),
        "m2_document_sha256": sha256_file(M2_DOCUMENT),
        "protocol_sha256": sha256_file(PROTOCOL),
        "feature_registry_sha256": sha256_file(FEATURE_REGISTRY),
        "model_registry_sha256": sha256_file(MODEL_REGISTRY),
        "traceability_sha256": sha256_file(TRACEABILITY),
        "row_registry_sha256": sha256_file(ROW_REGISTRY),
        "implementation_sha256": sha256_file(Path(__file__)),
        "test_sha256": sha256_file(TEST_FILE),
        "output_schema_sha256": schema_fingerprint(OUTPUT_SCHEMA),
        "source_records": sources,
        "population": {"registry_rows": len(rows), "available_sessions": EXPECTED_AVAILABLE_SESSIONS, "blocks": len(blocks), "anchors_total": EXPECTED_ANCHORS_TOTAL},
        "outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "relationships_candidates_execution_or_pnl_calculated": False,
        "freeze_receipt": None,
    }
    record["freeze_receipt"] = canonical_hash(record)
    write_json_once(FREEZE, record)
    print(json.dumps({"status": record["status"], "freeze_receipt": record["freeze_receipt"], "anchors": EXPECTED_ANCHORS_TOTAL}, sort_keys=True))


def verify_freeze(paths: Paths, *, verify_source_hashes: bool = True) -> dict[str, Any]:
    require(FREEZE.is_file(), "M2 freeze is missing")
    frozen = load_json(FREEZE)
    require(receipt_valid(frozen, "freeze_receipt"), "M2 freeze receipt invalid")
    require(frozen["status"] == "PASS_V3_M2_PRE_VALUE_FREEZE", "M2 freeze status changed")
    checks = {
        CONTRACT: frozen["contract_sha256"],
        M2_DOCUMENT: frozen["m2_document_sha256"],
        PROTOCOL: frozen["protocol_sha256"],
        FEATURE_REGISTRY: frozen["feature_registry_sha256"],
        MODEL_REGISTRY: frozen["model_registry_sha256"],
        TRACEABILITY: frozen["traceability_sha256"],
        ROW_REGISTRY: frozen["row_registry_sha256"],
        Path(__file__): frozen["implementation_sha256"],
        TEST_FILE: frozen["test_sha256"],
    }
    for path, expected in checks.items():
        require(sha256_file(path) == expected, f"Frozen file changed: {path}")
    require(schema_fingerprint(OUTPUT_SCHEMA) == frozen["output_schema_sha256"], "Output schema changed")
    verify_m1_boundary()
    verify_registry_population()
    verify_source_metadata(paths, hash_files=verify_source_hashes)
    return frozen


def unknown_observation(
    feature_id: str,
    availability: str,
    *,
    available_at_ns: int | None,
    lineage_payload: Mapping[str, Any],
) -> Observation:
    return Observation(
        value=None,
        availability=availability,
        available_at_ns=available_at_ns,
        lineage_hash=canonical_hash({"feature_id": feature_id, **dict(lineage_payload)}),
    )


def available_observation(
    feature_id: str,
    value: float,
    *,
    available_at_ns: int,
    lineage_payload: Mapping[str, Any],
) -> Observation:
    return Observation(
        value=float(value),
        availability=AV_AVAILABLE,
        available_at_ns=available_at_ns,
        lineage_hash=canonical_hash({"feature_id": feature_id, **dict(lineage_payload)}),
    )


class FixedBlockReader:
    """Read consecutive logical session blocks independent of row-group layout."""

    def __init__(self, path: Path, columns: Sequence[str]) -> None:
        self.path = path
        self.parquet = pq.ParquetFile(path)
        self.iterator = iter(self.parquet.iter_batches(batch_size=32_768, columns=list(columns), use_threads=False))
        self.pending: pa.Table | None = None
        self.pending_offset = 0
        self.rows_consumed = 0

    def take(self, count: int) -> pa.Table:
        pieces: list[pa.Table] = []
        remaining = count
        while remaining:
            if self.pending is None or self.pending_offset >= self.pending.num_rows:
                try:
                    batch = next(self.iterator)
                except StopIteration as exc:
                    raise ValueError(f"Unexpected end of GC source: {self.path}") from exc
                self.pending = pa.Table.from_batches([batch])
                self.pending_offset = 0
            available = self.pending.num_rows - self.pending_offset
            take = min(available, remaining)
            pieces.append(self.pending.slice(self.pending_offset, take))
            self.pending_offset += take
            self.rows_consumed += take
            remaining -= take
        table = pieces[0] if len(pieces) == 1 else pa.concat_tables(pieces)
        require(table.num_rows == count, "Logical block reader returned wrong count")
        return table.combine_chunks()

    def finish(self, expected_rows: int) -> None:
        require(self.rows_consumed == expected_rows, f"GC allocation count differs: {self.path}")
        remaining = 0
        if self.pending is not None:
            remaining += self.pending.num_rows - self.pending_offset
        for batch in self.iterator:
            remaining += batch.num_rows
        require(remaining == 0, f"Unallocated GC rows remain: {self.path}")


class ProjectionReader:
    def __init__(self, path: Path, registry_rows: Sequence[Mapping[str, Any]]) -> None:
        self.path = path
        self.registry_rows = list(registry_rows)
        self.index = 0
        self.handle = gzip.open(path, "rt", encoding="utf-8")

    def get(self, registry_index: int, expected: Mapping[str, Any]) -> dict[str, Any]:
        require(registry_index >= self.index, "Projection access is not chronological")
        selected: dict[str, Any] | None = None
        while self.index <= registry_index:
            line = self.handle.readline()
            require(bool(line), "Context projection ended early")
            record = json.loads(line)
            registry = self.registry_rows[self.index]
            require(str(record["session_date"]) == str(registry["session_date"]), "Projection date order changed")
            require(str(record["session_code"]) == str(registry["session_code"]), "Projection session order changed")
            require(not bool(record.get("outcome_fields_present")), "Outcome field entered context projection")
            require("subsequent_behaviour" not in record, "Subsequent behaviour entered M2")
            if self.index == registry_index:
                selected = record
            self.index += 1
        require(selected is not None, "Projection row not selected")
        require(str(selected["session_date"]) == str(expected["session_date"]), "Selected projection date mismatch")
        require(str(selected["session_code"]) == str(expected["session_code"]), "Selected projection session mismatch")
        return selected

    def close(self) -> None:
        self.handle.close()


def mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def number(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    try:
        result = float(value)
    except (TypeError, ValueError, OverflowError):
        return None
    return result if math.isfinite(result) else None


def nested_primary(value: Mapping[str, Any], *keys: str) -> Mapping[str, Any]:
    current: Any = value
    for key in keys:
        current = mapping(current).get(key)
    return mapping(current)


def nested_reference(value: Mapping[str, Any], path: str) -> Mapping[str, Any]:
    current: Any = value
    for key in path.split("."):
        current = mapping(current).get(key)
        if current is None:
            return {}
    return mapping(current)


def fact_eligible(fact: Mapping[str, Any], decision_ns: int) -> bool:
    if not fact or fact.get("value") is None or fact.get("epistemic_status") == "UNKNOWN":
        return False
    if fact.get("quality") not in VALID_FACT_QUALITIES:
        return False
    available = fact.get("available_at")
    if not isinstance(available, str):
        return False
    return dt_ns(parse_dt(available)) <= decision_ns


def fact_available_ns(fact: Mapping[str, Any]) -> int | None:
    value = fact.get("available_at")
    return dt_ns(parse_dt(str(value))) if value else None


def context_lineage(
    projection: Mapping[str, Any], feature_id: str, fact: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    return {
        "source": "SEALED_STEP5C_CONTEXT_PROJECTION",
        "source_sha256": load_json(PROTOCOL)["permitted_sources"]["decision_context_projection_sha256"],
        "projection_record_hash": projection.get("record_hash"),
        "source_session_record_id": projection.get("source_session_record_id"),
        "fact_hash": canonical_hash(dict(fact or {})),
        "feature": feature_id,
    }


def extract_macro_primary(
    projection: Mapping[str, Any], decision_ns: int
) -> dict[str, Observation]:
    state = mapping(projection.get("decision_state"))
    regime = nested_primary(state, "layers", "market_regime")
    facts = {
        "CSR_MACRO_ENGINE_SCORE": mapping(regime.get("regime_state")),
        "CSR_MACRO_REAL_YIELD_SUPPORT": nested_primary(regime, "rates", "real_yield_10y"),
        "CSR_MACRO_USD_SUPPORT": mapping(regime.get("usd")),
        "CSR_MACRO_2Y_SUPPORT": nested_primary(regime, "rates", "treasury_2y"),
    }
    return _macro_from_facts(projection, decision_ns, facts)


def extract_macro_reference(
    projection: Mapping[str, Any], decision_ns: int
) -> dict[str, Observation]:
    state = mapping(projection.get("decision_state"))
    paths = {
        "CSR_MACRO_ENGINE_SCORE": "layers.market_regime.regime_state",
        "CSR_MACRO_REAL_YIELD_SUPPORT": "layers.market_regime.rates.real_yield_10y",
        "CSR_MACRO_USD_SUPPORT": "layers.market_regime.usd",
        "CSR_MACRO_2Y_SUPPORT": "layers.market_regime.rates.treasury_2y",
    }
    facts = {feature: nested_reference(state, path) for feature, path in paths.items()}
    return _macro_from_facts(projection, decision_ns, facts)


def _macro_from_facts(
    projection: Mapping[str, Any],
    decision_ns: int,
    facts: Mapping[str, Mapping[str, Any]],
) -> dict[str, Observation]:
    output: dict[str, Observation] = {}
    for feature_id, fact in facts.items():
        lineage = context_lineage(projection, feature_id, fact)
        available_ns = fact_available_ns(fact)
        if not fact_eligible(fact, decision_ns):
            output[feature_id] = unknown_observation(feature_id, AV_UNKNOWN_CONTEXT, available_at_ns=available_ns, lineage_payload=lineage)
            continue
        value = mapping(fact.get("value"))
        calculated: float | None = None
        unavailable = AV_INVALID
        if feature_id == "CSR_MACRO_ENGINE_SCORE":
            calculated = number(value.get("directional_score"))
        elif value.get("change_epistemic_status") == "UNKNOWN" or not value.get("previous_record_id"):
            unavailable = AV_UNKNOWN_CHANGE
        elif feature_id == "CSR_MACRO_REAL_YIELD_SUPPORT":
            change = number(value.get("absolute_change"))
            calculated = -change if change is not None else None
            unavailable = AV_UNKNOWN_CHANGE
        elif feature_id == "CSR_MACRO_2Y_SUPPORT":
            change = number(value.get("absolute_change"))
            calculated = -100.0 * change if change is not None else None
            unavailable = AV_UNKNOWN_CHANGE
        else:
            current = number(value.get("value"))
            previous = number(value.get("previous_value"))
            if current is not None and previous is not None and current > 0 and previous > 0:
                calculated = -10_000.0 * math.log(current / previous)
            else:
                unavailable = AV_UNKNOWN_NONPOSITIVE
        if calculated is None or not math.isfinite(calculated):
            output[feature_id] = unknown_observation(feature_id, unavailable, available_at_ns=available_ns, lineage_payload=lineage)
        else:
            require(available_ns is not None, "Eligible macro fact lacks available_at")
            output[feature_id] = available_observation(feature_id, calculated, available_at_ns=available_ns, lineage_payload=lineage)
    return output


def table_array_primary(table: pa.Table, name: str) -> np.ndarray[Any, Any]:
    column = table[name].combine_chunks()
    if pa.types.is_string(column.type):
        return np.asarray(column.to_pylist(), dtype=object)
    if pa.types.is_boolean(column.type):
        return np.asarray(column.to_pylist(), dtype=bool)
    values = column.to_numpy(zero_copy_only=False)
    return np.asarray(values)


def valid_state_primary(arrays: Mapping[str, np.ndarray[Any, Any]], start: int, end: int) -> np.ndarray[Any, Any]:
    return (
        (arrays["market_state"][start:end] == "CONTINUOUS_MATCHING")
        & arrays["state_available"][start:end]
        & arrays["book_two_sided"][start:end]
        & ~arrays["book_locked"][start:end]
        & ~arrays["book_crossed"][start:end]
    )


def primary_median(values: np.ndarray[Any, Any]) -> float:
    return float(np.median(values))


def micro_lineage(
    source_sha: str,
    row: Mapping[str, Any],
    feature_id: str,
    decision_ns: int,
    columns: Sequence[str],
    window_seconds: int,
) -> dict[str, Any]:
    return {
        "source": "SEALED_V2R1_ONE_SECOND_GC",
        "source_sha256": source_sha,
        "session_row_id": row["row_id"],
        "feature": feature_id,
        "columns": list(columns),
        "window_start_exclusive_ns": decision_ns - window_seconds * ONE_SECOND_NS,
        "window_end_inclusive_ns": decision_ns,
    }


def calculate_micro_primary(
    table: pa.Table,
    row: Mapping[str, Any],
    source_sha: str,
    decision_ns: int,
    end_count: int,
) -> dict[str, Observation]:
    arrays = {name: table_array_primary(table, name) for name in SOURCE_COLUMNS}
    return _calculate_micro_numpy(arrays, row, source_sha, decision_ns, end_count)


def prepare_micro_primary(table: pa.Table) -> dict[str, np.ndarray[Any, Any]]:
    return {name: table_array_primary(table, name) for name in SOURCE_COLUMNS}


def _calculate_micro_numpy(
    arrays: Mapping[str, np.ndarray[Any, Any]],
    row: Mapping[str, Any],
    source_sha: str,
    decision_ns: int,
    end_count: int,
) -> dict[str, Observation]:
    s60, s900 = end_count - W60, end_count - W900
    require(s900 >= 0 and end_count <= len(arrays["bucket_end_ns"]), "Anchor outside GC source block")
    require(int(arrays["bucket_end_ns"][end_count - 1]) == decision_ns, "GC anchor bucket does not end at decision")
    valid60 = valid_state_primary(arrays, s60, end_count)
    valid900 = valid_state_primary(arrays, s900, end_count)
    output: dict[str, Observation] = {}

    fid = "CSR_FLOW_QUOTE_OFI_W60"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("quote_ofi_raw", "quote_ofi_transition_count", "state_available", "book_crossed"), W60)
    if int(valid60.sum()) < MIN_W60_STATE:
        output[fid] = unknown_observation(fid, AV_W60, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        transitions = int(np.asarray(arrays["quote_ofi_transition_count"][s60:end_count][valid60], dtype=np.int64).sum())
        if transitions <= 0:
            output[fid] = unknown_observation(fid, AV_UNKNOWN_ZERO_DENOM, available_at_ns=decision_ns, lineage_payload=lineage)
        else:
            raw = int(np.asarray(arrays["quote_ofi_raw"][s60:end_count][valid60], dtype=np.int64).sum())
            output[fid] = available_observation(fid, raw / transitions, available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_FLOW_TRADE_IMBALANCE_W60"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("trade_qty_buy", "trade_qty_sell"), W60)
    buy = int(np.asarray(arrays["trade_qty_buy"][s60:end_count], dtype=np.int64).sum())
    sell = int(np.asarray(arrays["trade_qty_sell"][s60:end_count], dtype=np.int64).sum())
    if buy + sell == 0:
        output[fid] = unknown_observation(fid, AV_UNKNOWN_ZERO_DENOM, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        output[fid] = available_observation(fid, (buy - sell) / (buy + sell), available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_FLOW_DISPLAYED_IMBALANCE_W60"
    cols = ("add_qty_bid", "add_qty_ask", "cancel_qty_bid", "cancel_qty_ask")
    lineage = micro_lineage(source_sha, row, fid, decision_ns, cols, W60)
    totals = {name: int(np.asarray(arrays[name][s60:end_count], dtype=np.int64).sum()) for name in cols}
    denominator = sum(totals.values())
    if denominator == 0:
        output[fid] = unknown_observation(fid, AV_UNKNOWN_ZERO_DENOM, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        numerator = (totals["add_qty_bid"] + totals["cancel_qty_ask"]) - (totals["add_qty_ask"] + totals["cancel_qty_bid"])
        output[fid] = available_observation(fid, numerator / denominator, available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_BOOK_DEPTH_IMBALANCE_L5_W60"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("depth_imbalance_l5_ppb", "state_available", "book_crossed"), W60)
    depth_values = np.asarray(arrays["depth_imbalance_l5_ppb"][s60:end_count], dtype=np.float64)
    depth_mask = valid60 & np.isfinite(depth_values)
    if int(depth_mask.sum()) < MIN_W60_STATE:
        output[fid] = unknown_observation(fid, AV_W60, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        output[fid] = available_observation(fid, primary_median(depth_values[depth_mask]), available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_BOOK_MICROPRICE_DISLOCATION_T0"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("microprice_fixed_1e9", "midpoint_fixed_1e9", "spread_fixed_1e9", "state_available", "book_crossed"), 1)
    terminal_valid = bool(valid_state_primary(arrays, end_count - 1, end_count)[0])
    micro = float(arrays["microprice_fixed_1e9"][end_count - 1])
    midpoint = float(arrays["midpoint_fixed_1e9"][end_count - 1])
    spread = float(arrays["spread_fixed_1e9"][end_count - 1])
    if not terminal_valid or not all(math.isfinite(value) for value in (micro, midpoint, spread)):
        output[fid] = unknown_observation(fid, AV_TECH_STATE, available_at_ns=decision_ns, lineage_payload=lineage)
    elif spread <= 0:
        output[fid] = unknown_observation(fid, AV_SPREAD, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        output[fid] = available_observation(fid, (micro - midpoint) / spread, available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_LIQ_SPREAD_FRAGILITY_60_900"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("spread_fixed_1e9", "state_available", "book_crossed"), W900)
    spreads60 = np.asarray(arrays["spread_fixed_1e9"][s60:end_count], dtype=np.float64)
    spreads900 = np.asarray(arrays["spread_fixed_1e9"][s900:end_count], dtype=np.float64)
    mask60 = valid60 & np.isfinite(spreads60) & (spreads60 > 0)
    mask900 = valid900 & np.isfinite(spreads900) & (spreads900 > 0)
    if int(mask60.sum()) < MIN_W60_STATE:
        output[fid] = unknown_observation(fid, AV_W60, available_at_ns=decision_ns, lineage_payload=lineage)
    elif int(mask900.sum()) < MIN_W900_STATE:
        output[fid] = unknown_observation(fid, AV_W900, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        med60 = primary_median(spreads60[mask60])
        med900 = primary_median(spreads900[mask900])
        calculated = math.log((med60 + GC_TICK_FIXED_1E9) / (med900 + GC_TICK_FIXED_1E9))
        output[fid] = available_observation(fid, calculated, available_at_ns=decision_ns, lineage_payload=lineage)
    return output


def prepare_micro_reference(table: pa.Table) -> dict[str, list[Any]]:
    return {name: table[name].combine_chunks().to_pylist() for name in SOURCE_COLUMNS}


def reference_state_valid(values: Mapping[str, Sequence[Any]], index: int) -> bool:
    return bool(
        values["market_state"][index] == "CONTINUOUS_MATCHING"
        and values["state_available"][index]
        and values["book_two_sided"][index]
        and not values["book_locked"][index]
        and not values["book_crossed"][index]
    )


def reference_median(values: Sequence[int | float]) -> float:
    ordered = sorted(float(value) for value in values)
    count = len(ordered)
    if count % 2:
        return ordered[count // 2]
    return (ordered[count // 2 - 1] + ordered[count // 2]) / 2.0


def calculate_micro_reference(
    values: Mapping[str, Sequence[Any]],
    row: Mapping[str, Any],
    source_sha: str,
    decision_ns: int,
    end_count: int,
) -> dict[str, Observation]:
    s60, s900 = end_count - W60, end_count - W900
    require(s900 >= 0 and end_count <= len(values["bucket_end_ns"]), "Anchor outside reference GC block")
    require(int(values["bucket_end_ns"][end_count - 1]) == decision_ns, "Reference GC anchor bucket mismatch")
    indexes60 = list(range(s60, end_count))
    indexes900 = list(range(s900, end_count))
    valid60 = [index for index in indexes60 if reference_state_valid(values, index)]
    valid900 = [index for index in indexes900 if reference_state_valid(values, index)]
    output: dict[str, Observation] = {}

    fid = "CSR_FLOW_QUOTE_OFI_W60"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("quote_ofi_raw", "quote_ofi_transition_count", "state_available", "book_crossed"), W60)
    if len(valid60) < MIN_W60_STATE:
        output[fid] = unknown_observation(fid, AV_W60, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        transitions = sum(int(values["quote_ofi_transition_count"][index]) for index in valid60)
        if transitions <= 0:
            output[fid] = unknown_observation(fid, AV_UNKNOWN_ZERO_DENOM, available_at_ns=decision_ns, lineage_payload=lineage)
        else:
            raw = sum(int(values["quote_ofi_raw"][index]) for index in valid60)
            output[fid] = available_observation(fid, raw / transitions, available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_FLOW_TRADE_IMBALANCE_W60"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("trade_qty_buy", "trade_qty_sell"), W60)
    buy = sum(int(values["trade_qty_buy"][index]) for index in indexes60)
    sell = sum(int(values["trade_qty_sell"][index]) for index in indexes60)
    if buy + sell == 0:
        output[fid] = unknown_observation(fid, AV_UNKNOWN_ZERO_DENOM, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        output[fid] = available_observation(fid, (buy - sell) / (buy + sell), available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_FLOW_DISPLAYED_IMBALANCE_W60"
    cols = ("add_qty_bid", "add_qty_ask", "cancel_qty_bid", "cancel_qty_ask")
    lineage = micro_lineage(source_sha, row, fid, decision_ns, cols, W60)
    totals = {name: sum(int(values[name][index]) for index in indexes60) for name in cols}
    denominator = sum(totals.values())
    if denominator == 0:
        output[fid] = unknown_observation(fid, AV_UNKNOWN_ZERO_DENOM, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        numerator = (totals["add_qty_bid"] + totals["cancel_qty_ask"]) - (totals["add_qty_ask"] + totals["cancel_qty_bid"])
        output[fid] = available_observation(fid, numerator / denominator, available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_BOOK_DEPTH_IMBALANCE_L5_W60"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("depth_imbalance_l5_ppb", "state_available", "book_crossed"), W60)
    depth = [float(values["depth_imbalance_l5_ppb"][index]) for index in valid60 if values["depth_imbalance_l5_ppb"][index] is not None]
    if len(depth) < MIN_W60_STATE:
        output[fid] = unknown_observation(fid, AV_W60, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        output[fid] = available_observation(fid, reference_median(depth), available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_BOOK_MICROPRICE_DISLOCATION_T0"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("microprice_fixed_1e9", "midpoint_fixed_1e9", "spread_fixed_1e9", "state_available", "book_crossed"), 1)
    terminal = end_count - 1
    raw_values = (values["microprice_fixed_1e9"][terminal], values["midpoint_fixed_1e9"][terminal], values["spread_fixed_1e9"][terminal])
    if not reference_state_valid(values, terminal) or any(value is None for value in raw_values):
        output[fid] = unknown_observation(fid, AV_TECH_STATE, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        micro, midpoint, spread = (float(value) for value in raw_values)
        if spread <= 0:
            output[fid] = unknown_observation(fid, AV_SPREAD, available_at_ns=decision_ns, lineage_payload=lineage)
        else:
            output[fid] = available_observation(fid, (micro - midpoint) / spread, available_at_ns=decision_ns, lineage_payload=lineage)

    fid = "CSR_LIQ_SPREAD_FRAGILITY_60_900"
    lineage = micro_lineage(source_sha, row, fid, decision_ns, ("spread_fixed_1e9", "state_available", "book_crossed"), W900)
    spreads60 = [float(values["spread_fixed_1e9"][index]) for index in valid60 if values["spread_fixed_1e9"][index] is not None and float(values["spread_fixed_1e9"][index]) > 0]
    spreads900 = [float(values["spread_fixed_1e9"][index]) for index in valid900 if values["spread_fixed_1e9"][index] is not None and float(values["spread_fixed_1e9"][index]) > 0]
    if len(spreads60) < MIN_W60_STATE:
        output[fid] = unknown_observation(fid, AV_W60, available_at_ns=decision_ns, lineage_payload=lineage)
    elif len(spreads900) < MIN_W900_STATE:
        output[fid] = unknown_observation(fid, AV_W900, available_at_ns=decision_ns, lineage_payload=lineage)
    else:
        med60 = reference_median(spreads60)
        med900 = reference_median(spreads900)
        output[fid] = available_observation(fid, math.log((med60 + GC_TICK_FIXED_1E9) / (med900 + GC_TICK_FIXED_1E9)), available_at_ns=decision_ns, lineage_payload=lineage)
    return output


def canonical_price_bars_primary(bars: Sequence[PriceBar], decision_ns: int) -> list[PriceBar]:
    canonical: dict[int, PriceBar] = {}
    for bar in sorted(bars, key=lambda item: (item.open_ns, item.available_ns, item.record_id)):
        if bar.close_ns <= decision_ns and bar.available_ns <= decision_ns:
            canonical[bar.open_ns] = bar
    return [canonical[key] for key in sorted(canonical)]


def canonical_price_bars_reference(bars: Sequence[PriceBar], decision_ns: int) -> list[PriceBar]:
    eligible = sorted(
        (bar for bar in bars if bar.close_ns <= decision_ns and bar.available_ns <= decision_ns),
        key=lambda item: (item.open_ns, item.available_ns, item.record_id),
    )
    output: list[PriceBar] = []
    for _, group in itertools.groupby(eligible, key=lambda item: item.open_ns):
        output.append(list(group)[-1])
    return output


def aggregate_primary(bars: Sequence[PriceBar], width_ns: int) -> dict[int, AggregateBar]:
    groups: dict[int, list[PriceBar]] = defaultdict(list)
    for bar in bars:
        groups[bar.open_ns - bar.open_ns % width_ns].append(bar)
    output: dict[int, AggregateBar] = {}
    expected = width_ns // ONE_MINUTE_NS
    for start_ns in sorted(groups):
        members = sorted(groups[start_ns], key=lambda item: item.open_ns)
        expected_opens = {start_ns + index * ONE_MINUTE_NS for index in range(expected)}
        actual_opens = {item.open_ns for item in members}
        output[start_ns] = AggregateBar(
            start_ns=start_ns,
            close_ns=start_ns + width_ns,
            open=members[0].open,
            high=max(item.high for item in members),
            low=min(item.low for item in members),
            close=members[-1].close,
            source_hashes=tuple(item.record_hash for item in members),
            maximum_available_ns=max(item.available_ns for item in members),
            member_count=len(members),
            complete=len(members) == expected and actual_opens == expected_opens,
        )
    return output


def aggregate_reference(bars: Sequence[PriceBar], width_ns: int) -> dict[int, AggregateBar]:
    ordered = sorted(bars, key=lambda item: item.open_ns)
    output: dict[int, AggregateBar] = {}
    expected = width_ns // ONE_MINUTE_NS
    for start_ns, iterator in itertools.groupby(ordered, key=lambda item: item.open_ns // width_ns * width_ns):
        members = list(iterator)
        complete = len(members) == expected
        if complete:
            for offset, member in enumerate(members):
                if member.open_ns != start_ns + offset * ONE_MINUTE_NS:
                    complete = False
                    break
        output[start_ns] = AggregateBar(
            start_ns=start_ns,
            close_ns=start_ns + width_ns,
            open=members[0].open,
            high=max(item.high for item in members),
            low=min(item.low for item in members),
            close=members[-1].close,
            source_hashes=tuple(item.record_hash for item in members),
            maximum_available_ns=max(item.available_ns for item in members),
            member_count=len(members),
            complete=complete,
        )
    return output


def atr14(
    hourly: Mapping[int, AggregateBar], decision_ns: int
) -> tuple[Decimal | None, tuple[AggregateBar, ...], str]:
    complete = sorted(
        (bar for bar in hourly.values() if bar.complete and bar.close_ns <= decision_ns),
        key=lambda item: item.close_ns,
    )
    if len(complete) < 15:
        return None, (), AV_ATR
    selected = tuple(complete[-15:])
    earliest, latest = selected[0].start_ns, selected[-1].start_ns
    partial = [
        bar
        for bar in hourly.values()
        if earliest <= bar.start_ns <= latest and 0 < bar.member_count < 60
    ]
    if partial:
        return None, selected, AV_TECH_XAU
    ranges: list[Decimal] = []
    for previous, current in zip(selected, selected[1:]):
        ranges.append(
            max(
                current.high - current.low,
                abs(current.high - previous.close),
                abs(current.low - previous.close),
            )
        )
    result = sum(ranges, Decimal("0")) / Decimal(len(ranges))
    if result <= 0:
        return None, selected, AV_UNKNOWN_NONPOSITIVE
    return result, selected, AV_AVAILABLE


def context_static_primary(projection: Mapping[str, Any], decision_ns: int) -> tuple[Decimal | None, list[tuple[str, Decimal, int]], int | None, str]:
    state = mapping(projection.get("decision_state"))
    asia_fact = nested_primary(state, "layers", "sessions_and_liquidity", "asia_state")
    levels = sequence(state.get("levels"))
    return _static_values(projection, asia_fact, levels, decision_ns)


def context_static_reference(projection: Mapping[str, Any], decision_ns: int) -> tuple[Decimal | None, list[tuple[str, Decimal, int]], int | None, str]:
    state = mapping(projection.get("decision_state"))
    asia_fact = nested_reference(state, "layers.sessions_and_liquidity.asia_state")
    levels = list(sequence(state.get("levels")))
    return _static_values(projection, asia_fact, levels, decision_ns)


def _static_values(
    projection: Mapping[str, Any],
    asia_fact: Mapping[str, Any],
    levels: Sequence[Any],
    decision_ns: int,
) -> tuple[Decimal | None, list[tuple[str, Decimal, int]], int | None, str]:
    asia_range: Decimal | None = None
    maximum_available: int | None = None
    if fact_eligible(asia_fact, decision_ns):
        raw = mapping(asia_fact.get("value")).get("range")
        if number(raw) is not None:
            asia_range = Decimal(str(raw))
            maximum_available = fact_available_ns(asia_fact)
    eligible_levels: list[tuple[str, Decimal, int]] = []
    for raw_level in levels:
        level = mapping(raw_level)
        price_fact = mapping(level.get("price"))
        if not fact_eligible(price_fact, decision_ns):
            continue
        price = number(price_fact.get("value"))
        available = fact_available_ns(price_fact)
        if price is None or available is None:
            continue
        eligible_levels.append((str(level.get("level_id")), Decimal(str(price)), available))
        maximum_available = available if maximum_available is None else max(maximum_available, available)
    signature = canonical_hash(
        {
            "projection_record_hash": projection.get("record_hash"),
            "asia_fact": asia_fact,
            "levels": [(item[0], str(item[1]), item[2]) for item in eligible_levels],
        }
    )
    return asia_range, eligible_levels, maximum_available, signature


def calculate_price_context(
    implementation: str,
    bars: Sequence[PriceBar],
    projection: Mapping[str, Any],
    row: Mapping[str, Any],
    decision_ns: int,
    prepared: PreparedPriceSession | None = None,
) -> dict[str, Observation]:
    if prepared is None and implementation == "primary":
        canonical = canonical_price_bars_primary(bars, decision_ns)
        fifteen = aggregate_primary(canonical, FIFTEEN_MINUTES_NS)
        hourly = aggregate_primary(canonical, ONE_HOUR_NS)
    elif prepared is None:
        canonical = canonical_price_bars_reference(bars, decision_ns)
        fifteen = aggregate_reference(canonical, FIFTEEN_MINUTES_NS)
        hourly = aggregate_reference(canonical, ONE_HOUR_NS)
    else:
        canonical = list(prepared.canonical)
        fifteen = prepared.fifteen
        hourly = prepared.hourly
    if implementation == "primary":
        asia_range, levels, context_available, context_signature = context_static_primary(projection, decision_ns)
    else:
        asia_range, levels, context_available, context_signature = context_static_reference(projection, decision_ns)

    output: dict[str, Observation] = {}
    atr_value, atr_bars, atr_status = atr14(hourly, decision_ns)
    latest_start = (decision_ns - 1) // FIFTEEN_MINUTES_NS * FIFTEEN_MINUTES_NS
    required_starts = [latest_start - offset * FIFTEEN_MINUTES_NS for offset in range(4, -1, -1)]
    momentum_bars = [fifteen.get(value) for value in required_starts]
    fid = "CSR_STRUCTURE_MOMENTUM_15M"
    used_hashes = [source for item in momentum_bars if item is not None for source in item.source_hashes]
    used_hashes.extend(source for item in atr_bars for source in item.source_hashes)
    lineage = {
        "source": "SEALED_XAUUSD_1M",
        "source_sha256": load_json(PROTOCOL)["permitted_sources"]["xauusd_price_bars_sha256"],
        "session_row_id": row["row_id"],
        "decision_at_ns": decision_ns,
        "source_record_hashes": used_hashes,
        "aggregation": "UTC_15M_CONTIGUOUS_AND_SMA_TRUE_RANGE_1H_ATR14",
    }
    if atr_value is None:
        available = max((item.maximum_available_ns for item in atr_bars), default=None)
        output[fid] = unknown_observation(fid, atr_status, available_at_ns=available, lineage_payload=lineage)
    elif any(item is None or not item.complete for item in momentum_bars):
        available = max((item.maximum_available_ns for item in momentum_bars if item is not None), default=None)
        output[fid] = unknown_observation(fid, AV_TECH_XAU, available_at_ns=available, lineage_payload=lineage)
    else:
        concrete = [item for item in momentum_bars if item is not None]
        calculated = (concrete[-1].close - concrete[0].close) / atr_value
        available = max([item.maximum_available_ns for item in concrete] + [item.maximum_available_ns for item in atr_bars])
        output[fid] = available_observation(fid, float(calculated), available_at_ns=available, lineage_payload=lineage)

    fid = "CSR_SESSION_LEVEL_TENSION"
    exact_bar = next((bar for bar in reversed(canonical) if bar.close_ns == decision_ns and bar.open_ns == decision_ns - ONE_MINUTE_NS), None)
    level_lineage = {
        "source": "SEALED_XAUUSD_1M_PLUS_SESSION_OPEN_CONTEXT",
        "source_sha256": load_json(PROTOCOL)["permitted_sources"]["xauusd_price_bars_sha256"],
        "context_signature": context_signature,
        "session_row_id": row["row_id"],
        "decision_at_ns": decision_ns,
        "xau_record_hash": exact_bar.record_hash if exact_bar else None,
        "atr_source_hashes": [source for item in atr_bars for source in item.source_hashes],
    }
    known_available = [value for value in (context_available, exact_bar.available_ns if exact_bar else None) if value is not None]
    if exact_bar is None:
        output[fid] = unknown_observation(fid, AV_TECH_XAU, available_at_ns=max(known_available, default=None), lineage_payload=level_lineage)
    elif atr_value is None:
        output[fid] = unknown_observation(fid, atr_status, available_at_ns=max(known_available, default=None), lineage_payload=level_lineage)
    elif asia_range is None:
        output[fid] = unknown_observation(fid, AV_UNKNOWN_CONTEXT, available_at_ns=max(known_available, default=None), lineage_payload=level_lineage)
    elif not levels:
        output[fid] = unknown_observation(fid, AV_LEVEL, available_at_ns=max(known_available, default=None), lineage_payload=level_lineage)
    else:
        nearest = min(levels, key=lambda item: abs(item[1] - exact_bar.close))
        asia_ratio = max(asia_range / atr_value, Decimal("0"))
        level_ratio = max(abs(nearest[1] - exact_bar.close) / atr_value, Decimal("0"))
        calculated = Decimal("1") / ((Decimal("1") + asia_ratio) * (Decimal("1") + level_ratio))
        available = max([exact_bar.available_ns, nearest[2], *(item.maximum_available_ns for item in atr_bars), *(known_available or [0])])
        level_lineage["nearest_level_id"] = nearest[0]
        output[fid] = available_observation(fid, float(calculated), available_at_ns=available, lineage_payload=level_lineage)
    return output


def prepare_price_session(
    implementation: str, bars: Sequence[PriceBar], last_decision_ns: int
) -> PreparedPriceSession:
    if implementation == "primary":
        canonical = canonical_price_bars_primary(bars, last_decision_ns)
        fifteen = aggregate_primary(canonical, FIFTEEN_MINUTES_NS)
        hourly = aggregate_primary(canonical, ONE_HOUR_NS)
    else:
        canonical = canonical_price_bars_reference(bars, last_decision_ns)
        fifteen = aggregate_reference(canonical, FIFTEEN_MINUTES_NS)
        hourly = aggregate_reference(canonical, ONE_HOUR_NS)
    return PreparedPriceSession(tuple(canonical), fifteen, hourly)


def validate_gc_block(table: pa.Table, row: Mapping[str, Any]) -> dict[str, Any]:
    require(table.num_rows == EXPECTED_SOURCE_ROWS_PER_DATE, "GC block cardinality changed")
    starts = np.asarray(table["bucket_start_ns"].combine_chunks().to_numpy(zero_copy_only=False), dtype=np.int64)
    ends = np.asarray(table["bucket_end_ns"].combine_chunks().to_numpy(zero_copy_only=False), dtype=np.int64)
    expected_start = int(row["window_start_inclusive_ns"])
    expected_starts = expected_start + np.arange(EXPECTED_SOURCE_ROWS_PER_DATE, dtype=np.int64) * ONE_SECOND_NS
    require(np.array_equal(starts, expected_starts), f"GC bucket starts changed: {row['row_id']}")
    require(np.array_equal(ends, expected_starts + ONE_SECOND_NS), f"GC bucket ends changed: {row['row_id']}")
    require(int(ends[-1]) == int(row["window_end_exclusive_ns"]), f"GC block end changed: {row['row_id']}")
    return {
        "rows": table.num_rows,
        "start_ns": int(starts[0]),
        "end_ns": int(ends[-1]),
        "identity_checksum": canonical_hash([int(starts[0]), int(ends[-1]), table.num_rows]),
    }


def validate_session_clock(row: Mapping[str, Any]) -> None:
    opened = parse_dt(str(row["session_open_utc"]))
    timezone = ZoneInfo(str(row["session_timezone"]))
    local = opened.astimezone(timezone)
    require(local.date().isoformat() == str(row["session_date"]), f"DST date mismatch: {row['row_id']}")
    require((local.hour, local.minute, local.second) == (8, 0, 0), f"DST local open mismatch: {row['row_id']}")
    expected_zone = "Europe/London" if row["session_code"] == "LONDON" else "America/New_York"
    require(str(row["session_timezone"]) == expected_zone, f"Session timezone changed: {row['row_id']}")


def anchor_identity(row: Mapping[str, Any], offset: int, block_number: int) -> dict[str, Any]:
    validate_session_clock(row)
    opened = parse_dt(str(row["session_open_utc"]))
    local = opened.astimezone(ZoneInfo(str(row["session_timezone"]))) + timedelta(minutes=offset)
    decision = local.astimezone(UTC)
    require(decision == opened + timedelta(minutes=offset), "DST offset arithmetic differs")
    return {
        "anchor_id": f"CSR_V3:{row['session_date']}:{row['session_code']}:{offset:03d}",
        "session_row_id": str(row["row_id"]),
        "session_date": str(row["session_date"]),
        "session_code": str(row["session_code"]),
        "selected_month_week_id": str(row["selected_month_week_id"]),
        "chronological_block": block_number,
        "anchor_offset_minutes": offset,
        "session_open_ns": dt_ns(opened),
        "decision_at_ns": dt_ns(decision),
    }


def anchor_record(identity: Mapping[str, Any], observations: Mapping[str, Observation]) -> dict[str, Any]:
    require(set(observations) == set(FEATURE_IDS), "Predictor set differs from freeze")
    record = dict(identity)
    for feature_id in FEATURE_IDS:
        item = observations[feature_id]
        record[f"{feature_id}__value"] = item.value
        record[f"{feature_id}__availability"] = item.availability
        record[f"{feature_id}__available_at_ns"] = item.available_at_ns
        record[f"{feature_id}__lineage_hash"] = item.lineage_hash
        if item.available_at_ns is not None:
            require(item.available_at_ns <= int(identity["decision_at_ns"]), f"Future predictor input: {identity['anchor_id']}/{feature_id}")
    return record


class PredictorWriter:
    def __init__(self, output: Path, implementation: str) -> None:
        self.final = {session: output / f"{implementation}_{session.lower()}_anchors.parquet" for session in SESSIONS}
        self.temporary = {session: path.with_suffix(path.suffix + ".tmp") for session, path in self.final.items()}
        for path in (*self.final.values(), *self.temporary.values()):
            require(not path.exists(), f"Refusing to overwrite predictor output: {path}")
        self.writers = {
            session: pq.ParquetWriter(
                self.temporary[session],
                OUTPUT_SCHEMA,
                compression="zstd",
                use_dictionary=False,
                write_statistics=True,
                data_page_version="1.0",
                version="2.6",
            )
            for session in SESSIONS
        }
        self.counts = Counter()

    def write(self, session: str, records: Sequence[Mapping[str, Any]]) -> None:
        require(len(records) == EXPECTED_ANCHORS_PER_DATE, "Session anchor count changed")
        columns = {field.name: [record[field.name] for record in records] for field in OUTPUT_SCHEMA}
        table = pa.Table.from_pydict(columns, schema=OUTPUT_SCHEMA)
        self.writers[session].write_table(table, row_group_size=EXPECTED_ANCHORS_PER_DATE)
        self.counts[session] += table.num_rows

    def close(self) -> None:
        for writer in self.writers.values():
            writer.close()
        for session in SESSIONS:
            require(self.counts[session] == EXPECTED_ANCHORS_PER_SESSION, f"Anchor output count changed: {session}")
            os.replace(self.temporary[session], self.final[session])

    def abort(self) -> None:
        for writer in self.writers.values():
            try:
                writer.close()
            except Exception:
                pass
        for path in self.temporary.values():
            path.unlink(missing_ok=True)


OPEN_TIME_PATTERN = re.compile(r'"open_time"\s*:\s*"([^"]+)"')
HOLDOUT_PATTERN = re.compile(r'"open_time"\s*:\s*"202(?:5|6)-')


def parse_price_bar(record: Mapping[str, Any]) -> PriceBar | None:
    if record.get("timeframe") != "1m" or record.get("instrument_code") != "XAUUSD":
        return None
    opened = parse_dt(str(record["open_time"]))
    closed = parse_dt(str(record["close_time"]))
    available = parse_dt(str(record["available_at"]))
    ohlc = mapping(record.get("ohlc"))
    if (
        not bool(record.get("complete"))
        or closed - opened != timedelta(minutes=1)
        or available > closed
        or any(ohlc.get(name) is None for name in ("open", "high", "low", "close"))
    ):
        return None
    return PriceBar(
        open_ns=dt_ns(opened),
        close_ns=dt_ns(closed),
        available_ns=dt_ns(available),
        open=Decimal(str(ohlc["open"])),
        high=Decimal(str(ohlc["high"])),
        low=Decimal(str(ohlc["low"])),
        close=Decimal(str(ohlc["close"])),
        record_id=str(record["record_id"]),
        record_hash=str(record["record_hash"]),
    )


def source_sha_for(paths: Paths, implementation: str, session: str) -> str:
    return str(load_json(PROTOCOL)["permitted_sources"][f"{implementation}_{session.lower()}_gc_sha256"])


def build_session_records(
    implementation: str,
    row: Mapping[str, Any],
    block_number: int,
    gc_table: pa.Table,
    projection: Mapping[str, Any],
    price_bars: Sequence[PriceBar],
    source_sha: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    validation = validate_gc_block(gc_table, row)
    prepared_primary = prepare_micro_primary(gc_table) if implementation == "primary" else None
    prepared_reference = prepare_micro_reference(gc_table) if implementation == "reference" else None
    last_decision_ns = dt_ns(parse_dt(str(row["session_open_utc"])) + timedelta(minutes=OFFSETS_MINUTES[-1]))
    prepared_price = prepare_price_session(implementation, price_bars, last_decision_ns)
    records: list[dict[str, Any]] = []
    availability = {feature_id: Counter() for feature_id in FEATURE_IDS}
    for offset in OFFSETS_MINUTES:
        identity = anchor_identity(row, offset, block_number)
        decision_ns = int(identity["decision_at_ns"])
        end_count = W900 + offset * 60
        if implementation == "primary":
            assert prepared_primary is not None
            micro = _calculate_micro_numpy(prepared_primary, row, source_sha, decision_ns, end_count)
            macro = extract_macro_primary(projection, decision_ns)
        else:
            assert prepared_reference is not None
            micro = calculate_micro_reference(prepared_reference, row, source_sha, decision_ns, end_count)
            macro = extract_macro_reference(projection, decision_ns)
        price = calculate_price_context(implementation, price_bars, projection, row, decision_ns, prepared_price)
        observations = {**micro, **macro, **price}
        record = anchor_record(identity, observations)
        records.append(record)
        for feature_id, observation in observations.items():
            availability[feature_id][observation.availability] += 1
    return records, {
        "session_row_id": row["row_id"],
        "gc_identity": validation,
        "anchor_count": len(records),
        "availability": {key: dict(sorted(value.items())) for key, value in availability.items()},
        "outcomes_accessed": False,
    }


def worker(paths: Paths, implementation: str) -> None:
    require(implementation in {"primary", "reference"}, implementation)
    frozen = verify_freeze(paths, verify_source_hashes=False)
    rows, block_map = verify_registry_population()
    targets = [(index, row) for index, row in enumerate(rows) if int(row["expected_bucket_rows"]) > 0]
    require(len(targets) == EXPECTED_AVAILABLE_SESSIONS, "Worker target count changed")
    gc_readers = {
        session: FixedBlockReader(paths.gc_file(implementation, session), SOURCE_COLUMNS)
        for session in SESSIONS
    }
    projection_reader = ProjectionReader(paths.context_projection, rows)
    paths.output.mkdir(parents=True, exist_ok=True)
    writer = PredictorWriter(paths.output, implementation)
    price_buffer: deque[PriceBar] = deque()
    target_index = 0
    source_rows_deserialized = 0
    malformed_price_rows = 0
    first_holdout_deserialized = False
    session_diagnostics: list[dict[str, Any]] = []
    per_session = Counter()

    def finalize(registry_index: int, row: Mapping[str, Any]) -> None:
        nonlocal price_buffer
        projection = projection_reader.get(registry_index, row)
        table = gc_readers[str(row["session_code"])].take(EXPECTED_SOURCE_ROWS_PER_DATE)
        relevant = list(price_buffer)
        records, diagnostics = build_session_records(
            implementation,
            row,
            block_map[str(row["selected_month_week_id"])],
            table,
            projection,
            relevant,
            source_sha_for(paths, implementation, str(row["session_code"])),
        )
        writer.write(str(row["session_code"]), records)
        session_diagnostics.append(diagnostics)
        per_session[str(row["session_code"])] += 1
        del table, relevant, records, projection

    try:
        saw_one_minute = False
        with gzip.open(paths.xau_bars, "rt", encoding="utf-8") as handle:
            for line in handle:
                if HOLDOUT_PATTERN.search(line):
                    break
                match = OPEN_TIME_PATTERN.search(line)
                if match:
                    line_open = parse_dt(match.group(1))
                    line_open_ns = dt_ns(line_open)
                    while target_index < len(targets):
                        registry_index, row = targets[target_index]
                        last_decision = dt_ns(parse_dt(str(row["session_open_utc"])) + timedelta(minutes=OFFSETS_MINUTES[-1]))
                        if line_open_ns < last_decision:
                            break
                        finalize(registry_index, row)
                        target_index += 1
                record = json.loads(line)
                if str(record.get("open_time", "")).startswith(("2025-", "2026-")):
                    first_holdout_deserialized = True
                    raise ValueError("A 2025/2026 XAU record was deserialized")
                timeframe = record.get("timeframe")
                if timeframe != "1m":
                    if saw_one_minute:
                        break
                    continue
                saw_one_minute = True
                if record.get("instrument_code") != "XAUUSD":
                    continue
                source_rows_deserialized += 1
                bar = parse_price_bar(record)
                if bar is None:
                    malformed_price_rows += 1
                    continue
                price_buffer.append(bar)
                cutoff = bar.open_ns - int(PRICE_LOOKBACK.total_seconds() * 1_000_000_000)
                while price_buffer and price_buffer[0].open_ns < cutoff:
                    price_buffer.popleft()
                if target_index >= len(targets):
                    break
        require(target_index == len(targets), f"XAU source ended before all targets: {target_index}/{len(targets)}")
        writer.close()
        for reader in gc_readers.values():
            reader.finish(EXPECTED_SOURCE_ROWS_PER_SESSION)
        projection_reader.close()
    except Exception:
        writer.abort()
        projection_reader.close()
        raise

    aggregate_availability = {feature_id: Counter() for feature_id in FEATURE_IDS}
    for item in session_diagnostics:
        for feature_id, counts in item["availability"].items():
            aggregate_availability[feature_id].update(counts)
    diagnostics = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_WORKER_DIAGNOSTICS_V1_0",
        "implementation": implementation,
        "status": "PASS_WORKER_OUTCOME_BLIND_MATERIALIZATION",
        "freeze_receipt": frozen["freeze_receipt"],
        "sessions": dict(sorted(per_session.items())),
        "session_count": sum(per_session.values()),
        "anchor_count": sum(per_session.values()) * EXPECTED_ANCHORS_PER_DATE,
        "gc_rows_consumed": {session: reader.rows_consumed for session, reader in gc_readers.items()},
        "xau_one_minute_rows_deserialized_before_2025": source_rows_deserialized,
        "xau_malformed_or_late_rows_observed": malformed_price_rows,
        "first_2025_or_2026_record_deserialized": first_holdout_deserialized,
        "availability": {feature_id: dict(sorted(counts.items())) for feature_id, counts in aggregate_availability.items()},
        "session_identity_checksum": canonical_hash([item["session_row_id"] for item in session_diagnostics]),
        "session_diagnostics_checksum": canonical_hash(session_diagnostics),
        "outcome_artifacts_opened": False,
        "relationships_candidates_execution_trades_or_pnl_calculated": False,
    }
    write_json_once(paths.output / f"{implementation}_worker_diagnostics.json", diagnostics)
    print(json.dumps({"status": diagnostics["status"], "implementation": implementation, "sessions": diagnostics["session_count"], "anchors": diagnostics["anchor_count"]}, sort_keys=True))


def proc_memory(pid: int) -> tuple[int, int]:
    status = Path(f"/proc/{pid}/status")
    if not status.is_file():
        return 0, 0
    rss = hwm = 0
    for line in status.read_text(encoding="utf-8").splitlines():
        if line.startswith("VmRSS:"):
            rss = int(line.split()[1]) * 1024
        elif line.startswith("VmHWM:"):
            hwm = int(line.split()[1]) * 1024
    return rss, hwm


def run_worker_child(paths: Paths, implementation: str) -> dict[str, Any]:
    stdout_path = paths.output / f"{implementation}_worker.stdout.log"
    stderr_path = paths.output / f"{implementation}_worker.stderr.log"
    command = [
        sys.executable,
        str(Path(__file__)),
        "worker",
        "--implementation",
        implementation,
        "--data-root",
        str(paths.data_root),
        "--output",
        str(paths.output),
    ]
    maximum = 0
    started = time.monotonic()
    with stdout_path.open("wb") as stdout, stderr_path.open("wb") as stderr:
        process = subprocess.Popen(command, stdout=stdout, stderr=stderr)
        while process.poll() is None:
            rss, hwm = proc_memory(process.pid)
            maximum = max(maximum, rss, hwm)
            if maximum >= RSS_GUARD_BYTES:
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait()
                raise MemoryError(f"{implementation} exceeded frozen RSS guard: {maximum}")
            time.sleep(RSS_POLL_SECONDS)
        rss, hwm = proc_memory(process.pid)
        maximum = max(maximum, rss, hwm)
        return_code = process.returncode
    record = {
        "implementation": implementation,
        "command": command,
        "return_code": return_code,
        "maximum_observed_rss_bytes": maximum,
        "rss_guard_bytes": RSS_GUARD_BYTES,
        "formal_rss_cap_bytes": RSS_CAP_BYTES,
        "elapsed_seconds": round(time.monotonic() - started, 3),
        "stdout_sha256": sha256_file(stdout_path),
        "stderr_sha256": sha256_file(stderr_path),
        "status": "PASS_CHILD_RESOURCE_AND_EXIT" if return_code == 0 and maximum < RSS_GUARD_BYTES else "FAIL_CHILD_RESOURCE_OR_EXIT",
    }
    write_json_once(paths.output / f"{implementation}_resource.json", record)
    if return_code != 0:
        tail = stderr_path.read_text(encoding="utf-8", errors="replace")[-4_000:]
        raise RuntimeError(f"{implementation} worker failed ({return_code}): {tail}")
    return record


def run(paths: Paths) -> None:
    frozen = verify_freeze(paths, verify_source_hashes=True)
    require(not paths.output.exists(), f"Refusing to overwrite M2 output: {paths.output}")
    paths.output.mkdir(parents=True, exist_ok=False)
    started = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_ATTEMPT_V1_0",
            "status": "M2_ATTEMPT_STARTED",
            "started_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "primary_reference_sequential": True,
            "outcomes_accessed": False,
            "attempt_receipt": None,
        },
        "attempt_receipt",
    )
    write_json_once(paths.output / "attempt_started.json", started)
    resources: list[dict[str, Any]] = []
    try:
        resources.append(run_worker_child(paths, "primary"))
        resources.append(run_worker_child(paths, "reference"))
    except Exception as exc:
        failure = seal_receipt(
            {
                "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_FAILURE_V1_0",
                "status": "FAIL_V3_M2_MATERIALIZATION_EXECUTION",
                "failed_at_utc": utc_now(),
                "error_type": type(exc).__name__,
                "error": str(exc),
                "completed_resources": resources,
                "outcomes_accessed": False,
                "year_2025_or_2026_values_accessed": False,
                "failure_receipt": None,
            },
            "failure_receipt",
        )
        write_json_once(paths.output / "execution_failure.json", failure)
        raise
    execution = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_EXECUTION_V1_0",
            "status": "PASS_V3_M2_SEQUENTIAL_WORKERS",
            "completed_at_utc": utc_now(),
            "resources": resources,
            "maximum_observed_rss_bytes": max(int(item["maximum_observed_rss_bytes"]) for item in resources),
            "formal_rss_cap_bytes": RSS_CAP_BYTES,
            "primary_reference_sequential": True,
            "outcomes_accessed": False,
            "execution_receipt": None,
        },
        "execution_receipt",
    )
    write_json_once(paths.output / "execution.json", execution)
    print(json.dumps({"status": execution["status"], "maximum_observed_rss_bytes": execution["maximum_observed_rss_bytes"], "next": "seal"}, sort_keys=True))


def normalized_scalar(value: Any) -> Any:
    if value is None:
        return None
    if isinstance(value, float):
        return value.hex()
    if isinstance(value, (np.integer, np.floating)):
        return normalized_scalar(value.item())
    return value


def parquet_fingerprint(path: Path) -> dict[str, Any]:
    parquet = pq.ParquetFile(path)
    require(parquet.schema_arrow == OUTPUT_SCHEMA, f"Output schema differs: {path}")
    table = parquet.read(use_threads=False).combine_chunks()
    column_checksums: dict[str, str] = {}
    values_by_column: dict[str, list[Any]] = {}
    for field in OUTPUT_SCHEMA:
        values = [normalized_scalar(value) for value in table[field.name].to_pylist()]
        values_by_column[field.name] = values
        column_checksums[field.name] = canonical_hash(values)
    rows = [
        [values_by_column[field.name][index] for field in OUTPUT_SCHEMA]
        for index in range(table.num_rows)
    ]
    return {
        "path": str(path),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
        "rows": table.num_rows,
        "row_groups": parquet.num_row_groups,
        "schema_sha256": schema_fingerprint(parquet.schema_arrow),
        "column_checksums": column_checksums,
        "complete_rows_checksum": canonical_hash(rows),
    }


def validate_output_rows(records: Sequence[Mapping[str, Any]], session: str) -> dict[str, Any]:
    require(len(records) == EXPECTED_ANCHORS_PER_SESSION, f"Anchor cardinality differs: {session}")
    identities: list[str] = []
    dates = Counter()
    blocks: set[int] = set()
    future_inputs = 0
    lineage_failures = 0
    value_status_failures = 0
    for record in records:
        require(record["session_code"] == session, "Cross-session row in output")
        identity = str(record["anchor_id"])
        identities.append(identity)
        dates[str(record["session_date"])] += 1
        blocks.add(int(record["chronological_block"]))
        expected_identity = f"CSR_V3:{record['session_date']}:{session}:{int(record['anchor_offset_minutes']):03d}"
        require(identity == expected_identity, f"Anchor identity differs: {identity}")
        for feature_id in FEATURE_IDS:
            availability = str(record[f"{feature_id}__availability"])
            value = record[f"{feature_id}__value"]
            available = record[f"{feature_id}__available_at_ns"]
            lineage = str(record[f"{feature_id}__lineage_hash"])
            if availability not in AVAILABILITY_VALUES or ((availability == AV_AVAILABLE) != (value is not None)):
                value_status_failures += 1
            if available is not None and int(available) > int(record["decision_at_ns"]):
                future_inputs += 1
            if not re.fullmatch(r"[0-9a-f]{64}", lineage):
                lineage_failures += 1
    require(len(set(identities)) == len(identities), "Duplicate anchor identities")
    require(len(dates) == EXPECTED_SESSION_DATES_PER_SESSION, "Session-date count differs")
    require(all(count == EXPECTED_ANCHORS_PER_DATE for count in dates.values()), "Per-date anchor count differs")
    require(blocks == set(range(1, 39)), "Chronological block coverage differs")
    return {
        "anchors": len(records),
        "unique_anchors": len(set(identities)),
        "session_dates": len(dates),
        "blocks": len(blocks),
        "future_input_timestamps": future_inputs,
        "lineage_failures": lineage_failures,
        "value_status_failures": value_status_failures,
        "identity_checksum": canonical_hash(identities),
    }


def read_output_records(path: Path, *, reference_reader: bool) -> list[dict[str, Any]]:
    if not reference_reader:
        return [dict(item) for item in pq.read_table(path, use_threads=False).to_pylist()]
    output: list[dict[str, Any]] = []
    parquet = pq.ParquetFile(path)
    for row_group in range(parquet.num_row_groups):
        batch_table = parquet.read_row_group(row_group, use_threads=False)
        for batch in batch_table.to_batches(max_chunksize=7):
            output.extend(dict(item) for item in pa.Table.from_batches([batch]).to_pylist())
    return output


def known_record(record: Mapping[str, Any], feature_id: str) -> bool:
    return record[f"{feature_id}__availability"] == AV_AVAILABLE and record[f"{feature_id}__value"] is not None


def support_common(records: Sequence[Mapping[str, Any]], mask: Sequence[bool]) -> dict[str, Any]:
    selected = [record for record, eligible in zip(records, mask) if eligible]
    dates = {str(record["session_date"]) for record in selected}
    blocks = {int(record["chronological_block"]) for record in selected}
    folds: dict[str, Any] = {}
    for fold, (start, end) in enumerate(((11, 19), (20, 28), (29, 38)), start=1):
        subset = [record for record in selected if start <= int(record["chronological_block"]) <= end]
        folds[str(fold)] = {
            "block_range": [start, end],
            "dates": len({str(record["session_date"]) for record in subset}),
            "anchors": len(subset),
        }
    years = {
        str(year): len(
            {
                str(record["session_date"])
                for record in selected
                if int(record["chronological_block"]) >= 11 and str(record["session_date"]).startswith(str(year))
            }
        )
        for year in (2022, 2023, 2024)
    }
    return {
        "known_anchors": len(selected),
        "completeness": round(len(selected) / len(records), 8),
        "distinct_dates": len(dates),
        "distinct_blocks": len(blocks),
        "validation_folds": folds,
        "required_year_oof_dates": years,
    }


def ordered_support_gates(common: Mapping[str, Any], completeness_floor: float, positive_dates: int, negative_dates: int) -> dict[str, bool]:
    return {
        "distinct_dates_gte_150": int(common["distinct_dates"]) >= 150,
        "distinct_blocks_gte_30": int(common["distinct_blocks"]) >= 30,
        "completeness_floor": float(common["completeness"]) >= completeness_floor,
        "each_validation_fold_dates_gte_35": all(int(item["dates"]) >= 35 for item in common["validation_folds"].values()),
        "each_validation_fold_anchors_gte_480": all(int(item["anchors"]) >= 480 for item in common["validation_folds"].values()),
        "each_required_year_oof_dates_gte_35": all(int(value) >= 35 for value in common["required_year_oof_dates"].values()),
        "positive_value_dates_gte_40": positive_dates >= 40,
        "negative_value_dates_gte_40": negative_dates >= 40,
    }


def feature_support(records: Sequence[Mapping[str, Any]], feature_id: str) -> dict[str, Any]:
    mask = [known_record(record, feature_id) for record in records]
    common = support_common(records, mask)
    positive_dates = {
        str(record["session_date"])
        for record, eligible in zip(records, mask)
        if eligible and float(record[f"{feature_id}__value"]) > 0
    }
    negative_dates = {
        str(record["session_date"])
        for record, eligible in zip(records, mask)
        if eligible and float(record[f"{feature_id}__value"]) < 0
    }
    gates = ordered_support_gates(common, 0.80, len(positive_dates), len(negative_dates))
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "feature_id": feature_id,
        **common,
        "positive_value_dates": len(positive_dates),
        "negative_value_dates": len(negative_dates),
        "gates": gates,
        "failed_gates": failures,
        "support_status": "SUPPORT_ELIGIBLE" if not failures else "SUPPORT_FAIL",
    }


def transform_center_scale(records: Sequence[Mapping[str, Any]], feature_id: str, train_end_block: int) -> tuple[float, float] | None:
    values = [
        float(record[f"{feature_id}__value"])
        for record in records
        if int(record["chronological_block"]) <= train_end_block and known_record(record, feature_id)
    ]
    if not values:
        return None
    center = float(statistics.median(values))
    deviations = [abs(value - center) for value in values]
    scale = float(statistics.median(deviations))
    if scale == 0:
        scale = float(statistics.pstdev(values)) if len(values) > 1 else 0.0
    if scale == 0 or not math.isfinite(scale):
        return None
    return center, scale


def stage2_interaction_sign_dates(
    records: Sequence[Mapping[str, Any]], interaction: Mapping[str, Any]
) -> tuple[set[str], set[str], int]:
    interaction_id = str(interaction["interaction_id"])
    left = str(interaction["left"])
    right = str(interaction["right"])
    positive: set[str] = set()
    negative: set[str] = set()
    scored = 0
    for train_end, validation_start, validation_end in ((10, 11, 19), (19, 20, 28), (28, 29, 38)):
        left_transform = transform_center_scale(records, left, train_end)
        right_transform = transform_center_scale(records, right, train_end)
        if left_transform is None or right_transform is None:
            continue
        left_center, left_scale = left_transform
        right_center, right_scale = right_transform
        for record in records:
            block = int(record["chronological_block"])
            if not validation_start <= block <= validation_end or not known_record(record, left) or not known_record(record, right):
                continue
            left_value = float(record[f"{left}__value"])
            right_value = float(record[f"{right}__value"])
            z_left = (left_value - left_center) / left_scale
            z_right = (right_value - right_center) / right_scale
            score = 0.0
            if interaction_id in {
                "CSR_INT_OFI_MACRO_CONCORDANCE",
                "CSR_INT_TRADE_MACRO_CONCORDANCE",
                "CSR_INT_DEPTH_REAL_YIELD_CONCORDANCE",
                "CSR_INT_MICROPRICE_USD_CONCORDANCE",
            }:
                if left_value != 0 and right_value != 0 and math.copysign(1.0, left_value) == math.copysign(1.0, right_value):
                    score = math.copysign(min(abs(z_left), abs(z_right)), left_value)
            elif interaction_id == "CSR_INT_OFI_SPREAD_FRAGILITY":
                score = z_left * max(z_right, 0.0)
            elif interaction_id == "CSR_INT_OFI_SESSION_LEVEL_TENSION":
                score = z_left * right_value
            else:
                raise ValueError(f"Unregistered interaction: {interaction_id}")
            if score > 0:
                positive.add(str(record["session_date"]))
                scored += 1
            elif score < 0:
                negative.add(str(record["session_date"]))
                scored += 1
    return positive, negative, scored


def interaction_support(records: Sequence[Mapping[str, Any]], interaction: Mapping[str, Any]) -> dict[str, Any]:
    left, right = str(interaction["left"]), str(interaction["right"])
    mask = [known_record(record, left) and known_record(record, right) for record in records]
    common = support_common(records, mask)
    positive, negative, scored = stage2_interaction_sign_dates(records, interaction)
    gates = ordered_support_gates(common, 0.70, len(positive), len(negative))
    failures = [name for name, passed in gates.items() if not passed]
    return {
        "interaction_id": interaction["interaction_id"],
        "left": left,
        "right": right,
        **common,
        "oof_nonzero_interaction_anchors": scored,
        "positive_value_dates": len(positive),
        "negative_value_dates": len(negative),
        "sign_support_method": "FROZEN_TRAIN_FOLD_ROBUST_CENTER_SCALE_THEN_REGISTERED_INTERACTION_FORMULA_WITHOUT_OUTCOMES",
        "gates": gates,
        "failed_gates": failures,
        "support_status": "SUPPORT_ELIGIBLE" if not failures else "SUPPORT_FAIL",
    }


def support_audit(paths: Paths, implementation: str, *, reference_reader: bool) -> dict[str, Any]:
    models = load_json(MODEL_REGISTRY)
    sessions: dict[str, Any] = {}
    for session in SESSIONS:
        records = read_output_records(paths.output / f"{implementation}_{session.lower()}_anchors.parquet", reference_reader=reference_reader)
        validation = validate_output_rows(records, session)
        stage1 = [feature_support(records, feature_id) for feature_id in STAGE1_IDS]
        stage2 = [interaction_support(records, interaction) for interaction in models["stage2"]["interactions"]]
        sessions[session] = {
            "population": validation,
            "stage1": stage1,
            "stage2": stage2,
            "stage1_support_eligible": sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in stage1),
            "stage1_support_fail": sum(item["support_status"] == "SUPPORT_FAIL" for item in stage1),
            "stage2_support_eligible": sum(item["support_status"] == "SUPPORT_ELIGIBLE" for item in stage2),
            "stage2_support_fail": sum(item["support_status"] == "SUPPORT_FAIL" for item in stage2),
        }
    payload = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_SUPPORT_AUDIT_V1_0",
        "implementation": implementation,
        "reader": "ROW_GROUP_BATCH_REFERENCE" if reference_reader else "WHOLE_TABLE_PRIMARY",
        "status": "PASS_OUTCOME_BLIND_SUPPORT_AUDIT",
        "sessions": sessions,
        "outcomes_opened_or_joined": False,
        "relationships_hit_rates_or_effects_calculated": False,
        "predictor_values_reported": False,
    }
    comparable = dict(payload)
    comparable.pop("implementation")
    comparable.pop("reader")
    payload["audit_checksum"] = canonical_hash(comparable)
    return payload


def artifact_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def normalized_worker_diagnostics(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output.pop("implementation", None)
    return output


def support_summary(audit: Mapping[str, Any]) -> dict[str, Any]:
    return {
        session: {
            key: int(audit["sessions"][session][key])
            for key in (
                "stage1_support_eligible",
                "stage1_support_fail",
                "stage2_support_eligible",
                "stage2_support_fail",
            )
        }
        for session in SESSIONS
    }


def report_text(verdict: Mapping[str, Any], support: Mapping[str, Any], fingerprints: Mapping[str, Any]) -> str:
    lines = [
        "# GC Continuous State-Response V3 — Milestone 2 Report",
        "",
        f"Formal verdict: `{verdict['status']}`",
        "",
        "## Certified population",
        "",
        f"- `{verdict['anchors_total']}` fixed anchors: 2,992 London and 2,992 New York.",
        "- 187 dates per session, 16 fixed anchors per date, and all 38 chronological blocks.",
        "- Exactly 12 frozen continuous predictors; every unavailable value retains its explicit null classification.",
        "",
        "## Reproduction and resource gates",
        "",
        f"- Primary/reference Parquet outputs byte-identical: `{str(verdict['byte_identical_outputs']).lower()}`.",
        f"- Complete-row and per-column semantic checksums exact: `{str(verdict['semantic_reproduction_exact']).lower()}`.",
        f"- Maximum observed worker RSS: `{verdict['maximum_observed_rss_bytes']}` bytes under the 4 GiB cap.",
        "- No development outcome was opened or joined; no 2025/2026 record was deserialized.",
        "",
        "## Outcome-blind support dispositions",
        "",
    ]
    for session in SESSIONS:
        summary = verdict["support_summary"][session]
        lines.append(
            f"- {session}: Stage 1 `{summary['stage1_support_eligible']}` support-eligible and "
            f"`{summary['stage1_support_fail']}` support-fail; Stage 2 `{summary['stage2_support_eligible']}` "
            f"support-eligible and `{summary['stage2_support_fail']}` support-fail."
        )
        for item in support["sessions"][session]["stage1"]:
            lines.append(
                f"  - `{item['feature_id']}`: `{item['support_status']}`, completeness "
                f"`{100 * float(item['completeness']):.2f}%`, known dates `{item['distinct_dates']}`, "
                f"positive/negative dates `{item['positive_value_dates']}/{item['negative_value_dates']}`"
                + (f", failed gates `{', '.join(item['failed_gates'])}`." if item["failed_gates"] else ".")
            )
        for item in support["sessions"][session]["stage2"]:
            lines.append(
                f"  - `{item['interaction_id']}`: `{item['support_status']}`, joint completeness "
                f"`{100 * float(item['completeness']):.2f}%`, positive/negative OOF dates "
                f"`{item['positive_value_dates']}/{item['negative_value_dates']}`"
                + (f", failed gates `{', '.join(item['failed_gates'])}`." if item["failed_gates"] else ".")
            )
    lines.extend(
        [
            "",
            "## Research boundary",
            "",
            "Support counts are predictor-only readiness statistics. No direction, displacement, return, hit rate, effect, candidate, trade, PnL, or edge claim was calculated.",
            "",
            "Milestone 3 remains unauthorized. It is the first milestone that may open the frozen development outcomes once, and only for support-eligible registered tests under the unchanged model registry.",
            "",
            "## Output hashes",
            "",
            f"- London predictor payload: `{fingerprints['primary']['LONDON']['sha256']}`",
            f"- New York predictor payload: `{fingerprints['primary']['NEW_YORK']['sha256']}`",
            "",
        ]
    )
    return "\n".join(lines)


def seal(paths: Paths) -> None:
    frozen = verify_freeze(paths, verify_source_hashes=True)
    execution = load_json(paths.output / "execution.json")
    require(receipt_valid(execution, "execution_receipt"), "Execution receipt invalid")
    require(execution["status"] == "PASS_V3_M2_SEQUENTIAL_WORKERS", "Workers did not complete")
    require(int(execution["maximum_observed_rss_bytes"]) < RSS_CAP_BYTES, "Formal RSS cap failed")

    fingerprints: dict[str, dict[str, Any]] = {implementation: {} for implementation in ("primary", "reference")}
    output_records: dict[str, dict[str, list[dict[str, Any]]]] = {implementation: {} for implementation in ("primary", "reference")}
    population_checks: dict[str, dict[str, Any]] = {implementation: {} for implementation in ("primary", "reference")}
    for implementation in ("primary", "reference"):
        for session in SESSIONS:
            path = paths.output / f"{implementation}_{session.lower()}_anchors.parquet"
            fingerprints[implementation][session] = parquet_fingerprint(path)
            records = read_output_records(path, reference_reader=implementation == "reference")
            output_records[implementation][session] = records
            population_checks[implementation][session] = validate_output_rows(records, session)

    byte_exact = all(
        fingerprints["primary"][session]["sha256"] == fingerprints["reference"][session]["sha256"]
        and fingerprints["primary"][session]["bytes"] == fingerprints["reference"][session]["bytes"]
        for session in SESSIONS
    )
    semantic_exact = all(
        fingerprints["primary"][session]["column_checksums"] == fingerprints["reference"][session]["column_checksums"]
        and fingerprints["primary"][session]["complete_rows_checksum"] == fingerprints["reference"][session]["complete_rows_checksum"]
        for session in SESSIONS
    )
    population_exact = all(population_checks["primary"][session] == population_checks["reference"][session] for session in SESSIONS)

    primary_worker = load_json(paths.output / "primary_worker_diagnostics.json")
    reference_worker = load_json(paths.output / "reference_worker_diagnostics.json")
    worker_exact = normalized_worker_diagnostics(primary_worker) == normalized_worker_diagnostics(reference_worker)
    no_forward = not primary_worker["first_2025_or_2026_record_deserialized"] and not reference_worker["first_2025_or_2026_record_deserialized"]

    primary_support = support_audit(paths, "primary", reference_reader=False)
    reference_support = support_audit(paths, "reference", reference_reader=True)
    write_json_once(paths.output / "primary_support_audit.json", primary_support)
    write_json_once(paths.output / "reference_support_audit.json", reference_support)
    support_exact = primary_support["audit_checksum"] == reference_support["audit_checksum"]

    technical = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_TECHNICAL_CERTIFICATION_V1_0",
        "status": "PASS_TECHNICAL_CERTIFICATION" if all((byte_exact, semantic_exact, population_exact, worker_exact, support_exact, no_forward)) else "FAIL_TECHNICAL_CERTIFICATION",
        "fingerprints": fingerprints,
        "population_checks": population_checks,
        "worker_diagnostics_exact": worker_exact,
        "support_audits_exact": support_exact,
        "byte_identical_outputs": byte_exact,
        "semantic_reproduction_exact": semantic_exact,
        "population_reproduction_exact": population_exact,
        "no_2025_or_2026_record_deserialized": no_forward,
        "output_schema_sha256": schema_fingerprint(OUTPUT_SCHEMA),
        "outcome_columns_present": False,
        "outcomes_opened_or_joined": False,
        "relationships_candidates_execution_or_pnl_calculated": False,
    }
    write_json_once(paths.output / "technical_certification.json", technical)

    gates = {
        "predecessor_and_freeze_seals_intact": True,
        "sealed_sources_hash_verified": True,
        "exact_5984_unique_fixed_anchors": all(
            population_checks[implementation][session]["anchors"] == EXPECTED_ANCHORS_PER_SESSION
            and population_checks[implementation][session]["unique_anchors"] == EXPECTED_ANCHORS_PER_SESSION
            for implementation in ("primary", "reference")
            for session in SESSIONS
        ),
        "exact_187_dates_38_blocks_per_session": all(
            population_checks[implementation][session]["session_dates"] == 187
            and population_checks[implementation][session]["blocks"] == 38
            for implementation in ("primary", "reference")
            for session in SESSIONS
        ),
        "no_future_input_timestamps": all(
            population_checks[implementation][session]["future_input_timestamps"] == 0
            for implementation in ("primary", "reference")
            for session in SESSIONS
        ),
        "complete_field_level_lineage": all(
            population_checks[implementation][session]["lineage_failures"] == 0
            for implementation in ("primary", "reference")
            for session in SESSIONS
        ),
        "value_null_classification_consistent": all(
            population_checks[implementation][session]["value_status_failures"] == 0
            for implementation in ("primary", "reference")
            for session in SESSIONS
        ),
        "primary_reference_worker_diagnostics_exact": worker_exact,
        "primary_reference_semantics_exact": semantic_exact and population_exact,
        "primary_reference_parquet_byte_identical": byte_exact,
        "support_audits_independently_exact": support_exact,
        "maximum_rss_below_4_gib": int(execution["maximum_observed_rss_bytes"]) < RSS_CAP_BYTES,
        "no_2025_or_2026_record_deserialized": no_forward,
        "no_outcomes_relationships_candidates_execution_or_pnl": True,
    }
    passed = all(gates.values())
    status = "PASS_V3_M2_OUTCOME_BLIND_PREDICTOR_MATERIALIZATION" if passed else "FAIL_V3_M2_CERTIFICATION"
    summary = support_summary(primary_support)
    verdict = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_VERDICT_V1_0",
            "status": status,
            "completed_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "anchors_total": EXPECTED_ANCHORS_TOTAL,
            "anchors_per_session": EXPECTED_ANCHORS_PER_SESSION,
            "feature_count": len(FEATURE_IDS),
            "support_summary": summary,
            "byte_identical_outputs": byte_exact,
            "semantic_reproduction_exact": semantic_exact,
            "maximum_observed_rss_bytes": int(execution["maximum_observed_rss_bytes"]),
            "gates": gates,
            "outcomes_accessed_or_joined": False,
            "year_2025_or_2026_values_accessed": False,
            "relationships_candidates_execution_trades_or_pnl_calculated": False,
            "candidate_count": 0,
            "verdict_receipt": None,
        },
        "verdict_receipt",
    )
    write_json_once(paths.output / "verdict.json", verdict)
    write_once(paths.output / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_2_REPORT.md", report_text(verdict, primary_support, fingerprints).encode("utf-8"))

    state = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_STATE_V2_0",
            "active_branch": "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3",
            "completed_milestone": "M2_OUTCOME_BLIND_CONTINUOUS_PREDICTOR_MATERIALIZATION",
            "status": status,
            "candidate_count": 0,
            "development": {"period": "2021-11-08/2024-12-13", "outcomes_locked_until_authorized_m3": True},
            "forward_locks": {"2025": "LOCKED", "2026": "LOCKED"},
            "next_milestone": "M3_ONE_CONTROLLED_DEVELOPMENT_OUTCOME_OPEN_AND_FROZEN_DISCOVERY" if passed else None,
            "next_milestone_authorized": False,
            "m1_final_seal_receipt": EXPECTED_M1_FINAL_SEAL,
            "m2_freeze_receipt": frozen["freeze_receipt"],
            "m2_verdict_receipt": verdict["verdict_receipt"],
            "state_receipt": None,
        },
        "state_receipt",
    )
    write_json_once(paths.output / "state_v02.json", state)

    artifact_names = [
        "attempt_started.json",
        "execution.json",
        "primary_resource.json",
        "reference_resource.json",
        "primary_worker.stdout.log",
        "primary_worker.stderr.log",
        "reference_worker.stdout.log",
        "reference_worker.stderr.log",
        "primary_worker_diagnostics.json",
        "reference_worker_diagnostics.json",
        "primary_london_anchors.parquet",
        "primary_new_york_anchors.parquet",
        "reference_london_anchors.parquet",
        "reference_new_york_anchors.parquet",
        "primary_support_audit.json",
        "reference_support_audit.json",
        "technical_certification.json",
        "verdict.json",
        "state_v02.json",
        "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_2_REPORT.md",
    ]
    artifacts = {name: artifact_record(paths.output / name) for name in artifact_names}
    manifest = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_MANIFEST_V1_0",
            "status": status,
            "sealed_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "verdict_receipt": verdict["verdict_receipt"],
            "state_receipt": state["state_receipt"],
            "artifacts": artifacts,
            "data_acquired": False,
            "charge_incurred_usd": 0.0,
            "outcome_artifacts_accessed": False,
            "year_2025_or_2026_values_accessed": False,
            "manifest_receipt": None,
        },
        "manifest_receipt",
    )
    write_json_once(paths.output / "manifest.json", manifest)
    final = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M2_FINAL_SEAL_V1_0",
            "status": status,
            "sealed_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "verdict_sha256": sha256_file(paths.output / "verdict.json"),
            "state_sha256": sha256_file(paths.output / "state_v02.json"),
            "manifest_sha256": sha256_file(paths.output / "manifest.json"),
            "manifest_receipt": manifest["manifest_receipt"],
            "primary_reference_byte_identical": byte_exact,
            "outcomes_accessed": False,
            "year_2025_or_2026_values_accessed": False,
            "final_seal_receipt": None,
        },
        "final_seal_receipt",
    )
    write_json_once(paths.output / "final_seal.json", final)
    print(json.dumps({"status": status, "support_summary": summary, "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def resolved_artifact(paths: Paths, record: Mapping[str, Any], name: str) -> Path:
    recorded = Path(str(record["path"]))
    return recorded if recorded.is_file() else paths.output / name


def verify(paths: Paths) -> None:
    verify_freeze(paths, verify_source_hashes=True)
    manifest = load_json(paths.output / "manifest.json")
    verdict = load_json(paths.output / "verdict.json")
    state = load_json(paths.output / "state_v02.json")
    final = load_json(paths.output / "final_seal.json")
    require(receipt_valid(manifest, "manifest_receipt"), "M2 manifest receipt invalid")
    require(receipt_valid(verdict, "verdict_receipt"), "M2 verdict receipt invalid")
    require(receipt_valid(state, "state_receipt"), "M2 state receipt invalid")
    require(receipt_valid(final, "final_seal_receipt"), "M2 final seal receipt invalid")
    require(sha256_file(paths.output / "manifest.json") == final["manifest_sha256"], "M2 manifest hash changed")
    require(sha256_file(paths.output / "verdict.json") == final["verdict_sha256"], "M2 verdict hash changed")
    require(sha256_file(paths.output / "state_v02.json") == final["state_sha256"], "M2 state hash changed")
    for name, record in manifest["artifacts"].items():
        path = resolved_artifact(paths, record, name)
        require(path.is_file(), f"Missing sealed M2 artifact: {name}")
        require(path.stat().st_size == int(record["bytes"]), f"M2 artifact size changed: {name}")
        require(sha256_file(path) == record["sha256"], f"M2 artifact hash changed: {name}")
    fingerprints = {
        implementation: {
            session: parquet_fingerprint(paths.output / f"{implementation}_{session.lower()}_anchors.parquet")
            for session in SESSIONS
        }
        for implementation in ("primary", "reference")
    }
    require(
        all(fingerprints["primary"][session]["sha256"] == fingerprints["reference"][session]["sha256"] for session in SESSIONS),
        "M2 Parquet outputs are not byte-identical",
    )
    primary_support = support_audit(paths, "primary", reference_reader=False)
    reference_support = support_audit(paths, "reference", reference_reader=True)
    require(primary_support["audit_checksum"] == reference_support["audit_checksum"], "M2 support reproduction differs")
    require(primary_support == load_json(paths.output / "primary_support_audit.json"), "Primary support audit changed")
    require(reference_support == load_json(paths.output / "reference_support_audit.json"), "Reference support audit changed")
    require(verdict["status"] == "PASS_V3_M2_OUTCOME_BLIND_PREDICTOR_MATERIALIZATION", "M2 did not pass")
    require(state["development"]["outcomes_locked_until_authorized_m3"], "Outcome lock not retained")
    require(state["forward_locks"] == {"2025": "LOCKED", "2026": "LOCKED"}, "Forward locks not retained")
    print(json.dumps({"status": "PASS_V3_M2_INDEPENDENT_VERIFICATION", "verdict": verdict["status"], "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def synthetic_micro_values() -> dict[str, list[Any]]:
    count = 900
    return {
        "bucket_index": list(range(count)),
        "bucket_start_ns": [index * ONE_SECOND_NS for index in range(count)],
        "bucket_end_ns": [(index + 1) * ONE_SECOND_NS for index in range(count)],
        "market_segment": ["REGULAR"] * count,
        "market_state": ["CONTINUOUS_MATCHING"] * count,
        "add_qty_bid": [4] * count,
        "add_qty_ask": [2] * count,
        "cancel_qty_bid": [1] * count,
        "cancel_qty_ask": [3] * count,
        "trade_qty_buy": [3] * count,
        "trade_qty_sell": [1] * count,
        "quote_ofi_transition_count": [2] * count,
        "quote_ofi_raw": [4] * count,
        "state_available": [True] * count,
        "book_two_sided": [True] * count,
        "book_locked": [False] * count,
        "book_crossed": [False] * count,
        "spread_fixed_1e9": [200_000_000] * count,
        "midpoint_fixed_1e9": [2_000_000_000_000] * count,
        "microprice_fixed_1e9": [2_000_050_000_000] * count,
        "depth_imbalance_l5_ppb": [100_000_000] * count,
    }


def self_test() -> None:
    require(len(FEATURE_IDS) == 12 and len(STAGE1_IDS) == 10 and len(MODIFIER_IDS) == 2, "Feature cardinality failed")
    require(len(OUTPUT_SCHEMA) == len(IDENTITY_COLUMNS) + 4 * len(FEATURE_IDS), "Output schema cardinality failed")
    prohibited_columns = {"outcome", "return", "pnl", "trade_id", "entry", "exit", "stop", "target", "r_multiple"}
    require(not any(field.name.lower() in prohibited_columns for field in OUTPUT_SCHEMA), "Prohibited output column")
    values = synthetic_micro_values()
    arrays: dict[str, np.ndarray[Any, Any]] = {}
    for name, items in values.items():
        dtype = object if name in {"market_segment", "market_state"} else bool if name in {"state_available", "book_two_sided", "book_locked", "book_crossed"} else np.int64
        arrays[name] = np.asarray(items, dtype=dtype)
    row = {"row_id": "SYNTHETIC", "session_code": "LONDON"}
    primary = _calculate_micro_numpy(arrays, row, "0" * 64, 900 * ONE_SECOND_NS, 900)
    reference = calculate_micro_reference(values, row, "0" * 64, 900 * ONE_SECOND_NS, 900)
    require(primary == reference, "Synthetic primary/reference micro calculation differs")
    require(primary["CSR_FLOW_QUOTE_OFI_W60"].value == 2.0, "Synthetic OFI formula differs")
    require(primary["CSR_FLOW_TRADE_IMBALANCE_W60"].value == 0.5, "Synthetic trade formula differs")
    require(primary["CSR_FLOW_DISPLAYED_IMBALANCE_W60"].value == 0.4, "Synthetic displayed-flow formula differs")
    values["book_crossed"][-1] = True
    arrays["book_crossed"][-1] = True
    primary_bad = _calculate_micro_numpy(arrays, row, "0" * 64, 900 * ONE_SECOND_NS, 900)
    reference_bad = calculate_micro_reference(values, row, "0" * 64, 900 * ONE_SECOND_NS, 900)
    require(primary_bad == reference_bad, "Synthetic technical latch reproduction differs")
    require(primary_bad["CSR_BOOK_MICROPRICE_DISLOCATION_T0"].availability == AV_TECH_STATE, "T0 latch failed")

    start = datetime(2024, 3, 20, 0, 0, tzinfo=UTC)
    bars = [
        PriceBar(
            open_ns=dt_ns(start + timedelta(minutes=index)),
            close_ns=dt_ns(start + timedelta(minutes=index + 1)),
            available_ns=dt_ns(start + timedelta(minutes=index + 1)),
            open=Decimal("2000") + Decimal(index) / 100,
            high=Decimal("2000.10") + Decimal(index) / 100,
            low=Decimal("1999.90") + Decimal(index) / 100,
            close=Decimal("2000.05") + Decimal(index) / 100,
            record_id=f"B{index}",
            record_hash=hashlib.sha256(f"B{index}".encode()).hexdigest(),
        )
        for index in range(20 * 60)
    ]
    primary_hour = aggregate_primary(canonical_price_bars_primary(bars, dt_ns(start + timedelta(hours=20))), ONE_HOUR_NS)
    reference_hour = aggregate_reference(canonical_price_bars_reference(bars, dt_ns(start + timedelta(hours=20))), ONE_HOUR_NS)
    require(primary_hour == reference_hour, "Synthetic hourly aggregation differs")
    require(atr14(primary_hour, dt_ns(start + timedelta(hours=20))) == atr14(reference_hour, dt_ns(start + timedelta(hours=20))), "Synthetic ATR differs")

    london = {
        "row_id": "S",
        "session_date": "2024-03-20",
        "session_code": "LONDON",
        "session_open_utc": "2024-03-20T08:00:00Z",
        "session_timezone": "Europe/London",
        "selected_month_week_id": "2024-03:SECOND_COMPLETE_CME_WEEK",
    }
    identity = anchor_identity(london, 225, 1)
    require(ns_iso(identity["decision_at_ns"]) == "2024-03-20T11:45:00Z", "Anchor clock failed")
    receipt = seal_receipt({"status": "SYNTHETIC", "receipt": None}, "receipt")
    require(receipt_valid(receipt, "receipt"), "Receipt primitive failed")
    print(json.dumps({"status": "PASS_V3_M2_SELF_TEST", "features": len(FEATURE_IDS), "schema_columns": len(OUTPUT_SCHEMA)}, sort_keys=True))


def build_paths(args: argparse.Namespace) -> Paths:
    data_root = Path(args.data_root)
    output = Path(args.output) if args.output else None
    return Paths.build(data_root, output)


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser()
    result.add_argument("action", choices=("freeze", "run", "worker", "seal", "verify", "self-test"))
    result.add_argument("--data-root", default=str(DEFAULT_DATA_ROOT))
    result.add_argument("--output")
    result.add_argument("--implementation", choices=("primary", "reference"))
    return result


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    paths = build_paths(args)
    if args.action == "self-test":
        self_test()
    elif args.action == "freeze":
        freeze(paths)
    elif args.action == "run":
        run(paths)
    elif args.action == "worker":
        require(args.implementation is not None, "--implementation is required")
        worker(paths, args.implementation)
    elif args.action == "seal":
        seal(paths)
    else:
        verify(paths)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
