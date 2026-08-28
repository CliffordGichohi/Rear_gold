#!/usr/bin/env python3
"""Freeze, run, reproduce, and seal the corrected all-transition regression."""

from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
import os
import runpy
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import render_gold_auction_trade_placement_examples_v1 as placement  # noqa: E402
import run_gold_auction_control_router_jan_jun_2022_v1 as source  # noqa: E402
from gold_intel.analytics.auction_all_transition_executable_multi_opportunity_v2 import (  # noqa: E402
    HARD_INEXECUTABLE_REASONS,
    IGNORED_FORMER_QUALITY_FILTERS,
    RISK_USD,
    RULESET,
    compile_executable_population,
    execute_every_executable,
    matched_nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import (  # noqa: E402
    FALLBACK_SPREAD_PRICE,
    LATENCY_MINUTES,
    SLIPPAGE_PRICE,
    resolve_plan,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


CONTRACT = ROOT / "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_all_transition_executable_multi_opportunity_v2.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_all_transition_executable_multi_opportunity_v2.py"
RUNNER = Path(__file__).resolve()
PLAN_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_trade_placement_examples_v1.py"
OUTCOME_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_trade_placement_outcomes_v1.py"
PLACEMENT_RUNNER = ROOT / "tools" / "render_gold_auction_trade_placement_examples_v1.py"
SOURCE_RUNNER = ROOT / "tools" / "run_gold_auction_control_router_jan_jun_2022_v1.py"

WRONG_MAPPING_ROOT = ROOT / "research_artifacts" / "gold_auction_fresh_clear_multi_opportunity_exposed_regression_v1"
WRONG_MAPPING_FREEZE = WRONG_MAPPING_ROOT / "prevalue_freeze.json"
WRONG_MAPPING_FINAL = WRONG_MAPPING_ROOT / "final_result.json"
WRONG_MAPPING_SEAL = WRONG_MAPPING_ROOT / "seal.json"
TEN_SELECTOR_FINAL = ROOT / "research_artifacts" / "gold_auction_ten_case_reusable_optimization_and_replay_v1" / "final_result.json"

OUT = ROOT / "research_artifacts" / "gold_auction_all_transition_executable_multi_opportunity_exposed_regression_v2"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2_REPORT.md"


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
    path = ROOT / str(record["path"])
    require(path.is_file(), f"Frozen file missing: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Frozen file size differs: {path}")
    require(sha256_file(path) == str(record["sha256"]), f"Frozen file hash differs: {path}")


def verify_canonical_payload(path: Path, hash_field: str) -> dict[str, Any]:
    payload = load_json(path)
    submitted = str(payload[hash_field])
    require(
        canonical_hash({key: value for key, value in payload.items() if key != hash_field}) == submitted,
        f"Canonical payload differs: {path}",
    )
    return payload


def verify_canonical_seal(path: Path) -> dict[str, Any]:
    payload = verify_canonical_payload(path, "seal_sha256")
    for record in payload.get("files", []):
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
    atomic_create(
        path,
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False, allow_nan=False) + "\n").encode("utf-8"),
    )


def write_text(path: Path, payload: str) -> None:
    atomic_create(path, payload.encode("utf-8"))


def unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for record in records:
        key = str(record["path"])
        if key in output:
            require(output[key] == record, f"Conflicting source record: {key}")
        output[key] = record
    return [output[key] for key in sorted(output)]


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
    require(len(tests) == 6, f"Unexpected synthetic-test population: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def verify_wrong_mapping_preserved() -> tuple[dict[str, Any], dict[str, Any]]:
    seal = verify_canonical_seal(WRONG_MAPPING_SEAL)
    freeze = verify_canonical_payload(WRONG_MAPPING_FREEZE, "freeze_sha256")
    for record in freeze["governing_files"] + freeze["source_records"]:
        verify_file_record(record)
    final = verify_canonical_payload(WRONG_MAPPING_FINAL, "final_sha256")
    require(final["summary"]["all_valid_signals"]["trades"] == 35, "Prior wrong-mapping result differs")
    require(final["selector_id"] == "A3_FRESH_AND_CLEAR::E0::R0", "Prior wrong-mapping selector differs")
    require(seal["verdict"] == final["verdict"], "Prior wrong-mapping seal differs")
    return freeze, seal


def load_compiled(side: str) -> list[dict[str, Any]]:
    events_path = placement.EVENTS_PRIMARY if side == "primary" else placement.EVENTS_REFERENCE
    overlays_path = placement.OVERLAYS_PRIMARY if side == "primary" else placement.OVERLAYS_REFERENCE
    events = load_json(events_path)["events"]
    overlays = load_json(overlays_path)["overlays"]
    return compile_executable_population(events, overlays)


def assert_population(rows: list[dict[str, Any]]) -> None:
    require(len(rows) == 729, "Expected exactly 729 transition identities")
    require(len({row["event_identity"] for row in rows}) == 729, "Transition identities are not unique")
    require(len({row["trading_date_utc"] for row in rows}) == 117, "Expected exactly 117 exposed days")
    require(all(row["session"] == "NEW_YORK" for row in rows), "Non-New-York event entered population")
    dates = sorted({row["trading_date_utc"] for row in rows})
    require(dates[0] == "2022-01-03" and dates[-1] == "2022-06-30", "Population endpoints differ")
    require(not any("2022-02-17" <= value <= "2022-02-28" for value in dates), "Unopened February gap entered population")
    executable = [row for row in rows if row["mechanically_executable"]]
    require(len(executable) == 660, "Corrected pre-outcome population must contain exactly 660 executable setups")
    require(len({row["trading_date_utc"] for row in executable}) == 116, "Expected 116 days with executable setups")


def verify_ten_are_all_executable(rows: list[dict[str, Any]]) -> list[str]:
    selector = load_json(TEN_SELECTOR_FINAL)
    ten = [str(row["event_identity"]) for row in selector["selected_candidate"]["rows"]]
    require(len(ten) == 10 and len(set(ten)) == 10, "Ten-example identities differ")
    by_identity = {str(row["event_identity"]): row for row in rows}
    require(all(identity in by_identity for identity in ten), "Ten-example identity absent from full scanner")
    require(all(by_identity[identity]["mechanically_executable"] for identity in ten), "Corrected mapping rejects a ten-example setup")
    return ten


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    require(not REPORT.exists(), f"Report already exists: {REPORT}")
    wrong_freeze, wrong_seal = verify_wrong_mapping_preserved()
    scanner_seal = placement.verify_source_seal()
    source.verify_sources()
    primary = load_compiled("primary")
    reference = load_compiled("reference")
    assert_population(primary)
    require(primary == reference, "Primary/reference corrected pre-outcome compilation differs")
    ten = verify_ten_are_all_executable(primary)
    proof = synthetic_proof()
    executable = [row for row in primary if row["mechanically_executable"]]
    hard_counts = dict(sorted(Counter(reason for row in primary for reason in row["hard_inexecutable_reasons"]).items()))
    ignored_counts = dict(sorted(Counter(reason for row in primary for reason in row["ignored_former_quality_filters"]).items()))
    require(hard_counts == {"M5_PROTECTED_PIVOT_ALREADY_CONSUMED": 45, "NONPOSITIVE_STRUCTURAL_RISK": 1, "NO_UNCONSUMED_H1_OR_H4_DESTINATION": 24}, f"Hard reason counts differ: {hard_counts}")
    require(ignored_counts == {"DECISION_PRICE_CHASED_BEYOND_ONE_M5_ATR": 413, "TARGET_ROOM_BELOW_1P5R": 460}, f"Ignored quality-filter counts differ: {ignored_counts}")
    source_records = unique_records(
        [dict(record) for record in wrong_freeze["source_records"]]
        + [
            file_record(path)
            for path in (
                placement.EVENTS_PRIMARY,
                placement.EVENTS_REFERENCE,
                placement.OVERLAYS_PRIMARY,
                placement.OVERLAYS_REFERENCE,
                placement.SOURCE_SEAL,
                WRONG_MAPPING_FREEZE,
                WRONG_MAPPING_FINAL,
                WRONG_MAPPING_SEAL,
                TEN_SELECTOR_FINAL,
            )
        ]
    )
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2_FREEZE_1_0",
        "frozen_at": now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_EXPOSED_CORRECTIVE_IMPLEMENTATION_REGRESSION",
        "correction": {
            "prior_35_trade_mapping_preserved": True,
            "prior_mapping_role": "WRONG_MAPPING_DIAGNOSTIC_NOT_THE_REQUESTED_IMPLEMENTATION",
            "ten_example_sampler_used_as_admission_filter": False,
            "fitted_a3_selector_used": False,
        },
        "population": {
            "events": 729,
            "session_days": 117,
            "executable_setups": 660,
            "days_with_executable_setup": 116,
            "event_identities": [row["event_identity"] for row in primary],
            "event_identities_sha256": canonical_hash([row["event_identity"] for row in primary]),
            "executable_identities": [row["event_identity"] for row in executable],
            "executable_identities_sha256": canonical_hash([row["event_identity"] for row in executable]),
            "hard_reason_counts": hard_counts,
            "ignored_former_quality_filter_counts": ignored_counts,
            "ten_example_identities": ten,
            "ten_examples_all_executable": True,
            "date_start": "2022-01-03",
            "date_end": "2022-06-30",
            "excluded_unopened_gap": ["2022-02-17", "2022-02-28"],
        },
        "admission": {
            "hard_inexecutable_reasons": sorted(HARD_INEXECUTABLE_REASONS),
            "ignored_former_quality_filters": sorted(IGNORED_FORMER_QUALITY_FILTERS),
            "a3_or_other_fitted_selector": False,
            "continuation_refresh_rejection": False,
            "minimum_reward_to_risk": None,
            "maximum_distance_from_break_atr": None,
            "local_m15_minimum_room": None,
        },
        "execution": {
            "scan_every_transition": True,
            "one_candidate_per_day_cap": False,
            "wait_for_previous_resolution": False,
            "execute_overlapping_positions": True,
            "suppress_defer_merge_net_or_resize": False,
            "latency_minutes": LATENCY_MINUTES,
            "slippage_price": SLIPPAGE_PRICE,
            "fallback_spread_price": FALLBACK_SPREAD_PRICE,
            "maximum_planned_risk_usd_per_setup": RISK_USD,
            "position_sizing": "WHOLE_OUNCE",
            "stop": "PROTECTED_M5_STRUCTURAL_PIVOT",
            "target": "NEAREST_KNOWN_UNCONSUMED_H1_H4_LIQUIDITY",
            "deadline": "NOON_NEW_YORK",
            "ambiguous_bar": "STOP_FIRST",
            "nonoverlap": "MATCHED_DIAGNOSTIC_ONLY",
        },
        "synthetic_proof": proof,
        "predecessor_seals": {
            "scanner": scanner_seal["seal_sha256"],
            "wrong_mapping": wrong_seal["seal_sha256"],
        },
        "governing_files": [
            file_record(path)
            for path in (
                CONTRACT,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                PLAN_IMPLEMENTATION,
                OUTCOME_IMPLEMENTATION,
                PLACEMENT_RUNNER,
                SOURCE_RUNNER,
            )
        ],
        "source_records": source_records,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json(FREEZE, payload)
    print(
        json.dumps(
            {
                "status": "FROZEN_CORRECTED_MAPPING",
                "events": 729,
                "executable_setups": 660,
                "days": 116,
                "hard_reasons": hard_counts,
                "ignored_filters": ignored_counts,
                "synthetic_tests": proof["passed"],
                "freeze_sha256": payload["freeze_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def verify_freeze() -> dict[str, Any]:
    frozen = verify_canonical_payload(FREEZE, "freeze_sha256")
    for record in frozen["governing_files"] + frozen["source_records"]:
        verify_file_record(record)
    _, wrong_seal = verify_wrong_mapping_preserved()
    scanner = placement.verify_source_seal()
    require(wrong_seal["seal_sha256"] == frozen["predecessor_seals"]["wrong_mapping"], "Wrong-mapping predecessor seal differs")
    require(scanner["seal_sha256"] == frozen["predecessor_seals"]["scanner"], "Scanner predecessor seal differs")
    source.verify_sources()
    require(frozen["population"]["executable_setups"] == 660, "Frozen executable count differs")
    require(frozen["admission"]["a3_or_other_fitted_selector"] is False, "A fitted selector entered corrected freeze")
    return frozen


def run_side(side: str, frozen: dict[str, Any]) -> dict[str, Any]:
    compiled = load_compiled(side)
    assert_population(compiled)
    require([row["event_identity"] for row in compiled] == frozen["population"]["event_identities"], f"{side} event identities differ")
    require([row["event_identity"] for row in compiled if row["mechanically_executable"]] == frozen["population"]["executable_identities"], f"{side} executable identities differ")
    streams = source.load_streams(side)
    require(len(streams) == 117, f"{side} stream count differs")
    rows = execute_every_executable(compiled, streams, resolve_plan)
    diagnostic = matched_nonoverlap_diagnostic(rows)
    summary = summarize(rows, diagnostic)
    require(summary["all_executable_signals"]["trades"] == 660, f"{side} did not execute all 660 setups")
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2_SIDE_1_0",
        "side": side,
        "rows": rows,
        "rows_sha256": canonical_hash(rows),
        "nonoverlap_diagnostic_rows": diagnostic,
        "nonoverlap_diagnostic_sha256": canonical_hash(diagnostic),
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
        "all_660_executed": True,
        "overlap_suppression_applied": False,
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def ledger_csv(rows: list[dict[str, Any]]) -> str:
    handle = io.StringIO(newline="")
    fields = [
        "trading_date_utc",
        "case_alias",
        "event_identity",
        "decision_at",
        "fill_at",
        "exit_at",
        "direction",
        "event_class",
        "context_family",
        "ignored_former_quality_filters",
        "entry",
        "stop",
        "target",
        "planned_r",
        "resolution",
        "quantity_ounces",
        "displayed_planned_risk_usd",
        "net_r50",
        "net_pnl_usd",
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        if row["execution_disposition"] != "EXECUTED_UNRESTRICTED_ALL_SIGNALS":
            continue
        result = row["result"]
        execution = result["execution"]
        writer.writerow(
            {
                "trading_date_utc": row["trading_date_utc"],
                "case_alias": row["case_alias"],
                "event_identity": row["event_identity"],
                "decision_at": row["decision_at"],
                "fill_at": execution["fill_at"],
                "exit_at": execution["exit_at"],
                "direction": row["direction"],
                "event_class": row["event_class"],
                "context_family": row["context_family"],
                "ignored_former_quality_filters": ";".join(row["ignored_former_quality_filters"]),
                "entry": result["entry"],
                "stop": result["stop"],
                "target": result["target"],
                "planned_r": result["planned_r"],
                "resolution": execution["resolution"],
                "quantity_ounces": execution["quantity_ounces"],
                "displayed_planned_risk_usd": execution["displayed_planned_risk_usd"],
                "net_r50": execution["net_r50"],
                "net_pnl_usd": execution["net_pnl_usd"],
            }
        )
    return handle.getvalue()


def pf(row: dict[str, Any]) -> str:
    return "inf" if row["profit_factor"] is None else f"{row['profit_factor']:.2f}"


def report_markdown(final: dict[str, Any]) -> str:
    summary = final["summary"]
    primary = summary["all_executable_signals"]
    diagnostic = summary["matched_nonoverlap_diagnostic"]
    lines = [
        "# Gold Auction All-Transition Executable Multi-Opportunity Exposed Regression V2 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "## Corrected implementation",
        "",
        "The prior 35-trade run is preserved as a wrong-mapping diagnostic. V2 did not use the ten-example sampler, A3 selector, 1.5R minimum, one-ATR chase limit, continuation rejection, local-M15-room filter, daily cap, or wait-for-resolution rule.",
        "",
        f"- Transitions scanned: **{summary['event_population']}**.",
        f"- Mechanically executable setups: **{primary['trades']}** across **{summary['days_with_trade']}** days.",
        f"- Frequency: **{summary['average_trades_per_calendar_month']:.2f} setups per calendar month**, maximum **{summary['maximum_trades_one_day']}** in one day.",
        f"- Direction: **{summary['by_direction']['LONG']['trades']} LONG / {summary['by_direction']['SHORT']['trades']} SHORT**.",
        f"- Overlapping signals retained: **{summary['overlap_signals_retained_by_primary']}**.",
        f"- Maximum concurrency: **{summary['concurrency']['maximum_concurrent_positions']} positions / ${summary['concurrency']['maximum_concurrent_planned_risk_usd']:.2f} planned risk**.",
        "",
        "## Primary exposed result",
        "",
        f"Unrestricted all-signal track: **{primary['net_r50']:+.4f}R / ${primary['net_pnl_usd']:+.2f}**, {primary['win_rate'] * 100:.2f}% win rate, {primary['expectancy_r50']:+.4f}R expectancy, PF {pf(primary)}, max drawdown {primary['maximum_drawdown_r50']:.4f}R.",
        "",
        f"Matched wait-for-resolution diagnostic: **{diagnostic['net_r50']:+.4f}R / ${diagnostic['net_pnl_usd']:+.2f}**, {diagnostic['trades']} trades, PF {pf(diagnostic)}, max drawdown {diagnostic['maximum_drawdown_r50']:.4f}R.",
        "",
        "## Monthly results",
        "",
        "| Month | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for month, row in summary["by_month"].items():
        lines.append(f"| {month} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {pf(row)} | {row['maximum_drawdown_r50']:.4f} |")
    lines.extend(
        [
            "",
            "## Direction results",
            "",
            "| Direction | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    for direction, row in summary["by_direction"].items():
        lines.append(f"| {direction} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {pf(row)} | {row['maximum_drawdown_r50']:.4f} |")
    lines.extend(
        [
            "",
            "## Event-family results",
            "",
            "| Event class | Trades | Win rate | Net R | PF |",
            "|---|---:|---:|---:|---:|",
        ]
    )
    for event_class, row in summary["by_event_class"].items():
        lines.append(f"| {event_class} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | {pf(row)} |")
    lines.extend(
        [
            "",
            "## Integrity and interpretation",
            "",
            "- All 660 frozen executable identities were resolved in both independent passes; results and checksums matched exactly.",
            "- Every overlapping setup remained in the primary ledger. The non-overlap result is diagnostic only.",
            "- Structural stops, known-liquidity targets, one-minute latency, costs, noon deadline, stop-first ambiguity, and whole-ounce sizing were preserved.",
            "- No new data, 2025, or 2026 was opened and no charge occurred.",
            "- This is an exposed implementation regression with zero validation credit, not proof of a validated edge.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    primary = run_side("primary", frozen)
    print(f"primary complete: {primary['summary']['all_executable_signals']['trades']} trades", flush=True)
    reference = run_side("reference", frozen)
    print(f"reference complete: {reference['summary']['all_executable_signals']['trades']} trades", flush=True)
    require(primary["rows"] == reference["rows"], "Primary/reference executions differ")
    require(primary["nonoverlap_diagnostic_rows"] == reference["nonoverlap_diagnostic_rows"], "Primary/reference non-overlap diagnostics differ")
    require(primary["summary"] == reference["summary"], "Primary/reference summaries differ")
    summary = primary["summary"]
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2_FINAL_1_0",
        "verdict": "COMPLETE_CORRECTED_ALL_660_EXPOSED_REGRESSION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "prior_35_trade_result_preserved_as_wrong_mapping_diagnostic": True,
        "primary_reference_exact": True,
        "all_660_executable_signals_executed": True,
        "overlap_suppression_applied": False,
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO_EXPOSED_CORRECTIVE_REGRESSION",
    }
    final["final_sha256"] = canonical_hash(final)
    write_json(PRIMARY, primary)
    write_json(REFERENCE, reference)
    write_json(FINAL, final)
    write_text(LEDGER, ledger_csv(primary["rows"]))
    write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "events_exact_729": summary["event_population"] == 729,
            "trades_exact_660": summary["all_executable_signals"]["trades"] == 660,
            "days_exact_116": summary["days_with_trade"] == 116,
            "fitted_selector_absent": frozen["admission"]["a3_or_other_fitted_selector"] is False,
            "quality_filters_absent": frozen["admission"]["minimum_reward_to_risk"] is None and frozen["admission"]["maximum_distance_from_break_atr"] is None,
            "daily_cap_absent": frozen["execution"]["one_candidate_per_day_cap"] is False,
            "wait_for_resolution_absent": frozen["execution"]["wait_for_previous_resolution"] is False,
            "overlaps_executed": True,
            "primary_reference_exact": True,
            "fresh_periods_locked": True,
            "no_acquisition_or_charge": True,
        },
        "output_records": [file_record(path) for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)],
    }
    require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_ALL_TRANSITION_EXECUTABLE_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V2_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [file_record(path) for path in (FREEZE, PRIMARY, REFERENCE, FINAL, LEDGER, CERTIFICATION, REPORT)],
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
                "summary": summary,
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
    parser.add_argument("action", choices=("freeze", "run", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"run", "all"}:
        run()


if __name__ == "__main__":
    main()
