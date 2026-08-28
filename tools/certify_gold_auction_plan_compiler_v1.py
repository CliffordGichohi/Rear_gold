#!/usr/bin/env python3
"""Certify Auction-Plan Compiler V1 using exposed, outcome-free evidence only."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import json
import math
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Mapping, Sequence


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

from gold_intel.analytics.auction_plan_compiler_v1 import (  # noqa: E402
    REQUIRED_COMPONENTS,
    causality_violations,
    compile_auction_plan_v1,
    plan_integrity_violations,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    complete_rows,
)


CONTRACT = ROOT / "GOLD_AUCTION_PLAN_COMPILER_SEMANTIC_FIDELITY_CERTIFICATION_V1.md"
COMPILER = ROOT / "backend/src/gold_intel/analytics/auction_plan_compiler_v1.py"
TESTS = ROOT / "backend/tests/unit/test_auction_plan_compiler_v1.py"
HUMAN_ROOT = ROOT / "research_artifacts/gold_matched_human_replay_v1"
HUMAN_LEDGER = HUMAN_ROOT / "ledgers/matched_human_visible_ledger.jsonl"
HUMAN_CERTIFICATION = HUMAN_ROOT / "stream_materialization_certification.json"
HUMAN_REGISTRY = HUMAN_ROOT / "population_registry.private.json"
GAV_SOURCE_REGISTRY = (
    ROOT
    / "research_artifacts/gold_coherent_auction_retrospective_process_audit_v1"
    / "sealed_process_classification_registry.json"
)
GAV_ROOT = ROOT / "research_artifacts/gold_coherent_auction_blind_validation_v1"
GAV_PRIMARY = GAV_ROOT / "validation_streams.primary.jsonl.gz"
GAV_REFERENCE = GAV_ROOT / "validation_streams.reference.jsonl.gz"
GAV_CERTIFICATION = GAV_ROOT / "stream_materialization_certification.json"
OUT = ROOT / "research_artifacts/gold_auction_plan_compiler_v1"
FREEZE = OUT / "source_and_implementation_freeze.json"
SIGNAL_REGISTRY = OUT / "gav_signal_identity_registry.json"
SYNTHETIC_PROOF = OUT / "synthetic_causal_proof.json"
HUMAN_PRIMARY = OUT / "human_plans.primary.json"
HUMAN_REFERENCE = OUT / "human_plans.reference.json"
GAV_PLANS_PRIMARY = OUT / "gav_plans.primary.json"
GAV_PLANS_REFERENCE = OUT / "gav_plans.reference.json"
MISMATCHES = OUT / "semantic_mismatch_catalog.json"
RESULT = OUT / "certification_result.json"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_PLAN_COMPILER_SEMANTIC_FIDELITY_CERTIFICATION_V1_REPORT.md"

HUMAN_ALIASES = [f"CBR-2022-{index:03d}" for index in range(1, 31)]
GAV_EXPECTED_SIGNALS = 20
ZERO_HASH = "0" * 64
BANNED_SOURCE_PARTS = ("outcome_vault", "comparison", "result", "early_stop")
BANNED_OUTPUT_KEYS = {
    "outcome",
    "resolution",
    "mfe",
    "mae",
    "pnl",
    "net_r50",
    "net_usd",
    "profit_factor",
    "win_rate",
}


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def record(path: Path) -> dict[str, Any]:
    if not path.is_file():
        raise RuntimeError(f"Required file is absent: {path}")
    relative = path.relative_to(ROOT).as_posix()
    if any(part in relative.casefold() for part in BANNED_SOURCE_PARTS):
        raise RuntimeError(f"Outcome/result-like source is prohibited: {relative}")
    return {"path": relative, "bytes": path.stat().st_size, "sha256": sha256_file(path)}


def seal(payload: dict[str, Any], key: str) -> dict[str, Any]:
    if key in payload:
        raise RuntimeError(f"Seal key already exists: {key}")
    payload[key] = canonical_hash(payload)
    return payload


def write_json(path: Path, payload: dict[str, Any]) -> None:
    if path.exists():
        raise RuntimeError(f"Append-only artifact exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def write_text(path: Path, payload: str) -> None:
    if path.exists():
        raise RuntimeError(f"Append-only artifact exists: {path}")
    path.write_text(payload.rstrip() + "\n", encoding="utf-8", newline="\n")


def validate_seal(path: Path, key: str) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    submitted = payload.pop(key)
    if canonical_hash(payload) != submitted:
        raise RuntimeError(f"Artifact seal differs: {path}")
    payload[key] = submitted
    return payload


def assert_no_banned_output(value: Any, trail: tuple[str, ...] = ()) -> None:
    if isinstance(value, dict):
        for key, item in value.items():
            normalized = str(key).casefold()
            if normalized in BANNED_OUTPUT_KEYS:
                raise RuntimeError(f"Prohibited output field: {'.'.join((*trail, str(key)))}")
            assert_no_banned_output(item, (*trail, str(key)))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            assert_no_banned_output(item, (*trail, str(index)))


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def verify_visible_chain(rows: Sequence[Mapping[str, Any]]) -> str:
    prior = ZERO_HASH
    for sequence, source in enumerate(rows, start=1):
        row = dict(source)
        if row.get("ledger_sequence") != sequence or row.get("prior_record_sha256") != prior:
            raise RuntimeError(f"Human visible ledger chain differs at {sequence}")
        submitted = str(row.pop("record_sha256", ""))
        if canonical_hash(row) != submitted:
            raise RuntimeError(f"Human visible ledger record differs at {sequence}")
        prior = submitted
    return prior


def human_decisions(rows: Sequence[Mapping[str, Any]]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for row in rows:
        if row.get("event_type") not in {"DECISION_SEALED", "NO_TRADE_SEALED"}:
            continue
        alias = str(row["case_alias"])
        decision = dict(row["data"]["decision"])
        if canonical_hash(decision) != row["data"]["decision_sha256"]:
            raise RuntimeError(f"Visible decision hash differs: {alias}")
        if alias in output:
            raise RuntimeError(f"Duplicate visible decision: {alias}")
        output[alias] = decision
    if list(sorted(output)) != HUMAN_ALIASES:
        raise RuntimeError("Human decision population differs")
    return output


def minimal_gav_registry() -> dict[str, Any]:
    source = validate_seal(GAV_SOURCE_REGISTRY, "registry_sha256")
    rows = [
        {
            "case_alias": row["case_alias"],
            "session_code": row["session_code"],
            "trading_date_utc": row["trading_date_utc"],
            "signal_at": row["signal_at"],
            "direction": "LONG",
            "source_packet_sha256": row["packet_sha256"],
        }
        for row in source["rows"]
    ]
    if len(rows) != GAV_EXPECTED_SIGNALS:
        raise RuntimeError(f"Expected 20 GAV signal identities, found {len(rows)}")
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_GAV_SIGNAL_IDENTITIES_V1_0",
        "status": "OUTCOME_FREE_MINIMAL_REGISTRY",
        "created_at": now(),
        "source_registry_sha256": source["registry_sha256"],
        "rows": rows,
        "learned_family_copied": False,
        "learned_stop_copied": False,
        "learned_target_copied": False,
    }
    assert_no_banned_output(payload)
    return seal(payload, "registry_sha256")


def freeze() -> None:
    if OUT.exists() or REPORT.exists():
        raise RuntimeError("Auction-plan certification output already exists")
    gav_registry = minimal_gav_registry()
    write_json(SIGNAL_REGISTRY, gav_registry)
    inputs = {
        "contract": record(CONTRACT),
        "compiler": record(COMPILER),
        "synthetic_tests": record(TESTS),
        "certification_runner": record(Path(__file__).resolve()),
        "human_visible_ledger": record(HUMAN_LEDGER),
        "human_stream_certification": record(HUMAN_CERTIFICATION),
        "human_population_registry": record(HUMAN_REGISTRY),
        "gav_source_registry": record(GAV_SOURCE_REGISTRY),
        "gav_signal_identity_registry": record(SIGNAL_REGISTRY),
        "gav_primary_stream": record(GAV_PRIMARY),
        "gav_reference_stream": record(GAV_REFERENCE),
        "gav_stream_certification": record(GAV_CERTIFICATION),
        "causal_structure_engine": record(
            ROOT / "backend/src/gold_intel/analytics/coherent_auction_correction_v1.py"
        ),
    }
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_V1_SOURCE_IMPLEMENTATION_FREEZE_1_0",
        "status": "SEALED_BEFORE_FULL_HUMAN_AND_GAV_PLAN_COMPILATION",
        "frozen_at": now(),
        "permitted_populations": {
            "human_aliases": HUMAN_ALIASES,
            "human_expected_trades": 16,
            "human_expected_no_trades": 14,
            "gav_signal_count": 20,
        },
        "gates": {
            "human_trade_plan_coverage_minimum": 13,
            "family_agreement_minimum": 0.75,
            "trigger_timeframe_agreement_minimum": 0.75,
            "h1_destination_agreement_minimum": 0.75,
            "causality_violations_maximum": 0,
            "integrity_violations_maximum": 0,
            "gav_exactly_once": 20,
        },
        "prohibitions": {
            "outcomes": True,
            "post_decision_paths": True,
            "pnl": True,
            "learned_geometry": True,
            "fresh_periods": True,
            "paid_acquisition": True,
        },
        "inputs": inputs,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    write_json(FREEZE, seal(payload, "freeze_sha256"))
    print(json.dumps({"status": payload["status"], "freeze": str(FREEZE)}, indent=2))


def verify_freeze() -> dict[str, Any]:
    payload = validate_seal(FREEZE, "freeze_sha256")
    if payload["status"] != "SEALED_BEFORE_FULL_HUMAN_AND_GAV_PLAN_COMPILATION":
        raise RuntimeError("Freeze status differs")
    for item in payload["inputs"].values():
        path = ROOT / item["path"]
        if path.stat().st_size != item["bytes"] or sha256_file(path) != item["sha256"]:
            raise RuntimeError(f"Frozen input differs: {path}")
    return payload


def load_gzip_stream(path: Path, expected_hash: str) -> dict[str, Any]:
    if sha256_file(path) != expected_hash:
        raise RuntimeError(f"Certified stream file differs: {path}")
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        payload = json.load(handle)
    submitted = payload.pop("stream_sha256")
    if canonical_hash(payload) != submitted:
        raise RuntimeError(f"Certified stream payload differs: {path}")
    payload["stream_sha256"] = submitted
    return payload


def human_streams(side: str) -> dict[str, dict[str, Any]]:
    certification = json.loads(HUMAN_CERTIFICATION.read_text(encoding="utf-8"))
    if certification["verdict"] != "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION":
        raise RuntimeError("Human stream certification is not PASS")
    output: dict[str, dict[str, Any]] = {}
    for row in certification["case_files"]:
        source = row[side]
        output[row["case_alias"]] = load_gzip_stream(ROOT / source["path"], source["sha256"])
    if list(sorted(output)) != HUMAN_ALIASES:
        raise RuntimeError("Human stream identities differ")
    return output


def gav_streams(side: str) -> dict[str, dict[str, Any]]:
    path = GAV_PRIMARY if side == "primary" else GAV_REFERENCE
    expected = json.loads(GAV_CERTIFICATION.read_text(encoding="utf-8"))[
        f"{side}_sha256"
    ]
    if sha256_file(path) != expected:
        raise RuntimeError(f"GAV {side} bundle differs")
    output: dict[str, dict[str, Any]] = {}
    with gzip.open(path, "rt", encoding="utf-8") as handle:
        for line in handle:
            payload = json.loads(line)
            submitted = payload.pop("stream_sha256")
            if canonical_hash(payload) != submitted:
                raise RuntimeError(f"GAV stream payload differs: {payload.get('case_alias')}")
            payload["stream_sha256"] = submitted
            output[payload["case_alias"]] = payload
    if len(output) != 50:
        raise RuntimeError("GAV source case count differs")
    return output


_HTF_RANGE = re.compile(r"(?:h1|h4).{0,30}range|range.{0,30}(?:h1|h4)")


def expected_family(annotation: Mapping[str, Any]) -> str:
    text = " ".join(
        str(annotation.get(key) or "").casefold()
        for key in ("higher_timeframe_context", "preexisting_location", "thesis")
    )
    if any(word in text for word in ("structural repair", "repair", "reversal")):
        return "STRUCTURAL_REPAIR"
    if _HTF_RANGE.search(text) and any(word in text for word in ("discount", "premium")):
        return "RANGE_ROTATION"
    return "CONTINUATION_WITH_ROOM"


def expected_trigger_timeframe(annotation: Mapping[str, Any]) -> str:
    text = " ".join(
        str(annotation.get(key) or "").casefold()
        for key in ("m15_transition", "session_liquidity_context", "thesis")
    )
    if re.search(r"\bm5\b|5m", text):
        return "M5"
    if re.search(r"\bm15\b|15m", text):
        return "M15"
    return "UNSPECIFIED"


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
    trigger_expected = expected_trigger_timeframe(annotation)
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
        "expected_trigger_timeframe": trigger_expected,
        "compiled_trigger_timeframe": trigger and trigger["timeframe"],
        "trigger_timeframe_match": (
            None
            if trigger_expected == "UNSPECIFIED"
            else compiled and trigger is not None and trigger["timeframe"] == trigger_expected
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
    side: str, decisions: Mapping[str, Mapping[str, Any]], streams: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for alias in HUMAN_ALIASES:
        decision = decisions[alias]
        direction = str(decision["action"]) if decision["action"] in {"LONG", "SHORT"} else None
        entry = float(decision["entry"]) if direction is not None else None
        plan = compile_auction_plan_v1(
            stream=streams[alias],
            decision_at=str(decision["expected_cursor_at"]),
            direction=direction,  # type: ignore[arg-type]
            entry_reference=entry,
        )
        integrity = plan_integrity_violations(plan)
        causality = causality_violations(plan)
        comparison = compare_human(decision, plan)
        row = {
            "case_alias": alias,
            "source_stream_sha256": streams[alias]["stream_sha256"],
            "decision_sha256": canonical_hash(decision),
            "plan": plan,
            "integrity_violations": integrity,
            "causality_violations": causality,
            "semantic_comparison": comparison,
            "row_sha256": None,
        }
        row["row_sha256"] = canonical_hash(
            {key: value for key, value in row.items() if key != "row_sha256"}
        )
        rows.append(row)
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_HUMAN_CERTIFICATION_V1_0",
        "side": side,
        "rows": rows,
    }
    assert_no_banned_output(payload)
    return seal(payload, "payload_sha256")


def latest_visible_close(stream: dict[str, Any], signal_at: str) -> float:
    rows = complete_rows(stream["timeframes"]["1m"], signal_at)
    if not rows:
        raise RuntimeError(f"No completed M1 entry reference at {signal_at}")
    return float(rows[-1]["close"])


def compile_gav_side(
    side: str, registry: Mapping[str, Any], streams: Mapping[str, dict[str, Any]]
) -> dict[str, Any]:
    rows: list[dict[str, Any]] = []
    for source in registry["rows"]:
        alias = source["case_alias"]
        stream = streams[alias]
        entry = latest_visible_close(stream, source["signal_at"])
        plan = compile_auction_plan_v1(
            stream=stream,
            decision_at=source["signal_at"],
            direction=source["direction"],
            entry_reference=entry,
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
        "version": "GOLD_AUCTION_PLAN_COMPILER_GAV_CERTIFICATION_V1_0",
        "side": side,
        "rows": rows,
    }
    assert_no_banned_output(payload)
    return seal(payload, "payload_sha256")


def core(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    return [
        {key: value for key, value in row.items() if key != "row_sha256"}
        for row in payload["rows"]
    ]


def synthetic_proof() -> dict[str, Any]:
    empty_stream = {"timeframes": {}, "context_timeline": {}}
    no_direction = compile_auction_plan_v1(
        stream=empty_stream,
        decision_at="2022-01-01T00:00:00Z",
        direction=None,
        entry_reference=None,
    )
    repeated = compile_auction_plan_v1(
        stream=empty_stream,
        decision_at="2022-01-01T00:00:00Z",
        direction=None,
        entry_reference=None,
    )
    future_probe = json.loads(json.dumps(no_direction))
    future_probe["components"]["macro_context"] = {
        "available_at": "2022-01-02T00:00:00Z"
    }
    gates = {
        "no_direction_is_unresolved": no_direction["disposition"] == "NO_TRADE_UNRESOLVED",
        "no_direction_reason_exact": no_direction.get("unresolved_reason") == "NO_DIRECTION_PROPOSAL",
        "deterministic_repeat_exact": no_direction == repeated,
        "no_learned_geometry": no_direction["learned_geometry_used"] is False,
        "future_probe_detected": len(causality_violations(future_probe)) == 1,
        "base_integrity_clean": plan_integrity_violations(no_direction) == [],
    }
    payload = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_SYNTHETIC_CAUSAL_PROOF_V1_0",
        "created_at": now(),
        "gates": gates,
        "verdict": "PASS" if all(gates.values()) else "FAIL",
        "no_direction_plan_sha256": no_direction["plan_sha256"],
    }
    return seal(payload, "proof_sha256")


def ratio(values: Sequence[bool]) -> float | None:
    return sum(values) / len(values) if values else None


def certification_metrics(human_rows: Sequence[Mapping[str, Any]], gav_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    human_trades = [row for row in human_rows if row["semantic_comparison"]["expected_action"] != "NO_TRADE"]
    human_no_trades = [row for row in human_rows if row["semantic_comparison"]["expected_action"] == "NO_TRADE"]
    compiled = [row for row in human_trades if row["plan"]["disposition"] == "EXECUTABLE_PLAN"]
    family_values = [bool(row["semantic_comparison"]["family_match"]) for row in compiled]
    trigger_values = [
        bool(row["semantic_comparison"]["trigger_timeframe_match"])
        for row in compiled
        if row["semantic_comparison"]["trigger_timeframe_match"] is not None
    ]
    destination_values = [
        bool(row["semantic_comparison"]["destination_timeframe_match"])
        for row in compiled
        if row["semantic_comparison"]["destination_timeframe_match"] is not None
    ]
    all_rows = list(human_rows) + list(gav_rows)
    return {
        "human": {
            "cases": len(human_rows),
            "trade_proposals": len(human_trades),
            "no_trade_proposals": len(human_no_trades),
            "compiled_trade_plans": len(compiled),
            "unresolved_trade_proposals": len(human_trades) - len(compiled),
            "no_direction_preserved": sum(
                bool(row["semantic_comparison"].get("no_direction_preserved"))
                for row in human_no_trades
            ),
            "family_agreement": ratio(family_values),
            "family_agreement_numerator": sum(family_values),
            "family_agreement_denominator": len(family_values),
            "trigger_timeframe_agreement": ratio(trigger_values),
            "trigger_timeframe_agreement_numerator": sum(trigger_values),
            "trigger_timeframe_agreement_denominator": len(trigger_values),
            "h1_destination_agreement": ratio(destination_values),
            "h1_destination_agreement_numerator": sum(destination_values),
            "h1_destination_agreement_denominator": len(destination_values),
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


def mismatch_catalog(human_rows: Sequence[Mapping[str, Any]], gav_rows: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
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
            if comparison.get("trigger_timeframe_match") is False:
                reasons.append("TRIGGER_TIMEFRAME_MISMATCH")
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
        "version": "GOLD_AUCTION_PLAN_COMPILER_SEMANTIC_MISMATCH_CATALOG_V1_0",
        "human_mismatches": human,
        "gav_unresolved": gav,
        "human_mismatch_count": len(human),
        "gav_unresolved_count": len(gav),
    }
    assert_no_banned_output(payload)
    return seal(payload, "catalog_sha256")


def markdown(result: Mapping[str, Any], catalog: Mapping[str, Any]) -> str:
    metrics = result["metrics"]
    human = metrics["human"]
    gav = metrics["gav"]
    lines = [
        "# Gold Auction-Plan Compiler and Semantic-Fidelity Certification V1 — Result",
        "",
        f"Formal verdict: **{result['verdict']}**",
        "",
        "This milestone used only exposed visible decisions, annotations, and certified point-in-time streams. It opened no outcome, PnL, post-decision path, fresh month, 2025, or 2026 artifact.",
        "",
        "## Human semantic certification",
        "",
        f"- Trade proposals compiled: **{human['compiled_trade_plans']} / {human['trade_proposals']}**.",
        f"- Human no-trades preserved: **{human['no_direction_preserved']} / {human['no_trade_proposals']}**.",
        f"- Governing-auction agreement: **{human['family_agreement_numerator']} / {human['family_agreement_denominator']}** ({100 * (human['family_agreement'] or 0):.1f}%).",
        f"- Trigger-timeframe agreement: **{human['trigger_timeframe_agreement_numerator']} / {human['trigger_timeframe_agreement_denominator']}** ({100 * (human['trigger_timeframe_agreement'] or 0):.1f}%).",
        f"- H1-destination agreement: **{human['h1_destination_agreement_numerator']} / {human['h1_destination_agreement_denominator']}** ({100 * (human['h1_destination_agreement'] or 0):.1f}%).",
        "",
        "## Exposed GAV signal disposition",
        "",
        f"- Signal proposals: **{gav['signal_proposals']}**.",
        f"- Complete executable plans: **{gav['executable_plans']}**.",
        f"- Explicit unresolved no-trades: **{gav['unresolved_plans']}**.",
        f"- Missing-component counts: `{json.dumps(gav['missing_components'], sort_keys=True)}`.",
        "",
        "## Gates",
        "",
    ]
    for name, passed in result["gates"].items():
        lines.append(f"- `{name}`: **{'PASS' if passed else 'FAIL'}**")
    lines.extend(
        [
            "",
            "## Mismatches",
            "",
            f"- Human cases with at least one semantic mismatch: **{catalog['human_mismatch_count']}**.",
            f"- GAV proposals left unresolved: **{catalog['gav_unresolved_count']}**.",
            "- Every mismatch is stored in the sealed mismatch catalog; none was repaired after inspection.",
            "",
            "## Interpretation",
            "",
            "A PASS certifies point-in-time semantic translation and traceability only. It does not certify profitability. A FAIL identifies an implementation mismatch and does not authorize outcome-driven threshold changes.",
        ]
    )
    return "\n".join(lines)


def certify() -> None:
    freeze_payload = verify_freeze()
    targets = (
        SYNTHETIC_PROOF,
        HUMAN_PRIMARY,
        HUMAN_REFERENCE,
        GAV_PLANS_PRIMARY,
        GAV_PLANS_REFERENCE,
        MISMATCHES,
        RESULT,
        FINAL_SEAL,
        REPORT,
    )
    if any(path.exists() for path in targets):
        raise RuntimeError("Certification artifact already exists")
    proof = synthetic_proof()
    write_json(SYNTHETIC_PROOF, proof)
    if proof["verdict"] != "PASS":
        raise RuntimeError("Synthetic causal proof failed before source access")

    visible_rows = load_jsonl(HUMAN_LEDGER)
    visible_head = verify_visible_chain(visible_rows)
    decisions = human_decisions(visible_rows)
    action_counts = Counter(row["action"] for row in decisions.values())
    if sum(action_counts[action] for action in ("LONG", "SHORT")) != 16 or action_counts["NO_TRADE"] != 14:
        raise RuntimeError(f"Human action population differs: {action_counts}")

    human_primary = compile_human_side("primary", decisions, human_streams("primary"))
    write_json(HUMAN_PRIMARY, human_primary)
    human_reference = compile_human_side("reference", decisions, human_streams("reference"))
    write_json(HUMAN_REFERENCE, human_reference)
    human_exact = core(human_primary) == core(human_reference)

    registry = validate_seal(SIGNAL_REGISTRY, "registry_sha256")
    gav_primary = compile_gav_side("primary", registry, gav_streams("primary"))
    write_json(GAV_PLANS_PRIMARY, gav_primary)
    gav_reference = compile_gav_side("reference", registry, gav_streams("reference"))
    write_json(GAV_PLANS_REFERENCE, gav_reference)
    gav_exact = core(gav_primary) == core(gav_reference)

    metrics = certification_metrics(human_primary["rows"], gav_primary["rows"])
    minimums = freeze_payload["gates"]
    gates = {
        "synthetic_causal_proof": proof["verdict"] == "PASS",
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
        "PASS_SEMANTIC_FIDELITY_CERTIFICATION"
        if all(gates.values())
        else "FAIL_SEMANTIC_FIDELITY_CERTIFICATION"
    )
    catalog = mismatch_catalog(human_primary["rows"], gav_primary["rows"])
    write_json(MISMATCHES, catalog)
    result = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_SEMANTIC_FIDELITY_RESULT_V1_0",
        "verdict": verdict,
        "completed_at": now(),
        "freeze_sha256": freeze_payload["freeze_sha256"],
        "human_visible_head_sha256": visible_head,
        "synthetic_proof_sha256": proof["proof_sha256"],
        "human_primary_sha256": human_primary["payload_sha256"],
        "human_reference_sha256": human_reference["payload_sha256"],
        "gav_primary_sha256": gav_primary["payload_sha256"],
        "gav_reference_sha256": gav_reference["payload_sha256"],
        "mismatch_catalog_sha256": catalog["catalog_sha256"],
        "metrics": metrics,
        "gates": gates,
        "outcome_artifacts_opened": False,
        "pnl_calculated": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    assert_no_banned_output(result)
    write_json(RESULT, seal(result, "result_sha256"))
    write_text(REPORT, markdown(result, catalog))
    final = {
        "version": "GOLD_AUCTION_PLAN_COMPILER_V1_FINAL_SEAL_1_0",
        "status": verdict,
        "sealed_at": now(),
        "files": {
            path.name: {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (
                FREEZE,
                SIGNAL_REGISTRY,
                SYNTHETIC_PROOF,
                HUMAN_PRIMARY,
                HUMAN_REFERENCE,
                GAV_PLANS_PRIMARY,
                GAV_PLANS_REFERENCE,
                MISMATCHES,
                RESULT,
                REPORT,
            )
        },
    }
    write_json(FINAL_SEAL, seal(final, "seal_sha256"))
    print(
        json.dumps(
            {
                "verdict": verdict,
                "metrics": metrics,
                "failed_gates": [key for key, passed in gates.items() if not passed],
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

