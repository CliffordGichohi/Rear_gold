#!/usr/bin/env python3
"""Run the frozen GC Session Trigger Edge Milestone 2-R1 diagnostic.

Only technical metadata and automated crossed/uncrossed classifications are
emitted.  Raw market, book, feature, outcome, and performance values are never
written or printed.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import os
import re
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime, time, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence
from zoneinfo import ZoneInfo

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2r1_protocol_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2r1_freeze_v01.json"
M2_PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2_protocol_v01.json"
M2_REGISTRY_PATH = MANIFESTS / "gc_session_trigger_edge_m2_row_registry_v01.json"
M2_FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2_freeze_v01.json"

DEFAULT_REMOTE_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_M2_DIR = DEFAULT_REMOTE_ROOT / "artifacts/gc_session_trigger_edge_m2_v01"
DEFAULT_ACQUISITION = DEFAULT_REMOTE_ROOT / "data/databento_gc_microstructure_budget_c_v01/acquisition_manifest.json"
DEFAULT_XAU = DEFAULT_REMOTE_ROOT / "data/gold_casebook_v01/price_bars.jsonl.gz"
DEFAULT_OUTPUT = DEFAULT_REMOTE_ROOT / "artifacts/gc_session_trigger_edge_m2r1_v01"

EXPECTED = {
    "m2_final_seal": "c6b86602eceb927db71f56e35bce3bd8778f350f7853429cebbbf281d94c7e85",
    "m2_manifest": "adffdc302f103c8eac307d30193ee06f83e5dafd2fa0e597c9601dbf78a67760",
    "m2_verdict": "03b1bbae4f56caa9b1586ec381805040d24f8e0764da40ad3a3ceaeb8dc85267",
    "m2_technical_diagnostics": "d08bf542afd77e09c44830d0a198300513dfeeb74cb94d8b0605e03fd04c223a",
    "m2_protocol": "d4490ac0311e0a6a6b40595b6c97ee7e8eba357db14f11ccdbbb0c5b32c8d509",
    "m2_registry": "a7a36ae82d92ce91a25e36fcb7f1c95807de67c996d01198648246daa345dc5d",
    "m2_freeze": "0705d12b25fb79ef5a74ea2ce1842d60265cf45deca177be9f904c0db47c0037",
    "acquisition": "b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc",
    "xau": "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
}

EXPECTED_M2_STATUS = "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE"
EXPECTED_AVAILABLE_SESSIONS = 374
EXPECTED_XAU_GAPS = 3
EXPECTED_CROSSED_CLOSES = 15
EXPECTED_ALLOWED_XAU_GAPS = 57
EXPECTED_FEATURE_ROWS_PER_SESSION = 18_900
XAU_MINUTES = 300
BUCKET_WIDTH_NS = 1_000_000_000
UNDEFINED_PRICE = 9_223_372_036_854_775_807
F_MAYBE_BAD_BOOK = 4
F_BAD_TS_RECV = 8
F_SNAPSHOT = 32
F_LAST = 128

CLASSES = {
    "DOCUMENTED_VALID_SEMANTICS",
    "RECOVERABLE_EXISTING_SOURCE",
    "RECOVERABLE_TARGETED_REFRESH",
    "GENUINE_SOURCE_OR_STATE_FAILURE",
    "UNRESOLVED",
}

FEATURE_METADATA_COLUMNS = (
    "bucket_index",
    "bucket_start_ns",
    "bucket_end_ns",
    "market_segment",
    "market_state",
    "state_source_row_ordinal",
    "state_ts_recv_ns",
    "state_available",
    "book_two_sided",
    "book_locked",
    "book_crossed",
)
SOURCE_METADATA_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "sequence",
    "action",
    "side",
    "flags",
)
MBP_LEVEL0_COLUMNS = (
    "bid_px_00",
    "bid_sz_00",
    "bid_ct_00",
    "ask_px_00",
    "ask_sz_00",
    "ask_ct_00",
)
MBP_DIAGNOSTIC_COLUMNS = (*SOURCE_METADATA_COLUMNS, *MBP_LEVEL0_COLUMNS)

XAU_STRING_FIELDS = {
    "record_type",
    "record_id",
    "record_hash",
    "provider_code",
    "instrument_code",
    "timeframe",
    "open_time",
    "close_time",
    "available_at",
    "ingested_at",
    "epistemic_status",
}
XAU_SCALAR_FIELDS = XAU_STRING_FIELDS | {"complete"}
HEX64 = re.compile(r"^[0-9a-fA-F]{64}$")


@dataclass(frozen=True, slots=True)
class Paths:
    m2: Path
    acquisition: Path
    xau: Path
    output: Path


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _canonical_hash(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


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
            if not value.endswith("\n"):
                handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def _file(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def _parse(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def _iso_ns(value: int) -> str:
    seconds, remainder = divmod(int(value), 1_000_000_000)
    stamp = datetime.fromtimestamp(seconds, UTC)
    if remainder:
        return stamp.strftime("%Y-%m-%dT%H:%M:%S") + f".{remainder:09d}Z"
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def _ns(value: datetime) -> int:
    return int(value.timestamp() * 1_000_000_000)


def _receipt_ok(value: Mapping[str, Any], field: str) -> bool:
    return value.get(field) == _canonical_hash({**value, field: None})


def _mapping(value: Any) -> Mapping[str, Any]:
    return value if isinstance(value, Mapping) else {}


def _sequence(value: Any) -> Sequence[Any]:
    return value if isinstance(value, Sequence) and not isinstance(value, (str, bytes, bytearray)) else ()


def _verified_control(paths: Paths, *, verify_registered_artifacts: bool) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    local_required = {
        "protocol": PROTOCOL_PATH,
        "freeze": FREEZE_PATH,
        "m2_protocol": M2_PROTOCOL_PATH,
        "m2_registry": M2_REGISTRY_PATH,
        "m2_freeze": M2_FREEZE_PATH,
        "implementation": Path(__file__),
    }
    for path in local_required.values():
        if not path.is_file():
            raise FileNotFoundError(path)
    protocol = _read(PROTOCOL_PATH)
    freeze = _read(FREEZE_PATH)
    registry = _read(M2_REGISTRY_PATH)
    if protocol.get("status") != "FROZEN_BEFORE_ROW_LEVEL_METADATA_ACCESS":
        raise ValueError("R1 protocol is not frozen")
    if freeze.get("status") != "SEALED_BEFORE_ROW_LEVEL_METADATA_ACCESS":
        raise ValueError("R1 freeze is not sealed")
    if not _receipt_ok(protocol, "protocol_receipt") or not _receipt_ok(freeze, "freeze_receipt"):
        raise ValueError("R1 protocol/freeze receipt failed")
    if _sha256(PROTOCOL_PATH) != str(_mapping(freeze.get("protocol")).get("sha256")):
        raise ValueError("R1 protocol binding failed")
    if _sha256(Path(__file__)) != str(_mapping(freeze.get("implementation")).get("sha256")):
        raise ValueError("R1 implementation binding failed")
    for key, expected in (
        ("m2_protocol", EXPECTED["m2_protocol"]),
        ("m2_registry", EXPECTED["m2_registry"]),
        ("m2_freeze", EXPECTED["m2_freeze"]),
    ):
        if _sha256(local_required[key]) != expected:
            raise ValueError(f"Local predecessor changed: {key}")
    m2_final_path = paths.m2 / "final_seal.json"
    m2_manifest_path = paths.m2 / "manifest.json"
    m2_verdict_path = paths.m2 / "verdict.json"
    m2_diag_path = paths.m2 / "technical_diagnostics.json"
    for name, path in (
        ("m2_final_seal", m2_final_path),
        ("m2_manifest", m2_manifest_path),
        ("m2_verdict", m2_verdict_path),
        ("m2_technical_diagnostics", m2_diag_path),
    ):
        if not path.is_file() or _sha256(path) != EXPECTED[name]:
            raise ValueError(f"Remote Milestone 2 binding failed: {name}")
    final = _read(m2_final_path)
    manifest = _read(m2_manifest_path)
    verdict = _read(m2_verdict_path)
    diagnostics = _read(m2_diag_path)
    if final.get("status") != EXPECTED_M2_STATUS or verdict.get("status") != EXPECTED_M2_STATUS:
        raise ValueError("Milestone 2 failure changed")
    if final.get("manifest_sha256") != _sha256(m2_manifest_path) or final.get("verdict_sha256") != _sha256(m2_verdict_path):
        raise ValueError("Milestone 2 final binding failed")
    if not _receipt_ok(final, "final_seal_receipt") or not _receipt_ok(manifest, "manifest_receipt") or not _receipt_ok(verdict, "verdict_receipt"):
        raise ValueError("Milestone 2 receipt failed")
    primary = _mapping(diagnostics.get("primary_technical"))
    reference = _mapping(diagnostics.get("reference_technical"))
    if primary != reference or int(primary.get("continuous_crossed_bucket_closes", -1)) != EXPECTED_CROSSED_CLOSES:
        raise ValueError("Milestone 2 crossed-close population changed")
    if int(_mapping(diagnostics.get("xau")).get("unexpected_missing_timestamps", -1)) != EXPECTED_XAU_GAPS:
        raise ValueError("Milestone 2 XAU gap population changed")
    if len(_sequence(registry.get("rows"))) != 376 or int(_mapping(registry.get("counts")).get("available_session_rows", -1)) != EXPECTED_AVAILABLE_SESSIONS:
        raise ValueError("Milestone 2 row registry changed")
    if any(str(row.get("session_date", "9999")) >= "2025-01-01" for row in _sequence(registry.get("rows"))):
        raise ValueError("Forward-year row entered R1 registry")
    if not paths.acquisition.is_file() or _sha256(paths.acquisition) != EXPECTED["acquisition"]:
        raise ValueError("Acquisition manifest binding failed")
    if not paths.xau.is_file() or paths.xau.stat().st_size != 258_834_096:
        raise ValueError("XAU source size binding failed")
    if verify_registered_artifacts:
        if _sha256(paths.xau) != EXPECTED["xau"]:
            raise ValueError("XAU source hash failed")
        for record in _sequence(manifest.get("artifacts")):
            path = Path(str(record.get("path")))
            if not path.is_file() or path.stat().st_size != int(record.get("bytes", -1)) or _sha256(path) != str(record.get("sha256")):
                raise ValueError(f"Milestone 2 registered artifact changed: {path}")
    return registry, manifest, _read(paths.acquisition)


def _preflight(paths: Paths) -> None:
    if paths.output.exists():
        raise FileExistsError(f"Refusing to overwrite R1 output: {paths.output}")
    registry, manifest, acquisition = _verified_control(paths, verify_registered_artifacts=True)
    request_ids = {str(item.get("request_id")) for item in _sequence(acquisition.get("requests"))}
    expected_request_ids = {
        str(row[key])
        for row in _sequence(registry.get("rows"))
        if int(row.get("expected_bucket_rows", 0)) > 0
        for key in ("mbo_request_id", "mbp10_request_id")
    }
    gates = {
        "m2_failure_and_all_16_registered_artifacts_hash_verified": len(_sequence(manifest.get("artifacts"))) == 16,
        "m2_protocol_registry_freeze_unchanged": True,
        "xau_source_hash_verified": True,
        "acquisition_manifest_hash_verified": True,
        "all_registry_request_ids_present": expected_request_ids <= request_ids,
        "exact_374_available_sessions": sum(int(row.get("expected_bucket_rows", 0)) > 0 for row in _sequence(registry.get("rows"))) == EXPECTED_AVAILABLE_SESSIONS,
        "exact_three_xau_and_fifteen_crossed_predecessor_counts": True,
        "no_forward_year_registry_rows": True,
        "no_row_level_metadata_access_in_preflight": True,
        "no_acquisition_or_charge": True,
    }
    if not all(gates.values()):
        raise ValueError(gates)
    paths.output.mkdir(parents=True, exist_ok=False)
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_PREFLIGHT_V1_0",
        "status": "PASS_M2_R1_PRE_DIAGNOSTIC_READINESS",
        "completed_at_utc": _utc_now(),
        "protocol": _file(PROTOCOL_PATH),
        "freeze": _file(FREEZE_PATH),
        "implementation": _file(Path(__file__)),
        "m2_final_seal": _file(paths.m2 / "final_seal.json"),
        "m2_manifest": _file(paths.m2 / "manifest.json"),
        "acquisition_manifest": _file(paths.acquisition),
        "xau_source": _file(paths.xau),
        "formal_gates": gates,
        "row_level_metadata_accessed": False,
        "market_book_feature_or_outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "preflight_receipt": None,
    }
    record["preflight_receipt"] = _canonical_hash({**record, "preflight_receipt": None})
    _write_json_exclusive(paths.output / "preflight.json", record)
    print(json.dumps({"status": record["status"], "verified_artifacts": 16, "row_level_metadata_accessed": False}, sort_keys=True))


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
    if len(output) != EXPECTED_ALLOWED_XAU_GAPS:
        raise AssertionError("Frozen XAU allowance changed")
    return output


def _expected_xau(rows: Sequence[Mapping[str, Any]]) -> tuple[dict[datetime, list[dict[str, Any]]], dict[str, Mapping[str, Any]]]:
    expected: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    by_id: dict[str, Mapping[str, Any]] = {}
    for row in rows:
        if int(row.get("expected_bucket_rows", 0)) == 0:
            continue
        row_id = str(row["row_id"])
        by_id[row_id] = row
        opened = _parse(str(row["session_open_utc"]))
        for minute in range(XAU_MINUTES):
            stamp = opened + timedelta(minutes=minute)
            expected[stamp].append({"row_id": row_id, "session_date": str(row["session_date"]), "session_code": str(row["session_code"]), "offset_minute": minute})
    if sum(len(values) for values in expected.values()) != EXPECTED_AVAILABLE_SESSIONS * XAU_MINUTES:
        raise ValueError("Expected XAU timestamp cardinality changed")
    return expected, by_id


def _regex_scalar(line: bytes, name: str) -> Any:
    key = re.escape(name.encode("ascii"))
    match = re.search(rb'"' + key + rb'"\s*:\s*("(?:\\.|[^"\\])*"|true|false|null|-?\d+)', line)
    return None if match is None else json.loads(match.group(1).decode("utf-8"))


def _skip_json_string(data: bytes, index: int) -> int:
    if data[index] != 34:
        raise ValueError("Expected JSON string")
    index += 1
    while index < len(data):
        if data[index] == 92:
            index += 2
        elif data[index] == 34:
            return index + 1
        else:
            index += 1
    raise ValueError("Unterminated JSON string")


def _manual_top_level_scalars(line: bytes) -> dict[str, Any]:
    output: dict[str, Any] = {name: None for name in XAU_SCALAR_FIELDS}
    index = 0
    length = len(line)
    while index < length and line[index] in b" \t\r\n":
        index += 1
    if index >= length or line[index] != 123:
        raise ValueError("JSON line is not an object")
    index += 1
    while index < length:
        while index < length and line[index] in b" \t\r\n,":
            index += 1
        if index < length and line[index] == 125:
            break
        key_start = index
        index = _skip_json_string(line, index)
        key = json.loads(line[key_start:index].decode("utf-8"))
        while index < length and line[index] in b" \t\r\n":
            index += 1
        if index >= length or line[index] != 58:
            raise ValueError("JSON key lacks colon")
        index += 1
        while index < length and line[index] in b" \t\r\n":
            index += 1
        value_start = index
        if line[index] == 34:
            index = _skip_json_string(line, index)
            if key in XAU_SCALAR_FIELDS:
                output[key] = json.loads(line[value_start:index].decode("utf-8"))
        elif line[index] in (123, 91):
            opening = line[index]
            closing = 125 if opening == 123 else 93
            depth = 0
            in_string = False
            escaped = False
            while index < length:
                byte = line[index]
                if in_string:
                    if escaped:
                        escaped = False
                    elif byte == 92:
                        escaped = True
                    elif byte == 34:
                        in_string = False
                else:
                    if byte == 34:
                        in_string = True
                    elif byte == opening:
                        depth += 1
                    elif byte == closing:
                        depth -= 1
                        if depth == 0:
                            index += 1
                            break
                index += 1
        else:
            while index < length and line[index] not in b",}":
                index += 1
            if key in XAU_SCALAR_FIELDS:
                output[key] = json.loads(line[value_start:index].decode("utf-8"))
    return output


def _project_regex(line: bytes) -> dict[str, Any]:
    return {name: _regex_scalar(line, name) for name in XAU_SCALAR_FIELDS}


def _xau_record_valid(record: Mapping[str, Any]) -> bool:
    try:
        opened = _parse(str(record["open_time"]))
        closed = _parse(str(record["close_time"]))
        available = _parse(str(record["available_at"]))
    except (KeyError, TypeError, ValueError):
        return False
    return (
        record.get("complete") is True
        and closed - opened == timedelta(minutes=1)
        and available <= closed
        and bool(str(record.get("record_id") or ""))
        and bool(HEX64.fullmatch(str(record.get("record_hash") or "")))
    )


def _xau_identity(record: Mapping[str, Any]) -> str:
    return _canonical_hash({name: record.get(name) for name in sorted(XAU_SCALAR_FIELDS) if name != "ingested_at"})


def _scan_xau(path: Path, expected: Mapping[datetime, Sequence[Mapping[str, Any]]], parser: str) -> dict[str, Any]:
    target_stamps = set(expected)
    qualifying: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    any_at_target: Counter[datetime] = Counter()
    all_qualifying: set[datetime] = set()
    rows = 0
    order_regressions = 0
    prior_open: datetime | None = None
    saw_one_minute = False
    holdout_line_deserialized = False
    projector = _project_regex if parser == "primary" else _manual_top_level_scalars
    with gzip.open(path, "rb") as handle:
        for line in handle:
            open_value = _regex_scalar(line, "open_time") if parser == "primary" else None
            if parser == "reference":
                quick = re.search(rb'"open_time"\s*:\s*"([^"\\]+)"', line)
                open_value = quick.group(1).decode("ascii") if quick else None
            if isinstance(open_value, str) and open_value[:4] in {"2025", "2026"}:
                break
            record = projector(line)
            timeframe = record.get("timeframe")
            if timeframe != "1m":
                if saw_one_minute:
                    break
                continue
            saw_one_minute = True
            opened_text = record.get("open_time")
            if not isinstance(opened_text, str):
                continue
            opened = _parse(opened_text)
            if opened.year >= 2025:
                holdout_line_deserialized = True
                raise ValueError("Forward-year XAU row was deserialized")
            if opened in target_stamps:
                any_at_target[opened] += 1
            if record.get("instrument_code") != "XAUUSD":
                continue
            rows += 1
            if prior_open is not None and opened < prior_open:
                order_regressions += 1
            prior_open = opened
            all_qualifying.add(opened)
            if opened in target_stamps:
                qualifying[opened].append(record)
    return {
        "qualifying": qualifying,
        "any_at_target": any_at_target,
        "all_qualifying": all_qualifying,
        "source_rows": rows,
        "source_order_regressions": order_regressions,
        "first_2025_or_2026_line_deserialized": holdout_line_deserialized,
    }


def _dst_matches(row: Mapping[str, Any]) -> bool:
    local_date = datetime.fromisoformat(str(row["session_date"])).date()
    zone = ZoneInfo(str(row["session_timezone"]))
    recomputed = datetime.combine(local_date, time(8, 0), tzinfo=zone).astimezone(UTC)
    return recomputed == _parse(str(row["session_open_utc"]))


def _classify_xau_primary(evidence: Mapping[str, Any]) -> str:
    if not evidence["dst_match"] or not evidence["source_lineage_bound"]:
        return "UNRESOLVED"
    if evidence["qualifying_count"] > 1 or evidence["source_order_regressions"] or evidence["malformed_exact_count"]:
        return "GENUINE_SOURCE_OR_STATE_FAILURE"
    if evidence["calendar_disposition"] != "EXPECTED_AVAILABLE":
        return "DOCUMENTED_VALID_SEMANTICS"
    if evidence["qualifying_count"] == 1:
        return "RECOVERABLE_EXISTING_SOURCE"
    if evidence["previous_minute_present"] and evidence["next_minute_present"]:
        return "RECOVERABLE_TARGETED_REFRESH"
    return "UNRESOLVED"


def _classify_xau_reference(evidence: Mapping[str, Any]) -> str:
    if evidence["dst_match"] is not True or evidence["source_lineage_bound"] is not True:
        return "UNRESOLVED"
    exact = int(evidence["qualifying_count"])
    if int(evidence["source_order_regressions"]) != 0 or int(evidence["malformed_exact_count"]) != 0 or exact > 1:
        return "GENUINE_SOURCE_OR_STATE_FAILURE"
    if str(evidence["calendar_disposition"]) != "EXPECTED_AVAILABLE":
        return "DOCUMENTED_VALID_SEMANTICS"
    if exact == 1:
        return "RECOVERABLE_EXISTING_SOURCE"
    adjacent = bool(evidence["previous_minute_present"]) and bool(evidence["next_minute_present"])
    return "RECOVERABLE_TARGETED_REFRESH" if adjacent else "UNRESOLVED"


def _xau_findings(rows: Sequence[Mapping[str, Any]], scan: Mapping[str, Any], implementation: str) -> list[dict[str, Any]]:
    expected, by_id = _expected_xau(rows)
    allowed = _allowed_xau_missing()
    qualifying = _mapping(scan.get("qualifying"))
    present = set(scan["all_qualifying"])
    missing: list[tuple[str, str, datetime, str]] = []
    for stamp, owners in expected.items():
        if stamp in qualifying:
            continue
        for owner in owners:
            item = (str(owner["session_date"]), str(owner["session_code"]), stamp)
            if item not in allowed:
                missing.append((*item, str(owner["row_id"])))
    missing.sort(key=lambda item: (item[0], item[1], item[2]))
    if len(missing) != EXPECTED_XAU_GAPS:
        raise ValueError(f"Expected three unexpected XAU gaps, found {len(missing)}")
    output = []
    classifier = _classify_xau_primary if implementation == "primary" else _classify_xau_reference
    for session_date, session_code, stamp, row_id in missing:
        records = list(qualifying.get(stamp, []))
        evidence = {
            "qualifying_count": len(records),
            "any_source_emission_at_timestamp": int(scan["any_at_target"].get(stamp, 0)),
            "malformed_exact_count": sum(not _xau_record_valid(record) for record in records),
            "duplicate_qualifying_count": max(0, len(records) - 1),
            "previous_minute_present": stamp - timedelta(minutes=1) in present,
            "next_minute_present": stamp + timedelta(minutes=1) in present,
            "previous_identity_hashes": sorted(_xau_identity(record) for record in qualifying.get(stamp - timedelta(minutes=1), [])),
            "next_identity_hashes": sorted(_xau_identity(record) for record in qualifying.get(stamp + timedelta(minutes=1), [])),
            "source_order_regressions": int(scan["source_order_regressions"]),
            "source_lineage_bound": True,
            "dst_match": _dst_matches(by_id[row_id]),
            "calendar_disposition": str(by_id[row_id]["availability_disposition"]),
            "weekday": _parse(str(by_id[row_id]["session_open_utc"])).strftime("%A").upper(),
            "holdout_line_deserialized": bool(scan["first_2025_or_2026_line_deserialized"]),
        }
        classification = classifier(evidence)
        output.append({
            "finding_id": _canonical_hash({"domain": "XAU_TIMESTAMP", "row_id": row_id, "expected": stamp.isoformat()}),
            "domain": "XAU_TIMESTAMP",
            "session_date": session_date,
            "session_code": session_code,
            "row_id": row_id,
            "expected_timestamp_utc": stamp.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "evidence": evidence,
            "classification": classification,
        })
    return output


def _feature_identity(row_id: str, values: Mapping[str, Any]) -> str:
    return _canonical_hash({
        "row_id": row_id,
        "bucket_start_ns": int(values["bucket_start_ns"]),
        "bucket_end_ns": int(values["bucket_end_ns"]),
        "state_source_row_ordinal": int(values["state_source_row_ordinal"]),
        "state_ts_recv_ns": int(values["state_ts_recv_ns"]),
    })


def _feature_record(row: Mapping[str, Any], values: Mapping[str, Any]) -> dict[str, Any]:
    if values.get("state_source_row_ordinal") is None or values.get("state_ts_recv_ns") is None:
        raise ValueError("Crossed feature row lacks state identity")
    record = {
        "row_id": str(row["row_id"]),
        "session_date": str(row["session_date"]),
        "session_code": str(row["session_code"]),
        "mbo_request_id": str(row["mbo_request_id"]),
        "mbp10_request_id": str(row["mbp10_request_id"]),
        "window_start_inclusive_ns": int(row["window_start_inclusive_ns"]),
        "window_end_exclusive_ns": int(row["window_end_exclusive_ns"]),
        "bucket_index": int(values["bucket_index"]),
        "bucket_start_ns": int(values["bucket_start_ns"]),
        "bucket_end_ns": int(values["bucket_end_ns"]),
        "market_segment": str(values["market_segment"]),
        "market_state": str(values["market_state"]),
        "state_source_row_ordinal": int(values["state_source_row_ordinal"]),
        "state_ts_recv_ns": int(values["state_ts_recv_ns"]),
        "state_available": bool(values["state_available"]),
        "book_two_sided": bool(values["book_two_sided"]),
        "book_locked": bool(values["book_locked"]),
        "book_crossed": bool(values["book_crossed"]),
    }
    record["feature_identity_hash"] = _feature_identity(str(row["row_id"]), record)
    return record


def _feature_rows_primary(path: Path, session_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    parquet = pq.ParquetFile(path)
    if parquet.num_row_groups != len(session_rows):
        raise ValueError("Feature row-group/session cardinality changed")
    output = []
    for index, row in enumerate(session_rows):
        table = parquet.read_row_group(index, columns=list(FEATURE_METADATA_COLUMNS))
        if table.num_rows != EXPECTED_FEATURE_ROWS_PER_SESSION:
            raise ValueError("Feature row group is not 18,900 rows")
        columns = {name: table[name].to_pylist() for name in FEATURE_METADATA_COLUMNS}
        for offset, crossed in enumerate(columns["book_crossed"]):
            if crossed and columns["market_state"][offset] == "CONTINUOUS_MATCHING":
                output.append(_feature_record(row, {name: columns[name][offset] for name in FEATURE_METADATA_COLUMNS}))
    return sorted(output, key=lambda item: item["feature_identity_hash"])


def _feature_rows_reference(path: Path, session_rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    dataset = ds.dataset(path, format="parquet")
    table = dataset.to_table(
        columns=list(FEATURE_METADATA_COLUMNS),
        filter=(ds.field("book_crossed") == True) & (ds.field("market_state") == "CONTINUOUS_MATCHING"),  # noqa: E712
        use_threads=True,
    )
    rows_by_time = sorted(session_rows, key=lambda row: int(row["window_start_inclusive_ns"]))
    output = []
    for values in table.to_pylist():
        start = int(values["bucket_start_ns"])
        owners = [row for row in rows_by_time if int(row["window_start_inclusive_ns"]) <= start < int(row["window_end_exclusive_ns"])]
        if len(owners) != 1:
            raise ValueError("Reference feature timestamp did not map uniquely within its session file")
        output.append(_feature_record(owners[0], values))
    return sorted(output, key=lambda item: item["feature_identity_hash"])


def _timestamp_scalar(value_ns: int) -> pa.Scalar:
    return pa.scalar(value_ns, type=pa.timestamp("ns", tz="UTC"))


def _read_range_primary(path: Path, columns: Sequence[str], start: int, end: int) -> pa.Table:
    dataset = ds.dataset(path, format="parquet")
    field = ds.field("ts_recv")
    return dataset.to_table(columns=list(columns), filter=(field >= _timestamp_scalar(start)) & (field < _timestamp_scalar(end)), use_threads=True)


def _read_range_reference(path: Path, columns: Sequence[str], start: int, end: int) -> pa.Table:
    parquet = pq.ParquetFile(path)
    ts_index = parquet.schema_arrow.get_field_index("ts_recv")
    tables: list[pa.Table] = []
    for group in range(parquet.num_row_groups):
        column_meta = parquet.metadata.row_group(group).column(ts_index)
        stats = column_meta.statistics
        if stats is not None and stats.has_min_max:
            minimum = int(pa.scalar(stats.min).cast(pa.int64()).as_py())
            maximum = int(pa.scalar(stats.max).cast(pa.int64()).as_py())
            if maximum < start or minimum >= end:
                continue
        table = parquet.read_row_group(group, columns=list(columns))
        receives = table["ts_recv"].combine_chunks().cast(pa.int64())
        mask = pc.and_(pc.greater_equal(receives, pa.scalar(start, pa.int64())), pc.less(receives, pa.scalar(end, pa.int64())))
        selected = table.filter(mask)
        if selected.num_rows:
            tables.append(selected)
    if not tables:
        schema = pa.schema([parquet.schema_arrow.field(name) for name in columns])
        return pa.Table.from_arrays([pa.array([], type=field.type) for field in schema], schema=schema)
    return pa.concat_tables(tables)


def _state_class_from_table(table: pa.Table, index: int) -> str:
    bid_px = int(table["bid_px_00"][index].as_py())
    bid_sz = int(table["bid_sz_00"][index].as_py())
    bid_ct = int(table["bid_ct_00"][index].as_py())
    ask_px = int(table["ask_px_00"][index].as_py())
    ask_sz = int(table["ask_sz_00"][index].as_py())
    ask_ct = int(table["ask_ct_00"][index].as_py())
    two_sided = bid_px != UNDEFINED_PRICE and ask_px != UNDEFINED_PRICE and bid_sz > 0 and ask_sz > 0 and bid_ct > 0 and ask_ct > 0
    if not two_sided:
        return "ONE_SIDED"
    return "CROSSED" if ask_px < bid_px else "TWO_SIDED_UNCROSSED"


def _technical_records(table: pa.Table, *, mbp: bool) -> list[dict[str, Any]]:
    output = []
    for index in range(table.num_rows):
        record = {
            "ordinal": int(table["source_row_ordinal"][index].as_py()),
            "recv": int(table["ts_recv"][index].cast(pa.int64()).as_py()),
            "event": int(table["ts_event"][index].cast(pa.int64()).as_py()),
            "publisher": int(table["publisher_id"][index].as_py()),
            "instrument": int(table["instrument_id"][index].as_py()),
            "sequence": int(table["sequence"][index].as_py()),
            "action": str(table["action"][index].as_py()),
            "side": str(table["side"][index].as_py()),
            "flags": int(table["flags"][index].as_py()),
        }
        if mbp:
            record["state_class"] = _state_class_from_table(table, index)
        output.append(record)
    return output


def _assert_order(records: Sequence[Mapping[str, Any]]) -> None:
    if any((int(current["recv"]), int(current["ordinal"])) <= (int(previous["recv"]), int(previous["ordinal"])) for previous, current in zip(records, records[1:])):
        raise ValueError("Source receive/ordinal order is not strict")


def _source_row_hash(schema: str, request_id: str, row: Mapping[str, Any]) -> str:
    return _canonical_hash({
        "schema": schema,
        "request_id": request_id,
        "source_row_ordinal": int(row["ordinal"]),
        "publisher_id": int(row["publisher"]),
        "instrument_id": int(row["instrument"]),
        "sequence": int(row["sequence"]),
        "ts_event": int(row["event"]),
        "ts_recv": int(row["recv"]),
    })


def _group_hash(schema: str, request_id: str, key: tuple[int, int, int]) -> str:
    return _canonical_hash({"schema": schema, "request_id": request_id, "publisher_id": key[0], "instrument_id": key[1], "sequence": key[2]})


def _group_indices(records: Sequence[Mapping[str, Any]], key: tuple[int, int, int]) -> list[int]:
    return [index for index, row in enumerate(records) if (int(row["publisher"]), int(row["instrument"]), int(row["sequence"])) == key]


def _group_metadata(records: Sequence[Mapping[str, Any]], indices: Sequence[int], request_id: str, schema: str) -> dict[str, Any]:
    if not indices:
        return {"present": False, "row_count": 0, "contiguous": False, "f_last_count": 0, "group_identity_hash": None}
    group = [records[index] for index in indices]
    key = (int(group[0]["publisher"]), int(group[0]["instrument"]), int(group[0]["sequence"]))
    f_last = [position for position, row in enumerate(group) if int(row["flags"]) & F_LAST]
    terminal_valid = len(f_last) == 1 and f_last[0] == len(group) - 1
    return {
        "present": True,
        "row_count": len(group),
        "contiguous": list(indices) == list(range(indices[0], indices[-1] + 1)),
        "f_last_count": len(f_last),
        "terminal_f_last": terminal_valid,
        "snapshot_rows": sum(bool(int(row["flags"]) & F_SNAPSHOT) for row in group),
        "reset_rows": sum(str(row["action"]) == "R" for row in group),
        "action_counts": dict(sorted(Counter(str(row["action"]) for row in group).items())),
        "side_counts": dict(sorted(Counter(str(row["side"]) for row in group).items())),
        "group_identity_hash": _group_hash(schema, request_id, key),
        "terminal_recv_ns": int(group[-1]["recv"]) if terminal_valid else None,
    }


def _classify_cross_primary(evidence: Mapping[str, Any]) -> str:
    if evidence["state_mapping_count"] != 1 or not evidence["mbp_group_contiguous"] or evidence["mbp_group_f_last_count"] != 1 or not evidence["mbp_terminal_f_last"]:
        return "UNRESOLVED"
    if evidence["selected_state_class"] != "CROSSED" or evidence["selected_snapshot"] or evidence["selected_reset"]:
        return "GENUINE_SOURCE_OR_STATE_FAILURE"
    if evidence["selected_f_last"] or evidence["terminal_state_class"] in {"CROSSED", "ONE_SIDED"}:
        return "GENUINE_SOURCE_OR_STATE_FAILURE"
    if not evidence["selected_is_latest_before_bucket_close"]:
        return "RECOVERABLE_EXISTING_SOURCE" if evidence["terminal_before_bucket_close"] and evidence["terminal_state_class"] == "TWO_SIDED_UNCROSSED" else "GENUINE_SOURCE_OR_STATE_FAILURE"
    if evidence["terminal_before_bucket_close"]:
        return "RECOVERABLE_EXISTING_SOURCE"
    if evidence["terminal_at_or_after_bucket_close"] and evidence["terminal_after_selected"] and evidence["terminal_state_class"] == "TWO_SIDED_UNCROSSED":
        return "DOCUMENTED_VALID_SEMANTICS"
    return "UNRESOLVED"


def _classify_cross_reference(evidence: Mapping[str, Any]) -> str:
    mapping_ok = int(evidence["state_mapping_count"]) == 1
    group_ok = bool(evidence["mbp_group_contiguous"]) and int(evidence["mbp_group_f_last_count"]) == 1 and bool(evidence["mbp_terminal_f_last"])
    if not mapping_ok or not group_ok:
        return "UNRESOLVED"
    if str(evidence["selected_state_class"]) != "CROSSED" or bool(evidence["selected_snapshot"]) or bool(evidence["selected_reset"]):
        return "GENUINE_SOURCE_OR_STATE_FAILURE"
    terminal_class = str(evidence["terminal_state_class"])
    if bool(evidence["selected_f_last"]) or terminal_class == "CROSSED" or terminal_class == "ONE_SIDED":
        return "GENUINE_SOURCE_OR_STATE_FAILURE"
    if bool(evidence["selected_is_latest_before_bucket_close"]) is False:
        recoverable = bool(evidence["terminal_before_bucket_close"]) and terminal_class == "TWO_SIDED_UNCROSSED"
        return "RECOVERABLE_EXISTING_SOURCE" if recoverable else "GENUINE_SOURCE_OR_STATE_FAILURE"
    if bool(evidence["terminal_before_bucket_close"]):
        return "RECOVERABLE_EXISTING_SOURCE"
    documented = bool(evidence["terminal_at_or_after_bucket_close"]) and bool(evidence["terminal_after_selected"]) and terminal_class == "TWO_SIDED_UNCROSSED"
    return "DOCUMENTED_VALID_SEMANTICS" if documented else "UNRESOLVED"


def _request_map(acquisition: Mapping[str, Any]) -> dict[str, Mapping[str, Any]]:
    output = {str(item["request_id"]): item for item in _sequence(acquisition.get("requests"))}
    if len(output) != 80:
        raise ValueError("Acquisition request inventory changed")
    return output


def _source_path(request: Mapping[str, Any]) -> Path:
    return Path(str(_mapping(_mapping(request.get("normalization")).get("normalized_payload")).get("path")))


def _verify_affected_request(request: Mapping[str, Any]) -> dict[str, Any]:
    verified = {}
    for name in ("normalized_payload", "data_quality", "lineage", "seal"):
        record = _mapping(_mapping(request.get("normalization")).get(name))
        path = Path(str(record.get("path")))
        valid = path.is_file() and path.stat().st_size == int(record.get("bytes", -1)) and _sha256(path) == str(record.get("sha256"))
        if not valid:
            raise ValueError(f"Affected source binding failed: {path}")
        verified[name] = {"bytes": int(record["bytes"]), "sha256": str(record["sha256"])}
    return verified


def _analyze_crossed_features(
    features: Sequence[Mapping[str, Any]],
    rows_by_id: Mapping[str, Mapping[str, Any]],
    acquisition: Mapping[str, Any],
    implementation: str,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    requests = _request_map(acquisition)
    grouped_features: dict[str, list[Mapping[str, Any]]] = defaultdict(list)
    for feature in features:
        grouped_features[str(feature["row_id"])].append(feature)
    findings: list[dict[str, Any]] = []
    source_bindings: dict[str, Any] = {}
    read_range = _read_range_primary if implementation == "primary" else _read_range_reference
    classifier = _classify_cross_primary if implementation == "primary" else _classify_cross_reference
    for row_id in sorted(grouped_features):
        row = rows_by_id[row_id]
        mbp_request_id = str(row["mbp10_request_id"])
        mbo_request_id = str(row["mbo_request_id"])
        mbp_request = requests[mbp_request_id]
        mbo_request = requests[mbo_request_id]
        for request_id, request in ((mbp_request_id, mbp_request), (mbo_request_id, mbo_request)):
            if request_id not in source_bindings:
                source_bindings[request_id] = _verify_affected_request(request)
        start = int(row["window_start_inclusive_ns"])
        end = int(row["window_end_exclusive_ns"])
        mbp_records = _technical_records(read_range(_source_path(mbp_request), MBP_DIAGNOSTIC_COLUMNS, start, end), mbp=True)
        mbo_records = _technical_records(read_range(_source_path(mbo_request), SOURCE_METADATA_COLUMNS, start, end), mbp=False)
        _assert_order(mbp_records)
        _assert_order(mbo_records)
        ordinal_map: dict[int, list[int]] = defaultdict(list)
        for index, source_row in enumerate(mbp_records):
            ordinal_map[int(source_row["ordinal"])].append(index)
        for feature in sorted(grouped_features[row_id], key=lambda item: int(item["bucket_end_ns"])):
            target_indices = [index for index in ordinal_map.get(int(feature["state_source_row_ordinal"]), []) if int(mbp_records[index]["recv"]) == int(feature["state_ts_recv_ns"])]
            if len(target_indices) == 1:
                target_index = target_indices[0]
                target = mbp_records[target_index]
                key = (int(target["publisher"]), int(target["instrument"]), int(target["sequence"]))
                mbp_indices = _group_indices(mbp_records, key)
                mbo_indices = _group_indices(mbo_records, key)
                mbp_group = [mbp_records[index] for index in mbp_indices]
                selected_position = mbp_indices.index(target_index)
                f_last_positions = [index for index, item in enumerate(mbp_group) if int(item["flags"]) & F_LAST]
                terminal_valid = len(f_last_positions) == 1 and f_last_positions[0] == len(mbp_group) - 1
                terminal = mbp_group[-1] if terminal_valid else None
                latest_before = max((item for item in mbp_records if int(item["recv"]) < int(feature["bucket_end_ns"])), key=lambda item: (int(item["recv"]), int(item["ordinal"])), default=None)
                mbp_meta = _group_metadata(mbp_records, mbp_indices, mbp_request_id, "MBP-10")
                mbo_meta = _group_metadata(mbo_records, mbo_indices, mbo_request_id, "MBO")
                terminal_recv = int(terminal["recv"]) if terminal is not None else None
                evidence = {
                    "state_mapping_count": 1,
                    "state_row_identity_hash": _source_row_hash("MBP-10", mbp_request_id, target),
                    "selected_action": str(target["action"]),
                    "selected_side": str(target["side"]),
                    "selected_sequence": int(target["sequence"]),
                    "selected_flags": int(target["flags"]),
                    "selected_snapshot": bool(int(target["flags"]) & F_SNAPSHOT),
                    "selected_reset": str(target["action"]) == "R",
                    "selected_f_last": bool(int(target["flags"]) & F_LAST),
                    "selected_state_class": str(target["state_class"]),
                    "selected_group_position_one_based": selected_position + 1,
                    "selected_is_latest_before_bucket_close": latest_before is not None and int(latest_before["ordinal"]) == int(target["ordinal"]) and int(latest_before["recv"]) == int(target["recv"]),
                    "mbp_group_identity_hash": mbp_meta["group_identity_hash"],
                    "mbp_group_row_count": mbp_meta["row_count"],
                    "mbp_group_contiguous": mbp_meta["contiguous"],
                    "mbp_group_f_last_count": mbp_meta["f_last_count"],
                    "mbp_terminal_f_last": mbp_meta.get("terminal_f_last", False),
                    "mbp_group_snapshot_rows": mbp_meta.get("snapshot_rows", 0),
                    "mbp_group_reset_rows": mbp_meta.get("reset_rows", 0),
                    "terminal_after_selected": terminal is not None and int(terminal["ordinal"]) != int(target["ordinal"]) and (int(terminal["recv"]), int(terminal["ordinal"])) > (int(target["recv"]), int(target["ordinal"])),
                    "terminal_state_class": str(terminal["state_class"]) if terminal is not None else None,
                    "terminal_before_bucket_close": terminal_recv is not None and terminal_recv < int(feature["bucket_end_ns"]),
                    "terminal_at_or_after_bucket_close": terminal_recv is not None and terminal_recv >= int(feature["bucket_end_ns"]),
                    "unfinished_native_event_at_bucket_close": terminal is not None and not bool(int(target["flags"]) & F_LAST) and terminal_recv is not None and terminal_recv >= int(feature["bucket_end_ns"]),
                    "completion_same_one_second_bucket": terminal_recv is not None and int(target["recv"]) // BUCKET_WIDTH_NS == terminal_recv // BUCKET_WIDTH_NS,
                    "completion_delay_ns": terminal_recv - int(target["recv"]) if terminal_recv is not None else None,
                    "crossing_persists_at_completed_boundary": terminal is not None and str(terminal["state_class"]) == "CROSSED",
                    "state_construction_selected_stale_partial": terminal is not None and terminal_recv is not None and terminal_recv < int(feature["bucket_end_ns"]) and (latest_before is None or int(latest_before["ordinal"]) != int(target["ordinal"]) or int(latest_before["recv"]) != int(target["recv"])),
                    "mbo_corroboration": mbo_meta,
                }
            else:
                evidence = {
                    "state_mapping_count": len(target_indices),
                    "state_row_identity_hash": None,
                    "selected_action": None,
                    "selected_side": None,
                    "selected_sequence": None,
                    "selected_flags": None,
                    "selected_snapshot": False,
                    "selected_reset": False,
                    "selected_f_last": False,
                    "selected_state_class": None,
                    "selected_group_position_one_based": None,
                    "selected_is_latest_before_bucket_close": False,
                    "mbp_group_identity_hash": None,
                    "mbp_group_row_count": 0,
                    "mbp_group_contiguous": False,
                    "mbp_group_f_last_count": 0,
                    "mbp_terminal_f_last": False,
                    "mbp_group_snapshot_rows": 0,
                    "mbp_group_reset_rows": 0,
                    "terminal_after_selected": False,
                    "terminal_state_class": None,
                    "terminal_before_bucket_close": False,
                    "terminal_at_or_after_bucket_close": False,
                    "unfinished_native_event_at_bucket_close": False,
                    "completion_same_one_second_bucket": False,
                    "completion_delay_ns": None,
                    "crossing_persists_at_completed_boundary": False,
                    "state_construction_selected_stale_partial": False,
                    "mbo_corroboration": {"present": False, "row_count": 0, "contiguous": False, "f_last_count": 0, "group_identity_hash": None},
                }
            classification = classifier(evidence)
            findings.append({
                "finding_id": str(feature["feature_identity_hash"]),
                "domain": "CROSSED_BUCKET_CLOSE",
                "session_date": str(feature["session_date"]),
                "session_code": str(feature["session_code"]),
                "row_id": row_id,
                "bucket_start_utc": _iso_ns(int(feature["bucket_start_ns"])),
                "bucket_end_utc": _iso_ns(int(feature["bucket_end_ns"])),
                "market_segment": str(feature["market_segment"]),
                "market_state": str(feature["market_state"]),
                "evidence": evidence,
                "classification": classification,
            })
    return sorted(findings, key=lambda item: item["finding_id"]), dict(sorted(source_bindings.items()))


def _recommendation(findings: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    classes = {str(item["classification"]) for item in findings}
    if classes & {"GENUINE_SOURCE_OR_STATE_FAILURE", "UNRESOLVED"}:
        return {"recommendation_id": "NONE", "bounded_correction_count": 0, "reason": "At least one genuine or unresolved integrity finding blocks a bounded recertification correction."}
    xau_ok = all(item["classification"] in {"DOCUMENTED_VALID_SEMANTICS", "RECOVERABLE_EXISTING_SOURCE", "RECOVERABLE_TARGETED_REFRESH"} for item in findings if item["domain"] == "XAU_TIMESTAMP")
    cross_ok = all(item["classification"] in {"DOCUMENTED_VALID_SEMANTICS", "RECOVERABLE_EXISTING_SOURCE"} for item in findings if item["domain"] == "CROSSED_BUCKET_CLOSE")
    if xau_ok and cross_ok:
        return {
            "recommendation_id": "TARGETED_XAU_REFRESH_AND_COMPLETED_MBP_STATE_RECERTIFICATION_V0_1",
            "bounded_correction_count": 1,
            "text": "In one future separately authorized amendment only: recover exactly the classified deficient XAU timestamps by the diagnosed source path, and construct authoritative MBP bucket-close state only from a valid snapshot baseline or unique terminal F_LAST native-event boundary. Preserve every other Milestone 2 definition and rerun full independent certification.",
        }
    return {"recommendation_id": "NONE", "bounded_correction_count": 0, "reason": "The frozen conditional recommendation rule was not satisfied."}


def _normalize_result(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output.pop("implementation", None)
    output.pop("completed_at_utc", None)
    output.pop("result_receipt", None)
    return output


def _run_diagnostic(paths: Paths) -> None:
    preflight_path = paths.output / "preflight.json"
    if not preflight_path.is_file() or _read(preflight_path).get("status") != "PASS_M2_R1_PRE_DIAGNOSTIC_READINESS":
        raise ValueError("Matching R1 preflight required")
    registry, _manifest, acquisition = _verified_control(paths, verify_registered_artifacts=False)
    rows = [dict(row) for row in _sequence(registry.get("rows")) if int(row.get("expected_bucket_rows", 0)) > 0]
    rows_by_id = {str(row["row_id"]): row for row in rows}
    expected, _ = _expected_xau(rows)
    outputs: dict[str, dict[str, Any]] = {}
    for implementation in ("primary", "reference"):
        xau_scan = _scan_xau(paths.xau, expected, implementation)
        xau_findings = _xau_findings(rows, xau_scan, implementation)
        crossed_features: list[dict[str, Any]] = []
        for session, filename in (("LONDON", f"{implementation}_london_one_second_features.parquet"), ("NEW_YORK", f"{implementation}_new_york_one_second_features.parquet")):
            session_rows = sorted((row for row in rows if row["session_code"] == session), key=lambda row: str(row["session_date"]))
            path = paths.m2 / filename
            selected = _feature_rows_primary(path, session_rows) if implementation == "primary" else _feature_rows_reference(path, session_rows)
            crossed_features.extend(selected)
        crossed_features.sort(key=lambda item: item["feature_identity_hash"])
        if len(crossed_features) != EXPECTED_CROSSED_CLOSES:
            raise ValueError(f"Expected fifteen crossed closes in {implementation}, found {len(crossed_features)}")
        crossed_findings, source_bindings = _analyze_crossed_features(crossed_features, rows_by_id, acquisition, implementation)
        findings = sorted([*xau_findings, *crossed_findings], key=lambda item: (item["domain"], item["finding_id"]))
        recommendation = _recommendation(findings)
        result: dict[str, Any] = {
            "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_RESULT_V1_0",
            "implementation": implementation,
            "completed_at_utc": _utc_now(),
            "status": "COMPLETE_PENDING_REPRODUCTION_SEAL",
            "xau_findings": xau_findings,
            "crossed_bucket_findings": crossed_findings,
            "classification_counts": dict(sorted(Counter(str(item["classification"]) for item in findings).items())),
            "domain_counts": {"XAU_TIMESTAMP": len(xau_findings), "CROSSED_BUCKET_CLOSE": len(crossed_findings)},
            "xau_source_audit": {
                "source_rows": int(xau_scan["source_rows"]),
                "source_order_regressions": int(xau_scan["source_order_regressions"]),
                "first_2025_or_2026_line_deserialized": bool(xau_scan["first_2025_or_2026_line_deserialized"]),
                "source_sha256": EXPECTED["xau"],
            },
            "affected_source_bindings": source_bindings,
            "recommendation": recommendation,
            "market_book_feature_or_outcome_values_reported": False,
            "development_outcomes_opened_or_joined": False,
            "year_2025_or_2026_values_accessed": False,
            "data_repaired_refreshed_filtered_relabeled_reacquired_or_recalculated": False,
            "relationships_candidates_execution_or_performance_calculated": False,
            "charge_incurred_usd": 0.0,
            "result_receipt": None,
        }
        result["result_receipt"] = _canonical_hash({**result, "result_receipt": None})
        _write_json_exclusive(paths.output / f"{implementation}_diagnostic.json", result)
        outputs[implementation] = result
        print(json.dumps({"stage": "M2_R1_IMPLEMENTATION_COMPLETE", "implementation": implementation, "xau_findings": len(xau_findings), "crossed_findings": len(crossed_findings), "values_reported": False}, sort_keys=True), flush=True)
    reproduction = _normalize_result(outputs["primary"]) == _normalize_result(outputs["reference"])
    _write_json_exclusive(paths.output / "reproduction_check.json", {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_REPRODUCTION_V1_0",
        "status": "PASS_EXACT_REPRODUCTION" if reproduction else "FAIL_DIAGNOSTIC_REPRODUCTION",
        "primary_normalized_receipt": _canonical_hash(_normalize_result(outputs["primary"])),
        "reference_normalized_receipt": _canonical_hash(_normalize_result(outputs["reference"])),
        "identical": reproduction,
        "compared_findings": EXPECTED_XAU_GAPS + EXPECTED_CROSSED_CLOSES,
    })
    print(json.dumps({"status": "M2_R1_DIAGNOSTIC_COMPLETE_PENDING_SEAL", "reproduction": reproduction, "findings": 18, "values_reported": False}, sort_keys=True))


def _render_report(verdict: Mapping[str, Any], result: Mapping[str, Any]) -> str:
    lines = [
        "# GC Session Trigger Edge Discovery V1 — Milestone 2-R1",
        "",
        f"Formal status: `{verdict['status']}`",
        "",
        "## Preserved predecessor",
        "",
        "Milestone 2 remains formally `FAIL_FULL_SESSION_TIMESTAMP_COVERAGE`. No predecessor artifact or verdict was changed.",
        "",
        "## XAUUSD timestamp findings",
        "",
        "| Session key | Expected UTC timestamp | Classification |",
        "|---|---|---|",
    ]
    for item in sorted(result["xau_findings"], key=lambda value: (value["session_date"], value["session_code"], value["expected_timestamp_utc"])):
        lines.append(f"| {item['session_date']} {item['session_code']} | {item['expected_timestamp_utc']} | {item['classification']} |")
    lines.extend(["", "## Crossed bucket-close findings", "", "| Session key | Bucket close UTC | Classification | Terminal class |", "|---|---|---|---|"])
    for item in sorted(result["crossed_bucket_findings"], key=lambda value: (value["session_date"], value["session_code"], value["bucket_end_utc"])):
        lines.append(f"| {item['session_date']} {item['session_code']} | {item['bucket_end_utc']} | {item['classification']} | {item['evidence']['terminal_state_class']} |")
    lines.extend([
        "",
        "## Reproduction and scope",
        "",
        "- Primary and reference diagnostics were required to agree exactly on all 18 findings.",
        f"- Reproduction: `{'PASS' if verdict['formal_gates']['primary_reference_exact_reproduction'] else 'FAIL'}`.",
        "- No prices, depths, order-flow values, feature values, outcomes, relationships, candidates, execution, trades, PnL, R multiples, or returns were reported.",
        "- No 2025 or 2026 row was opened; no data was acquired and no charge was incurred.",
        "",
        "## Bounded recommendation",
        "",
        f"`{result['recommendation']['recommendation_id']}`",
        "",
        str(result["recommendation"].get("text") or result["recommendation"].get("reason")),
        "",
        "Milestone 2-R1 is complete. Stop without implementing the recommendation or beginning relationship research.",
    ])
    return "\n".join(lines)


def _seal(paths: Paths) -> None:
    _verified_control(paths, verify_registered_artifacts=False)
    preflight = _read(paths.output / "preflight.json")
    primary = _read(paths.output / "primary_diagnostic.json")
    reference = _read(paths.output / "reference_diagnostic.json")
    reproduction = _read(paths.output / "reproduction_check.json")
    normalized_equal = _normalize_result(primary) == _normalize_result(reference)
    all_findings = [*primary["xau_findings"], *primary["crossed_bucket_findings"]]
    identities = [str(item["finding_id"]) for item in all_findings]
    classes_valid = all(str(item["classification"]) in CLASSES for item in all_findings)
    gates = {
        "predecessor_and_source_seals_valid": preflight.get("status") == "PASS_M2_R1_PRE_DIAGNOSTIC_READINESS" and all(_mapping(preflight.get("formal_gates")).values()),
        "exact_three_xau_findings": len(primary["xau_findings"]) == EXPECTED_XAU_GAPS,
        "exact_fifteen_crossed_bucket_findings": len(primary["crossed_bucket_findings"]) == EXPECTED_CROSSED_CLOSES,
        "every_finding_classified_once": len(identities) == 18 and len(set(identities)) == 18 and classes_valid,
        "primary_reference_exact_reproduction": normalized_equal and reproduction.get("identical") is True,
        "no_market_or_feature_values_reported": primary.get("market_book_feature_or_outcome_values_reported") is False and reference.get("market_book_feature_or_outcome_values_reported") is False,
        "at_most_one_recommendation": int(_mapping(primary.get("recommendation")).get("bounded_correction_count", -1)) <= 1,
        "no_repair_refresh_filter_relabel_reacquisition_or_recalculation": primary.get("data_repaired_refreshed_filtered_relabeled_reacquired_or_recalculated") is False,
        "no_outcome_relationship_candidate_execution_or_performance_work": primary.get("development_outcomes_opened_or_joined") is False and primary.get("relationships_candidates_execution_or_performance_calculated") is False,
        "no_2025_or_2026_access": primary.get("year_2025_or_2026_values_accessed") is False and not primary["xau_source_audit"]["first_2025_or_2026_line_deserialized"],
        "zero_charge": float(primary.get("charge_incurred_usd", -1)) == 0.0,
    }
    if not gates["predecessor_and_source_seals_valid"]:
        status = "FAIL_PREDECESSOR_OR_SOURCE_INTEGRITY"
    elif not all(value for name, value in gates.items() if name != "primary_reference_exact_reproduction"):
        status = "FAIL_DIAGNOSTIC_INTEGRITY"
    elif not gates["primary_reference_exact_reproduction"]:
        status = "FAIL_DIAGNOSTIC_REPRODUCTION"
    else:
        status = "PASS_DIAGNOSTIC_REPRODUCTION"
    verdict: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_VERDICT_V1_0",
        "status": status,
        "formal_pass": status == "PASS_DIAGNOSTIC_REPRODUCTION",
        "completed_at_utc": _utc_now(),
        "classification": "METADATA_ONLY_COVERAGE_AND_FEATURE_INTEGRITY_DIAGNOSTIC",
        "preserved_m2_status": EXPECTED_M2_STATUS,
        "formal_gates": gates,
        "finding_counts": {
            "xau_timestamp": len(primary["xau_findings"]),
            "crossed_bucket_close": len(primary["crossed_bucket_findings"]),
            "total": len(all_findings),
            "by_classification": dict(sorted(Counter(str(item["classification"]) for item in all_findings).items())),
        },
        "recommendation": primary["recommendation"],
        "market_book_feature_or_outcome_values_reported": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": "Milestone 2-R1 complete. Stop before implementing any correction, recertifying Milestone 2, opening outcomes, or beginning relationship research.",
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = _canonical_hash({**verdict, "verdict_receipt": None})
    verdict_path = paths.output / "verdict.json"
    report_path = paths.output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_2_R1.md"
    _write_json_exclusive(verdict_path, verdict)
    _write_text_exclusive(report_path, _render_report(verdict, primary))
    artifact_paths = [
        paths.output / "preflight.json",
        paths.output / "primary_diagnostic.json",
        paths.output / "reference_diagnostic.json",
        paths.output / "reproduction_check.json",
        verdict_path,
        report_path,
    ]
    manifest: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_MANIFEST_V1_0",
        "status": status,
        "sealed_at_utc": _utc_now(),
        "protocol": _file(PROTOCOL_PATH),
        "freeze": _file(FREEZE_PATH),
        "implementation": _file(Path(__file__)),
        "m2_final_seal": _file(paths.m2 / "final_seal.json"),
        "m2_manifest": _file(paths.m2 / "manifest.json"),
        "acquisition_manifest": _file(paths.acquisition),
        "xau_source": {"path": str(paths.xau), "bytes": paths.xau.stat().st_size, "sha256": EXPECTED["xau"]},
        "artifacts": [_file(path) for path in artifact_paths],
        "verdict_receipt": verdict["verdict_receipt"],
        "m2_verdict_preserved": True,
        "market_book_feature_or_outcome_values_reported": False,
        "year_2025_or_2026_values_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = _canonical_hash({**manifest, "manifest_receipt": None})
    manifest_path = paths.output / "manifest.json"
    _write_json_exclusive(manifest_path, manifest)
    final: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_FINAL_SEAL_V1_0",
        "status": status,
        "sealed_at_utc": _utc_now(),
        "freeze_sha256": _sha256(FREEZE_PATH),
        "verdict_sha256": _sha256(verdict_path),
        "manifest_sha256": _sha256(manifest_path),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = _canonical_hash({**final, "final_seal_receipt": None})
    _write_json_exclusive(paths.output / "final_seal.json", final)
    print(json.dumps({"status": status, "findings": len(all_findings), "recommendation": primary["recommendation"]["recommendation_id"], "values_reported": False}, sort_keys=True))


def _verify_final(paths: Paths) -> None:
    _verified_control(paths, verify_registered_artifacts=False)
    verdict = _read(paths.output / "verdict.json")
    manifest = _read(paths.output / "manifest.json")
    final = _read(paths.output / "final_seal.json")
    if final.get("freeze_sha256") != _sha256(FREEZE_PATH) or final.get("verdict_sha256") != _sha256(paths.output / "verdict.json") or final.get("manifest_sha256") != _sha256(paths.output / "manifest.json"):
        raise ValueError("R1 final bindings failed")
    if not _receipt_ok(verdict, "verdict_receipt") or not _receipt_ok(manifest, "manifest_receipt") or not _receipt_ok(final, "final_seal_receipt"):
        raise ValueError("R1 receipt verification failed")
    for record in _sequence(manifest.get("artifacts")):
        path = Path(str(record["path"]))
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or _sha256(path) != str(record["sha256"]):
            raise ValueError(f"R1 artifact verification failed: {path}")
    print(json.dumps({"status": final["status"], "verified_artifacts": len(manifest["artifacts"]), "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def _self_test() -> None:
    line = b'{"record_type":"PRICE_BAR","record_id":"r1","record_hash":"aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa","provider_code":"IC_MARKETS_MT5","instrument_code":"XAUUSD","timeframe":"1m","open_time":"2024-01-02T08:00:00Z","close_time":"2024-01-02T08:01:00Z","available_at":"2024-01-02T08:01:00Z","complete":true,"ohlc":{"open":"FORBIDDEN","high":"FORBIDDEN","low":"FORBIDDEN","close":"FORBIDDEN"}}\n'
    primary = _project_regex(line)
    reference = _manual_top_level_scalars(line)
    if primary != reference or "ohlc" in primary or "ohlc" in reference or not _xau_record_valid(primary):
        raise AssertionError("Independent XAU scalar projection self-test failed")
    documented = {
        "state_mapping_count": 1, "mbp_group_contiguous": True, "mbp_group_f_last_count": 1,
        "mbp_terminal_f_last": True, "selected_snapshot": False, "selected_reset": False,
        "selected_f_last": False, "selected_state_class": "CROSSED", "terminal_state_class": "TWO_SIDED_UNCROSSED",
        "selected_is_latest_before_bucket_close": True, "terminal_before_bucket_close": False,
        "terminal_at_or_after_bucket_close": True, "terminal_after_selected": True,
    }
    if _classify_cross_primary(documented) != "DOCUMENTED_VALID_SEMANTICS" or _classify_cross_reference(documented) != "DOCUMENTED_VALID_SEMANTICS":
        raise AssertionError("Crossed-state classification self-test failed")
    print(json.dumps({"status": "PASS_M2_R1_IMPLEMENTATION_SELF_TEST", "market_values_accessed": False}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("self-test", "preflight", "diagnose", "seal", "verify"))
    parser.add_argument("--m2", default=str(DEFAULT_M2_DIR))
    parser.add_argument("--acquisition", default=str(DEFAULT_ACQUISITION))
    parser.add_argument("--xau", default=str(DEFAULT_XAU))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    if args.action == "self-test":
        _self_test()
        return
    paths = Paths(Path(args.m2), Path(args.acquisition), Path(args.xau), Path(args.output))
    if args.action == "preflight":
        _preflight(paths)
    elif args.action == "diagnose":
        _run_diagnostic(paths)
    elif args.action == "seal":
        _seal(paths)
    else:
        _verify_final(paths)


if __name__ == "__main__":
    main()
