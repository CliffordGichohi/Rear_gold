"""Supplemental synthetic proof for damage, balance routing and stop ownership."""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    _trigger_from_break_event,
    active_balance_candidates,
    canonical_hash,
    h4_damage_state,
    structural_breaks,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_complete_correction_v1"
RESULT = OUTPUT / "synthetic_certification_amendment_a.json"
SEAL = OUTPUT / "synthetic_certification_amendment_a_seal.json"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py"
PRIOR = OUTPUT / "synthetic_certification_seal.json"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bars(
    centres: list[float], start: datetime, minutes: int, timeframe: str
) -> list[dict[str, object]]:
    output = []
    for index, value in enumerate(centres):
        opened = start + timedelta(minutes=minutes * index)
        closed = opened + timedelta(minutes=minutes)
        output.append(
            {
                "open_at": opened.isoformat().replace("+00:00", "Z"),
                "close_at": closed.isoformat().replace("+00:00", "Z"),
                "available_at": closed.isoformat().replace("+00:00", "Z"),
                "open": value,
                "high": value + 0.30,
                "low": value - 0.30,
                "close": value,
                "complete": True,
                "timeframe": timeframe,
            }
        )
    return output


def main() -> None:
    if RESULT.exists() or SEAL.exists():
        raise FileExistsError("Supplemental synthetic certification already exists")
    prior = json.loads(PRIOR.read_text(encoding="utf-8"))
    if prior["module_sha256"] != sha256(MODULE):
        raise RuntimeError("Module changed after initial synthetic certification")
    checks: list[dict[str, object]] = []

    start = datetime(2022, 1, 1, tzinfo=UTC)
    centres = [100.0, 100.3, 100.7, 100.2, 99.6, 99.2, 99.8] * 3
    centres += [100.2, 100.5, 101.5, 102.5]
    h4 = bars(centres, start, 240, "4h")
    breaks = structural_breaks(h4, h4[-1]["available_at"], "H4", "LONG")
    if not breaks:
        raise AssertionError("Synthetic bullish H4 break missing")
    protected = float(breaks[-1]["protected_level"])
    opened = start + timedelta(minutes=240 * len(h4))
    closed = opened + timedelta(minutes=240)
    h4.append(
        {
            "open_at": opened.isoformat().replace("+00:00", "Z"),
            "close_at": closed.isoformat().replace("+00:00", "Z"),
            "available_at": closed.isoformat().replace("+00:00", "Z"),
            "open": 102.5,
            "high": 102.8,
            "low": protected - 3.3,
            "close": protected - 3.0,
            "complete": True,
            "timeframe": "4h",
        }
    )
    damage = h4_damage_state(
        {"timeframes": {"4h": h4}}, str(h4[-1]["available_at"]), "LONG"
    )
    if damage is None or damage["damage_type"] != "SINGLE_DISPLACEMENT":
        raise AssertionError(f"H4 damage precedence failed: {damage}")
    checks.append(
        {
            "name": "H4_DAMAGE_OVERRIDES_STALE_BULLISH_BREAK",
            "status": "PASS",
            "evidence": {
                "prior_bullish_break_at": breaks[-1]["break_at"],
                "damage_at": damage["damage_at"],
                "damage_type": damage["damage_type"],
            },
        }
    )

    balance_centres = [100.0, 100.6, 101.0, 100.4, 99.5, 99.0, 99.6] * 6
    h1 = bars(balance_centres, start, 60, "1h")
    m15_flat = bars([100.0] * 180, start, 15, "15m")
    interior = active_balance_candidates(
        {"timeframes": {"1h": h1, "15m": m15_flat}},
        str(h1[-1]["available_at"]),
        100.0,
        "LONG",
        ("H1",),
    )
    lower = active_balance_candidates(
        {"timeframes": {"1h": h1, "15m": m15_flat}},
        str(h1[-1]["available_at"]),
        99.0,
        "LONG",
        ("H1",),
    )
    breakout_m15 = bars([100.0] * 168 + [102.0, 102.0, 101.4, 101.8], start, 15, "15m")
    breakout = active_balance_candidates(
        {"timeframes": {"1h": h1, "15m": breakout_m15}},
        str(breakout_m15[-1]["available_at"]),
        101.8,
        "LONG",
        ("H1",),
    )
    if interior or not lower or not any(item["accepted_breakout"] is not None for item in breakout):
        raise AssertionError(
            {"interior": len(interior), "lower": len(lower), "breakout": len(breakout)}
        )
    checks.append(
        {
            "name": "BALANCE_INTERIOR_BOUNDARY_AND_ACCEPTED_BREAKOUT_ROUTE_DIFFERENTLY",
            "status": "PASS",
            "evidence": {
                "interior_controlling_boxes": 0,
                "lower_quartile_boxes": len(lower),
                "accepted_breakout_boxes": sum(
                    item["accepted_breakout"] is not None for item in breakout
                ),
            },
        }
    )

    m5 = bars([100.5] * 20, start, 5, "5m")
    m5[15].update({"low": 99.9, "high": 100.8, "close": 100.5})
    event = {
        "identity": "synthetic-m5-break",
        "break_at": m5[15]["open_at"],
        "broken_level": 100.0,
        "protected_level": 99.5,
        "origin_adverse": 99.7,
        "atr": 1.0,
    }
    balance = {
        "identity": "synthetic-m15-balance",
        "low": 98.0,
        "high": 102.0,
        "known_at": m5[13]["available_at"],
    }
    trigger = _trigger_from_break_event(
        event=event,
        stream={"timeframes": {"5m": m5}},
        decision_at=str(m5[-1]["available_at"]),
        direction="LONG",
        family="M5_INTERNAL_ROTATION_IN_M15_BALANCE",
        controlling_balance=balance,
    )
    if trigger is None or float(trigger["stop_reference"]) != 98.0:
        raise AssertionError(f"Internal M5 trigger inherited wrong stop: {trigger}")
    checks.append(
        {
            "name": "M5_INTERNAL_ROTATION_INHERITS_M15_BALANCE_INVALIDATION",
            "status": "PASS",
            "evidence": {
                "m5_protected": 99.5,
                "m15_balance_boundary": 98.0,
                "selected_stop_reference": trigger["stop_reference"],
            },
        }
    )

    payload = {
        "version": "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_SYNTHETIC_AMENDMENT_A_1_0",
        "status": "PASS_SUPPLEMENTAL_SYNTHETIC_CLASSIFIER_CERTIFICATION",
        "prior_certification_sha256": prior["certification_sha256"],
        "module_sha256": sha256(MODULE),
        "checks": checks,
        "check_count": len(checks),
        "market_outcomes_opened": 0,
        "fresh_cases_opened": 0,
    }
    payload["payload_sha256"] = canonical_hash(payload)
    OUTPUT.mkdir(parents=True, exist_ok=True)
    RESULT.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": payload["status"],
        "result_sha256": sha256(RESULT),
        "payload_sha256": payload["payload_sha256"],
        "module_sha256": payload["module_sha256"],
        "prior_certification_sha256": payload["prior_certification_sha256"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "checks": len(checks), "seal": seal["result_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()

