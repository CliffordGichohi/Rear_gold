"""Pure direction-to-auction-control gate for the V2 exposed regression."""

from __future__ import annotations

from typing import Any, Literal

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash

Direction = Literal["LONG", "SHORT"]
ControlState = Literal[
    "BUYER_CONTROL", "SELLER_CONTROL", "CONFLICTED", "UNRESOLVED"
]

RULESET = "GOLD_DIRECTION_SYMMETRIC_AUCTION_CONTROL_ROUTER_V2"


def required_control(direction: Direction) -> ControlState:
    if direction == "LONG":
        return "BUYER_CONTROL"
    if direction == "SHORT":
        return "SELLER_CONTROL"
    raise ValueError(f"Unsupported direction: {direction}")


def route_candidate(
    *, candidate: dict[str, Any], control: dict[str, Any]
) -> dict[str, Any]:
    """Gate an existing candidate without changing any candidate field."""

    direction = candidate.get("direction")
    signal_at = candidate.get("signal_at")
    result = (candidate.get("corrected") or {}).get("effective_result")
    if signal_at is None or direction not in {"LONG", "SHORT"}:
        disposition = "NO_DIRECTIONAL_CANDIDATE"
        required = None
        admitted = False
    elif result is None or not result.get("executed"):
        disposition = f"SOURCE_NOT_EXECUTABLE::{candidate.get('disposition', 'UNKNOWN')}"
        required = required_control(direction)
        admitted = False
    else:
        required = required_control(direction)
        observed = control.get("state", "UNRESOLVED")
        admitted = observed == required
        disposition = "ADMIT_CONTROL_ALIGNED" if admitted else f"VETO_{observed}"
    payload: dict[str, Any] = {
        "ruleset": RULESET,
        "source_row_sha256": candidate.get("row_sha256"),
        "signal_at": signal_at,
        "direction": direction,
        "required_control": required,
        "observed_control": control,
        "source_disposition": candidate.get("disposition"),
        "admitted": admitted,
        "disposition": disposition,
        "effective_result": result if admitted else None,
    }
    payload["route_sha256"] = canonical_hash(payload)
    return payload


def earliest_trade(
    left: dict[str, Any] | None, right: dict[str, Any] | None
) -> dict[str, Any] | None:
    candidates = [row for row in (left, right) if row is not None]
    if not candidates:
        return None
    return min(
        candidates,
        key=lambda row: (
            str(row["fill_at"]),
            0 if row["direction"] == "LONG" else 1,
        ),
    )
