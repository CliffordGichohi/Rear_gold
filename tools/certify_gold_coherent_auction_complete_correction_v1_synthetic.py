"""Synthetic, outcome-free certification of the frozen correction policy."""

from __future__ import annotations

import hashlib
import json
import math
import sys
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend/src"))

from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    balance_boxes,
    canonical_hash,
    confirmed_swings,
    event_lock_state,
    level_lifecycle,
    simulate_policy_path,
    structural_breaks,
)


OUTPUT = ROOT / "research_artifacts/gold_coherent_auction_complete_correction_v1"
CERTIFICATION = OUTPUT / "synthetic_certification.json"
SEAL = OUTPUT / "synthetic_certification_seal.json"
MODULE = ROOT / "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py"
RULEBOOK = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_RULEBOOK_V1_DRAFT.md"
MAPPING = ROOT / "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_IMPLEMENTATION_MAPPING.md"


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def bar(
    opened: datetime,
    minutes: int,
    open_price: float,
    high: float,
    low: float,
    close: float,
    timeframe: str,
) -> dict[str, object]:
    closed = opened + timedelta(minutes=minutes)
    return {
        "open_at": opened.isoformat().replace("+00:00", "Z"),
        "close_at": closed.isoformat().replace("+00:00", "Z"),
        "available_at": closed.isoformat().replace("+00:00", "Z"),
        "open": open_price,
        "high": high,
        "low": low,
        "close": close,
        "complete": True,
        "timeframe": timeframe,
    }


def bars_from_centres(
    centres: list[float], *, start: datetime, minutes: int, timeframe: str
) -> list[dict[str, object]]:
    output = []
    prior = centres[0]
    for index, centre in enumerate(centres):
        output.append(
            bar(
                start + timedelta(minutes=minutes * index),
                minutes,
                prior,
                centre + 0.30,
                centre - 0.30,
                centre,
                timeframe,
            )
        )
        prior = centre
    return output


def certify() -> dict[str, object]:
    if CERTIFICATION.exists() or SEAL.exists():
        raise FileExistsError("Synthetic certification is append-only and already exists")
    checks: list[dict[str, object]] = []

    def record(name: str, condition: bool, evidence: object) -> None:
        if not condition:
            raise AssertionError(f"{name}: {evidence}")
        checks.append({"name": name, "status": "PASS", "evidence": evidence})

    start = datetime(2022, 1, 1, tzinfo=UTC)

    centres = [100.0 + (index % 3) * 0.05 for index in range(22)]
    centres[15] = 102.0
    rows = bars_from_centres(centres, start=start, minutes=15, timeframe="15m")
    _, early = confirmed_swings(rows, str(rows[16]["available_at"]), "M15")
    _, ready = confirmed_swings(rows, str(rows[17]["available_at"]), "M15")
    record(
        "FUTURE_SWING_UNAVAILABLE_UNTIL_SECOND_RIGHT_BAR",
        not any(item["pivot_index"] == 15 and item["kind"] == "HIGH" for item in early)
        and any(item["pivot_index"] == 15 and item["kind"] == "HIGH" for item in ready),
        {"early": len(early), "ready": len(ready)},
    )

    base = [99.5] * 14
    engaged_rows = bars_from_centres(base + [100.0], start=start, minutes=15, timeframe="15m")
    engaged_rows[-1]["high"] = 100.2
    engaged_rows[-1]["close"] = 99.9
    engaged = level_lifecycle(
        engaged_rows,
        level=100.0,
        known_at=engaged_rows[13]["available_at"],
        cutoff=engaged_rows[-1]["available_at"],
        direction="LONG",
    )
    consumed_rows = bars_from_centres(base + [100.8, 100.9], start=start, minutes=15, timeframe="15m")
    consumed = level_lifecycle(
        consumed_rows,
        level=100.0,
        known_at=consumed_rows[13]["available_at"],
        cutoff=consumed_rows[-1]["available_at"],
        direction="LONG",
    )
    reverse_rows = bars_from_centres(base + [100.8, 100.9, 99.0, 98.9], start=start, minutes=15, timeframe="15m")
    reactivated = level_lifecycle(
        reverse_rows,
        level=100.0,
        known_at=reverse_rows[13]["available_at"],
        cutoff=reverse_rows[-1]["available_at"],
        direction="LONG",
    )
    record(
        "LEVEL_LIFECYCLE_DISTINGUISHES_ENGAGED_CONSUMED_REACTIVATED",
        engaged["state"] == "ACTIVE_ENGAGED"
        and consumed["state"] == "CONSUMED_ACCEPTED"
        and reactivated["state"] == "REACTIVATED_REVERSE",
        {"engaged": engaged["state"], "consumed": consumed["state"], "reactivated": reactivated["state"]},
    )

    balance_centres = [100.0, 100.6, 101.0, 100.4, 99.5, 99.0, 99.6] * 6
    balance_rows = bars_from_centres(balance_centres, start=start, minutes=60, timeframe="1h")
    _, boxes = balance_boxes(balance_rows, balance_rows[-1]["available_at"], "H1")
    record(
        "FIXED_BALANCE_REQUIRES_CONFIRMED_TWO_SIDED_PIVOTS",
        bool(boxes) and all(box.high > box.low for box in boxes),
        {"boxes": len(boxes)},
    )

    break_centres = [100.0, 100.3, 100.7, 100.2, 99.6, 99.2, 99.8] * 3
    break_centres += [100.2, 100.5, 101.5, 102.5]
    long_rows = bars_from_centres(break_centres, start=start, minutes=15, timeframe="15m")
    short_rows = [
        {
            **row,
            "open": 200.0 - float(row["open"]),
            "high": 200.0 - float(row["low"]),
            "low": 200.0 - float(row["high"]),
            "close": 200.0 - float(row["close"]),
        }
        for row in long_rows
    ]
    long_breaks = structural_breaks(long_rows, long_rows[-1]["available_at"], "M15", "LONG")
    short_breaks = structural_breaks(short_rows, short_rows[-1]["available_at"], "M15", "SHORT")
    record(
        "LONG_SHORT_STRUCTURE_SYMMETRY",
        bool(long_breaks)
        and len(long_breaks) == len(short_breaks)
        and [item["break_at"] for item in long_breaks] == [item["break_at"] for item in short_breaks],
        {"long": len(long_breaks), "short": len(short_breaks)},
    )

    event_start = datetime(2022, 1, 1, 13, 0, tzinfo=UTC)
    m1 = bars_from_centres([100.0] * 70, start=event_start, minutes=1, timeframe="1m")
    m5 = bars_from_centres([100.0] * 20, start=event_start, minutes=5, timeframe="5m")
    event_at = event_start + timedelta(minutes=30)
    event_stream = {
        "timeframes": {"1m": m1, "5m": m5},
        "context_timeline": {
            "events": [
                {
                    "event_type": "CPI",
                    "event_code": "US_CPI",
                    "scheduled_at": event_at.isoformat().replace("+00:00", "Z"),
                    "released_at": event_at.isoformat().replace("+00:00", "Z"),
                    "event_available_at": event_at.isoformat().replace("+00:00", "Z"),
                }
            ]
        },
    }
    event_result = event_lock_state(
        event_stream, (event_at + timedelta(minutes=35)).isoformat(), "LONG"
    )
    record(
        "TIER1_EVENT_LOCK_REQUIRES_DIRECTIONAL_ACCEPTANCE_AND_RETEST",
        event_result["locked"] is True
        and event_result["reason"] == "TIER1_DIRECTIONAL_ACCEPTANCE_RETEST_MISSING",
        event_result,
    )

    history_start = start - timedelta(hours=8)
    sim_m15 = bars_from_centres([100.0] * 32, start=history_start, minutes=15, timeframe="15m")
    sim_m1 = bars_from_centres([100.0] * 60, start=start, minutes=1, timeframe="1m")
    sim_m1[2].update({"high": 102.2, "low": 99.8, "close": 102.0})
    sim_m1[20].update({"open": 102.2, "high": 104.2, "low": 102.0, "close": 104.0})
    sim_stream = {
        "end_exclusive": (start + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "timeframes": {"1m": sim_m1, "15m": sim_m15},
    }
    classification = {
        "admitted": True,
        "primary_disposition": "ADMIT",
        "classification_hash": "synthetic",
        "direction": "LONG",
        "fill": 100.0,
        "stop": 98.0,
        "target": 104.0,
        "first_realization": 102.0,
        "quantity_ounces": 10,
        "cost_per_ounce": 0.10,
        "thesis": "RANGE_ROTATION",
    }
    economic = simulate_policy_path(
        classification=classification,
        stream=sim_stream,
        fill_at=start.isoformat().replace("+00:00", "Z"),
    )
    record(
        "RANGE_PARTIAL_AND_FINAL_TARGET_LIFECYCLE",
        [leg["resolution"] for leg in economic["legs"]]
        == ["RANGE_MIDPOINT_REALIZATION", "RANGE_ROTATION_TARGET"]
        and sum(int(leg["quantity_ounces"]) for leg in economic["legs"]) == 10
        and math.isclose(float(economic["net_usd"]), 29.0, abs_tol=1e-9),
        economic,
    )

    record(
        "PRIMARY_REFERENCE_DETERMINISM",
        canonical_hash(economic)
        == canonical_hash(
            simulate_policy_path(
                classification=deepcopy(classification),
                stream=deepcopy(sim_stream),
                fill_at=start.isoformat().replace("+00:00", "Z"),
            )
        ),
        {"checksum": canonical_hash(economic)},
    )

    payload: dict[str, object] = {
        "version": "GOLD_COHERENT_AUCTION_COMPLETE_CORRECTION_V1_SYNTHETIC_CERTIFICATION_1_0",
        "status": "PASS_SYNTHETIC_POINT_IN_TIME_AND_LIFECYCLE_CERTIFICATION",
        "evidence_scope": "SYNTHETIC_ONLY_NO_MARKET_OUTCOMES",
        "module_sha256": sha256(MODULE),
        "approved_rulebook_sha256": sha256(RULEBOOK),
        "implementation_mapping_sha256": sha256(MAPPING),
        "checks": checks,
        "check_count": len(checks),
        "market_outcomes_opened": 0,
        "fresh_cases_opened": 0,
        "calendar_2025": "LOCKED",
        "calendar_2026": "LOCKED",
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def main() -> None:
    payload = certify()
    OUTPUT.mkdir(parents=True, exist_ok=True)
    CERTIFICATION.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    seal = {
        "status": payload["status"],
        "certification_path": str(CERTIFICATION.relative_to(ROOT)).replace("\\", "/"),
        "certification_sha256": sha256(CERTIFICATION),
        "payload_sha256": payload["payload_sha256"],
        "module_sha256": payload["module_sha256"],
        "rulebook_sha256": payload["approved_rulebook_sha256"],
        "mapping_sha256": payload["implementation_mapping_sha256"],
    }
    SEAL.write_text(json.dumps(seal, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": payload["status"], "checks": payload["check_count"], "seal": seal["certification_sha256"]}, sort_keys=True))


if __name__ == "__main__":
    main()

