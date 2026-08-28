#!/usr/bin/env python3
"""Freeze and seal the two-change Router V1-R1 mechanical correction."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))

import run_gold_auction_semantic_family_router_exposed_regression_v2 as seal_tools  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.auction_family_router_v1_r1 import (  # noqa: E402
    corrected_router_lifecycle,
)
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402


PROTOCOL = ROOT / "GOLD_AUCTION_FAMILY_ROUTER_V1_R1_MECHANICAL_CORRECTION.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_family_router_v1_r1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_family_router_v1_r1.py"
RUNNER = Path(__file__).resolve()

V1_ROOT = ROOT / "research_artifacts" / "gold_auction_family_router_exposed_regression_v1"
V1_RESULT = V1_ROOT / "final_result.json"
V1_SEAL = V1_ROOT / "final_seal.json"
V1_SEMANTIC_SHA256 = "6a5427449742fac3666c3a7db22c01eb041aaa74392b14abd4162990b0d39588"

SEMANTIC_R1_ROOT = ROOT / "research_artifacts" / "gold_auction_semantic_family_router_exposed_regression_v2_r1"
SEMANTIC_R1_RESULT = SEMANTIC_R1_ROOT / "final_result.json"
SEMANTIC_R1_SEAL = SEMANTIC_R1_ROOT / "final_seal.json"
SEMANTIC_R1_SHA256 = "e5f0d12d7256f855ca5e42d861cbe2aee0b645968f9df09a5dad814145f9f8c9"

OUT = ROOT / "research_artifacts" / "gold_auction_family_router_v1_r1_mechanical_correction"
FREEZE = OUT / "precalculation_freeze.json"
PRIMARY = OUT / "corrected.primary.json"
REFERENCE = OUT / "corrected.reference.json"
FINAL_RESULT = OUT / "final_result.json"
LEDGER = OUT / "daily_ledger.csv"
FINAL_SEAL = OUT / "final_seal.json"
REPORT = ROOT / "GOLD_AUCTION_FAMILY_ROUTER_V1_R1_MECHANICAL_CORRECTION_REPORT.md"

WIN_EPSILON = 1e-12


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
    path.write_text(
        json.dumps(payload, indent=2, sort_keys=True, allow_nan=False) + "\n",
        encoding="utf-8",
        newline="\n",
    )


def verify_sources() -> dict[str, Any]:
    v1 = seal_tools.verify_list_seal(
        V1_SEAL,
        semantic_path=V1_RESULT,
        semantic_hash=V1_SEMANTIC_SHA256,
    )
    semantic_r1 = seal_tools.verify_list_seal(
        SEMANTIC_R1_SEAL,
        semantic_path=SEMANTIC_R1_RESULT,
        semantic_hash=SEMANTIC_R1_SHA256,
    )
    return {
        "router_v1": {
            "result_sha256": V1_SEMANTIC_SHA256,
            "seal_sha256": v1["seal_sha256"],
            "file_sha256": sha256_file(V1_RESULT),
        },
        "semantic_v2_r1_diagnostic": {
            "result_sha256": SEMANTIC_R1_SHA256,
            "seal_sha256": semantic_r1["seal_sha256"],
            "file_sha256": sha256_file(SEMANTIC_R1_RESULT),
        },
    }


def synthetic_proof() -> dict[str, Any]:
    base = {
        "admitted": True,
        "disposition": "TARGET",
        "geometry": {"target_room_r": 2.0},
        "pre_overlay_result": {
            "executed": True,
            "resolution": "TARGET",
            "net_r50": 1.5,
            "net_usd": 75.0,
        },
        "effective_result": {
            "executed": True,
            "resolution": "BREAK_EVEN",
            "net_r50": 0.0,
            "net_usd": 0.0,
        },
    }
    continuation = corrected_router_lifecycle(
        {**base, "family": "CONTINUATION_WITH_ROOM"}
    )
    delayed_fail = corrected_router_lifecycle(
        {
            **base,
            "family": "RANGE_ROTATION",
            "geometry": {"target_room_r": 1.49},
        }
    )
    delayed_pass = corrected_router_lifecycle(
        {
            **base,
            "family": "STRUCTURAL_REPAIR",
            "geometry": {"target_room_r": 1.5},
        }
    )
    checks = {
        "overlay_removed": continuation["effective_result"]["net_r50"] == 1.5,
        "continuation_retained": continuation["admitted"] is True,
        "delayed_below_floor_rejected": delayed_fail["effective_result"] is None,
        "delayed_at_floor_retained": delayed_pass["effective_result"]["net_r50"] == 1.5,
        "no_overlay_in_all": all(
            row["break_even_overlay_used"] is False
            for row in (continuation, delayed_fail, delayed_pass)
        ),
    }
    require(all(checks.values()), f"Mechanical correction proof failed: {checks}")
    return {"checks": checks, "proof_sha256": canonical_hash(checks)}


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    for path in (PROTOCOL, IMPLEMENTATION, TESTS, RUNNER, V1_RESULT, V1_SEAL):
        require(path.is_file(), f"Required file absent: {path}")
    sources = verify_sources()
    rows = load_json(V1_RESULT)["rows"]
    require(len(rows) == 95, "Expected 95 sealed Router V1 rows")
    identities = [
        {
            "case_alias": row["case_alias"],
            "trading_date_utc": row["trading_date_utc"],
            "source_row_sha256": row["row_sha256"],
        }
        for row in rows
    ]
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_V1_R1_FREEZE_1_0",
        "sealed_at": now(),
        "status": "SEALED_BEFORE_MECHANICAL_CORRECTION",
        "files": [
            file_record(path)
            for path in (PROTOCOL, IMPLEMENTATION, TESTS, RUNNER, V1_RESULT, V1_SEAL)
        ],
        "sources": sources,
        "identities": identities,
        "population_sha256": canonical_hash(identities),
        "rules": {
            "effective_result": "SEALED_PRE_OVERLAY_RESULT",
            "break_even_overlay_used": False,
            "delayed_actual_fill_target_room_minimum_r": 1.5,
            "all_other_fields": "UNCHANGED",
        },
        "synthetic_proof": synthetic_proof(),
        "price_sources_opened": False,
        "fresh_dates_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_new_json(FREEZE, payload)
    print(json.dumps({"status": payload["status"], "rows": len(rows), "freeze_sha256": payload["freeze_sha256"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    require(FREEZE.is_file(), "Mechanical correction freeze absent")
    payload = load_json(FREEZE)
    submitted = payload.pop("freeze_sha256")
    require(canonical_hash(payload) == submitted, "Freeze payload differs")
    payload["freeze_sha256"] = submitted
    for record in payload["files"]:
        path = ROOT / record["path"]
        require(path.is_file(), f"Frozen file absent: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen hash differs: {path}")
    require(verify_sources() == payload["sources"], "Source seals differ")
    current = load_json(V1_RESULT)["rows"]
    identities = [
        {
            "case_alias": row["case_alias"],
            "trading_date_utc": row["trading_date_utc"],
            "source_row_sha256": row["row_sha256"],
        }
        for row in current
    ]
    require(identities == payload["identities"], "Frozen identities differ")
    return payload


def calculate(side: str, rows: list[dict[str, Any]]) -> dict[str, Any]:
    order = rows if side == "primary" else list(reversed(rows))
    output: list[dict[str, Any]] = []
    for source in order:
        corrected = corrected_router_lifecycle(source["family_router"])
        payload = {
            "case_alias": source["case_alias"],
            "trading_date_utc": source["trading_date_utc"],
            "source_row_sha256": source["row_sha256"],
            "source_router_disposition": source["family_router"]["disposition"],
            "source_router_effective_result": source["family_router"].get("effective_result"),
            "source_router_pre_overlay_result": source["family_router"].get("pre_overlay_result"),
            "corrected": corrected,
        }
        payload["row_sha256"] = canonical_hash(payload)
        output.append(payload)
    position = {row["case_alias"]: index for index, row in enumerate(rows)}
    output.sort(key=lambda row: position[row["case_alias"]])
    return {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_V1_R1_SIDE_1_0",
        "side": side,
        "rows": output,
        "rows_sha256": canonical_hash(output),
    }


def value(result: dict[str, Any] | None) -> float:
    return 0.0 if result is None or result.get("executed") is not True else float(result["net_r50"])


def metrics(rows: list[dict[str, Any]], key: str) -> dict[str, Any]:
    if key == "source_effective":
        results = [row["source_router_effective_result"] for row in rows]
    elif key == "source_pre_overlay":
        results = [row["source_router_pre_overlay_result"] for row in rows]
    else:
        results = [row["corrected"]["effective_result"] for row in rows]
    executed = [result for result in results if result is not None and result.get("executed")]
    values = [float(result["net_r50"]) for result in executed]
    wins = [item for item in values if item > WIN_EPSILON]
    losses = [item for item in values if item < -WIN_EPSILON]
    equity = peak = drawdown = 0.0
    for item in values:
        equity += item
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return {
        "trades": len(executed),
        "wins": len(wins),
        "losses": len(losses),
        "scratches": len(values) - len(wins) - len(losses),
        "win_rate": len(wins) / len(values) if values else None,
        "expectancy_r": sum(values) / len(values) if values else 0.0,
        "profit_factor": sum(wins) / abs(sum(losses)) if losses else None,
        "net_r": sum(values),
        "net_usd": sum(float(result["net_usd"]) for result in executed),
        "maximum_drawdown_r": drawdown,
    }


def comparison(rows: list[dict[str, Any]]) -> dict[str, Any]:
    source = metrics(rows, "source_effective")
    pre = metrics(rows, "source_pre_overlay")
    corrected = metrics(rows, "corrected")
    rejected = [
        row
        for row in rows
        if row["source_router_pre_overlay_result"] is not None
        and row["source_router_pre_overlay_result"].get("executed")
        and row["corrected"]["effective_result"] is None
    ]
    return {
        "router_v1": source,
        "pre_overlay": pre,
        "corrected": corrected,
        "overlay_removal_delta_r": pre["net_r"] - source["net_r"],
        "actual_fill_room_gate_delta_r": corrected["net_r"] - pre["net_r"],
        "total_delta_vs_router_v1_r": corrected["net_r"] - source["net_r"],
        "room_gate_rejected_count": len(rejected),
        "room_gate_rejected_rows": [
            {
                "trading_date_utc": row["trading_date_utc"],
                "case_alias": row["case_alias"],
                "family": row["corrected"]["family"],
                "actual_fill_target_room_r": row["corrected"]["actual_fill_target_room_r"],
                "pre_overlay_net_r": value(row["source_router_pre_overlay_result"]),
            }
            for row in rejected
        ],
    }


def write_ledger(rows: list[dict[str, Any]]) -> None:
    require(not LEDGER.exists(), f"Append-only ledger exists: {LEDGER}")
    with LEDGER.open("x", encoding="utf-8", newline="") as handle:
        fields = [
            "trading_date_utc",
            "case_alias",
            "family",
            "delayed",
            "actual_fill_target_room_r",
            "source_effective_r",
            "pre_overlay_r",
            "corrected_r",
            "corrected_disposition",
            "row_sha256",
        ]
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        for row in rows:
            corrected = row["corrected"]
            writer.writerow(
                {
                    "trading_date_utc": row["trading_date_utc"],
                    "case_alias": row["case_alias"],
                    "family": corrected["family"],
                    "delayed": corrected["delayed"],
                    "actual_fill_target_room_r": corrected["actual_fill_target_room_r"],
                    "source_effective_r": value(row["source_router_effective_result"]),
                    "pre_overlay_r": value(row["source_router_pre_overlay_result"]),
                    "corrected_r": value(corrected["effective_result"]),
                    "corrected_disposition": corrected["disposition"],
                    "row_sha256": row["row_sha256"],
                }
            )


def markdown(result: dict[str, Any]) -> str:
    lines = [
        "# Gold Auction Family Router V1-R1 Mechanical Correction — Result",
        "",
        f"Verdict: `{result['verdict']}`",
        "",
        "This is a reproducible exposed-data implementation correction with zero validation credit.",
        "",
        "| Period | Router V1 R | Before overlay R | Corrected trades | Corrected R | Win % | PF | DD R |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for key in ("JANUARY", "FEBRUARY_TO_DATE", "MARCH", "APRIL", "MAY", "COMBINED"):
        block = result["periods"][key]
        corrected = block["corrected"]
        lines.append(
            f"| {key} | {block['router_v1']['net_r']:+.4f} | {block['pre_overlay']['net_r']:+.4f} | {corrected['trades']} | {corrected['net_r']:+.4f} | {100 * float(corrected['win_rate'] or 0):.2f} | {corrected['profit_factor']} | {corrected['maximum_drawdown_r']:.4f} |"
        )
    combined = result["periods"]["COMBINED"]
    lines.extend(
        [
            "",
            "## Exact attribution",
            "",
            f"- Removing the harmful overlay: {combined['overlay_removal_delta_r']:+.6f}R.",
            f"- Enforcing delayed actual-fill room: {combined['actual_fill_room_gate_delta_r']:+.6f}R.",
            f"- Total correction versus Router V1: {combined['total_delta_vs_router_v1_r']:+.6f}R.",
            f"- Corrected exposed result: {combined['corrected']['net_r']:+.6f}R / ${combined['corrected']['net_usd']:+.2f}.",
            f"- Delayed trades rejected by the room gate: {combined['room_gate_rejected_count']}.",
            "",
            "No new market data or fresh date was opened. This result proves reproduction only; forward evidence is still required.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    for path in (PRIMARY, REFERENCE, FINAL_RESULT, LEDGER, FINAL_SEAL, REPORT):
        require(not path.exists(), f"One-shot output exists: {path}")
    source_rows = load_json(V1_RESULT)["rows"]
    primary = calculate("primary", source_rows)
    write_new_json(PRIMARY, primary)
    reference = calculate("reference", source_rows)
    write_new_json(REFERENCE, reference)
    require(primary["rows"] == reference["rows"], "Primary/reference rows differ")
    rows = primary["rows"]
    filters = {
        "JANUARY": lambda value: value.startswith("2022-01"),
        "FEBRUARY_TO_DATE": lambda value: value.startswith("2022-02"),
        "MARCH": lambda value: value.startswith("2022-03"),
        "APRIL": lambda value: value.startswith("2022-04"),
        "MAY": lambda value: value.startswith("2022-05"),
        "COMBINED": lambda value: True,
    }
    periods = {
        key: comparison(
            [row for row in rows if predicate(str(row["trading_date_utc"]))]
        )
        for key, predicate in filters.items()
    }
    write_ledger(rows)
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_V1_R1_RESULT_1_0",
        "completed_at": now(),
        "verdict": "PASS_MECHANICAL_CORRECTION_REPRODUCTION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "population_sha256": frozen["population_sha256"],
        "primary_reference_exact": True,
        "primary_rows_sha256": primary["rows_sha256"],
        "reference_rows_sha256": reference["rows_sha256"],
        "periods": periods,
        "dispositions": dict(sorted(Counter(row["corrected"]["disposition"] for row in rows).items())),
        "rows": rows,
        "price_sources_opened": False,
        "fresh_dates_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    final["result_sha256"] = canonical_hash(final)
    write_new_json(FINAL_RESULT, final)
    REPORT.write_text(markdown(final), encoding="utf-8", newline="\n")
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_FAMILY_ROUTER_V1_R1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "files": [
            file_record(path)
            for path in (
                PROTOCOL,
                FREEZE,
                IMPLEMENTATION,
                TESTS,
                RUNNER,
                PRIMARY,
                REFERENCE,
                FINAL_RESULT,
                LEDGER,
                REPORT,
            )
        ],
        "sources_untouched": verify_sources() == frozen["sources"],
        "primary_reference_exact": True,
        "fresh_dates_opened": False,
        "retuning_performed": False,
        "paid_acquisition": False,
    }
    seal["seal_sha256"] = canonical_hash(seal)
    write_new_json(FINAL_SEAL, seal)
    print(
        json.dumps(
            {
                "verdict": final["verdict"],
                "combined": periods["COMBINED"],
                "dispositions": final["dispositions"],
                "result_sha256": final["result_sha256"],
            },
            indent=2,
            sort_keys=True,
        )
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("freeze", "run"))
    args = parser.parse_args()
    if args.phase == "freeze":
        freeze()
    else:
        run()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

