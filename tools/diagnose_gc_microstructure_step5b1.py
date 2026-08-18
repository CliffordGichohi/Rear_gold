#!/usr/bin/env python3
"""Run the frozen Step 5B.1 metadata-only source-integrity diagnostic.

The scanner selects timestamps, flags, actions, sides, sequence/event-group
metadata, source ordinals, publisher IDs, and instrument IDs only. It never
selects price, size, depth, order-count, order-flow, outcome, feature, signal,
execution, trade, or PnL columns.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from collections import Counter
from datetime import UTC, date, datetime, time
from pathlib import Path
from typing import Any, Iterable
from zoneinfo import ZoneInfo

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_protocol_v01.json"
)
INVENTORY_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_source_inventory_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_freeze_v01.json"
)
CORRECTION_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_5b1_implementation_scope_correction_v01.json"
)

EXPECTED_PROTOCOL_SHA256 = (
    "62eaf586944d720ccab584e7ebfb1ce40d7eaabfe9e9508f542680873cfd5f87"
)
EXPECTED_INVENTORY_SHA256 = (
    "a4e2bf8acf97b0ddefde017f36142f5356223ec5ca106fc8e7228cdb5c75b0af"
)
EXPECTED_FREEZE_SHA256 = (
    "a6b9d1ceabb286836f279dc275e4427f8dd4871b1058abfa70e5e869e6a7e29a"
)
EXPECTED_STEP5B_STATUS = "FAIL_STEP_5B_BUDGET_C_SOURCE_INTEGRITY"
EXPECTED_ROWS = 144_352_215
EXPECTED_RECEIVE_BEFORE = 719_524
EXPECTED_BAD_OLD_RULE_VIOLATIONS = 174
EXPECTED_INCOMPLETE_WINDOWS = 4
EXPECTED_REQUESTS = 13

F_BAD_TS_RECV = 8
F_SNAPSHOT = 32
F_LAST = 128
DAY_NS = 86_400_000_000_000
LOOKBACK_NS = 900_000_000_000
INT32_MIN = -2_147_483_648
INT32_MAX = 2_147_483_647
ALLOWED_ACTIONS = {"A", "C", "M", "T", "F", "R", "N"}
SNAPSHOT_ACTIONS = {"A", "R"}
EXPECTED_PUBLISHER = 1
BATCH_SIZE_PRIMARY = 500_000
BATCH_SIZE_REFERENCE = 350_000

COLUMNS = (
    "source_file_index",
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "action",
    "side",
    "flags",
    "ts_in_delta",
    "sequence",
)
NUMERIC_COLUMNS = tuple(name for name in COLUMNS if name not in {"action", "side"})
PROHIBITED_COLUMN_TOKENS = (
    "price",
    "_px_",
    "size",
    "_sz_",
    "depth",
    "_ct_",
    "order_id",
)

RECEIVE_CLASSES = (
    "RB_STRUCTURAL_INVALID",
    "RB_FLAGGED_BAD_TS_RECV",
    "RB_UNFLAGGED_CLAMPED_TS_IN_DELTA",
    "RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT",
    "RB_UNFLAGGED_TIMESTAMP_INCOHERENT",
)
BAD_CLASSES = (
    "BAD_STRUCTURAL_INVALID",
    "BAD_SNAPSHOT_CONTRADICTION",
    "BAD_NON_SNAPSHOT_DOCUMENTED",
    "BAD_OTHER_UNRESOLVED",
)
RECOMMENDATION_ID = "TIMESTAMP_FLAG_AND_OFFICIAL_HOLIDAY_DISPOSITION_V0_1"
RECOMMENDATION_TEXT = (
    "In a separately authorized recertification only: accept structurally "
    "valid F_BAD_TS_RECV live rows under the general provider flag semantics; "
    "accept structurally valid unflagged ts_recv-before-ts_event rows only "
    "when negative, unclamped ts_in_delta yields publisher send time at/after "
    "event time; and mark the four 2022-04-15 London/New York windows "
    "unavailable under the official Good Friday calendar. Keep every other "
    "Step 5B source, feature definition, and integrity gate unchanged."
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("primary", "reference", "seal", "verify"))
    parser.add_argument(
        "--remote-root", default="/home/wapi/rear_gold_step5b_v01"
    )
    parser.add_argument("--output", default=None)
    parser.add_argument("--artifacts", default=None)
    parser.add_argument("--report", default=None)
    args = parser.parse_args()
    remote_root = Path(args.remote_root)
    output = Path(args.output) if args.output else remote_root / "artifacts/step5b1_runs"
    artifacts = (
        Path(args.artifacts)
        if args.artifacts
        else remote_root / "artifacts/step5b1_final"
    )
    report = (
        Path(args.report)
        if args.report
        else remote_root / "artifacts/GC_MICROSTRUCTURE_STEP_5B1_REPORT.md"
    )
    run_stage(args.action, remote_root, output, artifacts, report)


def run_stage(
    action: str,
    remote_root: Path,
    output: Path,
    artifacts: Path,
    report: Path,
) -> None:
    verify_payloads = action in {"primary", "reference", "verify"}
    context = _verified_context(remote_root, verify_payloads=verify_payloads)
    _assert_protocol_matches_code(context["protocol"])
    if action in {"primary", "reference"}:
        output.mkdir(parents=True, exist_ok=True)
        destination = output / f"{action}_diagnostic.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite {destination}")
        payload = (
            _run_primary(context)
            if action == "primary"
            else _run_reference(context)
        )
        result = {
            "version": "GC_MICROSTRUCTURE_STEP_5B1_RUN_V0_1",
            "implementation": action,
            "classification": "SOURCE_INTEGRITY_DIAGNOSTIC_ONLY",
            "research_or_validation_credit": "NONE",
            "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
            "inventory_sha256": EXPECTED_INVENTORY_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
            "implementation_scope_correction": _file_record(CORRECTION_PATH),
            "tool_sha256": _sha256(Path(__file__)),
            "completed_at_utc": _utc_now(),
            "reproducible_payload": payload,
        }
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_MICROSTRUCTURE_STEP_5B1_{action.upper()}_COMPLETE",
                    "rows_scanned": payload["aggregate"]["rows_scanned"],
                    "receive_before_event_rows": payload["aggregate"][
                        "receive_before_event_rows"
                    ],
                    "bad_ts_recv_old_rule_violations": payload["aggregate"][
                        "bad_ts_recv_old_rule_violations"
                    ],
                    "incomplete_windows": payload["aggregate"][
                        "incomplete_prediction_windows"
                    ],
                    "request_classifications": payload["aggregate"][
                        "request_classification_counts"
                    ],
                    "integrity_pass": payload["formal_integrity_pass"],
                    "market_values_or_outcomes_accessed": False,
                    "charge_incurred_usd": 0.0,
                },
                sort_keys=True,
            )
        )
        return
    if action == "seal":
        _seal(context, output, artifacts, report)
        return
    if action == "verify":
        _verify_seal(context, artifacts, report)
        return
    raise AssertionError(action)


def _run_primary(context: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for spec in context["inventory"]["sources"]:
        sources.append(_scan_source_primary(spec))
    return _assemble_payload(sources, implementation="primary", context=context)


def _run_reference(context: dict[str, Any]) -> dict[str, Any]:
    sources = []
    for spec in context["inventory"]["sources"]:
        sources.append(_scan_source_reference(spec))
    return _assemble_payload(sources, implementation="reference", context=context)


def _scan_source_primary(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["normalized_payload"]["path"])
    parquet = pq.ParquetFile(path)
    request_id = spec["request_id"]
    runtime = _source_runtime(spec)
    counters = _new_counters()
    hashes = _new_hashes()
    coverage = _new_coverage(runtime)
    group = PrimaryGroupCollector(request_id)
    rows = 0
    prior_file: int | None = None
    prior_ordinal: int | None = None
    file_regressions = 0
    ordinal_regressions = 0

    for batch in parquet.iter_batches(columns=list(COLUMNS), batch_size=BATCH_SIZE_PRIMARY):
        count = batch.num_rows
        if count == 0:
            continue
        rows += count
        arrays = {name: _arrow_ints(batch.column(name)) for name in NUMERIC_COLUMNS}
        recv = arrays["ts_recv"]
        event = arrays["ts_event"]
        flags = arrays["flags"]
        files = arrays["source_file_index"]
        ordinals = arrays["source_row_ordinal"]
        receive_mask = (
            recv < event
            if spec["schema"] == "mbo"
            else np.zeros(count, dtype=bool)
        )
        bad_mask = (flags & F_BAD_TS_RECV) != 0
        bad_indices = np.flatnonzero(bad_mask)
        bad_actions = _take_strings(batch.column("action"), bad_indices)
        bad_action_allowed = np.fromiter(
            (value in SNAPSHOT_ACTIONS for value in bad_actions),
            dtype=bool,
            count=len(bad_actions),
        )
        day_start = recv - (recv % DAY_NS)
        bad_core = bad_mask & (
            ((flags & F_SNAPSHOT) == 0)
            | (recv != day_start)
            | (event >= day_start)
            | (event > recv)
        )
        bad_violation = bad_core.copy()
        if len(bad_indices):
            bad_violation[bad_indices[~bad_action_allowed]] = True
        target_mask = receive_mask | bad_violation

        if prior_file is not None:
            file_regressions += int(int(files[0]) < prior_file)
            if int(files[0]) == prior_file:
                ordinal_regressions += int(int(ordinals[0]) <= int(prior_ordinal))
            else:
                ordinal_regressions += int(int(ordinals[0]) != 1)
        if count > 1:
            same_file = files[1:] == files[:-1]
            ordinal_regressions += int(
                ((same_file & (ordinals[1:] <= ordinals[:-1]))).sum()
            )
            file_regressions += int((files[1:] < files[:-1]).sum())
            ordinal_regressions += int(
                ((~same_file) & (ordinals[1:] != 1)).sum()
            )
        prior_file = int(files[-1])
        prior_ordinal = int(ordinals[-1])

        _update_coverage_numpy(coverage, recv)
        _classify_primary_batch(
            spec=spec,
            runtime=runtime,
            batch=batch,
            arrays=arrays,
            receive_mask=receive_mask,
            bad_mask=bad_mask,
            bad_violation=bad_violation,
            target_mask=target_mask,
            counters=counters,
            hashes=hashes,
        )
        group.feed(
            files=files,
            publishers=arrays["publisher_id"],
            instruments=arrays["instrument_id"],
            sequences=arrays["sequence"],
            flags=flags,
            target_mask=target_mask,
            receive_mask=receive_mask,
            bad_mask=bad_violation,
        )
    group.finish()
    return _finalize_source(
        spec=spec,
        rows=rows,
        counters=counters,
        hashes=hashes,
        coverage=coverage,
        group=group.result(),
        file_regressions=file_regressions,
        ordinal_regressions=ordinal_regressions,
    )


def _scan_source_reference(spec: dict[str, Any]) -> dict[str, Any]:
    path = Path(spec["normalized_payload"]["path"])
    scanner = ds.dataset(path, format="parquet").scanner(
        columns=list(COLUMNS), batch_size=BATCH_SIZE_REFERENCE, use_threads=False
    )
    request_id = spec["request_id"]
    runtime = _source_runtime(spec)
    counters = _new_counters()
    hashes = _new_hashes()
    coverage = _new_coverage(runtime)
    group = ReferenceGroupCollector(request_id)
    rows = 0
    prior_file: int | None = None
    prior_ordinal: int | None = None
    file_regressions = 0
    ordinal_regressions = 0

    for batch in scanner.to_batches():
        if batch.num_rows == 0:
            continue
        numeric = batch.select(list(NUMERIC_COLUMNS)).to_pandas()
        count = len(numeric)
        rows += count
        recv = numeric["ts_recv"].astype("int64").to_numpy()
        event = numeric["ts_event"].astype("int64").to_numpy()
        flags = numeric["flags"].astype("int64").to_numpy()
        files = numeric["source_file_index"].astype("int64").to_numpy()
        ordinals = numeric["source_row_ordinal"].astype("int64").to_numpy()
        receive_mask = (
            np.less(recv, event)
            if spec["schema"] == "mbo"
            else np.zeros(count, dtype=bool)
        )
        bad_mask = np.not_equal(np.bitwise_and(flags, F_BAD_TS_RECV), 0)
        bad_indices = np.flatnonzero(bad_mask)
        action_values = _take_strings(batch.column("action"), bad_indices)
        bad_action_disallowed = np.fromiter(
            (value not in SNAPSHOT_ACTIONS for value in action_values),
            dtype=bool,
            count=len(action_values),
        )
        starts = np.floor_divide(recv, DAY_NS) * DAY_NS
        bad_violation = bad_mask & (
            (np.bitwise_and(flags, F_SNAPSHOT) == 0)
            | (recv != starts)
            | (event >= starts)
            | (event > recv)
        )
        if len(bad_indices):
            bad_violation[bad_indices[bad_action_disallowed]] = True
        target_mask = np.logical_or(receive_mask, bad_violation)

        if prior_file is not None:
            file_regressions += int(int(files[0]) < prior_file)
            if int(files[0]) == prior_file:
                ordinal_regressions += int(int(ordinals[0]) <= int(prior_ordinal))
            else:
                ordinal_regressions += int(int(ordinals[0]) != 1)
        if count > 1:
            same_file = files[1:] == files[:-1]
            file_regressions += int((files[1:] < files[:-1]).sum())
            ordinal_regressions += int(
                (same_file & (ordinals[1:] <= ordinals[:-1])).sum()
            )
            ordinal_regressions += int(
                ((~same_file) & (ordinals[1:] != 1)).sum()
            )
        prior_file = int(files[-1])
        prior_ordinal = int(ordinals[-1])

        _update_coverage_pandas(coverage, numeric["ts_recv"])
        _classify_reference_batch(
            spec=spec,
            runtime=runtime,
            batch=batch,
            numeric=numeric,
            receive_mask=receive_mask,
            bad_mask=bad_mask,
            bad_violation=bad_violation,
            target_mask=target_mask,
            counters=counters,
            hashes=hashes,
        )
        group.feed_frame(
            pd.DataFrame(
                {
                    "file": files,
                    "publisher": numeric["publisher_id"].astype("int64"),
                    "instrument": numeric["instrument_id"].astype("int64"),
                    "sequence": numeric["sequence"].astype("int64"),
                    "flags": flags,
                    "target": target_mask.astype("int64"),
                    "receive": receive_mask.astype("int64"),
                    "bad": bad_violation.astype("int64"),
                }
            )
        )
    group.finish()
    return _finalize_source(
        spec=spec,
        rows=rows,
        counters=counters,
        hashes=hashes,
        coverage=coverage,
        group=group.result(),
        file_regressions=file_regressions,
        ordinal_regressions=ordinal_regressions,
    )


def _classify_primary_batch(
    *,
    spec: dict[str, Any],
    runtime: dict[str, Any],
    batch: pa.RecordBatch,
    arrays: dict[str, np.ndarray],
    receive_mask: np.ndarray,
    bad_mask: np.ndarray,
    bad_violation: np.ndarray,
    target_mask: np.ndarray,
    counters: dict[str, Counter[str]],
    hashes: dict[str, Any],
) -> None:
    counters["all"]["bad_flag_rows"] += int(bad_mask.sum())
    counters["all"]["bad_snapshot_rows"] += int(
        (bad_mask & ((arrays["flags"] & F_SNAPSHOT) != 0)).sum()
    )
    counters["all"]["receive_before_rows"] += int(receive_mask.sum())
    counters["all"]["bad_old_rule_violations"] += int(bad_violation.sum())
    counters["all"]["target_overlap_rows"] += int(
        (receive_mask & bad_violation).sum()
    )
    target_indices = np.flatnonzero(target_mask)
    if not len(target_indices):
        return
    actions = _take_strings(batch.column("action"), target_indices)
    sides = _take_strings(batch.column("side"), target_indices)
    expected_instruments, dates = _expected_instruments_and_dates(
        arrays["ts_recv"][target_indices], runtime
    )
    states = _market_states(arrays["ts_recv"][target_indices], runtime)
    start_ns = runtime["start_ns"]
    end_ns = runtime["end_ns"]
    for position, row_index in enumerate(target_indices.tolist()):
        recv = int(arrays["ts_recv"][row_index])
        event = int(arrays["ts_event"][row_index])
        publisher = int(arrays["publisher_id"][row_index])
        instrument = int(arrays["instrument_id"][row_index])
        action = actions[position]
        side = sides[position]
        flags = int(arrays["flags"][row_index])
        delta = int(arrays["ts_in_delta"][row_index])
        sequence = int(arrays["sequence"][row_index])
        file_index = int(arrays["source_file_index"][row_index])
        ordinal = int(arrays["source_row_ordinal"][row_index])
        date_label = dates[position]
        expected_instrument = int(expected_instruments[position])
        state = states[position]
        structural_invalid = (
            publisher != EXPECTED_PUBLISHER
            or expected_instrument < 0
            or instrument != expected_instrument
            or action not in ALLOWED_ACTIONS
            or recv < start_ns
            or recv >= end_ns
            or event >= end_ns
        )
        canonical = _canonical_row(
            spec["request_id"], file_index, ordinal, recv, event, publisher,
            instrument, action, side, flags, delta, sequence
        )
        hashes["target"].update(canonical)
        counters["target"]["rows"] += 1
        if receive_mask[row_index]:
            hashes["receive"].update(canonical)
            taxonomy = _primary_receive_class(
                structural_invalid, flags, delta, recv, event
            )
            _update_receive_counters(
                counters, taxonomy, date_label, action, side, flags, state,
                event - recv
            )
        if bad_violation[row_index]:
            hashes["bad"].update(canonical)
            taxonomy = _primary_bad_class(
                structural_invalid, flags, recv, event, action
            )
            _update_bad_counters(
                counters, taxonomy, action, side, flags, state,
                bool(receive_mask[row_index])
            )


def _classify_reference_batch(
    *,
    spec: dict[str, Any],
    runtime: dict[str, Any],
    batch: pa.RecordBatch,
    numeric: pd.DataFrame,
    receive_mask: np.ndarray,
    bad_mask: np.ndarray,
    bad_violation: np.ndarray,
    target_mask: np.ndarray,
    counters: dict[str, Counter[str]],
    hashes: dict[str, Any],
) -> None:
    counters["all"].update(
        {
            "bad_flag_rows": int(np.count_nonzero(bad_mask)),
            "bad_snapshot_rows": int(
                np.count_nonzero(
                    bad_mask
                    & ((numeric["flags"].astype("int64").to_numpy() & F_SNAPSHOT) != 0)
                )
            ),
            "receive_before_rows": int(np.count_nonzero(receive_mask)),
            "bad_old_rule_violations": int(np.count_nonzero(bad_violation)),
            "target_overlap_rows": int(
                np.count_nonzero(receive_mask & bad_violation)
            ),
        }
    )
    positions = np.flatnonzero(target_mask)
    if positions.size == 0:
        return
    action_values = _take_strings(batch.column("action"), positions)
    side_values = _take_strings(batch.column("side"), positions)
    start_ns = runtime["start_ns"]
    end_ns = runtime["end_ns"]
    for offset, index in enumerate(positions.tolist()):
        row = numeric.iloc[index]
        recv = int(pd.Timestamp(row["ts_recv"]).value)
        event = int(pd.Timestamp(row["ts_event"]).value)
        publisher = int(row["publisher_id"])
        instrument = int(row["instrument_id"])
        action = action_values[offset]
        side = side_values[offset]
        flags = int(row["flags"])
        delta = int(row["ts_in_delta"])
        sequence = int(row["sequence"])
        file_index = int(row["source_file_index"])
        ordinal = int(row["source_row_ordinal"])
        date_label, expected_instrument = _reference_date_and_instrument(
            recv, runtime
        )
        state = _reference_market_state(recv, runtime)
        invalid = any(
            (
                publisher != EXPECTED_PUBLISHER,
                expected_instrument is None,
                expected_instrument is not None and instrument != expected_instrument,
                action not in ALLOWED_ACTIONS,
                not (start_ns <= recv < end_ns),
                event >= end_ns,
            )
        )
        canonical = _canonical_row(
            spec["request_id"], file_index, ordinal, recv, event, publisher,
            instrument, action, side, flags, delta, sequence
        )
        hashes["target"].update(canonical)
        counters["target"]["rows"] += 1
        if bool(receive_mask[index]):
            hashes["receive"].update(canonical)
            if invalid:
                taxonomy = "RB_STRUCTURAL_INVALID"
            elif flags & F_BAD_TS_RECV:
                taxonomy = "RB_FLAGGED_BAD_TS_RECV"
            elif delta in (INT32_MIN, INT32_MAX):
                taxonomy = "RB_UNFLAGGED_CLAMPED_TS_IN_DELTA"
            else:
                send = recv - delta
                taxonomy = (
                    "RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT"
                    if delta < 0 and send >= event
                    else "RB_UNFLAGGED_TIMESTAMP_INCOHERENT"
                )
            _update_receive_counters(
                counters, taxonomy, date_label, action, side, flags, state,
                event - recv
            )
        if bool(bad_violation[index]):
            hashes["bad"].update(canonical)
            snapshot = bool(flags & F_SNAPSHOT)
            day_start = recv - recv % DAY_NS
            snapshot_contradiction = snapshot and (
                recv != day_start
                or event >= day_start
                or event > recv
                or action not in SNAPSHOT_ACTIONS
            )
            if invalid:
                taxonomy = "BAD_STRUCTURAL_INVALID"
            elif snapshot_contradiction:
                taxonomy = "BAD_SNAPSHOT_CONTRADICTION"
            elif not snapshot:
                taxonomy = "BAD_NON_SNAPSHOT_DOCUMENTED"
            else:
                taxonomy = "BAD_OTHER_UNRESOLVED"
            _update_bad_counters(
                counters, taxonomy, action, side, flags, state,
                bool(receive_mask[index])
            )


def _primary_receive_class(
    invalid: bool, flags: int, delta: int, recv: int, event: int
) -> str:
    if invalid:
        return "RB_STRUCTURAL_INVALID"
    if flags & F_BAD_TS_RECV:
        return "RB_FLAGGED_BAD_TS_RECV"
    if delta in (INT32_MIN, INT32_MAX):
        return "RB_UNFLAGGED_CLAMPED_TS_IN_DELTA"
    if delta < 0 and recv - delta >= event:
        return "RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT"
    return "RB_UNFLAGGED_TIMESTAMP_INCOHERENT"


def _primary_bad_class(
    invalid: bool, flags: int, recv: int, event: int, action: str
) -> str:
    if invalid:
        return "BAD_STRUCTURAL_INVALID"
    snapshot = bool(flags & F_SNAPSHOT)
    day_start = recv - recv % DAY_NS
    if snapshot and (
        recv != day_start
        or event >= day_start
        or event > recv
        or action not in SNAPSHOT_ACTIONS
    ):
        return "BAD_SNAPSHOT_CONTRADICTION"
    if not snapshot:
        return "BAD_NON_SNAPSHOT_DOCUMENTED"
    return "BAD_OTHER_UNRESOLVED"


def _update_receive_counters(
    counters: dict[str, Counter[str]],
    taxonomy: str,
    date_label: str,
    action: str,
    side: str,
    flags: int,
    state: str,
    lead_ns: int,
) -> None:
    counters["receive_taxonomy"][taxonomy] += 1
    counters["receive_date"][date_label] += 1
    counters["receive_action"][action] += 1
    counters["receive_side"][side] += 1
    counters["receive_flags"][str(flags)] += 1
    counters["receive_state"][state] += 1
    counters["receive_lead_bin"][_lead_bin(lead_ns)] += 1
    counters["receive_snapshot"][str(bool(flags & F_SNAPSHOT)).lower()] += 1
    counters["receive_reset"][str(action == "R").lower()] += 1


def _update_bad_counters(
    counters: dict[str, Counter[str]],
    taxonomy: str,
    action: str,
    side: str,
    flags: int,
    state: str,
    receive_overlap: bool,
) -> None:
    counters["bad_taxonomy"][taxonomy] += 1
    counters["bad_action"][action] += 1
    counters["bad_side"][side] += 1
    counters["bad_flags"][str(flags)] += 1
    counters["bad_state"][state] += 1
    counters["bad_snapshot"][str(bool(flags & F_SNAPSHOT)).lower()] += 1
    counters["bad_receive_overlap"][str(receive_overlap).lower()] += 1


class PrimaryGroupCollector:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.pending: dict[str, Any] | None = None
        self.seen: set[tuple[int, int, int, int]] = set()
        self.counters: dict[str, Counter[str]] = {
            "group_size_bin": Counter(),
            "target_count_bin": Counter(),
            "f_last_count": Counter(),
            "snapshot_count_bin": Counter(),
            "noncontiguous_reuse": Counter(),
        }
        self.digest = hashlib.sha256()
        self.target_groups = 0

    def feed(
        self,
        *,
        files: np.ndarray,
        publishers: np.ndarray,
        instruments: np.ndarray,
        sequences: np.ndarray,
        flags: np.ndarray,
        target_mask: np.ndarray,
        receive_mask: np.ndarray,
        bad_mask: np.ndarray,
    ) -> None:
        count = len(files)
        if count == 0:
            return
        change = np.flatnonzero(
            (files[1:] != files[:-1])
            | (publishers[1:] != publishers[:-1])
            | (instruments[1:] != instruments[:-1])
            | (sequences[1:] != sequences[:-1])
        ) + 1
        starts = np.concatenate((np.array([0]), change))
        ends = np.concatenate((change, np.array([count])))
        target_counts = np.add.reduceat(target_mask.astype(np.int64), starts)
        receive_counts = np.add.reduceat(receive_mask.astype(np.int64), starts)
        bad_counts = np.add.reduceat(bad_mask.astype(np.int64), starts)
        last_counts = np.add.reduceat(
            ((flags & F_LAST) != 0).astype(np.int64), starts
        )
        snapshot_counts = np.add.reduceat(
            ((flags & F_SNAPSHOT) != 0).astype(np.int64), starts
        )
        candidate_indices = sorted(
            set(np.flatnonzero(target_counts > 0).tolist())
            | {0, len(starts) - 1}
        )
        summaries = []
        for idx in candidate_indices:
            start = int(starts[idx])
            summaries.append(
                {
                    "key": (
                        int(files[start]),
                        int(publishers[start]),
                        int(instruments[start]),
                        int(sequences[start]),
                    ),
                    "size": int(ends[idx] - starts[idx]),
                    "target": int(target_counts[idx]),
                    "receive": int(receive_counts[idx]),
                    "bad": int(bad_counts[idx]),
                    "last": int(last_counts[idx]),
                    "snapshot": int(snapshot_counts[idx]),
                }
            )
        self._consume_summaries(summaries)

    def _consume_summaries(self, summaries: list[dict[str, Any]]) -> None:
        if not summaries:
            return
        first = summaries[0]
        if self.pending is not None:
            if self.pending["key"] == first["key"]:
                for field in ("size", "target", "receive", "bad", "last", "snapshot"):
                    self.pending[field] += first[field]
                summaries = [self.pending, *summaries[1:]]
                self.pending = None
            else:
                self._finalize(self.pending)
                self.pending = None
        for summary in summaries[:-1]:
            if summary["target"]:
                self._finalize(summary)
        self.pending = summaries[-1]

    def _finalize(self, summary: dict[str, Any]) -> None:
        if not summary["target"]:
            return
        key = summary["key"]
        reused = key in self.seen
        self.seen.add(key)
        self.target_groups += 1
        self.counters["group_size_bin"][_count_bin(summary["size"])] += 1
        self.counters["target_count_bin"][_count_bin(summary["target"])] += 1
        self.counters["f_last_count"][str(summary["last"])] += 1
        self.counters["snapshot_count_bin"][_count_bin(summary["snapshot"])] += 1
        self.counters["noncontiguous_reuse"][str(reused).lower()] += 1
        self.digest.update(
            (
                f"{self.request_id}|{key[0]}|{key[1]}|{key[2]}|{key[3]}|"
                f"{summary['size']}|{summary['target']}|{summary['receive']}|"
                f"{summary['bad']}|{summary['last']}|{summary['snapshot']}\n"
            ).encode()
        )

    def finish(self) -> None:
        if self.pending is not None:
            self._finalize(self.pending)
            self.pending = None

    def result(self) -> dict[str, Any]:
        return {
            "target_event_groups": self.target_groups,
            "counters": _serialize_counters(self.counters),
            "ordered_group_checksum": self.digest.hexdigest(),
        }


class ReferenceGroupCollector:
    def __init__(self, request_id: str) -> None:
        self.request_id = request_id
        self.pending: dict[str, Any] | None = None
        self.closed_keys: set[tuple[int, int, int, int]] = set()
        self.stats = {
            "group_size_bin": Counter(),
            "target_count_bin": Counter(),
            "f_last_count": Counter(),
            "snapshot_count_bin": Counter(),
            "noncontiguous_reuse": Counter(),
        }
        self.checksum = hashlib.sha256()
        self.group_count = 0

    def feed_frame(self, frame: pd.DataFrame) -> None:
        if frame.empty:
            return
        key_columns = ["file", "publisher", "instrument", "sequence"]
        changes = frame[key_columns].ne(frame[key_columns].shift()).any(axis=1)
        changes.iloc[0] = True
        group_ids = changes.cumsum()
        frame = frame.copy()
        frame["last"] = (frame["flags"].astype("int64") & F_LAST) != 0
        frame["snapshot"] = (frame["flags"].astype("int64") & F_SNAPSHOT) != 0
        grouped = frame.groupby(group_ids, sort=False, observed=True)
        starts = np.flatnonzero(changes.to_numpy())
        sizes = grouped.size().to_numpy(dtype=np.int64)
        target_counts = grouped["target"].sum().to_numpy(dtype=np.int64)
        receive_counts = grouped["receive"].sum().to_numpy(dtype=np.int64)
        bad_counts = grouped["bad"].sum().to_numpy(dtype=np.int64)
        last_counts = grouped["last"].sum().to_numpy(dtype=np.int64)
        snapshot_counts = grouped["snapshot"].sum().to_numpy(dtype=np.int64)
        candidate_indices = sorted(
            set(np.flatnonzero(target_counts > 0).tolist())
            | {0, len(starts) - 1}
        )
        summaries: list[dict[str, Any]] = []
        for group_index in candidate_indices:
            first = frame.iloc[int(starts[group_index])]
            summaries.append(
                {
                    "key": (
                        int(first["file"]),
                        int(first["publisher"]),
                        int(first["instrument"]),
                        int(first["sequence"]),
                    ),
                    "size": int(sizes[group_index]),
                    "target": int(target_counts[group_index]),
                    "receive": int(receive_counts[group_index]),
                    "bad": int(bad_counts[group_index]),
                    "last": int(last_counts[group_index]),
                    "snapshot": int(snapshot_counts[group_index]),
                }
            )
        self._accept(summaries)

    def _accept(self, summaries: list[dict[str, Any]]) -> None:
        if not summaries:
            return
        first = summaries[0]
        if self.pending is not None and self.pending["key"] == first["key"]:
            for field in ("size", "target", "receive", "bad", "last", "snapshot"):
                self.pending[field] += first[field]
        else:
            if self.pending is not None:
                self._close(self.pending)
            self.pending = first
        if len(summaries) == 1:
            return
        self._close(self.pending)
        self.pending = None
        for item in summaries[1:-1]:
            self._close(item)
        self.pending = summaries[-1]

    def _close(self, item: dict[str, Any]) -> None:
        if not item["target"]:
            return
        key = item["key"]
        reused = key in self.closed_keys
        self.closed_keys.add(key)
        self.group_count += 1
        self.stats["group_size_bin"][_count_bin(item["size"])] += 1
        self.stats["target_count_bin"][_count_bin(item["target"])] += 1
        self.stats["f_last_count"][str(item["last"])] += 1
        self.stats["snapshot_count_bin"][_count_bin(item["snapshot"])] += 1
        self.stats["noncontiguous_reuse"][str(reused).lower()] += 1
        text = (
            f"{self.request_id}|{key[0]}|{key[1]}|{key[2]}|{key[3]}|"
            f"{item['size']}|{item['target']}|{item['receive']}|{item['bad']}|"
            f"{item['last']}|{item['snapshot']}\n"
        )
        self.checksum.update(text.encode("utf-8"))

    def finish(self) -> None:
        if self.pending is not None:
            self._close(self.pending)
            self.pending = None

    def result(self) -> dict[str, Any]:
        return {
            "target_event_groups": self.group_count,
            "counters": _serialize_counters(self.stats),
            "ordered_group_checksum": self.checksum.hexdigest(),
        }


def _finalize_source(
    *,
    spec: dict[str, Any],
    rows: int,
    counters: dict[str, Counter[str]],
    hashes: dict[str, Any],
    coverage: dict[str, Any],
    group: dict[str, Any],
    file_regressions: int,
    ordinal_regressions: int,
) -> dict[str, Any]:
    windows = _finalize_windows(spec, coverage)
    expected = spec["sealed_expected_counts"]
    receive_count = counters["all"]["receive_before_rows"]
    bad_count = counters["all"]["bad_old_rule_violations"]
    receive_finding = None
    if int(expected["receive_before_event_rows"]) > 0:
        receive_finding = _receive_finding(counters["receive_taxonomy"])
    bad_finding = None
    if int(expected["bad_ts_recv_old_snapshot_rule_violations"]) > 0:
        bad_finding = _bad_finding(counters["bad_taxonomy"])
    calendar_finding = None
    if int(expected["incomplete_prediction_windows"]) > 0:
        calendar_finding = _calendar_finding(spec, windows)
    family_findings = {
        key: value
        for key, value in {
            "receive_before_event": receive_finding,
            "bad_ts_recv_old_snapshot_rule": bad_finding,
            "calendar_coverage": calendar_finding,
        }.items()
        if value is not None
    }
    request_classification = _request_classification(family_findings)
    integrity = {
        "footer_and_scan_rows_match": rows == int(spec["footer_record_count"]),
        "receive_before_count_reproduced": (
            receive_count == int(expected["receive_before_event_rows"])
        ),
        "bad_old_rule_violation_count_reproduced": (
            bad_count
            == int(expected["bad_ts_recv_old_snapshot_rule_violations"])
        ),
        "incomplete_window_count_reproduced": (
            sum(item["reproduced_disposition"] == "INCOMPLETE_SOURCE" for item in windows)
            == int(expected["incomplete_prediction_windows"])
        ),
        "source_file_order_nondecreasing": file_regressions == 0,
        "source_ordinals_strict": ordinal_regressions == 0,
        "every_receive_target_classified": (
            sum(counters["receive_taxonomy"].values()) == receive_count
        ),
        "every_bad_violation_classified": (
            sum(counters["bad_taxonomy"].values()) == bad_count
        ),
        "no_prohibited_columns_selected": _columns_are_value_blind(),
    }
    return {
        "request_id": spec["request_id"],
        "schema": spec["schema"],
        "selected_dates": spec["selected_dates"],
        "rows_scanned": rows,
        "sealed_normalized_payload_sha256": spec["normalized_payload"]["sha256"],
        "sealed_counts": expected,
        "reproduced_counts": {
            "receive_before_event_rows": receive_count,
            "bad_ts_recv_flag_rows": counters["all"]["bad_flag_rows"],
            "bad_ts_recv_snapshot_rows": counters["all"]["bad_snapshot_rows"],
            "bad_ts_recv_old_snapshot_rule_violations": bad_count,
            "target_overlap_rows": counters["all"]["target_overlap_rows"],
            "target_union_rows": counters["target"]["rows"],
            "incomplete_prediction_windows": sum(
                item["reproduced_disposition"] == "INCOMPLETE_SOURCE"
                for item in windows
            ),
        },
        "technical_cross_tabs": _serialize_counters(counters),
        "target_identity_checksums": {
            "target_union_ordered_sha256": hashes["target"].hexdigest(),
            "receive_before_ordered_sha256": hashes["receive"].hexdigest(),
            "bad_old_rule_violation_ordered_sha256": hashes["bad"].hexdigest(),
        },
        "native_event_grouping": group,
        "prediction_windows": windows,
        "family_findings": family_findings,
        "request_classification": request_classification,
        "integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        "market_values_or_outcomes_accessed_or_reported": False,
    }


def _assemble_payload(
    sources: list[dict[str, Any]],
    *,
    implementation: str,
    context: dict[str, Any],
) -> dict[str, Any]:
    request_classes = {
        source["request_id"]: source["request_classification"]
        for source in sources
    }
    class_counts = Counter(request_classes.values())
    rows = sum(source["rows_scanned"] for source in sources)
    receive = sum(
        source["reproduced_counts"]["receive_before_event_rows"]
        for source in sources
    )
    bad = sum(
        source["reproduced_counts"][
            "bad_ts_recv_old_snapshot_rule_violations"
        ]
        for source in sources
    )
    incomplete = sum(
        source["reproduced_counts"]["incomplete_prediction_windows"]
        for source in sources
    )
    source_integrity = all(source["formal_integrity_pass"] for source in sources)
    explained = all(
        value in {
            "DOCUMENTED_VALID_SEMANTICS",
            "EXPECTED_CALENDAR_UNAVAILABILITY",
        }
        for value in request_classes.values()
    )
    recommendation = (
        {"id": RECOMMENDATION_ID, "text": RECOMMENDATION_TEXT}
        if explained
        else {"id": "NONE", "text": None}
    )
    aggregate = {
        "failed_requests_processed": len(sources),
        "rows_scanned": rows,
        "receive_before_event_rows": receive,
        "bad_ts_recv_old_rule_violations": bad,
        "incomplete_prediction_windows": incomplete,
        "request_classifications": request_classes,
        "request_classification_counts": dict(sorted(class_counts.items())),
        "recommendation": recommendation,
    }
    integrity = {
        "step5b_failure_preserved": (
            context["step5b_verdict"]["status"] == EXPECTED_STEP5B_STATUS
        ),
        "exactly_13_failed_requests_processed": len(sources) == EXPECTED_REQUESTS,
        "all_144352215_rows_scanned": rows == EXPECTED_ROWS,
        "all_719524_receive_before_rows_reproduced": receive == EXPECTED_RECEIVE_BEFORE,
        "all_174_bad_old_rule_violations_reproduced": (
            bad == EXPECTED_BAD_OLD_RULE_VIOLATIONS
        ),
        "all_four_incomplete_windows_reproduced": (
            incomplete == EXPECTED_INCOMPLETE_WINDOWS
        ),
        "every_source_integrity_check_passed": source_integrity,
        "every_request_classified_once": len(request_classes) == EXPECTED_REQUESTS,
        "recommendation_count_at_most_one": recommendation["id"] in {
            "NONE",
            RECOMMENDATION_ID,
        },
        "no_prohibited_columns_selected": _columns_are_value_blind(),
        "no_market_values_outcomes_features_signals_execution_or_pnl": True,
        "no_data_filter_repair_replacement_reacquisition_or_charge": True,
    }
    return {
        "sources": sources,
        "aggregate": aggregate,
        "formal_integrity_checks": integrity,
        "formal_integrity_pass": all(integrity.values()),
        "restrictions": {
            "selected_columns": list(COLUMNS),
            "market_values_or_outcomes_accessed_or_reported": False,
            "features_relationships_or_signals_calculated": False,
            "execution_trades_pnl_r_or_returns_calculated": False,
            "data_filtered_repaired_replaced_or_reacquired": False,
            "charge_incurred_usd": 0.0,
        },
    }


def _receive_finding(counter: Counter[str]) -> str:
    if counter["RB_STRUCTURAL_INVALID"] or counter[
        "RB_UNFLAGGED_TIMESTAMP_INCOHERENT"
    ]:
        return "GENUINE_SOURCE_FAILURE"
    if counter["RB_UNFLAGGED_CLAMPED_TS_IN_DELTA"]:
        return "UNRESOLVED"
    documented = counter["RB_FLAGGED_BAD_TS_RECV"] + counter[
        "RB_UNFLAGGED_NEGATIVE_DELTA_COHERENT"
    ]
    return "DOCUMENTED_VALID_SEMANTICS" if documented == sum(counter.values()) else "UNRESOLVED"


def _bad_finding(counter: Counter[str]) -> str:
    if counter["BAD_STRUCTURAL_INVALID"] or counter[
        "BAD_SNAPSHOT_CONTRADICTION"
    ]:
        return "GENUINE_SOURCE_FAILURE"
    if counter["BAD_OTHER_UNRESOLVED"]:
        return "UNRESOLVED"
    return (
        "DOCUMENTED_VALID_SEMANTICS"
        if counter["BAD_NON_SNAPSHOT_DOCUMENTED"] == sum(counter.values())
        else "UNRESOLVED"
    )


def _calendar_finding(spec: dict[str, Any], windows: list[dict[str, Any]]) -> str:
    incomplete = [
        item for item in windows if item["reproduced_disposition"] == "INCOMPLETE_SOURCE"
    ]
    expected = {
        ("2022-04-15", "LONDON"),
        ("2022-04-15", "NEW_YORK"),
    }
    observed = {(item["trade_date"], item["session"]) for item in incomplete}
    other_complete = all(
        item["reproduced_disposition"] == "COMPLETE"
        for item in windows
        if (item["trade_date"], item["session"]) not in expected
    )
    if observed == expected and other_complete:
        return "EXPECTED_CALENDAR_UNAVAILABILITY"
    if any(item["trade_date"] != "2022-04-15" for item in incomplete):
        return "GENUINE_SOURCE_FAILURE"
    return "UNRESOLVED"


def _request_classification(findings: dict[str, str]) -> str:
    values = set(findings.values())
    if "GENUINE_SOURCE_FAILURE" in values:
        return "GENUINE_SOURCE_FAILURE"
    if "UNRESOLVED" in values:
        return "UNRESOLVED"
    if values == {"EXPECTED_CALENDAR_UNAVAILABILITY"}:
        return "EXPECTED_CALENDAR_UNAVAILABILITY"
    if values == {"DOCUMENTED_VALID_SEMANTICS"}:
        return "DOCUMENTED_VALID_SEMANTICS"
    return "UNRESOLVED"


def _source_runtime(spec: dict[str, Any]) -> dict[str, Any]:
    start_ns = _iso_ns(spec["request"]["start"])
    end_ns = _iso_ns(spec["request"]["end"])
    dates = []
    chicago = ZoneInfo("America/Chicago")
    for row in spec["selected_date_rows"]:
        label = row["trade_date"]
        selected = date.fromisoformat(label)
        day_start = _iso_ns(f"{label}T00:00:00Z")
        maintenance = int(
            datetime.combine(selected, time(16, 0), chicago).astimezone(UTC).timestamp()
            * 1_000_000_000
        )
        preopen = int(
            datetime.combine(selected, time(16, 45), chicago).astimezone(UTC).timestamp()
            * 1_000_000_000
        )
        reopen = int(
            datetime.combine(selected, time(17, 0), chicago).astimezone(UTC).timestamp()
            * 1_000_000_000
        )
        dates.append(
            {
                "label": label,
                "start": day_start,
                "end": day_start + DAY_NS,
                "expected_instrument": int(
                    spec["expected_instrument_id_by_date"][label]
                ),
                "maintenance": maintenance,
                "preopen": preopen,
                "reopen": reopen,
                "cutoffs": {
                    "LONDON": _iso_ns(row["london_decision_at_utc"]),
                    "NEW_YORK": _iso_ns(row["new_york_decision_at_utc"]),
                },
            }
        )
    return {"start_ns": start_ns, "end_ns": end_ns, "dates": dates}


def _expected_instruments_and_dates(
    recv: np.ndarray, runtime: dict[str, Any]
) -> tuple[np.ndarray, list[str]]:
    expected = np.full(len(recv), -1, dtype=np.int64)
    labels = ["OUTSIDE_REQUEST"] * len(recv)
    for item in runtime["dates"]:
        mask = (recv >= item["start"]) & (recv < item["end"])
        expected[mask] = item["expected_instrument"]
        for index in np.flatnonzero(mask).tolist():
            labels[index] = item["label"]
    return expected, labels


def _reference_date_and_instrument(
    recv: int, runtime: dict[str, Any]
) -> tuple[str, int | None]:
    for item in runtime["dates"]:
        if item["start"] <= recv < item["end"]:
            return item["label"], int(item["expected_instrument"])
    return "OUTSIDE_REQUEST", None


def _market_states(recv: np.ndarray, runtime: dict[str, Any]) -> list[str]:
    states = ["UNCLASSIFIED"] * len(recv)
    for item in runtime["dates"]:
        in_date = (recv >= item["start"]) & (recv < item["end"])
        maintenance = in_date & (recv >= item["maintenance"]) & (
            recv < item["preopen"]
        )
        preopen = in_date & (recv >= item["preopen"]) & (recv < item["reopen"])
        continuous = in_date & ~maintenance & ~preopen
        for index in np.flatnonzero(maintenance).tolist():
            states[index] = "MAINTENANCE"
        for index in np.flatnonzero(preopen).tolist():
            states[index] = "PRE_OPEN"
        for index in np.flatnonzero(continuous).tolist():
            states[index] = "CONTINUOUS_MATCHING"
    return states


def _reference_market_state(recv: int, runtime: dict[str, Any]) -> str:
    for item in runtime["dates"]:
        if item["start"] <= recv < item["end"]:
            if item["maintenance"] <= recv < item["preopen"]:
                return "MAINTENANCE"
            if item["preopen"] <= recv < item["reopen"]:
                return "PRE_OPEN"
            return "CONTINUOUS_MATCHING"
    return "UNCLASSIFIED"


def _new_coverage(runtime: dict[str, Any]) -> dict[str, Any]:
    return {
        item["label"]: {
            "rows": 0,
            "first": None,
            "last": None,
            "window_counts": {"LONDON": 0, "NEW_YORK": 0},
        }
        for item in runtime["dates"]
    }


def _update_coverage_numpy(coverage: dict[str, Any], recv: np.ndarray) -> None:
    for label, item in coverage.items():
        start = _iso_ns(f"{label}T00:00:00Z")
        values = recv[(recv >= start) & (recv < start + DAY_NS)]
        if len(values):
            item["rows"] += int(len(values))
            first = int(values[0])
            last = int(values[-1])
            item["first"] = first if item["first"] is None else min(item["first"], first)
            item["last"] = last if item["last"] is None else max(item["last"], last)


def _update_coverage_pandas(
    coverage: dict[str, Any], recv_series: pd.Series
) -> None:
    recv = recv_series.astype("int64")
    for label, item in coverage.items():
        start = _iso_ns(f"{label}T00:00:00Z")
        selected = recv[(recv >= start) & (recv < start + DAY_NS)]
        if not selected.empty:
            item["rows"] += int(selected.size)
            first = int(selected.iloc[0])
            last = int(selected.iloc[-1])
            item["first"] = first if item["first"] is None else min(item["first"], first)
            item["last"] = last if item["last"] is None else max(item["last"], last)


def _finalize_windows(
    spec: dict[str, Any], coverage: dict[str, Any]
) -> list[dict[str, Any]]:
    windows = []
    sealed = {
        (item["trade_date"], item["session"]): item["coverage_disposition"]
        for item in spec["sealed_prediction_window_coverage"]
    }
    runtime = _source_runtime(spec)
    for date_item in runtime["dates"]:
        label = date_item["label"]
        item = coverage[label]
        for session, cutoff in date_item["cutoffs"].items():
            lookback = cutoff - LOOKBACK_NS
            first = item["first"]
            last = item["last"]
            if item["rows"] == 0:
                disposition = "UNAVAILABLE_DOCUMENTED"
            elif first is not None and last is not None and first <= lookback and last >= cutoff:
                disposition = "COMPLETE"
            else:
                disposition = "INCOMPLETE_SOURCE"
            windows.append(
                {
                    "trade_date": label,
                    "session": session,
                    "official_calendar_state": (
                        "CME_GOOD_FRIDAY_HOLIDAY"
                        if label == "2022-04-15"
                        else "STANDARD_SELECTED_DATE"
                    ),
                    "sealed_disposition": sealed[(label, session)],
                    "reproduced_disposition": disposition,
                    "date_has_rows": item["rows"] > 0,
                    "first_receive_at_or_before_lookback": (
                        first is not None and first <= lookback
                    ),
                    "last_receive_at_or_after_cutoff": (
                        last is not None and last >= cutoff
                    ),
                    "market_values_accessed_or_reported": False,
                }
            )
    return windows


def _new_counters() -> dict[str, Counter[str]]:
    return {
        "all": Counter(),
        "target": Counter(),
        "receive_taxonomy": Counter(),
        "receive_date": Counter(),
        "receive_action": Counter(),
        "receive_side": Counter(),
        "receive_flags": Counter(),
        "receive_state": Counter(),
        "receive_lead_bin": Counter(),
        "receive_snapshot": Counter(),
        "receive_reset": Counter(),
        "bad_taxonomy": Counter(),
        "bad_action": Counter(),
        "bad_side": Counter(),
        "bad_flags": Counter(),
        "bad_state": Counter(),
        "bad_snapshot": Counter(),
        "bad_receive_overlap": Counter(),
    }


def _new_hashes() -> dict[str, Any]:
    return {
        "target": hashlib.sha256(),
        "receive": hashlib.sha256(),
        "bad": hashlib.sha256(),
    }


def _lead_bin(value: int) -> str:
    if value <= 1_000:
        return "1_TO_1K"
    if value <= 10_000:
        return "1K_TO_10K"
    if value <= 100_000:
        return "10K_TO_100K"
    if value <= 1_000_000:
        return "100K_TO_1M"
    return "GT_1M"


def _count_bin(value: int) -> str:
    if value == 0:
        return "0"
    if value == 1:
        return "1"
    if value == 2:
        return "2"
    if value <= 5:
        return "3_TO_5"
    if value <= 10:
        return "6_TO_10"
    return "GT_10"


def _canonical_row(*values: Any) -> bytes:
    return ("|".join(str(value) for value in values) + "\n").encode("utf-8")


def _arrow_ints(array: pa.Array) -> np.ndarray:
    if pa.types.is_timestamp(array.type):
        array = pc.cast(array, pa.int64())
    return np.asarray(array.to_numpy(zero_copy_only=False), dtype=np.int64)


def _take_strings(array: pa.Array, indices: np.ndarray) -> list[str]:
    if not len(indices):
        return []
    taken = pc.take(array, pa.array(indices, type=pa.int64()))
    return [str(value) for value in taken.to_pylist()]


def _iso_ns(value: str) -> int:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return int(parsed.timestamp() * 1_000_000_000)


def _serialize_counters(
    counters: dict[str, Counter[str]]
) -> dict[str, dict[str, int]]:
    return {
        key: {name: int(value) for name, value in sorted(counter.items())}
        for key, counter in sorted(counters.items())
    }


def _columns_are_value_blind() -> bool:
    return not any(
        token in name.lower()
        for name in COLUMNS
        for token in PROHIBITED_COLUMN_TOKENS
    )


def _verified_context(
    remote_root: Path, *, verify_payloads: bool
) -> dict[str, Any]:
    _verify_hash(PROTOCOL_PATH, EXPECTED_PROTOCOL_SHA256)
    _verify_hash(INVENTORY_PATH, EXPECTED_INVENTORY_SHA256)
    _verify_hash(FREEZE_PATH, EXPECTED_FREEZE_SHA256)
    correction = _read_json(CORRECTION_PATH)
    protocol = _read_json(PROTOCOL_PATH)
    inventory = _read_json(INVENTORY_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Freeze no longer binds the expected protocol")
    if freeze["source_inventory"]["sha256"] != EXPECTED_INVENTORY_SHA256:
        raise ValueError("Freeze no longer binds the expected inventory")
    if protocol["predecessor_preservation"]["required_step5b_status"] != EXPECTED_STEP5B_STATUS:
        raise ValueError("Protocol predecessor status changed")
    if correction["protocol_changed"] is not False:
        raise ValueError("The frozen Step 5B.1 protocol was changed")
    if correction["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Implementation correction does not bind the protocol")
    if correction["freeze_sha256"] != EXPECTED_FREEZE_SHA256:
        raise ValueError("Implementation correction does not bind the freeze")
    attempt = correction["preserved_attempt"]
    _verify_hash(Path(attempt["path"]), attempt["sha256"])
    if correction["corrected_tool_sha256"] != _sha256(Path(__file__)):
        raise ValueError("Corrected diagnostic tool differs from the recorded implementation correction")
    step5b_verdict_path = remote_root / "artifacts/step5b_budget_c_final/verdict.json"
    step5b_manifest_path = remote_root / "artifacts/step5b_budget_c_final/manifest.json"
    step5b_verdict = _read_json(step5b_verdict_path)
    step5b_manifest = _read_json(step5b_manifest_path)
    if step5b_verdict["status"] != EXPECTED_STEP5B_STATUS:
        raise ValueError("Step 5B verdict changed")
    if step5b_manifest["manifest_hash"] != protocol["predecessor_preservation"]["required_step5b_manifest_hash"]:
        raise ValueError("Step 5B manifest changed")
    for record in protocol["sealed_inputs"]["predecessor_files"]:
        _verify_hash(Path(record["path"]), record["sha256"])
    for source in inventory["sources"]:
        for key in ("quality", "lineage", "source_seal"):
            _verify_hash(Path(source[key]["path"]), source[key]["sha256"])
        payload = Path(source["normalized_payload"]["path"])
        if payload.stat().st_size != int(source["normalized_payload"]["bytes"]):
            raise ValueError(f"Payload size changed: {payload}")
        if verify_payloads:
            _verify_hash(payload, source["normalized_payload"]["sha256"])
        schema_names = pq.ParquetFile(payload).schema_arrow.names
        if any(name not in schema_names for name in COLUMNS):
            raise ValueError(f"Required technical column missing from {payload}")
    _verify_good_friday_raw_files(remote_root, inventory)
    return {
        "protocol": protocol,
        "inventory": inventory,
        "freeze": freeze,
        "implementation_scope_correction": correction,
        "step5b_verdict": step5b_verdict,
        "step5b_manifest": step5b_manifest,
    }


def _verify_good_friday_raw_files(
    remote_root: Path, inventory: dict[str, Any]
) -> None:
    acquisition_path = remote_root / "data/databento_gc_microstructure_budget_c_v01/acquisition_manifest.json"
    acquisition = _read_json(acquisition_path)
    by_id = {item["request_id"]: item for item in acquisition["requests"]}
    for request_id in ("Q017:mbo", "Q018:mbp-10"):
        request = by_id[request_id]
        matches = [
            record
            for record in request["local_files"]
            if "20220415" in Path(record["path"]).name
            and Path(record["path"]).suffixes[-2:] == [".dbn", ".zst"]
        ]
        if len(matches) != 1:
            raise ValueError(f"Expected one sealed Good Friday DBN file for {request_id}")
        _verify_hash(Path(matches[0]["path"]), matches[0]["sha256"])


def _assert_protocol_matches_code(protocol: dict[str, Any]) -> None:
    constants = protocol["constants"]
    if constants["flag_bad_ts_recv"] != F_BAD_TS_RECV:
        raise ValueError("F_BAD_TS_RECV code/protocol mismatch")
    if constants["flag_snapshot"] != F_SNAPSHOT:
        raise ValueError("F_SNAPSHOT code/protocol mismatch")
    if constants["flag_last"] != F_LAST:
        raise ValueError("F_LAST code/protocol mismatch")
    if set(constants["allowed_actions"]) != ALLOWED_ACTIONS:
        raise ValueError("Allowed-action registry changed")
    receive_ids = [
        item["id"]
        for item in protocol["receive_before_event_diagnostic"][
            "exclusive_row_taxonomy_in_precedence_order"
        ]
    ]
    if tuple(receive_ids) != RECEIVE_CLASSES:
        raise ValueError("Receive taxonomy code/protocol mismatch")
    bad_ids = [
        item["id"]
        for item in protocol["bad_ts_recv_diagnostic"][
            "exclusive_violation_taxonomy_in_precedence_order"
        ]
    ]
    if tuple(bad_ids) != BAD_CLASSES:
        raise ValueError("BAD_TS_RECV taxonomy code/protocol mismatch")
    if not _columns_are_value_blind():
        raise ValueError("A prohibited market-value column was selected")


def _seal(
    context: dict[str, Any], output: Path, artifacts: Path, report: Path
) -> None:
    if artifacts.exists():
        raise FileExistsError(f"Refusing to overwrite {artifacts}")
    if report.exists():
        raise FileExistsError(f"Refusing to overwrite {report}")
    primary_path = output / "primary_diagnostic.json"
    reference_path = output / "reference_diagnostic.json"
    primary = _read_json(primary_path)
    reference = _read_json(reference_path)
    reproduced = (
        primary["reproducible_payload"] == reference["reproducible_payload"]
    )
    primary_integrity = bool(
        primary["reproducible_payload"]["formal_integrity_pass"]
    )
    reference_integrity = bool(
        reference["reproducible_payload"]["formal_integrity_pass"]
    )
    if not primary_integrity or not reference_integrity:
        status = "FAIL_STEP_5B1_DIAGNOSTIC_INTEGRITY"
    elif not reproduced:
        status = "FAIL_STEP_5B1_DIAGNOSTIC_REPRODUCTION"
    else:
        status = "PASS_STEP_5B1_DIAGNOSTIC_REPRODUCTION"
    payload = primary["reproducible_payload"]
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_5B1_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS_STEP_5B1_DIAGNOSTIC_REPRODUCTION",
        "classification": "SOURCE_INTEGRITY_DIAGNOSTIC_ONLY",
        "research_or_validation_credit": "NONE",
        "completed_at_utc": _utc_now(),
        "step5b_original_status_preserved": context["step5b_verdict"]["status"],
        "step5b_original_formal_failure_changed": False,
        "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
        "inventory_sha256": EXPECTED_INVENTORY_SHA256,
        "freeze_sha256": EXPECTED_FREEZE_SHA256,
        "tool_sha256": _sha256(Path(__file__)),
        "implementation_scope_correction": _file_record(CORRECTION_PATH),
        "primary_diagnostic": _file_record(primary_path),
        "reference_diagnostic": _file_record(reference_path),
        "primary_integrity_pass": primary_integrity,
        "reference_integrity_pass": reference_integrity,
        "independent_reproduction_identical": reproduced,
        "aggregate": payload["aggregate"],
        "request_results": [
            {
                "request_id": source["request_id"],
                "schema": source["schema"],
                "family_findings": source["family_findings"],
                "classification": source["request_classification"],
                "integrity_pass": source["formal_integrity_pass"],
            }
            for source in payload["sources"]
        ],
        "recommendation": payload["aggregate"]["recommendation"],
        "recommendation_implemented": False,
        "data_filtered_repaired_replaced_or_reacquired": False,
        "charge_incurred_usd": 0.0,
        "market_values_or_outcomes_accessed_or_reported": False,
        "features_relationships_signals_execution_trades_or_pnl_calculated": False,
        "completion_policy": "Step 5B.1 is complete; stop before correction, recertification, or research.",
    }
    artifacts.mkdir(parents=True, exist_ok=False)
    verdict_path = artifacts / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    _write_report(report, verdict)
    manifest = {
        "version": "GC_MICROSTRUCTURE_STEP_5B1_MANIFEST_V0_1",
        "status": status,
        "created_at_utc": _utc_now(),
        "protocol": _file_record(PROTOCOL_PATH),
        "source_inventory": _file_record(INVENTORY_PATH),
        "freeze": _file_record(FREEZE_PATH),
        "implementation_scope_correction": _file_record(CORRECTION_PATH),
        "tool": _file_record(Path(__file__)),
        "inputs": [_file_record(primary_path), _file_record(reference_path)],
        "artifacts": [_file_record(verdict_path), _file_record(report)],
        "source_payloads": [
            {
                "request_id": source["request_id"],
                "path": source["normalized_payload"]["path"],
                "bytes": source["normalized_payload"]["bytes"],
                "sha256": source["normalized_payload"]["sha256"],
            }
            for source in context["inventory"]["sources"]
        ],
        "market_values_or_outcomes_accessed_or_reported": False,
        "manifest_hash": None,
    }
    manifest["manifest_hash"] = _canonical_json_hash(
        {**manifest, "manifest_hash": None}
    )
    _write_json_atomic(artifacts / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B1_SEALED",
                "status": status,
                "request_classifications": verdict["aggregate"][
                    "request_classification_counts"
                ],
                "recommendation": verdict["recommendation"]["id"],
                "independent_reproduction_identical": reproduced,
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _verify_seal(
    context: dict[str, Any], artifacts: Path, report: Path
) -> None:
    manifest_path = artifacts / "manifest.json"
    verdict_path = artifacts / "verdict.json"
    manifest = _read_json(manifest_path)
    verdict = _read_json(verdict_path)
    expected_manifest_hash = _canonical_json_hash(
        {**manifest, "manifest_hash": None}
    )
    if manifest["manifest_hash"] != expected_manifest_hash:
        raise ValueError("Step 5B.1 manifest hash mismatch")
    for record in (
        manifest["protocol"],
        manifest["source_inventory"],
        manifest["freeze"],
        manifest["implementation_scope_correction"],
        manifest["tool"],
        *manifest["inputs"],
        *manifest["artifacts"],
    ):
        _verify_file_record(record)
    for source in manifest["source_payloads"]:
        _verify_hash(Path(source["path"]), source["sha256"])
    if verdict["status"] != manifest["status"]:
        raise ValueError("Verdict and manifest status differ")
    if verdict["step5b_original_status_preserved"] != EXPECTED_STEP5B_STATUS:
        raise ValueError("Step 5B predecessor verdict was not preserved")
    if verdict["market_values_or_outcomes_accessed_or_reported"] is not False:
        raise ValueError("Prohibited value-access declaration changed")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5B1_SEAL_VERIFIED",
                "status": verdict["status"],
                "manifest_hash": manifest["manifest_hash"],
                "source_payloads_verified": len(manifest["source_payloads"]),
                "independent_reproduction_identical": verdict[
                    "independent_reproduction_identical"
                ],
                "market_values_or_outcomes_accessed": False,
                "charge_incurred_usd": 0.0,
            },
            sort_keys=True,
        )
    )


def _write_report(path: Path, verdict: dict[str, Any]) -> None:
    classes: dict[str, list[str]] = {}
    for row in verdict["request_results"]:
        classes.setdefault(row["classification"], []).append(row["request_id"])
    lines = [
        "# GC Microstructure Step 5B.1 — Metadata-Only Source Diagnostic",
        "",
        "## Formal diagnostic verdict",
        "",
        f"`{verdict['status']}`",
        "",
        "The original Step 5B verdict remains "
        f"`{verdict['step5b_original_status_preserved']}` and was not changed.",
        "",
        "## Reproduced technical scope",
        "",
        f"- Failed requests examined: {verdict['aggregate']['failed_requests_processed']}.",
        f"- Technical source rows scanned by each implementation: {verdict['aggregate']['rows_scanned']:,}.",
        f"- Receive-before-event occurrences: {verdict['aggregate']['receive_before_event_rows']:,}.",
        f"- Old snapshot-only BAD_TS_RECV violations: {verdict['aggregate']['bad_ts_recv_old_rule_violations']:,}.",
        f"- Incomplete prediction windows: {verdict['aggregate']['incomplete_prediction_windows']}.",
        f"- Independent outputs identical: `{str(verdict['independent_reproduction_identical']).lower()}`.",
        "",
        "## Request classifications",
        "",
    ]
    for classification in (
        "DOCUMENTED_VALID_SEMANTICS",
        "EXPECTED_CALENDAR_UNAVAILABILITY",
        "GENUINE_SOURCE_FAILURE",
        "UNRESOLVED",
    ):
        ids = classes.get(classification, [])
        lines.append(
            f"- `{classification}` ({len(ids)}): "
            + (", ".join(f"`{item}`" for item in ids) if ids else "none")
        )
    lines.extend(
        [
            "",
            "## Recommendation",
            "",
            f"`{verdict['recommendation']['id']}`",
            "",
            verdict["recommendation"]["text"] or "No amendment is recommended.",
            "",
            "The recommendation was not implemented.",
            "",
            "## Restrictions honored",
            "",
            "No source was filtered, repaired, relabeled, replaced, or reacquired. "
            "No charge was incurred. No price, depth, size, order-flow value, "
            "outcome, feature, relationship, signal, execution, trade, PnL, R "
            "multiple, or account return was inspected or calculated.",
            "",
            "Step 5B.1 stops here.",
        ]
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text("\n".join(lines) + "\n", encoding="utf-8")
    temp.replace(path)


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(
        json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    temp.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(8 * 1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _verify_hash(path: Path, expected: str) -> None:
    if not path.is_file():
        raise FileNotFoundError(path)
    actual = _sha256(path)
    if actual != expected:
        raise ValueError(f"SHA-256 mismatch for {path}: {actual} != {expected}")


def _file_record(path: Path) -> dict[str, Any]:
    path_text = (
        str(path.relative_to(REPO_ROOT)).replace("\\", "/")
        if path.is_relative_to(REPO_ROOT)
        else str(path)
    )
    return {"path": path_text, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _verify_file_record(record: dict[str, Any]) -> None:
    path = Path(record["path"])
    if not path.is_absolute():
        path = REPO_ROOT / path
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"Byte-size mismatch for {path}")
    _verify_hash(path, record["sha256"])


def _canonical_json_hash(payload: dict[str, Any]) -> str:
    encoded = json.dumps(payload, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def _utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
