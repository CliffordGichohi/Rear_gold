#!/usr/bin/env python3
"""Freeze, fit, rerun, reproduce, and seal the exposed ten-case policy."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import runpy
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import render_gold_auction_trade_placement_examples_v1 as placement  # noqa: E402
import reveal_gold_auction_trade_placement_outcomes_v1 as outcomes  # noqa: E402
from gold_intel.analytics.auction_ten_case_reusable_optimization_v1 import (  # noqa: E402
    ADMISSION_POLICIES,
    EARLY_FRACTIONS,
    FORBIDDEN_SELECTOR_FIELDS,
    LOCAL_PATH_MINIMUM_R,
    RULESET,
    RUNNER_FRACTIONS,
    candidate_registry,
    evaluate_candidate,
    finalize_candidate_matrix,
)
from gold_intel.analytics.auction_trade_placement_examples_v1 import select_ten_examples  # noqa: E402
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import resolve_plan  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


CONTRACT = ROOT / "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_ten_case_reusable_optimization_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_ten_case_reusable_optimization_v1.py"
RUNNER = Path(__file__).resolve()
UPSTREAM_PLAN_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_trade_placement_examples_v1.py"
UPSTREAM_EXECUTION_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_trade_placement_outcomes_v1.py"

PLACEMENT_ROOT = ROOT / "research_artifacts" / "gold_auction_trade_placement_examples_v1"
PLANS_PRIMARY = PLACEMENT_ROOT / "plans.primary.json"
PLANS_REFERENCE = PLACEMENT_ROOT / "plans.reference.json"
PLACEMENT_SEAL = PLACEMENT_ROOT / "seal.json"
OUTCOME_ROOT = PLACEMENT_ROOT / "outcome_reveal_v1"
OUTCOME_FREEZE = OUTCOME_ROOT / "preoutcome_freeze.json"
OUTCOMES_PRIMARY = OUTCOME_ROOT / "outcomes.primary.json"
OUTCOMES_REFERENCE = OUTCOME_ROOT / "outcomes.reference.json"
OUTCOME_SEAL = OUTCOME_ROOT / "seal.json"
DIAGNOSTIC_ROOT = ROOT / "research_artifacts" / "gold_auction_ten_case_failure_profit_retention_diagnostic_v1"
DIAGNOSTIC_SEAL = DIAGNOSTIC_ROOT / "seal.json"

OUT = ROOT / "research_artifacts" / "gold_auction_ten_case_reusable_optimization_and_replay_v1"
FREEZE = OUT / "prefit_freeze.json"
PRIMARY = OUT / "replay.primary.json"
REFERENCE = OUT / "replay.reference.json"
FINAL = OUT / "final_result.json"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1_REPORT.md"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def verify_file_record(record: dict[str, Any]) -> None:
    path = ROOT / record["path"]
    require(path.exists(), f"Frozen input missing: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Frozen input size differs: {path}")
    require(sha256_file(path) == str(record["sha256"]), f"Frozen input hash differs: {path}")


def verify_seal(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    submitted = str(payload["seal_sha256"])
    require(canonical_hash({key: value for key, value in payload.items() if key != "seal_sha256"}) == submitted, f"Seal payload differs: {path}")
    for record in payload["files"]:
        verify_file_record(record)
    return payload


def atomic_create(path: Path, payload: bytes) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("xb") as handle:
        handle.write(payload)
        handle.flush()
        os.fsync(handle.fileno())
    temporary.replace(path)


def write_json(path: Path, payload: Any) -> None:
    atomic_create(path, (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"))


def write_text(path: Path, payload: str) -> None:
    atomic_create(path, payload.encode("utf-8"))


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    names = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
    require(len(names) == 5, f"Unexpected synthetic-test population: {names}")
    for name in names:
        namespace[name]()
    payload = {"passed": len(names), "tests": names}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def reconstruct_plans(side: str) -> list[dict[str, Any]]:
    events_path = placement.EVENTS_PRIMARY if side == "primary" else placement.EVENTS_REFERENCE
    overlays_path = placement.OVERLAYS_PRIMARY if side == "primary" else placement.OVERLAYS_REFERENCE
    events = load_json(events_path)["events"]
    overlays = load_json(overlays_path)["overlays"]
    return select_ten_examples(events, overlays)


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    placement_seal = verify_seal(PLACEMENT_SEAL)
    outcome_seal = verify_seal(OUTCOME_SEAL)
    diagnostic_seal = verify_seal(DIAGNOSTIC_SEAL)
    primary_plans = reconstruct_plans("primary")
    reference_plans = reconstruct_plans("reference")
    sealed_plans = load_json(PLANS_PRIMARY)["plans"]
    require(primary_plans == reference_plans == sealed_plans, "Predecision plan reconstruction differs before freeze")
    require(len(sealed_plans) == 10, "Expected exactly ten exposed plans")
    registry = candidate_registry()
    for row in registry:
        require(row["direction_symmetric"] is True, "Asymmetric candidate registered")
        require(not (set(row["selector_fields"]) & set(FORBIDDEN_SELECTOR_FIELDS)), f"Forbidden selector in {row['candidate_id']}")
    source_records = load_json(OUTCOME_FREEZE)["source_records"]
    for record in source_records:
        verify_file_record(record)
    proof = synthetic_proof()
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1_FREEZE_1_0",
        "frozen_at": now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_EXPOSED_FIT_AND_IMPLEMENTATION_REPLAY",
        "population": {
            "count": 10,
            "event_identities": [row["event_identity"] for row in sealed_plans],
            "event_identities_sha256": canonical_hash([row["event_identity"] for row in sealed_plans]),
            "case_aliases": [row["case_alias"] for row in sealed_plans],
        },
        "admission_policies": list(ADMISSION_POLICIES),
        "local_path_minimum_r": LOCAL_PATH_MINIMUM_R,
        "early_realization_fractions": list(EARLY_FRACTIONS),
        "target_runner_fractions": list(RUNNER_FRACTIONS),
        "candidate_registry": registry,
        "candidate_registry_sha256": canonical_hash(registry),
        "candidate_count": len(registry),
        "selection": {
            "minimum_trades": 4,
            "both_directions": True,
            "minimum_retained_baseline_winners": 3,
            "minimum_component_activations": 2,
            "positive_net_r": True,
            "positive_leave_one_trade_out_net_r": True,
            "positive_registered_parameter_neighbors": True,
            "ranking": ["NET_R_DESC", "PF_DESC", "MAX_DD_ASC", "COMPONENTS_ASC", "TRADES_DESC", "ID_ASC"],
        },
        "synthetic_proof": proof,
        "predecessor_seals": {
            "placement": placement_seal["seal_sha256"],
            "outcomes": outcome_seal["seal_sha256"],
            "diagnostic": diagnostic_seal["seal_sha256"],
        },
        "governing_files": [file_record(path) for path in (CONTRACT, IMPLEMENTATION, TESTS, RUNNER)],
        "upstream_files": [
            file_record(path)
            for path in (
                placement.EVENTS_PRIMARY,
                placement.EVENTS_REFERENCE,
                placement.OVERLAYS_PRIMARY,
                placement.OVERLAYS_REFERENCE,
                PLANS_PRIMARY,
                PLANS_REFERENCE,
                PLACEMENT_SEAL,
                OUTCOME_FREEZE,
                OUTCOMES_PRIMARY,
                OUTCOMES_REFERENCE,
                OUTCOME_SEAL,
                DIAGNOSTIC_SEAL,
                UPSTREAM_PLAN_IMPLEMENTATION,
                UPSTREAM_EXECUTION_IMPLEMENTATION,
            )
        ],
        "source_records": source_records,
        "additional_cases_opened": 0,
        "additional_market_data_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json(FREEZE, payload)
    print(json.dumps({"status": "FROZEN", "candidate_count": len(registry), "synthetic_tests": proof["passed"], "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    frozen = load_json(FREEZE)
    submitted = str(frozen["freeze_sha256"])
    require(canonical_hash({key: value for key, value in frozen.items() if key != "freeze_sha256"}) == submitted, "Freeze payload differs")
    for record in frozen["governing_files"] + frozen["upstream_files"] + frozen["source_records"]:
        verify_file_record(record)
    seals = {
        "placement": verify_seal(PLACEMENT_SEAL)["seal_sha256"],
        "outcomes": verify_seal(OUTCOME_SEAL)["seal_sha256"],
        "diagnostic": verify_seal(DIAGNOSTIC_SEAL)["seal_sha256"],
    }
    require(seals == frozen["predecessor_seals"], "Predecessor seal differs")
    require(canonical_hash(frozen["candidate_registry"]) == frozen["candidate_registry_sha256"], "Candidate registry differs")
    return frozen


def side_replay(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    plans = reconstruct_plans(side)
    require([row["event_identity"] for row in plans] == frozen["population"]["event_identities"], f"{side} plan identities differ")
    streams = outcomes._load_targeted_streams(side, {str(row["case_alias"]) for row in plans})
    baseline_results: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        stream = streams[str(plan["case_alias"])]
        baseline_results.append(resolve_plan(plan, stream["timeframes"]["1m"]))
        print(f"{side} raw-stream baseline {index:02d}/10", flush=True)
    sealed_outcome_path = OUTCOMES_PRIMARY if side == "primary" else OUTCOMES_REFERENCE
    sealed_outcomes = load_json(sealed_outcome_path)["results"]
    require(baseline_results == sealed_outcomes, f"{side} raw-stream baseline did not reproduce sealed outcomes")

    matrix: list[dict[str, Any]] = []
    for index, specification in enumerate(frozen["candidate_registry"], start=1):
        matrix.append(
            evaluate_candidate(
                plans=plans,
                baseline_results=baseline_results,
                streams=streams,
                specification=specification,
            )
        )
        if index % 12 == 0:
            print(f"{side} reusable candidates {index:02d}/48", flush=True)
    finalized, selected_id = finalize_candidate_matrix(matrix, frozen["candidate_registry"])
    selected = next(row for row in finalized if row["candidate_id"] == selected_id)
    control_id = "A0_ORIGINAL::E0::R0"
    control = next(row for row in finalized if row["candidate_id"] == control_id)
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_REPLAY_SIDE_1_0",
        "side": side,
        "plans": plans,
        "plans_sha256": canonical_hash(plans),
        "baseline_results": baseline_results,
        "baseline_results_sha256": canonical_hash(baseline_results),
        "candidate_matrix": finalized,
        "candidate_matrix_sha256": canonical_hash(finalized),
        "selected_candidate_id": selected_id,
        "selected_candidate": selected,
        "control_candidate": control,
        "same_ten_baseline_reproduced": True,
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def _fmt(value: Any, digits: int = 4) -> str:
    if value is None:
        return "N/A"
    number = float(value)
    if math.isinf(number):
        return "inf"
    return f"{number:.{digits}f}"


def markdown(final: dict[str, Any]) -> str:
    control = final["control_candidate"]
    selected = final["selected_candidate"]
    control_summary = control["summary"]
    summary = selected["summary"]
    lines = [
        "# Gold Auction Ten-Case Reusable Optimization and Replay V1 Report",
        "",
        f"Status: `{final['verdict']}`",
        "",
        "## Direct verdict",
        "",
        "The frozen algorithm reran exactly the same ten exposed trades from the sealed raw streams before any later data was opened. Primary and reference passes matched exactly. This is exposed fitting and implementation certification, not validation of an edge.",
        "",
        f"- Original ten-trade control: **{control_summary['net_r50']:+.4f}R / ${control_summary['net_pnl_usd']:+.2f}**, PF {_fmt(control_summary['profit_factor'], 2)}, max drawdown {_fmt(control_summary['maximum_drawdown_r50'], 2)}R.",
        f"- Selected reusable policy: `{selected['candidate_id']}`.",
        f"- Optimized exposed replay: **{summary['net_r50']:+.4f}R / ${summary['net_pnl_usd']:+.2f}**, {summary['trades']} trades, {_fmt(summary['win_rate'] * 100, 2)}% win rate, PF {_fmt(summary['profit_factor'], 2)}, max drawdown {_fmt(summary['maximum_drawdown_r50'], 2)}R.",
        f"- Improvement over the unchanged control: **{summary['net_r50'] - control_summary['net_r50']:+.4f}R**.",
        "",
        "## Same-ten decisions",
        "",
        "| Date | Side | Event | Decision | Reason / management | Baseline R | Selected R |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for row in selected["rows"]:
        if row["admitted"]:
            management = row["management"]
            actions = []
            if management["early_realization_activated"]:
                actions.append(f"partial {management['early_realization_quantity']}oz")
            if management["target_runner_activated"]:
                actions.append(f"runner {management['target_runner_quantity']}oz")
            detail = ", ".join(actions) if actions else "original structural lifecycle"
            decision = "ADMIT"
        else:
            detail = "; ".join(row["rejection_reasons"])
            decision = "NO_TRADE"
        lines.append(
            f"| {row['decision_at'][:10]} | {row['direction']} | {row['event_class']} | {decision} | {detail} | {row['baseline_net_r50']:+.4f} | {row['net_r50']:+.4f} |"
        )
    rejected_winners = [row for row in selected["rows"] if not row["admitted"] and float(row["baseline_net_r50"]) > 0]
    lines.extend(
        [
            "",
            f"Valid original winners rejected: **{len(rejected_winners)}**" + (" (" + ", ".join(row["decision_at"][:10] for row in rejected_winners) + ")" if rejected_winners else "."),
            "",
            "## Complete frozen candidate matrix",
            "",
            "| Candidate | Trades | Net R | PF | Max DD | Eligible | Failed gates |",
            "|---|---:|---:|---:|---:|:---:|---|",
        ]
    )
    for row in final["candidate_matrix"]:
        candidate_summary = row["summary"]
        failures = ", ".join(row["selection_failures"]) or "-"
        lines.append(
            f"| `{row['candidate_id']}` | {candidate_summary['trades']} | {candidate_summary['net_r50']:+.4f} | {_fmt(candidate_summary['profit_factor'], 2)} | {_fmt(candidate_summary['maximum_drawdown_r50'], 2)} | {'YES' if row['selection_eligible'] else 'NO'} | {failures} |"
        )
    lines.extend(
        [
            "",
            "## Integrity and next-data gate",
            "",
            "- Exactly ten previously exposed cases were reopened; no additional case or market period was accessed.",
            "- The plans were reconstructed from the sealed point-in-time event and liquidity inputs rather than copied into the result.",
            "- Baseline executions reproduced the prior sealed outcomes exactly.",
            "- Primary and reference plans, executions, candidate matrix, selection, and checksums matched exactly.",
            "- No 2025 or 2026 data was opened and no acquisition or charge occurred.",
            "- The selected result has zero validation credit. A later period remains prohibited until separately authorized.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = side_replay("primary", frozen)
    reference = side_replay("reference", frozen)
    require(primary["plans"] == reference["plans"], "Primary/reference reconstructed plans differ")
    require(primary["baseline_results"] == reference["baseline_results"], "Primary/reference baseline executions differ")
    require(primary["candidate_matrix"] == reference["candidate_matrix"], "Primary/reference candidate matrix differs")
    require(primary["selected_candidate_id"] == reference["selected_candidate_id"], "Primary/reference selected policy differs")
    write_json(PRIMARY, primary)
    write_json(REFERENCE, reference)

    selected = primary["selected_candidate"]
    control = primary["control_candidate"]
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1_FINAL_1_0",
        "verdict": "PASS_SAME_TEN_REUSABLE_EXPOSED_FIT_AND_REPLAY_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "primary_reference_exact": True,
        "same_ten_baseline_reproduced": True,
        "selected_candidate_id": primary["selected_candidate_id"],
        "selected_candidate": selected,
        "control_candidate": control,
        "candidate_matrix": primary["candidate_matrix"],
        "candidate_matrix_sha256": primary["candidate_matrix_sha256"],
        "additional_cases_opened": 0,
        "additional_market_data_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO",
    }
    final["final_sha256"] = canonical_hash(final)
    write_json(FINAL, final)
    write_text(REPORT, markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "primary_reference_exact": True,
        "same_ten_baseline_reproduced": True,
        "selected_candidate_id": final["selected_candidate_id"],
        "control_summary": control["summary"],
        "selected_summary": selected["summary"],
        "additional_cases_opened": 0,
        "additional_market_data_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "report": file_record(REPORT),
    }
    certification["certification_sha256"] = canonical_hash(certification)
    write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_REUSABLE_OPTIMIZATION_AND_REPLAY_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [file_record(path) for path in (FREEZE, PRIMARY, REFERENCE, FINAL, CERTIFICATION, REPORT)],
        "additional_market_data_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": final["verdict"],
                "selected_candidate_id": final["selected_candidate_id"],
                "control": control["summary"],
                "selected": selected["summary"],
                "certification_sha256": certification["certification_sha256"],
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "run", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
