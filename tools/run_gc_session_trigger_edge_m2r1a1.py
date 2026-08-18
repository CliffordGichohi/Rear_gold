#!/usr/bin/env python3
"""Run the single-attempt Milestone 2-R1-A1 reproduction correction.

This module deliberately imports the sealed R1 implementation instead of
modifying it.  The only diagnostic implementation change is the explicit
nanosecond type supplied while converting Parquet ``ts_recv`` statistics.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

import diagnose_gc_session_trigger_edge_m2r1 as r1


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts"

PROTOCOL_PATH = MANIFESTS / "gc_session_trigger_edge_m2r1a1_protocol_v01.json"
FREEZE_PATH = MANIFESTS / "gc_session_trigger_edge_m2r1a1_freeze_v01.json"
DEFAULT_OLD_R1 = ARTIFACTS / "gc_session_trigger_edge_m2r1_v01"
DEFAULT_OUTPUT = ARTIFACTS / "gc_session_trigger_edge_m2r1a1_v01"

ENGINEERING_MBO_SEAL = ROOT / "data/raw/databento_gc_mbo_engineering_pilot/GLBX-20260730-WB9AXCVFET/normalized/seal_v02.json"
ENGINEERING_MBP_SEAL = ROOT / "data/raw/databento_gc_mbp10_engineering_benchmark/GLBX-20260731-UJHWEDQUSX/normalized/seal.json"

EXPECTED = {
    "r1_engine": "43302e6952fc4bd8924e4ce1b86861def9bbc90b38f78f33475907384713ef8b",
    "r1_primary": "82444ce02a05de75d276eb2e773b68b6f8dfd97a659277c557ecd51a672cd91d",
    "r1_reference": "bd61734628e6bc5f30435940f7a51f9c43c7a816b25fcd6f701237ab24397ebd",
    "r1_reproduction": "61a82091213ef334f8d6bfb6b241f739cc0de3b005a1ea82ff748f96f0cf6f12",
    "r1_verdict": "d860f6515562170b9ff6ce832d49c660d356ed45789969b27771ff9def83154e",
    "r1_manifest": "d1554b62c17343953867183e8f75878b6d482ca01e3990a5073f5c7df103a483",
    "r1_final": "07a4ee79e8bf75a699bf4fb34a546da7ccde8e1992d8d0d9123f24ed575db80f",
    "r1_final_receipt": "6d728c21f52cb189d82db2b20d8acd402bb8cf9d44ca142064b708e5d1865df2",
    "engineering_mbo": "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3",
    "engineering_mbp": "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4",
}

AUTHORIZATION = """Proceed to GC Session Trigger Edge Discovery V1 Milestone 2-R1-A1 under a single narrow reproduction-correction amendment. Preserve the sealed Milestone 2 and Milestone 2-R1 failures and every prior artifact and seal. Before freezing the amended implementation, prove the reference range reader on synthetic nanosecond timestamp boundary tests and existing engineering-only metadata by requiring exact [start, end) equality with the primary reader. Change only the reference Parquet timestamp-statistics conversion from its inferred unit to nanoseconds. Freeze the amended implementation before reopening development metadata. Reuse the sealed primary R1 diagnostic unchanged and rerun only the reference diagnostic against the identical sealed sources. Require exact agreement on all 18 findings, classifications, evidence and checksums. Permit one attempt only. Do not repair data, alter classifications, open outcomes, inspect 2025/2026, acquire data, or calculate relationships, trades or PnL. Seal an honest PASS or FAIL and stop."""

METADATA_COLUMNS = (
    "source_row_ordinal", "ts_recv", "ts_event", "publisher_id",
    "instrument_id", "sequence", "action", "side", "flags",
)


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
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


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def file_record(path: Path) -> dict[str, Any]:
    return {"path": str(path), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def receipt_valid(value: Mapping[str, Any], field: str) -> bool:
    return value.get(field) == canonical_hash({**value, field: None})


def verify_old_r1(old_r1: Path) -> dict[str, Any]:
    bindings = {
        "primary_diagnostic.json": EXPECTED["r1_primary"],
        "reference_diagnostic.json": EXPECTED["r1_reference"],
        "reproduction_check.json": EXPECTED["r1_reproduction"],
        "verdict.json": EXPECTED["r1_verdict"],
        "manifest.json": EXPECTED["r1_manifest"],
        "final_seal.json": EXPECTED["r1_final"],
    }
    if sha256_file(Path(r1.__file__)) != EXPECTED["r1_engine"]:
        raise ValueError("The sealed R1 implementation changed")
    for name, expected in bindings.items():
        path = old_r1 / name
        if not path.is_file() or sha256_file(path) != expected:
            raise ValueError(f"The sealed R1 artifact changed: {name}")
    verdict = read_json(old_r1 / "verdict.json")
    final = read_json(old_r1 / "final_seal.json")
    if verdict.get("status") != "FAIL_DIAGNOSTIC_REPRODUCTION":
        raise ValueError("R1 failure was not preserved")
    if final.get("status") != "FAIL_DIAGNOSTIC_REPRODUCTION" or final.get("final_seal_receipt") != EXPECTED["r1_final_receipt"]:
        raise ValueError("R1 final failure seal was not preserved")
    if not receipt_valid(final, "final_seal_receipt"):
        raise ValueError("R1 final receipt failed canonical verification")
    primary = read_json(old_r1 / "primary_diagnostic.json")
    findings = [*primary.get("xau_findings", []), *primary.get("crossed_bucket_findings", [])]
    if len(findings) != 18 or not receipt_valid(primary, "result_receipt"):
        raise ValueError("The sealed R1 primary diagnostic is not the exact 18-finding source")
    return {
        "m2_status_preserved": "FAIL_FULL_SESSION_TIMESTAMP_COVERAGE",
        "m2r1_status_preserved": final["status"],
        "m2r1_final_seal_receipt": final["final_seal_receipt"],
        "sealed_primary_sha256": EXPECTED["r1_primary"],
        "sealed_primary_findings": len(findings),
    }


def _statistics_ns(value: Any, timestamp_type: pa.DataType) -> int:
    """Convert a Parquet timestamp statistic using its explicit ns type."""
    return int(pa.scalar(value, type=timestamp_type).cast(pa.int64()).as_py())


def read_range_reference_ns(path: Path, columns: Sequence[str], start: int, end: int) -> pa.Table:
    """The sealed R1 reader with only its statistics conversion corrected."""
    with pq.ParquetFile(path) as parquet:
        ts_index = parquet.schema_arrow.get_field_index("ts_recv")
        timestamp_type = parquet.schema_arrow.field(ts_index).type
        tables: list[pa.Table] = []
        for group in range(parquet.num_row_groups):
            column_meta = parquet.metadata.row_group(group).column(ts_index)
            stats = column_meta.statistics
            if stats is not None and stats.has_min_max:
                minimum = _statistics_ns(stats.min, timestamp_type)
                maximum = _statistics_ns(stats.max, timestamp_type)
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


def table_checksum(table: pa.Table) -> str:
    digest = hashlib.sha256()
    for name in table.column_names:
        digest.update(name.encode("utf-8"))
        digest.update(str(table.schema.field(name).type).encode("utf-8"))
        for chunk in table[name].chunks:
            for buffer in chunk.buffers():
                if buffer is not None:
                    digest.update(buffer.to_pybytes())
    return digest.hexdigest()


def assert_exact_range(path: Path, columns: Sequence[str], start: int, end: int) -> dict[str, Any]:
    primary = r1._read_range_primary(path, columns, start, end)
    reference = read_range_reference_ns(path, columns, start, end)
    if not primary.equals(reference, check_metadata=True):
        raise AssertionError(f"Primary/reference range mismatch for [{start}, {end})")
    receives = reference["ts_recv"].combine_chunks().cast(pa.int64()).to_pylist()
    if any(int(value) < start or int(value) >= end for value in receives):
        raise AssertionError("Reference reader violated [start, end)")
    return {
        "start_ns": start,
        "end_ns": end,
        "rows": reference.num_rows,
        "checksum": table_checksum(reference),
        "exact_primary_reference_equality": True,
        "inclusive_start_exclusive_end": True,
    }


def synthetic_proof() -> dict[str, Any]:
    base_ns = 1_704_758_400_000_000_000
    offsets = [0, 1, 999, 1_000, 1_001, 1_999, 2_000, 2_001, 9_999, 10_000]
    with tempfile.TemporaryDirectory(prefix="gc_m2r1a1_") as directory:
        path = Path(directory) / "synthetic_ns.parquet"
        table = pa.table({
            "source_row_ordinal": pa.array(range(len(offsets)), type=pa.int64()),
            "ts_recv": pa.array([base_ns + value for value in offsets], type=pa.timestamp("ns", tz="UTC")),
        })
        pq.write_table(table, path, row_group_size=3, compression="zstd", write_statistics=True)
        with pq.ParquetFile(path) as parquet:
            ts_index = parquet.schema_arrow.get_field_index("ts_recv")
            first_stats = parquet.metadata.row_group(0).column(ts_index).statistics
            inferred_unit = str(pa.scalar(first_stats.min).type)
            explicit_unit = str(pa.scalar(first_stats.min, type=parquet.schema_arrow.field(ts_index).type).type)
        ranges = [
            (base_ns, base_ns + 1),
            (base_ns + 1, base_ns + 2),
            (base_ns + 999, base_ns + 1_000),
            (base_ns + 1_000, base_ns + 1_001),
            (base_ns + 1_001, base_ns + 2_000),
            (base_ns + 2_000, base_ns + 2_001),
            (base_ns + 2_001, base_ns + 10_000),
            (base_ns + 10_000, base_ns + 10_001),
            (base_ns - 1, base_ns),
            (base_ns + 10_001, base_ns + 20_000),
            (base_ns, base_ns + 20_000),
        ]
        tests = [assert_exact_range(path, ("source_row_ordinal", "ts_recv"), start, end) for start, end in ranges]
    return {
        "status": "PASS_SYNTHETIC_NS_BOUNDARIES",
        "cases": len(tests),
        "inferred_statistics_type_observed": inferred_unit,
        "explicit_statistics_type_required": explicit_unit,
        "tests": tests,
    }


def engineering_payload(seal_path: Path, expected_hash: str) -> Path:
    seal = read_json(seal_path)
    if seal.get("classification") != "ENGINEERING_ONLY" or seal.get("quality_gate") != "PASS":
        raise ValueError(f"Engineering source seal is not eligible: {seal_path}")
    record = seal.get("normalized_payload")
    if not isinstance(record, dict):
        raise TypeError(seal_path)
    path = seal_path.parent / str(record["path"])
    if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != expected_hash or record.get("sha256") != expected_hash:
        raise ValueError(f"Engineering payload binding failed: {path}")
    return path


def engineering_proof() -> dict[str, Any]:
    sources = (
        ("MBO", engineering_payload(ENGINEERING_MBO_SEAL, EXPECTED["engineering_mbo"]), ENGINEERING_MBO_SEAL),
        ("MBP-10", engineering_payload(ENGINEERING_MBP_SEAL, EXPECTED["engineering_mbp"]), ENGINEERING_MBP_SEAL),
    )
    results = []
    for schema, path, seal_path in sources:
        with pq.ParquetFile(path) as parquet:
            ts_index = parquet.schema_arrow.get_field_index("ts_recv")
            boundaries: list[int] = []
            for group in range(parquet.num_row_groups):
                stats = parquet.metadata.row_group(group).column(ts_index).statistics
                if stats is not None and stats.has_min_max:
                    boundaries.extend((int(stats.min_raw), int(stats.max_raw)))
            row_groups = parquet.num_row_groups
        points = sorted(set(boundaries))
        selected = sorted(set((points[0], points[len(points) // 2], points[-1])))
        ranges = []
        for point in selected:
            ranges.extend(((point, point + 1), (point, point + 1_000_000_000)))
        tests = [assert_exact_range(path, METADATA_COLUMNS, start, end) for start, end in ranges]
        results.append({
            "schema": schema,
            "classification": "ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
            "source_seal": file_record(seal_path),
            "payload": {"bytes": path.stat().st_size, "sha256": sha256_file(path)},
            "row_groups": row_groups,
            "cases": len(tests),
            "tests": tests,
        })
    return {"status": "PASS_ENGINEERING_METADATA_BOUNDARIES", "sources": results}


def prove_and_freeze(old_r1: Path, output: Path) -> None:
    if PROTOCOL_PATH.exists() or FREEZE_PATH.exists() or (output / "pre_freeze_reader_proof.json").exists():
        raise FileExistsError("A1 pre-freeze artifacts already exist; refusing to overwrite")
    predecessor = verify_old_r1(old_r1)
    proof = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_READER_PROOF_V1_0",
        "completed_at_utc": utc_now(),
        "status": "PASS_PRE_FREEZE_READER_PROOF",
        "synthetic": synthetic_proof(),
        "engineering_only_metadata": engineering_proof(),
        "predecessor": predecessor,
        "market_values_or_outcomes_reported": False,
        "development_metadata_opened": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "proof_receipt": None,
    }
    proof["proof_receipt"] = canonical_hash({**proof, "proof_receipt": None})
    proof_path = output / "pre_freeze_reader_proof.json"
    write_json_exclusive(proof_path, proof)

    protocol = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_PROTOCOL_V1_0",
        "status": "FROZEN_AFTER_READER_PROOF_BEFORE_DEVELOPMENT_METADATA",
        "frozen_at_utc": utc_now(),
        "authorization_sha256": hashlib.sha256(AUTHORIZATION.encode("utf-8")).hexdigest(),
        "preserved_verdicts": predecessor,
        "single_change": {
            "component": "reference Parquet ts_recv row-group statistics conversion",
            "before": "pa.scalar(statistic) inferred timestamp unit",
            "after": "pa.scalar(statistic, type=Parquet ts_recv timestamp[ns])",
            "all_other_reader_and_diagnostic_logic": "UNCHANGED_IMPORTED_FROM_SEALED_R1",
        },
        "attempt_budget": {"reference_diagnostic_attempts": 1, "primary_reruns": 0},
        "comparison_gate": "Exact equality of all 18 findings, classifications, evidence, normalized result checksum, and per-finding checksums.",
        "prohibitions": [
            "data repair", "classification change", "outcome access", "2025/2026 access",
            "data acquisition", "relationships", "trades", "PnL",
        ],
        "pre_freeze_proof": file_record(proof_path),
    }
    write_json_exclusive(PROTOCOL_PATH, protocol)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_FREEZE_V1_0",
        "status": "SEALED_BEFORE_DEVELOPMENT_METADATA_REOPEN",
        "sealed_at_utc": utc_now(),
        "protocol": file_record(PROTOCOL_PATH),
        "implementation": file_record(Path(__file__)),
        "sealed_r1_implementation": file_record(Path(r1.__file__)),
        "sealed_r1_primary": file_record(old_r1 / "primary_diagnostic.json"),
        "sealed_r1_final": file_record(old_r1 / "final_seal.json"),
        "pre_freeze_reader_proof": file_record(proof_path),
        "reference_attempt_limit": 1,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = canonical_hash({**freeze, "freeze_receipt": None})
    write_json_exclusive(FREEZE_PATH, freeze)
    print(json.dumps({"status": freeze["status"], "synthetic_cases": proof["synthetic"]["cases"], "engineering_sources": 2, "development_metadata_opened": False}, sort_keys=True))


def verify_freeze(old_r1: Path, output: Path) -> dict[str, Any]:
    predecessor = verify_old_r1(old_r1)
    protocol = read_json(PROTOCOL_PATH)
    freeze = read_json(FREEZE_PATH)
    proof_path = output / "pre_freeze_reader_proof.json"
    proof = read_json(proof_path)
    if proof.get("status") != "PASS_PRE_FREEZE_READER_PROOF" or not receipt_valid(proof, "proof_receipt"):
        raise ValueError("Pre-freeze reader proof failed")
    for key, path in (
        ("protocol", PROTOCOL_PATH),
        ("implementation", Path(__file__)),
        ("sealed_r1_implementation", Path(r1.__file__)),
        ("sealed_r1_primary", old_r1 / "primary_diagnostic.json"),
        ("sealed_r1_final", old_r1 / "final_seal.json"),
        ("pre_freeze_reader_proof", proof_path),
    ):
        record = freeze.get(key)
        if not isinstance(record, dict) or int(record.get("bytes", -1)) != path.stat().st_size or record.get("sha256") != sha256_file(path):
            raise ValueError(f"A1 freeze binding failed: {key}")
    if protocol.get("attempt_budget") != {"reference_diagnostic_attempts": 1, "primary_reruns": 0} or freeze.get("reference_attempt_limit") != 1:
        raise ValueError("A1 single-attempt policy changed")
    if not receipt_valid(freeze, "freeze_receipt"):
        raise ValueError("A1 freeze receipt failed")
    return predecessor


def build_reference(paths: r1.Paths) -> dict[str, Any]:
    registry, _manifest, acquisition = r1._verified_control(paths, verify_registered_artifacts=False)
    rows = [dict(row) for row in r1._sequence(registry.get("rows")) if int(row.get("expected_bucket_rows", 0)) > 0]
    rows_by_id = {str(row["row_id"]): row for row in rows}
    expected, _ = r1._expected_xau(rows)
    xau_scan = r1._scan_xau(paths.xau, expected, "reference")
    xau_findings = r1._xau_findings(rows, xau_scan, "reference")
    crossed_features: list[dict[str, Any]] = []
    for session, filename in (("LONDON", "reference_london_one_second_features.parquet"), ("NEW_YORK", "reference_new_york_one_second_features.parquet")):
        session_rows = sorted((row for row in rows if row["session_code"] == session), key=lambda row: str(row["session_date"]))
        crossed_features.extend(r1._feature_rows_reference(paths.m2 / filename, session_rows))
    crossed_features.sort(key=lambda item: item["feature_identity_hash"])
    if len(xau_findings) != 3 or len(crossed_features) != 15:
        raise ValueError("The frozen 3+15 finding population changed")
    original_reader = r1._read_range_reference
    try:
        r1._read_range_reference = read_range_reference_ns
        crossed_findings, source_bindings = r1._analyze_crossed_features(crossed_features, rows_by_id, acquisition, "reference")
    finally:
        r1._read_range_reference = original_reader
    findings = sorted([*xau_findings, *crossed_findings], key=lambda item: (item["domain"], item["finding_id"]))
    result: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_RESULT_V1_0",
        "implementation": "reference",
        "completed_at_utc": utc_now(),
        "status": "COMPLETE_PENDING_REPRODUCTION_SEAL",
        "xau_findings": xau_findings,
        "crossed_bucket_findings": crossed_findings,
        "classification_counts": dict(sorted(r1.Counter(str(item["classification"]) for item in findings).items())),
        "domain_counts": {"XAU_TIMESTAMP": len(xau_findings), "CROSSED_BUCKET_CLOSE": len(crossed_findings)},
        "xau_source_audit": {
            "source_rows": int(xau_scan["source_rows"]),
            "source_order_regressions": int(xau_scan["source_order_regressions"]),
            "first_2025_or_2026_line_deserialized": bool(xau_scan["first_2025_or_2026_line_deserialized"]),
            "source_sha256": r1.EXPECTED["xau"],
        },
        "affected_source_bindings": source_bindings,
        "recommendation": r1._recommendation(findings),
        "market_book_feature_or_outcome_values_reported": False,
        "development_outcomes_opened_or_joined": False,
        "year_2025_or_2026_values_accessed": False,
        "data_repaired_refreshed_filtered_relabeled_reacquired_or_recalculated": False,
        "relationships_candidates_execution_or_performance_calculated": False,
        "charge_incurred_usd": 0.0,
        "result_receipt": None,
    }
    result["result_receipt"] = canonical_hash({**result, "result_receipt": None})
    return result


def execute_once(old_r1: Path, output: Path, paths: r1.Paths) -> None:
    predecessor = verify_freeze(old_r1, output)
    if (output / "attempt_started.json").exists():
        raise RuntimeError("The single A1 reference attempt has already been consumed")
    r1._verified_control(paths, verify_registered_artifacts=False)
    primary = read_json(old_r1 / "primary_diagnostic.json")
    write_json_exclusive(output / "attempt_started.json", {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_ATTEMPT_V1_0",
        "attempt": 1,
        "maximum_attempts": 1,
        "started_at_utc": utc_now(),
        "primary_rerun": False,
        "development_outcomes_opened": False,
    })
    try:
        reference = build_reference(paths)
        write_json_exclusive(output / "reference_diagnostic.json", reference)
        primary_normalized = r1._normalize_result(primary)
        reference_normalized = r1._normalize_result(reference)
        primary_findings = sorted([*primary["xau_findings"], *primary["crossed_bucket_findings"]], key=lambda item: (item["domain"], item["finding_id"]))
        reference_findings = sorted([*reference["xau_findings"], *reference["crossed_bucket_findings"]], key=lambda item: (item["domain"], item["finding_id"]))
        finding_checksums_primary = [canonical_hash(item) for item in primary_findings]
        finding_checksums_reference = [canonical_hash(item) for item in reference_findings]
        gates = {
            "exact_eighteen_findings": len(primary_findings) == len(reference_findings) == 18,
            "finding_id_order_exact": [item["finding_id"] for item in primary_findings] == [item["finding_id"] for item in reference_findings],
            "classifications_exact": [item["classification"] for item in primary_findings] == [item["classification"] for item in reference_findings],
            "evidence_exact": [item["evidence"] for item in primary_findings] == [item["evidence"] for item in reference_findings],
            "per_finding_checksums_exact": finding_checksums_primary == finding_checksums_reference,
            "normalized_results_exact": primary_normalized == reference_normalized,
            "normalized_checksums_exact": canonical_hash(primary_normalized) == canonical_hash(reference_normalized),
            "sealed_primary_unchanged": sha256_file(old_r1 / "primary_diagnostic.json") == EXPECTED["r1_primary"],
            "reference_attempts_exactly_one": True,
            "primary_reruns_zero": True,
        }
        passed = all(gates.values())
        reproduction = {
            "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_REPRODUCTION_V1_0",
            "status": "PASS_EXACT_REPRODUCTION" if passed else "FAIL_EXACT_REPRODUCTION",
            "formal_gates": gates,
            "compared_findings": 18,
            "primary_normalized_checksum": canonical_hash(primary_normalized),
            "reference_normalized_checksum": canonical_hash(reference_normalized),
            "primary_finding_checksums": finding_checksums_primary,
            "reference_finding_checksums": finding_checksums_reference,
        }
        write_json_exclusive(output / "reproduction_check.json", reproduction)
        status = "PASS_M2_R1_A1_REFERENCE_REPRODUCTION" if passed else "FAIL_M2_R1_A1_REFERENCE_REPRODUCTION"
    except Exception as error:
        status = "FAIL_M2_R1_A1_ATTEMPT_EXECUTION"
        write_json_exclusive(output / "attempt_failure.json", {
            "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_ATTEMPT_FAILURE_V1_0",
            "status": status,
            "error_type": type(error).__name__,
            "error_sha256": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
            "market_values_or_outcomes_reported": False,
        })
        raise

    verdict: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_VERDICT_V1_0",
        "status": status,
        "formal_pass": passed,
        "completed_at_utc": utc_now(),
        "preserved_m2_status": predecessor["m2_status_preserved"],
        "preserved_m2r1_status": predecessor["m2r1_status_preserved"],
        "reference_attempts": 1,
        "primary_reruns": 0,
        "formal_gates": gates,
        "development_outcomes_opened": False,
        "year_2025_or_2026_accessed": False,
        "data_repaired_or_acquired": False,
        "relationships_trades_or_pnl_calculated": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": "Milestone 2-R1-A1 complete; stop without correction, recertification, outcome access, or research.",
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    write_json_exclusive(output / "verdict.json", verdict)
    artifact_names = ["pre_freeze_reader_proof.json", "attempt_started.json", "reference_diagnostic.json", "reproduction_check.json", "verdict.json"]
    manifest: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_MANIFEST_V1_0",
        "status": status,
        "sealed_at_utc": utc_now(),
        "protocol": file_record(PROTOCOL_PATH),
        "freeze": file_record(FREEZE_PATH),
        "implementation": file_record(Path(__file__)),
        "preserved_r1_final": file_record(old_r1 / "final_seal.json"),
        "reused_primary": file_record(old_r1 / "primary_diagnostic.json"),
        "artifacts": [file_record(output / name) for name in artifact_names],
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    write_json_exclusive(output / "manifest.json", manifest)
    final: dict[str, Any] = {
        "version": "GC_SESSION_TRIGGER_EDGE_M2_R1_A1_FINAL_SEAL_V1_0",
        "status": status,
        "sealed_at_utc": utc_now(),
        "freeze_sha256": sha256_file(FREEZE_PATH),
        "verdict_sha256": sha256_file(output / "verdict.json"),
        "manifest_sha256": sha256_file(output / "manifest.json"),
        "preserved_r1_final_seal_receipt": predecessor["m2r1_final_seal_receipt"],
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_exclusive(output / "final_seal.json", final)
    print(json.dumps({"status": status, "findings": 18, "reference_attempts": 1, "primary_reruns": 0, "outcomes_opened": False}, sort_keys=True))


def verify_final(old_r1: Path, output: Path) -> None:
    verify_freeze(old_r1, output)
    verdict = read_json(output / "verdict.json")
    manifest = read_json(output / "manifest.json")
    final = read_json(output / "final_seal.json")
    for value, field in ((verdict, "verdict_receipt"), (manifest, "manifest_receipt"), (final, "final_seal_receipt")):
        if not receipt_valid(value, field):
            raise ValueError(f"Final receipt failed: {field}")
    if final.get("freeze_sha256") != sha256_file(FREEZE_PATH) or final.get("verdict_sha256") != sha256_file(output / "verdict.json") or final.get("manifest_sha256") != sha256_file(output / "manifest.json"):
        raise ValueError("A1 final bindings failed")
    for record in manifest.get("artifacts", []):
        path = Path(str(record["path"]))
        if not path.is_file() or path.stat().st_size != int(record["bytes"]) or sha256_file(path) != record["sha256"]:
            raise ValueError(f"A1 artifact binding failed: {path}")
    print(json.dumps({"status": final["status"], "final_seal_receipt": final["final_seal_receipt"], "verified_artifacts": len(manifest["artifacts"])}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("prove-freeze", "execute-once", "verify"))
    parser.add_argument("--old-r1", default=str(DEFAULT_OLD_R1))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--m2", default=str(r1.DEFAULT_M2_DIR))
    parser.add_argument("--acquisition", default=str(r1.DEFAULT_ACQUISITION))
    parser.add_argument("--xau", default=str(r1.DEFAULT_XAU))
    args = parser.parse_args()
    old_r1 = Path(args.old_r1)
    output = Path(args.output)
    if args.action == "prove-freeze":
        prove_and_freeze(old_r1, output)
    elif args.action == "execute-once":
        execute_once(old_r1, output, r1.Paths(Path(args.m2), Path(args.acquisition), Path(args.xau), output))
    else:
        verify_final(old_r1, output)


if __name__ == "__main__":
    main()
