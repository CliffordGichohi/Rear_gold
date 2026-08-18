from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from gold_intel.api.blind_replay_schemas import (
    BlindReplayCaseResponse,
    BlindReplayDecisionRequest,
    BlindReplayDecisionResponse,
    BlindReplayStatusResponse,
)
from gold_intel.application.blind_replay import (
    BlindReplayService,
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
    get_blind_replay_service,
)

router = APIRouter(prefix="/blind-replay", tags=["blind discretionary replay"])
ReplayService = Annotated[BlindReplayService, Depends(get_blind_replay_service)]


@router.get("/status", response_model=BlindReplayStatusResponse)
def replay_status(service: ReplayService) -> BlindReplayStatusResponse:
    try:
        return BlindReplayStatusResponse.model_validate(service.status())
    except ReplayIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc


@router.get("/next", response_model=BlindReplayCaseResponse)
def next_replay_case(service: ReplayService) -> BlindReplayCaseResponse:
    try:
        payload = service.next_case()
    except ReplayIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    if payload is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Replay labeling is complete")
    return BlindReplayCaseResponse.model_validate(payload)


@router.post(
    "/decisions",
    response_model=BlindReplayDecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def lock_replay_decision(
    request: BlindReplayDecisionRequest,
    service: ReplayService,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> BlindReplayDecisionResponse:
    try:
        result = service.submit_decision(
            decision=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            locked_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError) as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except ReplayIntegrityError as exc:
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)) from exc
    return BlindReplayDecisionResponse.model_validate(result)
