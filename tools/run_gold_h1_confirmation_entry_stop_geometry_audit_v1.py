#!/usr/bin/env python3
"""Run the frozen January-May H1 confirmation entry/stop geometry audit."""

from __future__ import annotations

import csv
import gc
import gzip
import hashlib
import json
import math
import sys
from collections import Counter
from datetime import timedelta
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

import materialize_gold_blind_discretionary_replay_v1 as replay_source  # noqa: E402
import run_gold_february_h1_confirmation_only_reclaim_v1 as feb  # noqa: E402
import run_gold_mar_apr_may_h1_confirmation_only_reclaim_v1 as mar  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    canonical_json,
    iso,
    parse_dt,
)
from gold_intel.analytics.h1_confirmation_geometry_audit_v1 import (  # noqa: E402
    CONTROL_ENTRY,
    CONTROL_STOP,
    ENTRY_POLICIES,
    H1_STOP,
    M15_STOP,
    M5_STOP,
    RETEST_ENTRY,
    RULESET,
    SPLIT_CONTROL_FRACTION,
    SPLIT_ENTRY,
    SPLIT_RETEST_FRACTION,
    STOP_POLICIES,
    M1Path,
    build_structure_registry,
    evaluate_policy,
    stop_geometry,
    summarize,
    synthetic_proof,
)

SPEC = ROOT / "GOLD_H1_CONFIRMATION_ENTRY_STOP_GEOMETRY_AUDIT_V1.md"
MODULE = ROOT / "backend/src/gold_intel/analytics/h1_confirmation_geometry_audit_v1.py"
CASEBOOK = ROOT / "research_artifacts/gold_casebook_v01/price_bars.jsonl.gz"
CASEBOOK_MANIFEST = ROOT / "research_artifacts/gold_casebook_v01/manifest.json"
JAN_MANIFEST = ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2/manifest.json"
FEB_MANIFEST = ROOT / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1/manifest.json"
MAM_ROOT_MANIFEST = ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/manifest.json"

OUT = ROOT / "research_artifacts/gold_h1_confirmation_entry_stop_geometry_audit_v1"
PROTOCOL = OUT / "protocol_freeze.json"
SYNTHETIC = OUT / "synthetic_proof.json"
CONTEXTS = OUT / "case_contexts.json"
LEDGER = OUT / "case_geometry_ledger.csv"
SUMMARY_CSV = OUT / "policy_summary.csv"
RESULT = OUT / "result.json"
REPORT = OUT / "report.md"
MANIFEST = OUT / "manifest.json"

HISTORY_START = parse_dt("2021-07-23T00:00:00Z")
JAN_START = parse_dt("2022-01-01T00:00:00Z")
JUN_START = parse_dt("2022-06-01T00:00:00Z")
FINAL_CUTOFF = parse_dt("2022-06-03T00:00:00Z")
REQUIRED_TIMEFRAMES = ("1m", "5m", "15m", "1h")

MONTHS = (
    {
        "key": "january_2022",
        "label": "January 2022",
        "start": parse_dt("2022-01-01T00:00:00Z"),
        "end": parse_dt("2022-02-01T00:00:00Z"),
        "cutoff": parse_dt("2022-02-01T00:00:00Z"),
        "expected_executed": 65,
        "result": ROOT / "research_artifacts/gold_january_h1_confirmation_only_reclaim_v2/result.json",
        "manifest": JAN_MANIFEST,
    },
    {
        "key": "february_2022",
        "label": "February 2022",
        "start": parse_dt("2022-02-01T00:00:00Z"),
        "end": parse_dt("2022-03-01T00:00:00Z"),
        "cutoff": parse_dt("2022-03-03T00:00:00Z"),
        "expected_executed": 61,
        "result": ROOT / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1/result.json",
        "manifest": FEB_MANIFEST,
    },
    {
        "key": "march_2022",
        "label": "March 2022",
        "start": parse_dt("2022-03-01T00:00:00Z"),
        "end": parse_dt("2022-04-01T00:00:00Z"),
        "cutoff": parse_dt("2022-04-03T00:00:00Z"),
        "expected_executed": 79,
        "result": ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/march_2022/result.json",
        "manifest": ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/march_2022/manifest.json",
    },
    {
        "key": "april_2022",
        "label": "April 2022",
        "start": parse_dt("2022-04-01T00:00:00Z"),
        "end": parse_dt("2022-05-01T00:00:00Z"),
        "cutoff": parse_dt("2022-05-03T00:00:00Z"),
        "expected_executed": 60,
        "result": ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/april_2022/result.json",
        "manifest": ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/april_2022/manifest.json",
    },
    {
        "key": "may_2022",
        "label": "May 2022",
        "start": parse_dt("2022-05-01T00:00:00Z"),
        "end": JUN_START,
        "cutoff": FINAL_CUTOFF,
        "expected_executed": 61,
        "result": ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/may_2022/result.json",
        "manifest": ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1/may_2022/manifest.json",
    },
)


def write_json(path: Path, payload: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    temporary.replace(path)


def verify_manifest_files(manifest_path: Path) -> dict[str, Any]:
    require(manifest_path.is_file(), f"Missing predecessor manifest: {manifest_path}")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    failures: list[str] = []
    for row in manifest.get("files", []):
        path = ROOT / str(row["path"])
        if not path.is_file() or sha256_file(path) != str(row["sha256"]):
            failures.append(str(row["path"]))
    require(not failures, f"Predecessor manifest failures in {manifest_path}: {failures}")
    return {
        "path": manifest_path.relative_to(ROOT).as_posix(),
        "sha256": sha256_file(manifest_path),
        "verdict": manifest.get("verdict"),
        "bound_files": len(manifest.get("files", [])),
    }


def verify_predecessors() -> dict[str, Any]:
    for path in (SPEC, MODULE, CASEBOOK, CASEBOOK_MANIFEST, JAN_MANIFEST, FEB_MANIFEST, MAM_ROOT_MANIFEST):
        require(path.is_file(), f"Required predecessor absent: {path}")
    casebook_manifest = json.loads(CASEBOOK_MANIFEST.read_text(encoding="utf-8"))
    source_rows = [row for row in casebook_manifest["artifacts"] if row["name"] == CASEBOOK.name]
    require(len(source_rows) == 1, "Casebook price source binding is absent or ambiguous")
    casebook_sha = sha256_file(CASEBOOK)
    require(casebook_sha == str(source_rows[0]["sha256"]), "Casebook price source seal mismatch")

    manifests = [JAN_MANIFEST, FEB_MANIFEST, MAM_ROOT_MANIFEST]
    manifests.extend(month["manifest"] for month in MONTHS[2:])
    checks = [verify_manifest_files(path) for path in manifests]
    return {
        "casebook": {
            "path": CASEBOOK.relative_to(ROOT).as_posix(),
            "sha256": casebook_sha,
            "bytes": CASEBOOK.stat().st_size,
            "manifest_path": CASEBOOK_MANIFEST.relative_to(ROOT).as_posix(),
            "manifest_sha256": sha256_file(CASEBOOK_MANIFEST),
        },
        "predecessor_manifests": checks,
    }


def load_sealed_results() -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]]]:
    results: dict[str, dict[str, Any]] = {}
    fixed: list[dict[str, Any]] = []
    seen: set[str] = set()
    for month in MONTHS:
        result = json.loads(month["result"].read_text(encoding="utf-8"))
        rows = list(result["case_ledger"])
        executed = [row for row in rows if bool(row["executed"])]
        require(
            len(executed) == int(month["expected_executed"]),
            f"{month['label']} sealed executed count differs: {len(executed)}",
        )
        for row in executed:
            identity = str(row["trade_identity"])
            require(identity not in seen, f"Duplicate fixed trade identity: {identity}")
            seen.add(identity)
            fixed.append(
                {
                    "month": str(month["key"]),
                    "trade_identity": identity,
                    "direction": str(row["direction"]),
                    "route": str(row["route"]),
                    "entry_at": str(row["entry_at"]),
                    "stop": float(row.get("filled_stop", row.get("stop"))),
                    "target": None if row.get("target") is None else float(row["target"]),
                    "outcome": str(row["outcome"]),
                    "resolution_at": str(row["resolution_at"]),
                    "net_r": float(row["net_r"]),
                }
            )
        results[str(month["key"])] = result
    require(len(fixed) == 326, f"Frozen audit population must be 326, got {len(fixed)}")
    fixed.sort(key=lambda row: (row["entry_at"], row["trade_identity"]))
    return results, fixed


def freeze_protocol(bindings: Mapping[str, Any], fixed: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    payload = {
        "version": f"{RULESET}_PROTOCOL_FREEZE",
        "evidence_status": "EXPOSED_MATCHED_CASE_DIAGNOSTIC_ZERO_VALIDATION_CREDIT",
        "period": {"start": iso(JAN_START), "end_exclusive": iso(JUN_START)},
        "fixed_population": {
            "count": len(fixed),
            "monthly_counts": dict(sorted(Counter(str(row["month"]) for row in fixed).items())),
            "identities_sha256": canonical_hash([str(row["trade_identity"]) for row in fixed]),
            "complete_rows_sha256": canonical_hash(list(fixed)),
        },
        "entry_policies": list(ENTRY_POLICIES),
        "stop_policies": list(STOP_POLICIES),
        "matrix_rows_expected": len(fixed) * len(ENTRY_POLICIES) * len(STOP_POLICIES),
        "rules": {
            "retest_expiry_minutes": 15,
            "split_control_fraction": SPLIT_CONTROL_FRACTION,
            "split_retest_fraction": SPLIT_RETEST_FRACTION,
            "stop_buffer": "max(0.05 * point-in-time source-timeframe ATR14, 0.02)",
            "target": "unchanged original absolute target",
            "deadline": "original calendar-month end",
            "ambiguity": "stop first; limit plus target without stop cancels as unresolved",
            "population_policy": "all original executed trades retained, including alternative no-fills",
            "accounting": "gross before costs; $50 maximum case risk illustration",
        },
        "prohibitions": [
            "no fresh dates",
            "no outcome-derived stop distance",
            "no dropped losers or winners",
            "no economic edge or validation claim",
            "no visualization unless a later fidelity dispute requires it",
        ],
        "source_bindings": bindings,
        "implementation_bindings": {
            "spec_sha256": sha256_file(SPEC),
            "module_sha256": sha256_file(MODULE),
            "runner_sha256": sha256_file(Path(__file__).resolve()),
        },
    }
    payload["protocol_sha256"] = canonical_hash(payload)
    write_json(PROTOCOL, payload)
    return payload


def load_casebook(
    parser: Callable[[str], dict[str, Any]],
) -> tuple[dict[str, list[dict[str, Any]]], dict[str, Any]]:
    rows: dict[str, list[dict[str, Any]]] = {timeframe: [] for timeframe in REQUIRED_TIMEFRAMES}
    with gzip.open(CASEBOOK, "rt", encoding="utf-8") as handle:
        for line in handle:
            parsed = parser(line)
            timeframe = str(parsed["timeframe"])
            if timeframe not in rows or not bool(parsed["complete"]):
                continue
            opened = parse_dt(str(parsed["open_time"]))
            available = parse_dt(str(parsed["available_at"]))
            if timeframe == "1m":
                include = opened >= JAN_START and available <= JUN_START
            else:
                include = opened >= HISTORY_START and available <= FINAL_CUTOFF
            if include:
                rows[timeframe].append(feb.canonical_bar(parsed))

    diagnostics: dict[str, Any] = {}
    for timeframe, values in rows.items():
        values.sort(key=lambda row: (parse_dt(str(row["open_at"])), parse_dt(str(row["available_at"]))))
        require(values, f"No selected source rows for {timeframe}")
        identities = [(str(row["open_at"]), str(row["available_at"])) for row in values]
        require(len(identities) == len(set(identities)), f"Duplicate selected {timeframe} bars")
        digest = hashlib.sha256()
        for row in values:
            digest.update(canonical_json(row).encode("utf-8"))
            digest.update(b"\n")
        diagnostics[timeframe] = {
            "rows": len(values),
            "first_open_at": str(values[0]["open_at"]),
            "last_available_at": str(values[-1]["available_at"]),
            "stream_sha256": digest.hexdigest(),
        }
    return rows, diagnostics


def reconstruct_executed_context(
    trade: Mapping[str, Any],
    sealed_row: Mapping[str, Any],
    rows: Mapping[str, Sequence[Mapping[str, Any]]],
    m5_swings: Sequence[Mapping[str, Any]],
    *,
    month: Mapping[str, Any],
) -> dict[str, Any]:
    direction = str(trade["direction"])
    decision = parse_dt(str(trade["decision_at"]))
    boundary_at = parse_dt(str(trade["resolution_at"]))
    source_h1_level = float(trade["stop"])
    target = float(trade["target"])
    route = str(sealed_row["route"])
    initial_control = feb.latest_control(m5_swings, decision, direction)
    initial_confirmation = (
        feb.first_confirmation(
            rows["5m"],
            after=decision,
            through=boundary_at,
            direction=direction,
            control_level=float(initial_control["level"]),
        )
        if initial_control is not None
        else None
    )

    selected_control = initial_control
    selected_confirmation = initial_confirmation
    if route.startswith("RECLAIM_CONFIRMATION_"):
        later_target_at = feb.first_target_after(
            rows["1m"],
            after=boundary_at,
            direction=direction,
            target=target,
            end=month["end"],
        )
        h1_review = feb.first_h1_after(rows["1h"], boundary_at, end=month["end"])
        require(h1_review is not None, f"Missing H1 review for executed reclaim {trade['trade_identity']}")
        review_time = parse_dt(str(h1_review["available_at"]))
        selected_control = feb.latest_control(m5_swings, review_time, direction)
        require(selected_control is not None, f"Missing M5 control for executed reclaim {trade['trade_identity']}")
        next_breach_at = feb.first_h1_breach_after(
            rows["1h"],
            after=review_time,
            swing=source_h1_level,
            direction=direction,
            end=month["end"],
        )
        cancellation_points = [month["end"]]
        if later_target_at is not None:
            cancellation_points.append(later_target_at)
        if next_breach_at is not None:
            cancellation_points.append(next_breach_at)
        recovery_deadline = min(cancellation_points)
        selected_confirmation = feb.first_confirmation(
            rows["5m"],
            after=review_time,
            through=recovery_deadline,
            direction=direction,
            control_level=float(selected_control["level"]),
            required_valid_side=source_h1_level,
        )
        require(selected_confirmation is not None, f"Missing executed reclaim confirmation {trade['trade_identity']}")
        require(
            feb.confirmation_precedes_h1_breach(
                parse_dt(str(selected_confirmation["available_at"])), next_breach_at
            ),
            f"Reclaim confirmation follows H1 breach {trade['trade_identity']}",
        )
    else:
        require(route.startswith("INITIAL_CONFIRMATION_"), f"Unexpected executed route: {route}")

    require(selected_control is not None, f"Missing selected M5 control {trade['trade_identity']}")
    require(selected_confirmation is not None, f"Missing selected confirmation {trade['trade_identity']}")
    confirmation_at = parse_dt(str(selected_confirmation["available_at"]))
    entry_row = feb.first_m1_at_or_after(rows["1m"], confirmation_at, end=month["end"])
    require(entry_row is not None, f"Missing exact M1 entry row {trade['trade_identity']}")
    require(str(entry_row["open_at"]) == str(sealed_row["entry_at"]), f"Entry timestamp mismatch {trade['trade_identity']}")
    entry_price = float(entry_row["open"])
    if sealed_row.get("entry_price") is not None:
        require(entry_price == float(sealed_row["entry_price"]), f"Entry price mismatch {trade['trade_identity']}")
    require(
        float(sealed_row["stop"]) == float(sealed_row.get("filled_stop", sealed_row["stop"])),
        f"Internal stop mapping mismatch {trade['trade_identity']}",
    )

    return {
        "month": str(month["key"]),
        "month_label": str(month["label"]),
        "trade_identity": str(trade["trade_identity"]),
        "source_h1_swing_identity": str(trade["source_swing_identity"]),
        "source_h1_detected_at": str(trade["decision_at"]),
        "source_h1_level": source_h1_level,
        "target_h1_swing_identity": str(trade["target_swing_identity"]),
        "pivot_at": str(trade["pivot_at"]),
        "decision_at": str(trade["decision_at"]),
        "direction": direction,
        "route": route,
        "control_entry_at": str(sealed_row["entry_at"]),
        "control_entry_price": entry_price,
        "control_stop": float(sealed_row.get("filled_stop", sealed_row["stop"])),
        "target": target,
        "deadline": iso(month["end"]),
        "broken_m5_control_identity": str(selected_control["identity"]),
        "broken_m5_control_level": float(selected_control["level"]),
        "broken_m5_control_known_at": str(selected_control["detected_at"]),
        "confirmation_bar_identity": canonical_hash(selected_confirmation),
        "confirmation_bar_open_at": str(selected_confirmation["open_at"]),
        "confirmation_at": str(selected_confirmation["available_at"]),
        "original_outcome": str(sealed_row["outcome"]),
        "original_resolution_at": str(sealed_row["resolution_at"]),
        "original_net_r": float(sealed_row["net_r"]),
        "context_sha256": "",
    }


def flatten_policy_row(
    case: Mapping[str, Any], geometry: Mapping[str, Any], result: Mapping[str, Any]
) -> dict[str, Any]:
    row = {
        "month": str(case["month"]),
        "trade_identity": str(case["trade_identity"]),
        "direction": str(case["direction"]),
        "route": str(case["route"]),
        "decision_at": str(case["decision_at"]),
        "control_entry_at": str(case["control_entry_at"]),
        "control_entry_price": float(case["control_entry_price"]),
        "control_stop": float(case["control_stop"]),
        "target": float(case["target"]),
        "deadline": str(case["deadline"]),
        "source_h1_swing_identity": str(case["source_h1_swing_identity"]),
        "broken_m5_control_identity": str(case["broken_m5_control_identity"]),
        "broken_m5_control_level": float(case["broken_m5_control_level"]),
        "confirmation_bar_identity": str(case["confirmation_bar_identity"]),
        "confirmation_at": str(case["confirmation_at"]),
        "entry_policy": str(result["entry_policy"]),
        "stop_policy": str(result["stop_policy"]),
        "effective_stop_policy": str(result["effective_stop_policy"]),
        "stop_replaced_control": bool(geometry["replaced_control"]),
        "stop_fallback_reason": geometry["fallback_reason"] or "",
        "stop_source_identity": geometry["source_identity"] or "",
        "stop_source_known_at": geometry["source_known_at"] or "",
        "stop_source_level": geometry["source_level"],
        "stop_atr14": geometry["atr14"],
        "stop_buffer": geometry["buffer"],
        "stop": float(result["stop"]),
        "distance_ratio_to_control": float(geometry["distance_ratio_to_control"]),
        "filled": bool(result["filled"]),
        "entry_at": result["entry_at"],
        "entry_price": result["entry_price"],
        "outcome": str(result["outcome"]),
        "resolution_at": result["resolution_at"],
        "net_r": float(result["net_r"]),
        "dollars_at_50_max_case_risk": 50.0 * float(result["net_r"]),
        "mfe_r": result["mfe_r"],
        "mae_r": result["mae_r"],
        "retest_level": float(result["retest_level"]),
        "retest_opportunity": bool(result["retest_opportunity"]),
        "retest_used": bool(result["retest_used"]),
        "retest_fill_at": result["retest_fill_at"],
        "retest_disposition": str(result["retest_disposition"]),
        "retest_expiry_at": str(result["retest_expiry_at"]),
        "original_outcome": str(case["original_outcome"]),
        "original_resolution_at": str(case["original_resolution_at"]),
        "original_net_r": float(case["original_net_r"]),
        "delta_vs_original_r": float(result["net_r"]) - float(case["original_net_r"]),
        "geometry_sha256": str(geometry["geometry_sha256"]),
        "policy_result_sha256": str(result["policy_result_sha256"]),
    }
    row["row_sha256"] = canonical_hash(row)
    return row


def control_equivalence(
    rows: Sequence[Mapping[str, Any]], originals: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    control = [
        row
        for row in rows
        if row["entry_policy"] == CONTROL_ENTRY and row["stop_policy"] == CONTROL_STOP
    ]
    require(len(control) == len(originals), "Control matrix cardinality differs")
    failures: list[dict[str, Any]] = []
    for row in control:
        original = originals[str(row["trade_identity"])]
        checks = {
            "entry_at": row["entry_at"] == original["entry_at"],
            "stop": float(row["stop"]) == float(original["stop"]),
            "target": float(row["target"]) == float(original["target"]),
            "outcome": row["outcome"] == original["outcome"],
            "resolution_at": row["resolution_at"] == original["resolution_at"],
            "net_r": float(row["net_r"]) == float(original["net_r"]),
        }
        if not all(checks.values()):
            failures.append({"trade_identity": row["trade_identity"], "checks": checks})
    require(not failures, f"Exact control reproduction failed for {len(failures)} trades")
    return {"rows": len(control), "mismatches": 0, "exact": True}


def summarize_matrix(
    ledger: Sequence[Mapping[str, Any]], originals: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    monthly: dict[str, Any] = {}
    for month in MONTHS:
        monthly[str(month["key"])] = {}
        for entry_policy in ENTRY_POLICIES:
            monthly[str(month["key"])][entry_policy] = {}
            for stop_policy in STOP_POLICIES:
                selected = [
                    row
                    for row in ledger
                    if row["month"] == month["key"]
                    and row["entry_policy"] == entry_policy
                    and row["stop_policy"] == stop_policy
                ]
                monthly[str(month["key"])][entry_policy][stop_policy] = summarize(selected, originals)

    combined: dict[str, Any] = {}
    for entry_policy in ENTRY_POLICIES:
        combined[entry_policy] = {}
        for stop_policy in STOP_POLICIES:
            selected = [
                row
                for row in ledger
                if row["entry_policy"] == entry_policy and row["stop_policy"] == stop_policy
            ]
            combined[entry_policy][stop_policy] = summarize(selected, originals)

    for scope in (*monthly.values(), combined):
        control_r = float(scope[CONTROL_ENTRY][CONTROL_STOP]["net_r"])
        for entry_policy in ENTRY_POLICIES:
            for stop_policy in STOP_POLICIES:
                scope[entry_policy][stop_policy]["delta_vs_control_r"] = (
                    float(scope[entry_policy][stop_policy]["net_r"]) - control_r
                )
    return {"monthly": monthly, "combined": combined}


def run_side(
    parser: Callable[[str], dict[str, Any]], sealed_results: Mapping[str, Mapping[str, Any]]
) -> dict[str, Any]:
    rows, source_diagnostics = load_casebook(parser)
    registry = build_structure_registry(rows, cutoff=FINAL_CUTOFF)
    m5_swings = list(registry["5m"]["swings"])
    m1_path = M1Path(rows["1m"])
    contexts: list[dict[str, Any]] = []
    predecessor_equivalence: dict[str, Any] = {}
    originals: dict[str, dict[str, Any]] = {}

    for month in MONTHS:
        key = str(month["key"])
        population = feb.build_population(
            rows, start=month["start"], end=month["end"], cutoff=month["cutoff"]
        )
        generated = mar.apply_policy(population["trades"], rows, end=month["end"])
        predecessor_equivalence[key] = mar.compare_sealed(
            population, generated, sealed_results[key], label=key.upper()
        )
        trades_by_id = {str(row["trade_identity"]): row for row in population["trades"]}
        generated_executed = [row for row in generated if bool(row["executed"])]
        require(
            len(generated_executed) == int(month["expected_executed"]),
            f"Generated executed count differs for {month['label']}",
        )
        for sealed_row in generated_executed:
            identity = str(sealed_row["trade_identity"])
            require(identity in trades_by_id, f"Generated trade absent from population: {identity}")
            context = reconstruct_executed_context(
                trades_by_id[identity], sealed_row, rows, m5_swings, month=month
            )
            context["context_sha256"] = canonical_hash(
                {key_: value for key_, value in context.items() if key_ != "context_sha256"}
            )
            contexts.append(context)
            originals[identity] = {
                "entry_at": str(sealed_row["entry_at"]),
                "stop": float(sealed_row["stop"]),
                "target": float(sealed_row["target"]),
                "outcome": str(sealed_row["outcome"]),
                "resolution_at": str(sealed_row["resolution_at"]),
                "net_r": float(sealed_row["net_r"]),
            }

    require(len(contexts) == 326, f"Reconstructed context count differs: {len(contexts)}")
    contexts.sort(key=lambda row: (row["control_entry_at"], row["trade_identity"]))
    ledger: list[dict[str, Any]] = []
    for case in contexts:
        for entry_policy in ENTRY_POLICIES:
            for stop_policy in STOP_POLICIES:
                geometry = stop_geometry(case, registry, stop_policy)
                result = evaluate_policy(case, geometry, m1_path, entry_policy)
                ledger.append(flatten_policy_row(case, geometry, result))
    require(len(ledger) == 3_912, f"Matrix cardinality differs: {len(ledger)}")
    ledger.sort(
        key=lambda row: (
            row["control_entry_at"],
            row["trade_identity"],
            ENTRY_POLICIES.index(str(row["entry_policy"])),
            STOP_POLICIES.index(str(row["stop_policy"])),
        )
    )
    control = control_equivalence(ledger, originals)
    summaries = summarize_matrix(ledger, originals)
    payload = {
        "source_diagnostics": source_diagnostics,
        "structure_registry_sha256": registry["registry_sha256"],
        "predecessor_equivalence": predecessor_equivalence,
        "control_equivalence": control,
        "contexts": contexts,
        "ledger": ledger,
        "summaries": summaries,
    }
    payload["contexts_sha256"] = canonical_hash(contexts)
    payload["ledger_sha256"] = canonical_hash(ledger)
    payload["summaries_sha256"] = canonical_hash(summaries)
    return payload


def write_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    require(bool(rows), f"Cannot write empty CSV: {path}")
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)
    temporary.replace(path)


def summary_rows(summaries: Mapping[str, Any]) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    scopes = [(str(month["key"]), summaries["monthly"][str(month["key"])]) for month in MONTHS]
    scopes.append(("combined_january_to_may_2022", summaries["combined"]))
    for scope_name, scope in scopes:
        for entry_policy in ENTRY_POLICIES:
            for stop_policy in STOP_POLICIES:
                metrics = dict(scope[entry_policy][stop_policy])
                output.append(
                    {
                        "scope": scope_name,
                        "entry_policy": entry_policy,
                        "stop_policy": stop_policy,
                        **{key: value for key, value in metrics.items() if key != "outcome_counts"},
                        "outcome_counts_json": canonical_json(metrics["outcome_counts"]),
                    }
                )
    return output


def policy_label(value: str) -> str:
    labels = {
        CONTROL_ENTRY: "control entry",
        RETEST_ENTRY: "M5 retest only",
        SPLIT_ENTRY: "25/75 split",
        CONTROL_STOP: "control stop",
        M5_STOP: "latest M5 swing",
        M15_STOP: "latest M15 swing",
        H1_STOP: "buffered source H1",
    }
    return labels[value]


def render_scope_table(scope: Mapping[str, Any]) -> list[str]:
    lines = [
        "| Entry | Stop | Filled | Win rate | Net R | Delta vs control | PF | Max DD | $ at $50/case | Winner kept/lost/unfilled |",
        "|---|---|---:|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for entry_policy in ENTRY_POLICIES:
        for stop_policy in STOP_POLICIES:
            row = scope[entry_policy][stop_policy]
            pf = "n/a" if row["profit_factor"] is None else f"{float(row['profit_factor']):.3f}"
            win_rate = "n/a" if row["win_rate_filled"] is None else f"{100*float(row['win_rate_filled']):.1f}%"
            retention = (
                f"{row['original_positive_retained']}/"
                f"{row['original_positive_converted_to_loss']}/"
                f"{row['original_positive_unfilled']}"
            )
            lines.append(
                f"| {policy_label(entry_policy)} | {policy_label(stop_policy)} | "
                f"{row['filled_cases']}/{row['population']} | {win_rate} | {float(row['net_r']):+.3f} | "
                f"{float(row['delta_vs_control_r']):+.3f} | {pf} | {float(row['maximum_drawdown_r']):.3f} | "
                f"${float(row['dollars_at_50_max_case_risk']):+,.2f} | {retention} |"
            )
    return lines


def render_reports(result: Mapping[str, Any]) -> list[Path]:
    generated: list[Path] = []
    monthly_dir = OUT / "monthly"
    monthly_dir.mkdir(parents=True, exist_ok=True)
    for month in MONTHS:
        key = str(month["key"])
        path = monthly_dir / f"{key}.md"
        scope = result["summaries"]["monthly"][key]
        lines = [
            f"# {month['label']} H1 confirmation entry and stop geometry audit",
            "",
            "Exposed matched-case diagnostic only; gross before costs and overlap controls. No trade was removed from the fixed original population.",
            "",
            *render_scope_table(scope),
            "",
            "Winner kept/lost/unfilled compares each policy with the original positive-R cases. A tighter stop increases target R only when it survives first passage; every stop remains -1R under fixed-risk normalization.",
        ]
        path.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
        generated.append(path)

    combined = result["summaries"]["combined"]
    ranked = sorted(
        (
            (float(combined[entry][stop]["net_r"]), entry, stop)
            for entry in ENTRY_POLICIES
            for stop in STOP_POLICIES
        ),
        reverse=True,
    )
    best_r, best_entry, best_stop = ranked[0]
    control = combined[CONTROL_ENTRY][CONTROL_STOP]
    stop_lines = []
    for stop in STOP_POLICIES:
        row = combined[CONTROL_ENTRY][stop]
        stop_lines.append(
            f"- `{stop}`: replaced {row['stop_replacements']}; fallbacks {row['stop_fallbacks']}; "
            f"kept {row['original_positive_retained']} original winners; converted "
            f"{row['original_positive_converted_to_loss']} original winners to losses; net {float(row['net_r']):+.3f}R."
        )
    lines = [
        "# Gold H1 Confirmation Entry and Structural-Stop Geometry Audit V1",
        "",
        f"**Verdict:** `{result['verdict']}`",
        "",
        "This completed the frozen 3 x 4 matched-case audit over all 326 original executed trades from January-May 2022. It is exposed diagnostic evidence, not a validated edge.",
        "",
        "## Combined matrix",
        "",
        *render_scope_table(combined),
        "",
        "## Structural-stop survival",
        "",
        *stop_lines,
        "",
        "## Exposure-ranked result",
        "",
        f"The largest in-sample/exposed matrix result was `{best_entry}` with `{best_stop}` at {best_r:+.3f}R, "
        f"versus the exact control at {float(control['net_r']):+.3f}R. This ranking receives no candidate or validation credit.",
        "",
        "A smaller stop is not automatically safer. At fixed risk a stop-out still loses 1R; the only economic benefit comes when a closer point-in-time structural stop survives and enlarges the unchanged target multiple. Converted original winners quantify where the control width genuinely protected the trade.",
        "",
        "Separate monthly reports contain all twelve policy cells.",
    ]
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")
    generated.append(REPORT)
    return generated


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    bindings = verify_predecessors()
    sealed_results, fixed = load_sealed_results()
    protocol = freeze_protocol(bindings, fixed)
    proof = synthetic_proof()
    require(proof["verdict"] == "PASS", "Synthetic geometry proof failed")
    write_json(SYNTHETIC, proof)
    print("CHECKPOINT 1/4 PASS: seals, 326-case freeze and synthetic proof")

    primary = run_side(replay_source.parse_price_primary, sealed_results)
    require(
        [row["trade_identity"] for row in primary["contexts"]]
        == [row["trade_identity"] for row in fixed],
        "Primary context identities differ from frozen order",
    )
    print("CHECKPOINT 2/4 PASS: primary 3x4 matrix and exact 326-control reproduction")
    gc.collect()

    reference = run_side(replay_source.parse_price_reference, sealed_results)
    equality_fields = (
        "source_diagnostics",
        "structure_registry_sha256",
        "predecessor_equivalence",
        "control_equivalence",
        "contexts_sha256",
        "ledger_sha256",
        "summaries_sha256",
    )
    require(
        all(primary[field] == reference[field] for field in equality_fields),
        "Primary/reference audit digests or diagnostics differ",
    )
    require(primary["contexts"] == reference["contexts"], "Primary/reference contexts differ")
    require(primary["ledger"] == reference["ledger"], "Primary/reference matrix rows differ")
    require(primary["summaries"] == reference["summaries"], "Primary/reference summaries differ")
    print("CHECKPOINT 3/4 PASS: independent reference reproduction is exact")

    contexts_payload = {
        "version": f"{RULESET}_CASE_CONTEXTS",
        "count": len(primary["contexts"]),
        "contexts_sha256": primary["contexts_sha256"],
        "rows": primary["contexts"],
    }
    write_json(CONTEXTS, contexts_payload)
    write_csv(LEDGER, primary["ledger"])
    summaries_flat = summary_rows(primary["summaries"])
    write_csv(SUMMARY_CSV, summaries_flat)

    result = {
        "version": RULESET,
        "verdict": "PASS_EXPOSED_MATCHED_CASE_GEOMETRY_AUDIT_REPRODUCTION",
        "evidence_status": "EXPOSED_DIAGNOSTIC_HYPOTHESIS_GENERATION_ONLY",
        "period": protocol["period"],
        "population": protocol["fixed_population"],
        "matrix_rows": len(primary["ledger"]),
        "entry_policies": list(ENTRY_POLICIES),
        "stop_policies": list(STOP_POLICIES),
        "predecessor_equivalence": primary["predecessor_equivalence"],
        "control_equivalence": primary["control_equivalence"],
        "source_diagnostics": primary["source_diagnostics"],
        "structure_registry_sha256": primary["structure_registry_sha256"],
        "contexts_sha256": primary["contexts_sha256"],
        "ledger_sha256": primary["ledger_sha256"],
        "summaries_sha256": primary["summaries_sha256"],
        "summaries": primary["summaries"],
        "primary_reference_exact": True,
        "costs_included": False,
        "overlap_policy_applied": False,
        "validation_credit": False,
        "fresh_data_opened": False,
        "visualization_generated": False,
    }
    result["result_sha256"] = canonical_hash(result)
    write_json(RESULT, result)
    report_paths = render_reports(result)

    sealed_paths = [
        SPEC,
        MODULE,
        Path(__file__).resolve(),
        PROTOCOL,
        SYNTHETIC,
        CONTEXTS,
        LEDGER,
        SUMMARY_CSV,
        RESULT,
        *report_paths,
    ]
    manifest = {
        "version": f"{RULESET}_MANIFEST",
        "verdict": result["verdict"],
        "result_sha256": result["result_sha256"],
        "protocol_sha256": protocol["protocol_sha256"],
        "synthetic_proof_sha256": proof["proof_sha256"],
        "primary_reference_exact": True,
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in sealed_paths
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    write_json(MANIFEST, manifest)
    print("CHECKPOINT 4/4 PASS: reports and cryptographic manifest sealed")
    combined = result["summaries"]["combined"]
    print(
        json.dumps(
            {
                "verdict": result["verdict"],
                "control_net_r": combined[CONTROL_ENTRY][CONTROL_STOP]["net_r"],
                "monthly_control_net_r": {
                    month["key"]: result["summaries"]["monthly"][month["key"]][CONTROL_ENTRY][CONTROL_STOP]["net_r"]
                    for month in MONTHS
                },
                "result": RESULT.relative_to(ROOT).as_posix(),
                "report": REPORT.relative_to(ROOT).as_posix(),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
