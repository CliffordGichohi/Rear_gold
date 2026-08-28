#!/usr/bin/env python3
"""Freeze, run, reproduce, and seal the ten-case exposed diagnostic."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
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

import reveal_gold_auction_trade_placement_outcomes_v1 as upstream  # noqa: E402
from gold_intel.analytics.auction_ten_case_diagnostic_v1 import (  # noqa: E402
    CATEGORICAL_FIELDS,
    NUMERIC_FIELDS,
    RULESET,
    contrast_summary,
    economic_summary,
    management_overlay,
    outcome_attribution,
    preentry_features,
)
from gold_intel.analytics.coherent_auction_correction_v1 import (  # noqa: E402
    canonical_hash,
)


PROTOCOL = ROOT / "GOLD_AUCTION_TEN_CASE_FAILURE_AND_PROFIT_RETENTION_DIAGNOSTIC_V1.md"
IMPLEMENTATION = ROOT / "backend" / "src" / "gold_intel" / "analytics" / "auction_ten_case_diagnostic_v1.py"
TESTS = ROOT / "backend" / "tests" / "unit" / "test_auction_ten_case_diagnostic_v1.py"
RUNNER = Path(__file__).resolve()

UPSTREAM_ROOT = ROOT / "research_artifacts" / "gold_auction_trade_placement_examples_v1"
PLANS_PRIMARY = UPSTREAM_ROOT / "plans.primary.json"
PLANS_REFERENCE = UPSTREAM_ROOT / "plans.reference.json"
PLACEMENT_SEAL = UPSTREAM_ROOT / "seal.json"
OUTCOME_ROOT = UPSTREAM_ROOT / "outcome_reveal_v1"
OUTCOME_FREEZE = OUTCOME_ROOT / "preoutcome_freeze.json"
OUTCOMES_PRIMARY = OUTCOME_ROOT / "outcomes.primary.json"
OUTCOMES_REFERENCE = OUTCOME_ROOT / "outcomes.reference.json"
OUTCOME_FINAL = OUTCOME_ROOT / "final_results.json"
OUTCOME_SEAL = OUTCOME_ROOT / "seal.json"

OUT = ROOT / "research_artifacts" / "gold_auction_ten_case_failure_profit_retention_diagnostic_v1"
FREEZE = OUT / "prediagnostic_freeze.json"
PRIMARY = OUT / "diagnostic.primary.json"
REFERENCE = OUT / "diagnostic.reference.json"
FINAL = OUT / "final_diagnostic.json"
CERTIFICATION = OUT / "certification.json"
SEAL = OUT / "seal.json"
REPORT = ROOT / "GOLD_AUCTION_TEN_CASE_FAILURE_AND_PROFIT_RETENTION_DIAGNOSTIC_V1_REPORT.md"


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


def verify_file_record(record: dict[str, Any]) -> None:
    path = ROOT / record["path"]
    require(path.exists(), f"Frozen input missing: {path}")
    require(path.stat().st_size == int(record["bytes"]), f"Frozen size differs: {path}")
    require(sha256_file(path) == record["sha256"], f"Frozen hash differs: {path}")


def verify_seal(path: Path) -> dict[str, Any]:
    seal = load_json(path)
    submitted = str(seal["seal_sha256"])
    require(
        canonical_hash({key: value for key, value in seal.items() if key != "seal_sha256"}) == submitted,
        f"Seal payload differs: {path}",
    )
    for record in seal["files"]:
        verify_file_record(record)
    return seal


def synthetic_proof() -> dict[str, Any]:
    namespace = runpy.run_path(str(TESTS))
    names = sorted(name for name, value in namespace.items() if name.startswith("test_") and callable(value))
    require(len(names) == 5, f"Unexpected synthetic-test count: {names}")
    for name in names:
        namespace[name]()
    payload = {"tests": names, "passed": len(names)}
    payload["proof_sha256"] = canonical_hash(payload)
    return payload


def freeze() -> None:
    require(not OUT.exists(), f"Output directory already exists: {OUT}")
    placement_seal = verify_seal(PLACEMENT_SEAL)
    outcome_seal = verify_seal(OUTCOME_SEAL)
    require(outcome_seal["verdict"] == "REVEALED_TEN_DESCRIPTIVE_OUTCOMES_NOT_EDGE_VALIDATION", "Unexpected upstream outcome verdict")
    plans_primary = load_json(PLANS_PRIMARY)
    plans_reference = load_json(PLANS_REFERENCE)
    require(plans_primary["plans"] == plans_reference["plans"], "Plan sources differ")
    plans = plans_primary["plans"]
    require(len(plans) == 10, "Expected ten frozen plans")
    identities = [row["event_identity"] for row in plans]
    aliases = {str(row["case_alias"]) for row in plans}
    source_records = load_json(OUTCOME_FREEZE)["source_records"]
    for record in source_records:
        verify_file_record(record)
    proof = synthetic_proof()
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_FAILURE_PROFIT_RETENTION_DIAGNOSTIC_V1_FREEZE_1_0",
        "frozen_at": now(),
        "ruleset": RULESET,
        "research_credit": "ZERO_EXPOSED_POST_RESULT_DIAGNOSTIC",
        "population": {
            "count": 10,
            "event_identities": identities,
            "event_identities_sha256": canonical_hash(identities),
            "case_aliases": sorted(aliases),
        },
        "attribution": {
            "monetized_success": "NET_R50_GT_0",
            "directionally_useful_unmonetized": "NET_R50_LTE_0_AND_MFE_R_GTE_1P0",
            "no_meaningful_favourable_auction": "NET_R50_LTE_0_AND_MFE_R_LT_1P0",
        },
        "preentry_numeric_fields": list(NUMERIC_FIELDS),
        "preentry_categorical_fields": list(CATEGORICAL_FIELDS),
        "management_overlay": {
            "identity": "M5_CLOSE_PLUS_1R_NET_BREAK_EVEN",
            "activation": "FIRST_COMPLETED_M5_CLOSE_AT_OR_BEYOND_PLUS_1_EFFECTIVE_STRUCTURAL_R",
            "cost_allowance": "FILL_SPREAD_PLUS_TWO_TIMES_0P05_SLIPPAGE_PER_OUNCE",
            "same_bar": "PROTECTION_FIRST",
            "target": "UNCHANGED_ABSOLUTE_TARGET",
            "stop": "UNCHANGED_BEFORE_ACTIVATION",
            "changed_result": "ZERO_NET_R50",
        },
        "synthetic_proof": proof,
        "governing_files": [file_record(path) for path in (PROTOCOL, IMPLEMENTATION, TESTS, RUNNER)],
        "upstream_files": [file_record(path) for path in (PLANS_PRIMARY, PLANS_REFERENCE, PLACEMENT_SEAL, OUTCOME_FREEZE, OUTCOMES_PRIMARY, OUTCOMES_REFERENCE, OUTCOME_FINAL, OUTCOME_SEAL)],
        "source_records": source_records,
        "placement_seal_sha256": placement_seal["seal_sha256"],
        "outcome_seal_sha256": outcome_seal["seal_sha256"],
        "additional_outcomes_opened": 0,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    payload["freeze_sha256"] = canonical_hash(payload)
    write_json(FREEZE, payload)
    print(json.dumps({"status": "FROZEN", "freeze_sha256": payload["freeze_sha256"], "synthetic_tests": proof["passed"]}, indent=2))


def verify_freeze() -> dict[str, Any]:
    frozen = load_json(FREEZE)
    submitted = str(frozen["freeze_sha256"])
    require(
        canonical_hash({key: value for key, value in frozen.items() if key != "freeze_sha256"}) == submitted,
        "Diagnostic freeze payload differs",
    )
    for record in frozen["governing_files"] + frozen["upstream_files"] + frozen["source_records"]:
        verify_file_record(record)
    placement = verify_seal(PLACEMENT_SEAL)
    outcome = verify_seal(OUTCOME_SEAL)
    require(placement["seal_sha256"] == frozen["placement_seal_sha256"], "Placement predecessor seal differs")
    require(outcome["seal_sha256"] == frozen["outcome_seal_sha256"], "Outcome predecessor seal differs")
    return frozen


def side_payload(
    *,
    side: str,
    plans: list[dict[str, Any]],
    outcomes: list[dict[str, Any]],
) -> dict[str, Any]:
    aliases = {str(plan["case_alias"]) for plan in plans}
    streams = upstream._load_targeted_streams(side, aliases)
    outcome_by_identity = {str(row["event_identity"]): row for row in outcomes}
    require(set(outcome_by_identity) == {str(plan["event_identity"]) for plan in plans}, f"{side} outcome population differs")
    rows: list[dict[str, Any]] = []
    for index, plan in enumerate(plans, start=1):
        result = outcome_by_identity[str(plan["event_identity"])]
        require(str(result["plan_sha256"]) == str(plan["plan_sha256"]), f"{side} plan-result hash differs")
        features = preentry_features(plan)
        attribution = outcome_attribution(result)
        stream = streams[str(plan["case_alias"])]
        overlay = management_overlay(
            plan=plan,
            result=result,
            m1_rows=stream["timeframes"]["1m"],
            m5_rows=stream["timeframes"]["5m"],
            implementation="primary" if side == "primary" else "reference",
        )
        row: dict[str, Any] = {
            **{key: value for key, value in features.items() if key != "preentry_sha256"},
            "preentry_sha256": features["preentry_sha256"],
            "outcome_category": attribution["category"],
            "directionally_useful": attribution["directionally_useful"],
            "baseline_resolution": result["execution"]["resolution"],
            "baseline_net_r50": attribution["net_r50"],
            "mfe_r": attribution["mfe_r"],
            "mae_r": attribution["mae_r"],
            "attribution_sha256": attribution["attribution_sha256"],
            "overlay": overlay,
        }
        row["row_sha256"] = canonical_hash(row)
        rows.append(row)
        print(f"{side} diagnostic {index:02d}/10", flush=True)
    summary = {
        "outcome_categories": dict(sorted(Counter(row["outcome_category"] for row in rows).items())),
        "directionally_useful": sum(bool(row["directionally_useful"]) for row in rows),
        "contrasts": contrast_summary(rows),
        "baseline": economic_summary(rows, lambda row: float(row["baseline_net_r50"])),
        "overlay": economic_summary(rows, lambda row: float(row["overlay"]["effective_r50"])),
        "overlay_diagnostics": {
            "activated": sum(bool(row["overlay"]["activated"]) for row in rows),
            "changed": sum(bool(row["overlay"]["changed"]) for row in rows),
            "saved_losses": sum(bool(row["overlay"]["saved_loss"]) for row in rows),
            "clipped_winners": sum(bool(row["overlay"]["clipped_winner"]) for row in rows),
            "unchanged": sum(not bool(row["overlay"]["changed"]) for row in rows),
            "incremental_r50": sum(float(row["overlay"]["incremental_r50"]) for row in rows),
        },
    }
    payload: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_DIAGNOSTIC_SIDE_1_0",
        "side": side,
        "rows": rows,
        "summary": summary,
        "rows_sha256": canonical_hash(rows),
        "summary_sha256": canonical_hash(summary),
    }
    payload["payload_sha256"] = canonical_hash(payload)
    return payload


def _fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "UNKNOWN"
    if isinstance(value, float) and math.isinf(value):
        return "inf"
    return f"{float(value):.{digits}f}"


def markdown(rows: list[dict[str, Any]], summary: dict[str, Any]) -> str:
    baseline = summary["baseline"]
    overlay = summary["overlay"]
    diagnostics = summary["overlay_diagnostics"]
    lines = [
        "# Gold Auction Ten-Case Failure and Profit-Retention Diagnostic V1 Report",
        "",
        "Status: `PASS_EXPOSED_DIAGNOSTIC_REPRODUCTION_ZERO_VALIDATION_CREDIT`",
        "",
        "This is a ten-case exposed descriptive diagnostic, not edge validation.",
        "",
        "## Case-level attribution",
        "",
        "| Date | Side | Family | Category | Baseline R | MFE R | MAE R | Overlay | Effective R |",
        "|---|---|---|---|---:|---:|---:|---|---:|",
    ]
    for row in rows:
        lines.append(
            f"| {row['decision_at'][:10]} | {row['direction']} | {row['context_family']} | {row['outcome_category']} | "
            f"{float(row['baseline_net_r50']):+.2f} | {float(row['mfe_r']):.2f} | {float(row['mae_r']):.2f} | "
            f"{row['overlay']['disposition']} | {float(row['overlay']['effective_r50']):+.2f} |"
        )
    lines.extend(
        [
            "",
            "## Aggregate execution",
            "",
            f"- Baseline: **{baseline['net_r50']:+.4f}R50**, PF {_fmt(baseline['profit_factor'])}, maximum drawdown {_fmt(baseline['maximum_drawdown_r50'])}R50.",
            f"- Universal M5 +1R break-even overlay: **{overlay['net_r50']:+.4f}R50**, PF {_fmt(overlay['profit_factor'])}, maximum drawdown {_fmt(overlay['maximum_drawdown_r50'])}R50.",
            f"- Increment: **{diagnostics['incremental_r50']:+.4f}R50**; activated {diagnostics['activated']}, changed {diagnostics['changed']}, saved losses {diagnostics['saved_losses']}, clipped winners {diagnostics['clipped_winners']}.",
            "",
            "## Pre-entry descriptive contrasts",
            "",
            "No contrast below is a filter or candidate rule.",
            "",
            "| Field | Useful N | Useful mean | Useful median | Failed N | Failed mean | Failed median |",
            "|---|---:|---:|---:|---:|---:|---:|",
        ]
    )
    useful = summary["contrasts"]["DIRECTIONALLY_USEFUL"]["numeric"]
    failed = summary["contrasts"]["NO_MEANINGFUL_FAVOURABLE_AUCTION"]["numeric"]
    for field in NUMERIC_FIELDS:
        lines.append(
            f"| {field} | {useful[field]['n']} | {_fmt(useful[field]['mean'])} | {_fmt(useful[field]['median'])} | "
            f"{failed[field]['n']} | {_fmt(failed[field]['mean'])} | {_fmt(failed[field]['median'])} |"
        )
    lines.extend(
        [
            "",
            "Categorical distributions are preserved in the sealed JSON result. With n=10, no statistical inference, classifier, veto, or edge claim is permitted.",
            "",
        ]
    )
    return "\n".join(lines)


def run() -> None:
    frozen = verify_freeze()
    plans_primary = load_json(PLANS_PRIMARY)
    plans_reference = load_json(PLANS_REFERENCE)
    require(plans_primary["plans"] == plans_reference["plans"], "Plan sources differ at run")
    plans = plans_primary["plans"]
    require([row["event_identity"] for row in plans] == frozen["population"]["event_identities"], "Frozen population differs")
    outcomes_primary = load_json(OUTCOMES_PRIMARY)["results"]
    outcomes_reference = load_json(OUTCOMES_REFERENCE)["results"]
    primary = side_payload(side="primary", plans=plans, outcomes=outcomes_primary)
    reference = side_payload(side="reference", plans=plans, outcomes=outcomes_reference)
    require(primary["rows"] == reference["rows"], "Primary/reference diagnostic rows differ")
    require(primary["summary"] == reference["summary"], "Primary/reference summaries differ")
    write_json(PRIMARY, primary)
    write_json(REFERENCE, reference)
    final: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_FAILURE_PROFIT_RETENTION_DIAGNOSTIC_V1_FINAL_1_0",
        "verdict": "PASS_EXPOSED_DIAGNOSTIC_REPRODUCTION_ZERO_VALIDATION_CREDIT",
        "freeze_sha256": frozen["freeze_sha256"],
        "primary_reference_exact": True,
        "rows": primary["rows"],
        "summary": primary["summary"],
        "rows_sha256": primary["rows_sha256"],
        "summary_sha256": primary["summary_sha256"],
        "additional_outcomes_opened": 0,
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    final["final_sha256"] = canonical_hash(final)
    write_json(FINAL, final)
    write_text(REPORT, markdown(primary["rows"], primary["summary"]))
    certification: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_DIAGNOSTIC_V1_CERTIFICATION_1_0",
        "completed_at": now(),
        "verdict": final["verdict"],
        "freeze_sha256": frozen["freeze_sha256"],
        "final_sha256": final["final_sha256"],
        "primary_reference_exact": True,
        "opened_cases": 10,
        "additional_outcomes_opened": 0,
        "summary": primary["summary"],
        "report": file_record(REPORT),
        "calendar_2025_opened": False,
        "calendar_2026_opened": False,
        "paid_acquisition": False,
    }
    certification["certification_sha256"] = canonical_hash(certification)
    write_json(CERTIFICATION, certification)
    seal: dict[str, Any] = {
        "version": "GOLD_AUCTION_TEN_CASE_DIAGNOSTIC_V1_SEAL_1_0",
        "sealed_at": now(),
        "verdict": final["verdict"],
        "certification_sha256": certification["certification_sha256"],
        "files": [file_record(path) for path in (FREEZE, PRIMARY, REFERENCE, FINAL, CERTIFICATION, REPORT)],
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
                "summary": primary["summary"],
                "certification_sha256": certification["certification_sha256"],
                "seal_sha256": seal["seal_sha256"],
            },
            indent=2,
        )
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
