#!/usr/bin/env python3
"""Frozen continuous state-response relationship discovery, V3 Milestone 3.

Only ``open-outcomes`` reads XAUUSD values. ``prepare`` is metadata-only and
seals the complete population, join, model, resampling, and decision protocol
before the single authorized development-outcome opening.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import os
import re
import statistics
import sys
import tempfile
from collections import Counter, defaultdict
from copy import deepcopy
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m3_protocol_v01.json"
FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m3_freeze_v01.json"
DOCUMENT = ROOT / "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3_MILESTONE_3.md"
IMPLEMENTATION = Path(__file__).resolve()
TEST_FILE = ROOT / "tests" / "test_gc_continuous_state_response_v3_m3.py"
CONTRACT = ROOT / "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_CONTRACT_V3.md"
FEATURE_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_feature_registry_v01.json"
MODEL_REGISTRY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_model_registry_v01.json"
TRACEABILITY = ROOT / "research_manifests" / "gc_continuous_state_response_v3_traceability_v01.json"
M2_FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_freeze_v01.json"
M2_R1_FREEZE = ROOT / "research_manifests" / "gc_continuous_state_response_v3_m2_r1_freeze_v01.json"

M2_OUTPUT_NAME = "gc_continuous_state_response_v3_m2_v01"
M2_R1_OUTPUT_NAME = "gc_continuous_state_response_v3_m2_r1_v01"
DEFAULT_OUTPUT_NAME = "gc_continuous_state_response_v3_m3_v01"
EXPECTED_M2_FINAL = "cd90cda29077067a84613559abec866bab17d88665384ab81a836efadd663a62"
EXPECTED_R1_FINAL = "b02c5d9337b65c6d5e748180f29c58a9d89ec866aa17d23e9ef2c9fad3dfc8c6"
EXPECTED_ELIGIBLE_REGISTRY = "bda16c3cc7ad6919ed4da8fcf1bdd64ba4c0f4c4e1845eaa4f0a6ce8522eadc0"
EXPECTED_XAU_SHA = "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"

SESSIONS = ("LONDON", "NEW_YORK")
HORIZONS = (5, 15, 30, 60)
PRIMARY_HORIZON = 15
OFFSETS = tuple(range(0, 226, 15))
FOLDS = ((1, 10, 11, 19), (2, 19, 20, 28), (3, 28, 29, 38))
OOF_YEARS = (2022, 2023, 2024)
XAU_SCALE = 1_000_000_000
ONE_MINUTE_NS = 60_000_000_000
BOOTSTRAP_REPETITIONS = 20_000
PERMUTATION_REPETITIONS = 100_000
MINIMUM_FINITE_BOOTSTRAPS = 19_000
EXPECTED_ANCHORS = 5_984
EXPECTED_SESSION_ANCHORS = 2_992
EXPECTED_DATES = 187

FEATURE_IDS = (
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
    "CSR_LIQ_SPREAD_FRAGILITY_60_900",
    "CSR_SESSION_LEVEL_TENSION",
)
EXPECTED_STAGE1 = (
    "CSR_FLOW_QUOTE_OFI_W60",
    "CSR_FLOW_TRADE_IMBALANCE_W60",
    "CSR_FLOW_DISPLAYED_IMBALANCE_W60",
    "CSR_BOOK_DEPTH_IMBALANCE_L5_W60",
    "CSR_BOOK_MICROPRICE_DISLOCATION_T0",
    "CSR_MACRO_ENGINE_SCORE",
    "CSR_MACRO_REAL_YIELD_SUPPORT",
    "CSR_MACRO_USD_SUPPORT",
    "CSR_MACRO_2Y_SUPPORT",
)
EXPECTED_STAGE2 = (
    "CSR_INT_OFI_MACRO_CONCORDANCE",
    "CSR_INT_TRADE_MACRO_CONCORDANCE",
    "CSR_INT_DEPTH_REAL_YIELD_CONCORDANCE",
    "CSR_INT_MICROPRICE_USD_CONCORDANCE",
    "CSR_INT_OFI_SPREAD_FRAGILITY",
)
EXPECTED_STAGE1_FAIL = ("CSR_STRUCTURE_MOMENTUM_15M",)
EXPECTED_STAGE2_FAIL = ("CSR_INT_OFI_SESSION_LEVEL_TENSION",)
AV_AVAILABLE = "AVAILABLE"

META_COLUMNS = (
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

OUTCOME_FIELDS = tuple(
    field
    for horizon in HORIZONS
    for field in (
        pa.field(f"outcome_{horizon}m_displacement_fixed_1e9", pa.int64(), nullable=True),
        pa.field(f"outcome_{horizon}m_quality", pa.string(), nullable=False),
        pa.field(f"outcome_{horizon}m_endpoint_available_at_ns", pa.int64(), nullable=True),
        pa.field(f"outcome_{horizon}m_lineage_hash", pa.string(), nullable=False),
    )
) + (pa.field("outcome_lineage_hash", pa.string(), nullable=False),)

OPEN_TEXT = re.compile(r'"open_time"\s*:\s*"([^"\\]*)"')
CLOSE_TEXT = re.compile(r'"close_time"\s*:\s*"([^"\\]*)"')
AVAILABLE_TEXT = re.compile(r'"available_at"\s*:\s*"([^"\\]*)"')
TIMEFRAME_TEXT = re.compile(r'"timeframe"\s*:\s*"([^"\\]*)"')
INSTRUMENT_TEXT = re.compile(r'"instrument_code"\s*:\s*"([^"\\]*)"')
COMPLETE_TEXT = re.compile(r'"complete"\s*:\s*(true|false)')
OPEN_BYTES = re.compile(rb'"open_time"\s*:\s*"([^"\\]*)"')
CLOSE_BYTES = re.compile(rb'"close_time"\s*:\s*"([^"\\]*)"')
AVAILABLE_BYTES = re.compile(rb'"available_at"\s*:\s*"([^"\\]*)"')
TIMEFRAME_BYTES = re.compile(rb'"timeframe"\s*:\s*"([^"\\]*)"')
INSTRUMENT_BYTES = re.compile(rb'"instrument_code"\s*:\s*"([^"\\]*)"')
COMPLETE_BYTES = re.compile(rb'"complete"\s*:\s*(true|false)')


class DiscoveryFailure(RuntimeError):
    """Formal protocol or execution failure."""


def require(condition: bool, message: str) -> None:
    if not condition:
        raise DiscoveryFailure(message)


def utc_now() -> str:
    return datetime.now(tz=UTC).isoformat().replace("+00:00", "Z")


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False, allow_nan=False)


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    require(isinstance(value, dict), f"Expected JSON object: {path}")
    return value


def write_json_once(path: Path, value: Mapping[str, Any]) -> None:
    require(not path.exists(), f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def write_text_once(path: Path, value: str) -> None:
    require(not path.exists(), f"Refusing to overwrite: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(value, encoding="utf-8", newline="\n")


def seal_receipt(value: Mapping[str, Any], field: str) -> dict[str, Any]:
    output = dict(value)
    output[field] = None
    output[field] = canonical_hash(output)
    return output


def receipt_valid(value: Mapping[str, Any], field: str) -> bool:
    expected = value.get(field)
    if not isinstance(expected, str):
        return False
    candidate = dict(value)
    candidate[field] = None
    return canonical_hash(candidate) == expected


def rounded(value: float | None, digits: int = 12) -> float | None:
    if value is None or not math.isfinite(float(value)):
        return None
    result = round(float(value), digits)
    return 0.0 if result == 0 else result


def parse_dt(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    require(parsed.tzinfo is not None, f"Naive timestamp: {value}")
    return parsed.astimezone(UTC)


def iso_ns(value: int) -> str:
    seconds, nanos = divmod(int(value), 1_000_000_000)
    parsed = datetime.fromtimestamp(seconds, tz=UTC)
    if nanos:
        return parsed.strftime("%Y-%m-%dT%H:%M:%S") + f".{nanos:09d}Z"
    return parsed.strftime("%Y-%m-%dT%H:%M:%SZ")


def dt_ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def schema_fingerprint(schema: pa.Schema) -> str:
    return canonical_hash([{"name": field.name, "type": str(field.type), "nullable": field.nullable} for field in schema])


def artifact_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def seed_for(session: str, stage: int, test_id: str, method: str) -> int:
    material = f"GC_CSR_V3_M3|{session}|{stage}|{test_id}|{method}".encode("utf-8")
    return int.from_bytes(hashlib.sha256(material).digest()[:8], "big", signed=False)


@dataclass(frozen=True, slots=True)
class Paths:
    data_root: Path
    m2_output: Path
    r1_output: Path
    output: Path
    xau_source: Path

    @classmethod
    def build(
        cls,
        data_root: Path,
        output: Path | None = None,
        m2_output: Path | None = None,
        r1_output: Path | None = None,
    ) -> "Paths":
        remote_artifacts = data_root / "artifacts"
        local_artifacts = ROOT / "research_artifacts"
        artifacts = remote_artifacts if (remote_artifacts / M2_OUTPUT_NAME).is_dir() else local_artifacts
        inferred_output = artifacts / DEFAULT_OUTPUT_NAME
        return cls(
            data_root=data_root,
            m2_output=m2_output or artifacts / M2_OUTPUT_NAME,
            r1_output=r1_output or artifacts / M2_R1_OUTPUT_NAME,
            output=output or inferred_output,
            xau_source=data_root / "data" / "gold_casebook_v01" / "price_bars.jsonl.gz",
        )


def verify_sealed_directory(
    directory: Path,
    *,
    expected_status: str,
    expected_final_receipt: str,
) -> dict[str, Any]:
    final_path = directory / "final_seal.json"
    manifest_path = directory / "manifest.json"
    verdict_path = directory / "verdict.json"
    require(final_path.is_file() and manifest_path.is_file() and verdict_path.is_file(), f"Sealed boundary missing: {directory}")
    final = load_json(final_path)
    manifest = load_json(manifest_path)
    verdict = load_json(verdict_path)
    require(receipt_valid(final, "final_seal_receipt"), f"Final receipt invalid: {directory}")
    require(receipt_valid(manifest, "manifest_receipt"), f"Manifest receipt invalid: {directory}")
    require(receipt_valid(verdict, "verdict_receipt"), f"Verdict receipt invalid: {directory}")
    require(final["final_seal_receipt"] == expected_final_receipt, f"Final seal changed: {directory}")
    require(verdict["status"] == expected_status, f"Verdict status changed: {directory}")
    require(final["manifest_sha256"] == sha256_file(manifest_path), f"Manifest hash changed: {directory}")
    require(final["verdict_sha256"] == sha256_file(verdict_path), f"Verdict hash changed: {directory}")
    for name, expected in manifest["artifacts"].items():
        path = directory / name
        require(path.is_file(), f"Sealed artifact missing: {path}")
        require(path.stat().st_size == int(expected["bytes"]), f"Sealed artifact size changed: {path}")
        require(sha256_file(path) == expected["sha256"], f"Sealed artifact hash changed: {path}")
    return {
        "status": verdict["status"],
        "final_seal_receipt": final["final_seal_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "verdict_receipt": verdict["verdict_receipt"],
        "final_sha256": sha256_file(final_path),
        "manifest_sha256": sha256_file(manifest_path),
        "verdict_sha256": sha256_file(verdict_path),
    }


def verify_predecessors(paths: Paths, *, require_source: bool) -> dict[str, Any]:
    m2 = verify_sealed_directory(
        paths.m2_output,
        expected_status="PASS_V3_M2_OUTCOME_BLIND_PREDICTOR_MATERIALIZATION",
        expected_final_receipt=EXPECTED_M2_FINAL,
    )
    r1 = verify_sealed_directory(
        paths.r1_output,
        expected_status="PASS_V3_M2_R1_SUPPORT_FEASIBILITY_AND_SOURCE_COVERAGE_DISPOSITION",
        expected_final_receipt=EXPECTED_R1_FINAL,
    )
    eligible_path = paths.r1_output / "eligible_test_registry.json"
    eligible = load_json(eligible_path)
    require(receipt_valid(eligible, "registry_receipt"), "Eligible registry receipt invalid")
    require(eligible["registry_receipt"] == EXPECTED_ELIGIBLE_REGISTRY, "Eligible registry changed")
    for session in SESSIONS:
        item = eligible["sessions"][session]
        require(tuple(item["stage1_support_eligible"]) == EXPECTED_STAGE1, f"Stage-1 eligible registry changed: {session}")
        require(tuple(item["stage2_support_eligible"]) == EXPECTED_STAGE2, f"Stage-2 eligible registry changed: {session}")
        require(tuple(item["stage1_support_fail"]) == EXPECTED_STAGE1_FAIL, f"Stage-1 support failure changed: {session}")
        require(tuple(item["stage2_support_fail"]) == EXPECTED_STAGE2_FAIL, f"Stage-2 support failure changed: {session}")
    m2_freeze = load_json(M2_FREEZE)
    r1_freeze = load_json(M2_R1_FREEZE)
    require(receipt_valid(m2_freeze, "freeze_receipt"), "M2 freeze invalid")
    require(receipt_valid(r1_freeze, "freeze_receipt"), "M2-R1 freeze invalid")
    source = m2_freeze["source_records"]["xauusd_price_bars"]
    require(source["sha256"] == EXPECTED_XAU_SHA, "XAU source identity changed")
    if require_source:
        require(paths.xau_source.is_file(), "Sealed XAUUSD source missing")
        require(paths.xau_source.stat().st_size == int(source["bytes"]), "XAU source size changed")
        require(sha256_file(paths.xau_source) == source["sha256"], "XAU source hash changed")
    return {
        "m2": m2,
        "m2_r1": r1,
        "eligible_registry_sha256": sha256_file(eligible_path),
        "eligible_registry_receipt": eligible["registry_receipt"],
        "m2_freeze_sha256": sha256_file(M2_FREEZE),
        "m2_r1_freeze_sha256": sha256_file(M2_R1_FREEZE),
        "xau_source_sha256": source["sha256"],
        "xau_source_bytes": int(source["bytes"]),
    }


def read_metadata(path: Path, *, reference: bool) -> tuple[list[dict[str, Any]], pa.Schema]:
    parquet = pq.ParquetFile(path)
    require(set(META_COLUMNS).issubset(parquet.schema_arrow.names), f"Anchor metadata schema changed: {path}")
    if not reference:
        rows = pq.read_table(path, columns=list(META_COLUMNS), use_threads=False).to_pylist()
    else:
        rows: list[dict[str, Any]] = []
        for group_index in range(parquet.num_row_groups):
            table = parquet.read_row_group(group_index, columns=list(META_COLUMNS), use_threads=False)
            for batch in table.to_batches(max_chunksize=7):
                rows.extend(pa.Table.from_batches([batch]).to_pylist())
    return [dict(row) for row in rows], parquet.schema_arrow


def required_open_ns(decision_ns: int) -> tuple[int, ...]:
    return (decision_ns - ONE_MINUTE_NS, *tuple(decision_ns + minute * ONE_MINUTE_NS for minute in range(60)))


def population_registry(paths: Paths) -> tuple[dict[str, Any], pa.Schema]:
    primary: list[dict[str, Any]] = []
    reference: list[dict[str, Any]] = []
    full_schema: pa.Schema | None = None
    for session in SESSIONS:
        p_rows, p_schema = read_metadata(paths.m2_output / f"primary_{session.lower()}_anchors.parquet", reference=False)
        r_rows, r_schema = read_metadata(paths.m2_output / f"reference_{session.lower()}_anchors.parquet", reference=True)
        require(p_schema == r_schema, f"Predictor schemas differ: {session}")
        if full_schema is None:
            full_schema = p_schema
        else:
            require(full_schema == p_schema, "Cross-session predictor schemas differ")
        primary.extend(p_rows)
        reference.extend(r_rows)
    require(primary == reference, "Primary/reference anchor metadata differ")
    primary.sort(key=lambda row: (str(row["session_code"]), str(row["session_date"]), int(row["anchor_offset_minutes"])))
    require(len(primary) == EXPECTED_ANCHORS, "Anchor population cardinality changed")
    identities: list[str] = []
    date_counts = Counter()
    entries: list[dict[str, Any]] = []
    for row in primary:
        session = str(row["session_code"])
        date = str(row["session_date"])
        offset = int(row["anchor_offset_minutes"])
        decision = int(row["decision_at_ns"])
        expected_id = f"CSR_V3:{date}:{session}:{offset:03d}"
        require(str(row["anchor_id"]) == expected_id, f"Anchor identity changed: {row['anchor_id']}")
        require(offset in OFFSETS, f"Anchor offset changed: {expected_id}")
        opened = datetime.fromtimestamp(int(row["session_open_ns"]) / 1_000_000_000, tz=UTC)
        zone = ZoneInfo("Europe/London" if session == "LONDON" else "America/New_York")
        local = opened.astimezone(zone)
        require(local.date().isoformat() == date and (local.hour, local.minute) == (8, 0), f"DST/session conversion changed: {expected_id}")
        require(decision == int(row["session_open_ns"]) + offset * ONE_MINUTE_NS, f"Decision timestamp changed: {expected_id}")
        opens = required_open_ns(decision)
        identities.append(expected_id)
        date_counts[(session, date)] += 1
        entries.append(
            {
                "anchor_id": expected_id,
                "session_row_id": str(row["session_row_id"]),
                "session_code": session,
                "session_date": date,
                "selected_month_week_id": str(row["selected_month_week_id"]),
                "chronological_block": int(row["chronological_block"]),
                "anchor_offset_minutes": offset,
                "session_open_ns": int(row["session_open_ns"]),
                "decision_at_ns": decision,
                "required_open_count": len(opens),
                "required_open_timestamp_checksum": canonical_hash(list(opens)),
            }
        )
    require(len(set(identities)) == EXPECTED_ANCHORS, "Duplicate anchor identities")
    require(all(value == len(OFFSETS) for value in date_counts.values()), "Per-date anchor cardinality changed")
    require(sum(1 for key in date_counts if key[0] == "LONDON") == EXPECTED_DATES, "London date count changed")
    require(sum(1 for key in date_counts if key[0] == "NEW_YORK") == EXPECTED_DATES, "New York date count changed")
    assert full_schema is not None
    join_schema = pa.schema([*full_schema, *OUTCOME_FIELDS])
    payload = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_POPULATION_V1_0",
            "status": "FROZEN_PRE_OUTCOME_POPULATION",
            "anchors": entries,
            "anchor_count": len(entries),
            "anchor_identity_checksum": canonical_hash(identities),
            "required_timestamp_union_count": len({stamp for row in entries for stamp in required_open_ns(int(row["decision_at_ns"]))}),
            "predictor_schema_sha256": schema_fingerprint(full_schema),
            "joined_schema_sha256": schema_fingerprint(join_schema),
            "outcome_values_accessed": False,
            "population_receipt": None,
        },
        "population_receipt",
    )
    return payload, full_schema


def _match_text(pattern: re.Pattern[str], line: str) -> str | None:
    match = pattern.search(line)
    return match.group(1) if match else None


def _match_bytes(pattern: re.Pattern[bytes], line: bytes) -> str | None:
    match = pattern.search(line)
    return match.group(1).decode("ascii") if match else None


def metadata_coverage_scan(
    path: Path, targets: set[int], *, reference: bool
) -> tuple[dict[str, Any], set[int]]:
    valid_counts = Counter()
    invalid_counts = Counter()
    source_rows = selected_rows = 0
    if not reference:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                opened_raw = _match_text(OPEN_TEXT, line)
                if opened_raw is None:
                    continue
                if opened_raw.startswith(("2025-", "2026-")):
                    break
                if _match_text(TIMEFRAME_TEXT, line) != "1m" or _match_text(INSTRUMENT_TEXT, line) != "XAUUSD":
                    continue
                source_rows += 1
                opened = dt_ns(parse_dt(opened_raw))
                if opened not in targets:
                    continue
                selected_rows += 1
                close_raw = _match_text(CLOSE_TEXT, line)
                available_raw = _match_text(AVAILABLE_TEXT, line)
                complete = COMPLETE_TEXT.search(line)
                valid = (
                    close_raw is not None
                    and available_raw is not None
                    and complete is not None
                    and complete.group(1) == "true"
                    and parse_dt(close_raw) == parse_dt(opened_raw) + timedelta(minutes=1)
                    and parse_dt(available_raw) <= parse_dt(close_raw)
                )
                (valid_counts if valid else invalid_counts)[opened] += 1
    else:
        with gzip.open(path, "rb") as handle:
            for line in handle:
                opened_raw = _match_bytes(OPEN_BYTES, line)
                if opened_raw is None:
                    continue
                if opened_raw.startswith(("2025-", "2026-")):
                    break
                if _match_bytes(TIMEFRAME_BYTES, line) != "1m" or _match_bytes(INSTRUMENT_BYTES, line) != "XAUUSD":
                    continue
                source_rows += 1
                opened = dt_ns(parse_dt(opened_raw))
                if opened not in targets:
                    continue
                selected_rows += 1
                close_raw = _match_bytes(CLOSE_BYTES, line)
                available_raw = _match_bytes(AVAILABLE_BYTES, line)
                complete = COMPLETE_BYTES.search(line)
                valid = (
                    close_raw is not None
                    and available_raw is not None
                    and complete is not None
                    and complete.group(1) == b"true"
                    and parse_dt(close_raw) == parse_dt(opened_raw) + timedelta(seconds=60)
                    and parse_dt(available_raw) <= parse_dt(close_raw)
                )
                (valid_counts if valid else invalid_counts)[opened] += 1
    missing = sorted(targets.difference(valid_counts))
    nonunique = sorted(stamp for stamp, count in valid_counts.items() if count != 1)
    invalid = sorted(stamp for stamp, count in invalid_counts.items() if count)
    valid_unique = {stamp for stamp, count in valid_counts.items() if count == 1 and invalid_counts.get(stamp, 0) == 0}
    payload = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_METADATA_COVERAGE_V1_0",
        "reader": "BINARY_REGEX_REFERENCE" if reference else "TEXT_REGEX_PRIMARY",
        "status": "COMPLETE_METADATA_ONLY_OUTCOME_WINDOW_AUDIT",
        "target_timestamp_count": len(targets),
        "source_xau_1m_rows_before_2025_lock": source_rows,
        "selected_source_rows": selected_rows,
        "valid_unique_target_timestamps": sum(count == 1 for count in valid_counts.values()),
        "missing_target_timestamps": len(missing),
        "nonunique_target_timestamps": len(nonunique),
        "invalid_target_timestamps": len(invalid),
        "missing_timestamp_checksum": canonical_hash(missing),
        "nonunique_timestamp_checksum": canonical_hash(nonunique),
        "invalid_timestamp_checksum": canonical_hash(invalid),
        "valid_timestamp_count_checksum": canonical_hash(sorted((stamp, count) for stamp, count in valid_counts.items())),
        "valid_unique_timestamp_checksum": canonical_hash(sorted(valid_unique)),
        "ohlc_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    comparable = dict(payload)
    comparable.pop("reader")
    payload["coverage_checksum"] = canonical_hash(comparable)
    return payload, valid_unique


def coverage_comparable(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output.pop("reader", None)
    output.pop("coverage_checksum", None)
    return output


def required_horizon_open_ns(decision_ns: int, horizon: int) -> tuple[int, ...]:
    return (
        decision_ns - ONE_MINUTE_NS,
        *tuple(decision_ns + minute * ONE_MINUTE_NS for minute in range(horizon)),
    )


def outcome_metadata_support(
    anchors: Sequence[Mapping[str, Any]], horizon: int
) -> dict[str, Any]:
    sessions: dict[str, Any] = {}
    for session in SESSIONS:
        population = [anchor for anchor in anchors if anchor["session_code"] == session]
        available = [anchor for anchor in population if anchor[f"outcome_{horizon}m_metadata_available"]]
        folds: dict[str, Any] = {}
        for fold, _, start, end in FOLDS:
            selected = [anchor for anchor in available if start <= int(anchor["chronological_block"]) <= end]
            folds[str(fold)] = {
                "anchors": len(selected),
                "dates": len({str(anchor["session_date"]) for anchor in selected}),
            }
        years: dict[str, Any] = {}
        for year in OOF_YEARS:
            denominator_dates = {
                str(anchor["session_date"])
                for anchor in population
                if int(anchor["chronological_block"]) >= 11 and str(anchor["session_date"]).startswith(str(year))
            }
            numerator_dates = {
                str(anchor["session_date"])
                for anchor in available
                if int(anchor["chronological_block"]) >= 11 and str(anchor["session_date"]).startswith(str(year))
            }
            minimum = math.ceil(0.8 * len(denominator_dates))
            years[str(year)] = {
                "numerator_available_dates": len(numerator_dates),
                "denominator_frozen_oof_dates": len(denominator_dates),
                "minimum_required_dates": minimum,
                "coverage_fraction": rounded(len(numerator_dates) / len(denominator_dates) if denominator_dates else None, 8),
                "pass": bool(denominator_dates) and len(numerator_dates) >= minimum,
            }
        distinct_dates = len({str(anchor["session_date"]) for anchor in available})
        distinct_blocks = len({int(anchor["chronological_block"]) for anchor in available})
        completeness = len(available) / len(population)
        gates = {
            "anchor_completeness_gte_0_80": completeness >= 0.80,
            "distinct_dates_gte_150": distinct_dates >= 150,
            "distinct_blocks_gte_30": distinct_blocks >= 30,
            "each_validation_fold_dates_gte_35": all(item["dates"] >= 35 for item in folds.values()),
            "each_validation_fold_anchors_gte_480": all(item["anchors"] >= 480 for item in folds.values()),
            "each_required_year_oof_coverage_gte_80pct": all(item["pass"] for item in years.values()),
        }
        sessions[session] = {
            "anchors": len(population),
            "available_anchors": len(available),
            "unavailable_anchors": len(population) - len(available),
            "completeness": rounded(completeness, 8),
            "distinct_dates": distinct_dates,
            "distinct_blocks": distinct_blocks,
            "validation_folds": folds,
            "required_years": years,
            "gates": gates,
            "readiness_pass": all(gates.values()),
        }
    return {
        "horizon_minutes": horizon,
        "sessions": sessions,
        "primary_readiness_gate_applies": horizon == PRIMARY_HORIZON,
        "all_sessions_pass": all(item["readiness_pass"] for item in sessions.values()),
    }


def attach_outcome_metadata(
    population: Mapping[str, Any], valid_timestamps: set[int]
) -> dict[str, Any]:
    anchors = deepcopy(population["anchors"])
    for anchor in anchors:
        decision = int(anchor["decision_at_ns"])
        for horizon in HORIZONS:
            required = required_horizon_open_ns(decision, horizon)
            missing = sorted(set(required).difference(valid_timestamps))
            anchor[f"outcome_{horizon}m_metadata_available"] = not missing
            anchor[f"outcome_{horizon}m_missing_timestamp_count"] = len(missing)
            anchor[f"outcome_{horizon}m_missing_timestamp_checksum"] = canonical_hash(missing)
    support = {str(horizon): outcome_metadata_support(anchors, horizon) for horizon in HORIZONS}
    require(support["15"]["all_sessions_pass"], "Primary 15m outcome metadata support gates failed")
    base = dict(population)
    base["version"] = "GC_CSR_EDGE_DISCOVERY_V3_M3_POPULATION_V1_1"
    base["anchors"] = anchors
    base["source_valid_unique_timestamp_count"] = len(valid_timestamps)
    base["source_valid_unique_timestamp_checksum"] = canonical_hash(sorted(valid_timestamps))
    base["outcome_metadata_support"] = support
    base["population_receipt"] = None
    return seal_receipt(base, "population_receipt")


def decimal_to_scaled(value: Any) -> int:
    decimal = Decimal(str(value))
    scaled = decimal * Decimal(XAU_SCALE)
    integral = scaled.to_integral_value(rounding=ROUND_HALF_UP)
    require(scaled == integral, f"XAUUSD close exceeds frozen 1e9 scale: {value}")
    return int(integral)


def outcome_fields(decision_ns: int, bars: Mapping[int, Mapping[str, Any]], source_sha: str) -> dict[str, Any]:
    start = bars.get(decision_ns - ONE_MINUTE_NS)
    start_valid = start is not None and int(start["available_at_ns"]) <= decision_ns
    result: dict[str, Any] = {}
    horizon_lineages: dict[str, Any] = {}
    for horizon in HORIZONS:
        path = [bars.get(decision_ns + minute * ONE_MINUTE_NS) for minute in range(horizon)]
        complete = start_valid and all(
            item is not None
            and int(item["available_at_ns"]) <= decision_ns + (minute + 1) * ONE_MINUTE_NS
            for minute, item in enumerate(path)
        )
        if not complete:
            result[f"outcome_{horizon}m_displacement_fixed_1e9"] = None
            result[f"outcome_{horizon}m_quality"] = "UNKNOWN_MISSING_INVALID_OR_NONUNIQUE_PATH"
            result[f"outcome_{horizon}m_endpoint_available_at_ns"] = None
            result[f"outcome_{horizon}m_lineage_hash"] = canonical_hash({"horizon": horizon, "status": "UNKNOWN"})
            horizon_lineages[str(horizon)] = result[f"outcome_{horizon}m_lineage_hash"]
            continue
        assert start is not None
        concrete = [item for item in path if item is not None]
        endpoint = concrete[-1]
        result[f"outcome_{horizon}m_displacement_fixed_1e9"] = int(endpoint["close_scaled"]) - int(start["close_scaled"])
        result[f"outcome_{horizon}m_quality"] = "VALID_EXACT_CONTIGUOUS_PATH"
        result[f"outcome_{horizon}m_endpoint_available_at_ns"] = int(endpoint["available_at_ns"])
        lineage = canonical_hash([start["lineage"], *[item["lineage"] for item in concrete]])
        result[f"outcome_{horizon}m_lineage_hash"] = lineage
        horizon_lineages[str(horizon)] = lineage
    result["outcome_lineage_hash"] = canonical_hash(
        {"decision_at_ns": decision_ns, "source_sha256": source_sha, "horizons": horizon_lineages}
    )
    return result


def join_outcome_row(
    predictor: Mapping[str, Any],
    identity: Mapping[str, Any],
    bars: Mapping[int, Mapping[str, Any]],
) -> dict[str, Any]:
    require(str(predictor["anchor_id"]) == str(identity["anchor_id"]), "Outcome join anchor differs")
    require(
        int(predictor["decision_at_ns"]) == int(identity["decision_at_ns"]),
        "Outcome join decision timestamp differs",
    )
    return {
        **dict(predictor),
        **outcome_fields(int(predictor["decision_at_ns"]), bars, EXPECTED_XAU_SHA),
    }


def write_joined_parquet(path: Path, rows: Sequence[Mapping[str, Any]], schema: pa.Schema) -> None:
    require(not path.exists(), f"Refusing to overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    table = pa.Table.from_pylist(list(rows), schema=schema)
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=65_536,
    )
    os.replace(temporary, path)


def serializer_proof(predictor_schema: pa.Schema, directory: Path) -> dict[str, Any]:
    require(not directory.exists(), f"Serializer proof directory exists: {directory}")
    directory.mkdir(parents=True)
    schema = pa.schema([*predictor_schema, *OUTCOME_FIELDS])
    synthetic_rows: list[dict[str, Any]] = []
    for index in range(2):
        row: dict[str, Any] = {}
        for field in predictor_schema:
            if pa.types.is_string(field.type):
                row[field.name] = f"SYNTHETIC_{field.name}_{index}"
            elif pa.types.is_integer(field.type):
                row[field.name] = index + 1
            elif pa.types.is_floating(field.type):
                row[field.name] = None if field.nullable and index else float(index + 1) / 4
            elif pa.types.is_boolean(field.type):
                row[field.name] = bool(index)
            else:
                raise DiscoveryFailure(f"Unsupported synthetic field: {field}")
        for field in OUTCOME_FIELDS:
            if pa.types.is_string(field.type):
                row[field.name] = hashlib.sha256(f"{field.name}:{index}".encode()).hexdigest() if field.name.endswith("hash") else "VALID_EXACT_CONTIGUOUS_PATH"
            else:
                row[field.name] = index + 10
        synthetic_rows.append(row)
    primary = directory / "primary_synthetic_join.parquet"
    reference = directory / "reference_synthetic_join.parquet"
    write_joined_parquet(primary, synthetic_rows, schema)
    write_joined_parquet(reference, list(reversed(list(reversed(synthetic_rows)))), schema)
    primary_table = pq.read_table(primary, use_threads=False)
    reference_rows: list[dict[str, Any]] = []
    parquet = pq.ParquetFile(reference)
    for group in range(parquet.num_row_groups):
        reference_rows.extend(parquet.read_row_group(group, use_threads=False).to_pylist())
    require(primary.read_bytes() == reference.read_bytes(), "Synthetic Parquet bytes differ")
    require(primary_table.schema == schema and parquet.schema_arrow == schema, "Synthetic schema differs")
    require(primary_table.to_pylist() == reference_rows == synthetic_rows, "Synthetic round trip differs")

    decision = dt_ns(datetime(2024, 1, 2, 10, 0, tzinfo=UTC))
    bars: dict[int, dict[str, Any]] = {}
    all_opens = (decision - ONE_MINUTE_NS, *tuple(decision + minute * ONE_MINUTE_NS for minute in range(61)))
    for ordinal, stamp in enumerate(all_opens):
        bars[stamp] = {
            "close_scaled": 100 * XAU_SCALE + ordinal * XAU_SCALE,
            "available_at_ns": stamp + ONE_MINUTE_NS,
            "lineage": hashlib.sha256(str(stamp).encode()).hexdigest(),
        }
    fields = outcome_fields(decision, bars, "0" * 64)
    require(fields["outcome_5m_displacement_fixed_1e9"] == 5 * XAU_SCALE, "Synthetic 5m boundary differs")
    require(fields["outcome_15m_displacement_fixed_1e9"] == 15 * XAU_SCALE, "Synthetic 15m boundary differs")
    require(fields["outcome_30m_displacement_fixed_1e9"] == 30 * XAU_SCALE, "Synthetic 30m boundary differs")
    require(fields["outcome_60m_displacement_fixed_1e9"] == 60 * XAU_SCALE, "Synthetic 60m boundary differs")
    missing = dict(bars)
    missing.pop(decision + 14 * ONE_MINUTE_NS)
    missing_fields = outcome_fields(decision, missing, "0" * 64)
    require(missing_fields["outcome_15m_quality"] != "VALID_EXACT_CONTIGUOUS_PATH", "Synthetic missing-bar gate differs")
    late = deepcopy(bars)
    late[decision - ONE_MINUTE_NS]["available_at_ns"] = decision + 1
    late_fields = outcome_fields(decision, late, "0" * 64)
    require(late_fields["outcome_15m_quality"] != "VALID_EXACT_CONTIGUOUS_PATH", "Synthetic unavailable-at-anchor gate differs")
    synthetic_predictor = {"anchor_id": "SYNTHETIC_JOIN", "decision_at_ns": decision}
    synthetic_identity = {"anchor_id": "SYNTHETIC_JOIN", "decision_at_ns": decision}
    primary_join = join_outcome_row(synthetic_predictor, synthetic_identity, bars)
    reference_join = join_outcome_row(dict(synthetic_predictor), dict(synthetic_identity), deepcopy(bars))
    require(primary_join == reference_join, "Synthetic primary/reference join differs")
    require(
        canonical_hash(primary_join) == canonical_hash(reference_join),
        "Synthetic primary/reference join checksum differs",
    )
    return seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_SERIALIZER_PROOF_V1_0",
            "status": "PASS_PRE_OUTCOME_SERIALIZER_AND_BOUNDARY_PROOF",
            "schema_sha256": schema_fingerprint(schema),
            "primary_parquet": {"path": "serializer_proof_payload/primary_synthetic_join.parquet", "bytes": primary.stat().st_size, "sha256": sha256_file(primary)},
            "reference_parquet": {"path": "serializer_proof_payload/reference_synthetic_join.parquet", "bytes": reference.stat().st_size, "sha256": sha256_file(reference)},
            "byte_identical": True,
            "round_trip_exact": True,
            "start_end_boundary_exact": True,
            "missing_bar_rejected": True,
            "unavailable_start_bar_rejected": True,
            "primary_reference_join_exact": True,
            "joined_payload_checksum": canonical_hash(primary_join),
            "outcome_values_accessed": False,
            "proof_receipt": None,
        },
        "proof_receipt",
    )


def test_registry(paths: Paths) -> dict[str, Any]:
    eligible = load_json(paths.r1_output / "eligible_test_registry.json")
    models = load_json(MODEL_REGISTRY)
    interaction_map = {item["interaction_id"]: item for item in models["stage2"]["interactions"]}
    sessions: dict[str, Any] = {}
    for session in SESSIONS:
        stage1 = []
        for test_id in eligible["sessions"][session]["stage1_support_eligible"]:
            permutation_seed = seed_for(session, 1, test_id, "DATE_CLUSTER_PERMUTATION")
            stage1.append(
                {
                    "test_id": test_id,
                    "expected_sign": "POSITIVE",
                    "bootstrap_seed_uint64": seed_for(session, 1, test_id, "BLOCK_BOOTSTRAP"),
                    "permutation_seed_uint64": permutation_seed,
                    "permutation_horizon_seeds_uint64": {
                        str(horizon): horizon_seed(permutation_seed, horizon) for horizon in HORIZONS
                    },
                }
            )
        stage2 = []
        for test_id in eligible["sessions"][session]["stage2_support_eligible"]:
            item = interaction_map[test_id]
            permutation_seed = seed_for(session, 2, test_id, "DATE_CLUSTER_PERMUTATION")
            stage2.append(
                {
                    **item,
                    "test_id": test_id,
                    "bootstrap_seed_uint64": seed_for(session, 2, test_id, "BLOCK_BOOTSTRAP"),
                    "permutation_seed_uint64": permutation_seed,
                    "permutation_horizon_seeds_uint64": {
                        str(horizon): horizon_seed(permutation_seed, horizon) for horizon in HORIZONS
                    },
                }
            )
        sessions[session] = {
            "stage1": stage1,
            "stage2": stage2,
            "stage1_support_fail": list(EXPECTED_STAGE1_FAIL),
            "stage2_support_fail": list(EXPECTED_STAGE2_FAIL),
            "unsupported_modifier": ["CSR_SESSION_LEVEL_TENSION"],
        }
    return seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_TEST_REGISTRY_V1_0",
            "status": "FROZEN_PRE_OUTCOME_TESTS_AND_SEEDS",
            "sessions": sessions,
            "stage1_eligible_total": 18,
            "stage2_eligible_total": 10,
            "outcome_values_accessed": False,
            "registry_receipt": None,
        },
        "registry_receipt",
    )


def prepare(paths: Paths) -> None:
    require(not FREEZE.exists(), f"M3 freeze already exists: {FREEZE}")
    require(not paths.output.exists(), f"M3 output already exists: {paths.output}")
    protocol = load_json(PROTOCOL)
    require(protocol["status"] == "READY_TO_FREEZE_PRE_OUTCOME", "M3 protocol not ready")
    predecessors = verify_predecessors(paths, require_source=True)
    population, predictor_schema = population_registry(paths)
    target_timestamps = {
        stamp
        for anchor in population["anchors"]
        for stamp in required_open_ns(int(anchor["decision_at_ns"]))
    }
    primary_coverage, primary_valid_timestamps = metadata_coverage_scan(paths.xau_source, target_timestamps, reference=False)
    reference_coverage, reference_valid_timestamps = metadata_coverage_scan(paths.xau_source, target_timestamps, reference=True)
    require(coverage_comparable(primary_coverage) == coverage_comparable(reference_coverage), "Metadata coverage readers differ")
    require(primary_valid_timestamps == reference_valid_timestamps, "Metadata valid-timestamp sets differ")
    population = attach_outcome_metadata(population, primary_valid_timestamps)

    temporary = paths.output.with_name(paths.output.name + ".preparing")
    require(not temporary.exists(), f"M3 preparing directory exists: {temporary}")
    temporary.mkdir(parents=True)
    proof = serializer_proof(predictor_schema, temporary / "serializer_proof_payload")
    registry = test_registry(paths)
    write_json_once(temporary / "population_registry.json", population)
    write_json_once(temporary / "primary_metadata_coverage.json", primary_coverage)
    write_json_once(temporary / "reference_metadata_coverage.json", reference_coverage)
    write_json_once(temporary / "test_registry.json", registry)
    write_json_once(temporary / "serializer_proof.json", proof)
    preflight = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_PREFLIGHT_V1_0",
            "status": "PASS_V3_M3_PRE_OUTCOME_FREEZE_READINESS",
            "completed_at_utc": utc_now(),
            "predecessors": predecessors,
            "population_receipt": population["population_receipt"],
            "test_registry_receipt": registry["registry_receipt"],
            "serializer_proof_receipt": proof["proof_receipt"],
            "metadata_coverage_checksum": primary_coverage["coverage_checksum"],
            "outcome_source_openings": 0,
            "outcome_values_accessed": False,
            "year_2025_or_2026_values_accessed": False,
            "preflight_receipt": None,
        },
        "preflight_receipt",
    )
    write_json_once(temporary / "preflight.json", preflight)
    os.replace(temporary, paths.output)

    freeze_payload = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_FREEZE_V1_0",
            "status": "PASS_V3_M3_PRE_OUTCOME_FREEZE",
            "frozen_at_utc": utc_now(),
            "predecessors": predecessors,
            "population_receipt": population["population_receipt"],
            "test_registry_receipt": registry["registry_receipt"],
            "serializer_proof_receipt": proof["proof_receipt"],
            "preflight_receipt": preflight["preflight_receipt"],
            "artifacts": {
                name: artifact_record(paths.output / name)
                for name in (
                    "population_registry.json",
                    "primary_metadata_coverage.json",
                    "reference_metadata_coverage.json",
                    "test_registry.json",
                    "serializer_proof.json",
                    "preflight.json",
                )
            },
            "protocol_sha256": sha256_file(PROTOCOL),
            "implementation_sha256": sha256_file(IMPLEMENTATION),
            "test_sha256": sha256_file(TEST_FILE),
            "document_sha256": sha256_file(DOCUMENT),
            "contract_sha256": sha256_file(CONTRACT),
            "feature_registry_sha256": sha256_file(FEATURE_REGISTRY),
            "model_registry_sha256": sha256_file(MODEL_REGISTRY),
            "traceability_sha256": sha256_file(TRACEABILITY),
            "library_versions": {"numpy": np.__version__, "pyarrow": pa.__version__},
            "outcome_source_sha256": EXPECTED_XAU_SHA,
            "outcome_values_accessed_before_freeze": False,
            "year_2025_or_2026_values_accessed": False,
            "freeze_receipt": None,
        },
        "freeze_receipt",
    )
    write_json_once(FREEZE, freeze_payload)
    write_json_once(paths.output / "m3_freeze.json", freeze_payload)
    print(canonical_json({"status": freeze_payload["status"], "freeze_receipt": freeze_payload["freeze_receipt"], "anchors": population["anchor_count"], "target_timestamps": len(target_timestamps)}))


def verify_freeze(paths: Paths, *, require_source: bool) -> dict[str, Any]:
    require(FREEZE.is_file(), "M3 freeze missing")
    frozen = load_json(FREEZE)
    require(receipt_valid(frozen, "freeze_receipt"), "M3 freeze receipt invalid")
    require(frozen["status"] == "PASS_V3_M3_PRE_OUTCOME_FREEZE", "M3 freeze status changed")
    file_hashes = {
        "protocol_sha256": PROTOCOL,
        "implementation_sha256": IMPLEMENTATION,
        "test_sha256": TEST_FILE,
        "document_sha256": DOCUMENT,
        "contract_sha256": CONTRACT,
        "feature_registry_sha256": FEATURE_REGISTRY,
        "model_registry_sha256": MODEL_REGISTRY,
        "traceability_sha256": TRACEABILITY,
    }
    for key, path in file_hashes.items():
        require(sha256_file(path) == frozen[key], f"Frozen file changed: {path}")
    predecessors = verify_predecessors(paths, require_source=require_source)
    require(predecessors == frozen["predecessors"], "Predecessor boundary changed after M3 freeze")
    copied = load_json(paths.output / "m3_freeze.json")
    require(copied == frozen, "Copied M3 freeze differs")
    for name, expected in frozen["artifacts"].items():
        path = paths.output / name
        require(path.is_file(), f"Frozen M3 artifact missing: {name}")
        require(path.stat().st_size == int(expected["bytes"]), f"Frozen M3 artifact size changed: {name}")
        require(sha256_file(path) == expected["sha256"], f"Frozen M3 artifact hash changed: {name}")
    proof = load_json(paths.output / "serializer_proof.json")
    for key in ("primary_parquet", "reference_parquet"):
        expected = proof[key]
        path = paths.output / expected["path"]
        require(path.is_file(), f"Serializer proof payload missing: {path}")
        require(path.stat().st_size == int(expected["bytes"]), f"Serializer proof payload size changed: {path}")
        require(sha256_file(path) == expected["sha256"], f"Serializer proof payload hash changed: {path}")
    require(
        (paths.output / proof["primary_parquet"]["path"]).read_bytes()
        == (paths.output / proof["reference_parquet"]["path"]).read_bytes(),
        "Serializer proof payloads are no longer byte-identical",
    )
    require(not frozen["outcome_values_accessed_before_freeze"] and not frozen["year_2025_or_2026_values_accessed"], "M3 pre-outcome locks changed")
    return frozen


def verify_record_hash(record: Mapping[str, Any]) -> bool:
    expected = record.get("record_hash")
    if not isinstance(expected, str):
        return False
    unhashed = deepcopy(dict(record))
    unhashed.pop("record_hash", None)
    return canonical_hash(unhashed) == expected


def selected_price_bars(
    path: Path, targets: set[int]
) -> tuple[dict[int, dict[str, Any]], dict[int, dict[str, Any]], dict[str, Any]]:
    primary: dict[int, dict[str, Any]] = {}
    reference: dict[int, dict[str, Any]] = {}
    invalid = Counter()
    target_occurrences = Counter()
    source_rows = selected_rows = 0
    selected_line_numbers: list[int] = []
    with gzip.open(path, "rb") as handle:  # the single authorized value stream opening
        for line_number, raw in enumerate(handle, start=1):
            opened_match = OPEN_BYTES.search(raw)
            if opened_match is None:
                continue
            opened_raw = opened_match.group(1).decode("ascii")
            if opened_raw.startswith(("2025-", "2026-")):
                break
            timeframe = TIMEFRAME_BYTES.search(raw)
            instrument = INSTRUMENT_BYTES.search(raw)
            if timeframe is None or instrument is None or timeframe.group(1) != b"1m" or instrument.group(1) != b"XAUUSD":
                continue
            source_rows += 1
            opened_ns = dt_ns(parse_dt(opened_raw))
            if opened_ns not in targets:
                continue
            selected_rows += 1
            selected_line_numbers.append(line_number)
            target_occurrences[opened_ns] += 1
            if target_occurrences[opened_ns] != 1:
                primary.pop(opened_ns, None)
                reference.pop(opened_ns, None)
                invalid["DUPLICATE_TARGET_TIMESTAMP"] += 1
                continue
            try:
                p_record = json.loads(raw)
                r_record = json.loads(raw, parse_float=Decimal)
                require(isinstance(p_record, dict) and isinstance(r_record, dict), "PRICE_RECORD_TYPE")
                require(verify_record_hash(p_record), "PRICE_RECORD_HASH")
                require(p_record.get("record_type") == "PRICE_BAR", "PRICE_RECORD_CLASS")
                require(p_record.get("provider_code") == "IC_MARKETS_MT5", "PRICE_PROVIDER")
                require(p_record.get("instrument_code") == "XAUUSD" and p_record.get("timeframe") == "1m", "PRICE_SERIES")
                require(p_record.get("complete") is True and int(p_record.get("missing_source_minutes", -1)) == 0, "PRICE_COMPLETENESS")
                opened = parse_dt(str(p_record["open_time"]))
                closed = parse_dt(str(p_record["close_time"]))
                available = parse_dt(str(p_record["available_at"]))
                require(dt_ns(opened) == opened_ns, "PRICE_OPEN_TIMESTAMP")
                require(closed == opened + timedelta(minutes=1) and available <= closed, "PRICE_TIME_OR_AVAILABILITY")
                p_close = decimal_to_scaled(p_record["ohlc"]["close"])
                r_close = decimal_to_scaled(r_record["ohlc"]["close"])
                require(p_close == r_close, "INDEPENDENT_PRICE_ARITHMETIC")
                lineage = {
                    "record_id": str(p_record["record_id"]),
                    "record_hash": str(p_record["record_hash"]),
                    "source_hash": str(p_record["source"]["source_hash"]),
                    "open_time": str(p_record["open_time"]),
                    "close_time": str(p_record["close_time"]),
                    "available_at": str(p_record["available_at"]),
                    "source_line_sha256": hashlib.sha256(raw).hexdigest(),
                }
                payload = {
                    "close_scaled": p_close,
                    "available_at_ns": dt_ns(available),
                    "lineage": lineage,
                }
                primary[opened_ns] = payload
                reference[opened_ns] = {
                    "close_scaled": r_close,
                    "available_at_ns": dt_ns(available),
                    "lineage": deepcopy(lineage),
                }
            except Exception as exc:
                primary.pop(opened_ns, None)
                reference.pop(opened_ns, None)
                invalid[type(exc).__name__ + ":" + str(exc)] += 1
    require(primary == reference, "Primary/reference selected price bars differ")
    missing = targets.difference(primary)
    diagnostics = {
        "source_value_stream_open_count": 1,
        "source_xau_1m_rows_before_2025_lock": source_rows,
        "target_timestamp_count": len(targets),
        "selected_source_rows": selected_rows,
        "valid_unique_target_timestamps": len(primary),
        "valid_unique_target_timestamp_checksum": canonical_hash(sorted(primary)),
        "missing_or_invalid_target_timestamps": len(missing),
        "invalid_reason_counts": dict(sorted(invalid.items())),
        "selected_line_numbers_checksum": canonical_hash(selected_line_numbers),
        "selected_bar_lineage_checksum": canonical_hash(
            [(stamp, primary[stamp]["lineage"]) for stamp in sorted(primary)]
        ),
        "first_2025_or_2026_record_deserialized": False,
    }
    require(not invalid, f"Selected price validity changed at value opening: {diagnostics}")
    return primary, reference, diagnostics


def read_predictors(paths: Paths, implementation: str, *, reference_reader: bool) -> tuple[list[dict[str, Any]], pa.Schema]:
    rows: list[dict[str, Any]] = []
    schema: pa.Schema | None = None
    for session in SESSIONS:
        path = paths.m2_output / f"{implementation}_{session.lower()}_anchors.parquet"
        parquet = pq.ParquetFile(path)
        if schema is None:
            schema = parquet.schema_arrow
        else:
            require(schema == parquet.schema_arrow, "Predictor schemas differ across sessions")
        if not reference_reader:
            rows.extend(pq.read_table(path, use_threads=False).to_pylist())
        else:
            for group_index in range(parquet.num_row_groups):
                table = parquet.read_row_group(group_index, use_threads=False)
                for batch in table.to_batches(max_chunksize=7):
                    rows.extend(pa.Table.from_batches([batch]).to_pylist())
    rows = [dict(row) for row in rows]
    rows.sort(key=lambda row: (str(row["session_code"]), str(row["session_date"]), int(row["anchor_offset_minutes"])))
    require(len(rows) == EXPECTED_ANCHORS, "Predictor anchor cardinality changed")
    assert schema is not None
    return rows, schema


def join_outcomes(
    predictor_rows: Sequence[Mapping[str, Any]],
    bars: Mapping[int, Mapping[str, Any]],
    population: Mapping[str, Any],
) -> list[dict[str, Any]]:
    frozen = population["anchors"]
    require(len(predictor_rows) == len(frozen) == EXPECTED_ANCHORS, "Join cardinality changed")
    output: list[dict[str, Any]] = []
    for predictor, identity in zip(predictor_rows, frozen):
        output.append(join_outcome_row(predictor, identity, bars))
    require(len({str(row["anchor_id"]) for row in output}) == EXPECTED_ANCHORS, "Joined anchors are not unique")
    return output


def open_outcomes(paths: Paths) -> None:
    frozen = verify_freeze(paths, require_source=True)
    ledger_path = paths.output / "source_opening_ledger.json"
    opening_path = paths.output / "outcome_opening.json"
    require(not ledger_path.exists() and not opening_path.exists(), "Authorized outcome source opening already consumed")
    population = load_json(paths.output / "population_registry.json")
    require(receipt_valid(population, "population_receipt"), "Population receipt invalid")
    target_timestamps = {
        stamp
        for anchor in population["anchors"]
        for stamp in required_open_ns(int(anchor["decision_at_ns"]))
    }
    ledger = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_SOURCE_OPENING_LEDGER_V1_0",
            "status": "SINGLE_DEVELOPMENT_OUTCOME_VALUE_STREAM_OPENING_CONSUMED",
            "opened_at_utc": utc_now(),
            "opening_count": 1,
            "source_sha256": EXPECTED_XAU_SHA,
            "development_period": "2021-11-08/2024-12-13",
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
            "ledger_receipt": None,
        },
        "ledger_receipt",
    )
    write_json_once(ledger_path, ledger)
    try:
        primary_bars, reference_bars, source_diagnostics = selected_price_bars(paths.xau_source, target_timestamps)
        require(
            source_diagnostics["valid_unique_target_timestamps"] == population["source_valid_unique_timestamp_count"]
            and source_diagnostics["valid_unique_target_timestamp_checksum"] == population["source_valid_unique_timestamp_checksum"],
            "Value-opening timestamp availability differs from frozen metadata",
        )
        primary_predictors, primary_schema = read_predictors(paths, "primary", reference_reader=False)
        reference_predictors, reference_schema = read_predictors(paths, "reference", reference_reader=True)
        require(primary_schema == reference_schema, "Primary/reference predictor schema differs at join")
        primary_rows = join_outcomes(primary_predictors, primary_bars, population)
        reference_rows = join_outcomes(reference_predictors, reference_bars, population)
        require(primary_rows == reference_rows, "Primary/reference outcome arithmetic or join differs")
        join_schema = pa.schema([*primary_schema, *OUTCOME_FIELDS])
        require(schema_fingerprint(join_schema) == population["joined_schema_sha256"], "Joined schema changed")
        primary_path = paths.output / "primary_joined_anchor_outcomes.parquet"
        reference_path = paths.output / "reference_joined_anchor_outcomes.parquet"
        write_joined_parquet(primary_path, primary_rows, join_schema)
        write_joined_parquet(reference_path, reference_rows, join_schema)
        require(primary_path.read_bytes() == reference_path.read_bytes(), "Joined Parquet outputs are not byte-identical")
        quality = {
            session: {
                str(horizon): Counter(
                    str(row[f"outcome_{horizon}m_quality"])
                    for row in primary_rows
                    if row["session_code"] == session
                )
                for horizon in HORIZONS
            }
            for session in SESSIONS
        }
        frozen_by_id = {str(anchor["anchor_id"]): anchor for anchor in population["anchors"]}
        for row in primary_rows:
            frozen_anchor = frozen_by_id[str(row["anchor_id"])]
            for horizon in HORIZONS:
                actual = row[f"outcome_{horizon}m_quality"] == "VALID_EXACT_CONTIGUOUS_PATH"
                require(actual == bool(frozen_anchor[f"outcome_{horizon}m_metadata_available"]), f"Outcome availability differs from metadata freeze: {row['anchor_id']}/{horizon}")
        opening = seal_receipt(
            {
                "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_OUTCOME_OPENING_V1_0",
                "status": "PASS_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_JOIN",
                "completed_at_utc": utc_now(),
                "freeze_receipt": frozen["freeze_receipt"],
                "source_opening_ledger_receipt": ledger["ledger_receipt"],
                "source_opening_count": 1,
                "source_diagnostics": source_diagnostics,
                "joined_anchor_count": len(primary_rows),
                "quality_counts": {
                    session: {
                        horizon: dict(sorted(counts.items()))
                        for horizon, counts in horizons.items()
                    }
                    for session, horizons in quality.items()
                },
                "joined_payload_checksum": canonical_hash(primary_rows),
                "primary_joined": artifact_record(primary_path),
                "reference_joined": artifact_record(reference_path),
                "joined_parquet_byte_identical": True,
                "primary_reference_semantics_exact": True,
                "calendar_2025_or_2026_values_accessed": False,
                "execution_trades_or_pnl_calculated": False,
                "opening_receipt": None,
            },
            "opening_receipt",
        )
        write_json_once(opening_path, opening)
        print(canonical_json({"status": opening["status"], "anchors": opening["joined_anchor_count"], "opening_receipt": opening["opening_receipt"]}))
    except Exception as exc:
        failure = seal_receipt(
            {
                "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_OUTCOME_OPENING_FAILURE_V1_0",
                "status": "FAIL_SINGLE_AUTHORIZED_OUTCOME_OPENING",
                "failed_at_utc": utc_now(),
                "source_opening_count": 1,
                "reason_type": type(exc).__name__,
                "reason": str(exc),
                "another_opening_permitted": False,
                "failure_receipt": None,
            },
            "failure_receipt",
        )
        write_json_once(paths.output / "outcome_opening_failure.json", failure)
        raise


def rankdata_average(values: np.ndarray) -> np.ndarray:
    values = np.asarray(values, dtype=np.float64)
    order = np.argsort(values, kind="mergesort")
    ranks = np.empty(len(values), dtype=np.float64)
    position = 0
    while position < len(values):
        end = position + 1
        while end < len(values) and values[order[end]] == values[order[position]]:
            end += 1
        average = (position + 1 + end) / 2.0
        ranks[order[position:end]] = average
        position = end
    return ranks


def pearson(x: np.ndarray, y: np.ndarray) -> float | None:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    if len(x) < 3 or len(x) != len(y):
        return None
    xc = x - float(np.mean(x))
    yc = y - float(np.mean(y))
    denominator = math.sqrt(float(np.dot(xc, xc)) * float(np.dot(yc, yc)))
    if denominator <= 0 or not math.isfinite(denominator):
        return None
    return float(np.dot(xc, yc) / denominator)


def spearman(x: Sequence[float], y: Sequence[float]) -> float | None:
    if len(x) != len(y) or len(x) < 3:
        return None
    return pearson(rankdata_average(np.asarray(x, dtype=np.float64)), rankdata_average(np.asarray(y, dtype=np.float64)))


def direction_accuracy(scores: Sequence[float], outcomes: Sequence[float]) -> tuple[float | None, int, int]:
    score = np.asarray(scores, dtype=np.float64)
    outcome = np.asarray(outcomes, dtype=np.float64)
    mask = (score != 0) & (outcome != 0) & np.isfinite(score) & np.isfinite(outcome)
    denominator = int(np.sum(mask))
    if denominator == 0:
        return None, 0, 0
    correct = int(np.sum(np.sign(score[mask]) == np.sign(outcome[mask])))
    return correct / denominator, correct, denominator


def transform_parameters(values: Sequence[float]) -> dict[str, float] | None:
    array = np.asarray(values, dtype=np.float64)
    if len(array) < 3 or not np.all(np.isfinite(array)):
        return None
    lower, upper = np.quantile(array, [0.01, 0.99], method="linear")
    clipped = np.clip(array, lower, upper)
    center = float(np.median(clipped))
    scale = float(np.median(np.abs(clipped - center)))
    scale_method = "MAD"
    if scale == 0:
        scale = float(np.std(clipped, ddof=0))
        scale_method = "POPULATION_SD_FALLBACK"
    if scale <= 0 or not math.isfinite(scale):
        return None
    return {
        "winsor_lower": float(lower),
        "winsor_upper": float(upper),
        "center": center,
        "scale": scale,
        "scale_method": scale_method,
    }


def apply_transform(values: Sequence[float], parameters: Mapping[str, Any]) -> np.ndarray:
    array = np.asarray(values, dtype=np.float64)
    clipped = np.clip(array, float(parameters["winsor_lower"]), float(parameters["winsor_upper"]))
    return (clipped - float(parameters["center"])) / float(parameters["scale"])


def _solve_penalized(x: np.ndarray, y: np.ndarray, alpha: float) -> np.ndarray:
    design = np.column_stack((np.ones(len(x), dtype=np.float64), x))
    penalty = np.eye(design.shape[1], dtype=np.float64) * alpha
    penalty[0, 0] = 0.0
    matrix = design.T @ design + penalty
    vector = design.T @ y
    try:
        return np.linalg.solve(matrix, vector)
    except np.linalg.LinAlgError:
        return np.linalg.pinv(matrix, rcond=1e-15) @ vector


def robust_scale(values: np.ndarray) -> float:
    centered = values - float(np.median(values))
    scale = float(np.median(np.abs(centered)))
    if scale == 0:
        scale = float(np.std(values, ddof=0))
    if scale == 0:
        scale = float(np.max(np.abs(values))) if len(values) else 0.0
    return scale if scale > 0 and math.isfinite(scale) else 1.0


def fit_huber_irls(x: np.ndarray, y: np.ndarray) -> dict[str, Any]:
    x = np.asarray(x, dtype=np.float64).reshape(-1, 1)
    y = np.asarray(y, dtype=np.float64)
    require(len(x) == len(y) and len(y) >= 3, "Insufficient Huber training rows")
    beta = _solve_penalized(x, y, 0.0001)
    converged = False
    scale = robust_scale(y - (beta[0] + x[:, 0] * beta[1]))
    iterations = 0
    for iterations in range(1, 1001):
        residual = y - (beta[0] + x[:, 0] * beta[1])
        scale = robust_scale(residual)
        cutoff = 1.35 * scale
        absolute = np.abs(residual)
        weights = np.ones(len(y), dtype=np.float64)
        outside = absolute > cutoff
        weights[outside] = cutoff / absolute[outside]
        design = np.column_stack((np.ones(len(x), dtype=np.float64), x[:, 0]))
        root_weight = np.sqrt(weights)
        weighted_design = design * root_weight[:, None]
        weighted_y = y * root_weight
        penalty = np.diag([0.0, 0.0001])
        matrix = weighted_design.T @ weighted_design + penalty
        vector = weighted_design.T @ weighted_y
        try:
            updated = np.linalg.solve(matrix, vector)
        except np.linalg.LinAlgError:
            updated = np.linalg.pinv(matrix, rcond=1e-15) @ vector
        delta = float(np.max(np.abs(updated - beta)))
        tolerance = 1e-10 * (1.0 + float(np.max(np.abs(beta))))
        beta = updated
        if delta <= tolerance:
            converged = True
            break
    predictions = beta[0] + x[:, 0] * beta[1]
    return {
        "intercept": float(beta[0]),
        "coefficient": float(beta[1]),
        "iterations": iterations,
        "converged": converged,
        "residual_scale": float(scale),
        "training_mae": float(np.mean(np.abs(y - predictions))),
    }


def fit_ridge(x: np.ndarray, y: np.ndarray, alpha: float = 1.0) -> dict[str, Any]:
    x = np.asarray(x, dtype=np.float64)
    y = np.asarray(y, dtype=np.float64)
    require(x.ndim == 2 and len(x) == len(y) and len(y) >= x.shape[1] + 2, "Insufficient ridge training rows")
    beta = _solve_penalized(x, y, alpha)
    prediction = beta[0] + x @ beta[1:]
    return {
        "intercept": float(beta[0]),
        "coefficients": [float(value) for value in beta[1:]],
        "converged": bool(np.all(np.isfinite(beta))),
        "training_mae": float(np.mean(np.abs(y - prediction))),
    }


def ridge_predict(model: Mapping[str, Any], x: np.ndarray) -> np.ndarray:
    return float(model["intercept"]) + np.asarray(x, dtype=np.float64) @ np.asarray(model["coefficients"], dtype=np.float64)


def fold_for_block(block: int) -> int | None:
    for fold, _, start, end in FOLDS:
        if start <= block <= end:
            return fold
    return None


def outcome_value(row: Mapping[str, Any], horizon: int) -> float | None:
    if not outcome_available(row, horizon):
        return None
    raw = row[f"outcome_{horizon}m_displacement_fixed_1e9"]
    return float(int(raw) / XAU_SCALE)


def outcome_available(row: Mapping[str, Any], horizon: int) -> bool:
    return (
        row[f"outcome_{horizon}m_quality"] == "VALID_EXACT_CONTIGUOUS_PATH"
        and row[f"outcome_{horizon}m_displacement_fixed_1e9"] is not None
    )


def predictor_known(row: Mapping[str, Any], feature_id: str) -> bool:
    return row[f"{feature_id}__availability"] == AV_AVAILABLE and row[f"{feature_id}__value"] is not None


def interaction_value(interaction_id: str, left_raw: float, right_raw: float, left_z: float, right_z: float) -> float:
    if interaction_id in {
        "CSR_INT_OFI_MACRO_CONCORDANCE",
        "CSR_INT_TRADE_MACRO_CONCORDANCE",
        "CSR_INT_DEPTH_REAL_YIELD_CONCORDANCE",
        "CSR_INT_MICROPRICE_USD_CONCORDANCE",
    }:
        if left_raw != 0 and right_raw != 0 and math.copysign(1.0, left_raw) == math.copysign(1.0, right_raw):
            return math.copysign(min(abs(left_z), abs(right_z)), left_raw)
        return 0.0
    if interaction_id == "CSR_INT_OFI_SPREAD_FRAGILITY":
        return left_z * max(right_z, 0.0)
    if interaction_id == "CSR_INT_OFI_SESSION_LEVEL_TENSION":
        return left_z * right_raw
    raise DiscoveryFailure(f"Unregistered interaction formula: {interaction_id}")


def block_bootstrap(
    samples: Sequence[Mapping[str, Any]], seed: int, *, repetitions: int = BOOTSTRAP_REPETITIONS
) -> dict[str, Any]:
    scores = np.asarray([float(item["score"]) for item in samples], dtype=np.float64)
    outcomes = np.asarray([float(item["outcome_15m"]) for item in samples], dtype=np.float64)
    x_rank = rankdata_average(scores)
    y_rank = rankdata_average(outcomes)
    block_ids = sorted({str(item["selected_month_week_id"]) for item in samples})
    stats: list[list[float]] = []
    for block_id in block_ids:
        indices = np.asarray([index for index, item in enumerate(samples) if str(item["selected_month_week_id"]) == block_id], dtype=np.int64)
        x = x_rank[indices]
        y = y_rank[indices]
        nonflat = (scores[indices] != 0) & (outcomes[indices] != 0)
        correct = np.sign(scores[indices]) == np.sign(outcomes[indices])
        stats.append(
            [
                float(len(indices)),
                float(np.sum(x)),
                float(np.sum(y)),
                float(np.dot(x, x)),
                float(np.dot(y, y)),
                float(np.dot(x, y)),
                float(np.sum(correct & nonflat)),
                float(np.sum(nonflat)),
            ]
        )
    matrix = np.asarray(stats, dtype=np.float64)
    require(len(matrix) > 1, "Insufficient bootstrap blocks")
    rng = np.random.Generator(np.random.PCG64(seed))
    correlations: list[np.ndarray] = []
    lifts: list[np.ndarray] = []
    remaining = repetitions
    digest_rho = hashlib.sha256()
    digest_lift = hashlib.sha256()
    while remaining:
        batch = min(2_000, remaining)
        draws = rng.integers(0, len(matrix), size=(batch, len(matrix)), endpoint=False)
        totals = np.sum(matrix[draws], axis=1)
        n, sx, sy, sxx, syy, sxy, correct, nonflat = (totals[:, index] for index in range(8))
        covariance = sxy - sx * sy / n
        variance_x = sxx - sx * sx / n
        variance_y = syy - sy * sy / n
        denominator = np.sqrt(np.maximum(variance_x * variance_y, 0.0))
        rho = np.divide(covariance, denominator, out=np.full(batch, np.nan), where=denominator > 0)
        lift = np.divide(correct, nonflat, out=np.full(batch, np.nan), where=nonflat > 0) - 0.5
        correlations.append(rho)
        lifts.append(lift)
        digest_rho.update(np.asarray(rho, dtype="<f8").tobytes())
        digest_lift.update(np.asarray(lift, dtype="<f8").tobytes())
        remaining -= batch
    rho_values = np.concatenate(correlations)
    lift_values = np.concatenate(lifts)
    finite_rho = rho_values[np.isfinite(rho_values)]
    finite_lift = lift_values[np.isfinite(lift_values)]
    rho_ci = np.quantile(finite_rho, [0.025, 0.975], method="linear") if len(finite_rho) else [np.nan, np.nan]
    lift_ci = np.quantile(finite_lift, [0.025, 0.975], method="linear") if len(finite_lift) else [np.nan, np.nan]
    return {
        "method": "FIXED_FULL_OOF_RANK_MONTH_WEEK_BLOCK_BOOTSTRAP",
        "seed_uint64": seed,
        "repetitions": repetitions,
        "distinct_blocks": len(block_ids),
        "finite_rho_replicates": int(len(finite_rho)),
        "finite_accuracy_lift_replicates": int(len(finite_lift)),
        "rho_ci": [rounded(float(rho_ci[0])), rounded(float(rho_ci[1]))],
        "accuracy_lift_ci": [rounded(float(lift_ci[0])), rounded(float(lift_ci[1]))],
        "rho_replicates_sha256": digest_rho.hexdigest(),
        "accuracy_lift_replicates_sha256": digest_lift.hexdigest(),
    }


def horizon_seed(base_seed: int, horizon: int) -> int:
    return int.from_bytes(
        hashlib.sha256(f"{base_seed}|H{horizon}".encode("ascii")).digest()[:8],
        "big",
        signed=False,
    )


def _date_cluster_permutation_single(
    samples: Sequence[Mapping[str, Any]],
    horizon: int,
    seed: int,
    repetitions: int,
) -> dict[str, Any]:
    selected = [item for item in samples if item[f"outcome_{horizon}m"] is not None]
    if len(selected) < 3:
        return {
            "observed_rho": None,
            "two_sided_p_value": None,
            "exceedances": 0,
            "replicates_sha256": hashlib.sha256(b"").hexdigest(),
            "anchors": len(selected),
            "session_date_clusters": len({str(item["session_date"]) for item in selected}),
            "strata": [],
            "horizon_seed_uint64": seed,
        }
    scores = np.asarray([float(item["score"]) for item in selected], dtype=np.float64)
    outcomes = np.asarray([float(item[f"outcome_{horizon}m"]) for item in selected], dtype=np.float64)
    x_rank = rankdata_average(scores)
    y_rank = rankdata_average(outcomes)
    x_centered = x_rank - float(np.mean(x_rank))
    y_centered = y_rank - float(np.mean(y_rank))
    denominator = math.sqrt(float(np.dot(x_centered, x_centered)) * float(np.dot(y_centered, y_centered)))
    observed = float(np.dot(x_centered, y_centered) / denominator) if denominator > 0 else None
    date_indices: dict[tuple[int, str], list[int]] = defaultdict(list)
    for index, item in enumerate(selected):
        date_indices[(int(item["fold"]), str(item["session_date"]))].append(index)
    strata_dates: dict[tuple[int, tuple[int, ...]], list[tuple[str, list[int]]]] = defaultdict(list)
    for (fold, date), indices in date_indices.items():
        ordered = sorted(indices, key=lambda index: int(selected[index]["anchor_offset_minutes"]))
        signature = tuple(int(selected[index]["anchor_offset_minutes"]) for index in ordered)
        strata_dates[(fold, signature)].append((date, ordered))
    strata: list[dict[str, Any]] = []
    for (fold, signature), dates in sorted(strata_dates.items()):
        dates.sort(key=lambda item: item[0])
        index_matrix = np.asarray([indices for _, indices in dates], dtype=np.int64)
        contribution = x_centered[index_matrix] @ y_centered[index_matrix].T
        strata.append(
            {
                "fold": fold,
                "signature": signature,
                "dates": [date for date, _ in dates],
                "contribution": contribution,
            }
        )
    rng = np.random.Generator(np.random.PCG64(seed))
    exceedances = 0
    digest = hashlib.sha256()
    remaining = repetitions
    while remaining:
        batch = min(1_000, remaining)
        numerators = np.zeros(batch, dtype=np.float64)
        for stratum in strata:
            count = len(stratum["dates"])
            if count == 1:
                permutation = np.zeros((batch, 1), dtype=np.int64)
            else:
                permutation = np.argsort(rng.random((batch, count)), axis=1, kind="stable")
            rows = np.arange(count, dtype=np.int64)[None, :]
            numerators += np.sum(stratum["contribution"][rows, permutation], axis=1)
        correlations = numerators / denominator if denominator > 0 else np.full(batch, np.nan)
        if observed is not None:
            exceedances += int(np.sum(np.abs(correlations) >= abs(observed) - 1e-15))
        digest.update(np.asarray(correlations, dtype="<f8").tobytes())
        remaining -= batch
    return {
        "observed_rho": rounded(observed),
        "two_sided_p_value": rounded((1 + exceedances) / (repetitions + 1)) if observed is not None else None,
        "exceedances": exceedances,
        "replicates_sha256": digest.hexdigest(),
        "anchors": len(selected),
        "session_date_clusters": len(date_indices),
        "strata": [
            {
                "fold": item["fold"],
                "offset_signature": list(item["signature"]),
                "date_count": len(item["dates"]),
                "date_identity_checksum": canonical_hash(item["dates"]),
            }
            for item in strata
        ],
        "horizon_seed_uint64": seed,
    }


def date_cluster_permutations(
    samples: Sequence[Mapping[str, Any]], seed: int, *, repetitions: int = PERMUTATION_REPETITIONS
) -> dict[str, Any]:
    return {
        "method": "SESSION_DATE_VECTOR_PERMUTATION_WITHIN_FOLD_AND_OFFSET_SIGNATURE",
        "base_seed_uint64": seed,
        "horizon_subseed_derivation": "SHA256(base_seed|Hhorizon), first eight bytes big-endian unsigned",
        "repetitions": repetitions,
        "horizons": {
            str(horizon): _date_cluster_permutation_single(
                samples,
                horizon,
                horizon_seed(seed, horizon),
                repetitions,
            )
            for horizon in HORIZONS
        },
    }


def holm_adjust(p_values: Mapping[int, float | None]) -> dict[str, float | None]:
    finite = [(horizon, float(value)) for horizon, value in p_values.items() if value is not None]
    finite.sort(key=lambda item: (item[1], item[0]))
    adjusted: dict[int, float] = {}
    running = 0.0
    total = len(finite)
    for rank, (horizon, value) in enumerate(finite):
        running = max(running, min(1.0, (total - rank) * value))
        adjusted[horizon] = running
    return {str(horizon): rounded(adjusted.get(horizon)) for horizon in p_values}


def common_metrics(
    samples: Sequence[Mapping[str, Any]], bootstrap_seed: int, permutation_seed: int
) -> dict[str, Any]:
    require(samples, "No OOF samples")
    scores = [float(item["score"]) for item in samples]
    primary = [float(item["outcome_15m"]) for item in samples]
    rho = spearman(scores, primary)
    accuracy, correct, nonflat = direction_accuracy(scores, primary)
    fold_metrics: dict[str, Any] = {}
    for fold, _, _, _ in FOLDS:
        selected = [item for item in samples if int(item["fold"]) == fold]
        fold_scores = [float(item["score"]) for item in selected]
        fold_outcomes = [float(item["outcome_15m"]) for item in selected]
        fold_accuracy, fold_correct, fold_nonflat = direction_accuracy(fold_scores, fold_outcomes)
        fold_metrics[str(fold)] = {
            "anchors": len(selected),
            "dates": len({str(item["session_date"]) for item in selected}),
            "rho": rounded(spearman(fold_scores, fold_outcomes)),
            "direction_accuracy": rounded(fold_accuracy),
            "correct_nonflat": fold_correct,
            "nonflat": fold_nonflat,
        }
    annual: dict[str, Any] = {}
    for year in OOF_YEARS:
        selected = [item for item in samples if str(item["session_date"]).startswith(str(year))]
        year_scores = [float(item["score"]) for item in selected]
        year_outcomes = [float(item["outcome_15m"]) for item in selected]
        annual[str(year)] = {
            "anchors": len(selected),
            "dates": len({str(item["session_date"]) for item in selected}),
            "rho": rounded(spearman(year_scores, year_outcomes)),
        }
    bootstrap = block_bootstrap(samples, bootstrap_seed)
    permutation = date_cluster_permutations(samples, permutation_seed)
    secondary_p = {
        horizon: permutation["horizons"][str(horizon)]["two_sided_p_value"]
        for horizon in (5, 30, 60)
    }
    holm = holm_adjust(secondary_p)
    diagnostics = []
    for horizon in (5, 30, 60):
        selected = [item for item in samples if item[f"outcome_{horizon}m"] is not None]
        horizon_scores = [float(item["score"]) for item in selected]
        outcomes = [float(item[f"outcome_{horizon}m"]) for item in selected]
        horizon_accuracy, horizon_correct, horizon_nonflat = direction_accuracy(horizon_scores, outcomes)
        diagnostics.append(
            {
                "horizon_minutes": horizon,
                "anchors": len(selected),
                "missing_anchors": len(samples) - len(selected),
                "dates": len({str(item["session_date"]) for item in selected}),
                "rho": rounded(spearman(horizon_scores, outcomes)),
                "direction_accuracy": rounded(horizon_accuracy),
                "correct_nonflat": horizon_correct,
                "nonflat": horizon_nonflat,
                "permutation_p_value": secondary_p[horizon],
                "holm_adjusted_p_value": holm[str(horizon)],
                "diagnostic_only": True,
            }
        )
    return {
        "oof_anchors": len(samples),
        "oof_dates": len({str(item["session_date"]) for item in samples}),
        "oof_blocks": len({str(item["selected_month_week_id"]) for item in samples}),
        "signed_oof_spearman": rounded(rho),
        "oof_direction_accuracy": rounded(accuracy),
        "correct_nonflat": correct,
        "nonflat": nonflat,
        "folds": fold_metrics,
        "years": annual,
        "bootstrap": bootstrap,
        "permutation": permutation,
        "diagnostic_horizons": diagnostics,
    }


def test_specific_outcome_coverage(
    eligible_rows: Sequence[Mapping[str, Any]], *, stage: int
) -> dict[str, Any]:
    """Apply the frozen outcome-coverage gates before any relationship statistic.

    The denominator is the already support-eligible predictor population. The
    numerator is its intersection with an exact, point-in-time-valid 15-minute
    outcome. No predictor, anchor, or source row is repaired or replaced.
    """
    require(stage in {1, 2}, f"Unknown outcome-coverage stage: {stage}")
    available = [row for row in eligible_rows if outcome_available(row, PRIMARY_HORIZON)]
    completeness_floor = 0.80 if stage == 1 else 0.70
    completeness = len(available) / len(eligible_rows) if eligible_rows else 0.0
    folds: dict[str, Any] = {}
    for fold, _, start, end in FOLDS:
        denominator = [row for row in eligible_rows if start <= int(row["chronological_block"]) <= end]
        numerator = [row for row in available if start <= int(row["chronological_block"]) <= end]
        folds[str(fold)] = {
            "eligible_anchors": len(denominator),
            "available_anchors": len(numerator),
            "eligible_dates": len({str(row["session_date"]) for row in denominator}),
            "available_dates": len({str(row["session_date"]) for row in numerator}),
        }
    years: dict[str, Any] = {}
    for year in OOF_YEARS:
        denominator_dates = {
            str(row["session_date"])
            for row in eligible_rows
            if fold_for_block(int(row["chronological_block"])) is not None
            and str(row["session_date"]).startswith(str(year))
        }
        numerator_dates = {
            str(row["session_date"])
            for row in available
            if fold_for_block(int(row["chronological_block"])) is not None
            and str(row["session_date"]).startswith(str(year))
        }
        minimum = math.ceil(0.80 * len(denominator_dates))
        years[str(year)] = {
            "numerator_available_dates": len(numerator_dates),
            "denominator_predictor_eligible_oof_dates": len(denominator_dates),
            "minimum_required_dates": minimum,
            "coverage_fraction": rounded(
                len(numerator_dates) / len(denominator_dates) if denominator_dates else None,
                8,
            ),
            "pass": bool(denominator_dates) and len(numerator_dates) >= minimum,
        }
    dates = len({str(row["session_date"]) for row in available})
    blocks = len({int(row["chronological_block"]) for row in available})
    gates = {
        f"stage{stage}_outcome_completeness_gte_{str(completeness_floor).replace('.', '_')}": completeness
        >= completeness_floor,
        "outcome_available_distinct_dates_gte_150": dates >= 150,
        "outcome_available_distinct_blocks_gte_30": blocks >= 30,
        "each_validation_fold_outcome_dates_gte_35": all(
            item["available_dates"] >= 35 for item in folds.values()
        ),
        "each_validation_fold_outcome_anchors_gte_480": all(
            item["available_anchors"] >= 480 for item in folds.values()
        ),
        "each_required_year_predictor_eligible_oof_outcome_coverage_gte_80pct": all(
            item["pass"] for item in years.values()
        ),
    }
    return {
        "stage": stage,
        "eligible_predictor_anchors": len(eligible_rows),
        "available_primary_outcome_anchors": len(available),
        "unavailable_primary_outcome_anchors": len(eligible_rows) - len(available),
        "completeness": rounded(completeness, 8),
        "completeness_floor": completeness_floor,
        "available_dates": dates,
        "available_blocks": blocks,
        "validation_folds": folds,
        "required_years": years,
        "gates": gates,
        "pass": bool(eligible_rows) and all(gates.values()),
        "outcome_values_inspected": False,
    }


def read_joined(path: Path, *, reference: bool) -> list[dict[str, Any]]:
    parquet = pq.ParquetFile(path)
    if not reference:
        return [dict(row) for row in pq.read_table(path, use_threads=False).to_pylist()]
    rows: list[dict[str, Any]] = []
    for group_index in range(parquet.num_row_groups):
        table = parquet.read_row_group(group_index, use_threads=False)
        for batch in table.to_batches(max_chunksize=7):
            rows.extend(dict(row) for row in pa.Table.from_batches([batch]).to_pylist())
    return rows


def _sample_identity(row: Mapping[str, Any], fold: int, score: float) -> dict[str, Any]:
    sample = {
        "anchor_id": str(row["anchor_id"]),
        "session_date": str(row["session_date"]),
        "selected_month_week_id": str(row["selected_month_week_id"]),
        "chronological_block": int(row["chronological_block"]),
        "anchor_offset_minutes": int(row["anchor_offset_minutes"]),
        "fold": fold,
        "score": float(score),
    }
    for horizon in HORIZONS:
        value = outcome_value(row, horizon)
        sample[f"outcome_{horizon}m"] = value
    require(sample["outcome_15m"] is not None, f"Primary frozen outcome unavailable: {row['anchor_id']}")
    return sample


def evaluate_stage1_test(
    rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]
) -> dict[str, Any]:
    test_id = str(spec["test_id"])
    expected_multiplier = 1.0 if spec["expected_sign"] == "POSITIVE" else -1.0
    samples: list[dict[str, Any]] = []
    fold_models: list[dict[str, Any]] = []
    technical_issues: list[str] = []
    predictor_known_rows = [row for row in rows if predictor_known(row, test_id)]
    missing_primary = sum(not outcome_available(row, 15) for row in predictor_known_rows)
    outcome_coverage = test_specific_outcome_coverage(predictor_known_rows, stage=1)
    if not outcome_coverage["pass"]:
        return {
            "test_id": test_id,
            "stage": 1,
            "expected_sign": spec["expected_sign"],
            "model": "DETERMINISTIC_HUBER_IRLS",
            "predictor_known_anchors": len(predictor_known_rows),
            "predictor_known_dates": len({str(row["session_date"]) for row in predictor_known_rows}),
            "missing_primary_outcomes_on_known_predictor_rows": missing_primary,
            "outcome_coverage": outcome_coverage,
            "fold_models": [],
            "expected_coefficient_sign_every_fold": False,
            "metrics": None,
            "technical_issues": ["INCONCLUSIVE_OUTCOME_COVERAGE"],
            "oof_sample_identity_checksum": canonical_hash([]),
            "outcome_conditioned_calculation_performed": False,
        }
    for fold, train_end, validation_start, validation_end in FOLDS:
        training = [
            row
            for row in rows
            if int(row["chronological_block"]) <= train_end
            and predictor_known(row, test_id)
            and outcome_value(row, 15) is not None
        ]
        validation = [
            row
            for row in rows
            if validation_start <= int(row["chronological_block"]) <= validation_end
            and predictor_known(row, test_id)
            and outcome_value(row, 15) is not None
        ]
        if len(training) < 3:
            technical_issues.append(f"FOLD_{fold}:INCONCLUSIVE_INSUFFICIENT_TRAINING_ROWS")
            continue
        parameters = transform_parameters([float(row[f"{test_id}__value"]) for row in training])
        if parameters is None:
            technical_issues.append(f"FOLD_{fold}:INCONCLUSIVE_MODEL_DEGENERACY")
            continue
        train_x = apply_transform([float(row[f"{test_id}__value"]) for row in training], parameters)
        train_y = np.asarray([float(outcome_value(row, 15)) for row in training], dtype=np.float64)
        model = fit_huber_irls(train_x, train_y)
        if not model["converged"]:
            technical_issues.append(f"FOLD_{fold}:INCONCLUSIVE_MODEL_CONVERGENCE")
        validation_x = apply_transform([float(row[f"{test_id}__value"]) for row in validation], parameters)
        validation_y = [float(outcome_value(row, 15)) for row in validation]
        for row, transformed in zip(validation, validation_x):
            sample = _sample_identity(row, fold, expected_multiplier * float(transformed))
            sample["model_prediction_15m"] = float(model["intercept"] + float(model["coefficient"]) * transformed)
            samples.append(sample)
        fold_models.append(
            {
                "fold": fold,
                "train_blocks": [1, train_end],
                "validation_blocks": [validation_start, validation_end],
                "training_anchors": len(training),
                "training_dates": len({str(row["session_date"]) for row in training}),
                "validation_anchors": len(validation),
                "validation_dates": len({str(row["session_date"]) for row in validation}),
                "transform": {key: rounded(value) if isinstance(value, float) else value for key, value in parameters.items()},
                "huber": {
                    "intercept": rounded(float(model["intercept"])),
                    "coefficient": rounded(float(model["coefficient"])),
                    "iterations": int(model["iterations"]),
                    "converged": bool(model["converged"]),
                    "residual_scale": rounded(float(model["residual_scale"])),
                    "training_mae": rounded(float(model["training_mae"])),
                },
                "expected_coefficient_sign_pass": expected_multiplier * float(model["coefficient"]) > 0,
                "validation_model_prediction_spearman": rounded(
                    spearman(
                        [float(model["intercept"] + float(model["coefficient"]) * value) for value in validation_x],
                        validation_y,
                    )
                ),
            }
        )
    metrics = None
    if samples and len(fold_models) == 3:
        metrics = common_metrics(samples, int(spec["bootstrap_seed_uint64"]), int(spec["permutation_seed_uint64"]))
    return {
        "test_id": test_id,
        "stage": 1,
        "expected_sign": spec["expected_sign"],
        "model": "DETERMINISTIC_HUBER_IRLS",
        "predictor_known_anchors": len(predictor_known_rows),
        "predictor_known_dates": len({str(row["session_date"]) for row in predictor_known_rows}),
        "missing_primary_outcomes_on_known_predictor_rows": missing_primary,
        "outcome_coverage": outcome_coverage,
        "fold_models": fold_models,
        "expected_coefficient_sign_every_fold": len(fold_models) == 3 and all(item["expected_coefficient_sign_pass"] for item in fold_models),
        "metrics": metrics,
        "technical_issues": technical_issues,
        "oof_sample_identity_checksum": canonical_hash([item["anchor_id"] for item in samples]),
        "outcome_conditioned_calculation_performed": True,
    }


def evaluate_stage2_test(
    rows: Sequence[Mapping[str, Any]], spec: Mapping[str, Any]
) -> dict[str, Any]:
    test_id = str(spec["test_id"])
    left = str(spec["left"])
    right = str(spec["right"])
    expected_multiplier = 1.0 if spec["expected_sign"] == "POSITIVE" else -1.0
    eligible_rows = [row for row in rows if predictor_known(row, left) and predictor_known(row, right)]
    missing_primary = sum(not outcome_available(row, 15) for row in eligible_rows)
    outcome_coverage = test_specific_outcome_coverage(eligible_rows, stage=2)
    if not outcome_coverage["pass"]:
        return {
            "test_id": test_id,
            "stage": 2,
            "left": left,
            "right": right,
            "registered_formula": spec["score"],
            "expected_sign": spec["expected_sign"],
            "model": "HIERARCHICAL_RIDGE_MAIN_EFFECTS_PLUS_INTERACTION",
            "joint_predictor_known_anchors": len(eligible_rows),
            "joint_predictor_known_dates": len({str(row["session_date"]) for row in eligible_rows}),
            "missing_primary_outcomes_on_known_predictor_rows": missing_primary,
            "outcome_coverage": outcome_coverage,
            "fold_models": [],
            "expected_coefficient_sign_every_fold": False,
            "incremental_model_comparison": {
                "main_effects_oof_spearman": None,
                "full_model_oof_spearman": None,
                "incremental_oof_spearman": None,
                "main_effects_oof_mae": None,
                "full_model_oof_mae": None,
                "oof_mae_reduction_fraction": None,
            },
            "metrics": None,
            "technical_issues": ["INCONCLUSIVE_OUTCOME_COVERAGE"],
            "oof_sample_identity_checksum": canonical_hash([]),
            "outcome_conditioned_calculation_performed": False,
        }
    samples: list[dict[str, Any]] = []
    fold_models: list[dict[str, Any]] = []
    technical_issues: list[str] = []
    for fold, train_end, validation_start, validation_end in FOLDS:
        training = [
            row
            for row in rows
            if int(row["chronological_block"]) <= train_end
            and predictor_known(row, left)
            and predictor_known(row, right)
            and outcome_value(row, 15) is not None
        ]
        validation = [
            row
            for row in rows
            if validation_start <= int(row["chronological_block"]) <= validation_end
            and predictor_known(row, left)
            and predictor_known(row, right)
            and outcome_value(row, 15) is not None
        ]
        if len(training) < 5:
            technical_issues.append(f"FOLD_{fold}:INCONCLUSIVE_INSUFFICIENT_TRAINING_ROWS")
            continue
        left_parameters = transform_parameters([float(row[f"{left}__value"]) for row in training])
        right_parameters = transform_parameters([float(row[f"{right}__value"]) for row in training])
        if left_parameters is None or right_parameters is None:
            technical_issues.append(f"FOLD_{fold}:INCONCLUSIVE_MODEL_DEGENERACY")
            continue
        train_left_raw = np.asarray([float(row[f"{left}__value"]) for row in training], dtype=np.float64)
        train_right_raw = np.asarray([float(row[f"{right}__value"]) for row in training], dtype=np.float64)
        train_left_z = apply_transform(train_left_raw, left_parameters)
        train_right_z = apply_transform(train_right_raw, right_parameters)
        train_interaction = np.asarray(
            [
                interaction_value(test_id, l_raw, r_raw, l_z, r_z)
                for l_raw, r_raw, l_z, r_z in zip(train_left_raw, train_right_raw, train_left_z, train_right_z)
            ],
            dtype=np.float64,
        )
        train_y = np.asarray([float(outcome_value(row, 15)) for row in training], dtype=np.float64)
        main_x = np.column_stack((train_left_z, train_right_z))
        full_x = np.column_stack((train_left_z, train_right_z, train_interaction))
        main_model = fit_ridge(main_x, train_y, 1.0)
        full_model = fit_ridge(full_x, train_y, 1.0)
        if not main_model["converged"] or not full_model["converged"]:
            technical_issues.append(f"FOLD_{fold}:INCONCLUSIVE_MODEL_CONVERGENCE")

        validation_left_raw = np.asarray([float(row[f"{left}__value"]) for row in validation], dtype=np.float64)
        validation_right_raw = np.asarray([float(row[f"{right}__value"]) for row in validation], dtype=np.float64)
        validation_left_z = apply_transform(validation_left_raw, left_parameters)
        validation_right_z = apply_transform(validation_right_raw, right_parameters)
        validation_interaction = np.asarray(
            [
                interaction_value(test_id, l_raw, r_raw, l_z, r_z)
                for l_raw, r_raw, l_z, r_z in zip(validation_left_raw, validation_right_raw, validation_left_z, validation_right_z)
            ],
            dtype=np.float64,
        )
        validation_main_x = np.column_stack((validation_left_z, validation_right_z))
        validation_full_x = np.column_stack((validation_left_z, validation_right_z, validation_interaction))
        main_predictions = ridge_predict(main_model, validation_main_x)
        full_predictions = ridge_predict(full_model, validation_full_x)
        for index, row in enumerate(validation):
            sample = _sample_identity(row, fold, expected_multiplier * float(validation_interaction[index]))
            sample["main_model_prediction_15m"] = float(main_predictions[index])
            sample["full_model_prediction_15m"] = float(full_predictions[index])
            samples.append(sample)
        fold_models.append(
            {
                "fold": fold,
                "train_blocks": [1, train_end],
                "validation_blocks": [validation_start, validation_end],
                "training_anchors": len(training),
                "training_dates": len({str(row["session_date"]) for row in training}),
                "validation_anchors": len(validation),
                "validation_dates": len({str(row["session_date"]) for row in validation}),
                "left_transform": {key: rounded(value) if isinstance(value, float) else value for key, value in left_parameters.items()},
                "right_transform": {key: rounded(value) if isinstance(value, float) else value for key, value in right_parameters.items()},
                "main_effects_ridge": {
                    "intercept": rounded(float(main_model["intercept"])),
                    "coefficients": [rounded(float(value)) for value in main_model["coefficients"]],
                    "training_mae": rounded(float(main_model["training_mae"])),
                    "converged": bool(main_model["converged"]),
                },
                "full_hierarchical_ridge": {
                    "intercept": rounded(float(full_model["intercept"])),
                    "coefficients": [rounded(float(value)) for value in full_model["coefficients"]],
                    "training_mae": rounded(float(full_model["training_mae"])),
                    "converged": bool(full_model["converged"]),
                },
                "expected_interaction_coefficient_sign_pass": expected_multiplier * float(full_model["coefficients"][2]) > 0,
            }
        )
    metrics = None
    incremental = {
        "main_effects_oof_spearman": None,
        "full_model_oof_spearman": None,
        "incremental_oof_spearman": None,
        "main_effects_oof_mae": None,
        "full_model_oof_mae": None,
        "oof_mae_reduction_fraction": None,
    }
    if samples and len(fold_models) == 3:
        metrics = common_metrics(samples, int(spec["bootstrap_seed_uint64"]), int(spec["permutation_seed_uint64"]))
        outcomes = [float(item["outcome_15m"]) for item in samples]
        main_predictions = [float(item["main_model_prediction_15m"]) for item in samples]
        full_predictions = [float(item["full_model_prediction_15m"]) for item in samples]
        main_rho = spearman(main_predictions, outcomes)
        full_rho = spearman(full_predictions, outcomes)
        main_mae = float(np.mean(np.abs(np.asarray(outcomes) - np.asarray(main_predictions))))
        full_mae = float(np.mean(np.abs(np.asarray(outcomes) - np.asarray(full_predictions))))
        incremental = {
            "main_effects_oof_spearman": rounded(main_rho),
            "full_model_oof_spearman": rounded(full_rho),
            "incremental_oof_spearman": rounded(None if main_rho is None or full_rho is None else full_rho - main_rho),
            "main_effects_oof_mae": rounded(main_mae),
            "full_model_oof_mae": rounded(full_mae),
            "oof_mae_reduction_fraction": rounded((main_mae - full_mae) / main_mae if main_mae > 0 else None),
        }
    return {
        "test_id": test_id,
        "stage": 2,
        "left": left,
        "right": right,
        "registered_formula": spec["score"],
        "expected_sign": spec["expected_sign"],
        "model": "HIERARCHICAL_RIDGE_MAIN_EFFECTS_PLUS_INTERACTION",
        "joint_predictor_known_anchors": len(eligible_rows),
        "joint_predictor_known_dates": len({str(row["session_date"]) for row in eligible_rows}),
        "missing_primary_outcomes_on_known_predictor_rows": missing_primary,
        "outcome_coverage": outcome_coverage,
        "fold_models": fold_models,
        "expected_coefficient_sign_every_fold": len(fold_models) == 3 and all(item["expected_interaction_coefficient_sign_pass"] for item in fold_models),
        "incremental_model_comparison": incremental,
        "metrics": metrics,
        "technical_issues": technical_issues,
        "oof_sample_identity_checksum": canonical_hash([item["anchor_id"] for item in samples]),
        "outcome_conditioned_calculation_performed": True,
    }


def benjamini_hochberg(results: Sequence[Mapping[str, Any]]) -> dict[str, float]:
    total = len(results)
    ordered = sorted(
        (
            str(result["test_id"]),
            float(result["metrics"]["permutation"]["horizons"]["15"]["two_sided_p_value"])
            if result.get("metrics") is not None
            and result["metrics"]["permutation"]["horizons"]["15"]["two_sided_p_value"] is not None
            else 1.0,
        )
        for result in results
    )
    ordered.sort(key=lambda item: (item[1], item[0]))
    adjusted: dict[str, float] = {}
    running = 1.0
    for rank in range(total, 0, -1):
        test_id, p_value = ordered[rank - 1]
        running = min(running, min(1.0, p_value * total / rank))
        adjusted[test_id] = running
    return adjusted


def apply_decision(result: dict[str, Any], q_value: float) -> None:
    metrics = result.get("metrics")
    technical_gates = {
        "test_specific_primary_outcome_coverage_pass": bool(result["outcome_coverage"]["pass"]),
        "three_fold_models_completed": len(result["fold_models"]) == 3,
        "all_models_converged_and_nondegenerate": not result["technical_issues"],
        "primary_metrics_defined": metrics is not None
        and metrics["signed_oof_spearman"] is not None
        and metrics["oof_direction_accuracy"] is not None,
        "bootstrap_finite_rho_gte_19000": metrics is not None
        and int(metrics["bootstrap"]["finite_rho_replicates"]) >= MINIMUM_FINITE_BOOTSTRAPS,
        "bootstrap_finite_accuracy_gte_19000": metrics is not None
        and int(metrics["bootstrap"]["finite_accuracy_lift_replicates"]) >= MINIMUM_FINITE_BOOTSTRAPS,
        "permutation_primary_defined": metrics is not None
        and metrics["permutation"]["horizons"]["15"]["two_sided_p_value"] is not None,
    }
    result["bh_q_value"] = rounded(q_value)
    if metrics is None:
        relationship_gates = {
            "signed_oof_spearman_gte_0_08": False,
            "oof_direction_accuracy_gte_0_54": False,
            "bootstrap_lower_rho_gt_zero": False,
            "bootstrap_lower_accuracy_lift_gt_zero": False,
            "bh_q_lte_0_05": False,
            "all_rolling_validation_fold_rho_gt_zero": False,
            "at_least_two_validation_folds_rho_gte_0_05": False,
            "each_required_year_rho_gt_zero": False,
            "expected_coefficient_sign_every_fold": False,
        }
    else:
        fold_rhos = [metrics["folds"][str(fold)]["rho"] for fold, *_ in FOLDS]
        year_rhos = [metrics["years"][str(year)]["rho"] for year in OOF_YEARS]
        signed_rho = metrics["signed_oof_spearman"]
        direction_accuracy_value = metrics["oof_direction_accuracy"]
        relationship_gates = {
            "signed_oof_spearman_gte_0_08": signed_rho is not None and float(signed_rho) >= 0.08,
            "oof_direction_accuracy_gte_0_54": direction_accuracy_value is not None
            and float(direction_accuracy_value) >= 0.54,
            "bootstrap_lower_rho_gt_zero": metrics["bootstrap"]["rho_ci"][0] is not None and float(metrics["bootstrap"]["rho_ci"][0]) > 0,
            "bootstrap_lower_accuracy_lift_gt_zero": metrics["bootstrap"]["accuracy_lift_ci"][0] is not None and float(metrics["bootstrap"]["accuracy_lift_ci"][0]) > 0,
            "bh_q_lte_0_05": q_value <= 0.05,
            "all_rolling_validation_fold_rho_gt_zero": all(value is not None and float(value) > 0 for value in fold_rhos),
            "at_least_two_validation_folds_rho_gte_0_05": sum(value is not None and float(value) >= 0.05 for value in fold_rhos) >= 2,
            "each_required_year_rho_gt_zero": all(value is not None and float(value) > 0 for value in year_rhos),
            "expected_coefficient_sign_every_fold": bool(result["expected_coefficient_sign_every_fold"]),
        }
    if int(result["stage"]) == 2:
        incremental = result["incremental_model_comparison"]
        relationship_gates["incremental_oof_spearman_gte_0_03"] = (
            incremental["incremental_oof_spearman"] is not None
            and float(incremental["incremental_oof_spearman"]) >= 0.03
        )
        relationship_gates["oof_mae_reduction_gte_0_01"] = (
            incremental["oof_mae_reduction_fraction"] is not None
            and float(incremental["oof_mae_reduction_fraction"]) >= 0.01
        )
    result["technical_gates"] = technical_gates
    result["relationship_and_robustness_gates"] = relationship_gates
    failed_technical = [name for name, passed in technical_gates.items() if not passed]
    failed_relationship = [name for name, passed in relationship_gates.items() if not passed]
    result["failed_technical_gates"] = failed_technical
    result["failed_relationship_and_robustness_gates"] = failed_relationship
    if failed_technical:
        result["verdict"] = "INCONCLUSIVE"
    elif failed_relationship:
        result["verdict"] = "REJECT"
    else:
        result["verdict"] = "PASS"


def stage_payload(
    rows: Sequence[Mapping[str, Any]], registry: Mapping[str, Any], stage: int
) -> dict[str, Any]:
    sessions: dict[str, Any] = {}
    for session in SESSIONS:
        session_rows = [row for row in rows if row["session_code"] == session]
        specs = registry["sessions"][session][f"stage{stage}"]
        if stage == 1:
            results = [evaluate_stage1_test(session_rows, spec) for spec in specs]
            support_fail = [(test_id, "REGISTERED_STAGE1_TEST") for test_id in EXPECTED_STAGE1_FAIL]
        else:
            results = [evaluate_stage2_test(session_rows, spec) for spec in specs]
            support_fail = [
                ("CSR_SESSION_LEVEL_TENSION", "REGISTERED_STAGE2_MODIFIER"),
                *((test_id, "REGISTERED_STAGE2_TEST") for test_id in EXPECTED_STAGE2_FAIL),
            ]
        q_values = benjamini_hochberg(results)
        for result in results:
            apply_decision(result, q_values[str(result["test_id"])])
        sessions[session] = {
            "eligible_test_count": len(results),
            "eligible_test_results": results,
            "preserved_support_fail": [
                {
                    "test_id": test_id,
                    "entity_type": entity_type,
                    "verdict": "SUPPORT_FAIL",
                    "outcome_conditioned_calculation_performed": False,
                }
                for test_id, entity_type in support_fail
            ],
            "verdict_counts": dict(sorted(Counter(str(result["verdict"]) for result in results).items())),
            "complete_family_bh_applied": True,
        }
    return {
        "version": f"GC_CSR_EDGE_DISCOVERY_V3_M3_STAGE_{stage}_RESULTS_V1_0",
        "stage": stage,
        "status": f"COMPLETE_STAGE_{stage}_FROZEN_FAMILY_EVALUATION",
        "sessions": sessions,
        "eligible_tests_evaluated": sum(item["eligible_test_count"] for item in sessions.values()),
        "support_fail_registered_tests_not_outcome_conditioned": 2,
        "support_fail_entities_not_outcome_conditioned": 2 if stage == 1 else 4,
        "calendar_2025_or_2026_values_accessed": False,
        "execution_trades_or_pnl_calculated": False,
    }


def evaluate_stage(paths: Paths, implementation: str, stage: int) -> None:
    require(implementation in {"primary", "reference"}, "Unknown implementation")
    frozen = verify_freeze(paths, require_source=False)
    opening = load_json(paths.output / "outcome_opening.json")
    require(receipt_valid(opening, "opening_receipt") and opening["status"] == "PASS_SINGLE_CONTROLLED_DEVELOPMENT_OUTCOME_JOIN", "Outcome opening not sealed")
    if stage == 2:
        stage1_seal = load_json(paths.output / "stage1_seal.json")
        require(receipt_valid(stage1_seal, "seal_receipt") and stage1_seal["status"] == "PASS_V3_M3_STAGE1_INDEPENDENT_REPRODUCTION_SEALED", "Stage 1 not sealed before Stage 2")
    output_path = paths.output / f"{implementation}_stage{stage}_results.json"
    require(not output_path.exists(), f"Stage output already exists: {output_path}")
    joined_path = paths.output / f"{implementation}_joined_anchor_outcomes.parquet"
    expected_join = opening[f"{implementation}_joined"]
    require(sha256_file(joined_path) == expected_join["sha256"], "Joined payload changed")
    rows = read_joined(joined_path, reference=implementation == "reference")
    registry = load_json(paths.output / "test_registry.json")
    require(receipt_valid(registry, "registry_receipt") and registry["registry_receipt"] == frozen["test_registry_receipt"], "M3 test registry changed")
    payload = stage_payload(rows, registry, stage)
    record = {
        "version": f"GC_CSR_EDGE_DISCOVERY_V3_M3_{implementation.upper()}_STAGE_{stage}_V1_0",
        "implementation": implementation,
        "reader": "ROW_GROUP_BATCH_REFERENCE" if implementation == "reference" else "WHOLE_TABLE_PRIMARY",
        "payload": payload,
        "payload_hash": canonical_hash(payload),
    }
    write_json_once(output_path, record)
    print(canonical_json({"status": payload["status"], "implementation": implementation, "stage": stage, "payload_hash": record["payload_hash"], "verdict_counts": {session: payload["sessions"][session]["verdict_counts"] for session in SESSIONS}}))


def seal_stage1(paths: Paths) -> None:
    verify_freeze(paths, require_source=False)
    primary = load_json(paths.output / "primary_stage1_results.json")
    reference = load_json(paths.output / "reference_stage1_results.json")
    require(primary["payload_hash"] == reference["payload_hash"], "Stage-1 payload hashes differ")
    require(primary["payload"] == reference["payload"], "Stage-1 primary/reference results differ")
    seal = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_STAGE1_SEAL_V1_0",
            "status": "PASS_V3_M3_STAGE1_INDEPENDENT_REPRODUCTION_SEALED",
            "sealed_at_utc": utc_now(),
            "payload_hash": primary["payload_hash"],
            "primary_sha256": sha256_file(paths.output / "primary_stage1_results.json"),
            "reference_sha256": sha256_file(paths.output / "reference_stage1_results.json"),
            "eligible_tests_evaluated": 18,
            "support_fail_tests_not_outcome_conditioned": 2,
            "stage2_started_before_seal": False,
            "calendar_2025_or_2026_values_accessed": False,
            "seal_receipt": None,
        },
        "seal_receipt",
    )
    write_json_once(paths.output / "stage1_seal.json", seal)
    print(canonical_json({"status": seal["status"], "seal_receipt": seal["seal_receipt"], "payload_hash": seal["payload_hash"]}))


def candidate_ranking_key(result: Mapping[str, Any]) -> tuple[Any, ...]:
    metrics = result["metrics"]
    fold_rhos = [float(metrics["folds"][str(fold)]["rho"]) for fold, *_ in FOLDS]
    return (
        float(result["bh_q_value"]),
        -float(metrics["bootstrap"]["rho_ci"][0]),
        -float(metrics["oof_direction_accuracy"]),
        -min(fold_rhos),
        -int(metrics["oof_dates"]),
        str(result["test_id"]),
    )


def report_text(verdict: Mapping[str, Any], complete: Mapping[str, Any]) -> str:
    lines = [
        "# GC Continuous State-Response V3 — Milestone 3 Report",
        "",
        f"Formal process verdict: `{verdict['status']}`",
        "",
        "## Boundary",
        "",
        "- One controlled 2021-11-08 through 2024-12-13 development-outcome value-stream opening was consumed.",
        "- Exactly 5,984 fixed anchors were joined; source gaps remained horizon-specific UNKNOWN under the frozen no-repair policy.",
        "- Calendar 2025 and calendar 2026 remained locked.",
        "- No execution, trades, PnL, R multiples, account returns, or target-return calculations were performed.",
        "",
        "## Test verdicts",
        "",
    ]
    for session in SESSIONS:
        lines.extend([f"### {session.replace('_', ' ').title()}", ""])
        for stage in (1, 2):
            lines.append(f"Stage {stage}:")
            lines.append("")
            for result in complete["sessions"][session][f"stage{stage}"]:
                metrics = result.get("metrics")
                rho = None if metrics is None else metrics["signed_oof_spearman"]
                accuracy = None if metrics is None else metrics["oof_direction_accuracy"]
                failures = [*result["failed_technical_gates"], *result["failed_relationship_and_robustness_gates"]]
                lines.append(
                    f"- `{result['test_id']}`: `{result['verdict']}`; rho `{rho}`, accuracy `{accuracy}`, "
                    f"BH q `{result['bh_q_value']}`; failed gates: {', '.join(failures) if failures else 'none'}."
                )
            lines.append("")
        lines.append(
            "Preserved support failures: `CSR_STRUCTURE_MOMENTUM_15M`, `CSR_SESSION_LEVEL_TENSION`, "
            "and `CSR_INT_OFI_SESSION_LEVEL_TENSION`; no outcome-conditioned statistic was calculated for them."
        )
        lines.append("")
    lines.extend(
        [
            "## Candidate disposition",
            "",
            f"- Development PASS tests before the two-per-session cap: `{verdict['summary']['development_pass_before_cap']}`.",
            f"- Shortlisted provisional candidates: `{verdict['summary']['shortlisted_provisional_candidates']}`.",
            "- A development candidate is not a validated trading edge.",
            "",
        ]
    )
    for session in SESSIONS:
        names = [item["test_id"] for item in verdict["shortlist"][session]]
        lines.append(f"- {session}: {', '.join(names) if names else 'none'}.")
    lines.extend(["", verdict["research_interpretation"], ""])
    return "\n".join(lines)


def seal_final(paths: Paths) -> None:
    frozen = verify_freeze(paths, require_source=False)
    opening = load_json(paths.output / "outcome_opening.json")
    stage1_seal = load_json(paths.output / "stage1_seal.json")
    require(receipt_valid(opening, "opening_receipt"), "Outcome opening receipt invalid")
    require(receipt_valid(stage1_seal, "seal_receipt"), "Stage-1 seal invalid")
    primary_stage1 = load_json(paths.output / "primary_stage1_results.json")
    reference_stage1 = load_json(paths.output / "reference_stage1_results.json")
    primary_stage2 = load_json(paths.output / "primary_stage2_results.json")
    reference_stage2 = load_json(paths.output / "reference_stage2_results.json")
    require(primary_stage1["payload"] == reference_stage1["payload"], "Stage-1 reproduction changed")
    require(primary_stage2["payload"] == reference_stage2["payload"], "Stage-2 reproduction differs")
    require(primary_stage1["payload_hash"] == stage1_seal["payload_hash"], "Stage-1 seal payload changed")

    complete_sessions: dict[str, Any] = {}
    all_results: list[dict[str, Any]] = []
    shortlist: dict[str, list[dict[str, Any]]] = {}
    for session in SESSIONS:
        stage1_results = primary_stage1["payload"]["sessions"][session]["eligible_test_results"]
        stage2_results = primary_stage2["payload"]["sessions"][session]["eligible_test_results"]
        require(len(stage1_results) == 9 and len(stage2_results) == 5, f"Complete test family changed: {session}")
        session_results = [*stage1_results, *stage2_results]
        all_results.extend(session_results)
        passes = sorted((item for item in session_results if item["verdict"] == "PASS"), key=candidate_ranking_key)
        shortlist[session] = [
            {
                "rank": rank,
                "test_id": item["test_id"],
                "stage": item["stage"],
                "bh_q_value": item["bh_q_value"],
                "signed_oof_spearman": item["metrics"]["signed_oof_spearman"],
                "oof_direction_accuracy": item["metrics"]["oof_direction_accuracy"],
                "bootstrap_lower_rho": item["metrics"]["bootstrap"]["rho_ci"][0],
                "development_only": True,
            }
            for rank, item in enumerate(passes[:2], start=1)
        ]
        complete_sessions[session] = {
            "stage1": stage1_results,
            "stage2": stage2_results,
            "preserved_support_fail": [
                "CSR_STRUCTURE_MOMENTUM_15M",
                "CSR_SESSION_LEVEL_TENSION",
                "CSR_INT_OFI_SESSION_LEVEL_TENSION",
            ],
            "verdict_counts": dict(sorted(Counter(str(item["verdict"]) for item in session_results).items())),
        }
    candidate_count = sum(len(items) for items in shortlist.values())
    pass_before_cap = sum(item["verdict"] == "PASS" for item in all_results)
    complete = {
        "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_COMPLETE_RESULTS_V1_0",
        "status": "COMPLETE_FROZEN_CONTINUOUS_RELATIONSHIP_DISCOVERY",
        "sessions": complete_sessions,
        "eligible_tests_evaluated": len(all_results),
        "stage1_tests_evaluated": 18,
        "stage2_tests_evaluated": 10,
        "support_fail_registered_tests_not_outcome_conditioned": 4,
        "support_fail_entities_not_outcome_conditioned": 6,
        "test_result_checksum": canonical_hash(all_results),
        "calendar_2025_or_2026_values_accessed": False,
        "execution_trades_or_pnl_calculated": False,
    }
    write_json_once(paths.output / "complete_results.json", complete)
    status = "PASS_V3_M3_DISCOVERY_WITH_PROVISIONAL_CANDIDATES" if candidate_count else "PASS_V3_M3_DISCOVERY_ZERO_CANDIDATES"
    summary_counts = Counter(str(item["verdict"]) for item in all_results)
    verdict = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_VERDICT_V1_0",
            "status": status,
            "completed_at_utc": utc_now(),
            "summary": {
                "eligible_tests_evaluated": len(all_results),
                "pass": summary_counts.get("PASS", 0),
                "reject": summary_counts.get("REJECT", 0),
                "inconclusive": summary_counts.get("INCONCLUSIVE", 0),
                "development_pass_before_cap": pass_before_cap,
                "shortlisted_provisional_candidates": candidate_count,
            },
            "shortlist": shortlist,
            "research_interpretation": (
                "At least one frozen continuous relationship passed every development gate. These are provisional development candidates, not validated edges or trading signals."
                if candidate_count
                else "No frozen support-eligible continuous relationship passed every development gate; no candidate advances."
            ),
            "freeze_receipt": frozen["freeze_receipt"],
            "outcome_opening_receipt": opening["opening_receipt"],
            "stage1_seal_receipt": stage1_seal["seal_receipt"],
            "stage1_payload_hash": primary_stage1["payload_hash"],
            "stage2_payload_hash": primary_stage2["payload_hash"],
            "outcome_joined_payload_checksum": opening["joined_payload_checksum"],
            "calendar_2025_or_2026_values_accessed": False,
            "execution_entries_exits_trades_pnl_r_multiples_or_returns_calculated": False,
            "verdict_receipt": None,
        },
        "verdict_receipt",
    )
    write_json_once(paths.output / "verdict.json", verdict)
    state = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_STATE_V3_0",
            "status": status,
            "active_branch": "GC_CONTINUOUS_STATE_RESPONSE_EDGE_DISCOVERY_V3",
            "completed_milestone": "M3_SINGLE_DEVELOPMENT_OUTCOME_OPEN_AND_FROZEN_DISCOVERY",
            "m3_freeze_receipt": frozen["freeze_receipt"],
            "m3_verdict_receipt": verdict["verdict_receipt"],
            "candidate_count": candidate_count,
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
            "next_milestone": "M4_CANDIDATE_FREEZE_AND_PRE_HOLDOUT_READINESS" if candidate_count else "NONE_CURRENT_BRANCH_ZERO_CANDIDATES",
            "next_milestone_authorized": False,
            "state_receipt": None,
        },
        "state_receipt",
    )
    write_json_once(paths.output / "state_v03.json", state)
    write_text_once(paths.output / "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_3_REPORT.md", report_text(verdict, complete))

    artifact_names = (
        "population_registry.json",
        "primary_metadata_coverage.json",
        "reference_metadata_coverage.json",
        "test_registry.json",
        "serializer_proof.json",
        "preflight.json",
        "m3_freeze.json",
        "source_opening_ledger.json",
        "outcome_opening.json",
        "primary_joined_anchor_outcomes.parquet",
        "reference_joined_anchor_outcomes.parquet",
        "primary_stage1_results.json",
        "reference_stage1_results.json",
        "stage1_seal.json",
        "primary_stage2_results.json",
        "reference_stage2_results.json",
        "complete_results.json",
        "verdict.json",
        "state_v03.json",
        "GC_CONTINUOUS_STATE_RESPONSE_V3_MILESTONE_3_REPORT.md",
    )
    manifest = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_MANIFEST_V1_0",
            "status": status,
            "sealed_at_utc": utc_now(),
            "predecessors": frozen["predecessors"],
            "freeze_receipt": frozen["freeze_receipt"],
            "outcome_opening_receipt": opening["opening_receipt"],
            "stage1_seal_receipt": stage1_seal["seal_receipt"],
            "verdict_receipt": verdict["verdict_receipt"],
            "state_receipt": state["state_receipt"],
            "artifacts": {name: artifact_record(paths.output / name) for name in artifact_names},
            "independent_reproduction": {
                "outcome_join": True,
                "stage1": True,
                "stage2": True,
                "joined_parquet_byte_identical": True,
            },
            "source_value_stream_openings": 1,
            "complete_eligible_test_registry_recorded": True,
            "all_six_cross_session_support_fail_entities_preserved": True,
            "candidate_repair_retune_inversion_or_filter": False,
            "calendar_2025_or_2026_values_accessed": False,
            "execution_trades_or_pnl_calculated": False,
            "manifest_receipt": None,
        },
        "manifest_receipt",
    )
    write_json_once(paths.output / "manifest.json", manifest)
    final = seal_receipt(
        {
            "version": "GC_CSR_EDGE_DISCOVERY_V3_M3_FINAL_SEAL_V1_0",
            "status": status,
            "sealed_at_utc": utc_now(),
            "freeze_receipt": frozen["freeze_receipt"],
            "manifest_receipt": manifest["manifest_receipt"],
            "manifest_sha256": sha256_file(paths.output / "manifest.json"),
            "verdict_sha256": sha256_file(paths.output / "verdict.json"),
            "state_sha256": sha256_file(paths.output / "state_v03.json"),
            "calendar_2025_or_2026_values_accessed": False,
            "final_seal_receipt": None,
        },
        "final_seal_receipt",
    )
    write_json_once(paths.output / "final_seal.json", final)
    print(canonical_json({"status": status, "summary": verdict["summary"], "shortlist": shortlist, "final_seal_receipt": final["final_seal_receipt"]}))


def verify_final(paths: Paths) -> None:
    frozen = verify_freeze(paths, require_source=False)
    opening = load_json(paths.output / "outcome_opening.json")
    stage1 = load_json(paths.output / "stage1_seal.json")
    verdict = load_json(paths.output / "verdict.json")
    state = load_json(paths.output / "state_v03.json")
    manifest = load_json(paths.output / "manifest.json")
    final = load_json(paths.output / "final_seal.json")
    for record, field in (
        (opening, "opening_receipt"),
        (stage1, "seal_receipt"),
        (verdict, "verdict_receipt"),
        (state, "state_receipt"),
        (manifest, "manifest_receipt"),
        (final, "final_seal_receipt"),
    ):
        require(receipt_valid(record, field), f"Final receipt invalid: {field}")
    require(final["freeze_receipt"] == frozen["freeze_receipt"], "Final freeze linkage changed")
    require(final["manifest_sha256"] == sha256_file(paths.output / "manifest.json"), "Final manifest hash changed")
    require(final["verdict_sha256"] == sha256_file(paths.output / "verdict.json"), "Final verdict hash changed")
    require(final["state_sha256"] == sha256_file(paths.output / "state_v03.json"), "Final state hash changed")
    for name, expected in manifest["artifacts"].items():
        path = paths.output / name
        require(path.is_file(), f"Final artifact missing: {name}")
        require(path.stat().st_size == int(expected["bytes"]), f"Final artifact size changed: {name}")
        require(sha256_file(path) == expected["sha256"], f"Final artifact hash changed: {name}")
    require(
        (paths.output / "primary_joined_anchor_outcomes.parquet").read_bytes()
        == (paths.output / "reference_joined_anchor_outcomes.parquet").read_bytes(),
        "Final joined payloads differ",
    )
    for stage_number in (1, 2):
        primary = load_json(paths.output / f"primary_stage{stage_number}_results.json")
        reference = load_json(paths.output / f"reference_stage{stage_number}_results.json")
        require(primary["payload"] == reference["payload"] and primary["payload_hash"] == reference["payload_hash"], f"Final Stage {stage_number} reproduction differs")
    require(manifest["source_value_stream_openings"] == 1, "Outcome source opening count changed")
    require(not manifest["calendar_2025_or_2026_values_accessed"] and not manifest["execution_trades_or_pnl_calculated"], "Final research locks changed")
    print(canonical_json({"status": "PASS_V3_M3_INDEPENDENT_FINAL_VERIFICATION", "verdict": verdict["status"], "summary": verdict["summary"], "final_seal_receipt": final["final_seal_receipt"]}))


def self_test() -> None:
    ranks = rankdata_average(np.asarray([3.0, 1.0, 1.0, 2.0]))
    require(np.array_equal(ranks, np.asarray([4.0, 1.5, 1.5, 3.0])), "Average-rank proof failed")
    require(abs(float(spearman([1, 2, 3], [2, 4, 8])) - 1.0) < 1e-12, "Spearman proof failed")
    transform = transform_parameters(list(range(-50, 51)))
    require(transform is not None and transform["scale"] > 0, "Transform proof failed")
    x = np.linspace(-3, 3, 301)
    y = 0.4 + 1.7 * x
    y[::37] += 15
    huber = fit_huber_irls(x, y)
    require(huber["converged"] and huber["coefficient"] > 1.0, "Huber proof failed")
    ridge = fit_ridge(np.column_stack((x, x * x)), y, 1.0)
    require(ridge["converged"] and len(ridge["coefficients"]) == 2, "Ridge proof failed")
    samples: list[dict[str, Any]] = []
    for date_index in range(18):
        fold = 1 if date_index < 6 else 2 if date_index < 12 else 3
        block = 11 + date_index
        for offset in (0, 15):
            score = float(date_index - 8.5 + offset / 30)
            samples.append(
                {
                    "anchor_id": f"S:{date_index}:{offset}",
                    "session_date": f"2024-01-{date_index + 1:02d}",
                    "selected_month_week_id": f"B{block:02d}",
                    "chronological_block": block,
                    "anchor_offset_minutes": offset,
                    "fold": fold,
                    "score": score,
                    "outcome_5m": score + 0.1,
                    "outcome_15m": score + 0.2,
                    "outcome_30m": score + 0.3,
                    "outcome_60m": score + 0.4,
                }
            )
    bootstrap = block_bootstrap(samples, 7, repetitions=200)
    permutation = date_cluster_permutations(samples, 11, repetitions=200)
    require(bootstrap["finite_rho_replicates"] == 200, "Bootstrap proof failed")
    require(permutation["horizons"]["15"]["observed_rho"] > 0.99, "Permutation proof failed")
    bh = benjamini_hochberg(
        [
            {"test_id": "A", "metrics": {"permutation": {"horizons": {"15": {"two_sided_p_value": 0.01}}}}},
            {"test_id": "B", "metrics": {"permutation": {"horizons": {"15": {"two_sided_p_value": 0.04}}}}},
        ]
    )
    require(abs(bh["A"] - 0.02) < 1e-12 and abs(bh["B"] - 0.04) < 1e-12, "BH proof failed")
    print(canonical_json({"status": "PASS_V3_M3_SYNTHETIC_MODEL_RESAMPLING_AND_MULTIPLICITY_PROOF", "outcome_values_accessed": False}))


def metadata_diagnostic(paths: Paths) -> None:
    verify_predecessors(paths, require_source=True)
    population, _ = population_registry(paths)
    targets = {
        stamp
        for anchor in population["anchors"]
        for stamp in required_open_ns(int(anchor["decision_at_ns"]))
    }
    result, valid = metadata_coverage_scan(paths.xau_source, targets, reference=False)
    population = attach_outcome_metadata(population, valid)
    print(canonical_json({"coverage": result, "outcome_metadata_support": population["outcome_metadata_support"]}))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "self-test",
            "metadata-diagnostic",
            "prepare",
            "open-outcomes",
            "primary-stage1",
            "reference-stage1",
            "seal-stage1",
            "primary-stage2",
            "reference-stage2",
            "seal-final",
            "verify",
        ),
    )
    parser.add_argument("--data-root", type=Path, default=ROOT)
    parser.add_argument("--m2-output", type=Path)
    parser.add_argument("--r1-output", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    paths = Paths.build(args.data_root.resolve(), args.output, args.m2_output, args.r1_output)
    if args.action == "self-test":
        self_test()
    elif args.action == "metadata-diagnostic":
        metadata_diagnostic(paths)
    elif args.action == "prepare":
        prepare(paths)
    elif args.action == "open-outcomes":
        open_outcomes(paths)
    elif args.action in {"primary-stage1", "reference-stage1", "primary-stage2", "reference-stage2"}:
        implementation = "primary" if args.action.startswith("primary") else "reference"
        stage = 1 if args.action.endswith("stage1") else 2
        evaluate_stage(paths, implementation, stage)
    elif args.action == "seal-stage1":
        seal_stage1(paths)
    elif args.action == "seal-final":
        seal_final(paths)
    else:
        verify_final(paths)


if __name__ == "__main__":
    try:
        main()
    except DiscoveryFailure as exc:
        print(canonical_json({"status": "FAIL", "reason": str(exc)}), file=sys.stderr)
        raise SystemExit(1)
