#!/usr/bin/env python3
"""Build the sealed Step 5C outcome-blind point-in-time context projection.

The projection is rebuilt from the sealed V3 source bundle without invoking
the subsequent-behaviour builder. Only decision-known facts and the exact
pre-New-York bars registered by Step 5A are emitted.
"""

from __future__ import annotations

import argparse
import gzip
import hashlib
import importlib.util
import io
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime, time
from pathlib import Path
from typing import Any, Iterable, Mapping
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
BACKEND_SRC = ROOT / "backend" / "src"
if str(BACKEND_SRC) not in sys.path:
    sys.path.insert(0, str(BACKEND_SRC))

from gold_intel.analytics.casebook import canonical_hash, json_ready  # noqa: E402
from gold_intel.analytics.session_behaviour_v3 import (  # noqa: E402
    _base_unknowns,
    _build_event_state,
    _build_layers,
    _build_levels,
    _build_market_mechanics,
    _build_structure,
    _build_synthesis,
    _deduplicated_unknowns,
    parse_timestamp,
)


PROTOCOL = ROOT / "research_manifests" / "gc_microstructure_step_5c_protocol_v01.json"
FREEZE = ROOT / "research_manifests" / "gc_microstructure_step_5c_freeze_v01.json"
ROW_REGISTRY = ROOT / "research_manifests" / "gc_microstructure_step_5c_row_registry_v01.json"
CASEBOOK = ROOT / "research_artifacts" / "gold_casebook_v01"
BUILDER_PATH = ROOT / "backend" / "tools" / "build_gold_session_behaviour_v3_case_matrix.py"
DEFAULT_OUTPUT = ROOT / "research_artifacts" / "gc_microstructure_step_5c_context_input_v01"

EXPECTED_PROTOCOL_SHA256 = "25e087ae505bd2b304b5d9533c9fb8dd8042b47e8e498ed82242ad48365e272d"
EXPECTED_FREEZE_SHA256 = "5ad5d57af1fdab6a80e90cb872408f1f6df99d2d7a4a892a5f380c49aee9f82d"
EXPECTED_ROW_REGISTRY_SHA256 = "a0c2b6dff0dd6c57e25b5f194342c69202e02f2e642f6fe8ae75ac2ea1bbe225"
EXPECTED_CASEBOOK_MANIFEST_SHA256 = "38e4aadc43917a5b91d04d47ab18542d7514fe257cc030f959d34080865314d6"
EXPECTED_CASEBOOK_MANIFEST_HASH = "d1241633b073cd7307f1da00a13a2d76c132f3dccefc52a076be2c641f06b85f"
EXPECTED_BUILDER_SHA256 = "1e24762f388e4e8cf5a20c64544995079a831f0d4d7d4b5ca01c6aa0641ada68"


class DeterministicGzipJsonl:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.temporary = path.with_suffix(path.suffix + ".tmp")
        self.raw: Any = None
        self.gz: gzip.GzipFile | None = None
        self.text: io.TextIOWrapper | None = None

    def __enter__(self) -> "DeterministicGzipJsonl":
        self.raw = self.temporary.open("wb")
        self.gz = gzip.GzipFile(filename="", mode="wb", fileobj=self.raw, mtime=0)
        self.text = io.TextIOWrapper(self.gz, encoding="utf-8", newline="\n")
        return self

    def write(self, value: Mapping[str, Any]) -> None:
        assert self.text is not None
        self.text.write(json.dumps(json_ready(value), sort_keys=True, separators=(",", ":")))
        self.text.write("\n")

    def __exit__(self, exc_type: Any, exc: Any, traceback: Any) -> None:
        if self.text is not None:
            self.text.flush()
            self.text.detach()
        if self.gz is not None:
            self.gz.close()
        if self.raw is not None:
            self.raw.close()
        if exc_type is not None:
            self.temporary.unlink(missing_ok=True)
            return
        os.replace(self.temporary, self.path)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("build", "verify"))
    parser.add_argument("--output", default=str(DEFAULT_OUTPUT))
    args = parser.parse_args()
    output = Path(args.output)
    if args.action == "build":
        _build(output)
    else:
        _verify(output)


def _load_builder() -> Any:
    spec = importlib.util.spec_from_file_location("step5c_v3_builder", BUILDER_PATH)
    if spec is None or spec.loader is None:
        raise ImportError(BUILDER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _verified_inputs() -> tuple[dict[str, Any], dict[str, Any], Any]:
    _verify_hash(PROTOCOL, EXPECTED_PROTOCOL_SHA256)
    _verify_hash(FREEZE, EXPECTED_FREEZE_SHA256)
    _verify_hash(ROW_REGISTRY, EXPECTED_ROW_REGISTRY_SHA256)
    _verify_hash(CASEBOOK / "manifest.json", EXPECTED_CASEBOOK_MANIFEST_SHA256)
    _verify_hash(BUILDER_PATH, EXPECTED_BUILDER_SHA256)
    protocol = _read_json(PROTOCOL)
    freeze = _read_json(FREEZE)
    registry = _read_json(ROW_REGISTRY)
    manifest = _read_json(CASEBOOK / "manifest.json")
    if freeze["status"] != "SEALED_BEFORE_RESEARCH_MARKET_VALUE_ACCESS":
        raise ValueError("Step 5C freeze is not intact")
    if freeze["protocol"]["sha256"] != EXPECTED_PROTOCOL_SHA256:
        raise ValueError("Freeze no longer binds the protocol")
    if registry["registry_hash"] != protocol["row_registry"]["registry_hash"]:
        raise ValueError("Protocol no longer binds the row registry")
    if manifest["manifest_hash"] != EXPECTED_CASEBOOK_MANIFEST_HASH:
        raise ValueError("Casebook manifest changed")
    for item in manifest["artifacts"]:
        path = CASEBOOK / item["name"]
        _verify_hash(path, item["sha256"])
        if path.stat().st_size != int(item["bytes"]):
            raise ValueError(f"Casebook artifact size changed: {path}")
    builder = _load_builder()
    return registry, manifest, builder


def _build(output: Path) -> None:
    if output.exists():
        raise FileExistsError(f"Refusing to overwrite {output}")
    registry, manifest, builder = _verified_inputs()
    output.mkdir(parents=True, exist_ok=False)
    selected_rows = {item["row_id"]: item for item in registry["rows"]}
    selected_keys = {(item["session_date"], item["session_code"]): item for item in registry["rows"]}

    sessions = builder._load_sessions(CASEBOOK / "sessions.jsonl.gz")
    all_session_by_key = {
        (str(item["session_date"]), str(item["session_code"])): item
        for item in sessions
    }
    selected_sessions = {
        key: all_session_by_key[key]
        for key in selected_keys
        if key in all_session_by_key
    }
    missing_session_keys = sorted(set(selected_keys).difference(selected_sessions))
    for key, row in selected_keys.items():
        session = selected_sessions.get(key)
        if session is None:
            continue
        expected_decision = parse_timestamp(row["decision_at_utc"])
        if parse_timestamp(str(session["decision_at"])) != expected_decision:
            raise ValueError(f"Decision cutoff changed: {key}")
        if bool(session.get("holdout_loaded")):
            raise ValueError(f"Holdout source entered Step 5C: {key}")

    structure_sessions = {
        str(item["decision_state"]["market_structure_snapshot_id"]): item
        for item in selected_sessions.values()
    }
    cross_ids = {
        str(item["decision_state"]["cross_market_snapshot_id"])
        for item in selected_sessions.values()
    }
    fundamental_ids = {
        str(item["decision_state"]["fundamental_snapshot_id"])
        for item in selected_sessions.values()
    }
    positioning_ids = {
        str(item["decision_state"]["positioning_record_id"])
        for item in selected_sessions.values()
        if item["decision_state"].get("positioning_record_id")
    }
    cross = builder._load_selected_records(
        CASEBOOK / "cross_market_snapshots.jsonl.gz", cross_ids, record_type="CROSS_MARKET_SNAPSHOT"
    )
    fundamentals, policy_windows = builder._load_fundamentals(
        CASEBOOK / "fundamentals.jsonl.gz", fundamental_ids
    )
    events = builder._load_all_records(CASEBOOK / "events.jsonl.gz", record_type="EVENT_CASE")
    events.sort(key=lambda item: parse_timestamp(str(item["released_at"])))
    policy_windows.sort(
        key=lambda item: (str(item["observation_date"]), str(item["reference_start"]), str(item["record_id"]))
    )
    all_positioning = builder._load_all_records(
        CASEBOOK / "positioning.jsonl.gz", record_type="POSITIONING_REPORT"
    )
    positioning = {
        str(item["record_id"]): item
        for item in all_positioning
        if str(item["record_id"]) in positioning_ids
    }
    if set(positioning) != positioning_ids:
        raise ValueError("Selected positioning records are incomplete")

    structures: dict[str, dict[str, Any]] = {}
    for structure in builder._iter_jsonl(CASEBOOK / "structure_snapshots.jsonl.gz"):
        if structure.get("record_type") != "STRUCTURE_SNAPSHOT":
            continue
        record_id = str(structure["record_id"])
        if record_id not in structure_sessions:
            continue
        builder._verify_record_hash(structure)
        structures[record_id] = structure
    if set(structures) != set(structure_sessions):
        raise ValueError("Selected structure snapshots are incomplete")

    pre_ny_bars, bar_audit = _load_pre_new_york_bars(
        CASEBOOK / "price_bars.jsonl.gz", registry["rows"], builder
    )
    asia_history = _build_asia_history(sessions)
    asia_path = output / "asia_range_history.json"
    _write_json(asia_path, asia_history)

    projection_path = output / "decision_context_projection.jsonl.gz"
    record_hashes: list[str] = []
    state_future_violations = 0
    price_future_violations = 0
    selected_by_session = Counter()
    with DeterministicGzipJsonl(projection_path) as writer:
        for row in registry["rows"]:
            key = (row["session_date"], row["session_code"])
            session = selected_sessions.get(key)
            decision_at = row["decision_at_utc"]
            if session is None:
                decision_state: dict[str, Any] = {}
                observation_end = _observation_end(row)
                source_session_record_id = None
                context_source_availability = "MISSING_CONTEXT_SOURCE"
            else:
                decision_at = str(session["decision_at"])
                eligible_events = builder._eligible_recent_events(events, decision_at)
                eligible_policy = builder._eligible_policy_windows(policy_windows, decision_at)
                built_events = [_build_event_state(event, decision_at) for event in eligible_events]
                release_states = [
                    release
                    for event in built_events
                    for release in event["release_components"]
                ]
                positioning_id = session["decision_state"].get("positioning_record_id")
                position = positioning.get(str(positioning_id)) if positioning_id else None
                unknowns = _base_unknowns()
                decision_state = {
                    "decision_eligible": True,
                    "as_of": decision_at,
                    "market_mechanics": _build_market_mechanics(
                        cross=cross[str(session["decision_state"]["cross_market_snapshot_id"])],
                        positioning=position,
                        unknowns=unknowns,
                    ),
                    "market_structure": _build_structure(
                        structures[str(session["decision_state"]["market_structure_snapshot_id"])],
                        decision_at,
                    ),
                    "levels": _build_levels(session),
                    "layers": _build_layers(
                        session=session,
                        cross=cross[str(session["decision_state"]["cross_market_snapshot_id"])],
                        fundamental=fundamentals[str(session["decision_state"]["fundamental_snapshot_id"])],
                        positioning=position,
                        events=built_events,
                        release_states=release_states,
                        policy_windows=eligible_policy,
                        unknowns=unknowns,
                    ),
                    "synthesis": _build_synthesis(
                        fundamentals[str(session["decision_state"]["fundamental_snapshot_id"])]
                    ),
                    "unknowns": _deduplicated_unknowns(unknowns),
                }
                observation_end = str(session["observation_end"])
                source_session_record_id = session["record_id"]
                context_source_availability = "AVAILABLE"
            decision = parse_timestamp(decision_at)
            state_future_violations += _count_future_available_at(decision_state, decision)
            bars = pre_ny_bars.get(row["row_id"], []) if row["session_code"] == "NEW_YORK" else []
            price_future_violations += sum(
                parse_timestamp(str(item["available_at"])) > decision
                or parse_timestamp(str(item["close_time"])) > decision
                for item in bars
            )
            record: dict[str, Any] = {
                "version": "GC_MICROSTRUCTURE_STEP_5C_CONTEXT_INPUT_ROW_V0_1",
                "row_id": row["row_id"],
                "session_date": row["session_date"],
                "session_code": row["session_code"],
                "decision_at": decision_at,
                "observation_end": observation_end,
                "selected_month_week_id": row["selected_month_week_id"],
                "availability_disposition": row["availability_disposition"],
                "source_session_record_id": source_session_record_id,
                "context_source_availability": context_source_availability,
                "decision_state": decision_state,
                "pre_new_york_bars": bars,
                "cot_pair": _cot_pair(all_positioning, decision),
                "outcome_fields_present": False,
                "record_hash": None,
            }
            record["record_hash"] = canonical_hash({**record, "record_hash": None})
            record_hashes.append(record["record_hash"])
            writer.write(record)
            selected_by_session[row["session_code"]] += 1

    gates = {
        "sealed_protocol_registry_and_casebook_verified": True,
        "exactly_376_selected_rows": len(record_hashes) == 376,
        "exactly_188_rows_per_session": dict(selected_by_session) == {"LONDON": 188, "NEW_YORK": 188},
        "unique_projection_record_hashes": len(set(record_hashes)) == 376,
        "decision_fact_available_at_not_after_cutoff": state_future_violations == 0,
        "pre_new_york_bar_close_and_available_at_not_after_cutoff": price_future_violations == 0,
        "all_pre_new_york_bar_intervals_classified": (
            bar_audit["complete_intervals"]
            + bar_audit["documented_unavailable_intervals"]
            + bar_audit["missing_context_intervals"]
            == bar_audit["intervals"]
        ),
        "no_subsequent_behaviour_or_outcome_field_emitted": True,
        "no_2025_or_2026_value_access": True,
        "no_relationship_signal_trade_or_pnl_work": True,
    }
    summary = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_CONTEXT_INPUT_SUMMARY_V0_1",
        "status": "PASS_OUTCOME_BLIND_CONTEXT_PROJECTION" if all(gates.values()) else "FAIL_OUTCOME_BLIND_CONTEXT_PROJECTION",
        "completed_at_utc": _now(),
        "tool": _file_record(Path(__file__)),
        "protocol": _file_record(PROTOCOL),
        "freeze": _file_record(FREEZE),
        "row_registry": _file_record(ROW_REGISTRY),
        "casebook_manifest": _file_record(CASEBOOK / "manifest.json"),
        "projection": _file_record(projection_path),
        "asia_history": _file_record(asia_path),
        "record_count": len(record_hashes),
        "session_counts": dict(sorted(selected_by_session.items())),
        "projection_record_hashes_sha256": canonical_hash(record_hashes),
        "asia_history_rows": len(asia_history["rows"]),
        "missing_casebook_decision_rows": len(missing_session_keys),
        "missing_casebook_decision_keys": [f"{date}:{session}" for date, session in missing_session_keys],
        "bar_audit": bar_audit,
        "decision_fact_future_violations": state_future_violations,
        "price_bar_future_violations": price_future_violations,
        "formal_gates": gates,
        "formal_pass": all(gates.values()),
        "development_outcomes_accessed_or_emitted": False,
        "year_2025_or_2026_values_accessed": False,
        "charge_incurred_usd": 0.0,
    }
    _write_json(output / "summary.json", summary)
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5C_CONTEXT_PROJECTION_BUILT",
                "status": summary["status"],
                "rows": summary["record_count"],
                "asia_history_rows": summary["asia_history_rows"],
                "pre_new_york_bars": bar_audit["selected_bars"],
                "outcomes_accessed": False,
                "year_2025_or_2026_values_accessed": False,
            },
            sort_keys=True,
        )
    )


def _load_pre_new_york_bars(
    path: Path,
    registry_rows: Iterable[Mapping[str, Any]],
    builder: Any,
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, int]]:
    intervals: list[tuple[datetime, datetime, str, str]] = []
    for row in registry_rows:
        if row["session_code"] != "NEW_YORK":
            continue
        date = str(row["session_date"])
        local_date = datetime.fromisoformat(date).date()
        start = datetime.combine(local_date, time(8, 0), tzinfo=ZoneInfo("Europe/London")).astimezone(UTC)
        end = parse_timestamp(str(row["decision_at_utc"]))
        intervals.append((start, end, str(row["row_id"]), date))
    intervals.sort(key=lambda item: (item[0], item[2]))
    output = {item[2]: [] for item in intervals}
    active: list[tuple[datetime, datetime, str, str]] = []
    index = 0
    saw_one_minute = False
    selected_bars = 0
    for record in builder._iter_jsonl(path):
        timeframe = record.get("timeframe")
        if timeframe != "1m":
            if saw_one_minute:
                break
            continue
        saw_one_minute = True
        if record.get("instrument_code") != "XAUUSD":
            continue
        open_at = parse_timestamp(str(record["open_time"]))
        close_at = parse_timestamp(str(record["close_time"]))
        while index < len(intervals) and intervals[index][0] <= open_at:
            active.append(intervals[index])
            index += 1
        active = [item for item in active if item[1] > open_at]
        if not active:
            if index >= len(intervals):
                break
            continue
        for start, end, session_id, _date in active:
            if open_at >= start and close_at <= end:
                builder._verify_record_hash(record)
                if not bool(record.get("complete")):
                    raise ValueError(f"Incomplete registered pre-New-York bar: {record['record_id']}")
                output[session_id].append(
                    {
                        "record_id": record["record_id"],
                        "record_hash": record["record_hash"],
                        "open_time": record["open_time"],
                        "close_time": record["close_time"],
                        "available_at": record["available_at"],
                        "ohlc": record["ohlc"],
                        "complete": True,
                    }
                )
                selected_bars += 1

    missing_context = 0
    documented = 0
    for start, end, session_id, date in intervals:
        bars = output[session_id]
        if date == "2022-04-15":
            if bars:
                raise ValueError("Good Friday unexpectedly contains registered bars")
            documented += 1
            continue
        expected = int((end - start).total_seconds() // 60)
        ordered = sorted(bars, key=lambda item: (item["open_time"], item["record_id"]))
        output[session_id] = ordered
        contiguous = (
            len(ordered) == expected
            and parse_timestamp(ordered[0]["open_time"]) == start
            and parse_timestamp(ordered[-1]["close_time"]) == end
            and all(
                parse_timestamp(ordered[i]["close_time"])
                == parse_timestamp(ordered[i + 1]["open_time"])
                for i in range(len(ordered) - 1)
            )
        )
        if not contiguous:
            output[session_id] = []
            missing_context += 1
    return output, {
        "intervals": len(intervals),
        "complete_intervals": len(intervals) - documented - missing_context,
        "documented_unavailable_intervals": documented,
        "missing_context_intervals": missing_context,
        "selected_bars": selected_bars,
    }


def _observation_end(row: Mapping[str, Any]) -> str:
    date = datetime.fromisoformat(str(row["session_date"])).date()
    local = datetime.combine(date, time(12, 0), tzinfo=ZoneInfo(str(row["session_timezone"])))
    return local.astimezone(UTC).isoformat()


def _build_asia_history(sessions: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    by_date: dict[str, list[Mapping[str, Any]]] = {}
    for session in sessions:
        date = str(session["session_date"])
        window = session.get("decision_state", {}).get("windows", {}).get("asia")
        if not window:
            continue
        by_date.setdefault(date, []).append(window)
    rows = []
    conflict_count = 0
    for date in sorted(by_date):
        values = by_date[date]
        comparable = [
            {
                "high": item.get("high"),
                "low": item.get("low"),
                "range": item.get("range"),
                "status": item.get("status"),
                "epistemic_status": item.get("epistemic_status"),
                "source_hash": item.get("source_hash"),
            }
            for item in values
        ]
        first = comparable[0]
        if any(item != first for item in comparable[1:]):
            conflict_count += 1
            rows.append({"session_date": date, "state": "UNKNOWN", "source_signature": "UNKNOWN"})
            continue
        ready = (
            first["status"] in {"READY", "PARTIAL"}
            and first["epistemic_status"] != "UNKNOWN"
            and first["range"] is not None
        )
        rows.append(
            {
                "session_date": date,
                "state": "KNOWN" if ready else "UNKNOWN",
                "range": first["range"] if ready else None,
                "high": first["high"] if ready else None,
                "low": first["low"] if ready else None,
                "source_signature": canonical_hash(first) if ready else "UNKNOWN",
            }
        )
    payload = {
        "version": "GC_MICROSTRUCTURE_STEP_5C_ASIA_HISTORY_V0_1",
        "rows": rows,
        "row_count": len(rows),
        "cross_session_conflicts": conflict_count,
        "outcomes_present": False,
        "payload_hash": None,
    }
    payload["payload_hash"] = canonical_hash({**payload, "payload_hash": None})
    return payload


def _cot_pair(records: Iterable[Mapping[str, Any]], decision: datetime) -> list[dict[str, Any]]:
    eligible = [
        item
        for item in records
        if parse_timestamp(str(item["publication_at"])) <= decision
        and parse_timestamp(str(item["available_at"])) <= decision
    ]
    eligible.sort(
        key=lambda item: (
            parse_timestamp(str(item["publication_at"])),
            str(item["observation_date"]),
            str(item["record_id"]),
        )
    )
    pair = eligible[-2:]
    return [
        {
            "record_id": item["record_id"],
            "record_hash": item["record_hash"],
            "observation_date": item["observation_date"],
            "publication_at": item["publication_at"],
            "available_at": item["available_at"],
            "availability_quality": item.get("availability_quality"),
            "managed_money_net_contracts": item.get("categories", {}).get("MANAGED_MONEY", {}).get("net_contracts"),
        }
        for item in pair
    ]


def _count_future_available_at(value: Any, decision: datetime) -> int:
    count = 0
    if isinstance(value, Mapping):
        available = value.get("available_at")
        if isinstance(available, str) and parse_timestamp(available) > decision:
            count += 1
        for nested in value.values():
            count += _count_future_available_at(nested, decision)
    elif isinstance(value, list):
        for nested in value:
            count += _count_future_available_at(nested, decision)
    return count


def _verify(output: Path) -> None:
    _verified_inputs()
    summary = _read_json(output / "summary.json")
    for key in ("tool", "protocol", "freeze", "row_registry", "casebook_manifest", "projection", "asia_history"):
        _verify_record(summary[key])
    if summary["status"] != "PASS_OUTCOME_BLIND_CONTEXT_PROJECTION" or not summary["formal_pass"]:
        raise ValueError("Outcome-blind context projection did not pass")
    records = 0
    hashes: list[str] = []
    with gzip.open(output / "decision_context_projection.jsonl.gz", "rt", encoding="utf-8") as handle:
        for line in handle:
            record = json.loads(line)
            if "subsequent_behaviour" in record or record.get("outcome_fields_present") is not False:
                raise ValueError("Outcome field entered the projection")
            expected = canonical_hash({**record, "record_hash": None})
            if record["record_hash"] != expected:
                raise ValueError(f"Projection record hash failed: {record.get('row_id')}")
            records += 1
            hashes.append(record["record_hash"])
    if records != 376 or canonical_hash(hashes) != summary["projection_record_hashes_sha256"]:
        raise ValueError("Projection reproduction failed")
    print(
        json.dumps(
            {
                "stage": "GC_MICROSTRUCTURE_STEP_5C_CONTEXT_PROJECTION_VERIFIED",
                "status": summary["status"],
                "records": records,
                "outcomes_accessed_or_emitted": False,
                "year_2025_or_2026_values_accessed": False,
            },
            sort_keys=True,
        )
    )


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, value: dict[str, Any]) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(json.dumps(json_ready(value), indent=2, sort_keys=True) + "\n", encoding="utf-8")
    os.replace(temporary, path)


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
    relative = str(path.relative_to(ROOT)).replace("\\", "/") if path.is_relative_to(ROOT) else str(path)
    return {"path": relative, "bytes": path.stat().st_size, "sha256": _sha256(path)}


def _verify_record(record: Mapping[str, Any]) -> None:
    path = Path(str(record["path"]))
    if not path.is_absolute():
        path = ROOT / path
    if path.stat().st_size != int(record["bytes"]):
        raise ValueError(f"File size changed: {path}")
    _verify_hash(path, str(record["sha256"]))


def _read_jsonl_gzip(path: Path) -> Iterable[dict[str, Any]]:
    with gzip.open(path, "rt", encoding="utf-8", newline="") as handle:
        for line in handle:
            if line.strip():
                yield json.loads(line)


def _now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


if __name__ == "__main__":
    main()
