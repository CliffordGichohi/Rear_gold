from __future__ import annotations

import gzip
import json
import os
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from gold_intel.api.blind_replay_v2_schemas import (
    ReplayV2Action,
    ReplayV2EntryTrigger,
)
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

PROTOCOL = "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_PROTOCOL_1_0"
TIMEFRAMES = ("1w", "1d", "4h", "1h", "15m", "5m", "1m")
POSITION_KINDS = {"LONG_POSITION", "SHORT_POSITION"}


class BlindReplayV2Service:
    """Serve only cursor-filtered practice data and durably seal setup decisions."""

    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path.resolve()
        self.timeline_path = self.artifact_path / "practice_timelines_v2.primary.jsonl.gz"
        self.reference_timeline_path = self.artifact_path / "practice_timelines_v2.reference.jsonl.gz"
        self.certification_path = self.artifact_path / "timeline_materialization_certification.json"
        self.freeze_path = self.artifact_path / "preimplementation_state.json"
        self.cursor_ledger_path = self.artifact_path / "ledgers" / "cursor_ledger_v2.jsonl"
        self.setup_ledger_path = self.artifact_path / "ledgers" / "setup_ledger_v2.jsonl"
        self._lock = threading.RLock()
        self._timelines = self._load_and_verify_inputs()
        self._timeline_by_alias = {row["case_alias"]: row for row in self._timelines}

    @staticmethod
    def _read_gzip(path: Path) -> list[dict[str, Any]]:
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            return [json.loads(line) for line in handle]

    def _load_and_verify_inputs(self) -> list[dict[str, Any]]:
        required = (
            self.timeline_path,
            self.reference_timeline_path,
            self.certification_path,
            self.freeze_path,
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise ReplayIntegrityError(f"Certified V2 replay inputs are missing: {missing}")
        freeze = json.loads(self.freeze_path.read_text(encoding="utf-8"))
        if freeze.get("status") != "FROZEN_BEFORE_V2_VALUE_MATERIALIZATION_OR_IMPLEMENTATION":
            raise ReplayIntegrityError("V2 preimplementation state differs")
        if int(freeze.get("human_decisions_collected", -1)) != 0:
            raise ReplayIntegrityError("V2 was not frozen at zero human decisions")
        certification = json.loads(self.certification_path.read_text(encoding="utf-8"))
        if certification.get("verdict") != "PASS_V2_PRACTICE_TIMELINE_MATERIALIZATION":
            raise ReplayIntegrityError("V2 practice timeline materialization did not pass")
        if not all(certification.get("gates", {}).values()):
            raise ReplayIntegrityError("At least one V2 timeline gate failed")
        if sha256_file(self.timeline_path) != certification.get("primary_sha256"):
            raise ReplayIntegrityError("V2 primary timeline hash differs")
        if sha256_file(self.reference_timeline_path) != certification.get("reference_sha256"):
            raise ReplayIntegrityError("V2 reference timeline hash differs")
        if certification.get("primary_sha256") != certification.get("reference_sha256"):
            raise ReplayIntegrityError("V2 primary/reference timeline bytes differ")
        primary = self._read_gzip(self.timeline_path)
        reference = self._read_gzip(self.reference_timeline_path)
        if primary != reference or canonical_hash(primary) != certification.get("complete_timeline_set_sha256"):
            raise ReplayIntegrityError("V2 primary/reference timeline structures differ")
        expected_aliases = [f"P-{index:03d}" for index in range(1, 21)]
        if [row.get("case_alias") for row in primary] != expected_aliases:
            raise ReplayIntegrityError("V2 practice population or order differs")
        for index, row in enumerate(primary, start=1):
            if row.get("mode") != "PRACTICE" or int(row.get("mode_sequence", 0)) != index:
                raise ReplayIntegrityError("V2 contains a non-practice or misordered case")
            submitted = row.get("timeline_sha256")
            body = {key: value for key, value in row.items() if key != "timeline_sha256"}
            if submitted != canonical_hash(body):
                raise ReplayIntegrityError(f"V2 timeline hash failed for {row.get('case_alias')}")
            if set(row.get("timelines", {})) != set(TIMEFRAMES):
                raise ReplayIntegrityError("V2 timeframe registry differs")
            m1_future = [
                int(bar["close_offset_minutes"])
                for bar in row["timelines"]["1m"]
                if int(bar["close_offset_minutes"]) > 0
            ]
            if m1_future != list(range(1, 181)):
                raise ReplayIntegrityError("V2 practice future is not exactly minute 1 through 180")
        return primary

    @staticmethod
    def _read_chain(path: Path, *, version: str) -> list[dict[str, Any]]:
        if not path.exists():
            return []
        records: list[dict[str, Any]] = []
        prior = GENESIS_HASH
        keys: set[str] = set()
        with path.open("r", encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayIntegrityError(f"{path.name} contains invalid JSON") from exc
                if record.get("version") != version:
                    raise ReplayIntegrityError(f"{path.name} record version differs")
                if int(record.get("ledger_sequence", 0)) != sequence:
                    raise ReplayIntegrityError(f"{path.name} sequence is discontinuous")
                if record.get("prior_record_sha256") != prior:
                    raise ReplayIntegrityError(f"{path.name} hash chain is broken")
                body = {key: value for key, value in record.items() if key != "record_sha256"}
                if record.get("record_sha256") != canonical_hash(body):
                    raise ReplayIntegrityError(f"{path.name} record hash is invalid")
                key = str(record.get("idempotency_key", ""))
                if not key or key in keys:
                    raise ReplayIntegrityError(f"{path.name} has a duplicate idempotency identity")
                keys.add(key)
                prior = str(record["record_sha256"])
                records.append(record)
        return records

    def _read_setup_ledger(self) -> list[dict[str, Any]]:
        records = self._read_chain(
            self.setup_ledger_path, version="GOLD_BLIND_SYNCHRONIZED_SETUP_RECORD_V2"
        )
        if len(records) > 20:
            raise ReplayIntegrityError("V2 setup ledger exceeds its practice population")
        for index, record in enumerate(records, start=1):
            if record.get("case_alias") != f"P-{index:03d}":
                raise ReplayIntegrityError("V2 setup ledger differs from frozen practice order")
        return records

    def _read_cursor_ledger(self, completed: int) -> list[dict[str, Any]]:
        records = self._read_chain(
            self.cursor_ledger_path, version="GOLD_BLIND_SYNCHRONIZED_CURSOR_RECORD_V2"
        )
        last_by_alias: dict[str, int] = {}
        previous_case_number = 1
        for record in records:
            alias = str(record.get("case_alias"))
            if alias not in self._timeline_by_alias:
                raise ReplayIntegrityError("V2 cursor ledger contains an unknown case")
            case_number = int(alias.split("-")[1])
            if case_number < previous_case_number or case_number > completed + 1:
                raise ReplayIntegrityError("V2 cursor records violate frozen case order")
            previous_case_number = case_number
            prior_cursor = last_by_alias.get(alias, 0)
            if int(record.get("from_cursor_minute", -1)) != prior_cursor:
                raise ReplayIntegrityError("V2 cursor history is not contiguous")
            increment = int(record.get("increment_minutes", 0))
            to_cursor = int(record.get("to_cursor_minute", -1))
            if increment not in {1, 5, 15} or to_cursor != prior_cursor + increment:
                raise ReplayIntegrityError("V2 cursor increment differs from the frozen rule")
            if to_cursor > 180:
                raise ReplayIntegrityError("V2 cursor exceeds its frozen boundary")
            last_by_alias[alias] = to_cursor
        return records

    def _state(self) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
        setup = self._read_setup_ledger()
        cursor = self._read_cursor_ledger(len(setup))
        completed_aliases = {record["case_alias"] for record in setup}
        if any(record["case_alias"] in completed_aliases and int(record["case_alias"].split("-")[1]) > len(setup) for record in cursor):
            raise ReplayIntegrityError("Cursor ledger references an invalid completed case")
        return setup, cursor

    @staticmethod
    def _head(records: list[dict[str, Any]]) -> str:
        return str(records[-1]["record_sha256"]) if records else GENESIS_HASH

    @staticmethod
    def _cursor_for(alias: str, records: list[dict[str, Any]]) -> int:
        matching = [record for record in records if record["case_alias"] == alias]
        return int(matching[-1]["to_cursor_minute"]) if matching else 0

    def _status_from(
        self, setup: list[dict[str, Any]], cursor: list[dict[str, Any]]
    ) -> dict[str, Any]:
        completed = len(setup)
        alias = f"P-{completed + 1:03d}" if completed < 20 else None
        return {
            "protocol": PROTOCOL,
            "ready": True,
            "phase": "PRACTICE" if alias else "PRACTICE_COMPLETE_SCORED_CLOSED",
            "practice_completed": completed,
            "practice_total": 20,
            "total_locked": completed,
            "next_case_alias": alias,
            "cursor_minute": self._cursor_for(alias, cursor) if alias else None,
            "cursor_ledger_head_sha256": self._head(cursor),
            "setup_ledger_head_sha256": self._head(setup),
            "scored_labeling": "CLOSED_V2_PRACTICE_ONLY_CERTIFIED",
            "research_credit": "ZERO_PRACTICE_ONLY",
        }

    def status(self) -> dict[str, Any]:
        with self._lock:
            setup, cursor = self._state()
            return self._status_from(setup, cursor)

    @staticmethod
    def _visible_bars(row: dict[str, Any], cursor: int) -> dict[str, list[dict[str, Any]]]:
        return {
            timeframe: [
                bar
                for bar in row["timelines"][timeframe]
                if int(bar["close_offset_minutes"]) <= cursor
                and int(bar["available_offset_minutes"]) <= cursor
            ]
            for timeframe in TIMEFRAMES
        }

    @staticmethod
    def _m15_atr(bars: list[dict[str, Any]]) -> float:
        if len(bars) < 15:
            raise ReplayIntegrityError("Fewer than 15 completed M15 bars are visible")
        ranges: list[float] = []
        for prior, current in zip(bars[-15:-1], bars[-14:], strict=True):
            ranges.append(
                max(
                    float(current["high"]) - float(current["low"]),
                    abs(float(current["high"]) - float(prior["close"])),
                    abs(float(current["low"]) - float(prior["close"])),
                )
            )
        atr = sum(ranges) / len(ranges)
        if atr <= 0:
            raise ReplayIntegrityError("Point-in-time M15 ATR is nonpositive")
        return round(atr, 8)

    def _snapshot(self, row: dict[str, Any], cursor: int) -> dict[str, Any]:
        charts = self._visible_bars(row, cursor)
        visibility = {
            timeframe: {
                "count": len(charts[timeframe]),
                "terminal_bar_id": charts[timeframe][-1]["bar_id"] if charts[timeframe] else None,
                "sha256": canonical_hash(charts[timeframe]),
            }
            for timeframe in TIMEFRAMES
        }
        aggregate_hash = canonical_hash(
            {timeframe: visibility[timeframe]["sha256"] for timeframe in TIMEFRAMES}
        )
        m1 = charts["1m"]
        if not m1:
            raise ReplayIntegrityError("No M1 bar is visible at the cursor")
        return {
            "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_REPLAY_V2_SNAPSHOT_1_0",
            "case_alias": row["case_alias"],
            "mode": "PRACTICE",
            "mode_sequence": row["mode_sequence"],
            "session_code": row["session_code"],
            "cursor_minute": cursor,
            "maximum_cursor_minute": 180,
            "selected_timeframe_default": "15m",
            "reference_index": row["reference_index"],
            "latest_visible_m1_close_index": m1[-1]["close"],
            "latest_point_in_time_m15_atr_index": self._m15_atr(charts["15m"]),
            "context_frozen_at_cursor_minute": 0,
            "context_staleness_minutes": cursor,
            "context": row["context"],
            "context_sha256": row["context_sha256"],
            "charts": charts,
            "visible_timeframes": visibility,
            "visible_charts_sha256": aggregate_hash,
            "display_policy": {
                "one_way_cursor": True,
                "future_values_in_response": False,
                "timeframe_switch_changes_cursor": False,
                "drawings_case_global": True,
                "scored_labeling_closed": True,
                "context_frozen_at_t0": True,
            },
        }

    def next_case(self) -> dict[str, Any] | None:
        with self._lock:
            setup, cursor_records = self._state()
            if len(setup) >= 20:
                return None
            alias = f"P-{len(setup) + 1:03d}"
            cursor = self._cursor_for(alias, cursor_records)
            return {
                "case": self._snapshot(self._timeline_by_alias[alias], cursor),
                "progress": self._status_from(setup, cursor_records),
            }

    @staticmethod
    def _find_idempotent(
        records: list[dict[str, Any]], idempotency_key: str, submission_hash: str
    ) -> dict[str, Any] | None:
        existing = next(
            (record for record in records if record["idempotency_key"] == idempotency_key), None
        )
        if existing and existing.get("submission_sha256") != submission_hash:
            raise ReplayConflictError("Idempotency-Key was already used for another payload")
        return existing

    @staticmethod
    def _append_record(path: Path, record: dict[str, Any]) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8", newline="\n") as handle:
            handle.write(canonical_bytes(record).decode("utf-8") + "\n")
            handle.flush()
            os.fsync(handle.fileno())

    def advance(
        self, *, request: dict[str, Any], idempotency_key: str, advanced_at: str
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ReplayConflictError("Idempotency-Key must contain 1 through 128 characters")
        with self._lock:
            setup, cursor_records = self._state()
            submission_hash = canonical_hash(request)
            existing = self._find_idempotent(cursor_records, idempotency_key, submission_hash)
            if existing:
                alias = str(existing["case_alias"])
                return {
                    "case": self._snapshot(
                        self._timeline_by_alias[alias], int(existing["to_cursor_minute"])
                    ),
                    "progress": self._status_from(setup, cursor_records),
                }
            if len(setup) >= 20:
                raise ReplaySequenceError("All V2 practice setups are already locked")
            expected_alias = f"P-{len(setup) + 1:03d}"
            if request["case_alias"] != expected_alias:
                raise ReplaySequenceError(f"Only the current practice case may advance: {expected_alias}")
            current = self._cursor_for(expected_alias, cursor_records)
            if int(request["expected_cursor_minute"]) != current:
                raise ReplayConflictError(f"Stale cursor: expected current minute {current}")
            increment = int(request["increment_minutes"])
            target = current + increment
            if increment not in {1, 5, 15} or target > 180:
                raise ReplaySequenceError("Advance violates the frozen one-way cursor boundary")
            snapshot = self._snapshot(self._timeline_by_alias[expected_alias], target)
            record: dict[str, Any] = {
                "version": "GOLD_BLIND_SYNCHRONIZED_CURSOR_RECORD_V2",
                "ledger_sequence": len(cursor_records) + 1,
                "case_alias": expected_alias,
                "from_cursor_minute": current,
                "to_cursor_minute": target,
                "increment_minutes": increment,
                "selected_timeframe": request["selected_timeframe"],
                "visible_charts_sha256": snapshot["visible_charts_sha256"],
                "advanced_at": advanced_at,
                "idempotency_key": idempotency_key,
                "submission_sha256": submission_hash,
                "prior_record_sha256": self._head(cursor_records),
            }
            record["record_sha256"] = canonical_hash(record)
            self._append_record(self.cursor_ledger_path, record)
            updated = [*cursor_records, record]
            return {"case": snapshot, "progress": self._status_from(setup, updated)}

    @staticmethod
    def _validate_drawings(
        request: dict[str, Any], snapshot: dict[str, Any]
    ) -> None:
        cursor = int(snapshot["cursor_minute"])
        visible_offsets = {
            timeframe: {int(bar["close_offset_minutes"]) for bar in bars}
            for timeframe, bars in snapshot["charts"].items()
        }
        positions = []
        for drawing in request["drawings"]:
            if int(drawing["placed_at_cursor_minute"]) > cursor:
                raise ReplayConflictError("A drawing was created after the submitted cursor")
            if drawing["kind"] in POSITION_KINDS:
                positions.append(drawing)
                if int(drawing["placed_at_cursor_minute"]) != cursor:
                    raise ReplayConflictError("The position was not drawn at REPLAY NOW")
            for anchor in drawing["anchors"]:
                relative = int(anchor["relative_minute"])
                timeframe = str(anchor["source_timeframe"])
                if relative > cursor:
                    raise ReplayConflictError("A drawing anchor references an unrevealed minute")
                if relative not in visible_offsets.get(timeframe, set()):
                    raise ReplayConflictError("A drawing anchor does not identify a visible completed bar")
        if len(positions) > 1:
            raise ReplayConflictError("Exactly one position object is permitted")

    @staticmethod
    def _validate_geometry(request: dict[str, Any], snapshot: dict[str, Any]) -> None:
        if request["action"] == ReplayV2Action.NO_TRADE.value:
            return
        entry = float(request["entry_index"])
        stop = float(request["stop_index"])
        target = float(request["target_index"])
        latest = float(snapshot["latest_visible_m1_close_index"])
        atr = float(snapshot["latest_point_in_time_m15_atr_index"])
        offset = (entry - latest) / atr
        stop_atr = abs(entry - stop) / atr
        target_r = abs(target - entry) / abs(entry - stop)
        if not 0.25 - 1e-8 <= stop_atr <= 3.0 + 1e-8:
            raise ReplayConflictError("Stop distance is outside 0.25 through 3.00 M15 ATR")
        if not 0.5 - 1e-8 <= target_r <= 5.0 + 1e-8:
            raise ReplayConflictError("Target is outside 0.50 through 5.00 R")
        trigger = request["entry_trigger"]
        action = request["action"]
        if trigger == ReplayV2EntryTrigger.MARKET.value:
            if abs(entry - latest) > 1e-6:
                raise ReplayConflictError("MARKET entry must equal the latest visible M1 close")
            return
        if abs(offset) > 2.0 + 1e-8:
            raise ReplayConflictError("Entry offset exceeds the frozen 2.00 ATR limit")
        pullback_sign_ok = (
            action == ReplayV2Action.LONG.value and offset <= 1e-8
        ) or (action == ReplayV2Action.SHORT.value and offset >= -1e-8)
        if trigger == ReplayV2EntryTrigger.PULLBACK_LIMIT.value and not pullback_sign_ok:
            raise ReplayConflictError("Pullback entry is on the wrong side of REPLAY NOW")
        if (
            trigger == ReplayV2EntryTrigger.BREAKOUT_STOP.value
            and pullback_sign_ok
            and abs(offset) > 1e-8
        ):
            raise ReplayConflictError("Breakout entry is on the wrong side of REPLAY NOW")

    def submit_decision(
        self, *, request: dict[str, Any], idempotency_key: str, locked_at: str
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ReplayConflictError("Idempotency-Key must contain 1 through 128 characters")
        with self._lock:
            setup, cursor_records = self._state()
            submission_hash = canonical_hash(request)
            existing = self._find_idempotent(setup, idempotency_key, submission_hash)
            if existing:
                return self._decision_response(existing, setup, cursor_records, idempotent=True)
            if len(setup) >= 20:
                raise ReplaySequenceError("All V2 practice setups are already locked")
            expected_alias = f"P-{len(setup) + 1:03d}"
            if request["case_alias"] != expected_alias:
                raise ReplaySequenceError(f"Only the current practice case may be locked: {expected_alias}")
            cursor = self._cursor_for(expected_alias, cursor_records)
            if int(request["expected_cursor_minute"]) != cursor:
                raise ReplayConflictError(f"Stale cursor: expected current minute {cursor}")
            row = self._timeline_by_alias[expected_alias]
            snapshot = self._snapshot(row, cursor)
            if request["client_visible_charts_sha256"] != snapshot["visible_charts_sha256"]:
                raise ReplayConflictError("Visible chart snapshot differs from the server-sealed state")
            self._validate_drawings(request, snapshot)
            self._validate_geometry(request, snapshot)
            visibility = {
                timeframe: snapshot["visible_timeframes"][timeframe]
                for timeframe in TIMEFRAMES
            }
            record: dict[str, Any] = {
                "version": "GOLD_BLIND_SYNCHRONIZED_SETUP_RECORD_V2",
                "ledger_sequence": len(setup) + 1,
                "case_alias": expected_alias,
                "mode": "PRACTICE",
                "mode_sequence": len(setup) + 1,
                "cursor_minute": cursor,
                "selected_timeframe": request["selected_timeframe"],
                "latest_visible_m1_close_index": snapshot["latest_visible_m1_close_index"],
                "latest_point_in_time_m15_atr_index": snapshot[
                    "latest_point_in_time_m15_atr_index"
                ],
                "visible_timeframes": visibility,
                "visible_charts_sha256": snapshot["visible_charts_sha256"],
                "point_in_time_context": snapshot["context"],
                "context_sha256": snapshot["context_sha256"],
                "submitted_setup": request,
                "submitted_setup_sha256": submission_hash,
                "execution_policy": {
                    "account_equity_usd": 10_000.0,
                    "maximum_planned_risk_usd": 50.0,
                    "latency_minutes": 1,
                    "spread": "SEALED_V1_ASSUMPTION",
                    "slippage": "SEALED_V1_ASSUMPTION",
                    "commission": "SEALED_V1_ASSUMPTION",
                    "same_bar_ambiguity": "STOP_FIRST",
                    "position_overlap": "APPEND_ONLY_ONE_SETUP_DECISION",
                },
                "locked_at": locked_at,
                "idempotency_key": idempotency_key,
                "submission_sha256": submission_hash,
                "prior_record_sha256": self._head(setup),
            }
            record["record_sha256"] = canonical_hash(record)
            self._append_record(self.setup_ledger_path, record)
            updated = [*setup, record]
            return self._decision_response(record, updated, cursor_records, idempotent=False)

    def _decision_response(
        self,
        record: dict[str, Any],
        setup: list[dict[str, Any]],
        cursor_records: list[dict[str, Any]],
        *,
        idempotent: bool,
    ) -> dict[str, Any]:
        row = self._timeline_by_alias[str(record["case_alias"])]
        cursor = int(record["cursor_minute"])
        future = [
            bar
            for bar in row["timelines"]["1m"]
            if int(bar["close_offset_minutes"]) > cursor
            and int(bar["available_offset_minutes"]) <= 180
        ]
        return {
            "locked": True,
            "idempotent_replay": idempotent,
            "record_sha256": record["record_sha256"],
            "case_alias": record["case_alias"],
            "locked_cursor_minute": cursor,
            "progress": self._status_from(setup, cursor_records),
            "practice_feedback": {
                "status": "PRACTICE_RESOLUTION_REVEALED_ZERO_RESEARCH_CREDIT",
                "locked_cursor_minute": cursor,
                "bars": future,
                "economic_result": "NOT_CALCULATED_DURING_V2_PRACTICE",
            },
        }


@lru_cache(maxsize=1)
def get_blind_replay_v2_service() -> BlindReplayV2Service:
    return BlindReplayV2Service(get_settings().blind_replay_v2_artifact_path)
