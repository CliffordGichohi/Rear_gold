"""Two-change mechanical correction for the sealed Auction Family Router V1."""

from __future__ import annotations

import copy
from typing import Any

from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash

MINIMUM_DELAYED_TARGET_ROOM_R = 1.5
CONTINUATION_FAMILY = "CONTINUATION_WITH_ROOM"


def corrected_router_lifecycle(lifecycle: dict[str, Any]) -> dict[str, Any]:
    """Apply only the frozen overlay removal and delayed-fill room gate."""

    source_hash = canonical_hash(lifecycle)
    pre_overlay = lifecycle.get("pre_overlay_result")
    family = lifecycle.get("family")
    geometry = lifecycle.get("geometry") or {}
    delayed = family not in {None, CONTINUATION_FAMILY}
    actual_fill_room = geometry.get("target_room_r")

    if pre_overlay is None or pre_overlay.get("executed") is not True:
        payload = {
            "admitted": False,
            "disposition": str(lifecycle.get("disposition", "NO_ROUTED_TRADE")),
            "family": family,
            "delayed": delayed,
            "actual_fill_target_room_r": actual_fill_room,
            "room_gate_passed": None,
            "break_even_overlay_used": False,
            "effective_result": None,
            "source_lifecycle_sha256": source_hash,
        }
    elif delayed and (
        actual_fill_room is None
        or float(actual_fill_room) < MINIMUM_DELAYED_TARGET_ROOM_R
    ):
        payload = {
            "admitted": False,
            "disposition": "DELAYED_ACTUAL_FILL_TARGET_ROOM_LT_1P5R",
            "family": family,
            "delayed": True,
            "actual_fill_target_room_r": actual_fill_room,
            "room_gate_passed": False,
            "break_even_overlay_used": False,
            "effective_result": None,
            "source_lifecycle_sha256": source_hash,
        }
    else:
        payload = {
            "admitted": True,
            "disposition": str(pre_overlay["resolution"]),
            "family": family,
            "delayed": delayed,
            "actual_fill_target_room_r": actual_fill_room,
            "room_gate_passed": True,
            "break_even_overlay_used": False,
            "effective_result": copy.deepcopy(pre_overlay),
            "source_lifecycle_sha256": source_hash,
        }
    payload["correction_sha256"] = canonical_hash(payload)
    return payload

