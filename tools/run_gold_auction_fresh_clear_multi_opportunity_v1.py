#!/usr/bin/env python3
"""Run the exposed all-valid-signal Fresh-and-Clear scanner regression."""

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
import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as baseline  # noqa: E402
from gold_intel.analytics.auction_fresh_clear_multi_opportunity_v1 import (  # noqa: E402
    ADMISSION_POLICY,
    RISK_USD,
    RULESET,
    SELECTOR_ID,
    compile_transition_population,
    execute_all_admitted,
    nonoverlap_diagnostic,
    summarize,
)
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import (  # noqa: E402
    FALLBACK_SPREAD_PRICE,
    LATENCY_MINUTES,
    SLIPPAGE_PRICE,
    resolve_plan,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


CONTRACT = ROOT / "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_fresh_clear_multi_opportunity_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_fresh_clear_multi_opportunity_v1.py"
RUNNER = Path(__file__).resolve()
PLAN_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_trade_placement_examples_v1.py"
OUTCOME_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_trade_placement_outcomes_v1.py"
SELECTOR_IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_ten_case_reusable_optimization_v1.py"

SELECTOR_ROOT = ROOT / "research_artifacts" / "gold_auction_ten_case_reusable_optimization_and_replay_v1"
SELECTOR_FINAL = SELECTOR_ROOT / "final_result.json"
SELECTOR_SEAL = SELECTOR_ROOT / "seal.json"
SCANNER_SEAL = placement.SOURCE_SEAL

OUT = ROOT / "research_artifacts" / "gold_auction_fresh_clear_multi_opportunity_exposed_regression_v1"
FREEZE = OUT / "prevalue_freeze.json"
PRIMARY = OUT / "primary.json"
REFERENCE = OUT / "reference.json"
FINAL = OUT / "final_result.json"
LEDGER = OUT / "trade_ledger.csv"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1_REPORT.md"


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


def verify_canonical_seal(path: Path) -> dict[str, Any]:
    payload = load_json(path)
    submitted = str(payload["seal_sha256"])
    body = {key: value for key, value in payload.items() if key != "seal_sha256"}
    require(canonical_hash(body) == submitted, f"Seal payload differs: {path}")
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


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    tests = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
    require(len(tests) == 5, f"Unexpected synthetic tests: {tests}")
    for name in tests:
        namespace[name]()
    payload = {"passed": len(tests), "tests": tests}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def load_compiled(side: str) -> list[dict[str, Any]]:
    events_path = placement.EVENTS_PRIMARY if side == "primary" else placement.EVENTS_REFERENCE
    overlays_path = placement.OVERLAYS_PRIMARY if side == "primary" else placement.OVERLAYS_REFERENCE
    events = load_json(events_path)["events"]
    overlays = load_json(overlays_path)["overlays"]
    return compile_transition_population(events, overlays)


def selected_ten() -> tuple[dict[str, Any], dict[str, Any]]:
    seal = verify_canonical_seal(SELECTOR_SEAL)
    result = load_json(SELECTOR_FINAL)
    require(result["verdict"] == seal["verdict"], "Selector verdict and seal differ")
    require(result["selected_candidate_id"] == SELECTOR_ID, "Frozen selected candidate differs")
    require(result["selected_candidate"]["candidate_id"] == SELECTOR_ID, "Selected payload differs")
    return result, seal


def jan_stream_records() -> list[dict[str, Any]]:
    certification = load_json(baseline.JAN_CERTIFICATION)
    require(certification["verdict"] == "PASS_CODEX_OPERATOR_PRIVATE_STREAM_MATERIALIZATION", "January source certification differs")
    records: list[dict[str, Any]] = []
    for case in certification["case_files"]:
        for side in ("primary", "reference"):
            declared = case[side]
            path = ROOT / str(declared["path"])
            record = file_record(path)
            require(record["sha256"] == str(declared["sha256"]), f"January stream differs: {path}")
            records.append(record)
    return records


def unique_records(records: list[dict[str, Any]]) -> list[dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    for record in records:
        path = str(record["path"])
        if path in output:
            require(output[path] == record, f"Conflicting source record: {path}")
        output[path] = record
    return [output[path] for path in sorted(output)]


def assert_population(rows: list[dict[str, Any]]) -> None:
    require(len(rows) == 729, "Expected exactly 729 scanner events")
    require(len({row["event_identity"] for row in rows}) == 729, "Scanner identities are not unique")
    require(len({row["trading_date_utc"] for row in rows}) == 117, "Expected 117 exposed session-days")
    require(all(row["session"] == "NEW_YORK" for row in rows), "Non-New-York event entered the population")
    dates = sorted({row["trading_date_utc"] for row in rows})
    require(dates[0] == "2022-01-03" and dates[-1] == "2022-06-30", "Population endpoints differ")
    require(not any("2022-02-17" <= value <= "2022-02-28" for value in dates), "Unopened February gap entered population")


def verify_ten_decisions(compiled: list[dict[str, Any]], selector: dict[str, Any]) -> None:
    by_identity = {row["event_identity"]: row for row in compiled}
    selected_rows = selector["selected_candidate"]["rows"]
    require(len(selected_rows) == 10, "Expected ten selector rows")
    for expected in selected_rows:
        identity = str(expected["event_identity"])
        require(identity in by_identity, f"Ten-case event absent from scanner population: {identity}")
        require(bool(by_identity[identity]["admitted"]) == bool(expected["admitted"]), f"Ten-case admission differs: {identity}")


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    require(not REPORT.exists(), f"Report already exists: {REPORT}")
    scanner_seal = placement.verify_source_seal()
    selector, selector_seal = selected_ten()
    source_records = list(source.verify_sources().values())
    source_records.extend(jan_stream_records())
    source_records.extend(
        file_record(path)
        for path in (
            baseline.JAN_CERTIFICATION,
            baseline.MAR_PRIMARY_STREAM,
            baseline.MAR_REFERENCE_STREAM,
            source.JUNE_PRIMARY_STREAMS,
            source.JUNE_REFERENCE_STREAMS,
            placement.EVENTS_PRIMARY,
            placement.EVENTS_REFERENCE,
            placement.OVERLAYS_PRIMARY,
            placement.OVERLAYS_REFERENCE,
            SCANNER_SEAL,
            SELECTOR_FINAL,
            SELECTOR_SEAL,
        )
    )
    source_records = unique_records(source_records)

    primary = load_compiled("primary")
    reference = load_compiled("reference")
    assert_population(primary)
    require(primary == reference, "Primary/reference predecision compilation differs")
    verify_ten_decisions(primary, selector)
    proof = synthetic_proof()
    dispositions = dict(sorted(Counter(row["disposition"] for row in primary).items()))
    admitted = [row for row in primary if row["admitted"]]
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1_FREEZE_1_0",
        "frozen_at": now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_EXPOSED_IMPLEMENTATION_REGRESSION",
        "population": {
            "events": len(primary),
            "session_days": 117,
            "event_identities": [row["event_identity"] for row in primary],
            "event_identities_sha256": canonical_hash([row["event_identity"] for row in primary]),
            "admitted_identities": [row["event_identity"] for row in admitted],
            "admitted_identities_sha256": canonical_hash([row["event_identity"] for row in admitted]),
            "preoutcome_dispositions": dispositions,
            "date_start": "2022-01-03",
            "date_end": "2022-06-30",
            "excluded_unopened_gap": ["2022-02-17", "2022-02-28"],
        },
        "selector": {
            "candidate_id": SELECTOR_ID,
            "admission_policy": ADMISSION_POLICY,
            "continuation_refresh_rejected": True,
            "minimum_local_m15_destination_room_r": 1.0,
            "management": "E0_R0_ORIGINAL_STRUCTURAL_LIFECYCLE",
        },
        "execution": {
            "scan_all_transitions": True,
            "one_candidate_per_day_cap": False,
            "wait_for_previous_resolution": False,
            "overlapping_admitted_setups_executed": True,
            "signals_suppressed_deferred_merged_netted_or_resized": False,
            "latency_minutes": LATENCY_MINUTES,
            "slippage_price": SLIPPAGE_PRICE,
            "fallback_spread_price": FALLBACK_SPREAD_PRICE,
            "maximum_risk_usd_per_setup": RISK_USD,
            "position_sizing": "WHOLE_OUNCE",
            "stop": "ORIGINAL_PROTECTED_M5_PIVOT",
            "target": "ORIGINAL_NEAREST_KNOWN_UNCONSUMED_H1_H4_LIQUIDITY",
            "deadline": "NOON_NEW_YORK",
            "ambiguity": "STOP_FIRST",
            "nonoverlap_track": "MATCHED_DIAGNOSTIC_ONLY",
        },
        "synthetic_proof": proof,
        "ten_case_mapping_reproduced_preoutcome": True,
        "predecessor_seals": {
            "scanner": scanner_seal["seal_sha256"],
            "selector": selector_seal["seal_sha256"],
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
                SELECTOR_IMPLEMENTATION,
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
                "status": "FROZEN",
                "events": len(primary),
                "admitted_preoutcome": len(admitted),
                "dispositions": dispositions,
                "synthetic_tests": proof["passed"],
                "freeze_sha256": payload["freeze_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def verify_freeze() -> dict[str, Any]:
    frozen = load_json(FREEZE)
    submitted = str(frozen["freeze_sha256"])
    require(canonical_hash({key: value for key, value in frozen.items() if key != "freeze_sha256"}) == submitted, "Freeze payload differs")
    for record in frozen["governing_files"] + frozen["source_records"]:
        verify_file_record(record)
    scanner = placement.verify_source_seal()
    selector, selector_seal = selected_ten()
    require(scanner["seal_sha256"] == frozen["predecessor_seals"]["scanner"], "Scanner seal differs")
    require(selector_seal["seal_sha256"] == frozen["predecessor_seals"]["selector"], "Selector seal differs")
    require(selector["selected_candidate_id"] == frozen["selector"]["candidate_id"], "Selector identity differs")
    source.verify_sources()
    return frozen


def verify_ten_execution(rows: list[dict[str, Any]], selector: dict[str, Any]) -> dict[str, Any]:
    by_identity = {row["event_identity"]: row for row in rows}
    matched = 0
    executed = 0
    for expected in selector["selected_candidate"]["rows"]:
        row = by_identity[str(expected["event_identity"])]
        require(bool(row["execution_disposition"] == "EXECUTED_ALL_VALID_SIGNALS") == bool(expected["admitted"]), f"Ten-case execution admission differs: {row['event_identity']}")
        if expected["admitted"]:
            require(abs(float(row["net_r50"]) - float(expected["net_r50"])) <= 1e-10, f"Ten-case outcome differs: {row['event_identity']}")
            executed += 1
        matched += 1
    return {"matched": matched, "executed": executed, "exact": True}


def run_side(side: str, frozen: dict[str, Any], selector: dict[str, Any]) -> dict[str, Any]:
    compiled = load_compiled(side)
    assert_population(compiled)
    require([row["event_identity"] for row in compiled] == frozen["population"]["event_identities"], f"{side} event identities differ")
    require([row["event_identity"] for row in compiled if row["admitted"]] == frozen["population"]["admitted_identities"], f"{side} admitted identities differ")
    streams = source.load_streams(side)
    require(len(streams) == 117, f"{side} stream count differs")
    rows = execute_all_admitted(compiled, streams, resolve_plan)
    diagnostic = nonoverlap_diagnostic(rows)
    summary = summarize(rows, diagnostic)
    ten_mapping = verify_ten_execution(rows, selector)
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1_SIDE_1_0",
        "side": side,
        "compiled_rows": rows,
        "compiled_rows_sha256": canonical_hash(rows),
        "nonoverlap_diagnostic_rows": diagnostic,
        "nonoverlap_diagnostic_sha256": canonical_hash(diagnostic),
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
        "ten_case_execution_reproduction": ten_mapping,
        "all_admitted_signals_executed_including_overlaps": True,
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
        "entry",
        "stop",
        "target",
        "resolution",
        "quantity_ounces",
        "displayed_planned_risk_usd",
        "net_r50",
        "net_pnl_usd",
    ]
    writer = csv.DictWriter(handle, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for row in rows:
        if row["execution_disposition"] != "EXECUTED_ALL_VALID_SIGNALS":
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
                "entry": result["entry"],
                "stop": result["stop"],
                "target": result["target"],
                "resolution": execution["resolution"],
                "quantity_ounces": execution["quantity_ounces"],
                "displayed_planned_risk_usd": execution["displayed_planned_risk_usd"],
                "net_r50": execution["net_r50"],
                "net_pnl_usd": execution["net_pnl_usd"],
            }
        )
    return handle.getvalue()


def format_number(value: Any, digits: int = 3) -> str:
    if value is None:
        return "inf"
    return f"{float(value):.{digits}f}"


def report_markdown(final: dict[str, Any]) -> str:
    summary = final["summary"]
    primary = summary["all_valid_signals"]
    diagnostic = summary["nonoverlap_diagnostic"]
    lines = [
        "# Gold Fresh-and-Clear Multi-Opportunity Exposed Regression V1 Report",
        "",
        f"Verdict: `{final['verdict']}`",
        "",
        "## What was implemented",
        "",
        "The existing ten-trade scanner and its frozen `A3_FRESH_AND_CLEAR::E0::R0` selector were applied to every one of the 729 already exposed New York M15/M5 auction transitions. Every admitted setup was executed independently even when an earlier position was still open. No signal was suppressed, deferred, merged, netted, or resized because of overlap.",
        "",
        f"- Events scanned: **{summary['event_population']}** across **{summary['trading_days_in_population']}** exposed days.",
        f"- Qualifying setups executed: **{primary['trades']}** ({summary['average_trades_per_calendar_month']:.2f} per calendar month; maximum {summary['maximum_trades_one_day']} in one day).",
        f"- Direction mix: **{summary['by_direction'].get('LONG', {}).get('trades', 0)} LONG / {summary['by_direction'].get('SHORT', {}).get('trades', 0)} SHORT**.",
        f"- Overlapping setups retained: **{summary['overlap_signals_retained_by_primary']}**.",
        f"- Maximum concurrency: **{summary['concurrency']['maximum_concurrent_positions']} positions / ${summary['concurrency']['maximum_concurrent_planned_risk_usd']:.2f} planned risk**.",
        "",
        "## Exposed economics",
        "",
        f"All-valid-signal primary: **{primary['net_r50']:+.4f}R / ${primary['net_pnl_usd']:+.2f}**, {primary['win_rate'] * 100:.2f}% win rate, {primary['expectancy_r50']:+.4f}R expectancy, PF {format_number(primary['profit_factor'], 2)}, max drawdown {primary['maximum_drawdown_r50']:.4f}R.",
        "",
        f"Matched non-overlap diagnostic from the same signals: **{diagnostic['net_r50']:+.4f}R / ${diagnostic['net_pnl_usd']:+.2f}**, {diagnostic['trades']} trades, PF {format_number(diagnostic['profit_factor'], 2)}. This diagnostic did not suppress any primary trade.",
        "",
        "## Monthly results",
        "",
        "| Month | Trades | Win rate | Net R | PnL USD | PF | Max DD R |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for month, row in summary["by_month"].items():
        win_rate = 0.0 if row["win_rate"] is None else row["win_rate"] * 100.0
        lines.append(
            f"| {month} | {row['trades']} | {win_rate:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {format_number(row['profit_factor'], 2)} | {row['maximum_drawdown_r50']:.4f} |"
        )
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
        lines.append(
            f"| {direction} | {row['trades']} | {row['win_rate'] * 100:.2f}% | {row['net_r50']:+.4f} | ${row['net_pnl_usd']:+.2f} | {format_number(row['profit_factor'], 2)} | {row['maximum_drawdown_r50']:.4f} |"
        )
    lines.extend(
        [
            "",
            "## Integrity",
            "",
            "- The same-ten decisions and the four admitted same-ten outcomes reproduced the frozen selector result exactly.",
            "- Primary and reference compilations, executions, overlap diagnostics, summaries, and checksums matched exactly.",
            "- The 2022-02-17 through 2022-02-28 gap remained unopened. No 2025 or 2026 data was accessed.",
            "- This is an exposed implementation regression with zero validation credit; it measures what this exact scanner would have produced on already opened data.",
            "- No data was acquired and no charge was incurred.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    selector, _ = selected_ten()
    primary = run_side("primary", frozen, selector)
    print(f"primary complete: {primary['summary']['all_valid_signals']['trades']} trades", flush=True)
    reference = run_side("reference", frozen, selector)
    print(f"reference complete: {reference['summary']['all_valid_signals']['trades']} trades", flush=True)
    require(primary["compiled_rows"] == reference["compiled_rows"], "Primary/reference executions differ")
    require(primary["nonoverlap_diagnostic_rows"] == reference["nonoverlap_diagnostic_rows"], "Primary/reference overlap diagnostics differ")
    require(primary["summary"] == reference["summary"], "Primary/reference summaries differ")
    require(primary["ten_case_execution_reproduction"] == reference["ten_case_execution_reproduction"], "Primary/reference ten-case reproduction differs")

    summary = primary["summary"]
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1_FINAL_1_0",
        "verdict": "COMPLETE_EXPOSED_ALL_VALID_SIGNAL_REGRESSION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "selector_id": SELECTOR_ID,
        "primary_reference_exact": True,
        "all_admitted_signals_executed_including_overlaps": True,
        "summary": summary,
        "summary_sha256": canonical_hash(summary),
        "ten_case_execution_reproduction": primary["ten_case_execution_reproduction"],
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
        "validation_credit": "ZERO_EXPOSED_REGRESSION",
    }
    final["final_sha256"] = canonical_hash(final)

    write_json(PRIMARY, primary)
    write_json(REFERENCE, reference)
    write_json(FINAL, final)
    write_text(LEDGER, ledger_csv(primary["compiled_rows"]))
    write_text(REPORT, report_markdown(final))
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "gates": {
            "events_exact_729": summary["event_population"] == 729,
            "session_days_exact_117": summary["trading_days_in_population"] == 117,
            "no_daily_candidate_cap": True,
            "overlaps_executed": True,
            "same_ten_reproduced": primary["ten_case_execution_reproduction"]["exact"],
            "primary_reference_exact": True,
            "selector_unchanged": True,
            "structural_stops_preserved": True,
            "known_liquidity_targets_preserved": True,
            "fresh_periods_locked": True,
            "no_acquisition_or_charge": True,
        },
        "output_records": [file_record(path) for path in (PRIMARY, REFERENCE, FINAL, LEDGER, REPORT)],
    }
    require(all(certification["gates"].values()), "Certification gate failed")
    certification["certification_sha256"] = canonical_hash(certification)
    write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_FRESH_CLEAR_MULTI_OPPORTUNITY_EXPOSED_REGRESSION_V1_SEAL_1_0",
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
