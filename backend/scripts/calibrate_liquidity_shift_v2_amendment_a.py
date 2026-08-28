from __future__ import annotations

import argparse
import asyncio
import json
from collections import Counter
from dataclasses import asdict, replace
from pathlib import Path
from typing import Any

from calibrate_liquidity_shift_v2_matched_replay import (
    EXPECTED_CASES,
    aggregate_study_inputs,
    calibrate,
    canonical_hash,
    load_minutes,
    read_json,
    read_jsonl,
    sha256_file,
    verify_chain,
    verify_config,
    verify_freeze,
    write_csv_exclusive,
    write_json_exclusive,
)

from gold_intel.analytics.liquidity_shift_v2 import (
    LIQUIDITY_SHIFT_V2_RULESET,
    build_liquidity_shift_study_v2,
)


def verify_amendment(root: Path) -> dict[str, Any]:
    path = (
        root
        / "research_manifests"
        / "gold_hierarchical_liquidity_shift_edge_v2_amendment_a.json"
    )
    amendment = read_json(path)
    if amendment.get("preserved_verdict") != "FAIL_SEMANTIC_REPRESENTATION":
        raise RuntimeError("Original semantic failure was not preserved")
    change = amendment.get("single_change", {})
    if change != {
        "field": "maximum_stop_m15_atr",
        "before": 1.5,
        "after": 6.5,
        "selection_basis": "NEXT_HALF_ATR_BOUNDARY_ABOVE_MAXIMUM_OBSERVABLE_HUMAN_ENTRY_TO_STOP_GEOMETRY",
        "outcomes_used": False,
    }:
        raise RuntimeError("Amendment A scope changed")
    for record in amendment["files"].values():
        source = root / record["path"]
        if sha256_file(source) != record["sha256"]:
            raise RuntimeError(f"Amendment predecessor changed: {record['path']}")
    return amendment


async def run(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    freeze = verify_freeze(root)
    amendment = verify_amendment(root)
    config = replace(verify_config(root), maximum_stop_m15_atr=6.5)
    human_path = (
        root
        / "research_artifacts"
        / "gold_matched_human_replay_v1"
        / "ledgers"
        / "matched_human_visible_ledger.jsonl"
    )
    ledger = read_jsonl(human_path)
    head = verify_chain(ledger)
    decisions = [
        item
        for item in ledger
        if item.get("event_type") in {"DECISION_SEALED", "NO_TRADE_SEALED"}
    ]
    if len(decisions) != EXPECTED_CASES:
        raise RuntimeError(f"Expected {EXPECTED_CASES} decisions, found {len(decisions)}")
    minutes, source = await load_minutes()
    inputs = aggregate_study_inputs(minutes)
    primary = build_liquidity_shift_study_v2(inputs, config=config)
    reference = build_liquidity_shift_study_v2(
        {key: list(reversed(value)) for key, value in inputs.items()}, config=config
    )
    primary_hash = canonical_hash(asdict(primary))
    reference_hash = canonical_hash(asdict(reference))
    if primary_hash != reference_hash:
        raise RuntimeError("Amendment A primary/reference mismatch")
    protocol = read_json(
        root
        / "research_manifests"
        / "gold_hierarchical_liquidity_shift_edge_v2_protocol.json"
    )
    rows, metrics = calibrate(
        primary,
        decisions,
        int(protocol["semantic_gates"]["contact_lookback_hours"]),
    )
    result = {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_AMENDMENT_A_SEMANTIC_CALIBRATION_1_0",
        "ruleset": LIQUIDITY_SHIFT_V2_RULESET,
        "research_credit": "ZERO_ECONOMIC_CREDIT_EXPOSED_SEMANTIC_CALIBRATION",
        "preserved_original_verdict": "FAIL_SEMANTIC_REPRESENTATION",
        "amendment_sha256": sha256_file(
            root
            / "research_manifests"
            / "gold_hierarchical_liquidity_shift_edge_v2_amendment_a.json"
        ),
        "frozen_rules_hash": freeze["rules_hash"],
        "single_override": {"maximum_stop_m15_atr": 6.5},
        "human_visible_ledger_head_sha256": head,
        "source": source,
        "detector_counts": {
            "zones": len(primary.zones),
            "contacts": len(primary.contacts),
            "transitions": len(primary.transitions),
            "entry_intents": len(primary.entry_intents),
            "zones_by_timeframe": dict(Counter(item.timeframe for item in primary.zones)),
            "intents_by_family": dict(Counter(item.family for item in primary.entry_intents)),
            "intent_states": dict(Counter(item.state for item in primary.entry_intents)),
        },
        "metrics": metrics,
        "reproduction": {
            "primary_sha256": primary_hash,
            "reference_sha256": reference_hash,
            "identical": True,
        },
        "matched_outcome_ledger_opened": False,
        "development_outcomes_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    if amendment["semantic_rerun_attempts_authorized"] != 1:
        raise RuntimeError("Amendment A rerun cardinality changed")
    return result, rows


async def run_and_dispose(root: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    from gold_intel.infrastructure.database import engine

    try:
        return await run(root)
    finally:
        await engine.dispose()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, default=Path("/workspace"))
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    output = args.output.resolve()
    result_path = output / "semantic_calibration_amendment_a.json"
    rows_path = output / "semantic_rows_amendment_a.csv"
    seal_path = output / "semantic_seal_amendment_a.json"
    if any(path.exists() for path in (result_path, rows_path, seal_path)):
        raise FileExistsError("Amendment A semantic artifacts already exist")
    result, rows = asyncio.run(run_and_dispose(args.root.resolve()))
    write_json_exclusive(result_path, result)
    write_csv_exclusive(rows_path, rows)
    seal = {
        "version": "GOLD_HIERARCHICAL_LIQUIDITY_SHIFT_EDGE_V2_AMENDMENT_A_SEMANTIC_SEAL_1_0",
        "verdict": result["metrics"]["semantic_verdict"],
        "files": {
            result_path.name: {
                "bytes": result_path.stat().st_size,
                "sha256": sha256_file(result_path),
            },
            rows_path.name: {
                "bytes": rows_path.stat().st_size,
                "sha256": sha256_file(rows_path),
            },
        },
    }
    write_json_exclusive(seal_path, seal)
    print(
        json.dumps(
            {
                "metrics": result["metrics"],
                "detector_counts": result["detector_counts"],
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
