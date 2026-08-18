#!/usr/bin/env python3
"""Diagnose only the frozen Step 3A crossed/locked boundary failures.

No price levels, directional features, signals, outcomes, or PnL are emitted.
The diagnostic records timestamps, action types, state classifications, and
whether heap-derived and direct-scan BBO classifications agree.
"""

from __future__ import annotations

import hashlib
import json
import tempfile
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pyarrow as pa
import pyarrow.parquet as pq

from reconstruct_gc_mbo_engineering_book import (
    F_LAST,
    LevelBookReplay,
    PROTOCOL_PATH,
    _canonical_hash,
    _sha256,
    load_verified_source,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = (
    REPO_ROOT
    / "research_artifacts"
    / "gc_microstructure_step_3a_boundary_diagnostic_v01.json"
)
COLUMNS = (
    "ts_recv",
    "action",
    "side",
    "price_fixed_1e9",
    "size",
    "order_id",
    "flags",
)


def main() -> None:
    protocol, parquet_path = load_verified_source(PROTOCOL_PATH)
    output = DEFAULT_OUTPUT
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite diagnostic: {output}")

    book = LevelBookReplay()
    total_records = 0
    boundary_index = 0
    anomaly_counts: Counter[str] = Counter()
    anomaly_action_counts: Counter[str] = Counter()
    anomaly_hour_counts: Counter[str] = Counter()
    heap_direct_disagreements = 0
    episodes: list[dict[str, Any]] = []
    active_episode: dict[str, Any] | None = None

    parquet = pq.ParquetFile(parquet_path)
    for batch in parquet.iter_batches(batch_size=100_000, columns=list(COLUMNS)):
        arrays = {
            name: batch.column(batch.schema.get_field_index(name))
            for name in COLUMNS
        }
        recv = arrays["ts_recv"].cast(pa.int64()).to_numpy(zero_copy_only=False)
        numeric = {
            name: arrays[name].to_numpy(zero_copy_only=False)
            for name in ("price_fixed_1e9", "size", "order_id", "flags")
        }
        actions = arrays["action"].to_pylist()
        sides = arrays["side"].to_pylist()
        for index in range(batch.num_rows):
            total_records += 1
            action = str(actions[index])
            side = str(sides[index])
            flags = int(numeric["flags"][index])
            book.apply(
                ordinal=total_records,
                action=action,
                side=side,
                order_id=int(numeric["order_id"][index]),
                price=int(numeric["price_fixed_1e9"][index]),
                size=int(numeric["size"][index]),
                flags=flags,
            )
            if not flags & F_LAST:
                continue
            boundary_index += 1
            heap_bid = book.best_price("B")
            heap_ask = book.best_price("A")
            direct_bid = max(book.levels["B"], default=None)
            direct_ask = min(book.levels["A"], default=None)
            heap_state = _state(heap_bid, heap_ask)
            direct_state = _state(direct_bid, direct_ask)
            if heap_state != direct_state:
                heap_direct_disagreements += 1
            anomalous = heap_state in {"LOCKED", "CROSSED"}
            timestamp_ns = int(recv[index])
            if anomalous:
                anomaly_counts[heap_state] += 1
                anomaly_action_counts[action] += 1
                hour = datetime.fromtimestamp(
                    timestamp_ns / 1_000_000_000,
                    tz=UTC,
                ).strftime("%Y-%m-%dT%H:00Z")
                anomaly_hour_counts[hour] += 1
                if active_episode is None:
                    active_episode = {
                        "first_record_ordinal": total_records,
                        "last_record_ordinal": total_records,
                        "first_boundary_index": boundary_index,
                        "last_boundary_index": boundary_index,
                        "first_receive_timestamp": _iso(timestamp_ns),
                        "last_receive_timestamp": _iso(timestamp_ns),
                        "first_receive_timestamp_ns": timestamp_ns,
                        "last_receive_timestamp_ns": timestamp_ns,
                        "boundary_count": 0,
                        "state_counts": Counter(),
                        "action_counts": Counter(),
                        "onset_action": action,
                        "heap_direct_classification_match": True,
                    }
                active_episode["last_record_ordinal"] = total_records
                active_episode["last_boundary_index"] = boundary_index
                active_episode["last_receive_timestamp"] = _iso(timestamp_ns)
                active_episode["last_receive_timestamp_ns"] = timestamp_ns
                active_episode["boundary_count"] += 1
                active_episode["state_counts"][heap_state] += 1
                active_episode["action_counts"][action] += 1
                active_episode["heap_direct_classification_match"] = (
                    active_episode["heap_direct_classification_match"]
                    and heap_state == direct_state
                )
            elif active_episode is not None:
                active_episode["resolution_action"] = action
                active_episode["duration_ns"] = (
                    int(active_episode["last_receive_timestamp_ns"])
                    - int(active_episode["first_receive_timestamp_ns"])
                )
                active_episode["state_counts"] = dict(
                    sorted(active_episode["state_counts"].items())
                )
                active_episode["action_counts"] = dict(
                    sorted(active_episode["action_counts"].items())
                )
                active_episode.pop("first_receive_timestamp_ns")
                active_episode.pop("last_receive_timestamp_ns")
                episodes.append(active_episode)
                active_episode = None

    if active_episode is not None:
        active_episode["resolution_action"] = None
        active_episode["duration_ns"] = (
            int(active_episode["last_receive_timestamp_ns"])
            - int(active_episode["first_receive_timestamp_ns"])
        )
        active_episode["state_counts"] = dict(
            sorted(active_episode["state_counts"].items())
        )
        active_episode["action_counts"] = dict(
            sorted(active_episode["action_counts"].items())
        )
        active_episode.pop("first_receive_timestamp_ns")
        active_episode.pop("last_receive_timestamp_ns")
        episodes.append(active_episode)

    diagnostic: dict[str, Any] = {
        "diagnostic_version": "GC_MBO_STEP_3A_BOUNDARY_DIAGNOSTIC_V0_1",
        "created_at": datetime.now(UTC).isoformat(),
        "scope": "TECHNICAL_LOCKED_AND_CROSSED_BOUNDARY_DIAGNOSIS_ONLY",
        "protocol_sha256": _sha256(PROTOCOL_PATH),
        "source_parquet_sha256": _sha256(parquet_path),
        "source_records_processed": total_records,
        "event_boundaries_examined": boundary_index,
        "anomaly_counts": dict(sorted(anomaly_counts.items())),
        "anomaly_action_counts": dict(sorted(anomaly_action_counts.items())),
        "anomaly_hour_counts": dict(sorted(anomaly_hour_counts.items())),
        "anomaly_episode_count": len(episodes),
        "episodes": episodes,
        "heap_direct_classification_disagreements": heap_direct_disagreements,
        "final_invariant_violation_counts": dict(sorted(book.validate().items())),
        "technical_replay_processed_book_values": True,
        "price_values_reported": False,
        "directional_statistics_calculated": False,
        "signals_calculated": False,
        "outcomes_accessed": False,
        "execution_optimized": False,
        "pnl_calculated": False,
    }
    diagnostic["diagnostic_hash"] = _canonical_hash(diagnostic)
    _write_json_atomic(output, diagnostic)
    print(
        json.dumps(
            {
                "stage": "GC_MBO_STEP_3A_BOUNDARY_DIAGNOSTIC_COMPLETE",
                "source_records_processed": total_records,
                "event_boundaries_examined": boundary_index,
                "anomaly_counts": diagnostic["anomaly_counts"],
                "anomaly_episode_count": len(episodes),
                "anomaly_hour_counts": diagnostic["anomaly_hour_counts"],
                "heap_direct_classification_disagreements": (
                    heap_direct_disagreements
                ),
                "final_invariant_violations": sum(
                    diagnostic["final_invariant_violation_counts"].values()
                ),
                "diagnostic_hash": diagnostic["diagnostic_hash"],
                "price_values_reported": False,
                "directional_statistics_calculated": False,
                "outcomes_accessed": False,
            },
            sort_keys=True,
        )
    )


def _state(bid: int | None, ask: int | None) -> str:
    if bid is None or ask is None:
        return "EMPTY_SIDE"
    if bid > ask:
        return "CROSSED"
    if bid == ask:
        return "LOCKED"
    return "UNCROSSED"


def _iso(value_ns: int) -> str:
    seconds, nanoseconds = divmod(value_ns, 1_000_000_000)
    base = datetime.fromtimestamp(seconds, tz=UTC)
    return f"{base.strftime('%Y-%m-%dT%H:%M:%S')}.{nanoseconds:09d}Z"


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
