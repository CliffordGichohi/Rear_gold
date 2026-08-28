#!/usr/bin/env python3
"""Outcome-free recertification for Auction-Plan Compiler V1 Amendment A."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import certify_gold_auction_plan_compiler_v1 as v1_runner  # noqa: E402
from gold_intel.analytics.auction_plan_compiler_v1_semantic_amendment_a import (  # noqa: E402
    _trigger_hierarchy_component,
    causality_violations,
    compile_auction_plan_v1_semantic_amendment_a,
    plan_integrity_violations,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
)


CONTRACT = ROOT / "GOLD_AUCTION_PLAN_COMPILER_V1_SEMANTIC_AMENDMENT_A.md"
COMPILER = (
    ROOT
    / "backend/src/gold_intel/analytics/auction_plan_compiler_v1_semantic_amendment_a.py"
)
TESTS = (
    ROOT
    / "backend/tests/unit/test_auction_plan_compiler_v1_semantic_amendment_a.py"
)
PRIOR_FINAL_SEAL = (
    ROOT / "research_artifacts/gold_auction_plan_compiler_v1/final_seal.json"
)
PRIOR_HUMAN_PRIMARY = (
    ROOT / "research_artifacts/gold_auction_plan_compiler_v1/human_plans.primary.json"
)
PRIOR_GAV_PRIMARY = (
    ROOT / "research_artifacts/gold_auction_plan_compiler_v1/gav_plans.primary.json"
)
OUT = ROOT / "research_artifacts/gold_auction_plan_compiler_v1_semantic_amendment_a"
FREEZE = OUT / "amendment_and_source_freeze.json"
SYNTHETIC_PROOF = OUT / "synthetic_hierarchy_proof.json"
HUMAN_PRIMARY = OUT / "human_plans.primary.json"
HUMAN_REFERENCE = OUT / "human_plans.reference.json"
GAV_PRIMARY = OUT / "gav_plans.primary.json"
GAV_REFERENCE = OUT / "gav_plans.reference.json"
MISMATCHES = OUT / "semantic_mismatch_catalog.json"
RESULT = OUT / "certification_result.json"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_PLAN_COMPILER_V1_SEMANTIC_AMENDMENT_A_REPORT.md"


def verify_prior_v1() -> dict[str, Any]:
    payload = v1_runner.validate_seal(PRIOR_FINAL_SEAL, "seal_sha256")
    if payload["status"] != "FAIL_SEMANTIC_FIDELITY_CERTIFICATION":
        raise RuntimeError("Prior V1 formal verdict differs")
    for item in payload["files"].values():
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"]:
            raise RuntimeError(f"Prior V1 artifact size differs: {path}")
        if v1_runner.sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Prior V1 artifact hash differs: {path}")
    return payload


def freeze() -> None:
    if OUT.exists() or REPORT.exists():
        raise RuntimeError("Amendment A output already exists")
    prior = verify_prior_v1()
    prior_freeze = v1_runner.validate_seal(v1_runner.FREEZE, "freeze_sha256")
    inputs = {
        "amendment": v1_runner.record(CONTRACT),
        "amended_compiler": v1_runner.record(COMPILER),
        "amended_tests": v1_runner.record(TESTS),
        "amended_runner": v1_runner.record(Path(__file__).resolve()),
        "prior_v1_final_seal": v1_runner.record(PRIOR_FINAL_SEAL),
        "prior_v1_human_primary": v1_runner.record(PRIOR_HUMAN_PRIMARY),
        "prior_v1_gav_primary": v1_runner.record(PRIOR_GAV_PRIMARY),
        "base_v1_compiler": v1_runner.record(v1_runner.COMPILER),
        "causal_structure_engine": v1_runner.record(
            ROOT / "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py"
        ),
        "human_visible_ledger": v1_runner.record(v1_runner.HUMAN_LEDGER),
        "human_stream_certification": v1_runner.record(v1_runner.HUMAN_CERTIFICATION),
        "human_population_registry": v1_runner.record(v1_runner.HUMAN_REGISTRY),
        "gav_signal_identity_registry": v1_runner.record(v1_runner.SIGNAL_REGISTRY),
        "gav_primary_stream": v1_runner.record(v1_runner.GAV_PRIMARY),
        "gav_reference_stream": v1_runner.record(v1_runner.GAV_REFERENCE),
        "gav_stream_certification": v1_runner.record(v1_runner.GAV_CERTIFICATION),
    }
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_V1_SEMANTIC_AMENDMENT_A_FREEZE_1_0",
        "status": "SEALED_BEFORE_AMENDED_FULL_RECOMPILATION",
        "frozen_at": v1_runner.now(),
        "prior_v1_status": prior["status"],
        "prior_v1_seal_sha256": prior["seal_sha256"],
        "permitted_change": {
            "separate_h4_h1_m15_m5_semantic_layers": True,
            "correct_explicit_htf_range_comparator": True,
        },
        "preserved_v1_gates": prior_freeze["gates"],
        "additional_gate": "V1_NON_TRIGGER_COMPONENTS_AND_DISPOSITIONS_EXACT",
        "prohibitions": prior_freeze["prohibitions"],
        "inputs": inputs,
        "human_is_market_truth": False,
        "edge_claim_permitted": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    v1_runner.write_json(FREEZE, v1_runner.seal(payload, "freeze_sha256"))
    print(json.dumps({"status": payload["status"], "freeze": str(FREEZE)}, indent=2))


def verify_freeze() -> dict[str, Any]:
    payload = v1_runner.validate_seal(FREEZE, "freeze_sha256")
    verify_prior_v1()
    for item in payload["inputs"].values():
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"] or v1_runner.sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Frozen input differs: {path}")
    return payload


_EXPLICIT_HTF_RANGE = re.compile(
    r"\b(?:h1|h4)\b(?:\s+\w+){0,4}\s+\brange\b",
    flags=re.IGNORECASE,
)


def expected_family(annotation: Mapping[str, Any]) -> str:
    text = " ".join(
        str(annotation.get(key) or "").casefold()
        for key in ("higher_timeframe_context", "preexisting_location", "thesis")
    )
    if any(word in text for word in ("structural repair", "repair", "reversal")):
        return "STRUCTURAL_REPAIR"
    explicit_htf_range = _EXPLICIT_HTF_RANGE.search(text) is not None
    if explicit_htf_range and any(word in text for word in ("discount", "premium")):
        return "RANGE_ROTATION"
    return "CONTINUATION_WITH_ROOM"


def expected_trigger_layers(annotation: Mapping[str, Any]) -> list[str]:
    text = " ".join(
        str(annotation.get(key) or "").casefold()
        for key in ("m15_transition", "session_liquidity_context", "thesis")
    )
    layers: list[str] = []
    if re.search(r"\bm15\b|15m|\bmin\s*15\b", text):
        layers.append("M15")
    if re.search(r"\bm5\b|5m|\bmin\s*5\b", text):
        layers.append("M5")
    return layers


def compiled_trigger_layers(plan: Mapping[str, Any]) -> list[str]:
    trigger = plan["components"].get("local_trigger")
    if not isinstance(trigger, Mapping):
        return []
    layers: list[str] = []
    setup = trigger.get("setup_transition")
    refinement = trigger.get("entry_refinement")
    if isinstance(setup, Mapping) and setup.get("timeframe") == "M15":
        layers.append("M15")
    if isinstance(refinement, Mapping) and refinement.get("timeframe") == "M5":
        layers.append("M5")
    return layers


def compare_human(decision: Mapping[str, Any], plan: Mapping[str, Any]) -> dict[str, Any]:
    action = str(decision["action"])
    if action == "NO_TRADE":
        return {
            "expected_action": "NO_TRADE",
            "no_direction_preserved": plan["disposition"] == "NO_TRADE_UNRESOLVED"
            and plan.get("unresolved_reason") == "NO_DIRECTION_PROPOSAL",
        }
    annotation = decision["annotation"]
    compiled = plan["disposition"] == "EXECUTABLE_PLAN"
    governing = plan["components"]["governing_auction"]
    trigger = plan["components"]["local_trigger"]
    invalidation = plan["components"]["structural_invalidation"]
    destination = plan["components"]["liquidity_destination"]
    family_expected = expected_family(annotation)
    layers_expected = expected_trigger_layers(annotation)
    layers_compiled = compiled_trigger_layers(plan)
    layer_match = bool(layers_expected) and all(
        layer in layers_compiled for layer in layers_expected
    )
    m15_atr = float(invalidation["m15_atr"]) if invalidation else None
    human_stop = float(decision["stop"])
    human_target = float(decision["target"])
    stop_price = float(invalidation["price"]) if invalidation else None
    target_price = float(destination["level"]) if destination else None
    target_timeframe = str(annotation.get("target_timeframe", "")).casefold()
    expected_h1 = target_timeframe in {"1h", "h1", "h1_opposing_liquidity"}
    return {
        "expected_action": action,
        "compiled": compiled,
        "expected_family": family_expected,
        "compiled_family": governing and governing["family"],
        "family_match": compiled and governing["family"] == family_expected,
        "expected_trigger_layers": layers_expected,
        "compiled_trigger_layers": layers_compiled,
        "trigger_hierarchy_match": compiled and layer_match,
        "compiled_execution_anchor_timeframe": (
            trigger and trigger["execution_anchor"]["timeframe"]
        ),
        "expected_h1_destination": expected_h1,
        "compiled_destination_timeframe": destination and destination["source_timeframe"],
        "destination_timeframe_match": (
            None
            if not expected_h1
            else compiled and destination is not None and destination["source_timeframe"] == "H1"
        ),
        "human_invalidation": human_stop,
        "compiled_invalidation": stop_price,
        "invalidation_absolute_difference": (
            abs(human_stop - stop_price) if stop_price is not None else None
        ),
        "invalidation_difference_m15_atr": (
            abs(human_stop - stop_price) / m15_atr
            if stop_price is not None and m15_atr is not None and m15_atr > 0
            else None
        ),
        "human_destination": human_target,
        "compiled_destination": target_price,
        "destination_absolute_difference": (
            abs(human_target - target_price) if target_price is not None else None
        ),
        "annotation_sha256": canonical_hash(annotation),
    }


def compile_human_side(
    side: str,
    decisions: Mapping[str, Mapping[str, Any]],
    streams: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for alias in v1_runner.HUMAN_ALIASES:
        decision = decisions[alias]
        direction = str(decision["action"]) if decision["action"] in {"LONG", "SHORT"} else None
        entry = float(decision["entry"]) if direction is not None else None
        plan = compile_auction_plan_v1_semantic_amendment_a(
            stream=streams[alias],
            decision_at=str(decision["expected_cursor_at"]),
            direction=direction,  # type: ignore[arg-type]
            entry_reference=entry,
        )
        row = {
            "case_alias": alias,
            "source_stream_sha256": streams[alias]["stream_sha256"],
            "decision_sha256": canonical_hash(decision),
            "plan": plan,
            "integrity_violations": plan_integrity_violations(plan),
            "causality_violations": causality_violations(plan),
            "semantic_comparison": compare_human(decision, plan),
            "row_sha256": None,
        }
        row["row_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
        rows.append(row)
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_HUMAN_AMENDMENT_A_1_0",
        "side": side,
        "rows": rows,
    }
    v1_runner.assert_no_banned_output(payload)
    return v1_runner.seal(payload, "payload_sha256")


def latest_visible_close(stream: dict[str, Any], signal_at: str) -> float:
    rows = complete_rows(stream["timeframes"]["1m"], signal_at)
    if not rows:
        raise RuntimeError(f"No completed M1 entry reference at {signal_at}")
    return float(rows[-1]["close"])


def compile_gav_side(
    side: str,
    registry: Mapping[str, Any],
    streams: Mapping[str, dict[str, Any]],
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source in registry["rows"]:
        alias = source["case_alias"]
        stream = streams[alias]
        plan = compile_auction_plan_v1_semantic_amendment_a(
            stream=stream,
            decision_at=source["signal_at"],
            direction=source["direction"],
            entry_reference=latest_visible_close(stream, source["signal_at"]),
        )
        row = {
            "case_alias": alias,
            "session_code": source["session_code"],
            "signal_at": source["signal_at"],
            "source_stream_sha256": stream["stream_sha256"],
            "plan": plan,
            "integrity_violations": plan_integrity_violations(plan),
            "causality_violations": causality_violations(plan),
            "row_sha256": None,
        }
        row["row_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
        rows.append(row)
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_GAV_AMENDMENT_A_1_0",
        "side": side,
        "rows": rows,
    }
    v1_runner.assert_no_banned_output(payload)
    return v1_runner.seal(payload, "payload_sha256")


def core(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key != "row_sha256"}
        for row in payload["rows"]
    ]


def _synthetic_event(identity: str, timeframe: str, at: str) -> dict[str, Any]:
    return {
        "identity": identity,
        "timeframe": timeframe,
        "direction": "LONG",
        "break_at": at,
        "broken_identity": identity + "-broken",
        "broken_level": 101.0,
        "protected_identity": identity + "-protected",
        "protected_level": 99.0,
        "origin_at": "2022-01-01T09:00:00Z",
        "origin_adverse": 99.5,
        "atr": 1.0,
        "buffer": 0.1,
    }


def synthetic_proof() -> dict[str, Any]:
    no_direction = compile_auction_plan_v1_semantic_amendment_a(
        stream={"timeframes": {}, "context_timeline": {}},
        decision_at="2022-01-01T10:00:00Z",
        direction=None,
        entry_reference=None,
    )
    repeated = compile_auction_plan_v1_semantic_amendment_a(
        stream={"timeframes": {}, "context_timeline": {}},
        decision_at="2022-01-01T10:00:00Z",
        direction=None,
        entry_reference=None,
    )
    hierarchy = _trigger_hierarchy_component(
        legacy_trigger={
            "identity": "legacy",
            "family": "M5_INTERNAL_ROTATION",
            "timeframe": "M5",
            "break_at": "2022-01-01T09:25:00Z",
        },
        active_m15=_synthetic_event("m15", "M15", "2022-01-01T09:15:00Z"),
        active_m5=_synthetic_event("m5", "M5", "2022-01-01T09:25:00Z"),
        m15_balance=None,
        direction="LONG",
        entry=101.0,
        cutoff="2022-01-01T10:00:00Z",
    )
    future_probe = json.loads(json.dumps(no_direction))
    future_probe["components"]["local_trigger"] = {
        "setup_transition": {"known_at": "2022-01-01T10:01:00Z"}
    }
    gates = {
        "no_direction_unresolved": no_direction["disposition"] == "NO_TRADE_UNRESOLVED",
        "deterministic_repeat": no_direction == repeated,
        "m15_setup_retained": hierarchy["setup_transition"]["timeframe"] == "M15",
        "m5_refinement_retained": hierarchy["entry_refinement"]["timeframe"] == "M5",
        "m5_execution_anchor_preserved": hierarchy["execution_anchor"]["timeframe"] == "M5",
        "nested_future_probe_detected": len(causality_violations(future_probe)) == 1,
        "no_learned_geometry": no_direction["learned_geometry_used"] is False,
    }
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_AMENDMENT_A_SYNTHETIC_PROOF_1_0",
        "created_at": v1_runner.now(),
        "gates": gates,
        "verdict": "PASS" if all(gates.values()) else "FAIL",
    }
    return v1_runner.seal(payload, "proof_sha256")


def ratio(values: Sequence[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def certification_metrics(
    human_rows: Sequence[Mapping[str, Any]], gav_rows: Sequence[Mapping[str, Any]]
) -> dict[str, Any]:
    trades = [row for row in human_rows if row["semantic_comparison"]["expected_action"] != "NO_TRADE"]
    no_trades = [row for row in human_rows if row["semantic_comparison"]["expected_action"] == "NO_TRADE"]
    compiled = [row for row in trades if row["plan"]["disposition"] == "EXECUTABLE_PLAN"]
    family = [bool(row["semantic_comparison"]["family_match"]) for row in compiled]
    hierarchy = [bool(row["semantic_comparison"]["trigger_hierarchy_match"]) for row in compiled]
    destinations = [
        bool(row["semantic_comparison"]["destination_timeframe_match"])
        for row in compiled
        if row["semantic_comparison"]["destination_timeframe_match"] is not None
    ]
    all_rows = [*human_rows, *gav_rows]
    return {
        "human": {
            "cases": len(human_rows),
            "trade_proposals": len(trades),
            "no_trade_proposals": len(no_trades),
            "compiled_trade_plans": len(compiled),
            "no_direction_preserved": sum(
                bool(row["semantic_comparison"].get("no_direction_preserved"))
                for row in no_trades
            ),
            "family_agreement": ratio(family),
            "family_agreement_numerator": sum(family),
            "family_agreement_denominator": len(family),
            "trigger_timeframe_agreement": ratio(hierarchy),
            "trigger_timeframe_agreement_numerator": sum(hierarchy),
            "trigger_timeframe_agreement_denominator": len(hierarchy),
            "h1_destination_agreement": ratio(destinations),
            "h1_destination_agreement_numerator": sum(destinations),
            "h1_destination_agreement_denominator": len(destinations),
        },
        "gav": {
            "signal_proposals": len(gav_rows),
            "executable_plans": sum(row["plan"]["disposition"] == "EXECUTABLE_PLAN" for row in gav_rows),
            "unresolved_plans": sum(row["plan"]["disposition"] == "NO_TRADE_UNRESOLVED" for row in gav_rows),
            "dispositions": dict(sorted(Counter(row["plan"]["disposition"] for row in gav_rows).items())),
            "missing_components": dict(
                sorted(
                    Counter(
                        component
                        for row in gav_rows
                        for component in row["plan"]["missing_components"]
                    ).items()
                )
            ),
        },
        "integrity_violations": sum(len(row["integrity_violations"]) for row in all_rows),
        "causality_violations": sum(len(row["causality_violations"]) for row in all_rows),
    }


def v1_non_trigger_components_preserved(
    amended_human: Sequence[Mapping[str, Any]], amended_gav: Sequence[Mapping[str, Any]]
) -> tuple[bool, list[dict[str, Any]]]:
    old_human = v1_runner.validate_seal(PRIOR_HUMAN_PRIMARY, "payload_sha256")["rows"]
    old_gav = v1_runner.validate_seal(PRIOR_GAV_PRIMARY, "payload_sha256")["rows"]
    old_by_alias = {row["case_alias"]: row for row in [*old_human, *old_gav]}
    differences: list[dict[str, Any]] = []
    component_names = (
        "macro_context",
        "governing_auction",
        "controlling_structure",
        "structural_invalidation",
        "liquidity_destination",
    )
    for row in [*amended_human, *amended_gav]:
        alias = row["case_alias"]
        old_plan = old_by_alias[alias]["plan"]
        new_plan = row["plan"]
        changed = [
            name
            for name in component_names
            if canonical_hash(old_plan["components"][name])
            != canonical_hash(new_plan["components"][name])
        ]
        if old_plan["disposition"] != new_plan["disposition"]:
            changed.append("disposition")
        if old_plan["missing_components"] != new_plan["missing_components"]:
            changed.append("missing_components")
        if changed:
            differences.append({"case_alias": alias, "changed": changed})
    return not differences, differences


def mismatch_catalog(
    human_rows: Sequence[Mapping[str, Any]],
    gav_rows: Sequence[Mapping[str, Any]],
    preservation_differences: Sequence[Mapping[str, Any]],
) -> dict[str, Any]:
    human: list[dict[str, Any]] = []
    for row in human_rows:
        comparison = row["semantic_comparison"]
        reasons: list[str] = []
        if comparison["expected_action"] == "NO_TRADE":
            if not comparison["no_direction_preserved"]:
                reasons.append("HUMAN_NO_TRADE_NOT_PRESERVED")
        else:
            if not comparison["compiled"]:
                reasons.append("HUMAN_TRADE_UNRESOLVED")
            if comparison["compiled"] and not comparison["family_match"]:
                reasons.append("GOVERNING_FAMILY_MISMATCH")
            if comparison.get("trigger_hierarchy_match") is False:
                reasons.append("TRIGGER_HIERARCHY_MISMATCH")
            if comparison.get("destination_timeframe_match") is False:
                reasons.append("DESTINATION_TIMEFRAME_MISMATCH")
        if reasons:
            human.append(
                {
                    "case_alias": row["case_alias"],
                    "reasons": reasons,
                    "missing_components": row["plan"]["missing_components"],
                    "semantic_comparison": comparison,
                }
            )
    gav = [
        {
            "case_alias": row["case_alias"],
            "disposition": row["plan"]["disposition"],
            "missing_components": row["plan"]["missing_components"],
        }
        for row in gav_rows
        if row["plan"]["disposition"] != "EXECUTABLE_PLAN"
    ]
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_AMENDMENT_A_MISMATCHES_1_0",
        "human_mismatches": human,
        "gav_unresolved": gav,
        "v1_preservation_differences": list(preservation_differences),
        "human_mismatch_count": len(human),
        "gav_unresolved_count": len(gav),
    }
    v1_runner.assert_no_banned_output(payload)
    return v1_runner.seal(payload, "catalog_sha256")


def markdown(result: Mapping[str, Any], catalog: Mapping[str, Any]) -> str:
    human = result["metrics"]["human"]
    gav = result["metrics"]["gav"]
    lines = [
        "# Gold Auction-Plan Compiler V1 — Semantic Amendment A Result",
        "",
        f"Formal verdict: **{result['verdict']}**",
        "",
        "This is an outcome-free semantic certification. Agreement means the compiler can represent the annotated reasoning hierarchy; it does not establish that either the annotation or compiler is market-correct, and it is not an edge or profitability result.",
        "",
        "## Human-plan representation",
        "",
        f"- Trade plans compiled: **{human['compiled_trade_plans']} / {human['trade_proposals']}**.",
        f"- No-trades preserved: **{human['no_direction_preserved']} / {human['no_trade_proposals']}**.",
        f"- Governing-auction agreement: **{human['family_agreement_numerator']} / {human['family_agreement_denominator']}** ({100 * (human['family_agreement'] or 0):.1f}%).",
        f"- M15/M5 hierarchy coverage: **{human['trigger_timeframe_agreement_numerator']} / {human['trigger_timeframe_agreement_denominator']}** ({100 * (human['trigger_timeframe_agreement'] or 0):.1f}%).",
        f"- H1 destination agreement: **{human['h1_destination_agreement_numerator']} / {human['h1_destination_agreement_denominator']}** ({100 * (human['h1_destination_agreement'] or 0):.1f}%).",
        "",
        "## Existing GAV proposal disposition",
        "",
        f"- Proposals processed: **{gav['signal_proposals']}**.",
        f"- Executable plans: **{gav['executable_plans']}**.",
        f"- Explicit unresolved plans: **{gav['unresolved_plans']}**.",
        "",
        "## Gates",
        "",
    ]
    lines.extend(
        f"- `{name}`: **{'PASS' if passed else 'FAIL'}**"
        for name, passed in result["gates"].items()
    )
    lines.extend(
        [
            "",
            "## Remaining disagreements",
            "",
            f"- Human cases with a remaining mismatch: **{catalog['human_mismatch_count']}**.",
            f"- Existing GAV proposals unresolved: **{catalog['gav_unresolved_count']}**.",
            "- Every disagreement remains documented; none was removed or converted into a performance filter.",
            "",
            "## Boundary of this result",
            "",
            "The compiler still receives a proposed direction, timestamp, and visible entry reference. Independent setup discovery and economic validation remain separate tests.",
        ]
    )
    return "\n".join(lines)


def certify() -> None:
    frozen = verify_freeze()
    targets = (
        SYNTHETIC_PROOF,
        HUMAN_PRIMARY,
        HUMAN_REFERENCE,
        GAV_PRIMARY,
        GAV_REFERENCE,
        MISMATCHES,
        RESULT,
        FINAL_SEAL,
        REPORT,
    )
    if any(path.exists() for path in targets):
        raise RuntimeError("Amendment A certification artifact already exists")
    proof = synthetic_proof()
    v1_runner.write_json(SYNTHETIC_PROOF, proof)
    if proof["verdict"] != "PASS":
        raise RuntimeError("Synthetic hierarchy proof failed")

    visible_rows = v1_runner.load_jsonl(v1_runner.HUMAN_LEDGER)
    visible_head = v1_runner.verify_visible_chain(visible_rows)
    decisions = v1_runner.human_decisions(visible_rows)
    action_counts = Counter(row["action"] for row in decisions.values())
    if sum(action_counts[action] for action in ("LONG", "SHORT")) != 16 or action_counts["NO_TRADE"] != 14:
        raise RuntimeError(f"Human population differs: {action_counts}")

    human_primary = compile_human_side("primary", decisions, v1_runner.human_streams("primary"))
    v1_runner.write_json(HUMAN_PRIMARY, human_primary)
    human_reference = compile_human_side("reference", decisions, v1_runner.human_streams("reference"))
    v1_runner.write_json(HUMAN_REFERENCE, human_reference)
    human_exact = core(human_primary) == core(human_reference)

    registry = v1_runner.validate_seal(v1_runner.SIGNAL_REGISTRY, "registry_sha256")
    gav_primary = compile_gav_side("primary", registry, v1_runner.gav_streams("primary"))
    v1_runner.write_json(GAV_PRIMARY, gav_primary)
    gav_reference = compile_gav_side("reference", registry, v1_runner.gav_streams("reference"))
    v1_runner.write_json(GAV_REFERENCE, gav_reference)
    gav_exact = core(gav_primary) == core(gav_reference)

    metrics = certification_metrics(human_primary["rows"], gav_primary["rows"])
    v1_preserved, preservation_differences = v1_non_trigger_components_preserved(
        human_primary["rows"], gav_primary["rows"]
    )
    minimums = frozen["preserved_v1_gates"]
    gates = {
        "synthetic_hierarchy_proof": proof["verdict"] == "PASS",
        "prior_v1_seals_preserved": True,
        "v1_non_trigger_components_and_dispositions_exact": v1_preserved,
        "human_primary_reference_exact": human_exact,
        "gav_primary_reference_exact": gav_exact,
        "no_integrity_violations": metrics["integrity_violations"] <= minimums["integrity_violations_maximum"],
        "no_causality_violations": metrics["causality_violations"] <= minimums["causality_violations_maximum"],
        "human_no_trades_preserved": metrics["human"]["no_direction_preserved"] == 14,
        "human_trade_plan_coverage": metrics["human"]["compiled_trade_plans"] >= minimums["human_trade_plan_coverage_minimum"],
        "governing_auction_agreement": (metrics["human"]["family_agreement"] or 0.0) >= minimums["family_agreement_minimum"],
        "trigger_timeframe_agreement": (metrics["human"]["trigger_timeframe_agreement"] or 0.0) >= minimums["trigger_timeframe_agreement_minimum"],
        "h1_destination_agreement": (metrics["human"]["h1_destination_agreement"] or 0.0) >= minimums["h1_destination_agreement_minimum"],
        "gav_resolved_exactly_once": metrics["gav"]["signal_proposals"] == minimums["gav_exactly_once"]
        and metrics["gav"]["executable_plans"] + metrics["gav"]["unresolved_plans"] == minimums["gav_exactly_once"],
        "learned_geometry_absent": all(
            row["plan"]["learned_geometry_used"] is False
            for row in [*human_primary["rows"], *gav_primary["rows"]]
        ),
        "outcomes_and_fresh_periods_unopened": True,
    }
    verdict = (
        "PASS_SEMANTIC_AMENDMENT_A_CERTIFICATION"
        if all(gates.values())
        else "FAIL_SEMANTIC_AMENDMENT_A_CERTIFICATION"
    )
    catalog = mismatch_catalog(
        human_primary["rows"], gav_primary["rows"], preservation_differences
    )
    v1_runner.write_json(MISMATCHES, catalog)
    result = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_SEMANTIC_AMENDMENT_A_RESULT_1_0",
        "verdict": verdict,
        "completed_at": v1_runner.now(),
        "freeze_sha256": frozen["freeze_sha256"],
        "prior_v1_seal_sha256": frozen["prior_v1_seal_sha256"],
        "human_visible_head_sha256": visible_head,
        "synthetic_proof_sha256": proof["proof_sha256"],
        "human_primary_sha256": human_primary["payload_sha256"],
        "human_reference_sha256": human_reference["payload_sha256"],
        "gav_primary_sha256": gav_primary["payload_sha256"],
        "gav_reference_sha256": gav_reference["payload_sha256"],
        "mismatch_catalog_sha256": catalog["catalog_sha256"],
        "metrics": metrics,
        "gates": gates,
        "human_is_market_truth": False,
        "edge_claimed": False,
        "outcome_artifacts_opened": False,
        "pnl_calculated": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    v1_runner.assert_no_banned_output(result)
    v1_runner.write_json(RESULT, v1_runner.seal(result, "result_sha256"))
    v1_runner.write_text(REPORT, markdown(result, catalog))
    files = (
        FREEZE,
        SYNTHETIC_PROOF,
        HUMAN_PRIMARY,
        HUMAN_REFERENCE,
        GAV_PRIMARY,
        GAV_REFERENCE,
        MISMATCHES,
        RESULT,
        REPORT,
    )
    final = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_AMENDMENT_A_FINAL_SEAL_1_0",
        "status": verdict,
        "sealed_at": v1_runner.now(),
        "files": {
            path.name: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": v1_runner.sha256_file(path),
            }
            for path in files
        },
    }
    v1_runner.write_json(FINAL_SEAL, v1_runner.seal(final, "seal_sha256"))
    print(
        json.dumps(
            {
                "verdict": verdict,
                "metrics": metrics,
                "failed_gates": [name for name, passed in gates.items() if not passed],
                "report": str(REPORT),
            },
            indent=2,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=("freeze", "certify"))
    args = parser.parse_args()
    if args.stage == "freeze":
        freeze()
    else:
        certify()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
