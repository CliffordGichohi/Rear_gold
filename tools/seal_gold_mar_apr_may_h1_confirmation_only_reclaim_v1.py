#!/usr/bin/env python3
"""Verify and seal the separate March-May result and chart deliveries."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / "backend" / "src"), str(ROOT / "tools")]

from gold_coherent_auction_end_to_end_v1_common import require, sha256_file  # noqa: E402
from gold_intel.analytics.coherent_auction_correction_v1 import canonical_hash  # noqa: E402

BASE = ROOT / "research_artifacts/gold_mar_apr_may_h1_confirmation_only_reclaim_v1"
ROOT_MANIFEST = BASE / "manifest.json"
DELIVERY = BASE / "delivery_manifest.json"
SPEC = ROOT / "GOLD_MARCH_APRIL_MAY_2022_H1_CONFIRMATION_ONLY_RECLAIM_APPLICATION_V1.md"
RUNNER = ROOT / "tools/run_gold_mar_apr_may_h1_confirmation_only_reclaim_v1.py"
RENDERER = ROOT / "tools/render_gold_mar_apr_may_h1_confirmation_only_reclaim_v1.py"
BROWSER_TEST = ROOT / "frontend/tools/certify-gold-mar-apr-may-h1-confirmation-only-v1.mjs"
MONTHS = (
    ("march_2022", "March 2022", "march-2022"),
    ("april_2022", "April 2022", "april-2022"),
    ("may_2022", "May 2022", "may-2022"),
)


def verify_file_entries(manifest: Mapping[str, Any]) -> None:
    for entry in manifest["files"]:
        path = ROOT / str(entry["path"])
        require(path.is_file(), f"Sealed file absent: {path}")
        require(path.stat().st_size == int(entry["bytes"]), f"Sealed byte count differs: {path}")
        require(sha256_file(path) == str(entry["sha256"]), f"Sealed hash differs: {path}")


def main() -> None:
    for path in (ROOT_MANIFEST, SPEC, RUNNER, RENDERER, BROWSER_TEST):
        require(path.is_file(), f"Required delivery input absent: {path}")
    root_manifest = json.loads(ROOT_MANIFEST.read_text(encoding="utf-8"))
    require(root_manifest["verdict"] == "PASS_THREE_SEPARATE_UNCHANGED_MONTHLY_APPLICATIONS", "Root application did not pass")
    verify_file_entries(root_manifest)
    monthly = []
    for key, label, slug in MONTHS:
        out = BASE / key
        app_manifest_path = out / "manifest.json"
        chart_manifest_path = out / "chart_manifest.json"
        cert_path = out / "browser_certification.json"
        result_path = out / "result.json"
        report_path = out / "report.md"
        html_path = out / f"gold-{slug}-h1-confirmation-only-continuous-chart.html"
        for path in (app_manifest_path, chart_manifest_path, cert_path, result_path, report_path, html_path):
            require(path.is_file(), f"{label} delivery file absent: {path}")
        app_manifest = json.loads(app_manifest_path.read_text(encoding="utf-8"))
        chart_manifest = json.loads(chart_manifest_path.read_text(encoding="utf-8"))
        cert = json.loads(cert_path.read_text(encoding="utf-8"))
        result = json.loads(result_path.read_text(encoding="utf-8"))
        verify_file_entries(app_manifest)
        verify_file_entries(chart_manifest)
        require(cert["verdict"] == "PASS_WHITE_CONTINUOUS_MONTH_BROWSER_REGRESSION", f"{label} browser regression did not pass")
        require(sha256_file(html_path) == str(cert["html_sha256"]), f"{label} browser HTML hash differs")
        for screenshot in cert["responsive"]:
            screenshot_path = ROOT / str(screenshot["screenshot"])
            require(screenshot_path.is_file(), f"{label} screenshot absent: {screenshot_path}")
            require(sha256_file(screenshot_path) == str(screenshot["screenshot_sha256"]), f"{label} screenshot hash differs")
        require(int(cert["executed_trades"]) == int(result["v2_metrics"]["executed_trades"]), f"{label} trade count differs")
        require(float(cert["net_r"]) == float(result["v2_metrics"]["net_r"]), f"{label} browser/result R differs")
        monthly.append({
            "month": label,
            "application_manifest": app_manifest_path.relative_to(ROOT).as_posix(),
            "application_manifest_sha256": sha256_file(app_manifest_path),
            "chart_manifest": chart_manifest_path.relative_to(ROOT).as_posix(),
            "chart_manifest_sha256": sha256_file(chart_manifest_path),
            "browser_certification": cert_path.relative_to(ROOT).as_posix(),
            "browser_certification_sha256": sha256_file(cert_path),
            "report": report_path.relative_to(ROOT).as_posix(),
            "report_sha256": sha256_file(report_path),
            "html": html_path.relative_to(ROOT).as_posix(),
            "html_sha256": sha256_file(html_path),
            "setups": int(result["v2_metrics"]["setups"]),
            "executed_trades": int(result["v2_metrics"]["executed_trades"]),
            "net_r": float(result["v2_metrics"]["net_r"]),
            "profit_factor": float(result["v2_metrics"]["profit_factor"]),
            "win_rate": float(result["v2_metrics"]["trade_win_rate"]),
        })
    delivery = {
        "version": "GOLD_MARCH_APRIL_MAY_H1_CONFIRMATION_ONLY_RECLAIM_V1_DELIVERY_MANIFEST",
        "verdict": "PASS_SEPARATE_RESULT_AND_VISUAL_DELIVERY_CERTIFICATION",
        "policy_retuned": False,
        "pooled_performance_reported": False,
        "root_application_manifest_sha256": sha256_file(ROOT_MANIFEST),
        "code": {
            "spec_sha256": sha256_file(SPEC),
            "runner_sha256": sha256_file(RUNNER),
            "renderer_sha256": sha256_file(RENDERER),
            "browser_test_sha256": sha256_file(BROWSER_TEST),
            "sealer_sha256": sha256_file(Path(__file__).resolve()),
        },
        "months": monthly,
    }
    delivery["delivery_sha256"] = canonical_hash(delivery)
    DELIVERY.write_text(json.dumps(delivery, indent=2, sort_keys=True) + "\n", encoding="utf-8", newline="\n")
    print(json.dumps({"verdict": delivery["verdict"], "months": monthly}, indent=2))


if __name__ == "__main__":
    main()
