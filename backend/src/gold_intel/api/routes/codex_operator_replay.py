from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, status

from gold_intel.api.codex_operator_replay_schemas import (
    CodexAdvanceRequest,
    CodexDecisionRequest,
    CodexInspectRequest,
    CodexReplayMutationResponse,
    CodexReplaySnapshotResponse,
    CodexReplayStatusResponse,
)
from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
)
from gold_intel.application.codex_operator_replay import (
    CodexOperatorReplayService,
    get_codex_operator_replay_service,
)


router = APIRouter(prefix="/codex-operator-replay-v1", tags=["blind Codex operator replay"])
ReplayService = Annotated[CodexOperatorReplayService, Depends(get_codex_operator_replay_service)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


def _error(exc: Exception) -> HTTPException:
    code = status.HTTP_503_SERVICE_UNAVAILABLE if isinstance(exc, ReplayIntegrityError) else status.HTTP_409_CONFLICT
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/status", response_model=CodexReplayStatusResponse)
def replay_status(service: ReplayService) -> CodexReplayStatusResponse:
    try:
        return CodexReplayStatusResponse.model_validate(service.status())
    except ReplayIntegrityError as exc:
        raise _error(exc) from exc


@router.get("/next", response_model=CodexReplaySnapshotResponse)
def next_case(service: ReplayService) -> CodexReplaySnapshotResponse:
    try:
        payload = service.case()
    except (ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    if payload is None:
        raise HTTPException(status_code=404, detail="All 249 Codex cases are terminal; outcomes remain sealed")
    return CodexReplaySnapshotResponse.model_validate(payload)


@router.post("/advance", response_model=CodexReplayMutationResponse)
def advance_cursor(
    request: CodexAdvanceRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CodexReplayMutationResponse:
    try:
        payload = service.advance(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CodexReplayMutationResponse.model_validate(payload)


@router.post("/inspect", response_model=CodexReplayMutationResponse)
def inspect_timeframe(
    request: CodexInspectRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CodexReplayMutationResponse:
    try:
        payload = service.inspect_timeframe(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CodexReplayMutationResponse.model_validate(payload)


@router.post("/decisions", response_model=CodexReplayMutationResponse, status_code=201)
def seal_decision(
    request: CodexDecisionRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CodexReplayMutationResponse:
    try:
        payload = service.decide(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CodexReplayMutationResponse.model_validate(payload)

