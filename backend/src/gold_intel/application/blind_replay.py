from __future__ import annotations

import gzip
import hashlib
import json
import os
import re
import threading
from functools import lru_cache
from pathlib import Path
from typing import Any

from gold_intel.config import get_settings

PROTOCOL = "GOLD_BLIND_DISCRETIONARY_REPLAY_V1_PROTOCOL_1_0"
GENESIS_HASH = "0" * 64
DATE_PATTERN = re.compile(r"\b20(?:21|22|23|24|25|26)-\d{2}-\d{2}\b")
TIMESTAMP_PATTERN = re.compile(
    r"\b20(?:21|22|23|24|25|26)[-.]\d{2}[-.]\d{2}[T ]\d{2}:\d{2}"
)


class ReplayError(RuntimeError):
    pass


class ReplayIntegrityError(ReplayError):
    pass


class ReplayConflictError(ReplayError):
    pass


class ReplaySequenceError(ReplayError):
    pass


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class BlindReplayService:
    """Serve certified past-only cases and lock decisions in a hash chain."""

    def __init__(self, artifact_path: Path) -> None:
        self.artifact_path = artifact_path.resolve()
        self.display_path = self.artifact_path / "display_payloads_v1_1.primary.jsonl.gz"
        self.reference_display_path = self.artifact_path / "display_payloads_v1_1.reference.jsonl.gz"
        self.practice_path = self.artifact_path / "practice_future_paths_v1_1.primary.jsonl.gz"
        self.reference_practice_path = self.artifact_path / "practice_future_paths_v1_1.reference.jsonl.gz"
        self.certification_path = self.artifact_path / "materialization_certification_v1_1.json"
        self.ledger_path = self.artifact_path / "decisions" / "decision_ledger_v1.jsonl"
        self._lock = threading.RLock()
        self._payloads, self._practice_paths = self._load_and_verify_inputs()
        self._payload_by_alias = {row["case_alias"]: row for row in self._payloads}

    def _load_jsonl_gzip(self, path: Path) -> list[dict[str, Any]]:
        rows: list[dict[str, Any]] = []
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                rows.append(json.loads(line))
        return rows

    def _load_and_verify_inputs(
        self,
    ) -> tuple[list[dict[str, Any]], dict[str, dict[str, Any]]]:
        required = (
            self.display_path,
            self.reference_display_path,
            self.practice_path,
            self.reference_practice_path,
            self.certification_path,
        )
        missing = [str(path) for path in required if not path.is_file()]
        if missing:
            raise ReplayIntegrityError(f"Certified replay inputs are missing: {missing}")
        certification = json.loads(self.certification_path.read_text(encoding="utf-8"))
        if certification.get("verdict") != "PASS_PAST_ONLY_DISPLAY_MATERIALIZATION_AMENDMENT_A":
            raise ReplayIntegrityError("Replay materialization did not pass")
        if not all(certification.get("gates", {}).values()):
            raise ReplayIntegrityError("At least one replay materialization gate failed")
        hashes = {
            self.display_path: certification["primary_payload_sha256"],
            self.reference_display_path: certification["reference_payload_sha256"],
            self.practice_path: certification["primary_practice_sha256"],
            self.reference_practice_path: certification["reference_practice_sha256"],
        }
        for path, expected in hashes.items():
            if sha256_file(path) != expected:
                raise ReplayIntegrityError(f"Certified replay input differs: {path.name}")
        if hashes[self.display_path] != hashes[self.reference_display_path]:
            raise ReplayIntegrityError("Primary/reference display files differ")
        if hashes[self.practice_path] != hashes[self.reference_practice_path]:
            raise ReplayIntegrityError("Primary/reference practice files differ")

        payloads = self._load_jsonl_gzip(self.display_path)
        if len(payloads) != 260:
            raise ReplayIntegrityError("Replay population must contain exactly 260 cases")
        aliases = [str(row.get("case_alias")) for row in payloads]
        if len(set(aliases)) != 260:
            raise ReplayIntegrityError("Replay case aliases are not unique")
        if aliases[:20] != [f"P-{index:03d}" for index in range(1, 21)]:
            raise ReplayIntegrityError("Practice aliases or order differ from the freeze")
        if aliases[20:] != [f"S-{index:03d}" for index in range(1, 241)]:
            raise ReplayIntegrityError("Scored aliases or order differ from the freeze")
        for index, row in enumerate(payloads, start=1):
            if int(row.get("global_sequence", 0)) != index:
                raise ReplayIntegrityError("Global replay order differs from the freeze")
            submitted_hash = row.get("payload_sha256")
            body = {key: value for key, value in row.items() if key != "payload_sha256"}
            if submitted_hash != canonical_hash(body):
                raise ReplayIntegrityError(f"Replay payload hash failed for {aliases[index - 1]}")
            serialized = canonical_bytes(row).decode("utf-8")
            if DATE_PATTERN.search(serialized) or TIMESTAMP_PATTERN.search(serialized):
                raise ReplayIntegrityError(f"Calendar information leaked in {aliases[index - 1]}")
            if row["mode"] == "SCORED" and row.get("chart_availability", {}).get("status") != "FULL_FROZEN_HISTORY":
                raise ReplayIntegrityError(f"Scored chart history is incomplete for {aliases[index - 1]}")

        practice_rows = self._load_jsonl_gzip(self.practice_path)
        if len(practice_rows) != 20:
            raise ReplayIntegrityError("Practice feedback file must contain exactly 20 cases")
        practice = {str(row["case_alias"]): row for row in practice_rows}
        if set(practice) != set(aliases[:20]):
            raise ReplayIntegrityError("Practice feedback aliases differ from the freeze")
        return payloads, practice

    def _read_ledger(self) -> list[dict[str, Any]]:
        if not self.ledger_path.exists():
            return []
        records: list[dict[str, Any]] = []
        prior = GENESIS_HASH
        seen_aliases: set[str] = set()
        seen_keys: set[str] = set()
        with self.ledger_path.open("r", encoding="utf-8") as handle:
            for sequence, line in enumerate(handle, start=1):
                try:
                    record = json.loads(line)
                except json.JSONDecodeError as exc:
                    raise ReplayIntegrityError("Decision ledger contains invalid JSON") from exc
                if int(record.get("ledger_sequence", 0)) != sequence:
                    raise ReplayIntegrityError("Decision ledger sequence is discontinuous")
                if record.get("prior_record_sha256") != prior:
                    raise ReplayIntegrityError("Decision ledger hash chain is broken")
                record_hash = record.get("record_sha256")
                body = {key: value for key, value in record.items() if key != "record_sha256"}
                if record_hash != canonical_hash(body):
                    raise ReplayIntegrityError("Decision ledger record hash is invalid")
                expected_alias = self._payloads[sequence - 1]["case_alias"] if sequence <= len(self._payloads) else None
                if record.get("case_alias") != expected_alias:
                    raise ReplayIntegrityError("Decision ledger does not follow frozen case order")
                if record["case_alias"] in seen_aliases or record["idempotency_key"] in seen_keys:
                    raise ReplayIntegrityError("Decision ledger contains duplicate identity")
                seen_aliases.add(record["case_alias"])
                seen_keys.add(record["idempotency_key"])
                prior = str(record_hash)
                records.append(record)
        return records

    def status(self) -> dict[str, Any]:
        with self._lock:
            records = self._read_ledger()
            practice_completed = min(len(records), 20)
            scored_completed = max(0, len(records) - 20)
            next_alias = self._payloads[len(records)]["case_alias"] if len(records) < 260 else None
            phase = "PRACTICE" if practice_completed < 20 else "SCORED" if scored_completed < 240 else "COMPLETE"
            return {
                "protocol": PROTOCOL,
                "ready": True,
                "phase": phase,
                "practice_completed": practice_completed,
                "practice_total": 20,
                "scored_completed": scored_completed,
                "scored_total": 240,
                "total_locked": len(records),
                "next_case_alias": next_alias,
                "ledger_head_sha256": records[-1]["record_sha256"] if records else GENESIS_HASH,
                "scored_outcomes_locked": scored_completed < 240,
                "research_status": "HUMAN_LABELING_REQUIRED_EDGE_NOT_EVALUATED",
            }

    def next_case(self) -> dict[str, Any] | None:
        with self._lock:
            records = self._read_ledger()
            if len(records) >= len(self._payloads):
                return None
            return {"case": self._payloads[len(records)], "progress": self.status()}

    def submit_decision(
        self,
        *,
        decision: dict[str, Any],
        idempotency_key: str,
        locked_at: str,
    ) -> dict[str, Any]:
        if not idempotency_key or len(idempotency_key) > 128:
            raise ReplayConflictError("Idempotency-Key must contain 1 through 128 characters")
        with self._lock:
            records = self._read_ledger()
            submission = {"case_alias": decision["case_alias"], "decision": decision}
            submission_hash = canonical_hash(submission)
            existing = next((row for row in records if row["idempotency_key"] == idempotency_key), None)
            if existing is not None:
                if existing["submission_sha256"] != submission_hash:
                    raise ReplayConflictError("Idempotency-Key was already used for another payload")
                return self._response(existing, idempotent=True)
            if len(records) >= len(self._payloads):
                raise ReplaySequenceError("All frozen replay cases are already locked")
            expected = self._payloads[len(records)]
            if decision["case_alias"] != expected["case_alias"]:
                raise ReplaySequenceError(
                    f"Only the next frozen case may be submitted: {expected['case_alias']}"
                )
            prior = records[-1]["record_sha256"] if records else GENESIS_HASH
            record: dict[str, Any] = {
                "version": "GOLD_BLIND_REPLAY_DECISION_RECORD_V1",
                "ledger_sequence": len(records) + 1,
                "case_alias": expected["case_alias"],
                "mode": expected["mode"],
                "mode_sequence": expected["mode_sequence"],
                "locked_at": locked_at,
                "idempotency_key": idempotency_key,
                "prior_record_sha256": prior,
                "submission_sha256": submission_hash,
                "decision": decision,
            }
            record["record_sha256"] = canonical_hash(record)
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            with self.ledger_path.open("a", encoding="utf-8", newline="\n") as handle:
                handle.write(canonical_bytes(record).decode("utf-8") + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            return self._response(record, idempotent=False)

    def _response(self, record: dict[str, Any], *, idempotent: bool) -> dict[str, Any]:
        feedback: dict[str, Any] | None = None
        if record["mode"] == "PRACTICE":
            feedback = {
                "case_alias": record["case_alias"],
                "status": "PRACTICE_PATH_REVEALED_ZERO_RESEARCH_CREDIT",
                "bars": self._practice_paths[record["case_alias"]]["bars"],
                "economic_result": "NOT_CALCULATED_DURING_PRELABEL_MILESTONE",
            }
        return {
            "locked": True,
            "idempotent_replay": idempotent,
            "record_sha256": record["record_sha256"],
            "case_alias": record["case_alias"],
            "mode": record["mode"],
            "progress": self.status(),
            "practice_feedback": feedback,
        }


@lru_cache(maxsize=1)
def get_blind_replay_service() -> BlindReplayService:
    return BlindReplayService(get_settings().blind_replay_artifact_path)

