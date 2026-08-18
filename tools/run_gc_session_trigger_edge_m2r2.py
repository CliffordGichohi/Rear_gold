#!/usr/bin/env python3
"""Final outcome-blind Milestone 2-R2 technical recertification.

The sealed M2, M2-R1, and M2-R1-A1 implementations are imported unchanged.
R2 adds only the frozen universal technical-unavailability disposition and an
independent Parquet reference reader whose timestamp statistics are explicitly
converted as nanoseconds.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
import tempfile
from collections import Counter
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq

import materialize_gc_session_trigger_edge_m2 as m2
import run_gc_session_trigger_edge_m2r1a1 as a1


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"
PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2r2_protocol_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2r2_freeze_v01.json"
DEFAULT_OLD_M2 = ARTIFACTS / "gc_session_trigger_edge_m2_v01"
DEFAULT_OLD_R1 = ARTIFACTS / "gc_session_trigger_edge_m2r1_v01"
DEFAULT_OLD_A1 = ARTIFACTS / "gc_session_trigger_edge_m2r1a1_v01"
DEFAULT_OUTPUT = ARTIFACTS / "gc_session_trigger_edge_m2r2_v01"

ENGINEERING_PRIMARY = ARTIFACTS / "gc_microstructure_step_4a3_v01/primary_features.parquet"
ENGINEERING_REFERENCE = ARTIFACTS / "gc_microstructure_step_4a3_v01/reference_features.parquet"
ENGINEERING_VERDICT = ARTIFACTS / "gc_microstructure_step_4a3_v01/verdict.json"
ENGINEERING_MBO = ROOT / "data/raw/databento_gc_mbo_engineering_pilot/GLBX-20260730-WB9AXCVFET/normalized/gc_v_0_2024_01_09_mbo.parquet"
ENGINEERING_MBP = ROOT / "data/raw/databento_gc_mbp10_engineering_benchmark/GLBX-20260731-UJHWEDQUSX/normalized/gc_v_0_2024_01_09_mbp10.parquet"

EXPECTED = {
    "m2_engine": "acc7af0c5196cc943ad129560f736b31fda03727979fe43b58a7bcf0188d5479",
    "step5c_engine": "81e2aa4c620aa2bf4e151c727af6827d7743a4e8e452a85d3f78dc1ac7188e92",
    "base_engine": "c5589914a1acae6a3a1e9079c302821477866bba3741317392c567bb590c2369",
    "a1_engine": "6217d0c9e5e137c9163849b9f2ca8d9d539308bb88d6ac5a807e0bc69aa6bd8c",
    "m2_final": "c6b86602eceb927db71f56e35bce3bd8778f350f7853429cebbbf281d94c7e85",
    "m2_manifest": "adffdc302f103c8eac307d30193ee06f83e5dafd2fa0e597c9601dbf78a67760",
    "m2_verdict": "03b1bbae4f56caa9b1586ec381805040d24f8e0764da40ad3a3ceaeb8dc85267",
    "r1_final": "07a4ee79e8bf75a699bf4fb34a546da7ccde8e1992d8d0d9123f24ed575db80f",
    "r1_primary": "82444ce02a05de75d276eb2e773b68b6f8dfd97a659277c557ecd51a672cd91d",
    "a1_final": "0cf047b3c3d9aa01e5ee44876635192dad90b83be47886f8ce65f96904bd2c01",
    "statistics": "08fa00873058572b2df4a94e49eb6f85708c71cb60657b8d63d2f4a33dd3a7c2",
    "m2_protocol": "d4490ac0311e0a6a6b40595b6c97ee7e8eba357db14f11ccdbbb0c5b32c8d509",
    "m2_registry": "a7a36ae82d92ce91a25e36fcb7f1c95807de67c996d01198648246daa345dc5d",
    "engineering_features": "b559771bc332f400900da43e3c16619a5b75b9457c2a15975d390e977085eda3",
    "engineering_mbo": "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3",
    "engineering_mbp": "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4",
    "acquisition": "b4e64d508790364dbd400da1478b139bb643d2b7afc9c97ff6691958365c5ccc",
    "xau": "0758f9a759bf63064d0ed4478383c10f9afd860bf993528b7909965c1639090e",
}

PRESERVED = {
    "m2_status": "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE",
    "m2_receipt": "39aaf9ac37851a2bc948aba2fb503d68085563071604a50a672094f1560f000f",
    "r1_status": "FAIL_DIAGNOSTIC_REPRODUCTION",
    "r1_receipt": "6d728c21f52cb189d82db2b20d8acd402bb8cf9d44ca142064b708e5d1865df2",
    "a1_status": "PASS_M2_R1_A1_REFERENCE_REPRODUCTION",
    "a1_receipt": "31b659447d417696dc625dacfc7ccca8bfa913a1efa0866bd77be18315a01517",
}

AUTHORIZATION = """Proceed to GC Session Trigger Edge Discovery V1 Milestone 2-R2 under a final outcome-blind data-quality disposition amendment. Preserve the Milestone 2 and Milestone 2-R1 failures, the Milestone 2-R1-A1 PASS, and every prior artifact and seal. Preserve the original classifications of the fifteen terminal continuous-matching crossed MBP-10 bucket-close states and three unresolved XAUUSD timestamps; do not repair, impute, substitute, delete, or relabel them. Before reopening development metadata, freeze a universal eligibility policy: any continuous-matching bucket whose terminal F_LAST MBP-10 state is crossed must be classified UNAVAILABLE_TECHNICAL, and all state-dependent features must remain UNKNOWN until the next valid uncrossed terminal F_LAST state. Any XAUUSD-dependent context requiring a missing expected minute must also be UNAVAILABLE_TECHNICAL. Apply these rules universally rather than only to the eighteen known findings. Using only existing sealed 2021-2024 sources and the corrected nanosecond reference reader, regenerate only technical features, event identities, and event-support counts. Require exact primary/reference agreement on row identities, missingness classifications, feature checksums, event identities, support counts, and diagnostics. Require every frozen event family to retain its support floor and verify that no invalid state contributed to an eligible event. Permit one recertification attempt only. Do not open outcomes, calculate relationships or hit rates, create candidates, inspect 2025/2026, acquire data, optimize execution, or calculate trades or PnL. PASS advances the branch to relationship discovery. FAIL permanently terminates the current microstructure branch without another engineering diagnostic. Seal the result and stop."""

F_LAST = 128
VALID_GC = "VALID_CONTINUOUS_TWO_SIDED_UNCROSSED"
UNAVAILABLE = "UNAVAILABLE_TECHNICAL"
EXPECTED_RAW_CROSSED = 15
EXPECTED_UNRESOLVED_XAU = 3


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")).hexdigest()


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, indent=2, sort_keys=True, ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
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


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def receipt_valid(value: Mapping[str, Any], field: str) -> bool:
    return value.get(field) == canonical_hash({**value, field: None})


def verify_bound(path: Path, expected: str, label: str) -> None:
    if not path.is_file() or sha256_file(path) != expected:
        raise ValueError(f"Preserved binding failed: {label}")


def verify_predecessors(old_m2: Path, old_r1: Path, old_a1: Path) -> dict[str, Any]:
    bindings = (
        (Path(m2.__file__), EXPECTED["m2_engine"], "M2 implementation"),
        (m2.STEP5C_ENGINE_PATH, EXPECTED["step5c_engine"], "Step 5C implementation"),
        (m2.BASE_ENGINE_PATH, EXPECTED["base_engine"], "base feature implementation"),
        (Path(a1.__file__), EXPECTED["a1_engine"], "A1 implementation"),
        (old_m2 / "final_seal.json", EXPECTED["m2_final"], "M2 final"),
        (old_m2 / "manifest.json", EXPECTED["m2_manifest"], "M2 manifest"),
        (old_m2 / "verdict.json", EXPECTED["m2_verdict"], "M2 verdict"),
        (old_r1 / "final_seal.json", EXPECTED["r1_final"], "R1 final"),
        (old_r1 / "primary_diagnostic.json", EXPECTED["r1_primary"], "R1 primary"),
        (old_a1 / "final_seal.json", EXPECTED["a1_final"], "A1 final"),
        (m2.M1_STATISTICS, EXPECTED["statistics"], "frozen support rules"),
        (m2.PROTOCOL_PATH, EXPECTED["m2_protocol"], "M2 protocol"),
        (m2.ROW_REGISTRY_PATH, EXPECTED["m2_registry"], "M2 row registry"),
    )
    for path, expected, label in bindings:
        verify_bound(path, expected, label)
    m2_final = read_json(old_m2 / "final_seal.json")
    r1_final = read_json(old_r1 / "final_seal.json")
    a1_final = read_json(old_a1 / "final_seal.json")
    for value, status, receipt in (
        (m2_final, PRESERVED["m2_status"], PRESERVED["m2_receipt"]),
        (r1_final, PRESERVED["r1_status"], PRESERVED["r1_receipt"]),
        (a1_final, PRESERVED["a1_status"], PRESERVED["a1_receipt"]),
    ):
        if value.get("status") != status or value.get("final_seal_receipt") != receipt or not receipt_valid(value, "final_seal_receipt"):
            raise ValueError(f"Preserved final-seal verification failed: {status}")
    primary = read_json(old_r1 / "primary_diagnostic.json")
    xau = primary.get("xau_findings", [])
    crossed = primary.get("crossed_bucket_findings", [])
    if len(xau) != 3 or len(crossed) != 15:
        raise ValueError("The preserved 3+15 finding population changed")
    if any(item.get("classification") != "UNRESOLVED" for item in xau):
        raise ValueError("An unresolved XAU classification changed")
    if any(item.get("classification") != "GENUINE_SOURCE_OR_STATE_FAILURE" for item in crossed):
        raise ValueError("A terminal crossed-state classification changed")
    if any(not item.get("evidence", {}).get("selected_f_last") or item.get("evidence", {}).get("terminal_state_class") != "CROSSED" for item in crossed):
        raise ValueError("The preserved terminal F_LAST evidence changed")
    return {
        "m2_status": m2_final["status"],
        "m2_final_seal_receipt": m2_final["final_seal_receipt"],
        "m2r1_status": r1_final["status"],
        "m2r1_final_seal_receipt": r1_final["final_seal_receipt"],
        "m2r1a1_status": a1_final["status"],
        "m2r1a1_final_seal_receipt": a1_final["final_seal_receipt"],
        "preserved_terminal_crossed_findings": len(crossed),
        "preserved_unresolved_xau_findings": len(xau),
        "preserved_finding_checksum": canonical_hash(sorted([*xau, *crossed], key=lambda item: str(item["finding_id"]))),
    }


def clone_columns(columns: Mapping[str, Sequence[Any]]) -> dict[str, list[Any]]:
    return {name: list(values) for name, values in columns.items()}


def flags_by_ordinal(arrays: Mapping[str, np.ndarray[Any, Any]], anchor: pa.Table) -> dict[int, int]:
    output = {
        int(ordinal): int(flags)
        for ordinal, flags in zip(arrays["source_row_ordinal"], arrays["flags"], strict=True)
    }
    output[int(anchor["source_row_ordinal"][0].as_py())] = int(anchor["flags"][0].as_py())
    return output


def _make_ofi_unavailable(columns: dict[str, list[Any]], index: int) -> None:
    transitions = int(columns["quote_ofi_transition_count"][index])
    columns["quote_ofi_transition_count"][index] = 0
    columns["quote_ofi_skipped_count"][index] = int(columns["quote_ofi_skipped_count"][index]) + transitions
    columns["quote_ofi_raw"][index] = 0


def _make_book_unavailable(columns: dict[str, list[Any]], index: int, base: Any) -> None:
    columns["state_available"][index] = False
    columns["book_two_sided"][index] = False
    columns["book_locked"][index] = False
    columns["book_crossed"][index] = False
    nullable = (
        "state_source_row_ordinal", "state_ts_recv_ns", "book_age_ns",
        *base.MBP_PRICE_COLUMNS, *base.MBP_DEPTH_COLUMNS,
    )
    for name in nullable:
        columns[name][index] = None


def _make_unavailable(columns: dict[str, list[Any]], index: int, base: Any) -> None:
    _make_ofi_unavailable(columns, index)
    _make_book_unavailable(columns, index, base)


def _policy_receipt(
    row_id: str,
    columns: Mapping[str, Sequence[Any]],
    unavailable: Sequence[bool],
    ofi_unavailable: Sequence[bool],
) -> str:
    digest = hashlib.sha256()
    digest.update(row_id.encode("utf-8"))
    for index, state in enumerate(unavailable):
        digest.update(struct.pack(">qq??", int(columns["bucket_index"][index]), int(columns["bucket_start_ns"][index]), bool(state), bool(ofi_unavailable[index])))
    return digest.hexdigest()


def apply_policy_primary(
    row_id: str,
    source: Mapping[str, Sequence[Any]],
    ordinal_flags: Mapping[int, int],
    base: Any,
) -> tuple[dict[str, list[Any]], list[bool], dict[str, Any]]:
    columns = clone_columns(source)
    unavailable = [False] * len(columns["bucket_index"])
    ofi_unavailable = [False] * len(columns["bucket_index"])
    latched = False
    invalid_ordinal: int | None = None
    raw_crossed = starts = recoveries = nonterminal = retained = 0
    for index in range(len(unavailable)):
        recovered_this_bucket = False
        ordinal_raw = columns["state_source_row_ordinal"][index]
        ordinal = None if ordinal_raw is None else int(ordinal_raw)
        flags = None if ordinal is None else ordinal_flags.get(ordinal)
        crossed = (
            columns["market_state"][index] == "CONTINUOUS_MATCHING"
            and bool(columns["state_available"][index])
            and bool(columns["book_two_sided"][index])
            and bool(columns["book_crossed"][index])
        )
        if crossed:
            raw_crossed += 1
            if flags is None or not (flags & F_LAST):
                nonterminal += 1
                raise ValueError("Crossed bucket-close state is not a terminal F_LAST emission")
            if not latched:
                starts += 1
            latched = True
            invalid_ordinal = ordinal
        elif latched:
            valid_recovery = (
                ordinal is not None
                and ordinal != invalid_ordinal
                and flags is not None
                and bool(flags & F_LAST)
                and bool(columns["state_available"][index])
                and bool(columns["book_two_sided"][index])
                and not bool(columns["book_locked"][index])
                and not bool(columns["book_crossed"][index])
            )
            if valid_recovery:
                latched = False
                invalid_ordinal = None
                recoveries += 1
                recovered_this_bucket = True
        if latched:
            unavailable[index] = True
            ofi_unavailable[index] = True
            _make_unavailable(columns, index, base)
        elif recovered_this_bucket:
            ofi_unavailable[index] = True
            _make_ofi_unavailable(columns, index)
        if unavailable[index] and (columns["state_available"][index] or columns["book_crossed"][index] or columns["state_source_row_ordinal"][index] is not None):
            retained += 1
        if ofi_unavailable[index] and (int(columns["quote_ofi_transition_count"][index]) != 0 or int(columns["quote_ofi_raw"][index]) != 0):
            retained += 1
    diagnostics = {
        "raw_terminal_crossed_bucket_closes": raw_crossed,
        "unavailability_latch_starts": starts,
        "valid_recovery_boundaries": recoveries,
        "technical_unavailable_bucket_closes": sum(unavailable),
        "technical_unavailable_ofi_buckets": sum(ofi_unavailable),
        "crossed_non_f_last_failures": nonterminal,
        "invalid_state_values_retained": retained,
        "post_policy_crossed_bucket_closes": sum(bool(value) for value in columns["book_crossed"]),
        "post_policy_state_available_buckets": sum(bool(value) for value in columns["state_available"]),
        "classification_checksum": _policy_receipt(row_id, columns, unavailable, ofi_unavailable),
    }
    return columns, unavailable, diagnostics


def apply_policy_reference(
    row_id: str,
    source: Mapping[str, Sequence[Any]],
    ordinal_flags: Mapping[int, int],
    base: Any,
) -> tuple[dict[str, list[Any]], list[bool], dict[str, Any]]:
    columns = clone_columns(source)
    count = len(columns["bucket_index"])
    unavailable = np.zeros(count, dtype=bool)
    ofi_unavailable = np.zeros(count, dtype=bool)
    active = False
    poisoned: int | None = None
    raw_crossed = starts = recoveries = 0
    for index in range(count):
        recovered_this_bucket = False
        ordinal_value = columns["state_source_row_ordinal"][index]
        ordinal = None if ordinal_value is None else int(ordinal_value)
        flags = ordinal_flags.get(ordinal) if ordinal is not None else None
        is_crossed = columns["market_state"][index] == "CONTINUOUS_MATCHING" and all((
            bool(columns["state_available"][index]),
            bool(columns["book_two_sided"][index]),
            bool(columns["book_crossed"][index]),
        ))
        if is_crossed:
            raw_crossed += 1
            if flags is None or int(flags) & F_LAST == 0:
                raise ValueError("Reference crossed state lacks terminal F_LAST")
            starts += int(not active)
            active = True
            poisoned = ordinal
        if active and not is_crossed:
            recovers = all((
                ordinal is not None,
                ordinal != poisoned,
                flags is not None,
                flags is not None and int(flags) & F_LAST != 0,
                bool(columns["state_available"][index]),
                bool(columns["book_two_sided"][index]),
                not bool(columns["book_locked"][index]),
                not bool(columns["book_crossed"][index]),
            ))
            if recovers:
                active = False
                poisoned = None
                recoveries += 1
                recovered_this_bucket = True
        unavailable[index] = active
        if active:
            ofi_unavailable[index] = True
            _make_unavailable(columns, index, base)
        elif recovered_this_bucket:
            ofi_unavailable[index] = True
            _make_ofi_unavailable(columns, index)
    unavailable_list = unavailable.tolist()
    retained = sum(
        bool(unavailable_list[index])
        and (bool(columns["state_available"][index]) or bool(columns["book_crossed"][index]) or columns["state_source_row_ordinal"][index] is not None)
        for index in range(count)
    )
    retained += sum(
        bool(ofi_unavailable[index])
        and (int(columns["quote_ofi_transition_count"][index]) != 0 or int(columns["quote_ofi_raw"][index]) != 0)
        for index in range(count)
    )
    diagnostics = {
        "raw_terminal_crossed_bucket_closes": int(raw_crossed),
        "unavailability_latch_starts": int(starts),
        "valid_recovery_boundaries": int(recoveries),
        "technical_unavailable_bucket_closes": int(np.count_nonzero(unavailable)),
        "technical_unavailable_ofi_buckets": int(np.count_nonzero(ofi_unavailable)),
        "crossed_non_f_last_failures": 0,
        "invalid_state_values_retained": int(retained),
        "post_policy_crossed_bucket_closes": int(np.count_nonzero(np.asarray(columns["book_crossed"], dtype=bool))),
        "post_policy_state_available_buckets": int(np.count_nonzero(np.asarray(columns["state_available"], dtype=bool))),
        "classification_checksum": _policy_receipt(row_id, columns, unavailable_list, ofi_unavailable.tolist()),
    }
    return columns, unavailable_list, diagnostics


def synthetic_columns(base: Any) -> tuple[dict[str, list[Any]], dict[int, int]]:
    count = 6
    output: dict[str, list[Any]] = {}
    for field in base.FEATURE_SCHEMA:
        if field.name == "market_segment":
            output[field.name] = ["CONTINUOUS_00_22"] * count
        elif field.name == "market_state":
            output[field.name] = ["CONTINUOUS_MATCHING"] * count
        elif pa.types.is_boolean(field.type):
            output[field.name] = [False] * count
        elif field.nullable:
            output[field.name] = [1] * count
        else:
            output[field.name] = [0] * count
    output["bucket_index"] = list(range(count))
    output["bucket_start_ns"] = [1_704_758_400_000_000_000 + index * 1_000_000_000 for index in range(count)]
    output["bucket_end_ns"] = [value + 1_000_000_000 for value in output["bucket_start_ns"]]
    output["state_available"] = [True] * count
    output["book_two_sided"] = [True] * count
    output["book_locked"] = [False] * count
    output["book_crossed"] = [False, True, True, False, False, False]
    output["state_source_row_ordinal"] = [1, 2, 2, 3, 3, 4]
    output["quote_ofi_transition_count"] = [1] * count
    output["quote_ofi_skipped_count"] = [0] * count
    output["quote_ofi_raw"] = [10] * count
    return output, {1: F_LAST, 2: F_LAST | 2, 3: F_LAST, 4: F_LAST}


def engineering_integration_proof() -> dict[str, Any]:
    verify_bound(ENGINEERING_MBO, EXPECTED["engineering_mbo"], "engineering MBO payload")
    verify_bound(ENGINEERING_MBP, EXPECTED["engineering_mbp"], "engineering MBP-10 payload")
    s5c = m2._load_module(m2.STEP5C_ENGINE_PATH, "gc_m2r2_integration_s5c")
    base = m2._load_module(m2.BASE_ENGINE_PATH, "gc_m2r2_integration_base")
    start = int(datetime(2024, 1, 9, 7, 45, tzinfo=UTC).timestamp() * 1_000_000_000)
    end = start + m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION * m2.BUCKET_NS
    day_start = int(datetime(2024, 1, 9, tzinfo=UTC).timestamp() * 1_000_000_000)
    p_mbo = m2._source_table(ENGINEERING_MBO, base.MBO_COLUMNS, start, end, s5c)
    p_mbp = m2._source_table(ENGINEERING_MBP, base.MBP_COLUMNS, start, end, s5c)
    r_mbo = a1.read_range_reference_ns(ENGINEERING_MBO, base.MBO_COLUMNS, start, end)
    r_mbp = a1.read_range_reference_ns(ENGINEERING_MBP, base.MBP_COLUMNS, start, end)
    p_anchor = s5c._read_exact_anchor(ENGINEERING_MBP, base.MBP_COLUMNS, start, day_start)
    r_anchor = read_anchor_reference(ENGINEERING_MBP, base.MBP_COLUMNS, start, day_start)
    if not (table_exact(p_mbo, r_mbo) and table_exact(p_mbp, r_mbp) and table_exact(p_anchor, r_anchor)):
        raise AssertionError("Engineering integration source-reader equality failed")
    p_mbo_arrays = s5c._table_arrays(p_mbo, base.MBO_COLUMNS)
    p_mbp_arrays = s5c._table_arrays(p_mbp, base.MBP_COLUMNS)
    r_mbo_arrays = s5c._table_arrays(r_mbo, base.MBO_COLUMNS)
    r_mbp_arrays = s5c._table_arrays(r_mbp, base.MBP_COLUMNS)
    row = {
        "window_start_inclusive_ns": start,
        "window_end_exclusive_ns": end,
        "expected_instrument_id": int(p_mbp_arrays["instrument_id"][0]),
        "bucket_index_start_inclusive": 0,
        "session_code": "LONDON",
    }
    s5c.WINDOW_BUCKETS = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    p_raw, _ = s5c._primary_window_features(row, p_mbo_arrays, p_mbp_arrays, p_anchor, base)
    r_raw, _ = s5c._reference_window_features(row, r_mbo_arrays, r_mbp_arrays, r_anchor, base)
    p_columns, p_mask, p_policy = apply_policy_primary("ENGINEERING_INTEGRATION", p_raw, flags_by_ordinal(p_mbp_arrays, p_anchor), base)
    r_columns, r_mask, r_policy = apply_policy_reference("ENGINEERING_INTEGRATION", r_raw, flags_by_ordinal(r_mbp_arrays, r_anchor), base)
    if p_columns != r_columns or p_mask != r_mask or p_policy != r_policy:
        raise AssertionError("Engineering integration feature/policy equality failed")
    return {
        "classification": "ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
        "mbo_rows": p_mbo.num_rows,
        "mbp10_rows": p_mbp.num_rows,
        "anchor_rows": p_anchor.num_rows,
        "buckets": len(p_mask),
        "technical_unavailable_buckets": sum(p_mask),
        "primary_reference_source_reader_exact": True,
        "primary_reference_features_and_policy_exact": True,
        "classification_checksum": p_policy["classification_checksum"],
    }


def pre_freeze_proof() -> dict[str, Any]:
    base = m2._load_module(m2.BASE_ENGINE_PATH, "gc_m2r2_proof_base")
    columns, flags = synthetic_columns(base)
    primary, primary_mask, primary_diag = apply_policy_primary("SYNTHETIC", columns, flags, base)
    reference, reference_mask, reference_diag = apply_policy_reference("SYNTHETIC", columns, flags, base)
    if primary != reference or primary_mask != [False, True, True, False, False, False] or primary_mask != reference_mask or primary_diag != reference_diag:
        raise AssertionError("Synthetic universal-disposition reproduction failed")
    if primary_diag["raw_terminal_crossed_bucket_closes"] != 2 or primary_diag["technical_unavailable_bucket_closes"] != 2 or primary_diag["valid_recovery_boundaries"] != 1:
        raise AssertionError("Synthetic latch semantics failed")
    if read_json(ENGINEERING_VERDICT).get("status") != "PASS_FEATURE_INTEGRITY_RECERTIFICATION":
        raise ValueError("Engineering-only predecessor is not recertified")
    for path in (ENGINEERING_PRIMARY, ENGINEERING_REFERENCE):
        verify_bound(path, EXPECTED["engineering_features"], "engineering-only feature payload")
    primary_table = pq.read_table(ENGINEERING_PRIMARY)
    reference_table = pq.read_table(ENGINEERING_REFERENCE)
    if not primary_table.equals(reference_table, check_metadata=True):
        raise AssertionError("Engineering-only primary/reference feature payloads differ")
    engineering = primary_table.to_pydict()
    p_eng, p_mask, p_diag = apply_policy_primary("ENGINEERING_2024_01_09", engineering, {}, base)
    r_eng, r_mask, r_diag = apply_policy_reference("ENGINEERING_2024_01_09", engineering, {}, base)
    if p_eng != engineering or r_eng != engineering or any(p_mask) or p_mask != r_mask or p_diag != r_diag:
        raise AssertionError("Engineering-only pass-through policy proof failed")
    integration = engineering_integration_proof()
    return {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_PRE_FREEZE_PROOF_V1_0",
        "status": "PASS_PRE_FREEZE_POLICY_PROOF",
        "completed_at_utc": utc_now(),
        "synthetic": {
            "buckets": 6,
            "expected_unavailable_mask": [False, True, True, False, False, False],
            "primary_reference_exact": True,
            "diagnostics": primary_diag,
        },
        "engineering_only": {
            "classification": "ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
            "rows": primary_table.num_rows,
            "primary": file_record(ENGINEERING_PRIMARY),
            "reference": file_record(ENGINEERING_REFERENCE),
            "zero_crossed_pass_through_exact": True,
            "classification_checksum": p_diag["classification_checksum"],
        },
        "engineering_integration": integration,
        "a1_nanosecond_reader_proof": file_record(DEFAULT_OLD_A1 / "pre_freeze_reader_proof.json"),
        "development_metadata_opened": False,
        "outcomes_opened": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "proof_receipt": None,
    }


def prove_and_freeze(old_m2: Path, old_r1: Path, old_a1: Path, output: Path) -> None:
    proof_path = output / "pre_freeze_policy_proof.json"
    if PROTOCOL_PATH.exists() or FREEZE_PATH.exists() or proof_path.exists():
        raise FileExistsError("R2 pre-freeze artifacts already exist")
    predecessor = verify_predecessors(old_m2, old_r1, old_a1)
    proof = pre_freeze_proof()
    proof["predecessors"] = predecessor
    proof["proof_receipt"] = canonical_hash({**proof, "proof_receipt": None})
    write_json_exclusive(proof_path, proof)
    protocol = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_PROTOCOL_V1_0",
        "status": "FROZEN_AFTER_POLICY_PROOF_BEFORE_DEVELOPMENT_METADATA",
        "frozen_at_utc": utc_now(),
        "authorization_sha256": hashlib.sha256(AUTHORIZATION.encode("utf-8")).hexdigest(),
        "predecessors": predecessor,
        "universal_policy": {
            "scope": "Every 2021-2024 development bucket and XAU-dependent context, not only known findings.",
            "terminal_crossed": "When the bucket-close state is two-sided crossed and its selected emission is F_LAST, latch UNAVAILABLE_TECHNICAL.",
            "latch_release": "First later, different source ordinal that is F_LAST, state-available, two-sided, unlocked, and uncrossed.",
            "book_fields_during_latch": "state_available=false; state identity, age, prices and depths null; locked/crossed false only in the disposition output while raw classification remains separately counted.",
            "ofi_during_latch": "quote OFI transitions become skipped, transition count and raw contribution become zero.",
            "mbo_flow_during_latch": "Retained because event-flow metadata does not use the invalid MBP book state.",
            "xau_missing": "Never impute. Current-bar and dependent-context quality is UNAVAILABLE_TECHNICAL; any event whose frozen +60-minute availability window contains a missing expected minute is UNAVAILABLE_TECHNICAL and excluded from support.",
            "preserve_original_classifications": True,
        },
        "formal_pass_gates": [
            "predecessor and source seals valid",
            "exact preserved 15 crossed and 3 unresolved findings",
            "raw terminal crossed count exactly 15 and post-policy crossed count zero",
            "zero invalid book-state values retained",
            "exact primary/reference source rows and anchors",
            "exact feature row identities, missingness classifications, column/null/complete checksums",
            "exact decision and event identities/checksums",
            "exact support counts and all 12 session-family Stage-1 tests support eligible",
            "no invalid state contributes to an eligible GC microstructure event",
            "one attempt, zero prohibited work",
        ],
        "attempt_budget": {"recertification_attempts": 1},
        "hard_kill_gate": "Any formal FAIL permanently terminates this microstructure branch without another engineering diagnostic.",
        "pass_disposition": "Advance only to separately authorized relationship discovery.",
        "pre_freeze_proof": file_record(proof_path),
    }
    write_json_exclusive(PROTOCOL_PATH, protocol)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_FREEZE_V1_0",
        "status": "SEALED_BEFORE_DEVELOPMENT_METADATA_REOPEN",
        "sealed_at_utc": utc_now(),
        "protocol": file_record(PROTOCOL_PATH),
        "implementation": file_record(Path(__file__)),
        "m2_implementation": file_record(Path(m2.__file__)),
        "a1_implementation": file_record(Path(a1.__file__)),
        "m2_final": file_record(old_m2 / "final_seal.json"),
        "m2r1_final": file_record(old_r1 / "final_seal.json"),
        "m2r1a1_final": file_record(old_a1 / "final_seal.json"),
        "m2r1_primary": file_record(old_r1 / "primary_diagnostic.json"),
        "pre_freeze_proof": file_record(proof_path),
        "recertification_attempt_limit": 1,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = canonical_hash({**freeze, "freeze_receipt": None})
    write_json_exclusive(FREEZE_PATH, freeze)
    print(json.dumps({"status": freeze["status"], "synthetic_policy": "PASS", "engineering_policy": "PASS", "development_metadata_opened": False}, sort_keys=True))


def verify_freeze(old_m2: Path, old_r1: Path, old_a1: Path, output: Path) -> dict[str, Any]:
    predecessor = verify_predecessors(old_m2, old_r1, old_a1)
    freeze = read_json(FREEZE_PATH)
    protocol = read_json(PROTOCOL_PATH)
    proof_path = output / "pre_freeze_policy_proof.json"
    proof = read_json(proof_path)
    if proof.get("status") != "PASS_PRE_FREEZE_POLICY_PROOF" or not receipt_valid(proof, "proof_receipt"):
        raise ValueError("R2 pre-freeze proof failed")
    checks = (
        ("protocol", PROTOCOL_PATH),
        ("implementation", Path(__file__)),
        ("m2_implementation", Path(m2.__file__)),
        ("a1_implementation", Path(a1.__file__)),
        ("m2_final", old_m2 / "final_seal.json"),
        ("m2r1_final", old_r1 / "final_seal.json"),
        ("m2r1a1_final", old_a1 / "final_seal.json"),
        ("m2r1_primary", old_r1 / "primary_diagnostic.json"),
        ("pre_freeze_proof", proof_path),
    )
    for name, path in checks:
        record = freeze.get(name)
        if not isinstance(record, dict) or record.get("sha256") != sha256_file(path) or int(record.get("bytes", -1)) != path.stat().st_size:
            raise ValueError(f"R2 freeze binding failed: {name}")
    if protocol.get("attempt_budget") != {"recertification_attempts": 1} or freeze.get("recertification_attempt_limit") != 1:
        raise ValueError("R2 one-attempt rule changed")
    if not receipt_valid(freeze, "freeze_receipt"):
        raise ValueError("R2 freeze receipt failed")
    return predecessor


def read_anchor_reference(path: Path, columns: Sequence[str], start_ns: int, day_start_ns: int) -> pa.Table:
    span = m2.BUCKET_NS
    metadata: pa.Table | None = None
    while start_ns - span >= day_start_ns - m2.BUCKET_NS:
        lower = max(day_start_ns, start_ns - span)
        metadata = a1.read_range_reference_ns(path, ("source_row_ordinal", "ts_recv"), lower, start_ns)
        if metadata.num_rows or lower == day_start_ns:
            break
        span *= 2
    if metadata is None or metadata.num_rows == 0:
        raise ValueError("Reference reader found no prior MBP-10 anchor")
    receives = metadata["ts_recv"].combine_chunks().cast(pa.int64()).to_numpy(zero_copy_only=False)
    ordinals = metadata["source_row_ordinal"].combine_chunks().to_numpy(zero_copy_only=False)
    order = np.lexsort((ordinals, receives))
    selected = int(order[-1])
    receive, ordinal = int(receives[selected]), int(ordinals[selected])
    candidates = a1.read_range_reference_ns(path, columns, receive, receive + 1)
    ordinal_values = candidates["source_row_ordinal"].combine_chunks().to_numpy(zero_copy_only=False)
    exact = candidates.filter(pa.array(ordinal_values == ordinal))
    if exact.num_rows != 1:
        raise ValueError("Reference anchor did not identify one row")
    return exact


def table_exact(left: pa.Table, right: pa.Table) -> bool:
    return left.combine_chunks().equals(right.combine_chunks(), check_metadata=True)


def xau_missing_keys(rows: Sequence[Mapping[str, Any]], sessions: Mapping[str, m2.XauSession]) -> list[tuple[str, str, str]]:
    allowed = m2._allowed_xau_missing()
    missing = []
    for row in rows:
        if int(row.get("expected_bucket_rows", 0)) == 0:
            continue
        opened = m2._parse(str(row["session_open_utc"]))
        expected = {opened + timedelta(minutes=index) for index in range(m2.EXPECTED_XAU_BARS_PER_SESSION)}
        session = sessions[str(row["row_id"])]
        for stamp in sorted(expected - session.coverage_opens):
            key = (str(row["session_date"]), str(row["session_code"]), stamp)
            if key not in allowed:
                missing.append((key[0], key[1], m2._iso(key[2])))
    return sorted(missing)


def xau_context_unavailable(
    row: Mapping[str, Any], session: m2.XauSession, decision: datetime
) -> dict[str, bool]:
    opened = m2._parse(str(row["session_open_utc"]))
    current = decision - timedelta(minutes=1)
    current_missing = current not in session.coverage_opens
    history_start = m2._history_start(row)
    history_expected = {history_start + timedelta(minutes=index) for index in range(max(0, int((decision - history_start).total_seconds() // 60)))}
    history_missing = not history_expected <= session.coverage_opens
    london_missing = False
    if row["session_code"] == "NEW_YORK":
        london_expected = {history_start + timedelta(minutes=index) for index in range(max(0, int((opened - history_start).total_seconds() // 60)))}
        london_missing = not london_expected <= session.coverage_opens
    return {"current": current_missing, "history": history_missing, "london": london_missing}


def decision_rows_r2(
    s5c: Any,
    base: Any,
    row: Mapping[str, Any],
    columns: Mapping[str, Sequence[Any]],
    micro: Mapping[datetime, Mapping[str, Any]],
    projection: Mapping[str, Any],
    history: Mapping[str, Any],
    session: m2.XauSession,
    implementation: str,
    unavailable_mask: Sequence[bool],
) -> tuple[list[dict[str, Any]], dict[datetime, dict[str, dict[str, Any]]]]:
    decisions, levels = m2._decision_rows(s5c, base, row, columns, micro, projection, history, session, implementation)
    for record in decisions:
        minute = int(record["decision_minute"])
        index = 900 + minute * 60 - 1
        decision = m2._parse(str(record["decision_at_utc"]))
        missing = xau_context_unavailable(row, session, decision)
        if missing["current"]:
            record["xau_bar_quality"] = UNAVAILABLE
            for name in ("ASIA_RANGE_LOCATION", "PRIOR_DAY_RANGE_LOCATION"):
                if record[f"{name}__state"] == "UNKNOWN":
                    record[f"{name}__quality"] = UNAVAILABLE
        if missing["history"] and record["ASIA_PREDECISION_BREAK_STATE__state"] == "UNKNOWN":
            record["ASIA_PREDECISION_BREAK_STATE__quality"] = UNAVAILABLE
        if missing["london"]:
            for name in ("LONDON_PRE_NEW_YORK_DIRECTION", "LONDON_ASIA_INTERACTION_PRE_NEW_YORK"):
                if record[f"{name}__state"] == "UNKNOWN":
                    record[f"{name}__quality"] = UNAVAILABLE
        if unavailable_mask[index]:
            record["gc_state_quality"] = UNAVAILABLE
    return decisions, levels


def future_quality_r2(row: Mapping[str, Any], session: m2.XauSession, decision: datetime) -> str:
    opened = m2._parse(str(row["session_open_utc"]))
    anchor_open = decision - timedelta(minutes=1)
    expected = {anchor_open + timedelta(minutes=index) for index in range(61)}
    expected = {stamp for stamp in expected if opened <= stamp < m2._parse(str(row["coverage_end_exclusive_utc"]))}
    return "ELIGIBLE" if expected <= session.coverage_opens else UNAVAILABLE


def preflight(
    paths: m2.Paths,
    old_m2: Path,
    old_r1: Path,
    old_a1: Path,
) -> dict[str, Any]:
    predecessor = verify_freeze(old_m2, old_r1, old_a1, paths.output)
    _s5c, _base, registry, acquisition = m2._verified_control(paths, verify_payload_hashes=False)
    gates = {
        "predecessor_and_freeze_bindings": True,
        "exact_80_sealed_requests": len(acquisition.get("requests", [])) == 80,
        "exact_376_registry_rows": len(registry.get("rows", [])) == 376,
        "exact_374_available_sessions": sum(int(row.get("expected_bucket_rows", 0)) > 0 for row in registry.get("rows", [])) == 374,
        "acquisition_manifest_binding": sha256_file(paths.acquisition) == EXPECTED["acquisition"],
        "xau_source_binding": sha256_file(paths.xau) == EXPECTED["xau"],
        "calendar_2025_2026_locked": True,
        "zero_acquisition_or_charge": True,
        "single_attempt_unconsumed": not (paths.output / "attempt_started.json").exists(),
    }
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_PREFLIGHT_V1_0",
        "status": "PASS_M2_R2_PRE_ATTEMPT_READINESS" if all(gates.values()) else "FAIL_M2_R2_PRE_ATTEMPT_READINESS",
        "completed_at_utc": utc_now(),
        "formal_gates": gates,
        "predecessors": predecessor,
        "development_rows_opened": False,
        "outcomes_opened": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
    }
    if record["status"] != "PASS_M2_R2_PRE_ATTEMPT_READINESS":
        raise ValueError("R2 pre-attempt readiness failed")
    write_json_exclusive(paths.output / "preflight.json", record)
    return record


def materialize(paths: m2.Paths) -> None:
    s5c, base, registry, acquisition = m2._verified_control(paths, verify_payload_hashes=False)
    contexts, history, _context_summary = m2._load_contexts(paths)
    rows = list(registry["rows"])
    sessions, xau_diagnostics = m2._load_xau(paths, rows)
    missing_keys = xau_missing_keys(rows, sessions)
    if len(missing_keys) != EXPECTED_UNRESOLVED_XAU:
        raise ValueError("The exact unresolved XAU population changed")
    request_by_id = m2._request_map(acquisition)
    feature_writers = {name: m2.FeatureWriters(paths.output, name, base.FEATURE_SCHEMA) for name in ("primary", "reference")}
    decision_writers = {name: m2.RowWriter(paths.output / f"{name}_minute_contexts.parquet", m2.DECISION_SCHEMA, m2.EXPECTED_DECISIONS_PER_SESSION) for name in ("primary", "reference")}
    all_events: dict[str, list[dict[str, str]]] = {"primary": [], "reference": []}
    aggregate = {"primary": Counter(), "reference": Counter()}
    policy_rows = {"primary": [], "reference": []}
    source_reader_mismatches = decision_mismatches = event_mismatches = 0
    available = 0
    original_future_quality = m2._future_timestamp_quality
    m2._future_timestamp_quality = future_quality_r2
    try:
        for row in rows:
            if int(row["expected_bucket_rows"]) == 0:
                aggregate["primary"]["documented_unavailable_sessions"] += 1
                aggregate["reference"]["documented_unavailable_sessions"] += 1
                continue
            available += 1
            mbo_request = request_by_id[str(row["mbo_request_id"])]
            mbp_request = request_by_id[str(row["mbp10_request_id"])]
            mbo_path = Path(str(mbo_request["normalization"]["normalized_payload"]["path"]))
            mbp_path = Path(str(mbp_request["normalization"]["normalized_payload"]["path"]))
            start, end = int(row["window_start_inclusive_ns"]), int(row["window_end_exclusive_ns"])
            p_mbo = m2._source_table(mbo_path, base.MBO_COLUMNS, start, end, s5c)
            p_mbp = m2._source_table(mbp_path, base.MBP_COLUMNS, start, end, s5c)
            r_mbo = a1.read_range_reference_ns(mbo_path, base.MBO_COLUMNS, start, end)
            r_mbp = a1.read_range_reference_ns(mbp_path, base.MBP_COLUMNS, start, end)
            p_anchor = s5c._read_exact_anchor(mbp_path, base.MBP_COLUMNS, start, int(row["utc_day_start_ns"]))
            r_anchor = read_anchor_reference(mbp_path, base.MBP_COLUMNS, start, int(row["utc_day_start_ns"]))
            if not (table_exact(p_mbo, r_mbo) and table_exact(p_mbp, r_mbp) and table_exact(p_anchor, r_anchor)):
                source_reader_mismatches += 1
                raise ValueError("Primary/reference source reader mismatch")
            p_mbo_arrays = s5c._table_arrays(p_mbo, base.MBO_COLUMNS)
            p_mbp_arrays = s5c._table_arrays(p_mbp, base.MBP_COLUMNS)
            r_mbo_arrays = s5c._table_arrays(r_mbo, base.MBO_COLUMNS)
            r_mbp_arrays = s5c._table_arrays(r_mbp, base.MBP_COLUMNS)
            s5c._assert_source_order(p_mbo_arrays, "MBO-primary", str(row["row_id"]))
            s5c._assert_source_order(p_mbp_arrays, "MBP-primary", str(row["row_id"]))
            s5c._assert_source_order(r_mbo_arrays, "MBO-reference", str(row["row_id"]))
            s5c._assert_source_order(r_mbp_arrays, "MBP-reference", str(row["row_id"]))
            s5c.WINDOW_BUCKETS = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
            p_raw, p_technical = s5c._primary_window_features(row, p_mbo_arrays, p_mbp_arrays, p_anchor, base)
            r_raw, r_technical = s5c._reference_window_features(row, r_mbo_arrays, r_mbp_arrays, r_anchor, base)
            p_columns, p_mask, p_policy = apply_policy_primary(str(row["row_id"]), p_raw, flags_by_ordinal(p_mbp_arrays, p_anchor), base)
            r_columns, r_mask, r_policy = apply_policy_reference(str(row["row_id"]), r_raw, flags_by_ordinal(r_mbp_arrays, r_anchor), base)
            if p_columns != r_columns or p_mask != r_mask or p_policy != r_policy:
                raise ValueError("Primary/reference universal disposition mismatch")
            for technical, policy in ((p_technical, p_policy), (r_technical, r_policy)):
                technical["raw_state_available_bucket_closes"] += int(technical.get("state_available_bucket_closes", 0))
                technical["state_available_bucket_closes"] = int(policy["post_policy_state_available_buckets"])
                technical["raw_terminal_crossed_bucket_closes"] += int(policy["raw_terminal_crossed_bucket_closes"])
                technical["technical_unavailable_bucket_closes"] += int(policy["technical_unavailable_bucket_closes"])
                technical["technical_unavailable_ofi_buckets"] += int(policy["technical_unavailable_ofi_buckets"])
                technical["unavailability_latch_starts"] += int(policy["unavailability_latch_starts"])
                technical["valid_recovery_boundaries"] += int(policy["valid_recovery_boundaries"])
                technical["crossed_non_f_last_failures"] += int(policy["crossed_non_f_last_failures"])
                technical["invalid_state_values_retained"] += int(policy["invalid_state_values_retained"])
                technical["continuous_crossed_bucket_closes"] = int(policy["post_policy_crossed_bucket_closes"])
            feature_writers["primary"].write(str(row["session_code"]), p_columns, base.FEATURE_SCHEMA)
            feature_writers["reference"].write(str(row["session_code"]), r_columns, base.FEATURE_SCHEMA)
            p_micro = m2._minute_micro_states(s5c, base, p_columns, "primary")
            r_micro = m2._minute_micro_states(s5c, base, r_columns, "reference")
            context = contexts[str(row["source_step5c_row_id"])]
            session = sessions[str(row["row_id"])]
            p_decisions, p_levels = decision_rows_r2(s5c, base, row, p_columns, p_micro, context, history, session, "primary", p_mask)
            r_decisions, r_levels = decision_rows_r2(s5c, base, row, r_columns, r_micro, context, history, session, "reference", r_mask)
            decision_writers["primary"].write(p_decisions)
            decision_writers["reference"].write(r_decisions)
            if m2._canonical(p_decisions) != m2._canonical(r_decisions):
                decision_mismatches += 1
            p_events = m2._detect_events(row, session, p_decisions, p_levels, p_micro, "primary")
            r_events = m2._detect_events(row, session, r_decisions, r_levels, r_micro, "reference")
            all_events["primary"].extend(p_events)
            all_events["reference"].extend(r_events)
            if m2._canonical(p_events) != m2._canonical(r_events):
                event_mismatches += 1
            aggregate["primary"].update(p_technical)
            aggregate["reference"].update(r_technical)
            policy_rows["primary"].append({"row_id": row["row_id"], **p_policy})
            policy_rows["reference"].append({"row_id": row["row_id"], **r_policy})
            if available % 25 == 0 or available == m2.EXPECTED_AVAILABLE_SESSIONS:
                print(json.dumps({"stage": "M2_R2_SESSION_PROGRESS", "completed": available, "total": m2.EXPECTED_AVAILABLE_SESSIONS, "outcomes": False}), flush=True)
    finally:
        m2._future_timestamp_quality = original_future_quality
    for writer in feature_writers.values():
        writer.close()
    for writer in decision_writers.values():
        writer.close()
    if any(writer.rows != m2.EXPECTED_DECISION_ROWS for writer in decision_writers.values()):
        raise ValueError("R2 decision row count changed")
    event_files: dict[str, Path] = {}
    support_files: dict[str, Path] = {}
    for implementation in ("primary", "reference"):
        events = sorted(all_events[implementation], key=lambda item: (item["session_date"], item["session_code"], item["decision_at_utc"], item["event_family"], item["directional_prior"], item["event_id"]))
        event_path = paths.output / f"{implementation}_events.parquet"
        pq.write_table(pa.Table.from_pylist(events, schema=m2.EVENT_SCHEMA), event_path, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=max(1, len(events)))
        support = m2._support_report(events, implementation)
        support_path = paths.output / f"{implementation}_support_counts.json"
        write_json_exclusive(support_path, support)
        event_files[implementation] = event_path
        support_files[implementation] = support_path
    diagnostics = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_DIAGNOSTICS_V1_0",
        "xau": xau_diagnostics,
        "unresolved_xau_keys_count": len(missing_keys),
        "unresolved_xau_keys_checksum": canonical_hash(missing_keys),
        "available_sessions": available,
        "source_reader_mismatch_sessions": source_reader_mismatches,
        "decision_reproduction_mismatch_sessions": decision_mismatches,
        "event_reproduction_mismatch_sessions": event_mismatches,
        "primary_technical": dict(sorted(aggregate["primary"].items())),
        "reference_technical": dict(sorted(aggregate["reference"].items())),
        "primary_missingness_checksum": canonical_hash(policy_rows["primary"]),
        "reference_missingness_checksum": canonical_hash(policy_rows["reference"]),
        "policy_session_rows": len(policy_rows["primary"]),
        "market_or_feature_values_reported": False,
        "outcomes_opened": False,
    }
    write_json_exclusive(paths.output / "technical_diagnostics.json", diagnostics)
    for implementation in ("primary", "reference"):
        summary = {
            "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_RUN_V1_0",
            "implementation": implementation,
            "status": "COMPLETE_PENDING_R2_SEAL",
            "completed_at_utc": utc_now(),
            "feature_files": {session: file_record(feature_writers[implementation].final[session]) for session in ("LONDON", "NEW_YORK")},
            "decision_file": file_record(decision_writers[implementation].final),
            "event_file": file_record(event_files[implementation]),
            "support_file": file_record(support_files[implementation]),
            "feature_rows": m2.EXPECTED_FEATURE_ROWS,
            "decision_rows": m2.EXPECTED_DECISION_ROWS,
            "event_rows": len(all_events[implementation]),
            "development_outcomes_opened_or_joined": False,
            "relationships_hit_rates_candidates_execution_trades_or_pnl_calculated": False,
            "year_2025_or_2026_accessed": False,
            "data_acquired": False,
            "charge_incurred_usd": 0.0,
        }
        write_json_exclusive(paths.output / f"{implementation}_summary.json", summary)


def normalized_support(value: Mapping[str, Any]) -> dict[str, Any]:
    output = dict(value)
    output.pop("implementation", None)
    output.pop("support_receipt", None)
    return output


def seal_completed(paths: m2.Paths, predecessor: Mapping[str, Any]) -> None:
    s5c, base, _registry, _acquisition = m2._verified_control(paths, verify_payload_hashes=False)
    preflight_record = read_json(paths.output / "preflight.json")
    diagnostics = read_json(paths.output / "technical_diagnostics.json")
    summaries = {name: read_json(paths.output / f"{name}_summary.json") for name in ("primary", "reference")}
    supports = {name: read_json(paths.output / f"{name}_support_counts.json") for name in ("primary", "reference")}
    feature_rows_per_session = m2.EXPECTED_FEATURE_ROWS // 2
    feature_fingerprints: dict[str, dict[str, Any]] = {"primary": {}, "reference": {}}
    for implementation in ("primary", "reference"):
        for session in ("LONDON", "NEW_YORK"):
            path = Path(summaries[implementation]["feature_files"][session]["path"])
            feature_fingerprints[implementation][session] = s5c._parquet_hashes(path, base.FEATURE_SCHEMA, feature_rows_per_session, s5c._schema_hash(base.FEATURE_SCHEMA))
    decision_fingerprints = {
        name: s5c._parquet_hashes(Path(summaries[name]["decision_file"]["path"]), m2.DECISION_SCHEMA, m2.EXPECTED_DECISION_ROWS, s5c._schema_hash(m2.DECISION_SCHEMA))
        for name in ("primary", "reference")
    }
    event_fingerprints = {
        name: s5c._parquet_hashes(Path(summaries[name]["event_file"]["path"]), m2.EVENT_SCHEMA, int(summaries[name]["event_rows"]), s5c._schema_hash(m2.EVENT_SCHEMA))
        for name in ("primary", "reference")
    }
    feature_reproduction = all(
        feature_fingerprints["primary"][session] == feature_fingerprints["reference"][session]
        and summaries["primary"]["feature_files"][session]["sha256"] == summaries["reference"]["feature_files"][session]["sha256"]
        for session in ("LONDON", "NEW_YORK")
    )
    decision_reproduction = decision_fingerprints["primary"] == decision_fingerprints["reference"] and summaries["primary"]["decision_file"]["sha256"] == summaries["reference"]["decision_file"]["sha256"]
    event_reproduction = event_fingerprints["primary"] == event_fingerprints["reference"] and summaries["primary"]["event_file"]["sha256"] == summaries["reference"]["event_file"]["sha256"]
    support_reproduction = normalized_support(supports["primary"]) == normalized_support(supports["reference"])
    technical = diagnostics["primary_technical"]
    technical_equal = technical == diagnostics["reference_technical"]
    missingness_equal = diagnostics["primary_missingness_checksum"] == diagnostics["reference_missingness_checksum"]
    primary_events = pq.read_table(Path(summaries["primary"]["event_file"]["path"]), columns=["event_family", "source_domain", "decision_id", "quality_state"]).to_pylist()
    decisions_table = pq.read_table(Path(summaries["primary"]["decision_file"]["path"]), columns=["decision_id", "gc_state_quality"])
    decision_quality = dict(zip(decisions_table["decision_id"].to_pylist(), decisions_table["gc_state_quality"].to_pylist(), strict=True))
    invalid_eligible_micro = sum(
        event["quality_state"] == "ELIGIBLE"
        and event["source_domain"] == "GC_MICROSTRUCTURE"
        and decision_quality.get(event["decision_id"]) != VALID_GC
        for event in primary_events
    )
    stage1_all = supports["primary"]["stage1_tests"] == 12 and supports["primary"]["stage1_support_eligible"] == 12 and all(item["support_status"] == "SUPPORT_ELIGIBLE" for item in supports["primary"]["stage1"])
    gates = {
        "preflight_and_predecessor_seals": preflight_record.get("status") == "PASS_M2_R2_PRE_ATTEMPT_READINESS" and all(preflight_record.get("formal_gates", {}).values()),
        "preserved_15_crossed_and_3_unresolved_classifications": predecessor["preserved_terminal_crossed_findings"] == 15 and predecessor["preserved_unresolved_xau_findings"] == 3,
        "exact_three_unresolved_xau_keys": diagnostics["unresolved_xau_keys_count"] == 3,
        "xau_missingness_and_source_scope_exact": (
            int(diagnostics["xau"].get("unexpected_missing_timestamps", -1)) == 3
            and int(diagnostics["xau"].get("duplicate_timestamps", -1)) == 0
            and int(diagnostics["xau"].get("malformed_or_late_predecision_rows", -1)) == 0
            and diagnostics["xau"].get("first_2025_or_2026_line_deserialized") is False
        ),
        "raw_terminal_crossed_count_exactly_15": int(technical.get("raw_terminal_crossed_bucket_closes", -1)) == 15,
        "post_policy_crossed_count_zero": int(technical.get("continuous_crossed_bucket_closes", -1)) == 0,
        "state_availability_drop_matches_unavailable_latch": (
            int(technical.get("raw_state_available_bucket_closes", -1))
            - int(technical.get("state_available_bucket_closes", -1))
            == int(technical.get("technical_unavailable_bucket_closes", -2))
        ),
        "zero_crossed_non_f_last_failures": int(technical.get("crossed_non_f_last_failures", -1)) == 0,
        "zero_invalid_state_values_retained": int(technical.get("invalid_state_values_retained", -1)) == 0,
        "primary_reference_source_reader_exact": diagnostics["source_reader_mismatch_sessions"] == 0,
        "primary_reference_technical_exact": technical_equal,
        "primary_reference_missingness_exact": missingness_equal,
        "primary_reference_feature_rows_and_checksums_exact": feature_reproduction,
        "primary_reference_decision_rows_and_checksums_exact": decision_reproduction and diagnostics["decision_reproduction_mismatch_sessions"] == 0,
        "primary_reference_event_identities_and_checksums_exact": event_reproduction and diagnostics["event_reproduction_mismatch_sessions"] == 0,
        "primary_reference_support_counts_exact": support_reproduction,
        "all_frozen_session_event_families_retain_support": stage1_all,
        "no_invalid_state_contributed_to_eligible_micro_event": invalid_eligible_micro == 0,
        "one_recertification_attempt": read_json(paths.output / "attempt_started.json").get("attempt") == 1,
        "no_outcomes_relationships_hit_rates_candidates_execution_trades_or_pnl": True,
        "no_2025_or_2026_access": True,
        "no_acquisition_or_charge": True,
    }
    if not gates["all_frozen_session_event_families_retain_support"]:
        status = "FAIL_M2_R2_SUPPORT_FLOOR_BRANCH_TERMINATED"
    elif not all(gates.values()):
        status = "FAIL_M2_R2_RECERTIFICATION_BRANCH_TERMINATED"
    else:
        status = "PASS_M2_R2_OUTCOME_BLIND_RECERTIFICATION"
    verdict: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_VERDICT_V1_0",
        "status": status,
        "formal_pass": status == "PASS_M2_R2_OUTCOME_BLIND_RECERTIFICATION",
        "completed_at_utc": utc_now(),
        "formal_gates": gates,
        "preserved_predecessors": predecessor,
        "technical_counts": {
            "feature_rows": m2.EXPECTED_FEATURE_ROWS,
            "decision_rows": m2.EXPECTED_DECISION_ROWS,
            "event_rows": summaries["primary"]["event_rows"],
            "raw_terminal_crossed_bucket_closes": technical["raw_terminal_crossed_bucket_closes"],
            "technical_unavailable_bucket_closes": technical["technical_unavailable_bucket_closes"],
            "valid_recovery_boundaries": technical["valid_recovery_boundaries"],
            "unresolved_xau_timestamps": diagnostics["unresolved_xau_keys_count"],
            "stage1_tests": supports["primary"]["stage1_tests"],
            "stage1_support_eligible": supports["primary"]["stage1_support_eligible"],
            "stage2_tests": supports["primary"]["stage2_tests"],
            "stage2_support_eligible": supports["primary"]["stage2_support_eligible"],
            "invalid_eligible_micro_events": invalid_eligible_micro,
        },
        "development_outcomes_opened_or_joined": False,
        "relationships_hit_rates_effects_candidates_or_rankings_calculated": False,
        "execution_trades_pnl_r_multiples_or_returns_calculated": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": "PASS advances only to separately authorized relationship discovery. Any FAIL permanently terminates the current microstructure branch without another engineering diagnostic.",
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    write_json_exclusive(paths.output / "verdict.json", verdict)
    report = "\n".join([
        "# GC Session Trigger Edge Discovery V1 — Milestone 2-R2",
        "",
        f"Formal status: `{status}`",
        "",
        "This was the single final outcome-blind technical recertification. The prior M2 and M2-R1 failures and A1 PASS remain unchanged.",
        "",
        f"Raw terminal crossed bucket closes preserved: {technical['raw_terminal_crossed_bucket_closes']}.",
        f"Technically unavailable bucket closes after universal disposition: {technical['technical_unavailable_bucket_closes']}.",
        f"Unresolved XAUUSD timestamps preserved: {diagnostics['unresolved_xau_keys_count']}.",
        f"Stage-1 support-eligible session/family tests: {supports['primary']['stage1_support_eligible']} of {supports['primary']['stage1_tests']}.",
        "",
        "No outcomes, relationships, hit rates, candidates, 2025/2026 values, execution, trades, or PnL were accessed or calculated.",
        "",
        verdict["completion_policy"],
    ])
    write_text_exclusive(paths.output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_2_R2.md", report)
    artifact_names = [
        "pre_freeze_policy_proof.json", "preflight.json", "attempt_started.json", "technical_diagnostics.json",
        "primary_summary.json", "reference_summary.json", "primary_support_counts.json", "reference_support_counts.json",
        "primary_london_one_second_features.parquet", "primary_new_york_one_second_features.parquet",
        "reference_london_one_second_features.parquet", "reference_new_york_one_second_features.parquet",
        "primary_minute_contexts.parquet", "reference_minute_contexts.parquet",
        "primary_events.parquet", "reference_events.parquet", "verdict.json", "GC_SESSION_TRIGGER_EDGE_MILESTONE_2_R2.md",
    ]
    manifest: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_MANIFEST_V1_0",
        "status": status,
        "sealed_at_utc": utc_now(),
        "protocol": file_record(PROTOCOL_PATH),
        "freeze": file_record(FREEZE_PATH),
        "implementation": file_record(Path(__file__)),
        "artifacts": [file_record(paths.output / name) for name in artifact_names],
        "feature_fingerprints": feature_fingerprints,
        "decision_fingerprints": decision_fingerprints,
        "event_fingerprints": event_fingerprints,
        "verdict_receipt": verdict["verdict_receipt"],
        "outcomes_or_prohibited_work": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    manifest["preserved_final_seal_receipts"] = {
        "m2": predecessor["m2_final_seal_receipt"],
        "m2r1": predecessor["m2r1_final_seal_receipt"],
        "m2r1a1": predecessor["m2r1a1_final_seal_receipt"],
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    write_json_exclusive(paths.output / "manifest.json", manifest)
    final: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_FINAL_SEAL_V1_0",
        "status": status,
        "sealed_at_utc": utc_now(),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "verdict_sha256": sha256_file(paths.output / "verdict.json"),
        "manifest_sha256": sha256_file(paths.output / "manifest.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_exclusive(paths.output / "final_seal.json", final)
    print(json.dumps({"status": status, "event_rows": summaries["primary"]["event_rows"], "stage1_support": f"{supports['primary']['stage1_support_eligible']}/12", "outcomes": False}, sort_keys=True))


def seal_execution_failure(paths: m2.Paths, predecessor: Mapping[str, Any], error: Exception) -> None:
    failure = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_EXECUTION_FAILURE_V1_0",
        "status": "FAIL_M2_R2_EXECUTION_BRANCH_TERMINATED",
        "failed_at_utc": utc_now(),
        "error_type": type(error).__name__,
        "error_sha256": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
        "outcomes_or_market_values_reported": False,
    }
    write_json_exclusive(paths.output / "execution_failure.json", failure)
    verdict: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_VERDICT_V1_0",
        "status": failure["status"],
        "formal_pass": False,
        "completed_at_utc": utc_now(),
        "preserved_predecessors": predecessor,
        "attempts": 1,
        "branch_disposition": "PERMANENTLY_TERMINATED_NO_FURTHER_ENGINEERING_DIAGNOSTIC",
        "development_outcomes_opened_or_joined": False,
        "relationships_hit_rates_candidates_execution_trades_or_pnl_calculated": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    write_json_exclusive(paths.output / "verdict.json", verdict)
    artifacts = [path for path in (paths.output / "pre_freeze_policy_proof.json", paths.output / "preflight.json", paths.output / "attempt_started.json", paths.output / "execution_failure.json", paths.output / "verdict.json") if path.is_file()]
    manifest: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_FAILURE_MANIFEST_V1_0",
        "status": failure["status"],
        "sealed_at_utc": utc_now(),
        "protocol": file_record(PROTOCOL_PATH),
        "freeze": file_record(FREEZE_PATH),
        "implementation": file_record(Path(__file__)),
        "artifacts": [file_record(path) for path in artifacts],
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    write_json_exclusive(paths.output / "manifest.json", manifest)
    final: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_FINAL_SEAL_V1_0",
        "status": failure["status"],
        "sealed_at_utc": utc_now(),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "verdict_sha256": sha256_file(paths.output / "verdict.json"),
        "manifest_sha256": sha256_file(paths.output / "manifest.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_exclusive(paths.output / "final_seal.json", final)
    print(json.dumps({"status": failure["status"], "error_type": failure["error_type"], "outcomes": False}, sort_keys=True))


def execute_once(paths: m2.Paths, old_m2: Path, old_r1: Path, old_a1: Path) -> None:
    if (paths.output / "attempt_started.json").exists():
        raise RuntimeError("The single R2 recertification attempt has already been consumed")
    preflight_record = preflight(paths, old_m2, old_r1, old_a1)
    predecessor = preflight_record["predecessors"]
    write_json_exclusive(paths.output / "attempt_started.json", {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R2_ATTEMPT_V1_0",
        "attempt": 1,
        "maximum_attempts": 1,
        "started_at_utc": utc_now(),
        "outcomes_opened": False,
    })
    try:
        materialize(paths)
        seal_completed(paths, predecessor)
    except Exception as error:
        seal_execution_failure(paths, predecessor, error)


def verify_final(paths: m2.Paths, old_m2: Path, old_r1: Path, old_a1: Path) -> None:
    verify_freeze(old_m2, old_r1, old_a1, paths.output)
    verdict = read_json(paths.output / "verdict.json")
    manifest = read_json(paths.output / "manifest.json")
    final = read_json(paths.output / "final_seal.json")
    for value, field in ((verdict, "verdict_receipt"), (manifest, "manifest_receipt"), (final, "final_seal_receipt")):
        if not receipt_valid(value, field):
            raise ValueError(f"R2 final receipt failed: {field}")
    if final.get("freeze_sha256") != sha256_file(FREEZE_PATH) or final.get("verdict_sha256") != sha256_file(paths.output / "verdict.json") or final.get("manifest_sha256") != sha256_file(paths.output / "manifest.json"):
        raise ValueError("R2 final seal bindings failed")
    for record in manifest.get("artifacts", []):
        path = Path(str(record["path"]))
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise ValueError(f"R2 artifact binding failed: {path}")
    print(json.dumps({"status": final["status"], "final_seal_receipt": final["final_seal_receipt"], "verified_artifacts": len(manifest["artifacts"])}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prove-freeze", "execute-once", "verify"))
    parser.add_argument("--old-m2", default=str(DEFAULT_OLD_M2))
    parser.add_argument("--old-r1", default=str(DEFAULT_OLD_R1))
    parser.add_argument("--old-a1", default=str(DEFAULT_OLD_A1))
    parser.add_argument("--acquisition", default=str(m2.DEFAULT_ACQUISITION))
    parser.add_argument("--step5b2", default=str(m2.DEFAULT_STEP5B2))
    parser.add_argument("--context", default=str(m2.DEFAULT_CONTEXT))
    parser.add_argument("--xau", default=str(m2.DEFAULT_XAU))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output)
    old_m2, old_r1, old_a1 = Path(args.old_m2), Path(args.old_r1), Path(args.old_a1)
    paths = m2.Paths(Path(args.acquisition), Path(args.step5b2), Path(args.context), Path(args.xau), output)
    if args.action == "prove-freeze":
        prove_and_freeze(old_m2, old_r1, old_a1, output)
    elif args.action == "execute-once":
        execute_once(paths, old_m2, old_r1, old_a1)
    else:
        verify_final(paths, old_m2, old_r1, old_a1)


if __name__ == "__main__":
    main()
