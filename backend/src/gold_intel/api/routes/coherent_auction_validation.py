from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status

from gold_intel.api.coherent_auction_validation_schemas import (
    ALIAS_PATTERN,
    CoherentAuctionAdvanceRequest,
    CoherentAuctionAmendRequest,
    CoherentAuctionCancelRequest,
    CoherentAuctionManualCloseRequest,
    CoherentAuctionMutationResponse,
    CoherentAuctionOrderRequest,
    CoherentAuctionSkipRequest,
    CoherentAuctionSnapshotResponse,
    CoherentAuctionStatusResponse,
)
from gold_intel.application.blind_replay import (
    ReplayConflictError,
    ReplayIntegrityError,
    ReplaySequenceError,
)
from gold_intel.application.coherent_auction_validation import (
    CoherentAuctionValidationService,
    get_coherent_auction_validation_service,
)

router = APIRouter(
    prefix="/coherent-auction-validation", tags=["coherent auction blind validation"]
)
ReplayService = Annotated[
    CoherentAuctionValidationService, Depends(get_coherent_auction_validation_service)
]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
]


def _error(exc: Exception) -> HTTPException:
    code = (
        status.HTTP_503_SERVICE_UNAVAILABLE
        if isinstance(exc, ReplayIntegrityError)
        else status.HTTP_409_CONFLICT
    )
    return HTTPException(status_code=code, detail=str(exc))


@router.get("/status", response_model=CoherentAuctionStatusResponse)
def replay_status(service: ReplayService) -> CoherentAuctionStatusResponse:
    try:
        return CoherentAuctionStatusResponse.model_validate(service.status())
    except ReplayIntegrityError as exc:
        raise _error(exc) from exc


@router.get("/next", response_model=CoherentAuctionSnapshotResponse)
def next_session(
    service: ReplayService,
    case_alias: Annotated[str | None, Query(pattern=ALIAS_PATTERN)] = None,
) -> CoherentAuctionSnapshotResponse:
    try:
        payload = service.case(case_alias)
    except (ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    if payload is None:
        raise HTTPException(
            status_code=404,
            detail="All fifty blind validation sessions are complete; aggregate results remain sealed",
        )
    return CoherentAuctionSnapshotResponse.model_validate(payload)


@router.post("/advance", response_model=CoherentAuctionMutationResponse)
def advance_cursor(
    request: CoherentAuctionAdvanceRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CoherentAuctionMutationResponse:
    try:
        payload = service.advance(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CoherentAuctionMutationResponse.model_validate(payload)


@router.post("/skip", response_model=CoherentAuctionMutationResponse)
def skip_interval(
    request: CoherentAuctionSkipRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CoherentAuctionMutationResponse:
    try:
        payload = service.skip(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CoherentAuctionMutationResponse.model_validate(payload)


@router.post("/orders", response_model=CoherentAuctionMutationResponse, status_code=201)
def submit_order(
    request: CoherentAuctionOrderRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CoherentAuctionMutationResponse:
    try:
        payload = service.submit_order(
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CoherentAuctionMutationResponse.model_validate(payload)


@router.post(
    "/orders/{order_id}/amend", response_model=CoherentAuctionMutationResponse
)
def amend_order(
    order_id: str,
    request: CoherentAuctionAmendRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CoherentAuctionMutationResponse:
    try:
        payload = service.amend_order(
            order_id=order_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CoherentAuctionMutationResponse.model_validate(payload)


@router.post(
    "/orders/{order_id}/cancel", response_model=CoherentAuctionMutationResponse
)
def cancel_order(
    order_id: str,
    request: CoherentAuctionCancelRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CoherentAuctionMutationResponse:
    try:
        payload = service.cancel_order(
            order_id=order_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CoherentAuctionMutationResponse.model_validate(payload)


@router.post(
    "/orders/{order_id}/manual-close", response_model=CoherentAuctionMutationResponse
)
def manual_close(
    order_id: str,
    request: CoherentAuctionManualCloseRequest,
    service: ReplayService,
    idempotency_key: IdempotencyKey,
) -> CoherentAuctionMutationResponse:
    try:
        payload = service.manual_close(
            order_id=order_id,
            request=request.model_dump(mode="json"),
            idempotency_key=idempotency_key,
            recorded_at=datetime.now(UTC).isoformat(),
        )
    except (ReplayConflictError, ReplaySequenceError, ReplayIntegrityError) as exc:
        raise _error(exc) from exc
    return CoherentAuctionMutationResponse.model_validate(payload)
