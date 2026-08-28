from __future__ import annotations

import json
from pathlib import Path

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from gold_intel.api.routes import coherent_auction_validation
from gold_intel.application.blind_replay import ReplayConflictError
from gold_intel.application.coherent_auction_validation import (
    CoherentAuctionValidationService,
    get_coherent_auction_validation_service,
)

ROOT = Path(__file__).resolve().parents[3]
ARTIFACTS = ROOT / "research_artifacts" / "gold_coherent_auction_blind_validation_v1"


@pytest.fixture(scope="module")
def service(tmp_path_factory: pytest.TempPathFactory) -> CoherentAuctionValidationService:
    path = tmp_path_factory.mktemp("coherent-auction-validation") / "events.jsonl"
    return CoherentAuctionValidationService(ARTIFACTS, path)


def api(service: CoherentAuctionValidationService) -> TestClient:
    app = FastAPI()
    app.include_router(coherent_auction_validation.router, prefix="/api/v1")
    app.dependency_overrides[get_coherent_auction_validation_service] = lambda: service
    return TestClient(app)


def annotation() -> dict[str, object]:
    return {
        "thesis": "The completed auction response supports a long from this location.",
        "fundamental_direction": "BULLISH",
        "dominant_driver": "Falling real-yield pressure",
        "higher_timeframe_context": "H4 pullback retains room to opposing H1 liquidity.",
        "session_liquidity_context": "London response formed at pre-existing support.",
        "entry_trigger": "Completed M15 transition and first retest are visible.",
        "invalidation_logic": "Break of the active protected M15 swing invalidates the trade.",
        "target_logic": "Exit at the next opposing H1 liquidity area.",
        "event_risk": "No unresolved scheduled release inside the immediate entry window.",
        "confidence": 65,
        "auction_family": "CONTINUATION_WITH_ROOM",
        "controlling_h4_state": "PULLBACK_WITH_ROOM",
        "location_assessment": "DISCOUNT",
        "stop_basis": "ACTIVE_M15_PROTECTED_SWING",
        "target_timeframe": "H1_OPPOSING_LIQUIDITY",
        "macro_override_reason": "NOT_AGAINST_DISPLAYED_MACRO",
    }


def order(snapshot: dict[str, object], *, order_type: str = "LIMIT") -> dict[str, object]:
    charts = snapshot["charts"]
    assert isinstance(charts, dict)
    m1 = charts["1m"]
    assert isinstance(m1, list) and m1
    latest = float(m1[-1]["close"])
    entry = latest - 20 if order_type == "LIMIT" else latest
    stop = entry - 40
    target = entry + 60
    cursor = str(snapshot["cursor_at"])
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
        "drawings": [
            {
                "drawing_id": "position-1",
                "kind": "LONG_POSITION",
                "created_at_cursor": cursor,
                "anchors": [
                    {"anchor_at": cursor, "price": entry, "source_timeframe": "1m"},
                    {"anchor_at": cursor, "price": stop, "source_timeframe": "1m"},
                    {"anchor_at": cursor, "price": target, "source_timeframe": "1m"},
                ],
            }
        ],
        "annotation": annotation(),
    }


def test_certified_population_and_initial_snapshot_are_future_hidden(
    service: CoherentAuctionValidationService,
) -> None:
    status = service.status()
    assert status["practice_total"] == 50
    assert status["practice_completed"] == 0
    assert sum(row["session_code"] == "LONDON" for row in status["practice_cases"]) == 25
    assert sum(row["session_code"] == "NEW_YORK" for row in status["practice_cases"]) == 25
    assert status["calendar_2025"] == status["calendar_2026"] == "LOCKED"

    payload = service.case("GAV-2022-001")
    assert payload is not None
    snapshot = payload["case"]
    assert snapshot["mode"] == "BLIND_HISTORICAL_ROBUSTNESS"
    assert snapshot["cursor_at"] == snapshot["start_at"]
    assert snapshot["session_code"] in {"LONDON", "NEW_YORK"}
    for bars in snapshot["charts"].values():
        assert all(
            bar["close_at"] <= snapshot["cursor_at"]
            and bar["available_at"] <= snapshot["cursor_at"]
            for bar in bars
        )
    serialized = json.dumps(snapshot["context"])
    assert "fixed_horizon_reactions" not in serialized
    assert "subsequent_observation" not in serialized


def test_api_advances_one_way_and_enforces_one_order_per_session(
    service: CoherentAuctionValidationService,
) -> None:
    client = api(service)
    initial_response = client.get(
        "/api/v1/coherent-auction-validation/next?case_alias=GAV-2022-001"
    )
    assert initial_response.status_code == 200
    initial = initial_response.json()["case"]
    advanced = client.post(
        "/api/v1/coherent-auction-validation/advance",
        headers={"Idempotency-Key": "validation-advance-1"},
        json={
            "case_alias": initial["case_alias"],
            "expected_cursor_at": initial["cursor_at"],
            "increment_minutes": 5,
            "selected_timeframe": "15m",
        },
    )
    assert advanced.status_code == 200
    snapshot = advanced.json()["case"]
    assert snapshot["cursor_at"] > initial["cursor_at"]
    assert all(bar["close_at"] <= snapshot["cursor_at"] for bar in snapshot["charts"]["1m"])

    request = order(snapshot)
    submitted = service.submit_order(
        request=request,
        idempotency_key="validation-order-1",
        recorded_at="2026-08-20T00:00:00+00:00",
    )
    pending = submitted["case"]["live_order"]
    assert pending["state"] == "PENDING_ORDER"
    assert pending["risk_usd"] <= 50
    cancelled = service.cancel_order(
        order_id=pending["order_id"],
        request={
            "case_alias": snapshot["case_alias"],
            "expected_cursor_at": snapshot["cursor_at"],
            "client_visible_state_sha256": submitted["case"]["visible_state_sha256"],
            "reason": "The pending geometry no longer represents the original response.",
        },
        idempotency_key="validation-cancel-1",
        recorded_at="2026-08-20T00:00:01+00:00",
    )
    with pytest.raises(ReplayConflictError, match="at most one order"):
        service.submit_order(
            request=order(cancelled["case"]),
            idempotency_key="validation-order-2",
            recorded_at="2026-08-20T00:00:02+00:00",
        )


def test_api_rejects_incomplete_auction_classification(
    service: CoherentAuctionValidationService,
) -> None:
    snapshot = service.case("GAV-2022-001")
    assert snapshot is not None
    request = order(snapshot["case"])
    del request["annotation"]["stop_basis"]  # type: ignore[index]
    response = api(service).post(
        "/api/v1/coherent-auction-validation/orders",
        headers={"Idempotency-Key": "validation-invalid-classification"},
        json=request,
    )
    assert response.status_code == 422
