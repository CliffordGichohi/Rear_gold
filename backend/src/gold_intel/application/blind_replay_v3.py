from __future__ import annotations

import gzip
import json
import math
import os
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from gold_intel.api.blind_replay_v3_schemas import ReplayV3OrderType
from gold_intel.application.blind_replay import (
    GENESIS_HASH,
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
    canonical_bytes,
    canonical_hash,
    sha256_file,
)
from gold_intel.config import get_settings

PROTOCOL = "GOLD_ANNOTATED_TRADINGVIEW_STYLE_REPLAY_V3_PROTOCOL_1_0"
EVENT_VERSION = "GOLD_ANNOTATED_REPLAY_V3_EVENT_1_0"
TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
TERMINAL_ORDER_STATES = {"CANCELLED", "EXPIRED", "RESOLVED"}
LIVE_ORDER_STATES = {"PENDING_ORDER", "ACTIVE_POSITION"}


def parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ReplayIntegrityError("Replay timestamp is not timezone-aware")
    return parsed.astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


class AnnotatedReplayV3Service:
    """Practice-only chronological replay and deterministic broker journal."""

    def __init__(self, artifact_path: Path, ledger_path: Path | None = None) -> None:
        self.artifact_path = artifact_path.resolve()
        self.primary_path = self.artifact_path / "practice_streams_v3_1.primary.jsonl.gz"
        self.reference_path = self.artifact_path / "practice_streams_v3_1.reference.jsonl.gz"
        self.certification_path = (
            self.artifact_path / "practice_stream_materialization_certification_v3_1.json"
        )
        self.registry_path = self.artifact_path / "practice_registry.private.json"
        self.execution_path = self.artifact_path / "execution_policy.json"
        self.ledger_policy_path = self.artifact_path / "ledger_policy.json"
        configured = ledger_path or get_settings().blind_replay_v3_ledger_path
        self.event_ledger_path = configured.resolve()
        self._lock = threading.RLock()
        self._rows, self._registry, self._execution = self._load_and_verify_inputs()
        self._by_alias = {row["case_alias"]: row for row in self._rows}

    @staticmethod
    def _read_gzip(path: Path) -> list[dict[str, Any]]:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def _load_and_verify_inputs(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, Any], dict[str, Any]]:
        required = (
            self.primary_path,
            self.reference_path,
            self.certification_path,
            self.registry_path,
            self.execution_path,
            self.ledger_policy_path,
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise ReplayIntegrityError(f"Certified V3 replay inputs are missing: {missing}")
        certification = json.loads(self.certification_path.read_text(encoding="utf-8"))
        if certification.get("verdict") != "PASS_V3_PRACTICE_STREAM_COVERAGE_AMENDMENT_A":
            raise ReplayIntegrityError("V3 corrected practice stream did not pass")
        if not all(certification.get("gates", {}).values()):
            raise ReplayIntegrityError("At least one V3 materialization gate failed")
        primary_sha = sha256_file(self.primary_path)
        reference_sha = sha256_file(self.reference_path)
        if primary_sha != certification.get("primary_sha256"):
            raise ReplayIntegrityError("V3 primary practice stream hash differs")
        if reference_sha != certification.get("reference_sha256"):
            raise ReplayIntegrityError("V3 reference practice stream hash differs")
        if primary_sha != reference_sha:
            raise ReplayIntegrityError("V3 independently produced stream bytes differ")
        primary = self._read_gzip(self.primary_path)
        reference = self._read_gzip(self.reference_path)
        if primary != reference:
            raise ReplayIntegrityError("V3 independently produced stream values differ")
        if canonical_hash(primary) != certification.get("complete_stream_set_sha256"):
            raise ReplayIntegrityError("V3 complete stream-set hash differs")
        aliases = [f"V3-P-{index:03d}" for index in range(1, 21)]
        if [row.get("case_alias") for row in primary] != aliases:
            raise ReplayIntegrityError("V3 practice population differs")
        for index, row in enumerate(primary, start=1):
            if row.get("mode") != "PRACTICE" or row.get("research_credit") != "ZERO_PRACTICE_ONLY":
                raise ReplayIntegrityError("V3 stream contains non-practice research data")
            if int(row.get("mode_sequence", 0)) != index:
                raise ReplayIntegrityError("V3 practice order differs")
            submitted = row.get("stream_sha256")
            body = {key: value for key, value in row.items() if key != "stream_sha256"}
            if submitted != canonical_hash(body):
                raise ReplayIntegrityError(
                    f"V3 stream record hash differs: {row.get('case_alias')}"
                )
            if set(row.get("timeframes", {})) != set(TIMEFRAMES):
                raise ReplayIntegrityError("V3 timeframe registry differs")
            for timeframe, bars in row["timeframes"].items():
                keys = [(bar["close_at"], bar["bar_id"]) for bar in bars]
                if keys != sorted(keys) or len({bar["bar_id"] for bar in bars}) != len(bars):
                    raise ReplayIntegrityError(
                        f"V3 bar identities differ: {row['case_alias']} {timeframe}"
                    )
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if (
            registry.get("case_count") != 20
            or registry.get("primary_collection_state") != "CLOSED_NOT_MATERIALIZED"
        ):
            raise ReplayIntegrityError("V3 public practice registry differs")
        if registry.get("primary_collection_year") != certification.get("primary_collection_year"):
            raise ReplayIntegrityError("V3 closed collection-year identity differs")
        execution = json.loads(self.execution_path.read_text(encoding="utf-8"))
        if execution.get("version") != "GOLD_ANNOTATED_REPLAY_V3_EXECUTION_POLICY_1_0":
            raise ReplayIntegrityError("V3 execution policy differs")
        ledger = json.loads(self.ledger_policy_path.read_text(encoding="utf-8"))
        if ledger.get("version") != "GOLD_ANNOTATED_REPLAY_V3_LEDGER_POLICY_1_0":
            raise ReplayIntegrityError("V3 ledger policy differs")
        if ledger.get("one_year_collection_ledger") != "NOT_CREATED_UNTIL_SEPARATE_AUTHORIZATION":
            raise ReplayIntegrityError("V3 one-year collection was unexpectedly opened")
        return primary, registry, execution

    def _read_events(self) -> list[dict[str, Any]]:
        if not self.event_ledger_path.exists():
            return []
        events: list[dict[str, Any]] = []
        prior = GENESIS_HASH
        idempotency_keys: set[str] = set()
        with self.event_ledger_path.open("r", encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayIntegrityError("V3 event ledger contains invalid JSON") from exc
                if event.get("version") != EVENT_VERSION:
                    raise ReplayIntegrityError("V3 event ledger version differs")
                if int(event.get("ledger_sequence", 0)) != sequence:
                    raise ReplayIntegrityError("V3 event ledger sequence is discontinuous")
                if event.get("prior_record_sha256") != prior:
                    raise ReplayIntegrityError("V3 event ledger hash chain is broken")
                body = {key: value for key, value in event.items() if key != "record_sha256"}
                if event.get("record_sha256") != canonical_hash(body):
                    raise ReplayIntegrityError("V3 event ledger record hash is invalid")
                key = str(event.get("idempotency_key", ""))
                if not key or key in idempotency_keys:
                    raise ReplayIntegrityError("V3 event ledger idempotency identity is invalid")
                if event.get("case_alias") not in self._by_alias:
                    raise ReplayIntegrityError("V3 event ledger references an unknown practice day")
                idempotency_keys.add(key)
                prior = str(event["record_sha256"])
                events.append(event)
        self._derive_state(events)
        return events

    @staticmethod
    def _head(events: list[dict[str, Any]]) -> str:
        return str(events[-1]["record_sha256"]) if events else GENESIS_HASH

    def _append_batch(
        self,
        existing: list[dict[str, Any]],
        descriptors: list[dict[str, Any]],
    ) -> list[dict[str, Any]]:
        if not descriptors:
            return existing
        records: list[dict[str, Any]] = []
        prior = self._head(existing)
        sequence = len(existing)
        for descriptor in descriptors:
            sequence += 1
            record = {
                "version": EVENT_VERSION,
                "ledger_sequence": sequence,
                **descriptor,
                "prior_record_sha256": prior,
            }
            record["record_sha256"] = canonical_hash(record)
            prior = record["record_sha256"]
            records.append(record)
        self.event_ledger_path.parent.mkdir(parents=True, exist_ok=True)
        payload = b"".join(canonical_bytes(record) + b"\n" for record in records)
        with self.event_ledger_path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        updated = [*existing, *records]
        self._derive_state(updated)
        return updated

    def _derive_state(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        cursors = {alias: row["start_inclusive"] for alias, row in self._by_alias.items()}
        completed: set[str] = set()
        current_alias: str | None = None
        orders: dict[str, dict[str, Any]] = {}
        order_sequence: list[str] = []
        for event in events:
            alias = str(event["case_alias"])
            if alias in completed:
                raise ReplayIntegrityError("V3 ledger mutates an already completed practice day")
            if current_alias is None:
                current_alias = alias
            if alias != current_alias:
                raise ReplayIntegrityError("V3 ledger interleaves practice days")
            cursor = parse_time(cursors[alias])
            event_cursor = parse_time(str(event["cursor_at"]))
            start = parse_time(self._by_alias[alias]["start_inclusive"])
            end = parse_time(self._by_alias[alias]["end_exclusive"])
            if not start <= event_cursor <= end:
                raise ReplayIntegrityError("V3 ledger timestamp is outside its practice day")
            event_type = str(event["event_type"])
            data = event.get("data", {})
            if event_type in {"CURSOR_ADVANCED", "INTERVAL_SKIPPED"}:
                if parse_time(str(data.get("from_cursor_at"))) != cursor:
                    raise ReplayIntegrityError("V3 cursor ledger is not contiguous")
                target = parse_time(str(data.get("to_cursor_at")))
                if not cursor < target <= end or target != event_cursor:
                    raise ReplayIntegrityError("V3 cursor event is invalid")
                cursors[alias] = iso(target)
            elif event_cursor > parse_time(cursors[alias]):
                raise ReplayIntegrityError("V3 trade event occurs after the durable cursor")

            if event_type == "ORDER_SUBMITTED":
                order = deepcopy(data["order"])
                order_id = str(order["order_id"])
                if order_id in orders or any(
                    item["state"] in LIVE_ORDER_STATES for item in orders.values()
                ):
                    raise ReplayIntegrityError("V3 ledger violates one-live-order policy")
                order["state"] = "PENDING_ORDER"
                orders[order_id] = order
                order_sequence.append(order_id)
            elif event_type == "ORDER_AMENDED":
                order_id = str(data["order_id"])
                order = orders.get(order_id)
                if not order or order["state"] != "PENDING_ORDER":
                    raise ReplayIntegrityError("V3 amendment does not reference a pending order")
                if data.get("previous_sha256") != canonical_hash(order):
                    raise ReplayIntegrityError("V3 amendment previous-state hash differs")
                original_annotation = order["annotation"]
                original_direction = order["direction"]
                order.update(deepcopy(data["new_values"]))
                if (
                    order["annotation"] != original_annotation
                    or order["direction"] != original_direction
                ):
                    raise ReplayIntegrityError("V3 amendment mutated immutable submitted fields")
            elif event_type == "ORDER_CANCELLED":
                order_id = str(data["order_id"])
                order = orders.get(order_id)
                if not order or order["state"] != "PENDING_ORDER":
                    raise ReplayIntegrityError("V3 cancellation does not reference a pending order")
                order["state"] = str(data["terminal_state"])
                if order["state"] not in {"CANCELLED", "EXPIRED"}:
                    raise ReplayIntegrityError("V3 pending-order terminal state differs")
                order["cancelled_at"] = event["cursor_at"]
            elif event_type == "ORDER_FILLED":
                order_id = str(data["order_id"])
                order = orders.get(order_id)
                if not order or order["state"] != "PENDING_ORDER":
                    raise ReplayIntegrityError("V3 fill does not reference a pending order")
                order["state"] = "ACTIVE_POSITION"
                order["fill"] = deepcopy(data["fill"])
                order["immutable_active_sha256"] = canonical_hash(
                    {
                        key: order[key]
                        for key in (
                            "direction",
                            "order_type",
                            "entry",
                            "stop",
                            "target",
                            "risk_usd",
                            "annotation",
                        )
                    }
                )
            elif event_type == "POSITION_CLOSED":
                order_id = str(data["order_id"])
                order = orders.get(order_id)
                if not order or order["state"] != "ACTIVE_POSITION":
                    raise ReplayIntegrityError("V3 close does not reference an active position")
                immutable = canonical_hash(
                    {
                        key: order[key]
                        for key in (
                            "direction",
                            "order_type",
                            "entry",
                            "stop",
                            "target",
                            "risk_usd",
                            "annotation",
                        )
                    }
                )
                if immutable != order["immutable_active_sha256"]:
                    raise ReplayIntegrityError("V3 active geometry or reasoning was mutated")
                order["state"] = "RESOLVED"
                order["resolution"] = deepcopy(data["resolution"])
            elif event_type == "PRACTICE_DAY_COMPLETED":
                if parse_time(cursors[alias]) != end:
                    raise ReplayIntegrityError("V3 practice day completed before its end cursor")
                if any(item["state"] in LIVE_ORDER_STATES for item in orders.values()):
                    raise ReplayIntegrityError("V3 practice day completed with a live order")
                completed.add(alias)
                current_alias = None
            elif event_type not in {"CURSOR_ADVANCED", "INTERVAL_SKIPPED"}:
                raise ReplayIntegrityError(f"Unknown V3 event type: {event_type}")
        live = next(
            (
                orders[order_id]
                for order_id in reversed(order_sequence)
                if orders[order_id]["state"] in LIVE_ORDER_STATES
            ),
            None,
        )
        return {
            "cursors": cursors,
            "completed": completed,
            "current_alias": current_alias,
            "orders": orders,
            "order_sequence": order_sequence,
            "live_order": live,
        }

    def _status_from(self, events: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        cases = []
        for registry_case in self._registry["cases"]:
            alias = registry_case["case_alias"]
            cases.append(
                {
                    "case_alias": alias,
                    "trading_date_utc": registry_case["trading_date_utc"],
                    "completed": alias in state["completed"],
                    "active": alias == state["current_alias"],
                    "research_credit": "ZERO_PRACTICE_ONLY",
                }
            )
        completed = len(state["completed"])
        return {
            "protocol": PROTOCOL,
            "ready": True,
            "phase": "PRACTICE" if completed < 20 else "PRACTICE_COMPLETE_COLLECTION_CLOSED",
            "practice_completed": completed,
            "practice_total": 20,
            "current_case_alias": state["current_alias"],
            "event_ledger_head_sha256": self._head(events),
            "collection_year": int(self._registry["primary_collection_year"]),
            "collection_state": "CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE",
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
            "research_credit": "ZERO_PRACTICE_ONLY",
            "practice_cases": cases,
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            events = self._read_events()
            state = self._derive_state(events)
            return self._status_from(events, state)

    @staticmethod
    def _latest(rows: list[dict[str, Any]], cursor: datetime) -> dict[str, Any] | None:
        eligible = [row for row in rows if parse_time(str(row["available_at"])) <= cursor]
        return deepcopy(eligible[-1]) if eligible else None

    @staticmethod
    def _available_items(value: Any, cursor: datetime) -> Any:
        if not isinstance(value, list):
            return deepcopy(value)
        output = []
        for item in value:
            if not isinstance(item, dict):
                output.append(deepcopy(item))
                continue
            available = next(
                (
                    item[key]
                    for key in (
                        "available_at",
                        "forecast_available_at",
                        "release_available_at",
                        "revision_available_at",
                    )
                    if item.get(key)
                ),
                None,
            )
            if available is None or parse_time(str(available)) <= cursor:
                output.append(deepcopy(item))
        return output

    def _point_in_time_context(self, row: dict[str, Any], cursor: datetime) -> dict[str, Any]:
        timeline = row["context_timeline"]
        fundamental = self._latest(timeline["fundamentals"], cursor)
        structure = self._latest(timeline["structure"], cursor)
        cross_market = self._latest(timeline["cross_market"], cursor)
        positioning = self._latest(timeline["positioning"], cursor)
        sessions = [
            deepcopy(item)
            for item in timeline["sessions"]
            if parse_time(str(item["available_at"])) <= cursor
        ]
        events: list[dict[str, Any]] = []
        for source in timeline["events"]:
            scheduled = parse_time(str(source.get("scheduled_at") or source["released_at"]))
            released = parse_time(str(source["event_available_at"]))
            if cursor < released:
                if not source.get("schedule_verified_for_pre_event_use"):
                    continue
                events.append(
                    {
                        "record_id": source["record_id"],
                        "event_code": source["event_code"],
                        "name": source["name"],
                        "event_type": source["event_type"],
                        "importance": source["importance"],
                        "epistemic_status": "OBSERVED",
                        "state": "SCHEDULED",
                        "scheduled_at": iso(scheduled),
                        "forecasts": self._available_items(source.get("forecasts", []), cursor),
                    }
                )
                continue
            events.append(
                {
                    "record_id": source["record_id"],
                    "event_code": source["event_code"],
                    "name": source["name"],
                    "event_type": source["event_type"],
                    "importance": source["importance"],
                    "epistemic_status": "OBSERVED",
                    "state": "RELEASED",
                    "scheduled_at": source.get("scheduled_at"),
                    "released_at": source["released_at"],
                    "forecasts": self._available_items(source.get("forecasts", []), cursor),
                    "releases": self._available_items(source.get("releases", []), cursor),
                    "raw_surprises": self._available_items(source.get("raw_surprises", []), cursor),
                    "standardized_surprises": self._available_items(
                        source.get("standardized_surprises", []), cursor
                    ),
                }
            )
        engine = (fundamental or {}).get("engine_state", {})
        summary = {
            "bias_label": engine.get("bias_label", "UNKNOWN"),
            "directional_score": engine.get("directional_score"),
            "confidence": engine.get("confidence"),
            "regime_label": engine.get("regime_label", "UNKNOWN"),
            "dominant_driver": engine.get("dominant_driver", "UNKNOWN"),
            "main_contradiction": engine.get("main_contradiction", "UNKNOWN"),
            "event_risk": engine.get("event_risk", "UNKNOWN"),
            "components": engine.get("components", []),
            "epistemic_status": (fundamental or {}).get("epistemic_status", "UNKNOWN"),
            "available_at": (fundamental or {}).get("available_at"),
        }
        return {
            "fundamental_summary": summary,
            "fundamental": fundamental,
            "structure": structure,
            "cross_market": cross_market,
            "positioning": positioning,
            "events": events,
            "sessions": sessions,
            "display_policy": {
                "point_in_time_only": True,
                "recommendations_present": False,
                "future_reactions_present": False,
                "classification_labels": ["OBSERVED", "CALCULATED", "INFERRED", "UNKNOWN"],
            },
        }

    def _snapshot(
        self, row: dict[str, Any], cursor_at: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        cursor = parse_time(cursor_at)
        charts = {
            timeframe: [
                deepcopy(bar)
                for bar in row["timeframes"][timeframe]
                if parse_time(str(bar["close_at"])) <= cursor
                and parse_time(str(bar["available_at"])) <= cursor
            ]
            for timeframe in TIMEFRAMES
        }
        context = self._point_in_time_context(row, cursor)
        visibility = {
            timeframe: {
                "count": len(bars),
                "terminal_bar_id": bars[-1]["bar_id"] if bars else None,
                "sha256": canonical_hash(bars),
            }
            for timeframe, bars in charts.items()
        }
        live = deepcopy(state["live_order"])
        visible_body = {
            "case_alias": row["case_alias"],
            "cursor_at": iso(cursor),
            "charts": {timeframe: item["sha256"] for timeframe, item in visibility.items()},
            "context_sha256": canonical_hash(context),
            "live_order_sha256": canonical_hash(live),
        }
        return {
            "version": "GOLD_ANNOTATED_REPLAY_V3_SNAPSHOT_1_0",
            "case_alias": row["case_alias"],
            "mode": "PRACTICE",
            "mode_sequence": row["mode_sequence"],
            "trading_date_utc": row["trading_date_utc"],
            "start_at": row["start_inclusive"],
            "end_at": row["end_exclusive"],
            "cursor_at": iso(cursor),
            "selected_timeframe_default": "15m",
            "charts": charts,
            "visible_timeframes": visibility,
            "context": context,
            "live_order": live,
            "order_history": [
                deepcopy(state["orders"][order_id])
                for order_id in state["order_sequence"]
                if state["orders"][order_id]["case_alias"] == row["case_alias"]
            ],
            "visible_state_sha256": canonical_hash(visible_body),
            "execution": {
                "maximum_planned_risk_usd": self._execution["maximum_planned_risk_usd"],
                "account_equity_usd": self._execution["account_equity_usd"],
                "one_live_order_or_position": True,
                "post_fill_geometry_mutable": False,
                "same_bar_ambiguity": "STOP_FIRST",
            },
            "display_policy": {
                "actual_timestamps": True,
                "future_values_in_response": False,
                "one_way_cursor": True,
                "camera_navigation_is_not_cursor_rewind": True,
                "practice_zero_credit": True,
                "collection_closed": True,
                "calendar_2025_2026_locked": True,
            },
        }

    def case(self, requested_alias: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            events = self._read_events()
            state = self._derive_state(events)
            if len(state["completed"]) == 20:
                return None
            active = state["current_alias"]
            alias = active or requested_alias
            if alias is None:
                alias = next(
                    row["case_alias"]
                    for row in self._rows
                    if row["case_alias"] not in state["completed"]
                )
            if alias not in self._by_alias or alias in state["completed"]:
                raise ReplaySequenceError("The requested V3 practice day is unavailable")
            if active is not None and alias != active:
                raise ReplaySequenceError(f"Complete the active practice day first: {active}")
            snapshot = self._snapshot(self._by_alias[alias], state["cursors"][alias], state)
            return {"case": snapshot, "progress": self._status_from(events, state)}

    @staticmethod
    def _validate_key(value: str) -> None:
        if not value or len(value) > 128:
            raise ReplayConflictError("Idempotency-Key must contain 1 through 128 characters")

    @staticmethod
    def _idempotent_event(
        events: list[dict[str, Any]], key: str, submission_sha: str
    ) -> dict[str, Any] | None:
        event = next((item for item in events if item["idempotency_key"] == key), None)
        if event and event.get("submission_sha256") != submission_sha:
            raise ReplayConflictError("Idempotency-Key was already used for another payload")
        return event

    def _validate_current(
        self, request: dict[str, Any], state: dict[str, Any]
    ) -> tuple[dict[str, Any], datetime]:
        alias = str(request["case_alias"])
        if alias not in self._by_alias or alias in state["completed"]:
            raise ReplaySequenceError("The requested V3 practice day is unavailable")
        if state["current_alias"] is not None and state["current_alias"] != alias:
            raise ReplaySequenceError(
                f"Complete the active practice day first: {state['current_alias']}"
            )
        current = parse_time(state["cursors"][alias])
        expected = parse_time(str(request["expected_cursor_at"]))
        if expected != current:
            raise ReplayConflictError(f"Stale replay cursor; current cursor is {iso(current)}")
        return self._by_alias[alias], current

    def _response(
        self,
        events: list[dict[str, Any]],
        event_sha: str,
        *,
        idempotent: bool,
        preferred_alias: str | None,
    ) -> dict[str, Any]:
        state = self._derive_state(events)
        case_payload = None
        alias = state["current_alias"] or preferred_alias
        if alias and alias not in state["completed"]:
            case_payload = self._snapshot(self._by_alias[alias], state["cursors"][alias], state)
        return {
            "event_sha256": event_sha,
            "idempotent_replay": idempotent,
            "case": case_payload,
            "progress": self._status_from(events, state),
        }

    def _base_descriptor(
        self,
        *,
        event_type: str,
        alias: str,
        cursor_at: datetime,
        idempotency_key: str,
        submission_sha: str,
        recorded_at: str,
        data: dict[str, Any],
    ) -> dict[str, Any]:
        return {
            "event_type": event_type,
            "case_alias": alias,
            "cursor_at": iso(cursor_at),
            "idempotency_key": idempotency_key,
            "submission_sha256": submission_sha,
            "recorded_at": recorded_at,
            "data": data,
        }

    @staticmethod
    def _spread(bar: dict[str, Any]) -> float:
        value = bar.get("spread_price")
        return float(value) if value is not None and float(value) >= 0 else 0.20

    def _fill_for(self, order: dict[str, Any], bar: dict[str, Any]) -> dict[str, Any] | None:
        effective = parse_time(order["effective_at"])
        if parse_time(bar["open_at"]) < effective:
            return None
        direction = order["direction"]
        order_type = order["order_type"]
        entry = float(order["entry"])
        half_spread = self._spread(bar) / 2
        slip = float(self._execution["market_and_stop_slippage_price"])
        if order_type == ReplayV3OrderType.MARKET.value:
            raw = float(bar["open"])
            actual = raw + half_spread + slip if direction == "LONG" else raw - half_spread - slip
            return {
                "fill_at": bar["open_at"],
                "raw_price": raw,
                "actual_price": round(actual, 8),
                "spread_price": self._spread(bar),
                "slippage_price": slip,
                "rule": "MARKET_NEXT_OBSERVED_M1_OPEN",
            }
        if order_type == ReplayV3OrderType.LIMIT.value:
            touched = (
                float(bar["low"]) <= entry - 0.01
                if direction == "LONG"
                else float(bar["high"]) >= entry + 0.01
            )
            if not touched:
                return None
            return {
                "fill_at": bar["close_at"],
                "raw_price": entry,
                "actual_price": entry,
                "spread_price": self._spread(bar),
                "slippage_price": 0.0,
                "rule": "LIMIT_EXCEEDED_BY_ONE_TICK",
            }
        if direction == "LONG" and float(bar["high"]) >= entry:
            raw = max(entry, float(bar["open"]))
            return {
                "fill_at": bar["close_at"],
                "raw_price": raw,
                "actual_price": round(raw + half_spread + slip, 8),
                "spread_price": self._spread(bar),
                "slippage_price": slip,
                "rule": "BUY_STOP_FIRST_TOUCH_OR_GAP",
            }
        if direction == "SHORT" and float(bar["low"]) <= entry:
            raw = min(entry, float(bar["open"]))
            return {
                "fill_at": bar["close_at"],
                "raw_price": raw,
                "actual_price": round(raw - half_spread - slip, 8),
                "spread_price": self._spread(bar),
                "slippage_price": slip,
                "rule": "SELL_STOP_FIRST_TOUCH_OR_GAP",
            }
        return None

    def _resolution_for(self, order: dict[str, Any], bar: dict[str, Any]) -> dict[str, Any] | None:
        direction = order["direction"]
        stop = float(order["stop"])
        target = float(order["target"])
        if direction == "LONG":
            stop_touched = float(bar["low"]) <= stop
            target_touched = float(bar["high"]) >= target
        else:
            stop_touched = float(bar["high"]) >= stop
            target_touched = float(bar["low"]) <= target
        if not stop_touched and not target_touched:
            return None
        if stop_touched:
            half_spread = self._spread(bar) / 2
            slip = float(self._execution["market_and_stop_slippage_price"])
            if direction == "LONG":
                raw = min(stop, float(bar["open"]))
                actual = raw - half_spread - slip
            else:
                raw = max(stop, float(bar["open"]))
                actual = raw + half_spread + slip
            return {
                "state": "STOPPED",
                "exit_at": bar["close_at"],
                "raw_exit_price": raw,
                "actual_exit_price": round(actual, 8),
                "spread_price": self._spread(bar),
                "slippage_price": slip,
                "same_bar_policy": "STOP_FIRST",
            }
        return {
            "state": "TARGET_HIT",
            "exit_at": bar["close_at"],
            "raw_exit_price": target,
            "actual_exit_price": target,
            "spread_price": self._spread(bar),
            "slippage_price": 0.0,
            "same_bar_policy": "STOP_FIRST",
        }

    def _broker_descriptors(
        self,
        *,
        row: dict[str, Any],
        state: dict[str, Any],
        from_cursor: datetime,
        to_cursor: datetime,
        idempotency_key: str,
        submission_sha: str,
        recorded_at: str,
    ) -> list[dict[str, Any]]:
        live = deepcopy(state["live_order"])
        if not live:
            return []
        bars = [
            bar
            for bar in row["timeframes"]["1m"]
            if from_cursor < parse_time(bar["close_at"]) <= to_cursor
            and parse_time(bar["available_at"]) <= to_cursor
        ]
        descriptors: list[dict[str, Any]] = []
        for bar_index, bar in enumerate(bars):
            if live["state"] == "PENDING_ORDER":
                if parse_time(live["expiry_at"]) <= parse_time(bar["open_at"]):
                    descriptors.append(
                        self._base_descriptor(
                            event_type="ORDER_CANCELLED",
                            alias=row["case_alias"],
                            cursor_at=to_cursor,
                            idempotency_key=f"{idempotency_key}:expiry",
                            submission_sha=submission_sha,
                            recorded_at=recorded_at,
                            data={
                                "order_id": live["order_id"],
                                "terminal_state": "EXPIRED",
                                "reason": "FROZEN_ORDER_EXPIRY",
                            },
                        )
                    )
                    live["state"] = "EXPIRED"
                    break
                fill = self._fill_for(live, bar)
                if fill is None:
                    continue
                descriptors.append(
                    self._base_descriptor(
                        event_type="ORDER_FILLED",
                        alias=row["case_alias"],
                        cursor_at=to_cursor,
                        idempotency_key=f"{idempotency_key}:fill:{bar_index}",
                        submission_sha=submission_sha,
                        recorded_at=recorded_at,
                        data={"order_id": live["order_id"], "fill": fill},
                    )
                )
                live["state"] = "ACTIVE_POSITION"
                live["fill"] = fill
            if live["state"] == "ACTIVE_POSITION":
                resolution = self._resolution_for(live, bar)
                if resolution:
                    descriptors.append(
                        self._base_descriptor(
                            event_type="POSITION_CLOSED",
                            alias=row["case_alias"],
                            cursor_at=to_cursor,
                            idempotency_key=f"{idempotency_key}:close:{bar_index}",
                            submission_sha=submission_sha,
                            recorded_at=recorded_at,
                            data={"order_id": live["order_id"], "resolution": resolution},
                        )
                    )
                    live["state"] = "RESOLVED"
                    break
        end = parse_time(row["end_exclusive"])
        if live["state"] == "PENDING_ORDER" and parse_time(live["expiry_at"]) <= to_cursor:
            descriptors.append(
                self._base_descriptor(
                    event_type="ORDER_CANCELLED",
                    alias=row["case_alias"],
                    cursor_at=to_cursor,
                    idempotency_key=f"{idempotency_key}:expiry-at-cursor",
                    submission_sha=submission_sha,
                    recorded_at=recorded_at,
                    data={
                        "order_id": live["order_id"],
                        "terminal_state": "EXPIRED",
                        "reason": "FROZEN_ORDER_EXPIRY",
                    },
                )
            )
            live["state"] = "EXPIRED"
        if to_cursor == end and live["state"] == "PENDING_ORDER":
            descriptors.append(
                self._base_descriptor(
                    event_type="ORDER_CANCELLED",
                    alias=row["case_alias"],
                    cursor_at=to_cursor,
                    idempotency_key=f"{idempotency_key}:day-expiry",
                    submission_sha=submission_sha,
                    recorded_at=recorded_at,
                    data={
                        "order_id": live["order_id"],
                        "terminal_state": "EXPIRED",
                        "reason": "UTC_TRADING_DAY_END",
                    },
                )
            )
            live["state"] = "EXPIRED"
        if to_cursor == end and live["state"] == "ACTIVE_POSITION":
            visible = [bar for bar in row["timeframes"]["1m"] if parse_time(bar["close_at"]) <= end]
            if not visible:
                raise ReplayIntegrityError("V3 day has no M1 close for time exit")
            bar = visible[-1]
            half_spread = self._spread(bar) / 2
            slip = float(self._execution["market_and_stop_slippage_price"])
            raw = float(bar["close"])
            actual = (
                raw - half_spread - slip
                if live["direction"] == "LONG"
                else raw + half_spread + slip
            )
            resolution = {
                "state": "TIME_EXIT",
                "exit_at": bar["close_at"],
                "raw_exit_price": raw,
                "actual_exit_price": round(actual, 8),
                "spread_price": self._spread(bar),
                "slippage_price": slip,
                "same_bar_policy": "STOP_FIRST",
            }
            descriptors.append(
                self._base_descriptor(
                    event_type="POSITION_CLOSED",
                    alias=row["case_alias"],
                    cursor_at=to_cursor,
                    idempotency_key=f"{idempotency_key}:time-exit",
                    submission_sha=submission_sha,
                    recorded_at=recorded_at,
                    data={"order_id": live["order_id"], "resolution": resolution},
                )
            )
        return descriptors

    def advance(
        self, *, request: dict[str, Any], idempotency_key: str, recorded_at: str
    ) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        with self._lock:
            events = self._read_events()
            submission_sha = canonical_hash(request)
            existing = self._idempotent_event(events, idempotency_key, submission_sha)
            if existing:
                return self._response(
                    events,
                    existing["record_sha256"],
                    idempotent=True,
                    preferred_alias=request["case_alias"],
                )
            state = self._derive_state(events)
            row, current = self._validate_current(request, state)
            end = parse_time(row["end_exclusive"])
            target = min(current + timedelta(minutes=int(request["increment_minutes"])), end)
            if target <= current:
                raise ReplaySequenceError("The V3 practice cursor is already at day end")
            descriptor = self._base_descriptor(
                event_type="CURSOR_ADVANCED",
                alias=row["case_alias"],
                cursor_at=target,
                idempotency_key=idempotency_key,
                submission_sha=submission_sha,
                recorded_at=recorded_at,
                data={
                    "from_cursor_at": iso(current),
                    "to_cursor_at": iso(target),
                    "requested_increment_minutes": request["increment_minutes"],
                    "actual_increment_minutes": int((target - current).total_seconds() // 60),
                    "selected_timeframe": request["selected_timeframe"],
                    "observation_mode": "OBSERVED_IN_REAL_TIME",
                },
            )
            broker = self._broker_descriptors(
                row=row,
                state=state,
                from_cursor=current,
                to_cursor=target,
                idempotency_key=idempotency_key,
                submission_sha=submission_sha,
                recorded_at=recorded_at,
            )
            descriptors = [descriptor, *broker]
            if target == end:
                descriptors.append(
                    self._base_descriptor(
                        event_type="PRACTICE_DAY_COMPLETED",
                        alias=row["case_alias"],
                        cursor_at=target,
                        idempotency_key=f"{idempotency_key}:day-complete",
                        submission_sha=submission_sha,
                        recorded_at=recorded_at,
                        data={"disposition": "ZERO_CREDIT_PRACTICE_COMPLETE"},
                    )
                )
            updated = self._append_batch(events, descriptors)
            return self._response(
                updated,
                updated[len(events)]["record_sha256"],
                idempotent=False,
                preferred_alias=row["case_alias"],
            )

    def skip(
        self, *, request: dict[str, Any], idempotency_key: str, recorded_at: str
    ) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        with self._lock:
            events = self._read_events()
            submission_sha = canonical_hash(request)
            existing = self._idempotent_event(events, idempotency_key, submission_sha)
            if existing:
                return self._response(
                    events,
                    existing["record_sha256"],
                    idempotent=True,
                    preferred_alias=request["case_alias"],
                )
            state = self._derive_state(events)
            row, current = self._validate_current(request, state)
            if state["live_order"]:
                raise ReplayConflictError(
                    "Skipped intervals are allowed only while flat with no pending order"
                )
            target = parse_time(request["target_cursor_at"])
            end = parse_time(row["end_exclusive"])
            if not current < target <= end:
                raise ReplaySequenceError(
                    "Skip target must be later than the cursor and within the practice day"
                )
            descriptors = [
                self._base_descriptor(
                    event_type="INTERVAL_SKIPPED",
                    alias=row["case_alias"],
                    cursor_at=target,
                    idempotency_key=idempotency_key,
                    submission_sha=submission_sha,
                    recorded_at=recorded_at,
                    data={
                        "from_cursor_at": iso(current),
                        "to_cursor_at": iso(target),
                        "skipped_minutes": int((target - current).total_seconds() // 60),
                        "reason": request["reason"],
                        "selected_timeframe": request["selected_timeframe"],
                        "observation_mode": "REVEALED_BUT_NOT_OBSERVED_IN_REAL_TIME",
                    },
                )
            ]
            if target == end:
                descriptors.append(
                    self._base_descriptor(
                        event_type="PRACTICE_DAY_COMPLETED",
                        alias=row["case_alias"],
                        cursor_at=target,
                        idempotency_key=f"{idempotency_key}:day-complete",
                        submission_sha=submission_sha,
                        recorded_at=recorded_at,
                        data={"disposition": "ZERO_CREDIT_PRACTICE_COMPLETE_AFTER_SKIP"},
                    )
                )
            updated = self._append_batch(events, descriptors)
            return self._response(
                updated,
                updated[len(events)]["record_sha256"],
                idempotent=False,
                preferred_alias=row["case_alias"],
            )

    def _validate_snapshot_and_drawings(
        self, request: dict[str, Any], row: dict[str, Any], state: dict[str, Any]
    ) -> dict[str, Any]:
        snapshot = self._snapshot(row, state["cursors"][row["case_alias"]], state)
        if request["client_visible_state_sha256"] != snapshot["visible_state_sha256"]:
            raise ReplayConflictError("The submitted visible-state hash is stale")
        cursor = parse_time(snapshot["cursor_at"])
        start = min(
            parse_time(bar["close_at"]) for bars in row["timeframes"].values() for bar in bars
        )
        for drawing in request.get("drawings", []):
            if parse_time(drawing["created_at_cursor"]) > cursor:
                raise ReplayConflictError("A drawing was created after the current replay cursor")
            for anchor in drawing["anchors"]:
                anchor_at = parse_time(anchor["anchor_at"])
                if anchor_at > cursor:
                    raise ReplayConflictError("A drawing anchor references an unrevealed timestamp")
                if anchor_at < start:
                    raise ReplayConflictError(
                        "A drawing anchor precedes the certified chart history"
                    )
        return snapshot

    @staticmethod
    def _geometry(direction: str, entry: float, stop: float, target: float) -> None:
        if direction == "LONG" and not stop < entry < target:
            raise ReplayConflictError("LONG requires stop < entry < target")
        if direction == "SHORT" and not target < entry < stop:
            raise ReplayConflictError("SHORT requires target < entry < stop")

    def submit_order(
        self, *, request: dict[str, Any], idempotency_key: str, recorded_at: str
    ) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        with self._lock:
            events = self._read_events()
            submission_sha = canonical_hash(request)
            existing = self._idempotent_event(events, idempotency_key, submission_sha)
            if existing:
                return self._response(
                    events,
                    existing["record_sha256"],
                    idempotent=True,
                    preferred_alias=request["case_alias"],
                )
            state = self._derive_state(events)
            row, cursor = self._validate_current(request, state)
            if state["live_order"]:
                raise ReplayConflictError(
                    "Only one pending order or active gold position is permitted"
                )
            snapshot = self._validate_snapshot_and_drawings(request, row, state)
            entry, stop, target = (float(request[key]) for key in ("entry", "stop", "target"))
            direction = str(request["direction"])
            self._geometry(direction, entry, stop, target)
            quantity = math.floor(
                float(self._execution["maximum_planned_risk_usd"]) / abs(entry - stop)
            )
            if quantity < int(self._execution["minimum_quantity_ounces"]):
                raise ReplayConflictError(
                    "The selected stop is too wide for one whole ounce under the $50 risk cap"
                )
            planned_risk = round(quantity * abs(entry - stop), 8)
            end = parse_time(row["end_exclusive"])
            expiry = parse_time(request["expiry_at"]) if request.get("expiry_at") else end
            if not cursor < expiry <= end:
                raise ReplayConflictError(
                    "Order expiry must be after the cursor and no later than practice-day end"
                )
            order_id = f"{row['case_alias']}-O-{len(state['order_sequence']) + 1:04d}-{canonical_hash(idempotency_key)[:8]}"
            order = {
                "order_id": order_id,
                "case_alias": row["case_alias"],
                "submitted_at": iso(cursor),
                "effective_at": iso(
                    cursor + timedelta(minutes=int(self._execution["latency_minutes"]))
                ),
                "direction": direction,
                "order_type": str(request["order_type"]),
                "entry": entry,
                "stop": stop,
                "target": target,
                "expiry_at": iso(expiry),
                "quantity_ounces": quantity,
                "risk_usd": planned_risk,
                "risk_cap_usd": float(self._execution["maximum_planned_risk_usd"]),
                "selected_timeframe": request["selected_timeframe"],
                "visible_state_sha256": snapshot["visible_state_sha256"],
                "point_in_time_context_sha256": canonical_hash(snapshot["context"]),
                "drawings": deepcopy(request["drawings"]),
                "annotation": deepcopy(request["annotation"]),
                "research_credit": "ZERO_PRACTICE_ONLY",
            }
            descriptor = self._base_descriptor(
                event_type="ORDER_SUBMITTED",
                alias=row["case_alias"],
                cursor_at=cursor,
                idempotency_key=idempotency_key,
                submission_sha=submission_sha,
                recorded_at=recorded_at,
                data={"order": order},
            )
            updated = self._append_batch(events, [descriptor])
            return self._response(
                updated,
                updated[-1]["record_sha256"],
                idempotent=False,
                preferred_alias=row["case_alias"],
            )

    def amend_order(
        self,
        *,
        order_id: str,
        request: dict[str, Any],
        idempotency_key: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        with self._lock:
            events = self._read_events()
            submission_sha = canonical_hash({"order_id": order_id, **request})
            existing = self._idempotent_event(events, idempotency_key, submission_sha)
            if existing:
                return self._response(
                    events,
                    existing["record_sha256"],
                    idempotent=True,
                    preferred_alias=request["case_alias"],
                )
            state = self._derive_state(events)
            row, cursor = self._validate_current(request, state)
            order = state["orders"].get(order_id)
            if not order or order["state"] != "PENDING_ORDER":
                raise ReplayConflictError(
                    "Only a still-pending order may be amended; active geometry is immutable"
                )
            self._validate_snapshot_and_drawings(request, row, state)
            entry, stop, target = (float(request[key]) for key in ("entry", "stop", "target"))
            self._geometry(order["direction"], entry, stop, target)
            quantity = math.floor(
                float(self._execution["maximum_planned_risk_usd"]) / abs(entry - stop)
            )
            if quantity < int(self._execution["minimum_quantity_ounces"]):
                raise ReplayConflictError(
                    "The amended stop is too wide for one whole ounce under the $50 risk cap"
                )
            end = parse_time(row["end_exclusive"])
            expiry = parse_time(request["expiry_at"]) if request.get("expiry_at") else end
            if not cursor < expiry <= end:
                raise ReplayConflictError(
                    "Amended expiry must be after the cursor and no later than day end"
                )
            new_values = {
                "order_type": str(request["order_type"]),
                "entry": entry,
                "stop": stop,
                "target": target,
                "expiry_at": iso(expiry),
                "quantity_ounces": quantity,
                "risk_usd": round(quantity * abs(entry - stop), 8),
                "drawings": deepcopy(request["drawings"]),
                "visible_state_sha256": request["client_visible_state_sha256"],
            }
            descriptor = self._base_descriptor(
                event_type="ORDER_AMENDED",
                alias=row["case_alias"],
                cursor_at=cursor,
                idempotency_key=idempotency_key,
                submission_sha=submission_sha,
                recorded_at=recorded_at,
                data={
                    "order_id": order_id,
                    "previous_sha256": canonical_hash(order),
                    "new_values": new_values,
                    "reason": request.get("reason"),
                },
            )
            updated = self._append_batch(events, [descriptor])
            return self._response(
                updated,
                updated[-1]["record_sha256"],
                idempotent=False,
                preferred_alias=row["case_alias"],
            )

    def cancel_order(
        self,
        *,
        order_id: str,
        request: dict[str, Any],
        idempotency_key: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        with self._lock:
            events = self._read_events()
            submission_sha = canonical_hash({"order_id": order_id, **request})
            existing = self._idempotent_event(events, idempotency_key, submission_sha)
            if existing:
                return self._response(
                    events,
                    existing["record_sha256"],
                    idempotent=True,
                    preferred_alias=request["case_alias"],
                )
            state = self._derive_state(events)
            row, cursor = self._validate_current(request, state)
            order = state["orders"].get(order_id)
            if not order or order["state"] != "PENDING_ORDER":
                raise ReplayConflictError("Only a still-pending order may be cancelled")
            self._validate_snapshot_and_drawings({**request, "drawings": []}, row, state)
            descriptor = self._base_descriptor(
                event_type="ORDER_CANCELLED",
                alias=row["case_alias"],
                cursor_at=cursor,
                idempotency_key=idempotency_key,
                submission_sha=submission_sha,
                recorded_at=recorded_at,
                data={
                    "order_id": order_id,
                    "terminal_state": "CANCELLED",
                    "reason": request.get("reason"),
                },
            )
            updated = self._append_batch(events, [descriptor])
            return self._response(
                updated,
                updated[-1]["record_sha256"],
                idempotent=False,
                preferred_alias=row["case_alias"],
            )

    def manual_close(
        self,
        *,
        order_id: str,
        request: dict[str, Any],
        idempotency_key: str,
        recorded_at: str,
    ) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        with self._lock:
            events = self._read_events()
            submission_sha = canonical_hash({"order_id": order_id, **request})
            existing = self._idempotent_event(events, idempotency_key, submission_sha)
            if existing:
                return self._response(
                    events,
                    existing["record_sha256"],
                    idempotent=True,
                    preferred_alias=request["case_alias"],
                )
            state = self._derive_state(events)
            row, cursor = self._validate_current(request, state)
            order = state["orders"].get(order_id)
            if not order or order["state"] != "ACTIVE_POSITION":
                raise ReplayConflictError("Only an active position may be closed manually")
            snapshot = self._validate_snapshot_and_drawings({**request, "drawings": []}, row, state)
            bars = snapshot["charts"]["1m"]
            if not bars:
                raise ReplayConflictError("No visible M1 price is available for a manual close")
            bar = bars[-1]
            half_spread = self._spread(bar) / 2
            slip = float(self._execution["market_and_stop_slippage_price"])
            raw = float(bar["close"])
            actual = (
                raw - half_spread - slip
                if order["direction"] == "LONG"
                else raw + half_spread + slip
            )
            resolution = {
                "state": "MANUAL_CLOSE",
                "exit_at": iso(cursor),
                "raw_exit_price": raw,
                "actual_exit_price": round(actual, 8),
                "spread_price": self._spread(bar),
                "slippage_price": slip,
                "reason": request["reason"],
                "original_geometry_preserved": True,
            }
            descriptor = self._base_descriptor(
                event_type="POSITION_CLOSED",
                alias=row["case_alias"],
                cursor_at=cursor,
                idempotency_key=idempotency_key,
                submission_sha=submission_sha,
                recorded_at=recorded_at,
                data={"order_id": order_id, "resolution": resolution},
            )
            updated = self._append_batch(events, [descriptor])
            return self._response(
                updated,
                updated[-1]["record_sha256"],
                idempotent=False,
                preferred_alias=row["case_alias"],
            )


@lru_cache(maxsize=1)
def get_annotated_replay_v3_service() -> AnnotatedReplayV3Service:
    settings = get_settings()
    return AnnotatedReplayV3Service(
        settings.blind_replay_v3_artifact_path,
        ledger_path=settings.blind_replay_v3_ledger_path,
    )
