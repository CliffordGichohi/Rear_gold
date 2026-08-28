from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from gold_intel.api.blind_replay_v3_schemas import (
    ReplayV3AdvanceRequest,
    ReplayV3AmendRequest,
    ReplayV3Annotation,
    ReplayV3CancelRequest,
    ReplayV3ManualCloseRequest,
    ReplayV3OrderRequest,
    ReplayV3SkipRequest,
)

ALIAS_PATTERN = r"^GAV-2022-\d{3}$"


class AuctionFamily(StrEnum):
    CONTINUATION_WITH_ROOM = "CONTINUATION_WITH_ROOM"
    RANGE_ROTATION = "RANGE_ROTATION"
    STRUCTURAL_REPAIR = "STRUCTURAL_REPAIR"
    OTHER_EXPLICIT = "OTHER_EXPLICIT"


class ControllingH4State(StrEnum):
    PULLBACK_WITH_ROOM = "PULLBACK_WITH_ROOM"
    BALANCE_LOWER_ROTATION = "BALANCE_LOWER_ROTATION"
    BALANCE_UPPER_ROTATION = "BALANCE_UPPER_ROTATION"
    UPPER_BOUNDARY_EXTENDED = "UPPER_BOUNDARY_EXTENDED"
    LOWER_BOUNDARY_EXTENDED = "LOWER_BOUNDARY_EXTENDED"
    BEARISH_DAMAGE = "BEARISH_DAMAGE"
    BULLISH_DAMAGE = "BULLISH_DAMAGE"
    ACCEPTED_REPAIR = "ACCEPTED_REPAIR"
    UNKNOWN = "UNKNOWN"


class LocationAssessment(StrEnum):
    DISCOUNT = "DISCOUNT"
    MIDRANGE = "MIDRANGE"
    PREMIUM = "PREMIUM"
    AT_SUPPORT = "AT_SUPPORT"
    AT_RESISTANCE = "AT_RESISTANCE"
    UNKNOWN = "UNKNOWN"


class StopBasis(StrEnum):
    ACTIVE_M15_PROTECTED_SWING = "ACTIVE_M15_PROTECTED_SWING"
    CONTROLLING_M15_RANGE_BOUNDARY = "CONTROLLING_M15_RANGE_BOUNDARY"
    POST_REPAIR_ORIGIN = "POST_REPAIR_ORIGIN"
    OTHER_EXPLICIT = "OTHER_EXPLICIT"


class CoherentAuctionAnnotation(ReplayV3Annotation):
    auction_family: AuctionFamily
    controlling_h4_state: ControllingH4State
    location_assessment: LocationAssessment
    stop_basis: StopBasis
    target_timeframe: str = Field(pattern=r"^H1_OPPOSING_LIQUIDITY$")
    macro_override_reason: str = Field(min_length=1, max_length=2000)


class CoherentAuctionAdvanceRequest(ReplayV3AdvanceRequest):
    case_alias: str = Field(pattern=ALIAS_PATTERN)


class CoherentAuctionSkipRequest(ReplayV3SkipRequest):
    case_alias: str = Field(pattern=ALIAS_PATTERN)


class CoherentAuctionOrderRequest(ReplayV3OrderRequest):
    case_alias: str = Field(pattern=ALIAS_PATTERN)
    annotation: CoherentAuctionAnnotation


class CoherentAuctionAmendRequest(ReplayV3AmendRequest):
    case_alias: str = Field(pattern=ALIAS_PATTERN)


class CoherentAuctionCancelRequest(ReplayV3CancelRequest):
    case_alias: str = Field(pattern=ALIAS_PATTERN)


class CoherentAuctionManualCloseRequest(ReplayV3ManualCloseRequest):
    case_alias: str = Field(pattern=ALIAS_PATTERN)


class CoherentAuctionStatusResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    protocol: str
    ready: bool
    phase: str
    practice_completed: int
    practice_total: int
    current_case_alias: str | None
    event_ledger_head_sha256: str
    collection_year: int
    collection_state: str
    calendar_2025: str
    calendar_2026: str
    research_credit: str
    practice_cases: list[dict[str, Any]]


class CoherentAuctionSnapshotResponse(BaseModel):
    case: dict[str, Any]
    progress: CoherentAuctionStatusResponse


class CoherentAuctionMutationResponse(BaseModel):
    event_sha256: str
    idempotent_replay: bool
    case: dict[str, Any] | None
    progress: CoherentAuctionStatusResponse
