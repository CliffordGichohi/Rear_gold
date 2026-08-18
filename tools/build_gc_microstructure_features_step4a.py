#!/usr/bin/env python3
"""Build the frozen Step 4A engineering-only GC feature payload.

The tool keeps vendor MBP-10 book states and MBO event flows separate.  It
never aligns MBO rows to MBP-10 rows and never calculates outcomes, signals,
execution, trades, or PnL.  Emitted feature values are sealed without being
printed or inspected by the tool's operator.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import struct
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq


REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a_protocol_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_4a_freeze_v01.json"
)
STEP3F_MANIFEST_PATH = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3f_v01"
    / "manifest.json"
)
MBO_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbo_engineering_pilot"
    / "GLBX-20260730-WB9AXCVFET"
    / "normalized"
    / "gc_v_0_2024_01_09_mbo.parquet"
)
MBP_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbp10_engineering_benchmark"
    / "GLBX-20260731-UJHWEDQUSX"
    / "normalized"
    / "gc_v_0_2024_01_09_mbp10.parquet"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_4a_v01"
)
REPORT_PATH = REPO_ROOT / "GC_MICROSTRUCTURE_STEP_4A_REPORT.md"

EXPECTED_PROTOCOL_SHA256 = (
    "8f1ba7230919b7422344253d4f3e55fea1e86495551cbbbf53f3e1bdcb9ec3a2"
)
EXPECTED_FREEZE_SHA256 = (
    "dba14cef54b8469b28c1e30700c1f0bf64d77962a82479011e53361ac916d32f"
)
EXPECTED_STEP3F_MANIFEST_HASH = (
    "aed3bbff4aaba27dfa574812a2f311b9aee06371e1da9eec84c8da9319072a81"
)
EXPECTED_STEP3F_VERDICT_HASH = (
    "d8d8b6283117c570d71aeafbaf3370713596b66f75845cf33cb16f9c13c89213"
)
EXPECTED_MBO_SHA256 = (
    "43a8a3bb2be9a4a36ab324e3fe0ca0e29ccb4529f445013a87156d3bad4c0ba3"
)
EXPECTED_MBP_SHA256 = (
    "4ead358f538d7c383a14f39bbde35b8ccfa21e38e58205edbc51bedfb2ed80d4"
)
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBP_RECORDS = 1_924_786
EXPECTED_PUBLISHER_ID = 1
EXPECTED_INSTRUMENT_ID = 41_512

DAY_START_NS = 1_704_758_400_000_000_000
DAY_END_NS = 1_704_844_800_000_000_000
BUCKET_WIDTH_NS = 1_000_000_000
BUCKET_COUNT = 86_400
RATIO_SCALE = 1_000_000_000
UNDEFINED_PRICE = 9_223_372_036_854_775_807
F_BAD_TS_RECV = 8
F_MAYBE_BAD_BOOK = 4
F_SNAPSHOT = 32
F_TOB = 64
BATCH_SIZE = 50_000

SEGMENTS = (
    (
        "CONTINUOUS_00_22",
        "CONTINUOUS_MATCHING",
        1_704_758_400_000_000_000,
        1_704_837_600_000_000_000,
    ),
    (
        "MAINTENANCE_22_2245",
        "MAINTENANCE",
        1_704_837_600_000_000_000,
        1_704_840_300_000_000_000,
    ),
    (
        "PRE_OPEN_2245_23",
        "PRE_OPEN",
        1_704_840_300_000_000_000,
        1_704_841_200_000_000_000,
    ),
    (
        "CONTINUOUS_23_24",
        "CONTINUOUS_MATCHING",
        1_704_841_200_000_000_000,
        1_704_844_800_000_000_000,
    ),
)

MBO_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "action",
    "side",
    "price_fixed_1e9",
    "size",
    "order_id",
    "flags",
    "sequence",
)
BOOK_FIELDS = tuple(
    f"{side}_{kind}_{level:02d}"
    for level in range(10)
    for side in ("bid", "ask")
    for kind in ("px", "sz", "ct")
)
MBP_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "sequence",
    "action",
    "side",
    "depth",
    "flags",
    *BOOK_FIELDS,
)

IDENTITY_COLUMNS = (
    "bucket_index",
    "bucket_start_ns",
    "bucket_end_ns",
    "market_segment",
    "market_state",
)
MBO_COUNT_COLUMNS = (
    "mbo_total_records",
    "mbo_live_records",
    "mbo_snapshot_records",
    "mbo_reset_count",
    "mbo_none_count",
    "mbo_unknown_action_count",
    "mbo_invalid_side_count",
    "mbo_nonpositive_size_count",
    "mbo_undefined_price_count",
    "mbo_bad_ts_recv_flag_count",
    "mbo_maybe_bad_book_flag_count",
    "mbo_top_of_book_add_count",
)
MBO_SIDE_FLOW_COLUMNS = (
    "add_count_bid",
    "add_count_ask",
    "add_qty_bid",
    "add_qty_ask",
    "cancel_count_bid",
    "cancel_count_ask",
    "cancel_qty_bid",
    "cancel_qty_ask",
    "modify_count_bid",
    "modify_count_ask",
    "modify_new_size_qty_bid",
    "modify_new_size_qty_ask",
    "trade_count_buy",
    "trade_count_sell",
    "trade_count_unknown",
    "trade_qty_buy",
    "trade_qty_sell",
    "trade_qty_unknown",
    "fill_count_bid",
    "fill_count_ask",
    "fill_count_unknown",
    "fill_qty_bid",
    "fill_qty_ask",
    "fill_qty_unknown",
)
MBO_RATIO_COLUMNS = (
    "add_imbalance_ppb",
    "cancel_pressure_imbalance_ppb",
    "displayed_pressure_ppb",
    "trade_imbalance_ppb",
)
MBP_STATE_COLUMNS = (
    "mbp_update_count",
    "mbp_snapshot_count",
    "mbp_reset_count",
    "mbp_unknown_action_count",
    "mbp_bad_ts_recv_flag_count",
    "mbp_maybe_bad_book_flag_count",
    "quote_ofi_transition_count",
    "quote_ofi_skipped_count",
    "quote_ofi_raw",
    "state_available",
    "book_two_sided",
    "state_source_row_ordinal",
    "state_ts_recv_ns",
    "book_age_ns",
    "book_locked",
    "book_crossed",
)
MBP_PRICE_COLUMNS = (
    "best_bid_px_fixed_1e9",
    "best_ask_px_fixed_1e9",
    "spread_fixed_1e9",
    "midpoint_fixed_1e9",
    "microprice_fixed_1e9",
)
MBP_DEPTH_COLUMNS = (
    "bid_depth_l1",
    "ask_depth_l1",
    "bid_depth_l5",
    "ask_depth_l5",
    "bid_depth_l10",
    "ask_depth_l10",
    "bid_order_count_l1",
    "ask_order_count_l1",
    "bid_order_count_l5",
    "ask_order_count_l5",
    "bid_order_count_l10",
    "ask_order_count_l10",
    "depth_imbalance_l1_ppb",
    "depth_imbalance_l5_ppb",
    "depth_imbalance_l10_ppb",
    "order_count_imbalance_l1_ppb",
    "order_count_imbalance_l5_ppb",
    "order_count_imbalance_l10_ppb",
    "depth_concentration_l1_ppb",
)
FEATURE_COLUMNS = (
    *IDENTITY_COLUMNS,
    *MBO_COUNT_COLUMNS,
    *MBO_SIDE_FLOW_COLUMNS,
    *MBO_RATIO_COLUMNS,
    *MBP_STATE_COLUMNS,
    *MBP_PRICE_COLUMNS,
    *MBP_DEPTH_COLUMNS,
)

BOOL_COLUMNS = {
    "state_available",
    "book_two_sided",
    "book_locked",
    "book_crossed",
}
STRING_COLUMNS = {"market_segment", "market_state"}
NULLABLE_INT_COLUMNS = {
    *MBO_RATIO_COLUMNS,
    "state_source_row_ordinal",
    "state_ts_recv_ns",
    "book_age_ns",
    *MBP_PRICE_COLUMNS,
    *MBP_DEPTH_COLUMNS,
}

FEATURE_SCHEMA = pa.schema(
    [
        pa.field(
            name,
            (
                pa.string()
                if name in STRING_COLUMNS
                else pa.bool_()
                if name in BOOL_COLUMNS
                else pa.int64()
            ),
            nullable=name in NULLABLE_INT_COLUMNS,
        )
        for name in FEATURE_COLUMNS
    ]
)

KNOWN_ACTIONS = {"A", "C", "M", "T", "F", "R", "N"}
INT64 = struct.Struct(">q")
UINT32 = struct.Struct(">I")


@dataclass(frozen=True, slots=True)
class PrimaryBookState:
    ordinal: int
    recv: int
    action: str
    flags: int
    levels: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class ReferenceBookState:
    ordinal: int
    recv: int
    action: str
    flags: int
    levels: dict[str, int]


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("primary", "reference", "seal", "verify"),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(args.action, Path(args.output))


def run_stage(action: str, output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    output.mkdir(parents=True, exist_ok=True)

    if action in {"primary", "reference"}:
        feature_path = output / f"{action}_features.parquet"
        summary_path = output / f"{action}_summary.json"
        if feature_path.exists() or summary_path.exists():
            raise FileExistsError(
                f"Refusing to overwrite existing Step 4A {action} output"
            )
        if action == "primary":
            columns, audits, input_checksums = _calculate_primary()
        else:
            columns, audits, input_checksums = _calculate_reference()
        _validate_column_lengths(columns)
        integrity = _integrity_checks(columns, audits, context)
        hashes = _feature_hashes(columns)
        _write_feature_parquet(feature_path, columns)
        parquet_sha = _sha256(feature_path)
        summary = {
            "version": "GC_MICROSTRUCTURE_STEP_4A_RUN_V0_1",
            "implementation": action,
            "classification": "ENGINEERING_ONLY",
            "research_or_validation_credit": "NONE",
            "protocol_sha256": EXPECTED_PROTOCOL_SHA256,
            "freeze_sha256": EXPECTED_FREEZE_SHA256,
            "tool_sha256": _sha256(Path(__file__)),
            "mbo_source_sha256": EXPECTED_MBO_SHA256,
            "mbp10_source_sha256": EXPECTED_MBP_SHA256,
            "source_input_checksums": input_checksums,
            "feature_rows": BUCKET_COUNT,
            "feature_columns": list(FEATURE_COLUMNS),
            "feature_column_count": len(FEATURE_COLUMNS),
            "feature_schema_hash": _feature_schema_hash(),
            "feature_hashes": hashes,
            "feature_parquet": {
                "path": str(feature_path.resolve()),
                "bytes": feature_path.stat().st_size,
                "sha256": parquet_sha,
            },
            "audits": audits,
            "integrity_checks": integrity,
            "formal_integrity_pass": all(integrity.values()),
            "mbo_mbp_alignment_attempts": 0,
            "additional_data_acquired": False,
            "another_date_inspected": False,
            "market_values_human_or_model_inspected": False,
            "outcomes_accessed": False,
            "signals_calculated": False,
            "execution_optimized": False,
            "pnl_calculated": False,
        }
        _write_json_atomic(summary_path, summary)
        print(
            json.dumps(
                {
                    "stage": (
                        f"GC_MICROSTRUCTURE_STEP_4A_{action.upper()}_COMPLETE"
                    ),
                    "implementation": action,
                    "mbo_records": audits["mbo"]["records"],
                    "mbp10_records": audits["mbp10"]["records"],
                    "feature_rows": BUCKET_COUNT,
                    "feature_columns": len(FEATURE_COLUMNS),
                    "integrity_pass": all(integrity.values()),
                    "complete_row_checksum": hashes[
                        "complete_row_checksum"
                    ],
                    "market_values_reported": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if action == "seal":
        _seal(output, context)
        return
    if action == "verify":
        _verify_seal(output)
        return
    raise AssertionError(action)


def _calculate_primary() -> tuple[
    dict[str, list[Any]], dict[str, Any], dict[str, str]
]:
    event = {name: [0] * BUCKET_COUNT for name in (*MBO_COUNT_COLUMNS, *MBO_SIDE_FLOW_COLUMNS)}
    mbo_audit: Counter[str] = Counter()
    mbo_hash = hashlib.sha256()
    prior_recv: int | None = None
    prior_ordinal: int | None = None

    parquet = pq.ParquetFile(MBO_PATH)
    for batch in parquet.iter_batches(
        batch_size=BATCH_SIZE,
        columns=list(MBO_COLUMNS),
    ):
        _update_batch_checksum(mbo_hash, batch)
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in MBO_COLUMNS
        }
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        ordinals = arrays["source_row_ordinal"].to_numpy(
            zero_copy_only=False
        )
        publishers = arrays["publisher_id"].to_numpy(zero_copy_only=False)
        instruments = arrays["instrument_id"].to_numpy(zero_copy_only=False)
        prices = arrays["price_fixed_1e9"].to_numpy(zero_copy_only=False)
        sizes = arrays["size"].to_numpy(zero_copy_only=False)
        flags_values = arrays["flags"].to_numpy(zero_copy_only=False)
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()

        for index in range(batch.num_rows):
            recv = int(receives[index])
            ordinal = int(ordinals[index])
            action = str(actions[index])
            side = str(sides[index])
            price = int(prices[index])
            size = int(sizes[index])
            flags = int(flags_values[index])
            mbo_audit["records"] += 1
            if prior_recv is not None and recv < prior_recv:
                mbo_audit["receive_timestamp_regressions"] += 1
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                mbo_audit["source_ordinal_regressions"] += 1
            prior_recv = recv
            prior_ordinal = ordinal
            if int(publishers[index]) != EXPECTED_PUBLISHER_ID:
                mbo_audit["publisher_mismatches"] += 1
            if int(instruments[index]) != EXPECTED_INSTRUMENT_ID:
                mbo_audit["instrument_mismatches"] += 1
            if not DAY_START_NS <= recv < DAY_END_NS:
                mbo_audit["outside_frozen_day"] += 1
                continue
            bucket = (recv - DAY_START_NS) // BUCKET_WIDTH_NS
            mbo_audit["allocated_records"] += 1
            event["mbo_total_records"][bucket] += 1
            if flags & F_BAD_TS_RECV:
                event["mbo_bad_ts_recv_flag_count"][bucket] += 1
            if flags & F_MAYBE_BAD_BOOK:
                event["mbo_maybe_bad_book_flag_count"][bucket] += 1
            if flags & F_SNAPSHOT:
                event["mbo_snapshot_records"][bucket] += 1
                continue

            event["mbo_live_records"][bucket] += 1
            if action not in KNOWN_ACTIONS:
                event["mbo_unknown_action_count"][bucket] += 1
                continue
            if action in {"A", "C", "M", "T", "F"} and size <= 0:
                event["mbo_nonpositive_size_count"][bucket] += 1
            if action in {"A", "C", "M"} and price == UNDEFINED_PRICE:
                event["mbo_undefined_price_count"][bucket] += 1

            if action == "R":
                event["mbo_reset_count"][bucket] += 1
                continue
            if action == "N":
                event["mbo_none_count"][bucket] += 1
                continue
            if action in {"A", "C", "M"} and side not in {"A", "B"}:
                event["mbo_invalid_side_count"][bucket] += 1
                continue
            if action in {"T", "F"} and side not in {"A", "B", "N"}:
                event["mbo_invalid_side_count"][bucket] += 1
                continue

            if action == "A":
                if flags & F_TOB:
                    event["mbo_top_of_book_add_count"][bucket] += 1
                elif size > 0 and price != UNDEFINED_PRICE:
                    suffix = "bid" if side == "B" else "ask"
                    event[f"add_count_{suffix}"][bucket] += 1
                    event[f"add_qty_{suffix}"][bucket] += size
            elif action == "C":
                if size > 0:
                    suffix = "bid" if side == "B" else "ask"
                    event[f"cancel_count_{suffix}"][bucket] += 1
                    event[f"cancel_qty_{suffix}"][bucket] += size
            elif action == "M":
                if size > 0 and price != UNDEFINED_PRICE:
                    suffix = "bid" if side == "B" else "ask"
                    event[f"modify_count_{suffix}"][bucket] += 1
                    event[f"modify_new_size_qty_{suffix}"][bucket] += size
            elif action == "T":
                if size > 0:
                    suffix = (
                        "buy" if side == "B" else "sell" if side == "A" else "unknown"
                    )
                    event[f"trade_count_{suffix}"][bucket] += 1
                    event[f"trade_qty_{suffix}"][bucket] += size
            elif action == "F" and size > 0:
                suffix = (
                    "bid" if side == "B" else "ask" if side == "A" else "unknown"
                )
                event[f"fill_count_{suffix}"][bucket] += 1
                event[f"fill_qty_{suffix}"][bucket] += size

    mbo_audit["buckets_with_records"] = sum(
        value > 0 for value in event["mbo_total_records"]
    )

    mbp = {name: [0] * BUCKET_COUNT for name in MBP_STATE_COLUMNS[:9]}
    latest_by_bucket: list[PrimaryBookState | None] = [None] * BUCKET_COUNT
    mbp_audit: Counter[str] = Counter()
    mbp_hash = hashlib.sha256()
    prior_recv = None
    prior_ordinal = None
    prior_transition: tuple[
        int, bool, str, int, int, int, int
    ] | None = None
    prior_segment: int | None = None

    parquet = pq.ParquetFile(MBP_PATH)
    for batch in parquet.iter_batches(
        batch_size=BATCH_SIZE,
        columns=list(MBP_COLUMNS),
    ):
        _update_batch_checksum(mbp_hash, batch)
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in MBP_COLUMNS
        }
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        ordinals = arrays["source_row_ordinal"].to_numpy(
            zero_copy_only=False
        )
        publishers = arrays["publisher_id"].to_numpy(zero_copy_only=False)
        instruments = arrays["instrument_id"].to_numpy(zero_copy_only=False)
        flags_values = arrays["flags"].to_numpy(zero_copy_only=False)
        actions = arrays["action"].to_pylist()
        level_arrays = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in BOOK_FIELDS
        }
        _primary_validate_level_arrays(level_arrays, mbp_audit)

        for index in range(batch.num_rows):
            recv = int(receives[index])
            ordinal = int(ordinals[index])
            action = str(actions[index])
            flags = int(flags_values[index])
            mbp_audit["records"] += 1
            if prior_recv is not None and recv < prior_recv:
                mbp_audit["receive_timestamp_regressions"] += 1
            if prior_ordinal is not None and ordinal <= prior_ordinal:
                mbp_audit["source_ordinal_regressions"] += 1
            prior_recv = recv
            prior_ordinal = ordinal
            if int(publishers[index]) != EXPECTED_PUBLISHER_ID:
                mbp_audit["publisher_mismatches"] += 1
            if int(instruments[index]) != EXPECTED_INSTRUMENT_ID:
                mbp_audit["instrument_mismatches"] += 1
            if not DAY_START_NS <= recv < DAY_END_NS:
                mbp_audit["outside_frozen_day"] += 1
                continue
            bucket = (recv - DAY_START_NS) // BUCKET_WIDTH_NS
            segment_index = _segment_index_for_timestamp(recv)
            mbp_audit["allocated_records"] += 1
            mbp["mbp_update_count"][bucket] += 1
            if flags & F_SNAPSHOT:
                mbp["mbp_snapshot_count"][bucket] += 1
            if action == "R":
                mbp["mbp_reset_count"][bucket] += 1
            if action not in KNOWN_ACTIONS:
                mbp["mbp_unknown_action_count"][bucket] += 1
            if flags & F_BAD_TS_RECV:
                mbp["mbp_bad_ts_recv_flag_count"][bucket] += 1
            if flags & F_MAYBE_BAD_BOOK:
                mbp["mbp_maybe_bad_book_flag_count"][bucket] += 1

            bid_px = int(level_arrays["bid_px_00"][index])
            bid_sz = int(level_arrays["bid_sz_00"][index])
            bid_ct = int(level_arrays["bid_ct_00"][index])
            ask_px = int(level_arrays["ask_px_00"][index])
            ask_sz = int(level_arrays["ask_sz_00"][index])
            ask_ct = int(level_arrays["ask_ct_00"][index])
            two_sided = _primary_two_sided(
                bid_px, bid_sz, bid_ct, ask_px, ask_sz, ask_ct
            )
            if (
                two_sided
                and SEGMENTS[segment_index][1] == "CONTINUOUS_MATCHING"
                and ask_px < bid_px
            ):
                mbp_audit["continuous_crossed_book_rows"] += 1
            if prior_segment != segment_index:
                prior_transition = None
                prior_segment = segment_index
            eligible = (
                prior_transition is not None
                and not bool(flags & F_SNAPSHOT)
                and action != "R"
                and prior_transition[1]
                and prior_transition[2] != "R"
                and two_sided
            )
            if eligible:
                (
                    _prior_recv_unused,
                    _prior_two_sided,
                    _prior_action,
                    prev_bid_px,
                    prev_bid_sz,
                    prev_ask_px,
                    prev_ask_sz,
                ) = prior_transition
                ofi = (
                    (bid_sz if bid_px >= prev_bid_px else 0)
                    - (prev_bid_sz if bid_px <= prev_bid_px else 0)
                    - (ask_sz if ask_px <= prev_ask_px else 0)
                    + (prev_ask_sz if ask_px >= prev_ask_px else 0)
                )
                mbp["quote_ofi_transition_count"][bucket] += 1
                mbp["quote_ofi_raw"][bucket] += ofi
            else:
                mbp["quote_ofi_skipped_count"][bucket] += 1
            prior_transition = (
                recv,
                two_sided and not bool(flags & F_SNAPSHOT),
                action,
                bid_px,
                bid_sz,
                ask_px,
                ask_sz,
            )

            next_bucket_differs = (
                index == batch.num_rows - 1
                or (
                    int(receives[index + 1]) - DAY_START_NS
                )
                // BUCKET_WIDTH_NS
                != bucket
            )
            if next_bucket_differs:
                levels = tuple(
                    int(level_arrays[name][index]) for name in BOOK_FIELDS
                )
                latest_by_bucket[bucket] = PrimaryBookState(
                    ordinal=ordinal,
                    recv=recv,
                    action=action,
                    flags=flags,
                    levels=levels,
                )

    mbp_audit["buckets_with_updates"] = sum(
        value > 0 for value in mbp["mbp_update_count"]
    )

    columns = _primary_materialize(event, mbp, latest_by_bucket)
    audits = {
        "mbo": _complete_audit(mbo_audit),
        "mbp10": _complete_audit(mbp_audit),
        "output": _output_audit(columns),
        "alignment_attempts": 0,
        "market_values_human_or_model_inspected": False,
    }
    return columns, audits, {
        "mbo_complete_pass": mbo_hash.hexdigest(),
        "mbp10_complete_pass": mbp_hash.hexdigest(),
    }


def _calculate_reference() -> tuple[
    dict[str, list[Any]], dict[str, Any], dict[str, str]
]:
    event_by_bucket: dict[int, Counter[str]] = defaultdict(Counter)
    mbo_stats: Counter[str] = Counter()
    mbo_hash = hashlib.sha256()
    last_receive: int | None = None
    last_ordinal: int | None = None

    parquet = pq.ParquetFile(MBO_PATH)
    for batch in parquet.iter_batches(
        batch_size=BATCH_SIZE,
        columns=list(MBO_COLUMNS),
    ):
        _update_batch_checksum(mbo_hash, batch)
        receives = batch.column(
            batch.schema.get_field_index("ts_recv")
        ).cast(pa.int64()).to_numpy(zero_copy_only=False)
        ordinals = batch.column(
            batch.schema.get_field_index("source_row_ordinal")
        ).to_numpy(zero_copy_only=False)
        publishers = batch.column(
            batch.schema.get_field_index("publisher_id")
        ).to_numpy(zero_copy_only=False)
        instruments = batch.column(
            batch.schema.get_field_index("instrument_id")
        ).to_numpy(zero_copy_only=False)
        prices = batch.column(
            batch.schema.get_field_index("price_fixed_1e9")
        ).to_numpy(zero_copy_only=False)
        sizes = batch.column(
            batch.schema.get_field_index("size")
        ).to_numpy(zero_copy_only=False)
        flags_values = batch.column(
            batch.schema.get_field_index("flags")
        ).to_numpy(zero_copy_only=False)
        actions = batch.column(
            batch.schema.get_field_index("action")
        ).to_pylist()
        sides = batch.column(
            batch.schema.get_field_index("side")
        ).to_pylist()

        for row in range(batch.num_rows):
            receive = int(receives[row])
            ordinal = int(ordinals[row])
            current_action = str(actions[row])
            current_side = str(sides[row])
            current_price = int(prices[row])
            current_size = int(sizes[row])
            current_flags = int(flags_values[row])
            mbo_stats["records"] += 1
            if last_receive is not None and receive < last_receive:
                mbo_stats["receive_timestamp_regressions"] += 1
            if last_ordinal is not None and ordinal <= last_ordinal:
                mbo_stats["source_ordinal_regressions"] += 1
            last_receive = receive
            last_ordinal = ordinal
            mbo_stats["publisher_mismatches"] += int(
                int(publishers[row]) != EXPECTED_PUBLISHER_ID
            )
            mbo_stats["instrument_mismatches"] += int(
                int(instruments[row]) != EXPECTED_INSTRUMENT_ID
            )
            if receive < DAY_START_NS or receive >= DAY_END_NS:
                mbo_stats["outside_frozen_day"] += 1
                continue
            key = int((receive - DAY_START_NS) // BUCKET_WIDTH_NS)
            target = event_by_bucket[key]
            mbo_stats["allocated_records"] += 1
            target["mbo_total_records"] += 1
            target["mbo_bad_ts_recv_flag_count"] += int(
                bool(current_flags & F_BAD_TS_RECV)
            )
            target["mbo_maybe_bad_book_flag_count"] += int(
                bool(current_flags & F_MAYBE_BAD_BOOK)
            )
            if current_flags & F_SNAPSHOT:
                target["mbo_snapshot_records"] += 1
                continue

            target["mbo_live_records"] += 1
            if current_action not in KNOWN_ACTIONS:
                target["mbo_unknown_action_count"] += 1
                continue
            quantity_action = current_action in {"A", "C", "M", "T", "F"}
            if quantity_action and current_size <= 0:
                target["mbo_nonpositive_size_count"] += 1
            if current_action in {"A", "C", "M"} and current_price == UNDEFINED_PRICE:
                target["mbo_undefined_price_count"] += 1

            if current_action in {"R", "N"}:
                target[
                    "mbo_reset_count" if current_action == "R" else "mbo_none_count"
                ] += 1
                continue
            side_allowed = (
                current_side in {"A", "B"}
                if current_action in {"A", "C", "M"}
                else current_side in {"A", "B", "N"}
            )
            if not side_allowed:
                target["mbo_invalid_side_count"] += 1
                continue

            resting_suffix = "bid" if current_side == "B" else "ask"
            if current_action == "A":
                if current_flags & F_TOB:
                    target["mbo_top_of_book_add_count"] += 1
                elif current_size > 0 and current_price != UNDEFINED_PRICE:
                    target[f"add_count_{resting_suffix}"] += 1
                    target[f"add_qty_{resting_suffix}"] += current_size
            elif current_action == "C" and current_size > 0:
                target[f"cancel_count_{resting_suffix}"] += 1
                target[f"cancel_qty_{resting_suffix}"] += current_size
            elif (
                current_action == "M"
                and current_size > 0
                and current_price != UNDEFINED_PRICE
            ):
                target[f"modify_count_{resting_suffix}"] += 1
                target[f"modify_new_size_qty_{resting_suffix}"] += current_size
            elif current_action == "T" and current_size > 0:
                aggressor = {"B": "buy", "A": "sell", "N": "unknown"}[
                    current_side
                ]
                target[f"trade_count_{aggressor}"] += 1
                target[f"trade_qty_{aggressor}"] += current_size
            elif current_action == "F" and current_size > 0:
                fill_side = {"B": "bid", "A": "ask", "N": "unknown"}[
                    current_side
                ]
                target[f"fill_count_{fill_side}"] += 1
                target[f"fill_qty_{fill_side}"] += current_size

    mbo_stats["buckets_with_records"] = len(event_by_bucket)

    mbp_by_bucket: dict[int, Counter[str]] = defaultdict(Counter)
    latest_states: dict[int, ReferenceBookState] = {}
    mbp_stats: Counter[str] = Counter()
    mbp_hash = hashlib.sha256()
    last_receive = None
    last_ordinal = None
    previous_by_segment: dict[
        int, dict[str, int | str | bool]
    ] = {}

    parquet = pq.ParquetFile(MBP_PATH)
    for batch in parquet.iter_batches(
        batch_size=BATCH_SIZE,
        columns=list(MBP_COLUMNS),
    ):
        _update_batch_checksum(mbp_hash, batch)
        receives = batch.column(
            batch.schema.get_field_index("ts_recv")
        ).cast(pa.int64()).to_numpy(zero_copy_only=False)
        ordinals = batch.column(
            batch.schema.get_field_index("source_row_ordinal")
        ).to_numpy(zero_copy_only=False)
        publishers = batch.column(
            batch.schema.get_field_index("publisher_id")
        ).to_numpy(zero_copy_only=False)
        instruments = batch.column(
            batch.schema.get_field_index("instrument_id")
        ).to_numpy(zero_copy_only=False)
        flags_values = batch.column(
            batch.schema.get_field_index("flags")
        ).to_numpy(zero_copy_only=False)
        actions = batch.column(
            batch.schema.get_field_index("action")
        ).to_pylist()
        books = {
            name: batch.column(batch.schema.get_field_index(name)).to_numpy(
                zero_copy_only=False
            )
            for name in BOOK_FIELDS
        }
        _reference_validate_level_arrays(books, mbp_stats)

        for row in range(batch.num_rows):
            receive = int(receives[row])
            ordinal = int(ordinals[row])
            current_action = str(actions[row])
            current_flags = int(flags_values[row])
            mbp_stats["records"] += 1
            if last_receive is not None and receive < last_receive:
                mbp_stats["receive_timestamp_regressions"] += 1
            if last_ordinal is not None and ordinal <= last_ordinal:
                mbp_stats["source_ordinal_regressions"] += 1
            last_receive = receive
            last_ordinal = ordinal
            mbp_stats["publisher_mismatches"] += int(
                int(publishers[row]) != EXPECTED_PUBLISHER_ID
            )
            mbp_stats["instrument_mismatches"] += int(
                int(instruments[row]) != EXPECTED_INSTRUMENT_ID
            )
            if receive < DAY_START_NS or receive >= DAY_END_NS:
                mbp_stats["outside_frozen_day"] += 1
                continue
            bucket_key = int((receive - DAY_START_NS) // BUCKET_WIDTH_NS)
            segment_key = _segment_index_for_timestamp(receive)
            target = mbp_by_bucket[bucket_key]
            mbp_stats["allocated_records"] += 1
            target["mbp_update_count"] += 1
            target["mbp_snapshot_count"] += int(
                bool(current_flags & F_SNAPSHOT)
            )
            target["mbp_reset_count"] += int(current_action == "R")
            target["mbp_unknown_action_count"] += int(
                current_action not in KNOWN_ACTIONS
            )
            target["mbp_bad_ts_recv_flag_count"] += int(
                bool(current_flags & F_BAD_TS_RECV)
            )
            target["mbp_maybe_bad_book_flag_count"] += int(
                bool(current_flags & F_MAYBE_BAD_BOOK)
            )

            current = {
                "recv": receive,
                "snapshot": bool(current_flags & F_SNAPSHOT),
                "action": current_action,
                "bid_px": int(books["bid_px_00"][row]),
                "bid_sz": int(books["bid_sz_00"][row]),
                "bid_ct": int(books["bid_ct_00"][row]),
                "ask_px": int(books["ask_px_00"][row]),
                "ask_sz": int(books["ask_sz_00"][row]),
                "ask_ct": int(books["ask_ct_00"][row]),
            }
            current["two_sided"] = _reference_two_sided(current)
            if (
                bool(current["two_sided"])
                and SEGMENTS[segment_key][1] == "CONTINUOUS_MATCHING"
                and int(current["ask_px"]) < int(current["bid_px"])
            ):
                mbp_stats["continuous_crossed_book_rows"] += 1
            previous = previous_by_segment.get(segment_key)
            can_measure = (
                previous is not None
                and not bool(previous["snapshot"])
                and str(previous["action"]) != "R"
                and bool(previous["two_sided"])
                and not bool(current["snapshot"])
                and current_action != "R"
                and bool(current["two_sided"])
            )
            if can_measure:
                bid_component = (
                    int(current["bid_sz"])
                    if int(current["bid_px"]) >= int(previous["bid_px"])
                    else 0
                ) - (
                    int(previous["bid_sz"])
                    if int(current["bid_px"]) <= int(previous["bid_px"])
                    else 0
                )
                ask_component = -(
                    int(current["ask_sz"])
                    if int(current["ask_px"]) <= int(previous["ask_px"])
                    else 0
                ) + (
                    int(previous["ask_sz"])
                    if int(current["ask_px"]) >= int(previous["ask_px"])
                    else 0
                )
                target["quote_ofi_transition_count"] += 1
                target["quote_ofi_raw"] += bid_component + ask_component
            else:
                target["quote_ofi_skipped_count"] += 1
            previous_by_segment[segment_key] = current

            is_bucket_tail = (
                row + 1 == batch.num_rows
                or int((int(receives[row + 1]) - DAY_START_NS) // BUCKET_WIDTH_NS)
                != bucket_key
            )
            if is_bucket_tail:
                latest_states[bucket_key] = ReferenceBookState(
                    ordinal=ordinal,
                    recv=receive,
                    action=current_action,
                    flags=current_flags,
                    levels={name: int(books[name][row]) for name in BOOK_FIELDS},
                )

    mbp_stats["buckets_with_updates"] = len(mbp_by_bucket)
    columns = _reference_materialize(
        event_by_bucket, mbp_by_bucket, latest_states
    )
    audits = {
        "mbo": _complete_audit(mbo_stats),
        "mbp10": _complete_audit(mbp_stats),
        "output": _output_audit(columns),
        "alignment_attempts": 0,
        "market_values_human_or_model_inspected": False,
    }
    return columns, audits, {
        "mbo_complete_pass": mbo_hash.hexdigest(),
        "mbp10_complete_pass": mbp_hash.hexdigest(),
    }


def _primary_materialize(
    event: dict[str, list[int]],
    mbp: dict[str, list[int]],
    latest: list[PrimaryBookState | None],
) -> dict[str, list[Any]]:
    columns: dict[str, list[Any]] = {
        name: [] for name in FEATURE_COLUMNS
    }
    carried: PrimaryBookState | None = None
    previous_segment: str | None = None
    for bucket in range(BUCKET_COUNT):
        start = DAY_START_NS + bucket * BUCKET_WIDTH_NS
        end = start + BUCKET_WIDTH_NS
        segment_id, state = _segment_for_bucket(bucket)
        if segment_id != previous_segment:
            carried = None
            previous_segment = segment_id
        if latest[bucket] is not None:
            carried = latest[bucket]

        columns["bucket_index"].append(bucket)
        columns["bucket_start_ns"].append(start)
        columns["bucket_end_ns"].append(end)
        columns["market_segment"].append(segment_id)
        columns["market_state"].append(state)
        for name in (*MBO_COUNT_COLUMNS, *MBO_SIDE_FLOW_COLUMNS):
            columns[name].append(event[name][bucket])

        add_bid = event["add_qty_bid"][bucket]
        add_ask = event["add_qty_ask"][bucket]
        cancel_bid = event["cancel_qty_bid"][bucket]
        cancel_ask = event["cancel_qty_ask"][bucket]
        trade_buy = event["trade_qty_buy"][bucket]
        trade_sell = event["trade_qty_sell"][bucket]
        columns["add_imbalance_ppb"].append(
            _primary_ratio(add_bid - add_ask, add_bid + add_ask)
        )
        columns["cancel_pressure_imbalance_ppb"].append(
            _primary_ratio(
                cancel_ask - cancel_bid, cancel_ask + cancel_bid
            )
        )
        columns["displayed_pressure_ppb"].append(
            _primary_ratio(
                (add_bid + cancel_ask) - (add_ask + cancel_bid),
                add_bid + cancel_ask + add_ask + cancel_bid,
            )
        )
        columns["trade_imbalance_ppb"].append(
            _primary_ratio(trade_buy - trade_sell, trade_buy + trade_sell)
        )
        for name in MBP_STATE_COLUMNS[:9]:
            columns[name].append(mbp[name][bucket])
        features = _primary_book_features(carried, end)
        for name in (*MBP_STATE_COLUMNS[9:], *MBP_PRICE_COLUMNS, *MBP_DEPTH_COLUMNS):
            columns[name].append(features[name])
    return columns


def _reference_materialize(
    event_by_bucket: dict[int, Counter[str]],
    mbp_by_bucket: dict[int, Counter[str]],
    latest: dict[int, ReferenceBookState],
) -> dict[str, list[Any]]:
    result: dict[str, list[Any]] = {name: [] for name in FEATURE_COLUMNS}
    state_cache: ReferenceBookState | None = None
    segment_cache: str | None = None
    for bucket_number in range(0, BUCKET_COUNT):
        bucket_start = DAY_START_NS + BUCKET_WIDTH_NS * bucket_number
        bucket_end = DAY_START_NS + BUCKET_WIDTH_NS * (bucket_number + 1)
        segment_name, market_state = _segment_for_bucket(bucket_number)
        if segment_name != segment_cache:
            state_cache = None
            segment_cache = segment_name
        if bucket_number in latest:
            state_cache = latest[bucket_number]

        result["bucket_index"].append(bucket_number)
        result["bucket_start_ns"].append(bucket_start)
        result["bucket_end_ns"].append(bucket_end)
        result["market_segment"].append(segment_name)
        result["market_state"].append(market_state)
        event = event_by_bucket.get(bucket_number, Counter())
        for name in (*MBO_COUNT_COLUMNS, *MBO_SIDE_FLOW_COLUMNS):
            result[name].append(int(event[name]))

        bid_add = int(event["add_qty_bid"])
        ask_add = int(event["add_qty_ask"])
        bid_cancel = int(event["cancel_qty_bid"])
        ask_cancel = int(event["cancel_qty_ask"])
        buy_trade = int(event["trade_qty_buy"])
        sell_trade = int(event["trade_qty_sell"])
        result["add_imbalance_ppb"].append(
            _reference_ratio(bid_add - ask_add, bid_add + ask_add)
        )
        result["cancel_pressure_imbalance_ppb"].append(
            _reference_ratio(
                ask_cancel - bid_cancel, ask_cancel + bid_cancel
            )
        )
        gross_pressure = bid_add + ask_cancel + ask_add + bid_cancel
        net_pressure = bid_add + ask_cancel - ask_add - bid_cancel
        result["displayed_pressure_ppb"].append(
            _reference_ratio(net_pressure, gross_pressure)
        )
        result["trade_imbalance_ppb"].append(
            _reference_ratio(
                buy_trade - sell_trade, buy_trade + sell_trade
            )
        )
        mbp = mbp_by_bucket.get(bucket_number, Counter())
        for name in MBP_STATE_COLUMNS[:9]:
            result[name].append(int(mbp[name]))
        book_features = _reference_book_features(state_cache, bucket_end)
        for name in (*MBP_STATE_COLUMNS[9:], *MBP_PRICE_COLUMNS, *MBP_DEPTH_COLUMNS):
            result[name].append(book_features[name])
    return result


def _primary_book_features(
    state: PrimaryBookState | None, bucket_end: int
) -> dict[str, Any]:
    names = (*MBP_STATE_COLUMNS[9:], *MBP_PRICE_COLUMNS, *MBP_DEPTH_COLUMNS)
    if state is None:
        empty = {name: None for name in names}
        empty.update(
            {
                "state_available": False,
                "book_two_sided": False,
                "book_locked": False,
                "book_crossed": False,
            }
        )
        return empty

    levels = state.levels
    bid_px, bid_sz, bid_ct = levels[0], levels[1], levels[2]
    ask_px, ask_sz, ask_ct = levels[3], levels[4], levels[5]
    two_sided = _primary_two_sided(
        bid_px, bid_sz, bid_ct, ask_px, ask_sz, ask_ct
    )
    output: dict[str, Any] = {
        "state_available": True,
        "book_two_sided": two_sided,
        "state_source_row_ordinal": state.ordinal,
        "state_ts_recv_ns": state.recv,
        "book_age_ns": bucket_end - state.recv,
        "book_locked": bool(two_sided and ask_px == bid_px),
        "book_crossed": bool(two_sided and ask_px < bid_px),
        "best_bid_px_fixed_1e9": bid_px if two_sided else None,
        "best_ask_px_fixed_1e9": ask_px if two_sided else None,
        "spread_fixed_1e9": ask_px - bid_px if two_sided else None,
        "midpoint_fixed_1e9": (
            _primary_divide_round(bid_px + ask_px, 2)
            if two_sided
            else None
        ),
        "microprice_fixed_1e9": (
            _primary_divide_round(
                ask_px * bid_sz + bid_px * ask_sz,
                bid_sz + ask_sz,
            )
            if two_sided and bid_sz + ask_sz > 0
            else None
        ),
    }
    bid_depth = []
    ask_depth = []
    bid_counts = []
    ask_counts = []
    for depth in (1, 5, 10):
        bid_total = sum(levels[level * 6 + 1] for level in range(depth))
        ask_total = sum(levels[level * 6 + 4] for level in range(depth))
        bid_count = sum(levels[level * 6 + 2] for level in range(depth))
        ask_count = sum(levels[level * 6 + 5] for level in range(depth))
        bid_depth.append(bid_total)
        ask_depth.append(ask_total)
        bid_counts.append(bid_count)
        ask_counts.append(ask_count)
        suffix = f"l{depth}"
        output[f"bid_depth_{suffix}"] = bid_total
        output[f"ask_depth_{suffix}"] = ask_total
        output[f"bid_order_count_{suffix}"] = bid_count
        output[f"ask_order_count_{suffix}"] = ask_count
        output[f"depth_imbalance_{suffix}_ppb"] = _primary_ratio(
            bid_total - ask_total, bid_total + ask_total
        )
        output[f"order_count_imbalance_{suffix}_ppb"] = _primary_ratio(
            bid_count - ask_count, bid_count + ask_count
        )
    output["depth_concentration_l1_ppb"] = _primary_ratio(
        bid_depth[0] + ask_depth[0], bid_depth[2] + ask_depth[2]
    )
    return output


def _reference_book_features(
    state: ReferenceBookState | None, bucket_end: int
) -> dict[str, Any]:
    expected = (*MBP_STATE_COLUMNS[9:], *MBP_PRICE_COLUMNS, *MBP_DEPTH_COLUMNS)
    if state is None:
        missing: dict[str, Any] = {key: None for key in expected}
        missing["state_available"] = False
        missing["book_two_sided"] = False
        missing["book_locked"] = False
        missing["book_crossed"] = False
        return missing

    book = state.levels
    bid_price = book["bid_px_00"]
    ask_price = book["ask_px_00"]
    bid_size = book["bid_sz_00"]
    ask_size = book["ask_sz_00"]
    two_sided = _reference_two_sided(
        {
            "bid_px": bid_price,
            "bid_sz": bid_size,
            "bid_ct": book["bid_ct_00"],
            "ask_px": ask_price,
            "ask_sz": ask_size,
            "ask_ct": book["ask_ct_00"],
        }
    )
    values: dict[str, Any] = {
        "state_available": True,
        "book_two_sided": two_sided,
        "state_source_row_ordinal": state.ordinal,
        "state_ts_recv_ns": state.recv,
        "book_age_ns": bucket_end - state.recv,
        "book_locked": two_sided and bid_price == ask_price,
        "book_crossed": two_sided and bid_price > ask_price,
    }
    if two_sided:
        values["best_bid_px_fixed_1e9"] = bid_price
        values["best_ask_px_fixed_1e9"] = ask_price
        values["spread_fixed_1e9"] = ask_price - bid_price
        values["midpoint_fixed_1e9"] = _reference_divide_round(
            bid_price + ask_price, 2
        )
        values["microprice_fixed_1e9"] = _reference_divide_round(
            ask_price * bid_size + bid_price * ask_size,
            bid_size + ask_size,
        )
    else:
        for name in MBP_PRICE_COLUMNS:
            values[name] = None

    depth_pairs: dict[int, tuple[int, int]] = {}
    count_pairs: dict[int, tuple[int, int]] = {}
    for depth_limit in (1, 5, 10):
        selected = range(depth_limit)
        bid_total = sum(book[f"bid_sz_{level:02d}"] for level in selected)
        ask_total = sum(
            book[f"ask_sz_{level:02d}"] for level in range(depth_limit)
        )
        bid_orders = sum(
            book[f"bid_ct_{level:02d}"] for level in range(depth_limit)
        )
        ask_orders = sum(
            book[f"ask_ct_{level:02d}"] for level in range(depth_limit)
        )
        depth_pairs[depth_limit] = (bid_total, ask_total)
        count_pairs[depth_limit] = (bid_orders, ask_orders)
        suffix = f"l{depth_limit}"
        values[f"bid_depth_{suffix}"] = bid_total
        values[f"ask_depth_{suffix}"] = ask_total
        values[f"bid_order_count_{suffix}"] = bid_orders
        values[f"ask_order_count_{suffix}"] = ask_orders
        values[f"depth_imbalance_{suffix}_ppb"] = _reference_ratio(
            bid_total - ask_total, bid_total + ask_total
        )
        values[f"order_count_imbalance_{suffix}_ppb"] = _reference_ratio(
            bid_orders - ask_orders, bid_orders + ask_orders
        )
    l1_bid, l1_ask = depth_pairs[1]
    l10_bid, l10_ask = depth_pairs[10]
    values["depth_concentration_l1_ppb"] = _reference_ratio(
        l1_bid + l1_ask, l10_bid + l10_ask
    )
    return values


def _primary_validate_level_arrays(
    arrays: dict[str, np.ndarray[Any, Any]], audit: Counter[str]
) -> None:
    for level in range(10):
        for side in ("bid", "ask"):
            px = arrays[f"{side}_px_{level:02d}"]
            size = arrays[f"{side}_sz_{level:02d}"]
            count = arrays[f"{side}_ct_{level:02d}"]
            empty = px == UNDEFINED_PRICE
            audit["empty_level_canonical_violations"] += int(
                np.count_nonzero(empty & ((size != 0) | (count != 0)))
            )
            audit["negative_size_or_count_values"] += int(
                np.count_nonzero(size < 0) + np.count_nonzero(count < 0)
            )


def _reference_validate_level_arrays(
    arrays: dict[str, np.ndarray[Any, Any]], audit: Counter[str]
) -> None:
    for level_number in range(0, 10):
        for side_name in ("ask", "bid"):
            prices = arrays[f"{side_name}_px_{level_number:02d}"]
            quantities = arrays[f"{side_name}_sz_{level_number:02d}"]
            orders = arrays[f"{side_name}_ct_{level_number:02d}"]
            undefined_positions = np.equal(prices, UNDEFINED_PRICE)
            malformed = np.logical_and(
                undefined_positions,
                np.logical_or(
                    np.not_equal(quantities, 0), np.not_equal(orders, 0)
                ),
            )
            audit["empty_level_canonical_violations"] += int(malformed.sum())
            audit["negative_size_or_count_values"] += int(
                np.less(quantities, 0).sum() + np.less(orders, 0).sum()
            )


def _primary_ratio(numerator: int, denominator: int) -> int | None:
    if denominator == 0:
        return None
    sign = -1 if numerator < 0 else 1
    absolute = abs(numerator) * RATIO_SCALE
    return sign * ((absolute * 2 + denominator) // (2 * denominator))


def _reference_ratio(numerator: int, denominator: int) -> int | None:
    if denominator <= 0:
        return None
    scaled = abs(numerator) * RATIO_SCALE
    quotient, remainder = divmod(scaled, denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return -quotient if numerator < 0 else quotient


def _primary_divide_round(numerator: int, denominator: int) -> int:
    sign = -1 if numerator < 0 else 1
    absolute = abs(numerator)
    return sign * ((absolute * 2 + denominator) // (2 * denominator))


def _reference_divide_round(numerator: int, denominator: int) -> int:
    quotient, remainder = divmod(abs(numerator), denominator)
    if remainder * 2 >= denominator:
        quotient += 1
    return -quotient if numerator < 0 else quotient


def _primary_two_sided(
    bid_px: int,
    bid_sz: int,
    bid_ct: int,
    ask_px: int,
    ask_sz: int,
    ask_ct: int,
) -> bool:
    return (
        bid_px != UNDEFINED_PRICE
        and ask_px != UNDEFINED_PRICE
        and bid_sz > 0
        and ask_sz > 0
        and bid_ct > 0
        and ask_ct > 0
    )


def _reference_two_sided(values: dict[str, int | str | bool]) -> bool:
    return all(
        (
            int(values["bid_px"]) != UNDEFINED_PRICE,
            int(values["ask_px"]) != UNDEFINED_PRICE,
            int(values["bid_sz"]) > 0,
            int(values["ask_sz"]) > 0,
            int(values["bid_ct"]) > 0,
            int(values["ask_ct"]) > 0,
        )
    )


def _segment_index_for_timestamp(timestamp: int) -> int:
    for index, (_segment, _state, start, end) in enumerate(SEGMENTS):
        if start <= timestamp < end:
            return index
    raise ValueError(f"Timestamp outside frozen market-state segments: {timestamp}")


def _segment_for_bucket(bucket: int) -> tuple[str, str]:
    timestamp = DAY_START_NS + bucket * BUCKET_WIDTH_NS
    index = _segment_index_for_timestamp(timestamp)
    return SEGMENTS[index][0], SEGMENTS[index][1]


def _update_batch_checksum(digest: Any, batch: pa.RecordBatch) -> None:
    payload = batch.serialize().to_pybytes()
    digest.update(UINT32.pack(batch.num_rows))
    digest.update(UINT32.pack(len(payload)))
    digest.update(payload)


def _complete_audit(counter: Counter[str]) -> dict[str, int]:
    names = (
        "records",
        "allocated_records",
        "outside_frozen_day",
        "receive_timestamp_regressions",
        "source_ordinal_regressions",
        "publisher_mismatches",
        "instrument_mismatches",
        "buckets_with_records",
        "buckets_with_updates",
        "empty_level_canonical_violations",
        "negative_size_or_count_values",
        "continuous_crossed_book_rows",
    )
    return {name: int(counter[name]) for name in names}


def _output_audit(columns: dict[str, list[Any]]) -> dict[str, int]:
    return {
        "bucket_rows": len(columns["bucket_index"]),
        "feature_columns": len(columns),
        "buckets_with_mbo_records": sum(
            int(value > 0) for value in columns["mbo_total_records"]
        ),
        "buckets_with_mbp_updates": sum(
            int(value > 0) for value in columns["mbp_update_count"]
        ),
        "state_available_buckets": sum(columns["state_available"]),
        "two_sided_buckets": sum(columns["book_two_sided"]),
        "locked_buckets": sum(columns["book_locked"]),
        "crossed_buckets": sum(columns["book_crossed"]),
        "mbo_snapshot_records": sum(columns["mbo_snapshot_records"]),
        "mbo_reset_records": sum(columns["mbo_reset_count"]),
        "mbp_snapshot_records": sum(columns["mbp_snapshot_count"]),
        "mbp_reset_records": sum(columns["mbp_reset_count"]),
        "quote_ofi_transitions": sum(columns["quote_ofi_transition_count"]),
        "quote_ofi_skipped": sum(columns["quote_ofi_skipped_count"]),
        "mbo_unknown_actions": sum(columns["mbo_unknown_action_count"]),
        "mbp_unknown_actions": sum(columns["mbp_unknown_action_count"]),
        "bad_ts_recv_flag_rows": (
            sum(columns["mbo_bad_ts_recv_flag_count"])
            + sum(columns["mbp_bad_ts_recv_flag_count"])
        ),
        "maybe_bad_book_flag_rows": (
            sum(columns["mbo_maybe_bad_book_flag_count"])
            + sum(columns["mbp_maybe_bad_book_flag_count"])
        ),
    }


def _integrity_checks(
    columns: dict[str, list[Any]],
    audits: dict[str, Any],
    context: dict[str, Any],
) -> dict[str, bool]:
    mbo = audits["mbo"]
    mbp = audits["mbp10"]
    output = audits["output"]
    grid = columns["bucket_index"]
    starts = columns["bucket_start_ns"]
    ends = columns["bucket_end_ns"]
    no_cross_segment_carry = True
    for bucket in range(BUCKET_COUNT):
        segment_index = _segment_index_for_timestamp(starts[bucket])
        expected_segment = SEGMENTS[segment_index][0]
        if columns["market_segment"][bucket] != expected_segment:
            no_cross_segment_carry = False
        state_recv = columns["state_ts_recv_ns"][bucket]
        if state_recv is not None and not (
            SEGMENTS[segment_index][2] <= state_recv < ends[bucket]
        ):
            no_cross_segment_carry = False

    return {
        "predecessor_and_source_seals_valid": bool(
            context["predecessor_and_source_seals_valid"]
        ),
        "required_input_columns_present": bool(
            context["required_input_columns_present"]
        ),
        "source_record_counts_exact": (
            mbo["records"] == EXPECTED_MBO_RECORDS
            and mbp["records"] == EXPECTED_MBP_RECORDS
        ),
        "publisher_and_instrument_exact": (
            mbo["publisher_mismatches"] == 0
            and mbo["instrument_mismatches"] == 0
            and mbp["publisher_mismatches"] == 0
            and mbp["instrument_mismatches"] == 0
        ),
        "all_receive_timestamps_in_frozen_day": (
            mbo["outside_frozen_day"] == 0
            and mbp["outside_frozen_day"] == 0
        ),
        "receive_timestamp_and_source_ordinal_order_nondecreasing": (
            mbo["receive_timestamp_regressions"] == 0
            and mbo["source_ordinal_regressions"] == 0
            and mbp["receive_timestamp_regressions"] == 0
            and mbp["source_ordinal_regressions"] == 0
        ),
        "every_source_row_allocated_exactly_once": (
            mbo["allocated_records"] == EXPECTED_MBO_RECORDS
            and mbp["allocated_records"] == EXPECTED_MBP_RECORDS
            and sum(columns["mbo_total_records"]) == EXPECTED_MBO_RECORDS
            and sum(columns["mbp_update_count"]) == EXPECTED_MBP_RECORDS
        ),
        "output_bucket_rows_exact": output["bucket_rows"] == BUCKET_COUNT,
        "output_bucket_grid_complete_unique_and_ordered": (
            grid == list(range(BUCKET_COUNT))
            and starts
            == [DAY_START_NS + i * BUCKET_WIDTH_NS for i in range(BUCKET_COUNT)]
            and ends
            == [
                DAY_START_NS + (i + 1) * BUCKET_WIDTH_NS
                for i in range(BUCKET_COUNT)
            ]
        ),
        "no_cross_segment_state_carry": no_cross_segment_carry,
        "empty_levels_canonical": (
            mbp["empty_level_canonical_violations"] == 0
        ),
        "book_sizes_and_counts_nonnegative": (
            mbp["negative_size_or_count_values"] == 0
        ),
        "continuous_crossed_book_rows_zero": (
            mbp["continuous_crossed_book_rows"] == 0
        ),
        "bad_ts_recv_flag_rows_zero": output["bad_ts_recv_flag_rows"] == 0,
        "maybe_bad_book_flag_rows_zero": (
            output["maybe_bad_book_flag_rows"] == 0
        ),
        "unknown_action_rows_zero": (
            output["mbo_unknown_actions"] == 0
            and output["mbp_unknown_actions"] == 0
        ),
        "no_mbo_to_mbp_alignment": audits["alignment_attempts"] == 0,
        "no_outcome_signal_execution_or_pnl_work": True,
    }


def _feature_hashes(columns: dict[str, list[Any]]) -> dict[str, Any]:
    null_counts: dict[str, int] = {}
    column_hashes: dict[str, str] = {}
    for field in FEATURE_SCHEMA:
        digest = hashlib.sha256()
        digest.update(field.name.encode("utf-8"))
        digest.update(str(field.type).encode("ascii"))
        nulls = 0
        for value in columns[field.name]:
            if value is None:
                nulls += 1
            _update_value_hash(digest, value, field.type)
        null_counts[field.name] = nulls
        column_hashes[field.name] = digest.hexdigest()

    complete = hashlib.sha256()
    complete.update(_feature_schema_hash().encode("ascii"))
    for row in range(BUCKET_COUNT):
        for field in FEATURE_SCHEMA:
            _update_value_hash(complete, columns[field.name][row], field.type)
    return {
        "null_counts": null_counts,
        "column_checksums": column_hashes,
        "complete_row_checksum": complete.hexdigest(),
    }


def _update_value_hash(
    digest: Any, value: Any, data_type: pa.DataType
) -> None:
    if value is None:
        digest.update(b"\x00")
        return
    digest.update(b"\x01")
    if pa.types.is_string(data_type):
        encoded = str(value).encode("utf-8")
        digest.update(UINT32.pack(len(encoded)))
        digest.update(encoded)
    elif pa.types.is_boolean(data_type):
        digest.update(b"\x01" if bool(value) else b"\x00")
    else:
        digest.update(INT64.pack(int(value)))


def _write_feature_parquet(
    path: Path, columns: dict[str, list[Any]]
) -> None:
    table = pa.Table.from_pydict(columns, schema=FEATURE_SCHEMA)
    temporary = path.with_suffix(path.suffix + ".tmp")
    pq.write_table(
        table,
        temporary,
        compression="zstd",
        use_dictionary=False,
        write_statistics=True,
        data_page_version="1.0",
        version="2.6",
        row_group_size=BUCKET_COUNT,
    )
    os.replace(temporary, path)


def _validate_column_lengths(columns: dict[str, list[Any]]) -> None:
    if tuple(columns) != FEATURE_COLUMNS:
        raise ValueError("Feature output column order differs from frozen registry")
    invalid = {
        name: len(values)
        for name, values in columns.items()
        if len(values) != BUCKET_COUNT
    }
    if invalid:
        raise ValueError(f"Invalid feature column lengths: {invalid}")


def _seal(output: Path, context: dict[str, Any]) -> None:
    primary_path = output / "primary_summary.json"
    reference_path = output / "reference_summary.json"
    if not primary_path.exists() or not reference_path.exists():
        raise FileNotFoundError("Both Step 4A runs are required before sealing")
    primary = _read_json(primary_path)
    reference = _read_json(reference_path)
    current_tool_hash = _sha256(Path(__file__))
    for run in (primary, reference):
        if run["tool_sha256"] != current_tool_hash:
            raise ValueError("Tool changed between calculation and seal")
        _verify_run_payload(run)

    compared_sections = (
        "source_input_checksums",
        "feature_rows",
        "feature_columns",
        "feature_column_count",
        "feature_schema_hash",
        "feature_hashes",
        "audits",
        "integrity_checks",
        "formal_integrity_pass",
    )
    matching_sections = {
        name: primary[name] == reference[name] for name in compared_sections
    }
    parquet_identical = (
        primary["feature_parquet"]["sha256"]
        == reference["feature_parquet"]["sha256"]
    )
    reproduction_pass = all(matching_sections.values()) and parquet_identical
    primary_integrity = bool(primary["formal_integrity_pass"])
    reference_integrity = bool(reference["formal_integrity_pass"])
    predecessor_source_pass = bool(
        context["predecessor_and_source_seals_valid"]
        and context["required_input_columns_present"]
    )
    if not predecessor_source_pass:
        status = "FAIL_PREDECESSOR_OR_SOURCE_INTEGRITY"
    elif not primary_integrity or not reference_integrity:
        status = "FAIL_FEATURE_INTEGRITY"
    elif not reproduction_pass:
        status = "FAIL_REPRODUCTION"
    else:
        status = "PASS"

    formal_gates = {
        "predecessor_and_source_seals_valid": predecessor_source_pass,
        "primary_integrity_pass": primary_integrity,
        "reference_integrity_pass": reference_integrity,
        "source_input_checksums_identical": matching_sections[
            "source_input_checksums"
        ],
        "feature_counts_and_schema_identical": all(
            matching_sections[name]
            for name in (
                "feature_rows",
                "feature_columns",
                "feature_column_count",
                "feature_schema_hash",
            )
        ),
        "null_counts_identical": (
            primary["feature_hashes"]["null_counts"]
            == reference["feature_hashes"]["null_counts"]
        ),
        "column_checksums_identical": (
            primary["feature_hashes"]["column_checksums"]
            == reference["feature_hashes"]["column_checksums"]
        ),
        "complete_row_checksum_identical": (
            primary["feature_hashes"]["complete_row_checksum"]
            == reference["feature_hashes"]["complete_row_checksum"]
        ),
        "technical_diagnostics_identical": matching_sections["audits"],
        "output_parquet_sha256_identical": parquet_identical,
        "no_mbo_mbp_alignment": (
            primary["mbo_mbp_alignment_attempts"] == 0
            and reference["mbo_mbp_alignment_attempts"] == 0
        ),
        "no_data_outcomes_signals_execution_or_pnl": all(
            not run[key]
            for run in (primary, reference)
            for key in (
                "additional_data_acquired",
                "another_date_inspected",
                "market_values_human_or_model_inspected",
                "outcomes_accessed",
                "signals_calculated",
                "execution_optimized",
                "pnl_calculated",
            )
        ),
    }
    verdict = {
        "version": "GC_MICROSTRUCTURE_STEP_4A_VERDICT_V0_1",
        "status": status,
        "formal_pass": status == "PASS",
        "classification": "ENGINEERING_ONLY",
        "research_or_validation_credit": "NONE",
        "predecessor_step_3f_status": "FAIL_BOOK_MISMATCH",
        "predecessor_verdicts_preserved": True,
        "formal_gates": formal_gates,
        "passed_formal_gates": sum(formal_gates.values()),
        "total_formal_gates": len(formal_gates),
        "reproduction": {
            "pass": reproduction_pass,
            "matching_sections": matching_sections,
            "parquet_sha256_identical": parquet_identical,
        },
        "technical_counts": primary["audits"],
        "feature_rows": primary["feature_rows"],
        "feature_columns": primary["feature_column_count"],
        "complete_row_checksum": primary["feature_hashes"][
            "complete_row_checksum"
        ],
        "feature_parquet_sha256": primary["feature_parquet"]["sha256"],
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_reported": False,
        "market_values_human_or_model_inspected": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
        "completion_policy": "Preserve this result and stop Step 4A without correction or research.",
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    verdict_path = output / "verdict.json"
    _write_json_atomic(verdict_path, verdict)
    report = _render_report(verdict)
    _write_text_atomic(REPORT_PATH, report)

    artifact_paths_list = [
        output / "primary_features.parquet",
        output / "primary_summary.json",
        output / "reference_features.parquet",
        output / "reference_summary.json",
        verdict_path,
        REPORT_PATH,
    ]
    rejected_preflight = output / "preflight_attempt_01_rejected.json"
    if rejected_preflight.exists():
        artifact_paths_list.insert(0, rejected_preflight)
    artifact_paths = tuple(artifact_paths_list)
    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_4A_MANIFEST_V0_1",
        "status": status,
        "sealed_at_utc": datetime.now(timezone.utc).isoformat().replace(
            "+00:00", "Z"
        ),
        "classification": "ENGINEERING_ONLY",
        "research_or_validation_credit": "NONE",
        "protocol": _file_record(PROTOCOL_PATH),
        "freeze_receipt": _file_record(FREEZE_PATH),
        "step3f_manifest": _file_record(STEP3F_MANIFEST_PATH),
        "mbo_source": _file_record(MBO_PATH),
        "mbp10_source": _file_record(MBP_PATH),
        "feature_tool": _file_record(Path(__file__)),
        "artifacts": [_file_record(path) for path in artifact_paths],
        "verdict_hash": verdict["verdict_hash"],
        "predecessor_verdicts_preserved": True,
        "mbo_mbp_alignment_attempts": 0,
        "additional_data_acquired": False,
        "another_date_inspected": False,
        "market_values_human_or_model_inspected": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(output / "manifest.json", manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A_SEALED",
                "status": status,
                "formal_pass": status == "PASS",
                "feature_rows": primary["feature_rows"],
                "feature_columns": primary["feature_column_count"],
                "reproduction_pass": reproduction_pass,
                "complete_row_checksum": primary["feature_hashes"][
                    "complete_row_checksum"
                ],
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _render_report(verdict: dict[str, Any]) -> str:
    output = verdict["technical_counts"]["output"]
    mbp = verdict["technical_counts"]["mbp10"]
    return "\n".join(
        [
            "# GC Microstructure Step 4A — Deterministic Feature Engineering",
            "",
            "## Scope",
            "",
            "- Permanently engineering-only date: `2024-01-09`.",
            "- Vendor MBP-10 is authoritative for top-ten book state.",
            "- MBO contributes receive-time one-second event-flow aggregates only.",
            "- No MBO-to-MBP row alignment or comparator correction was performed.",
            "",
            "## Formal verdict",
            "",
            f"`{verdict['status']}`",
            "",
            f"- MBO source rows: {verdict['technical_counts']['mbo']['records']:,}.",
            f"- MBP-10 source rows: {mbp['records']:,}.",
            f"- Output buckets: {verdict['feature_rows']:,}.",
            f"- Feature columns: {verdict['feature_columns']:,}.",
            f"- Buckets with MBO records: {output['buckets_with_mbo_records']:,}.",
            f"- Buckets with MBP-10 updates: {output['buckets_with_mbp_updates']:,}.",
            f"- State-available buckets: {output['state_available_buckets']:,}.",
            f"- Two-sided buckets: {output['two_sided_buckets']:,}.",
            f"- Continuous crossed-book rows: {mbp['continuous_crossed_book_rows']:,}.",
            f"- Empty-level violations: {mbp['empty_level_canonical_violations']:,}.",
            f"- Negative size/count values: {mbp['negative_size_or_count_values']:,}.",
            "",
            "## Independent reproduction",
            "",
            f"- Reproduction pass: `{str(verdict['reproduction']['pass']).lower()}`.",
            f"- Complete-row checksum: `{verdict['complete_row_checksum']}`.",
            f"- Feature payload SHA-256: `{verdict['feature_parquet_sha256']}`.",
            "",
            "## Restrictions honored",
            "",
            "No additional data, other date, future outcome, signal, candidate, execution optimization, trade, PnL, R multiple, or account return was accessed or calculated.",
            "",
            "Feature payload values were sealed without human or model inspection and receive zero research or validation credit.",
            "",
        ]
    )


def _verify_seal(output: Path) -> None:
    context = _verified_context()
    _assert_protocol_matches_code(context["protocol"])
    manifest_path = output / "manifest.json"
    verdict_path = output / "verdict.json"
    manifest = _read_json(manifest_path)
    verdict = _read_json(verdict_path)
    if manifest["manifest_hash"] != _canonical_hash(
        {key: value for key, value in manifest.items() if key != "manifest_hash"}
    ):
        raise ValueError("Step 4A manifest canonical hash mismatch")
    if verdict["verdict_hash"] != _canonical_hash(
        {key: value for key, value in verdict.items() if key != "verdict_hash"}
    ):
        raise ValueError("Step 4A verdict canonical hash mismatch")
    for record in manifest["artifacts"]:
        path = Path(record["path"])
        if not path.exists():
            raise FileNotFoundError(path)
        if path.stat().st_size != record["bytes"]:
            raise ValueError(f"Artifact size mismatch: {path}")
        if _sha256(path) != record["sha256"]:
            raise ValueError(f"Artifact hash mismatch: {path}")
    for key, expected in (
        ("protocol", EXPECTED_PROTOCOL_SHA256),
        ("freeze_receipt", EXPECTED_FREEZE_SHA256),
        ("mbo_source", EXPECTED_MBO_SHA256),
        ("mbp10_source", EXPECTED_MBP_SHA256),
    ):
        if manifest[key]["sha256"] != expected:
            raise ValueError(f"Manifest {key} hash declaration mismatch")
        if _sha256(Path(manifest[key]["path"])) != expected:
            raise ValueError(f"Sealed {key} changed")
    if manifest["feature_tool"]["sha256"] != _sha256(Path(__file__)):
        raise ValueError("Step 4A feature tool changed after sealing")
    if manifest["status"] != verdict["status"]:
        raise ValueError("Manifest and verdict status differ")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_4A_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]),
                "predecessor_verdicts_preserved": manifest[
                    "predecessor_verdicts_preserved"
                ],
                "mbo_mbp_alignment_attempts": manifest[
                    "mbo_mbp_alignment_attempts"
                ],
                "additional_data_acquired": manifest[
                    "additional_data_acquired"
                ],
                "another_date_inspected": manifest["another_date_inspected"],
                "outcomes_accessed": manifest["outcomes_accessed"],
                "signals_calculated": manifest["signals_calculated"],
                "pnl_calculated": manifest["pnl_calculated"],
                "research_or_validation_credit": manifest[
                    "research_or_validation_credit"
                ],
            },
            sort_keys=True,
        )
    )


def _verify_run_payload(run: dict[str, Any]) -> None:
    if run["protocol_sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Run protocol hash mismatch")
    if run["freeze_sha256"] != EXPECTED_FREEZE_SHA256:
        raise ValueError("Run freeze hash mismatch")
    if run["mbo_source_sha256"] != EXPECTED_MBO_SHA256:
        raise ValueError("Run MBO source hash mismatch")
    if run["mbp10_source_sha256"] != EXPECTED_MBP_SHA256:
        raise ValueError("Run MBP-10 source hash mismatch")
    feature_path = Path(run["feature_parquet"]["path"])
    if feature_path.stat().st_size != run["feature_parquet"]["bytes"]:
        raise ValueError("Feature payload size mismatch")
    if _sha256(feature_path) != run["feature_parquet"]["sha256"]:
        raise ValueError("Feature payload hash mismatch")
    metadata = pq.ParquetFile(feature_path).metadata
    if metadata.num_rows != BUCKET_COUNT:
        raise ValueError("Feature payload row count changed")


def _verified_context() -> dict[str, Any]:
    if _sha256(PROTOCOL_PATH) != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Step 4A protocol is not the frozen byte sequence")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 4A freeze receipt changed")
    protocol = _read_json(PROTOCOL_PATH)
    freeze = _read_json(FREEZE_PATH)
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Freeze receipt does not bind the frozen protocol")

    step3f = _read_json(STEP3F_MANIFEST_PATH)
    declared_step3f_hash = step3f.get("manifest_hash")
    computed_step3f_hash = _canonical_hash(
        {key: value for key, value in step3f.items() if key != "manifest_hash"}
    )
    if (
        declared_step3f_hash != EXPECTED_STEP3F_MANIFEST_HASH
        or computed_step3f_hash != EXPECTED_STEP3F_MANIFEST_HASH
        or step3f.get("status") != "FAIL_BOOK_MISMATCH"
        or step3f.get("verdict_hash") != EXPECTED_STEP3F_VERDICT_HASH
    ):
        raise ValueError("Step 3F predecessor seal or verdict changed")
    for record in step3f["artifacts"]:
        path = Path(record["path"])
        if path.stat().st_size != record["bytes"] or _sha256(path) != record[
            "sha256"
        ]:
            raise ValueError(f"Step 3F artifact changed: {path}")
    for record_name in ("amendment", "freeze_receipt", "comparison_tool"):
        record = step3f[record_name]
        path = Path(record["path"])
        if path.stat().st_size != record["bytes"] or _sha256(path) != record[
            "sha256"
        ]:
            raise ValueError(f"Step 3F sealed dependency changed: {path}")

    mbo_hash = _sha256(MBO_PATH)
    mbp_hash = _sha256(MBP_PATH)
    if mbo_hash != EXPECTED_MBO_SHA256 or mbp_hash != EXPECTED_MBP_SHA256:
        raise ValueError("A sealed Step 4A source changed")
    mbo_parquet = pq.ParquetFile(MBO_PATH)
    mbp_parquet = pq.ParquetFile(MBP_PATH)
    required_columns_present = (
        set(MBO_COLUMNS).issubset(mbo_parquet.schema_arrow.names)
        and set(MBP_COLUMNS).issubset(mbp_parquet.schema_arrow.names)
    )
    record_counts_exact = (
        mbo_parquet.metadata.num_rows == EXPECTED_MBO_RECORDS
        and mbp_parquet.metadata.num_rows == EXPECTED_MBP_RECORDS
    )
    if not required_columns_present or not record_counts_exact:
        raise ValueError("Sealed source schema or metadata count changed")
    return {
        "protocol": protocol,
        "freeze": freeze,
        "predecessor_and_source_seals_valid": True,
        "required_input_columns_present": True,
        "source_record_counts_exact": True,
    }


def _assert_protocol_matches_code(protocol: dict[str, Any]) -> None:
    registry = protocol["feature_registry"]
    frozen_ratio_columns = tuple(
        name
        for name in registry["mbo_ratios_ppb"]
        if name != "null_rule"
    )
    frozen_columns = (
        *registry["identity_and_time"],
        *registry["mbo_counts"],
        *registry["mbo_side_flow"],
        *frozen_ratio_columns,
        *registry["mbp_counts_and_state"],
        *registry["mbp_price_features_fixed_1e9"].keys(),
        *registry["mbp_depth_features"],
    )
    if tuple(frozen_columns) != FEATURE_COLUMNS:
        raise ValueError("Code feature columns differ from frozen registry")
    temporal = protocol["temporal_contract"]
    if (
        temporal["day_start_inclusive_ns"] != DAY_START_NS
        or temporal["day_end_exclusive_ns"] != DAY_END_NS
        or temporal["bucket_width_ns"] != BUCKET_WIDTH_NS
        or temporal["bucket_count"] != BUCKET_COUNT
    ):
        raise ValueError("Code temporal grid differs from frozen protocol")
    constants = protocol["constants"]
    if (
        constants["undefined_price_fixed_1e9"] != UNDEFINED_PRICE
        or constants["ratio_scale_ppb"] != RATIO_SCALE
        or constants["flag_snapshot"] != F_SNAPSHOT
        or constants["flag_top_of_book"] != F_TOB
    ):
        raise ValueError("Code constants differ from frozen protocol")
    frozen_segments = tuple(
        (
            item["segment_id"],
            item["state"],
            item["start_inclusive_ns"],
            item["end_exclusive_ns"],
        )
        for item in temporal["market_state_segments"]
    )
    if frozen_segments != SEGMENTS:
        raise ValueError("Code market-state segments differ from protocol")
    if tuple(protocol["input_fields"]["mbo"]) != MBO_COLUMNS:
        raise ValueError("Code MBO inputs differ from frozen protocol")
    if tuple(protocol["input_fields"]["mbp10_metadata"]) != MBP_COLUMNS[:10]:
        raise ValueError("Code MBP-10 metadata differs from frozen protocol")


def _feature_schema_hash() -> str:
    payload = [
        {
            "name": field.name,
            "type": str(field.type),
            "nullable": field.nullable,
        }
        for field in FEATURE_SCHEMA
    ]
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _file_record(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json_atomic(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)


def _write_text_atomic(path: Path, value: str) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(value, encoding="utf-8")
    os.replace(temporary, path)


if __name__ == "__main__":
    main()
