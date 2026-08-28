from __future__ import annotations

import gzip
import hashlib
import json
import math
import os
import threading
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Any

from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
)
from gold_intel.config import get_settings

PROTOCOL = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_AUDIT_V1_PROTOCOL_1_0"
VISIBLE_EVENT_VERSION = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_VISIBLE_EVENT_1_0"
OUTCOME_EVENT_VERSION = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_OUTCOME_EVENT_1_0"
SNAPSHOT_VERSION = "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_SNAPSHOT_1_0"
TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
GENESIS = "0" * 64
HUMAN_LEDGER_SHA256 = "7639d3609b904a2bd7f92c6df5a596cecf148a91d4853282a6d5a17e68d193d6"


def parse_time(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def iso(value: datetime) -> str:
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class CodexOperatorReplayService:
    def __init__(
        self,
        artifact_path: Path,
        visible_ledger_path: Path,
        outcome_ledger_path: Path,
        human_ledger_path: Path,
        *,
        expected_case_count: int = 249,
        expected_alias_prefix: str = "CBR-2022",
        expected_calendar_year: int = 2022,
        expected_human_ledger_sha256: str = HUMAN_LEDGER_SHA256,
    ) -> None:
        self.artifact_path = artifact_path.resolve()
        self.visible_ledger_path = visible_ledger_path.resolve()
        self.outcome_ledger_path = outcome_ledger_path.resolve()
        self.human_ledger_path = human_ledger_path.resolve()
        self.expected_case_count = expected_case_count
        self.expected_alias_prefix = expected_alias_prefix
        self.expected_calendar_year = expected_calendar_year
        self.expected_human_ledger_sha256 = expected_human_ledger_sha256
        self.certification_path = self.artifact_path / "stream_materialization_certification.json"
        self.registry_path = self.artifact_path / "population_registry.private.json"
        self.decision_policy_path = self.artifact_path / "decision_policy.json"
        self.execution_policy_path = self.artifact_path / "execution_policy.json"
        self.ledger_policy_path = self.artifact_path / "ledger_policy.json"
        self._lock = threading.RLock()
        self._registry, self._execution, self._case_files = self._load_and_verify_inputs()
        self._cases = {row["case_alias"]: row for row in self._registry["cases"]}

    def _load_and_verify_inputs(self) -> tuple[dict[str, Any], dict[str, Any], dict[str, dict[str, Any]]]:
        required = (
            self.certification_path,
            self.registry_path,
            self.decision_policy_path,
            self.execution_policy_path,
            self.ledger_policy_path,
            self.human_ledger_path,
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise ReplayIntegrityError(f"Codex replay inputs are missing: {missing}")
        if sha256_file(self.human_ledger_path) != self.expected_human_ledger_sha256:
            raise ReplayIntegrityError("The preserved human V3 ledger differs")
        certification = json.loads(self.certification_path.read_text(encoding="utf-8"))
        if certification.get("verdict") != "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION":
            raise ReplayIntegrityError("Codex private streams are not certified")
        if not all(certification.get("gates", {}).values()):
            raise ReplayIntegrityError("At least one Codex stream gate failed")
        if certification.get("case_count") != self.expected_case_count:
            raise ReplayIntegrityError("Codex stream certification case count differs")
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if registry.get("case_count") != self.expected_case_count or registry.get("outcomes") != "LOCKED_UNTIL_COMPLETE_POPULATION":
            raise ReplayIntegrityError("Codex population registry differs")
        if registry.get("population_sha256") != certification.get("population_sha256"):
            raise ReplayIntegrityError("Codex population hash differs")
        aliases = [f"{self.expected_alias_prefix}-{index:03d}" for index in range(1, self.expected_case_count + 1)]
        if [row.get("case_alias") for row in registry["cases"]] != aliases:
            raise ReplayIntegrityError("Codex case identities or ordering differ")
        if any(not str(row.get("trading_date_utc", "")).startswith(f"{self.expected_calendar_year:04d}-") for row in registry["cases"]):
            raise ReplayIntegrityError("Codex case population contains an unexpected calendar year")
        execution = json.loads(self.execution_policy_path.read_text(encoding="utf-8"))
        if execution.get("version") != "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_EXECUTION_POLICY_1_0":
            raise ReplayIntegrityError("Codex execution policy differs")
        decision = json.loads(self.decision_policy_path.read_text(encoding="utf-8"))
        if decision.get("version") != "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_DECISION_POLICY_1_0":
            raise ReplayIntegrityError("Codex decision policy differs")
        ledger = json.loads(self.ledger_policy_path.read_text(encoding="utf-8"))
        if ledger.get("version") != "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_LEDGER_POLICY_1_0":
            raise ReplayIntegrityError("Codex ledger policy differs")
        case_files: dict[str, dict[str, Any]] = {}
        for item in certification.get("case_files", []):
            alias = str(item.get("case_alias"))
            if alias in case_files or not item.get("bytes_exact"):
                raise ReplayIntegrityError("Codex case-file certification differs")
            primary = item["primary"]
            reference = item["reference"]
            for file_item in (primary, reference):
                path = Path(file_item["path"])
                if not path.is_absolute():
                    path = (self.artifact_path.parents[1] / path).resolve()
                if not path.is_file() or path.stat().st_size != file_item["bytes"] or sha256_file(path) != file_item["sha256"]:
                    raise ReplayIntegrityError(f"Certified private stream differs: {file_item['path']}")
            case_files[alias] = item
        if sorted(case_files) != sorted(aliases):
            raise ReplayIntegrityError("Codex certified case-file population differs")
        return registry, execution, case_files

    def _resolved_path(self, item: dict[str, Any]) -> Path:
        path = Path(item["path"])
        if path.is_absolute():
            return path
        return (self.artifact_path.parents[1] / path).resolve()

    def _load_case(self, alias: str) -> dict[str, Any]:
        item = self._case_files[alias]["primary"]
        path = self._resolved_path(item)
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            row = json.loads(handle.readline())
            if handle.readline():
                raise ReplayIntegrityError(f"Private stream has multiple rows: {alias}")
        submitted = row.pop("stream_sha256", None)
        if submitted != item["stream_sha256"] or canonical_hash(row) != submitted:
            raise ReplayIntegrityError(f"Private stream record hash differs: {alias}")
        row["stream_sha256"] = submitted
        if row.get("case_alias") != alias or row.get("mode") != "CODEX_BLIND":
            raise ReplayIntegrityError(f"Private stream identity differs: {alias}")
        for timeframe in TIMEFRAMES:
            bars = row["timeframes"].get(timeframe)
            if not isinstance(bars, list):
                raise ReplayIntegrityError(f"Private stream timeframe is absent: {alias} {timeframe}")
            if bars != sorted(bars, key=lambda bar: (bar["close_at"], bar["bar_id"])):
                raise ReplayIntegrityError(f"Private stream bars are unordered: {alias} {timeframe}")
        return row

    @staticmethod
    def _read_chain(path: Path, version: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        output: list[dict[str, Any]] = []
        prior = GENESIS
        seen_keys: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, start=1):
                try:
                    event = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayIntegrityError(f"Invalid append-only ledger JSON: {path}") from exc
                if event.get("version") != version or event.get("ledger_sequence") != sequence:
                    raise ReplayIntegrityError(f"Append-only ledger sequence/version differs: {path}")
                if event.get("prior_record_sha256") != prior:
                    raise ReplayIntegrityError(f"Append-only ledger chain is broken: {path}")
                submitted = event.get("record_sha256")
                body = {key: value for key, value in event.items() if key != "record_sha256"}
                if canonical_hash(body) != submitted:
                    raise ReplayIntegrityError(f"Append-only ledger record hash differs: {path}")
                key = str(event.get("idempotency_key"))
                if key in seen_keys:
                    raise ReplayIntegrityError(f"Duplicate idempotency key: {path}")
                seen_keys.add(key)
                prior = str(submitted)
                output.append(event)
        return output

    @staticmethod
    def _append(path: Path, version: str, descriptor: dict[str, Any]) -> dict[str, Any]:
        events = CodexOperatorReplayService._read_chain(path, version)
        event = {
            "version": version,
            "ledger_sequence": len(events) + 1,
            **descriptor,
            "prior_record_sha256": events[-1]["record_sha256"] if events else GENESIS,
        }
        event["record_sha256"] = canonical_hash(event)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = canonical_bytes(event) + b"\n"
        with path.open("ab") as handle:
            handle.write(payload)
            handle.flush()
            os.fsync(handle.fileno())
        return event

    @staticmethod
    def _append_once(path: Path, version: str, descriptor: dict[str, Any]) -> dict[str, Any]:
        events = CodexOperatorReplayService._read_chain(path, version)
        key = str(descriptor["idempotency_key"])
        existing = next((event for event in events if event["idempotency_key"] == key), None)
        if existing is not None:
            if existing.get("submission_sha256") != descriptor.get("submission_sha256"):
                raise ReplayIntegrityError(f"Outcome idempotency key was reused with another payload: {key}")
            return existing
        return CodexOperatorReplayService._append(path, version, descriptor)

    def _derive_visible_state(self, events: list[dict[str, Any]]) -> dict[str, Any]:
        cursors = {alias: case["start_inclusive"] for alias, case in self._cases.items()}
        completed: set[str] = set()
        inspected: dict[str, list[str]] = {alias: [] for alias in self._cases}
        decisions: dict[str, dict[str, Any]] = {}
        for event in events:
            alias = str(event["case_alias"])
            if alias not in self._cases:
                raise ReplayIntegrityError("Visible ledger references an unknown Codex case")
            event_type = str(event["event_type"])
            data = event.get("data", {})
            if alias in completed:
                raise ReplayIntegrityError("Visible ledger mutates a terminal Codex case")
            if event_type == "CURSOR_ADVANCED":
                previous = parse_time(cursors[alias])
                if parse_time(str(data["from_cursor_at"])) != previous:
                    raise ReplayIntegrityError("Codex cursor ledger is discontinuous")
                target = parse_time(str(data["to_cursor_at"]))
                if target <= previous or target > parse_time(self._cases[alias]["end_exclusive"]):
                    raise ReplayIntegrityError("Codex cursor event is invalid")
                cursors[alias] = iso(target)
                timeframe = str(data["selected_timeframe"])
                if timeframe not in inspected[alias]:
                    inspected[alias].append(timeframe)
            elif event_type == "TIMEFRAME_INSPECTED":
                if parse_time(str(event["cursor_at"])) != parse_time(cursors[alias]):
                    raise ReplayIntegrityError("Codex timeframe inspection is not at the durable cursor")
                timeframe = str(data["selected_timeframe"])
                if timeframe not in inspected[alias]:
                    inspected[alias].append(timeframe)
            elif event_type in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
                if alias in decisions or parse_time(str(event["cursor_at"])) != parse_time(cursors[alias]):
                    raise ReplayIntegrityError("Codex decision identity/cursor differs")
                decisions[alias] = deepcopy(data["decision"])
            elif event_type == "CASE_TERMINAL_HIDDEN":
                if alias not in decisions or data.get("decision_sha256") != canonical_hash(decisions[alias]):
                    raise ReplayIntegrityError("Codex terminal marker does not bind its decision")
                completed.add(alias)
            else:
                raise ReplayIntegrityError(f"Unknown Codex visible event type: {event_type}")
        incomplete = [alias for alias in self._cases if alias not in completed]
        return {
            "cursors": cursors,
            "completed": completed,
            "inspected": inspected,
            "decisions": decisions,
            "current_alias": incomplete[0] if incomplete else None,
        }

    def _recover_incomplete_terminal(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """Finish a decision that was fsynced before a process interruption.

        The visible decision is the irrevocable commit point. Resolution and the
        terminal marker are deterministic and idempotent, so restart may finish
        those writes without accepting another operator decision.
        """
        state = self._derive_visible_state(events)
        incomplete = [alias for alias in state["decisions"] if alias not in state["completed"]]
        if len(incomplete) > 1:
            raise ReplayIntegrityError("More than one Codex decision lacks a terminal marker")
        if not incomplete:
            return events
        alias = incomplete[0]
        decision = state["decisions"][alias]
        decision_event = next(
            event
            for event in events
            if event["case_alias"] == alias and event["event_type"] in {"DECISION_SEALED", "NO_TRADE_SEALED"}
        )
        decision_sha = canonical_hash(decision)
        outcome_head = self._seal_outcome(self._load_case(alias), decision, str(decision_event["recorded_at"]))
        self._append_once(self.visible_ledger_path, VISIBLE_EVENT_VERSION, {
            "event_type": "CASE_TERMINAL_HIDDEN",
            "case_alias": alias,
            "cursor_at": decision_event["cursor_at"],
            "idempotency_key": f"{decision_event['idempotency_key']}:terminal",
            "submission_sha256": decision_event["submission_sha256"],
            "recorded_at": decision_event["recorded_at"],
            "data": {
                "decision_sha256": decision_sha,
                "outcome_vault_record_sha256": outcome_head,
                "outcome_state": "SEALED_OPERATOR_INACCESSIBLE",
            },
        })
        return self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)

    @staticmethod
    def _head(events: list[dict[str, Any]]) -> str:
        return events[-1]["record_sha256"] if events else GENESIS

    def _status_from(self, events: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        completed = len(state["completed"])
        return {
            "protocol": PROTOCOL,
            "ready": True,
            "phase": "BLIND_COLLECTION" if completed < self.expected_case_count else "BLIND_COLLECTION_COMPLETE_OUTCOMES_LOCKED",
            "cases_completed": completed,
            "cases_total": self.expected_case_count,
            "current_case_alias": state["current_alias"],
            "visible_ledger_head_sha256": self._head(events),
            "outcome_vault_state": "SEALED_OPERATOR_INACCESSIBLE",
            "human_decisions": "HIDDEN",
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
            "research_credit": "BLINDED_HISTORICAL_OPERATOR_EVIDENCE",
            "cases": [
                {
                    "case_alias": case["case_alias"],
                    "trading_date_utc": case["trading_date_utc"],
                    "completed": case["case_alias"] in state["completed"],
                    "active": case["case_alias"] == state["current_alias"],
                }
                for case in self._registry["cases"]
            ],
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            events = self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)
            events = self._recover_incomplete_terminal(events)
            return self._status_from(events, self._derive_visible_state(events))

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
            available = next((item[key] for key in ("available_at", "forecast_available_at", "release_available_at", "revision_available_at") if item.get(key)), None)
            if available is None or parse_time(str(available)) <= cursor:
                output.append(deepcopy(item))
        return output

    def _context(self, row: dict[str, Any], cursor: datetime) -> dict[str, Any]:
        timeline = row["context_timeline"]
        fundamental = self._latest(timeline["fundamentals"], cursor)
        structure = self._latest(timeline["structure"], cursor)
        cross_market = self._latest(timeline["cross_market"], cursor)
        positioning = self._latest(timeline["positioning"], cursor)
        sessions = [deepcopy(item) for item in timeline["sessions"] if parse_time(str(item["available_at"])) <= cursor]
        events: list[dict[str, Any]] = []
        for source in timeline["events"]:
            scheduled = parse_time(str(source.get("scheduled_at") or source["released_at"]))
            released = parse_time(str(source["event_available_at"]))
            if cursor < released:
                if not source.get("schedule_verified_for_pre_event_use"):
                    continue
                events.append({
                    "record_id": source["record_id"], "event_code": source["event_code"],
                    "name": source["name"], "event_type": source["event_type"],
                    "importance": source["importance"], "epistemic_status": "OBSERVED",
                    "state": "SCHEDULED", "scheduled_at": iso(scheduled),
                    "forecasts": self._available_items(source.get("forecasts", []), cursor),
                })
            else:
                events.append({
                    "record_id": source["record_id"], "event_code": source["event_code"],
                    "name": source["name"], "event_type": source["event_type"],
                    "importance": source["importance"], "epistemic_status": "OBSERVED",
                    "state": "RELEASED", "scheduled_at": source.get("scheduled_at"),
                    "released_at": source["released_at"],
                    "forecasts": self._available_items(source.get("forecasts", []), cursor),
                    "releases": self._available_items(source.get("releases", []), cursor),
                    "raw_surprises": self._available_items(source.get("raw_surprises", []), cursor),
                    "standardized_surprises": self._available_items(source.get("standardized_surprises", []), cursor),
                })
        engine = (fundamental or {}).get("engine_state", {})
        return {
            "fundamental_summary": {
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
            },
            "fundamental": fundamental,
            "structure": structure,
            "cross_market": cross_market,
            "positioning": positioning,
            "events": events,
            "sessions": sessions,
            # Session clock boundaries are frozen calendar metadata, not future
            # market observations.  Keep them available from the first replay
            # cursor so the browser can mark London and New York before their
            # point-in-time session records become available.
            "session_schedule": self._session_schedule(row),
            "display_policy": {
                "point_in_time_only": True,
                "recommendations_present": False,
                "future_reactions_present": False,
            },
        }

    @staticmethod
    def _session_schedule(row: dict[str, Any]) -> list[dict[str, Any]]:
        schedule = [
            {
                "session_code": str(session["session_code"]),
                "decision_at": iso(parse_time(str(session["decision_at"]))),
                "observation_end": iso(parse_time(str(session["observation_end"]))),
                "session_timezone": str(session.get("session_timezone", "UTC")),
            }
            for session in row["context_timeline"]["sessions"]
            if str(session["session_code"]) in {"LONDON", "NEW_YORK"}
        ]
        counts = {
            code: sum(item["session_code"] == code for item in schedule)
            for code in ("LONDON", "NEW_YORK")
        }
        if counts != {"LONDON": 1, "NEW_YORK": 1}:
            raise ReplayIntegrityError(
                "A Codex case must have exactly one frozen London and New York session schedule"
            )
        return sorted(schedule, key=lambda item: (item["decision_at"], item["session_code"]))

    def _snapshot(self, row: dict[str, Any], cursor_at: str, state: dict[str, Any]) -> dict[str, Any]:
        cursor = parse_time(cursor_at)
        charts = {
            timeframe: [
                deepcopy(bar) for bar in row["timeframes"][timeframe]
                if parse_time(str(bar["close_at"])) <= cursor and parse_time(str(bar["available_at"])) <= cursor
            ]
            for timeframe in TIMEFRAMES
        }
        if any(parse_time(str(bar["close_at"])) > cursor or parse_time(str(bar["available_at"])) > cursor for bars in charts.values() for bar in bars):
            raise ReplayIntegrityError("A future bar entered a Codex browser snapshot")
        context = self._context(row, cursor)
        visibility = {
            timeframe: {
                "count": len(bars),
                "terminal_bar_id": bars[-1]["bar_id"] if bars else None,
                "sha256": canonical_hash(bars),
            }
            for timeframe, bars in charts.items()
        }
        body = {
            "case_alias": row["case_alias"],
            "cursor_at": iso(cursor),
            "charts": {timeframe: item["sha256"] for timeframe, item in visibility.items()},
            "context_sha256": canonical_hash(context),
            "inspected_timeframes": state["inspected"][row["case_alias"]],
        }
        snapshot = {
            "version": SNAPSHOT_VERSION,
            "case_alias": row["case_alias"],
            "mode": "CODEX_BLIND",
            "mode_sequence": row["mode_sequence"],
            "trading_date_utc": row["trading_date_utc"],
            "start_at": row["start_inclusive"],
            "end_at": row["end_exclusive"],
            "cursor_at": iso(cursor),
            "observation_terminal_at": iso(self._new_york_observation_end(row)),
            "active_entry_session": self._active_entry_session(row, cursor),
            "selected_timeframe_default": "15m",
            "charts": charts,
            "visible_timeframes": visibility,
            "context": context,
            "visible_state_sha256": canonical_hash(body),
            "inspected_timeframes": deepcopy(state["inspected"][row["case_alias"]]),
            "execution": {
                "maximum_planned_risk_usd": 50.0,
                "maximum_effective_risk_usd": 55.0,
                "order_types": ["MARKET"],
                "one_trade_per_case": True,
                "same_bar_ambiguity": "STOP_FIRST",
            },
            "display_policy": {
                "future_values_in_response": False,
                "outcomes_in_response": False,
                "one_way_cursor": True,
                "operator_input": "RENDERED_PIXELS_ONLY",
                "calendar_2025_2026_locked": True,
            },
        }
        self._assert_operator_safe(snapshot)
        return snapshot

    @staticmethod
    def _assert_operator_safe(snapshot: dict[str, Any]) -> None:
        forbidden_keys = {
            "source_lineage",
            "resolution",
            "net_pnl_usd",
            "r50",
            "mfe_r50",
            "mae_r50",
            "outcome_sha256",
            "outcome_vault_record_sha256",
            "future_bars",
        }

        def walk(value: Any) -> None:
            if isinstance(value, dict):
                overlap = forbidden_keys.intersection(value)
                if overlap:
                    raise ReplayIntegrityError(f"Operator snapshot contains forbidden keys: {sorted(overlap)}")
                for child in value.values():
                    walk(child)
            elif isinstance(value, list):
                for child in value:
                    walk(child)

        walk(snapshot)

    def case(self) -> dict[str, Any] | None:
        with self._lock:
            events = self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)
            events = self._recover_incomplete_terminal(events)
            state = self._derive_visible_state(events)
            if state["current_alias"] is None:
                return None
            alias = state["current_alias"]
            return {
                "case": self._snapshot(self._load_case(alias), state["cursors"][alias], state),
                "progress": self._status_from(events, state),
            }

    @staticmethod
    def _validate_key(value: str) -> None:
        if not value or len(value) > 128:
            raise ReplayConflictError("Idempotency-Key must contain 1 through 128 characters")

    @staticmethod
    def _find_idempotent(events: list[dict[str, Any]], key: str, submission_sha256: str) -> dict[str, Any] | None:
        event = next((item for item in events if item["idempotency_key"] == key), None)
        if event and event.get("submission_sha256") != submission_sha256:
            raise ReplayConflictError("Idempotency-Key was reused with another payload")
        return event

    def _validate_current(self, request: dict[str, Any], state: dict[str, Any]) -> tuple[str, datetime]:
        alias = str(request["case_alias"])
        if state["current_alias"] != alias:
            raise ReplaySequenceError(f"The active Codex case is {state['current_alias']}")
        current = parse_time(state["cursors"][alias])
        if parse_time(str(request["expected_cursor_at"])) != current:
            raise ReplayConflictError(f"Stale Codex cursor; current cursor is {iso(current)}")
        return alias, current

    def _mutation_response(self, event_sha256: str, idempotent: bool) -> dict[str, Any]:
        events = self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)
        events = self._recover_incomplete_terminal(events)
        state = self._derive_visible_state(events)
        payload = None
        if state["current_alias"]:
            alias = state["current_alias"]
            payload = self._snapshot(self._load_case(alias), state["cursors"][alias], state)
        return {
            "event_sha256": event_sha256,
            "idempotent_replay": idempotent,
            "case": payload,
            "progress": self._status_from(events, state),
            "outcome_hidden": True,
        }

    def advance(self, request: dict[str, Any], idempotency_key: str, recorded_at: str) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        submission_sha = canonical_hash(request)
        with self._lock:
            events = self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)
            events = self._recover_incomplete_terminal(events)
            existing = self._find_idempotent(events, idempotency_key, submission_sha)
            if existing:
                return self._mutation_response(existing["record_sha256"], True)
            state = self._derive_visible_state(events)
            alias, current = self._validate_current(request, state)
            row = self._load_case(alias)
            target = min(
                current + timedelta(minutes=int(request["increment_minutes"])),
                self._new_york_observation_end(row),
                parse_time(self._cases[alias]["end_exclusive"]),
            )
            if target <= current:
                raise ReplaySequenceError("The Codex cursor is already at case end")
            event = self._append(self.visible_ledger_path, VISIBLE_EVENT_VERSION, {
                "event_type": "CURSOR_ADVANCED",
                "case_alias": alias,
                "cursor_at": iso(target),
                "idempotency_key": idempotency_key,
                "submission_sha256": submission_sha,
                "recorded_at": recorded_at,
                "data": {
                    "from_cursor_at": iso(current),
                    "to_cursor_at": iso(target),
                    "increment_minutes": int(request["increment_minutes"]),
                    "selected_timeframe": request["selected_timeframe"],
                },
            })
            return self._mutation_response(event["record_sha256"], False)

    def inspect_timeframe(self, request: dict[str, Any], idempotency_key: str, recorded_at: str) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        submission_sha = canonical_hash(request)
        with self._lock:
            events = self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)
            events = self._recover_incomplete_terminal(events)
            existing = self._find_idempotent(events, idempotency_key, submission_sha)
            if existing:
                return self._mutation_response(existing["record_sha256"], True)
            state = self._derive_visible_state(events)
            alias, current = self._validate_current(request, state)
            event = self._append(self.visible_ledger_path, VISIBLE_EVENT_VERSION, {
                "event_type": "TIMEFRAME_INSPECTED",
                "case_alias": alias,
                "cursor_at": iso(current),
                "idempotency_key": idempotency_key,
                "submission_sha256": submission_sha,
                "recorded_at": recorded_at,
                "data": {
                    "selected_timeframe": request["selected_timeframe"],
                    "screenshot_sha256": request.get("screenshot_sha256"),
                },
            })
            return self._mutation_response(event["record_sha256"], False)

    @staticmethod
    def _active_entry_session(row: dict[str, Any], cursor: datetime) -> str | None:
        active = {
            str(session["session_code"])
            for session in row["context_timeline"]["sessions"]
            if str(session["session_code"]) in {"LONDON", "NEW_YORK"}
            and parse_time(str(session["decision_at"])) <= cursor < parse_time(str(session["observation_end"]))
        }
        if active == {"LONDON", "NEW_YORK"}:
            return "LONDON_NEW_YORK_OVERLAP"
        if "LONDON" in active:
            return "LONDON"
        if "NEW_YORK" in active:
            return "NEW_YORK"
        return None

    @staticmethod
    def _new_york_observation_end(row: dict[str, Any]) -> datetime:
        ends = [
            parse_time(str(session["observation_end"]))
            for session in row["context_timeline"]["sessions"]
            if str(session["session_code"]) == "NEW_YORK"
        ]
        if len(ends) != 1:
            raise ReplayIntegrityError("A Codex case must have exactly one frozen New York observation end")
        return ends[0]

    def _verify_predecision_evidence(
        self,
        request: dict[str, Any],
        snapshot: dict[str, Any],
    ) -> None:
        alias = str(request["case_alias"])
        manifest_path = self.artifact_path / "evidence" / "predecision" / alias / "predecision_evidence_manifest.json"
        if not manifest_path.is_file() or sha256_file(manifest_path) != request["predecision_evidence_sha256"]:
            raise ReplayIntegrityError("The frozen pre-decision evidence manifest is absent or differs")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            manifest.get("version") != "GOLD_BLIND_CODEX_OPERATOR_REPLAY_V1_PREDECISION_EVIDENCE_1_0"
            or manifest.get("case_alias") != alias
            or manifest.get("cursor_at") != request["expected_cursor_at"]
            or manifest.get("visible_state_sha256") != snapshot["visible_state_sha256"]
            or manifest.get("inspected_timeframes") != request["inspected_timeframes"]
        ):
            raise ReplayIntegrityError("The pre-decision evidence manifest does not bind the submitted visible state")
        artifacts = manifest.get("artifacts")
        if not isinstance(artifacts, list):
            raise ReplayIntegrityError("The pre-decision evidence artifact registry is absent")
        required = {
            "INITIAL_FULL_PAGE_SCREENSHOT",
            "FINAL_PREDECISION_FULL_PAGE_SCREENSHOT",
            "FINAL_PREDECISION_CHART_CROP",
            "COMPLETED_DECISION_FORM_SCREENSHOT",
            "CHRONOLOGICAL_ACTION_LOG",
        }
        kinds = {str(item.get("kind")) for item in artifacts}
        if not required.issubset(kinds):
            raise ReplayIntegrityError("Required pre-decision browser evidence is absent")
        timeframe_evidence = {
            str(item.get("timeframe"))
            for item in artifacts
            if item.get("kind") == "TIMEFRAME_SCREENSHOT"
        }
        if not set(request["inspected_timeframes"]).issubset(timeframe_evidence):
            raise ReplayIntegrityError("At least one inspected timeframe lacks a screenshot")
        evidence_root = (self.artifact_path / "evidence").resolve()
        for item in artifacts:
            relative = Path(str(item.get("path", "")))
            path = (self.artifact_path.parents[1] / relative).resolve()
            try:
                path.relative_to(evidence_root)
            except ValueError as exc:
                raise ReplayIntegrityError("An evidence path escapes the sealed evidence root") from exc
            if (
                not path.is_file()
                or path.stat().st_size != int(item.get("bytes", -1))
                or sha256_file(path) != item.get("sha256")
            ):
                raise ReplayIntegrityError(f"Pre-decision evidence differs: {relative.as_posix()}")

    def _validate_decision_rules(
        self,
        request: dict[str, Any],
        row: dict[str, Any],
        cursor: datetime,
        state: dict[str, Any],
    ) -> None:
        inspected = state["inspected"][row["case_alias"]]
        required = {"1w", "1d", "4h", "1h", "15m"}
        if not required.issubset(inspected):
            raise ReplaySequenceError("The frozen rubric requires W1, D1, H4, H1, and M15 inspection")
        if request["selected_timeframe"] not in inspected:
            raise ReplayConflictError("The submitted decision timeframe was not inspected at the durable cursor")
        for drawing in request.get("drawings", []):
            if parse_time(str(drawing["created_at_cursor"])) > cursor:
                raise ReplayConflictError("A drawing was created after the decision cursor")
            if any(parse_time(str(anchor["anchor_at"])) > cursor for anchor in drawing["anchors"]):
                raise ReplayConflictError("A drawing anchor references future time")
        if request["action"] == "NO_TRADE":
            if cursor != self._new_york_observation_end(row):
                raise ReplaySequenceError("NO_TRADE may be sealed only at the exact frozen New York observation end")
            return
        if self._active_entry_session(row, cursor) is None:
            raise ReplaySequenceError("Trades may be sealed only during London, overlap, or New York")

    @staticmethod
    def _spread(bar: dict[str, Any]) -> float:
        value = bar.get("spread_price")
        return float(value) if value is not None and float(value) >= 0 else 0.20

    def _resolve_trade(self, row: dict[str, Any], decision: dict[str, Any]) -> dict[str, Any]:
        direction = str(decision["action"])
        sign = 1 if direction == "LONG" else -1
        cursor = parse_time(str(decision["expected_cursor_at"]))
        effective_at = cursor + timedelta(minutes=int(self._execution["latency_minutes"]))
        bars = [bar for bar in row["timeframes"]["1m"] if parse_time(str(bar["open_at"])) >= effective_at]
        if not bars:
            raise ReplayIntegrityError(f"No eligible market fill bar: {row['case_alias']}")
        fill_bar = bars[0]
        half_spread = self._spread(fill_bar) / 2
        slip = float(self._execution["market_and_stop_slippage_price"])
        raw_fill = float(fill_bar["open"])
        fill_price = raw_fill + half_spread + slip if direction == "LONG" else raw_fill - half_spread - slip
        entry = float(decision["entry"])
        stop = float(decision["stop"])
        target = float(decision["target"])
        quantity = math.floor(float(self._execution["maximum_planned_risk_usd"]) / abs(entry - stop))
        if quantity < int(self._execution["minimum_quantity_ounces"]):
            raise ReplayIntegrityError("Frozen whole-ounce risk sizing produced zero quantity")
        effective_risk = sign * (fill_price - stop) * quantity
        effective_reward_price = sign * (target - fill_price)
        invalid_geometry = effective_risk <= 0 or effective_reward_price <= 0 or effective_risk > float(self._execution["maximum_effective_fill_to_stop_risk_usd"])
        path = bars
        resolution: dict[str, Any] | None = None
        if invalid_geometry:
            exit_bar = bars[1] if len(bars) > 1 else bars[0]
            raw_exit = float(exit_bar["open"] if len(bars) > 1 else exit_bar["close"])
            exit_half = self._spread(exit_bar) / 2
            actual_exit = raw_exit - exit_half - slip if direction == "LONG" else raw_exit + exit_half + slip
            resolution = {
                "state": "POST_FILL_GEOMETRY_INVALID",
                "exit_at": exit_bar["open_at"] if len(bars) > 1 else exit_bar["close_at"],
                "raw_exit_price": raw_exit,
                "actual_exit_price": round(actual_exit, 8),
                "effective_fill_to_stop_risk_usd": round(effective_risk, 8),
            }
            path = bars[:2]
        else:
            for index, bar in enumerate(bars):
                stop_touched = float(bar["low"]) <= stop if direction == "LONG" else float(bar["high"]) >= stop
                target_touched = float(bar["high"]) >= target if direction == "LONG" else float(bar["low"]) <= target
                if not stop_touched and not target_touched:
                    continue
                if stop_touched:
                    exit_half = self._spread(bar) / 2
                    raw_exit = min(stop, float(bar["open"])) if direction == "LONG" else max(stop, float(bar["open"]))
                    actual_exit = raw_exit - exit_half - slip if direction == "LONG" else raw_exit + exit_half + slip
                    resolution = {
                        "state": "STOPPED", "exit_at": bar["close_at"],
                        "raw_exit_price": raw_exit, "actual_exit_price": round(actual_exit, 8),
                        "same_bar_policy": "STOP_FIRST",
                    }
                else:
                    resolution = {
                        "state": "TARGET_HIT", "exit_at": bar["close_at"],
                        "raw_exit_price": target, "actual_exit_price": target,
                        "same_bar_policy": "STOP_FIRST",
                    }
                path = bars[: index + 1]
                break
        if resolution is None:
            exit_bar = bars[-1]
            raw_exit = float(exit_bar["close"])
            exit_half = self._spread(exit_bar) / 2
            actual_exit = raw_exit - exit_half - slip if direction == "LONG" else raw_exit + exit_half + slip
            resolution = {
                "state": "TIME_EXIT", "exit_at": exit_bar["close_at"],
                "raw_exit_price": raw_exit, "actual_exit_price": round(actual_exit, 8),
                "same_bar_policy": "STOP_FIRST",
            }
        pnl = sign * (float(resolution["actual_exit_price"]) - fill_price) * quantity
        if direction == "LONG":
            mfe = max(0.0, max(float(bar["high"]) for bar in path) - fill_price)
            mae = max(0.0, fill_price - min(float(bar["low"]) for bar in path))
        else:
            mfe = max(0.0, fill_price - min(float(bar["low"]) for bar in path))
            mae = max(0.0, max(float(bar["high"]) for bar in path) - fill_price)
        return {
            "order_id": f"{row['case_alias']}-CODEX-01",
            "case_alias": row["case_alias"],
            "decision_sha256": canonical_hash(decision),
            "direction": direction,
            "submitted_at": decision["expected_cursor_at"],
            "effective_at": iso(effective_at),
            "entry": entry,
            "stop": stop,
            "target": target,
            "quantity_ounces": quantity,
            "planned_risk_usd": round(abs(entry - stop) * quantity, 8),
            "fill": {
                "fill_at": fill_bar["open_at"], "raw_price": raw_fill,
                "actual_price": round(fill_price, 8), "spread_price": self._spread(fill_bar),
                "slippage_price": slip, "rule": "MARKET_NEXT_OBSERVED_M1_OPEN",
            },
            "resolution": resolution,
            "net_pnl_usd": round(pnl, 8),
            "r50": round(pnl / 50.0, 8),
            "mfe_r50": round(mfe * quantity / 50.0, 8),
            "mae_r50": round(mae * quantity / 50.0, 8),
            "post_fill_geometry_invalid": invalid_geometry,
        }

    def _seal_outcome(self, row: dict[str, Any], decision: dict[str, Any], recorded_at: str) -> str:
        decision_sha = canonical_hash(decision)
        if decision["action"] == "NO_TRADE":
            event = self._append_once(self.outcome_ledger_path, OUTCOME_EVENT_VERSION, {
                "event_type": "CASE_OUTCOME_SEALED",
                "case_alias": row["case_alias"],
                "cursor_at": decision["expected_cursor_at"],
                "idempotency_key": f"outcome:{decision_sha}",
                "submission_sha256": decision_sha,
                "recorded_at": recorded_at,
                "data": {"decision_sha256": decision_sha, "state": "NO_TRADE"},
            })
            return event["record_sha256"]
        outcome = self._resolve_trade(row, decision)
        fill = self._append_once(self.outcome_ledger_path, OUTCOME_EVENT_VERSION, {
            "event_type": "ORDER_FILLED",
            "case_alias": row["case_alias"],
            "cursor_at": outcome["fill"]["fill_at"],
            "idempotency_key": f"fill:{decision_sha}",
            "submission_sha256": decision_sha,
            "recorded_at": recorded_at,
            "data": {key: value for key, value in outcome.items() if key not in {"resolution", "net_pnl_usd", "r50", "mfe_r50", "mae_r50"}},
        })
        resolved = self._append_once(self.outcome_ledger_path, OUTCOME_EVENT_VERSION, {
            "event_type": "POSITION_RESOLVED",
            "case_alias": row["case_alias"],
            "cursor_at": outcome["resolution"]["exit_at"],
            "idempotency_key": f"resolution:{decision_sha}",
            "submission_sha256": decision_sha,
            "recorded_at": recorded_at,
            "data": outcome,
        })
        sealed = self._append_once(self.outcome_ledger_path, OUTCOME_EVENT_VERSION, {
            "event_type": "CASE_OUTCOME_SEALED",
            "case_alias": row["case_alias"],
            "cursor_at": outcome["resolution"]["exit_at"],
            "idempotency_key": f"outcome:{decision_sha}",
            "submission_sha256": decision_sha,
            "recorded_at": recorded_at,
            "data": {
                "decision_sha256": decision_sha,
                "fill_record_sha256": fill["record_sha256"],
                "resolution_record_sha256": resolved["record_sha256"],
                "outcome_sha256": canonical_hash(outcome),
            },
        })
        return sealed["record_sha256"]

    def decide(self, request: dict[str, Any], idempotency_key: str, recorded_at: str) -> dict[str, Any]:
        self._validate_key(idempotency_key)
        submission_sha = canonical_hash(request)
        with self._lock:
            events = self._read_chain(self.visible_ledger_path, VISIBLE_EVENT_VERSION)
            existing = self._find_idempotent(events, idempotency_key, submission_sha)
            if existing:
                events = self._recover_incomplete_terminal(events)
                terminal = next(
                    (
                        event
                        for event in events
                        if event["idempotency_key"] == f"{idempotency_key}:terminal"
                    ),
                    existing,
                )
                return self._mutation_response(terminal["record_sha256"], True)
            state = self._derive_visible_state(events)
            alias, current = self._validate_current(request, state)
            row = self._load_case(alias)
            snapshot = self._snapshot(row, iso(current), state)
            if request["client_visible_state_sha256"] != snapshot["visible_state_sha256"]:
                raise ReplayConflictError("Client visible-state hash differs from the sealed server snapshot")
            inspected = request["inspected_timeframes"]
            if inspected != state["inspected"][alias]:
                raise ReplayConflictError("Submitted inspected-timeframe sequence differs from the ledger")
            self._validate_decision_rules(request, row, current, state)
            self._verify_predecision_evidence(request, snapshot)
            event_type = "NO_TRADE_SEALED" if request["action"] == "NO_TRADE" else "DECISION_SEALED"
            decision = deepcopy(request)
            self._append(self.visible_ledger_path, VISIBLE_EVENT_VERSION, {
                "event_type": event_type,
                "case_alias": alias,
                "cursor_at": iso(current),
                "idempotency_key": idempotency_key,
                "submission_sha256": submission_sha,
                "recorded_at": recorded_at,
                "data": {"decision": decision, "decision_sha256": canonical_hash(decision)},
            })
            outcome_head = self._seal_outcome(row, decision, recorded_at)
            terminal = self._append_once(self.visible_ledger_path, VISIBLE_EVENT_VERSION, {
                "event_type": "CASE_TERMINAL_HIDDEN",
                "case_alias": alias,
                "cursor_at": iso(current),
                "idempotency_key": f"{idempotency_key}:terminal",
                "submission_sha256": submission_sha,
                "recorded_at": recorded_at,
                "data": {
                    "decision_sha256": canonical_hash(decision),
                    "outcome_vault_record_sha256": outcome_head,
                    "outcome_state": "SEALED_OPERATOR_INACCESSIBLE",
                },
            })
            return self._mutation_response(terminal["record_sha256"], False)


@lru_cache(maxsize=1)
def get_codex_operator_replay_service() -> CodexOperatorReplayService:
    settings = get_settings()
    return CodexOperatorReplayService(
        artifact_path=settings.codex_operator_replay_artifact_path,
        visible_ledger_path=settings.codex_operator_replay_visible_ledger_path,
        outcome_ledger_path=settings.codex_operator_replay_outcome_ledger_path,
        human_ledger_path=settings.blind_replay_v3_ledger_path,
    )
