#!/usr/bin/env python3
"""Compare both sealed GC MBO reconstructions with sealed vendor MBP-10.

The comparator implements Step 3B.2 Amendment A. It processes market values
only inside deterministic equality checks and emits counts and hashes, never
prices or depth values.
"""

from __future__ import annotations

import bisect
import hashlib
import json
import struct
import tempfile
from collections import Counter, defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterator

import pyarrow as pa
import pyarrow.parquet as pq

from reconstruct_gc_mbo_engineering_book import (
    F_LAST,
    F_TOB,
    PROTOCOL_PATH as STEP_3A_PROTOCOL_PATH,
    LevelBookReplay,
    OrderMapReplay,
    state_hash,
    load_verified_source,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
AMENDMENT_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3b2_amendment_a_v01.json"
)
FREEZE_PATH = (
    REPO_ROOT
    / "research_manifests"
    / "gc_microstructure_step_3b2_freeze_v01.json"
)
EXPECTED_AMENDMENT_SHA256 = (
    "dc437c6f8a6f01c9c6c04a28133d9dfed5b9eeff9f87b8f62e87f113651a2709"
)
EXPECTED_FREEZE_SHA256 = (
    "5f13cf74f8598fcb15e21202bafee9a0f42211cfffa577aff355688f5b63053f"
)
MBP_ACQUISITION_PATH = (
    REPO_ROOT
    / "data"
    / "raw"
    / "databento_gc_mbp10_engineering_benchmark"
    / "acquisition_manifest.json"
)
DEFAULT_OUTPUT = (
    REPO_ROOT / "research_artifacts" / "gc_microstructure_step_3b2_v01"
)
UNDEFINED_FIXED_PRICE = 9_223_372_036_854_775_807
EXPECTED_MBO_RECORDS = 2_322_905
EXPECTED_MBO_BOUNDARIES = 2_062_923
EXPECTED_MBP_RECORDS = 1_924_786
CHECKPOINT_INTERVAL = 250_000
KEY_STRUCT = struct.Struct(">5q")
INT_STRUCT = struct.Struct(">q")
FIELD_NAMES = tuple(
    f"{side}_{kind}_{level:02d}"
    for level in range(10)
    for side in ("bid", "ask")
    for kind in ("px", "sz", "ct")
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
MBP_COLUMNS = (
    "source_row_ordinal",
    "ts_recv",
    "ts_event",
    "publisher_id",
    "instrument_id",
    "sequence",
    *FIELD_NAMES,
)
STATE_INTERVALS = (
    (
        "CONTINUOUS_MATCHING",
        1_704_758_400_000_000_000,
        1_704_837_600_000_000_000,
    ),
    (
        "MAINTENANCE",
        1_704_837_600_000_000_000,
        1_704_840_300_000_000_000,
    ),
    (
        "PRE_OPEN",
        1_704_840_300_000_000_000,
        1_704_841_200_000_000_000,
    ),
    (
        "CONTINUOUS_MATCHING",
        1_704_841_200_000_000_000,
        1_704_844_800_000_000_000,
    ),
)


@dataclass(frozen=True, slots=True)
class Boundary:
    recv: int
    key: tuple[int, int, int, int, int]
    levels: tuple[int, ...]
    relation: str


@dataclass(frozen=True, slots=True)
class VendorRow:
    recv: int
    key: tuple[int, int, int, int, int]
    levels: tuple[int, ...]
    relation: str


class SortedPriceIndex:
    """Sorted price lists synchronized to the primary explicit-level book."""

    def __init__(self) -> None:
        self.prices: dict[str, list[int]] = {"A": [], "B": []}

    def after_apply(
        self,
        book: LevelBookReplay,
        *,
        action: str,
        side: str,
        price: int,
        flags: int,
        prior_location: tuple[str, int] | None,
    ) -> None:
        if action == "R":
            self.prices = {"A": [], "B": []}
            return
        if action == "A" and flags & F_TOB and side in {"A", "B"}:
            self.prices[side] = sorted(book.levels[side])
            return
        candidates: set[tuple[str, int]] = set()
        if prior_location is not None:
            candidates.add(prior_location)
        if side in {"A", "B"} and price != UNDEFINED_FIXED_PRICE:
            candidates.add((side, price))
        for current_side, current_price in candidates:
            values = self.prices[current_side]
            position = bisect.bisect_left(values, current_price)
            present = position < len(values) and values[position] == current_price
            exists = current_price in book.levels[current_side]
            if exists and not present:
                values.insert(position, current_price)
            elif present and not exists:
                values.pop(position)

    def validate(self, book: LevelBookReplay) -> int:
        return sum(
            self.prices[side] != sorted(book.levels[side])
            for side in ("A", "B")
        )


class ReferenceLevelIndex:
    """Independent aggregate index synchronized from OrderMapReplay deltas."""

    def __init__(self) -> None:
        self.levels: dict[str, dict[int, list[int]]] = {"A": {}, "B": {}}
        self.prices: dict[str, list[int]] = {"A": [], "B": []}

    def rebuild(self, book: OrderMapReplay) -> None:
        self.levels = {"A": {}, "B": {}}
        self.prices = {"A": [], "B": []}
        for order in book.orders.values():
            self._add(order.side, order.price, order.size)

    def apply_delta(
        self,
        *,
        prior: tuple[str, int, int] | None,
        current: tuple[str, int, int] | None,
    ) -> None:
        if prior == current:
            return
        if prior is not None:
            self._remove(*prior)
        if current is not None:
            self._add(*current)

    def _add(self, side: str, price: int, size: int) -> None:
        level = self.levels[side].get(price)
        if level is None:
            self.levels[side][price] = [size, 1]
            bisect.insort(self.prices[side], price)
        else:
            level[0] += size
            level[1] += 1

    def _remove(self, side: str, price: int, size: int) -> None:
        level = self.levels[side].get(price)
        if level is None:
            raise ValueError("Reference aggregate index missing prior level")
        level[0] -= size
        level[1] -= 1
        if level[1] == 0:
            if level[0] != 0:
                raise ValueError("Reference aggregate level has residual size")
            del self.levels[side][price]
            position = bisect.bisect_left(self.prices[side], price)
            if (
                position >= len(self.prices[side])
                or self.prices[side][position] != price
            ):
                raise ValueError("Reference sorted price index missing level")
            self.prices[side].pop(position)
        elif level[0] <= 0 or level[1] < 0:
            raise ValueError("Reference aggregate level became nonpositive")

    def validate(self, book: OrderMapReplay) -> int:
        rebuilt: dict[str, dict[int, list[int]]] = {"A": {}, "B": {}}
        for order in book.orders.values():
            level = rebuilt[order.side].setdefault(order.price, [0, 0])
            level[0] += order.size
            level[1] += 1
        violations = int(rebuilt != self.levels)
        violations += sum(
            self.prices[side] != sorted(self.levels[side])
            for side in ("A", "B")
        )
        return violations


def main() -> None:
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("primary", "reference", "reproduce", "compare", "verify"),
    )
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    run_stage(args.action, output=Path(args.output))


def run_stage(action: str, *, output: Path) -> None:
    context = _verified_context()
    output.mkdir(parents=True, exist_ok=True)
    if action in {"primary", "reference", "reproduce"}:
        implementation = "primary" if action == "primary" else "reference"
        destination = output / f"{action}_comparison.json"
        if destination.exists():
            raise FileExistsError(f"Refusing to overwrite result: {destination}")
        result = compare_streams(
            context["mbo_parquet"],
            context["mbp_parquet"],
            implementation=implementation,
        )
        result["run_label"] = action
        result["amendment_sha256"] = EXPECTED_AMENDMENT_SHA256
        result["freeze_sha256"] = EXPECTED_FREEZE_SHA256
        result["mbo_parquet_sha256"] = context["mbo_parquet_sha256"]
        result["mbp_parquet_sha256"] = context["mbp_parquet_sha256"]
        result["result_hash"] = _canonical_hash(result)
        _write_json_atomic(destination, result)
        print(
            json.dumps(
                {
                    "stage": f"GC_STEP_3B2_{action.upper()}_COMPARISON_COMPLETE",
                    "implementation": implementation,
                    "mbo_boundaries": result["counts"]["mbo_boundaries"],
                    "mbp10_records": result["counts"]["mbp10_records"],
                    "matched_mbp10_records": result["counts"][
                        "matched_mbp10_records"
                    ],
                    "unmatched_mbp10_records": result["counts"][
                        "unmatched_mbp10_records"
                    ],
                    "unrepresented_mbo_boundaries": result["counts"][
                        "unrepresented_mbo_boundaries"
                    ],
                    "mismatched_book_rows": result["counts"][
                        "mismatched_book_rows"
                    ],
                    "book_field_mismatches": result["counts"][
                        "book_field_mismatches"
                    ],
                    "canonical_comparison_checksum": result["hashes"][
                        "canonical_comparison_checksum"
                    ],
                    "market_values_reported": False,
                    "outcomes_accessed": False,
                },
                sort_keys=True,
            )
        )
        return
    if action == "compare":
        _seal_comparison(output, context)
        return
    if action == "verify":
        _verify_result_seal(output)
        return
    raise AssertionError(f"Unhandled action: {action}")


def compare_streams(
    mbo_path: Path,
    mbp_path: Path,
    *,
    implementation: str,
) -> dict[str, Any]:
    replay_audit: dict[str, Any] = {}
    vendor_audit: dict[str, Any] = {}
    mbo_stream = iter(
        _mbo_boundaries(
            mbo_path,
            implementation=implementation,
            audit=replay_audit,
        )
    )
    vendor_stream = iter(_vendor_rows(mbp_path, audit=vendor_audit))
    current_mbo = next(mbo_stream, None)
    current_vendor = next(vendor_stream, None)

    counts: Counter[str] = Counter()
    state_counts: dict[str, Counter[str]] = defaultdict(Counter)
    mismatch_fields: Counter[str] = Counter()
    vendor_hash = hashlib.sha256()
    reconstruction_hash = hashlib.sha256()
    comparison_hash = hashlib.sha256()
    alignment_hash = hashlib.sha256()

    while current_mbo is not None or current_vendor is not None:
        candidate_receives = [
            item.recv
            for item in (current_mbo, current_vendor)
            if item is not None
        ]
        recv = min(candidate_receives)
        mbo_group: list[Boundary] = []
        while current_mbo is not None and current_mbo.recv == recv:
            mbo_group.append(current_mbo)
            current_mbo = next(mbo_stream, None)
        vendor_group: list[VendorRow] = []
        while current_vendor is not None and current_vendor.recv == recv:
            vendor_group.append(current_vendor)
            current_vendor = next(vendor_stream, None)

        state = _market_state(recv)
        mbo_by_key: dict[tuple[int, int, int, int, int], Boundary] = {}
        for boundary in mbo_group:
            if boundary.key in mbo_by_key:
                counts["duplicate_mbo_boundary_keys"] += 1
            else:
                mbo_by_key[boundary.key] = boundary
        vendor_by_key: dict[tuple[int, int, int, int, int], VendorRow] = {}
        for vendor in vendor_group:
            if vendor.key in vendor_by_key:
                counts["duplicate_mbp10_keys"] += 1
            else:
                vendor_by_key[vendor.key] = vendor

        for vendor in vendor_group:
            counts["mbp10_records"] += 1
            state_counts[state]["mbp10_records"] += 1
            _hash_row(vendor_hash, vendor.key, vendor.levels)
            boundary = mbo_by_key.get(vendor.key)
            if boundary is None:
                counts["unmatched_mbp10_records"] += 1
                state_counts[state]["unmatched_mbp10_records"] += 1
                _hash_key_with_marker(alignment_hash, b"V", vendor.key)
                continue
            counts["matched_mbp10_records"] += 1
            state_counts[state]["matched_mbp10_records"] += 1
            _hash_row(reconstruction_hash, boundary.key, boundary.levels)
            _hash_comparison(
                comparison_hash,
                boundary.key,
                vendor.levels,
                boundary.levels,
            )
            _hash_key_with_marker(alignment_hash, b"M", vendor.key)
            field_mismatch_count = 0
            for field_name, vendor_value, reconstructed_value in zip(
                FIELD_NAMES,
                vendor.levels,
                boundary.levels,
                strict=True,
            ):
                if vendor_value != reconstructed_value:
                    mismatch_fields[field_name] += 1
                    field_mismatch_count += 1
            if field_mismatch_count:
                counts["mismatched_book_rows"] += 1
                counts["book_field_mismatches"] += field_mismatch_count
                state_counts[state]["mismatched_book_rows"] += 1
                state_counts[state][
                    "book_field_mismatches"
                ] += field_mismatch_count
            if vendor.relation != boundary.relation:
                counts["relation_mismatches"] += 1
                state_counts[state]["relation_mismatches"] += 1
            if state == "CONTINUOUS_MATCHING":
                if vendor.relation in {"LOCKED", "CROSSED"}:
                    counts["continuous_vendor_locked_or_crossed"] += 1
                if boundary.relation in {"LOCKED", "CROSSED"}:
                    counts[
                        "continuous_reconstruction_locked_or_crossed"
                    ] += 1

        for boundary in mbo_group:
            counts["mbo_boundaries"] += 1
            state_counts[state]["mbo_boundaries"] += 1
            if boundary.key not in vendor_by_key:
                counts["unrepresented_mbo_boundaries"] += 1
                state_counts[state]["unrepresented_mbo_boundaries"] += 1
                _hash_key_with_marker(alignment_hash, b"O", boundary.key)

    for key in (
        "duplicate_mbo_boundary_keys",
        "duplicate_mbp10_keys",
        "unmatched_mbp10_records",
        "mismatched_book_rows",
        "book_field_mismatches",
        "relation_mismatches",
        "continuous_vendor_locked_or_crossed",
        "continuous_reconstruction_locked_or_crossed",
    ):
        counts.setdefault(key, 0)
    counts["duplicate_matched_mbo_keys"] = counts[
        "duplicate_mbo_boundary_keys"
    ]
    market_state_coverage = sum(
        value["mbo_boundaries"] for value in state_counts.values()
    )
    result: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3B2_STREAM_COMPARISON_V0_1",
        "implementation": implementation,
        "counts": dict(sorted(counts.items())),
        "state_counts": {
            state: dict(sorted(values.items()))
            for state, values in sorted(state_counts.items())
        },
        "mismatch_field_counts": dict(sorted(mismatch_fields.items())),
        "hashes": {
            "vendor_input_hash": vendor_hash.hexdigest(),
            "reconstructed_matched_state_hash": reconstruction_hash.hexdigest(),
            "canonical_comparison_checksum": comparison_hash.hexdigest(),
            "alignment_checksum": alignment_hash.hexdigest(),
        },
        "replay_audit": replay_audit,
        "vendor_audit": vendor_audit,
        "market_state_coverage": {
            "classified_mbo_boundaries": market_state_coverage,
            "expected_mbo_boundaries": counts["mbo_boundaries"],
            "complete": market_state_coverage == counts["mbo_boundaries"],
        },
        "exact_alignment_key": [
            "publisher_id",
            "instrument_id",
            "sequence",
            "ts_event",
            "ts_recv",
        ],
        "exact_book_fields": len(FIELD_NAMES),
        "price_tolerance_fixed_1e9_units": 0,
        "size_tolerance": 0,
        "order_count_tolerance": 0,
        "technical_market_values_processed": True,
        "market_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    result["comparison_payload_hash"] = _canonical_hash(result)
    return result


def _mbo_boundaries(
    path: Path,
    *,
    implementation: str,
    audit: dict[str, Any],
) -> Iterator[Boundary]:
    if implementation == "primary":
        book: LevelBookReplay | OrderMapReplay = LevelBookReplay()
        primary_index: SortedPriceIndex | None = SortedPriceIndex()
        reference_index: ReferenceLevelIndex | None = None
    elif implementation == "reference":
        book = OrderMapReplay()
        primary_index = None
        reference_index = ReferenceLevelIndex()
    else:
        raise ValueError(f"Unknown implementation: {implementation}")

    input_hash = hashlib.sha256()
    boundary_hash = hashlib.sha256()
    source_records = 0
    boundaries = 0
    index_validation_violations = 0
    book_invariant_violations = 0
    instrument_ids: set[int] = set()
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=100_000,
        columns=list(MBO_COLUMNS),
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in MBO_COLUMNS
        }
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in MBO_COLUMNS
            if name not in {"ts_recv", "ts_event", "action", "side"}
        }
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        events = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()
        for index in range(batch.num_rows):
            source_records += 1
            recv = int(receives[index])
            event = int(events[index])
            publisher = int(numeric["publisher_id"][index])
            instrument = int(numeric["instrument_id"][index])
            sequence = int(numeric["sequence"][index])
            action = str(actions[index])
            side = str(sides[index])
            price = int(numeric["price_fixed_1e9"][index])
            size = int(numeric["size"][index])
            order_id = int(numeric["order_id"][index])
            flags = int(numeric["flags"][index])
            source_ordinal = int(numeric["source_row_ordinal"][index])
            instrument_ids.add(instrument)
            key = (publisher, instrument, sequence, event, recv)
            _hash_mbo_input(
                input_hash,
                source_ordinal,
                key,
                action,
                side,
                price,
                size,
                order_id,
                flags,
            )

            prior_order = book.orders.get(order_id)
            prior = (
                (prior_order.side, prior_order.price, prior_order.size)
                if prior_order is not None
                else None
            )
            prior_location = (
                (prior_order.side, prior_order.price)
                if prior_order is not None
                else None
            )
            book.apply(
                ordinal=source_records,
                action=action,
                side=side,
                order_id=order_id,
                price=price,
                size=size,
                flags=flags,
            )
            if primary_index is not None:
                primary_index.after_apply(
                    book,
                    action=action,
                    side=side,
                    price=price,
                    flags=flags,
                    prior_location=prior_location,
                )
            else:
                assert reference_index is not None
                current_order = book.orders.get(order_id)
                current = (
                    (
                        current_order.side,
                        current_order.price,
                        current_order.size,
                    )
                    if current_order is not None
                    else None
                )
                if action == "R" or (
                    action == "A" and flags & F_TOB and side in {"A", "B"}
                ):
                    reference_index.rebuild(book)
                else:
                    reference_index.apply_delta(prior=prior, current=current)

            if source_records % CHECKPOINT_INTERVAL == 0:
                book_invariant_violations += sum(book.validate().values())
                if primary_index is not None:
                    index_validation_violations += primary_index.validate(book)
                else:
                    assert reference_index is not None
                    index_validation_violations += reference_index.validate(book)

            if flags & F_LAST:
                boundaries += 1
                levels = (
                    _primary_top_ten(book, primary_index)
                    if primary_index is not None
                    else _reference_top_ten(reference_index)
                )
                relation = _relation(levels)
                boundary_hash.update(KEY_STRUCT.pack(*key))
                yield Boundary(
                    recv=recv,
                    key=key,
                    levels=levels,
                    relation=relation,
                )

    book_invariant_violations += sum(book.validate().values())
    if primary_index is not None:
        index_validation_violations += primary_index.validate(book)
    else:
        assert reference_index is not None
        index_validation_violations += reference_index.validate(book)
    audit.update(
        {
            "source_records": source_records,
            "f_last_boundaries": boundaries,
            "input_hash": input_hash.hexdigest(),
            "boundary_key_hash": boundary_hash.hexdigest(),
            "instrument_ids": sorted(instrument_ids),
            "book_invariant_violations": book_invariant_violations,
            "index_validation_violations": index_validation_violations,
            "final_state_hash": state_hash(book.orders),
            "final_structure_hash": book.structure_hash(),
        }
    )


def _vendor_rows(path: Path, *, audit: dict[str, Any]) -> Iterator[VendorRow]:
    input_hash = hashlib.sha256()
    records = 0
    instrument_ids: set[int] = set()
    parquet = pq.ParquetFile(path)
    for batch in parquet.iter_batches(
        batch_size=50_000,
        columns=list(MBP_COLUMNS),
    ):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in MBP_COLUMNS
        }
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in MBP_COLUMNS
            if name not in {"ts_recv", "ts_event"}
        }
        receives = arrays["ts_recv"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        events = arrays["ts_event"].cast(pa.int64()).to_numpy(
            zero_copy_only=False
        )
        for index in range(batch.num_rows):
            records += 1
            recv = int(receives[index])
            event = int(events[index])
            publisher = int(numeric["publisher_id"][index])
            instrument = int(numeric["instrument_id"][index])
            sequence = int(numeric["sequence"][index])
            key = (publisher, instrument, sequence, event, recv)
            levels = tuple(
                int(numeric[name][index]) for name in FIELD_NAMES
            )
            instrument_ids.add(instrument)
            _hash_row(input_hash, key, levels)
            yield VendorRow(
                recv=recv,
                key=key,
                levels=levels,
                relation=_relation(levels),
            )
    audit.update(
        {
            "records": records,
            "input_hash": input_hash.hexdigest(),
            "instrument_ids": sorted(instrument_ids),
        }
    )


def _primary_top_ten(
    book: LevelBookReplay | OrderMapReplay,
    index: SortedPriceIndex | None,
) -> tuple[int, ...]:
    if not isinstance(book, LevelBookReplay) or index is None:
        raise TypeError("Primary top-ten extraction received wrong book")
    levels: list[int] = []
    bids = list(reversed(index.prices["B"][-10:]))
    asks = index.prices["A"][:10]
    for level in range(10):
        for side, prices in (("B", bids), ("A", asks)):
            if level < len(prices):
                price = prices[level]
                current = book.levels[side][price]
                levels.extend((price, current.total_size, len(current.queue)))
            else:
                levels.extend((UNDEFINED_FIXED_PRICE, 0, 0))
    return tuple(levels)


def _reference_top_ten(
    index: ReferenceLevelIndex | None,
) -> tuple[int, ...]:
    if index is None:
        raise TypeError("Reference top-ten extraction received no index")
    levels: list[int] = []
    bids = list(reversed(index.prices["B"][-10:]))
    asks = index.prices["A"][:10]
    for level in range(10):
        for side, prices in (("B", bids), ("A", asks)):
            if level < len(prices):
                price = prices[level]
                size, count = index.levels[side][price]
                levels.extend((price, size, count))
            else:
                levels.extend((UNDEFINED_FIXED_PRICE, 0, 0))
    return tuple(levels)


def _relation(levels: tuple[int, ...]) -> str:
    bid = levels[0]
    ask = levels[3]
    if bid == UNDEFINED_FIXED_PRICE or ask == UNDEFINED_FIXED_PRICE:
        return "EMPTY_SIDE"
    if bid < ask:
        return "UNCROSSED"
    if bid == ask:
        return "LOCKED"
    return "CROSSED"


def _market_state(recv: int) -> str:
    matches = [
        state
        for state, start, end in STATE_INTERVALS
        if start <= recv < end
    ]
    if len(matches) != 1:
        raise ValueError("Timestamp does not map to exactly one market state")
    return matches[0]


def _seal_comparison(output: Path, context: dict[str, Any]) -> None:
    verdict_path = output / "verdict.json"
    manifest_path = output / "manifest.json"
    if verdict_path.exists() or manifest_path.exists():
        raise FileExistsError("Refusing to overwrite Step 3B.2 seal")
    primary_path = output / "primary_comparison.json"
    reference_path = output / "reference_comparison.json"
    reproduction_path = output / "reproduce_comparison.json"
    primary = _verified_result(primary_path, "primary", "primary")
    reference = _verified_result(reference_path, "reference", "reference")
    reproduction = _verified_result(
        reproduction_path,
        "reference",
        "reproduce",
    )

    pc = primary["counts"]
    rc = reference["counts"]
    xc = reproduction["counts"]
    ph = primary["hashes"]
    rh = reference["hashes"]
    xh = reproduction["hashes"]
    quality = context["mbp_quality"]
    lineage_consistent = (
        primary["replay_audit"]["instrument_ids"]
        == primary["vendor_audit"]["instrument_ids"]
        == reference["replay_audit"]["instrument_ids"]
        == reference["vendor_audit"]["instrument_ids"]
    )
    counts_match = pc == rc
    mismatch_counts_match = (
        primary["mismatch_field_counts"]
        == reference["mismatch_field_counts"]
    )
    checksums_match = (
        ph["canonical_comparison_checksum"]
        == rh["canonical_comparison_checksum"]
        and ph["reconstructed_matched_state_hash"]
        == rh["reconstructed_matched_state_hash"]
    )
    reproduction_matches = (
        rc == xc
        and reference["state_counts"] == reproduction["state_counts"]
        and reference["mismatch_field_counts"]
        == reproduction["mismatch_field_counts"]
        and rh == xh
        and reference["replay_audit"] == reproduction["replay_audit"]
        and reference["vendor_audit"] == reproduction["vendor_audit"]
    )
    unrepresented_reported = (
        pc["unrepresented_mbo_boundaries"]
        == pc["mbo_boundaries"] - pc["matched_mbp10_records"]
        and sum(
            values.get("unrepresented_mbo_boundaries", 0)
            for values in primary["state_counts"].values()
        )
        == pc["unrepresented_mbo_boundaries"]
    )
    gates = {
        "all_predecessor_seals_valid": context["predecessor_seals_valid"],
        "mbo_source_seal_unchanged": context["mbo_source_seal_valid"],
        "fresh_quote_at_or_below_0_40_usd": (
            float(context["mbp_acquisition"]["actual_cost_usd"]) <= 0.40
        ),
        "mbp10_request_identity_exact": context["mbp_request_identity_exact"],
        "mbp10_raw_and_normalized_sources_hashed_and_sealed": context[
            "mbp_source_seal_valid"
        ],
        "normalized_mbp10_record_count_matches_fresh_provider_metadata": (
            int(quality["normalized_record_count"])
            == int(quality["provider_expected_record_count"])
            == EXPECTED_MBP_RECORDS
        ),
        "full_requested_interval_covered_under_provider_snapshot_semantics": (
            quality["quality_gate"] == "PASS"
        ),
        "symbol_and_instrument_lineage_consistent": lineage_consistent,
        "market_state_classification_complete_and_nonoverlapping": (
            primary["market_state_coverage"]["complete"] is True
            and reference["market_state_coverage"]["complete"] is True
        ),
        "mbp10_alignment_keys_unique": pc["duplicate_mbp10_keys"] == 0,
        "every_mbp10_record_has_exactly_one_mbo_f_last_match": (
            pc["matched_mbp10_records"] == pc["mbp10_records"]
        ),
        "unmatched_mbp10_records": pc["unmatched_mbp10_records"] == 0,
        "duplicate_matched_mbo_keys": pc["duplicate_matched_mbo_keys"] == 0,
        "all_mbp10_records_compared": (
            pc["matched_mbp10_records"] == EXPECTED_MBP_RECORDS
        ),
        "book_field_mismatches": pc["book_field_mismatches"] == 0,
        "continuous_matching_relation_mismatches": (
            pc["relation_mismatches"] == 0
        ),
        "continuous_matching_locked_or_crossed_rows": (
            pc["continuous_vendor_locked_or_crossed"] == 0
            and pc["continuous_reconstruction_locked_or_crossed"] == 0
        ),
        "unrepresented_mbo_boundaries_reported": unrepresented_reported,
        "primary_and_reference_alignment_counts_match": counts_match,
        "primary_and_reference_mismatch_counts_match": mismatch_counts_match,
        "primary_and_reference_comparison_checksums_match": checksums_match,
        "deterministic_repeat_checksum_matches": reproduction_matches,
    }
    integrity_checks = {
        "mbo_record_count_exact": (
            primary["replay_audit"]["source_records"]
            == reference["replay_audit"]["source_records"]
            == EXPECTED_MBO_RECORDS
        ),
        "mbo_boundary_count_exact": (
            pc["mbo_boundaries"]
            == rc["mbo_boundaries"]
            == EXPECTED_MBO_BOUNDARIES
        ),
        "mbp10_record_count_exact": (
            pc["mbp10_records"]
            == rc["mbp10_records"]
            == EXPECTED_MBP_RECORDS
        ),
        "primary_book_and_index_invariants_hold": (
            primary["replay_audit"]["book_invariant_violations"] == 0
            and primary["replay_audit"]["index_validation_violations"] == 0
        ),
        "reference_book_and_index_invariants_hold": (
            reference["replay_audit"]["book_invariant_violations"] == 0
            and reference["replay_audit"]["index_validation_violations"] == 0
        ),
        "mbo_input_hashes_match": (
            primary["replay_audit"]["input_hash"]
            == reference["replay_audit"]["input_hash"]
        ),
        "mbo_boundary_hashes_match": (
            primary["replay_audit"]["boundary_key_hash"]
            == reference["replay_audit"]["boundary_key_hash"]
        ),
        "vendor_input_hashes_match": (
            primary["vendor_audit"]["input_hash"]
            == reference["vendor_audit"]["input_hash"]
        ),
        "final_reconstructed_state_hashes_match": (
            primary["replay_audit"]["final_state_hash"]
            == reference["replay_audit"]["final_state_hash"]
        ),
        "final_reconstructed_structure_hashes_match": (
            primary["replay_audit"]["final_structure_hash"]
            == reference["replay_audit"]["final_structure_hash"]
        ),
        "earlier_verdicts_preserved": (
            context["earlier_verdicts"]
            == {
                "step_3a": "FAIL",
                "step_3a1": "PASS",
                "step_3b1": "FAIL_PRE_ACQUISITION_READINESS",
            }
        ),
    }
    status = (
        "PASS"
        if all(gates.values()) and all(integrity_checks.values())
        else "FAIL"
    )
    verdict: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3B2_VERDICT_V0_1",
        "status": status,
        "classification": "ENGINEERING_ONLY_BOOK_BENCHMARK",
        "research_or_validation_credit": "NONE",
        "amended_pass_gates": gates,
        "integrity_checks": integrity_checks,
        "counts": pc,
        "state_counts": primary["state_counts"],
        "mismatch_field_counts": primary["mismatch_field_counts"],
        "hashes": ph,
        "earlier_verdicts": context["earlier_verdicts"],
        "actual_cost_usd": context["mbp_acquisition"]["actual_cost_usd"],
        "market_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    verdict["verdict_hash"] = _canonical_hash(verdict)
    _write_json_atomic(verdict_path, verdict)

    manifest: dict[str, Any] = {
        "version": "GC_MICROSTRUCTURE_STEP_3B2_MANIFEST_V0_1",
        "status": status,
        "classification": verdict["classification"],
        "research_or_validation_credit": "NONE",
        "amendment": _artifact(AMENDMENT_PATH),
        "freeze_receipt": _artifact(FREEZE_PATH),
        "comparison_tool": _artifact(Path(__file__).resolve()),
        "mbo_source": {
            "path": str(context["mbo_parquet"].resolve()),
            "bytes": context["mbo_parquet"].stat().st_size,
            "sha256": context["mbo_parquet_sha256"],
        },
        "mbp10_source": {
            "path": str(context["mbp_parquet"].resolve()),
            "bytes": context["mbp_parquet"].stat().st_size,
            "sha256": context["mbp_parquet_sha256"],
            "seal_hash": context["mbp_seal"]["seal_hash"],
        },
        "artifacts": [
            _artifact(primary_path),
            _artifact(reference_path),
            _artifact(reproduction_path),
            _artifact(verdict_path),
        ],
        "verdict_hash": verdict["verdict_hash"],
        "earlier_verdicts": context["earlier_verdicts"],
        "actual_cost_usd": context["mbp_acquisition"]["actual_cost_usd"],
        "market_values_reported": False,
        "outcomes_accessed": False,
        "signals_calculated": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    manifest["manifest_hash"] = _canonical_hash(manifest)
    _write_json_atomic(manifest_path, manifest)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3B2_VERDICT_SEALED",
                "status": status,
                "passed_amended_gates": sum(gates.values()),
                "total_amended_gates": len(gates),
                "passed_integrity_checks": sum(integrity_checks.values()),
                "total_integrity_checks": len(integrity_checks),
                "matched_mbp10_records": pc["matched_mbp10_records"],
                "unmatched_mbp10_records": pc["unmatched_mbp10_records"],
                "unrepresented_mbo_boundaries": pc[
                    "unrepresented_mbo_boundaries"
                ],
                "book_field_mismatches": pc["book_field_mismatches"],
                "manifest_hash": manifest["manifest_hash"],
                "market_values_reported": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _verified_context() -> dict[str, Any]:
    if _sha256(AMENDMENT_PATH) != EXPECTED_AMENDMENT_SHA256:
        raise ValueError("Amendment A changed")
    if _sha256(FREEZE_PATH) != EXPECTED_FREEZE_SHA256:
        raise ValueError("Step 3B.2 freeze receipt changed")
    amendment = _load_json(AMENDMENT_PATH)
    for item in amendment["predecessor_preservation"]["frozen_files"]:
        path = REPO_ROOT / str(item["path"])
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Predecessor changed: {path}")
    _, mbo_parquet = load_verified_source(STEP_3A_PROTOCOL_PATH)
    acquisition = _load_json(MBP_ACQUISITION_PATH)
    if (
        acquisition.get("status") != "NORMALIZED_HASHED_AND_SEALED"
        or acquisition.get("amendment_sha256") != EXPECTED_AMENDMENT_SHA256
        or float(acquisition.get("actual_cost_usd", 1.0)) > 0.40
    ):
        raise ValueError("MBP-10 acquisition is not authorized and sealed")
    seal_path = Path(str(acquisition["normalization"]["path"]))
    if _sha256(seal_path) != acquisition["normalization"]["sha256"]:
        raise ValueError("MBP-10 source seal changed")
    seal = _load_json(seal_path)
    seal_without_hash = {
        key: value for key, value in seal.items() if key != "seal_hash"
    }
    if (
        seal["seal_hash"] != _canonical_hash(seal_without_hash)
        or seal["quality_gate"] != "PASS"
    ):
        raise ValueError("MBP-10 canonical source seal failed")
    base = seal_path.parent
    mbp_parquet = base / str(seal["normalized_payload"]["path"])
    quality_path = base / str(seal["data_quality"]["path"])
    for item, path in (
        (seal["normalized_payload"], mbp_parquet),
        (seal["data_quality"], quality_path),
    ):
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError("MBP-10 normalized source artifact changed")
    quality = _load_json(quality_path)
    return {
        "mbo_parquet": mbo_parquet,
        "mbo_parquet_sha256": _sha256(mbo_parquet),
        "mbp_parquet": mbp_parquet,
        "mbp_parquet_sha256": _sha256(mbp_parquet),
        "mbp_acquisition": acquisition,
        "mbp_seal": seal,
        "mbp_quality": quality,
        "predecessor_seals_valid": True,
        "mbo_source_seal_valid": True,
        "mbp_request_identity_exact": (
            acquisition["request"] == amendment["exact_request"]
        ),
        "mbp_source_seal_valid": True,
        "earlier_verdicts": {
            "step_3a": "FAIL",
            "step_3a1": "PASS",
            "step_3b1": "FAIL_PRE_ACQUISITION_READINESS",
        },
    }


def _verified_result(
    path: Path,
    expected_implementation: str,
    expected_label: str,
) -> dict[str, Any]:
    result = _load_json(path)
    declared_hash = result["result_hash"]
    without_hash = {
        key: value for key, value in result.items() if key != "result_hash"
    }
    if declared_hash != _canonical_hash(without_hash):
        raise ValueError(f"Comparison result hash mismatch: {path}")
    if (
        result["implementation"] != expected_implementation
        or result["run_label"] != expected_label
        or result["amendment_sha256"] != EXPECTED_AMENDMENT_SHA256
        or result["freeze_sha256"] != EXPECTED_FREEZE_SHA256
    ):
        raise ValueError(f"Comparison result identity mismatch: {path}")
    return result


def _verify_result_seal(output: Path) -> None:
    manifest_path = output / "manifest.json"
    manifest = _load_json(manifest_path)
    manifest_without_hash = {
        key: value for key, value in manifest.items() if key != "manifest_hash"
    }
    if manifest["manifest_hash"] != _canonical_hash(manifest_without_hash):
        raise ValueError("Step 3B.2 manifest canonical hash mismatch")
    for item in (
        manifest["amendment"],
        manifest["freeze_receipt"],
        manifest["comparison_tool"],
        manifest["mbo_source"],
        manifest["mbp10_source"],
        *manifest["artifacts"],
    ):
        path = Path(str(item["path"]))
        if (
            not path.is_file()
            or path.stat().st_size != int(item["bytes"])
            or _sha256(path) != item["sha256"]
        ):
            raise ValueError(f"Step 3B.2 sealed artifact changed: {path}")
    verdict = _load_json(output / "verdict.json")
    verdict_without_hash = {
        key: value for key, value in verdict.items() if key != "verdict_hash"
    }
    if (
        verdict["verdict_hash"] != _canonical_hash(verdict_without_hash)
        or verdict["verdict_hash"] != manifest["verdict_hash"]
    ):
        raise ValueError("Step 3B.2 verdict seal mismatch")
    if verdict["earlier_verdicts"] != {
        "step_3a": "FAIL",
        "step_3a1": "PASS",
        "step_3b1": "FAIL_PRE_ACQUISITION_READINESS",
    }:
        raise ValueError("Earlier verdicts were not preserved")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_3B2_SEAL_VERIFIED",
                "status": manifest["status"],
                "manifest_hash": manifest["manifest_hash"],
                "sealed_artifacts_verified": len(manifest["artifacts"]) + 5,
                "earlier_verdicts_preserved": True,
                "market_values_reported": False,
                "outcomes_accessed": False,
                "signals_calculated": False,
                "execution_optimized": False,
                "pnl_calculated": False,
            },
            sort_keys=True,
        )
    )


def _hash_mbo_input(
    digest: Any,
    ordinal: int,
    key: tuple[int, int, int, int, int],
    action: str,
    side: str,
    price: int,
    size: int,
    order_id: int,
    flags: int,
) -> None:
    digest.update(INT_STRUCT.pack(ordinal))
    digest.update(KEY_STRUCT.pack(*key))
    digest.update(action.encode("ascii"))
    digest.update(side.encode("ascii"))
    for value in (price, size, order_id, flags):
        digest.update(INT_STRUCT.pack(value))


def _hash_row(
    digest: Any,
    key: tuple[int, int, int, int, int],
    levels: tuple[int, ...],
) -> None:
    digest.update(KEY_STRUCT.pack(*key))
    for value in levels:
        digest.update(INT_STRUCT.pack(value))


def _hash_comparison(
    digest: Any,
    key: tuple[int, int, int, int, int],
    vendor: tuple[int, ...],
    reconstructed: tuple[int, ...],
) -> None:
    _hash_row(digest, key, vendor)
    for value in reconstructed:
        digest.update(INT_STRUCT.pack(value))


def _hash_key_with_marker(
    digest: Any,
    marker: bytes,
    key: tuple[int, int, int, int, int],
) -> None:
    digest.update(marker)
    digest.update(KEY_STRUCT.pack(*key))


def _artifact(path: Path) -> dict[str, Any]:
    return {
        "path": str(path.resolve()),
        "bytes": path.stat().st_size,
        "sha256": _sha256(path),
    }


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
        json.dump(value, handle, indent=2, sort_keys=True)
        handle.write("\n")
        temporary = Path(handle.name)
    temporary.replace(path)


if __name__ == "__main__":
    main()
