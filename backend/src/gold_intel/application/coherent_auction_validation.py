from __future__ import annotations

import json
import threading
from copy import deepcopy
from functools import lru_cache
from pathlib import Path
from typing import Any

from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
    canonical_hash,
    sha256_file,
)
from gold_intel.application.blind_replay_v3 import AnnotatedReplayV3Service
from gold_intel.config import get_settings

PROTOCOL = "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_PROTOCOL_1_0"
RESEARCH_CREDIT = "HISTORICAL_BLIND_ROBUSTNESS_ONLY"
CASE_COUNT = 50
REQUIRED_ANNOTATION_FIELDS = {
    "auction_family",
    "controlling_h4_state",
    "location_assessment",
    "stop_basis",
    "target_timeframe",
    "macro_override_reason",
}


class CoherentAuctionValidationService(AnnotatedReplayV3Service):
    """Isolated, outcome-hidden replay service for the frozen 50-session block."""

    def __init__(self, artifact_path: Path, ledger_path: Path | None = None) -> None:
        self.artifact_path = artifact_path.resolve()
        self.primary_path = self.artifact_path / "validation_streams.primary.jsonl.gz"
        self.reference_path = self.artifact_path / "validation_streams.reference.jsonl.gz"
        self.certification_path = self.artifact_path / "stream_materialization_certification.json"
        self.registry_path = self.artifact_path / "population_registry.private.json"
        self.execution_path = self.artifact_path / "execution_policy.json"
        self.ledger_policy_path = self.artifact_path / "ledger_policy.json"
        configured = ledger_path or get_settings().coherent_auction_validation_ledger_path
        self.event_ledger_path = configured.resolve()
        self._lock = threading.RLock()
        self._rows, self._registry, self._execution = self._load_and_verify_inputs()
        self._by_alias = {row["case_alias"]: row for row in self._rows}

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
            raise ReplayIntegrityError(f"Certified auction-validation inputs are missing: {missing}")
        certification = json.loads(self.certification_path.read_text(encoding="utf-8"))
        if certification.get("verdict") != "PASS_BLIND_VALIDATION_STREAM_MATERIALIZATION":
            raise ReplayIntegrityError("Auction-validation stream certification did not pass")
        if not all(certification.get("gates", {}).values()):
            raise ReplayIntegrityError("At least one auction-validation materialization gate failed")
        primary_sha = sha256_file(self.primary_path)
        reference_sha = sha256_file(self.reference_path)
        if primary_sha != certification.get("primary_sha256"):
            raise ReplayIntegrityError("Auction-validation primary stream hash differs")
        if reference_sha != certification.get("reference_sha256"):
            raise ReplayIntegrityError("Auction-validation reference stream hash differs")
        if primary_sha != reference_sha:
            raise ReplayIntegrityError("Auction-validation independent stream bytes differ")
        primary = self._read_gzip(self.primary_path)
        reference = self._read_gzip(self.reference_path)
        if primary != reference:
            raise ReplayIntegrityError("Auction-validation independent stream values differ")
        if canonical_hash(primary) != certification.get("complete_stream_set_sha256"):
            raise ReplayIntegrityError("Auction-validation complete stream-set hash differs")
        aliases = [f"GAV-2022-{index:03d}" for index in range(1, CASE_COUNT + 1)]
        if [row.get("case_alias") for row in primary] != aliases:
            raise ReplayIntegrityError("Auction-validation aliases or order differ")
        for index, row in enumerate(primary, start=1):
            if (
                row.get("mode") != "BLIND_HISTORICAL_ROBUSTNESS"
                or row.get("research_credit") != RESEARCH_CREDIT
                or int(row.get("mode_sequence", 0)) != index
            ):
                raise ReplayIntegrityError("Auction-validation stream population differs")
            submitted = row.get("stream_sha256")
            body = {key: value for key, value in row.items() if key != "stream_sha256"}
            if submitted != canonical_hash(body):
                raise ReplayIntegrityError(
                    f"Auction-validation stream record hash differs: {row.get('case_alias')}"
                )
            if set(row.get("timeframes", {})) != set(self._rows_timeframes()):
                raise ReplayIntegrityError("Auction-validation timeframe registry differs")
        registry = json.loads(self.registry_path.read_text(encoding="utf-8"))
        if (
            registry.get("case_count") != CASE_COUNT
            or registry.get("population_sha256") != certification.get("population_sha256")
        ):
            raise ReplayIntegrityError("Auction-validation frozen population differs")
        execution = json.loads(self.execution_path.read_text(encoding="utf-8"))
        if execution.get("version") != "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_EXECUTION_POLICY_1_0":
            raise ReplayIntegrityError("Auction-validation execution policy differs")
        ledger = json.loads(self.ledger_policy_path.read_text(encoding="utf-8"))
        if ledger.get("version") != "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_LEDGER_POLICY_1_0":
            raise ReplayIntegrityError("Auction-validation ledger policy differs")
        return primary, registry, execution

    @staticmethod
    def _rows_timeframes() -> tuple[str, ...]:
        return ("1w", "1d", "4h", "1h", "15m", "5m", "1m")

    def _status_from(self, events: list[dict[str, Any]], state: dict[str, Any]) -> dict[str, Any]:
        cases = []
        registry_by_alias = {row["case_alias"]: row for row in self._registry["cases"]}
        for row in self._rows:
            alias = row["case_alias"]
            source = registry_by_alias[alias]
            cases.append(
                {
                    "case_alias": alias,
                    "trading_date_utc": source["trading_date_utc"],
                    "session_code": source["session_code"],
                    "completed": alias in state["completed"],
                    "active": alias == state["current_alias"],
                    "research_credit": RESEARCH_CREDIT,
                }
            )
        completed = len(state["completed"])
        return {
            "protocol": PROTOCOL,
            "ready": True,
            "phase": "BLIND_COLLECTION" if completed < CASE_COUNT else "BLIND_COLLECTION_COMPLETE_RESULTS_LOCKED",
            "practice_completed": completed,
            "practice_total": CASE_COUNT,
            "current_case_alias": state["current_alias"],
            "event_ledger_head_sha256": self._head(events),
            "collection_year": 2022,
            "collection_state": "OPEN_BLIND_AGGREGATES_LOCKED",
            "calendar_2025": "LOCKED",
            "calendar_2026": "LOCKED",
            "research_credit": RESEARCH_CREDIT,
            "practice_cases": cases,
        }

    def _snapshot(
        self, row: dict[str, Any], cursor_at: str, state: dict[str, Any]
    ) -> dict[str, Any]:
        payload = super()._snapshot(row, cursor_at, state)
        payload["version"] = "GOLD_COHERENT_AUCTION_BLIND_VALIDATION_V1_SNAPSHOT_1_0"
        payload["mode"] = "BLIND_HISTORICAL_ROBUSTNESS"
        payload["session_code"] = row["session_code"]
        payload["display_policy"] = {
            **payload["display_policy"],
            "practice_zero_credit": False,
            "historical_blind_robustness_only": True,
            "aggregate_results_locked_until_all_50_complete": True,
            "calendar_2025_2026_locked": True,
        }
        return payload

    def case(self, requested_alias: str | None = None) -> dict[str, Any] | None:
        with self._lock:
            events = self._read_events()
            state = self._derive_state(events)
            if len(state["completed"]) == CASE_COUNT:
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
                raise ReplaySequenceError("The requested auction-validation session is unavailable")
            if active is not None and alias != active:
                raise ReplaySequenceError(f"Complete the active validation session first: {active}")
            snapshot = self._snapshot(self._by_alias[alias], state["cursors"][alias], state)
            return {"case": snapshot, "progress": self._status_from(events, state)}

    def submit_order(
        self, *, request: dict[str, Any], idempotency_key: str, recorded_at: str
    ) -> dict[str, Any]:
        annotation = request.get("annotation")
        if not isinstance(annotation, dict) or not REQUIRED_ANNOTATION_FIELDS.issubset(annotation):
            raise ReplayConflictError("The frozen coherent-auction classification is incomplete")
        if annotation.get("target_timeframe") != "H1_OPPOSING_LIQUIDITY":
            raise ReplayConflictError("The frozen target timeframe must be H1 opposing liquidity")
        with self._lock:
            events = self._read_events()
            alias = str(request.get("case_alias"))
            if any(
                event.get("case_alias") == alias and event.get("event_type") == "ORDER_SUBMITTED"
                for event in events
            ):
                raise ReplayConflictError("The frozen policy permits at most one order per session")
            return super().submit_order(
                request=deepcopy(request),
                idempotency_key=idempotency_key,
                recorded_at=recorded_at,
            )


@lru_cache(maxsize=1)
def get_coherent_auction_validation_service() -> CoherentAuctionValidationService:
    settings = get_settings()
    return CoherentAuctionValidationService(
        settings.coherent_auction_validation_artifact_path,
        ledger_path=settings.coherent_auction_validation_ledger_path,
    )
