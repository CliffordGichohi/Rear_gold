#!/usr/bin/env python3
"""Outcome-blind external-memory correction for GC Session Trigger Edge V2-R1."""

from __future__ import annotations

import argparse
import gc
import hashlib
import json
import os
import subprocess
import sys
import time
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator, Mapping, Sequence

import numpy as np
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.dataset as ds
import pyarrow.parquet as pq

import materialize_gc_session_trigger_edge_m2 as m2
import run_gc_session_trigger_edge_m2r1a1 as a1
import run_gc_session_trigger_edge_m2r2 as r2
import run_gc_session_trigger_edge_v2 as v2


ROOT = Path(__file__).resolve().parents[1]
CONTRACT_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_DISCOVERY_CONTRACT_V2_R1.md"
PROTOCOL_PATH = ROOT / "research_manifests/gc_session_trigger_edge_v2r1_protocol_v01.json"
PRE_VALUE_FREEZE_PATH = ROOT / "research_manifests/gc_session_trigger_edge_v2r1_pre_value_freeze_v01.json"
FREEZE_PATH = ROOT / "research_manifests/gc_session_trigger_edge_v2r1_freeze_v01.json"
DEFAULT_ENGINEERING_OUTPUT = ROOT / "research_artifacts/gc_session_trigger_edge_v2r1_engineering_v01"
DEFAULT_OUTPUT = ROOT / "research_artifacts/gc_session_trigger_edge_v2r1_v01"

PRIMARY_BATCH_ROWS = 65_536
REFERENCE_BATCH_ROWS = 32_768
RSS_CAP_BYTES = 4 * 1024**3
RSS_GUARD_BYTES = 3_584 * 1024**2
RSS_PROOF_BYTES = 2_560 * 1024**2
RSS_SAMPLE_SECONDS = 0.05
EXPECTED_IMPORTED_COMMITS = 293
EXPECTED_NEW_COMMITS = 81
V2_STATUS = "FAIL_GC_SESSION_TRIGGER_EDGE_V2_EXECUTION"
V2_FINAL_RECEIPT = "0f64374ad742ce60d00d0c381f3034b5170e028fc37391a44ad96e4d7c5831d3"
V2_FINAL_SHA256 = "4184e39cc0cd2aaae34ee5c84ec64e8c469f45c0204bc3389048e0fa935a3a07"
V2_VERDICT_SHA256 = "f38520305ac0c6e81df726effca8e7f83cdfe434c2bd3efc841bef4c0dbcea15"
V2_FREEZE_SHA256 = "18396e473086374d963d6ac5ddd08f8e9d8f52cca09082cf8c477b07949a01fd"
V2_IMPLEMENTATION_SHA256 = "20167fee1028957c980335b7b13c0d5cfa32fca4db0fb1f635439d4151a9f319"
FAILED_ROW_ID = "TRIGGER_M2:2024-04-12:NEW_YORK"
CONTROL_ROW_ID = "TRIGGER_M2:2024-04-12:LONDON"
IMPLEMENTATIONS = ("primary", "reference")


@dataclass(frozen=True, slots=True)
class Paths:
    acquisition: Path
    step5b2: Path
    context: Path
    xau: Path
    old_m2: Path
    old_r1: Path
    old_a1: Path
    old_v1: Path
    old_v2: Path
    output: Path
    engineering_output: Path
    data_root: Path
    artifact_root: Path

    def v2_paths(self, output: Path | None = None) -> v2.RunPaths:
        return v2.RunPaths(
            acquisition=self.acquisition,
            step5b2=self.step5b2,
            context=self.context,
            xau=self.xau,
            old_m2=self.old_m2,
            old_r1=self.old_r1,
            old_a1=self.old_a1,
            old_v1=self.old_v1,
            output=output or self.output,
        )


class StreamingIdentity:
    """Batch-boundary-independent, value-blind semantic source identity."""

    def __init__(self, schema: pa.Schema, columns: Sequence[str]) -> None:
        self.columns = tuple(columns)
        self.types = {name: str(schema.field(name).type) for name in self.columns}
        self.hashers = {name: hashlib.sha256() for name in self.columns}
        self.rows = 0

    def update(self, arrays: Mapping[str, np.ndarray[Any, Any]]) -> None:
        lengths = {len(arrays[name]) for name in self.columns}
        if len(lengths) != 1:
            raise ValueError("Streaming identity received unequal column lengths")
        count = lengths.pop()
        self.rows += count
        for name in self.columns:
            values = arrays[name]
            if values.dtype.kind == "U":
                payload = np.ascontiguousarray(values.astype("S1", copy=False)).tobytes()
                dtype = "S1"
            else:
                contiguous = np.ascontiguousarray(values)
                payload = contiguous.tobytes()
            self.hashers[name].update(payload)

    def finish(self) -> str:
        return v2.canonical_hash(
            {
                "version": "GC_V2R1_STREAMING_SOURCE_IDENTITY_V1_0",
                "rows": self.rows,
                "columns": [
                    {
                        "name": name,
                        "arrow_type": self.types[name],
                        "stream_sha256": self.hashers[name].hexdigest(),
                    }
                    for name in self.columns
                ],
            }
        )


def _batch_arrays(batch: pa.RecordBatch, columns: Sequence[str]) -> dict[str, np.ndarray[Any, Any]]:
    output: dict[str, np.ndarray[Any, Any]] = {}
    for name in columns:
        array = batch.column(batch.schema.get_field_index(name))
        if array.null_count:
            raise ValueError(f"Unexpected null in frozen source column {name}")
        if pa.types.is_timestamp(array.type):
            output[name] = array.cast(pa.int64()).to_numpy(zero_copy_only=False)
        elif pa.types.is_string(array.type):
            output[name] = np.fromiter(
                (str(value.as_py()) for value in array), dtype="<U1", count=len(array)
            )
        else:
            output[name] = array.to_numpy(zero_copy_only=False)
    return output


def _timestamp_scalar(value_ns: int) -> pa.Scalar:
    return pa.scalar(value_ns, type=pa.timestamp("ns", tz="UTC"))


def _primary_batches(
    path: Path, columns: Sequence[str], start: int, end: int
) -> Iterator[pa.RecordBatch]:
    field = ds.field("ts_recv")
    scanner = ds.dataset(path, format="parquet").scanner(
        columns=list(columns),
        filter=(field >= _timestamp_scalar(start)) & (field < _timestamp_scalar(end)),
        batch_size=PRIMARY_BATCH_ROWS,
        use_threads=False,
    )
    for batch in scanner.to_batches():
        if batch.num_rows:
            yield batch


def _reference_batches(
    path: Path, columns: Sequence[str], start: int, end: int
) -> Iterator[pa.RecordBatch]:
    with pq.ParquetFile(path) as parquet:
        ts_index = parquet.schema_arrow.get_field_index("ts_recv")
        timestamp_type = parquet.schema_arrow.field(ts_index).type
        selected_ts_index = list(columns).index("ts_recv")
        for group in range(parquet.num_row_groups):
            column_meta = parquet.metadata.row_group(group).column(ts_index)
            stats = column_meta.statistics
            if stats is not None and stats.has_min_max:
                minimum = a1._statistics_ns(stats.min, timestamp_type)
                maximum = a1._statistics_ns(stats.max, timestamp_type)
                if maximum < start or minimum >= end:
                    continue
            for batch in parquet.iter_batches(
                batch_size=REFERENCE_BATCH_ROWS,
                row_groups=[group],
                columns=list(columns),
                use_threads=False,
            ):
                receives = batch.column(selected_ts_index).cast(pa.int64())
                mask = pc.and_(
                    pc.greater_equal(receives, pa.scalar(start, pa.int64())),
                    pc.less(receives, pa.scalar(end, pa.int64())),
                )
                selected = batch.filter(mask)
                if selected.num_rows:
                    yield selected


def _batches(
    implementation: str, path: Path, columns: Sequence[str], start: int, end: int
) -> Iterator[pa.RecordBatch]:
    if implementation == "primary":
        yield from _primary_batches(path, columns, start, end)
    elif implementation == "reference":
        yield from _reference_batches(path, columns, start, end)
    else:
        raise ValueError(implementation)


def _cross_boundary_regression(
    previous: tuple[int, int] | None,
    receives: np.ndarray[Any, Any],
    ordinals: np.ndarray[Any, Any],
) -> int:
    if previous is None or not len(receives):
        return 0
    return int(int(receives[0]) < previous[0]) + int(
        int(receives[0]) == previous[0] and int(ordinals[0]) <= previous[1]
    )


def _stream_mbo(
    *,
    implementation: str,
    path: Path,
    columns: Sequence[str],
    start: int,
    end: int,
    instrument_id: int,
    s5c: Any,
    base: Any,
) -> tuple[dict[str, np.ndarray[Any, Any]], Counter[str], dict[str, Any]]:
    output = s5c._empty_event_arrays(base)
    audit: Counter[str] = Counter()
    schema = pq.ParquetFile(path).schema_arrow
    identity = StreamingIdentity(schema, columns)
    previous: tuple[int, int] | None = None
    batches = 0
    for batch in _batches(implementation, path, columns, start, end):
        arrays = _batch_arrays(batch, columns)
        identity.update(arrays)
        receives = arrays["ts_recv"].astype(np.int64, copy=False)
        ordinals = arrays["source_row_ordinal"].astype(np.int64, copy=False)
        boundary = _cross_boundary_regression(previous, receives, ordinals)
        allocator = (
            s5c._primary_mbo_allocate
            if implementation == "primary"
            else s5c._reference_mbo_allocate
        )
        partial, partial_audit = allocator(arrays, start, end, instrument_id, base)
        for name in output:
            output[name] += partial[name]
        audit.update(partial_audit)
        audit["mbo_timestamp_or_ordinal_regressions"] += boundary
        previous = (int(receives[-1]), int(ordinals[-1]))
        batches += 1
        del arrays, partial
    if int(audit.get("mbo_timestamp_or_ordinal_regressions", 0)):
        raise ValueError("Streaming MBO source order failed")
    return output, audit, {
        "rows": identity.rows,
        "batches": batches,
        "identity_checksum": identity.finish(),
    }


def _accumulate(
    implementation: str,
    target: np.ndarray[Any, Any],
    buckets: np.ndarray[Any, Any],
    mask: np.ndarray[Any, Any],
    weights: np.ndarray[Any, Any] | None = None,
) -> None:
    if implementation == "primary":
        selected = buckets[mask]
        if not len(selected):
            return
        values = (
            np.bincount(selected, minlength=m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION)
            if weights is None
            else np.bincount(
                selected,
                weights=weights[mask],
                minlength=m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION,
            )
        )
        target[:] += values.astype(np.int64)
    else:
        selected = buckets[mask]
        if not len(selected):
            return
        additions = (
            np.ones(len(selected), dtype=np.int64)
            if weights is None
            else weights[mask].astype(np.int64, copy=False)
        )
        np.add.at(target, selected, additions)


def _stream_mbp(
    *,
    implementation: str,
    path: Path,
    columns: Sequence[str],
    start: int,
    end: int,
    instrument_id: int,
    anchor: pa.Table,
    s5c: Any,
    base: Any,
) -> tuple[dict[str, np.ndarray[Any, Any]], list[Any], Counter[str], dict[str, Any]]:
    window = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    counts = {name: np.zeros(window, dtype=np.int64) for name in base.MBP_STATE_COLUMNS[:9]}
    anchor_arrays = s5c._table_arrays(anchor, base.MBP_COLUMNS)
    if anchor.num_rows != 1:
        raise ValueError("Streaming MBP requires one anchor")
    anchor_recv = int(anchor_arrays["ts_recv"][0])
    day_start = start - (start % (86_400 * m2.BUCKET_NS))
    if not day_start <= anchor_recv < start:
        raise ValueError("Streaming MBP anchor crossed the date/window boundary")

    state_present = np.zeros(window, dtype=bool)
    state_ordinal = np.zeros(window, dtype=np.int64)
    state_recv = np.zeros(window, dtype=np.int64)
    state_action = np.full(window, "", dtype="<U1")
    state_flags = np.zeros(window, dtype=np.int64)
    state_book = {name: np.zeros(window, dtype=np.int64) for name in base.BOOK_FIELDS}

    schema = pq.ParquetFile(path).schema_arrow
    identity = StreamingIdentity(schema, columns)
    previous_order: tuple[int, int] | None = None
    previous_two = bool(s5c._two_sided_arrays(anchor_arrays, base)[0])
    previous_snapshot = bool(int(anchor_arrays["flags"][0]) & s5c.F_SNAPSHOT)
    previous_action = str(anchor_arrays["action"][0])
    previous_bid_px = int(anchor_arrays["bid_px_00"][0])
    previous_bid_sz = int(anchor_arrays["bid_sz_00"][0])
    previous_ask_px = int(anchor_arrays["ask_px_00"][0])
    previous_ask_sz = int(anchor_arrays["ask_sz_00"][0])

    audit: Counter[str] = Counter()
    canonical, negative = s5c._book_validity_counts(anchor_arrays, base)
    continuous_crossed = 0
    batches = 0
    rows = 0

    for batch in _batches(implementation, path, columns, start, end):
        arrays = _batch_arrays(batch, columns)
        identity.update(arrays)
        receives = arrays["ts_recv"].astype(np.int64, copy=False)
        ordinals = arrays["source_row_ordinal"].astype(np.int64, copy=False)
        buckets = ((receives - start) // m2.BUCKET_NS).astype(np.int64)
        if np.any(
            (receives < start)
            | (receives >= end)
            | (buckets < 0)
            | (buckets >= window)
        ):
            raise ValueError("Streaming MBP row escaped frozen window")
        audit["mbp10_timestamp_or_ordinal_regressions"] += s5c._order_regressions(
            receives, ordinals
        ) + _cross_boundary_regression(previous_order, receives, ordinals)
        previous_order = (int(receives[-1]), int(ordinals[-1]))

        actions = arrays["action"].astype("<U1", copy=False)
        flags = arrays["flags"].astype(np.int64, copy=False)
        every = np.ones(len(receives), dtype=bool)
        snapshots = (flags & s5c.F_SNAPSHOT) != 0
        known = np.isin(actions, tuple(s5c.KNOWN_ACTIONS))
        _accumulate(implementation, counts["mbp_update_count"], buckets, every)
        _accumulate(implementation, counts["mbp_snapshot_count"], buckets, snapshots)
        _accumulate(implementation, counts["mbp_reset_count"], buckets, actions == "R")
        _accumulate(implementation, counts["mbp_unknown_action_count"], buckets, ~known)
        _accumulate(
            implementation,
            counts["mbp_bad_ts_recv_flag_count"],
            buckets,
            (flags & s5c.F_BAD_TS_RECV) != 0,
        )
        _accumulate(
            implementation,
            counts["mbp_maybe_bad_book_flag_count"],
            buckets,
            (flags & s5c.F_MAYBE_BAD_BOOK) != 0,
        )

        two = s5c._two_sided_arrays(arrays, base)
        prior_two = np.empty(len(two), dtype=bool)
        prior_two[0] = previous_two
        prior_two[1:] = two[:-1]
        prior_snapshot = np.empty(len(two), dtype=bool)
        prior_snapshot[0] = previous_snapshot
        prior_snapshot[1:] = snapshots[:-1]
        prior_action = np.empty(len(two), dtype="<U1")
        prior_action[0] = previous_action
        prior_action[1:] = actions[:-1]
        eligible = (
            prior_two
            & ~prior_snapshot
            & (prior_action != "R")
            & two
            & ~snapshots
            & (actions != "R")
        )

        bid_px = arrays["bid_px_00"].astype(np.int64, copy=False)
        bid_sz = arrays["bid_sz_00"].astype(np.int64, copy=False)
        ask_px = arrays["ask_px_00"].astype(np.int64, copy=False)
        ask_sz = arrays["ask_sz_00"].astype(np.int64, copy=False)
        prior_bid_px = np.empty(len(two), dtype=np.int64)
        prior_bid_sz = np.empty(len(two), dtype=np.int64)
        prior_ask_px = np.empty(len(two), dtype=np.int64)
        prior_ask_sz = np.empty(len(two), dtype=np.int64)
        prior_bid_px[0], prior_bid_sz[0] = previous_bid_px, previous_bid_sz
        prior_ask_px[0], prior_ask_sz[0] = previous_ask_px, previous_ask_sz
        prior_bid_px[1:], prior_bid_sz[1:] = bid_px[:-1], bid_sz[:-1]
        prior_ask_px[1:], prior_ask_sz[1:] = ask_px[:-1], ask_sz[:-1]
        ofi = (
            np.where(bid_px >= prior_bid_px, bid_sz, 0)
            - np.where(bid_px <= prior_bid_px, prior_bid_sz, 0)
            - np.where(ask_px <= prior_ask_px, ask_sz, 0)
            + np.where(ask_px >= prior_ask_px, prior_ask_sz, 0)
        ).astype(np.int64)
        _accumulate(
            implementation, counts["quote_ofi_transition_count"], buckets, eligible
        )
        _accumulate(
            implementation, counts["quote_ofi_skipped_count"], buckets, ~eligible
        )
        _accumulate(
            implementation, counts["quote_ofi_raw"], buckets, eligible, ofi
        )

        tails = np.r_[np.flatnonzero(buckets[1:] != buckets[:-1]), len(buckets) - 1]
        tail_buckets = buckets[tails]
        state_present[tail_buckets] = True
        state_ordinal[tail_buckets] = ordinals[tails]
        state_recv[tail_buckets] = receives[tails]
        state_action[tail_buckets] = actions[tails]
        state_flags[tail_buckets] = flags[tails]
        for name in base.BOOK_FIELDS:
            state_book[name][tail_buckets] = arrays[name][tails]

        part_canonical, part_negative = s5c._book_validity_counts(arrays, base)
        canonical += part_canonical
        negative += part_negative
        continuous_crossed += int(np.count_nonzero(two & (ask_px < bid_px)))
        audit["mbp10_publisher_mismatches"] += int(
            np.count_nonzero(arrays["publisher_id"] != 1)
        )
        audit["mbp10_instrument_mismatches"] += int(
            np.count_nonzero(arrays["instrument_id"] != instrument_id)
        )
        audit["mbp10_unknown_action_rows"] += int(np.count_nonzero(~known))
        audit["mbp10_maybe_bad_book_rows"] += int(
            np.count_nonzero((flags & s5c.F_MAYBE_BAD_BOOK) != 0)
        )
        rows += len(receives)
        batches += 1

        previous_two = bool(two[-1])
        previous_snapshot = bool(snapshots[-1])
        previous_action = str(actions[-1])
        previous_bid_px, previous_bid_sz = int(bid_px[-1]), int(bid_sz[-1])
        previous_ask_px, previous_ask_sz = int(ask_px[-1]), int(ask_sz[-1])
        del arrays

    if int(audit.get("mbp10_timestamp_or_ordinal_regressions", 0)):
        raise ValueError("Streaming MBP source order failed")

    anchor_state = (
        base.PrimaryBookState(
            ordinal=int(anchor_arrays["source_row_ordinal"][0]),
            recv=anchor_recv,
            action=str(anchor_arrays["action"][0]),
            flags=int(anchor_arrays["flags"][0]),
            levels=tuple(int(anchor_arrays[name][0]) for name in base.BOOK_FIELDS),
        )
        if implementation == "primary"
        else base.ReferenceBookState(
            ordinal=int(anchor_arrays["source_row_ordinal"][0]),
            recv=anchor_recv,
            action=str(anchor_arrays["action"][0]),
            flags=int(anchor_arrays["flags"][0]),
            levels={name: int(anchor_arrays[name][0]) for name in base.BOOK_FIELDS},
        )
    )
    states: list[Any] = []
    carried = anchor_state
    for bucket in range(window):
        if state_present[bucket]:
            if implementation == "primary":
                carried = base.PrimaryBookState(
                    ordinal=int(state_ordinal[bucket]),
                    recv=int(state_recv[bucket]),
                    action=str(state_action[bucket]),
                    flags=int(state_flags[bucket]),
                    levels=tuple(int(state_book[name][bucket]) for name in base.BOOK_FIELDS),
                )
            else:
                carried = base.ReferenceBookState(
                    ordinal=int(state_ordinal[bucket]),
                    recv=int(state_recv[bucket]),
                    action=str(state_action[bucket]),
                    flags=int(state_flags[bucket]),
                    levels={name: int(state_book[name][bucket]) for name in base.BOOK_FIELDS},
                )
        states.append(carried)

    audit["mbp10_selected_rows"] = rows
    audit["mbp10_anchor_rows"] = 1
    audit["mbp10_publisher_mismatches"] += int(int(anchor_arrays["publisher_id"][0]) != 1)
    audit["mbp10_instrument_mismatches"] += int(
        int(anchor_arrays["instrument_id"][0]) != instrument_id
    )
    audit["empty_level_canonical_violations"] = canonical
    audit["negative_size_or_count_values"] = negative
    audit["continuous_crossed_book_rows"] = continuous_crossed
    audit["mbp10_rows_allocated"] = int(np.sum(counts["mbp_update_count"]))
    audit["anchor_not_before_window"] = int(anchor_recv >= start)
    return counts, states, audit, {
        "rows": identity.rows,
        "batches": batches,
        "identity_checksum": identity.finish(),
        "anchor_identity_checksum": v2.table_buffer_checksum(anchor),
    }


def _technical_counter(
    row: Mapping[str, Any],
    columns: Mapping[str, Sequence[Any]],
    mbo_audit: Mapping[str, int],
    mbp_audit: Mapping[str, int],
) -> Counter[str]:
    technical: Counter[str] = Counter()
    technical.update(mbo_audit)
    technical.update(mbp_audit)
    technical["available_sessions"] = 1
    technical["bucket_rows"] = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    technical[
        "london_bucket_rows" if row["session_code"] == "LONDON" else "new_york_bucket_rows"
    ] = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    technical["continuous_crossed_bucket_closes"] = sum(
        bool(value) for value in columns["book_crossed"]
    )
    technical["state_available_bucket_closes"] = sum(
        bool(value) for value in columns["state_available"]
    )
    technical["selected_bad_ts_recv_rows"] = sum(
        columns["mbo_bad_ts_recv_flag_count"]
    ) + sum(columns["mbp_bad_ts_recv_flag_count"])
    return technical


def worker_feature(spec_path: Path) -> None:
    spec = v2.read_json(spec_path)
    implementation = str(spec["implementation"])
    if implementation not in IMPLEMENTATIONS:
        raise ValueError("Invalid implementation")
    output = Path(str(spec["feature_path"]))
    mask_path = Path(str(spec["mask_path"]))
    diagnostic_path = Path(str(spec["diagnostic_path"]))
    for path in (output, mask_path, diagnostic_path):
        if path.exists():
            raise FileExistsError(path)
    s5c = m2._load_module(m2.STEP5C_ENGINE_PATH, f"gc_v2r1_s5c_{os.getpid()}")
    base = m2._load_module(m2.BASE_ENGINE_PATH, f"gc_v2r1_base_{os.getpid()}")
    mbo_path = Path(str(spec["mbo_path"]))
    mbp_path = Path(str(spec["mbp_path"]))
    start = int(spec["window_start_inclusive_ns"])
    end = int(spec["window_end_exclusive_ns"])
    day_start = int(spec["utc_day_start_ns"])
    if implementation == "primary":
        anchor = s5c._read_exact_anchor(mbp_path, base.MBP_COLUMNS, start, day_start)
    else:
        anchor = r2.read_anchor_reference(mbp_path, base.MBP_COLUMNS, start, day_start)
    s5c.WINDOW_BUCKETS = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    events, mbo_audit, mbo_source = _stream_mbo(
        implementation=implementation,
        path=mbo_path,
        columns=base.MBO_COLUMNS,
        start=start,
        end=end,
        instrument_id=int(spec["feature_row"]["expected_instrument_id"]),
        s5c=s5c,
        base=base,
    )
    counts, states, mbp_audit, mbp_source = _stream_mbp(
        implementation=implementation,
        path=mbp_path,
        columns=base.MBP_COLUMNS,
        start=start,
        end=end,
        instrument_id=int(spec["feature_row"]["expected_instrument_id"]),
        anchor=anchor,
        s5c=s5c,
        base=base,
    )
    row = dict(spec["feature_row"])
    raw = s5c._materialize_window(row, events, counts, states, base, implementation)
    technical = _technical_counter(row, raw, mbo_audit, mbp_audit)
    selected_flags = {
        int(state.ordinal): int(state.flags) for state in states
    }
    selected_flags[int(anchor["source_row_ordinal"][0].as_py())] = int(
        anchor["flags"][0].as_py()
    )
    if implementation == "primary":
        columns, mask, policy = r2.apply_policy_primary(
            str(spec["row_id"]), raw, selected_flags, base
        )
    else:
        columns, mask, policy = r2.apply_policy_reference(
            str(spec["row_id"]), raw, selected_flags, base
        )
    technical["raw_state_available_bucket_closes"] += int(
        technical.get("state_available_bucket_closes", 0)
    )
    technical["state_available_bucket_closes"] = int(
        policy["post_policy_state_available_buckets"]
    )
    technical["raw_terminal_crossed_bucket_closes"] += int(
        policy["raw_terminal_crossed_bucket_closes"]
    )
    technical["technical_unavailable_bucket_closes"] += int(
        policy["technical_unavailable_bucket_closes"]
    )
    technical["technical_unavailable_ofi_buckets"] += int(
        policy["technical_unavailable_ofi_buckets"]
    )
    technical["unavailability_latch_starts"] += int(policy["unavailability_latch_starts"])
    technical["valid_recovery_boundaries"] += int(policy["valid_recovery_boundaries"])
    technical["crossed_non_f_last_failures"] += int(policy["crossed_non_f_last_failures"])
    technical["invalid_state_values_retained"] += int(policy["invalid_state_values_retained"])
    technical["continuous_crossed_bucket_closes"] = int(
        policy["post_policy_crossed_bucket_closes"]
    )

    table = pa.Table.from_pydict(columns, schema=base.FEATURE_SCHEMA)
    if table.num_rows != m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION:
        raise ValueError("V2-R1 feature worker row count changed")
    v2.atomic_parquet(output, table, m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION)
    encoded_mask = v2.encode_mask(mask)
    v2.atomic_bytes(mask_path, encoded_mask)
    fingerprint = s5c._parquet_hashes(
        output,
        base.FEATURE_SCHEMA,
        m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION,
        s5c._schema_hash(base.FEATURE_SCHEMA),
    )
    memory = v2.proc_memory_bytes()
    diagnostic = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_FEATURE_WORKER_V1_0",
        "status": "PASS_FEATURE_WORKER",
        "completed_at_utc": v2.utc_now(),
        "classification": str(spec["classification"]),
        "row_id": str(spec["row_id"]),
        "implementation": implementation,
        "source": {
            "mbo_rows": int(mbo_source["rows"]),
            "mbp10_rows": int(mbp_source["rows"]),
            "anchor_rows": anchor.num_rows,
            "mbo_identity_checksum": mbo_source["identity_checksum"],
            "mbp10_identity_checksum": mbp_source["identity_checksum"],
            "anchor_identity_checksum": mbp_source["anchor_identity_checksum"],
        },
        "feature": {"file": v2.file_record(output), "fingerprint": fingerprint},
        "unavailable_mask": {
            "file": v2.file_record(mask_path),
            "unavailable_buckets": int(sum(mask)),
            "checksum": hashlib.sha256(encoded_mask).hexdigest(),
        },
        "technical": dict(sorted(technical.items())),
        "policy": policy,
        "worker_memory": memory,
        "bounded_reader": {
            "primary_batch_rows": PRIMARY_BATCH_ROWS,
            "reference_batch_rows": REFERENCE_BATCH_ROWS,
            "observed_mbo_batches": int(mbo_source["batches"]),
            "observed_mbp10_batches": int(mbp_source["batches"]),
            "full_window_source_arrays_retained": False,
        },
        "outcomes_opened_or_joined": False,
        "relationships_candidates_execution_trades_or_pnl_calculated": False,
        "year_2025_or_2026_accessed": False,
    }
    diagnostic["diagnostic_receipt"] = v2.canonical_hash(
        {**diagnostic, "diagnostic_receipt": None}
    )
    v2.write_json_exclusive(diagnostic_path, diagnostic)
    print(
        json.dumps(
            {
                "status": diagnostic["status"],
                "row_id": diagnostic["row_id"],
                "implementation": implementation,
                "outcomes": False,
            },
            sort_keys=True,
        ),
        flush=True,
    )


def run_feature_child(
    spec_path: Path, monitor_path: Path, stdout_path: Path, stderr_path: Path
) -> dict[str, Any]:
    for path in (monitor_path, stdout_path, stderr_path):
        if path.exists():
            raise FileExistsError(path)
        path.parent.mkdir(parents=True, exist_ok=True)
    environment = dict(os.environ)
    environment.update(
        {
            "PYTHONHASHSEED": "0",
            "MALLOC_ARENA_MAX": "2",
            "OMP_NUM_THREADS": "1",
            "ARROW_NUM_THREADS": "1",
        }
    )
    with stdout_path.open("xb") as stdout_handle, stderr_path.open("xb") as stderr_handle:
        process = subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "feature-worker", "--spec", str(spec_path)],
            stdout=stdout_handle,
            stderr=stderr_handle,
            env=environment,
        )
        maximum_rss = 0
        samples = 0
        guard_triggered = False
        while process.poll() is None:
            memory = v2.proc_memory_bytes(process.pid)
            maximum_rss = max(maximum_rss, int(memory["rss_bytes"]), int(memory["hwm_bytes"]))
            samples += 1
            if maximum_rss >= RSS_GUARD_BYTES:
                guard_triggered = True
                process.terminate()
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=10)
                break
            time.sleep(RSS_SAMPLE_SECONDS)
        return_code = int(process.wait())
    monitor = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_RESOURCE_MONITOR_V1_0",
        "completed_at_utc": v2.utc_now(),
        "spec_sha256": v2.sha256_file(spec_path),
        "worker_pid": process.pid,
        "samples": samples,
        "sampling_interval_seconds": RSS_SAMPLE_SECONDS,
        "maximum_observed_rss_bytes": maximum_rss,
        "guard_rss_bytes": RSS_GUARD_BYTES,
        "formal_cap_bytes": RSS_CAP_BYTES,
        "guard_triggered": guard_triggered,
        "return_code": return_code,
        "stdout": v2.file_record(stdout_path),
        "stderr": v2.file_record(stderr_path),
        "monitor_receipt": None,
    }
    monitor["monitor_receipt"] = v2.canonical_hash({**monitor, "monitor_receipt": None})
    v2.write_json_exclusive(monitor_path, monitor)
    if guard_triggered:
        raise v2.ResourceCapExceeded(
            f"V2-R1 worker reached guard: {maximum_rss} >= {RSS_GUARD_BYTES}"
        )
    if return_code != 0:
        raise v2.WorkerFailed(
            f"V2-R1 worker failed rc={return_code}; stderr_sha256={v2.sha256_file(stderr_path)}"
        )
    return monitor


def _patch_v2_runtime() -> None:
    v2.run_feature_child = run_feature_child
    v2.RSS_CAP_BYTES = RSS_CAP_BYTES
    v2.RSS_GUARD_BYTES = RSS_GUARD_BYTES
    v2.RSS_SAMPLE_SECONDS = RSS_SAMPLE_SECONDS


def _old_commit_index(old_v2: Path) -> tuple[list[dict[str, Any]], str]:
    records: list[dict[str, Any]] = []
    for path in sorted((old_v2 / "checkpoints/sessions").glob("*.json")):
        commit = v2.verify_session_commit(path)
        records.append(
            {
                "row_id": str(commit["row_id"]),
                "commit_receipt": str(commit["commit_receipt"]),
                "commit_file": v2.file_record(path),
            }
        )
    if len(records) != EXPECTED_IMPORTED_COMMITS:
        raise ValueError(f"Expected 293 sealed V2 commits, found {len(records)}")
    return records, v2.canonical_hash(records)


def verify_v2_failure(paths: Paths) -> dict[str, Any]:
    v2.verify_v2_freeze(paths.v2_paths(paths.old_v2))
    final_path = paths.old_v2 / "final_seal.json"
    verdict_path = paths.old_v2 / "verdict.json"
    manifest_path = paths.old_v2 / "manifest.json"
    failure_path = paths.old_v2 / "execution_failure.json"
    if v2.sha256_file(final_path) != V2_FINAL_SHA256:
        raise ValueError("V2 final seal changed")
    if v2.sha256_file(verdict_path) != V2_VERDICT_SHA256:
        raise ValueError("V2 verdict changed")
    if v2.sha256_file(v2.FREEZE_PATH) != V2_FREEZE_SHA256:
        raise ValueError("V2 freeze changed")
    if v2.sha256_file(Path(v2.__file__)) != V2_IMPLEMENTATION_SHA256:
        raise ValueError("V2 implementation changed")
    final = v2.read_json(final_path)
    verdict = v2.read_json(verdict_path)
    manifest = v2.read_json(manifest_path)
    failure = v2.read_json(failure_path)
    for value, field in (
        (final, "final_seal_receipt"),
        (verdict, "verdict_receipt"),
        (manifest, "manifest_receipt"),
    ):
        if not v2.receipt_valid(value, field):
            raise ValueError(f"V2 receipt failed: {field}")
    if final.get("status") != V2_STATUS or final.get("final_seal_receipt") != V2_FINAL_RECEIPT:
        raise ValueError("V2 terminal failure disposition changed")
    if failure.get("error_type") != "ResourceCapExceeded" or int(failure.get("committed_sessions", -1)) != 293:
        raise ValueError("V2 resource failure evidence changed")
    for record in manifest.get("artifacts", []):
        v2.verify_record(record)
    records, index_receipt = _old_commit_index(paths.old_v2)
    return {
        "v2_status": final["status"],
        "v2_final_seal_receipt": final["final_seal_receipt"],
        "v2_final_seal_sha256": v2.sha256_file(final_path),
        "v2_verdict_sha256": v2.sha256_file(verdict_path),
        "v2_failure": failure,
        "sealed_commit_count": len(records),
        "sealed_commit_index_receipt": index_receipt,
    }


def seal_pre_value_freeze(paths: Paths) -> dict[str, Any]:
    predecessor = verify_v2_failure(paths)
    expected = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_PRE_VALUE_FREEZE_V1_0",
        "status": "SEALED_BEFORE_V2R1_SOURCE_VALUE_ACCESS",
        "sealed_at_utc": None,
        "contract": v2.file_record(CONTRACT_PATH),
        "protocol": v2.file_record(PROTOCOL_PATH),
        "implementation": v2.file_record(Path(__file__)),
        "predecessor": predecessor,
        "resource_policy": {
            "formal_rss_cap_bytes": RSS_CAP_BYTES,
            "child_guard_rss_bytes": RSS_GUARD_BYTES,
            "proof_qualification_rss_bytes": RSS_PROOF_BYTES,
            "sampling_interval_seconds": RSS_SAMPLE_SECONDS,
        },
        "outcomes_opened": False,
        "freeze_receipt": None,
    }
    if PRE_VALUE_FREEZE_PATH.is_file():
        existing = v2.read_json(PRE_VALUE_FREEZE_PATH)
        for key in ("contract", "protocol", "implementation"):
            if existing.get(key) != expected[key]:
                raise ValueError(f"V2-R1 pre-value freeze binding changed: {key}")
        if existing.get("predecessor") != predecessor or not v2.receipt_valid(existing, "freeze_receipt"):
            raise ValueError("V2-R1 pre-value freeze failed")
        return existing
    expected["sealed_at_utc"] = v2.utc_now()
    expected["freeze_receipt"] = v2.canonical_hash({**expected, "freeze_receipt": None})
    v2.write_json_exclusive(PRE_VALUE_FREEZE_PATH, expected)
    return expected


def _proof_checkpoint(
    *,
    output: Path,
    row: Mapping[str, Any],
    mbo_path: Path,
    mbp_path: Path,
    classification: str,
) -> dict[str, Any]:
    checkpoints: dict[str, dict[str, Any]] = {}
    for implementation in IMPLEMENTATIONS:
        checkpoints[implementation] = v2.ensure_feature_pass(
            output=output,
            row_id=str(row["row_id"]),
            classification=classification,
            implementation=implementation,
            mbo_path=mbo_path,
            mbp_path=mbp_path,
            row=row,
            invocation=1,
        )
    primary = v2.pass_paths(output, str(row["row_id"]), "primary")
    reference = v2.pass_paths(output, str(row["row_id"]), "reference")
    gates = {
        "source_identities_exact": checkpoints["primary"]["source"] == checkpoints["reference"]["source"],
        "features_exact": primary["feature"].read_bytes() == reference["feature"].read_bytes(),
        "masks_exact": primary["mask"].read_bytes() == reference["mask"].read_bytes(),
        "technical_exact": checkpoints["primary"]["technical"] == checkpoints["reference"]["technical"],
        "policy_exact": checkpoints["primary"]["policy"] == checkpoints["reference"]["policy"],
        "proof_rss_at_or_below_2_5_gib": max(
            int(checkpoints["primary"]["maximum_observed_rss_bytes"]),
            int(checkpoints["reference"]["maximum_observed_rss_bytes"]),
        ) <= RSS_PROOF_BYTES,
    }
    return {
        "checkpoints": checkpoints,
        "paths": {"primary": primary, "reference": reference},
        "gates": gates,
        "maximum_observed_rss_bytes": max(
            int(checkpoints["primary"]["maximum_observed_rss_bytes"]),
            int(checkpoints["reference"]["maximum_observed_rss_bytes"]),
        ),
    }


def run_proof(paths: Paths) -> dict[str, Any]:
    if FREEZE_PATH.exists():
        raise FileExistsError("V2-R1 final freeze already exists")
    prefreeze = seal_pre_value_freeze(paths)
    _patch_v2_runtime()
    sources = v2.engineering_sources(paths.data_root, paths.artifact_root)
    paths.engineering_output.mkdir(parents=True, exist_ok=True)
    marker = paths.engineering_output / "attempt_started.json"
    if not marker.exists():
        v2.write_json_exclusive(
            marker,
            {
                "version": "GC_SESSION_TRIGGER_EDGE_V2R1_ENGINEERING_ATTEMPT_V1_0",
                "started_at_utc": v2.utc_now(),
                "outcomes_opened": False,
            },
        )
    commits: list[dict[str, Any]] = []
    for selected_date in v2.EXPECTED_ENGINEERING_DATES:
        source = sources[selected_date]
        for key in ("mbo", "mbp"):
            path = Path(source[key])
            if not path.is_file() or v2.sha256_file(path) != str(source[f"{key}_sha256"]):
                raise ValueError(f"Engineering source changed: {selected_date} {key}")
        for session_code in v2.SESSIONS:
            row = v2.engineering_row(selected_date, session_code, source)
            row["row_id"] = f"V2R1_ENGINEERING:{selected_date}:{session_code}"
            result = _proof_checkpoint(
                output=paths.engineering_output,
                row=row,
                mbo_path=Path(source["mbo"]),
                mbp_path=Path(source["mbp"]),
                classification="ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
            )
            expected = pq.read_table(Path(source["known"])).slice(
                int(row["bucket_index_start_inclusive"]),
                m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION,
            )
            actual = pq.read_table(result["paths"]["primary"]["feature"])
            result["gates"]["existing_sealed_engineering_slice_exact"] = actual.equals(
                expected, check_metadata=True
            )
            del actual, expected
            if not all(result["gates"].values()):
                raise ValueError(f"V2-R1 engineering proof failed: {row['row_id']}")
            commits.append(
                {
                    "row_id": row["row_id"],
                    "classification": "ENGINEERING_ONLY_ZERO_RESEARCH_OR_VALIDATION_CREDIT",
                    "maximum_observed_rss_bytes": result["maximum_observed_rss_bytes"],
                    "gates": result["gates"],
                }
            )
            print(
                json.dumps(
                    {
                        "stage": "V2R1_ENGINEERING_WINDOW_COMPLETE",
                        "completed": len(commits),
                        "total": 14,
                        "row_id": row["row_id"],
                        "outcomes": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )

    mp = m2.Paths(paths.acquisition, paths.step5b2, paths.context, paths.xau, paths.output)
    _s5c, _base, registry, acquisition = m2._verified_control(mp, verify_payload_hashes=False)
    row_map = {str(row["row_id"]): dict(row) for row in registry["rows"]}
    request_map = m2._request_map(acquisition)
    proof_development = paths.engineering_output / "resource_stress"
    for row_id, classification in (
        (CONTROL_ROW_ID, "OUTCOME_BLIND_ADJACENT_RESOURCE_CONTROL"),
        (FAILED_ROW_ID, "OUTCOME_BLIND_RESOURCE_STRESS_WINDOW"),
    ):
        row = row_map[row_id]
        mbo_path = Path(
            str(request_map[str(row["mbo_request_id"])]["normalization"]["normalized_payload"]["path"])
        )
        mbp_path = Path(
            str(request_map[str(row["mbp10_request_id"])]["normalization"]["normalized_payload"]["path"])
        )
        result = _proof_checkpoint(
            output=proof_development,
            row=row,
            mbo_path=mbo_path,
            mbp_path=mbp_path,
            classification=classification,
        )
        if row_id == CONTROL_ROW_ID:
            old_commit = v2.verify_session_commit(v2.session_commit_path(paths.old_v2, row_id))
            result["gates"]["sealed_v2_control_feature_exact"] = all(
                v2.sha256_file(result["paths"][implementation]["feature"])
                == str(old_commit["files"][implementation]["feature"]["sha256"])
                and v2.sha256_file(result["paths"][implementation]["mask"])
                == str(old_commit["files"][implementation]["mask"]["sha256"])
                for implementation in IMPLEMENTATIONS
            )
            result["gates"]["sealed_v2_control_technical_exact"] = (
                result["checkpoints"]["primary"]["technical"] == old_commit["technical"]
                and result["checkpoints"]["primary"]["policy"] == old_commit["policy"]
            )
        if not all(result["gates"].values()):
            raise ValueError(f"V2-R1 stress/control proof failed: {row_id}")
        commits.append(
            {
                "row_id": row_id,
                "classification": classification,
                "maximum_observed_rss_bytes": result["maximum_observed_rss_bytes"],
                "gates": result["gates"],
            }
        )
        print(
            json.dumps(
                {
                    "stage": "V2R1_RESOURCE_PROOF_WINDOW_COMPLETE",
                    "completed": len(commits),
                    "total": 14,
                    "row_id": row_id,
                    "outcomes": False,
                },
                sort_keys=True,
            ),
            flush=True,
        )
    if len(commits) != 14:
        raise ValueError("V2-R1 proof did not complete fourteen windows")
    maximum_rss = max(int(item["maximum_observed_rss_bytes"]) for item in commits)
    proof = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_ENGINEERING_PROOF_V1_0",
        "status": "PASS_V2R1_EXTERNAL_MEMORY_REPRODUCTION_AND_RESOURCE_PROOF",
        "completed_at_utc": v2.utc_now(),
        "windows": 14,
        "commits": commits,
        "maximum_observed_rss_bytes": maximum_rss,
        "proof_qualification_rss_bytes": RSS_PROOF_BYTES,
        "formal_rss_cap_bytes": RSS_CAP_BYTES,
        "pre_value_freeze": v2.file_record(PRE_VALUE_FREEZE_PATH),
        "development_outcomes_opened_or_joined": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "proof_receipt": None,
    }
    proof["proof_receipt"] = v2.canonical_hash({**proof, "proof_receipt": None})
    proof_path = paths.engineering_output / "engineering_proof.json"
    v2.write_json_exclusive(proof_path, proof)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_FREEZE_V1_0",
        "status": "SEALED_AFTER_V2R1_PROOF_BEFORE_FULL_DEVELOPMENT_CONTINUATION",
        "sealed_at_utc": v2.utc_now(),
        "contract": v2.file_record(CONTRACT_PATH),
        "protocol": v2.file_record(PROTOCOL_PATH),
        "implementation": v2.file_record(Path(__file__)),
        "pre_value_freeze": v2.file_record(PRE_VALUE_FREEZE_PATH),
        "engineering_proof": v2.file_record(proof_path),
        "predecessor": prefreeze["predecessor"],
        "analytical_definitions_changed": False,
        "outcomes_opened": False,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = v2.canonical_hash({**freeze, "freeze_receipt": None})
    v2.write_json_exclusive(FREEZE_PATH, freeze)
    print(
        json.dumps(
            {
                "status": freeze["status"],
                "windows": 14,
                "maximum_observed_rss_bytes": maximum_rss,
                "outcomes": False,
            },
            sort_keys=True,
        )
    )
    return proof


def verify_freeze(paths: Paths) -> dict[str, Any]:
    predecessor = verify_v2_failure(paths)
    freeze = v2.read_json(FREEZE_PATH)
    if freeze.get("status") != "SEALED_AFTER_V2R1_PROOF_BEFORE_FULL_DEVELOPMENT_CONTINUATION":
        raise ValueError("V2-R1 freeze status failed")
    if not v2.receipt_valid(freeze, "freeze_receipt"):
        raise ValueError("V2-R1 freeze receipt failed")
    for key, path in (
        ("contract", CONTRACT_PATH),
        ("protocol", PROTOCOL_PATH),
        ("implementation", Path(__file__)),
        ("pre_value_freeze", PRE_VALUE_FREEZE_PATH),
    ):
        if freeze[key]["sha256"] != v2.sha256_file(path):
            raise ValueError(f"V2-R1 freeze binding failed: {key}")
    v2.verify_record(freeze["engineering_proof"])
    proof = v2.read_json(Path(str(freeze["engineering_proof"]["path"])))
    if (
        proof.get("status") != "PASS_V2R1_EXTERNAL_MEMORY_REPRODUCTION_AND_RESOURCE_PROOF"
        or not v2.receipt_valid(proof, "proof_receipt")
        or int(proof.get("maximum_observed_rss_bytes", RSS_CAP_BYTES + 1)) > RSS_PROOF_BYTES
    ):
        raise ValueError("V2-R1 engineering proof failed")
    if freeze.get("predecessor") != predecessor:
        raise ValueError("V2-R1 predecessor binding changed")
    return freeze


def _write_import_ledger(paths: Paths, rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    ledger_path = paths.output / "v2_import_ledger.json"
    entries: list[dict[str, Any]] = []
    row_ids = {str(row["row_id"]) for row in rows if int(row["expected_bucket_rows"]) > 0}
    for commit_path in sorted((paths.old_v2 / "checkpoints/sessions").glob("*.json")):
        commit = v2.verify_session_commit(commit_path)
        if str(commit["row_id"]) not in row_ids:
            raise ValueError("Imported V2 commit is outside frozen registry")
        entries.append(
            {
                "row_id": str(commit["row_id"]),
                "commit_receipt": str(commit["commit_receipt"]),
                "commit_file": v2.file_record(commit_path),
            }
        )
    if len(entries) != EXPECTED_IMPORTED_COMMITS:
        raise ValueError("V2-R1 import ledger count changed")
    ledger = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_IMPORT_LEDGER_V1_0",
        "status": "PASS_VERIFIED_REFERENCE_ONLY_V2_IMPORT",
        "sealed_at_utc": v2.utc_now(),
        "entries": entries,
        "entries_receipt": v2.canonical_hash(entries),
        "old_v2_final_seal": v2.file_record(paths.old_v2 / "final_seal.json"),
        "files_copied_or_modified": False,
        "outcomes_opened": False,
        "ledger_receipt": None,
    }
    ledger["ledger_receipt"] = v2.canonical_hash({**ledger, "ledger_receipt": None})
    if ledger_path.exists():
        existing = v2.read_json(ledger_path)
        if existing != ledger and existing.get("entries_receipt") != ledger["entries_receipt"]:
            raise ValueError("V2-R1 import ledger changed")
        return existing
    v2.write_json_exclusive(ledger_path, ledger)
    return ledger


def _seal_outer(paths: Paths, inner: Mapping[str, Any], freeze: Mapping[str, Any], ledger: Mapping[str, Any]) -> dict[str, Any]:
    status = (
        "PASS_GC_SESSION_TRIGGER_EDGE_V2R1_TECHNICAL_CERTIFICATION"
        if inner.get("status") == "PASS_GC_SESSION_TRIGGER_EDGE_V2_TECHNICAL_CERTIFICATION"
        else "FAIL_GC_SESSION_TRIGGER_EDGE_V2R1_TECHNICAL_CERTIFICATION"
    )
    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_VERDICT_V1_0",
        "status": status,
        "formal_pass": status.startswith("PASS_"),
        "completed_at_utc": v2.utc_now(),
        "imported_v2_commits": EXPECTED_IMPORTED_COMMITS,
        "new_v2r1_commits": EXPECTED_NEW_COMMITS,
        "total_session_commits": int(inner.get("session_commits", -1)),
        "maximum_observed_rss_bytes": int(inner.get("maximum_observed_rss_bytes", -1)),
        "inner_v2_assembly_status": str(inner.get("status")),
        "development_outcomes_opened_or_joined": False,
        "relationships_candidates_execution_trades_pnl_or_returns_calculated": False,
        "year_2025_or_2026_accessed": False,
        "data_acquired": False,
        "charge_incurred_usd": 0.0,
        "completion_policy": (
            "PASS: stop before separately authorized relationship discovery."
            if status.startswith("PASS_")
            else "FAIL: stop without automatic repair or research inference."
        ),
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = v2.canonical_hash({**verdict, "verdict_receipt": None})
    verdict_path = paths.output / "v2r1_verdict.json"
    v2.write_json_exclusive(verdict_path, verdict)
    inner_files = [
        "verdict.json",
        "manifest.json",
        "final_seal.json",
        "technical_diagnostics.json",
        "fragment_manifest.json",
        "primary_support_counts.json",
        "reference_support_counts.json",
    ]
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_MANIFEST_V1_0",
        "status": status,
        "sealed_at_utc": v2.utc_now(),
        "contract": v2.file_record(CONTRACT_PATH),
        "protocol": v2.file_record(PROTOCOL_PATH),
        "pre_value_freeze": v2.file_record(PRE_VALUE_FREEZE_PATH),
        "freeze": v2.file_record(FREEZE_PATH),
        "implementation": v2.file_record(Path(__file__)),
        "inherited_v2_engine": v2.file_record(Path(v2.__file__)),
        "import_ledger": v2.file_record(paths.output / "v2_import_ledger.json"),
        "inner_artifacts": [v2.file_record(paths.output / name) for name in inner_files],
        "verdict": v2.file_record(verdict_path),
        "freeze_receipt": freeze["freeze_receipt"],
        "import_ledger_receipt": ledger["ledger_receipt"],
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = v2.canonical_hash({**manifest, "manifest_receipt": None})
    manifest_path = paths.output / "v2r1_manifest.json"
    v2.write_json_exclusive(manifest_path, manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_FINAL_SEAL_V1_0",
        "status": status,
        "sealed_at_utc": v2.utc_now(),
        "verdict_sha256": v2.sha256_file(verdict_path),
        "manifest_sha256": v2.sha256_file(manifest_path),
        "verdict_receipt": verdict["verdict_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = v2.canonical_hash({**final, "final_seal_receipt": None})
    v2.write_json_exclusive(paths.output / "v2r1_final_seal.json", final)
    return verdict


def seal_failure(paths: Paths, error: Exception) -> None:
    final_path = paths.output / "v2r1_final_seal.json"
    if final_path.exists():
        raise RuntimeError("Refusing to replace V2-R1 final seal")
    failure = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_EXECUTION_FAILURE_V1_0",
        "status": "FAIL_GC_SESSION_TRIGGER_EDGE_V2R1_EXECUTION",
        "failed_at_utc": v2.utc_now(),
        "error_type": type(error).__name__,
        "error_sha256": hashlib.sha256(str(error).encode("utf-8")).hexdigest(),
        "new_committed_sessions": len(list((paths.output / "checkpoints/sessions").glob("*.json"))),
        "outcomes_opened": False,
        "failure_receipt": None,
    }
    failure["failure_receipt"] = v2.canonical_hash({**failure, "failure_receipt": None})
    failure_path = paths.output / "v2r1_execution_failure.json"
    v2.write_json_exclusive(failure_path, failure)
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_FAILURE_MANIFEST_V1_0",
        "status": failure["status"],
        "sealed_at_utc": v2.utc_now(),
        "contract": v2.file_record(CONTRACT_PATH),
        "protocol": v2.file_record(PROTOCOL_PATH),
        "freeze": v2.file_record(FREEZE_PATH),
        "implementation": v2.file_record(Path(__file__)),
        "failure": v2.file_record(failure_path),
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = v2.canonical_hash({**manifest, "manifest_receipt": None})
    manifest_path = paths.output / "v2r1_manifest.json"
    v2.write_json_exclusive(manifest_path, manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_FINAL_SEAL_V1_0",
        "status": failure["status"],
        "sealed_at_utc": v2.utc_now(),
        "failure_sha256": v2.sha256_file(failure_path),
        "manifest_sha256": v2.sha256_file(manifest_path),
        "failure_receipt": failure["failure_receipt"],
        "manifest_receipt": manifest["manifest_receipt"],
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = v2.canonical_hash({**final, "final_seal_receipt": None})
    v2.write_json_exclusive(final_path, final)


def run_development(paths: Paths) -> None:
    freeze = verify_freeze(paths)
    _patch_v2_runtime()
    paths.output.mkdir(parents=True, exist_ok=True)
    if (paths.output / "v2r1_final_seal.json").exists():
        raise RuntimeError("V2-R1 already has a final seal")
    mp = m2.Paths(paths.acquisition, paths.step5b2, paths.context, paths.xau, paths.output)
    s5c, base, registry, acquisition = m2._verified_control(mp, verify_payload_hashes=True)
    contexts, history, context_summary = m2._load_contexts(mp)
    if context_summary.get("status") != "PASS_OUTCOME_BLIND_CONTEXT_PROJECTION":
        raise ValueError("Step 5C context projection failed")
    rows = list(registry["rows"])
    sessions, xau_diagnostics = m2._load_xau(mp, rows)
    missing_keys = r2.xau_missing_keys(rows, sessions)
    request_map = m2._request_map(acquisition)
    ledger = _write_import_ledger(paths, rows)
    free_storage = __import__("shutil").disk_usage(paths.output).free
    preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2R1_PREFLIGHT_V1_0",
        "status": "PASS_V2R1_CONTINUATION_READINESS",
        "completed_at_utc": v2.utc_now(),
        "formal_gates": {
            "freeze_valid": True,
            "exact_293_imported_v2_commits": len(ledger["entries"]) == 293,
            "exact_374_available_sessions": sum(int(row["expected_bucket_rows"]) > 0 for row in rows) == 374,
            "exact_three_unresolved_xau_timestamps": len(missing_keys) == 3,
            "exact_80_source_requests_hash_verified": len(acquisition["requests"]) == 80,
            "minimum_20_gib_free_output_storage": free_storage >= 20 * 1024**3,
            "no_2025_or_2026_rows": all(str(row["session_date"]) < "2025-01-01" for row in rows),
            "outcomes_locked": True,
            "zero_acquisition_and_charge": True,
        },
        "outcomes_opened": False,
        "free_storage_bytes": free_storage,
    }
    if not all(preflight["formal_gates"].values()):
        raise ValueError("V2-R1 preflight failed")
    preflight_path = paths.output / "preflight.json"
    if not preflight_path.exists():
        v2.write_json_exclusive(preflight_path, preflight)
    attempt_path = paths.output / "attempt_started.json"
    if not attempt_path.exists():
        v2.write_json_exclusive(
            attempt_path,
            {
                "version": "GC_SESSION_TRIGGER_EDGE_V2R1_LOGICAL_ATTEMPT_V1_0",
                "logical_attempt": 1,
                "maximum_logical_attempts": 1,
                "started_at_utc": v2.utc_now(),
                "append_only_resume_permitted": True,
                "outcomes_opened": False,
            },
        )
    invocation = len(list((paths.output / "invocations").glob("*_started.json"))) + 1
    invocation_path = paths.output / "invocations" / f"{invocation:04d}_started.json"
    v2.write_json_exclusive(
        invocation_path,
        {
            "version": "GC_SESSION_TRIGGER_EDGE_V2R1_INVOCATION_V1_0",
            "invocation": invocation,
            "logical_attempt": 1,
            "started_at_utc": v2.utc_now(),
            "freeze_receipt": freeze["freeze_receipt"],
            "outcomes_opened": False,
        },
    )
    old_by_id = {
        str(v2.read_json(Path(str(entry["commit_file"]["path"])))["row_id"]): Path(
            str(entry["commit_file"]["path"])
        )
        for entry in ledger["entries"]
    }
    commits: list[dict[str, Any]] = []
    new_count = 0
    try:
        for row in rows:
            if int(row["expected_bucket_rows"]) == 0:
                continue
            row_id = str(row["row_id"])
            if row_id in old_by_id:
                commit = v2.verify_session_commit(old_by_id[row_id])
                source = "IMPORTED_VERIFIED_V2"
            else:
                commit_path = v2.session_commit_path(paths.output, row_id)
                if commit_path.exists():
                    commit = v2.verify_session_commit(commit_path)
                else:
                    mbo_request = request_map[str(row["mbo_request_id"])]
                    mbp_request = request_map[str(row["mbp10_request_id"])]
                    mbo_path = Path(str(mbo_request["normalization"]["normalized_payload"]["path"]))
                    mbp_path = Path(str(mbp_request["normalization"]["normalized_payload"]["path"]))
                    checkpoints: dict[str, dict[str, Any]] = {}
                    for implementation in IMPLEMENTATIONS:
                        checkpoints[implementation] = v2.ensure_feature_pass(
                            output=paths.output,
                            row_id=row_id,
                            classification="OUTCOME_BLIND_2021_2024_DEVELOPMENT_TECHNICAL",
                            implementation=implementation,
                            mbo_path=mbo_path,
                            mbp_path=mbp_path,
                            row=row,
                            invocation=invocation,
                        )
                    commit = v2.materialize_decisions_and_events(
                        output=paths.output,
                        row=row,
                        checkpoints=checkpoints,
                        context=contexts[str(row["source_step5c_row_id"])],
                        history=history,
                        session=sessions[row_id],
                        s5c=s5c,
                        base=base,
                        invocation=invocation,
                    )
                new_count += 1
                source = "V2R1_NEW_OR_RESUMED"
            commits.append(commit)
            print(
                json.dumps(
                    {
                        "stage": "V2R1_SESSION_READY",
                        "completed": len(commits),
                        "total": 374,
                        "row_id": row_id,
                        "source": source,
                        "outcomes": False,
                    },
                    sort_keys=True,
                ),
                flush=True,
            )
        if len(commits) != 374 or new_count != EXPECTED_NEW_COMMITS:
            raise ValueError(f"V2-R1 continuation counts changed: total={len(commits)} new={new_count}")
        old_contract, old_protocol, old_freeze = v2.CONTRACT_PATH, v2.PROTOCOL_PATH, v2.FREEZE_PATH
        v2.CONTRACT_PATH, v2.PROTOCOL_PATH, v2.FREEZE_PATH = CONTRACT_PATH, PROTOCOL_PATH, FREEZE_PATH
        try:
            inner = v2.finalize_development(
                paths=paths.v2_paths(paths.output),
                freeze=freeze,
                rows=rows,
                commits=commits,
                xau_diagnostics=xau_diagnostics,
                missing_keys=missing_keys,
                invocation=invocation,
            )
        finally:
            v2.CONTRACT_PATH, v2.PROTOCOL_PATH, v2.FREEZE_PATH = old_contract, old_protocol, old_freeze
        verdict = _seal_outer(paths, inner, freeze, ledger)
        v2.write_json_exclusive(
            paths.output / "invocations" / f"{invocation:04d}_completed.json",
            {
                "version": "GC_SESSION_TRIGGER_EDGE_V2R1_INVOCATION_COMPLETION_V1_0",
                "invocation": invocation,
                "completed_at_utc": v2.utc_now(),
                "total_commits": len(commits),
                "imported_commits": EXPECTED_IMPORTED_COMMITS,
                "new_commits": EXPECTED_NEW_COMMITS,
                "status": verdict["status"],
                "outcomes_opened": False,
            },
        )
        print(json.dumps(verdict, sort_keys=True))
    except Exception as error:
        if not (paths.output / "v2r1_final_seal.json").exists():
            seal_failure(paths, error)
        raise


def verify_final(paths: Paths) -> dict[str, Any]:
    freeze = verify_freeze(paths)
    final = v2.read_json(paths.output / "v2r1_final_seal.json")
    manifest = v2.read_json(paths.output / "v2r1_manifest.json")
    if not v2.receipt_valid(final, "final_seal_receipt") or not v2.receipt_valid(
        manifest, "manifest_receipt"
    ):
        raise ValueError("V2-R1 final receipt failed")
    if "inner_artifacts" in manifest:
        verdict = v2.read_json(paths.output / "v2r1_verdict.json")
        if not v2.receipt_valid(verdict, "verdict_receipt"):
            raise ValueError("V2-R1 verdict receipt failed")
        if final["verdict_sha256"] != v2.sha256_file(paths.output / "v2r1_verdict.json"):
            raise ValueError("V2-R1 verdict hash failed")
        for record in manifest["inner_artifacts"]:
            v2.verify_record(record)
        v2.verify_record(manifest["import_ledger"])
    else:
        v2.verify_record(manifest["failure"])
    if final["manifest_sha256"] != v2.sha256_file(paths.output / "v2r1_manifest.json"):
        raise ValueError("V2-R1 manifest hash failed")
    result = {
        "status": final["status"],
        "final_seal_receipt": final["final_seal_receipt"],
        "freeze_receipt": freeze["freeze_receipt"],
    }
    print(json.dumps(result, sort_keys=True))
    return result


def build_paths(args: argparse.Namespace) -> Paths:
    return Paths(
        acquisition=Path(args.acquisition),
        step5b2=Path(args.step5b2),
        context=Path(args.context),
        xau=Path(args.xau),
        old_m2=Path(args.old_m2),
        old_r1=Path(args.old_r1),
        old_a1=Path(args.old_a1),
        old_v1=Path(args.old_v1),
        old_v2=Path(args.old_v2),
        output=Path(args.output),
        engineering_output=Path(args.engineering_output),
        data_root=Path(args.data_root),
        artifact_root=Path(args.artifact_root),
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("feature-worker", "prove-freeze", "execute", "verify"))
    parser.add_argument("--spec")
    parser.add_argument("--acquisition", default=str(m2.DEFAULT_ACQUISITION))
    parser.add_argument("--step5b2", default=str(m2.DEFAULT_STEP5B2))
    parser.add_argument("--context", default=str(m2.DEFAULT_CONTEXT))
    parser.add_argument("--xau", default=str(m2.DEFAULT_XAU))
    parser.add_argument("--old-m2", default=str(r2.DEFAULT_OLD_M2))
    parser.add_argument("--old-r1", default=str(r2.DEFAULT_OLD_R1))
    parser.add_argument("--old-a1", default=str(r2.DEFAULT_OLD_A1))
    parser.add_argument("--old-v1", default=str(r2.DEFAULT_OUTPUT))
    parser.add_argument("--old-v2", default=str(v2.DEFAULT_OUTPUT))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    parser.add_argument("--engineering-output", default=str(DEFAULT_ENGINEERING_OUTPUT))
    parser.add_argument("--data-root", default=str(ROOT))
    parser.add_argument("--artifact-root", default=str(ROOT / "research_artifacts"))
    args = parser.parse_args()
    if args.action == "feature-worker":
        if not args.spec:
            parser.error("feature-worker requires --spec")
        worker_feature(Path(args.spec))
        return
    paths = build_paths(args)
    if args.action == "prove-freeze":
        run_proof(paths)
    elif args.action == "execute":
        run_development(paths)
    else:
        verify_final(paths)


if __name__ == "__main__":
    main()
