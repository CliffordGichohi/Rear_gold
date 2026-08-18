from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from gold_intel.api.blind_replay_v3_schemas import (
    ReplayV3AdvanceRequest,
    ReplayV3AmendRequest,
    ReplayV3CancelRequest,
    ReplayV3ManualCloseRequest,
    ReplayV3MutationResponse,
    ReplayV3OrderRequest,
    ReplayV3SkipRequest,
    ReplayV3SnapshotResponse,
    ReplayV3StatusResponse,
)
from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
)
from gold_intel.application.blind_replay_v3 import (
    AnnotatedReplayV3Service,
    get_annotated_replay_v3_service,
)

router = APIRouter(prefix="/blind-replay-v3", tags=["annotated trading replay"])
ReplayService = Annotated[AnnotatedReplayV3Service, Depends(get_annotated_replay_v3_service)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)]


def _error(exc: Exception) -> HTTPException:
    code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if isinstance(exc, ReplayIntegrityError)
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/status", response_model=ReplayV3StatusResponse)
def replay_status(service: ReplayService) -> ReplayV3StatusResponse:
    try:
        return ReplayV3StatusResponse.model_validate(service.status())
    except ReplayIntegrityError as exc:
        raise _error(exc) from exc


@router.get("/next", response_model=ReplayV3SnapshotResponse)
def next_practice_day(
    service: ReplayService,
    case_alias: Annotated[str | None, Query(pattern=r"^V3-P-\d{3}$")] = None,
) -> ReplayV3SnapshotResponse:
    try:
        payload = service.case(case_alias)
    except (ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="All twenty zero-credit V3 practice days are complete; collection remains closed",
        )
    return ReplayV3SnapshotResponse.model_validate(payload)


@router.post("/advance", response_model=ReplayV3MutationResponse)
def advance_cursor(
    request: ReplayV3AdvanceRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> ReplayV3MutationResponse:
    try:
        payload = service.advance(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return ReplayV3MutationResponse.model_validate(payload)


@router.post("/skip", response_model=ReplayV3MutationResponse)
def skip_interval(
    request: ReplayV3SkipRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> ReplayV3MutationResponse:
    try:
        payload = service.skip(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return ReplayV3MutationResponse.model_validate(payload)


@router.post("/orders", response_model=ReplayV3MutationResponse, status_code=201)
def submit_order(
    request: ReplayV3OrderRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> ReplayV3MutationResponse:
    try:
        payload = service.submit_order(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return ReplayV3MutationResponse.model_validate(payload)


@router.post("/orders/{order_id}/amend", response_model=ReplayV3MutationResponse)
def amend_order(
    order_id: str,
    request: ReplayV3AmendRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> ReplayV3MutationResponse:
    try:
        payload = service.amend_order(
            order_id=order_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return ReplayV3MutationResponse.model_validate(payload)


@router.post("/orders/{order_id}/cancel", response_model=ReplayV3MutationResponse)
def cancel_order(
    order_id: str,
    request: ReplayV3CancelRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> ReplayV3MutationResponse:
    try:
        payload = service.cancel_order(
            order_id=order_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return ReplayV3MutationResponse.model_validate(payload)


@router.post("/orders/{order_id}/manual-close", response_model=ReplayV3MutationResponse)
def manual_close(
    order_id: str,
    request: ReplayV3ManualCloseRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> ReplayV3MutationResponse:
    try:
        payload = service.manual_close(
            order_id=order_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return ReplayV3MutationResponse.model_validate(payload)
