from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gold_intel.api.routes import blind_replay_v3
from gold_intel.application.blind_replay import ReplayConflictError, ReplayIntegrityError
from gold_intel.application.blind_replay_v3 import (
    AnnotatedReplayV3Service,
    get_annotated_replay_v3_service,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "research_artifacts" / "gold_annotated_replay_v3"


@pytest.fixture
def service(tmp_path: Path) -> AnnotatedReplayV3Service:
    return AnnotatedReplayV3Service(ARTIFACTS, tmp_path / "isolated" / "events.jsonl")


def client(service: AnnotatedReplayV3Service) -> TestClient:
    app = FastAPI()
    app.include_router(blind_replay_v3.router, prefix="/api/v1")
    app.dependency_overrides[get_annotated_replay_v3_service] = lambda: service
    return TestClient(app)


def annotation() -> dict[str, object]:
    return {
        "thesis": "Completed structure and macro context justify this practice order now.",
        "fundamental_direction": "NEUTRAL_OR_CONFLICTED",
        "dominant_driver": "Real-yield and dollar context",
        "higher_timeframe_context": "The completed higher-timeframe structure is visible.",
        "session_liquidity_context": "The order is placed around a pre-existing liquidity level.",
        "entry_trigger": "A completed candle confirms the selected response.",
        "invalidation_logic": "The structural level beyond the stop invalidates the idea.",
        "target_logic": "The target is the next pre-existing liquidity objective.",
        "event_risk": "No unacknowledged event assumption.",
        "confidence": 65,
    }


def order_payload(snapshot: dict[str, object], *, order_type: str = "MARKET") -> dict[str, object]:
    charts = snapshot["charts"]
    assert isinstance(charts, dict)
    m1 = charts["1m"]
    assert isinstance(m1, list) and m1
    latest = float(m1[-1]["close"])
    entry = latest if order_type == "MARKET" else latest - 25
    stop = entry - 40
    target = entry + 40
    cursor = str(snapshot["cursor_at"])
    drawing = {
        "drawing_id": "position-1",
        "kind": "LONG_POSITION",
        "created_at_cursor": cursor,
        "anchors": [
            {"anchor_at": cursor, "price": entry, "source_timeframe": "1m"},
            {"anchor_at": cursor, "price": stop, "source_timeframe": "1m"},
            {"anchor_at": cursor, "price": target, "source_timeframe": "1m"},
        ],
    }
    return {
        "case_alias": snapshot["case_alias"],
        "expected_cursor_at": cursor,
        "selected_timeframe": "15m",
        "client_visible_state_sha256": snapshot["visible_state_sha256"],
        "direction": "LONG",
        "order_type": order_type,
        "entry": entry,
        "stop": stop,
        "target": target,
        "expiry_at": snapshot["end_at"],
        "drawings": [drawing],
        "annotation": annotation(),
    }


def test_practice_only_snapshot_hides_future_and_collection(
    service: AnnotatedReplayV3Service,
) -> None:
    status = service.status()
    assert status["practice_total"] == 20
    assert status["practice_completed"] == 0
    assert status["collection_year"] == 2022
    assert status["collection_state"] == "CLOSED_NOT_MATERIALIZED_OR_ACCESSIBLE"
    assert status["calendar_2025"] == status["calendar_2026"] == "LOCKED"

    payload = service.case("V3-P-001")
    assert payload is not None
    snapshot = payload["case"]
    cursor = snapshot["cursor_at"]
    assert cursor == snapshot["start_at"]
    for bars in snapshot["charts"].values():
        assert all(bar["close_at"] <= cursor and bar["available_at"] <= cursor for bar in bars)
    serialized = json.dumps(snapshot["context"])
    assert "fixed_horizon_reactions" not in serialized
    assert "reaction_snapshots" not in serialized
    assert "subsequent_observation" not in serialized


def test_cursor_is_one_way_idempotent_and_skip_is_durable(
    service: AnnotatedReplayV3Service,
) -> None:
    api = client(service)
    initial = api.get("/api/v1/blind-replay-v3/next?case_alias=V3-P-001").json()["case"]
    request = {
        "case_alias": "V3-P-001",
        "expected_cursor_at": initial["cursor_at"],
        "increment_minutes": 5,
        "selected_timeframe": "15m",
    }
    advanced = api.post(
        "/api/v1/blind-replay-v3/advance",
        headers={"Idempotency-Key": "advance-1"},
        json=request,
    )
    assert advanced.status_code == 200
    after = advanced.json()["case"]
    assert after["cursor_at"] > initial["cursor_at"]
    assert all(bar["close_at"] <= after["cursor_at"] for bar in after["charts"]["1m"])
    repeated = api.post(
        "/api/v1/blind-replay-v3/advance",
        headers={"Idempotency-Key": "advance-1"},
        json=request,
    )
    assert repeated.status_code == 200
    assert repeated.json()["idempotent_replay"] is True
    stale = api.post(
        "/api/v1/blind-replay-v3/advance",
        headers={"Idempotency-Key": "advance-stale"},
        json=request,
    )
    assert stale.status_code == 409
    assert "Stale replay cursor" in stale.json()["detail"]

    skip = api.post(
        "/api/v1/blind-replay-v3/skip",
        headers={"Idempotency-Key": "skip-to-hour"},
        json={
            "case_alias": "V3-P-001",
            "expected_cursor_at": after["cursor_at"],
            "target_cursor_at": "2021-08-02T01:00:00Z",
            "reason": "Initial practice time selection",
            "selected_timeframe": "15m",
        },
    )
    assert skip.status_code == 200
    assert skip.json()["case"]["cursor_at"] == "2021-08-02T01:00:00Z"
    ledger = service.event_ledger_path.read_text(encoding="utf-8")
    assert "INTERVAL_SKIPPED" in ledger
    assert "REVEALED_BUT_NOT_OBSERVED_IN_REAL_TIME" in ledger


def test_pending_amend_cancel_and_post_fill_geometry_lock(
    service: AnnotatedReplayV3Service,
) -> None:
    initial = service.case("V3-P-001")
    assert initial is not None
    snapshot = initial["case"]
    pending_request = order_payload(snapshot, order_type="LIMIT")
    submitted = service.submit_order(
        request=pending_request,
        idempotency_key="limit-submit",
        recorded_at="2026-08-14T00:00:00+00:00",
    )
    pending = submitted["case"]["live_order"]
    assert pending["state"] == "PENDING_ORDER"
    assert pending["quantity_ounces"] == 1

    amended_entry = float(pending["entry"]) - 1
    amended = service.amend_order(
        order_id=pending["order_id"],
        request={
            "case_alias": "V3-P-001",
            "expected_cursor_at": snapshot["cursor_at"],
            "client_visible_state_sha256": submitted["case"]["visible_state_sha256"],
            "order_type": "LIMIT",
            "entry": amended_entry,
            "stop": amended_entry - 40,
            "target": amended_entry + 40,
            "expiry_at": snapshot["end_at"],
            "drawings": [
                {
                    **pending_request["drawings"][0],
                    "anchors": [
                        {
                            "anchor_at": snapshot["cursor_at"],
                            "price": amended_entry,
                            "source_timeframe": "1m",
                        },
                        {
                            "anchor_at": snapshot["cursor_at"],
                            "price": amended_entry - 40,
                            "source_timeframe": "1m",
                        },
                        {
                            "anchor_at": snapshot["cursor_at"],
                            "price": amended_entry + 40,
                            "source_timeframe": "1m",
                        },
                    ],
                }
            ],
            "reason": "Moved before any fill at the current cursor",
        },
        idempotency_key="limit-amend",
        recorded_at="2026-08-14T00:00:01+00:00",
    )
    assert amended["case"]["live_order"]["entry"] == amended_entry
    assert amended["case"]["live_order"]["annotation"] == pending["annotation"]
    cancelled = service.cancel_order(
        order_id=pending["order_id"],
        request={
            "case_alias": "V3-P-001",
            "expected_cursor_at": snapshot["cursor_at"],
            "client_visible_state_sha256": amended["case"]["visible_state_sha256"],
            "reason": "Practice cancellation",
        },
        idempotency_key="limit-cancel",
        recorded_at="2026-08-14T00:00:02+00:00",
    )
    assert cancelled["case"]["live_order"] is None

    market_request = order_payload(cancelled["case"], order_type="MARKET")
    market = service.submit_order(
        request=market_request,
        idempotency_key="market-submit",
        recorded_at="2026-08-14T00:00:03+00:00",
    )
    current = market["case"]
    for index in range(1, 9):
        if current["live_order"] and current["live_order"]["state"] == "ACTIVE_POSITION":
            break
        advanced = service.advance(
            request={
                "case_alias": "V3-P-001",
                "expected_cursor_at": current["cursor_at"],
                "increment_minutes": 15,
                "selected_timeframe": "1m",
            },
            idempotency_key=f"market-advance-{index}",
            recorded_at=f"2026-08-14T00:01:{index:02d}+00:00",
        )
        current = advanced["case"]
    assert current["live_order"]["state"] == "ACTIVE_POSITION"
    active = current["live_order"]
    with pytest.raises(ReplayConflictError, match="active geometry is immutable"):
        service.amend_order(
            order_id=active["order_id"],
            request={
                "case_alias": "V3-P-001",
                "expected_cursor_at": current["cursor_at"],
                "client_visible_state_sha256": current["visible_state_sha256"],
                "order_type": "MARKET",
                "entry": active["entry"] + 1,
                "stop": active["stop"],
                "target": active["target"],
                "expiry_at": current["end_at"],
                "drawings": active["drawings"],
                "reason": "Forbidden after fill",
            },
            idempotency_key="forbidden-active-amend",
            recorded_at="2026-08-14T00:02:00+00:00",
        )
    closed = service.manual_close(
        order_id=active["order_id"],
        request={
            "case_alias": "V3-P-001",
            "expected_cursor_at": current["cursor_at"],
            "client_visible_state_sha256": current["visible_state_sha256"],
            "reason": "The observable premise no longer holds.",
        },
        idempotency_key="manual-close",
        recorded_at="2026-08-14T00:02:01+00:00",
    )
    resolved = closed["case"]["order_history"][-1]
    assert resolved["state"] == "RESOLVED"
    assert resolved["resolution"]["state"] == "MANUAL_CLOSE"
    assert resolved["entry"] == active["entry"]
    assert resolved["annotation"] == active["annotation"]


def test_hash_chain_tamper_is_detected(service: AnnotatedReplayV3Service) -> None:
    snapshot = service.case("V3-P-001")["case"]  # type: ignore[index]
    service.advance(
        request={
            "case_alias": "V3-P-001",
            "expected_cursor_at": snapshot["cursor_at"],
            "increment_minutes": 1,
            "selected_timeframe": "1m",
        },
        idempotency_key="tamper-source",
        recorded_at="2026-08-14T00:00:00+00:00",
    )
    record = json.loads(service.event_ledger_path.read_text(encoding="utf-8"))
    record["data"]["actual_increment_minutes"] = 99
    service.event_ledger_path.write_text(json.dumps(record) + "\n", encoding="utf-8")
    with pytest.raises(ReplayIntegrityError, match="record hash"):
        service.status()
