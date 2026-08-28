#!/usr/bin/env python3
"""Reveal and seal outcomes for the ten frozen trade-placement examples."""

from __future__ import annotations

import argparse
import gzip
import hashlib
import html
import json
import math
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend" / "src"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT))

import run_gold_day_by_day_auction_confirmation_exposed_regression_v1 as source  # noqa: E402
from gold_coherent_auction_end_to_end_v1_common import load_stream  # noqa: E402
from gold_intel.analytics.auction_trade_placement_outcomes_v1 import (  # noqa: E402
    RISK_BUDGET_USD,
    RULESET,
    resolve_plan,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
    parse_dt,
)


PROTOCOL = ROOT / "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_REVEAL.md"
IMPLEMENTATION = (
    ROOT
    / "backend"
    / "src"
    / "gold_intel"
    / "analytics"
    / "auction_trade_placement_outcomes_v1.py"
)
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_trade_placement_outcomes_v1.py"
RUNNER = Path(__file__).resolve()

PLACEMENT_ROOT = ROOT / "research_artifacts" / "gold_auction_trade_placement_examples_v1"
PLACEMENT_PLANS = PLACEMENT_ROOT / "plans.primary.json"
PLACEMENT_REFERENCE = PLACEMENT_ROOT / "plans.reference.json"
PLACEMENT_CERTIFICATION = PLACEMENT_ROOT / "certification.json"
PLACEMENT_SEAL = PLACEMENT_ROOT / "seal.json"
PLACEMENT_CHARTS = PLACEMENT_ROOT / "charts"

OUT = PLACEMENT_ROOT / "outcome_reveal_v1"
FREEZE = OUT / "preoutcome_freeze.json"
PRIMARY = OUT / "outcomes.primary.json"
REFERENCE = OUT / "outcomes.reference.json"
FINAL = OUT / "final_results.json"
ATLAS = OUT / "revealed_outcome_atlas.html"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_REVEAL_REPORT.md"


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
        (json.dumps(payload, indent=2, sort_keys=True, ensure_ascii=False) + "\n").encode("utf-8"),
    )


def write_text(path: Path, payload: str) -> None:
    atomic_create(path, payload.encode("utf-8"))


def verify_placement_seal() -> dict[str, Any]:
    seal = load_json(PLACEMENT_SEAL)
    submitted = seal["seal_sha256"]
    require(
        canonical_hash({key: value for key, value in seal.items() if key != "seal_sha256"})
        == submitted,
        "Placement seal payload differs",
    )
    for record in seal["files"]:
        path = ROOT / record["path"]
        require(path.exists(), f"Placement artifact missing: {path}")
        require(path.stat().st_size == record["bytes"], f"Placement size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Placement hash differs: {path}")
    require(seal["outcomes_accessed"] is False, "Placement stage already accessed outcomes")
    return seal


def _source_records(aliases: set[str]) -> list[dict[str, Any]]:
    certification = load_json(source.JAN_CERTIFICATION)
    records: list[dict[str, Any]] = []
    cbr = {alias for alias in aliases if alias.startswith("CBR-")}
    found: set[str] = set()
    for row in certification["case_files"]:
        alias = str(row["case_alias"])
        if alias not in cbr:
            continue
        found.add(alias)
        records.extend(
            {
                "case_alias": alias,
                "side": side,
                "path": row[side]["path"],
                "bytes": int(row[side]["bytes"]),
                "sha256": row[side]["sha256"],
                "stream_sha256": row[side]["stream_sha256"],
            }
            for side in ("primary", "reference")
        )
    require(found == cbr, f"January source aliases missing: {sorted(cbr - found)}")
    cam = {alias for alias in aliases if alias.startswith("CAM-")}
    require(cam <= {"CAM-2022-064"}, f"Unexpected aggregated source aliases: {sorted(cam)}")
    if cam:
        records.extend(
            {
                "case_alias": "CAM-2022-064",
                "side": side,
                **file_record(path),
                "container_scan_policy": "PARSE_ONLY_MATCHED_CASE_ALIAS_LINE",
            }
            for side, path in (
                ("primary", source.MAR_PRIMARY_STREAM),
                ("reference", source.MAR_REFERENCE_STREAM),
            )
        )
    return records


def freeze() -> None:
    require(not FREEZE.exists(), f"Freeze exists: {FREEZE}")
    placement_seal = verify_placement_seal()
    primary = load_json(PLACEMENT_PLANS)
    reference = load_json(PLACEMENT_REFERENCE)
    require(primary["plans"] == reference["plans"], "Frozen placement plans differ")
    plans = primary["plans"]
    require(len(plans) == 10, "Expected ten frozen plans")
    aliases = {str(item["case_alias"]) for item in plans}
    require(len(aliases) == 10, "Expected ten distinct source cases")
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_REVEAL_FREEZE_1_0",
        "frozen_at": now(),
        "ruleset": RULESET,
        "plan_identities": [item["event_identity"] for item in plans],
        "plan_identities_sha256": canonical_hash([item["event_identity"] for item in plans]),
        "case_aliases": sorted(aliases),
        "resolution": {
            "structural_start": "FIRST_COMPLETE_M1_OPEN_AT_OR_AFTER_DECISION",
            "execution_latency_minutes": 1,
            "deadline": "12:00_AMERICA_NEW_YORK",
            "same_bar": "STOP_FIRST",
            "risk_budget_usd": RISK_BUDGET_USD,
            "spread_fallback_price": 0.20,
            "slippage_price": 0.05,
            "quantity": "FLOOR_50_DIVIDED_BY_DISPLAYED_ENTRY_STOP_DISTANCE_WHOLE_OUNCES",
        },
        "placement_seal_sha256": placement_seal["seal_sha256"],
        "governing_files": [
            file_record(PROTOCOL),
            file_record(IMPLEMENTATION),
            file_record(TESTS),
            file_record(RUNNER),
        ],
        "placement_files": [
            file_record(PLACEMENT_PLANS),
            file_record(PLACEMENT_REFERENCE),
            file_record(PLACEMENT_CERTIFICATION),
            file_record(PLACEMENT_SEAL),
        ],
        "source_records": _source_records(aliases),
        "outcomes_accessed": False,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json(FREEZE, payload)


def _load_targeted_streams(side: str, aliases: set[str]) -> dict[str, dict[str, Any]]:
    output: dict[str, dict[str, Any]] = {}
    certification = load_json(source.JAN_CERTIFICATION)
    for record in certification["case_files"]:
        alias = str(record["case_alias"])
        if alias not in aliases:
            continue
        item = record[side]
        stream = load_stream(ROOT / item["path"], str(item["sha256"]))
        require(str(stream["case_alias"]) == alias, f"January stream alias differs: {alias}")
        output[alias] = stream

    remaining = aliases - set(output)
    if remaining:
        require(remaining == {"CAM-2022-064"}, f"Unsupported targeted aliases: {sorted(remaining)}")
        path = source.MAR_PRIMARY_STREAM if side == "primary" else source.MAR_REFERENCE_STREAM
        tokens = ('"case_alias": "CAM-2022-064"', '"case_alias":"CAM-2022-064"')
        matched: dict[str, Any] | None = None
        with gzip.open(path, "rt", encoding="utf-8") as handle:
            for line in handle:
                if not any(token in line for token in tokens):
                    continue
                row = json.loads(line)
                submitted = str(row.pop("stream_sha256"))
                require(canonical_hash(row) == submitted, "CAM-2022-064 stream payload differs")
                row["stream_sha256"] = submitted
                require(str(row["case_alias"]) == "CAM-2022-064", "Targeted CAM alias differs")
                matched = row
                break
        require(matched is not None, "CAM-2022-064 targeted stream not found")
        output["CAM-2022-064"] = matched
    require(set(output) == aliases, "Targeted stream population differs")
    return output


def _side(side: str, plans: list[dict[str, Any]]) -> dict[str, Any]:
    aliases = {str(item["case_alias"]) for item in plans}
    streams = _load_targeted_streams(side, aliases)
    results: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        stream = streams[str(plan["case_alias"])]
        result = resolve_plan(plan, stream["timeframes"]["1m"])
        results.append(result)
        print(f"{side} outcome {index:02d}/10", flush=True)
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_SIDE_1_0",
        "side": side,
        "results": results,
        "results_sha256": canonical_hash(results),
    }
    return payload


def _maximum_drawdown(values: list[float]) -> float:
    equity = 0.0
    peak = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return drawdown


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    chronological = sorted(results, key=lambda item: (parse_dt(item["decision_at"]), item["event_identity"]))
    r_values = [float(item["execution"]["net_r50"]) for item in chronological]
    dollar_values = [float(item["execution"]["net_pnl_usd"]) for item in chronological]
    positive = sum(value for value in r_values if value > 0)
    negative = -sum(value for value in r_values if value < 0)
    return {
        "observations": len(results),
        "structural_resolutions": dict(Counter(item["structural"]["resolution"] for item in results)),
        "execution_resolutions": dict(Counter(item["execution"]["resolution"] for item in results)),
        "wins": sum(value > 0 for value in r_values),
        "losses": sum(value < 0 for value in r_values),
        "win_rate": sum(value > 0 for value in r_values) / len(r_values),
        "net_r50": sum(r_values),
        "net_pnl_usd": sum(dollar_values),
        "expectancy_r50": sum(r_values) / len(r_values),
        "profit_factor": positive / negative if negative > 0 else math.inf,
        "maximum_drawdown_r50": _maximum_drawdown(r_values),
        "average_mfe_r": sum(float(item["execution"]["mfe_r"]) for item in results) / len(results),
        "average_mae_r": sum(float(item["execution"]["mae_r"]) for item in results) / len(results),
        "same_bar_stop_first": sum(bool(item["execution"]["ambiguous_stop_first"]) for item in results),
    }


def _atlas(plans: list[dict[str, Any]], results: list[dict[str, Any]]) -> str:
    charts = sorted(PLACEMENT_CHARTS.glob("*.svg"), key=lambda path: int(path.name.split("_", 1)[0]))
    require(len(charts) == len(plans) == len(results), "Outcome atlas population differs")
    cards: list[str] = []
    for plan, result, chart in zip(plans, results, charts, strict=True):
        execution = result["execution"]
        structural = result["structural"]
        css = "win" if float(execution["net_r50"]) > 0 else "loss"
        cards.append(
            f"<section class='card {css}'>"
            f"<h2>{html.escape(plan['direction'])} · {html.escape(plan['context_family'])}</h2>"
            f"<p class='result'>Structural: {html.escape(structural['resolution'])} {structural['gross_r']:+.2f}R · "
            f"Execution: {html.escape(execution['resolution'])} {execution['net_r50']:+.2f}R / ${execution['net_pnl_usd']:+.2f}</p>"
            f"<p>{html.escape(plan['decision_at'])} · fill {execution['actual_fill']:.2f} · exit {execution['actual_exit']:.2f} · MFE {execution['mfe_r']:.2f}R · MAE {execution['mae_r']:.2f}R</p>"
            f"<img src='../charts/{html.escape(chart.name)}' alt='Frozen predecision trade plan'>"
            "</section>"
        )
    return """<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Revealed Gold Trade Placement Outcomes</title><style>
body{margin:0;background:#f1f5f9;color:#0f172a;font-family:Arial,sans-serif}main{max-width:1540px;margin:auto;padding:28px}.note{background:#fff;padding:14px;border-left:5px solid #7c3aed;margin:14px 0 24px}.card{background:#fff;border:2px solid #cbd5e1;border-radius:10px;padding:15px;margin-bottom:22px}.card.win{border-color:#16a34a}.card.loss{border-color:#dc2626}.card h2{margin:0 0 6px}.card p{margin:4px 0 10px;color:#475569}.card .result{font-weight:700;color:#0f172a}.card img{width:100%;height:auto;border:1px solid #e2e8f0}
</style></head><body><main><h1>Gold Auction Trade Placement Outcomes</h1><div class="note">The charts remain the frozen predecision views. Results were revealed afterward using M1 stop-first resolution and the unchanged absolute stop and target.</div>
""" + "\n".join(cards) + "\n</main></body></html>\n"


def _markdown(results: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    lines = [
        "# Gold Auction Trade Placement Examples V1 Outcome Reveal Report",
        "",
        "These ten observations are descriptive and do not validate an edge.",
        "",
        "| # | Date | Side | Structural | Gross R | Execution | Net R50 | Net USD |",
        "|---:|---|---|---|---:|---|---:|---:|",
    ]
    for index, item in enumerate(results, start=1):
        structural = item["structural"]
        execution = item["execution"]
        lines.append(
            f"| {index} | {item['decision_at'][:10]} | {item['direction']} | {structural['resolution']} | {structural['gross_r']:+.2f} | {execution['resolution']} | {execution['net_r50']:+.2f} | {execution['net_pnl_usd']:+.2f} |"
        )
    lines.extend(
        [
            "",
            f"- Net: **{summary['net_r50']:+.2f}R50 / ${summary['net_pnl_usd']:+.2f}**.",
            f"- Win rate: **{summary['win_rate']:.1%}**.",
            f"- Expectancy: **{summary['expectancy_r50']:+.2f}R50 per observation**.",
            f"- Profit factor: **{summary['profit_factor']:.2f}**.",
            f"- Maximum drawdown: **{summary['maximum_drawdown_r50']:.2f}R50**.",
            "",
        ]
    )
    return "\n".join(lines)


def reveal() -> None:
    require(FREEZE.exists(), "Run freeze before outcome access")
    frozen = load_json(FREEZE)
    require(
        canonical_hash({key: value for key, value in frozen.items() if key != "freeze_sha256"})
        == frozen["freeze_sha256"],
        "Outcome freeze differs",
    )
    for record in frozen["governing_files"] + frozen["placement_files"] + frozen["source_records"]:
        path = ROOT / record["path"]
        require(path.exists(), f"Frozen input missing: {path}")
        require(path.stat().st_size == record["bytes"], f"Frozen input size differs: {path}")
        require(sha256_file(path) == record["sha256"], f"Frozen input hash differs: {path}")
    verify_placement_seal()
    plans = load_json(PLACEMENT_PLANS)["plans"]
    require([item["event_identity"] for item in plans] == frozen["plan_identities"], "Plan population differs")

    primary = _side("primary", plans)
    reference = _side("reference", plans)
    require(primary["results"] == reference["results"], "Primary/reference outcomes differ")
    write_json(PRIMARY, primary)
    write_json(REFERENCE, reference)
    summary = aggregate(primary["results"])
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_FINAL_1_0",
        "verdict": "REVEALED_TEN_DESCRIPTIVE_OUTCOMES_NOT_EDGE_VALIDATION",
        "results": primary["results"],
        "summary": summary,
        "results_sha256": primary["results_sha256"],
    }
    final["final_sha256"] = canonical_hash(final)
    write_json(FINAL, final)
    write_text(ATLAS, _atlas(plans, primary["results"]))
    write_text(REPORT, _markdown(primary["results"], summary))
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "results_sha256": primary["results_sha256"],
        "primary_reference_exact": True,
        "opened_case_aliases": sorted({item["case_alias"] for item in primary["results"]}),
        "opened_cases": 10,
        "additional_cases_resolved": 0,
        "summary": summary,
        "atlas": file_record(ATLAS),
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_TRADE_PLACEMENT_EXAMPLES_V1_OUTCOME_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [
            file_record(FREEZE),
            file_record(PRIMARY),
            file_record(REFERENCE),
            file_record(FINAL),
            file_record(ATLAS),
            file_record(CERTIFICATION),
            file_record(REPORT),
        ],
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
                "atlas": ATLAS.relative_to(ROOT).as_posix(),
                "certification_sha256": certification["certification_sha256"],
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        ),
        flush=True,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("action", choices=("freeze", "reveal", "all"))
    args = parser.parse_args()
    if args.action in {"freeze", "all"}:
        freeze()
    if args.action in {"reveal", "all"}:
        reveal()


if __name__ == "__main__":
    main()
