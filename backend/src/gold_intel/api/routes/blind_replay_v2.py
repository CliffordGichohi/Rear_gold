from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from gold_intel.api.blind_replay_v2_schemas import (
    BlindReplayV2AdvanceRequest,
    BlindReplayV2DecisionRequest,
    BlindReplayV2DecisionResponse,
    BlindReplayV2SnapshotResponse,
    BlindReplayV2StatusResponse,
)
from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
)
from gold_intel.application.blind_replay_v2 import (
    BlindReplayV2Service,
    get_blind_replay_v2_service,
)

router = APIRouter(prefix="/blind-replay-v2", tags=["blind synchronized setup replay"])
ReplayService = Annotated[BlindReplayV2Service, Depends(get_blind_replay_v2_service)]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
]


def _handle_error(exc: Exception) -> HTTPException:
    if isinstance(exc, ReplayIntegrityError):
        return HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc))
    return HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc))


@router.get("/status", response_model=BlindReplayV2StatusResponse)
def replay_status(service: ReplayService) -> BlindReplayV2StatusResponse:
    try:
        return BlindReplayV2StatusResponse.model_validate(service.status())
    except ReplayIntegrityError as exc:
        raise _handle_error(exc) from exc


@router.get("/next", response_model=BlindReplayV2SnapshotResponse)
def next_replay_case(service: ReplayService) -> BlindReplayV2SnapshotResponse:
    try:
        payload = service.next_case()
    except ReplayIntegrityError as exc:
        raise _handle_error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="V2 practice is complete; scored labeling remains closed",
        )
    return BlindReplayV2SnapshotResponse.model_validate(payload)


@router.post("/advance", response_model=BlindReplayV2SnapshotResponse)
def advance_replay_cursor(
    request: BlindReplayV2AdvanceRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> BlindReplayV2SnapshotResponse:
    try:
        payload = service.advance(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            advanced_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _handle_error(exc) from exc
    return BlindReplayV2SnapshotResponse.model_validate(payload)


@router.post(
    "/decisions",
    response_model=BlindReplayV2DecisionResponse,
    status_code=status.HTTP_201_CREATED,
)
def lock_replay_setup(
    request: BlindReplayV2DecisionRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> BlindReplayV2DecisionResponse:
    try:
        payload = service.submit_decision(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            locked_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _handle_error(exc) from exc
    return BlindReplayV2DecisionResponse.model_validate(payload)
