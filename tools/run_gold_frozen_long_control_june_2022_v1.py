#!/usr/bin/env python3
"""Run the exact preserved LONG control once on calendar June 2022."""

from __future__ import annotations

import argparse
import csv
import gc
import json
import math
import os
import sys
from collections import Counter
from datetime import UTC, date, datetime, time, timedelta
from pathlib import Path
from typing import Any, Callable
from zoneinfo import ZoneInfo


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import materialize_gold_annotated_replay_v3 as replay  # noqa: E402
import run_gold_auction_family_router_exposed_regression_v1 as router  # noqa: E402
import run_gold_auction_family_router_v1_r1_mechanical_correction as correction_runner  # noqa: E402
import run_gold_coherent_auction_consecutive_months_mar_may_2022_v1 as source_month  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1_r1 import (  # noqa: E402
    corrected_router_lifecycle,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402
from run_gold_coherent_auction_frozen_translator_unseen_block_v1 import (  # noqa: E402
    infer_streams,
)


CONTRACT = ROOT / "GOLD_FROZEN_LONG_CONTROL_JUNE_2022_ROBUSTNESS_TEST_V1.md"
RUNNER = Path(__file__).resolve()
TRANSLATOR = (
    ROOT
    / "research_artifacts"
    / "gold_coherent_auction_end_to_end_same_month_v1"
    / "translator.json"
)
CONTROL_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_auction_family_router_v1_r1_mechanical_correction"
    / "final_result.json"
)
CONTROL_SEAL = CONTROL_RESULT.with_name("final_seal.json")
PRESERVATION_RESULT = (
    ROOT
    / "research_artifacts"
    / "gold_long_multi_opportunity_auction_v1"
    / "final_result.json"
)
PRESERVATION_SEAL = PRESERVATION_RESULT.with_name("final_seal_r2.json")

OUT = ROOT / "research_artifacts" / "gold_frozen_long_control_june_2022_v1"
FREEZE = OUT / "prevalue_freeze.json"
STATUS = OUT / "status.json"
PRIMARY_STREAMS = OUT / "june_streams.primary.jsonl.gz"
REFERENCE_STREAMS = OUT / "june_streams.reference.jsonl.gz"
PRIMARY_RESULT = OUT / "june_result.primary.json"
REFERENCE_RESULT = OUT / "june_result.reference.json"
FINAL_RESULT = OUT / "final_result.json"
LEDGER = OUT / "daily_ledger.csv"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_FROZEN_LONG_CONTROL_JUNE_2022_ROBUSTNESS_TEST_V1_REPORT.md"

START = date(2022, 6, 1)
END_EXCLUSIVE = date(2022, 7, 1)
LONDON = ZoneInfo("Europe/London")
NEW_YORK = ZoneInfo("America/New_York")
RISK_USD = 50.0
STARTING_EQUITY_USD = 10_000.0
WIN_EPSILON = 1e-12
TRANSLATOR_SHA256 = "c95e200194bece77ed435741202d1bacd4f267ab0f1d1ed7803dd9d4ebd30841"


def now() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def file_record(path: Path) -> dict[str, Any]:
    return {
        "path": path.relative_to(ROOT).as_posix(),
        "bytes": path.stat().st_size,
        "sha256": sha256_file(path),
    }


def write_new_json(path: Path, payload: dict[str, Any]) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n")
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_new_text(path: Path, value: str) -> None:
    require(not path.exists(), f"Append-only output exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    require(not temporary.exists(), f"Temporary output exists: {temporary}")
    with temporary.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(value)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temporary, path)


def write_status(phase: str, **extra: Any) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    payload = {"phase": phase, "updated_at": now(), **extra}
    temporary = STATUS.with_suffix(".json.tmp")
    temporary.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )
    os.replace(temporary, STATUS)


def canonical_dates() -> list[date]:
    days: list[date] = []
    current = START
    while current < END_EXCLUSIVE:
        if current.weekday() < 5:
            days.append(current)
        current += timedelta(days=1)
    require(len(days) == 22, "Expected 22 June 2022 weekdays")
    return days


def verify_listed_seal(path: Path) -> dict[str, Any]:
    seal = load_json(path)
    for record in seal.get("files", []):
        item = ROOT / record["path"]
        require(item.is_file(), f"Sealed predecessor file absent: {item}")
        require(item.stat().st_size == int(record["bytes"]), f"Sealed size differs: {item}")
        require(sha256_file(item) == record["sha256"], f"Sealed hash differs: {item}")
    return seal


def verify_static_inputs() -> dict[str, Any]:
    for path in (CONTRACT, RUNNER, TRANSLATOR, CONTROL_RESULT, CONTROL_SEAL, PRESERVATION_RESULT, PRESERVATION_SEAL):
        require(path.is_file(), f"Required input absent: {path}")
    require(sha256_file(TRANSLATOR) == TRANSLATOR_SHA256, "Frozen translator differs")
    for relative, expected in source_month.SOURCE_HASHES.items():
        path = ROOT / relative
        require(path.is_file(), f"Casebook source absent: {relative}")
        require(sha256_file(path) == expected, f"Casebook source differs: {relative}")

    control_seal = verify_listed_seal(CONTROL_SEAL)
    require(
        control_seal["verdict"] == "PASS_MECHANICAL_CORRECTION_REPRODUCTION_ZERO_VALIDATION_CREDIT",
        "Frozen LONG-control predecessor verdict differs",
    )
    preservation = load_json(PRESERVATION_SEAL)
    require(
        preservation["verdict"] == "REJECT_ADDITIONS_PRESERVE_FROZEN_LONG_CONTROL",
        "LONG-control preservation verdict differs",
    )
    require(
        sha256_file(PRESERVATION_RESULT) == preservation["final_result"]["sha256"],
        "Preserved LONG-control result differs",
    )
    require(correction_runner.verify_sources(), "Family-router source seals failed")
    return {
        "control_seal": file_record(CONTROL_SEAL),
        "control_result": file_record(CONTROL_RESULT),
        "preservation_seal": file_record(PRESERVATION_SEAL),
        "preservation_result": file_record(PRESERVATION_RESULT),
        "translator": file_record(TRANSLATOR),
        "casebook_sources": [
            file_record(ROOT / relative) for relative in source_month.SOURCE_HASHES
        ],
    }


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    lineage = verify_static_inputs()
    preserved = load_json(PRESERVATION_RESULT)
    control_metrics = preserved["metrics"]["FROZEN_LONG_CONTROL"]
    dates = [day.isoformat() for day in canonical_dates()]
    synthetic = {
        "family_router": router.synthetic_proof(),
        "mechanical_correction": correction_runner.synthetic_proof(),
    }
    payload: dict[str, Any] = {
        "version": "GOLD_FROZEN_LONG_CONTROL_JUNE_2022_V1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_JUNE_2022_VALUE_OPEN",
        "contract": file_record(CONTRACT),
        "runner": file_record(RUNNER),
        "lineage": lineage,
        "preserved_control_metrics": control_metrics,
        "dates": dates,
        "population_sha256": canonical_hash(dates),
        "policy": {
            "name": "FROZEN_LONG_CONTROL",
            "direction": "LONG_ONLY",
            "risk_usd": RISK_USD,
            "starting_equity_usd": STARTING_EQUITY_USD,
            "maximum_decisions_per_day": 1,
            "multi_opportunity_enabled": False,
            "new_structural_management_enabled": False,
            "router": "GOLD_AUCTION_FAMILY_ROUTER_V1_R1",
        },
        "pass_gates": {
            "net_r_gt_zero": 0.0,
            "stressed_1p5x_cost_net_r_gt_zero": 0.0,
            "profit_factor_gte": 1.10,
            "primary_reference_exact": True,
        },
        "synthetic_proof": synthetic,
        "june_values_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    write_status("FROZEN", completed_days=0, total_days=len(dates))
    print(json.dumps({"status": payload["status"], "dates": len(dates), "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Prevalue freeze is absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Prevalue freeze differs")
    payload["freeze_sha256"] = submitted
    require(payload["dates"] == [day.isoformat() for day in canonical_dates()], "June population differs")
    current = verify_static_inputs()
    require(current == payload["lineage"], "Frozen lineage differs")
    require(file_record(CONTRACT) == payload["contract"], "Contract differs after freeze")
    require(file_record(RUNNER) == payload["runner"], "Runner differs after freeze")
    return payload


def utc_bounds(day: date, zone: ZoneInfo) -> tuple[datetime, datetime]:
    opened = datetime.combine(day, time(8, 0), tzinfo=zone).astimezone(UTC)
    return opened, opened + timedelta(hours=4)


def session_count(rows: list[dict[str, Any]], day: date, zone: ZoneInfo) -> int:
    start, end = utc_bounds(day, zone)
    return sum(start <= replay.parse_time(row["close_at"]) < end for row in rows)


def cases_from_prices(prices: dict[str, list[dict[str, Any]]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    m1 = prices.get("1m", [])
    cases: list[dict[str, Any]] = []
    coverage: list[dict[str, Any]] = []
    for sequence, day in enumerate(canonical_dates(), start=1):
        start = datetime.combine(day, time.min, tzinfo=UTC)
        end = start + timedelta(days=1)
        observed = sum(start <= replay.parse_time(row["close_at"]) < end for row in m1)
        london = session_count(m1, day, LONDON)
        new_york = session_count(m1, day, NEW_YORK)
        require(observed > 0, f"No M1 path for {day}")
        require(london >= 216, f"London coverage below 90% for {day}: {london}")
        require(new_york >= 216, f"New York coverage below 90% for {day}: {new_york}")
        alias = f"JUN-2022-{sequence:03d}"
        identity = canonical_hash(
            {"alias": alias, "date": day.isoformat(), "start": replay.iso(start), "end": replay.iso(end)}
        )
        cases.append(
            {
                "case_alias": alias,
                "mode_sequence": sequence,
                "trading_date_utc": day.isoformat(),
                "start_inclusive": replay.iso(start),
                "end_exclusive": replay.iso(end),
                "observed_m1_minutes": observed,
                "minute_identity_sha256": identity,
            }
        )
        coverage.append(
            {
                "case_alias": alias,
                "trading_date_utc": day.isoformat(),
                "observed_m1_closes": observed,
                "london_m1_closes": london,
                "new_york_m1_closes": new_york,
            }
        )
    return cases, coverage


def build_streams(
    loader: Callable[[datetime], dict[str, list[dict[str, Any]]]],
) -> tuple[dict[str, dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    prices = loader(datetime(2022, 7, 1, tzinfo=UTC))
    cases, coverage = cases_from_prices(prices)
    contexts = replay.build_contexts()
    streams: dict[str, dict[str, Any]] = {}
    lineage: list[dict[str, Any]] = []
    for case in cases:
        stream = replay.timeline_for_case(case, prices, contexts)
        alias = str(case["case_alias"])
        streams[alias] = stream
        lineage.append(
            {
                "case_alias": alias,
                "stream_sha256": stream["stream_sha256"],
                "minute_identity_sha256": case["minute_identity_sha256"],
            }
        )
    return streams, lineage, coverage


def apply_policy(
    *, side: str, base_rows: list[dict[str, Any]], streams: dict[str, dict[str, Any]]
) -> dict[str, Any]:
    order = base_rows if side == "primary" else list(reversed(base_rows))
    output: list[dict[str, Any]] = []
    for index, control in enumerate(order, start=1):
        alias = str(control["case_alias"])
        stream = streams[alias]
        lifecycle = router.family_lifecycle(control=control, stream=stream)
        corrected = corrected_router_lifecycle(lifecycle)
        result = corrected.get("effective_result")
        classification = lifecycle.get("classification")
        if result is not None and result.get("executed"):
            require(classification is not None, f"Executed trade lacks classification: {alias}")
            require(classification["direction"] == "LONG", f"Non-LONG trade entered: {alias}")
        row = {
            "case_alias": alias,
            "trading_date_utc": control["trading_date_utc"],
            "base_row_sha256": control["row_sha256"],
            "signal_at": control.get("signal_at"),
            "signal_probability": control.get("signal_probability"),
            "base_geometry": control.get("geometry"),
            "base_classification": control.get("classification"),
            "family_router": lifecycle,
            "corrected": corrected,
        }
        row["row_sha256"] = canonical_hash(row)
        output.append(row)
        write_status(
            f"{side.upper()}_POLICY",
            completed_days=index,
            total_days=len(order),
            current_date=control["trading_date_utc"],
        )
        print(f"{side} policy {index:02d}/{len(order):02d} {control['trading_date_utc']}", flush=True)
    positions = {alias: position for position, alias in enumerate(sorted(streams))}
    output.sort(key=lambda row: positions[row["case_alias"]])
    return {
        "version": "GOLD_FROZEN_LONG_CONTROL_JUNE_2022_V1_SIDE_1_0",
        "side": side,
        "rows": output,
        "rows_sha256": canonical_hash(output),
    }


def metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    executed = [
        row["corrected"]["effective_result"]
        for row in rows
        if row["corrected"].get("effective_result") is not None
        and row["corrected"]["effective_result"].get("executed")
    ]
    values = [float(result["net_r50"]) for result in executed]
    wins = [value for value in values if value > WIN_EPSILON]
    losses = [value for value in values if value < -WIN_EPSILON]
    equity = peak = drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    positive = sum(wins)
    negative = abs(sum(losses))
    profit_factor = positive / negative if negative else None
    sessions = Counter(
        row["family_router"].get("session")
        for row in rows
        if row["corrected"].get("effective_result") is not None
    )
    families = Counter(
        row["corrected"].get("family")
        for row in rows
        if row["corrected"].get("effective_result") is not None
    )
    return {
        "days": len(rows),
        "signal_days": sum(row.get("signal_at") is not None for row in rows),
        "trades": len(executed),
        "no_trade_days": len(rows) - len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "net_r": sum(values),
        "net_usd": sum(float(result["net_usd"]) for result in executed),
        "account_return_pct": 100.0 * sum(float(result["net_usd"]) for result in executed) / STARTING_EQUITY_USD,
        "expectancy_r": sum(values) / len(values) if values else 0.0,
        "profit_factor": profit_factor,
        "profit_factor_infinite": bool(wins and not losses),
        "maximum_drawdown_r": drawdown,
        "maximum_drawdown_usd": drawdown * RISK_USD,
        "stressed_1p5x_cost_net_r": sum(
            float(result["stressed_1_5x_cost_r50"]) for result in executed
        ),
        "session_counts": {str(key): value for key, value in sorted(sessions.items(), key=lambda item: str(item[0]))},
        "family_counts": {str(key): value for key, value in sorted(families.items(), key=lambda item: str(item[0]))},
    }


def daily_ledger(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    equity = STARTING_EQUITY_USD
    output: list[dict[str, Any]] = []
    for row in rows:
        corrected = row["corrected"]
        result = corrected.get("effective_result")
        net_r = 0.0 if result is None else float(result["net_r50"])
        net_usd = 0.0 if result is None else float(result["net_usd"])
        equity += net_usd
        output.append(
            {
                "trading_date_utc": row["trading_date_utc"],
                "case_alias": row["case_alias"],
                "signal_at": row.get("signal_at"),
                "session": row["family_router"].get("session"),
                "family": corrected.get("family"),
                "disposition": corrected["disposition"],
                "executed": result is not None,
                "net_r": net_r,
                "net_usd": net_usd,
                "account_equity_usd": equity,
                "row_sha256": row["row_sha256"],
            }
        )
    return output


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not LEDGER.exists(), f"Append-only ledger exists: {LEDGER}")
    fields = list(rows[0])
    with LEDGER.open("x", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def markdown(result: dict[str, Any]) -> str:
    m = result["metrics"]
    pf = "INF" if m["profit_factor_infinite"] else ("N/A" if m["profit_factor"] is None else f"{m['profit_factor']:.3f}")
    lines = [
        "# Gold Frozen LONG Control — June 2022 Robustness Test V1 Report",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This applied only the preserved frozen LONG control. The rejected multi-opportunity and structural-management additions were not used.",
        "",
        "| Days | Signals | Trades | Wins | Losses | Scratches | Win rate | Net R | Net USD | Expectancy R | PF | Max DD R | 1.5x-cost R |",
        "|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|",
        f"| {m['days']} | {m['signal_days']} | {m['trades']} | {m['wins']} | {m['losses']} | {m['scratches']} | {100 * float(m['win_rate'] or 0):.2f}% | {m['net_r']:+.4f} | {m['net_usd']:+.2f} | {m['expectancy_r']:+.4f} | {pf} | {m['maximum_drawdown_r']:.4f} | {m['stressed_1p5x_cost_net_r']:+.4f} |",
        "",
        "## Daily ledger",
        "",
        "| Date | Session | Signal | Family | Disposition | Net R | Equity USD |",
        "|---|---|---|---|---|---:|---:|",
    ]
    for row in result["daily_ledger"]:
        lines.append(
            f"| {row['trading_date_utc']} | {row['session'] or 'NONE'} | {row['signal_at'] or 'NONE'} | {row['family'] or 'NONE'} | {row['disposition']} | {row['net_r']:+.4f} | {row['account_equity_usd']:.2f} |"
        )
    lines.extend(
        [
            "",
            "June 2022 is a single exposed historical robustness month. No fitting, retuning, additional opportunity, SHORT test or alternative management was performed.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY_STREAMS, REFERENCE_STREAMS, PRIMARY_RESULT, REFERENCE_RESULT, FINAL_RESULT, LEDGER, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    translator = load_json(TRANSLATOR)
    require(translator["status"] == "PASS_PREPATH_TRANSLATOR_FREEZE", "Translator status differs")

    write_status("PRIMARY_STREAMS", completed_days=0, total_days=22)
    print("building primary June streams", flush=True)
    primary_streams, primary_lineage, primary_coverage = build_streams(source_month.load_prices_primary)
    source_month.write_stream_bundle(PRIMARY_STREAMS, primary_streams)
    primary_base = infer_streams(
        streams=primary_streams,
        lineage=primary_lineage,
        translator=translator,
        side="primary",
        include_validation_metadata=False,
    )
    primary = apply_policy(side="primary", base_rows=primary_base["rows"], streams=primary_streams)
    del primary_streams, primary_lineage, primary_base
    gc.collect()
    write_new_json(PRIMARY_RESULT, primary)

    write_status("REFERENCE_STREAMS", completed_days=0, total_days=22)
    print("building reference June streams", flush=True)
    reference_streams, reference_lineage, reference_coverage = build_streams(source_month.load_prices_reference)
    source_month.write_stream_bundle(REFERENCE_STREAMS, reference_streams)
    reference_base = infer_streams(
        streams=reference_streams,
        lineage=reference_lineage,
        translator=translator,
        side="reference",
        include_validation_metadata=False,
    )
    reference = apply_policy(side="reference", base_rows=reference_base["rows"], streams=reference_streams)
    del reference_streams, reference_lineage, reference_base
    gc.collect()
    write_new_json(REFERENCE_RESULT, reference)

    require(primary_coverage == reference_coverage, "Primary/reference coverage differs")
    require(primary["rows"] == reference["rows"], "Primary/reference policy rows differ")
    require(primary["rows_sha256"] == reference["rows_sha256"], "Primary/reference checksums differ")
    require(sha256_file(PRIMARY_STREAMS) == sha256_file(REFERENCE_STREAMS), "Stream bytes differ")
    require(
        [row["trading_date_utc"] for row in primary["rows"]] == frozen["dates"],
        "June result population differs",
    )

    ledger = daily_ledger(primary["rows"])
    summary = metrics(primary["rows"])
    pf_pass = summary["profit_factor_infinite"] or (
        summary["profit_factor"] is not None and summary["profit_factor"] >= 1.10
    )
    gates = {
        "net_r_gt_zero": summary["net_r"] > 0,
        "stressed_1p5x_cost_net_r_gt_zero": summary["stressed_1p5x_cost_net_r"] > 0,
        "profit_factor_gte_1p10": pf_pass,
        "primary_reference_exact": True,
    }
    verdict = (
        "PASS_JUNE_2022_EXPOSED_ROBUSTNESS"
        if all(gates.values())
        else "FAIL_JUNE_2022_EXPOSED_ROBUSTNESS"
    )
    result: dict[str, Any] = {
        "version": "GOLD_FROZEN_LONG_CONTROL_JUNE_2022_V1_RESULT_1_0",
        "completed_at": now(),
        "verdict": verdict,
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "primary_reference_exact": True,
        "stream_bytes_exact": True,
        "coverage": primary_coverage,
        "metrics": summary,
        "pass_gates": gates,
        "daily_ledger": ledger,
        "rows_sha256": primary["rows_sha256"],
        "rows": primary["rows"],
        "multi_opportunity_enabled": False,
        "new_structural_management_enabled": False,
        "short_branch_opened": False,
        "july_2022_opened": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    result["result_sha256"] = canonical_hash(result)
    write_new_json(FINAL_RESULT, result)
    write_ledger(ledger)
    write_new_text(REPORT, markdown(result))
    seal: dict[str, Any] = {
        "version": "GOLD_FROZEN_LONG_CONTROL_JUNE_2022_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": verdict,
        "files": [
            file_record(path)
            for path in (
                CONTRACT,
                RUNNER,
                FREEZE,
                PRIMARY_STREAMS,
                REFERENCE_STREAMS,
                PRIMARY_RESULT,
                REFERENCE_RESULT,
                FINAL_RESULT,
                LEDGER,
                REPORT,
            )
        ],
        "primary_reference_exact": True,
        "policy_changed": False,
        "multi_opportunity_enabled": False,
        "new_structural_management_enabled": False,
        "short_branch_opened": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(FINAL_SEAL, seal)
    write_status("COMPLETE", completed_days=22, total_days=22, verdict=verdict, sealed=True)
    print(json.dumps({"verdict": verdict, "metrics": summary, "pass_gates": gates}, indent=2, sort_keys=True))


def status() -> None:
    if STATUS.is_file():
        print(STATUS.read_text(encoding="utf-8"))
    else:
        print(json.dumps({"phase": "NOT_STARTED"}, indent=2))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run", "status"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    elif args.phase == "run":
        run()
    else:
        status()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
