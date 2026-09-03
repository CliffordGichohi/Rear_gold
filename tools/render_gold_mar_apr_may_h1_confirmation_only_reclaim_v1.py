#!/usr/bin/env python3
"""Render separate March, April and May confirmation-only charts."""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash, parse_dt  # noqa: E402

BASE = ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1"
SOURCE_TEMPLATE = (
    ROOT
    / "research_artifacts/gold_february_h1_confirmation_only_reclaim_v1"
    / "february-h1-confirmation-only-continuous.template.html"
)
MONTHS = (
    ("march_2022", "March 2022", "March"),
    ("april_2022", "April 2022", "April"),
    ("may_2022", "May 2022", "May"),
)


def sec(value: str) -> int:
    return int(parse_dt(value).timestamp())


def duration_minutes(start: str, end: str) -> int:
    return max(0, round((parse_dt(end) - parse_dt(start)).total_seconds() / 60))


def compact_trade(row: Mapping[str, Any], number: int) -> dict[str, Any]:
    entry = float(row["entry_price"])
    stop = float(row["stop"])
    target = float(row["target"])
    outcome = str(row["outcome"])
    route = str(row["route"])
    return {
        "number": number,
        "planIdentity": str(row["trade_identity"]),
        "sampleId": str(row["trade_identity"]),
        "decision": sec(str(row["entry_at"])),
        "resolution": sec(str(row["resolution_at"])),
        "resolutionKnown": sec(str(row["resolution_at"])),
        "direction": str(row["direction"]),
        "family": "Reclaim" if route.startswith("RECLAIM") else "Initial confirmation",
        "h1State": str(row["evidence_segment"]),
        "setupFamily": route,
        "entry": round(entry, 4),
        "stop": round(stop, 4),
        "target": round(target, 4),
        "targetTimeframe": "H1",
        "targetRole": "PRE_EXISTING_OPPOSING_H1_SWING",
        "disposition": "MONTH_END_MARK" if outcome == "TIME_EXIT" else outcome,
        "grossR": round(float(row["net_r"]), 6),
        "targetR": round(abs(target - entry) / abs(entry - stop), 6),
        "durationMinutes": duration_minutes(str(row["entry_at"]), str(row["resolution_at"])),
        "ambiguous": outcome == "STOP_FIRST_AMBIGUOUS",
        "route": route,
    }


def month_template(source: str, key: str, label: str, month_name: str) -> str:
    return (
        source
        .replace("gold-february-h1-confirmation-only-v1", f"gold-{key.replace('_', '-')}-h1-confirmation-only-v1")
        .replace("February 2022", label)
        .replace("Full February", f"Full {month_name}")
        .replace("February trade ledger", f"{label} trade ledger")
        .replace("continuous February chart", f"continuous {month_name} chart")
        .replace("February chart", f"{month_name} chart")
        .replace("February timeline", f"{month_name} timeline")
        .replace("February 2022 continuous", f"{label} continuous")
    )


def render_one(key: str, label: str, month_name: str) -> dict[str, Any]:
    out = BASE / key
    result_path = out / "result.json"
    chart_data_path = out / "chart_data.json"
    report_path = out / "report.md"
    template_path = out / f"{key.replace('_', '-')}-confirmation-only.template.html"
    html_path = out / f"gold-{key.replace('_', '-')}-h1-confirmation-only-continuous-chart.html"
    manifest_path = out / "chart_manifest.json"
    for path in (SOURCE_TEMPLATE, result_path, chart_data_path, report_path):
        require(path.is_file(), f"Required rendering input absent: {path}")
    result = json.loads(result_path.read_text(encoding="utf-8"))
    source_data = json.loads(chart_data_path.read_text(encoding="utf-8"))
    require(result["primary_reference_exact"] is True, f"{label} result did not reproduce")
    executed = [row for row in result["case_ledger"] if row["executed"]]
    require(len(executed) == int(result["v2_metrics"]["executed_trades"]), f"{label} executed count differs")
    plans = [compact_trade(row, index) for index, row in enumerate(executed, start=1)]
    metrics = result["v2_metrics"]
    summary = {
        "plans": len(plans),
        "target_hits": sum(plan["disposition"] == "TARGET" for plan in plans),
        "stops": sum(plan["disposition"] == "STOP" for plan in plans),
        "stop_first_ambiguous": sum(plan["disposition"] == "STOP_FIRST_AMBIGUOUS" for plan in plans),
        "month_end_marks": sum(plan["disposition"] == "MONTH_END_MARK" for plan in plans),
        "resolved_hit_rate": float(metrics["trade_win_rate"]),
        "gross_r_sum": float(metrics["net_r"]),
        "profit_factor": float(metrics["profit_factor"]),
        "max_drawdown_r": float(metrics["maximum_drawdown_r"]),
    }
    dataset: dict[str, Any] = {
        "version": f"GOLD_{key.upper()}_H1_CONFIRMATION_ONLY_CONTINUOUS_CHART_V1",
        "period": result["period"],
        "summary": summary,
        "bars": source_data["bars"],
        "plans": plans,
        "guards": {
            "continuous_month_not_cases": True,
            "unchanged_january_v2_policy": True,
            "no_probe": True,
            "stop_first_ambiguity": True,
            "gross_before_costs": True,
            "primary_reference_exact": True,
            "exposed_historical_regression": True,
        },
        "source_hashes": {
            "result": sha256_file(result_path),
            "chart_data": sha256_file(chart_data_path),
            "source_template": sha256_file(SOURCE_TEMPLATE),
            "renderer": sha256_file(Path(__file__).resolve()),
        },
    }
    dataset["dataSha256"] = canonical_hash(dataset)
    template = month_template(SOURCE_TEMPLATE.read_text(encoding="utf-8"), key, label, month_name)
    marker = "__FEBRUARY_CONFIRMATION_ONLY_DATA__"
    require(template.count(marker) == 1, f"{label} chart marker differs")
    template_path.write_text(template, encoding="utf-8", newline="\n")
    encoded = json.dumps(dataset, separators=(",", ":"), allow_nan=False).replace("</", "<\\/")
    rendered = template.replace(marker, encoded)
    require(len(rendered.encode("utf-8")) < 1_000_000, f"{label} chart exceeds 1 MB")
    html_path.write_text(rendered, encoding="utf-8", newline="\n")
    manifest = {
        "version": f"GOLD_{key.upper()}_H1_CONFIRMATION_ONLY_CONTINUOUS_CHART_V1_MANIFEST",
        "verdict": "PASS_DETERMINISTIC_CHART_RENDER",
        "month": label,
        "data_sha256": dataset["dataSha256"],
        "executed_trades": len(plans),
        "files": [
            {
                "path": path.relative_to(ROOT).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": sha256_file(path),
            }
            for path in (result_path, chart_data_path, report_path, SOURCE_TEMPLATE, Path(__file__).resolve(), template_path, html_path)
        ],
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    return {"month": label, "verdict": manifest["verdict"], "trades": len(plans), "html": str(html_path)}


def main() -> None:
    require(SOURCE_TEMPLATE.is_file(), f"Sealed source template absent: {SOURCE_TEMPLATE}")
    for month in MONTHS:
        print(json.dumps(render_one(*month), indent=2))


if __name__ == "__main__":
    main()
