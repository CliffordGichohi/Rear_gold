from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
import sys
import tempfile

import pyarrow as pa
import pyarrow.parquet as pq

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "tools"))

import materialize_gc_session_trigger_edge_m2 as m2
import run_gc_session_trigger_edge_v2 as v2
import run_gc_session_trigger_edge_v2r1 as v2r1


def _timestamp(values: list[int]) -> pa.Array:
    return pa.array(values, type=pa.timestamp("ns", tz="UTC"))


def _mbo_table(start: int, rows: int) -> pa.Table:
    receives = [start + (index // 2) * 1_000_000_000 + (index % 2) for index in range(rows)]
    actions = ["A", "C", "M", "T", "F", "N", "R"]
    sides = ["B", "A", "B", "A", "N", "N", "N"]
    return pa.table(
        {
            "source_row_ordinal": pa.array(range(100, 100 + rows), type=pa.int64()),
            "ts_recv": _timestamp(receives),
            "ts_event": _timestamp([value - 100 for value in receives]),
            "publisher_id": pa.array([1] * rows, type=pa.int64()),
            "instrument_id": pa.array([42] * rows, type=pa.int64()),
            "action": pa.array([actions[index % len(actions)] for index in range(rows)]),
            "side": pa.array([sides[index % len(sides)] for index in range(rows)]),
            "price_fixed_1e9": pa.array([2_000_000_000_000] * rows, type=pa.int64()),
            "size": pa.array([index % 9 + 1 for index in range(rows)], type=pa.int64()),
            "order_id": pa.array(range(10_000, 10_000 + rows), type=pa.int64()),
            "flags": pa.array([128] * rows, type=pa.int64()),
            "sequence": pa.array(range(1, rows + 1), type=pa.int64()),
        }
    )


def _mbp_table(start: int, rows: int) -> pa.Table:
    receives = [start - 1_000_000_000] + [
        start + (index // 2) * 1_000_000_000 + (index % 2) for index in range(rows)
    ]
    count = rows + 1
    values: dict[str, pa.Array] = {
        "source_row_ordinal": pa.array(range(1_000, 1_000 + count), type=pa.int64()),
        "ts_recv": _timestamp(receives),
        "ts_event": _timestamp([value - 100 for value in receives]),
        "publisher_id": pa.array([1] * count, type=pa.int64()),
        "instrument_id": pa.array([42] * count, type=pa.int64()),
        "sequence": pa.array(range(1, count + 1), type=pa.int64()),
        "action": pa.array(["A"] * count),
        "side": pa.array(["B"] * count),
        "depth": pa.array([0] * count, type=pa.int64()),
        "flags": pa.array([128] * count, type=pa.int64()),
    }
    for level in range(10):
        values[f"bid_px_{level:02d}"] = pa.array(
            [2_000_000_000_000 - level * 1_000_000_000 + index for index in range(count)],
            type=pa.int64(),
        )
        values[f"ask_px_{level:02d}"] = pa.array(
            [2_001_000_000_000 + level * 1_000_000_000 + index for index in range(count)],
            type=pa.int64(),
        )
        for side in ("bid", "ask"):
            values[f"{side}_sz_{level:02d}"] = pa.array(
                [10 + level + index % 3 for index in range(count)], type=pa.int64()
            )
            values[f"{side}_ct_{level:02d}"] = pa.array([1] * count, type=pa.int64())
    return pa.table(values)


def test_streaming_is_batch_invariant_and_matches_frozen_formulas(tmp_path: Path) -> None:
    start = int(datetime(2024, 1, 9, 8, 0, tzinfo=UTC).timestamp() * 1_000_000_000)
    end = start + m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION * m2.BUCKET_NS
    mbo_path, mbp_path = tmp_path / "mbo.parquet", tmp_path / "mbp.parquet"
    pq.write_table(_mbo_table(start, 37), mbo_path, row_group_size=11)
    pq.write_table(_mbp_table(start, 43), mbp_path, row_group_size=13)

    s5c = m2._load_module(m2.STEP5C_ENGINE_PATH, "gc_v2r1_test_s5c")
    base = m2._load_module(m2.BASE_ENGINE_PATH, "gc_v2r1_test_base")
    s5c.WINDOW_BUCKETS = m2.EXPECTED_FEATURE_BUCKETS_PER_SESSION
    row = {
        "row_id": "SYNTHETIC",
        "session_code": "LONDON",
        "window_start_inclusive_ns": start,
        "window_end_exclusive_ns": end,
        "utc_day_start_ns": start - start % (86_400 * m2.BUCKET_NS),
        "bucket_index_start_inclusive": 28_800,
        "expected_instrument_id": 42,
    }
    old_primary_batch, old_reference_batch = v2r1.PRIMARY_BATCH_ROWS, v2r1.REFERENCE_BATCH_ROWS
    v2r1.PRIMARY_BATCH_ROWS, v2r1.REFERENCE_BATCH_ROWS = 7, 5
    try:
        streaming: dict[str, tuple[object, ...]] = {}
        for implementation in ("primary", "reference"):
            anchor = (
                s5c._read_exact_anchor(mbp_path, base.MBP_COLUMNS, start, row["utc_day_start_ns"])
                if implementation == "primary"
                else v2r1.r2.read_anchor_reference(
                    mbp_path, base.MBP_COLUMNS, start, row["utc_day_start_ns"]
                )
            )
            events, mbo_audit, mbo_source = v2r1._stream_mbo(
                implementation=implementation,
                path=mbo_path,
                columns=base.MBO_COLUMNS,
                start=start,
                end=end,
                instrument_id=42,
                s5c=s5c,
                base=base,
            )
            counts, states, mbp_audit, mbp_source = v2r1._stream_mbp(
                implementation=implementation,
                path=mbp_path,
                columns=base.MBP_COLUMNS,
                start=start,
                end=end,
                instrument_id=42,
                anchor=anchor,
                s5c=s5c,
                base=base,
            )
            columns = s5c._materialize_window(row, events, counts, states, base, implementation)
            technical = v2r1._technical_counter(row, columns, mbo_audit, mbp_audit)
            selected_flags = {int(state.ordinal): int(state.flags) for state in states}
            selected_flags[int(anchor["source_row_ordinal"][0].as_py())] = int(
                anchor["flags"][0].as_py()
            )
            processed = (
                v2r1.r2.apply_policy_primary("SYNTHETIC", columns, selected_flags, base)
                if implementation == "primary"
                else v2r1.r2.apply_policy_reference("SYNTHETIC", columns, selected_flags, base)
            )
            streaming[implementation] = (
                columns,
                technical,
                {"mbo": mbo_source, "mbp": mbp_source},
                processed,
            )

        assert streaming["primary"][0] == streaming["reference"][0]
        assert streaming["primary"][1] == streaming["reference"][1]
        assert streaming["primary"][3] == streaming["reference"][3]
        assert streaming["primary"][2]["mbo"]["identity_checksum"] == streaming["reference"][2]["mbo"]["identity_checksum"]
        assert streaming["primary"][2]["mbp"]["identity_checksum"] == streaming["reference"][2]["mbp"]["identity_checksum"]

        mbo = s5c._read_exact_ranges(mbo_path, base.MBO_COLUMNS, [(start, end)])
        mbp = s5c._read_exact_ranges(mbp_path, base.MBP_COLUMNS, [(start, end)])
        anchor = s5c._read_exact_anchor(mbp_path, base.MBP_COLUMNS, start, row["utc_day_start_ns"])
        mbo_arrays = v2.compact_table_arrays(mbo, base.MBO_COLUMNS)
        mbp_arrays = v2.compact_table_arrays(mbp, base.MBP_COLUMNS)
        frozen_columns, frozen_technical = s5c._primary_window_features(
            row, mbo_arrays, mbp_arrays, anchor, base
        )
        frozen_flags = v2.selected_flags_by_ordinal(
            mbp_arrays, anchor, frozen_columns["state_source_row_ordinal"]
        )
        frozen_processed = v2r1.r2.apply_policy_primary(
            "SYNTHETIC", frozen_columns, frozen_flags, base
        )
        assert streaming["primary"][0] == frozen_columns
        assert streaming["primary"][1] == frozen_technical
        assert streaming["primary"][3] == frozen_processed
    finally:
        v2r1.PRIMARY_BATCH_ROWS, v2r1.REFERENCE_BATCH_ROWS = old_primary_batch, old_reference_batch


if __name__ == "__main__":
    with tempfile.TemporaryDirectory(prefix="gc_v2r1_streaming_test_") as directory:
        test_streaming_is_batch_invariant_and_matches_frozen_formulas(Path(directory))
