#!/usr/bin/env python3
"""Status-aware Step 3A.1 wrapper around the unchanged Step 3A replays."""

from __future__ import annotations

import json
import struct
import tempfile
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from reconstruct_gc_mbo_engineering_book import (
    F_LAST,
    PROTOCOL_PATH,
    LevelBookReplay,
    _canonical_hash,
    _sha256,
    compare_replays,
    load_verified_source,
    replay_source,
    run_synthetic_self_test,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3a1_amendment_v01.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3a1_v01"
)
PREDECESSOR_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3a_v01"
)
CLASSIFICATION_RECORD = struct.Struct(">qqcc")
CLASSIFICATION_COLUMNS = (
    "ts_recv",
    "action",
    "side",
    "price_fixed_1e9",
    "size",
    "order_id",
    "flags",
)


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("primary", "reference", "classify", "compare", "verify"),
    )
    parser.add_argument("--amendment", default=str(AMENDMENT_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(
        args.action,
        amendment_path=Path(args.amendment),
        output=Path(args.output),
    )


def run_stage(action: str, *, amendment_path: Path, output: Path) -> None:
    amendment, protocol, parquet_path = _verified_context(amendment_path)
    output.mkdir(parents=True, exist_ok=True)

    if action in {"primary", "reference"}:
        destination = output / f"{action}_replay.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite replay: {destination}")
        self_test = run_synthetic_self_test()
        if self_test["status"] != "PASS":
            raise RuntimeError("Synthetic semantics self-test failed")
        result = replay_source(
            parquet_path,
            implementation=action,
            expected_records=int(protocol["source"]["normalized_records"]),
        )
        result["protocol_sha256"] = _sha256(PROTOCOL_PATH)
        result["source_parquet_sha256"] = _sha256(parquet_path)
        result["synthetic_self_test"] = self_test
        result["result_hash"] = _canonical_hash(result)
        predecessor = _load_json(
            PREDECESSOR_OUTPUT / f"{action}_replay.json"
        )
        if result["result_hash"] != predecessor["result_hash"]:
            raise ValueError(f"{action} replay did not reproduce Step 3A")
        result["step3a1_amendment_sha256"] = _sha256(amendment_path)
        result["predecessor_result_hash"] = predecessor["result_hash"]
        result["predecessor_result_hash_match"] = True
        result["step3a1_result_hash"] = _canonical_hash(result)
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_MBO_STEP_3A1_{action.upper()}_REPLAY_COMPLETE",
                    "source_records_processed": result[
                        "source_records_processed"
                    ],
                    "checkpoints": len(result["checkpoints"]),
                    "input_stream_hash": result["input_stream_hash"],
                    "final_state_hash": result["final_state_hash"],
                    "predecessor_result_hash_match": True,
                    "price_values_reported": False,
                    "directional_statistics_calculated": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if action == "classify":
        destination = output / "market_state_boundary_audit.json"
        if destination.exists():
            raise FileExistsError(
                f"Refusing to overwrite boundary audit: {destination}"
            )
        audit = classify_boundaries(
            parquet_path,
            amendment["market_state_policy"]["intervals"],
        )
        predecessor_primary = _load_json(
            PREDECESSOR_OUTPUT / "primary_replay.json"
        )
        predecessor_boundaries = predecessor_primary["book_boundaries"]
        audit["predecessor_all_hours_counts_match"] = (
            audit["event_boundaries_examined"]
            == int(predecessor_boundaries["examined"])
            and audit["all_hours_relation_counts"].get("CROSSED", 0)
            == int(predecessor_boundaries.get("crossed", 0))
            and audit["all_hours_relation_counts"].get("LOCKED", 0)
            == int(predecessor_boundaries.get("locked", 0))
            and audit["all_hours_relation_counts"].get("EMPTY_SIDE", 0)
            == int(predecessor_boundaries.get("empty_side", 0))
        )
        audit["amendment_sha256"] = _sha256(amendment_path)
        audit["audit_hash"] = _canonical_hash(audit)
        _write_json_atomic(destination, audit)
        print(
            json.dumps(
                {
                    "stage": "GC_MBO_STEP_3A1_MARKET_STATE_AUDIT_COMPLETE",
                    "event_boundaries_examined": audit[
                        "event_boundaries_examined"
                    ],
                    "state_boundary_counts": audit["state_boundary_counts"],
                    "state_relation_counts": audit["state_relation_counts"],
                    "classification_coverage_errors": audit[
                        "classification_coverage_errors"
                    ],
                    "heap_direct_classification_disagreements": audit[
                        "heap_direct_classification_disagreements"
                    ],
                    "predecessor_all_hours_counts_match": audit[
                        "predecessor_all_hours_counts_match"
                    ],
                    "price_values_reported": False,
                    "directional_statistics_calculated": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if action == "compare":
        comparison_path = output / "comparison.json"
        manifest_path = output / "manifest.json"
        if comparison_path.exists() or manifest_path.exists():
            raise FileExistsError("Refusing to overwrite Step 3A.1 seal")
        primary_path = output / "primary_replay.json"
        reference_path = output / "reference_replay.json"
        audit_path = output / "market_state_boundary_audit.json"
        primary = _load_json(primary_path)
        reference = _load_json(reference_path)
        audit = _load_json(audit_path)
        self_test = run_synthetic_self_test()

        reproduced = compare_replays(
            protocol,
            primary,
            reference,
            self_test,
        )
        reproduced["protocol_sha256"] = _sha256(PROTOCOL_PATH)
        reproduced["primary_result_hash"] = primary["result_hash"]
        reproduced["reference_result_hash"] = reference["result_hash"]
        reproduced["comparison_hash"] = _canonical_hash(reproduced)
        predecessor_comparison = _load_json(
            PREDECESSOR_OUTPUT / "comparison.json"
        )
        predecessor_exactly_reproduced = (
            reproduced == predecessor_comparison
        )

        prior_gate_name = "crossed_or_locked_boundaries_zero"
        amended_gate_name = (
            "continuous_matching_crossed_or_locked_boundaries_zero"
        )
        amended_gates = dict(reproduced["gates"])
        prior_gate_value = amended_gates.pop(prior_gate_name)
        continuous_counts = audit["state_relation_counts"].get(
            "CONTINUOUS_MATCHING",
            {},
        )
        amended_gates[amended_gate_name] = (
            int(continuous_counts.get("CROSSED", 0)) == 0
            and int(continuous_counts.get("LOCKED", 0)) == 0
        )
        predecessor_gates = predecessor_comparison["gates"]
        unchanged_gate_names = sorted(
            set(predecessor_gates).difference({prior_gate_name})
        )
        unchanged_gates_equal_predecessor = all(
            amended_gates[name] == predecessor_gates[name]
            for name in unchanged_gate_names
        )
        integrity_checks = {
            "predecessor_files_unchanged": True,
            "predecessor_formal_fail_preserved": (
                amendment["predecessor"]["formal_verdict"] == "FAIL"
                and amendment["predecessor"]["verdict_preserved"] is True
            ),
            "predecessor_comparison_exactly_reproduced": (
                predecessor_exactly_reproduced
            ),
            "primary_replay_exactly_reproduced": primary[
                "predecessor_result_hash_match"
            ]
            is True,
            "reference_replay_exactly_reproduced": reference[
                "predecessor_result_hash_match"
            ]
            is True,
            "all_unchanged_gates_equal_predecessor": (
                unchanged_gates_equal_predecessor
            ),
            "only_one_gate_name_replaced": (
                set(amended_gates)
                == set(predecessor_gates)
                .difference({prior_gate_name})
                .union({amended_gate_name})
            ),
            "market_state_boundary_coverage_complete": (
                audit["classification_coverage_errors"] == 0
                and sum(audit["state_boundary_counts"].values())
                == audit["event_boundaries_examined"]
            ),
            "heap_and_direct_classification_agree": (
                audit["heap_direct_classification_disagreements"] == 0
            ),
            "all_hours_counts_match_predecessor": audit[
                "predecessor_all_hours_counts_match"
            ]
            is True,
            "source_and_final_invariants_hold": (
                not audit["final_invariant_violation_counts"]
            ),
        }
        formal_status = (
            "PASS"
            if all(amended_gates.values())
            and all(integrity_checks.values())
            else "FAIL"
        )
        comparison: dict[str, Any] = {
            "comparison_version": "GC_MBO_STEP_3A1_COMPARISON_V0_1",
            "status": formal_status,
            "classification": "POST_RESULT_ENGINEERING_SEMANTICS_CORRECTION",
            "research_or_validation_credit": "NONE",
            "predecessor": {
                "formal_verdict": "FAIL",
                "formal_verdict_preserved": True,
                "comparison_hash": predecessor_comparison["comparison_hash"],
                "comparison_exactly_reproduced": (
                    predecessor_exactly_reproduced
                ),
                "prior_gate_name": prior_gate_name,
                "prior_gate_value": prior_gate_value,
            },
            "sole_gate_amendment": {
                "removed_gate": prior_gate_name,
                "added_gate": amended_gate_name,
                "all_other_gate_names_and_values_unchanged": (
                    unchanged_gates_equal_predecessor
                ),
            },
            "amended_gates": amended_gates,
            "integrity_checks": integrity_checks,
            "state_boundary_counts": audit["state_boundary_counts"],
            "state_relation_counts": audit["state_relation_counts"],
            "maintenance_and_pre_open_reported_not_rejected": True,
            "input_stream_hash": primary["input_stream_hash"],
            "final_state_hash": primary["final_state_hash"],
            "final_structure_hash": primary["final_structure_hash"],
            "amendment_sha256": _sha256(amendment_path),
            "primary_step3a1_result_hash": primary["step3a1_result_hash"],
            "reference_step3a1_result_hash": reference[
                "step3a1_result_hash"
            ],
            "market_state_audit_hash": audit["audit_hash"],
            "technical_replay_processed_book_values": True,
            "price_values_reported": False,
            "directional_statistics_calculated": False,
            "signals_calculated": False,
            "outcomes_accessed": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
        comparison["comparison_hash"] = _canonical_hash(comparison)
        _write_json_atomic(comparison_path, comparison)

        manifest: dict[str, Any] = {
            "manifest_version": "GC_MBO_STEP_3A1_MANIFEST_V0_1",
            "status": formal_status,
            "classification": comparison["classification"],
            "research_or_validation_credit": "NONE",
            "predecessor_formal_verdict": "FAIL",
            "predecessor_formal_verdict_preserved": True,
            "amendment": {
                "path": str(amendment_path.resolve()),
                "sha256": _sha256(amendment_path),
            },
            "unchanged_replay_tool": {
                "path": str(
                    (
                        REPO_ROOT
                        / "tools"
                        / "reconstruct_gc_mbo_engineering_book.py"
                    ).resolve()
                ),
                "sha256": _sha256(
                    REPO_ROOT
                    / "tools"
                    / "reconstruct_gc_mbo_engineering_book.py"
                ),
            },
            "orchestration_tool": {
                "path": str(Path(__file__).resolve()),
                "sha256": _sha256(Path(__file__).resolve()),
            },
            "source": {
                "path": str(parquet_path.resolve()),
                "sha256": _sha256(parquet_path),
                "records": int(protocol["source"]["normalized_records"]),
            },
            "artifacts": [
                _artifact(primary_path),
                _artifact(reference_path),
                _artifact(audit_path),
                _artifact(comparison_path),
            ],
            "comparison_hash": comparison["comparison_hash"],
            "price_values_reported": False,
            "directional_statistics_calculated": False,
            "signals_calculated": False,
            "outcomes_accessed": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
        manifest["manifest_hash"] = _canonical_hash(manifest)
        _write_json_atomic(manifest_path, manifest)
        print(
            json.dumps(
                {
                    "stage": "GC_MBO_STEP_3A1_COMPARISON_SEALED",
                    "status": formal_status,
                    "passed_amended_gates": sum(amended_gates.values()),
                    "total_amended_gates": len(amended_gates),
                    "passed_integrity_checks": sum(
                        integrity_checks.values()
                    ),
                    "total_integrity_checks": len(integrity_checks),
                    "predecessor_formal_fail_preserved": True,
                    "manifest_hash": manifest["manifest_hash"],
                    "price_values_reported": False,
                    "directional_statistics_calculated": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if action == "verify":
        manifest_path = output / "manifest.json"
        manifest = _load_json(manifest_path)
        manifest_without_hash = {
            key: value for key, value in manifest.items() if key != "manifest_hash"
        }
        if manifest["manifest_hash"] != _canonical_hash(manifest_without_hash):
            raise ValueError("Step 3A.1 manifest hash mismatch")
        for item in manifest["artifacts"]:
            path = Path(str(item["path"]))
            if (
                not path.is_file()
                or path.stat().st_size != int(item["bytes"])
                or _sha256(path) != item["sha256"]
            ):
                raise ValueError(f"Step 3A.1 artifact changed: {path}")
        comparison = _load_json(output / "comparison.json")
        comparison_without_hash = {
            key: value
            for key, value in comparison.items()
            if key != "comparison_hash"
        }
        if (
            comparison["comparison_hash"]
            != _canonical_hash(comparison_without_hash)
            or comparison["comparison_hash"] != manifest["comparison_hash"]
        ):
            raise ValueError("Step 3A.1 comparison seal mismatch")
        if manifest["predecessor_formal_verdict_preserved"] is not True:
            raise ValueError("Step 3A predecessor verdict was not preserved")
        if (
            _sha256(Path(str(manifest["orchestration_tool"]["path"])))
            != manifest["orchestration_tool"]["sha256"]
            or _sha256(Path(str(manifest["unchanged_replay_tool"]["path"])))
            != manifest["unchanged_replay_tool"]["sha256"]
        ):
            raise ValueError("Step 3A.1 replay tooling changed after sealing")
        print(
            json.dumps(
                {
                    "stage": "GC_MBO_STEP_3A1_SEAL_VERIFIED",
                    "status": manifest["status"],
                    "artifacts_verified": len(manifest["artifacts"]),
                    "manifest_hash": manifest["manifest_hash"],
                    "predecessor_formal_fail_preserved": True,
                    "classification": manifest["classification"],
                    "price_values_reported": False,
                    "directional_statistics_calculated": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    raise AssertionError(f"Unhandled action: {action}")


def classify_boundaries(
    parquet_path: Path,
    intervals: list[dict[str, Any]],
) -> dict[str, Any]:
    parsed_intervals = [
        {
            "state": str(item["state"]),
            "start_ns": _timestamp_ns(str(item["start_inclusive"])),
            "end_ns": _timestamp_ns(str(item["end_exclusive"])),
        }
        for item in intervals
    ]
    book = LevelBookReplay()
    total_records = 0
    boundaries = 0
    coverage_errors = 0
    heap_direct_disagreements = 0
    state_boundary_counts: Counter[str] = Counter()
    all_hours_relations: Counter[str] = Counter()
    state_relations: dict[str, Counter[str]] = defaultdict(Counter)
    classification_hash = __import__("hashlib").sha256()
    for interval in parsed_intervals:
        state_boundary_counts[interval["state"]] += 0
        state_relations[interval["state"]]

    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(
        batch_size=100_000,
        columns=list(CLASSIFICATION_COLUMNS),
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in CLASSIFICATION_COLUMNS
        }
        recv = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in ("price_fixed_1e9", "size", "order_id", "flags")
        }
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()
        for index in range(batch.num_rows):
            total_records += 1
            flags = int(numeric["flags"][index])
            book.apply(
                ordinal=total_records,
                action=str(actions[index]),
                side=str(sides[index]),
                order_id=int(numeric["order_id"][index]),
                price=int(numeric["price_fixed_1e9"][index]),
                size=int(numeric["size"][index]),
                flags=flags,
            )
            if not flags & F_LAST:
                continue
            boundaries += 1
            recv_ns = int(recv[index])
            states = [
                interval["state"]
                for interval in parsed_intervals
                if interval["start_ns"] <= recv_ns < interval["end_ns"]
            ]
            if len(states) != 1:
                coverage_errors += 1
                state = "UNCLASSIFIED"
            else:
                state = states[0]
            heap_bid = book.best_price("B")
            heap_ask = book.best_price("A")
            direct_bid = max(book.levels["B"], default=None)
            direct_ask = min(book.levels["A"], default=None)
            relation = _book_relation(heap_bid, heap_ask)
            direct_relation = _book_relation(direct_bid, direct_ask)
            if relation != direct_relation:
                heap_direct_disagreements += 1
            state_boundary_counts[state] += 1
            state_relations[state][relation] += 1
            all_hours_relations[relation] += 1
            classification_hash.update(
                CLASSIFICATION_RECORD.pack(
                    total_records,
                    recv_ns,
                    _state_code(state),
                    _relation_code(relation),
                )
            )
    return {
        "audit_version": "GC_MBO_STEP_3A1_MARKET_STATE_AUDIT_V0_1",
        "source_records_processed": total_records,
        "event_boundaries_examined": boundaries,
        "state_boundary_counts": dict(sorted(state_boundary_counts.items())),
        "state_relation_counts": {
            state: dict(sorted(counts.items()))
            for state, counts in sorted(state_relations.items())
        },
        "all_hours_relation_counts": dict(
            sorted(all_hours_relations.items())
        ),
        "classification_coverage_errors": coverage_errors,
        "heap_direct_classification_disagreements": (
            heap_direct_disagreements
        ),
        "classification_stream_hash": classification_hash.hexdigest(),
        "final_invariant_violation_counts": dict(
            sorted(book.validate().items())
        ),
        "technical_replay_processed_book_values": True,
        "price_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }


def _verified_context(
    amendment_path: Path,
) -> tuple[dict[str, Any], dict[str, Any], Path]:
    amendment = _load_json(amendment_path)
    if (
        amendment.get("status") != "FROZEN_BEFORE_AMENDED_REPLAY"
        or amendment.get("classification")
        != "POST_RESULT_ENGINEERING_SEMANTICS_CORRECTION"
        or amendment.get("research_or_validation_credit") != "NONE"
    ):
        raise ValueError("Step 3A.1 amendment is not frozen")
    if (
        amendment["predecessor"]["formal_verdict"] != "FAIL"
        or amendment["predecessor"]["verdict_preserved"] is not True
    ):
        raise ValueError("Step 3A predecessor FAIL was not preserved")
    for item in amendment["predecessor"]["files"]:
        path = REPO_ROOT / str(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Step 3A predecessor changed: {path}")
    predecessor_manifest = _load_json(
        PREDECESSOR_OUTPUT / "manifest.json"
    )
    if (
        predecessor_manifest["manifest_hash"]
        != amendment["predecessor"]["manifest_hash"]
        or predecessor_manifest["status"] != "FAIL"
    ):
        raise ValueError("Step 3A predecessor verdict seal failed")
    _validate_intervals(amendment["market_state_policy"]["intervals"])
    protocol, parquet_path = load_verified_source(PROTOCOL_PATH)
    return amendment, protocol, parquet_path


def _validate_intervals(intervals: list[dict[str, Any]]) -> None:
    expected_start = _timestamp_ns("2024-01-09T00:00:00Z")
    expected_end = _timestamp_ns("2024-01-10T00:00:00Z")
    prior_end = expected_start
    for item in intervals:
        start = _timestamp_ns(str(item["start_inclusive"]))
        end = _timestamp_ns(str(item["end_exclusive"]))
        if start != prior_end or end <= start:
            raise ValueError("Market-state intervals overlap or have a gap")
        prior_end = end
    if prior_end != expected_end:
        raise ValueError("Market-state intervals do not cover the frozen day")


def _timestamp_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    epoch = datetime(1970, 1, 1, tzinfo=UTC)
    delta = parsed - epoch
    return (
        (delta.days * 86_400 + delta.seconds) * 1_000_000_000
        + delta.microseconds * 1_000
    )


def _book_relation(bid: int | None, ask: int | None) -> str:
    if bid is None or ask is None:
        return "EMPTY_SIDE"
    if bid > ask:
        return "CROSSED"
    if bid == ask:
        return "LOCKED"
    return "UNCROSSED"


def _state_code(value: str) -> bytes:
    return {
        "CONTINUOUS_MATCHING": b"C",
        "MAINTENANCE": b"M",
        "PRE_OPEN": b"P",
        "UNCLASSIFIED": b"U",
    }[value]


def _relation_code(value: str) -> bytes:
    return {
        "UNCROSSED": b"U",
        "LOCKED": b"L",
        "CROSSED": b"C",
        "EMPTY_SIDE": b"E",
    }[value]


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        suffix=".tmp",
        delete=False,
    ) as handle:
        temporary = Path(handle.name)
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
    temporary.replace(path)


if __name__ == "__main__":
    main()
