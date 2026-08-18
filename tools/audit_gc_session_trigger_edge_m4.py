from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import sys
from collections import Counter, defaultdict
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_INPUT = ROOT / "research_artifacts" / "gc_session_trigger_edge_m3r1_v01"
DEFAULT_OUTPUT = ROOT / "research_artifacts" / "gc_session_trigger_edge_m4_v01"
PROTOCOL_PATH = ROOT / "research_manifests" / "gc_session_trigger_edge_m4_protocol_v01.json"
FREEZE_PATH = ROOT / "research_manifests" / "gc_session_trigger_edge_m4_freeze_v01.json"
AMENDMENT_PATH = ROOT / "GC_SESSION_TRIGGER_EDGE_DISCOVERY_V2_MILESTONE_4.md"
TEST_PATH = ROOT / "tests" / "test_gc_session_trigger_edge_m4.py"

FORMAL_GATE_ORDER = (
    "frozen_effect_threshold",
    "bootstrap_effect_lower_bound",
    "bootstrap_median_lower_bound_gt_zero",
    "bootstrap_finite_effect_gte_19000",
    "bootstrap_finite_median_gte_19000",
    "bh_q_lte_0_05",
    "directional_symmetry",
    "annual_stability",
    "block_stability",
    "first_event_sensitivity",
    "gc_not_statistically_opposite",
)
STATISTICAL_GATES = frozenset(FORMAL_GATE_ORDER[:6])
STABILITY_GATES = frozenset(
    ("directional_symmetry", "annual_stability", "block_stability", "first_event_sensitivity")
)
TAXONOMY = (
    "NO_MEASURABLE_RELATIONSHIP",
    "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED",
    "UNSTABLE_RELATIONSHIP",
    "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS",
)
DOMINANCE_TIE_PRIORITY = (
    "NO_MEASURABLE_RELATIONSHIP",
    "UNSTABLE_RELATIONSHIP",
    "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED",
    "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS",
)
REQUIRED_RESULT_FILES = (
    "complete_results.json",
    "primary_stage1_results.json",
    "reference_stage1_results.json",
    "primary_stage2_results.json",
    "reference_stage2_results.json",
    "manifest.json",
    "verdict.json",
    "final_seal.json",
    "r1_manifest.json",
    "r1_verdict.json",
    "r1_final_seal.json",
    "GC_SESSION_TRIGGER_EDGE_MILESTONE_3_REPORT.md",
)


def utc_now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def canonical_hash(value: Any) -> str:
    return hashlib.sha256(canonical_bytes(value)).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(4 * 1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"Expected JSON object: {path}")
    return value


def receipt_valid(record: Mapping[str, Any], field: str) -> bool:
    expected = record.get(field)
    if not isinstance(expected, str):
        return False
    without = dict(record)
    without.pop(field, None)
    return expected in {canonical_hash(without), canonical_hash({**record, field: None})}


def json_bytes(value: Any) -> bytes:
    return (json.dumps(value, sort_keys=True, indent=2, ensure_ascii=False) + "\n").encode("utf-8")


def write_once(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != payload:
            raise FileExistsError(f"Sealed artifact differs: {path}")
        return
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_bytes(payload)
    temporary.replace(path)


def write_json_once(path: Path, value: Any) -> None:
    write_once(path, json_bytes(value))


def finite_number(value: Any) -> float | None:
    if value is None:
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def round12(value: Any) -> float | None:
    number = finite_number(value)
    if number is None:
        return None
    output = round(number, 12)
    return 0.0 if output == -0.0 else output


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ValueError(message)


def verify_predecessor(source: Path) -> dict[str, Any]:
    for name in REQUIRED_RESULT_FILES:
        _require((source / name).is_file(), f"Missing sealed result artifact: {name}")

    outer_manifest = load_json(source / "r1_manifest.json")
    outer_verdict = load_json(source / "r1_verdict.json")
    outer_final = load_json(source / "r1_final_seal.json")
    inner_manifest = load_json(source / "manifest.json")
    inner_verdict = load_json(source / "verdict.json")
    inner_final = load_json(source / "final_seal.json")
    complete = load_json(source / "complete_results.json")

    for record, field, label in (
        (outer_manifest, "manifest_receipt", "outer manifest"),
        (outer_verdict, "verdict_receipt", "outer verdict"),
        (outer_final, "final_seal_receipt", "outer final seal"),
        (inner_manifest, "manifest_receipt", "inner manifest"),
        (inner_verdict, "verdict_receipt", "inner verdict"),
        (inner_final, "final_seal_receipt", "inner final seal"),
    ):
        _require(receipt_valid(record, field), f"Invalid {label} receipt")

    _require(outer_final["status"] == "PASS_M3_R1_DISCOVERY_ZERO_CANDIDATES", "Unexpected R1 status")
    _require(inner_final["status"] == "PASS_M3_DISCOVERY_ZERO_CANDIDATES", "Unexpected inner M3 status")
    _require(sha256_file(source / "r1_manifest.json") == outer_final["r1_manifest_sha256"], "Outer manifest hash changed")
    _require(sha256_file(source / "r1_verdict.json") == outer_final["r1_verdict_sha256"], "Outer verdict hash changed")
    _require(sha256_file(source / "final_seal.json") == outer_final["inner_final_seal_sha256"], "Inner final seal hash changed")
    _require(sha256_file(source / "manifest.json") == inner_final["manifest_sha256"], "Inner manifest hash changed")
    _require(sha256_file(source / "verdict.json") == inner_final["verdict_sha256"], "Inner verdict hash changed")
    _require(sha256_file(source / "complete_results.json") == inner_final["complete_results_sha256"], "Complete results hash changed")
    _require(sha256_file(source / "GC_SESSION_TRIGGER_EDGE_MILESTONE_3_REPORT.md") == inner_final["report_sha256"], "M3 report hash changed")

    for name in REQUIRED_RESULT_FILES:
        if name in outer_manifest.get("artifacts", {}):
            _require(sha256_file(source / name) == outer_manifest["artifacts"][name]["sha256"], f"R1 artifact hash changed: {name}")
        elif name in inner_manifest.get("artifacts", {}):
            _require(sha256_file(source / name) == inner_manifest["artifacts"][name]["sha256"], f"M3 artifact hash changed: {name}")

    primary_stage1 = load_json(source / "primary_stage1_results.json")
    reference_stage1 = load_json(source / "reference_stage1_results.json")
    primary_stage2 = load_json(source / "primary_stage2_results.json")
    reference_stage2 = load_json(source / "reference_stage2_results.json")
    _require(primary_stage1["payload_hash"] == reference_stage1["payload_hash"], "Stage-1 payloads no longer reproduce")
    _require(primary_stage2["payload_hash"] == reference_stage2["payload_hash"], "Stage-2 payloads no longer reproduce")
    _require(canonical_hash(primary_stage1["payload"]) == primary_stage1["payload_hash"], "Primary Stage-1 payload hash invalid")
    _require(canonical_hash(reference_stage1["payload"]) == reference_stage1["payload_hash"], "Reference Stage-1 payload hash invalid")
    _require(canonical_hash(primary_stage2["payload"]) == primary_stage2["payload_hash"], "Primary Stage-2 payload hash invalid")
    _require(canonical_hash(reference_stage2["payload"]) == reference_stage2["payload_hash"], "Reference Stage-2 payload hash invalid")

    all_results = complete.get("results")
    _require(isinstance(all_results, list) and len(all_results) == 72, "Complete result registry must contain 72 tests")
    _require(canonical_hash(all_results) == complete["all_results_hash"], "Complete result registry hash invalid")
    eligible = [row for row in all_results if row.get("support_status") == "SUPPORT_ELIGIBLE"]
    support_fail = [row for row in all_results if row.get("verdict") == "SUPPORT_FAIL"]
    _require(len(eligible) == 38 and all(row.get("verdict") == "REJECT" for row in eligible), "Expected exactly 38 eligible rejections")
    _require(len(support_fail) == 34, "Expected exactly 34 frozen support failures")
    _require(not complete.get("year_2025_or_2026_values_accessed"), "Forward years were accessed")
    _require(not complete.get("execution_trade_pnl_r_or_return_calculated"), "Prohibited execution/PnL field is true")

    return {
        "status": "PASS_M4_PREDECESSOR_RESULT_CLOSURE",
        "outer_final_seal_receipt": outer_final["final_seal_receipt"],
        "inner_final_seal_receipt": inner_final["final_seal_receipt"],
        "complete_results_sha256": sha256_file(source / "complete_results.json"),
        "complete_results_hash": complete["all_results_hash"],
        "stage1_payload_hash": primary_stage1["payload_hash"],
        "stage2_payload_hash": primary_stage2["payload_hash"],
        "registered_tests": 72,
        "support_fail": 34,
        "support_eligible_rejected": 38,
        "required_result_artifact_hashes": {name: sha256_file(source / name) for name in REQUIRED_RESULT_FILES},
        "market_sources_opened": False,
        "year_2025_or_2026_values_accessed": False,
    }


def protocol_payload() -> dict[str, Any]:
    return {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_PROTOCOL_V1_0",
        "scope": "negative-result attribution from sealed M3-R1 result artifacts only",
        "population": {"registered": 72, "support_fail_preserved": 34, "audited_support_eligible_rejections": 38, "by_session": {"LONDON": 19, "NEW_YORK": 19}},
        "formal_gate_order": list(FORMAL_GATE_ORDER),
        "statistical_credibility_gates": list(FORMAL_GATE_ORDER[:6]),
        "stability_gates": ["directional_symmetry", "annual_stability", "block_stability", "first_event_sensitivity"],
        "horizon_diagnostic": {"horizons_minutes": [5, 30, 60], "consistent": "all three known, at least two effects > 0pp, and no effect <= -5pp", "formal_m3_gate": False},
        "taxonomy_order": ["STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS", "NO_MEASURABLE_RELATIONSHIP", "UNSTABLE_RELATIONSHIP", "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED"],
        "taxonomy_rules": {
            "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS": "all six statistical credibility gates pass and at least one other formal gate fails",
            "NO_MEASURABLE_RELATIONSHIP": "frozen_effect_threshold fails",
            "UNSTABLE_RELATIONSHIP": "effect threshold passes and any frozen stability gate fails or horizon diagnostic is not CONSISTENT",
            "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED": "effect threshold and stability diagnostics pass but one or more statistical uncertainty/multiplicity gates fail",
        },
        "descriptive_near_miss_order": ["fewest formal failed gates", "lowest BH q", "largest effect_pp", "lexical test_id"],
        "dominance_tie_priority": list(DOMINANCE_TIE_PRIORITY),
        "v3_design_map": {
            "NO_MEASURABLE_RELATIONSHIP": "V3_CONTINUOUS_STATE_RESPONSE_DISCOVERY",
            "UNSTABLE_RELATIONSHIP": "V3_PRE_REGISTERED_TIME_REGIME_STABILITY_DISCOVERY",
            "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED": "V3_OUTCOME_BLIND_DEVELOPMENT_SAMPLE_EXPANSION",
            "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS": "V3_TARGETED_UNCHANGED_ROBUSTNESS_REPLICATION",
        },
        "independent_reproduction": {"primary_source": "complete_results.json", "reference_source": "reference_stage1_results.json + reference_stage2_results.json", "require_exact_payload_and_csv_checksums": True},
        "prohibited": ["market-source reopening", "outcome reconstruction", "retuning", "inversion", "candidate creation", "2025/2026 access", "execution", "trades", "PnL", "R multiples", "returns"],
    }


def prepare(source: Path, output: Path) -> None:
    closure = verify_predecessor(source)
    protocol = protocol_payload()
    protocol["protocol_receipt"] = canonical_hash(protocol)
    write_json_once(PROTOCOL_PATH, protocol)
    freeze = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_FREEZE_V1_0",
        "frozen_at_utc": utc_now(),
        "protocol_path": str(PROTOCOL_PATH.relative_to(ROOT)).replace("\\", "/"),
        "protocol_sha256": sha256_file(PROTOCOL_PATH),
        "protocol_receipt": protocol["protocol_receipt"],
        "amendment_sha256": sha256_file(AMENDMENT_PATH),
        "implementation_sha256": sha256_file(Path(__file__)),
        "test_sha256": sha256_file(TEST_PATH),
        "predecessor": closure,
        "rules_frozen_before_aggregate_attribution": True,
        "market_sources_opened": False,
        "freeze_receipt": None,
    }
    freeze["freeze_receipt"] = canonical_hash({**freeze, "freeze_receipt": None})
    write_json_once(FREEZE_PATH, freeze)
    preflight = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_PREFLIGHT_V1_0",
        "status": "PASS_M4_PRE_ATTRIBUTION_FREEZE",
        "completed_at_utc": utc_now(),
        "freeze_receipt": freeze["freeze_receipt"],
        "predecessor": closure,
        "market_sources_opened": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "preflight_receipt": None,
    }
    preflight["preflight_receipt"] = canonical_hash({**preflight, "preflight_receipt": None})
    write_json_once(output / "preflight.json", preflight)
    print(json.dumps({"status": preflight["status"], "freeze_receipt": freeze["freeze_receipt"], "audited_tests": 38}, sort_keys=True))


def verify_freeze(source: Path, output: Path) -> tuple[dict[str, Any], dict[str, Any]]:
    closure = verify_predecessor(source)
    protocol = load_json(PROTOCOL_PATH)
    freeze = load_json(FREEZE_PATH)
    preflight = load_json(output / "preflight.json")
    _require(receipt_valid(freeze, "freeze_receipt"), "Invalid M4 freeze receipt")
    _require(receipt_valid(preflight, "preflight_receipt"), "Invalid M4 preflight receipt")
    _require(protocol.get("protocol_receipt") == canonical_hash({k: v for k, v in protocol.items() if k != "protocol_receipt"}), "Protocol receipt invalid")
    _require(sha256_file(PROTOCOL_PATH) == freeze["protocol_sha256"], "Protocol changed after freeze")
    _require(sha256_file(AMENDMENT_PATH) == freeze["amendment_sha256"], "Amendment changed after freeze")
    _require(sha256_file(Path(__file__)) == freeze["implementation_sha256"], "Implementation changed after freeze")
    _require(sha256_file(TEST_PATH) == freeze["test_sha256"], "Tests changed after freeze")
    _require(closure["complete_results_sha256"] == freeze["predecessor"]["complete_results_sha256"], "Input results changed after freeze")
    return protocol, freeze


def horizon_diagnostic(row: Mapping[str, Any]) -> dict[str, Any]:
    items = sorted(row["secondary_consistency"], key=lambda item: int(item["horizon_minutes"]))
    effects = [finite_number(item.get("effect_pp")) for item in items]
    known = sum(effect is not None for effect in effects)
    favorable = sum(effect is not None and effect > 0 for effect in effects)
    materially_opposite = sum(effect is not None and effect <= -5.0 for effect in effects)
    if known < 3:
        status = "INSUFFICIENT"
    elif favorable >= 2 and materially_opposite == 0:
        status = "CONSISTENT"
    else:
        status = "MIXED_OR_CONTRADICTORY"
    return {
        "status": status,
        "known_horizons": known,
        "favorable_horizons": favorable,
        "materially_opposite_horizons": materially_opposite,
        "formal_m3_gate": False,
        "horizons": [
            {"minutes": int(item["horizon_minutes"]), "effect_pp": round12(item.get("effect_pp")), "p_value": round12(item.get("p_value")), "holm_adjusted_p_value": round12(item.get("holm_adjusted_p_value"))}
            for item in items
        ],
    }


def classify_checks(checks: Mapping[str, Any], horizon_status: str) -> str:
    statistical_pass = all(bool(checks[name]) for name in STATISTICAL_GATES)
    formal_pass = all(bool(checks[name]) for name in FORMAL_GATE_ORDER)
    if statistical_pass and not formal_pass:
        return "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS"
    if not bool(checks["frozen_effect_threshold"]):
        return "NO_MEASURABLE_RELATIONSHIP"
    if any(not bool(checks[name]) for name in STABILITY_GATES) or horizon_status != "CONSISTENT":
        return "UNSTABLE_RELATIONSHIP"
    return "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED"


def _effect_ci_lift_pp(row: Mapping[str, Any]) -> list[float | None]:
    values = row["bootstrap"]["effect_ci_fraction"]
    offset = 0.5 if int(row["stage"]) == 1 else 0.0
    return [None if finite_number(value) is None else round12(100.0 * (float(value) - offset)) for value in values]


def audit_row_primary(row: Mapping[str, Any]) -> dict[str, Any]:
    checks = {name: bool(row["advancement_checks"][name]) for name in FORMAL_GATE_ORDER}
    failed = [name for name in FORMAL_GATE_ORDER if not checks[name]]
    horizon = horizon_diagnostic(row)
    condition = row["condition"]
    comparison = row.get("comparison")
    return {
        "session": row["session"], "stage": int(row["stage"]), "test_id": row["test_id"], "event_family": row["event_family"], "context": row.get("context"),
        "effect": {"condition_hit_rate": round12(condition.get("hit_rate")), "comparison_hit_rate": None if comparison is None else round12(comparison.get("hit_rate")), "effect_pp": round12(row.get("effect_pp")), "median_difference_usd": round12(row.get("median_difference_usd"))},
        "support": {"condition_events": int(condition["assigned_events"]), "condition_distinct_dates": int(row["condition_distinct_dates"]), "comparison_events": None if comparison is None else int(comparison["assigned_events"]), "minimum_bullish_bearish_condition_distinct_dates": int(row["minimum_bullish_bearish_condition_distinct_dates"]), "unknown_context_events": int(row["unknown_context_events"])},
        "uncertainty": {"bootstrap_effect_lift_ci_pp": _effect_ci_lift_pp(row), "bootstrap_median_difference_ci_usd": [round12(value) for value in row["bootstrap"]["median_difference_ci_usd"]], "finite_effect_replicates": int(row["bootstrap"]["finite_effect_replicates"]), "finite_median_replicates": int(row["bootstrap"]["finite_median_replicates"]), "randomization_p_value": round12(row["p_value"])},
        "multiplicity": {"method": "BH_BY_SESSION_AND_STAGE", "q_threshold": 0.05, "bh_q_value": round12(row["bh_q_value"]), "pass": checks["bh_q_lte_0_05"]},
        "directional_symmetry": row["directional_symmetry"],
        "annual_stability": row["annual_stability"],
        "rolling_block_stability": row["block_stability"],
        "horizon_consistency": horizon,
        "first_event_robustness": row["first_event_sensitivity"],
        "gc_consistency": row["gc_consistency"],
        "formal_gate_results": checks,
        "ordered_formal_failed_gates": failed,
        "first_formal_failed_gate": failed[0],
        "formal_failed_gate_count": len(failed),
        "attribution": classify_checks(checks, horizon["status"]),
        "original_verdict": row["verdict"],
        "candidate_or_validation_credit": False,
    }


def audit_row_reference(row: Mapping[str, Any]) -> dict[str, Any]:
    advancement = row.get("advancement_checks", {})
    checks: dict[str, bool] = {}
    failed: list[str] = []
    for gate in FORMAL_GATE_ORDER:
        passed = advancement.get(gate) is True
        checks[gate] = passed
        if not passed:
            failed.append(gate)
    secondary = list(row.get("secondary_consistency", []))
    secondary.sort(key=lambda value: int(value.get("horizon_minutes", -1)))
    horizon_rows: list[dict[str, Any]] = []
    positive = opposite = known = 0
    for value in secondary:
        effect = finite_number(value.get("effect_pp"))
        known += int(effect is not None)
        positive += int(effect is not None and effect > 0.0)
        opposite += int(effect is not None and effect <= -5.0)
        horizon_rows.append({"minutes": int(value["horizon_minutes"]), "effect_pp": round12(effect), "p_value": round12(value.get("p_value")), "holm_adjusted_p_value": round12(value.get("holm_adjusted_p_value"))})
    horizon_status = "INSUFFICIENT" if known != 3 else ("CONSISTENT" if positive >= 2 and opposite == 0 else "MIXED_OR_CONTRADICTORY")
    horizon = {"status": horizon_status, "known_horizons": known, "favorable_horizons": positive, "materially_opposite_horizons": opposite, "formal_m3_gate": False, "horizons": horizon_rows}
    condition = row["condition"]
    comparison = row.get("comparison")
    effect_ci = row["bootstrap"]["effect_ci_fraction"]
    adjustment = 50.0 if int(row["stage"]) == 1 else 0.0
    converted_ci = [None if finite_number(value) is None else round12(float(value) * 100.0 - adjustment) for value in effect_ci]
    statistical_pass = all(checks[gate] for gate in FORMAL_GATE_ORDER[:6])
    if statistical_pass and failed:
        category = "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS"
    elif not checks["frozen_effect_threshold"]:
        category = "NO_MEASURABLE_RELATIONSHIP"
    elif (not checks["directional_symmetry"] or not checks["annual_stability"] or not checks["block_stability"] or not checks["first_event_sensitivity"] or horizon_status != "CONSISTENT"):
        category = "UNSTABLE_RELATIONSHIP"
    else:
        category = "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED"
    return {
        "session": row["session"], "stage": int(row["stage"]), "test_id": row["test_id"], "event_family": row["event_family"], "context": row.get("context"),
        "effect": {"condition_hit_rate": round12(condition.get("hit_rate")), "comparison_hit_rate": None if comparison is None else round12(comparison.get("hit_rate")), "effect_pp": round12(row.get("effect_pp")), "median_difference_usd": round12(row.get("median_difference_usd"))},
        "support": {"condition_events": int(condition["assigned_events"]), "condition_distinct_dates": int(row["condition_distinct_dates"]), "comparison_events": None if comparison is None else int(comparison["assigned_events"]), "minimum_bullish_bearish_condition_distinct_dates": int(row["minimum_bullish_bearish_condition_distinct_dates"]), "unknown_context_events": int(row["unknown_context_events"])},
        "uncertainty": {"bootstrap_effect_lift_ci_pp": converted_ci, "bootstrap_median_difference_ci_usd": [round12(value) for value in row["bootstrap"]["median_difference_ci_usd"]], "finite_effect_replicates": int(row["bootstrap"]["finite_effect_replicates"]), "finite_median_replicates": int(row["bootstrap"]["finite_median_replicates"]), "randomization_p_value": round12(row["p_value"])},
        "multiplicity": {"method": "BH_BY_SESSION_AND_STAGE", "q_threshold": 0.05, "bh_q_value": round12(row["bh_q_value"]), "pass": checks["bh_q_lte_0_05"]},
        "directional_symmetry": row["directional_symmetry"], "annual_stability": row["annual_stability"], "rolling_block_stability": row["block_stability"], "horizon_consistency": horizon, "first_event_robustness": row["first_event_sensitivity"], "gc_consistency": row["gc_consistency"],
        "formal_gate_results": checks, "ordered_formal_failed_gates": failed, "first_formal_failed_gate": failed[0], "formal_failed_gate_count": len(failed), "attribution": category, "original_verdict": row["verdict"], "candidate_or_validation_credit": False,
    }


def near_miss_sort_key(row: Mapping[str, Any]) -> tuple[Any, ...]:
    q_value = finite_number(row["multiplicity"]["bh_q_value"])
    effect = finite_number(row["effect"]["effect_pp"])
    return (int(row["formal_failed_gate_count"]), float("inf") if q_value is None else q_value, -(effect if effect is not None else -float("inf")), str(row["test_id"]))


def aggregate_rows(rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    by_session: dict[str, Any] = {}
    for session in ("LONDON", "NEW_YORK"):
        selected = [row for row in rows if row["session"] == session]
        by_session[session] = {
            "audited": len(selected),
            "by_stage": {str(stage): sum(int(row["stage"]) == stage for row in selected) for stage in (1, 2)},
            "taxonomy": dict(sorted(Counter(str(row["attribution"]) for row in selected).items())),
            "formal_gate_failures": {gate: sum(not row["formal_gate_results"][gate] for row in selected) for gate in FORMAL_GATE_ORDER},
            "first_failed_gate": dict(sorted(Counter(str(row["first_formal_failed_gate"]) for row in selected).items())),
            "horizon_diagnostics": dict(sorted(Counter(str(row["horizon_consistency"]["status"]) for row in selected).items())),
            "effect_threshold_pass": sum(row["formal_gate_results"]["frozen_effect_threshold"] for row in selected),
            "bh_q_pass": sum(row["formal_gate_results"]["bh_q_lte_0_05"] for row in selected),
            "statistical_core_pass": sum(all(row["formal_gate_results"][gate] for gate in FORMAL_GATE_ORDER[:6]) for row in selected),
        }
    total_taxonomy = Counter(str(row["attribution"]) for row in rows)
    return {
        "audited_support_eligible_rejections": len(rows),
        "support_fail_preserved_not_reinterpreted": 34,
        "taxonomy": {name: total_taxonomy.get(name, 0) for name in TAXONOMY},
        "formal_gate_failures": {gate: sum(not row["formal_gate_results"][gate] for row in rows) for gate in FORMAL_GATE_ORDER},
        "first_failed_gate": dict(sorted(Counter(str(row["first_formal_failed_gate"]) for row in rows).items())),
        "by_session": by_session,
        "candidate_count": 0,
        "validation_credit": False,
    }


def choose_recommendation(aggregate: Mapping[str, Any]) -> dict[str, Any]:
    counts = aggregate["taxonomy"]
    dominant = sorted(DOMINANCE_TIE_PRIORITY, key=lambda name: (-int(counts[name]), DOMINANCE_TIE_PRIORITY.index(name)))[0]
    designs = {
        "NO_MEASURABLE_RELATIONSHIP": {
            "design_id": "V3_CONTINUOUS_STATE_RESPONSE_DISCOVERY",
            "research_question": "Do continuous signed microstructure state and event-intensity measurements explain the magnitude and direction of the next 15-minute XAUUSD displacement, conditional on session and a separately stated point-in-time directional prior?",
            "material_change": "Replace information-losing binary event-presence tests with transparent continuous dose-response estimates; do not lower any evidence or stability threshold.",
            "bounded_method": ["London and New York estimated separately", "pre-register a small traceable continuous feature set from the sealed 85 columns", "transparent regularized linear/additive effects with blocked out-of-fold predictions", "month-week and year stability gates retained", "5m/30m/60m remain consistency diagnostics", "no execution or PnL"],
        },
        "UNSTABLE_RELATIONSHIP": {
            "design_id": "V3_PRE_REGISTERED_TIME_REGIME_STABILITY_DISCOVERY",
            "research_question": "Are event responses stable only within preregistered point-in-time macro-reaction and liquidity regimes rather than pooled across structurally different periods?",
            "material_change": "Model a bounded set of preregistered regimes and explicit time variation while retaining the original uncertainty and multiplicity standards.",
            "bounded_method": ["London and New York separate", "no data-derived regime labels", "blocked out-of-fold estimation", "effect sign required across supported years and blocks", "no execution or PnL"],
        },
        "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED": {
            "design_id": "V3_OUTCOME_BLIND_DEVELOPMENT_SAMPLE_EXPANSION",
            "research_question": "Do the same frozen relationships become estimable with materially greater outcome-blind development coverage?",
            "material_change": "Expand dates before opening outcomes; preserve definitions and evidence thresholds.",
            "bounded_method": ["outcome-blind calendar sampling", "power target frozen before acquisition", "same session separation", "same multiplicity and stability gates", "no execution or PnL"],
        },
        "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS": {
            "design_id": "V3_TARGETED_UNCHANGED_ROBUSTNESS_REPLICATION",
            "research_question": "Can statistically credible development effects reproduce under the exact robustness dimension that rejected them?",
            "material_change": "Target the failed robustness dimension without changing the relationship definition or threshold.",
            "bounded_method": ["definitions unchanged", "failure-specific preregistered replication", "London and New York separate", "no candidate credit until all gates pass", "no execution or PnL"],
        },
    }
    return {
        "selected_from_dominant_attribution": dominant,
        "dominant_count": int(counts[dominant]),
        "tie_priority": list(DOMINANCE_TIE_PRIORITY),
        "recommendation": designs[dominant],
        "candidate_or_validation_credit": False,
    }


def build_payload(rows: list[dict[str, Any]]) -> dict[str, Any]:
    rows.sort(key=lambda row: (str(row["session"]), int(row["stage"]), str(row["test_id"])))
    for session in ("LONDON", "NEW_YORK"):
        ranked = sorted((row for row in rows if row["session"] == session), key=near_miss_sort_key)
        for rank, row in enumerate(ranked, start=1):
            row["descriptive_near_miss_rank_within_session"] = rank
    aggregate = aggregate_rows(rows)
    recommendation = choose_recommendation(aggregate)
    return {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_ATTRIBUTION_PAYLOAD_V1_0",
        "formal_gate_order": list(FORMAL_GATE_ORDER),
        "audited_results": rows,
        "audit_rows_hash": canonical_hash(rows),
        "aggregate": aggregate,
        "v3_design_recommendation": recommendation,
        "m3_zero_candidate_verdict_preserved": True,
        "new_candidates_created": 0,
        "market_sources_opened": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
    }


CSV_FIELDS = (
    "session", "stage", "test_id", "event_family", "context", "attribution", "descriptive_near_miss_rank_within_session",
    "condition_events", "condition_distinct_dates", "comparison_events", "condition_hit_rate", "comparison_hit_rate", "effect_pp", "median_difference_usd",
    "bootstrap_effect_lift_ci_lower_pp", "bootstrap_effect_lift_ci_upper_pp", "bootstrap_median_ci_lower_usd", "bootstrap_median_ci_upper_usd", "p_value", "bh_q_value", "multiplicity_pass",
    "directional_symmetry_pass", "annual_stability_pass", "block_stability_pass", "horizon_status", "effect_5m_pp", "effect_30m_pp", "effect_60m_pp", "first_event_pass", "first_event_effect_pp",
    "formal_failed_gate_count", "first_formal_failed_gate", "ordered_formal_failed_gates", "original_verdict", "candidate_or_validation_credit",
)


def csv_projection(row: Mapping[str, Any]) -> dict[str, Any]:
    horizon = {int(value["minutes"]): value for value in row["horizon_consistency"]["horizons"]}
    effect_ci = row["uncertainty"]["bootstrap_effect_lift_ci_pp"]
    median_ci = row["uncertainty"]["bootstrap_median_difference_ci_usd"]
    return {
        "session": row["session"], "stage": row["stage"], "test_id": row["test_id"], "event_family": row["event_family"], "context": row["context"], "attribution": row["attribution"], "descriptive_near_miss_rank_within_session": row["descriptive_near_miss_rank_within_session"],
        "condition_events": row["support"]["condition_events"], "condition_distinct_dates": row["support"]["condition_distinct_dates"], "comparison_events": row["support"]["comparison_events"], "condition_hit_rate": row["effect"]["condition_hit_rate"], "comparison_hit_rate": row["effect"]["comparison_hit_rate"], "effect_pp": row["effect"]["effect_pp"], "median_difference_usd": row["effect"]["median_difference_usd"],
        "bootstrap_effect_lift_ci_lower_pp": effect_ci[0], "bootstrap_effect_lift_ci_upper_pp": effect_ci[1], "bootstrap_median_ci_lower_usd": median_ci[0], "bootstrap_median_ci_upper_usd": median_ci[1], "p_value": row["uncertainty"]["randomization_p_value"], "bh_q_value": row["multiplicity"]["bh_q_value"], "multiplicity_pass": row["multiplicity"]["pass"],
        "directional_symmetry_pass": row["formal_gate_results"]["directional_symmetry"], "annual_stability_pass": row["formal_gate_results"]["annual_stability"], "block_stability_pass": row["formal_gate_results"]["block_stability"], "horizon_status": row["horizon_consistency"]["status"], "effect_5m_pp": horizon[5]["effect_pp"], "effect_30m_pp": horizon[30]["effect_pp"], "effect_60m_pp": horizon[60]["effect_pp"], "first_event_pass": row["formal_gate_results"]["first_event_sensitivity"], "first_event_effect_pp": round12(row["first_event_robustness"].get("effect_pp")),
        "formal_failed_gate_count": row["formal_failed_gate_count"], "first_formal_failed_gate": row["first_formal_failed_gate"], "ordered_formal_failed_gates": "|".join(row["ordered_formal_failed_gates"]), "original_verdict": row["original_verdict"], "candidate_or_validation_credit": False,
    }


def csv_bytes(rows: Sequence[Mapping[str, Any]]) -> bytes:
    import io
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(buffer, fieldnames=CSV_FIELDS, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        writer.writerow(csv_projection(row))
    return buffer.getvalue().encode("utf-8")


def run_audit(source: Path, output: Path, implementation: str) -> None:
    verify_freeze(source, output)
    if implementation == "primary":
        raw = load_json(source / "complete_results.json")["results"]
        eligible = [row for row in raw if row.get("support_status") == "SUPPORT_ELIGIBLE" and row.get("verdict") == "REJECT"]
        rows = [audit_row_primary(row) for row in eligible]
    else:
        stage1 = load_json(source / "reference_stage1_results.json")["payload"]["test_results"]
        stage2 = load_json(source / "reference_stage2_results.json")["payload"]["test_results"]
        eligible = [row for row in [*stage1, *stage2] if row.get("support_status") == "SUPPORT_ELIGIBLE" and row.get("verdict") == "REJECT"]
        rows = [audit_row_reference(row) for row in eligible]
    _require(len(rows) == 38, "Attribution population changed")
    _require(Counter(row["session"] for row in rows) == {"LONDON": 19, "NEW_YORK": 19}, "Session attribution population changed")
    payload = build_payload(rows)
    record = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_AUDIT_RUN_V1_0",
        "implementation": implementation,
        "completed_at_utc": utc_now(),
        "payload": payload,
        "payload_hash": canonical_hash(payload),
    }
    write_json_once(output / f"{implementation}_attribution.json", record)
    write_once(output / f"{implementation}_failure_matrix.csv", csv_bytes(payload["audited_results"]))
    print(json.dumps({"implementation": implementation, "payload_hash": record["payload_hash"], "taxonomy": payload["aggregate"]["taxonomy"], "recommendation": payload["v3_design_recommendation"]["recommendation"]["design_id"]}, sort_keys=True))


def report_text(payload: Mapping[str, Any]) -> str:
    aggregate = payload["aggregate"]
    recommendation = payload["v3_design_recommendation"]
    lines = [
        "# GC Session Trigger Edge Discovery V2 Milestone 4 Report", "", "Formal status: `PASS_M4_NEGATIVE_RESULT_ATTRIBUTION`", "",
        "## Audit population", "", "- 38 support-eligible Milestone 3 rejections audited: 19 London and 19 New York.", "- 34 outcome-blind support failures remain unchanged and were not reinterpreted.", "- The Milestone 3-R1 zero-candidate verdict remains unchanged.", "",
        "## Attribution taxonomy", "",
    ]
    for name in TAXONOMY:
        lines.append(f"- `{name}`: `{aggregate['taxonomy'][name]}`")
    lines.extend(["", "## Session results", ""])
    for session in ("LONDON", "NEW_YORK"):
        item = aggregate["by_session"][session]
        lines.extend([f"### {session.replace('_', ' ').title()}", "", f"- Audited: `{item['audited']}`.", f"- Effect-threshold passes: `{item['effect_threshold_pass']}`.", f"- BH q-value passes: `{item['bh_q_pass']}`.", f"- Complete statistical-core passes: `{item['statistical_core_pass']}`."])
        for name, count in item["taxonomy"].items():
            lines.append(f"- `{name}`: `{count}`.")
        lines.append("")
    lines.extend(["## Most frequent formal failures", ""])
    ordered = sorted(aggregate["formal_gate_failures"].items(), key=lambda item: (-item[1], FORMAL_GATE_ORDER.index(item[0])))
    for gate, count in ordered:
        lines.append(f"- `{gate}`: `{count}` of 38.")
    lines.extend([
        "", "## Exactly one bounded V3 recommendation", "",
        f"Selected design: `{recommendation['recommendation']['design_id']}`.", "",
        f"Dominant attribution: `{recommendation['selected_from_dominant_attribution']}` (`{recommendation['dominant_count']}` of 38).", "",
        recommendation["recommendation"]["research_question"], "",
        recommendation["recommendation"]["material_change"], "",
        "This is a research-design recommendation, not a candidate, signal, validation result, or trading edge.", "",
        "## Scope boundary", "", "No market source was reopened. Calendar 2025 and 2026 remained locked. No candidate, execution, trade, PnL, R multiple, position size, or return was calculated.", "",
    ])
    return "\n".join(lines)


def seal(source: Path, output: Path) -> None:
    _, freeze = verify_freeze(source, output)
    primary = load_json(output / "primary_attribution.json")
    reference = load_json(output / "reference_attribution.json")
    _require(primary["payload_hash"] == reference["payload_hash"], "Independent attribution payloads differ")
    _require(canonical_hash(primary["payload"]) == primary["payload_hash"], "Primary attribution payload hash invalid")
    _require(canonical_hash(reference["payload"]) == reference["payload_hash"], "Reference attribution payload hash invalid")
    _require(sha256_file(output / "primary_failure_matrix.csv") == sha256_file(output / "reference_failure_matrix.csv"), "Independent failure matrices differ")
    payload = primary["payload"]
    write_json_once(output / "failure_matrix.json", {"version": "GC_SESSION_TRIGGER_EDGE_V2_M4_FAILURE_MATRIX_V1_0", "rows": payload["audited_results"], "rows_hash": payload["audit_rows_hash"]})
    write_json_once(output / "aggregate_taxonomy.json", {"version": "GC_SESSION_TRIGGER_EDGE_V2_M4_AGGREGATE_V1_0", **payload["aggregate"]})
    write_json_once(output / "v3_design_recommendation.json", {"version": "GC_SESSION_TRIGGER_EDGE_V2_M4_V3_RECOMMENDATION_V1_0", **payload["v3_design_recommendation"]})
    write_once(output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_4_REPORT.md", report_text(payload).encode("utf-8"))
    verdict = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_VERDICT_V1_0",
        "status": "PASS_M4_NEGATIVE_RESULT_ATTRIBUTION",
        "formal_milestone_pass": True,
        "completed_at_utc": utc_now(),
        "m3_r1_status_preserved": "PASS_M3_R1_DISCOVERY_ZERO_CANDIDATES",
        "audited_support_eligible_rejections": 38,
        "support_fail_preserved": 34,
        "taxonomy": payload["aggregate"]["taxonomy"],
        "selected_v3_design": payload["v3_design_recommendation"]["recommendation"]["design_id"],
        "new_candidates_created": 0,
        "market_sources_opened": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "verdict_receipt": None,
    }
    verdict["verdict_receipt"] = canonical_hash({**verdict, "verdict_receipt": None})
    write_json_once(output / "verdict.json", verdict)
    artifact_names = (
        "preflight.json", "primary_attribution.json", "reference_attribution.json", "primary_failure_matrix.csv", "reference_failure_matrix.csv",
        "failure_matrix.json", "aggregate_taxonomy.json", "v3_design_recommendation.json", "GC_SESSION_TRIGGER_EDGE_MILESTONE_4_REPORT.md", "verdict.json",
    )
    manifest = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_MANIFEST_V1_0",
        "status": verdict["status"],
        "sealed_at_utc": utc_now(),
        "predecessor_m3r1_final_seal_receipt": freeze["predecessor"]["outer_final_seal_receipt"],
        "freeze_receipt": freeze["freeze_receipt"],
        "artifacts": {name: {"sha256": sha256_file(output / name), "bytes": (output / name).stat().st_size} for name in artifact_names},
        "independent_reproduction": {"exact_payload": True, "payload_hash": primary["payload_hash"], "byte_identical_csv": True, "csv_sha256": sha256_file(output / "primary_failure_matrix.csv")},
        "audited_support_eligible_rejections": 38,
        "new_candidates_created": 0,
        "market_sources_opened": False,
        "year_2025_or_2026_values_accessed": False,
        "execution_trade_pnl_r_or_return_calculated": False,
        "manifest_receipt": None,
    }
    manifest["manifest_receipt"] = canonical_hash({**manifest, "manifest_receipt": None})
    write_json_once(output / "manifest.json", manifest)
    final = {
        "version": "GC_SESSION_TRIGGER_EDGE_V2_M4_FINAL_SEAL_V1_0",
        "status": verdict["status"],
        "sealed_at_utc": utc_now(),
        "manifest_sha256": sha256_file(output / "manifest.json"),
        "manifest_receipt": manifest["manifest_receipt"],
        "verdict_sha256": sha256_file(output / "verdict.json"),
        "verdict_receipt": verdict["verdict_receipt"],
        "failure_matrix_sha256": sha256_file(output / "failure_matrix.json"),
        "report_sha256": sha256_file(output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_4_REPORT.md"),
        "final_seal_receipt": None,
    }
    final["final_seal_receipt"] = canonical_hash({**final, "final_seal_receipt": None})
    write_json_once(output / "final_seal.json", final)
    print(json.dumps({"status": verdict["status"], "taxonomy": verdict["taxonomy"], "selected_v3_design": verdict["selected_v3_design"], "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def verify(source: Path, output: Path) -> None:
    verify_freeze(source, output)
    primary = load_json(output / "primary_attribution.json")
    reference = load_json(output / "reference_attribution.json")
    verdict = load_json(output / "verdict.json")
    manifest = load_json(output / "manifest.json")
    final = load_json(output / "final_seal.json")
    _require(primary["payload_hash"] == reference["payload_hash"] == canonical_hash(primary["payload"]) == canonical_hash(reference["payload"]), "Payload reproduction verification failed")
    _require(sha256_file(output / "primary_failure_matrix.csv") == sha256_file(output / "reference_failure_matrix.csv"), "CSV reproduction verification failed")
    for record, field in ((verdict, "verdict_receipt"), (manifest, "manifest_receipt"), (final, "final_seal_receipt")):
        _require(receipt_valid(record, field), f"Invalid receipt: {field}")
    _require(sha256_file(output / "manifest.json") == final["manifest_sha256"], "Manifest changed after final seal")
    _require(sha256_file(output / "verdict.json") == final["verdict_sha256"], "Verdict changed after final seal")
    _require(sha256_file(output / "failure_matrix.json") == final["failure_matrix_sha256"], "Failure matrix changed after final seal")
    _require(sha256_file(output / "GC_SESSION_TRIGGER_EDGE_MILESTONE_4_REPORT.md") == final["report_sha256"], "Report changed after final seal")
    for name, metadata in manifest["artifacts"].items():
        _require(sha256_file(output / name) == metadata["sha256"], f"Sealed M4 artifact changed: {name}")
    _require(verdict["new_candidates_created"] == 0 and not verdict["market_sources_opened"], "Scope boundary failed")
    _require(not verdict["year_2025_or_2026_values_accessed"] and not verdict["execution_trade_pnl_r_or_return_calculated"], "Prohibited scope flag failed")
    print(json.dumps({"status": verdict["status"], "independent_reproduction": True, "audited_tests": verdict["audited_support_eligible_rejections"], "selected_v3_design": verdict["selected_v3_design"], "final_seal_receipt": final["final_seal_receipt"]}, sort_keys=True))


def self_test() -> None:
    base = {name: True for name in FORMAL_GATE_ORDER}
    cases = []
    checks = dict(base); checks["frozen_effect_threshold"] = False
    cases.append((checks, "CONSISTENT", "NO_MEASURABLE_RELATIONSHIP"))
    checks = dict(base); checks["bh_q_lte_0_05"] = False
    cases.append((checks, "CONSISTENT", "POTENTIALLY_MEANINGFUL_BUT_UNDERPOWERED"))
    checks = dict(base); checks["annual_stability"] = False
    cases.append((checks, "CONSISTENT", "STATISTICALLY_CREDIBLE_REJECTED_OTHER_ROBUSTNESS"))
    checks = dict(base); checks["bh_q_lte_0_05"] = False; checks["block_stability"] = False
    cases.append((checks, "CONSISTENT", "UNSTABLE_RELATIONSHIP"))
    for checks, horizon, expected in cases:
        _require(classify_checks(checks, horizon) == expected, f"Classification self-test failed: {expected}")
    record = {"a": 1, "receipt": None}
    record["receipt"] = canonical_hash(record)
    _require(receipt_valid(record, "receipt"), "Receipt self-test failed")
    print(json.dumps({"status": "PASS_M4_SELF_TEST", "taxonomy_cases": len(cases)}, sort_keys=True))


def parser() -> argparse.ArgumentParser:
    value = argparse.ArgumentParser()
    value.add_argument("action", choices=("self-test", "prepare", "audit-primary", "audit-reference", "seal", "verify"))
    value.add_argument("--source", type=Path, default=DEFAULT_INPUT)
    value.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return value


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.action == "self-test":
        self_test()
    elif args.action == "prepare":
        prepare(args.source.resolve(), args.output.resolve())
    elif args.action == "audit-primary":
        run_audit(args.source.resolve(), args.output.resolve(), "primary")
    elif args.action == "audit-reference":
        run_audit(args.source.resolve(), args.output.resolve(), "reference")
    elif args.action == "seal":
        seal(args.source.resolve(), args.output.resolve())
    else:
        verify(args.source.resolve(), args.output.resolve())
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Exception as exc:  # formal CLI boundary
        print(json.dumps({"status": "FAIL_M4", "error_type": type(exc).__name__, "error": str(exc)}, sort_keys=True), file=sys.stderr)
        raise
