from __future__ import annotations

import gzip
import json
import shutil
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from gold_intel.api.blind_replay_schemas import BlindReplayDecisionRequest
from gold_intel.api.routes import blind_replay
from gold_intel.application.blind_replay import (
    BlindReplayService,
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
    canonical_bytes,
    canonical_hash,
    get_blind_replay_service,
    sha256_file,
)


def _write_gzip(path: Path, rows: list[dict[str, object]]) -> None:
    with gzip.open(path, "wt", encoding="utf-8") as handle:
        for row in rows:
            handle.write(canonical_bytes(row).decode("utf-8") + "\n")


def _artifacts(tmp_path: Path) -> Path:
    rows: list[dict[str, object]] = []
    for index in range(1, 261):
        practice = index <= 20
        mode_sequence = index if practice else index - 20
        alias = f"P-{mode_sequence:03d}" if practice else f"S-{mode_sequence:03d}"
        row: dict[str, object] = {
            "case_alias": alias,
            "mode": "PRACTICE" if practice else "SCORED",
            "mode_sequence": mode_sequence,
            "global_sequence": index,
            "session_code": "LONDON" if index % 2 else "NEW_YORK",
            "chart_availability": {
                "status": "FULL_FROZEN_HISTORY",
                "counts": {"1w": 52, "1d": 120},
            },
            "display_policy": {
                "absolute_date_hidden": True,
                "absolute_time_hidden": True,
                "absolute_price_hidden": True,
                "completed_candles_only": True,
                "future_scored_path_present": False,
            },
            "reference_index": 100.0,
        }
        row["payload_sha256"] = canonical_hash(row)
        rows.append(row)

    display = tmp_path / "display_payloads_v1_1.primary.jsonl.gz"
    display_reference = tmp_path / "display_payloads_v1_1.reference.jsonl.gz"
    _write_gzip(display, rows)
    shutil.copyfile(display, display_reference)
    practice = [
        {
            "case_alias": f"P-{index:03d}",
            "mode": "PRACTICE",
            "bars": [{"minutes_after_checkpoint": 1, "open": 100, "high": 101, "low": 99, "close": 100.5}],
        }
        for index in range(1, 21)
    ]
    practice_path = tmp_path / "practice_future_paths_v1_1.primary.jsonl.gz"
    practice_reference = tmp_path / "practice_future_paths_v1_1.reference.jsonl.gz"
    _write_gzip(practice_path, practice)
    shutil.copyfile(practice_path, practice_reference)
    certification = {
        "verdict": "PASS_PAST_ONLY_DISPLAY_MATERIALIZATION_AMENDMENT_A",
        "gates": {"independent_reproduction": True, "no_scored_future": True},
        "primary_payload_sha256": sha256_file(display),
        "reference_payload_sha256": sha256_file(display_reference),
        "primary_practice_sha256": sha256_file(practice_path),
        "reference_practice_sha256": sha256_file(practice_reference),
    }
    (tmp_path / "materialization_certification_v1_1.json").write_text(
        json.dumps(certification), encoding="utf-8"
    )
    return tmp_path


def _no_trade(alias: str) -> dict[str, object]:
    return {
        "case_alias": alias,
        "action": "NO_TRADE",
        "confidence": 70,
        "entry_trigger": None,
        "entry_offset_atr": None,
        "stop_distance_atr": None,
        "target_r": None,
        "evidence_codes": ["OTHER"],
        "thesis": "No directional advantage",
        "trigger_condition": "No valid trigger exists",
        "invalidation": "A later signal would change the view",
        "target_explanation": "No target because this is an abstention",
    }


def test_decision_schema_enforces_directional_geometry() -> None:
    valid = BlindReplayDecisionRequest.model_validate(
        {
            **_no_trade("P-001"),
            "action": "LONG",
            "entry_trigger": "PULLBACK_LIMIT",
            "entry_offset_atr": -0.5,
            "stop_distance_atr": 1.0,
            "target_r": 2.0,
        }
    )
    assert valid.entry_offset_atr == -0.5
    with pytest.raises(ValidationError, match="LONG PULLBACK_LIMIT"):
        BlindReplayDecisionRequest.model_validate(
            {
                **valid.model_dump(mode="json"),
                "entry_offset_atr": 0.5,
            }
        )
    with pytest.raises(ValidationError, match="NO_TRADE requires"):
        BlindReplayDecisionRequest.model_validate(
            {**_no_trade("P-001"), "entry_trigger": "MARKET"}
        )


def test_service_is_sequential_idempotent_and_append_only(tmp_path: Path) -> None:
    service = BlindReplayService(_artifacts(tmp_path))
    assert service.status()["next_case_alias"] == "P-001"
    assert service.next_case()["case"]["case_alias"] == "P-001"  # type: ignore[index]

    first = service.submit_decision(
        decision=_no_trade("P-001"),
        idempotency_key="decision-1",
        locked_at="lock-1",
    )
    assert first["locked"] is True
    assert first["practice_feedback"]["case_alias"] == "P-001"
    replayed = service.submit_decision(
        decision=_no_trade("P-001"),
        idempotency_key="decision-1",
        locked_at="ignored-on-replay",
    )
    assert replayed["idempotent_replay"] is True
    assert replayed["record_sha256"] == first["record_sha256"]
    assert len(service.ledger_path.read_text(encoding="utf-8").splitlines()) == 1

    with pytest.raises(ReplayConflictError):
        service.submit_decision(
            decision={**_no_trade("P-001"), "confidence": 71},
            idempotency_key="decision-1",
            locked_at="lock-2",
        )
    with pytest.raises(ReplaySequenceError, match="P-002"):
        service.submit_decision(
            decision=_no_trade("P-003"),
            idempotency_key="decision-3",
            locked_at="lock-3",
        )


def test_service_detects_ledger_tampering(tmp_path: Path) -> None:
    service = BlindReplayService(_artifacts(tmp_path))
    service.submit_decision(
        decision=_no_trade("P-001"), idempotency_key="one", locked_at="lock"
    )
    content = service.ledger_path.read_text(encoding="utf-8")
    service.ledger_path.write_text(content.replace("NO_TRADE", "LONG", 1), encoding="utf-8")
    with pytest.raises(ReplayIntegrityError, match="record hash"):
        service.status()


def test_api_never_returns_scored_outcomes_and_requires_idempotency(tmp_path: Path) -> None:
    service = BlindReplayService(_artifacts(tmp_path))
    app = FastAPI()
    app.include_router(blind_replay.router, prefix="/api/v1")
    app.dependency_overrides[get_blind_replay_service] = lambda: service
    client = TestClient(app)

    response = client.get("/api/v1/blind-replay/next")
    assert response.status_code == 200
    assert response.json()["case"]["case_alias"] == "P-001"
    assert response.json()["case"]["display_policy"]["future_scored_path_present"] is False
    assert "practice_feedback" not in response.json()
    assert client.post("/api/v1/blind-replay/decisions", json=_no_trade("P-001")).status_code == 422
    locked = client.post(
        "/api/v1/blind-replay/decisions",
        headers={"Idempotency-Key": "api-one"},
        json=_no_trade("P-001"),
    )
    assert locked.status_code == 201
    assert locked.json()["practice_feedback"]["case_alias"] == "P-001"
