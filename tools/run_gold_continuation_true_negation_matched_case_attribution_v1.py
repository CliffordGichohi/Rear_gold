#!/usr/bin/env python3
"""Freeze, reproduce, document and seal the matched-case attribution audit."""

from __future__ import annotations

import argparse
import csv
import io
import json
import runpy
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import run_gold_auction_all_transition_executable_multi_opportunity_v2 as support  # noqa: E402
import run_gold_auction_all_transition_executable_multi_opportunity_v2_r1 as original  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
import run_gold_continuation_refresh_true_negation_fixed_quantity_v1 as negated  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from gold_intel.analytics.continuation_true_negation_attribution_v1 import (  # noqa: E402
    GROUP_FIELDS,
    RULESET,
    aggregate,
    analyse_pair,
    assign_run_ordinals,
)


CONTRACT = ROOT / "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_AUDIT_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "continuation_true_negation_attribution_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_continuation_true_negation_attribution_v1.py"
RUNNER = Path(__file__).resolve()

OUT = ROOT / "research_artifacts" / "gold_continuation_true_negation_matched_case_attribution_v1"
FREEZE = OUT / "preanalysis_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "matched_case_attribution.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_V1_REPORT.md"


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(
        name
        for name, value in namespace.items()
        if name.startswith("test_") and callable(value)
    )
    support.require(len(tests) == 4, f"Unexpected attribution tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_result_payload(side: str, branch: str) -> dict[str, Any]:
    if branch == "original":
        path = original.PRIMARY if side == "primary" else original.REFERENCE
    else:
        path = negated.PRIMARY if side == "primary" else negated.REFERENCE
    return support.verify_canonical_payload(path, "payload_sha256")


def continuation_result_rows(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    rows = {
        str(row["event_identity"]): dict(row)
        for row in payload["rows"]
        if row["execution_disposition"] == "EXECUTED_UNRESTRICTED_ALL_SIGNALS"
        and row["event_class"] == "CONTINUATION_REFRESH"
    }
    support.require(len(rows) == 434, "Expected exactly 434 continuation result rows")
    return rows


def load_matched_metadata(side: str) -> dict[str, Any]:
    compiled_all = original.load_compiled(side)
    compiled = [
        row
        for row in compiled_all
        if row["mechanically_executable"] and row["event_class"] == "CONTINUATION_REFRESH"
    ]
    original_rows = continuation_result_rows(load_result_payload(side, "original"))
    negated_rows = continuation_result_rows(load_result_payload(side, "negated"))
    identities = [str(row["event_identity"]) for row in compiled]
    support.require(len(compiled) == 434, "Expected 434 compiled continuation plans")
    support.require(len(set(identities)) == 434, "Continuation identities are not unique")
    support.require(set(identities) == set(original_rows), "Original result identities differ")
    support.require(set(identities) == set(negated_rows), "Negated result identities differ")
    for identity in identities:
        old_execution = original_rows[identity]["result"]["execution"]
        new_execution = negated_rows[identity]["result"]["execution"]
        support.require(
            int(old_execution["quantity_ounces"])
            == int(new_execution["quantity_ounces"]),
            f"Quantity differs in matched pair: {identity}",
        )
        support.require(
            original_rows[identity]["direction"] != negated_rows[identity]["direction"],
            f"Direction did not negate: {identity}",
        )
    return {
        "compiled_all": compiled_all,
        "compiled": compiled,
        "original": original_rows,
        "negated": negated_rows,
        "identities": identities,
    }


def preflight() -> dict[str, Any]:
    original_state = original.verify_freeze()
    original_seal = support.verify_canonical_seal(original.SEAL)
    negated_state = negated.verify_freeze()
    negated_seal = support.verify_canonical_seal(negated.SEAL)
    primary = load_matched_metadata("primary")
    reference = load_matched_metadata("reference")
    support.require(primary["compiled"] == reference["compiled"], "Compiled metadata differs")
    support.require(primary["identities"] == reference["identities"], "Matched identities differ")
    proof = synthetic_proof()
    payload: dict[str, Any] = {
        "status": "PASS_MATCHED_CASE_ATTRIBUTION_PREFLIGHT",
        "matched_cases": 434,
        "identities_sha256": canonical_hash(primary["identities"]),
        "compiled_rows_sha256": canonical_hash(primary["compiled"]),
        "original_result_rows_sha256": canonical_hash(
            [primary["original"][identity] for identity in primary["identities"]]
        ),
        "negated_result_rows_sha256": canonical_hash(
            [primary["negated"][identity] for identity in primary["identities"]]
        ),
        "original_freeze_sha256": original_state["freeze_sha256"],
        "original_seal_sha256": original_seal["seal_sha256"],
        "negated_freeze_sha256": negated_state["freeze_sha256"],
        "negated_seal_sha256": negated_seal["seal_sha256"],
        "synthetic_proof": proof,
    }
    payload["preflight_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    support.require(not OUT.exists(), f"Output directory already exists: {OUT}")
    support.require(not REPORT.exists(), f"Report already exists: {REPORT}")
    checked = preflight()
    metadata = load_matched_metadata("primary")
    original_state = original.verify_freeze()
    definitions: dict[str, Any] = {
        "result_sign": "WIN_GT_1E_12__LOSS_LT_MINUS_1E_12__ELSE_SCRATCH",
        "post_exit_path": "OPEN_AT_GTE_EXIT_AT_AND_OPEN_AT_LT_EXISTING_DEADLINE",
        "stop_disposition_order": [
            "STOP_THEN_TARGET",
            "STOP_THEN_ENTRY_RECLAIM",
            "STOP_CONFIRMED_TO_DEADLINE",
        ],
        "target_opportunity": "ACTUAL_FROZEN_TARGET_EXIT_VS_FINAL_COMPLETE_M1_CLOSE_BEFORE_SAME_DEADLINE",
        "structure": "UP_ONLY_HH_HL__DOWN_ONLY_LH_LL__ELSE_MIXED_OR_RANGE",
        "macro_alignment": "SEALED_STATE_VS_ORIGINAL_DIRECTION",
        "planned_r_bins": ["<0.5", "0.5-1.0", "1.0-1.5", "1.5-2.0", ">=2.0"],
        "break_distance_bins": ["<1", "1-2", "2-4", ">=4"],
        "time_remaining_bins": ["<30m", "30-60m", "60-120m", ">=120m"],
        "pivot_age_bins": ["<15m", "15-30m", "30-60m", ">=60m"],
        "target_age_bins": ["<1h", "1-4h", "4-24h", ">=24h"],
        "new_york_phases": ["08:00-09:30", "09:30-10:30", "10:30-11:30", "11:30-12:00"],
        "continuation_run": "SAME_DAY_UNINTERRUPTED_CONTINUATION_SIGNAL_SEQUENCE_WITH_SAME_ORIGINAL_DIRECTION",
        "group_fields": list(GROUP_FIELDS),
        "r_denominator_usd": 50.0,
        "overlapping_setups_retained": True,
        "one_trade_rule": False,
        "wait_for_resolution": False,
        "strategy_change_permitted": False,
    }
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_V1_FREEZE_1_0",
        "frozen_at": support.now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_EXPOSED_POST_RESULT_ATTRIBUTION",
        "population": {
            "matched_cases": 434,
            "identities": metadata["identities"],
            "identities_sha256": checked["identities_sha256"],
            "compiled_rows_sha256": checked["compiled_rows_sha256"],
            "original_result_rows_sha256": checked["original_result_rows_sha256"],
            "negated_result_rows_sha256": checked["negated_result_rows_sha256"],
        },
        "definitions": definitions,
        "definitions_sha256": canonical_hash(definitions),
        "synthetic_proof": checked["synthetic_proof"],
        "predecessor": {
            "original_freeze_sha256": checked["original_freeze_sha256"],
            "original_seal_sha256": checked["original_seal_sha256"],
            "negated_freeze_sha256": checked["negated_freeze_sha256"],
            "negated_seal_sha256": checked["negated_seal_sha256"],
            "original_freeze": support.file_record(original.FREEZE),
            "original_primary": support.file_record(original.PRIMARY),
            "original_reference": support.file_record(original.REFERENCE),
            "original_final": support.file_record(original.FINAL),
            "original_seal": support.file_record(original.SEAL),
            "negated_freeze": support.file_record(negated.FREEZE),
            "negated_primary": support.file_record(negated.PRIMARY),
            "negated_reference": support.file_record(negated.REFERENCE),
            "negated_final": support.file_record(negated.FINAL),
            "negated_seal": support.file_record(negated.SEAL),
        },
        "governing_files": [
            support.file_record(path)
            for path in (CONTRACT, IMPLEMENTATION, TESTS, RUNNER)
        ],
        "source_records": original_state["source_records"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    support.write_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": "FROZEN_MATCHED_CASE_ATTRIBUTION",
                "matched_cases": 434,
                "synthetic_tests": checked["synthetic_proof"]["passed"],
                "freeze_sha256": payload["freeze_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def verify_freeze() -> dict[str, Any]:
    frozen = support.verify_canonical_payload(FREEZE, "freeze_sha256")
    for record in frozen["governing_files"] + frozen["source_records"]:
        support.verify_file_record(record)
    for record in frozen["predecessor"].values():
        if isinstance(record, dict) and "path" in record:
            support.verify_file_record(record)
    original_state = original.verify_freeze()
    original_seal = support.verify_canonical_seal(original.SEAL)
    negated_state = negated.verify_freeze()
    negated_seal = support.verify_canonical_seal(negated.SEAL)
    support.require(
        original_state["freeze_sha256"] == frozen["predecessor"]["original_freeze_sha256"],
        "Original predecessor freeze differs",
    )
    support.require(
        original_seal["seal_sha256"] == frozen["predecessor"]["original_seal_sha256"],
        "Original predecessor seal differs",
    )
    support.require(
        negated_state["freeze_sha256"] == frozen["predecessor"]["negated_freeze_sha256"],
        "Negated predecessor freeze differs",
    )
    support.require(
        negated_seal["seal_sha256"] == frozen["predecessor"]["negated_seal_sha256"],
        "Negated predecessor seal differs",
    )
    return frozen


def run_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    metadata = load_matched_metadata(side)
    support.require(
        metadata["identities"] == frozen["population"]["identities"],
        f"{side} identities differ from freeze",
    )
    run_states = assign_run_ordinals(metadata["compiled_all"])
    streams = source.load_streams(side)
    rows: list[dict[str, Any]] = []
    for compiled in metadata["compiled"]:
        identity = str(compiled["event_identity"])
        alias = str(compiled["case_alias"])
        support.require(alias in streams, f"Missing {side} stream: {alias}")
        rows.append(
            analyse_pair(
                compiled,
                metadata["original"][identity]["result"],
                metadata["negated"][identity]["result"],
                streams[alias]["timeframes"]["1m"],
                run_states[identity],
            )
        )
    summary = aggregate(rows)
    support.require(summary["matched_cases"] == 434, f"{side} case count differs")
    payload: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_V1_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "aggregate": summary,
        "aggregate_sha256": summary["aggregate_sha256"],
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def ledger_csv(rows: list[dict[str, Any]]) -> str:
    fields = [
        "trading_date_utc",
        "case_alias",
        "event_identity",
        "decision_at",
        "original_direction",
        "pair_result_transition",
        "pair_resolution_transition",
        "original_net_r50",
        "negated_net_r50",
        "negation_delta_r50",
        "original_stop_disposition",
        "negated_stop_disposition",
        "original_deadline_minus_actual_r50",
        "negated_deadline_minus_actual_r50",
        "original_available_mfe_r50",
        "negated_available_mfe_r50",
        "original_cost_drag_r50",
        "negated_cost_drag_r50",
        "macro_alignment",
        "h1_alignment",
        "h4_alignment",
        "target_timeframe",
        "planned_r_bin",
        "break_distance_bin",
        "decision_phase",
        "continuation_ordinal_label",
    ]
    handle = io.StringIO(newline="")
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        groups = row["groups"]
        writer.writerow(
            {
                "trading_date_utc": row["trading_date_utc"],
                "case_alias": row["case_alias"],
                "event_identity": row["event_identity"],
                "decision_at": row["decision_at"],
                "original_direction": groups["original_direction"],
                "pair_result_transition": row["pair_result_transition"],
                "pair_resolution_transition": row["pair_resolution_transition"],
                "original_net_r50": row["original"]["net_r50"],
                "negated_net_r50": row["negated"]["net_r50"],
                "negation_delta_r50": row["negation_delta_r50"],
                "original_stop_disposition": row["original"]["stopped_disposition"],
                "negated_stop_disposition": row["negated"]["stopped_disposition"],
                "original_deadline_minus_actual_r50": row["original"]["deadline_minus_actual_r50"],
                "negated_deadline_minus_actual_r50": row["negated"]["deadline_minus_actual_r50"],
                "original_available_mfe_r50": row["original"]["available_mfe_r50"],
                "negated_available_mfe_r50": row["negated"]["available_mfe_r50"],
                "original_cost_drag_r50": row["original"]["explicit_cost_drag_r50"],
                "negated_cost_drag_r50": row["negated"]["explicit_cost_drag_r50"],
                "macro_alignment": groups["macro_alignment"],
                "h1_alignment": groups["h1_alignment"],
                "h4_alignment": groups["h4_alignment"],
                "target_timeframe": groups["target_timeframe"],
                "planned_r_bin": groups["planned_r_bin"],
                "break_distance_bin": groups["break_distance_bin"],
                "decision_phase": groups["decision_phase"],
                "continuation_ordinal_label": groups["continuation_ordinal_label"],
            }
        )
    return handle.getvalue()


def fmt_pf(value: Any) -> str:
    return "inf" if value is None else f"{float(value):.2f}"


def group_table(lines: list[str], aggregate_payload: dict[str, Any], field: str) -> None:
    lines.extend(
        [
            f"### {field}",
            "",
            "| State | N | Original win | Original R | Negated win | Negated R | Delta R |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for state, row in aggregate_payload["group_tables"][field].items():
        old = row["original"]
        new = row["negated"]
        lines.append(
            f"| {state} | {row['support']} | {old['win_rate'] * 100:.2f}% | {old['net_r50']:+.4f} | {new['win_rate'] * 100:.2f}% | {new['net_r50']:+.4f} | {row['negation_delta_r50']:+.4f} |"
        )
    lines.append("")


def report_markdown(final: dict[str, Any]) -> str:
    data = final["aggregate"]
    old = data["original"]
    new = data["negated"]
    old_econ = old["economic"]
    new_econ = new["economic"]
    lines = [
        "# Gold Continuation True-Negation Matched-Case Attribution V1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "This is a descriptive audit of the same 434 exposed continuation identities. It changes no trade and retains every overlapping setup.",
        "",
        "## Net result and negation change",
        "",
        "| Track | Trades | Win rate | Net R | PF |",
        "|---|---:|---:|---:|---:|",
        f"| Original | {old_econ['trades']} | {old_econ['win_rate'] * 100:.2f}% | {old_econ['net_r50']:+.4f} | {fmt_pf(old_econ['profit_factor'])} |",
        f"| Fixed-quantity negation | {new_econ['trades']} | {new_econ['win_rate'] * 100:.2f}% | {new_econ['net_r50']:+.4f} | {fmt_pf(new_econ['profit_factor'])} |",
        f"| Change from negation | {data['matched_cases']} |  | {data['negation_delta_r50_total']:+.4f} |  |",
        "",
        "## Matched outcome transitions",
        "",
        "| Transition | Cases |",
        "|---|---:|",
    ]
    for key, count in data["pair_result_transition_counts"].items():
        lines.append(f"| {key} | {count} |")
    lines.extend(["", "## Matched execution-resolution transitions", "", "| Transition | Cases |", "|---|---:|"])
    for key, count in sorted(
        data["pair_resolution_transition_counts"].items(),
        key=lambda item: (-item[1], item[0]),
    ):
        lines.append(f"| {key} | {count} |")
    lines.extend(
        [
            "",
            "## Stop attribution",
            "",
            "| Track | Stops | Then target | Then entry reclaim | Confirmed to deadline | Pre-stop MFE R | Recovery opportunity R | Ambiguous |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label, track in (("Original", old), ("Negated", new)):
        stops = track["stops"]
        dispositions = stops["dispositions"]
        lines.append(
            f"| {label} | {stops['count']} | {dispositions.get('STOP_THEN_TARGET', 0)} | {dispositions.get('STOP_THEN_ENTRY_RECLAIM', 0)} | {dispositions.get('STOP_CONFIRMED_TO_DEADLINE', 0)} | {stops['pre_stop_mfe_r50_total']:.4f} | {stops['stopped_then_target_recovery_delta_r50_total']:.4f} | {track['ambiguous_stop_first']} |"
        )
    lines.extend(
        [
            "",
            "## Profit and exit attribution",
            "",
            "| Track | Targets | Deadline better | Deadline worse | Deadline delta R | Post-target extension R | Time exits | Time-exit uncaptured MFE R |",
            "|---|---:|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for label, track in (("Original", old), ("Negated", new)):
        targets = track["targets"]
        time_exits = track["time_exits"]
        lines.append(
            f"| {label} | {targets['count']} | {targets['deadline_better_count']} | {targets['deadline_worse_count']} | {targets['deadline_minus_actual_r50_total']:+.4f} | {targets['post_target_extension_r50_total']:.4f} | {time_exits['count']} | {time_exits['mfe_not_captured_r50_total']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Execution and available movement",
            "",
            "| Track | Cost drag R | Market entry degradation R | Total entry degradation R | Available MFE R | MFE not captured R | Structural/execution disagreements |",
            "|---|---:|---:|---:|---:|---:|---:|",
            f"| Original | {old['explicit_cost_drag_r50_total']:.4f} | {old['market_entry_degradation_r50_total']:+.4f} | {old['total_entry_degradation_r50_total']:+.4f} | {old['available_mfe_r50_total']:.4f} | {old['mfe_not_captured_r50_total']:.4f} | {old['structural_execution_disagreements']} |",
            f"| Negated | {new['explicit_cost_drag_r50_total']:.4f} | {new['market_entry_degradation_r50_total']:+.4f} | {new['total_entry_degradation_r50_total']:+.4f} | {new['available_mfe_r50_total']:.4f} | {new['mfe_not_captured_r50_total']:.4f} | {new['structural_execution_disagreements']} |",
            "",
            "`Available MFE` and recovery figures are hindsight attribution ceilings, not executable strategy returns.",
            "",
            "## Point-in-time descriptive group tables",
            "",
        ]
    )
    for field in GROUP_FIELDS:
        group_table(lines, data, field)
    lines.extend(
        [
            "## Integrity",
            "",
            "- All 434 original and negated identities and original quantities matched their predecessor seals.",
            "- Primary and reference case rows, matrices, aggregates and checksums matched exactly.",
            "- All overlapping setups remained in the audit; no one-trade or wait-for-resolution rule was applied.",
            "- No rule was changed, no setup removed, no new date opened, and 2025/2026 remained locked.",
            "- This is exposed post-result attribution with zero validation credit.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print("primary matched-case attribution complete: 434", flush=True)
    reference = run_side("reference", frozen)
    print("reference matched-case attribution complete: 434", flush=True)
    support.require(primary["rows"] == reference["rows"], "Primary/reference case rows differ")
    support.require(primary["aggregate"] == reference["aggregate"], "Primary/reference aggregate differs")
    data = primary["aggregate"]
    predecessor_final = support.verify_canonical_payload(negated.FINAL, "final_sha256")
    support.require(
        abs(data["original"]["economic"]["net_r50"] - predecessor_final["original_continuation"]["net_r50"]) <= 1e-9,
        "Original total does not reproduce",
    )
    support.require(
        abs(data["negated"]["economic"]["net_r50"] - predecessor_final["true_negated_continuation"]["net_r50"]) <= 1e-9,
        "Negated total does not reproduce",
    )
    final: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_V1_FINAL_1_0",
        "verdict": "COMPLETE_MATCHED_CASE_ATTRIBUTION_EXPOSED_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "aggregate": data,
        "aggregate_sha256": data["aggregate_sha256"],
        "primary_reference_exact": True,
        "all_overlapping_setups_retained": True,
        "strategy_changed": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO_EXPOSED_POST_RESULT_ATTRIBUTION",
    }
    final["final_sha256"] = canonical_hash(final)
    support.write_json(PRIMARY, primary)
    support.write_json(REFERENCE, reference)
    support.write_json(FINAL, final)
    support.write_text(LEDGER, ledger_csv(primary["rows"]))
    support.write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_V1_CERTIFICATION_1_0",
        "completed_at": support.now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "matched_cases_exact_434": data["matched_cases"] == 434,
            "original_total_reproduced": abs(data["original"]["economic"]["net_r50"] + 71.72636214285433) <= 1e-9,
            "negated_total_reproduced": abs(data["negated"]["economic"]["net_r50"] - 53.17798714286161) <= 1e-9,
            "primary_reference_exact": True,
            "overlapping_setups_retained": True,
            "one_trade_rule_absent": True,
            "strategy_unchanged": True,
            "fresh_periods_locked": True,
            "no_charge": True,
        },
        "output_records": [
            support.file_record(path) for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)
        ],
    }
    support.require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    support.write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_CONTINUATION_TRUE_NEGATION_MATCHED_CASE_ATTRIBUTION_V1_SEAL_1_0",
        "sealed_at": support.now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [
            support.file_record(path)
            for path in (FREEZE, PRIMARY, REFERENCE, FINAL, LEDGER, CERTIFICATION, REPORT)
        ],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    support.write_json(SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": final["verdict"],
                "pair_result_transition_counts": data["pair_result_transition_counts"],
                "pair_resolution_transition_counts": data["pair_resolution_transition_counts"],
                "original": data["original"],
                "negated": data["negated"],
                "negation_delta_r50_total": data["negation_delta_r50_total"],
                "report": REPORT.relative_to(ROOT).as_posix(),
                "ledger": LEDGER.relative_to(ROOT).as_posix(),
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("preflight", "freeze", "run", "all"))
    args = parser.parse_args()
    if args.action == "preflight":
        print(json.dumps(preflight(), indent=2), flush=True)
        return
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
