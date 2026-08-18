#!/usr/bin/env python3
"""Run sealed Step 5D development conditional-edge discovery.

The program is action-gated so that the development outcome source is streamed
exactly once, Stage 1 is fully reproduced and sealed before Stage 2, and the
final result can be verified without reopening the source case matrix.
"""

from __future__ import annotations

import argparse
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import UTC, date, datetime, time
import gzip
import hashlib
import json
import math
from pathlib import Path
import re
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFEST_DIR = ROOT / "research_manifests"
PROTOCOL_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_protocol_v01.json"
TEST_REGISTRY_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_test_registry_v01.json"
FREEZE_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_freeze_v01.json"
ORIGINAL_IMPLEMENTATION_SEAL_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_implementation_v01.json"
IMPLEMENTATION_AMENDMENT_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_implementation_amendment_a_v01.json"
IMPLEMENTATION_SEAL_PATH = MANIFEST_DIR / "gc_microstructure_step_5d_implementation_v02.json"
ROW_REGISTRY_PATH = MANIFEST_DIR / "gc_microstructure_step_5c_row_registry_v01.json"

DEFAULT_STEP5C = ROOT / "artifacts" / "gc_microstructure_step5c_v01"
DEFAULT_CASES = ROOT / "artifacts" / "gold_session_behaviour_v3_case_matrix_v01"
DEFAULT_OUTPUT = ROOT / "artifacts" / "gc_microstructure_step5d_v01"

EXPECTED_PROTOCOL_SHA256 = "835361070b3955912938b5519ec0b7b32542d6774c895f43bde11a93fb268b64"
EXPECTED_TEST_REGISTRY_SHA256 = "e3b7a132f03cebaff4c05cc646e00f0b1867881d0109c65b71f1076e74ab2d4a"
EXPECTED_FREEZE_SHA256 = "982464e185fabaab57b5871506fc3f75b9f577267eb3bcd52ebd83a4fbf2725d"
EXPECTED_FREEZE_RECEIPT = "7eafca4f3d9f0402911b5a82bdbd9bd9c0fd0732cc30e7106e5ea1c00a2df47c"
EXPECTED_ROW_REGISTRY_SHA256 = "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225"
EXPECTED_STEP5C_MANIFEST_SHA256 = "f7150f861f4883e3f7c100822af527ba497b8343225c24ebe16ffe11107e31fb"
EXPECTED_STEP5C_VERDICT_SHA256 = "f98702e5260f60fa258a8f5ed43adc944724075bf442f958677fdf8fe3dee2ad"
EXPECTED_STEP5C_DECISION_SHA256 = "277993e0cd2d5bff2e8f49c6aaf519ac024a1f7ac1ed8bbd0808f5d3213b5d98"
EXPECTED_CASE_MANIFEST_SHA256 = "dddbe125d11afef2094b7843f5521b7bbfcc95178e3fa376b60af8bdd2efc3b5"
EXPECTED_CASE_PAYLOAD_SHA256 = "d0f5120713b5f9ce641c6285941bfc23d3aac3b83b561c8fc1138e33a5ede9b9"
EXPECTED_ORIGINAL_IMPLEMENTATION_SEAL_SHA256 = "dce2e997e6c95fa2bf2eb0759595bb3ad80dd298b7d30897f63ca65d8f2fac7a"
EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256 = "436300bc285914a9151c3fe74ec25a8b6c7651716a2e94c0e0c86f39537332fe"

SESSIONS = ("LONDON", "NEW_YORK")
UNKNOWN_STATES = frozenset(("UNKNOWN", "NEUTRAL_OR_UNKNOWN", "UNKNOWN_WITHOUT_EVENT_AND_REGIME_CORE"))
DOCUMENTED_UNAVAILABLE = frozenset(("2022-04-15|LONDON", "2022-04-15|NEW_YORK"))
OUTCOME_STATES = frozenset(("UP", "DOWN", "FLAT", "UNKNOWN"))
DATE_RE = re.compile(rb'"session_date":"(\d{4}-\d{2}-\d{2})"')
SESSION_RE = re.compile(rb'"session_code":"(LONDON|NEW_YORK)"')


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        value = json.load(handle)
    if not isinstance(value, dict):
        raise TypeError(f"Expected object: {path}")
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def write_text_exclusive(path: Path, value: str) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite sealed artifact: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8", newline="\n")
    temporary.replace(path)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def rounded(value: float | None, digits: int = 10) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    answer = round(float(value), digits)
    return 0.0 if answer == -0.0 else answer


def verify_control() -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    expected_files = {
        PROTOCOL_PATH: EXPECTED_PROTOCOL_SHA256,
        TEST_REGISTRY_PATH: EXPECTED_TEST_REGISTRY_SHA256,
        FREEZE_PATH: EXPECTED_FREEZE_SHA256,
        ROW_REGISTRY_PATH: EXPECTED_ROW_REGISTRY_SHA256,
    }
    for path, expected in expected_files.items():
        actual = sha256_file(path)
        if actual != expected:
            raise ValueError(f"Frozen control file changed: {path} {actual}")
    protocol = load_json(PROTOCOL_PATH)
    tests = load_json(TEST_REGISTRY_PATH)
    freeze = load_json(FREEZE_PATH)
    if freeze.get("status") != "SEALED_BEFORE_DEVELOPMENT_OUTCOME_ACCESS":
        raise ValueError("Step 5D pre-outcome freeze missing")
    if freeze.get("freeze_receipt") != EXPECTED_FREEZE_RECEIPT:
        raise ValueError("Step 5D freeze receipt changed")
    if freeze.get("development_outcomes_accessed_before_freeze"):
        raise ValueError("Freeze records pre-freeze outcome access")
    if protocol.get("authority", {}).get("year_2025") != "LOCKED":
        raise ValueError("2025 lock changed")
    if protocol.get("authority", {}).get("year_2026") != "LOCKED":
        raise ValueError("2026 lock changed")
    if tests.get("counts", {}).get("total") != 148:
        raise ValueError("Frozen test count changed")
    return protocol, tests, freeze


def verify_implementation_seal() -> dict[str, Any]:
    if sha256_file(ORIGINAL_IMPLEMENTATION_SEAL_PATH) != EXPECTED_ORIGINAL_IMPLEMENTATION_SEAL_SHA256:
        raise ValueError("Original Step 5D implementation seal changed")
    if sha256_file(IMPLEMENTATION_AMENDMENT_PATH) != EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256:
        raise ValueError("Step 5D implementation Amendment A changed")
    seal = load_json(IMPLEMENTATION_SEAL_PATH)
    if seal.get("status") != "SEALED_BEFORE_DEVELOPMENT_OUTCOME_ACCESS":
        raise ValueError("Implementation seal status changed")
    if seal.get("tool_sha256") != sha256_file(Path(__file__)):
        raise ValueError("Step 5D implementation changed after sealing")
    if seal.get("protocol_sha256") != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Implementation bound to a different protocol")
    if seal.get("test_registry_sha256") != EXPECTED_TEST_REGISTRY_SHA256:
        raise ValueError("Implementation bound to a different test registry")
    if seal.get("freeze_sha256") != EXPECTED_FREEZE_SHA256:
        raise ValueError("Implementation bound to a different freeze")
    if seal.get("amendment_a_sha256") != EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256:
        raise ValueError("Implementation is not bound to Amendment A")
    if seal.get("original_implementation_seal_sha256") != EXPECTED_ORIGINAL_IMPLEMENTATION_SEAL_SHA256:
        raise ValueError("Implementation does not preserve its original seal")
    receipt = dict(seal)
    embedded = receipt.pop("implementation_receipt", None)
    if embedded != canonical_hash(receipt):
        raise ValueError("Implementation receipt fails")
    return seal


def seal_implementation() -> None:
    verify_control()
    if sha256_file(ORIGINAL_IMPLEMENTATION_SEAL_PATH) != EXPECTED_ORIGINAL_IMPLEMENTATION_SEAL_SHA256:
        raise ValueError("Original implementation seal changed")
    if sha256_file(IMPLEMENTATION_AMENDMENT_PATH) != EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256:
        raise ValueError("Implementation Amendment A changed")
    if IMPLEMENTATION_SEAL_PATH.exists():
        raise FileExistsError("Implementation was already sealed")
    record: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_IMPLEMENTATION_V0_2",
        "status": "SEALED_BEFORE_DEVELOPMENT_OUTCOME_ACCESS",
        "sealed_at_utc": utc_now(),
        "tool_path": str(Path(__file__).relative_to(ROOT)).replace("\\", "/"),
        "tool_sha256": sha256_file(Path(__file__)),
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "test_registry_sha256": EXPECTED_TEST_REGISTRY_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "original_implementation_seal_sha256": EXPECTED_ORIGINAL_IMPLEMENTATION_SEAL_SHA256,
        "amendment_a_sha256": EXPECTED_IMPLEMENTATION_AMENDMENT_SHA256,
        "preserved_attempt_1_verdict": "FAIL_PRE_OUTCOME_METADATA_CHECK_IMPLEMENTATION",
        "development_outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "algorithms": {
            "primary": "vectorized week-block accumulation",
            "reference": "independent indexed week-block accumulation",
            "shared_random_schedule": "NumPy PCG64 with exact per-test uint64 seeds",
        },
    }
    record["implementation_receipt"] = canonical_hash(record)
    write_json_exclusive(IMPLEMENTATION_SEAL_PATH, record)
    print(json.dumps(record, indent=2, sort_keys=True))


def preflight(step5c: Path, cases: Path, output: Path) -> None:
    verify_control()
    implementation = verify_implementation_seal()
    checks: dict[str, bool] = {}
    paths = {
        "step5c_manifest": (step5c / "manifest.json", EXPECTED_STEP5C_MANIFEST_SHA256),
        "step5c_verdict": (step5c / "verdict.json", EXPECTED_STEP5C_VERDICT_SHA256),
        "primary_decision": (step5c / "primary_decision_features.parquet", EXPECTED_STEP5C_DECISION_SHA256),
        "reference_decision": (step5c / "reference_decision_features.parquet", EXPECTED_STEP5C_DECISION_SHA256),
        "case_manifest": (cases / "manifest.json", EXPECTED_CASE_MANIFEST_SHA256),
        "case_payload": (cases / "cases.jsonl.gz", EXPECTED_CASE_PAYLOAD_SHA256),
    }
    source_hashes: dict[str, Any] = {}
    for name, (path, expected) in paths.items():
        actual = sha256_file(path)
        checks[f"{name}_seal"] = actual == expected
        source_hashes[name] = {"path": str(path), "sha256": actual, "bytes": path.stat().st_size}
    manifest = load_json(step5c / "manifest.json")
    verdict = load_json(step5c / "verdict.json")
    case_manifest = load_json(cases / "manifest.json")
    checks["step5c_pass"] = (
        manifest.get("status") == "PASS_STEP_5C_FEATURE_MATERIALIZATION"
        and verdict.get("formal_pass") is True
    )
    checks["step5c_outcome_blind"] = (
        manifest.get("development_outcomes_accessed") is False
        and verdict.get("development_outcomes_opened_or_joined") is False
    )
    checks["case_source_development_only"] = (
        case_manifest.get("development_partition", {}).get("session_date_end_inclusive") == "2024-12-31"
    )
    checks["output_absent"] = not output.exists()
    if not all(checks.values()):
        raise ValueError(f"Preflight failed: {[name for name, passed in checks.items() if not passed]}")
    record = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_PREFLIGHT_V0_1",
        "status": "PASS_PRE_OUTCOME_READINESS",
        "completed_at_utc": utc_now(),
        "checks": checks,
        "sources": source_hashes,
        "implementation_receipt": implementation["implementation_receipt"],
        "development_outcomes_accessed": False,
        "year_2025_or_2026_values_accessed": False,
    }
    output.mkdir(parents=True, exist_ok=False)
    write_json_exclusive(output / "preflight.json", record)
    print(json.dumps(record, indent=2, sort_keys=True))


def _case_record_hash(case: Mapping[str, Any]) -> str:
    unhashed = deepcopy(case)
    metadata = unhashed.get("case_metadata")
    if not isinstance(metadata, dict):
        raise ValueError("Missing case_metadata")
    metadata.pop("record_hash", None)
    return canonical_hash(unhashed)


def _parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _expected_times(session_date: str, session: str) -> tuple[datetime, datetime, datetime]:
    zone = ZoneInfo("Europe/London" if session == "LONDON" else "America/New_York")
    local_date = date.fromisoformat(session_date)
    decision = datetime.combine(local_date, time(8, 0), tzinfo=zone).astimezone(UTC)
    neutral = datetime.combine(local_date, time(8, 1), tzinfo=zone).astimezone(UTC)
    end = datetime.combine(local_date, time(12, 0), tzinfo=zone).astimezone(UTC)
    return decision, neutral, end


def _state_from_displacement(value: float) -> str:
    if value > 0.01:
        return "UP"
    if value < -0.01:
        return "DOWN"
    return "FLAT"


def _extract_primary(case: Mapping[str, Any]) -> tuple[float, str, str]:
    outcome = case["subsequent_behaviour"]
    signed = float(outcome["neutral_excursions"]["signed_close_displacement"]["value"])
    state = str(outcome["path_classification"]["value"]["net_state"])
    return signed, state, str(outcome["observation_end"])


def _extract_reference(case: Mapping[str, Any]) -> tuple[float, str, str]:
    outcome = case["subsequent_behaviour"]
    horizons = [item for item in outcome["fixed_horizons"] if item["horizon"] == "SESSION_CLOSE"]
    if len(horizons) != 1:
        raise ValueError("Expected exactly one SESSION_CLOSE horizon")
    signed = float(horizons[0]["signed_displacement"]["value"])
    return signed, _state_from_displacement(signed), str(horizons[0]["horizon_end"])


def _table_rows(table: pa.Table) -> list[dict[str, Any]]:
    return table.to_pylist()


def _write_parquet_exclusive(path: Path, table: pa.Table) -> None:
    if path.exists():
        raise FileExistsError(f"Refusing to overwrite: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        row_group_size=max(1, table.num_rows),
    )
    temporary.replace(path)


def open_outcomes_once(step5c: Path, cases: Path, output: Path) -> None:
    verify_control()
    verify_implementation_seal()
    preflight_record = load_json(output / "preflight.json")
    if preflight_record.get("status") != "PASS_PRE_OUTCOME_READINESS":
        raise ValueError("Preflight PASS missing")
    if (output / "outcome_opening.json").exists():
        raise FileExistsError("Outcome source was already opened for Step 5D")

    row_registry = load_json(ROW_REGISTRY_PATH)
    registry_by_id = {str(item["row_id"]): item for item in row_registry["rows"]}
    if len(registry_by_id) != 376:
        raise ValueError("Step 5C row registry count changed")

    feature_tables = {
        "primary": pq.read_table(step5c / "primary_decision_features.parquet"),
        "reference": pq.read_table(step5c / "reference_decision_features.parquet"),
    }
    if feature_tables["primary"].num_rows != 376 or feature_tables["reference"].num_rows != 376:
        raise ValueError("Step 5C decision row count changed")
    if feature_tables["primary"].schema != feature_tables["reference"].schema:
        raise ValueError("Primary/reference Step 5C schemas differ")
    primary_rows = _table_rows(feature_tables["primary"])
    reference_rows = _table_rows(feature_tables["reference"])
    if canonical_hash(primary_rows) != canonical_hash(reference_rows):
        raise ValueError("Primary/reference Step 5C decision values differ")

    selected: dict[tuple[str, str], dict[str, Any]] = {}
    for row in primary_rows:
        key = (str(row["session_date"]), str(row["session_code"]))
        if key in selected:
            raise ValueError(f"Duplicate feature key: {key}")
        if key[0] < "2021-11-08" or key[0] > "2024-12-13":
            raise ValueError(f"Feature key outside frozen development sample: {key}")
        selected[key] = row
    if len(selected) != 376:
        raise ValueError("Selected feature key count changed")

    selected_available = {
        key for key in selected if f"{key[0]}|{key[1]}" not in DOCUMENTED_UNAVAILABLE
    }
    outcomes: dict[tuple[str, str], dict[str, Any]] = {}
    metadata_rows_seen = 0
    full_selected_rows_deserialized = 0
    unselected_outcomes_deserialized = 0
    source_line_numbers: list[int] = []
    with gzip.open(cases / "cases.jsonl.gz", "rb") as handle:
        for line_number, raw in enumerate(handle, start=1):
            date_match = DATE_RE.search(raw)
            session_match = SESSION_RE.search(raw)
            if date_match is None or session_match is None:
                raise ValueError(f"Case metadata unavailable at line {line_number}")
            metadata_rows_seen += 1
            session_date = date_match.group(1).decode("ascii")
            session = session_match.group(1).decode("ascii")
            if session_date > "2024-12-31":
                raise ValueError("A 2025/2026 row entered the sealed development case payload")
            key = (session_date, session)
            if key not in selected_available:
                continue
            case = json.loads(raw)
            full_selected_rows_deserialized += 1
            metadata = case["case_metadata"]
            actual_key = (str(metadata["session_date"]), str(metadata["session_code"]))
            if actual_key != key:
                raise ValueError(f"Metadata regex/full parse mismatch: {key} {actual_key}")
            if key in outcomes:
                raise ValueError(f"Duplicate selected outcome: {key}")
            if metadata.get("data_partition") != "DEVELOPMENT_2021_2024":
                raise ValueError("Non-development selected outcome")
            if metadata.get("access_class") != "DEVELOPMENT":
                raise ValueError("Selected outcome access class changed")
            if case.get("quality", {}).get("overall_state") != "VALID":
                raise ValueError(f"Invalid selected case: {key}")
            if not case.get("quality", {}).get("outcome_separation_check_passed"):
                raise ValueError(f"Outcome separation failed: {key}")
            if _case_record_hash(case) != metadata.get("record_hash"):
                raise ValueError(f"Selected case record hash failed: {key}")
            decision, neutral, end = _expected_times(session_date, session)
            feature_decision = _parse_time(str(selected[key]["decision_at_utc"]))
            if _parse_time(str(metadata["decision_at"])) != decision or feature_decision != decision:
                raise ValueError(f"Decision timestamp mismatch: {key}")
            outcome = case["subsequent_behaviour"]
            neutral_record = outcome["neutral_reference"]
            if neutral_record.get("method") != "OPEN_OF_FIRST_COMPLETE_1M_BAR_AT_08_01_LOCAL":
                raise ValueError(f"Neutral reference method changed: {key}")
            if _parse_time(str(neutral_record["timestamp"])) != neutral:
                raise ValueError(f"Neutral timestamp mismatch: {key}")
            primary = _extract_primary(case)
            reference = _extract_reference(case)
            if primary != reference:
                raise ValueError(f"Independent outcome extraction mismatch: {key}")
            if _parse_time(primary[2]) != end:
                raise ValueError(f"Outcome end mismatch: {key}")
            if primary[1] not in OUTCOME_STATES or primary[1] == "UNKNOWN":
                raise ValueError(f"Unexpected selected outcome state: {key}")
            if _state_from_displacement(primary[0]) != primary[1]:
                raise ValueError(f"Outcome threshold mismatch: {key}")
            line_hash = hashlib.sha256(raw).hexdigest()
            outcomes[key] = {
                "outcome_signed_displacement": primary[0],
                "outcome_state": primary[1],
                "outcome_available_at": end.isoformat(),
                "outcome_lineage_hash": canonical_hash(
                    {
                        "case_id": metadata["case_id"],
                        "case_record_hash": metadata["record_hash"],
                        "source_line_sha256": line_hash,
                        "neutral_source_bar_id": neutral_record["source_bar_id"],
                    }
                ),
                "outcome_source_case_id": str(metadata["case_id"]),
            }
            source_line_numbers.append(line_number)

    if metadata_rows_seen != 1659:
        raise ValueError(f"Case metadata row count changed: {metadata_rows_seen}")
    if set(outcomes) != selected_available or full_selected_rows_deserialized != 374:
        missing = sorted(selected_available.difference(outcomes))
        extra = sorted(set(outcomes).difference(selected_available))
        raise ValueError(f"Selected outcome coverage failed: missing={missing} extra={extra}")

    for key in selected:
        if key not in outcomes:
            token = f"{key[0]}|{key[1]}"
            if token not in DOCUMENTED_UNAVAILABLE:
                raise ValueError(f"Undocumented missing outcome: {key}")
            outcomes[key] = {
                "outcome_signed_displacement": None,
                "outcome_state": "UNKNOWN",
                "outcome_available_at": "UNKNOWN",
                "outcome_lineage_hash": canonical_hash(
                    {"key": token, "disposition": "UNAVAILABLE_DOCUMENTED_CME_GOOD_FRIDAY"}
                ),
                "outcome_source_case_id": "UNAVAILABLE_DOCUMENTED",
            }

    joined_tables: dict[str, pa.Table] = {}
    joined_rows_by_impl: dict[str, list[dict[str, Any]]] = {}
    registry_order = [str(item["row_id"]) for item in row_registry["rows"]]
    for implementation, table in feature_tables.items():
        rows_by_id = {str(row["row_id"]): row for row in _table_rows(table)}
        if set(rows_by_id) != set(registry_order):
            raise ValueError(f"{implementation} feature row identities changed")
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

    joined_hash = canonical_hash(joined_rows_by_impl["primary"])
    if joined_hash != canonical_hash(joined_rows_by_impl["reference"]):
        raise ValueError("Independent joined feature/outcome payloads differ")
    if joined_tables["primary"].schema != joined_tables["reference"].schema:
        raise ValueError("Independent joined schemas differ")

    paths = {
        "primary": output / "primary_joined_development.parquet",
        "reference": output / "reference_joined_development.parquet",
    }
    for implementation in ("primary", "reference"):
        _write_parquet_exclusive(paths[implementation], joined_tables[implementation])
    if paths["primary"].read_bytes() != paths["reference"].read_bytes():
        raise ValueError("Joined Parquet outputs are not byte-identical")

    projection_rows = [
        {
            "session_date": key[0],
            "session_code": key[1],
            **outcomes[key],
        }
        for key in sorted(outcomes)
    ]
    projection_table = pa.Table.from_pylist(projection_rows)
    projection_path = output / "outcome_projection.parquet"
    _write_parquet_exclusive(projection_path, projection_table)

    record = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_OUTCOME_OPENING_V0_1",
        "status": "PASS_SINGLE_DEVELOPMENT_OUTCOME_OPEN_AND_JOIN",
        "completed_at_utc": utc_now(),
        "source_stream_open_count": 1,
        "source_metadata_rows_seen": metadata_rows_seen,
        "selected_outcome_rows_deserialized": full_selected_rows_deserialized,
        "unselected_outcomes_deserialized": unselected_outcomes_deserialized,
        "selected_available_outcomes": 374,
        "documented_unknown_outcomes": 2,
        "joined_rows": 376,
        "sessions": {"LONDON": 188, "NEW_YORK": 188},
        "primary_reference_outcome_extraction_exact": True,
        "primary_reference_join_exact": True,
        "primary_reference_joined_parquet_byte_identical": True,
        "joined_payload_hash": joined_hash,
        "source_selected_line_numbers_hash": canonical_hash(source_line_numbers),
        "files": {
            "primary_joined": {"path": str(paths["primary"]), "sha256": sha256_file(paths["primary"])},
            "reference_joined": {"path": str(paths["reference"]), "sha256": sha256_file(paths["reference"])},
            "outcome_projection": {"path": str(projection_path), "sha256": sha256_file(projection_path)},
        },
        "outcome_source_sha256": EXPECTED_CASE_PAYLOAD_SHA256,
        "development_outcomes_opened": True,
        "secondary_outcomes_admitted_to_testing": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    record["opening_receipt"] = canonical_hash(record)
    write_json_exclusive(output / "outcome_opening.json", record)
    print(json.dumps(record, indent=2, sort_keys=True))


def _field_known(row: Mapping[str, Any], field: str) -> bool:
    state = str(row.get(f"{field}__state", "UNKNOWN"))
    epistemic = str(row.get(f"{field}__epistemic_status", "UNKNOWN"))
    quality = str(row.get(f"{field}__quality", "MISSING"))
    signature = str(row.get(f"{field}__source_signature", "UNKNOWN"))
    return (
        state not in UNKNOWN_STATES
        and epistemic != "UNKNOWN"
        and quality not in {"MISSING", "INVALID"}
        and signature != "UNKNOWN"
    )


def _effect(rows: Sequence[Mapping[str, Any]], condition: np.ndarray, complement: np.ndarray, favorable: str) -> float | None:
    states = np.asarray([row["outcome_state"] for row in rows], dtype=object)
    binary = np.isin(states, ("UP", "DOWN"))
    cond = condition & binary
    comp = complement & binary
    if not cond.any() or not comp.any():
        return None
    return 100.0 * (float(np.mean(states[cond] == favorable)) - float(np.mean(states[comp] == favorable)))


def _bootstrap_effects(
    rows: Sequence[Mapping[str, Any]],
    condition: np.ndarray,
    complement: np.ndarray,
    favorable: str,
    seed: int,
    implementation: str,
    replicates: int = 20_000,
) -> np.ndarray:
    states = np.asarray([row["outcome_state"] for row in rows], dtype=object)
    binary = np.isin(states, ("UP", "DOWN"))
    success = states == favorable
    years = np.asarray([int(row["calendar_year"]) for row in rows], dtype=np.int64)
    weeks = np.asarray([str(row["selected_month_week_id"]) for row in rows], dtype=object)
    grouped: list[tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]] = []
    for year in (2021, 2022, 2023, 2024):
        year_weeks = sorted(set(weeks[years == year]))
        cn: list[int] = []
        cs: list[int] = []
        pn: list[int] = []
        ps: list[int] = []
        for week in year_weeks:
            mask = (years == year) & (weeks == week)
            cond = mask & condition & binary
            comp = mask & complement & binary
            cn.append(int(cond.sum()))
            cs.append(int((cond & success).sum()))
            pn.append(int(comp.sum()))
            ps.append(int((comp & success).sum()))
        grouped.append(
            (
                np.asarray(cn, dtype=np.int64),
                np.asarray(cs, dtype=np.int64),
                np.asarray(pn, dtype=np.int64),
                np.asarray(ps, dtype=np.int64),
            )
        )
    rng = np.random.Generator(np.random.PCG64(seed))
    effects = np.full(replicates, np.nan, dtype=np.float64)
    batch_size = 1000
    for start in range(0, replicates, batch_size):
        size = min(batch_size, replicates - start)
        total_cn = np.zeros(size, dtype=np.int64)
        total_cs = np.zeros(size, dtype=np.int64)
        total_pn = np.zeros(size, dtype=np.int64)
        total_ps = np.zeros(size, dtype=np.int64)
        for cn, cs, pn, ps in grouped:
            count = len(cn)
            draws = rng.integers(0, count, size=(size, count), endpoint=False)
            if implementation == "primary":
                total_cn += cn[draws].sum(axis=1)
                total_cs += cs[draws].sum(axis=1)
                total_pn += pn[draws].sum(axis=1)
                total_ps += ps[draws].sum(axis=1)
            else:
                for column in range(count):
                    selected = draws[:, column]
                    total_cn += np.take(cn, selected)
                    total_cs += np.take(cs, selected)
                    total_pn += np.take(pn, selected)
                    total_ps += np.take(ps, selected)
        valid = (total_cn > 0) & (total_pn > 0)
        effects[start : start + size][valid] = 100.0 * (
            total_cs[valid] / total_cn[valid] - total_ps[valid] / total_pn[valid]
        )
    return effects


def _permutation_extremes(
    rows: Sequence[Mapping[str, Any]],
    condition: np.ndarray,
    complement: np.ndarray,
    favorable: str,
    observed: float,
    seed: int,
    implementation: str,
    replicates: int = 100_000,
) -> tuple[int, int]:
    grouped: list[tuple[np.ndarray, np.ndarray, np.ndarray]] = []
    for year in (2021, 2022, 2023, 2024):
        year_rows = [row for row in rows if int(row["calendar_year"]) == year]
        week_ids = sorted({str(row["selected_month_week_id"]) for row in year_rows})
        week_lookup = {week: index for index, week in enumerate(week_ids)}
        outcomes = np.zeros((len(week_ids), 5), dtype=np.int8)
        cond = np.zeros((len(week_ids), 5), dtype=bool)
        comp = np.zeros((len(week_ids), 5), dtype=bool)
        row_index = {str(row["row_id"]): index for index, row in enumerate(rows)}
        for row in year_rows:
            week_index = week_lookup[str(row["selected_month_week_id"])]
            weekday = int(row["weekday_index"])
            code = {"UNKNOWN": 0, "UP": 1, "DOWN": 2, "FLAT": 3}[str(row["outcome_state"])]
            outcomes[week_index, weekday] = code
            index = row_index[str(row["row_id"])]
            cond[week_index, weekday] = bool(condition[index])
            comp[week_index, weekday] = bool(complement[index])
        grouped.append((outcomes, cond, comp))

    favorable_code = 1 if favorable == "UP" else 2
    rng = np.random.Generator(np.random.PCG64(seed))
    extreme = 0
    nonfinite = 0
    batch_size = 1000
    threshold = abs(observed) - 1e-12
    for start in range(0, replicates, batch_size):
        size = min(batch_size, replicates - start)
        total_cn = np.zeros(size, dtype=np.int64)
        total_cs = np.zeros(size, dtype=np.int64)
        total_pn = np.zeros(size, dtype=np.int64)
        total_ps = np.zeros(size, dtype=np.int64)
        for outcomes, cond, comp in grouped:
            count = outcomes.shape[0]
            permutations = np.argsort(rng.random((size, count)), axis=1, kind="stable")
            if implementation == "primary":
                permuted = outcomes[permutations, :]
                binary = (permuted == 1) | (permuted == 2)
                success = permuted == favorable_code
                total_cn += (binary & cond[None, :, :]).sum(axis=(1, 2))
                total_cs += (success & cond[None, :, :]).sum(axis=(1, 2))
                total_pn += (binary & comp[None, :, :]).sum(axis=(1, 2))
                total_ps += (success & comp[None, :, :]).sum(axis=(1, 2))
            else:
                for target_week in range(count):
                    block = outcomes[permutations[:, target_week], :]
                    binary = (block == 1) | (block == 2)
                    success = block == favorable_code
                    total_cn += (binary & cond[target_week][None, :]).sum(axis=1)
                    total_cs += (success & cond[target_week][None, :]).sum(axis=1)
                    total_pn += (binary & comp[target_week][None, :]).sum(axis=1)
                    total_ps += (success & comp[target_week][None, :]).sum(axis=1)
        valid = (total_cn > 0) & (total_pn > 0)
        effects = np.zeros(size, dtype=np.float64)
        effects[valid] = 100.0 * (
            total_cs[valid] / total_cn[valid] - total_ps[valid] / total_pn[valid]
        )
        extreme += int((valid & (np.abs(effects) >= threshold)).sum())
        nonfinite += int((~valid).sum())
    return extreme, nonfinite


def _bh_adjust(results: list[dict[str, Any]]) -> None:
    eligible = [item for item in results if item["p_value"] is not None]
    eligible.sort(key=lambda item: (float(item["p_value"]), str(item["test_id"])))
    count = len(eligible)
    running = 1.0
    for reverse_index in range(count - 1, -1, -1):
        rank = reverse_index + 1
        value = min(1.0, float(eligible[reverse_index]["p_value"]) * count / rank)
        running = min(running, value)
        eligible[reverse_index]["bh_q_value"] = rounded(running, 12)


def _condition_masks(rows: Sequence[Mapping[str, Any]], test: Mapping[str, Any]) -> tuple[np.ndarray, np.ndarray, dict[str, float]]:
    conditions = list(test["conditions"])
    known = np.ones(len(rows), dtype=bool)
    exact = np.ones(len(rows), dtype=bool)
    constituent_coverage: dict[str, float] = {}
    for condition in conditions:
        field = str(condition["field"])
        state = str(condition["state"])
        field_known = np.asarray([_field_known(row, field) for row in rows], dtype=bool)
        field_exact = np.asarray([str(row[f"{field}__state"]) == state for row in rows], dtype=bool)
        constituent_coverage[field] = float(field_known.mean())
        known &= field_known
        exact &= field_exact
    condition_mask = known & exact
    complement_mask = known & ~exact
    return condition_mask, complement_mask, constituent_coverage


def _stability(
    rows: Sequence[Mapping[str, Any]],
    condition: np.ndarray,
    complement: np.ndarray,
    favorable: str,
    stage: int,
) -> dict[str, Any]:
    years = np.asarray([int(row["calendar_year"]) for row in rows], dtype=np.int64)
    states = np.asarray([row["outcome_state"] for row in rows], dtype=object)
    binary = np.isin(states, ("UP", "DOWN"))
    annual: list[dict[str, Any]] = []
    per_year_floor = 5 if stage == 1 else 4
    supported_positive = 0
    supported_bad = False
    for year in (2021, 2022, 2023, 2024):
        year_mask = years == year
        cond = condition & binary & year_mask
        comp = complement & binary & year_mask
        effect = _effect(rows, condition & year_mask, complement & year_mask, favorable)
        supported = int(cond.sum()) >= per_year_floor and int(comp.sum()) >= 1
        if supported and effect is not None and effect > 0:
            supported_positive += 1
        if supported and effect is not None and effect <= -10.0:
            supported_bad = True
        annual.append(
            {
                "year": year,
                "condition_binary_rows": int(cond.sum()),
                "complement_binary_rows": int(comp.sum()),
                "effect_pp": rounded(effect),
                "supported": supported,
            }
        )

    leave_one_out: list[dict[str, Any]] = []
    loo_pass = True
    for year in (2021, 2022, 2023, 2024):
        keep = years != year
        cond_n = int((condition & binary & keep).sum())
        comp_n = int((complement & binary & keep).sum())
        effect = _effect(rows, condition & keep, complement & keep, favorable)
        passed = cond_n > 0 and comp_n > 0 and effect is not None and effect > 0
        loo_pass &= passed
        leave_one_out.append(
            {
                "omitted_year": year,
                "condition_binary_rows": cond_n,
                "complement_binary_rows": comp_n,
                "effect_pp": rounded(effect),
                "pass": passed,
            }
        )

    week_first_date: dict[str, str] = {}
    for row in rows:
        week = str(row["selected_month_week_id"])
        current = week_first_date.get(week)
        session_date = str(row["session_date"])
        if current is None or session_date < current:
            week_first_date[week] = session_date
    ordered_weeks = sorted(week_first_date, key=lambda week: (week_first_date[week], week))
    if len(ordered_weeks) != 38:
        raise ValueError(f"Expected 38 selected monthly weeks, got {len(ordered_weeks)}")
    week_values = np.asarray([str(row["selected_month_week_id"]) for row in rows], dtype=object)
    rolling: list[dict[str, Any]] = []
    for start in range(0, len(ordered_weeks) - 12 + 1):
        selected_weeks = set(ordered_weeks[start : start + 12])
        mask = np.asarray([week in selected_weeks for week in week_values], dtype=bool)
        cond_n = int((condition & binary & mask).sum())
        comp_n = int((complement & binary & mask).sum())
        effect = _effect(rows, condition & mask, complement & mask, favorable)
        evaluable = cond_n > 0 and comp_n > 0 and effect is not None
        rolling.append(
            {
                "start_week": ordered_weeks[start],
                "end_week": ordered_weeks[start + 11],
                "condition_binary_rows": cond_n,
                "complement_binary_rows": comp_n,
                "effect_pp": rounded(effect),
                "evaluable": evaluable,
                "positive": bool(evaluable and effect is not None and effect > 0),
            }
        )
    evaluable = [item for item in rolling if item["evaluable"]]
    positive_fraction = (
        sum(item["positive"] for item in evaluable) / len(evaluable) if evaluable else 0.0
    )
    annual_gate = supported_positive >= 3 and not supported_bad
    rolling_gate = len(evaluable) >= 10 and positive_fraction >= 0.70
    return {
        "annual": annual,
        "annual_supported_positive_count": supported_positive,
        "annual_no_supported_effect_lte_minus_10pp": not supported_bad,
        "annual_gate_pass": annual_gate,
        "leave_one_year_out": leave_one_out,
        "leave_one_year_out_gate_pass": loo_pass,
        "rolling_windows": rolling,
        "rolling_evaluable_count": len(evaluable),
        "rolling_positive_fraction": rounded(positive_fraction, 12),
        "rolling_gate_pass": rolling_gate,
        "all_stability_gates_pass": annual_gate and loo_pass and rolling_gate,
    }


def _evaluate_test(rows: Sequence[Mapping[str, Any]], test: Mapping[str, Any], implementation: str) -> dict[str, Any]:
    stage = int(test["stage"])
    condition, complement, constituent_coverage = _condition_masks(rows, test)
    states = np.asarray([row["outcome_state"] for row in rows], dtype=object)
    binary = np.isin(states, ("UP", "DOWN"))
    known_outcome = np.isin(states, ("UP", "DOWN", "FLAT"))
    feature_known = condition | complement
    joint_coverage = float((feature_known & known_outcome).mean())
    cond_binary = condition & binary
    comp_binary = complement & binary
    weeks = np.asarray([str(row["selected_month_week_id"]) for row in rows], dtype=object)
    years = np.asarray([int(row["calendar_year"]) for row in rows], dtype=np.int64)
    cond_weeks = len(set(weeks[cond_binary]))
    comp_weeks = len(set(weeks[comp_binary]))
    year_floor = 5 if stage == 1 else 4
    years_with_floor = sum(int((cond_binary & (years == year)).sum()) >= year_floor for year in (2021, 2022, 2023, 2024))
    thresholds = (
        {
            "condition_rows": 40,
            "complement_rows": 80,
            "condition_weeks": 12,
            "complement_weeks": 20,
            "years": 3,
        }
        if stage == 1
        else {
            "condition_rows": 30,
            "complement_rows": 100,
            "condition_weeks": 10,
            "complement_weeks": 24,
            "years": 3,
        }
    )
    support_checks = {
        "joint_known_coverage_gte_0_70": joint_coverage >= 0.70,
        "each_constituent_known_coverage_gte_0_70": all(value >= 0.70 for value in constituent_coverage.values()),
        "condition_binary_rows": int(cond_binary.sum()) >= thresholds["condition_rows"],
        "complement_binary_rows": int(comp_binary.sum()) >= thresholds["complement_rows"],
        "condition_distinct_weeks": cond_weeks >= thresholds["condition_weeks"],
        "complement_distinct_weeks": comp_weeks >= thresholds["complement_weeks"],
        "calendar_years_with_condition_floor": years_with_floor >= thresholds["years"],
    }
    support_pass = all(support_checks.values())
    favorable = str(test["favorable_direction"])
    descriptive = {
        "condition": {state: int((condition & (states == state)).sum()) for state in ("UP", "DOWN", "FLAT", "UNKNOWN")},
        "complement": {state: int((complement & (states == state)).sum()) for state in ("UP", "DOWN", "FLAT", "UNKNOWN")},
    }
    result: dict[str, Any] = {
        "test_id": str(test["test_id"]),
        "session": str(test["session"]),
        "stage": stage,
        "hypothesis_ids": list(test["hypothesis_ids"]),
        "conditions": list(test["conditions"]),
        "favorable_direction": favorable,
        "known_coverage_fraction": rounded(joint_coverage, 12),
        "constituent_known_coverage": {key: rounded(value, 12) for key, value in sorted(constituent_coverage.items())},
        "condition_binary_rows": int(cond_binary.sum()),
        "complement_binary_rows": int(comp_binary.sum()),
        "condition_distinct_weeks": cond_weeks,
        "complement_distinct_weeks": comp_weeks,
        "calendar_years_with_condition_floor": years_with_floor,
        "descriptive_outcomes": descriptive,
        "support_checks": support_checks,
        "support_pass": support_pass,
        "effect_pp": None,
        "bootstrap_finite_replicates": None,
        "bootstrap_95pct_ci_pp": [None, None],
        "permutation_extreme_count": None,
        "permutation_nonfinite_count": None,
        "p_value": None,
        "bh_q_value": None,
        "median_condition_signed_displacement": None,
        "stability": None,
        "advancement_checks": None,
        "verdict": "SUPPORT_FAIL" if not support_pass else "PENDING_MULTIPLICITY",
    }
    if not support_pass:
        return result

    effect = _effect(rows, condition, complement, favorable)
    if effect is None:
        raise ValueError(f"Support-passing test has no effect: {test['test_id']}")
    boot = _bootstrap_effects(
        rows,
        condition,
        complement,
        favorable,
        int(test["bootstrap_seed_uint64"]),
        implementation,
    )
    finite = boot[np.isfinite(boot)]
    if len(finite) >= 19_000:
        lower, upper = np.quantile(finite, (0.025, 0.975), method="linear")
    else:
        lower, upper = math.nan, math.nan
    extreme, nonfinite = _permutation_extremes(
        rows,
        condition,
        complement,
        favorable,
        effect,
        int(test["permutation_seed_uint64"]),
        implementation,
    )
    displacement = np.asarray(
        [
            float(row["outcome_signed_displacement"])
            for index, row in enumerate(rows)
            if condition[index] and row["outcome_signed_displacement"] is not None
        ],
        dtype=np.float64,
    )
    median = float(np.median(displacement)) if len(displacement) else math.nan
    result.update(
        {
            "effect_pp": rounded(effect),
            "bootstrap_finite_replicates": int(len(finite)),
            "bootstrap_95pct_ci_pp": [rounded(float(lower)), rounded(float(upper))],
            "permutation_extreme_count": extreme,
            "permutation_nonfinite_count": nonfinite,
            "p_value": rounded((1 + extreme) / 100_001, 12),
            "median_condition_signed_displacement": rounded(median),
            "stability": _stability(rows, condition, complement, favorable, stage),
        }
    )
    return result


def _finalize_verdicts(results: list[dict[str, Any]], stage: int) -> None:
    for session in SESSIONS:
        _bh_adjust([item for item in results if item["session"] == session])
    minimum_effect = 10.0 if stage == 1 else 15.0
    for result in results:
        if not result["support_pass"]:
            continue
        lower = result["bootstrap_95pct_ci_pp"][0]
        median = result["median_condition_signed_displacement"]
        direction = result["favorable_direction"]
        checks = {
            "minimum_effect": result["effect_pp"] is not None and float(result["effect_pp"]) >= minimum_effect,
            "bootstrap_finite_replicates_gte_19000": int(result["bootstrap_finite_replicates"]) >= 19_000,
            "bootstrap_lower_bound_gt_zero": lower is not None and float(lower) > 0,
            "bh_q_lte_0_05": result["bh_q_value"] is not None and float(result["bh_q_value"]) <= 0.05,
            "median_signed_displacement_matches": (
                median is not None
                and ((direction == "UP" and float(median) > 0) or (direction == "DOWN" and float(median) < 0))
            ),
            "stability": bool(result["stability"]["all_stability_gates_pass"]),
        }
        result["advancement_checks"] = checks
        result["verdict"] = (
            "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" if all(checks.values()) else "REJECT"
        )


def evaluate_stage(implementation: str, stage: int, output: Path) -> None:
    verify_control()
    verify_implementation_seal()
    opening = load_json(output / "outcome_opening.json")
    if opening.get("status") != "PASS_SINGLE_DEVELOPMENT_OUTCOME_OPEN_AND_JOIN":
        raise ValueError("Sealed outcome opening PASS missing")
    if stage == 2:
        stage1 = load_json(output / "stage1_seal.json")
        if stage1.get("status") != "PASS_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED":
            raise ValueError("Stage 1 must be sealed before Stage 2")
        _verify_stage_files(output, stage1, 1)
    _, registry, _ = verify_control()
    path = output / f"{implementation}_joined_development.parquet"
    expected_path = opening["files"][f"{implementation}_joined"]
    if sha256_file(path) != expected_path["sha256"]:
        raise ValueError(f"Joined payload changed: {implementation}")
    rows = pq.read_table(path).to_pylist()
    tests = [item for item in registry["tests"] if int(item["stage"]) == stage]
    results: list[dict[str, Any]] = []
    for session in SESSIONS:
        session_rows = [row for row in rows if row["session_code"] == session]
        if len(session_rows) != 188:
            raise ValueError(f"{session} row count changed")
        for test in [item for item in tests if item["session"] == session]:
            results.append(_evaluate_test(session_rows, test, implementation))
    results.sort(key=lambda item: (item["session"], item["test_id"]))
    _finalize_verdicts(results, stage)
    summary = {
        session: {
            "registered": sum(item["session"] == session for item in results),
            "support_fail": sum(item["session"] == session and item["verdict"] == "SUPPORT_FAIL" for item in results),
            "rejected": sum(item["session"] == session and item["verdict"] == "REJECT" for item in results),
            "provisional_pass": sum(
                item["session"] == session
                and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"
                for item in results
            ),
        }
        for session in SESSIONS
    }
    payload = {
        "stage": stage,
        "test_results": results,
        "summary": summary,
        "development_rows": 376,
        "outcome_joined_payload_hash": opening["joined_payload_hash"],
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "test_registry_sha256": EXPECTED_TEST_REGISTRY_SHA256,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    record = {
        "version": f"GC_MICROSTRUCTURE_STEP_5D_STAGE_{stage}_RUN_V0_1",
        "implementation": implementation,
        "completed_at_utc": utc_now(),
        "payload": payload,
        "payload_hash": canonical_hash(payload),
    }
    write_json_exclusive(output / f"{implementation}_stage{stage}_results.json", record)
    print(json.dumps({"implementation": implementation, "stage": stage, "payload_hash": record["payload_hash"], "summary": summary}, indent=2, sort_keys=True))


def _verify_stage_files(output: Path, seal: Mapping[str, Any], stage: int) -> None:
    for implementation in ("primary", "reference"):
        path = output / f"{implementation}_stage{stage}_results.json"
        expected = seal["files"][implementation]["sha256"]
        if sha256_file(path) != expected:
            raise ValueError(f"Stage {stage} {implementation} result changed")
        record = load_json(path)
        if record.get("payload_hash") != seal["payload_hash"]:
            raise ValueError(f"Stage {stage} {implementation} payload hash changed")


def seal_stage1(output: Path) -> None:
    verify_control()
    verify_implementation_seal()
    records = {
        implementation: load_json(output / f"{implementation}_stage1_results.json")
        for implementation in ("primary", "reference")
    }
    hashes = {implementation: record["payload_hash"] for implementation, record in records.items()}
    exact = len(set(hashes.values())) == 1
    if not exact:
        raise ValueError(f"Stage 1 independent reproduction failed: {hashes}")
    seal: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_STAGE_1_SEAL_V0_1",
        "status": "PASS_STAGE_1_INDEPENDENT_REPRODUCTION_SEALED",
        "sealed_at_utc": utc_now(),
        "payload_hash": records["primary"]["payload_hash"],
        "independent_reproduction_exact": True,
        "stage_1_completed_before_stage_2": True,
        "summary": records["primary"]["payload"]["summary"],
        "files": {
            implementation: {
                "path": str(output / f"{implementation}_stage1_results.json"),
                "sha256": sha256_file(output / f"{implementation}_stage1_results.json"),
            }
            for implementation in ("primary", "reference")
        },
        "year_2025_or_2026_values_accessed": False,
    }
    seal["seal_receipt"] = canonical_hash(seal)
    write_json_exclusive(output / "stage1_seal.json", seal)
    print(json.dumps(seal, indent=2, sort_keys=True))


def _ranking_key(item: Mapping[str, Any]) -> tuple[Any, ...]:
    return (
        float(item["bh_q_value"]),
        -float(item["bootstrap_95pct_ci_pp"][0]),
        -float(item["effect_pp"]),
        -int(item["condition_distinct_weeks"]),
        str(item["test_id"]),
    )


def seal_final(output: Path) -> None:
    verify_control()
    implementation = verify_implementation_seal()
    opening = load_json(output / "outcome_opening.json")
    stage1 = load_json(output / "stage1_seal.json")
    _verify_stage_files(output, stage1, 1)
    stage2_records = {
        impl: load_json(output / f"{impl}_stage2_results.json")
        for impl in ("primary", "reference")
    }
    if stage2_records["primary"]["payload_hash"] != stage2_records["reference"]["payload_hash"]:
        raise ValueError("Stage 2 independent reproduction failed")
    all_results = [
        *load_json(output / "primary_stage1_results.json")["payload"]["test_results"],
        *stage2_records["primary"]["payload"]["test_results"],
    ]
    shortlist: dict[str, list[dict[str, Any]]] = {}
    pass_counts: dict[str, int] = {}
    for session in SESSIONS:
        passing = [
            item
            for item in all_results
            if item["session"] == session
            and item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED"
        ]
        passing.sort(key=_ranking_key)
        pass_counts[session] = len(passing)
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

    final_status = (
        "PASS_STEP_5D_DISCOVERY_WITH_PROVISIONAL_CANDIDATES"
        if any(shortlist[session] for session in SESSIONS)
        else "PASS_STEP_5D_DISCOVERY_ZERO_CANDIDATES"
    )
    summary = {
        "registered_tests": len(all_results),
        "support_fail": sum(item["verdict"] == "SUPPORT_FAIL" for item in all_results),
        "rejected": sum(item["verdict"] == "REJECT" for item in all_results),
        "development_pass_before_cap": sum(
            item["verdict"] == "PROVISIONAL_DEVELOPMENT_CANDIDATE_NOT_VALIDATED" for item in all_results
        ),
        "shortlisted_provisional_candidates": sum(len(value) for value in shortlist.values()),
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
            for session in SESSIONS
            for stage in (1, 2)
        },
    }
    complete_payload = {
        "status": final_status,
        "summary": summary,
        "shortlist": shortlist,
        "all_test_results_hash": canonical_hash(all_results),
        "stage1_payload_hash": stage1["payload_hash"],
        "stage2_payload_hash": stage2_records["primary"]["payload_hash"],
        "outcome_joined_payload_hash": opening["joined_payload_hash"],
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "test_registry_sha256": EXPECTED_TEST_REGISTRY_SHA256,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    results_path = output / "complete_results.json"
    write_json_exclusive(results_path, {"version": "GC_MICROSTRUCTURE_STEP_5D_COMPLETE_RESULTS_V0_1", "results": all_results, "payload": complete_payload})

    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_VERDICT_V0_1",
        "status": final_status,
        "formal_step_pass": True,
        "completed_at_utc": utc_now(),
        "summary": summary,
        "shortlist": shortlist,
        "research_interpretation": (
            "Development evidence produced provisional unvalidated candidates; no trading edge or out-of-sample validity is claimed."
            if any(shortlist[session] for session in SESSIONS)
            else "No registered condition passed every frozen development gate; no edge candidate advances."
        ),
        "development_only": True,
        "out_of_sample_validation_credit": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }
    verdict["verdict_hash"] = canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    write_json_exclusive(verdict_path, verdict)

    stage2_files = {
        impl: {
            "path": str(output / f"{impl}_stage2_results.json"),
            "sha256": sha256_file(output / f"{impl}_stage2_results.json"),
        }
        for impl in ("primary", "reference")
    }
    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_5D_MANIFEST_V0_1",
        "status": final_status,
        "sealed_at_utc": utc_now(),
        "predecessors": {
            "freeze_receipt": EXPECTED_FREEZE_RECEIPT,
            "step5c_manifest_hash": "37ba904c257499a5247696fbae24461c994b765dfbc44b3bbeaa59cb9d58fb75",
            "outcome_opening_receipt": opening["opening_receipt"],
            "stage1_seal_receipt": stage1["seal_receipt"],
            "implementation_receipt": implementation["implementation_receipt"],
        },
        "independent_reproduction": {
            "outcome_extraction_and_join": True,
            "stage_1": True,
            "stage_2": True,
            "primary_stage2_payload_hash": stage2_records["primary"]["payload_hash"],
            "reference_stage2_payload_hash": stage2_records["reference"]["payload_hash"],
        },
        "artifacts": {
            "preflight": {"path": str(output / "preflight.json"), "sha256": sha256_file(output / "preflight.json")},
            "outcome_opening": {"path": str(output / "outcome_opening.json"), "sha256": sha256_file(output / "outcome_opening.json")},
            "outcome_projection": opening["files"]["outcome_projection"],
            "primary_joined": opening["files"]["primary_joined"],
            "reference_joined": opening["files"]["reference_joined"],
            "primary_stage1": stage1["files"]["primary"],
            "reference_stage1": stage1["files"]["reference"],
            "stage1_seal": {"path": str(output / "stage1_seal.json"), "sha256": sha256_file(output / "stage1_seal.json")},
            "primary_stage2": stage2_files["primary"],
            "reference_stage2": stage2_files["reference"],
            "complete_results": {"path": str(results_path), "sha256": sha256_file(results_path)},
            "verdict": {"path": str(verdict_path), "sha256": sha256_file(verdict_path)},
        },
        "summary": summary,
        "shortlist": shortlist,
        "outcome_source_open_count": 1,
        "development_rows": 376,
        "year_2025_or_2026_values_accessed": False,
        "candidate_repair_retune_inversion_or_filter": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    manifest["manifest_hash"] = canonical_hash(manifest)
    manifest_path = output / "manifest.json"
    write_json_exclusive(manifest_path, manifest)

    report_lines = [
        "# GC Microstructure Step 5D — Development Conditional-Edge Discovery",
        "",
        "## Formal verdict",
        "",
        f"`{final_status}`",
        "",
        "## Complete registered search",
        "",
        f"- Registered tests: `{summary['registered_tests']}`.",
        f"- Support failures: `{summary['support_fail']}`.",
        f"- Support-eligible rejections: `{summary['rejected']}`.",
        f"- Tests passing every development gate before the two-per-session cap: `{summary['development_pass_before_cap']}`.",
        f"- Shortlisted provisional candidates: `{summary['shortlisted_provisional_candidates']}`.",
        "",
        "## Provisional shortlist",
        "",
    ]
    for session in SESSIONS:
        report_lines.append(f"### {session.replace('_', ' ').title()}")
        report_lines.append("")
        if not shortlist[session]:
            report_lines.append("No candidate passed every frozen gate.")
        else:
            for item in shortlist[session]:
                report_lines.append(
                    f"- Rank {item['rank']}: `{item['test_id']}` — effect `{item['effect_pp']}` pp, "
                    f"95% cluster CI `{item['bootstrap_95pct_ci_pp']}`, BH q `{item['bh_q_value']}`, "
                    f"support `{item['condition_binary_rows']}` rows across `{item['condition_distinct_weeks']}` weeks."
                )
        report_lines.append("")
    report_lines.extend(
        [
            "## Scope boundary",
            "",
            "These are development-only conditional direction-frequency results. A shortlisted result is provisional and unvalidated; it is not a trade, execution rule, or demonstrated account-level edge.",
            "",
            "Calendar 2025 and every 2026 value remained locked. No execution, trade, PnL, R multiple, or account return was calculated. No data was acquired and no charge was incurred.",
            "",
            "Step 5D is complete. Work stops here.",
            "",
        ]
    )
    report_path = output / "GC_MICROSTRUCTURE_STEP_5D_REPORT.md"
    write_text_exclusive(report_path, "\n".join(report_lines))
    print(json.dumps({"status": final_status, "manifest_hash": manifest["manifest_hash"], "verdict_hash": verdict["verdict_hash"], "summary": summary, "shortlist": shortlist}, indent=2, sort_keys=True))


def verify_final(output: Path) -> None:
    verify_control()
    verify_implementation_seal()
    manifest = load_json(output / "manifest.json")
    verdict = load_json(output / "verdict.json")
    copy_manifest = dict(manifest)
    embedded_manifest_hash = copy_manifest.pop("manifest_hash", None)
    if embedded_manifest_hash != canonical_hash(copy_manifest):
        raise ValueError("Final manifest hash failed")
    copy_verdict = dict(verdict)
    embedded_verdict_hash = copy_verdict.pop("verdict_hash", None)
    if embedded_verdict_hash != canonical_hash(copy_verdict):
        raise ValueError("Final verdict hash failed")
    for record in manifest["artifacts"].values():
        path = Path(record["path"])
        if sha256_file(path) != record["sha256"]:
            raise ValueError(f"Final artifact hash failed: {path}")
    opening = load_json(output / "outcome_opening.json")
    if opening.get("source_stream_open_count") != 1:
        raise ValueError("Outcome source opening count changed")
    if manifest.get("year_2025_or_2026_values_accessed"):
        raise ValueError("Holdout lock violation")
    if manifest.get("execution_trade_pnl_r_or_return_calculated"):
        raise ValueError("Execution-scope violation")
    print(
        json.dumps(
            {
                "status": manifest["status"],
                "manifest_hash": embedded_manifest_hash,
                "verdict_hash": embedded_verdict_hash,
                "all_artifact_hashes_verified": True,
                "independent_reproduction": manifest["independent_reproduction"],
                "year_2025_or_2026_values_accessed": False,
                "execution_trade_pnl_r_or_return_calculated": False,
            },
            indent=2,
            sort_keys=True,
        )
    )


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument(
        "action",
        choices=(
            "seal-implementation",
            "preflight",
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
    value.add_argument("--step5c", type=Path, default=DEFAULT_STEP5C)
    value.add_argument("--cases", type=Path, default=DEFAULT_CASES)
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return value


def main() -> None:
    args = parser().parse_args()
    if args.action == "seal-implementation":
        seal_implementation()
    elif args.action == "preflight":
        preflight(args.step5c, args.cases, args.output)
    elif args.action == "open-outcomes":
        open_outcomes_once(args.step5c, args.cases, args.output)
    elif args.action in {"primary-stage1", "reference-stage1", "primary-stage2", "reference-stage2"}:
        implementation, stage_token = args.action.split("-stage")
        evaluate_stage(implementation, int(stage_token), args.output)
    elif args.action == "seal-stage1":
        seal_stage1(args.output)
    elif args.action == "seal-final":
        seal_final(args.output)
    else:
        verify_final(args.output)


if __name__ == "__main__":
    main()
