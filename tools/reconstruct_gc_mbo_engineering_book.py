#!/usr/bin/env python3
"""Deterministically reconstruct the sealed GC MBO engineering sample.

The utility performs technical replay only. It never emits price levels,
directional statistics, signals, outcomes, trades, or PnL. Two separate book
implementations read the sealed source independently and are compared through
stream, state, structure, and lifecycle checksums.
"""

from __future__ import annotations

import argparse
import hashlib
import heapq
import json
import struct
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

REPO_ROOT = Path(__file__).resolve().parents[1]
PROTOCOL_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3a_protocol_v01.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3a_v01"
)

F_LAST = 128
F_TOB = 64
F_SNAPSHOT = 32
F_BAD_TS_RECV = 8
F_MAYBE_BAD_BOOK = 4
UNDEF_PRICE = 9_223_372_036_854_775_807
CHECKPOINT_INTERVAL = 250_000

REQUIRED_COLUMNS = (
    "source_file_index",
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "rtype",
    "publisher_id",
    "instrument_id",
    "action",
    "side",
    "price_fixed_1e9",
    "size",
    "channel_id",
    "order_id",
    "flags",
    "ts_in_delta",
    "sequence",
)
STREAM_RECORD = struct.Struct(">hqqqHHIccqIBQBiI")
ORDER_RECORD = struct.Struct(">Qcqqq")
LEVEL_HEADER = struct.Struct(">cqqq")


@dataclass(slots=True)
class Order:
    side: str
    price: int
    size: int
    priority: int


@dataclass(slots=True)
class Level:
    total_size: int
    queue: dict[int, None]


class LevelBookReplay:
    """Primary replay: explicit orders, price levels, queues, and BBO heaps."""

    def __init__(self) -> None:
        self.orders: dict[int, Order] = {}
        self.levels: dict[str, dict[int, Level]] = {"A": {}, "B": {}}
        self.heaps: dict[str, list[int]] = {"A": [], "B": []}
        self.metrics: Counter[str] = Counter()
        self.internal_violations: Counter[str] = Counter()

    def apply(
        self,
        *,
        ordinal: int,
        action: str,
        side: str,
        order_id: int,
        price: int,
        size: int,
        flags: int,
    ) -> None:
        if action in {"T", "F", "N"}:
            self.metrics[f"{action}_nonmutating"] += 1
            return
        if action == "R":
            self.metrics["clear"] += 1
            self.orders.clear()
            self.levels["A"].clear()
            self.levels["B"].clear()
            self.heaps["A"].clear()
            self.heaps["B"].clear()
            return
        if action not in {"A", "C", "M"}:
            self.metrics["invalid_action"] += 1
            return
        if side not in {"A", "B"}:
            self.metrics["invalid_side"] += 1
            return

        if action == "A":
            if flags & F_TOB:
                self.metrics["top_of_book_add"] += 1
                self._clear_side(side)
                if price == UNDEF_PRICE:
                    self.metrics["top_of_book_remove"] += 1
                    return
            if not self._valid_resting_values(price, size):
                return
            if order_id in self.orders:
                self.metrics["duplicate_add"] += 1
                return
            self._insert(order_id, Order(side, price, size, ordinal))
            self.metrics["add_applied"] += 1
            return

        existing = self.orders.get(order_id)
        if action == "C":
            if existing is None:
                self.metrics["orphan_cancel"] += 1
                return
            if size <= 0:
                self.metrics["nonpositive_cancel_size"] += 1
                return
            if existing.side != side:
                self.metrics["cancel_side_mismatch"] += 1
            if existing.price != price:
                self.metrics["cancel_price_mismatch"] += 1
            if size > existing.size:
                self.metrics["oversized_cancel"] += 1
                return
            if size == existing.size:
                self._remove(order_id)
                self.metrics["full_cancel_applied"] += 1
            else:
                level = self.levels[existing.side].get(existing.price)
                if level is None:
                    self.internal_violations["missing_cancel_level"] += 1
                    return
                existing.size -= size
                level.total_size -= size
                self.metrics["partial_cancel_applied"] += 1
                if level.total_size <= 0:
                    self.internal_violations["nonpositive_level_after_cancel"] += 1
            return

        if not self._valid_resting_values(price, size):
            return
        if existing is None:
            self.metrics["orphan_modify_treated_as_add"] += 1
            self._insert(order_id, Order(side, price, size, ordinal))
            return
        if existing.side != side:
            self.metrics["modify_side_mismatch"] += 1
            return
        loses_priority = existing.price != price or existing.size < size
        if loses_priority:
            self._remove(order_id)
            self._insert(order_id, Order(side, price, size, ordinal))
            self.metrics["priority_losing_modify_applied"] += 1
            return
        level = self.levels[existing.side].get(existing.price)
        if level is None:
            self.internal_violations["missing_modify_level"] += 1
            return
        level.total_size += size - existing.size
        existing.size = size
        existing.price = price
        self.metrics["priority_retaining_modify_applied"] += 1
        if level.total_size <= 0:
            self.internal_violations["nonpositive_level_after_modify"] += 1

    def _valid_resting_values(self, price: int, size: int) -> bool:
        valid = True
        if price == UNDEF_PRICE:
            self.metrics["unexpected_undefined_resting_price"] += 1
            valid = False
        if size <= 0:
            self.metrics["nonpositive_resting_size"] += 1
            valid = False
        return valid

    def _insert(self, order_id: int, order: Order) -> None:
        levels = self.levels[order.side]
        level = levels.get(order.price)
        if level is None:
            level = Level(total_size=0, queue={})
            levels[order.price] = level
            heapq.heappush(
                self.heaps[order.side],
                order.price if order.side == "A" else -order.price,
            )
        if order_id in level.queue:
            self.internal_violations["duplicate_level_queue_order"] += 1
            return
        level.queue[order_id] = None
        level.total_size += order.size
        self.orders[order_id] = order

    def _remove(self, order_id: int) -> None:
        order = self.orders.pop(order_id)
        level = self.levels[order.side].get(order.price)
        if level is None:
            self.internal_violations["missing_remove_level"] += 1
            return
        if order_id not in level.queue:
            self.internal_violations["missing_remove_queue_order"] += 1
            return
        level.queue.pop(order_id)
        level.total_size -= order.size
        if not level.queue:
            if level.total_size != 0:
                self.internal_violations["empty_level_nonzero_depth"] += 1
            self.levels[order.side].pop(order.price)
        elif level.total_size <= 0:
            self.internal_violations["nonpositive_nonempty_level"] += 1

    def _clear_side(self, side: str) -> None:
        order_ids = [
            order_id
            for level in self.levels[side].values()
            for order_id in level.queue
        ]
        for order_id in order_ids:
            self.orders.pop(order_id, None)
        self.levels[side].clear()
        self.heaps[side].clear()

    def best_price(self, side: str) -> int | None:
        heap = self.heaps[side]
        levels = self.levels[side]
        while heap:
            candidate = heap[0] if side == "A" else -heap[0]
            if candidate in levels:
                return candidate
            heapq.heappop(heap)
        return None

    def has_both_sides(self) -> bool:
        return bool(self.levels["A"]) and bool(self.levels["B"])

    def level_count(self) -> int:
        return len(self.levels["A"]) + len(self.levels["B"])

    def validate(self) -> Counter[str]:
        violations: Counter[str] = Counter(self.internal_violations)
        seen: set[int] = set()
        for side in ("A", "B"):
            for price, level in self.levels[side].items():
                if not level.queue:
                    violations["empty_level"] += 1
                computed_size = 0
                last_priority = -1
                for order_id in level.queue:
                    if order_id in seen:
                        violations["order_in_multiple_levels"] += 1
                    seen.add(order_id)
                    order = self.orders.get(order_id)
                    if order is None:
                        violations["queue_order_missing_from_map"] += 1
                        continue
                    if order.side != side or order.price != price:
                        violations["queue_order_location_mismatch"] += 1
                    if order.size <= 0:
                        violations["nonpositive_order_size"] += 1
                    if order.priority <= last_priority:
                        violations["queue_priority_not_strictly_increasing"] += 1
                    last_priority = order.priority
                    computed_size += order.size
                if computed_size != level.total_size:
                    violations["level_depth_mismatch"] += 1
                if level.total_size <= 0:
                    violations["nonpositive_level_depth"] += 1
        missing = set(self.orders).difference(seen)
        if missing:
            violations["map_orders_missing_from_levels"] += len(missing)
        return violations

    def structure_hash(self) -> str:
        digest = hashlib.sha256()
        for side in ("A", "B"):
            for price in sorted(self.levels[side]):
                level = self.levels[side][price]
                digest.update(
                    LEVEL_HEADER.pack(
                        side.encode("ascii"),
                        price,
                        level.total_size,
                        len(level.queue),
                    )
                )
                for order_id in level.queue:
                    digest.update(struct.pack(">Q", order_id))
        return digest.hexdigest()


class OrderMapReplay:
    """Reference replay: independent order-only state and checkpoint rebuilds."""

    def __init__(self) -> None:
        self.orders: dict[int, Order] = {}
        self.metrics: Counter[str] = Counter()

    def apply(
        self,
        *,
        ordinal: int,
        action: str,
        side: str,
        order_id: int,
        price: int,
        size: int,
        flags: int,
    ) -> None:
        if action == "R":
            self.metrics["clear"] += 1
            self.orders = {}
            return
        if action in {"T", "F", "N"}:
            self.metrics[f"{action}_nonmutating"] += 1
            return
        if action not in {"A", "C", "M"}:
            self.metrics["invalid_action"] += 1
            return
        if side not in {"A", "B"}:
            self.metrics["invalid_side"] += 1
            return

        if action == "A":
            if flags & F_TOB:
                self.metrics["top_of_book_add"] += 1
                self.orders = {
                    key: value
                    for key, value in self.orders.items()
                    if value.side != side
                }
                if price == UNDEF_PRICE:
                    self.metrics["top_of_book_remove"] += 1
                    return
            if not self._valid_resting_values(price, size):
                return
            if order_id in self.orders:
                self.metrics["duplicate_add"] += 1
                return
            self.orders[order_id] = Order(side, price, size, ordinal)
            self.metrics["add_applied"] += 1
            return

        existing = self.orders.get(order_id)
        if action == "C":
            if existing is None:
                self.metrics["orphan_cancel"] += 1
                return
            if size <= 0:
                self.metrics["nonpositive_cancel_size"] += 1
                return
            if existing.side != side:
                self.metrics["cancel_side_mismatch"] += 1
            if existing.price != price:
                self.metrics["cancel_price_mismatch"] += 1
            if size > existing.size:
                self.metrics["oversized_cancel"] += 1
                return
            remaining = existing.size - size
            if remaining == 0:
                del self.orders[order_id]
                self.metrics["full_cancel_applied"] += 1
            else:
                existing.size = remaining
                self.metrics["partial_cancel_applied"] += 1
            return

        if not self._valid_resting_values(price, size):
            return
        if existing is None:
            self.metrics["orphan_modify_treated_as_add"] += 1
            self.orders[order_id] = Order(side, price, size, ordinal)
            return
        if existing.side != side:
            self.metrics["modify_side_mismatch"] += 1
            return
        if existing.price != price or existing.size < size:
            self.orders[order_id] = Order(side, price, size, ordinal)
            self.metrics["priority_losing_modify_applied"] += 1
        else:
            existing.price = price
            existing.size = size
            self.metrics["priority_retaining_modify_applied"] += 1

    def _valid_resting_values(self, price: int, size: int) -> bool:
        valid = True
        if price == UNDEF_PRICE:
            self.metrics["unexpected_undefined_resting_price"] += 1
            valid = False
        if size <= 0:
            self.metrics["nonpositive_resting_size"] += 1
            valid = False
        return valid

    def has_both_sides(self) -> bool:
        sides = {order.side for order in self.orders.values()}
        return sides == {"A", "B"}

    def level_count(self) -> int:
        return len({(order.side, order.price) for order in self.orders.values()})

    def validate(self) -> Counter[str]:
        violations: Counter[str] = Counter()
        for order in self.orders.values():
            if order.side not in {"A", "B"}:
                violations["invalid_order_side"] += 1
            if order.size <= 0:
                violations["nonpositive_order_size"] += 1
            if order.price == UNDEF_PRICE:
                violations["undefined_resting_price"] += 1
        return violations

    def structure_hash(self) -> str:
        grouped: dict[tuple[str, int], list[tuple[int, Order]]] = defaultdict(list)
        for order_id, order in self.orders.items():
            grouped[(order.side, order.price)].append((order_id, order))
        digest = hashlib.sha256()
        for side in ("A", "B"):
            prices = sorted(
                price for current_side, price in grouped if current_side == side
            )
            for price in prices:
                queue = sorted(
                    grouped[(side, price)],
                    key=lambda item: (item[1].priority, item[0]),
                )
                total_size = sum(order.size for _, order in queue)
                digest.update(
                    LEVEL_HEADER.pack(
                        side.encode("ascii"),
                        price,
                        total_size,
                        len(queue),
                    )
                )
                for order_id, _ in queue:
                    digest.update(struct.pack(">Q", order_id))
        return digest.hexdigest()


def state_hash(orders: dict[int, Order]) -> str:
    digest = hashlib.sha256()
    for order_id in sorted(orders):
        order = orders[order_id]
        digest.update(
            ORDER_RECORD.pack(
                order_id,
                order.side.encode("ascii"),
                order.price,
                order.size,
                order.priority,
            )
        )
    return digest.hexdigest()


def replay_source(
    parquet_path: Path,
    *,
    implementation: str,
    expected_records: int,
) -> dict[str, Any]:
    import pyarrow as pa
    import pyarrow.parquet as pq

    book: LevelBookReplay | OrderMapReplay
    if implementation == "primary":
        book = LevelBookReplay()
    elif implementation == "reference":
        book = OrderMapReplay()
    else:
        raise ValueError(f"Unknown implementation: {implementation}")

    fixed_checkpoints = set(
        range(CHECKPOINT_INTERVAL, expected_records, CHECKPOINT_INTERVAL)
    )
    fixed_checkpoints.add(expected_records)
    checkpoint_ordinals: set[int] = set()
    checkpoints: list[dict[str, Any]] = []
    input_hash = hashlib.sha256()
    action_counts: Counter[str] = Counter()
    flag_counts: Counter[str] = Counter()
    timestamp_counts: Counter[str] = Counter()
    sequence_counts: Counter[str] = Counter()
    snapshot_counts: Counter[str] = Counter()
    boundary_counts: Counter[str] = Counter()
    prior_recv: int | None = None
    prior_live_event: int | None = None
    prior_live_sequence: int | None = None
    snapshot_started = False
    snapshot_complete = False
    snapshot_recovery_valid = False
    snapshot_orders_after: int | None = None
    snapshot_levels_after: int | None = None
    total_records = 0

    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(
        batch_size=100_000,
        columns=list(REQUIRED_COLUMNS),
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in REQUIRED_COLUMNS
        }
        ts_recv = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        ts_event = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in REQUIRED_COLUMNS
            if name
            not in {
                "ts_recv",
                "ts_event",
                "action",
                "side",
            }
        }
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()

        for index in range(batch.num_rows):
            total_records += 1
            source_file_index = int(numeric["source_file_index"][index])
            source_ordinal = int(numeric["source_row_ordinal"][index])
            recv = int(ts_recv[index])
            event = int(ts_event[index])
            rtype = int(numeric["rtype"][index])
            publisher_id = int(numeric["publisher_id"][index])
            instrument_id = int(numeric["instrument_id"][index])
            action = str(actions[index])
            side = str(sides[index])
            price = int(numeric["price_fixed_1e9"][index])
            size = int(numeric["size"][index])
            channel_id = int(numeric["channel_id"][index])
            order_id = int(numeric["order_id"][index])
            flags = int(numeric["flags"][index])
            ts_in_delta = int(numeric["ts_in_delta"][index])
            sequence = int(numeric["sequence"][index])
            input_hash.update(
                STREAM_RECORD.pack(
                    source_file_index,
                    source_ordinal,
                    recv,
                    event,
                    rtype,
                    publisher_id,
                    instrument_id,
                    action.encode("ascii"),
                    side.encode("ascii"),
                    price,
                    size,
                    channel_id,
                    order_id,
                    flags,
                    ts_in_delta,
                    sequence,
                )
            )
            action_counts[action] += 1
            if flags & F_LAST:
                flag_counts["last"] += 1
            if flags & F_TOB:
                flag_counts["top_of_book"] += 1
            if flags & F_SNAPSHOT:
                flag_counts["snapshot"] += 1
            if flags & F_BAD_TS_RECV:
                flag_counts["bad_receive_timestamp"] += 1
            if flags & F_MAYBE_BAD_BOOK:
                flag_counts["maybe_bad_book"] += 1

            if prior_recv is not None and recv < prior_recv:
                timestamp_counts["receive_regression"] += 1
            prior_recv = recv

            is_snapshot = bool(flags & F_SNAPSHOT)
            if is_snapshot:
                snapshot_counts["records"] += 1
                if not snapshot_started:
                    snapshot_started = True
                    snapshot_counts["starts"] += 1
                    if action != "R":
                        snapshot_counts["first_action_not_clear"] += 1
                elif snapshot_complete:
                    snapshot_counts["noncontiguous_records"] += 1
                if not flags & F_BAD_TS_RECV:
                    snapshot_counts["missing_bad_receive_flag"] += 1
                if action == "R":
                    snapshot_counts["clear_actions"] += 1
                elif action == "A":
                    snapshot_counts["add_actions"] += 1
                else:
                    snapshot_counts["invalid_actions"] += 1
            elif snapshot_started and not snapshot_complete:
                snapshot_counts["ended_without_last_flag"] += 1

            if not is_snapshot:
                if prior_live_event is not None and event < prior_live_event:
                    timestamp_counts["live_event_regression"] += 1
                prior_live_event = event
                if (
                    prior_live_sequence is not None
                    and sequence < prior_live_sequence
                ):
                    sequence_counts["live_sequence_regression"] += 1
                prior_live_sequence = sequence

            book.apply(
                ordinal=total_records,
                action=action,
                side=side,
                order_id=order_id,
                price=price,
                size=size,
                flags=flags,
            )

            snapshot_completed_now = bool(is_snapshot and flags & F_LAST)
            if snapshot_completed_now:
                snapshot_counts["last_flags"] += 1
                snapshot_complete = True
                snapshot_orders_after = len(book.orders)
                snapshot_levels_after = book.level_count()
                violations = book.validate()
                snapshot_recovery_valid = (
                    snapshot_counts["starts"] == 1
                    and snapshot_counts["clear_actions"] == 1
                    and snapshot_counts["invalid_actions"] == 0
                    and snapshot_counts["missing_bad_receive_flag"] == 0
                    and snapshot_counts["last_flags"] == 1
                    and snapshot_orders_after > 0
                    and snapshot_levels_after > 0
                    and book.has_both_sides()
                    and not violations
                )

            if flags & F_LAST and isinstance(book, LevelBookReplay):
                boundary_counts["examined"] += 1
                best_bid = book.best_price("B")
                best_ask = book.best_price("A")
                if best_bid is None or best_ask is None:
                    boundary_counts["empty_side"] += 1
                elif best_bid == best_ask:
                    boundary_counts["locked"] += 1
                elif best_bid > best_ask:
                    boundary_counts["crossed"] += 1

            if total_records in fixed_checkpoints or snapshot_completed_now:
                if total_records not in checkpoint_ordinals:
                    violations = book.validate()
                    checkpoints.append(
                        {
                            "record_ordinal": total_records,
                            "state_hash": state_hash(book.orders),
                            "structure_hash": book.structure_hash(),
                            "resting_order_count": len(book.orders),
                            "price_level_count": book.level_count(),
                            "invariant_violation_counts": dict(
                                sorted(violations.items())
                            ),
                        }
                    )
                    checkpoint_ordinals.add(total_records)

    final_violations = book.validate()
    lifecycle_denominator = (
        action_counts.get("C", 0) + action_counts.get("M", 0)
    )
    orphan_events = (
        book.metrics.get("orphan_cancel", 0)
        + book.metrics.get("orphan_modify_treated_as_add", 0)
    )
    return {
        "replay_version": "GC_MBO_ENGINEERING_REPLAY_V0_1",
        "implementation": implementation,
        "source_records_processed": total_records,
        "input_stream_hash": input_hash.hexdigest(),
        "action_counts": dict(sorted(action_counts.items())),
        "flag_counts": dict(sorted(flag_counts.items())),
        "timestamp_counts": dict(sorted(timestamp_counts.items())),
        "sequence_counts": dict(sorted(sequence_counts.items())),
        "snapshot": {
            "counts": dict(sorted(snapshot_counts.items())),
            "recovery_valid": snapshot_recovery_valid,
            "resting_orders_after_recovery": snapshot_orders_after,
            "price_levels_after_recovery": snapshot_levels_after,
        },
        "book_boundaries": dict(sorted(boundary_counts.items())),
        "lifecycle_metrics": dict(sorted(book.metrics.items())),
        "orphan_event_rate": (
            orphan_events / lifecycle_denominator
            if lifecycle_denominator
            else None
        ),
        "checkpoints": checkpoints,
        "final_state_hash": state_hash(book.orders),
        "final_structure_hash": book.structure_hash(),
        "final_resting_order_count": len(book.orders),
        "final_price_level_count": book.level_count(),
        "final_invariant_violation_counts": dict(
            sorted(final_violations.items())
        ),
        "technical_replay_processed_book_values": True,
        "price_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }


def run_synthetic_self_test() -> dict[str, Any]:
    primary = LevelBookReplay()
    reference = OrderMapReplay()
    events = [
        ("R", "N", 0, UNDEF_PRICE, 0, F_SNAPSHOT),
        ("A", "B", 1, 100, 10, F_SNAPSHOT),
        ("A", "B", 2, 100, 5, F_SNAPSHOT),
        ("A", "A", 3, 110, 6, F_SNAPSHOT | F_LAST),
        ("C", "B", 1, 100, 3, F_LAST),
        ("M", "B", 2, 100, 7, F_LAST),
        ("M", "B", 1, 101, 7, F_LAST),
        ("T", "B", 0, 101, 1, 0),
        ("F", "A", 3, 110, 1, F_LAST),
        ("M", "A", 4, 111, 2, F_LAST),
        ("C", "A", 3, 110, 6, F_LAST),
    ]
    for ordinal, (action, side, order_id, price, size, flags) in enumerate(
        events,
        start=1,
    ):
        kwargs = {
            "ordinal": ordinal,
            "action": action,
            "side": side,
            "order_id": order_id,
            "price": price,
            "size": size,
            "flags": flags,
        }
        primary.apply(**kwargs)
        reference.apply(**kwargs)
    checks = {
        "state_hashes_match": state_hash(primary.orders)
        == state_hash(reference.orders),
        "structure_hashes_match": primary.structure_hash()
        == reference.structure_hash(),
        "lifecycle_metrics_match": primary.metrics == reference.metrics,
        "primary_invariants_hold": not primary.validate(),
        "reference_invariants_hold": not reference.validate(),
        "trade_and_fill_nonmutating": (
            primary.metrics["T_nonmutating"] == 1
            and primary.metrics["F_nonmutating"] == 1
        ),
        "orphan_modify_applied_as_add": (
            primary.metrics["orphan_modify_treated_as_add"] == 1
        ),
    }
    return {
        "self_test_version": "GC_MBO_ENGINEERING_SYNTHETIC_SELF_TEST_V0_1",
        "checks": checks,
        "status": "PASS" if all(checks.values()) else "FAIL",
        "synthetic_events": len(events),
        "uses_market_data": False,
    }


def compare_replays(
    protocol: dict[str, Any],
    primary: dict[str, Any],
    reference: dict[str, Any],
    self_test: dict[str, Any],
) -> dict[str, Any]:
    primary_checkpoints = {
        int(item["record_ordinal"]): item for item in primary["checkpoints"]
    }
    reference_checkpoints = {
        int(item["record_ordinal"]): item for item in reference["checkpoints"]
    }
    checkpoint_ordinals_match = set(primary_checkpoints) == set(
        reference_checkpoints
    )
    checkpoint_comparisons: list[dict[str, Any]] = []
    if checkpoint_ordinals_match:
        for ordinal in sorted(primary_checkpoints):
            left = primary_checkpoints[ordinal]
            right = reference_checkpoints[ordinal]
            checkpoint_comparisons.append(
                {
                    "record_ordinal": ordinal,
                    "state_hash_match": left["state_hash"] == right["state_hash"],
                    "structure_hash_match": left["structure_hash"]
                    == right["structure_hash"],
                    "resting_order_count_match": left["resting_order_count"]
                    == right["resting_order_count"],
                    "price_level_count_match": left["price_level_count"]
                    == right["price_level_count"],
                    "primary_invariant_violations": left[
                        "invariant_violation_counts"
                    ],
                    "reference_invariant_violations": right[
                        "invariant_violation_counts"
                    ],
                }
            )

    lifecycle = primary["lifecycle_metrics"]
    boundaries = primary["book_boundaries"]
    snapshot = primary["snapshot"]
    gates = {
        "source_record_counts_match_seal": (
            primary["source_records_processed"]
            == reference["source_records_processed"]
            == int(protocol["source"]["normalized_records"])
        ),
        "input_stream_hashes_match": primary["input_stream_hash"]
        == reference["input_stream_hash"],
        "checkpoint_ordinals_match": checkpoint_ordinals_match,
        "all_checkpoint_state_hashes_match": (
            bool(checkpoint_comparisons)
            and all(item["state_hash_match"] for item in checkpoint_comparisons)
        ),
        "all_checkpoint_structure_hashes_match": (
            bool(checkpoint_comparisons)
            and all(
                item["structure_hash_match"] for item in checkpoint_comparisons
            )
        ),
        "all_checkpoint_invariants_hold": (
            all(
                not item["primary_invariant_violations"]
                and not item["reference_invariant_violations"]
                for item in checkpoint_comparisons
            )
        ),
        "final_state_hashes_match": primary["final_state_hash"]
        == reference["final_state_hash"],
        "final_structure_hashes_match": primary["final_structure_hash"]
        == reference["final_structure_hash"],
        "final_invariants_hold": (
            not primary["final_invariant_violation_counts"]
            and not reference["final_invariant_violation_counts"]
        ),
        "lifecycle_metric_counts_match": primary["lifecycle_metrics"]
        == reference["lifecycle_metrics"],
        "receive_timestamp_regressions_zero": (
            primary["timestamp_counts"].get("receive_regression", 0) == 0
            and reference["timestamp_counts"].get("receive_regression", 0) == 0
        ),
        "invalid_actions_zero": lifecycle.get("invalid_action", 0) == 0,
        "invalid_sides_zero": lifecycle.get("invalid_side", 0) == 0,
        "duplicate_adds_zero": lifecycle.get("duplicate_add", 0) == 0,
        "orphan_cancels_zero": lifecycle.get("orphan_cancel", 0) == 0,
        "oversized_cancels_zero": lifecycle.get("oversized_cancel", 0) == 0,
        "cancel_side_mismatches_zero": lifecycle.get(
            "cancel_side_mismatch",
            0,
        )
        == 0,
        "cancel_price_mismatches_zero": lifecycle.get(
            "cancel_price_mismatch",
            0,
        )
        == 0,
        "modify_side_mismatches_zero": lifecycle.get(
            "modify_side_mismatch",
            0,
        )
        == 0,
        "nonpositive_resting_order_violations_zero": (
            lifecycle.get("nonpositive_resting_size", 0) == 0
            and lifecycle.get("unexpected_undefined_resting_price", 0) == 0
            and lifecycle.get("nonpositive_cancel_size", 0) == 0
        ),
        "crossed_or_locked_boundaries_zero": (
            boundaries.get("crossed", 0) == 0
            and boundaries.get("locked", 0) == 0
        ),
        "maybe_bad_book_flags_zero": (
            primary["flag_counts"].get("maybe_bad_book", 0) == 0
        ),
        "snapshot_structure_valid": (
            snapshot["counts"].get("starts", 0) == 1
            and snapshot["counts"].get("clear_actions", 0) == 1
            and snapshot["counts"].get("last_flags", 0) == 1
            and snapshot["counts"].get("invalid_actions", 0) == 0
            and snapshot["counts"].get("noncontiguous_records", 0) == 0
            and snapshot["counts"].get("ended_without_last_flag", 0) == 0
            and snapshot["counts"].get("missing_bad_receive_flag", 0) == 0
        ),
        "snapshot_recovery_valid": (
            primary["snapshot"]["recovery_valid"]
            and reference["snapshot"]["recovery_valid"]
        ),
        "synthetic_semantics_self_test_passes": self_test["status"] == "PASS",
    }
    return {
        "comparison_version": "GC_MBO_ENGINEERING_REPLAY_COMPARISON_V0_1",
        "status": "PASS" if all(gates.values()) else "FAIL",
        "gates": gates,
        "checkpoint_comparisons": checkpoint_comparisons,
        "primary_input_stream_hash": primary["input_stream_hash"],
        "reference_input_stream_hash": reference["input_stream_hash"],
        "primary_final_state_hash": primary["final_state_hash"],
        "reference_final_state_hash": reference["final_state_hash"],
        "primary_final_structure_hash": primary["final_structure_hash"],
        "reference_final_structure_hash": reference["final_structure_hash"],
        "reported_not_rejected": {
            "modify_without_prior_order_count": lifecycle.get(
                "orphan_modify_treated_as_add",
                0,
            ),
            "orphan_event_rate": primary["orphan_event_rate"],
            "empty_book_side_boundaries": boundaries.get("empty_side", 0),
            "live_event_timestamp_regressions": primary[
                "timestamp_counts"
            ].get("live_event_regression", 0),
            "live_sequence_regressions": primary["sequence_counts"].get(
                "live_sequence_regression",
                0,
            ),
        },
        "technical_replay_processed_book_values": True,
        "price_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }


def load_verified_source(protocol_path: Path) -> tuple[dict[str, Any], Path]:
    protocol = _load_json(protocol_path)
    if (
        protocol.get("status") != "FROZEN_BEFORE_REPLAY"
        or protocol.get("scope")
        != "ENGINEERING_ONLY_LIMIT_ORDER_BOOK_RECONSTRUCTION"
    ):
        raise ValueError("Step 3A protocol is not frozen")
    source = protocol["source"]
    acquisition_path = REPO_ROOT / str(source["acquisition_manifest_path"])
    if _sha256(acquisition_path) != source["acquisition_manifest_sha256"]:
        raise ValueError("Step 2 acquisition manifest changed")
    acquisition = _load_json(acquisition_path)
    if (
        acquisition.get("classification") != "ENGINEERING_ONLY"
        or acquisition.get("research_and_validation_exclusion") != "PERMANENT"
        or acquisition.get("normalization", {}).get("quality_gate") != "PASS"
    ):
        raise ValueError("Step 2 engineering-only source policy failed")
    seal_path = Path(str(acquisition["normalization"]["path"]))
    if (
        _sha256(seal_path) != source["seal_sha256"]
        or acquisition["normalization"]["seal_hash"] != source["seal_hash"]
    ):
        raise ValueError("Step 2 source seal changed")
    seal = _load_json(seal_path)
    canonical_seal = {
        key: value for key, value in seal.items() if key != "seal_hash"
    }
    if (
        seal.get("seal_hash") != _canonical_hash(canonical_seal)
        or seal.get("quality_gate") != "PASS"
        or seal.get("classification") != "ENGINEERING_ONLY"
        or seal.get("research_and_validation_exclusion") != "PERMANENT"
    ):
        raise ValueError("Step 2 canonical seal validation failed")
    parquet_path = seal_path.parent / str(seal["normalized_payload"]["path"])
    if (
        not parquet_path.is_file()
        or parquet_path.stat().st_size
        != int(seal["normalized_payload"]["bytes"])
        or _sha256(parquet_path) != seal["normalized_payload"]["sha256"]
    ):
        raise ValueError("Step 2 normalized payload seal failed")
    return protocol, parquet_path


def run_stage(
    action: str,
    *,
    protocol_path: Path,
    output: Path,
) -> None:
    protocol, parquet_path = load_verified_source(protocol_path)
    output.mkdir(parents=True, exist_ok=True)
    if action in {"primary", "reference"}:
        destination = output / f"{action}_replay.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite replay: {destination}")
        self_test = run_synthetic_self_test()
        if self_test["status"] != "PASS":
            raise RuntimeError("Synthetic MBO semantics self-test failed")
        result = replay_source(
            parquet_path,
            implementation=action,
            expected_records=int(protocol["source"]["normalized_records"]),
        )
        result["protocol_sha256"] = _sha256(protocol_path)
        result["source_parquet_sha256"] = _sha256(parquet_path)
        result["synthetic_self_test"] = self_test
        result["result_hash"] = _canonical_hash(result)
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_MBO_STEP_3A_{action.upper()}_REPLAY_COMPLETE",
                    "source_records_processed": result[
                        "source_records_processed"
                    ],
                    "checkpoints": len(result["checkpoints"]),
                    "final_invariant_violations": sum(
                        result["final_invariant_violation_counts"].values()
                    ),
                    "input_stream_hash": result["input_stream_hash"],
                    "final_state_hash": result["final_state_hash"],
                    "price_values_reported": False,
                    "directional_statistics_calculated": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return

    if action == "compare":
        manifest_path = output / "manifest.json"
        comparison_path = output / "comparison.json"
        if manifest_path.exists() or comparison_path.exists():
            raise FileExistsError("Refusing to overwrite sealed Step 3A results")
        primary_path = output / "primary_replay.json"
        reference_path = output / "reference_replay.json"
        primary = _load_json(primary_path)
        reference = _load_json(reference_path)
        if primary["protocol_sha256"] != _sha256(protocol_path):
            raise ValueError("Primary replay protocol hash mismatch")
        if reference["protocol_sha256"] != _sha256(protocol_path):
            raise ValueError("Reference replay protocol hash mismatch")
        self_test = run_synthetic_self_test()
        comparison = compare_replays(protocol, primary, reference, self_test)
        comparison["protocol_sha256"] = _sha256(protocol_path)
        comparison["primary_result_hash"] = primary["result_hash"]
        comparison["reference_result_hash"] = reference["result_hash"]
        comparison["comparison_hash"] = _canonical_hash(comparison)
        _write_json_atomic(comparison_path, comparison)
        manifest: dict[str, Any] = {
            "manifest_version": "GC_MBO_ENGINEERING_STEP_3A_MANIFEST_V0_1",
            "status": comparison["status"],
            "classification": "ENGINEERING_ONLY",
            "research_and_validation_exclusion": "PERMANENT",
            "protocol": {
                "path": str(protocol_path.resolve()),
                "sha256": _sha256(protocol_path),
            },
            "source": {
                "path": str(parquet_path.resolve()),
                "sha256": _sha256(parquet_path),
                "records": int(protocol["source"]["normalized_records"]),
            },
            "artifacts": [
                _artifact(primary_path),
                _artifact(reference_path),
                _artifact(comparison_path),
            ],
            "comparison_hash": comparison["comparison_hash"],
            "technical_replay_processed_book_values": True,
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
                    "stage": "GC_MBO_STEP_3A_COMPARISON_SEALED",
                    "status": comparison["status"],
                    "passed_gates": sum(comparison["gates"].values()),
                    "total_gates": len(comparison["gates"]),
                    "checkpoint_comparisons": len(
                        comparison["checkpoint_comparisons"]
                    ),
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
            raise ValueError("Step 3A manifest hash mismatch")
        for item in manifest["artifacts"]:
            path = Path(str(item["path"]))
            if (
                not path.is_file()
                or path.stat().st_size != int(item["bytes"])
                or _sha256(path) != item["sha256"]
            ):
                raise ValueError(f"Step 3A artifact mismatch: {path}")
        comparison = _load_json(output / "comparison.json")
        if comparison["comparison_hash"] != manifest["comparison_hash"]:
            raise ValueError("Step 3A comparison hash mismatch")
        print(
            json.dumps(
                {
                    "stage": "GC_MBO_STEP_3A_SEAL_VERIFIED",
                    "status": manifest["status"],
                    "artifacts_verified": len(manifest["artifacts"]),
                    "manifest_hash": manifest["manifest_hash"],
                    "classification": manifest["classification"],
                    "research_and_validation_exclusion": manifest[
                        "research_and_validation_exclusion"
                    ],
                    "price_values_reported": False,
                    "directional_statistics_calculated": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    raise AssertionError(f"Unhandled action: {action}")


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("primary", "reference", "compare", "verify"),
    )
    parser.add_argument("--protocol", default=str(PROTOCOL_PATH))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    return parser


def _canonical_hash(value: Any) -> str:
    payload = json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


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
    args = _parser().parse_args()
    run_stage(
        args.action,
        protocol_path=Path(args.protocol),
        output=Path(args.output),
    )
