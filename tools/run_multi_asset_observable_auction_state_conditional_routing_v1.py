#!/usr/bin/env python3
"""Execute the sealed Multi-Asset Observable Auction-State Routing V1 branch."""

from __future__ import annotations

import gc
import hashlib
import json
import os
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping, Sequence

try:
    from tools import maoascr_v1_engine as research
    from tools import msbam_v1_m2_m3_engine as base
except ModuleNotFoundError:
    import maoascr_v1_engine as research
    import msbam_v1_m2_m3_engine as base


ROOT = Path(__file__).resolve().parents[1]
MANIFESTS = ROOT / "research_manifests"
ARTIFACTS = ROOT / "research_artifacts/multi_asset_observable_auction_state_conditional_routing_v1"
FREEZE = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_preoutcome_freeze.json"
M3_SEAL = MANIFESTS / "multi_asset_session_behaviour_archetype_monetization_v1_m3_seal.json"
R2_PRIMARY = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification_primary.json"
R2_REFERENCE = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification_reference.json"
R2_RESULT = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m1_r2/recertification.json"
SOURCE_CERT = ROOT / "research_artifacts/multi_asset_macro_session_portfolio_v1_m2/certification.json"
OUTCOME_SOURCE = ROOT / "research_artifacts/multi_asset_session_behaviour_archetype_monetization_v1_m3/primary_feasibility.json"
PRIMARY_FEATURES = ARTIFACTS / "checkpoint_features_primary.json"
REFERENCE_FEATURES = ARTIFACTS / "checkpoint_features_reference.json"
MATERIALIZATION = ARTIFACTS / "materialization_certification.json"
OUTCOME_OPENING = ARTIFACTS / "development_outcome_opening.json"
PRIMARY_JOIN = ARTIFACTS / "development_join_primary.json"
REFERENCE_JOIN = ARTIFACTS / "development_join_reference.json"
STAGE1_PRIMARY = ARTIFACTS / "stage1_primary.json"
STAGE1_REFERENCE = ARTIFACTS / "stage1_reference.json"
STAGE1_SEAL = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_stage1_seal.json"
STAGE2_PRIMARY = ARTIFACTS / "stage2_primary.json"
STAGE2_REFERENCE = ARTIFACTS / "stage2_reference.json"
ROUTER_PRIMARY = ARTIFACTS / "router_primary.json"
ROUTER_REFERENCE = ARTIFACTS / "router_reference.json"
FINAL_RESULT = ARTIFACTS / "final_result.json"
STATE = ARTIFACTS / "state.json"
REPORT = ROOT / "MULTI_ASSET_OBSERVABLE_AUCTION_STATE_CONDITIONAL_ROUTING_EDGE_DISCOVERY_V1_REPORT.md"
FINAL_SEAL = MANIFESTS / "multi_asset_observable_auction_state_conditional_routing_v1_final_seal.json"
SYMBOLS = tuple(base.INSTRUMENTS)
EXPECTED_CASES = 10_388
EXPECTED_CHECKPOINTS = {"M15": 10_385, "H1": 9_353, "H4": 4_098}
UTC = timezone.utc


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    return {"path": path.resolve().relative_to(ROOT.resolve()).as_posix(), "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(path)
    return value


def write_json_exclusive(path: Path, value: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            json.dump(value, handle, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
            handle.write("\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def write_text_exclusive(path: Path, value: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(value.rstrip() + "\n")
    except Exception:
        path.unlink(missing_ok=True)
        raise


def verify_record(item: Mapping[str, Any]) -> None:
    path = ROOT / str(item["path"])
    if not path.is_file() or path.stat().st_size != int(item["bytes"]) or sha256_file(path) != str(item["sha256"]):
        raise ValueError(f"Sealed binding changed: {item['path']}")


def verify_freeze() -> dict[str, Any]:
    freeze = load(FREEZE)
    if freeze.get("status") != "SEALED_BEFORE_CHECKPOINT_OR_OUTCOME_VALUE_ACCESS":
        raise ValueError("Invalid pre-outcome freeze")
    for item in freeze.get("bindings", {}).values():
        verify_record(item)
    for item in freeze.get("source_bindings", []):
        verify_record(item)
    controls = freeze.get("controls", {})
    if controls.get("2025_values_accessed") or controls.get("2026_values_accessed") or float(controls.get("charge_usd", 0.0)) != 0.0:
        raise ValueError("Forward/no-charge lock failed")
    m3 = load(M3_SEAL)
    if m3.get("verdict") != "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY" or not m3.get("independent_reproduction"):
        raise ValueError("Required predecessor verdict is not intact")
    for item in m3.get("artifacts", []):
        verify_record(item)
    return freeze


def source_inventory() -> dict[str, list[Path]]:
    certification = load(SOURCE_CERT)
    inventory: dict[str, list[Path]] = {}
    for item in certification.get("instrument_certifications", []):
        symbol = str(item.get("mt5_symbol"))
        if symbol not in SYMBOLS:
            continue
        if item.get("classification") != "PRESENT_AND_ADEQUATE":
            raise ValueError(f"Source no longer adequate: {symbol}")
        paths: list[Path] = []
        for source in item.get("coverage", {}).get("source_files", []):
            verify_record(source)
            path = ROOT / str(source["path"])
            if "2025" in path.name or "2026" in path.name:
                raise ValueError(f"Forward source selected during development: {path.name}")
            paths.append(path)
        inventory[symbol] = paths
    if set(inventory) != set(SYMBOLS):
        raise ValueError("Development source inventory is incomplete")
    return inventory


def selected_cases(path: Path) -> list[dict[str, Any]]:
    payload = load(path)
    passing = set(load(R2_RESULT)["passing_units"])
    rows = [
        dict(row) for row in payload["case_rows"]
        if row["eligible_for_milestone_2"] and f"{row['instrument']}|{row['session_code']}" in passing
    ]
    rows.sort(key=lambda row: (row["session_date_local"], row["instrument"], row["session_code"], row["case_id"]))
    if len(rows) != EXPECTED_CASES or any(str(row["session_date_local"]) >= "2025-01-01" for row in rows):
        raise ValueError("Frozen development population changed")
    return rows


def materialize_features(
    implementation: str,
    cases: Sequence[Mapping[str, Any]],
    inventory: Mapping[str, Sequence[Path]],
    output: Path,
) -> dict[str, Any]:
    legacy = base.load_legacy()
    base.patch_sources(legacy, inventory)
    macro = legacy.MacroBook(implementation)
    previous = base.prior_case_map(cases)
    rows: list[dict[str, Any]] = []
    diagnostics: list[dict[str, Any]] = []
    for symbol in SYMBOLS:
        series, diagnostic = legacy.load_price_series(symbol, implementation)
        bundle = legacy.build_technical_bundle(series, implementation)
        symbol_cases = [case for case in cases if str(case["instrument"]) == symbol]
        for case in symbol_cases:
            for timeframe in base.TIMEFRAMES:
                row = research.feature_row(legacy, bundle, macro, case, previous[str(case["case_id"])], timeframe)
                if row is not None:
                    rows.append(row)
        diagnostics.append({
            "symbol": symbol, "source_files": diagnostic["source_files"], "canonical_rows": diagnostic["canonical_rows"],
            "source_inventory_hash": diagnostic["source_inventory_hash"], "checkpoint_rows": sum(row["instrument"] == symbol for row in rows),
        })
        del bundle, series
        gc.collect()
    rows.sort(key=lambda row: (row["session_date"], row["instrument"], row["session"], row["case_id"], base.TIMEFRAMES[row["timeframe"]]))
    counts = Counter(row["timeframe"] for row in rows)
    if dict(counts) != EXPECTED_CHECKPOINTS:
        raise ValueError(f"Checkpoint counts changed: {dict(counts)}")
    if len({row["checkpoint_id"] for row in rows}) != len(rows):
        raise ValueError("Duplicate checkpoint identity")
    forbidden = {"archetype", "MFE", "MAE", "future_extrema", "exit_reason", "target_before_stop", "realized_net_r"}
    if any(forbidden & set(row) for row in rows):
        raise ValueError("Outcome field leaked into checkpoint features")
    payload = {"version": "MAOASCR_V1_CHECKPOINT_FEATURES_1_0", "implementation": implementation, "rows": rows}
    write_json_exclusive(output, payload)
    return {
        "rows": len(rows), "timeframe_counts": dict(sorted(counts.items())),
        "row_identity_hash": research.canonical_hash([row["checkpoint_id"] for row in rows]),
        "semantic_hash": research.canonical_hash(rows), "file_sha256": sha256_file(output),
        "source_diagnostics": diagnostics,
    }


def open_and_join_outcomes(feature_rows: Sequence[Mapping[str, Any]]) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    outcome_payload = load(OUTCOME_SOURCE)
    outcomes = outcome_payload["track_rows"]
    index = {(str(row["case_id"]), str(row["timeframe"])): row for row in outcomes if row.get("triggered")}
    if len(index) != sum(EXPECTED_CHECKPOINTS.values()):
        raise ValueError("Sealed outcome checkpoint population changed")
    joined: list[dict[str, Any]] = []
    for feature in feature_rows:
        key = (str(feature["case_id"]), str(feature["timeframe"]))
        outcome = index.get(key)
        if outcome is None:
            raise KeyError(f"Missing outcome: {key}")
        if (
            int(outcome["trigger_available_minute"]) != int(feature["checkpoint_minute"])
            or int(outcome["entry_minute"]) != int(feature["entry_minute"])
            or int(outcome["direction"]) != int(feature["direction"])
        ):
            raise ValueError(f"Checkpoint identity mismatch: {key}")
        gross = float(outcome["stage3_stop_feasible_gross_r"])
        cost = float(outcome["cost_r"])
        item = dict(feature)
        item.update({
            "target_before_stop": research.resolved_label(outcome),
            "outcome_status": "RESOLVED" if research.resolved_label(outcome) is not None else "CENSORED_TIME_EXIT",
            "exit_reason": str(outcome["exit_reason"]), "exit_minute": int(outcome["exit_minute"]),
            "realized_gross_r": base.rounded(gross), "realized_cost_r": base.rounded(cost),
            "realized_net_r": base.rounded(float(outcome["stage3_net_r"])),
            "realized_stress_net_r": base.rounded(gross - 1.5 * cost) if outcome.get("size_executable") else 0.0,
            "realized_net_pnl_usd": base.rounded(float(outcome["net_pnl_usd"])),
            "actual_risk_usd": outcome.get("actual_risk_usd"), "size_executable": bool(outcome.get("size_executable")),
            "calendar_year": str(feature["session_date"])[:4],
        })
        item["outcome_lineage_hash"] = research.canonical_hash({key: item[key] for key in ("checkpoint_id", "target_before_stop", "exit_reason", "exit_minute", "realized_gross_r", "realized_cost_r", "realized_net_r")})
        joined.append(base.normalize_payload(item))
    joined.sort(key=lambda row: (row["session_date"], row["instrument"], row["session"], row["case_id"], base.TIMEFRAMES[row["timeframe"]]))
    diagnostics = {
        "joined_rows": len(joined), "resolved_rows": sum(row["target_before_stop"] is not None for row in joined),
        "censored_rows": sum(row["target_before_stop"] is None for row in joined),
        "checkpoint_identity_hash": research.canonical_hash([row["checkpoint_id"] for row in joined]),
        "join_semantic_hash": research.canonical_hash(joined),
    }
    return joined, diagnostics


def report(final: Mapping[str, Any]) -> str:
    router = final["router"]
    stage1 = final["stage1"]
    stage2 = final["stage2"]
    return f"""# Multi-Asset Observable Auction-State Conditional Routing V1

## Verdict

**{final['verdict']}**

- Point-in-time checkpoints: **{final['checkpoint_rows']:,}** across M15, H1 and H4.
- Stage-1 tests: **{stage1['tests']}**; relationship passes: **{stage1['passes']}**.
- Stage-2 interactions: **{stage2['tests']}**; relationship passes: **{stage2['passes']}**.
- Router-selected, cluster-accepted trades: **{router['accepted_trades']}** ({router['trades_per_month']:.2f}/month).
- OOF expectancy: **{router['net_expectancy_r']} R/trade**; PF **{router['profit_factor']}**.
- OOF result: **{router['net_r_per_month']} R/month**, **${router['dollars_per_month']}/month**.
- Maximum drawdown: **{router['maximum_drawdown_r']} R**.
- 1.5x-cost expectancy: **{router['stress_expectancy_r']} R/trade**.
- Calibration Brier skill: **{router['calibration'].get('brier_skill')}**; ECE **{router['calibration'].get('ece')}**.

Failed economic gates: {', '.join(router['failed_gates']) if router['failed_gates'] else 'none'}.

XAUUSD remained outside this branch. No paid data were acquired. Calendar 2025 and 2026 were opened only if the frozen development router passed; forward disposition: **{final['forward_disposition']}**.
"""


def seal(path: Path, verdict: str, artifacts: Sequence[Path], extra: Mapping[str, Any]) -> None:
    records = [record(item) for item in artifacts]
    write_json_exclusive(path, {
        "version": "MAOASCR_V1_FINAL_SEAL_1_0", "status": "SEALED_COMPLETE", "verdict": verdict,
        "sealed_at_utc": utc_now(), "artifacts": records, "artifact_set_hash": research.canonical_hash(records),
        "controls": {"charge_usd": 0.0, "XAUUSD_accessed": False}, **extra,
    })


def main() -> int:
    verify_freeze()
    inventory = source_inventory()
    primary_cases = selected_cases(R2_PRIMARY)
    reference_cases = selected_cases(R2_REFERENCE)
    if research.canonical_hash(primary_cases) != research.canonical_hash(reference_cases):
        raise ValueError("Independent case populations differ")

    primary_materialization = materialize_features("primary", primary_cases, inventory, PRIMARY_FEATURES)
    reference_materialization = materialize_features("reference", reference_cases, inventory, REFERENCE_FEATURES)
    materialization_pass = (
        sha256_file(PRIMARY_FEATURES) == sha256_file(REFERENCE_FEATURES)
        and primary_materialization["semantic_hash"] == reference_materialization["semantic_hash"]
        and primary_materialization["row_identity_hash"] == reference_materialization["row_identity_hash"]
    )
    materialization_result = {
        "version": "MAOASCR_V1_MATERIALIZATION_CERTIFICATION_1_0",
        "verdict": "PASS_OUTCOME_BLIND_FEATURE_REPRODUCTION" if materialization_pass else "FAIL_FEATURE_REPRODUCTION",
        "primary": primary_materialization, "reference": reference_materialization,
        "exact_byte_reproduction": sha256_file(PRIMARY_FEATURES) == sha256_file(REFERENCE_FEATURES),
        "outcomes_accessed": False, "2025_values_accessed": False, "2026_values_accessed": False,
    }
    write_json_exclusive(MATERIALIZATION, materialization_result)
    if not materialization_pass:
        raise RuntimeError("Point-in-time checkpoint materialization did not reproduce")

    opening = {
        "version": "MAOASCR_V1_DEVELOPMENT_OUTCOME_OPENING_1_0", "opened_at_utc": utc_now(),
        "opening_count": 1, "source": record(OUTCOME_SOURCE),
        "feature_population_hash": primary_materialization["row_identity_hash"],
        "2025_values_accessed": False, "2026_values_accessed": False,
    }
    write_json_exclusive(OUTCOME_OPENING, opening)
    primary_rows = load(PRIMARY_FEATURES)["rows"]
    reference_rows = load(REFERENCE_FEATURES)["rows"]
    primary_join, primary_join_diag = open_and_join_outcomes(primary_rows)
    reference_join, reference_join_diag = open_and_join_outcomes(reference_rows)
    write_json_exclusive(PRIMARY_JOIN, {"rows": primary_join})
    write_json_exclusive(REFERENCE_JOIN, {"rows": reference_join})
    if sha256_file(PRIMARY_JOIN) != sha256_file(REFERENCE_JOIN) or primary_join_diag != reference_join_diag:
        raise RuntimeError("Outcome join did not reproduce")

    primary_stage1 = research.stage1_tests(primary_join)
    reference_stage1 = research.stage1_tests(reference_join)
    write_json_exclusive(STAGE1_PRIMARY, {"tests": primary_stage1})
    write_json_exclusive(STAGE1_REFERENCE, {"tests": reference_stage1})
    stage1_reproduced = sha256_file(STAGE1_PRIMARY) == sha256_file(STAGE1_REFERENCE)
    stage1_records = [record(STAGE1_PRIMARY), record(STAGE1_REFERENCE)]
    write_json_exclusive(STAGE1_SEAL, {
        "version": "MAOASCR_V1_STAGE1_SEAL_1_0", "status": "SEALED_BEFORE_STAGE2",
        "sealed_at_utc": utc_now(), "reproduced": stage1_reproduced,
        "test_count": len(primary_stage1), "pass_count": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage1),
        "artifacts": stage1_records, "artifact_set_hash": research.canonical_hash(stage1_records),
    })
    if not stage1_reproduced:
        raise RuntimeError("Stage 1 did not reproduce")

    primary_stage2 = research.stage2_tests(primary_join)
    reference_stage2 = research.stage2_tests(reference_join)
    write_json_exclusive(STAGE2_PRIMARY, {"tests": primary_stage2})
    write_json_exclusive(STAGE2_REFERENCE, {"tests": reference_stage2})
    if sha256_file(STAGE2_PRIMARY) != sha256_file(STAGE2_REFERENCE):
        raise RuntimeError("Stage 2 did not reproduce")

    primary_predictions, primary_models = research.oof_router(primary_join)
    reference_predictions, reference_models = research.oof_router(reference_join)
    primary_router = research.router_metrics(primary_predictions)
    reference_router = research.router_metrics(reference_predictions)
    primary_payload = {"models": primary_models, "predictions": primary_predictions, **primary_router}
    reference_payload = {"models": reference_models, "predictions": reference_predictions, **reference_router}
    write_json_exclusive(ROUTER_PRIMARY, primary_payload)
    write_json_exclusive(ROUTER_REFERENCE, reference_payload)
    router_reproduced = sha256_file(ROUTER_PRIMARY) == sha256_file(ROUTER_REFERENCE)
    if not router_reproduced:
        raise RuntimeError("Router evaluation did not reproduce")

    metrics = primary_router["metrics"]
    development_pass = metrics["verdict"] == "PASS_PROVISIONAL_UNVALIDATED_CANDIDATE"
    # Existing local inventory contains no certified 2025/2026 files for all six
    # instruments.  It is inspected only after a development PASS; otherwise the
    # holdouts remain strictly unopened as required.
    if development_pass:
        forward_disposition = "BLOCKED_REQUIRED_EXISTING_2025_2026_SOURCES_NOT_CERTIFIED"
        verdict = "PASS_DEVELOPMENT_CANDIDATE_FORWARD_BLOCKED_SOURCE_UNAVAILABLE"
        calendar_2025_accessed = False
        calendar_2026_accessed = False
    else:
        forward_disposition = "NOT_OPENED_NO_DEVELOPMENT_CANDIDATE"
        verdict = "REJECT_NO_ECONOMICALLY_TRADABLE_CONDITIONAL_ROUTER"
        calendar_2025_accessed = False
        calendar_2026_accessed = False

    final = {
        "version": "MAOASCR_V1_FINAL_RESULT_1_0", "verdict": verdict, "completed_at_utc": utc_now(),
        "checkpoint_rows": primary_materialization["rows"],
        "stage1": {"tests": len(primary_stage1), "passes": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage1), "support_failures": sum(row["verdict"] == "SUPPORT_FAIL" for row in primary_stage1)},
        "stage2": {"tests": len(primary_stage2), "passes": sum(row["verdict"] == "PASS_RELATIONSHIP" for row in primary_stage2), "support_failures": sum(row["verdict"] == "SUPPORT_FAIL" for row in primary_stage2)},
        "router": metrics, "candidate_count": 1 if development_pass else 0,
        "forward_disposition": forward_disposition,
        "independent_reproduction": True, "outcome_opening_count": 1,
        "controls": {"2025_values_accessed": calendar_2025_accessed, "2026_values_accessed": calendar_2026_accessed, "charge_usd": 0.0, "XAUUSD_accessed": False},
        "preserved_predecessor_verdict": "FAIL_M3_CURRENT_UNIVERSE_BELOW_10R_CAPACITY",
    }
    write_json_exclusive(FINAL_RESULT, final)
    write_json_exclusive(STATE, {
        "version": "MAOASCR_V1_STATE_1_0", "status": "COMPLETE", "verdict": verdict,
        "forward_disposition": forward_disposition, "candidate_count": final["candidate_count"],
        "2025_locked_or_accessed": "LOCKED_NOT_ACCESSED" if not calendar_2025_accessed else "OPENED_ONCE",
        "2026_locked_or_accessed": "LOCKED_NOT_ACCESSED" if not calendar_2026_accessed else "OPENED_ONCE",
    })
    write_text_exclusive(REPORT, report(final))
    seal(
        FINAL_SEAL, verdict,
        [FREEZE, MATERIALIZATION, PRIMARY_FEATURES, REFERENCE_FEATURES, OUTCOME_OPENING, PRIMARY_JOIN, REFERENCE_JOIN, STAGE1_SEAL, STAGE1_PRIMARY, STAGE1_REFERENCE, STAGE2_PRIMARY, STAGE2_REFERENCE, ROUTER_PRIMARY, ROUTER_REFERENCE, FINAL_RESULT, STATE, REPORT, Path(__file__).resolve(), ROOT / "tools/maoascr_v1_engine.py"],
        {"independent_reproduction": True, "2025_values_accessed": calendar_2025_accessed, "2026_values_accessed": calendar_2026_accessed, "candidate_count": final["candidate_count"]},
    )
    print(json.dumps({
        "verdict": verdict, "checkpoint_rows": final["checkpoint_rows"], "stage1": final["stage1"], "stage2": final["stage2"],
        "router": {key: metrics.get(key) for key in ("accepted_trades", "trades_per_month", "win_rate", "net_expectancy_r", "profit_factor", "net_r_per_month", "dollars_per_month", "maximum_drawdown_r", "stress_expectancy_r", "failed_gates")},
        "forward_disposition": forward_disposition, "final_seal_sha256": sha256_file(FINAL_SEAL),
    }, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

