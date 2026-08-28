#!/usr/bin/env python3
"""Raw-stream-only autonomous inference for the same-month translation audit.

This process deliberately contains no path to the human decision ledger,
matched classifications, prior signal timestamps, or outcome ledger.
"""

from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_coherent_auction_end_to_end_v1_common import (  # noqa: E402
    load_certified_streams,
    materialize_case,
    predict_class,
    predict_class_probability,
    predict_regression,
    prepare_features,
    require,
    sha256_file,
    transform_rows,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
    h4_damage_state,
    iso,
    parse_dt,
)
from gold_intel.analytics.coherent_auction_human_policy_v2 import (  # noqa: E402
    RISK_BUDGET_USD,
    active_m15_directional_structure,
    contextual_veto_codes,
    event_lock_state,
    h4_context_metrics,
    macro_state,
    simulate_track,
)


CONTRACT = ROOT / "GOLD_COHERENT_AUCTION_END_TO_END_SAME_MONTH_REPLICATION_V1.md"
CONTRACT_SHA256 = "8a3d3301ec5f382dc378e7554d313b95657a00adeaeb17826e5edf7b677fcd39"
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
TRANSLATOR_SHA256 = "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841"
CERTIFICATION = (
    ROOT
    / "research_artifacts"
    / "gold_matched_human_replay_v1"
    / "stream_materialization_certification.json"
)
OUT = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
)
PRIMARY = OUT / "autonomous_primary.json"
REFERENCE = OUT / "autonomous_reference.json"
RESULT = OUT / "autonomous_result.json"
SLIPPAGE_USD_PER_OUNCE = 0.05
SPREAD_FALLBACK = 0.20


def spread(row: dict[str, Any]) -> float:
    value = row.get("spread_price")
    if value is None:
        return SPREAD_FALLBACK
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else SPREAD_FALLBACK


def first_m1_after(stream: dict[str, Any], checkpoint_at: str) -> dict[str, Any] | None:
    point = parse_dt(checkpoint_at)
    return next(
        (
            row
            for row in complete_rows(
                stream["timeframes"]["1m"], stream["end_exclusive"]
            )
            if parse_dt(row["open_at"]) > point
        ),
        None,
    )


def latest_m1_at(stream: dict[str, Any], checkpoint_at: str) -> dict[str, Any] | None:
    eligible = complete_rows(stream["timeframes"]["1m"], checkpoint_at)
    return eligible[-1] if eligible else None


def classify_autonomous(
    *,
    stream: dict[str, Any],
    signal_at: str,
    family: str,
    fill: float,
    stop: float,
    target: float,
    cost_per_ounce: float,
) -> dict[str, Any]:
    h4 = h4_context_metrics(stream, signal_at, "LONG")
    m15 = active_m15_directional_structure(stream, signal_at, "LONG")
    event = event_lock_state(stream, signal_at, "LONG")
    macro = macro_state(stream, signal_at, "LONG")
    damage = h4_damage_state(stream, signal_at, "LONG")
    blockers: list[dict[str, Any]] = []
    geometry_valid = (
        math.isfinite(fill)
        and math.isfinite(stop)
        and math.isfinite(target)
        and math.isfinite(cost_per_ounce)
        and stop < fill < target
    )
    planned_loss_per_ounce = fill - stop + cost_per_ounce if geometry_valid else math.inf
    quantity = (
        math.floor(RISK_BUDGET_USD / planned_loss_per_ounce)
        if geometry_valid and planned_loss_per_ounce > 0
        else 0
    )
    if not geometry_valid or not h4["available"] or quantity < 1:
        blockers.append(
            {
                "gate": 1,
                "code": "GEOMETRY_OR_REQUIRED_CONTEXT_UNAVAILABLE",
                "evidence": {
                    "geometry_valid": geometry_valid,
                    "h4_available": h4["available"],
                    "quantity_ounces": quantity,
                },
            }
        )
    gate_by_code = {
        "NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE": 2,
        "UNRESOLVED_TIER1_EVENT_AUCTION": 3,
        "EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION": 4,
        "SEVERE_OPPOSING_HTF_IMPULSE": 5,
        "HTF_PREMIUM_RANGE_ROTATION_CONFLICT": 6,
    }
    for code in contextual_veto_codes(
        family=family, h4=h4, m15=m15, event=event, damage=damage
    ):
        evidence: Any = h4
        if code == "NO_ACTIVE_M15_DIRECTIONAL_STRUCTURE":
            evidence = m15
        elif code == "UNRESOLVED_TIER1_EVENT_AUCTION":
            evidence = event
        elif code == "SEVERE_OPPOSING_HTF_IMPULSE":
            evidence = {"h4": h4, "damage": damage}
        blockers.append(
            {"gate": gate_by_code[code], "code": code, "evidence": evidence}
        )
    warnings: list[str] = []
    if macro["state"] in {"OPPOSED", "UNKNOWN"}:
        warnings.append(f"MACRO_{macro['state']}")
    if damage is not None and not any(
        row["code"] == "SEVERE_OPPOSING_HTF_IMPULSE" for row in blockers
    ):
        warnings.append("BOUNDED_STRUCTURAL_REPAIR_ONLY")
    signed_location = h4.get("signed_range_location")
    if (
        signed_location is not None
        and signed_location >= 0.80
        and not any(
            row["code"] == "EXTREME_HTF_EXTENSION_INTO_OPPOSING_AUCTION"
            for row in blockers
        )
    ):
        warnings.append("HIGH_HTF_LOCATION_WITHOUT_EXTENSION_CONJUNCTION")
    blockers.sort(key=lambda row: (int(row["gate"]), str(row["code"])))
    admitted = not blockers
    result = {
        "ruleset": "AUTONOMOUS_TRANSLATOR_PLUS_FROZEN_HUMAN_POLICY_V2",
        "decision_at": signal_at,
        "direction": "LONG",
        "family": family,
        "admitted": admitted,
        "primary_disposition": "ADMIT" if admitted else blockers[0]["code"],
        "blockers": blockers,
        "warnings": sorted(warnings),
        "macro": macro,
        "event": event,
        "h4": h4,
        "h4_damage": damage,
        "m15_structure": m15,
        "fill": fill,
        "stop": stop,
        "target": target,
        "structural_price_risk_per_ounce": abs(fill - stop),
        "cost_per_ounce": cost_per_ounce,
        "planned_loss_per_ounce": planned_loss_per_ounce,
        "quantity_ounces": quantity,
        "classification_hash": None,
    }
    result["classification_hash"] = canonical_hash(
        {key: value for key, value in result.items() if key != "classification_hash"}
    )
    return result


def summarize(rows: list[dict[str, Any]]) -> dict[str, Any]:
    signals = [row for row in rows if row["signal_at"] is not None]
    admitted = [row for row in signals if row["classification"]["admitted"]]
    results = [row["result"] for row in admitted]
    net = [float(row["net_r50"]) for row in results]
    wins = [value for value in net if value > 1e-12]
    losses = [value for value in net if value < -1e-12]
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in net:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "cases": len(rows),
        "signal_days": len(signals),
        "no_signal_days": len(rows) - len(signals),
        "admitted": len(admitted),
        "rejected": len(signals) - len(admitted),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(results) - len(wins) - len(losses),
        "win_rate": len(wins) / len(results) if results else None,
        "net_r50": sum(net),
        "net_usd": sum(float(row["net_usd"]) for row in results),
        "profit_factor": (
            sum(wins) / abs(sum(losses)) if losses else math.inf if wins else None
        ),
        "maximum_drawdown_r50": drawdown,
        "decision_set_sha256": canonical_hash(
            [
                {
                    "case_alias": row["case_alias"],
                    "signal_at": row["signal_at"],
                    "classification_hash": (
                        row["classification"]["classification_hash"]
                        if row["classification"] is not None
                        else None
                    ),
                    "result_hash": (
                        row["result"]["result_hash"]
                        if row["result"] is not None
                        else None
                    ),
                }
                for row in rows
            ]
        ),
    }


def infer(side: str, translator: dict[str, Any]) -> dict[str, Any]:
    streams, lineage = load_certified_streams(CERTIFICATION, side)
    prepared = prepare_features(streams.values())
    rows: list[dict[str, Any]] = []
    semantic = translator["semantic"]
    geometry = translator["geometry"]
    schema = translator["preprocessing"]
    for alias in sorted(streams):
        stream = streams[alias]
        checkpoints = materialize_case(
            alias=alias, stream=stream, prepared=prepared, end_at=None
        )
        signal_row: dict[str, Any] | None = None
        signal_probability: float | None = None
        for checkpoint in checkpoints:
            matrix = transform_rows([checkpoint], schema)
            probability = float(
                predict_class_probability(
                    semantic["tree"], matrix, positive_class=1
                )[0]
            )
            if probability >= float(semantic["threshold"]):
                signal_row = checkpoint
                signal_probability = probability
                break
        if signal_row is None:
            row = {
                "case_alias": alias,
                "trading_date_utc": stream["trading_date_utc"],
                "signal_at": None,
                "signal_probability": None,
                "classification": None,
                "result": None,
            }
            row["row_sha256"] = canonical_hash(row)
            rows.append(row)
            continue

        matrix = transform_rows([signal_row], schema)
        stop_distance = float(
            predict_regression(geometry["stop_distance_tree"], matrix)[0]
        )
        target_distance = float(
            predict_regression(geometry["target_distance_tree"], matrix)[0]
        )
        family = str(predict_class(geometry["family_tree"], matrix)[0])
        reference_close = float(signal_row["m1_reference_close"])
        m15_atr = float(signal_row["m15_atr_scale"])
        stop = reference_close - stop_distance * m15_atr
        target = reference_close + target_distance * m15_atr
        signal_at = str(signal_row["checkpoint_at"])
        fill_bar = first_m1_after(stream, signal_at)
        decision_bar = latest_m1_at(stream, signal_at)
        if fill_bar is None or decision_bar is None:
            raise RuntimeError(f"Execution bar unavailable: {alias}")
        fill = (
            float(fill_bar["open"])
            + spread(fill_bar) / 2.0
            + SLIPPAGE_USD_PER_OUNCE
        )
        cost_per_ounce = spread(decision_bar) + 2.0 * SLIPPAGE_USD_PER_OUNCE
        classification = classify_autonomous(
            stream=stream,
            signal_at=signal_at,
            family=family,
            fill=fill,
            stop=stop,
            target=target,
            cost_per_ounce=cost_per_ounce,
        )
        result = simulate_track(
            classification=classification,
            stream=stream,
            fill_at=iso(fill_bar["open_at"]),
            track="COMPLETE_V2_POLICY",
        )
        row = {
            "case_alias": alias,
            "trading_date_utc": stream["trading_date_utc"],
            "signal_at": signal_at,
            "signal_probability": signal_probability,
            "geometry": {
                "reference_close": reference_close,
                "m15_atr": m15_atr,
                "stop_distance_atr": stop_distance,
                "target_distance_atr": target_distance,
                "family": family,
                "fill_at": iso(fill_bar["open_at"]),
                "fill": fill,
                "stop": stop,
                "target": target,
                "cost_per_ounce": cost_per_ounce,
            },
            "classification": classification,
            "result": result,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
    output = {
        "version": "GOLD_COHERENT_AUCTION_END_TO_END_AUTONOMOUS_INFERENCE_V1_1_0",
        "side": side,
        "contract_sha256": CONTRACT_SHA256,
        "translator_sha256": TRANSLATOR_SHA256,
        "source_lineage_sha256": canonical_hash(lineage),
        "rows": rows,
        "summary": summarize(rows),
        "human_ledger_opened": False,
        "human_classification_opened": False,
        "stored_signal_registry_opened": False,
        "outcome_ledger_opened": False,
        "postdecision_stream_paths_opened": True,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    output["payload_sha256"] = canonical_hash(output)
    return output


def main() -> None:
    require(sha256_file(CONTRACT) == CONTRACT_SHA256, "Frozen contract changed")
    require(sha256_file(TRANSLATOR) == TRANSLATOR_SHA256, "Translator seal changed")
    translator = json.loads(TRANSLATOR.read_text(encoding="utf-8"))
    require(
        translator["status"] == "PASS_PREPATH_TRANSLATOR_FREEZE",
        "Translator did not pass pre-path gates",
    )
    primary = infer("primary", translator)
    reference = infer("reference", translator)
    require(
        primary["rows"] == reference["rows"],
        "Primary/reference autonomous decisions or results differ",
    )
    require(primary["summary"] == reference["summary"], "Summary differs")
    OUT.mkdir(parents=True, exist_ok=True)
    PRIMARY.write_text(
        json.dumps(primary, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    REFERENCE.write_text(
        json.dumps(reference, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    result = dict(primary)
    result["version"] = "GOLD_COHERENT_AUCTION_END_TO_END_AUTONOMOUS_RESULT_V1_1_0"
    result["side"] = "PRIMARY_REFERENCE_EXACT"
    result["primary_sha256"] = sha256_file(PRIMARY)
    result["reference_sha256"] = sha256_file(REFERENCE)
    result["primary_reference_exact_rows"] = True
    result["payload_sha256"] = canonical_hash(
        {key: value for key, value in result.items() if key != "payload_sha256"}
    )
    RESULT.write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    print(json.dumps(result["summary"], indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
