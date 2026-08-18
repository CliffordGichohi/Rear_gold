#!/usr/bin/env python3
"""Run Step 5D-R3 with the sealed 370-outcome population amendment."""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
import gzip
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

import pyarrow as pa
import pyarrow.parquet as pq

import run_gc_microstructure_step5d as base


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
AMENDMENT_PATH = MANIFESTS / "gc_microstructure_step_5dr3_amendment_v01.json"
POPULATION_PATH = MANIFESTS / "gc_microstructure_step_5dr3_population_v01.json"
FREEZE_PATH = MANIFESTS / "gc_microstructure_step_5dr3_freeze_v01.json"
TEST_REGISTRY_PATH = MANIFESTS / "gc_microstructure_step_5d_test_registry_v01.json"
ROW_REGISTRY_PATH = MANIFESTS / "gc_microstructure_step_5c_row_registry_v01.json"
STEP5C_DIR = ARTIFACTS / "gc_microstructure_step5c_v01"
CASE_DIR = ARTIFACTS / "gold_session_behaviour_v3_case_matrix_v01"
CASE_PATH = CASE_DIR / "cases.jsonl.gz"
PRICE_PATH = ARTIFACTS / "gold_casebook_v01" / "price_bars.jsonl.gz"
OUTPUT_DIR = ARTIFACTS / "gc_microstructure_step5dr3_v01"
REPORT_PATH = ROOT / "GC_MICROSTRUCTURE_STEP_5D_R3_REPORT.md"

ORIGINAL_TOOL_PATH = ROOT / "tools" / "run_gc_microstructure_step5d.py"
ORIGINAL_TOOL_SHA = "b129b18d6f62ba8338c81b05163b9ee8e4cff0fd79d8f3fd89a50b7ecef6e44a"
TEST_REGISTRY_SHA = "e3b7a132f03cebaff4c05cc646e00f0b1867881d0109c65b71f1076e74ab2d4a"
ROW_REGISTRY_SHA = "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225"
STEP5C_DECISION_SHA = "277993e0cd2d5bff2e8f49c6aaf519ac024a1f7ac1ed8bbd0808f5d3213b5d98"
CASE_SHA = "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
PRICE_SHA = "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e"
QUANTUM = Decimal("0.00000001")
DATE_RE = re.compile(rb'"session_date":"(\d{4}-\d{2}-\d{2})"')
SESSION_RE = re.compile(rb'"session_code":"(LONDON|NEW_YORK)"')
OPEN_RE = re.compile(rb'"open_time":"([^"]+)"')
TIMEFRAME_RE = re.compile(rb'"timeframe":"([^"]+)"')
SESSIONS = ("LONDON", "NEW_YORK")


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def write_text(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(path)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError(value)
    return parsed.astimezone(UTC)


def iso_z(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def expected_times(session_date: str, session_code: str) -> tuple[datetime, datetime, datetime]:
    return base._expected_times(session_date, session_code)


def expected_opens(session_date: str, session_code: str) -> list[str]:
    _, cursor, end = expected_times(session_date, session_code)
    output: list[str] = []
    while cursor < end:
        output.append(iso_z(cursor))
        cursor += timedelta(minutes=1)
    if len(output) != 239:
        raise ValueError((session_date, session_code, len(output)))
    return output


def verify_record_hash(record: Mapping[str, Any]) -> None:
    unhashed = deepcopy(record)
    expected = unhashed.pop("record_hash", None)
    if not isinstance(expected, str) or base.canonical_hash(unhashed) != expected:
        raise ValueError(f"Record hash failed: {record.get('record_id')}")


def verify_control() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    amendment = load_json(AMENDMENT_PATH)
    population = load_json(POPULATION_PATH)
    freeze = load_json(FREEZE_PATH)
    registry = load_json(TEST_REGISTRY_PATH)
    if amendment.get("status") != "SEALED_BEFORE_R3_OUTCOME_VALUE_ACCESS":
        raise ValueError("R3 amendment is not sealed")
    if population.get("status") != "SEALED_EXACT_370_OUTCOME_KEY_POPULATION":
        raise ValueError("R3 population is not sealed")
    if freeze.get("status") != "SEALED_BEFORE_R3_OUTCOME_VALUE_ACCESS":
        raise ValueError("R3 freeze is not sealed")
    if base.sha256_file(AMENDMENT_PATH) != freeze["amendment"]["sha256"]:
        raise ValueError("R3 amendment changed")
    if base.sha256_file(POPULATION_PATH) != freeze["population"]["sha256"]:
        raise ValueError("R3 population changed")
    if base.sha256_file(Path(__file__).resolve()) != freeze["implementation"]["sha256"]:
        raise ValueError("R3 implementation changed after freeze")
    if base.sha256_file(ORIGINAL_TOOL_PATH) != ORIGINAL_TOOL_SHA:
        raise ValueError("Original frozen Step 5D implementation changed")
    if base.sha256_file(TEST_REGISTRY_PATH) != TEST_REGISTRY_SHA:
        raise ValueError("Original test registry changed")
    if base.sha256_file(ROW_REGISTRY_PATH) != ROW_REGISTRY_SHA:
        raise ValueError("Step 5C row registry changed")
    for binding in amendment["predecessor_bindings"].values():
        path = ROOT / binding["path"]
        if base.sha256_file(path) != binding["sha256"]:
            raise ValueError(f"Bound predecessor changed: {path}")
    if registry.get("counts", {}).get("total") != 148:
        raise ValueError("Frozen test count changed")
    if len(population["outcome_bearing_keys"]) != 370:
        raise ValueError("Outcome-bearing population changed")
    if len(population["v3_payload_keys"]) != 358 or len(population["recovered_price_bar_keys"]) != 12:
        raise ValueError("R3 source allocation changed")
    if len(population["unknown_keys"]) != 6:
        raise ValueError("R3 UNKNOWN population changed")
    return amendment, population, freeze, registry


def preflight() -> None:
    _, population, freeze, _ = verify_control()
    if OUTPUT_DIR.exists() or REPORT_PATH.exists():
        raise FileExistsError("R3 output already exists")
    paths = {
        "primary_features": (STEP5C_DIR / "primary_decision_features.parquet", STEP5C_DECISION_SHA),
        "reference_features": (STEP5C_DIR / "reference_decision_features.parquet", STEP5C_DECISION_SHA),
        "v3_case_payload": (CASE_PATH, CASE_SHA),
        "casebook_price_bars": (PRICE_PATH, PRICE_SHA),
    }
    checks: dict[str, bool] = {}
    sources: dict[str, Any] = {}
    for name, (path, expected) in paths.items():
        actual = base.sha256_file(path)
        checks[f"{name}_seal"] = actual == expected
        sources[name] = {"path": str(path.relative_to(ROOT)).replace("\\", "/"), "sha256": actual, "bytes": path.stat().st_size}
    checks["primary_feature_metadata_rows_376"] = pq.ParquetFile(paths["primary_features"][0]).metadata.num_rows == 376
    checks["reference_feature_metadata_rows_376"] = pq.ParquetFile(paths["reference_features"][0]).metadata.num_rows == 376
    checks["outcome_population_370"] = len(population["outcome_bearing_keys"]) == 370
    checks["v3_allocation_358"] = len(population["v3_payload_keys"]) == 358
    checks["recovery_allocation_12"] = len(population["recovered_price_bar_keys"]) == 12
    checks["unknown_dispositions_6"] = len(population["unknown_keys"]) == 6
    checks["outcome_values_accessed_before_freeze_false"] = not bool(freeze["outcome_values_accessed_before_freeze"])
    if not all(checks.values()):
        raise ValueError([name for name, passed in checks.items() if not passed])
    OUTPUT_DIR.mkdir(parents=True)
    record = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_PREFLIGHT_V0_1",
        "status": "PASS_R3_PRE_OUTCOME_READINESS",
        "completed_at_utc": utc_now(),
        "checks": checks,
        "sources": sources,
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    record["preflight_receipt"] = base.canonical_hash(record)
    write_json(OUTPUT_DIR / "preflight.json", record)
    print(json.dumps({"status": record["status"], "checks_passed": len(checks), "outcome_values_accessed": False}, indent=2, sort_keys=True))


def extract_v3_outcomes(
    *,
    selected: Mapping[tuple[str, str], Mapping[str, Any]],
    keys: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    metadata_rows = full_rows = 0
    selected_line_numbers: list[int] = []
    with gzip.open(CASE_PATH, "rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            date_match = DATE_RE.search(raw)
            session_match = SESSION_RE.search(raw)
            if date_match is None or session_match is None:
                raise ValueError(f"Case metadata unavailable at line {line_number}")
            metadata_rows += 1
            session_date = date_match.group(1).decode("ascii")
            session_code = session_match.group(1).decode("ascii")
            if session_date > "2024-12-31":
                raise ValueError("2025/2026 case entered R3")
            key = (session_date, session_code)
            if key not in keys:
                continue
            case = json.loads(raw)
            full_rows += 1
            metadata = case["case_metadata"]
            if (str(metadata["session_date"]), str(metadata["session_code"])) != key:
                raise ValueError(f"V3 metadata mismatch: {key}")
            if key in outcomes:
                raise ValueError(f"Duplicate V3 outcome: {key}")
            if metadata.get("data_partition") != "DEVELOPMENT_2021_2024" or metadata.get("access_class") != "DEVELOPMENT":
                raise ValueError(f"V3 partition mismatch: {key}")
            if case.get("quality", {}).get("overall_state") != "VALID" or not case.get("quality", {}).get("outcome_separation_check_passed"):
                raise ValueError(f"V3 quality failed: {key}")
            if base._case_record_hash(case) != metadata.get("record_hash"):
                raise ValueError(f"V3 record hash failed: {key}")
            decision, neutral, end = expected_times(*key)
            if parse_time(str(metadata["decision_at"])) != decision:
                raise ValueError(f"V3 decision mismatch: {key}")
            if parse_time(str(selected[key]["decision_at_utc"])) != decision:
                raise ValueError(f"Feature decision mismatch: {key}")
            neutral_record = case["subsequent_behaviour"]["neutral_reference"]
            if neutral_record.get("method") != "OPEN_OF_FIRST_COMPLETE_1M_BAR_AT_08_01_LOCAL":
                raise ValueError(f"V3 neutral method changed: {key}")
            if parse_time(str(neutral_record["timestamp"])) != neutral:
                raise ValueError(f"V3 neutral timestamp mismatch: {key}")
            primary = base._extract_primary(case)
            reference = base._extract_reference(case)
            if primary != reference or parse_time(primary[2]) != end:
                raise ValueError(f"V3 independent extraction mismatch: {key}")
            if primary[1] not in {"UP", "DOWN", "FLAT"} or base._state_from_displacement(primary[0]) != primary[1]:
                raise ValueError(f"V3 state mismatch: {key}")
            outcomes[key] = {
                "outcome_signed_displacement": primary[0],
                "outcome_state": primary[1],
                "outcome_available_at": end.isoformat(),
                "outcome_lineage_hash": base.canonical_hash({
                    "case_id": metadata["case_id"],
                    "case_record_hash": metadata["record_hash"],
                    "source_line_sha256": hashlib.sha256(raw).hexdigest(),
                    "neutral_source_bar_id": neutral_record["source_bar_id"],
                }),
                "outcome_source_case_id": str(metadata["case_id"]),
                "outcome_source_family": "SEALED_V3_CASE_PAYLOAD",
            }
            selected_line_numbers.append(line_number)
    if metadata_rows != 1659 or full_rows != 358 or set(outcomes) != keys:
        raise ValueError({
            "metadata_rows": metadata_rows,
            "full_rows": full_rows,
            "missing": sorted(keys.difference(outcomes)),
            "extra": sorted(set(outcomes).difference(keys)),
        })
    return outcomes, {
        "source_open_count": 1,
        "metadata_rows_seen": metadata_rows,
        "selected_rows_deserialized": full_rows,
        "selected_line_numbers_hash": base.canonical_hash(selected_line_numbers),
    }


def extract_recovered_outcomes(
    keys: set[tuple[str, str]],
) -> tuple[dict[tuple[str, str], dict[str, Any]], dict[str, Any]]:
    target_to_key: dict[str, tuple[str, str]] = {}
    expected_by_key: dict[tuple[str, str], list[str]] = {}
    for key in sorted(keys):
        expected = expected_opens(*key)
        expected_by_key[key] = expected
        for timestamp in expected:
            if timestamp in target_to_key:
                raise ValueError(f"Overlapping R3 recovery timestamp: {timestamp}")
            target_to_key[timestamp] = key
    bars: dict[tuple[str, str], dict[str, dict[str, Any]]] = defaultdict(dict)
    metadata_rows = selected_rows = 0
    with gzip.open(PRICE_PATH, "rb") as handle:
        for raw in handle:
            metadata_rows += 1
            timeframe_match = TIMEFRAME_RE.search(raw)
            if timeframe_match is None or timeframe_match.group(1) != b"1m":
                continue
            open_match = OPEN_RE.search(raw)
            if open_match is None:
                raise ValueError(f"PRICE_BAR open_time unavailable at row {metadata_rows}")
            normalized_open = iso_z(parse_time(open_match.group(1).decode("ascii")))
            key = target_to_key.get(normalized_open)
            if key is None:
                continue
            bar = json.loads(raw)
            selected_rows += 1
            verify_record_hash(bar)
            if bar.get("record_type") != "PRICE_BAR" or bar.get("provider_code") != "IC_MARKETS_MT5":
                raise ValueError(f"Recovery provider mismatch: {key} {normalized_open}")
            if bar.get("instrument_code") != "XAUUSD" or bar.get("timeframe") != "1m":
                raise ValueError(f"Recovery instrument mismatch: {key} {normalized_open}")
            if bar.get("complete") is not True or bar.get("missing_source_minutes") != 0:
                raise ValueError(f"Recovery incomplete bar: {key} {normalized_open}")
            open_dt = parse_time(str(bar["open_time"]))
            close_dt = parse_time(str(bar["close_time"]))
            available_dt = parse_time(str(bar["available_at"]))
            if close_dt != open_dt + timedelta(minutes=1) or available_dt > close_dt:
                raise ValueError(f"Recovery clock mismatch: {key} {normalized_open}")
            if normalized_open in bars[key]:
                raise ValueError(f"Duplicate recovery bar: {key} {normalized_open}")
            bars[key][normalized_open] = bar
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    key_diagnostics: list[dict[str, Any]] = []
    for key in sorted(keys):
        expected = expected_by_key[key]
        if set(bars[key]) != set(expected):
            raise ValueError(f"Recovery coverage failed: {key} missing={sorted(set(expected).difference(bars[key]))}")
        ordered = [bars[key][timestamp] for timestamp in expected]
        first_open = Decimal(str(ordered[0]["ohlc"]["open"]))
        last_close = Decimal(str(ordered[-1]["ohlc"]["close"]))
        primary_decimal = (last_close - first_open).quantize(QUANTUM, rounding=ROUND_HALF_UP)
        first_scaled = int((first_open / QUANTUM).to_integral_value(rounding=ROUND_HALF_UP))
        last_scaled = int((last_close / QUANTUM).to_integral_value(rounding=ROUND_HALF_UP))
        reference_decimal = (Decimal(last_scaled - first_scaled) * QUANTUM).quantize(QUANTUM)
        if primary_decimal != reference_decimal:
            raise ValueError(f"Recovered independent displacement mismatch: {key}")
        displacement = float(primary_decimal)
        primary_state = base._state_from_displacement(displacement)
        reference_state = (
            "UP" if reference_decimal > Decimal("0.01")
            else "DOWN" if reference_decimal < Decimal("-0.01")
            else "FLAT"
        )
        if primary_state != reference_state:
            raise ValueError(f"Recovered independent state mismatch: {key}")
        _, neutral, end = expected_times(*key)
        if parse_time(str(ordered[0]["open_time"])) != neutral or parse_time(str(ordered[-1]["close_time"])) != end:
            raise ValueError(f"Recovered boundary mismatch: {key}")
        lineage_rows = [
            {
                "record_id": str(bar["record_id"]),
                "record_hash": str(bar["record_hash"]),
                "source_hash": str(bar["source"]["source_hash"]),
                "open_time": str(bar["open_time"]),
                "close_time": str(bar["close_time"]),
            }
            for bar in ordered
        ]
        outcomes[key] = {
            "outcome_signed_displacement": displacement,
            "outcome_state": primary_state,
            "outcome_available_at": end.isoformat(),
            "outcome_lineage_hash": base.canonical_hash({
                "source_artifact_sha256": PRICE_SHA,
                "neutral_method": "OPEN_OF_FIRST_COMPLETE_1M_BAR_AT_08_01_LOCAL",
                "bar_lineage": lineage_rows,
            }),
            "outcome_source_case_id": f"RECOVERED:{key[0]}:{key[1]}",
            "outcome_source_family": "SEALED_GOLD_CASEBOOK_PRICE_BARS",
        }
        key_diagnostics.append({
            "session_date": key[0],
            "session_code": key[1],
            "bar_count": len(ordered),
            "first_open": expected[0],
            "last_open": expected[-1],
            "bar_identity_hash": base.canonical_hash(lineage_rows),
            "primary_reference_exact": True,
        })
    if len(outcomes) != 12 or selected_rows != 12 * 239:
        raise ValueError((len(outcomes), selected_rows))
    return outcomes, {
        "source_open_count": 1,
        "metadata_rows_seen": metadata_rows,
        "selected_rows_deserialized": selected_rows,
        "keys": key_diagnostics,
    }


def open_outcomes() -> None:
    _, population, _, _ = verify_control()
    preflight_record = load_json(OUTPUT_DIR / "preflight.json")
    if preflight_record.get("status") != "PASS_R3_PRE_OUTCOME_READINESS":
        raise ValueError("R3 preflight PASS missing")
    if (OUTPUT_DIR / "outcome_opening.json").exists():
        raise FileExistsError("R3 outcome join was already opened")
    row_registry = load_json(ROW_REGISTRY_PATH)
    registry_by_id = {str(item["row_id"]): item for item in row_registry["rows"]}
    if len(registry_by_id) != 376:
        raise ValueError("Step 5C row registry count changed")
    feature_tables = {
        "primary": pq.read_table(STEP5C_DIR / "primary_decision_features.parquet"),
        "reference": pq.read_table(STEP5C_DIR / "reference_decision_features.parquet"),
    }
    primary_rows = feature_tables["primary"].to_pylist()
    reference_rows = feature_tables["reference"].to_pylist()
    if len(primary_rows) != 376 or base.canonical_hash(primary_rows) != base.canonical_hash(reference_rows):
        raise ValueError("Step 5C independent feature payload changed")
    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in primary_rows:
        key = (str(row["session_date"]), str(row["session_code"]))
        if key in selected:
            raise ValueError(f"Duplicate feature key: {key}")
        selected[key] = row
    population_keys = {
        (str(item["session_date"]), str(item["session_code"]))
        for item in population["all_feature_keys"]
    }
    if set(selected) != population_keys:
        raise ValueError("Feature keys differ from the sealed R3 population")
    v3_keys = {(item["session_date"], item["session_code"]) for item in population["v3_payload_keys"]}
    recovery_keys = {(item["session_date"], item["session_code"]) for item in population["recovered_price_bar_keys"]}
    known_keys = {(item["session_date"], item["session_code"]) for item in population["outcome_bearing_keys"]}
    v3_outcomes, v3_diagnostics = extract_v3_outcomes(selected=selected, keys=v3_keys)
    recovered_outcomes, recovery_diagnostics = extract_recovered_outcomes(recovery_keys)
    outcomes = {**v3_outcomes, **recovered_outcomes}
    if set(outcomes) != known_keys or len(outcomes) != 370:
        raise ValueError("R3 known outcome population mismatch")
    for item in population["unknown_keys"]:
        key = (str(item["session_date"]), str(item["session_code"]))
        disposition = str(item["disposition"])
        if key in outcomes:
            raise ValueError(f"UNKNOWN key has an outcome: {key}")
        outcomes[key] = {
            "outcome_signed_displacement": None,
            "outcome_state": "UNKNOWN",
            "outcome_available_at": "UNKNOWN",
            "outcome_lineage_hash": base.canonical_hash({
                "key": f"{key[0]}|{key[1]}",
                "disposition": disposition,
                "amendment": "STEP_5D_R3",
            }),
            "outcome_source_case_id": disposition,
            "outcome_source_family": "DOCUMENTED_UNAVAILABLE",
        }
    if set(outcomes) != set(selected) or len(outcomes) != 376:
        raise ValueError("R3 complete join population mismatch")

    registry_order = [str(item["row_id"]) for item in row_registry["rows"]]
    joined_rows_by_impl: dict[str, list[dict[str, Any]]] = {}
    joined_tables: dict[str, pa.Table] = {}
    for implementation, table in feature_tables.items():
        rows_by_id = {str(row["row_id"]): row for row in table.to_pylist()}
        if set(rows_by_id) != set(registry_order):
            raise ValueError(f"{implementation} feature identities changed")
        joined_rows: list[dict[str, Any]] = []
        for row_id in registry_order:
            row = dict(rows_by_id[row_id])
            registry_row = registry_by_id[row_id]
            key = (str(row["session_date"]), str(row["session_code"]))
            if key != (str(registry_row["session_date"]), str(registry_row["session_code"])):
                raise ValueError(f"Registry identity mismatch: {row_id}")
            row["selected_month_week_id"] = str(registry_row["selected_month_week_id"])
            row["calendar_year"] = int(str(row["session_date"])[:4])
            row["weekday_index"] = date.fromisoformat(str(row["session_date"])).weekday()
            row.update(outcomes[key])
            joined_rows.append(row)
        joined_rows_by_impl[implementation] = joined_rows
        joined_tables[implementation] = pa.Table.from_pylist(joined_rows)
    joined_hash = base.canonical_hash(joined_rows_by_impl["primary"])
    if joined_hash != base.canonical_hash(joined_rows_by_impl["reference"]):
        raise ValueError("R3 independent joins differ")
    paths = {
        "primary": OUTPUT_DIR / "primary_joined_development.parquet",
        "reference": OUTPUT_DIR / "reference_joined_development.parquet",
    }
    for implementation in ("primary", "reference"):
        base._write_parquet_exclusive(paths[implementation], joined_tables[implementation])
    if paths["primary"].read_bytes() != paths["reference"].read_bytes():
        raise ValueError("R3 joined Parquet files are not byte-identical")
    projection_rows = [
        {"session_date": key[0], "session_code": key[1], **outcomes[key]}
        for key in sorted(outcomes)
    ]
    projection_path = OUTPUT_DIR / "outcome_projection.parquet"
    base._write_parquet_exclusive(projection_path, pa.Table.from_pylist(projection_rows))
    counts = Counter(row["outcome_state"] for row in projection_rows)
    record = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_OUTCOME_OPENING_V0_1",
        "status": "PASS_R3_SINGLE_CONTROLLED_RECOVERY_OUTCOME_CONSTRUCTION_AND_JOIN",
        "completed_at_utc": utc_now(),
        "recovery_join_operation_count": 1,
        "historical_step5d_source_open_record_preserved": 1,
        "r3_v3_case_payload_open_count": v3_diagnostics["source_open_count"],
        "r3_price_source_open_count": recovery_diagnostics["source_open_count"],
        "v3_outcomes": len(v3_outcomes),
        "recovered_price_bar_outcomes": len(recovered_outcomes),
        "known_outcomes": counts["UP"] + counts["DOWN"] + counts["FLAT"],
        "unknown_outcomes": counts["UNKNOWN"],
        "joined_rows": len(projection_rows),
        "sessions": {
            session: {
                "feature_rows": sum(row["session_code"] == session for row in projection_rows),
                "known_outcomes": sum(row["session_code"] == session and row["outcome_state"] != "UNKNOWN" for row in projection_rows),
            }
            for session in SESSIONS
        },
        "v3_source_diagnostics": v3_diagnostics,
        "recovery_source_diagnostics": recovery_diagnostics,
        "primary_reference_outcome_extraction_exact": True,
        "primary_reference_join_exact": True,
        "primary_reference_joined_parquet_byte_identical": True,
        "joined_payload_hash": joined_hash,
        "files": {
            "primary_joined": {"path": str(paths["primary"]), "sha256": base.sha256_file(paths["primary"])},
            "reference_joined": {"path": str(paths["reference"]), "sha256": base.sha256_file(paths["reference"])},
            "outcome_projection": {"path": str(projection_path), "sha256": base.sha256_file(projection_path)},
        },
        "secondary_outcomes_admitted_to_testing": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    if record["known_outcomes"] != 370 or record["unknown_outcomes"] != 6:
        raise ValueError("R3 outcome count gate failed")
    record["opening_receipt"] = base.canonical_hash(record)
    write_json(OUTPUT_DIR / "outcome_opening.json", record)
    print(json.dumps({
        "status": record["status"],
        "known_outcomes": record["known_outcomes"],
        "unknown_outcomes": record["unknown_outcomes"],
        "v3_outcomes": record["v3_outcomes"],
        "recovered_outcomes": record["recovered_price_bar_outcomes"],
        "joined_payload_hash": joined_hash,
    }, indent=2, sort_keys=True))


def evaluate_stage(implementation: str, stage: int) -> None:
    _, _, _, registry = verify_control()
    opening = load_json(OUTPUT_DIR / "outcome_opening.json")
    if opening.get("status") != "PASS_R3_SINGLE_CONTROLLED_RECOVERY_OUTCOME_CONSTRUCTION_AND_JOIN":
        raise ValueError("R3 outcome join PASS missing")
    if stage == 2:
        seal = load_json(OUTPUT_DIR / "stage1_seal.json")
        if seal.get("status") != "PASS_R3_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED":
            raise ValueError("R3 Stage 1 must be sealed first")
        verify_stage_files(seal, 1)
    path = OUTPUT_DIR / f"{implementation}_joined_development.parquet"
    if base.sha256_file(path) != opening["files"][f"{implementation}_joined"]["sha256"]:
        raise ValueError("R3 joined payload changed")
    rows = pq.read_table(path).to_pylist()
    tests = [item for item in registry["tests"] if int(item["stage"]) == stage]
    results: list[dict[str, Any]] = []
    for session in SESSIONS:
        session_rows = [row for row in rows if row["session_code"] == session]
        if len(session_rows) != 188:
            raise ValueError(f"{session} row count changed")
        for test in [item for item in tests if item["session"] == session]:
            results.append(base._evaluate_test(session_rows, test, implementation))
    results.sort(key=lambda item: (item["session"], item["test_id"]))
    base._finalize_verdicts(results, stage)
    summary = {
        session: {
            "registered": sum(item["session"] == session for item in results),
            "support_fail": sum(item["session"] == session and item["verdict"] == "SUPPORT_FAIL" for item in results),
            "rejected": sum(item["session"] == session and item["verdict"] == "REJECT" for item in results),
            "provisional_pass": sum(
                item["session"] == session and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"
                for item in results
            ),
        }
        for session in SESSIONS
    }
    payload = {
        "stage": stage,
        "test_results": results,
        "summary": summary,
        "development_feature_rows": 376,
        "effective_known_outcomes": 370,
        "outcome_joined_payload_hash": opening["joined_payload_hash"],
        "amendment_sha256": base.sha256_file(AMENDMENT_PATH),
        "population_sha256": base.sha256_file(POPULATION_PATH),
        "original_test_registry_sha256": TEST_REGISTRY_SHA,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    record = {
        "version": f"GC_MICROSTRUCTURE_STEP_5D_R3_STAGE_{stage}_RUN_V0_1",
        "implementation": implementation,
        "completed_at_utc": utc_now(),
        "payload": payload,
        "payload_hash": base.canonical_hash(payload),
    }
    write_json(OUTPUT_DIR / f"{implementation}_stage{stage}_results.json", record)
    print(json.dumps({
        "implementation": implementation,
        "stage": stage,
        "payload_hash": record["payload_hash"],
        "summary": summary,
    }, indent=2, sort_keys=True))


def verify_stage_files(seal: Mapping[str, Any], stage: int) -> None:
    for implementation in ("primary", "reference"):
        path = OUTPUT_DIR / f"{implementation}_stage{stage}_results.json"
        if base.sha256_file(path) != seal["files"][implementation]["sha256"]:
            raise ValueError(f"R3 Stage {stage} file changed: {implementation}")
        if load_json(path)["payload_hash"] != seal["payload_hash"]:
            raise ValueError(f"R3 Stage {stage} payload changed: {implementation}")


def seal_stage1() -> None:
    verify_control()
    records = {
        implementation: load_json(OUTPUT_DIR / f"{implementation}_stage1_results.json")
        for implementation in ("primary", "reference")
    }
    if records["primary"]["payload_hash"] != records["reference"]["payload_hash"]:
        raise ValueError("R3 Stage 1 independent reproduction failed")
    seal = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_STAGE_1_SEAL_V0_1",
        "status": "PASS_R3_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED",
        "sealed_at_utc": utc_now(),
        "payload_hash": records["primary"]["payload_hash"],
        "independent_reproduction_exact": True,
        "stage_1_completed_before_stage_2": True,
        "summary": records["primary"]["payload"]["summary"],
        "files": {
            implementation: {
                "path": str((OUTPUT_DIR / f"{implementation}_stage1_results.json").relative_to(ROOT)).replace("\\", "/"),
                "sha256": base.sha256_file(OUTPUT_DIR / f"{implementation}_stage1_results.json"),
            }
            for implementation in ("primary", "reference")
        },
        "year_2025_or_2026_values_accessed": False,
    }
    seal["seal_receipt"] = base.canonical_hash(seal)
    write_json(OUTPUT_DIR / "stage1_seal.json", seal)
    print(json.dumps({"status": seal["status"], "payload_hash": seal["payload_hash"], "summary": seal["summary"]}, indent=2, sort_keys=True))


def ranking_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return base._ranking_key(item)


def seal_final() -> None:
    amendment, population, freeze, _ = verify_control()
    opening = load_json(OUTPUT_DIR / "outcome_opening.json")
    stage1 = load_json(OUTPUT_DIR / "stage1_seal.json")
    verify_stage_files(stage1, 1)
    stage2 = {
        implementation: load_json(OUTPUT_DIR / f"{implementation}_stage2_results.json")
        for implementation in ("primary", "reference")
    }
    if stage2["primary"]["payload_hash"] != stage2["reference"]["payload_hash"]:
        raise ValueError("R3 Stage 2 independent reproduction failed")
    all_results = [
        *load_json(OUTPUT_DIR / "primary_stage1_results.json")["payload"]["test_results"],
        *stage2["primary"]["payload"]["test_results"],
    ]
    if len(all_results) != 148:
        raise ValueError("R3 complete test count changed")
    shortlist: dict[str, list[dict[str, Any]]] = {}
    overflow: dict[str, list[str]] = {}
    for session in SESSIONS:
        passing = [
            item for item in all_results
            if item["session"] == session and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"
        ]
        passing.sort(key=ranking_key)
        shortlist[session] = [
            {
                "rank": rank,
                "test_id": item["test_id"],
                "stage": item["stage"],
                "conditions": item["conditions"],
                "favorable_direction": item["favorable_direction"],
                "effect_pp": item["effect_pp"],
                "bootstrap_95pct_ci_pp": item["bootstrap_95pct_ci_pp"],
                "p_value": item["p_value"],
                "bh_q_value": item["bh_q_value"],
                "condition_binary_rows": item["condition_binary_rows"],
                "condition_distinct_weeks": item["condition_distinct_weeks"],
                "label": "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED",
            }
            for rank, item in enumerate(passing[:2], start=1)
        ]
        overflow[session] = [str(item["test_id"]) for item in passing[2:]]
    final_status = (
        "PASS_STEP_5D_R3_DISCOVERY_WITH_PROVISIONAL_CANDIDATES"
        if any(shortlist.values())
        else "PASS_STEP_5D_R3_DISCOVERY_ZERO_CANDIDATES"
    )
    summary = {
        "registered_tests": len(all_results),
        "support_fail": sum(item["verdict"] == "SUPPORT_FAIL" for item in all_results),
        "rejected": sum(item["verdict"] == "REJECT" for item in all_results),
        "development_pass_before_cap": sum(
            item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" for item in all_results
        ),
        "shortlisted_provisional_candidates": sum(len(value) for value in shortlist.values()),
        "pass_not_shortlisted_cap": sum(len(value) for value in overflow.values()),
        "by_session_stage": {
            f"{session}_STAGE_{stage}": {
                "registered": sum(item["session"] == session and item["stage"] == stage for item in all_results),
                "support_fail": sum(
                    item["session"] == session and item["stage"] == stage and item["verdict"] == "SUPPORT_FAIL"
                    for item in all_results
                ),
                "rejected": sum(
                    item["session"] == session and item["stage"] == stage and item["verdict"] == "REJECT"
                    for item in all_results
                ),
                "pass": sum(
                    item["session"] == session
                    and item["stage"] == stage
                    and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"
                    for item in all_results
                ),
            }
            for session in SESSIONS for stage in (1, 2)
        },
    }
    complete_payload = {
        "status": final_status,
        "summary": summary,
        "shortlist": shortlist,
        "pass_not_shortlisted_cap": overflow,
        "all_test_results_hash": base.canonical_hash(all_results),
        "stage1_payload_hash": stage1["payload_hash"],
        "stage2_payload_hash": stage2["primary"]["payload_hash"],
        "outcome_joined_payload_hash": opening["joined_payload_hash"],
        "amendment_sha256": base.sha256_file(AMENDMENT_PATH),
        "population_sha256": base.sha256_file(POPULATION_PATH),
        "original_test_registry_sha256": TEST_REGISTRY_SHA,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    complete_results_path = OUTPUT_DIR / "complete_results.json"
    write_json(complete_results_path, {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_COMPLETE_RESULTS_V0_1",
        "results": all_results,
        "payload": complete_payload,
    })
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_VERDICT_V0_1",
        "status": final_status,
        "formal_step_pass": True,
        "completed_at_utc": utc_now(),
        "effective_known_outcomes": 370,
        "documented_unknown_rows": 6,
        "summary": summary,
        "shortlist": shortlist,
        "pass_not_shortlisted_cap": overflow,
        "research_interpretation": (
            "Development evidence produced provisional unvalidated candidates; no trading edge or out-of-sample validity is claimed."
            if any(shortlist.values())
            else "No registered condition passed every frozen development gate; no edge candidate advances."
        ),
        "development_only": True,
        "out_of_sample_validation_credit": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    verdict["verdict_hash"] = base.canonical_hash(verdict)
    verdict_path = OUTPUT_DIR / "verdict.json"
    write_json(verdict_path, verdict)
    artifacts: dict[str, Any] = {}
    for name in (
        "preflight.json", "outcome_opening.json", "outcome_projection.parquet",
        "primary_joined_development.parquet", "reference_joined_development.parquet",
        "primary_stage1_results.json", "reference_stage1_results.json", "stage1_seal.json",
        "primary_stage2_results.json", "reference_stage2_results.json", "complete_results.json", "verdict.json",
    ):
        path = OUTPUT_DIR / name
        artifacts[name] = {
            "path": str(path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": base.sha256_file(path),
            "bytes": path.stat().st_size,
        }
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_MANIFEST_V0_1",
        "status": final_status,
        "sealed_at_utc": utc_now(),
        "predecessors": {
            "amendment_receipt": amendment["amendment_receipt"],
            "population_receipt": population["population_receipt"],
            "freeze_receipt": freeze["freeze_receipt"],
            "outcome_opening_receipt": opening["opening_receipt"],
            "stage1_seal_receipt": stage1["seal_receipt"],
        },
        "independent_reproduction": {
            "outcome_extraction_and_join": True,
            "stage_1": True,
            "stage_2": True,
            "primary_stage2_payload_hash": stage2["primary"]["payload_hash"],
            "reference_stage2_payload_hash": stage2["reference"]["payload_hash"],
        },
        "artifacts": artifacts,
        "summary": summary,
        "shortlist": shortlist,
        "pass_not_shortlisted_cap": overflow,
        "historical_step5d_source_open_record_preserved": 1,
        "r3_recovery_join_operation_count": 1,
        "r3_v3_case_payload_open_count": 1,
        "r3_price_source_open_count": 1,
        "development_feature_rows": 376,
        "effective_known_outcomes": 370,
        "documented_unknown_rows": 6,
        "all_148_frozen_tests_recorded": True,
        "candidate_repair_retune_inversion_or_filter": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    manifest["manifest_hash"] = base.canonical_hash(manifest)
    manifest_path = OUTPUT_DIR / "manifest.json"
    write_json(manifest_path, manifest)
    report_lines = [
        "# GC Microstructure Step 5D-R3 Report",
        "",
        f"Formal status: `{final_status}`",
        "",
        "## Complete frozen search",
        "",
        f"- Effective known outcomes: `370` (186 London, 184 New York).",
        f"- Explicit UNKNOWN rows: `6` (two Good Friday, four source-unavailable).",
        f"- Registered tests: `{summary['registered_tests']}`.",
        f"- Support failures: `{summary['support_fail']}`.",
        f"- Support-eligible rejections: `{summary['rejected']}`.",
        f"- Development passes before cap: `{summary['development_pass_before_cap']}`.",
        f"- Shortlisted provisional candidates: `{summary['shortlisted_provisional_candidates']}`.",
        f"- Passing but excluded by cap: `{summary['pass_not_shortlisted_cap']}`.",
        "",
        "## Provisional shortlist",
        "",
    ]
    for session in SESSIONS:
        report_lines.extend([f"### {session.replace('_', ' ').title()}", ""])
        if not shortlist[session]:
            report_lines.append("No candidate passed every frozen gate.")
        else:
            for item in shortlist[session]:
                report_lines.append(
                    f"- Rank {item['rank']}: `{item['test_id']}` — favorable `{item['favorable_direction']}`, "
                    f"effect `{item['effect_pp']}` pp, 95% cluster CI `{item['bootstrap_95pct_ci_pp']}`, "
                    f"BH q `{item['bh_q_value']}`, support `{item['condition_binary_rows']}` rows across "
                    f"`{item['condition_distinct_weeks']}` weeks."
                )
        report_lines.append("")
    report_lines.extend([
        "## Scope boundary",
        "",
        "All results are development-only conditional direction-frequency evidence. A shortlisted candidate is not a validated edge, trade, or account-return claim.",
        "",
        "Calendar 2025 and 2026 remained locked. No execution, trade, PnL, R multiple, or account return was calculated. Step 5D-R3 stops here.",
        "",
    ])
    write_text(REPORT_PATH, "\n".join(report_lines))
    final_seal = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_R3_FINAL_SEAL_V0_1",
        "status": final_status,
        "manifest_sha256": base.sha256_file(manifest_path),
        "manifest_hash": manifest["manifest_hash"],
        "verdict_sha256": base.sha256_file(verdict_path),
        "verdict_hash": verdict["verdict_hash"],
        "complete_results_sha256": base.sha256_file(complete_results_path),
        "report_sha256": base.sha256_file(REPORT_PATH),
        "sealed_at_utc": utc_now(),
    }
    final_seal["final_seal_receipt"] = base.canonical_hash(final_seal)
    write_json(OUTPUT_DIR / "final_seal.json", final_seal)
    print(json.dumps({
        "status": final_status,
        "summary": summary,
        "shortlist": shortlist,
        "manifest_hash": manifest["manifest_hash"],
        "verdict_hash": verdict["verdict_hash"],
        "final_seal_sha256": base.sha256_file(OUTPUT_DIR / "final_seal.json"),
    }, indent=2, sort_keys=True))


def verify_final() -> None:
    verify_control()
    manifest = load_json(OUTPUT_DIR / "manifest.json")
    verdict = load_json(OUTPUT_DIR / "verdict.json")
    seal = load_json(OUTPUT_DIR / "final_seal.json")
    manifest_copy = dict(manifest)
    manifest_hash = manifest_copy.pop("manifest_hash", None)
    if manifest_hash != base.canonical_hash(manifest_copy):
        raise ValueError("R3 manifest hash failed")
    verdict_copy = dict(verdict)
    verdict_hash = verdict_copy.pop("verdict_hash", None)
    if verdict_hash != base.canonical_hash(verdict_copy):
        raise ValueError("R3 verdict hash failed")
    for metadata in manifest["artifacts"].values():
        path = ROOT / metadata["path"]
        if base.sha256_file(path) != metadata["sha256"]:
            raise ValueError(f"R3 artifact changed: {path}")
    if base.sha256_file(OUTPUT_DIR / "manifest.json") != seal["manifest_sha256"]:
        raise ValueError("R3 final manifest seal failed")
    if base.sha256_file(REPORT_PATH) != seal["report_sha256"]:
        raise ValueError("R3 report seal failed")
    if manifest["effective_known_outcomes"] != 370 or not manifest["all_148_frozen_tests_recorded"]:
        raise ValueError("R3 completion gate failed")
    print(json.dumps({
        "status": manifest["status"],
        "all_artifact_hashes_verified": True,
        "effective_known_outcomes": 370,
        "registered_tests": manifest["summary"]["registered_tests"],
        "shortlisted_provisional_candidates": manifest["summary"]["shortlisted_provisional_candidates"],
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }, indent=2, sort_keys=True))


def self_test() -> None:
    values = expected_opens("2023-08-15", "LONDON")
    if len(values) != 239 or values[0] != "2023-08-15T07:01:00Z" or values[-1] != "2023-08-15T10:59:00Z":
        raise AssertionError("R3 DST window self-test failed")
    if base._state_from_displacement(0.01) != "FLAT" or base._state_from_displacement(0.01000001) != "UP":
        raise AssertionError("R3 outcome threshold self-test failed")
    print(json.dumps({"status": "PASS_R3_SYNTHETIC_SELF_TEST", "outcome_values_accessed": False}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=(
            "self-test", "preflight", "open-outcomes", "primary-stage1", "reference-stage1",
            "seal-stage1", "primary-stage2", "reference-stage2", "seal-final", "verify",
        ),
    )
    args = parser.parse_args()
    if args.action == "self-test":
        self_test()
    elif args.action == "preflight":
        preflight()
    elif args.action == "open-outcomes":
        open_outcomes()
    elif args.action == "primary-stage1":
        evaluate_stage("primary", 1)
    elif args.action == "reference-stage1":
        evaluate_stage("reference", 1)
    elif args.action == "seal-stage1":
        seal_stage1()
    elif args.action == "primary-stage2":
        evaluate_stage("primary", 2)
    elif args.action == "reference-stage2":
        evaluate_stage("reference", 2)
    elif args.action == "seal-final":
        seal_final()
    else:
        verify_final()


if __name__ == "__main__":
    main()
