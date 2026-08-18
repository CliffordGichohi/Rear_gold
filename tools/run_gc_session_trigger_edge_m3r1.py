#!/usr/bin/env python3
"""Serialization-only recovery wrapper for GC Session Trigger Edge M3-R1."""

from __future__ import annotations

import argparse
from copy import deepcopy
from datetime import UTC, datetime
import importlib.util
import inspect
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Mapping, Sequence

import pyarrow as pa
import pyarrow.parquet as pq


ROOT = Path(__file__).resolve().parents[1]
BASE_PATH = ROOT / "tools" / "run_gc_session_trigger_edge_m3.py"
AMENDMENT_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_DISCOVERY_V2_MILESTONE_3_R1.md"
PROTOCOL_PATH = ROOT / "research_manifests" / "gc_session_trigger_edge_m3r1_protocol_v01.json"
FREEZE_PATH = ROOT / "research_manifests" / "gc_session_trigger_edge_m3r1_freeze_v01.json"
TEST_PATH = ROOT / "tests" / "test_gc_session_trigger_edge_m3r1.py"

DEFAULT_ROOT = Path("/home/wapi/rear_gold_step5b_v01")
DEFAULT_V2R1 = DEFAULT_ROOT / "artifacts/gc_session_trigger_edge_v2r1_v01"
DEFAULT_XAU = DEFAULT_ROOT / "data/gold_casebook_v01/price_bars.jsonl.gz"
DEFAULT_FAILED = DEFAULT_ROOT / "artifacts/gc_session_trigger_edge_m3_v01"
DEFAULT_OUTPUT = DEFAULT_ROOT / "artifacts/gc_session_trigger_edge_m3r1_v01"
DEFAULT_ENGINEERING = DEFAULT_ROOT / "artifacts/gc_session_trigger_edge_m3r1_engineering_v01"


def _load_base() -> Any:
    spec = importlib.util.spec_from_file_location("gc_session_trigger_edge_m3_frozen", BASE_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(BASE_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


base = _load_base()


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def corrected_write_parquet_exclusive(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    if path.exists():
        raise FileExistsError(path)
    table = pa.Table.from_pylist(list(rows), schema=base.OUTCOME_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(table, temporary, compression="zstd", use_dictionary=False, write_statistics=True, data_page_version="1.0", version="2.6", row_group_size=65_536)
    temporary.replace(path)


def patch_writer_only() -> None:
    base.write_parquet_exclusive = corrected_write_parquet_exclusive


def _synthetic_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row_index in range(2):
        row: dict[str, Any] = {}
        for field_index, field in enumerate(base.OUTCOME_SCHEMA):
            if pa.types.is_string(field.type):
                row[field.name] = f"SYNTHETIC_{row_index}_{field.name}"
            elif pa.types.is_int64(field.type):
                row[field.name] = None if field.nullable and row_index == 1 and field_index % 2 else row_index * 10_000 + field_index
            else:
                raise TypeError(field)
        rows.append(row)
    return rows


def _serializer_proof(directory: Path) -> dict[str, Any]:
    if directory.exists():
        raise FileExistsError(directory)
    directory.mkdir(parents=True)
    primary_rows = _synthetic_rows()
    reference_rows = [dict((key, value) for key, value in reversed(list(row.items()))) for row in deepcopy(primary_rows)]
    primary_path = directory / "primary_synthetic_outcomes.parquet"
    reference_path = directory / "reference_synthetic_outcomes.parquet"
    corrected_write_parquet_exclusive(primary_path, primary_rows)
    corrected_write_parquet_exclusive(reference_path, reference_rows)
    primary_table = pq.read_table(primary_path)
    reference_table = pq.read_table(reference_path)
    checks = {
        "exact_frozen_schema_primary": primary_table.schema == base.OUTCOME_SCHEMA,
        "exact_frozen_schema_reference": reference_table.schema == base.OUTCOME_SCHEMA,
        "primary_round_trip_exact": primary_table.to_pylist() == primary_rows,
        "reference_round_trip_exact": reference_table.to_pylist() == primary_rows,
        "primary_reference_rows_exact": primary_table.to_pylist() == reference_table.to_pylist(),
        "primary_reference_bytes_identical": primary_path.read_bytes() == reference_path.read_bytes(),
        "primary_reference_sha256_identical": base.sha256_file(primary_path) == base.sha256_file(reference_path),
        "row_count_exact": primary_table.num_rows == reference_table.num_rows == 2,
        "column_count_exact": primary_table.num_columns == reference_table.num_columns == len(base.OUTCOME_SCHEMA),
    }
    if not all(checks.values()):
        raise ValueError([name for name, passed in checks.items() if not passed])
    proof = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_SERIALIZER_PROOF_V1_0",
        "status": "PASS_M3_R1_EXACT_SCHEMA_SERIALIZATION_PROOF",
        "completed_at_utc": utc_now(),
        "checks": checks,
        "schema_hash": base.canonical_hash(str(base.OUTCOME_SCHEMA)),
        "round_trip_rows_hash": base.canonical_hash(primary_rows),
        "primary": {"path": str(primary_path), "sha256": base.sha256_file(primary_path), "bytes": primary_path.stat().st_size},
        "reference": {"path": str(reference_path), "sha256": base.sha256_file(reference_path), "bytes": reference_path.stat().st_size},
        "market_source_opened": False,
        "outcome_values_accessed": False,
        "year_2025_or_2026_values_accessed": False,
        "proof_receipt": None,
    }
    proof["proof_receipt"] = base.canonical_hash({**proof, "proof_receipt": None})
    base.write_json_exclusive(directory / "proof.json", proof)
    return proof


def _protocol() -> dict[str, Any]:
    value = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_PROTOCOL_V1_0",
        "status": "FROZEN_SERIALIZATION_ONLY_BEFORE_SECOND_SOURCE_OPENING",
        "preserved_failure_status": "FAIL_M3_SINGLE_OUTCOME_OPEN_SERIALIZATION",
        "first_source_opening_count": 1,
        "first_opening_research_credit": 0,
        "permitted_second_source_opening_count": 1,
        "maximum_cumulative_source_openings": 2,
        "sole_correction": {"from": "pq.write_table(temporary, table, ...)", "to": "pq.write_table(table, temporary, ...)", "all_keyword_arguments_unchanged": True},
        "proof_gates": ["exact frozen schema", "byte-identical primary/reference Parquet", "round-trip row equality", "SHA-256 equality", "no market-source access"],
        "analytical_definitions_changed": False,
        "tests_assignments_thresholds_seeds_support_statistics_or_rankings_changed": False,
        "another_failure_disposition": "PERMANENTLY_TERMINATE_MILESTONE_3_R1",
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "protocol_receipt": None,
    }
    value["protocol_receipt"] = base.canonical_hash({**value, "protocol_receipt": None})
    return value


def _verify_failure(failed: Path) -> dict[str, Any]:
    failure = base.load_json(failed / "outcome_opening_failure.json")
    verdict = base.load_json(failed / "verdict.json")
    manifest = base.load_json(failed / "manifest.json")
    final = base.load_json(failed / "final_seal.json")
    status = "FAIL_M3_SINGLE_OUTCOME_OPEN_SERIALIZATION"
    if any(record.get("status") != status for record in (failure, verdict, manifest, final)):
        raise ValueError("Original M3 failure status changed")
    for record, field in ((failure, "failure_receipt"), (verdict, "verdict_receipt"), (manifest, "manifest_receipt"), (final, "final_seal_receipt")):
        if not base.receipt_valid(record, field):
            raise ValueError(f"Original M3 failure receipt changed: {field}")
    if final["failure_sha256"] != base.sha256_file(failed / "outcome_opening_failure.json") or final["verdict_sha256"] != base.sha256_file(failed / "verdict.json") or final["manifest_sha256"] != base.sha256_file(failed / "manifest.json"):
        raise ValueError("Original M3 failure hashes changed")
    if failure.get("development_outcome_source_open_count") != 1 or failure.get("relationship_or_hit_rate_calculation_started"):
        raise ValueError("Original M3 source-opening disposition changed")
    return {"failure": failure, "verdict": verdict, "manifest": manifest, "final": final}


def prepare(v2r1: Path, xau: Path, failed: Path, output: Path, engineering: Path) -> None:
    for path in (PROTOCOL_PATH, FREEZE_PATH):
        if path.exists():
            raise FileExistsError(path)
    if output.exists() or engineering.exists():
        raise FileExistsError((output, engineering))
    failure_chain = _verify_failure(failed)
    original_freeze = base.load_json(base.FREEZE_PATH)
    if not base.receipt_valid(original_freeze, "freeze_receipt") or base.sha256_file(BASE_PATH) != original_freeze["implementation"]["sha256"]:
        raise ValueError("Original M3 implementation or freeze changed")
    base.verify_control(v2r1, xau, failed)
    failed_source = inspect.getsource(base.write_parquet_exclusive)
    corrected_source = inspect.getsource(corrected_write_parquet_exclusive)
    if "pq.write_table(temporary, table," not in failed_source or "pq.write_table(table, temporary," not in corrected_source:
        raise ValueError("Exact serializer correction source audit failed")
    if any(token not in corrected_source for token in ('compression="zstd"', 'use_dictionary=False', 'write_statistics=True', 'data_page_version="1.0"', 'version="2.6"', 'row_group_size=65_536')):
        raise ValueError("Frozen Parquet keyword parameters changed")
    proof = _serializer_proof(engineering)
    protocol = _protocol()
    protocol["frozen_at_utc"] = utc_now()
    protocol["serializer_proof_receipt"] = proof["proof_receipt"]
    protocol["protocol_receipt"] = None
    protocol["protocol_receipt"] = base.canonical_hash({**protocol, "protocol_receipt": None})
    base.write_json_exclusive(PROTOCOL_PATH, protocol)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_FREEZE_V1_0",
        "status": "SEALED_M3_R1_BEFORE_SECOND_SOURCE_OPENING",
        "sealed_at_utc": utc_now(),
        "amendment": {"path": str(AMENDMENT_PATH), "sha256": base.sha256_file(AMENDMENT_PATH), "bytes": AMENDMENT_PATH.stat().st_size},
        "wrapper": {"path": str(Path(__file__).resolve()), "sha256": base.sha256_file(Path(__file__).resolve()), "bytes": Path(__file__).stat().st_size},
        "tests": {"path": str(TEST_PATH), "sha256": base.sha256_file(TEST_PATH), "bytes": TEST_PATH.stat().st_size},
        "protocol": {"path": str(PROTOCOL_PATH), "sha256": base.sha256_file(PROTOCOL_PATH)},
        "proof": {"path": str(engineering / "proof.json"), "sha256": base.sha256_file(engineering / "proof.json"), "receipt": proof["proof_receipt"]},
        "original_m3": {
            "implementation_path": str(BASE_PATH), "implementation_sha256": base.sha256_file(BASE_PATH),
            "freeze_path": str(base.FREEZE_PATH), "freeze_sha256": base.sha256_file(base.FREEZE_PATH), "freeze_receipt": original_freeze["freeze_receipt"],
            "failed_output": str(failed), "failure_final_seal_sha256": base.sha256_file(failed / "final_seal.json"), "failure_final_seal_receipt": failure_chain["final"]["final_seal_receipt"],
        },
        "analytical_change_count": 0,
        "serialization_change_count": 1,
        "source_openings_before_r1": 1,
        "source_openings_permitted_in_r1": 1,
        "maximum_cumulative_source_openings": 2,
        "outcome_values_accessed_during_r1_preparation": False,
        "year_2025_or_2026_values_accessed": False,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = base.canonical_hash({**freeze, "freeze_receipt": None})
    base.write_json_exclusive(FREEZE_PATH, freeze)
    output.mkdir(parents=True)
    shutil.copyfile(failed / "preflight.json", output / "preflight.json")
    r1_preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_PREFLIGHT_V1_0",
        "status": "PASS_M3_R1_PRE_SECOND_OPENING_READINESS",
        "completed_at_utc": utc_now(),
        "original_failure_preserved": True,
        "serializer_proof_passed": True,
        "serializer_proof_receipt": proof["proof_receipt"],
        "r1_freeze_receipt": freeze["freeze_receipt"],
        "source_openings_before_r1": 1,
        "market_source_opened_in_r1": False,
        "outcome_values_accessed_in_r1": False,
        "year_2025_or_2026_values_accessed": False,
        "preflight_receipt": None,
    }
    r1_preflight["preflight_receipt"] = base.canonical_hash({**r1_preflight, "preflight_receipt": None})
    base.write_json_exclusive(output / "r1_preflight.json", r1_preflight)
    print(json.dumps({"status": r1_preflight["status"], "proof": proof["status"], "cumulative_openings": 1, "outcomes_opened_in_r1": False}, sort_keys=True))


def verify_r1_control(v2r1: Path, xau: Path, failed: Path, output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    freeze = base.load_json(FREEZE_PATH)
    protocol = base.load_json(PROTOCOL_PATH)
    proof = base.load_json(Path(freeze["proof"]["path"]))
    preflight = base.load_json(output / "r1_preflight.json")
    if freeze.get("status") != "SEALED_M3_R1_BEFORE_SECOND_SOURCE_OPENING" or not base.receipt_valid(freeze, "freeze_receipt"):
        raise ValueError("R1 freeze failed")
    for record, field in ((protocol, "protocol_receipt"), (proof, "proof_receipt"), (preflight, "preflight_receipt")):
        if not base.receipt_valid(record, field):
            raise ValueError(f"R1 receipt failed: {field}")
    bindings = {
        AMENDMENT_PATH: freeze["amendment"]["sha256"],
        Path(__file__).resolve(): freeze["wrapper"]["sha256"],
        TEST_PATH: freeze["tests"]["sha256"],
        PROTOCOL_PATH: freeze["protocol"]["sha256"],
        Path(freeze["proof"]["path"]): freeze["proof"]["sha256"],
        BASE_PATH: freeze["original_m3"]["implementation_sha256"],
        base.FREEZE_PATH: freeze["original_m3"]["freeze_sha256"],
        failed / "final_seal.json": freeze["original_m3"]["failure_final_seal_sha256"],
    }
    for path, expected in bindings.items():
        if not path.exists() or base.sha256_file(path) != expected:
            raise ValueError(f"R1 binding changed: {path}")
    _verify_failure(failed)
    base.verify_control(v2r1, xau, output)
    return freeze, protocol


def _seal_recovery_failure(output: Path, exc: BaseException) -> None:
    failure = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_RECOVERY_FAILURE_V1_0",
        "status": "FAIL_M3_R1_RECOVERY_PERMANENTLY_TERMINATED",
        "recorded_at_utc": utc_now(),
        "exception_type": type(exc).__name__, "exception_message": str(exc),
        "cumulative_source_openings": 2, "relationship_tests_completed": 0,
        "year_2025_or_2026_values_accessed": False, "execution_trade_pnl_r_or_return_calculated": False,
        "failure_receipt": None,
    }
    failure["failure_receipt"] = base.canonical_hash({**failure, "failure_receipt": None})
    base.write_json_exclusive(output / "r1_recovery_failure.json", failure)
    final = {"version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_FAILURE_FINAL_SEAL_V1_0", "status": failure["status"], "sealed_at_utc": utc_now(), "failure_sha256": base.sha256_file(output / "r1_recovery_failure.json"), "failure_receipt": failure["failure_receipt"], "final_seal_receipt": None}
    final["final_seal_receipt"] = base.canonical_hash({**final, "final_seal_receipt": None})
    base.write_json_exclusive(output / "r1_final_seal.json", final)


def open_outcomes(v2r1: Path, xau: Path, failed: Path, output: Path) -> None:
    freeze, _ = verify_r1_control(v2r1, xau, failed, output)
    if (output / "r1_attempt_started.json").exists() or (output / "outcome_opening.json").exists():
        raise FileExistsError("R1 recovery opening was already attempted")
    attempt = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_ATTEMPT_V1_0",
        "status": "SECOND_AND_FINAL_SOURCE_OPENING_STARTED",
        "started_at_utc": utc_now(), "prior_source_openings": 1, "this_opening_ordinal": 2,
        "r1_freeze_receipt": freeze["freeze_receipt"], "attempt_receipt": None,
    }
    attempt["attempt_receipt"] = base.canonical_hash({**attempt, "attempt_receipt": None})
    base.write_json_exclusive(output / "r1_attempt_started.json", attempt)
    patch_writer_only()
    try:
        base.open_outcomes(v2r1, xau, output)
    except BaseException as exc:
        _seal_recovery_failure(output, exc)
        raise
    opening = base.load_json(output / "outcome_opening.json")
    ledger = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_SOURCE_OPENING_LEDGER_V1_0",
        "status": "SEALED_CUMULATIVE_SOURCE_OPENINGS_TWO",
        "sealed_at_utc": utc_now(),
        "openings": [
            {"ordinal": 1, "branch": "M3", "status": "FAILED_SERIALIZATION", "research_credit": 0, "final_seal_receipt": base.load_json(failed / "final_seal.json")["final_seal_receipt"]},
            {"ordinal": 2, "branch": "M3_R1", "status": "PASS_OUTCOME_JOIN", "research_credit": 1, "opening_receipt": opening["opening_receipt"]},
        ],
        "cumulative_source_openings": 2,
        "additional_openings_permitted": 0,
        "year_2025_or_2026_values_accessed": False,
        "ledger_receipt": None,
    }
    ledger["ledger_receipt"] = base.canonical_hash({**ledger, "ledger_receipt": None})
    base.write_json_exclusive(output / "r1_source_opening_ledger.json", ledger)
    print(json.dumps({"status": opening["status"], "eligible_event_rows": opening["eligible_event_rows_joined"], "cumulative_source_openings": 2, "primary_reference_exact": opening["primary_reference_exact"]}, sort_keys=True))


def _require_opening_ledger(output: Path) -> dict[str, Any]:
    ledger = base.load_json(output / "r1_source_opening_ledger.json")
    if ledger.get("status") != "SEALED_CUMULATIVE_SOURCE_OPENINGS_TWO" or not base.receipt_valid(ledger, "ledger_receipt") or ledger.get("cumulative_source_openings") != 2:
        raise ValueError("R1 source-opening ledger failed")
    return ledger


def evaluate_stage(v2r1: Path, xau: Path, failed: Path, output: Path, implementation: str, stage: int) -> None:
    verify_r1_control(v2r1, xau, failed, output)
    _require_opening_ledger(output)
    patch_writer_only()
    base.evaluate_stage(v2r1, xau, output, implementation, stage)


def seal_stage1(v2r1: Path, xau: Path, failed: Path, output: Path) -> None:
    verify_r1_control(v2r1, xau, failed, output)
    _require_opening_ledger(output)
    base.seal_stage1(v2r1, xau, output)


def seal_final(v2r1: Path, xau: Path, failed: Path, output: Path) -> None:
    freeze, _ = verify_r1_control(v2r1, xau, failed, output)
    ledger = _require_opening_ledger(output)
    base.seal_final(v2r1, xau, output)
    inner_verdict = base.load_json(output / "verdict.json")
    inner_manifest = base.load_json(output / "manifest.json")
    inner_final = base.load_json(output / "final_seal.json")
    inner_status = str(inner_verdict["status"])
    if inner_status == "PASS_M3_DISCOVERY_WITH_PROVISIONAL_CANDIDATES":
        status = "PASS_M3_R1_DISCOVERY_WITH_PROVISIONAL_CANDIDATES"
    elif inner_status == "PASS_M3_DISCOVERY_ZERO_CANDIDATES":
        status = "PASS_M3_R1_DISCOVERY_ZERO_CANDIDATES"
    else:
        raise ValueError(f"Unexpected inner result: {inner_status}")
    r1_verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_VERDICT_V1_0", "status": status, "formal_milestone_pass": True, "completed_at_utc": utc_now(),
        "preserved_failure_status": "FAIL_M3_SINGLE_OUTCOME_OPEN_SERIALIZATION", "cumulative_source_openings": ledger["cumulative_source_openings"],
        "first_opening_research_credit": 0, "second_opening_join_pass": True,
        "summary": inner_verdict["summary"], "shortlist": inner_verdict["shortlist"],
        "research_interpretation": inner_verdict["research_interpretation"],
        "year_2025_or_2026_values_accessed": False, "execution_trade_pnl_r_or_return_calculated": False,
        "verdict_receipt": None,
    }
    r1_verdict["verdict_receipt"] = base.canonical_hash({**r1_verdict, "verdict_receipt": None})
    base.write_json_exclusive(output / "r1_verdict.json", r1_verdict)
    artifacts = {}
    for name in (
        "r1_preflight.json", "r1_attempt_started.json", "r1_source_opening_ledger.json", "outcome_opening.json",
        "primary_joined_event_outcomes.parquet", "reference_joined_event_outcomes.parquet",
        "primary_stage1_results.json", "reference_stage1_results.json", "stage1_seal.json",
        "primary_stage2_results.json", "reference_stage2_results.json", "complete_results.json", "verdict.json", "manifest.json", "final_seal.json", "GC_SESSION_TRIGGER_EDGE_MILESTONE_3_REPORT.md", "r1_verdict.json",
    ):
        path = output / name
        artifacts[name] = {"path": str(path), "sha256": base.sha256_file(path), "bytes": path.stat().st_size}
    r1_manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_MANIFEST_V1_0", "status": status, "sealed_at_utc": utc_now(),
        "predecessors": {"r1_freeze_receipt": freeze["freeze_receipt"], "preserved_failure_final_seal_receipt": base.load_json(failed / "final_seal.json")["final_seal_receipt"], "inner_final_seal_receipt": inner_final["final_seal_receipt"], "source_opening_ledger_receipt": ledger["ledger_receipt"]},
        "artifacts": artifacts, "summary": inner_manifest["summary"], "shortlist": inner_manifest["shortlist"],
        "cumulative_source_openings": 2, "first_opening_research_credit": 0,
        "serializer_correction_count": 1, "analytical_definition_change_count": 0,
        "independent_reproduction": inner_manifest["independent_reproduction"],
        "year_2025_or_2026_values_accessed": False, "execution_trade_pnl_r_or_return_calculated": False, "data_acquired": False, "charge_incurred_usd": 0.0,
        "manifest_receipt": None,
    }
    r1_manifest["manifest_receipt"] = base.canonical_hash({**r1_manifest, "manifest_receipt": None})
    base.write_json_exclusive(output / "r1_manifest.json", r1_manifest)
    r1_final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M3_R1_FINAL_SEAL_V1_0", "status": status, "sealed_at_utc": utc_now(),
        "r1_verdict_sha256": base.sha256_file(output / "r1_verdict.json"), "r1_verdict_receipt": r1_verdict["verdict_receipt"],
        "r1_manifest_sha256": base.sha256_file(output / "r1_manifest.json"), "r1_manifest_receipt": r1_manifest["manifest_receipt"],
        "inner_final_seal_sha256": base.sha256_file(output / "final_seal.json"), "inner_final_seal_receipt": inner_final["final_seal_receipt"],
        "final_seal_receipt": None,
    }
    r1_final["final_seal_receipt"] = base.canonical_hash({**r1_final, "final_seal_receipt": None})
    base.write_json_exclusive(output / "r1_final_seal.json", r1_final)
    print(json.dumps({"status": status, "summary": r1_verdict["summary"], "shortlist": r1_verdict["shortlist"], "cumulative_source_openings": 2, "final_seal_receipt": r1_final["final_seal_receipt"]}, sort_keys=True))


def verify_final(v2r1: Path, xau: Path, failed: Path, output: Path) -> None:
    verify_r1_control(v2r1, xau, failed, output)
    ledger = _require_opening_ledger(output)
    base.verify_final(v2r1, xau, output)
    verdict = base.load_json(output / "r1_verdict.json")
    manifest = base.load_json(output / "r1_manifest.json")
    final = base.load_json(output / "r1_final_seal.json")
    for record, field in ((verdict, "verdict_receipt"), (manifest, "manifest_receipt"), (final, "final_seal_receipt")):
        if not base.receipt_valid(record, field):
            raise ValueError(f"R1 final receipt failed: {field}")
    if final["r1_verdict_sha256"] != base.sha256_file(output / "r1_verdict.json") or final["r1_manifest_sha256"] != base.sha256_file(output / "r1_manifest.json") or final["inner_final_seal_sha256"] != base.sha256_file(output / "final_seal.json"):
        raise ValueError("R1 final hashes failed")
    for name, item in manifest["artifacts"].items():
        if base.sha256_file(Path(item["path"])) != item["sha256"]:
            raise ValueError(f"R1 manifest artifact changed: {name}")
    if ledger["cumulative_source_openings"] != 2 or verdict["cumulative_source_openings"] != 2 or manifest["cumulative_source_openings"] != 2:
        raise ValueError("R1 cumulative source-opening count failed")
    if manifest["analytical_definition_change_count"] != 0 or manifest["serializer_correction_count"] != 1:
        raise ValueError("R1 amendment scope failed")
    print(json.dumps({"status": final["status"], "final_seal_receipt": final["final_seal_receipt"], "shortlisted_provisional_candidates": verdict["summary"]["shortlisted_provisional_candidates"], "cumulative_source_openings": 2, "year_2025_or_2026_values_accessed": False}, sort_keys=True))


def self_test() -> None:
    with tempfile.TemporaryDirectory(prefix="gc_m3r1_proof_") as temporary:
        proof = _serializer_proof(Path(temporary) / "proof")
        if proof["status"] != "PASS_M3_R1_EXACT_SCHEMA_SERIALIZATION_PROOF":
            raise AssertionError(proof)
    print(json.dumps({"status": "PASS_M3_R1_SYNTHETIC_SERIALIZATION_SELF_TEST", "market_source_opened": False}, sort_keys=True))


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("self-test", "prepare", "open-outcomes", "primary-stage1", "reference-stage1", "seal-stage1", "primary-stage2", "reference-stage2", "seal-final", "verify"))
    parser.add_argument("--v2r1", type=Path, default=DEFAULT_V2R1)
    parser.add_argument("--xau", type=Path, default=DEFAULT_XAU)
    parser.add_argument("--failed", type=Path, default=DEFAULT_FAILED)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--engineering", type=Path, default=DEFAULT_ENGINEERING)
    args = parser.parse_args()
    if args.action == "self-test":
        self_test()
    elif args.action == "prepare":
        prepare(args.v2r1, args.xau, args.failed, args.output, args.engineering)
    elif args.action == "open-outcomes":
        open_outcomes(args.v2r1, args.xau, args.failed, args.output)
    elif args.action in {"primary-stage1", "reference-stage1", "primary-stage2", "reference-stage2"}:
        implementation = "primary" if args.action.startswith("primary") else "reference"
        stage = 1 if args.action.endswith("stage1") else 2
        evaluate_stage(args.v2r1, args.xau, args.failed, args.output, implementation, stage)
    elif args.action == "seal-stage1":
        seal_stage1(args.v2r1, args.xau, args.failed, args.output)
    elif args.action == "seal-final":
        seal_final(args.v2r1, args.xau, args.failed, args.output)
    else:
        verify_final(args.v2r1, args.xau, args.failed, args.output)


if __name__ == "__main__":
    main()
